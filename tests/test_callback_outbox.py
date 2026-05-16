from __future__ import annotations

import json
from pathlib import Path
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
        "process_tracking": {"root_pid": None, "process_group_id": None, "processes": [], "live_process_count": 0},
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


def test_failed_delivery_keeps_pending_record(monkeypatch, tmp_path: Path) -> None:
    state = tmp_path / "state"
    callback_outbox.write_pending(state, _payload())

    def fail(*args, **kwargs):
        raise TimeoutError("timed out")

    monkeypatch.setattr(callback_outbox.request, "urlopen", fail)
    result = callback_outbox.deliver_pending_file(
        callback_outbox.pending_path(state, "run-1"),
        state_dir=state,
        url="http://127.0.0.1/callback",
        token="token",
        timeout=0.01,
    )

    assert not result.ok
    assert callback_outbox.pending_path(state, "run-1").exists()
    data = json.loads(callback_outbox.pending_path(state, "run-1").read_text(encoding="utf-8"))
    assert data["attempt_count"] == 1
    assert "TimeoutError" in data["last_error"]


def test_successful_delivery_moves_to_delivered_and_marks_worker_state(monkeypatch, tmp_path: Path) -> None:
    state = tmp_path / "state"
    run_dir = state / "runs"
    run_dir.mkdir(parents=True)
    (run_dir / "run-1.json").write_text(json.dumps({"run_id": "run-1", "gate_state": "running"}), encoding="utf-8")
    callback_outbox.write_pending(state, _payload())

    class FakeResponse:
        status = 200
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def read(self, *_args):
            return b'{"ok": true}'

    monkeypatch.setattr(callback_outbox.request, "urlopen", lambda *args, **kwargs: FakeResponse())
    result = callback_outbox.deliver_pending_file(
        callback_outbox.pending_path(state, "run-1"),
        state_dir=state,
        url="http://127.0.0.1/callback",
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
