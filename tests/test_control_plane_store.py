from __future__ import annotations

import json
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from enoch_control_plane.control_plane.models import (
    IdeaIntakeRequest,
    ImportSnapshotRequest,
    NotionIntakeRequest,
    PaperRecord,
    PaperReviewApproveFinalizationRequest,
    PaperReviewBackfillRequest,
    PaperReviewChecklistUpdateRequest,
    PaperReviewClaimRequest,
    PaperReviewPrepareFinalizationRequest,
    PaperReviewStatusUpdateRequest,
    PaperStatus,
)
from enoch_control_plane.control_plane.store import ControlPlaneStore
from enoch_control_plane.enoch_core.store import IdempotencyConflict


class ControlPlaneStoreTests(unittest.TestCase):

    def test_append_event_idempotency_key_conflicts_on_different_event_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ControlPlaneStore(Path(tmp) / "control.sqlite3")
            event_id, inserted = store.append_event(
                idempotency_key="same-key",
                event_type="first.event",
                entity_type="project",
                entity_id="project-1",
                payload={"same": True},
            )
            self.assertTrue(inserted)

            replay_id, replay_inserted = store.append_event(
                idempotency_key="same-key",
                event_type="first.event",
                entity_type="project",
                entity_id="project-1",
                payload={"same": True},
            )
            self.assertEqual(replay_id, event_id)
            self.assertFalse(replay_inserted)

            with self.assertRaises(IdempotencyConflict):
                store.append_event(
                    idempotency_key="same-key",
                    event_type="second.event",
                    entity_type="project",
                    entity_id="project-1",
                    payload={"same": True},
                )

            with self.assertRaises(IdempotencyConflict):
                store.append_event(
                    idempotency_key="same-key",
                    event_type="first.event",
                    entity_type="run",
                    entity_id="run-1",
                    payload={"same": True},
                )

    def test_replayed_event_id_conflicts_on_different_event_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ControlPlaneStore(Path(tmp) / "control.sqlite3")
            payload = {"same": True}
            event_id, _inserted = store.append_event(
                idempotency_key="same-key",
                event_type="first.event",
                entity_type="project",
                entity_id="project-1",
                payload=payload,
            )

            replay_id = store._replayed_event_id(  # noqa: SLF001 - focused invariant test
                "same-key",
                payload,
                event_type="first.event",
                entity_type="project",
                entity_id="project-1",
            )
            self.assertEqual(replay_id, event_id)

            with self.assertRaises(IdempotencyConflict):
                store._replayed_event_id(  # noqa: SLF001 - focused invariant test
                    "same-key",
                    payload,
                    event_type="second.event",
                    entity_type="project",
                    entity_id="project-1",
                )
            with self.assertRaises(IdempotencyConflict):
                store._replayed_event_id(  # noqa: SLF001 - focused invariant test
                    "same-key",
                    payload,
                    event_type="first.event",
                    entity_type="run",
                    entity_id="run-1",
                )
    def test_control_plane_defaults_to_paused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ControlPlaneStore(Path(tmp) / "control.sqlite3")
            flags = store.flags()
            self.assertTrue(flags.queue_paused)
            self.assertTrue(flags.maintenance_mode)

    def test_next_followup_candidate_requires_concrete_evidence_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ControlPlaneStore(Path(tmp) / "control.sqlite3")
            base = {
                "project_id": "parent",
                "project_name": "Parent",
                "status": "completed",
                "manual_review_required": False,
                "followup_recommended": True,
                "followup_title": "Medium follow-up",
                "followup_hypothesis": "The signal holds at medium scale.",
                "followup_success_threshold": "Beat the baseline.",
                "followup_stop_condition": "Stop on regression.",
                "followup_depth": 1,
                "compute_scale_blocked": False,
                "followup_launched": False,
                "updated_at": "2026-05-17T00:00:00Z",
            }

            malformed = dict(base, followup_required_evidence="metric\nablation")
            store.operator_queue_rows_sql = lambda: [malformed]  # type: ignore[method-assign]
            self.assertIsNone(store.next_followup_candidate())
            self.assertEqual(store.launch_followup_candidate(dry_run=True)["action"], "noop")

            sparse = dict(base, followup_required_evidence=["metric", ""])
            store.operator_queue_rows_sql = lambda: [sparse]  # type: ignore[method-assign]
            self.assertIsNone(store.next_followup_candidate())

            concrete = dict(base, followup_required_evidence=["metric", "ablation"])
            store.operator_queue_rows_sql = lambda: [concrete]  # type: ignore[method-assign]
            self.assertEqual(store.next_followup_candidate()["project_id"], "parent")

    def test_import_snapshot_defaults_missing_origin_status_to_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ControlPlaneStore(Path(tmp) / "control.sqlite3")
            store.import_snapshot(
                ImportSnapshotRequest(
                    idempotency_key="import-missing-origin-status",
                    queue_rows=[{
                        "project_id": "missing-status-queue",
                        "project_name": "Missing Status Queue",
                        "status": "queued",
                    }],
                    paper_rows=[{
                        "paper_id": "missing-status-paper",
                        "project_id": "missing-status-paper-project",
                        "paper_status": "draft_review",
                    }],
                )
            )

            self.assertEqual(store.project_row("missing-status-queue")["origin_idea_status"], "unknown")
            self.assertEqual(store.project_row("missing-status-paper-project")["origin_idea_status"], "unknown")

    def test_import_snapshot_row_failure_does_not_consume_idempotency_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ControlPlaneStore(Path(tmp) / "control.sqlite3")
            original_connect = store._connect
            fail_project_insert = True

            class FailingConnection:
                def __init__(self, manager):
                    self.manager = manager
                    self.conn = None

                def __enter__(self):
                    self.conn = self.manager.__enter__()
                    return self

                def __exit__(self, *args):
                    return self.manager.__exit__(*args)

                def __getattr__(self, name):
                    return getattr(self.conn, name)

                def execute(self, sql, params=()):
                    nonlocal fail_project_insert
                    if fail_project_insert and "INSERT INTO projects" in str(sql):
                        fail_project_insert = False
                        raise RuntimeError("simulated import row write failure")
                    return self.conn.execute(sql, params)

            def failing_connect():
                return FailingConnection(original_connect())

            request = ImportSnapshotRequest(
                idempotency_key="import-row-failure-retry",
                queue_rows=[{
                    "project_id": "import-retry-project",
                    "project_name": "Import Retry Project",
                    "status": "queued",
                }],
                paper_rows=[],
            )
            with unittest.mock.patch.object(store, "_connect", side_effect=failing_connect):
                with self.assertRaises(RuntimeError):
                    store.import_snapshot(request)
                inserted, projects, queue_items, papers = store.import_snapshot(request)

            self.assertTrue(inserted)
            self.assertEqual((projects, queue_items, papers), (1, 1, 0))
            self.assertIsNotNone(store.queue_row("import-retry-project"))

    def test_pause_resume_records_events_and_controls_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ControlPlaneStore(Path(tmp) / "control.sqlite3")
            store.resume(resumed_by="test", maintenance_mode=False)
            self.assertFalse(store.flags().queue_paused)
            store.pause(reason="maintenance", paused_by="test", maintenance_mode=True)
            before_events = len(store.recent_events(100))
            action, candidate, event_id, reason = store.dispatch_next_dry_run(requested_by="test")
            self.assertEqual(action, "paused")
            self.assertIsNone(candidate)
            self.assertIsNone(event_id)
            self.assertEqual(len(store.recent_events(100)), before_events)
            self.assertIn("maintenance", reason)

    def test_pause_append_failure_does_not_mutate_control_flags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ControlPlaneStore(Path(tmp) / "control.sqlite3")
            before = store.flags()

            def fail_append_event(*_args, **_kwargs):
                raise RuntimeError("simulated pause event write failure")

            with unittest.mock.patch.object(store, "_append_event_in_conn", side_effect=fail_append_event):
                with self.assertRaises(RuntimeError):
                    store.pause(reason="maintenance", paused_by="test", maintenance_mode=True)

            after = store.flags()
            self.assertEqual(after.queue_paused, before.queue_paused)
            self.assertEqual(after.maintenance_mode, before.maintenance_mode)
            self.assertEqual(after.pause_reason, before.pause_reason)

    def test_resume_append_failure_does_not_mutate_control_flags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ControlPlaneStore(Path(tmp) / "control.sqlite3")
            store.pause(reason="maintenance", paused_by="test", maintenance_mode=True)
            before = store.flags()

            def fail_append_event(*_args, **_kwargs):
                raise RuntimeError("simulated resume event write failure")

            with unittest.mock.patch.object(store, "_append_event_in_conn", side_effect=fail_append_event):
                with self.assertRaises(RuntimeError):
                    store.resume(resumed_by="test", maintenance_mode=False)

            after = store.flags()
            self.assertEqual(after.queue_paused, before.queue_paused)
            self.assertEqual(after.maintenance_mode, before.maintenance_mode)
            self.assertEqual(after.pause_reason, before.pause_reason)

    def test_import_snapshot_is_idempotent_and_selects_candidate_after_resume(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ControlPlaneStore(Path(tmp) / "control.sqlite3")
            payload = ImportSnapshotRequest(
                idempotency_key="import-1",
                queue_rows=[{
                    "project_id": "idea-1",
                    "project_name": "Good Project",
                    "project_dir": str(Path(tmp) / "idea-1"),
                    "status": "queued",
                    "dispatch_priority": 5,
                }],
                paper_rows=[],
            )
            inserted, projects, queue_items, papers = store.import_snapshot(payload)
            self.assertTrue(inserted)
            self.assertEqual((projects, queue_items, papers), (1, 1, 0))
            inserted_again, *_ = store.import_snapshot(payload)
            self.assertFalse(inserted_again)
            with self.assertRaises(IdempotencyConflict):
                store.import_snapshot(payload.model_copy(update={"queue_rows": []}))
            store.resume(resumed_by="test", maintenance_mode=False)
            before_events = len(store.recent_events(100))
            action, candidate, event_id, _ = store.dispatch_next_dry_run(requested_by="test")
            self.assertEqual(action, "dry_run_dispatch")
            self.assertEqual(candidate["project_id"], "idea-1")
            self.assertIsNone(event_id)
            self.assertEqual(len(store.recent_events(100)), before_events)

    def test_import_snapshot_idempotency_replay_does_not_rewrite_runtime_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ControlPlaneStore(Path(tmp) / "control.sqlite3")
            payload = ImportSnapshotRequest(
                idempotency_key="import-replay-no-runtime-rewrite",
                queue_rows=[{
                    "project_id": "idea-replay-runtime",
                    "project_name": "Replay Runtime",
                    "project_dir": "idea-replay-runtime",
                    "status": "queued",
                    "current_run_id": "",
                    "last_result_summary": "original import",
                }],
                paper_rows=[],
            )
            inserted, *_ = store.import_snapshot(payload)
            self.assertTrue(inserted)
            paused = store.mark_queue_item_paused(
                project_id="idea-replay-runtime",
                reason="operator pause after import",
                updated_by="test",
            )
            self.assertTrue(paused)
            before = store.queue_row("idea-replay-runtime")
            self.assertEqual(before["status"], "paused")
            self.assertEqual(before["last_result_summary"], "operator pause after import")

            inserted_again, *_ = store.import_snapshot(payload)
            after = store.queue_row("idea-replay-runtime")

            self.assertFalse(inserted_again)
            self.assertEqual(after["status"], before["status"])
            self.assertEqual(after["current_run_id"], before["current_run_id"])
            self.assertEqual(after["last_result_summary"], before["last_result_summary"])

    def test_notion_intake_replay_does_not_rewrite_queue_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ControlPlaneStore(Path(tmp) / "control.sqlite3")
            payload = NotionIntakeRequest(
                idempotency_key="notion-replay-1",
                dry_run=False,
                notion_rows=[{
                    "id": "00000000-0000-4000-8000-000000000001",
                    "property_idea": "Replay Safe Idea",
                    "property_status": "testing",
                    "property_priority": "High",
                    "url": "https://www.notion.so/Replay-Safe-Idea-00000000000040008000000000000001",
                }],
            )
            inserted, created, updated, *_ = store.ingest_notion_ideas(payload)
            self.assertTrue(inserted)
            self.assertEqual((created, updated), (1, 0))
            before = store.queue_row("00000000000040008000000000000001")

            inserted_again, created_again, updated_again, *_ = store.ingest_notion_ideas(payload)
            after = store.queue_row("00000000000040008000000000000001")

            self.assertFalse(inserted_again)
            self.assertEqual((created_again, updated_again), (0, 0))
            self.assertEqual(after, before)
            with self.assertRaises(IdempotencyConflict):
                store.ingest_notion_ideas(payload.model_copy(update={"notion_rows": []}))

    def test_notion_intake_preserves_existing_queue_routing_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ControlPlaneStore(Path(tmp) / "control.sqlite3")
            store.import_snapshot(
                ImportSnapshotRequest(
                    idempotency_key="seed-notion-preserve-routing",
                    queue_rows=[{
                        "project_id": "00000000000040008000000000000002",
                        "project_name": "Preserve Routing",
                        "project_dir": "preserve-routing",
                        "status": "queued",
                        "selection_rank": 3,
                        "dispatch_priority": 3,
                        "machine_target": "gb10.local",
                        "model": "gpt-5.5-high",
                        "sandbox": "workspace-write",
                    }],
                    paper_rows=[],
                )
            )
            before = store.queue_row("00000000000040008000000000000002")

            inserted, created, updated, *_ = store.ingest_notion_ideas(
                NotionIntakeRequest(
                    idempotency_key="notion-preserve-routing",
                    dry_run=False,
                    default_machine_target="worker.example",
                    default_model="gpt-5.5",
                    default_sandbox="danger-full-access",
                    notion_rows=[{
                        "id": "00000000-0000-4000-8000-000000000002",
                        "property_idea": "Preserve Routing",
                        "property_status": "testing",
                        "property_priority": "High",
                        "url": "https://www.notion.so/Preserve-Routing-00000000000040008000000000000002",
                    }],
                )
            )
            after = store.queue_row("00000000000040008000000000000002")

            self.assertTrue(inserted)
            self.assertEqual((created, updated), (0, 1))
            self.assertEqual(after["machine_target"], before["machine_target"])
            self.assertEqual(after["model"], before["model"])
            self.assertEqual(after["sandbox"], before["sandbox"])
            self.assertEqual(after["dispatch_priority"], 10)
            self.assertEqual(after["selection_rank"], 10)
            self.assertEqual(after["project_dir"], before["project_dir"])

    def test_supabase_native_intake_preserves_existing_source_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ControlPlaneStore(Path(tmp) / "control.sqlite3")
            project_id = "00000000000040008000000000000004"
            store.import_snapshot(
                ImportSnapshotRequest(
                    idempotency_key="seed-native-preserve-provenance",
                    queue_rows=[{
                        "project_id": project_id,
                        "project_name": "Preserve Provenance",
                        "project_dir": "preserve-provenance",
                        "status": "queued",
                        "notion_page_url": "https://source.example/preserve-provenance",
                        "notion_page_id": "source-page-id",
                    }],
                    paper_rows=[],
                )
            )
            before = store.queue_row(project_id)

            inserted, created, updated, *_ = store.ingest_ideas(
                IdeaIntakeRequest(
                    idempotency_key="native-preserve-provenance",
                    dry_run=False,
                    ideas=[{
                        "idea_id": project_id,
                        "title": "Preserve Provenance Renamed",
                        "idea_status": "exploring",
                        "priority": "High",
                    }],
                )
            )
            after = store.queue_row(project_id)

            self.assertTrue(inserted)
            self.assertEqual((created, updated), (0, 1))
            self.assertEqual(after["notion_page_url"], before["notion_page_url"])
            self.assertEqual(after["notion_page_id"], before["notion_page_id"])
            self.assertEqual(after["project_name"], "Preserve Provenance Renamed")

    def test_native_intake_row_failure_does_not_consume_idempotency_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ControlPlaneStore(Path(tmp) / "control.sqlite3")
            original_connect = store._connect
            fail_project_insert = True

            class FailingConnection:
                def __init__(self, manager):
                    self.manager = manager
                    self.conn = None

                def __enter__(self):
                    self.conn = self.manager.__enter__()
                    return self

                def __exit__(self, *args):
                    return self.manager.__exit__(*args)

                def __getattr__(self, name):
                    return getattr(self.conn, name)

                def execute(self, sql, params=()):
                    nonlocal fail_project_insert
                    if fail_project_insert and "INSERT INTO projects" in str(sql):
                        fail_project_insert = False
                        raise RuntimeError("simulated native intake project write failure")
                    return self.conn.execute(sql, params)

            request = IdeaIntakeRequest(
                idempotency_key="native-intake-atomic-key",
                dry_run=False,
                ideas=[{
                    "idea_id": "native-intake-atomic",
                    "title": "Native Intake Atomic",
                    "idea_status": "testing",
                }],
            )
            with unittest.mock.patch.object(store, "_connect", side_effect=lambda: FailingConnection(original_connect())):
                with self.assertRaises(RuntimeError):
                    store.ingest_ideas(request)
                inserted, created, updated, skipped, _candidates, skipped_rows = store.ingest_ideas(request)

            self.assertTrue(inserted)
            self.assertEqual((created, updated, skipped), (1, 0, 0))
            self.assertEqual(skipped_rows, [])
            self.assertIsNotNone(store.queue_row("native-intake-atomic"))

    def test_legacy_notion_reingest_preserves_runtime_project_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ControlPlaneStore(Path(tmp) / "control.sqlite3")
            project_id = "00000000000040008000000000000005"
            store.import_snapshot(
                ImportSnapshotRequest(
                    idempotency_key="seed-notion-preserve-project-dir",
                    queue_rows=[{
                        "project_id": project_id,
                        "project_name": "Preserve Project Dir",
                        "project_dir": "/runtime/projects/preserve-project-dir",
                        "status": "queued",
                    }],
                    paper_rows=[],
                )
            )
            before = store.queue_row(project_id)

            inserted, created, updated, *_ = store.ingest_notion_ideas(
                NotionIntakeRequest(
                    idempotency_key="notion-preserve-project-dir",
                    dry_run=False,
                    notion_rows=[{
                        "id": "00000000-0000-4000-8000-000000000005",
                        "property_idea": "Preserve Project Dir From Notion",
                        "property_status": "testing",
                        "url": "https://www.notion.so/Preserve-Project-Dir-00000000000040008000000000000005",
                    }],
                )
            )
            after = store.queue_row(project_id)

            self.assertTrue(inserted)
            self.assertEqual((created, updated), (0, 1))
            self.assertEqual(after["project_dir"], before["project_dir"])
            self.assertEqual(after["notion_page_url"], "https://www.notion.so/Preserve-Project-Dir-00000000000040008000000000000005")

    def test_notion_intake_preserves_active_queue_routing_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ControlPlaneStore(Path(tmp) / "control.sqlite3")
            store.import_snapshot(
                ImportSnapshotRequest(
                    idempotency_key="seed-notion-preserve-active-routing",
                    queue_rows=[{
                        "project_id": "00000000000040008000000000000003",
                        "project_name": "Preserve Active Routing",
                        "project_dir": "preserve-active-routing",
                        "status": "running",
                        "selection_rank": 3,
                        "dispatch_priority": 3,
                        "current_run_id": "run-active",
                        "machine_target": "gb10.local",
                        "model": "gpt-5.5-high",
                        "sandbox": "workspace-write",
                    }],
                    paper_rows=[],
                )
            )
            before = store.queue_row("00000000000040008000000000000003")

            inserted, created, updated, *_ = store.ingest_notion_ideas(
                NotionIntakeRequest(
                    idempotency_key="notion-preserve-active-routing",
                    dry_run=False,
                    default_machine_target="worker.example",
                    default_model="gpt-5.5",
                    default_sandbox="danger-full-access",
                    notion_rows=[{
                        "id": "00000000-0000-4000-8000-000000000003",
                        "property_idea": "Preserve Active Routing",
                        "property_status": "testing",
                        "property_priority": "High",
                        "url": "https://www.notion.so/Preserve-Active-Routing-00000000000040008000000000000003",
                    }],
                )
            )
            after = store.queue_row("00000000000040008000000000000003")

            self.assertTrue(inserted)
            self.assertEqual((created, updated), (0, 1))
            self.assertEqual(after["status"], before["status"])
            self.assertEqual(after["current_run_id"], before["current_run_id"])
            self.assertEqual(after["machine_target"], before["machine_target"])
            self.assertEqual(after["model"], before["model"])
            self.assertEqual(after["sandbox"], before["sandbox"])
            self.assertEqual(after["dispatch_priority"], before["dispatch_priority"])
            self.assertEqual(after["selection_rank"], before["selection_rank"])

    def test_notion_intake_can_override_existing_dispatch_metadata_explicitly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ControlPlaneStore(Path(tmp) / "control.sqlite3")
            project_id = "00000000000040008000000000000003"
            store.import_snapshot(
                ImportSnapshotRequest(
                    idempotency_key="import-existing-notion-row-override",
                    queue_rows=[{
                        "project_id": project_id,
                        "project_name": "Override Notion Idea",
                        "project_dir": project_id,
                        "status": "queued",
                        "machine_target": "gb10.local",
                        "model": "gpt-5.5-high",
                        "sandbox": "workspace-write",
                    }],
                    paper_rows=[],
                )
            )

            payload = NotionIntakeRequest(
                idempotency_key="notion-override-existing-metadata",
                dry_run=False,
                default_machine_target="operator-selected",
                default_model="gpt-5.4",
                default_sandbox="danger-full-access",
                override_existing_dispatch_metadata=True,
                notion_rows=[{
                    "id": "00000000-0000-4000-8000-000000000003",
                    "property_idea": "Override Notion Idea",
                    "property_status": "testing",
                    "property_priority": "Medium",
                    "url": "https://www.notion.so/Override-Notion-Idea-00000000000040008000000000000003",
                }],
            )
            inserted, created, updated, *_ = store.ingest_notion_ideas(payload)
            row = store.queue_row(project_id)

            self.assertTrue(inserted)
            self.assertEqual((created, updated), (0, 1))
            self.assertEqual(row["dispatch_priority"], 50)
            self.assertEqual(row["machine_target"], "operator-selected")
            self.assertEqual(row["model"], "gpt-5.4")
            self.assertEqual(row["sandbox"], "danger-full-access")

    def test_import_snapshot_preserves_active_runtime_even_when_current_run_id_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ControlPlaneStore(Path(tmp) / "control.sqlite3")
            store.import_snapshot(
                ImportSnapshotRequest(
                    idempotency_key="import-active-empty-run",
                    queue_rows=[{
                        "project_id": "idea-active-empty-import",
                        "project_name": "Active Empty Import",
                        "project_dir": "idea-active-empty-import",
                        "status": "reconciling",
                        "current_run_id": "",
                        "next_action_hint": "await_callback",
                        "last_run_state": "wake_received",
                    }],
                    paper_rows=[],
                )
            )

            store.import_snapshot(
                ImportSnapshotRequest(
                    idempotency_key="import-stale-completed-over-active-empty-run",
                    queue_rows=[{
                        "project_id": "idea-active-empty-import",
                        "project_name": "Active Empty Import",
                        "project_dir": "idea-active-empty-import",
                        "status": "completed",
                        "current_run_id": "",
                        "next_action_hint": "select_next_project",
                        "last_run_state": "finalize_negative",
                    }],
                    paper_rows=[],
                )
            )

            row = store.queue_row("idea-active-empty-import")
            self.assertEqual(row["status"], "reconciling")
            self.assertEqual(row["next_action_hint"], "await_callback")
            self.assertEqual(row["last_run_state"], "wake_received")

    def test_mark_dispatch_started_clears_stale_error_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ControlPlaneStore(Path(tmp) / "control.sqlite3")
            store.import_snapshot(
                ImportSnapshotRequest(
                    idempotency_key="import-error-row",
                    queue_rows=[{
                        "project_id": "idea-1",
                        "project_name": "Retry Project",
                        "project_dir": "idea-1",
                        "status": "queued",
                        "last_error": "old dispatch failure",
                        "last_result_summary": "old dispatch failure",
                    }],
                    paper_rows=[],
                )
            )
            _, row = store.mark_dispatch_started(
                project_id="idea-1",
                run_id="run-1",
                session_id="",
                dispatch_payload={"accepted": True},
                requested_by="test",
            )
            self.assertEqual(row["status"], "awaiting_wake")
            self.assertEqual(row["last_run_state"], "awaiting_wake")
            self.assertEqual(row["last_error"], "")
            self.assertEqual(row["last_result_summary"], "")

    def test_dispatch_claim_prevents_second_dispatch_before_worker_call(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ControlPlaneStore(Path(tmp) / "control.sqlite3")
            store.import_snapshot(
                ImportSnapshotRequest(
                    idempotency_key="import-claim-row",
                    queue_rows=[{
                        "project_id": "idea-claim",
                        "project_name": "Claim Project",
                        "project_dir": "idea-claim",
                        "status": "queued",
                    }],
                    paper_rows=[],
                )
            )
            store.resume(resumed_by="test", maintenance_mode=False)

            first = store.claim_dispatch_candidate(project_id="idea-claim", run_id="run-claim-1", requested_by="pump-a")
            second = store.claim_dispatch_candidate(project_id="idea-claim", run_id="run-claim-2", requested_by="pump-b")

            self.assertIsNotNone(first)
            self.assertIsNone(second)
            row = store.queue_row("idea-claim")
            self.assertEqual(row["status"], "dispatching")
            self.assertEqual(row["current_run_id"], "run-claim-1")
            self.assertIsNone(store.next_dispatch_candidate())

            released = store.release_dispatch_claim(project_id="idea-claim", run_id="run-claim-1", reason="worker preflight failed")
            self.assertEqual(released["status"], "queued")
            self.assertEqual(released["current_run_id"], "")
            self.assertEqual(released["last_error"], "worker preflight failed")
            self.assertEqual(store.next_dispatch_candidate()["project_id"], "idea-claim")


    def test_session_started_callback_keeps_queue_item_active(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ControlPlaneStore(Path(tmp) / "control.sqlite3")
            store.import_snapshot(
                ImportSnapshotRequest(
                    idempotency_key="callback-session-started-import",
                    queue_rows=[{
                        "project_id": "idea-started",
                        "project_name": "Started Project",
                        "project_dir": "idea-started",
                        "status": "awaiting_wake",
                        "current_run_id": "run-started",
                    }],
                    paper_rows=[],
                )
            )
            store.mark_dispatch_started(
                project_id="idea-started",
                run_id="run-started",
                session_id="session-dispatched",
                dispatch_payload={"project_id": "idea-started"},
                requested_by="test",
            )
            event_id, inserted, row = store.record_worker_callback({
                "event_type": "session_started",
                "run_id": "run-started",
                "session_id": "session-started",
                "project_id": "idea-started",
                "source_event": "session-start",
                "gate_state": "running",
                "process_tracking": {},
                "telemetry": {},
                "reason": "worker accepted dispatch",
                "idempotency_key": "run-started:session_started:test",
            })
            self.assertTrue(inserted)
            self.assertIsInstance(event_id, int)
            self.assertEqual(row["status"], "running")
            self.assertEqual(row["next_action_hint"], "await_callback")
            self.assertEqual(row["last_run_state"], "running")
            self.assertFalse(row["manual_review_required"])
            run = store.run_row("run-started")
            self.assertEqual(run["state"], "running")
            self.assertIsNone(run["ended_at"])
            self.assertEqual(run["last_callback_at"], row["last_callback_at"])

    def test_dispatch_started_idempotent_replay_does_not_regress_completed_queue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ControlPlaneStore(Path(tmp) / "control.sqlite3")
            store.import_snapshot(
                ImportSnapshotRequest(
                    idempotency_key="dispatch-replay-import",
                    queue_rows=[{
                        "project_id": "idea-dispatch-replay",
                        "project_name": "Dispatch Replay",
                        "project_dir": "idea-dispatch-replay",
                        "status": "queued",
                    }],
                    paper_rows=[],
                )
            )
            dispatch_payload = {"project_id": "idea-dispatch-replay", "worker": "gb10"}
            first_event_id, first_row = store.mark_dispatch_started(
                project_id="idea-dispatch-replay",
                run_id="run-dispatch-replay",
                session_id="session-dispatch-replay",
                dispatch_payload=dispatch_payload,
                requested_by="test",
            )
            self.assertEqual(first_row["status"], "awaiting_wake")
            _callback_event_id, _inserted, completed_row = store.record_worker_callback({
                "event_type": "wake_ready",
                "run_id": "run-dispatch-replay",
                "session_id": "session-dispatch-replay",
                "project_id": "idea-dispatch-replay",
                "gate_state": "wake_ready",
                "reason": "worker ready",
                "idempotency_key": "run-dispatch-replay:wake-ready",
            })
            self.assertEqual(completed_row["status"], "completed")

            replay_event_id, replay_row = store.mark_dispatch_started(
                project_id="idea-dispatch-replay",
                run_id="run-dispatch-replay",
                session_id="session-dispatch-replay",
                dispatch_payload=dispatch_payload,
                requested_by="test",
            )

            self.assertEqual(replay_event_id, first_event_id)
            self.assertEqual(replay_row["status"], "completed")
            self.assertEqual(replay_row["last_run_state"], "wake_ready")
            self.assertEqual(replay_row["next_action_hint"], "draft_paper_or_select_next_project")

    def test_release_dispatch_claim_does_not_emit_event_when_no_claim_released(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ControlPlaneStore(Path(tmp) / "control.sqlite3")
            store.import_snapshot(
                ImportSnapshotRequest(
                    idempotency_key="release-stale-claim-import",
                    queue_rows=[{
                        "project_id": "idea-release-stale",
                        "project_name": "Release Stale Claim",
                        "project_dir": "idea-release-stale",
                        "status": "queued",
                        "current_run_id": "",
                    }],
                    paper_rows=[],
                )
            )

            row = store.release_dispatch_claim(
                project_id="idea-release-stale",
                run_id="stale-run",
                reason="stale worker preflight failure",
            )

            self.assertEqual(row["status"], "queued")
            events = store.event_rows(limit=10, entity_type="project", entity_id="idea-release-stale")
            self.assertEqual([event["event_type"] for event in events], [])

    def test_worker_callback_missing_run_id_does_not_mutate_active_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ControlPlaneStore(Path(tmp) / "control.sqlite3")
            store.import_snapshot(
                ImportSnapshotRequest(
                    idempotency_key="callback-missing-run-import",
                    queue_rows=[{
                        "project_id": "idea-active",
                        "project_name": "Active Project",
                        "project_dir": "idea-active",
                        "status": "awaiting_wake",
                        "current_run_id": "run-active",
                        "current_session_id": "session-active",
                        "next_action_hint": "await_callback",
                    }],
                    paper_rows=[],
                )
            )

            event_id, inserted, row = store.record_worker_callback({
                "project_id": "idea-active",
                "event_type": "",
                "reason": "malformed callback without run id",
            })

            self.assertTrue(inserted)
            self.assertIsInstance(event_id, int)
            self.assertEqual(row["status"], "awaiting_wake")
            self.assertEqual(row["current_run_id"], "run-active")
            self.assertEqual(row["next_action_hint"], "await_callback")
            event = store.event_rows(limit=1, entity_type="run", entity_id="idea-active")[0]
            self.assertEqual(event["payload"]["stale_callback_ignored"], True)
            self.assertEqual(event["payload"]["ignore_reason"], "missing_run_id_for_active_project")

    def test_worker_callback_missing_run_id_does_not_mutate_active_project_with_empty_current_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ControlPlaneStore(Path(tmp) / "control.sqlite3")
            store.import_snapshot(
                ImportSnapshotRequest(
                    idempotency_key="callback-missing-run-empty-current-import",
                    queue_rows=[{
                        "project_id": "idea-active-empty",
                        "project_name": "Active Project Empty Current",
                        "project_dir": "idea-active-empty",
                        "status": "awaiting_wake",
                        "current_run_id": "",
                        "current_session_id": "session-active",
                        "next_action_hint": "await_callback",
                    }],
                    paper_rows=[],
                )
            )

            event_id, inserted, row = store.record_worker_callback({
                "project_id": "idea-active-empty",
                "event_type": "wake_ready",
                "reason": "project-only callback without run id",
            })

            self.assertTrue(inserted)
            self.assertIsInstance(event_id, int)
            self.assertEqual(row["status"], "awaiting_wake")
            self.assertEqual(row["current_run_id"], "")
            self.assertEqual(row["next_action_hint"], "await_callback")
            event = store.event_rows(limit=1, entity_type="run", entity_id="idea-active-empty")[0]
            self.assertEqual(event["payload"]["stale_callback_ignored"], True)
            self.assertEqual(event["payload"]["ignore_reason"], "missing_run_id_for_active_project")

    def test_worker_callback_missing_run_id_does_not_complete_queued_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ControlPlaneStore(Path(tmp) / "control.sqlite3")
            store.import_snapshot(
                ImportSnapshotRequest(
                    idempotency_key="callback-missing-run-queued-import",
                    queue_rows=[{
                        "project_id": "idea-queued-project-only",
                        "project_name": "Queued Project Only",
                        "project_dir": "idea-queued-project-only",
                        "status": "queued",
                        "current_run_id": "",
                        "next_action_hint": "controller_review",
                    }],
                    paper_rows=[],
                )
            )

            event_id, inserted, row = store.record_worker_callback({
                "project_id": "idea-queued-project-only",
                "event_type": "wake_ready",
                "reason": "project-only callback without run id",
            })

            self.assertTrue(inserted)
            self.assertIsInstance(event_id, int)
            self.assertEqual(row["status"], "queued")
            self.assertEqual(row["current_run_id"], "")
            self.assertEqual(row["next_action_hint"], "controller_review")
            event = store.event_rows(limit=1, entity_type="run", entity_id="idea-queued-project-only")[0]
            self.assertEqual(event["payload"]["stale_callback_ignored"], True)
            self.assertEqual(event["payload"]["ignore_reason"], "missing_run_id_for_project_callback")

    def test_stale_worker_callback_replay_stays_idempotent_after_current_run_completes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ControlPlaneStore(Path(tmp) / "control.sqlite3")
            store.import_snapshot(
                ImportSnapshotRequest(
                    idempotency_key="callback-stale-replay-import",
                    queue_rows=[{
                        "project_id": "idea-stale-replay",
                        "project_name": "Stale Replay",
                        "project_dir": "idea-stale-replay",
                        "status": "awaiting_wake",
                        "current_run_id": "run-current",
                        "current_session_id": "session-current",
                        "next_action_hint": "await_callback",
                    }],
                    paper_rows=[],
                )
            )

            stale_callback = {
                "project_id": "idea-stale-replay",
                "run_id": "run-old",
                "session_id": "session-old",
                "event_type": "wake_ready",
                "reason": "old worker retry",
                "idempotency_key": "stale-replay-key",
            }
            first_event_id, first_inserted, first_row = store.record_worker_callback(stale_callback)
            self.assertTrue(first_inserted)
            self.assertEqual(first_row["status"], "awaiting_wake")

            store.record_worker_callback({
                "project_id": "idea-stale-replay",
                "run_id": "run-current",
                "session_id": "session-current",
                "event_type": "wake_ready",
                "reason": "current worker ready",
                "idempotency_key": "current-ready-key",
            })

            second_event_id, second_inserted, second_row = store.record_worker_callback(stale_callback)

            self.assertEqual(second_event_id, first_event_id)
            self.assertFalse(second_inserted)
            self.assertEqual(second_row["status"], "completed")
            events = store.event_rows(limit=10, entity_type="run", entity_id="run-old")
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["payload"]["stale_callback_ignored"], True)


    def test_worker_callback_idempotency_rejects_payload_subset_reuse(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ControlPlaneStore(Path(tmp) / "control.sqlite3")
            store.import_snapshot(
                ImportSnapshotRequest(
                    idempotency_key="callback-subset-reuse-import",
                    queue_rows=[{
                        "project_id": "idea-subset-reuse",
                        "project_name": "Subset Reuse",
                        "project_dir": "idea-subset-reuse",
                        "status": "awaiting_wake",
                        "current_run_id": "run-subset-reuse",
                    }],
                    paper_rows=[],
                )
            )
            original = {
                "event_type": "wake_ready",
                "run_id": "run-subset-reuse",
                "session_id": "session-subset-reuse",
                "project_id": "idea-subset-reuse",
                "gate_state": "wake_ready",
                "reason": "original worker ready",
                "telemetry": {"exit_code": 0},
                "idempotency_key": "subset-reuse-key",
            }
            event_id, inserted, _row = store.record_worker_callback(original)
            self.assertTrue(inserted)
            self.assertIsInstance(event_id, int)

            subset = {
                "event_type": "wake_ready",
                "run_id": "run-subset-reuse",
                "session_id": "session-subset-reuse",
                "project_id": "idea-subset-reuse",
                "idempotency_key": "subset-reuse-key",
            }

            with self.assertRaises(IdempotencyConflict):
                store.record_worker_callback(subset)


    def test_mark_queue_item_paused_append_failure_does_not_mutate_queue_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ControlPlaneStore(Path(tmp) / "control.sqlite3")
            project_id = "idea-pause-item-atomic"
            store.import_snapshot(
                ImportSnapshotRequest(
                    idempotency_key="pause-item-atomic-import",
                    queue_rows=[{
                        "project_id": project_id,
                        "project_name": "Pause Item Atomic",
                        "project_dir": "pause-item-atomic",
                        "status": "queued",
                    }],
                    paper_rows=[],
                )
            )
            before = store.queue_row(project_id)

            def fail_append_event(*_args, **_kwargs):
                raise RuntimeError("simulated queue pause event write failure")

            with unittest.mock.patch.object(store, "_append_event_in_conn", side_effect=fail_append_event):
                with self.assertRaises(RuntimeError):
                    store.mark_queue_item_paused(project_id=project_id, reason="operator pause", updated_by="test")

            after = store.queue_row(project_id)
            self.assertEqual(after["status"], before["status"])
            self.assertEqual(after["next_action_hint"], before["next_action_hint"])
            self.assertEqual(after["last_result_summary"], before["last_result_summary"])

    def test_dispatch_claim_idempotent_replay_does_not_reclaim_released_queue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ControlPlaneStore(Path(tmp) / "control.sqlite3")
            project_id = "idea-claim-replay"
            run_id = "run-claim-replay"
            store.import_snapshot(
                ImportSnapshotRequest(
                    idempotency_key="claim-replay-import",
                    queue_rows=[{
                        "project_id": project_id,
                        "project_name": "Claim Replay",
                        "project_dir": "claim-replay",
                        "status": "queued",
                    }],
                    paper_rows=[],
                )
            )
            claimed = store.claim_dispatch_candidate(project_id=project_id, run_id=run_id, requested_by="test")
            self.assertIsNotNone(claimed)
            released = store.release_dispatch_claim(project_id=project_id, run_id=run_id, reason="worker preflight failed")
            self.assertEqual(released["status"], "queued")
            before = store.queue_row(project_id)

            replay = store.claim_dispatch_candidate(project_id=project_id, run_id=run_id, requested_by="test")
            after = store.queue_row(project_id)

            self.assertIsNone(replay)
            self.assertEqual(after["status"], before["status"])
            self.assertEqual(after["current_run_id"], before["current_run_id"])
            self.assertEqual(after["next_action_hint"], before["next_action_hint"])
            events = store.event_rows(limit=10, entity_type="project", entity_id=project_id)
            self.assertEqual(
                [event["event_type"] for event in events].count("controller.dispatch_claimed"),
                1,
            )

    def test_dispatch_claim_append_failure_does_not_mutate_queue_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ControlPlaneStore(Path(tmp) / "control.sqlite3")
            project_id = "idea-claim-atomic"
            store.import_snapshot(
                ImportSnapshotRequest(
                    idempotency_key="claim-atomic-import",
                    queue_rows=[{
                        "project_id": project_id,
                        "project_name": "Claim Atomic",
                        "project_dir": "claim-atomic",
                        "status": "queued",
                    }],
                    paper_rows=[],
                )
            )
            before = store.queue_row(project_id)

            def fail_append_event(*_args, **_kwargs):
                raise RuntimeError("simulated claim event write failure")

            with unittest.mock.patch.object(store, "_append_event_in_conn", side_effect=fail_append_event):
                with self.assertRaises(RuntimeError):
                    store.claim_dispatch_candidate(project_id=project_id, run_id="run-claim-atomic", requested_by="test")

            after = store.queue_row(project_id)
            self.assertEqual(after["status"], before["status"])
            self.assertEqual(after["current_run_id"], before["current_run_id"])
            self.assertEqual(after["next_action_hint"], before["next_action_hint"])

    def test_dispatch_claim_release_append_failure_does_not_mutate_queue_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ControlPlaneStore(Path(tmp) / "control.sqlite3")
            project_id = "idea-release-atomic"
            run_id = "run-release-atomic"
            store.import_snapshot(
                ImportSnapshotRequest(
                    idempotency_key="release-atomic-import",
                    queue_rows=[{
                        "project_id": project_id,
                        "project_name": "Release Atomic",
                        "project_dir": "release-atomic",
                        "status": "queued",
                    }],
                    paper_rows=[],
                )
            )
            claimed = store.claim_dispatch_candidate(project_id=project_id, run_id=run_id, requested_by="test")
            self.assertIsNotNone(claimed)
            before = store.queue_row(project_id)

            def fail_append_event(*_args, **_kwargs):
                raise RuntimeError("simulated release event write failure")

            with unittest.mock.patch.object(store, "_append_event_in_conn", side_effect=fail_append_event):
                with self.assertRaises(RuntimeError):
                    store.release_dispatch_claim(project_id=project_id, run_id=run_id, reason="worker preflight failed")

            after = store.queue_row(project_id)
            self.assertEqual(after["status"], before["status"])
            self.assertEqual(after["current_run_id"], before["current_run_id"])
            self.assertEqual(after["next_action_hint"], before["next_action_hint"])

    def test_mark_dispatch_started_append_failure_does_not_mutate_runtime_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ControlPlaneStore(Path(tmp) / "control.sqlite3")
            project_id = "idea-dispatch-atomic"
            run_id = "run-dispatch-atomic"
            store.import_snapshot(
                ImportSnapshotRequest(
                    idempotency_key="dispatch-atomic-import",
                    queue_rows=[{
                        "project_id": project_id,
                        "project_name": "Dispatch Atomic",
                        "project_dir": "dispatch-atomic",
                        "status": "queued",
                    }],
                    paper_rows=[],
                )
            )
            before_queue = store.queue_row(project_id)
            before_run = store.run_row(run_id)

            def fail_append_event(*_args, **_kwargs):
                raise RuntimeError("simulated dispatch event write failure")

            with unittest.mock.patch.object(store, "_append_event_in_conn", side_effect=fail_append_event):
                with self.assertRaises(RuntimeError):
                    store.mark_dispatch_started(
                        project_id=project_id,
                        run_id=run_id,
                        session_id="session-after",
                        dispatch_payload={"project_id": project_id},
                        requested_by="test",
                    )

            after_queue = store.queue_row(project_id)
            after_run = store.run_row(run_id)
            self.assertEqual(after_queue["status"], before_queue["status"])
            self.assertEqual(after_queue["current_run_id"], before_queue["current_run_id"])
            self.assertEqual(after_queue["current_session_id"], before_queue["current_session_id"])
            self.assertEqual(after_queue["last_run_state"], before_queue["last_run_state"])
            self.assertIsNone(before_run)
            self.assertIsNone(after_run)

    def test_worker_callback_append_failure_does_not_mutate_runtime_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ControlPlaneStore(Path(tmp) / "control.sqlite3")
            project_id = "idea-callback-atomic"
            run_id = "run-callback-atomic"
            store.import_snapshot(
                ImportSnapshotRequest(
                    idempotency_key="callback-atomic-import",
                    queue_rows=[{
                        "project_id": project_id,
                        "project_name": "Callback Atomic",
                        "project_dir": "callback-atomic",
                        "status": "queued",
                    }],
                    paper_rows=[],
                )
            )
            store.mark_dispatch_started(
                project_id=project_id,
                run_id=run_id,
                session_id="session-before",
                dispatch_payload={"project_id": project_id},
                requested_by="test",
            )
            before_queue = store.queue_row(project_id)
            before_run = store.run_row(run_id)

            def fail_append_event(*_args, **_kwargs):
                raise RuntimeError("simulated event write failure")

            callback = {
                "event_type": "wake_ready",
                "run_id": run_id,
                "session_id": "session-after",
                "project_id": project_id,
                "gate_state": "wake_ready",
                "reason": "worker ready",
                "idempotency_key": "callback-atomic-key",
            }
            with unittest.mock.patch.object(store, "_append_event_in_conn", side_effect=fail_append_event):
                with self.assertRaises(RuntimeError):
                    store.record_worker_callback(callback)

            after_queue = store.queue_row(project_id)
            after_run = store.run_row(run_id)
            self.assertEqual(after_queue["status"], before_queue["status"])
            self.assertEqual(after_queue["current_session_id"], before_queue["current_session_id"])
            self.assertEqual(after_queue["last_run_state"], before_queue["last_run_state"])
            self.assertEqual(after_queue["next_action_hint"], before_queue["next_action_hint"])
            self.assertEqual(after_run["state"], before_run["state"])
            self.assertEqual(after_run["session_id"], before_run["session_id"])
            self.assertEqual(after_run["gate_state"], before_run["gate_state"])

    def test_launch_followup_append_failure_does_not_queue_followup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ControlPlaneStore(Path(tmp) / "control.sqlite3")
            parent_id = "parent-followup-atomic"
            candidate = {
                "project_id": parent_id,
                "project_name": "Parent Followup Atomic",
                "status": "completed",
                "manual_review_required": False,
                "followup_recommended": True,
                "followup_title": "Atomic Followup Branch",
                "followup_hypothesis": "The signal survives a branch test.",
                "followup_required_evidence": ["direct metric", "ablation"],
                "followup_success_threshold": "Beat the baseline.",
                "followup_stop_condition": "Stop on regression.",
                "followup_depth": 1,
                "compute_scale_blocked": False,
                "followup_launched": False,
                "selection_rank": 42,
                "dispatch_priority": 42,
                "updated_at": "2026-05-17T00:00:00Z",
            }
            store.operator_queue_rows_sql = lambda: [candidate]  # type: ignore[method-assign]
            dry_run = store.launch_followup_candidate(dry_run=True)
            followup_id = dry_run["followup"]["idea_id"]

            def fail_append_event(*_args, **_kwargs):
                raise RuntimeError("simulated follow-up event write failure")

            with unittest.mock.patch.object(store, "_append_event_in_conn", side_effect=fail_append_event):
                with self.assertRaises(RuntimeError):
                    store.launch_followup_candidate(dry_run=False, requested_by="test")

            self.assertIsNone(store.project_row(followup_id))
            self.assertIsNone(store.queue_row(followup_id))

    def test_worker_callback_without_idempotency_key_replays_by_run_event_and_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ControlPlaneStore(Path(tmp) / "control.sqlite3")
            store.import_snapshot(
                ImportSnapshotRequest(
                    idempotency_key="callback-missing-idempotency-import",
                    queue_rows=[{
                        "project_id": "idea-missing-idempotency",
                        "project_name": "Missing Idempotency",
                        "project_dir": "idea-missing-idempotency",
                        "status": "awaiting_wake",
                        "current_run_id": "run-missing-idempotency",
                    }],
                    paper_rows=[],
                )
            )
            store.mark_dispatch_started(
                project_id="idea-missing-idempotency",
                run_id="run-missing-idempotency",
                session_id="session-dispatched",
                dispatch_payload={"project_id": "idea-missing-idempotency"},
                requested_by="test",
            )
            callback = {
                "event_type": "wake_ready",
                "run_id": "run-missing-idempotency",
                "session_id": "session-missing-idempotency",
                "project_id": "idea-missing-idempotency",
                "source_event": "wake-ready",
                "gate_state": "wake_ready",
                "reason": "worker ready",
            }

            first_event_id, first_inserted, first_row = store.record_worker_callback(callback)
            second_event_id, second_inserted, second_row = store.record_worker_callback(callback)

            self.assertEqual(first_event_id, second_event_id)
            self.assertTrue(first_inserted)
            self.assertFalse(second_inserted)
            self.assertEqual(second_row, first_row)
            self.assertEqual(len(store.event_rows(limit=10, entity_type="run", entity_id="run-missing-idempotency")), 1)

            changed_callback = {**callback, "reason": "worker ready after retry"}
            third_event_id, third_inserted, _third_row = store.record_worker_callback(changed_callback)
            self.assertNotEqual(third_event_id, first_event_id)
            self.assertTrue(third_inserted)
            self.assertEqual(len(store.event_rows(limit=10, entity_type="run", entity_id="run-missing-idempotency")), 2)

    def test_worker_callback_without_identifiers_dedupes_by_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ControlPlaneStore(Path(tmp) / "control.sqlite3")
            callback = {
                "source_event": "malformed-worker-callback",
                "reason": "missing worker identifiers",
                "telemetry": {"exit_code": 0},
            }

            first_event_id, first_inserted, _first_row = store.record_worker_callback(callback)
            second_event_id, second_inserted, _second_row = store.record_worker_callback(callback)

            self.assertEqual(first_event_id, second_event_id)
            self.assertTrue(first_inserted)
            self.assertFalse(second_inserted)
            self.assertEqual(len(store.event_rows(limit=10, entity_type="run", entity_id="unknown")), 1)


    def test_upsert_paper_preserves_existing_review_row(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ControlPlaneStore(Path(tmp) / "control.sqlite3")
            paper_id = "paper-upsert-preserve-review:run-1:arxiv_draft"
            store.import_snapshot(
                ImportSnapshotRequest(
                    idempotency_key="paper-upsert-preserve-review-import",
                    paper_rows=[{
                        "paper_id": paper_id,
                        "project_id": "paper-upsert-preserve-review",
                        "project_name": "Paper Upsert Preserve Review",
                        "run_id": "run-1",
                        "paper_status": "publication_draft",
                        "draft_markdown_path": "papers/run-1/original.md",
                        "draft_latex_path": "papers/run-1/original.tex",
                        "evidence_bundle_path": "papers/run-1/evidence.json",
                        "claim_ledger_path": "papers/run-1/claims.json",
                        "manifest_path": "papers/run-1/manifest.json",
                    }],
                )
            )
            inserted, created, _updated, _skipped, errors = store.backfill_paper_reviews(
                PaperReviewBackfillRequest(
                    idempotency_key="paper-upsert-preserve-review-backfill",
                    dry_run=False,
                )
            )
            self.assertTrue(inserted)
            self.assertEqual(created, 1)
            self.assertEqual(errors, [])
            self.assertIsNotNone(store.paper_review_row(paper_id))

            store.upsert_paper(
                PaperRecord(
                    paper_id=paper_id,
                    project_id="paper-upsert-preserve-review",
                    run_id="run-1",
                    paper_status=PaperStatus.PUBLICATION_DRAFT,
                    draft_markdown_path="papers/run-1/rewritten.md",
                    draft_latex_path="papers/run-1/rewritten.tex",
                    evidence_bundle_path="papers/run-1/evidence.json",
                    claim_ledger_path="papers/run-1/claims.json",
                    manifest_path="papers/run-1/manifest.json",
                )
            )

            paper = store.paper_row(paper_id)
            self.assertEqual(paper["draft_markdown_path"], "papers/run-1/rewritten.md")
            self.assertIsNotNone(store.paper_review_row(paper_id))


    def test_unknown_worker_callback_requires_manual_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ControlPlaneStore(Path(tmp) / "control.sqlite3")
            store.import_snapshot(
                ImportSnapshotRequest(
                    idempotency_key="callback-unknown-import",
                    queue_rows=[{
                        "project_id": "idea-unknown-callback",
                        "project_name": "Unknown Callback Project",
                        "project_dir": "idea-unknown-callback",
                        "status": "awaiting_wake",
                        "current_run_id": "run-unknown-callback",
                    }],
                    paper_rows=[],
                )
            )
            store.mark_dispatch_started(
                project_id="idea-unknown-callback",
                run_id="run-unknown-callback",
                session_id="session-dispatched",
                dispatch_payload={"project_id": "idea-unknown-callback"},
                requested_by="test",
            )
            _event_id, inserted, row = store.record_worker_callback({
                "event_type": "surprise_ready",
                "run_id": "run-unknown-callback",
                "session_id": "session-unknown-callback",
                "project_id": "idea-unknown-callback",
                "source_event": "test",
                "gate_state": "surprise_ready",
                "process_tracking": {},
                "telemetry": {},
                "reason": "unexpected worker callback",
                "idempotency_key": "run-unknown-callback:surprise_ready:test",
            })
            self.assertTrue(inserted)
            self.assertEqual(row["status"], "needs_review")
            self.assertEqual(row["next_action_hint"], "inspect_unknown_worker_callback")
            self.assertTrue(row["manual_review_required"])
            self.assertIn("unexpected worker callback", row["last_error"])
            self.assertEqual(row["last_run_state"], "needs_review")
            run = store.run_row("run-unknown-callback")
            self.assertEqual(run["state"], "needs_review")
            self.assertEqual(run["gate_state"], "needs_review")

    def test_dashboard_observations_store_latest_by_source_and_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ControlPlaneStore(Path(tmp) / "control.sqlite3")
            first = store.upsert_dashboard_observation(
                source="worker_preflight",
                scope="global",
                observed_at="2026-04-28T16:00:00+00:00",
                ttl_seconds=60,
                status="warn",
                payload={"ok": False},
            )
            second = store.upsert_dashboard_observation(
                source="worker_preflight",
                scope="global",
                observed_at="2026-04-28T16:01:00+00:00",
                ttl_seconds=300,
                status="ok",
                payload={"ok": True},
            )
            self.assertNotEqual(first.observation_id, second.observation_id)
            latest = store.latest_dashboard_observation(source="worker_preflight")
            self.assertIsNotNone(latest)
            self.assertEqual(latest.status, "ok")
            self.assertEqual(latest.payload, {"ok": True})
            self.assertEqual(store.latest_dashboard_observations()["worker_preflight"].observation_id, second.observation_id)

    def test_dashboard_observations_latest_prefers_observed_at_over_insert_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ControlPlaneStore(Path(tmp) / "control.sqlite3")
            newest = store.upsert_dashboard_observation(
                source="worker_preflight",
                observed_at="2026-04-28T16:05:00+00:00",
                payload={"fresh": True},
            )
            store.upsert_dashboard_observation(
                source="worker_preflight",
                observed_at="2026-04-28T16:00:00+00:00",
                payload={"fresh": False},
            )
            self.assertEqual(store.latest_dashboard_observations()["worker_preflight"].observation_id, newest.observation_id)

    def test_imports_raw_wake_gate_snapshots_and_builds_notion_projections(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ControlPlaneStore(Path(tmp) / "control.sqlite3")
            payload = ImportSnapshotRequest(
                idempotency_key="import-snapshot-files",
                queue_snapshot={
                    "active_rows": [{
                        "project_id": "idea-active",
                        "project_name": "Active Legacy Row",
                        "queue_status": "awaiting_wake",
                        "current_run_id": "run-active",
                        "current_session_id": "session-active",
                        "next_action_hint": "await_callback",
                        "last_run_state": "dispatch_accepted",
                        "last_event_type": "resume_current",
                        "last_execution_update": "2026-04-28T14:33:35.005Z",
                    }],
                    "blocked_rows": [{
                        "project_id": "idea-blocked",
                        "project_name": "Blocked Legacy Row",
                        "queue_status": "blocked",
                        "blocked_reason": "external evidence required",
                    }],
                },
                paper_snapshot={
                    "latest_rows": [{
                        "paper_id": "idea-active:run-active:arxiv_draft",
                        "project_id": "idea-active",
                        "run_id": "run-active",
                        "paper_status": "draft_review",
                        "paper_type": "arxiv_draft",
                        "draft_markdown_path": "papers/run-active/paper.md",
                    }]
                },
            )
            inserted, projects, queue_items, papers = store.import_snapshot(payload)
            self.assertTrue(inserted)
            self.assertEqual((projects, queue_items, papers), (2, 2, 1))
            self.assertEqual(store.status_counts()["awaiting_wake"], 1)
            self.assertEqual(store.status_counts()["blocked"], 1)
            queue_projection = {row["project_id"]: row for row in store.queue_notion_projection()}
            self.assertEqual(queue_projection["idea-active"]["queue_status"], "awaiting_wake")
            paper_projection = store.paper_notion_projection()
            self.assertEqual(paper_projection[0]["project_name"], "Active Legacy Row")
            exported = store.export_snapshot()
            self.assertEqual(len(exported["queue_rows"]), 2)
            self.assertEqual(len(exported["paper_rows"]), 1)
            self.assertTrue(store.mark_queue_item_paused(project_id="idea-active", reason="verified no live process", updated_by="test"))
            self.assertEqual(store.status_counts()["paused"], 1)
            self.assertFalse(store.active_items())

    def test_paper_review_backfill_is_idempotent_and_ranks_publication_drafts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ControlPlaneStore(Path(tmp) / "control.sqlite3")
            audit_path = Path(tmp) / "audit.json"
            store.import_snapshot(
                ImportSnapshotRequest(
                    idempotency_key="paper-review-import",
                    queue_rows=[
                        {"project_id": "pub", "project_name": "Publication Project", "status": "completed"},
                        {"project_id": "draft", "project_name": "Draft Project", "status": "completed"},
                    ],
                    paper_rows=[
                        {
                            "paper_id": "pub:run-1:arxiv_draft",
                            "project_id": "pub",
                            "run_id": "run-1",
                            "paper_status": "publication_draft",
                            "draft_markdown_path": "paper.md",
                            "draft_latex_path": "paper.tex",
                            "evidence_bundle_path": "evidence.json",
                            "claim_ledger_path": "claims.json",
                            "manifest_path": "manifest.json",
                            "updated_at": "2026-04-28T10:00:00+00:00",
                        },
                        {
                            "paper_id": "draft:run-1:arxiv_draft",
                            "project_id": "draft",
                            "run_id": "run-1",
                            "paper_status": "draft_review",
                            "draft_markdown_path": "paper.md",
                            "draft_latex_path": "paper.tex",
                            "evidence_bundle_path": "evidence.json",
                            "claim_ledger_path": "claims.json",
                            "manifest_path": "manifest.json",
                            "updated_at": "2026-04-28T11:00:00+00:00",
                        },
                    ],
                )
            )
            audit_path.write_text('{"papers":[{"paper_id":"pub:run-1:arxiv_draft","ready":true},{"paper_id":"draft:run-1:arxiv_draft","ready":true}]}', encoding="utf-8")
            dry_inserted, dry_created, _, dry_skipped, dry_errors = store.backfill_paper_reviews(
                PaperReviewBackfillRequest(idempotency_key="review-backfill-1", source_audit_path=str(audit_path), dry_run=True)
            )
            self.assertFalse(dry_inserted)
            self.assertEqual((dry_created, dry_skipped, dry_errors), (2, 0, []))
            inserted, created, updated, skipped, errors = store.backfill_paper_reviews(
                PaperReviewBackfillRequest(idempotency_key="review-backfill-1", source_audit_path=str(audit_path), dry_run=False)
            )
            self.assertTrue(inserted)
            self.assertEqual((created, updated, skipped, errors), (2, 0, 0, []))
            inserted_again, created_again, updated_again, skipped_again, errors_again = store.backfill_paper_reviews(
                PaperReviewBackfillRequest(idempotency_key="review-backfill-2", source_audit_path=str(audit_path), dry_run=False)
            )
            self.assertTrue(inserted_again)
            self.assertEqual((created_again, updated_again, skipped_again, errors_again), (0, 0, 2, []))
            rows = store.paper_review_rows()
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["paper_id"], "pub:run-1:arxiv_draft")
            self.assertEqual(rows[0]["review_status"], "queued")
            self.assertIn("readiness audit passed +20", rows[0]["rank_reasons"])
            self.assertEqual(rows[0]["checklist_progress"]["pending"], 9)

    def test_paper_review_backfill_upserts_stale_ranking_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ControlPlaneStore(Path(tmp) / "control.sqlite3")
            audit_path = Path(tmp) / "audit.json"
            paper_id = "stale:run-1:arxiv_draft"
            store.import_snapshot(
                ImportSnapshotRequest(
                    idempotency_key="paper-review-stale-import-1",
                    paper_rows=[{
                        "paper_id": paper_id,
                        "project_id": "stale",
                        "run_id": "run-1",
                        "paper_status": "draft_review",
                        "draft_markdown_path": "paper.md",
                        "draft_latex_path": "paper.tex",
                        "evidence_bundle_path": "evidence.json",
                        "claim_ledger_path": "claims.json",
                        "manifest_path": "manifest.json",
                        "updated_at": "2026-04-28T10:00:00+00:00",
                    }],
                )
            )
            store.backfill_paper_reviews(PaperReviewBackfillRequest(idempotency_key="review-backfill-stale-1", dry_run=False))
            initial = store.paper_review_row(paper_id)
            self.assertIsNotNone(initial)
            self.assertEqual(initial["review_status"], "queued")
            self.assertIn("readiness_audit", initial["missing_signals"])

            store.import_snapshot(
                ImportSnapshotRequest(
                    idempotency_key="paper-review-stale-import-2",
                    paper_rows=[{
                        "paper_id": paper_id,
                        "project_id": "stale",
                        "run_id": "run-1",
                        "paper_status": "publication_draft",
                        "draft_markdown_path": "paper.md",
                        "draft_latex_path": "paper.tex",
                        "evidence_bundle_path": "evidence.json",
                        "claim_ledger_path": "claims.json",
                        "manifest_path": "manifest.json",
                        "updated_at": "2026-04-28T11:00:00+00:00",
                    }],
                )
            )
            audit_path.write_text(json.dumps({"papers": [{"paper_id": paper_id, "ready": True}]}), encoding="utf-8")
            inserted, created, updated, skipped, errors = store.backfill_paper_reviews(
                PaperReviewBackfillRequest(idempotency_key="review-backfill-stale-2", source_audit_path=str(audit_path), dry_run=False)
            )
            self.assertTrue(inserted)
            self.assertEqual((created, updated, skipped, errors), (0, 1, 0, []))
            refreshed = store.paper_review_row(paper_id)
            self.assertIsNotNone(refreshed)
            self.assertEqual(refreshed["review_status"], "queued")
            self.assertEqual(refreshed["missing_signals"], [])
            self.assertGreater(refreshed["rank_score"], initial["rank_score"])

    def test_paper_review_backfill_records_missing_paths_as_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ControlPlaneStore(Path(tmp) / "control.sqlite3")
            store.import_snapshot(
                ImportSnapshotRequest(
                    idempotency_key="paper-review-missing-import",
                    paper_rows=[{
                        "paper_id": "missing:run-1:arxiv_draft",
                        "project_id": "missing",
                        "run_id": "run-1",
                        "paper_status": "draft_review",
                        "draft_markdown_path": "paper.md",
                    }],
                )
            )
            inserted, created, updated, skipped, errors = store.backfill_paper_reviews(
                PaperReviewBackfillRequest(idempotency_key="review-backfill-missing", dry_run=False)
            )
            self.assertTrue(inserted)
            self.assertEqual((created, updated, skipped), (1, 0, 0))
            self.assertEqual(len(errors), 1)
            self.assertIn("draft_latex_path", errors[0]["missing_paths"])
            rows = store.paper_review_rows()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["review_status"], "blocked")
            self.assertIn("draft_latex_path", rows[0]["missing_signals"])

    def test_paper_review_claim_checklist_status_and_approval_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ControlPlaneStore(Path(tmp) / "control.sqlite3")
            paper_id = "review:run-1:arxiv_draft"
            audit_path = Path(tmp) / "audit.json"
            audit_path.write_text(json.dumps({"papers": [{"paper_id": paper_id, "ready": True}]}), encoding="utf-8")
            store.import_snapshot(
                ImportSnapshotRequest(
                    idempotency_key="paper-review-mutation-import",
                    paper_rows=[{
                        "paper_id": paper_id,
                        "project_id": "review",
                        "run_id": "run-1",
                        "paper_status": "publication_draft",
                        "draft_markdown_path": "paper.md",
                        "draft_latex_path": "paper.tex",
                        "evidence_bundle_path": "evidence.json",
                        "claim_ledger_path": "claims.json",
                        "manifest_path": "manifest.json",
                    }],
                )
            )
            store.backfill_paper_reviews(PaperReviewBackfillRequest(idempotency_key="review-mutation-backfill", source_audit_path=str(audit_path), dry_run=False))

            event_id, inserted, item = store.claim_paper_review(paper_id, PaperReviewClaimRequest(idempotency_key="claim-1", requested_by="alice", reviewer="alice"))
            self.assertTrue(inserted)
            self.assertEqual(item["review_status"], "claimed")
            self.assertEqual(item["reviewer"], "alice")
            event_id_again, inserted_again, _ = store.claim_paper_review(paper_id, PaperReviewClaimRequest(idempotency_key="claim-1", requested_by="alice", reviewer="alice"))
            self.assertFalse(inserted_again)
            self.assertEqual(event_id_again, event_id)

            with self.assertRaises(ValueError):
                store.update_paper_review_checklist(paper_id, "artifact_readability", PaperReviewChecklistUpdateRequest(idempotency_key="checklist-fail-no-note", requested_by="alice", status="fail"))
            with self.assertRaises(ValueError):
                store.approve_paper_review_finalization(paper_id, PaperReviewApproveFinalizationRequest(idempotency_key="approve-too-soon", requested_by="alice"))

            required_items = [entry[0] for entry in (
                ("artifact_readability",), ("title_abstract_quality",), ("claim_evidence_alignment",), ("novelty_significance",),
                ("reproducibility",), ("limitations_ethics",), ("formatting_quality",), ("final_human_approval",),
            )]
            for item_id in required_items:
                store.update_paper_review_checklist(paper_id, item_id, PaperReviewChecklistUpdateRequest(idempotency_key=f"checklist-pass-{item_id}", requested_by="alice", status="pass"))
            checklist = store.paper_review_checklist(paper_id)
            self.assertEqual(checklist["progress"]["passed"], 8)
            self.assertEqual(checklist["progress"]["pending"], 1)

            with self.assertRaises(ValueError):
                store.approve_paper_review_finalization(paper_id, PaperReviewApproveFinalizationRequest(idempotency_key="approve-1", requested_by="alice", note="ready"))
            self.assertEqual(store.paper_row(paper_id)["paper_status"], "publication_draft")
            events = store.event_rows(entity_id=paper_id, limit=50)
            self.assertTrue(any(event["event_type"] == "paper_review.claimed" for event in events))
            self.assertTrue(any(event["event_type"] == "paper_review.checklist_updated" for event in events))
            self.assertFalse(any(event["event_type"] == "paper_review.approved_for_finalization" for event in events))

    def test_prepare_finalization_package_dry_run_commit_and_retry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ControlPlaneStore(Path(tmp) / "control.sqlite3")
            project_dir = Path(tmp) / "project"
            project_dir.mkdir()
            artifact_paths = {
                "draft_markdown_path": "paper.md",
                "draft_latex_path": "paper.tex",
                "evidence_bundle_path": "evidence.json",
                "claim_ledger_path": "claims.json",
                "manifest_path": "manifest.json",
            }
            (project_dir / "paper.md").write_text("Measured result improved over baseline.", encoding="utf-8")
            (project_dir / "paper.tex").write_text("content", encoding="utf-8")
            (project_dir / "evidence.json").write_text(
                json.dumps({
                    "schema_version": "evidence_bundle.v2",
                    "public_evidence_files": [{
                        "path": "evidence/run_notes.md",
                        "source_path": "run_notes.md",
                        "content": "Measured result improved over baseline.",
                        "sha256": "abc",
                    }],
                }),
                encoding="utf-8",
            )
            (project_dir / "claims.json").write_text(
                json.dumps({
                    "schema_version": "claim_ledger.v2",
                    "ledger_status": "claims_reference_evidence",
                    "claims": [{
                        "id": "C1",
                        "claim": "Measured result improved over baseline.",
                        "support_status": "supported",
                        "evidence_refs": [{"path": "evidence/run_notes.md", "source_path": "run_notes.md", "match_score": 1.0}],
                    }],
                    "unsupported_claim_count": 0,
                }),
                encoding="utf-8",
            )
            (project_dir / "manifest.json").write_text(
                json.dumps({
                    "paper_id": "package:run-1:arxiv_draft",
                    "evidence_file_count": 1,
                    "claim_count": 1,
                    "claim_ledger_status": "claims_reference_evidence",
                }),
                encoding="utf-8",
            )
            paper_id = "package:run-1:arxiv_draft"
            audit_path = Path(tmp) / "audit.json"
            audit_path.write_text(json.dumps({"papers": [{"paper_id": paper_id, "ready": True}]}), encoding="utf-8")
            store.import_snapshot(
                ImportSnapshotRequest(
                    idempotency_key="paper-review-package-import",
                    paper_rows=[{
                        "paper_id": paper_id,
                        "project_id": "package",
                        "project_name": "Package Project",
                        "project_dir": str(project_dir),
                        "run_id": "run-1",
                        "paper_status": "publication_draft",
                        **artifact_paths,
                    }],
                )
            )
            store.backfill_paper_reviews(PaperReviewBackfillRequest(idempotency_key="package-backfill", source_audit_path=str(audit_path), dry_run=False))
            _event_id, _inserted, _item = store.claim_paper_review(paper_id, PaperReviewClaimRequest(idempotency_key="package-claim", requested_by="alice", reviewer="alice"))
            for item_id in ["artifact_readability", "title_abstract_quality", "claim_evidence_alignment", "novelty_significance", "reproducibility", "limitations_ethics", "formatting_quality", "final_human_approval"]:
                store.update_paper_review_checklist(paper_id, item_id, PaperReviewChecklistUpdateRequest(idempotency_key=f"package-check-{item_id}", requested_by="alice", status="pass"))
            event_id, inserted, item, package_path, manifest = store.prepare_paper_review_finalization_package(
                paper_id, PaperReviewPrepareFinalizationRequest(idempotency_key="package-dry", requested_by="alice", target_label="first-paper", dry_run=True)
            )
            self.assertIsNone(event_id)
            self.assertFalse(inserted)
            self.assertFalse(Path(package_path).exists())
            self.assertTrue(manifest["no_submission_side_effects"])
            self.assertEqual(len(manifest["artifacts"]), 5)
            self.assertTrue(all(artifact["readable"] for artifact in manifest["artifacts"]))
            self.assertTrue(manifest["semantic_evidence_gate"]["ok"])
            self.assertEqual(item["review_status"], "claimed")

            existing_manifest = Path(package_path)
            existing_manifest.parent.mkdir(parents=True, exist_ok=True)
            existing_manifest.write_text("previous manifest", encoding="utf-8")
            with unittest.mock.patch("enoch_control_plane.control_plane.store._atomic_write_text", side_effect=OSError("simulated manifest write failure")):
                with self.assertRaises(OSError):
                    store.prepare_paper_review_finalization_package(
                        paper_id,
                        PaperReviewPrepareFinalizationRequest(idempotency_key="package-dry", requested_by="alice", target_label="first-paper", dry_run=False),
                        require_approval=False,
                    )
            self.assertEqual(existing_manifest.read_text(encoding="utf-8"), "previous manifest")
            existing_manifest.unlink()

            event_id, inserted, finalized, package_path, manifest = store.prepare_paper_review_finalization_package(
                paper_id, PaperReviewPrepareFinalizationRequest(idempotency_key="package-commit", requested_by="alice", target_label="first-paper", dry_run=False), require_approval=False
            )
            self.assertTrue(inserted)
            self.assertEqual(finalized["review_status"], "finalized")
            self.assertEqual(finalized["finalization_package_path"], package_path)
            self.assertTrue(Path(package_path).exists())
            self.assertEqual(store.paper_row(paper_id)["paper_status"], "publication_draft")
            event_id_again, inserted_again, finalized_again, package_path_again, _manifest_again = store.prepare_paper_review_finalization_package(
                paper_id, PaperReviewPrepareFinalizationRequest(idempotency_key="package-commit", requested_by="alice", target_label="first-paper", dry_run=False), require_approval=False
            )
            self.assertFalse(inserted_again)
            self.assertEqual(event_id_again, event_id)
            self.assertEqual(package_path_again, package_path)
            self.assertEqual(finalized_again["review_status"], "finalized")

    def test_prepare_finalization_package_event_failure_restores_manifest_and_review_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ControlPlaneStore(Path(tmp) / "control.sqlite3")
            project_dir = Path(tmp) / "project"
            project_dir.mkdir()
            artifact_paths = {
                "draft_markdown_path": "paper.md",
                "draft_latex_path": "paper.tex",
                "evidence_bundle_path": "evidence.json",
                "claim_ledger_path": "claims.json",
                "manifest_path": "manifest.json",
            }
            (project_dir / "paper.md").write_text("Measured result improved over baseline.", encoding="utf-8")
            (project_dir / "paper.tex").write_text("content", encoding="utf-8")
            (project_dir / "evidence.json").write_text(
                json.dumps({
                    "schema_version": "evidence_bundle.v2",
                    "public_evidence_files": [{
                        "path": "evidence/run_notes.md",
                        "source_path": "run_notes.md",
                        "content": "Measured result improved over baseline.",
                        "sha256": "abc",
                    }],
                }),
                encoding="utf-8",
            )
            (project_dir / "claims.json").write_text(
                json.dumps({
                    "schema_version": "claim_ledger.v2",
                    "ledger_status": "claims_reference_evidence",
                    "claims": [{
                        "id": "C1",
                        "claim": "Measured result improved over baseline.",
                        "support_status": "supported",
                        "evidence_refs": [{"path": "evidence/run_notes.md", "source_path": "run_notes.md", "match_score": 1.0}],
                    }],
                    "unsupported_claim_count": 0,
                }),
                encoding="utf-8",
            )
            (project_dir / "manifest.json").write_text(
                json.dumps({
                    "paper_id": "package-event-fail:run-1:arxiv_draft",
                    "evidence_file_count": 1,
                    "claim_count": 1,
                    "claim_ledger_status": "claims_reference_evidence",
                }),
                encoding="utf-8",
            )
            paper_id = "package-event-fail:run-1:arxiv_draft"
            store.import_snapshot(
                ImportSnapshotRequest(
                    idempotency_key="paper-review-package-event-fail-import",
                    paper_rows=[{
                        "paper_id": paper_id,
                        "project_id": "package-event-fail",
                        "project_name": "Package Event Fail Project",
                        "project_dir": str(project_dir),
                        "run_id": "run-1",
                        "paper_status": "publication_draft",
                        **artifact_paths,
                    }],
                )
            )
            store.backfill_paper_reviews(PaperReviewBackfillRequest(idempotency_key="package-event-fail-backfill", dry_run=False))
            store.claim_paper_review(paper_id, PaperReviewClaimRequest(idempotency_key="package-event-fail-claim", requested_by="alice", reviewer="alice"))
            package_path = store._finalization_manifest_path(paper_id, "package-event-fails")
            package_path.parent.mkdir(parents=True, exist_ok=True)
            package_path.write_text("previous manifest", encoding="utf-8")

            def fail_append_event(*_args, **_kwargs):
                raise RuntimeError("simulated finalization event write failure")

            with unittest.mock.patch.object(store, "_append_event_in_conn", side_effect=fail_append_event):
                with self.assertRaises(RuntimeError):
                    store.prepare_paper_review_finalization_package(
                        paper_id,
                        PaperReviewPrepareFinalizationRequest(idempotency_key="package-event-fails", requested_by="alice", target_label="first-paper", dry_run=False),
                        require_approval=False,
                    )

            self.assertEqual(package_path.read_text(encoding="utf-8"), "previous manifest")
            item = store.paper_review_row(paper_id) or {}
            self.assertEqual(item["review_status"], "claimed")
            self.assertEqual(item["finalization_package_path"], "")
            self.assertFalse(any(event["event_type"] == "paper_review.finalization_package_prepared" for event in store.event_rows(entity_id=paper_id, limit=50)))

    def test_prepare_finalization_package_rejects_empty_evidence_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ControlPlaneStore(Path(tmp) / "control.sqlite3")
            project_dir = Path(tmp) / "project"
            project_dir.mkdir()
            artifact_paths = {
                "draft_markdown_path": "paper.md",
                "draft_latex_path": "paper.tex",
                "evidence_bundle_path": "evidence.json",
                "claim_ledger_path": "claims.json",
                "manifest_path": "manifest.json",
            }
            for rel in artifact_paths.values():
                (project_dir / rel).write_text("{}" if rel.endswith(".json") else "content", encoding="utf-8")
            paper_id = "empty-evidence:run-1:arxiv_draft"
            store.import_snapshot(
                ImportSnapshotRequest(
                    idempotency_key="empty-evidence-import",
                    paper_rows=[{
                        "paper_id": paper_id,
                        "project_id": "empty-evidence",
                        "project_dir": str(project_dir),
                        "run_id": "run-1",
                        "paper_status": "publication_draft",
                        **artifact_paths,
                    }],
                )
            )
            store.backfill_paper_reviews(PaperReviewBackfillRequest(idempotency_key="empty-evidence-review-backfill", dry_run=False))

            with self.assertRaisesRegex(ValueError, "semantic evidence gate"):
                store.prepare_paper_review_finalization_package(
                    paper_id,
                    PaperReviewPrepareFinalizationRequest(idempotency_key="empty-evidence-finalize", requested_by="test", dry_run=False),
                    require_approval=False,
                )

    def test_prepare_finalization_package_rechecks_existing_finalized_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ControlPlaneStore(Path(tmp) / "control.sqlite3")
            project_dir = Path(tmp) / "project"
            project_dir.mkdir()
            artifact_paths = {
                "draft_markdown_path": "paper.md",
                "draft_latex_path": "paper.tex",
                "evidence_bundle_path": "evidence.json",
                "claim_ledger_path": "claims.json",
                "manifest_path": "manifest.json",
            }
            for rel in artifact_paths.values():
                (project_dir / rel).write_text("{}" if rel.endswith(".json") else "content", encoding="utf-8")
            package_path = Path(tmp) / "old-finalization.json"
            package_path.write_text('{"semantic_evidence_gate":{"ok":false}}\n', encoding="utf-8")
            paper_id = "stale-finalized:run-1:arxiv_draft"
            store.import_snapshot(
                ImportSnapshotRequest(
                    idempotency_key="stale-finalized-import",
                    paper_rows=[{
                        "paper_id": paper_id,
                        "project_id": "stale-finalized",
                        "project_dir": str(project_dir),
                        "run_id": "run-1",
                        "paper_status": "publication_draft",
                        **artifact_paths,
                    }],
                )
            )
            store.backfill_paper_reviews(PaperReviewBackfillRequest(idempotency_key="stale-finalized-review-backfill", dry_run=False))
            with store._connect() as conn:
                conn.execute(
                    "UPDATE paper_review_items SET review_status='finalized', finalization_package_path=? WHERE paper_id=?",
                    (str(package_path), paper_id),
                )

            with self.assertRaisesRegex(ValueError, "semantic evidence gate"):
                store.prepare_paper_review_finalization_package(
                    paper_id,
                    PaperReviewPrepareFinalizationRequest(idempotency_key="stale-finalized-recheck", requested_by="test", dry_run=False),
                    require_approval=False,
                )

    def test_paper_review_status_validation_blocks_invalid_transitions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ControlPlaneStore(Path(tmp) / "control.sqlite3")
            paper_id = "status:run-1:arxiv_draft"
            store.import_snapshot(
                ImportSnapshotRequest(
                    idempotency_key="paper-review-status-import",
                    paper_rows=[{
                        "paper_id": paper_id,
                        "project_id": "status",
                        "run_id": "run-1",
                        "paper_status": "draft_review",
                        "draft_markdown_path": "paper.md",
                        "draft_latex_path": "paper.tex",
                        "evidence_bundle_path": "evidence.json",
                        "claim_ledger_path": "claims.json",
                        "manifest_path": "manifest.json",
                    }],
                )
            )
            store.backfill_paper_reviews(PaperReviewBackfillRequest(idempotency_key="review-status-backfill", dry_run=False))
            with self.assertRaises(ValueError):
                store.update_paper_review_status(paper_id, PaperReviewStatusUpdateRequest(idempotency_key="bad-approval", requested_by="alice", review_status="approved_for_finalization"))
            event_id, inserted, item = store.update_paper_review_status(paper_id, PaperReviewStatusUpdateRequest(idempotency_key="block-1", requested_by="alice", review_status="blocked", blocker="venue choice required"))
            self.assertTrue(inserted)
            self.assertEqual(item["review_status"], "blocked")
            self.assertEqual(item["blocker"], "venue choice required")
            with self.assertRaises(ValueError):
                store.claim_paper_review(paper_id, PaperReviewClaimRequest(idempotency_key="claim-blocked", requested_by="alice", reviewer="alice"))
            _event_id, _inserted, claimed = store.claim_paper_review(paper_id, PaperReviewClaimRequest(idempotency_key="claim-cleared", requested_by="alice", reviewer="alice", clear_blocker=True))
            self.assertEqual(claimed["review_status"], "claimed")
            self.assertEqual(claimed["blocker"], "")

    def test_claim_paper_review_update_failure_does_not_consume_idempotency_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ControlPlaneStore(Path(tmp) / "control.sqlite3")
            paper_id = "claim-atomic:run-1:arxiv_draft"
            store.import_snapshot(
                ImportSnapshotRequest(
                    idempotency_key="claim-atomic-import",
                    paper_rows=[{
                        "paper_id": paper_id,
                        "project_id": "claim-atomic",
                        "run_id": "run-1",
                        "paper_status": "publication_draft",
                    }],
                )
            )
            store.backfill_paper_reviews(PaperReviewBackfillRequest(idempotency_key="claim-atomic-backfill", dry_run=False))
            original_connect = store._connect
            fail_review_update = True

            class FailingConnection:
                def __init__(self, manager):
                    self.manager = manager
                    self.conn = None

                def __enter__(self):
                    self.conn = self.manager.__enter__()
                    return self

                def __exit__(self, *args):
                    return self.manager.__exit__(*args)

                def __getattr__(self, name):
                    return getattr(self.conn, name)

                def execute(self, sql, params=()):
                    nonlocal fail_review_update
                    if fail_review_update and "UPDATE paper_review_items" in str(sql):
                        fail_review_update = False
                        raise RuntimeError("simulated paper review claim update failure")
                    return self.conn.execute(sql, params)

            with unittest.mock.patch.object(store, "_connect", side_effect=lambda: FailingConnection(original_connect())):
                with self.assertRaises(RuntimeError):
                    store.claim_paper_review(paper_id, PaperReviewClaimRequest(idempotency_key="claim-atomic-key", requested_by="alice", reviewer="alice"))
                event_id, inserted, item = store.claim_paper_review(paper_id, PaperReviewClaimRequest(idempotency_key="claim-atomic-key", requested_by="alice", reviewer="alice"))

            self.assertTrue(inserted)
            self.assertEqual(item["review_status"], "claimed")
            self.assertEqual(item["reviewer"], "alice")
            self.assertTrue(any(event["event_id"] == event_id and event["event_type"] == "paper_review.claimed" for event in store.event_rows(entity_id=paper_id, limit=50)))

    def test_backfill_paper_reviews_row_failure_does_not_consume_idempotency_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ControlPlaneStore(Path(tmp) / "control.sqlite3")
            paper_id = "backfill-atomic:run-1:arxiv_draft"
            store.import_snapshot(
                ImportSnapshotRequest(
                    idempotency_key="backfill-atomic-import",
                    paper_rows=[{
                        "paper_id": paper_id,
                        "project_id": "backfill-atomic",
                        "run_id": "run-1",
                        "paper_status": "publication_draft",
                        "draft_markdown_path": "paper.md",
                        "draft_latex_path": "paper.tex",
                        "evidence_bundle_path": "evidence.json",
                        "claim_ledger_path": "claims.json",
                        "manifest_path": "manifest.json",
                    }],
                )
            )
            original_connect = store._connect
            fail_review_insert = True

            class FailingConnection:
                def __init__(self, manager):
                    self.manager = manager
                    self.conn = None

                def __enter__(self):
                    self.conn = self.manager.__enter__()
                    return self

                def __exit__(self, *args):
                    return self.manager.__exit__(*args)

                def __getattr__(self, name):
                    return getattr(self.conn, name)

                def execute(self, sql, params=()):
                    nonlocal fail_review_insert
                    if fail_review_insert and "INSERT INTO paper_review_items" in str(sql):
                        fail_review_insert = False
                        raise RuntimeError("simulated paper review backfill insert failure")
                    return self.conn.execute(sql, params)

            request = PaperReviewBackfillRequest(idempotency_key="backfill-atomic-key", dry_run=False)
            with unittest.mock.patch.object(store, "_connect", side_effect=lambda: FailingConnection(original_connect())):
                with self.assertRaises(RuntimeError):
                    store.backfill_paper_reviews(request)
                inserted, created, updated, skipped, errors = store.backfill_paper_reviews(request)

            self.assertTrue(inserted)
            self.assertEqual((created, updated, skipped), (1, 0, 0))
            self.assertEqual(errors, [])
            self.assertEqual(store.paper_review_row(paper_id)["review_status"], "queued")

    def test_paper_finalization_rejects_artifacts_outside_project_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project_dir = root / "project"
            project_dir.mkdir()
            outside = root / "outside.json"
            outside.write_text("{}", encoding="utf-8")
            store = ControlPlaneStore(root / "control.sqlite3")
            paper_id = "escape:run-1:arxiv_draft"
            store.import_snapshot(
                ImportSnapshotRequest(
                    idempotency_key="paper-finalization-escape-import",
                    paper_rows=[{
                        "paper_id": paper_id,
                        "project_id": "escape",
                        "project_dir": str(project_dir),
                        "run_id": "run-1",
                        "paper_status": "draft_review",
                        "draft_markdown_path": str(outside),
                        "draft_latex_path": str(outside),
                        "evidence_bundle_path": str(outside),
                        "claim_ledger_path": str(outside),
                        "manifest_path": str(outside),
                    }],
                )
            )
            store.backfill_paper_reviews(PaperReviewBackfillRequest(idempotency_key="escape-review-backfill", dry_run=False))

            with self.assertRaisesRegex(ValueError, "readable artifacts"):
                store.prepare_paper_review_finalization_package(
                    paper_id,
                    PaperReviewPrepareFinalizationRequest(idempotency_key="escape-finalize", requested_by="test", dry_run=False),
                    require_approval=False,
                )

    def test_notion_intake_dry_run_and_commit_preserves_pause_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ControlPlaneStore(Path(tmp) / "control.sqlite3")
            payload = NotionIntakeRequest(
                idempotency_key="notion-intake-1",
                dry_run=True,
                notion_rows=[
                    {
                        "id": "00000000-0000-4000-8000-000000000001",
                        "property_idea": "Dynamic Context Window Training",
                        "property_status": "exploring",
                        "property_priority": "High",
                        "url": "https://www.notion.so/Dynamic-Context-Window-Training-00000000000040008000000000000001",
                    },
                    {"id": "discard-me", "property_idea": "Discarded", "property_status": "discarded"},
                ],
            )
            inserted, created, updated, skipped, candidates, skipped_rows = store.ingest_notion_ideas(payload)
            self.assertFalse(inserted)
            self.assertEqual((created, updated, skipped), (0, 0, 1))
            self.assertEqual(len(candidates), 1)
            self.assertEqual(candidates[0]["dispatch_priority"], 10)
            self.assertEqual(store.queue_rows(), [])

            committed = payload.model_copy(update={"dry_run": False})
            inserted, created, updated, skipped, candidates, skipped_rows = store.ingest_notion_ideas(committed)
            self.assertTrue(inserted)
            self.assertEqual((created, updated, skipped), (1, 0, 1))
            self.assertTrue(store.flags().queue_paused)
            rows = store.queue_rows()
            self.assertEqual(rows[0]["project_name"], "Dynamic Context Window Training")
            self.assertEqual(rows[0]["notion_page_id"], "00000000-0000-4000-8000-000000000001")
            updates = store.notion_execution_update_projection()
            self.assertEqual(updates[0]["page_id"], "00000000-0000-4000-8000-000000000001")
            self.assertEqual(updates[0]["properties"]["Execution State"], "queued")
            self.assertEqual(updates[0]["properties"]["Next Action"], "controller_review")



if __name__ == "__main__":
    unittest.main()


def test_control_plane_store_closes_sqlite_connections_after_context(monkeypatch) -> None:
    closed = 0

    class FakeConnection:
        row_factory = None
        def execute(self, *_args, **_kwargs):
            return self
        def executescript(self, *_args, **_kwargs):
            return self
        def fetchall(self):
            return []
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            return None
        def close(self):
            nonlocal closed
            closed += 1

    monkeypatch.setattr("enoch_control_plane.control_plane.store.sqlite3.connect", lambda *_args, **_kwargs: FakeConnection())
    ControlPlaneStore(Path("/tmp/fake-control-plane.sqlite3"))

    assert closed == 1
