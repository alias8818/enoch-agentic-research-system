from __future__ import annotations

import io
import json
from datetime import datetime, timedelta, timezone
from email.message import Message
from pathlib import Path
from typing import Any
from urllib import error

from enoch_control_plane import callback_outbox


def _payload(run_id: str = "run-1") -> dict:
    return {
        "event_type": "wake_ready",
        "run_id": run_id,
        "session_id": "session-1",
        "project_id": "project-1",
        "project_name": "project-1",
        "source_event": "codex-runner-exit",
        "gate_state": "wake_ready",
        "process_tracking": {
            "root_pid": None,
            "process_group_id": None,
            "processes": [],
            "live_process_count": 0,
        },
        "telemetry": {"runner": "codex", "exit_code": 0},
        "reason": "codex runner completed",
        "idempotency_key": f"{run_id}:wake_ready:codex-runner:done",
    }


def test_write_pending_preserves_failed_attempt_metadata(tmp_path: Path) -> None:
    state = tmp_path / "state"
    path = callback_outbox.write_pending(state, _payload())
    data = json.loads(path.read_text(encoding="utf-8"))
    data["attempt_count"] = 3
    data["last_error"] = "TimeoutError: timed out"
    path.write_text(json.dumps(data), encoding="utf-8")

    path = callback_outbox.write_pending(state, _payload())
    data = json.loads(path.read_text(encoding="utf-8"))

    assert data["attempt_count"] == 3
    assert data["last_error"] == "TimeoutError: timed out"


def test_write_pending_records_corrupt_existing_metadata(tmp_path: Path) -> None:
    state = tmp_path / "state"
    path = callback_outbox.write_pending(state, _payload())
    path.write_text("{not-json", encoding="utf-8")

    path = callback_outbox.write_pending(state, _payload())
    data = json.loads(path.read_text(encoding="utf-8"))

    assert data["attempt_count"] == 0
    assert "existing pending metadata unreadable" in data["last_error"]


def test_write_pending_updates_local_worker_state_for_terminal_gate_error(
    tmp_path: Path,
) -> None:
    state = tmp_path / "state"
    run_dir = state / "runs"
    run_dir.mkdir(parents=True)
    (run_dir / "run-failed.json").write_text(
        json.dumps({"run_id": "run-failed", "gate_state": "running"}), encoding="utf-8"
    )

    callback_outbox.write_pending(
        state,
        {
            **_payload("run-failed"),
            "event_type": "gate_error",
            "gate_state": "gate_error",
            "reason": "codex runner exited nonzero: 1",
            "idempotency_key": "run-failed:gate_error:codex-runner:done",
        },
    )

    data = json.loads((run_dir / "run-failed.json").read_text(encoding="utf-8"))
    assert data["gate_state"] == "gate_error"
    assert data["last_error"] == "codex runner exited nonzero: 1"


def test_pending_paths_do_not_collide_for_sanitized_run_ids(tmp_path: Path) -> None:
    state = tmp_path / "state"

    unsafe = callback_outbox.write_pending(state, _payload("run/unsafe"))
    safe = callback_outbox.write_pending(state, _payload("run_unsafe"))

    assert unsafe != safe
    assert len(unsafe.stem.rsplit("-", 1)[-1]) == 32
    assert unsafe.exists()
    assert safe.exists()
    assert json.loads(unsafe.read_text(encoding="utf-8"))["run_id"] == "run/unsafe"
    assert json.loads(safe.read_text(encoding="utf-8"))["run_id"] == "run_unsafe"


def test_failed_delivery_keeps_pending_record(monkeypatch, tmp_path: Path) -> None:
    state = tmp_path / "state"
    callback_outbox.write_pending(state, _payload())

    def fail(*args, **kwargs):
        raise TimeoutError("timed out")

    monkeypatch.setattr(callback_outbox, "urlopen_validated", fail)
    result = callback_outbox.deliver_pending_file(
        callback_outbox.pending_path(state, "run-1"),
        state_dir=state,
        url="http://93.184.216.34/callback",
        token="token",
        timeout=0.01,
    )

    assert not result.ok
    assert callback_outbox.pending_path(state, "run-1").exists()
    data = json.loads(
        callback_outbox.pending_path(state, "run-1").read_text(encoding="utf-8")
    )
    assert data["attempt_count"] == 1
    assert "TimeoutError" in data["last_error"]
    assert data["next_attempt_at"]


