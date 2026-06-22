from __future__ import annotations

import json
import fcntl
from pathlib import Path

from pytest import MonkeyPatch

from enoch_control_plane.config import GateConfig
from enoch_control_plane.operational_trace import OperatorTrace, summarize_lane_snapshot


def test_operator_trace_redacts_sensitive_fields_and_bounds_payload(
    tmp_path: Path,
) -> None:
    path = tmp_path / "operator_trace.jsonl"
    trace = OperatorTrace(enabled=True, path=path, max_payload_bytes=1024)

    trace.record(
        "dispatch.live.attempt",
        trace_id="trace-1",
        requested_by="pytest",
        bearer_token="secret-token",
        nested={"Authorization": "Bearer secret-token", "prompt": "x" * 5000},
    )

    text = path.read_text(encoding="utf-8")
    assert "secret-token" not in text
    row = json.loads(text)
    assert row["event"] == "dispatch.live.attempt"
    assert row["bearer_token"] == "[REDACTED]"
    assert len(text.encode("utf-8")) <= 1400


def test_operator_trace_from_config_defaults_to_state_dir(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    config = GateConfig(
        state_dir=str(state_dir),
        project_root=str(tmp_path / "projects"),
        dispatch_script_path=str(tmp_path / "dispatch.sh"),
        control_api_bearer_token="test-token",
        completion_callback_url="http://example.invalid/callback",
        completion_callback_token="callback-token",
        operational_trace_enabled=True,
    )

    trace = OperatorTrace.from_config(config)
    trace.record("research.run_cycle.start", trace_id="trace-2")

    assert (state_dir / "operator_trace.jsonl").is_file()


def test_operator_trace_rotates_bounded_jsonl_file(tmp_path: Path, monkeypatch) -> None:
    from enoch_control_plane import operational_trace

    monkeypatch.setattr(operational_trace, "_MAX_TRACE_FILE_BYTES", 20)
    path = tmp_path / "operator_trace.jsonl"
    path.write_text("old-line-that-is-long-enough\n", encoding="utf-8")
    trace = OperatorTrace(enabled=True, path=path, max_payload_bytes=1024)

    trace.record("research.run_cycle.start", trace_id="trace-rotate")

    assert (
        (tmp_path / "operator_trace.jsonl.1")
        .read_text(encoding="utf-8")
        .startswith("old-line")
    )
    assert "trace-rotate" in path.read_text(encoding="utf-8")


def test_operator_trace_serializes_and_fsyncs_writes(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    from enoch_control_plane import operational_trace

    path = tmp_path / "operator_trace.jsonl"
    fsynced: list[int] = []
    locks: list[int] = []

    def fake_fsync(fd: int) -> None:
        fsynced.append(fd)

    def fake_flock(fd: int, operation: int) -> None:
        locks.append(operation)

    monkeypatch.setattr(operational_trace.os, "fsync", fake_fsync)
    monkeypatch.setattr(
        operational_trace.fcntl,
        "flock",
        fake_flock,
    )

    trace = OperatorTrace(enabled=True, path=path, max_payload_bytes=1024)
    trace.record("research.run_cycle.start", trace_id="trace-fsync")

    assert "trace-fsync" in path.read_text(encoding="utf-8")
    assert (tmp_path / "operator_trace.jsonl.lock").exists()
    assert fcntl.LOCK_EX in locks
    assert fcntl.LOCK_UN in locks
    assert len(fsynced) >= 2


def test_summarize_lane_snapshot_keeps_operator_relevant_fields_only() -> None:
    lanes = [
        {
            "lane_key": "http://worker:8787",
            "machine_target": "cpu-proxmox-1",
            "worker_role": "cpu_worker",
            "status": "idle",
            "active_count": 0,
            "queued_count": 2,
            "dispatch_available": True,
            "next_candidate": {"project_id": "next", "secret": "ignored"},
            "feed_pressure": {
                "next_autopilot_action": "dispatch_queued",
                "queue_deficit": 23,
            },
        }
    ]

    assert summarize_lane_snapshot(lanes) == [
        {
            "lane_key": "http://worker:8787",
            "machine_target": "cpu-proxmox-1",
            "worker_role": "cpu_worker",
            "status": "idle",
            "active_count": 0,
            "queued_count": 2,
            "dispatch_available": True,
            "dispatch_blocker": None,
            "active_project_id": None,
            "active_run_id": None,
            "next_project_id": "next",
            "feed_action": "dispatch_queued",
            "queue_deficit": 23,
        }
    ]
