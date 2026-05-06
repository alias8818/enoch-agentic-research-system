#!/usr/bin/env python3
"""Validate staged SQLite -> Supabase/Postgres backfill in an ephemeral container."""

from __future__ import annotations

import json
import secrets
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.backfill_control_plane_to_supabase import import_sqlite_to_postgres  # noqa: E402
from omx_wake_gate.control_plane.store import ControlPlaneStore  # noqa: E402

IMAGE = "postgres:17-alpine"
NOW = "2026-05-06T10:30:00Z"
HASH_0 = "0" * 64
HASH_1 = "1" * 64


def run(cmd: list[str], *, stdin: str | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, input=stdin, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=check)


def wait_for_postgres(container: str) -> None:
    for _ in range(60):
        if run(["docker", "exec", container, "pg_isready", "-U", "postgres"], check=False).returncode == 0:
            return
        time.sleep(1)
    raise RuntimeError("Postgres container did not become ready")


def psql(container: str, sql: str) -> None:
    run(["docker", "exec", "-i", container, "psql", "-U", "postgres", "-d", "postgres", "-v", "ON_ERROR_STOP=1"], stdin=sql)


def apply_migrations(container: str) -> None:
    psql(container, "create role anon; create role authenticated; create role service_role;")
    for migration in sorted((ROOT / "supabase" / "migrations").glob("*.sql")):
        psql(container, migration.read_text())


def pg_url(container: str) -> str:
    port_line = run(["docker", "port", container, "5432/tcp"]).stdout.strip()
    port = port_line.rsplit(":", 1)[-1]
    return f"postgresql://postgres:postgres@127.0.0.1:{port}/postgres"