def test_rate_limited_delivery_records_retry_after_and_replay_skips_until_due(
    monkeypatch: Any, tmp_path: Path
) -> None:
    state = tmp_path / "state"
    callback_outbox.write_pending(state, _payload())

    def rate_limited(*args: object, **kwargs: object) -> None:
        del args, kwargs
        headers = Message()
        headers["Retry-After"] = "60"
        raise error.HTTPError(
            "http://93.184.216.34/callback",
            429,
            "rate limited",
            headers,
            io.BytesIO(b"slow down"),
        )

    monkeypatch.setattr(callback_outbox, "urlopen_validated", rate_limited)
    result = callback_outbox.deliver_pending_file(
        callback_outbox.pending_path(state, "run-1"),
        state_dir=state,
        url="http://93.184.216.34/callback",
        token="token",
        timeout=1,
    )

    assert not result.ok
    assert result.status_code == 429
    assert result.retry_after_seconds == 60.0
    pending = callback_outbox.pending_path(state, "run-1")
    data = json.loads(pending.read_text(encoding="utf-8"))
    next_attempt_at = datetime.fromisoformat(
        data["next_attempt_at"].replace("Z", "+00:00")
    )
    assert next_attempt_at > datetime.now(timezone.utc) + timedelta(seconds=30)

    replayed = callback_outbox.replay_pending(
        state_dir=state,
        url="http://93.184.216.34/callback",
        token="token",
        timeout=1,
    )

    assert len(replayed) == 1
    assert not replayed[0].ok
    assert "retry delayed until" in replayed[0].detail
    assert json.loads(pending.read_text(encoding="utf-8"))["attempt_count"] == 1


def test_successful_delivery_moves_to_delivered_and_marks_worker_state(
    monkeypatch, tmp_path: Path
) -> None:
    state = tmp_path / "state"
    run_dir = state / "runs"
    run_dir.mkdir(parents=True)
    (run_dir / "run-1.json").write_text(
        json.dumps({"run_id": "run-1", "gate_state": "running"}), encoding="utf-8"
    )
    callback_outbox.write_pending(state, _payload())

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, *_args):
            return b'{"ok": true}'

    monkeypatch.setattr(
        callback_outbox, "urlopen_validated", lambda *args, **kwargs: FakeResponse()
    )
    result = callback_outbox.deliver_pending_file(
        callback_outbox.pending_path(state, "run-1"),
        state_dir=state,
        url="http://93.184.216.34/callback",
        token="token",
        timeout=1,
    )

    assert result.ok
    assert not callback_outbox.pending_path(state, "run-1").exists()
    delivered = state / callback_outbox.DELIVERED_DIRNAME / "run-1.json"
    assert delivered.exists()
    worker_state = json.loads((run_dir / "run-1.json").read_text(encoding="utf-8"))
    assert worker_state["gate_state"] == "wake_ready"
    assert worker_state["last_idempotency_key"] == "run-1:wake_ready:codex-runner:done"


def test_deliver_pending_file_rejects_paths_outside_outbox(tmp_path: Path) -> None:
    state = tmp_path / "state"
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps(_payload()), encoding="utf-8")

    result = callback_outbox.deliver_pending_file(
        outside,
        state_dir=state,
        url="http://93.184.216.34/callback",
        token="token",
        timeout=1,
    )

    assert not result.ok
    assert "outside callback outbox" in result.detail
    assert "attempt_count" not in json.loads(outside.read_text(encoding="utf-8"))


def test_deliver_pending_file_rejects_unexpandable_pending_path_without_crashing(
    tmp_path: Path,
) -> None:
    result = callback_outbox.deliver_pending_file(
        "~enoch-user-that-should-not-exist/run.json",
        state_dir=tmp_path / "state",
        url="http://93.184.216.34/callback",
        token="token",
        timeout=1,
    )

    assert not result.ok
    assert "invalid callback outbox path" in result.detail
    assert "RuntimeError" in result.detail


