#!/usr/bin/env python3
"""Re-queue Supabase cutover-paused control-plane items after safety checks.

This targets only rows paused by the migration cutover marker:
- queue_items.status = 'paused'
- next_action_hint = 'maintenance_cutover_reconcile'
- manual_review_required = false
- no paper row exists for the project

Default mode is dry-run. With --apply, matching rows are moved back to queued
while the global queue can remain paused. This does not dispatch work or enable
timers.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, UTC
from typing import Any


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")


def _connect(database_url: str) -> Any:
    import psycopg
    from psycopg.rows import dict_row

    return psycopg.connect(database_url, row_factory=dict_row)


def _worker_process_check(worker_ssh_host: str, project_ids: list[str]) -> dict[str, Any]:
    if not worker_ssh_host or not project_ids:
        return {"checked": False, "matches": []}
    pattern = "|".join(project_ids)
    cmd = [
        "ssh",
        "-o",
        "ConnectTimeout=8",
        worker_ssh_host,
        f"ps -eo pid,etimes,cmd | grep -E '{pattern}' | grep -v grep || true",
    ]
    completed = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    matches = [line for line in completed.stdout.splitlines() if line.strip()]
    if completed.returncode != 0:
        return {
            "checked": True,
            "ok": False,
            "returncode": completed.returncode,
            "matches": [],
            "raw": completed.stdout,
        }
    return {"checked": True, "ok": True, "returncode": completed.returncode, "matches": matches, "raw": completed.stdout}


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _candidate_rows(conn: Any) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute("set search_path to enoch, public")
        rows = cur.execute(
            """
            select q.project_id, p.project_name, q.status, q.next_action_hint, q.last_run_state,
                   q.current_run_id, q.updated_at
            from queue_items q
            join projects p using(project_id)
            where q.status = 'paused'
              and q.next_action_hint = 'maintenance_cutover_reconcile'
              and q.manual_review_required = false
              and not exists (select 1 from papers pa where pa.project_id = q.project_id)
            order by q.updated_at desc, q.project_id asc
            """
        ).fetchall()
    return [_jsonable(dict(row)) for row in rows]


def reconcile(args: argparse.Namespace) -> dict[str, Any]:
    database_url = args.database_url or os.environ.get("ENOCH_SUPABASE_DATABASE_URL", "")
    if not database_url.strip():
        return {"ok": False, "failures": ["missing database URL; set ENOCH_SUPABASE_DATABASE_URL or --database-url"]}
    with _connect(database_url) as conn:
        rows = _candidate_rows(conn)
        project_ids = [row["project_id"] for row in rows]
        process_check = _worker_process_check(args.worker_ssh_host, project_ids)
        failures: list[str] = []
        if process_check.get("checked") and not process_check.get("ok", True):
            failures.append("worker process check failed; refusing to requeue without clean process evidence")
        if process_check.get("matches"):
            failures.append("worker process check found matching project processes; refusing to requeue")
        if failures or not args.apply:
            return {
                "ok": not failures,
                "applied": False,
                "failures": failures,
                "candidate_count": len(rows),
                "candidates": rows,
                "worker_process_check": process_check,
            }
        now = _utc_now()
        with conn.cursor() as cur:
            cur.execute("set search_path to enoch, public")
            updated = cur.execute(
                """
                update queue_items q
                set status = 'queued',
                    next_action_hint = 'controller_review',
                    last_result_summary = %s,
                    updated_at = %s
                where q.status = 'paused'
                  and q.next_action_hint = 'maintenance_cutover_reconcile'
                  and q.manual_review_required = false
                  and not exists (select 1 from papers pa where pa.project_id = q.project_id)
                returning q.project_id
                """,
                (f"Re-queued after Supabase cutover reconciliation by {args.requested_by}.", now),
            ).fetchall()
            payload = {
                "requested_by": args.requested_by,
                "candidate_count": len(rows),
                "updated_count": len(updated),
                "project_ids": [row["project_id"] for row in updated],
                "worker_process_check": process_check,
            }
            import hashlib
            payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
            payload_hash = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
            cur.execute(
                """
                insert into control_events(idempotency_key, event_type, entity_type, entity_id, payload_json, payload_hash, created_at)
                values (%s, 'queue.cutover_requeue', 'control', 'queue', %s::jsonb, %s, %s)
                on conflict (idempotency_key) do nothing
                """,
                (args.idempotency_key or f"queue-cutover-requeue:{now}", payload_json, payload_hash, now),
            )
        conn.commit()
    return {"ok": True, "applied": True, "updated_count": len(updated), "updated_project_ids": [row["project_id"] for row in updated]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default="")
    parser.add_argument("--worker-ssh-host", default="")
    parser.add_argument("--requested-by", default="supabase-cutover-reconcile")
    parser.add_argument("--idempotency-key", default="")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    try:
        result = reconcile(args)
    except Exception as exc:
        result = {"ok": False, "failures": [f"{type(exc).__name__}: {exc}"]}
    text = json.dumps(result, indent=2, sort_keys=True)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
    print(text)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
