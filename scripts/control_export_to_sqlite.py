#!/usr/bin/env python3
"""Convert `/control/export/snapshot` JSON into a slim control-plane SQLite DB.

This is for Supabase migration rehearsal when the live SQLite file is too large to
copy because of historical observation rows. It preserves queue, paper,
publication automation, recent events, flags, and minimal run rows needed by
foreign keys.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from enoch_control_plane.control_plane.store import ControlPlaneStore
from enoch_control_plane.models import utc_now


def text(value: Any) -> str:
    return str(value or "")


def integer(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def boolean(value: Any) -> int:
    return int(value is True or value in {1, "1", "true", "True", "TRUE", "yes", "YES"})


def load_snapshot(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("snapshot JSON must be an object")
    return payload


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value if isinstance(value, dict | list) else {},
        sort_keys=True,
        separators=(",", ":"),
    )


def _reject_conflicting_snapshot_replays(
    rows: list[dict[str, Any]],
    *,
    key_name: str,
    identity_fields: tuple[str, ...],
    label: str,
) -> None:
    seen: dict[str, tuple[str, ...]] = {}
    for row in rows:
        key = text(row.get(key_name))
        if not key:
            continue
        identity = tuple(text(row.get(field)) for field in identity_fields)
        existing = seen.get(key)
        if existing is not None and existing != identity:
            raise ValueError(f"conflicting {label} identity for {key_name} {key!r}")
        seen[key] = identity


def _reject_conflicting_event_replays(rows: list[dict[str, Any]]) -> None:
    seen: dict[str, tuple[str, str, str, str]] = {}
    for row in rows:
        key = (
            text(row.get("idempotency_key")) or f"snapshot-event:{row.get('event_id')}"
        )
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        identity = (
            text(row.get("event_type")) or "unknown",
            text(row.get("entity_type")) or "unknown",
            text(row.get("entity_id")),
            _canonical_json(payload),
        )
        existing = seen.get(key)
        if existing is not None and existing != identity:
            raise ValueError(f"conflicting event idempotency key {key!r}")
        seen[key] = identity


def convert(snapshot_path: Path, output_path: Path) -> dict[str, Any]:
    snapshot = load_snapshot(snapshot_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        output_path.unlink()
    store = ControlPlaneStore(output_path)
    now = utc_now()
    queue_rows = [
        row for row in snapshot.get("queue_rows") or [] if isinstance(row, dict)
    ]
    paper_rows = [
        row for row in snapshot.get("paper_rows") or [] if isinstance(row, dict)
    ]
    event_rows = [row for row in snapshot.get("events") or [] if isinstance(row, dict)]
    flags = snapshot.get("flags") if isinstance(snapshot.get("flags"), dict) else {}
    run_project: dict[str, dict[str, str]] = {}
    _reject_conflicting_snapshot_replays(
        queue_rows,
        key_name="project_id",
        identity_fields=("project_name", "project_dir", "status", "current_run_id"),
        label="queue project",
    )
    _reject_conflicting_snapshot_replays(
        paper_rows,
        key_name="paper_id",
        identity_fields=(
            "project_id",
            "run_id",
            "paper_type",
            "paper_status",
            "draft_markdown_path",
            "draft_latex_path",
            "evidence_bundle_path",
            "claim_ledger_path",
            "manifest_path",
        ),
        label="paper",
    )
    _reject_conflicting_event_replays(event_rows)

    with store._connect() as conn:  # noqa: SLF001 - migration utility intentionally writes the store schema directly.
        conn.executescript(
            """
            delete from dashboard_observations;
            delete from paper_review_items;
            delete from papers;
            delete from runs;
            delete from queue_items;
            delete from projects;
            delete from events;
            """
        )
        conn.execute(
            """
            update control_flags
            set queue_paused=?, maintenance_mode=?, pause_reason=?, paused_at=?, paused_by=?, updated_at=?
            where singleton=1
            """,
            (
                boolean(flags.get("queue_paused")),
                boolean(flags.get("maintenance_mode")),
                text(flags.get("pause_reason")),
                flags.get("paused_at"),
                text(flags.get("paused_by")),
                text(flags.get("updated_at")) or now,
            ),
        )
        for row in queue_rows:
            project_id = text(row.get("project_id"))
            if not project_id:
                continue
            conn.execute(
                """
                insert or replace into projects(project_id, project_name, project_dir, notion_page_url, notion_page_id,
                  origin_idea_status, created_at, updated_at)
                values (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    text(row.get("project_name")) or project_id,
                    text(row.get("project_dir")),
                    text(row.get("notion_page_url")),
                    text(row.get("notion_page_id")),
                    text(row.get("origin_idea_status")),
                    text(row.get("project_created_at") or row.get("created_at")) or now,
                    text(row.get("project_updated_at") or row.get("updated_at")) or now,
                ),
            )
            conn.execute(
                """
                insert or replace into queue_items(project_id, status, selection_rank, dispatch_priority, auto_continue,
                  continue_count, max_continues, retry_count, max_retries, current_run_id, current_session_id,
                  last_run_state, last_event_type, next_action_hint, manual_review_required, blocked_reason,
                  last_error, last_result_summary, machine_target, model, sandbox, last_dispatch_at,
                  last_callback_at, stale_after, updated_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    text(row.get("status")) or "queued",
                    integer(row.get("selection_rank")),
                    integer(row.get("dispatch_priority")),
                    boolean(row.get("auto_continue")),
                    integer(row.get("continue_count")),
                    integer(row.get("max_continues")),
                    integer(row.get("retry_count")),
                    integer(row.get("max_retries")),
                    text(row.get("current_run_id")),
                    text(row.get("current_session_id")),
                    text(row.get("last_run_state")),
                    text(row.get("last_event_type")),
                    text(row.get("next_action_hint")),
                    boolean(row.get("manual_review_required")),
                    text(row.get("blocked_reason")),
                    text(row.get("last_error")),
                    text(row.get("last_result_summary")),
                    text(row.get("machine_target")),
                    text(row.get("model")),
                    text(row.get("sandbox")),
                    row.get("last_dispatch_at"),
                    row.get("last_callback_at"),
                    row.get("stale_after"),
                    text(row.get("updated_at")) or now,
                ),
            )
            run_id = text(row.get("current_run_id"))
            if run_id:
                run_project.setdefault(
                    run_id,
                    {
                        "project_id": project_id,
                        "state": text(row.get("last_run_state")) or "unknown",
                        "session_id": text(row.get("current_session_id")),
                    },
                )

        for row in paper_rows:
            project_id = text(row.get("project_id"))
            paper_id = text(row.get("paper_id"))
            if not project_id or not paper_id:
                continue
            conn.execute(
                """
                insert or ignore into projects(project_id, project_name, project_dir, notion_page_url, notion_page_id,
                  origin_idea_status, created_at, updated_at)
                values (?, ?, ?, ?, ?, '', ?, ?)
                """,
                (
                    project_id,
                    text(row.get("project_name")) or project_id,
                    text(row.get("project_dir")),
                    text(row.get("notion_page_url")),
                    text(row.get("notion_page_id")),
                    now,
                    now,
                ),
            )
            run_id = text(row.get("run_id"))
            if run_id:
                run_project.setdefault(
                    run_id,
                    {"project_id": project_id, "state": "unknown", "session_id": ""},
                )
            conn.execute(
                """
                insert or replace into papers(paper_id, project_id, run_id, paper_type, paper_status,
                  draft_markdown_path, draft_latex_path, evidence_bundle_path, claim_ledger_path,
                  manifest_path, generated_at, updated_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    paper_id,
                    project_id,
                    run_id,
                    text(row.get("paper_type")) or "arxiv_draft",
                    text(row.get("paper_status")) or "draft_review",
                    text(row.get("draft_markdown_path")),
                    text(row.get("draft_latex_path")),
                    text(row.get("evidence_bundle_path")),
                    text(row.get("claim_ledger_path")),
                    text(row.get("manifest_path")),
                    text(row.get("generated_at")) or now,
                    text(row.get("updated_at")) or now,
                ),
            )
            review_status = text(
                row.get("review_status") or row.get("related_review_status")
            )
            if review_status:
                conn.execute(
                    """
                    insert or replace into paper_review_items(paper_id, review_status, reviewer, blocker, claimed_at,
                      checklist_json, rank_score, rank_reasons_json, missing_signals_json, rank_tiebreaker,
                      source_audit_path, finalization_package_path, finalized_at, decision_summary, created_at, updated_at)
                    values (?, ?, '', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        paper_id,
                        review_status,
                        text(row.get("blocker")),
                        text(row.get("claimed_at")),
                        json.dumps(
                            row.get("checklist_json") or {},
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                        integer(row.get("rank_score")),
                        json.dumps(
                            row.get("rank_reasons")
                            or row.get("rank_reasons_json")
                            or [],
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                        json.dumps(
                            row.get("missing_signals")
                            or row.get("missing_signals_json")
                            or [],
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                        text(row.get("rank_tiebreaker") or paper_id),
                        text(row.get("source_audit_path")),
                        text(row.get("finalization_package_path")),
                        text(row.get("finalized_at")),
                        text(row.get("decision_summary")),
                        text(row.get("created_at")) or now,
                        text(row.get("updated_at")) or now,
                    ),
                )

        for run_id, meta in run_project.items():
            conn.execute(
                """
                insert or replace into runs(run_id, project_id, session_id, state, dispatch_mode, started_at, ended_at,
                  last_callback_at, gate_state, current_activity, idempotency_key, updated_at)
                values (?, ?, ?, ?, '', null, null, null, '', '', ?, ?)
                """,
                (
                    run_id,
                    meta["project_id"],
                    meta["session_id"],
                    meta["state"],
                    f"snapshot-run:{run_id}",
                    now,
                ),
            )

        for event in event_rows:
            payload = (
                event.get("payload") if isinstance(event.get("payload"), dict) else {}
            )
            conn.execute(
                """
                insert or ignore into events(idempotency_key, event_type, entity_type, entity_id, payload_json, payload_hash, created_at)
                values (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    text(event.get("idempotency_key"))
                    or f"snapshot-event:{event.get('event_id')}",
                    text(event.get("event_type")) or "unknown",
                    text(event.get("entity_type")) or "unknown",
                    text(event.get("entity_id")),
                    json.dumps(payload, sort_keys=True, separators=(",", ":")),
                    "0" * 64,
                    text(event.get("created_at")) or now,
                ),
            )

    return {
        "ok": True,
        "output": str(output_path),
        "queue_rows": len(queue_rows),
        "paper_rows": len(paper_rows),
        "run_rows": len(run_project),
        "event_rows": len(event_rows),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-json", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    print(
        json.dumps(convert(args.snapshot_json, args.output), indent=2, sort_keys=True)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
