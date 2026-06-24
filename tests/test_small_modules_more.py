from __future__ import annotations

import fcntl
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from enoch_control_plane import callbacks as callbacks_mod
from enoch_control_plane.callbacks import CallbackSender
from enoch_control_plane.config import GateConfig
from enoch_control_plane.models import GateCallback, ProcessSnapshot, RunRecord
from enoch_control_plane.state_store import StateStore
from enoch_control_plane.research_quality import dspy_programs
from scripts import backfill_promising_signals
from scripts import research_provider_budget


def test_state_store_roundtrip_and_skips_invalid_json(tmp_path: Path) -> None:
    store = StateStore(tmp_path)
    record = RunRecord(run_id="run", session_id="session", project_id="project")
    assert store.load_run("missing") is None
    store.save_run(record)
    assert store.load_run("run").project_id == "project"
    (store.runs_dir / "bad.json").write_text("not-json")
    assert [item.run_id for item in store.list_runs()] == ["run"]
    store.append_event({"b": 2, "a": 1})
    assert store.events_log.read_text().strip() == '{"a": 1, "b": 2}'


def test_state_store_append_event_serializes_file_append_with_flock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = StateStore(tmp_path)
    lock_calls: list[int] = []

    def record_flock(_fd: int, operation: int) -> None:
        lock_calls.append(operation)

    monkeypatch.setattr("enoch_control_plane.state_store.fcntl.flock", record_flock)

    store.append_event({"event": "one"})
    store.append_event({"event": "two"})

    assert lock_calls == [
        fcntl.LOCK_EX,
        fcntl.LOCK_UN,
        fcntl.LOCK_EX,
        fcntl.LOCK_UN,
    ]
    assert [json.loads(line) for line in store.events_log.read_text().splitlines()] == [
        {"event": "one"},
        {"event": "two"},
    ]


def test_state_store_load_run_treats_corrupt_file_as_missing(tmp_path: Path) -> None:
    store = StateStore(tmp_path)
    store.run_path("corrupt-run").write_text("not-json", encoding="utf-8")

    assert store.load_run("corrupt-run") is None


def test_state_store_save_run_recreates_missing_runs_dir(tmp_path: Path) -> None:
    store = StateStore(tmp_path)
    for child in store.runs_dir.iterdir():
        child.unlink()
    store.runs_dir.rmdir()

    store.save_run(RunRecord(run_id="run", session_id="session", project_id="project"))

    assert store.load_run("run").project_id == "project"


def test_state_store_run_path_rejects_escape_and_caps_long_ids(tmp_path: Path) -> None:
    store = StateStore(tmp_path)
    escaped = RunRecord(run_id="../escape", session_id="session", project_id="project")
    long_id = "r" * 400
    long_record = RunRecord(run_id=long_id, session_id="session", project_id="project")

    store.save_run(escaped)
    store.save_run(long_record)

    assert not (tmp_path / "escape.json").exists()
    assert store.load_run("../escape").project_id == "project"
    long_path = store.run_path(long_id)
    assert long_path.exists()
    assert len(long_path.name) <= 120
    assert store.load_run(long_id).run_id == long_id


def test_callback_sender_posts_expected_headers(monkeypatch) -> None:
    config = GateConfig(
        state_dir="/tmp/state",
        project_root="/tmp/projects",
        dispatch_script_path="/tmp/dispatch.sh",
        control_api_bearer_token="control",
        completion_callback_url="http://93.184.216.34/callback",
        completion_callback_token="secret",
        completion_callback_hmac_secret="signing-secret",
    )
    callback = GateCallback(
        event_type="wake_ready",
        run_id="run",
        session_id="session",
        project_id="project",
        source_event="session-idle",
        gate_state="wake_ready",
        process_tracking=ProcessSnapshot(),
        telemetry={},
        reason="quiet",
        idempotency_key="idem",
    )
    captured = {}

    class Resp:
        status = 202

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return b"accepted"

    def fake_urlopen(req, timeout, **_kwargs):
        captured["url"] = req.full_url
        captured["headers"] = dict(req.header_items())
        captured["timeout"] = timeout
        return Resp()

    monkeypatch.setattr("enoch_control_plane.callbacks.urlopen_validated", fake_urlopen)
    status, text = CallbackSender(config).send(callback)
    assert status == 202
    assert text == "accepted"
    assert captured["url"] == "http://93.184.216.34/callback"
    assert captured["headers"]["Authorization"] == "Bearer secret"
    assert captured["headers"]["X-idempotency-key"] == "idem"
    assert captured["headers"]["X-enoch-timestamp"].isdigit()
    assert captured["headers"]["X-enoch-signature"].startswith("sha256=")


def test_callback_retry_wait_uses_jitter() -> None:
    wait_strategy = callbacks_mod._CALLBACK_RETRY_WAIT

    assert type(wait_strategy).__name__ == "wait_random_exponential"
    assert wait_strategy.min == 0.5
    assert wait_strategy.max == 8.0


def test_research_provider_budget_missing_payload_raises_runtime_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing_payload(_args: object) -> tuple[None, None]:
        return None, None

    monkeypatch.setattr(
        research_provider_budget,
        "_resolve_quota_payload",
        missing_payload,
    )

    with pytest.raises(RuntimeError, match="quota payload unavailable"):
        research_provider_budget.main(["--no-auth"])


def test_backfill_promising_signals_missing_exporter_raises_import_error(
    tmp_path: Path,
) -> None:
    missing_exporter = tmp_path / "missing_export_promising_signals.py"

    with pytest.raises(ImportError, match="could not load promising-signals exporter"):
        backfill_promising_signals._load_exporter(missing_exporter)


def test_callback_sender_rejects_file_scheme_before_urlopen(monkeypatch) -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError) as raised:
        GateConfig(
            state_dir="/tmp/state",
            project_root="/tmp/projects",
            dispatch_script_path="/tmp/dispatch.sh",
            control_api_bearer_token="control",
            completion_callback_url="file:///etc/passwd",
            completion_callback_token="secret",
        )
    assert "completion_callback_url must use http or https" in str(raised.value)


def test_dspy_program_signatures_with_fake_module(monkeypatch) -> None:
    class Signature:
        pass

    class Field:
        def __init__(self, *args, **kwargs):
            pass

    fake = SimpleNamespace(Signature=Signature, InputField=Field, OutputField=Field)
    monkeypatch.setitem(sys.modules, "dspy", fake)
    assert dspy_programs.dspy_available() is True
    candidate = dspy_programs.candidate_quality_signature()
    decision = dspy_programs.decision_quality_signature()
    assert issubclass(candidate, Signature)
    assert issubclass(decision, Signature)
    monkeypatch.delitem(sys.modules, "dspy", raising=False)
