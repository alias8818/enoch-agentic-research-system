#!/usr/bin/env python3
"""Preflight a live control-plane cutover to the Supabase backend.

This script is intentionally read-only. It compares the paused live SQLite-backed
control-plane dashboard against the hosted Supabase views populated by the
backfill. It refuses to pass without a real Postgres URL so the final runtime
switch cannot rely on the Supabase CLI session alone.
"""

from __future__ import annotations

import argparse
import json
import os
import urllib.request
from dataclasses import dataclass
from typing import Any

EXPECTED_SAFE_FLAGS = {"queue_paused": True, "maintenance_mode": True}
PIPELINE_KEYS = (
    "write_needed",
    "raw_completed_no_paper_candidates",
    "not_writable_by_decision_gate",
    "publication_ready",
    "needs_attention",
)


@dataclass(frozen=True)
class CutoverCheck:
    ok: bool
    failures: list[str]
    live: dict[str, Any]
    supabase: dict[str, Any]


def _load_token(path: str) -> str:
    explicit = os.environ.get("ENOCH_CONTROL_PLANE_TOKEN", "").strip()
    if explicit:
        return explicit
    try:
        return open(path, encoding="utf-8").read().strip()
    except OSError:
        return ""


def _get_json(url: str, token: str) -> dict[str, Any]:
    req = urllib.request.Request(url)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=15) as response:  # noqa: S310 - operator-provided LAN URL
        return json.loads(response.read().decode("utf-8"))


def _connect_pg(database_url: str) -> Any:
    import psycopg
    from psycopg.rows import dict_row

    return psycopg.connect(database_url, row_factory=dict_row)


def _supabase_counts(database_url: str) -> dict[str, Any]:
    with _connect_pg(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute("set search_path to enoch, public")
            dashboard = cur.execute(
                "select * from operator_dashboard_counts"
            ).fetchone()
            tables = cur.execute(
                """
                select jsonb_object_agg(name, count_value order by name) as counts
                from (
                  select 'projects' as name, count(*)::int as count_value from projects
                  union all select 'queue_items', count(*)::int from queue_items
                  union all select 'runs', count(*)::int from runs
                  union all select 'papers', count(*)::int from papers
                  union all select 'project_decisions', count(*)::int from project_decisions
                  union all select 'publication_automation_items', count(*)::int from publication_automation_items
                  union all select 'control_events', count(*)::int from control_events
                  union all select 'core_events', count(*)::int from core_events
                  union all select 'core_snapshots', count(*)::int from core_snapshots
                ) counts
                """
            ).fetchone()["counts"]
    out = dict(dashboard or {})
    out["table_counts"] = dict(tables or {})
    return out


def _live_counts(control_url: str, token: str) -> dict[str, Any]:
    base = control_url.rstrip("/")
    overview = _get_json(f"{base}/control/api/v1/overview", token)
    state = _get_json(f"{base}/control/state", token)
    core_health = _get_json(f"{base}/enoch-core/health", token)
    pipeline = overview.get("paper_pipeline") or {}
    operator_counts = overview.get("operator_counts") or {}
    return {
        "write_needed": int(pipeline.get("write_needed") or 0),
        "raw_completed_no_paper_candidates": int(
            pipeline.get("raw_completed_no_paper_candidates") or 0
        ),
        "not_writable_by_decision_gate": int(
            pipeline.get("not_writable_by_decision_gate") or 0
        ),
        "publication_ready": int(pipeline.get("publish_ready") or 0),
        "needs_attention": int(
            operator_counts.get("needs_attention")
            or (overview.get("counts") or {}).get("blocked")
            or 0
        ),
        "flags": state.get("flags") or {},
        "state_counts": state.get("counts") or {},
        "overview_counts": overview.get("counts") or {},
        "paper_counts": overview.get("paper_counts") or {},
        "enoch_core": {
            "store_backend": core_health.get("store_backend"),
            "db_path": core_health.get("db_path"),
        },
    }


def compare(
    live: dict[str, Any], supabase: dict[str, Any], *, require_safe_pause: bool = True
) -> CutoverCheck:
    failures: list[str] = []
    for key in PIPELINE_KEYS:
        if int(live.get(key) or 0) != int(supabase.get(key) or 0):
            failures.append(
                f"{key} mismatch: live={live.get(key)} supabase={supabase.get(key)}"
            )
    if require_safe_pause:
        flags = live.get("flags") or {}
        for key, expected in EXPECTED_SAFE_FLAGS.items():
            if bool(flags.get(key)) is not expected:
                failures.append(
                    f"live safety flag {key}={flags.get(key)!r}, expected {expected!r}"
                )
    if (live.get("enoch_core") or {}).get("store_backend") != "supabase":
        failures.append(
            f"enoch-core store_backend={(live.get('enoch_core') or {}).get('store_backend')!r}, expected 'supabase'"
        )
    table_counts = supabase.get("table_counts") or {}
    if int(table_counts.get("queue_items") or 0) < int(
        (live.get("state_counts") or {}).get("queue_total") or 0
    ):
        failures.append("supabase queue_items count is lower than live queue_total")
    if int(table_counts.get("papers") or 0) != int(
        (live.get("paper_counts") or {}).get("all") or 0
    ):
        failures.append("supabase papers count does not match live paper_counts.all")
    if "core_events" not in table_counts or "core_snapshots" not in table_counts:
        failures.append(
            "Supabase Enoch core tables are missing from the runtime schema"
        )
    return CutoverCheck(
        ok=not failures, failures=failures, live=live, supabase=supabase
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--control-url", default="http://127.0.0.1:8787")
    parser.add_argument(
        "--token-file",
        default=os.environ.get(
            "ENOCH_CONTROL_PLANE_TOKEN_FILE", "/root/enoch-control-plane-token.txt"
        ),
    )
    parser.add_argument(
        "--database-url", default=os.environ.get("ENOCH_SUPABASE_DATABASE_URL", "")
    )
    parser.add_argument(
        "--allow-unpaused",
        action="store_true",
        help="do not require live control plane queue_paused/maintenance_mode flags",
    )
    args = parser.parse_args(argv)

    failures: list[str] = []
    token = _load_token(args.token_file)
    if not token:
        failures.append(
            "missing control-plane token; set ENOCH_CONTROL_PLANE_TOKEN or --token-file"
        )
    if not args.database_url.strip():
        failures.append(
            "missing Supabase Postgres URL; set ENOCH_SUPABASE_DATABASE_URL or pass --database-url"
        )
    if failures:
        print(json.dumps({"ok": False, "failures": failures}, indent=2, sort_keys=True))
        return 2

    try:
        live = _live_counts(args.control_url, token)
        supabase = _supabase_counts(args.database_url.strip())
        result = compare(live, supabase, require_safe_pause=not args.allow_unpaused)
    except Exception as exc:  # pragma: no cover - operational diagnostic path
        print(
            json.dumps(
                {
                    "ok": False,
                    "failures": [f"preflight exception: {type(exc).__name__}: {exc}"],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 1
    print(
        json.dumps(
            {
                "ok": result.ok,
                "failures": result.failures,
                "live": result.live,
                "supabase": result.supabase,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
