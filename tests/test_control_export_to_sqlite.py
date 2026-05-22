from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from scripts.control_export_to_sqlite import convert


def test_control_export_to_sqlite_preserves_paper_review_and_run_rows(
    tmp_path: Path,
) -> None:
    snapshot = {
        "flags": {
            "queue_paused": True,
            "maintenance_mode": True,
            "pause_reason": "migration",
            "paused_by": "test",
        },
        "queue_rows": [
            {
                "project_id": "p1",
                "project_name": "Project One",
                "project_dir": "p1",
                "status": "completed",
                "current_run_id": "r1",
                "current_session_id": "s1",
                "last_run_state": "wake_ready",
                "machine_target": "worker",
                "model": "gpt-5.5",
                "sandbox": "danger-full-access",
                "updated_at": "2026-05-06T10:00:00Z",
            }
        ],
        "paper_rows": [
            {
                "paper_id": "paper1",
                "project_id": "p1",
                "project_name": "Project One",
                "run_id": "r1",
                "paper_status": "publication_draft",
                "review_status": "finalized",
                "finalization_package_path": "package.json",
                "updated_at": "2026-05-06T10:00:00Z",
            }
        ],
        "events": [
            {
                "idempotency_key": "e1",
                "event_type": "fixture",
                "entity_type": "project",
                "entity_id": "p1",
                "payload": {"ok": True},
            }
        ],
    }
    source = tmp_path / "snapshot.json"
    output = tmp_path / "snapshot.sqlite3"
    source.write_text(json.dumps(snapshot), encoding="utf-8")

    result = convert(source, output)

    assert result["queue_rows"] == 1
    assert result["paper_rows"] == 1
    assert result["run_rows"] == 1
    with sqlite3.connect(output) as conn:
        assert conn.execute("select count(*) from queue_items").fetchone()[0] == 1
        assert conn.execute("select count(*) from papers").fetchone()[0] == 1
        assert (
            conn.execute("select review_status from paper_review_items").fetchone()[0]
            == "finalized"
        )
        assert (
            conn.execute("select state from runs where run_id='r1'").fetchone()[0]
            == "wake_ready"
        )


def test_control_export_to_sqlite_rejects_conflicting_event_replays(
    tmp_path: Path,
) -> None:
    snapshot = {
        "events": [
            {
                "idempotency_key": "event-1",
                "event_type": "queue.alert",
                "entity_type": "queue",
                "entity_id": "active",
                "payload": {"status": "blocked"},
            },
            {
                "idempotency_key": "event-1",
                "event_type": "queue.alert",
                "entity_type": "queue",
                "entity_id": "active",
                "payload": {"status": "ready"},
            },
        ],
    }
    source = tmp_path / "snapshot.json"
    output = tmp_path / "snapshot.sqlite3"
    source.write_text(json.dumps(snapshot), encoding="utf-8")

    with pytest.raises(ValueError, match="conflicting event idempotency key"):
        convert(source, output)


def test_control_export_to_sqlite_rejects_conflicting_paper_replays(
    tmp_path: Path,
) -> None:
    snapshot = {
        "paper_rows": [
            {
                "paper_id": "paper-1",
                "project_id": "project-a",
                "paper_status": "publication_draft",
            },
            {
                "paper_id": "paper-1",
                "project_id": "project-b",
                "paper_status": "publication_draft",
            },
        ],
    }
    source = tmp_path / "snapshot.json"
    output = tmp_path / "snapshot.sqlite3"
    source.write_text(json.dumps(snapshot), encoding="utf-8")

    with pytest.raises(ValueError, match="conflicting paper identity"):
        convert(source, output)
