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
sys.path.insert(0, str(ROOT))

from scripts.validate_state_contract import validate as validate_state_contract
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


def seed_native_ideas_backfill_fixture(container: str) -> None:
    """Seed rows that must be migrated by the native ideas migration.

    This runs immediately before the `enoch_native_ideas` migration is applied,
    after the baseline tables exist but before `enoch.ideas` exists.
    """

    psql(
        container,
        """
        insert into enoch.projects(project_id, project_name, project_dir, notion_page_id, notion_page_url, origin_idea_status)
        values
          ('fixture-project-only', 'Fixture Project Only', 'fixture-project-only', '', '', 'exploring');

        insert into enoch.queue_items(project_id, status, selection_rank, dispatch_priority, machine_target, model, sandbox)
        values
          ('fixture-project-only', 'queued', 41, 42, 'fixture-worker', 'gpt-5.5', 'danger-full-access');

        insert into enoch.control_events(
          idempotency_key, event_type, entity_type, entity_id, payload_json, payload_hash
        ) values (
          'fixture-native-ideas-backfill',
          'notion.intake',
          'snapshot',
          'notion',
          jsonb_build_object(
            'notion_rows',
            jsonb_build_array(jsonb_build_object(
              'id', 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
              'url', 'https://notion.example/Fixture-aaaaaaaaaaaa',
              'property_idea', 'Fixture Rich Idea',
              'property_status', 'testing',
              'property_priority', 'High',
              'property_category', 'spec-decoding',
              'property_description', 'rich description',
              'property_omx_project_id', 'fixture-rich-idea',
              'property_omx_machine_target', 'gb10',
              'property_omx_model', 'gpt-5.5',
              'property_omx_sandbox', 'danger-full-access',
              'property_omx_selection_rank', '7',
              'property_omx_dispatch_priority', '8'
            ))
          ),
          repeat('9', 64)
        );
        """,
    )


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
        if migration.name.endswith("_enoch_native_ideas.sql"):
            seed_native_ideas_backfill_fixture(container)
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

        insert into enoch.corpus_imports(
          paper_id, corpus_repo, artifact_slug, source_record_fingerprint, imported_at
        ) values (
          'paper-existing',
          'enoch-ai-research-corpus',
          'fixture-existing-paper',
          left(encode(extensions.digest('paper-existing', 'sha256'), 'hex'), 16),
          now()
        );

        with inserted_event as (
          insert into enoch.core_events(idempotency_key, event_type, source, payload_json, payload_hash)
          values ('fixture-core-snapshot', 'n8n.queue_snapshot', 'migration-validator', '{"ok":true}'::jsonb, 'fixture-hash')
          returning id
        )
        insert into enoch.core_snapshots(idempotency_key, snapshot_type, event_id, source, payload_json)
        select 'fixture-core-snapshot', 'n8n_queue', id, 'migration-validator',
               '{"idempotency_key":"fixture-core-snapshot","queue_rows":[{"project_id":"core-fixture"}],"paper_rows":[]}'::jsonb
        from inserted_event;

        do $$
        begin
          begin
            insert into enoch.queue_items(project_id, status, last_run_state)
            values ('fixture-invalid-last-run-state', 'queued', 'session_started');
            raise exception 'queue_items.last_run_state accepted invalid callback state';
          exception when check_violation then
            null;
          end;

          begin
            update enoch.runs set gate_state = 'surprise_ready'
            where run_id = 'run-positive';
            raise exception 'runs.gate_state accepted invalid callback state';
          exception when check_violation then
            null;
          end;
        end $$;
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
          ),
          'native_ideas_contract', (
            select jsonb_build_object(
              'idea_count', count(*),
              'rich_idea', (
                select to_jsonb(i)
                from enoch.ideas i
                where i.idea_id = 'fixture-rich-idea'
              ),
              'project_snapshot', (
                select to_jsonb(i)
                from enoch.ideas i
                where i.idea_id = 'fixture-project-only'
              ),
              'workbench_rows', (
                select count(*)
                from enoch.idea_workbench
                where idea_id in ('fixture-rich-idea', 'fixture-project-only')
              )
            )
            from enoch.ideas
          ),
          'enoch_core_contract', (
            select jsonb_build_object(
              'event_count', (select count(*) from enoch.core_events),
              'snapshot_count', (select count(*) from enoch.core_snapshots),
              'latest_project_id', (
                select payload_json #>> '{queue_rows,0,project_id}'
                from enoch.core_snapshots
                where idempotency_key = 'fixture-core-snapshot'
              )
            )
          ),
          'research_facility_contract', (
            select jsonb_build_object(
              'source_tables_present', (
                select count(*)
                from information_schema.tables
                where table_schema = 'enoch'
                  and table_name in ('research_sources', 'research_candidates', 'research_admissions', 'research_lineage')
              ),
              'workbench_present', exists (
                select 1
                from information_schema.views
                where table_schema = 'enoch'
                  and table_name = 'research_facility_workbench'
              ),
              'fresh_grounded_check', exists (
                select 1
                from pg_constraint
                where conrelid = 'enoch.research_candidates'::regclass
                  and pg_get_constraintdef(oid) like '%generation_mode <> ''fresh_grounded''%'
              ),
              'followup_parent_check', exists (
                select 1
                from pg_constraint
                where conrelid = 'enoch.research_candidates'::regclass
                  and pg_get_constraintdef(oid) like '%generation_mode <> ''followup_from_negative''%'
              ),
              'followup_source_kind_allowed', exists (
                select 1
                from pg_constraint
                where conrelid = 'enoch.research_sources'::regclass
                  and pg_get_constraintdef(oid) like '%followup_parent_run%'
              ),
              'research_synthesis_source_kind_allowed', exists (
                select 1
                from pg_constraint
                where conrelid = 'enoch.research_sources'::regclass
                  and pg_get_constraintdef(oid) like '%research_synthesis%'
              ),
              'followup_parent_relation_allowed', exists (
                select 1
                from pg_constraint
                where conrelid = 'enoch.research_lineage'::regclass
                  and pg_get_constraintdef(oid) like '%followup_parent%'
              ),
              'synthesis_candidate_statuses_allowed', exists (
                select 1
                from pg_constraint
                where conrelid = 'enoch.research_candidates'::regclass
                  and pg_get_constraintdef(oid) like '%deferred_pending_oracle%'
                  and pg_get_constraintdef(oid) like '%superseded%'
              ),
              'synthesis_relation_allowed', exists (
                select 1
                from pg_constraint
                where conrelid = 'enoch.research_lineage'::regclass
                  and pg_get_constraintdef(oid) like '%synthesized_from%'
                  and pg_get_constraintdef(oid) like '%superseded_by%'
                  and pg_get_constraintdef(oid) like '%inspired_by_success%'
              ),
              'security_invoker', coalesce((
                select (c.reloptions::text like '%security_invoker=true%')
                from pg_class c
                join pg_namespace n on n.oid = c.relnamespace
                where n.nspname = 'enoch'
                  and c.relname = 'research_facility_workbench'
              ), false)
            )
          )
        );
        """,
    )

    state_contract = validate_state_contract()
    checks["state_contract"] = state_contract

    failures: list[str] = []
    if not state_contract.get("ok"):
        failures.append(f"state contract validation failed: {state_contract.get('failures')}")
    if checks["enoch_base_tables"] < 15:
        failures.append("expected at least 15 enoch base tables including Enoch core Supabase tables")
    if checks["enoch_views"] < 3:
        failures.append("expected at least 3 enoch views including Research Facility workbench")
    if checks["public_base_tables"] != 0:
        failures.append("expected 0 public base tables")
    dashboard_counts = checks["operator_dashboard_counts"]
    if dashboard_counts["write_needed"] != 1:
        failures.append("expected fixture write_needed count to be 1")
    if dashboard_counts["raw_completed_no_paper_candidates"] != 2:
        failures.append("expected fixture raw completed/no-paper candidates to be 2")
    if dashboard_counts["not_writable_by_decision_gate"] != 1:
        failures.append("expected fixture decision-gate rejects to be 1")
    if dashboard_counts["publication_ready"] != 0:
        failures.append("expected fixture publication-ready missing-corpus count to be 0")
    if dashboard_counts["publication_ready_total"] != 1:
        failures.append("expected fixture publication-ready total count to be 1")
    if dashboard_counts["corpus_imported"] != 1:
        failures.append("expected fixture corpus-imported count to be 1")
    if checks["rls_disabled_tables"]:
        failures.append(f"RLS disabled tables: {checks['rls_disabled_tables']}")
    if checks["rls_tables_without_policies"]:
        failures.append(f"RLS tables without policies: {checks['rls_tables_without_policies']}")
    if "search_path=enoch, pg_temp" not in (checks["set_updated_at_search_path"] or []):
        failures.append("set_updated_at must pin search_path to enoch, pg_temp")
    native_ideas = checks["native_ideas_contract"]
    rich_idea = native_ideas["rich_idea"] or {}
    project_snapshot = native_ideas["project_snapshot"] or {}
    if rich_idea.get("title") != "Fixture Rich Idea":
        failures.append("native ideas migration did not backfill rich Notion payload title")
    if rich_idea.get("source_kind") != "notion_import":
        failures.append("native ideas migration did not preserve Notion import as provenance")
    if rich_idea.get("selection_rank") != 7 or rich_idea.get("dispatch_priority") != 8:
        failures.append("native ideas migration did not preserve numeric dispatch metadata")
    if project_snapshot.get("source_kind") != "project_snapshot":
        failures.append("native ideas migration did not backfill project-only rows")
    if native_ideas.get("workbench_rows") != 2:
        failures.append("idea_workbench must expose both native ideas fixture rows")
    enoch_core = checks["enoch_core_contract"] or {}
    if enoch_core.get("event_count") != 1 or enoch_core.get("snapshot_count") != 1:
        failures.append("Enoch core Supabase tables must accept one shadow event and one snapshot")
    if enoch_core.get("latest_project_id") != "core-fixture":
        failures.append("Enoch core Supabase snapshot payload did not preserve queue rows")
    research_facility = checks.get("research_facility_contract") or {}
    if research_facility.get("source_tables_present") != 4:
        failures.append("Research Facility must create all four ledgers")
    if not research_facility.get("workbench_present"):
        failures.append("Research Facility workbench view is missing")
    if not research_facility.get("fresh_grounded_check"):
        failures.append("Research Facility fresh_grounded candidates must require source evidence")
    if not research_facility.get("followup_parent_check"):
        failures.append("Research Facility followup_from_negative candidates must require parent lineage")
    if not research_facility.get("followup_source_kind_allowed"):
        failures.append("Research Facility research_sources constraint must allow followup_parent_run")
    if not research_facility.get("research_synthesis_source_kind_allowed"):
        failures.append("Research Facility research_sources constraint must allow research_synthesis")
    if not research_facility.get("followup_parent_relation_allowed"):
        failures.append("Research Facility lineage must allow followup_parent project edges")
    if not research_facility.get("synthesis_candidate_statuses_allowed"):
        failures.append("Research Facility candidates must allow synthesis deferral statuses")
    if not research_facility.get("synthesis_relation_allowed"):
        failures.append("Research Facility lineage must allow synthesis/reflection relation edges")
    if not research_facility.get("security_invoker"):
        failures.append("Research Facility workbench must use security_invoker")

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
