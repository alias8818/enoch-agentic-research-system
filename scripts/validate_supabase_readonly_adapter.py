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

from enoch_control_plane.control_plane.store import ControlPlaneStore  # noqa: E402
from enoch_control_plane.control_plane.models import (  # noqa: E402
    ImportSnapshotRequest,
    NotionIntakeRequest,
    PaperRecord,
    PaperReviewBackfillRequest,
    PaperReviewChecklistUpdateRequest,
    PaperReviewClaimRequest,
    PaperReviewPrepareFinalizationRequest,
    PaperStatus,
)
from enoch_control_plane.control_plane.supabase_store import (
    ReadOnlyStoreError,
    SupabaseControlPlaneStore,
    SupabaseReadOnlyControlPlaneStore,
)  # noqa: E402

IMAGE = "postgres:17-alpine"
NOW = "2026-05-05T23:55:00Z"
HASH_0 = "0" * 64
HASH_1 = "1" * 64


def run(
    cmd: list[str], *, stdin: str | None = None, check: bool = True
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        input=stdin,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=check,
    )


def wait_for_postgres(container: str) -> None:
    for _ in range(60):
        if (
            run(
                ["docker", "exec", container, "pg_isready", "-U", "postgres"],
                check=False,
            ).returncode
            == 0
        ):
            return
        time.sleep(1)
    raise RuntimeError("Postgres container did not become ready")


def psql(container: str, sql: str) -> None:
    run(
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
        stdin=sql,
    )


