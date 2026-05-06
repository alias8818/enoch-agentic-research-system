#!/usr/bin/env python3
"""Validate Supabase migration SQL against an ephemeral Postgres container.

This is intentionally local-only. It never connects to a Supabase cloud project
and never runs `supabase db push` or MCP migration APIs.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_IMAGE = "postgres:17-alpine"


class ValidationError(RuntimeError):
    """Raised when validation cannot complete."""


def run(cmd: list[str], *, stdin: str | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        input=stdin,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=check,
    )


def docker_available() -> None:
    try:
        run(["docker", "version", "--format", "{{.Server.Version}}"])
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        raise ValidationError("Docker is required for local migration validation") from exc


def psql(container: str, sql: str, *, tuples_only: bool = False) -> str:
    cmd = ["docker", "exec", "-i", container, "psql", "-U", "postgres", "-d", "postgres", "-v", "ON_ERROR_STOP=1"]
    if tuples_only:
        cmd.extend(["-A", "-t"])
    result = run(cmd, stdin=sql)
    return result.stdout


def psql_file(container: str, path: Path) -> str:
    with path.open() as handle:
        result = run(
            [
                "docker",
                "exec",
                "-i",
                container,
                "psql",
                "-U",
                "postgres",
                "-d",
                "postgres",
                "-v",
                "ON_ERROR_STOP=1",
            ],
            stdin=handle.read(),
        )
    return result.stdout


def wait_for_postgres(container: str, timeout_seconds: int = 60) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        probe = run(["docker", "exec", container, "pg_isready", "-U", "postgres"], check=False)
        if probe.returncode == 0:
            return
        time.sleep(1)
    raise ValidationError(f"Postgres container {container} did not become ready")


def fetch_json(container: str, sql: str) -> Any:
    raw = psql(container, sql, tuples_only=True).strip()
    return json.loads(raw)


def validate(container: str, migrations: list[Path]) -> dict[str, Any]:
    psql(
        container,
        """
        do $$
        begin
          if not exists (select 1 from pg_roles where rolname = 'anon') then
            create role anon;
          end if;
          if not exists (select 1 from pg_roles where rolname = 'authenticated') then
            create role authenticated;
          end if;
          if not exists (select 1 from pg_roles where rolname = 'service_role') then
            create role service_role;
          end if;
        end $$;
        """,
    )
    for migration in migrations:
        psql_file(container, migration)

    psql(
        container,
        """
        insert into enoch.projects(project_id, project_name, project_dir) values
          ('fixture-positive', 'Fixture Positive', 'fixture-positive'),
          ('fixture-negative', 'Fixture Negative', 'fixture-negative'),
          ('fixture-existing-paper', 'Fixture Existing Paper', 'fixture-existing-paper');

        insert into enoch.queue_items(project_id, status, current_run_id, last_run_state, next_action_hint) values
          ('fixture-positive', 'completed', 'run-positive', 'wake_ready', 'draft_paper_or_select_next_project'),
          ('fixture-negative', 'completed', 'run-negative', 'wake_ready', 'draft_paper_or_select_next_project'),
          ('fixture-existing-paper', 'completed', 'run-existing', 'wake_ready', 'draft_paper_or_select_next_project');

        insert into enoch.runs(run_id, project_id, state, idempotency_key) values
          ('run-positive', 'fixture-positive', 'wake_ready', 'fixture-run-positive'),
          ('run-negative', 'fixture-negative', 'wake_ready', 'fixture-run-negative'),
          ('run-existing', 'fixture-existing-paper', 'wake_ready', 'fixture-run-existing');

        insert into enoch.project_decisions(
          project_id, run_id, decision_gate_state, decision_summary, payload_hash
        ) values
          ('fixture-positive', 'run-positive', 'positive', 'positive fixture should be writable', repeat('0', 64)),
          ('fixture-negative', 'run-negative', 'negative', 'negative fixture must not be writable', repeat('1', 64)),
          ('fixture-existing-paper', 'run-existing', 'positive', 'positive but already has paper', repeat('2', 64));

        insert into enoch.papers(paper_id, project_id, run_id, paper_status) values
          ('paper-existing', 'fixture-existing-paper', 'run-existing', 'publication_draft');

        insert into enoch.publication_automation_items(paper_id, automation_status, finalization_package_path) values
          ('paper-existing', 'finalized', 'package.json');
        """,
    )

    checks = fetch_json(
        container,
        """
        select jsonb_build_object(
          'enoch_base_tables', (
            select count(*)
            from information_schema.tables
            where table_schema = 'enoch' and table_type = 'BASE TABLE'
          ),
          'enoch_views', (
            select count(*)
            from information_schema.views
            where table_schema = 'enoch'
          ),
          'public_base_tables', (
            select count(*)
            from information_schema.tables
            where table_schema = 'public' and table_type = 'BASE TABLE'
          ),
          'rls_disabled_tables', coalesce((
            select jsonb_agg(tablename order by tablename)
            from pg_tables
            where schemaname = 'enoch' and not rowsecurity
          ), '[]'::jsonb),
          'rls_tables_without_policies', coalesce((
            select jsonb_agg(t.tablename order by t.tablename)
            from pg_tables t
            where t.schemaname = 'enoch'
              and not exists (
                select 1
                from pg_policies p
                where p.schemaname = t.schemaname
                  and p.tablename = t.tablename
              )
          ), '[]'::jsonb),
          'set_updated_at_search_path', coalesce((
            select to_jsonb(p.proconfig)
            from pg_proc p
            join pg_namespace n on n.oid = p.pronamespace
            where n.nspname = 'enoch' and p.proname = 'set_updated_at'
            limit 1
          ), 'null'::jsonb),
          'operator_dashboard_counts', (
            select to_jsonb(odc)
            from enoch.operator_dashboard_counts odc
          )
        );
        """,
    )

    failures: list[str] = []
    if checks["enoch_base_tables"] < 11:
        failures.append("expected at least 11 enoch base tables")
    if checks["enoch_views"] < 2:
        failures.append("expected at least 2 enoch views")
    if checks["public_base_tables"] != 0:
        failures.append("expected 0 public base tables")
    dashboard_counts = checks["operator_dashboard_counts"]
    if dashboard_counts["write_needed"] != 1:
        failures.append("expected fixture write_needed count to be 1")
    if dashboard_counts["raw_completed_no_paper_candidates"] != 2:
        failures.append("expected fixture raw completed/no-paper candidates to be 2")
    if dashboard_counts["not_writable_by_decision_gate"] != 1:
        failures.append("expected fixture decision-gate rejects to be 1")
    if dashboard_counts["publication_ready"] != 1:
        failures.append("expected fixture publication-ready count to be 1")
    if checks["rls_disabled_tables"]:
        failures.append(f"RLS disabled tables: {checks['rls_disabled_tables']}")
    if checks["rls_tables_without_policies"]:
        failures.append(f"RLS tables without policies: {checks['rls_tables_without_policies']}")
    if "search_path=enoch, pg_temp" not in (checks["set_updated_at_search_path"] or []):
        failures.append("set_updated_at must pin search_path to enoch, pg_temp")

    return {
        "ok": not failures,
        "migration_count": len(migrations),
        "migrations": [str(path.relative_to(ROOT)) for path in migrations],
        "checks": checks,
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default=os.environ.get("POSTGRES_IMAGE", DEFAULT_IMAGE))
    parser.add_argument("--keep-container", action="store_true")
    args = parser.parse_args()

    migrations_dir = ROOT / "supabase" / "migrations"
    migrations = sorted(migrations_dir.glob("*.sql"))
    if not migrations:
        raise ValidationError(f"no migrations found in {migrations_dir}")

    docker_available()
    container = f"enoch-supabase-validate-{secrets.token_hex(4)}"
    try:
        run(
            [
                "docker",
                "run",
                "--name",
                container,
                "-e",
                "POSTGRES_PASSWORD=postgres",
                "-e",
                "POSTGRES_DB=postgres",
                "-d",
                args.image,
            ]
        )
        wait_for_postgres(container)
        report = validate(container, migrations)
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0 if report["ok"] else 1
    finally:
        if args.keep_container:
            print(f"kept container: {container}", file=sys.stderr)
        else:
            run(["docker", "rm", "-f", container], check=False)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValidationError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2), file=sys.stderr)
        raise SystemExit(2)
