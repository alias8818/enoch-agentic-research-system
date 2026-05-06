#!/usr/bin/env python3
"""Validate the read-only Supabase adapter against SQLite fixtures.

This script is local-only. It starts an ephemeral Postgres container, applies the
repo migrations, writes a small fixture to both SQLite and Postgres, then checks
that the first read-only adapter methods return matching operator data.
"""

from __future__ import annotations

import json
import sys
import secrets
import sqlite3
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from omx_wake_gate.control_plane.store import ControlPlaneStore  # noqa: E402
from omx_wake_gate.control_plane.models import ImportSnapshotRequest, NotionIntakeRequest, PaperRecord, PaperStatus  # noqa: E402
from omx_wake_gate.control_plane.supabase_store import ReadOnlyStoreError, SupabaseControlPlaneStore, SupabaseReadOnlyControlPlaneStore  # noqa: E402

IMAGE = "postgres:17-alpine"
NOW = "2026-05-05T23:55:00Z"
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


def sqlite_fixture(store: ControlPlaneStore) -> None:
    with sqlite3.connect(store.path) as conn:
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
            set queue_paused = 1,
                maintenance_mode = 1,
                pause_reason = ?,
                paused_at = ?,
                paused_by = ?,
                updated_at = ?
            where singleton = 1
            """,
            ("hard cutover: LangGraph control plane not resumed", NOW, "system", NOW),
        )
        conn.execute(
            """
            insert into projects(
              project_id, project_name, project_dir, notion_page_url, notion_page_id,
              origin_idea_status, created_at, updated_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("proj-1", "Adapter Fixture", "Adapter Fixture", "", "", "exploring", NOW, NOW),
        )
        conn.execute(
            """
            insert into queue_items(
              project_id, status, selection_rank, dispatch_priority, auto_continue,
              continue_count, max_continues, retry_count, max_retries, current_run_id,
              current_session_id, last_run_state, last_event_type, next_action_hint,
              manual_review_required, blocked_reason, last_error, last_result_summary,
              machine_target, model, sandbox, last_dispatch_at, last_callback_at,
              stale_after, updated_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "proj-1", "queued", 1, 5, 0, 0, 2, 0, 2, "run-1", "session-1",
                "", "", "select_next", 0, "", "", "", "worker", "gpt-5.5",
                "danger-full-access", None, None, None, NOW,
            ),
        )
        conn.execute(
            """
            insert into runs(
              run_id, project_id, session_id, state, dispatch_mode, started_at,
              ended_at, last_callback_at, gate_state, current_activity,
              idempotency_key, updated_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("run-1", "proj-1", "session-1", "wake_ready", "live", NOW, None, NOW, "", "worker_callback", "run-key-1", NOW),
        )
        conn.execute(
            """
            insert into papers(
              paper_id, project_id, run_id, paper_type, paper_status,
              draft_markdown_path, draft_latex_path, evidence_bundle_path,
              claim_ledger_path, manifest_path, generated_at, updated_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "paper-1", "proj-1", "run-1", "arxiv_draft", "publication_draft",
                "draft.md", "draft.tex", "evidence.json", "claims.json", "manifest.json", NOW, NOW,
            ),
        )
        conn.execute(
            """
            insert into paper_review_items(
              paper_id, review_status, reviewer, blocker, claimed_at, checklist_json,
              rank_score, rank_reasons_json, missing_signals_json, rank_tiebreaker,
              source_audit_path, finalization_package_path, finalized_at,
              decision_summary, created_at, updated_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "paper-1", "finalized", "", "", "", "{}", 100, "[]", "[]", "paper-1",
                "audit.json", "package.json", NOW, "positive", NOW, NOW,
            ),
        )
        payload = {"ok": True}
        conn.execute(
            """
            insert into events(idempotency_key, event_type, entity_type, entity_id, payload_json, payload_hash, created_at)
            values (?, ?, ?, ?, ?, ?, ?)
            """,
            ("event-1", "fixture.created", "project", "proj-1", json.dumps(payload), HASH_0, NOW),
        )
        conn.execute(
            """
            insert into dashboard_observations(source, scope, observed_at, ttl_seconds, status, payload_json, payload_hash, created_at)
            values (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("worker_preflight", "global", NOW, 300, "ok", json.dumps(payload), HASH_1, NOW),
        )


def postgres_fixture(database_url: str) -> None:
    import psycopg

    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute("set search_path to enoch, public")
            cur.execute(
                """
                insert into projects(project_id, project_name, project_dir, origin_idea_status, created_at, updated_at)
                values ('proj-1', 'Adapter Fixture', 'Adapter Fixture', 'exploring', %s, %s)
                """,
                (NOW, NOW),
            )
            cur.execute(
                """
                insert into queue_items(
                  project_id, status, selection_rank, dispatch_priority, auto_continue,
                  continue_count, max_continues, retry_count, max_retries, current_run_id,
                  current_session_id, last_run_state, last_event_type, next_action_hint,
                  manual_review_required, blocked_reason, last_error, last_result_summary,
                  machine_target, model, sandbox, updated_at
                ) values ('proj-1', 'queued', 1, 5, false, 0, 2, 0, 2, 'run-1', 'session-1', '', '',
                  'select_next', false, '', '', '', 'worker', 'gpt-5.5', 'danger-full-access', %s)
                """,
                (NOW,),
            )
            cur.execute(
                """
                insert into runs(run_id, project_id, session_id, state, dispatch_mode, started_at,
                  last_callback_at, gate_state, current_activity, idempotency_key, updated_at)
                values ('run-1', 'proj-1', 'session-1', 'wake_ready', 'live', %s, %s, '', 'worker_callback', 'run-key-1', %s)
                """,
                (NOW, NOW, NOW),
            )
            cur.execute(
                """
                insert into papers(paper_id, project_id, run_id, paper_type, paper_status,
                  draft_markdown_path, draft_latex_path, evidence_bundle_path, claim_ledger_path,
                  manifest_path, generated_at, updated_at)
                values ('paper-1', 'proj-1', 'run-1', 'arxiv_draft', 'publication_draft',
                  'draft.md', 'draft.tex', 'evidence.json', 'claims.json', 'manifest.json', %s, %s)
                """,
                (NOW, NOW),
            )
            cur.execute(
                """
                insert into publication_automation_items(
                  paper_id, automation_status, checklist_json, rank_score, rank_reasons_json,
                  missing_signals_json, rank_tiebreaker, source_audit_path, finalization_package_path,
                  finalized_at, decision_summary, created_at, updated_at
                ) values ('paper-1', 'finalized', '{}'::jsonb, 100, '[]'::jsonb, '[]'::jsonb,
                  'paper-1', 'audit.json', 'package.json', %s, 'positive', %s, %s)
                """,
                (NOW, NOW, NOW),
            )
            cur.execute(
                """
                insert into control_events(idempotency_key, event_type, entity_type, entity_id, payload_json, payload_hash, created_at)
                values ('event-1', 'fixture.created', 'project', 'proj-1', %s::jsonb, %s, %s)
                """,
                (json.dumps({"ok": True}), HASH_0, NOW),
            )
            cur.execute(
                """
                insert into operator_observations(source, scope, observed_at, ttl_seconds, status, payload_json, payload_hash, created_at)
                values ('worker_preflight', 'global', %s, 300, 'ok', %s::jsonb, %s, %s)
                """,
                (NOW, json.dumps({"ok": True}), HASH_1, NOW),
            )


def comparable(row: dict[str, Any], keys: list[str]) -> dict[str, Any]:
    return {key: row.get(key) for key in keys}


def main() -> int:
    container = f"enoch-supabase-adapter-{secrets.token_hex(4)}"
    with tempfile.TemporaryDirectory() as tmp:
        sqlite_store = ControlPlaneStore(Path(tmp) / "control.sqlite3")
        sqlite_fixture(sqlite_store)
        try:
            run([
                "docker", "run", "--name", container, "-e", "POSTGRES_PASSWORD=postgres",
                "-e", "POSTGRES_DB=postgres", "-p", "127.0.0.1::5432", "-d", IMAGE,
            ])
            wait_for_postgres(container)
            apply_migrations(container)
            url = pg_url(container)
            postgres_fixture(url)
            pg_store = SupabaseReadOnlyControlPlaneStore(url)

            failures: list[str] = []
            if sqlite_store.flags().model_dump(mode="json")["queue_paused"] != pg_store.flags().model_dump(mode="json")["queue_paused"]:
                failures.append("flags queue_paused mismatch")
            if sqlite_store.queue_counts_sql() != pg_store.queue_counts_sql():
                failures.append("queue_counts_sql mismatch")
            if sqlite_store.paper_counts_sql() != pg_store.paper_counts_sql():
                failures.append("paper_counts_sql mismatch")
            queue_keys = ["project_id", "project_name", "status", "current_run_id", "related_paper_id", "related_paper_status"]
            if comparable(sqlite_store.queue_rows()[0], queue_keys) != comparable(pg_store.queue_rows()[0], queue_keys):
                failures.append("queue_rows first row mismatch")
            paper_keys = ["paper_id", "project_id", "run_id", "paper_status", "review_status", "finalization_package_path"]
            if comparable(sqlite_store.paper_rows()[0], paper_keys) != comparable(pg_store.paper_rows()[0], paper_keys):
                failures.append("paper_rows first row mismatch")
            if sqlite_store.recent_events(1)[0]["payload"] != pg_store.recent_events(1)[0]["payload"]:
                failures.append("recent_events payload mismatch")
            if sqlite_store.latest_dashboard_observation(source="worker_preflight").payload != pg_store.latest_dashboard_observation(source="worker_preflight").payload:  # type: ignore[union-attr]
                failures.append("latest_dashboard_observation payload mismatch")

            try:
                pg_store.pause(reason="should fail", paused_by="validator", maintenance_mode=True)
                failures.append("read-only store accepted pause")
            except ReadOnlyStoreError:
                pass

            write_store = SupabaseControlPlaneStore(url)
            event_id, inserted = write_store.append_event(
                idempotency_key="write-smoke-event",
                event_type="fixture.write_smoke",
                entity_type="validator",
                entity_id="write-smoke",
                payload={"ok": True},
            )
            event_id_again, inserted_again = write_store.append_event(
                idempotency_key="write-smoke-event",
                event_type="fixture.write_smoke",
                entity_type="validator",
                entity_id="write-smoke",
                payload={"ok": True},
            )
            if not inserted or inserted_again or event_id != event_id_again:
                failures.append("append_event idempotency mismatch")
            paused_flags, pause_event_id = write_store.pause(reason="validator pause", paused_by="validator", maintenance_mode=True)
            if not paused_flags.queue_paused or pause_event_id <= 0:
                failures.append("pause did not persist queue_paused")
            resumed_flags, resume_event_id = write_store.resume(resumed_by="validator", maintenance_mode=True)
            if resumed_flags.queue_paused or not resumed_flags.maintenance_mode or resume_event_id <= 0:
                failures.append("resume did not persist expected flags")
            observation = write_store.upsert_dashboard_observation(
                source="worker_preflight",
                status="ok",
                payload={"write": True},
            )
            if observation.observation_id <= 0 or write_store.latest_dashboard_observation(source="worker_preflight") is None:
                failures.append("upsert_dashboard_observation did not persist")
            if not write_store.mark_queue_item_paused(project_id="proj-1", reason="validator item pause", updated_by="validator"):
                failures.append("mark_queue_item_paused returned false")
            if write_store.queue_row("proj-1")["status"] != "paused":  # type: ignore[index]
                failures.append("mark_queue_item_paused did not update queue status")
            write_store.update_project_dir("proj-1", "updated-dir")
            if write_store.project_row("proj-1")["project_dir"] != "updated-dir":  # type: ignore[index]
                failures.append("update_project_dir did not persist")
            write_store.upsert_paper(PaperRecord(
                paper_id="paper-write-smoke",
                project_id="proj-1",
                run_id="run-1",
                paper_status=PaperStatus.DRAFT_REVIEW,
                draft_markdown_path="write.md",
            ))
            if write_store.paper_row("paper-write-smoke") is None:
                failures.append("upsert_paper did not persist")
            inserted_snapshot, projects, queue_items, papers = write_store.import_snapshot(ImportSnapshotRequest(
                idempotency_key="write-smoke-import",
                source="validator",
                queue_rows=[{
                    "project_id": "proj-import",
                    "project_name": "Imported Project",
                    "status": "queued",
                    "current_run_id": "run-import",
                    "next_action_hint": "select_next",
                }],
                paper_rows=[{
                    "paper_id": "paper-import",
                    "project_id": "proj-import",
                    "run_id": "",
                    "paper_status": "draft_review",
                }],
            ))
            if not inserted_snapshot or (projects, queue_items, papers) != (1, 1, 1):
                failures.append("import_snapshot counts mismatch")
            if write_store.queue_row("proj-import") is None or write_store.paper_row("paper-import") is None:
                failures.append("import_snapshot did not persist imported rows")
            dispatch_event_id, dispatched = write_store.mark_dispatch_started(
                project_id="proj-import",
                run_id="run-live-smoke",
                session_id="session-live-smoke",
                dispatch_payload={"target": "validator"},
                requested_by="validator",
            )
            if dispatch_event_id <= 0 or dispatched.get("status") != "awaiting_wake":
                failures.append("mark_dispatch_started did not persist awaiting_wake state")
            callback_payload = {
                "run_id": "run-live-smoke",
                "project_id": "proj-import",
                "session_id": "session-live-smoke",
                "event_type": "wake_ready",
                "gate_state": "wake_ready",
                "reason": "validator ready",
                "idempotency_key": "write-smoke-worker-callback",
            }
            callback_event_id, callback_inserted, callback_row = write_store.record_worker_callback(callback_payload)
            callback_event_id_again, callback_inserted_again, _ = write_store.record_worker_callback(callback_payload)
            if (
                callback_event_id <= 0
                or not callback_inserted
                or callback_inserted_again
                or callback_event_id_again != callback_event_id
                or callback_row.get("status") != "completed"
                or callback_row.get("next_action_hint") != "draft_paper_or_select_next_project"
            ):
                failures.append("record_worker_callback did not persist idempotent wake_ready completion")
            final_queue_counts = write_store.queue_counts_sql()
            if final_queue_counts.get("queued") != 0 or final_queue_counts.get("paused") != 1 or final_queue_counts.get("completed") != 1:
                failures.append(f"queue_counts_sql bucket mismatch after writes: {final_queue_counts}")
            dry_notion = write_store.ingest_notion_ideas(NotionIntakeRequest(
                dry_run=True,
                source="validator-notion",
                notion_rows=[{"Idea": "Dry Notion Idea", "Status": "exploring"}],
            ))
            if dry_notion[0] or dry_notion[1] != 0 or not dry_notion[4]:
                failures.append("dry-run notion intake did not return candidates without insert")
            notion_inserted, notion_created, notion_updated, notion_skipped, notion_candidates, _ = write_store.ingest_notion_ideas(NotionIntakeRequest(
                dry_run=False,
                idempotency_key="write-smoke-notion-intake",
                source="validator-notion",
                include_statuses=["exploring"],
                default_machine_target="validator-worker",
                default_model="gpt-5.5",
                default_sandbox="danger-full-access",
                notion_rows=[{
                    "Idea": "Live Notion Idea",
                    "Status": "exploring",
                    "url": "https://www.notion.so/Live-Notion-Idea-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                    "Priority": "High",
                }],
            ))
            if not notion_inserted or notion_created != 1 or notion_updated != 0 or notion_skipped != 0 or not notion_candidates:
                failures.append("notion intake insert counts mismatch")
            notion_project_id = notion_candidates[0]["project_id"] if notion_candidates else ""
            notion_row = write_store.queue_row(notion_project_id) if notion_project_id else None
            if not notion_row or notion_row.get("machine_target") != "validator-worker":
                failures.append("notion intake did not persist queue/project metadata")
            if not any(row.get("project_id") == notion_project_id for row in write_store.queue_notion_projection()):
                failures.append("queue_notion_projection missing notion intake row")
            if not any(row.get("project_id") == notion_project_id for row in write_store.notion_execution_update_projection()):
                failures.append("notion_execution_update_projection missing notion intake row")

            report: dict[str, Any] = {
                "ok": not failures,
                "failures": failures,
                "queue_counts": write_store.queue_counts_sql(),
                "paper_counts": pg_store.paper_counts_sql(),
                "queue_row": comparable(pg_store.queue_rows()[0], queue_keys),
                "paper_row": comparable(pg_store.paper_rows()[0], paper_keys),
            }
            print(json.dumps(report, indent=2, sort_keys=True))
            return 0 if not failures else 1
        finally:
            run(["docker", "rm", "-f", container], check=False)


if __name__ == "__main__":
    raise SystemExit(main())
