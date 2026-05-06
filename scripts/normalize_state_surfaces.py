#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from typing import Any

NORMALIZATION_STATEMENTS: tuple[dict[str, str], ...] = (
    {
        "name": "finalized_draft_review_papers_to_publication_draft",
        "sql": """
        update papers p
        set paper_status = 'publication_draft', updated_at = now()
        from publication_automation_items a
        where a.paper_id = p.paper_id
          and p.paper_status = 'draft_review'
          and a.automation_status = 'finalized'
          and coalesce(a.finalization_package_path, '') <> ''
        """,
        "reason": "finalized automation package, not paper_status, is the ready-to-publish proof; collapse legacy first-draft rows",
    },
    {
        "name": "legacy_project_decision_needs_review_to_unknown",
        "sql": """
        update project_decisions
        set decision_gate_state = 'unknown', updated_at = now()
        where decision_gate_state = 'needs_review'
        """,
        "reason": "ambiguous project decisions are non-writable, not a human paper-review state",
    },
    {
        "name": "legacy_publication_unreviewed_to_queued",
        "sql": """
        update publication_automation_items
        set automation_status = 'queued', updated_at = now()
        where automation_status in ('unreviewed', 'triage_ready', 'approved_for_finalization')
        """,
        "reason": "legacy review/approval queue states collapse to automation queued",
    },
    {
        "name": "legacy_publication_in_review_to_claimed",
        "sql": """
        update publication_automation_items
        set automation_status = 'claimed', updated_at = now()
        where automation_status = 'in_review'
        """,
        "reason": "legacy review-running state is automation claimed",
    },
    {
        "name": "legacy_publication_changes_requested_to_blocked",
        "sql": """
        update publication_automation_items
        set automation_status = 'blocked', updated_at = now()
        where automation_status = 'changes_requested'
        """,
        "reason": "correction/request language is just an automation blocker",
    },
    {
        "name": "legacy_queue_needs_review_to_blocked",
        "sql": """
        update queue_items
        set status = 'blocked', updated_at = now()
        where status = 'needs_review'
        """,
        "reason": "operator attention is represented by blocked/needs_operator, not review",
    },
    {
        "name": "legacy_queue_last_run_needs_review_to_gate_error",
        "sql": """
        update queue_items
        set last_run_state = 'gate_error', updated_at = now()
        where last_run_state = 'needs_review'
        """,
        "reason": "legacy run attention detail collapses to gate_error for blocker handling",
    },
    {
        "name": "queue_session_finished_alias_to_wake_ready",
        "sql": """
        update queue_items
        set last_run_state = 'wake_ready', updated_at = now()
        where last_run_state = 'session_finished_ready'
        """,
        "reason": "session_finished_ready is a delivery-complete alias of wake_ready",
    },
    {
        "name": "legacy_run_needs_review_to_gate_error",
        "sql": """
        update runs
        set state = 'gate_error', updated_at = now()
        where state = 'needs_review'
        """,
        "reason": "legacy run attention state collapses to gate_error",
    },
    {
        "name": "superseded_dispatch_accepted_runs_to_reconciled",
        "sql": """
        update runs r
        set state = 'reconciled', updated_at = now()
        from queue_items q
        where q.project_id = r.project_id
          and r.state = 'dispatch_accepted'
          and coalesce(q.current_run_id, '') <> r.run_id
        """,
        "reason": "old dispatch-accepted run rows superseded by a newer queue run are historical, not active work",
    },
    {
        "name": "current_dispatch_accepted_runs_to_awaiting_wake",
        "sql": """
        update runs r
        set state = 'awaiting_wake', updated_at = now()
        from queue_items q
        where q.project_id = r.project_id
          and r.state = 'dispatch_accepted'
          and q.current_run_id = r.run_id
        """,
        "reason": "current old dispatch-accepted bridge rows are waiting for callback",
    },
    {
        "name": "legacy_run_gate_needs_review_to_gate_error",
        "sql": """
        update runs
        set gate_state = 'gate_error', updated_at = now()
        where gate_state = 'needs_review'
        """,
        "reason": "legacy gate attention state collapses to gate_error",
    },
    {
        "name": "legacy_run_gate_dispatch_accepted_to_awaiting_wake",
        "sql": """
        update runs
        set gate_state = 'awaiting_wake', updated_at = now()
        where gate_state = 'dispatch_accepted'
        """,
        "reason": "old dispatch bridge gate detail collapses to waiting for callback",
    },
    {
        "name": "run_session_finished_alias_to_wake_ready",
        "sql": """
        update runs
        set state = 'wake_ready', updated_at = now()
        where state = 'session_finished_ready'
        """,
        "reason": "session_finished_ready is a delivery-complete alias of wake_ready",
    },
    {
        "name": "run_gate_session_finished_alias_to_wake_ready",
        "sql": """
        update runs
        set gate_state = 'wake_ready', updated_at = now()
        where gate_state = 'session_finished_ready'
        """,
        "reason": "session_finished_ready is a delivery-complete alias of wake_ready",
    },
)


def normalize(database_url: str, *, apply: bool) -> dict[str, Any]:
    import psycopg

    changes: list[dict[str, Any]] = []
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute("set search_path to enoch, public")
            for statement in NORMALIZATION_STATEMENTS:
                cur.execute(statement["sql"])
                changes.append({
                    "name": statement["name"],
                    "rows": int(cur.rowcount if cur.rowcount is not None and cur.rowcount >= 0 else 0),
                    "reason": statement["reason"],
                })
        if apply:
            conn.commit()
        else:
            conn.rollback()
    return {"ok": True, "applied": apply, "changes": changes, "total_rows": sum(item["rows"] for item in changes)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Normalize legacy Enoch state values after the Supabase state contract audit.")
    parser.add_argument("--database-url", default=os.environ.get("ENOCH_SUPABASE_DATABASE_URL", ""))
    parser.add_argument("--apply", action="store_true", help="Commit updates. Default is a dry-run transaction rollback.")
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    if not args.database_url:
        raise SystemExit("missing --database-url or ENOCH_SUPABASE_DATABASE_URL")
    result = normalize(args.database_url, apply=args.apply)
    text = json.dumps(result, indent=2, sort_keys=True)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(text + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
