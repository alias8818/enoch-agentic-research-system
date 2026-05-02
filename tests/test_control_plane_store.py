from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from omx_wake_gate.control_plane.models import (
    ImportSnapshotRequest,
    NotionIntakeRequest,
    PaperReviewApproveFinalizationRequest,
    PaperReviewBackfillRequest,
    PaperReviewChecklistUpdateRequest,
    PaperReviewClaimRequest,
    PaperReviewPrepareFinalizationRequest,
    PaperReviewStatusUpdateRequest,
)
from omx_wake_gate.control_plane.store import ControlPlaneStore
from omx_wake_gate.enoch_core.store import IdempotencyConflict


class ControlPlaneStoreTests(unittest.TestCase):
    def test_control_plane_defaults_to_paused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ControlPlaneStore(Path(tmp) / "control.sqlite3")
            flags = store.flags()
            self.assertTrue(flags.queue_paused)
            self.assertTrue(flags.maintenance_mode)

    def test_pause_resume_records_events_and_controls_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ControlPlaneStore(Path(tmp) / "control.sqlite3")
            store.resume(resumed_by="test", maintenance_mode=False)
            self.assertFalse(store.flags().queue_paused)
            store.pause(reason="maintenance", paused_by="test", maintenance_mode=True)
            action, candidate, event_id, reason = store.dispatch_next_dry_run(requested_by="test")
            self.assertEqual(action, "paused")
            self.assertIsNone(candidate)
            self.assertIsNotNone(event_id)
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
            action, candidate, _, _ = store.dispatch_next_dry_run(requested_by="test")
            self.assertEqual(action, "dry_run_dispatch")
            self.assertEqual(candidate["project_id"], "idea-1")

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
            self.assertEqual(row["last_run_state"], "dispatch_accepted")
            self.assertEqual(row["last_error"], "")
            self.assertEqual(row["last_result_summary"], "")

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
            self.assertEqual(rows[0]["review_status"], "triage_ready")
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
            self.assertEqual(initial["review_status"], "unreviewed")
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
            self.assertEqual(refreshed["review_status"], "triage_ready")
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
            self.assertEqual(rows[0]["review_status"], "unreviewed")
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
            self.assertEqual(item["review_status"], "in_review")
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

            event_id, inserted, approved = store.approve_paper_review_finalization(paper_id, PaperReviewApproveFinalizationRequest(idempotency_key="approve-1", requested_by="alice", note="ready"))
            self.assertTrue(inserted)
            self.assertEqual(approved["review_status"], "approved_for_finalization")
            event_id_again, inserted_again, approved_again = store.approve_paper_review_finalization(paper_id, PaperReviewApproveFinalizationRequest(idempotency_key="approve-1", requested_by="alice", note="ready"))
            self.assertFalse(inserted_again)
            self.assertEqual(event_id_again, event_id)
            self.assertEqual(approved_again["review_status"], "approved_for_finalization")
            self.assertEqual(store.paper_row(paper_id)["paper_status"], "publication_draft")
            events = store.event_rows(entity_id=paper_id, limit=50)
            self.assertTrue(any(event["event_type"] == "paper_review.claimed" for event in events))
            self.assertTrue(any(event["event_type"] == "paper_review.checklist_updated" for event in events))
            self.assertTrue(any(event["event_type"] == "paper_review.approved_for_finalization" for event in events))

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
            store.approve_paper_review_finalization(paper_id, PaperReviewApproveFinalizationRequest(idempotency_key="package-approve", requested_by="alice"))

            event_id, inserted, item, package_path, manifest = store.prepare_paper_review_finalization_package(
                paper_id, PaperReviewPrepareFinalizationRequest(idempotency_key="package-dry", requested_by="alice", target_label="first-paper", dry_run=True)
            )
            self.assertIsNone(event_id)
            self.assertFalse(inserted)
            self.assertFalse(Path(package_path).exists())
            self.assertTrue(manifest["no_submission_side_effects"])
            self.assertEqual(len(manifest["artifacts"]), 5)
            self.assertTrue(all(artifact["readable"] for artifact in manifest["artifacts"]))
            self.assertEqual(item["review_status"], "approved_for_finalization")

            event_id, inserted, finalized, package_path, manifest = store.prepare_paper_review_finalization_package(
                paper_id, PaperReviewPrepareFinalizationRequest(idempotency_key="package-commit", requested_by="alice", target_label="first-paper", dry_run=False)
            )
            self.assertTrue(inserted)
            self.assertEqual(finalized["review_status"], "finalized")
            self.assertEqual(finalized["finalization_package_path"], package_path)
            self.assertTrue(Path(package_path).exists())
            self.assertEqual(store.paper_row(paper_id)["paper_status"], "publication_draft")
            event_id_again, inserted_again, finalized_again, package_path_again, _manifest_again = store.prepare_paper_review_finalization_package(
                paper_id, PaperReviewPrepareFinalizationRequest(idempotency_key="package-commit", requested_by="alice", target_label="first-paper", dry_run=False)
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
            self.assertEqual(claimed["review_status"], "in_review")
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