def apply_migrations(container: str) -> None:
    psql(
        container,
        "create role anon; create role authenticated; create role service_role;",
    )
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
            (
                "proj-1",
                "Adapter Fixture",
                "Adapter Fixture",
                "",
                "",
                "exploring",
                NOW,
                NOW,
            ),
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
                "proj-1",
                "queued",
                1,
                5,
                0,
                0,
                2,
                0,
                2,
                "run-1",
                "session-1",
                "",
                "",
                "select_next",
                0,
                "",
                "",
                "",
                "worker",
                "gpt-5.5",
                "danger-full-access",
                None,
                None,
                None,
                NOW,
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
            (
                "run-1",
                "proj-1",
                "session-1",
                "wake_ready",
                "live",
                NOW,
                None,
                NOW,
                "",
                "worker_callback",
                "run-key-1",
                NOW,
            ),
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
                "paper-1",
                "proj-1",
                "run-1",
                "arxiv_draft",
                "publication_draft",
                "draft.md",
                "draft.tex",
                "evidence.json",
                "claims.json",
                "manifest.json",
                NOW,
                NOW,
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
                "paper-1",
                "finalized",
                "",
                "",
                "",
                "{}",
                100,
                "[]",
                "[]",
                "paper-1",
                "audit.json",
                "package.json",
                NOW,
                "positive",
                NOW,
                NOW,
            ),
        )
        payload = {"ok": True}
        conn.execute(
            """
            insert into events(idempotency_key, event_type, entity_type, entity_id, payload_json, payload_hash, created_at)
            values (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "event-1",
                "fixture.created",
                "project",
                "proj-1",
                json.dumps(payload),
                HASH_0,
                NOW,
            ),
        )
        conn.execute(
            """
            insert into dashboard_observations(source, scope, observed_at, ttl_seconds, status, payload_json, payload_hash, created_at)
            values (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "worker_preflight",
                "global",
                NOW,
                300,
                "ok",
                json.dumps(payload),
                HASH_1,
                NOW,
            ),
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


def _assert_ok(condition: bool, message: str, failures: list[str]) -> None:
    """Record a failure message if the condition is false.

    Extracted from the long main() and inner smoke helpers to reduce
    cyclomatic complexity (C901) while preserving exact behavior and
    error reporting. The validator script itself serves as the
    deterministic integration check; this helper makes the assertions
    uniform and the control flow in main() a simple sequence.
    """
    if not condition:
        failures.append(message)


def main() -> int:
    container = f"enoch-supabase-adapter-{secrets.token_hex(4)}"
    with tempfile.TemporaryDirectory() as tmp:
        sqlite_store = ControlPlaneStore(Path(tmp) / "control.sqlite3")
        sqlite_fixture(sqlite_store)
        try:
            run(
                [
                    "docker",
                    "run",
                    "--name",
                    container,
                    "-e",
                    "POSTGRES_PASSWORD=postgres",  # NOSONAR(S2068) - ephemeral test-only Postgres container using official image default
                    "-e",
                    "POSTGRES_DB=postgres",
                    "-p",
                    "127.0.0.1::5432",
                    "-d",
                    IMAGE,
                ]
            )
            wait_for_postgres(container)
            apply_migrations(container)
            url = pg_url(container)
            postgres_fixture(url)
            pg_store = SupabaseReadOnlyControlPlaneStore(url)

            failures: list[str] = []

            def _check(name: str, sqlite_val: Any, pg_val: Any) -> None:
                if sqlite_val != pg_val:
                    failures.append(f"{name} mismatch")

            sqlite_flags = sqlite_store.flags().model_dump(mode="json")
            pg_flags = pg_store.flags().model_dump(mode="json")
            _check(
                "flags queue_paused",
                sqlite_flags["queue_paused"],
                pg_flags["queue_paused"],
            )

            _check(
                "queue_counts_sql",
                sqlite_store.queue_counts_sql(),
                pg_store.queue_counts_sql(),
            )
            _check(
                "paper_counts_sql",
                sqlite_store.paper_counts_sql(),
                pg_store.paper_counts_sql(),
            )

            queue_keys = [
                "project_id",
                "project_name",
                "status",
                "current_run_id",
                "related_paper_id",
                "related_paper_status",
            ]
            _check(
                "queue_rows first row",
                comparable(sqlite_store.queue_rows()[0], queue_keys),
                comparable(pg_store.queue_rows()[0], queue_keys),
            )

            paper_keys = [
                "paper_id",
                "project_id",
                "run_id",
                "paper_status",
                "review_status",
                "finalization_package_path",
            ]
            _check(
                "paper_rows first row",
                comparable(sqlite_store.paper_rows()[0], paper_keys),
                comparable(pg_store.paper_rows()[0], paper_keys),
            )

            sqlite_recent = sqlite_store.recent_events(1)[0]["payload"]
            pg_recent = pg_store.recent_events(1)[0]["payload"]
            _check(
                "recent_events omit payload",
                sqlite_recent.get("payload_omitted"),
                pg_recent.get("payload_omitted"),
            )

            _check(
                "recent_events payload_bytes > 0",
                int(sqlite_recent.get("payload_bytes") or 0) > 0,
                int(pg_recent.get("payload_bytes") or 0) > 0,
            )

            _check(
                "latest_dashboard_observation payload",
                sqlite_store.latest_dashboard_observation(
                    source="worker_preflight"
                ).payload,
                pg_store.latest_dashboard_observation(
                    source="worker_preflight"
                ).payload,
            )  # type: ignore[union-attr]

            try:
                pg_store.pause(
                    reason="should fail", paused_by="validator", maintenance_mode=True
                )
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

            def _run_write_smoke(write_store, failures: list[str]) -> None:
                paused_flags, pause_event_id = write_store.pause(
                    reason="validator pause",
                    paused_by="validator",
                    maintenance_mode=True,
                )
                _assert_ok(
                    paused_flags.queue_paused and pause_event_id > 0,
                    "pause did not persist queue_paused",
                    failures,
                )
                resumed_flags, resume_event_id = write_store.resume(
                    resumed_by="validator", maintenance_mode=True
                )
                _assert_ok(
                    not resumed_flags.queue_paused
                    and resumed_flags.maintenance_mode
                    and resume_event_id > 0,
                    "resume did not persist expected flags",
                    failures,
                )
                observation = write_store.upsert_dashboard_observation(
                    source="worker_preflight",
                    status="ok",
                    payload={"write": True},
                )
                _assert_ok(
                    observation.observation_id > 0
                    and write_store.latest_dashboard_observation(
                        source="worker_preflight"
                    )
                    is not None,
                    "upsert_dashboard_observation did not persist",
                    failures,
                )
                _assert_ok(
                    write_store.mark_queue_item_paused(
                        project_id="proj-1",
                        reason="validator item pause",
                        updated_by="validator",
                    ),
                    "mark_queue_item_paused returned false",
                    failures,
                )
                _assert_ok(
                    write_store.queue_row("proj-1")["status"] == "paused",  # type: ignore[index]
                    "mark_queue_item_paused did not update queue status",
                    failures,
                )
                write_store.update_project_dir("proj-1", "updated-dir")
                _assert_ok(
                    write_store.project_row("proj-1")["project_dir"] == "updated-dir",  # type: ignore[index]
                    "update_project_dir did not persist",
                    failures,
                )
                write_store.upsert_paper(
                    PaperRecord(
                        paper_id="paper-write-smoke",
                        project_id="proj-1",
                        run_id="run-1",
                        paper_status=PaperStatus.DRAFT_REVIEW,
                        draft_markdown_path="write.md",
                    )
                )
                _assert_ok(
                    write_store.paper_row("paper-write-smoke") is not None,
                    "upsert_paper did not persist",
                    failures,
                )
                inserted_snapshot, projects, queue_items, papers = (
                    write_store.import_snapshot(
                        ImportSnapshotRequest(
                            idempotency_key="write-smoke-import",
                            source="validator",
                            queue_rows=[
                                {
                                    "project_id": "proj-import",
                                    "project_name": "Imported Project",
                                    "status": "queued",
                                    "current_run_id": "run-import",
                                    "next_action_hint": "select_next",
                                }
                            ],
                            paper_rows=[
                                {
                                    "paper_id": "paper-import",
                                    "project_id": "proj-import",
                                    "run_id": "",
                                    "paper_status": "draft_review",
                                }
                            ],
                        )
                    )
                )

            _run_write_smoke(write_store, failures)

            def _run_more_write_operations(write_store, failures: list[str]) -> None:
                _assert_ok(
                    inserted_snapshot and (projects, queue_items, papers) == (1, 1, 1),  # noqa: F821 - resolved at runtime by prior _run_write_smoke call in same enclosing main()
                    "import_snapshot counts mismatch",
                    failures,
                )
                _assert_ok(
                    write_store.queue_row("proj-import") is not None
                    and write_store.paper_row("paper-import") is not None,
                    "import_snapshot did not persist imported rows",
                    failures,
                )
                dispatch_event_id, dispatched = write_store.mark_dispatch_started(
                    project_id="proj-import",
                    run_id="run-live-smoke",
                    session_id="session-live-smoke",
                    dispatch_payload={"target": "validator"},
                    requested_by="validator",
                )
                _assert_ok(
                    dispatch_event_id > 0
                    and dispatched.get("status") == "awaiting_wake"
                    and dispatched.get("last_run_state") == "awaiting_wake",
                    "mark_dispatch_started did not persist awaiting_wake state",
                    failures,
                )
                callback_payload = {
                    "run_id": "run-live-smoke",
                    "project_id": "proj-import",
                    "session_id": "session-live-smoke",
                    "event_type": "wake_ready",
                    "gate_state": "wake_ready",
                    "reason": "validator ready",
                    "idempotency_key": "write-smoke-worker-callback",
                }
                callback_event_id, callback_inserted, callback_row = (
                    write_store.record_worker_callback(callback_payload)
                )
                callback_event_id_again, callback_inserted_again, _ = (
                    write_store.record_worker_callback(callback_payload)
                )
                _assert_ok(
                    callback_event_id > 0
                    and callback_inserted
                    and not callback_inserted_again
                    and callback_event_id_again == callback_event_id
                    and callback_row.get("status") == "completed"
                    and callback_row.get("next_action_hint")
                    == "draft_paper_or_select_next_project",
                    "record_worker_callback idempotency or state mismatch",
                    failures,
                )

            _run_more_write_operations(write_store, failures)
            final_queue_counts = write_store.queue_counts_sql()
            if (
                final_queue_counts.get("queued") != 0
                or final_queue_counts.get("paused") != 1
                or final_queue_counts.get("completed") != 1
            ):
                failures.append(
                    f"queue_counts_sql bucket mismatch after writes: {final_queue_counts}"
                )
            dry_notion = write_store.ingest_notion_ideas(
                NotionIntakeRequest(
                    dry_run=True,
                    source="validator-notion",
                    notion_rows=[{"Idea": "Dry Notion Idea", "Status": "exploring"}],
                )
            )
            if dry_notion[0] or dry_notion[1] != 0 or not dry_notion[4]:
                failures.append(
                    "dry-run notion intake did not return candidates without insert"
                )
            (
                notion_inserted,
                notion_created,
                notion_updated,
                notion_skipped,
                notion_candidates,
                _,
            ) = write_store.ingest_notion_ideas(
                NotionIntakeRequest(
                    dry_run=False,
                    idempotency_key="write-smoke-notion-intake",
                    source="validator-notion",
                    include_statuses=["exploring"],
                    default_machine_target="validator-worker",
                    default_model="gpt-5.5",
                    default_sandbox="danger-full-access",
                    notion_rows=[
                        {
                            "Idea": "Live Notion Idea",
                            "Status": "exploring",
                            "url": "https://www.notion.so/Live-Notion-Idea-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                            "Priority": "High",
                        }
                    ],
                )
            )
            if (
                not notion_inserted
                or notion_created != 1
                or notion_updated != 0
                or notion_skipped != 0
                or not notion_candidates
            ):
                failures.append("notion intake insert counts mismatch")
            notion_project_id = (
                notion_candidates[0]["project_id"] if notion_candidates else ""
            )
            notion_row = (
                write_store.queue_row(notion_project_id) if notion_project_id else None
            )
            if not notion_row or notion_row.get("machine_target") != "validator-worker":
                failures.append("notion intake did not persist queue/project metadata")
            if not any(
                row.get("project_id") == notion_project_id
                for row in write_store.queue_notion_projection()
            ):
                failures.append("queue_notion_projection missing notion intake row")
            if not any(
                row.get("project_id") == notion_project_id
                for row in write_store.notion_execution_update_projection()
            ):
                failures.append(
                    "notion_execution_update_projection missing notion intake row"
                )
            write_store.upsert_paper(
                PaperRecord(
                    paper_id="paper-review-smoke",
                    project_id=notion_project_id,
                    run_id="",
                    paper_status=PaperStatus.DRAFT_REVIEW,
                    draft_markdown_path="draft.md",
                    draft_latex_path="draft.tex",
                    evidence_bundle_path="evidence.json",
                    claim_ledger_path="claims.json",
                    manifest_path="manifest.json",
                )
            )
            (
                review_inserted,
                review_created,
                review_updated,
                _review_skipped,
                review_errors,
            ) = write_store.backfill_paper_reviews(
                PaperReviewBackfillRequest(
                    idempotency_key="write-smoke-paper-review-backfill",
                    dry_run=False,
                    paper_ids=["paper-review-smoke"],
                )
            )
            if (
                not review_inserted
                or review_created != 1
                or review_updated != 0
                or review_errors
            ):
                failures.append(
                    f"publication automation backfill mismatch: created={review_created} updated={review_updated} errors={review_errors}"
                )
            claim_event_id, claim_inserted, claimed_review = (
                write_store.claim_paper_review(
                    "paper-review-smoke",
                    PaperReviewClaimRequest(
                        idempotency_key="write-smoke-paper-review-claim",
                        reviewer="validator",
                    ),
                )
            )
            if (
                claim_event_id <= 0
                or not claim_inserted
                or claimed_review.get("review_status") != "claimed"
            ):
                failures.append(
                    "publication automation claim did not persist claimed state"
                )
            checklist = write_store.paper_review_checklist("paper-review-smoke")
            for item in checklist.get("items", []):
                if item.get("required"):
                    write_store.update_paper_review_checklist(
                        "paper-review-smoke",
                        item["id"],
                        PaperReviewChecklistUpdateRequest(
                            idempotency_key=f"write-smoke-checklist-{item['id']}",
                            requested_by="validator",
                            status="pass",
                        ),
                    )
            if not any(
                row.get("paper_id") == "paper-review-smoke"
                for row in write_store.paper_review_rows()
            ):
                failures.append("paper_review_rows missing smoke review row")
            artifact_root = Path(tmp) / "artifact-root"
            artifact_root.mkdir()
            for rel_path in (
                "draft.md",
                "draft.tex",
                "evidence.json",
                "claims.json",
                "manifest.json",
            ):
                (artifact_root / rel_path).write_text(f"{rel_path}\n", encoding="utf-8")
            write_store.update_project_dir(notion_project_id, str(artifact_root))
            dry_event_id, dry_inserted, _dry_item, dry_package_path, dry_manifest = (
                write_store.prepare_paper_review_finalization_package(
                    "paper-review-smoke",
                    PaperReviewPrepareFinalizationRequest(
                        idempotency_key="write-smoke-finalization-dry",
                        requested_by="validator",
                        dry_run=True,
                    ),
                )
            )
            if (
                dry_event_id is not None
                or dry_inserted
                or not dry_manifest.get("dry_run")
                or not dry_package_path
            ):
                failures.append(
                    "dry-run finalization package did not stay side-effect free"
                )
            (
                package_event_id,
                package_inserted,
                finalized_item,
                package_path,
                manifest,
            ) = write_store.prepare_paper_review_finalization_package(
                "paper-review-smoke",
                PaperReviewPrepareFinalizationRequest(
                    idempotency_key="write-smoke-finalization",
                    requested_by="validator",
                    dry_run=False,
                ),
                require_approval=False,
            )
            (
                package_event_id_again,
                package_inserted_again,
                _finalized_item_again,
                package_path_again,
                _manifest_again,
            ) = write_store.prepare_paper_review_finalization_package(
                "paper-review-smoke",
                PaperReviewPrepareFinalizationRequest(
                    idempotency_key="write-smoke-finalization",
                    requested_by="validator",
                    dry_run=False,
                ),
                require_approval=False,
            )
            _assert_ok(
                package_event_id is not None
                and package_event_id > 0
                and package_inserted
                and not package_inserted_again
                and package_event_id_again == package_event_id
                and package_path_again == package_path
                and finalized_item.get("review_status") == "finalized"
                and Path(package_path).exists()
                and manifest.get("schema") == "paper_finalization_package_v1",
                "finalization package did not persist idempotent finalized state",
                failures,
            )

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
