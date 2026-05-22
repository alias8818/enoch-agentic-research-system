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

from enoch_control_plane.control_plane.state_contract import (  # noqa: E402
    STATE_CONTRACT,
    STATE_DISPOSITIONS,
    STATE_LIKE_COLUMN_NAMES,
    STATE_SURFACE_INVENTORY,
    STATE_REDUCTION_PLAN,
)

MIGRATION_GLOBS = ("supabase/migrations/*.sql",)


def _extract_in_values(sql: str, column: str) -> set[str]:
    # Purposefully simple: this validates our migration text contains the same
    # literal state vocabulary as the Python contract.
    pattern = re.compile(
        rf"(?<![a-z0-9_]){re.escape(column)}(?![a-z0-9_])\s+in\s*\((.*?)\)",
        re.IGNORECASE | re.DOTALL,
    )
    values: set[str] = set()
    for match in pattern.finditer(sql):
        values.update(re.findall(r"'([^']*)'", match.group(1)))
    return values


def _migration_sql() -> str:
    chunks: list[str] = []
    for glob in MIGRATION_GLOBS:
        for path in sorted(REPO_ROOT.glob(glob)):
            chunks.append(path.read_text(encoding="utf-8"))
    return "\n".join(chunks)


def _migration_state_like_surfaces() -> set[str]:
    """Return persisted schema columns that look state-bearing or state-adjacent.

    This intentionally catches more than finite lifecycle states. The inventory
    then classifies each surface as canonical lifecycle, flag, hint, provenance,
    taxonomy, or projection metadata so future changes do not silently promote
    raw metadata into operator-facing workflow states.
    """

    sql = _migration_sql()
    surfaces: set[str] = set()
    table_pattern = re.compile(
        r"create\s+table\s+if\s+not\s+exists\s+enoch\.([a-z_]+)\s*\((.*?)\n\);",
        re.IGNORECASE | re.DOTALL,
    )
    state_suffixes = ("_status", "_state", "_mode", "_type")
    for match in table_pattern.finditer(sql):
        table = match.group(1)
        body = match.group(2)
        for line in body.splitlines():
            column_match = re.match(
                r"\s*([a-z_][a-z0-9_]*)\s+([a-z][a-z0-9_ ]*)", line, re.IGNORECASE
            )
            if not column_match:
                continue
            column = column_match.group(1)
            if column in {
                "constraint",
                "primary",
                "foreign",
                "unique",
                "check",
                "on",
                "references",
            }:
                continue
            if column in STATE_LIKE_COLUMN_NAMES or column.endswith(state_suffixes):
                surfaces.add(f"{table}.{column}")
    return surfaces


