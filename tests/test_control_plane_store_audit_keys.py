from __future__ import annotations

import sqlite3
from pathlib import Path

from pytest import MonkeyPatch

from enoch_control_plane.control_plane.store import ControlPlaneStore


FIXED_NOW = "2026-06-22T00:00:00.000Z"


def _event_keys(db_path: Path, event_type: str) -> list[str]:
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "select idempotency_key from events where event_type = ? order by event_id",
            (event_type,),
        ).fetchall()
    return [str(row[0]) for row in rows]


def test_pause_resume_audit_keys_do_not_collapse_same_timestamp(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.setattr("enoch_control_plane.control_plane.store.utc_now", lambda: FIXED_NOW)
    store = ControlPlaneStore(tmp_path / "control_plane.sqlite3")

    _flags, first_pause_event_id = store.pause(
        reason="operator clicked twice", paused_by="pytest", maintenance_mode=False
    )
    _flags, second_pause_event_id = store.pause(
        reason="operator clicked twice", paused_by="pytest", maintenance_mode=False
    )
    _flags, first_resume_event_id = store.resume(
        resumed_by="pytest", maintenance_mode=False
    )
    _flags, second_resume_event_id = store.resume(
        resumed_by="pytest", maintenance_mode=False
    )

    assert second_pause_event_id != first_pause_event_id
    assert second_resume_event_id != first_resume_event_id
    pause_keys = _event_keys(tmp_path / "control_plane.sqlite3", "control.pause")
    resume_keys = _event_keys(tmp_path / "control_plane.sqlite3", "control.resume")
    assert len(pause_keys) == len(set(pause_keys)) == 2
    assert len(resume_keys) == len(set(resume_keys)) == 2
    assert all(key.startswith(f"pause:{FIXED_NOW}:") for key in pause_keys)
    assert all(key.startswith(f"resume:{FIXED_NOW}:") for key in resume_keys)


def test_queue_item_paused_audit_keys_do_not_collapse_same_timestamp(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.setattr("enoch_control_plane.control_plane.store.utc_now", lambda: FIXED_NOW)
    db_path = tmp_path / "control_plane.sqlite3"
    store = ControlPlaneStore(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            insert into projects(
                project_id, project_name, project_dir, notion_page_url, notion_page_id,
                origin_idea_status, created_at, updated_at
            ) values (?,?,?,?,?,?,?,?)
            """,
            (
                "project-1",
                "Project 1",
                str(tmp_path / "project-1"),
                "",
                "",
                "queued",
                FIXED_NOW,
                FIXED_NOW,
            ),
        )
        conn.execute(
            """
            insert into queue_items(
                project_id, status, selection_rank, dispatch_priority, auto_continue,
                continue_count, max_continues, retry_count, max_retries,
                current_run_id, current_session_id, last_run_state, last_event_type,
                next_action_hint, manual_review_required, blocked_reason, last_error,
                last_result_summary, machine_target, model, sandbox, last_dispatch_at,
                last_callback_at, stale_after, updated_at
            ) values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                "project-1",
                "queued",
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                "",
                "",
                "",
                "",
                "",
                0,
                "",
                "",
                "",
                "gb10",
                "gpt-5.5",
                "danger-full-access",
                None,
                None,
                None,
                FIXED_NOW,
            ),
        )

    assert store.mark_queue_item_paused(project_id="project-1", reason="first") is True
    assert store.mark_queue_item_paused(project_id="project-1", reason="second") is True

    keys = _event_keys(db_path, "queue.item_paused")
    assert len(keys) == len(set(keys)) == 2
    assert all(key.startswith(f"queue-item-paused:project-1:{FIXED_NOW}:") for key in keys)