def test_deliver_pending_file_reports_corrupt_pending_json_without_crashing(
    tmp_path: Path,
) -> None:
    state = tmp_path / "state"
    pending = callback_outbox.pending_path(state, "run-corrupt")
    pending.write_text("{not-json", encoding="utf-8")

    result = callback_outbox.deliver_pending_file(
        pending,
        state_dir=state,
        url="http://93.184.216.34/callback",
        token="token",
        timeout=1,
    )

    assert not result.ok
    assert "pending callback payload unreadable" in result.detail
    assert result.path == str(pending)
    assert pending.exists()


def test_atomic_write_json_preserves_existing_file_and_cleans_temp_on_replace_failure(
    monkeypatch, tmp_path: Path
) -> None:
    target = tmp_path / "pending.json"
    target.write_text('{"old": true}\n', encoding="utf-8")
    original_replace = Path.replace

    def flaky_replace(self: Path, target_arg: Path | str):
        if Path(target_arg) == target:
            raise OSError("simulated replace failure")
        return original_replace(self, target_arg)

    monkeypatch.setattr(Path, "replace", flaky_replace)

    try:
        callback_outbox._atomic_write_json(target, {"new": True})
    except OSError:
        pass
    else:  # pragma: no cover - regression guard
        raise AssertionError("expected simulated replace failure")

    assert target.read_text(encoding="utf-8") == '{"old": true}\n'
    assert sorted(path.name for path in tmp_path.iterdir()) == ["pending.json"]


def test_successful_delivery_records_worker_state_update_errors(
    monkeypatch, tmp_path: Path
) -> None:
    state = tmp_path / "state"
    run_dir = state / "runs"
    run_dir.mkdir(parents=True)
    (run_dir / "run-1.json").write_text("{not-json", encoding="utf-8")
    callback_outbox.write_pending(state, _payload())

    monkeypatch.setattr(
        callback_outbox,
        "deliver_payload",
        lambda payload, **kwargs: callback_outbox.DeliveryResult(
            ok=True, status_code=204, detail="ok"
        ),
    )

    result = callback_outbox.deliver_pending_file(
        callback_outbox.pending_path(state, "run-1"),
        state_dir=state,
        url="http://93.184.216.34/callback",
        token="token",
        timeout=1,
    )

    assert result.ok
    assert "local worker state update failed" in result.detail
    delivered = json.loads(
        (state / callback_outbox.DELIVERED_DIRNAME / "run-1.json").read_text(
            encoding="utf-8"
        )
    )
    assert "local_worker_state_error" in delivered
    assert "JSONDecodeError" in delivered["local_worker_state_error"]


def test_deliver_cli_can_read_token_from_stdin(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    captured: dict[str, object] = {}

    def fake_deliver(path, **kwargs):
        captured["path"] = path
        captured.update(kwargs)
        return callback_outbox.DeliveryResult(
            ok=True, status_code=204, detail="ok", path=str(path)
        )

    monkeypatch.setattr(callback_outbox, "deliver_pending_file", fake_deliver)
    monkeypatch.setattr("sys.stdin", io.StringIO("secret-token\n"))

    rc = callback_outbox.main(
        [
            "deliver",
            "--state-dir",
            str(tmp_path),
            "--run-id",
            "run-1",
            "--url",
            "http://93.184.216.34/callback",
            "--token-stdin",
        ]
    )

    assert rc == 0
    assert captured["token"] == "secret-token"
    assert json.loads(capsys.readouterr().out)["ok"] is True


def test_replay_cli_can_read_token_from_stdin(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    captured: dict[str, object] = {}

    def fake_replay(**kwargs):
        captured.update(kwargs)
        return [
            callback_outbox.DeliveryResult(
                ok=True, status_code=204, detail="ok", path="p"
            )
        ]

    monkeypatch.setattr(callback_outbox, "replay_pending", fake_replay)
    monkeypatch.setattr("sys.stdin", io.StringIO("secret-token\n"))

    rc = callback_outbox.main(
        [
            "replay",
            "--state-dir",
            str(tmp_path),
            "--url",
            "http://93.184.216.34/callback",
            "--token-stdin",
        ]
    )

    assert rc == 0
    assert captured["token"] == "secret-token"
    assert json.loads(capsys.readouterr().out)["ok"] is True
