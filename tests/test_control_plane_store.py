from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from enoch_control_plane.control_plane.models import (
    IdeaIntakeRequest,
    ImportSnapshotRequest,
    NotionIntakeRequest,
    PaperReviewApproveFinalizationRequest,
    PaperReviewBackfillRequest,
    PaperReviewChecklistUpdateRequest,
    PaperReviewClaimRequest,
    PaperReviewPrepareFinalizationRequest,
    PaperReviewStatusUpdateRequest,
)
from enoch_control_plane.control_plane.store import ControlPlaneStore
from enoch_control_plane.enoch_core.store import IdempotencyConflict


class ControlPlaneStoreTests(unittest.TestCase):
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
            for rel in artifact_paths.values():
                (project_dir / rel).write_text("{}" if rel.endswith(".json") else "content", encoding="utf-8")
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
            self.assertEqual(item["review_status"], "claimed")

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