def sqlite_fixture(path: Path) -> None:
    ControlPlaneStore(path)
    with sqlite3.connect(path) as conn:
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
            set queue_paused=1, maintenance_mode=1, pause_reason=?, paused_at=?, paused_by=?, updated_at=?
            where singleton=1
            """,
            ("paused for Supabase migration", NOW, "validator", NOW),
        )
        projects = [
            ("proj-final", "Finalized Paper"),
            ("proj-approved", "Approved For Finalization"),
            ("proj-rejected", "Rejected Paper"),
            ("proj-negative", "Negative No Paper"),
        ]
        for project_id, name in projects:
            conn.execute(
                """
                insert into projects(project_id, project_name, project_dir, notion_page_url, notion_page_id,
                  origin_idea_status, created_at, updated_at)
                values (?, ?, ?, '', '', 'exploring', ?, ?)
                """,
                (project_id, name, name, NOW, NOW),
            )
            conn.execute(
                """
                insert into queue_items(project_id, status, selection_rank, dispatch_priority, auto_continue,
                  continue_count, max_continues, retry_count, max_retries, current_run_id, current_session_id,
                  last_run_state, last_event_type, next_action_hint, manual_review_required, blocked_reason,
                  last_error, last_result_summary, machine_target, model, sandbox, last_dispatch_at,
                  last_callback_at, stale_after, updated_at)
                values (?, 'completed', 1, 5, 0, 0, 2, 0, 2, ?, 'session', '', '', '', 0, '', '', '',
                  'worker', 'gpt-5.5', 'danger-full-access', null, null, null, ?)
                """,
                (project_id, f"run-{project_id}", NOW),
            )
            conn.execute(
                """
                insert into runs(run_id, project_id, session_id, state, dispatch_mode, started_at, ended_at,
                  last_callback_at, gate_state, current_activity, idempotency_key, updated_at)
                values (?, ?, 'session', 'wake_ready', 'live', ?, ?, ?, '', 'worker_callback', ?, ?)
                """,
                (f"run-{project_id}", project_id, NOW, NOW, NOW, f"run-key-{project_id}", NOW),
            )
        paper_specs = [
            ("paper-final", "proj-final", "publication_draft", "finalized", "package.json"),
            ("paper-approved", "proj-approved", "publication_draft", "approved_for_finalization", ""),
            ("paper-rejected", "proj-rejected", "draft_review", "rejected", ""),
        ]
        for paper_id, project_id, paper_status, review_status, package_path in paper_specs:
            conn.execute(
                """
                insert into papers(paper_id, project_id, run_id, paper_type, paper_status,
                  draft_markdown_path, draft_latex_path, evidence_bundle_path, claim_ledger_path,
                  manifest_path, generated_at, updated_at)
                values (?, ?, ?, 'arxiv_draft', ?, 'draft.md', 'draft.tex', 'evidence.json', 'claims.json', 'manifest.json', ?, ?)
                """,
                (paper_id, project_id, f"run-{project_id}", paper_status, NOW, NOW),
            )
            conn.execute(
                """
                insert into paper_review_items(paper_id, review_status, reviewer, blocker, claimed_at,
                  checklist_json, rank_score, rank_reasons_json, missing_signals_json, rank_tiebreaker,
                  source_audit_path, finalization_package_path, finalized_at, decision_summary, created_at, updated_at)
                values (?, ?, '', '', '', '{}', 100, '[]', '[]', ?, 'audit.json', ?, ?, 'fixture', ?, ?)
                """,
                (paper_id, review_status, paper_id, package_path, NOW if review_status == "finalized" else "", NOW, NOW),
            )
        conn.execute(
            """
            insert into events(idempotency_key, event_type, entity_type, entity_id, payload_json, payload_hash, created_at)
            values ('event-1', 'fixture.created', 'project', 'proj-final', ?, ?, ?)
            """,
            (json.dumps({"ok": True}), HASH_0, NOW),
        )
        conn.execute(
            """
            insert into dashboard_observations(source, scope, observed_at, ttl_seconds, status, payload_json, payload_hash, created_at)
            values ('snapshot_mirror', 'global', ?, 300, 'ok', ?, ?, ?)
            """,
            (NOW, json.dumps({"ok": True}), HASH_1, NOW),
        )


def main() -> int:
    container = f"enoch-supabase-backfill-{secrets.token_hex(4)}"
    with tempfile.TemporaryDirectory() as tmp:
        sqlite_path = Path(tmp) / "control.sqlite3"
        sqlite_fixture(sqlite_path)
        try:
            run([
                "docker", "run", "--name", container, "-e", "POSTGRES_PASSWORD=postgres",
                "-e", "POSTGRES_DB=postgres", "-p", "127.0.0.1::5432", "-d", IMAGE,
            ])
            wait_for_postgres(container)
            apply_migrations(container)
            url = pg_url(container)

            dry = import_sqlite_to_postgres(sqlite_path=sqlite_path, database_url=url, apply=False, reset_target=False, observation_limit=-1)
            import psycopg
            with psycopg.connect(url) as conn:
                with conn.cursor() as cur:
                    cur.execute("set search_path to enoch, public")
                    persisted = cur.execute("select count(*) from projects").fetchone()[0]
            if persisted != 0:
                raise AssertionError(f"dry-run persisted target rows: projects={persisted}")

            applied = import_sqlite_to_postgres(sqlite_path=sqlite_path, database_url=url, apply=True, reset_target=True, observation_limit=-1)
            counts = applied["target_counts_in_transaction"]
            expected = {
                "projects": 4,
                "queue_items": 4,
                "runs": 4,
                "papers": 3,
                "publication_automation_items": 3,
                "control_events": 1,
                "operator_observations": 1,
            }
            for key, value in expected.items():
                if counts.get(key) != value:
                    raise AssertionError(f"{key} count mismatch: {counts.get(key)} != {value}")
            dashboard = applied["operator_dashboard_counts"]
            if dashboard.get("write_needed") != 0:
                raise AssertionError(f"write_needed should remain 0, got {dashboard.get('write_needed')}")
            if dashboard.get("publication_ready") != 2:
                raise AssertionError(f"publication_ready should be 2, got {dashboard.get('publication_ready')}")
            if dashboard.get("corpus_imported") != 0:
                raise AssertionError(f"corpus_imported should be 0, got {dashboard.get('corpus_imported')}")
            if dashboard.get("raw_completed_no_paper_candidates") != 1:
                raise AssertionError(
                    f"raw_completed_no_paper_candidates should be 1, got {dashboard.get('raw_completed_no_paper_candidates')}"
                )
            if dashboard.get("not_writable_by_decision_gate") != 1:
                raise AssertionError(
                    f"not_writable_by_decision_gate should be 1, got {dashboard.get('not_writable_by_decision_gate')}"
                )
            print(json.dumps({"ok": True, "dry_run_committed": dry["committed"], "applied_counts": counts, "dashboard": dashboard}, indent=2, sort_keys=True))
            return 0
        finally:
            run(["docker", "rm", "-f", container], check=False)


if __name__ == "__main__":
    raise SystemExit(main())
