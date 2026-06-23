from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, cast

from enoch_control_plane.gate import _is_duplicate_gate_callback
from enoch_control_plane.models import RunRecord


def test_duplicate_gate_callback_matches_iso_timestamp_suffix_with_colons() -> None:
    seen_at = "2026-06-22T01:02:03+00:00"
    record = RunRecord(
        run_id="run-1",
        session_id="session-1",
        project_id="project-1",
        idle_seen_at=seen_at,
        last_event_at="2026-06-22T01:02:02+00:00",
        last_idempotency_key=f"run-1:wake_ready:{seen_at}",
    )

    assert _is_duplicate_gate_callback(record)


def test_duplicate_gate_callback_normalizes_datetime_and_iso_string() -> None:
    seen_at = datetime(2026, 6, 22, 1, 2, 3, tzinfo=timezone.utc)
    record = RunRecord(
        run_id="run-1",
        session_id="session-1",
        project_id="project-1",
        idle_seen_at="2026-06-22T01:02:03+00:00",
        last_event_at="2026-06-22T01:02:02+00:00",
        last_idempotency_key=f"run-1:wake_ready:{seen_at.isoformat()}",
    )
    # Simulate callers that still hold a parsed timestamp despite the persisted
    # model field normally being a string.
    cast(Any, record).idle_seen_at = seen_at

    assert _is_duplicate_gate_callback(record)


def test_duplicate_gate_callback_rejects_different_seen_timestamp() -> None:
    record = RunRecord(
        run_id="run-1",
        session_id="session-1",
        project_id="project-1",
        idle_seen_at="2026-06-22T01:02:04+00:00",
        last_event_at="2026-06-22T01:02:04+00:00",
        last_idempotency_key="run-1:wake_ready:2026-06-22T01:02:03+00:00",
    )

    assert not _is_duplicate_gate_callback(record)
