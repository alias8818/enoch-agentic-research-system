#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from omx_wake_gate.control_plane.state_contract import STATE_CONTRACT, STATE_DISPOSITIONS, STATE_REDUCTION_PLAN  # noqa: E402

MIGRATION_GLOBS = ("supabase/migrations/*.sql",)


def _extract_in_values(sql: str, column: str) -> set[str]:
    # Purposefully simple: this validates our migration text contains the same
    # literal state vocabulary as the Python contract.
    pattern = re.compile(rf"{re.escape(column)}\s+in\s*\((.*?)\)", re.IGNORECASE | re.DOTALL)
    values: set[str] = set()
    for match in pattern.finditer(sql):
        values.update(re.findall(r"'([^']+)'", match.group(1)))
    return values


def _migration_sql() -> str:
    chunks: list[str] = []
    for glob in MIGRATION_GLOBS:
        for path in sorted(REPO_ROOT.glob(glob)):
            chunks.append(path.read_text(encoding="utf-8"))
    return "\n".join(chunks)


def _validate_migrations() -> list[str]:
    sql = _migration_sql()
    failures: list[str] = []
    column_by_surface = {
        "queue_items.status": "status",
        "runs.state": "state",
        "papers.paper_status": "paper_status",
        "publication_automation_items.automation_status": "automation_status",
        "project_decisions.decision_gate_state": "decision_gate_state",
        "ideas.idea_status": "idea_status",
        "projects.origin_idea_status": "origin_idea_status",
    }
    for surface, column in column_by_surface.items():
        expected = STATE_CONTRACT[surface]
        values = _extract_in_values(sql, column)
        missing = expected - values
        if missing:
            failures.append(f"migration contract for {surface} missing values: {sorted(missing)}")
    return failures


def _validate_reduction_plan() -> list[str]:
    failures: list[str] = []
    for surface, values in STATE_CONTRACT.items():
        planned = STATE_REDUCTION_PLAN.get(surface)
        if planned is None:
            failures.append(f"state reduction plan missing surface: {surface}")
            continue
        missing = values - set(planned)
        extra = set(planned) - values
        if missing:
            failures.append(f"state reduction plan for {surface} missing values: {sorted(missing)}")
        if extra:
            failures.append(f"state reduction plan for {surface} has values outside contract: {sorted(extra)}")
        for value, decision in planned.items():
            disposition = str(decision.get("disposition") or "")
            lane = str(decision.get("operator_lane") or "")
            replacement = str(decision.get("replacement") or "")
            if disposition not in STATE_DISPOSITIONS:
                failures.append(f"state reduction plan for {surface}.{value} has invalid disposition: {disposition!r}")
            if not lane:
                failures.append(f"state reduction plan for {surface}.{value} missing operator_lane")
            if disposition in {"alias", "migrate_after_freeze"} and not replacement:
                failures.append(f"state reduction plan for {surface}.{value} disposition={disposition} needs replacement")
    return failures


def _live_distincts(database_url: str) -> dict[str, list[tuple[str, int]]]:
    import psycopg

    table_column = {
        "queue_items.status": ("queue_items", "status"),
        "queue_items.last_run_state": ("queue_items", "last_run_state"),
        "runs.state": ("runs", "state"),
        "runs.gate_state": ("runs", "gate_state"),
        "papers.paper_status": ("papers", "paper_status"),
        "publication_automation_items.automation_status": ("publication_automation_items", "automation_status"),
        "project_decisions.decision_gate_state": ("project_decisions", "decision_gate_state"),
        "ideas.idea_status": ("ideas", "idea_status"),
        "projects.origin_idea_status": ("projects", "origin_idea_status"),
    }
    result: dict[str, list[tuple[str, int]]] = {}
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute("set search_path to enoch, public")
            for surface, (table, column) in table_column.items():
                cur.execute(f"select {column}, count(*)::int from {table} group by {column} order by {column}")
                result[surface] = [(str(value or ""), int(count)) for value, count in cur.fetchall()]
    return result


def validate(*, database_url: str = "") -> dict[str, Any]:
    failures = _validate_migrations() + _validate_reduction_plan()
    live: dict[str, Any] = {}
    if database_url:
        live = _live_distincts(database_url)
        for surface, rows in live.items():
            allowed = STATE_CONTRACT[surface]
            unknown = sorted(value for value, _count in rows if value not in allowed)
            if unknown:
                failures.append(f"live {surface} has values outside contract: {unknown}")
    return {
        "ok": not failures,
        "failures": failures,
        "contract": {surface: sorted(values) for surface, values in sorted(STATE_CONTRACT.items())},
        "reduction_plan": STATE_REDUCTION_PLAN,
        "live_distincts": live,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Enoch raw state vocabulary against the canonical state contract.")
    parser.add_argument("--database-url", default=os.environ.get("ENOCH_SUPABASE_DATABASE_URL", ""), help="Optional live Supabase/Postgres URL for distinct-value validation.")
    parser.add_argument("--output", default="", help="Optional JSON report path.")
    args = parser.parse_args()
    result = validate(database_url=args.database_url)
    text = json.dumps(result, indent=2, sort_keys=True)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