def _validate_migrations() -> list[str]:
    sql = _migration_sql()
    failures: list[str] = []
    column_by_surface = {
        "queue_items.status": "status",
        "queue_items.last_run_state": "last_run_state",
        "runs.state": "state",
        "runs.gate_state": "gate_state",
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
            failures.append(
                f"migration contract for {surface} missing values: {sorted(missing)}"
            )
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
            failures.append(
                f"state reduction plan for {surface} missing values: {sorted(missing)}"
            )
        if extra:
            failures.append(
                f"state reduction plan for {surface} has values outside contract: {sorted(extra)}"
            )
        for value, decision in planned.items():
            disposition = str(decision.get("disposition") or "")
            lane = str(decision.get("operator_lane") or "")
            replacement = str(decision.get("replacement") or "")
            if disposition not in STATE_DISPOSITIONS:
                failures.append(
                    f"state reduction plan for {surface}.{value} has invalid disposition: {disposition!r}"
                )
            if not lane:
                failures.append(
                    f"state reduction plan for {surface}.{value} missing operator_lane"
                )
            if disposition in {"alias", "migrate_after_freeze"} and not replacement:
                failures.append(
                    f"state reduction plan for {surface}.{value} disposition={disposition} needs replacement"
                )
    return failures


def _validate_surface_inventory() -> list[str]:
    failures: list[str] = []
    discovered = _migration_state_like_surfaces()
    missing = discovered - set(STATE_SURFACE_INVENTORY)
    extra_canonical = {
        surface
        for surface, decision in STATE_SURFACE_INVENTORY.items()
        if decision.get("class") == "canonical_lifecycle"
        and surface not in STATE_CONTRACT
    }
    noncanonical_contract = {
        surface
        for surface, decision in STATE_SURFACE_INVENTORY.items()
        if surface in STATE_CONTRACT and decision.get("class") != "canonical_lifecycle"
    }
    if missing:
        failures.append(
            f"state surface inventory missing schema surfaces: {sorted(missing)}"
        )
    if extra_canonical:
        failures.append(
            f"state surface inventory marks non-contract surfaces as canonical_lifecycle: {sorted(extra_canonical)}"
        )
    if noncanonical_contract:
        failures.append(
            f"state surface inventory marks contract surfaces as non-canonical: {sorted(noncanonical_contract)}"
        )
    for surface, decision in sorted(STATE_SURFACE_INVENTORY.items()):
        surface_class = str(decision.get("class") or "")
        if surface_class not in {
            "canonical_lifecycle",
            "derived_operator",
            "system_flag",
            "attention_flag",
            "operator_hint",
            "diagnostic_context",
            "provenance_text",
            "type_discriminator",
            "event_taxonomy",
            "projection_metadata",
        }:
            failures.append(
                f"state surface inventory for {surface} has invalid class: {surface_class!r}"
            )
        if not str(decision.get("reason") or ""):
            failures.append(f"state surface inventory for {surface} missing reason")
    return failures


def _live_distincts(database_url: str) -> dict[str, list[tuple[str, int]]]:
    import psycopg

    table_column = {
        "queue_items.status": ("queue_items", "status"),
        "queue_items.last_run_state": ("queue_items", "last_run_state"),
        "runs.state": ("runs", "state"),
        "runs.gate_state": ("runs", "gate_state"),
        "papers.paper_status": ("papers", "paper_status"),
        "publication_automation_items.automation_status": (
            "publication_automation_items",
            "automation_status",
        ),
        "project_decisions.decision_gate_state": (
            "project_decisions",
            "decision_gate_state",
        ),
        "ideas.idea_status": ("ideas", "idea_status"),
        "projects.origin_idea_status": ("projects", "origin_idea_status"),
    }
    result: dict[str, list[tuple[str, int]]] = {}
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute("set search_path to enoch, public")
            for surface, (table, column) in table_column.items():
                cur.execute(
                    f"select {column}, count(*)::int from {table} group by {column} order by {column}"
                )
                result[surface] = [
                    (str(value or ""), int(count)) for value, count in cur.fetchall()
                ]
    return result


def validate(*, database_url: str = "") -> dict[str, Any]:
    failures = (
        _validate_migrations()
        + _validate_reduction_plan()
        + _validate_surface_inventory()
    )
    live: dict[str, Any] = {}
    if database_url:
        live = _live_distincts(database_url)
        for surface, rows in live.items():
            allowed = STATE_CONTRACT[surface]
            unknown = sorted(value for value, _count in rows if value not in allowed)
            if unknown:
                failures.append(
                    f"live {surface} has values outside contract: {unknown}"
                )
    return {
        "ok": not failures,
        "failures": failures,
        "contract": {
            surface: sorted(values)
            for surface, values in sorted(STATE_CONTRACT.items())
        },
        "state_surface_inventory": STATE_SURFACE_INVENTORY,
        "reduction_plan": STATE_REDUCTION_PLAN,
        "live_distincts": live,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate Enoch raw state vocabulary against the canonical state contract."
    )
    parser.add_argument(
        "--database-url",
        default=os.environ.get("ENOCH_SUPABASE_DATABASE_URL", ""),
        help="Optional live Supabase/Postgres URL for distinct-value validation.",
    )
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
