from __future__ import annotations

import sqlite3
import tempfile
import unittest
import json
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from enoch_control_plane.config import GateConfig
from enoch_control_plane.control_plane.read_models import OPERATOR_DETAIL_LABELS, OPERATOR_LANE_LABELS, operator_stage_for_record, paper_links, paper_source_fingerprint, queue_links, row_age_seconds
from enoch_control_plane.control_plane.state_contract import OperatorLane
from enoch_control_plane.control_plane.store import REVIEW_CHECKLIST_DEFINITION
from enoch_control_plane.control_plane.router import create_control_plane_router


TOKEN = "test-token"


def _write_decision(project_dir: Path, decision: str) -> None:
    decision_dir = project_dir / ".omx"
    decision_dir.mkdir(parents=True, exist_ok=True)
    (decision_dir / "project_decision.json").write_text(f'{{"decision":"{decision}"}}\n', encoding="utf-8")


def _write_publication_artifacts(project_dir: Path) -> None:
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "paper.md").write_text("Measured result improved over baseline.", encoding="utf-8")
    (project_dir / "paper.tex").write_text("content", encoding="utf-8")
    (project_dir / "evidence_bundle.json").write_text(
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
    (project_dir / "claim_ledger.json").write_text(
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
    (project_dir / "paper_manifest.json").write_text(
        json.dumps({
            "evidence_file_count": 1,
            "claim_count": 1,
            "claim_ledger_status": "claims_reference_evidence",
        }),
        encoding="utf-8",
    )


def _client(tmp: str) -> TestClient:
    app = FastAPI()
    root = Path(tmp) / "projects"
    root.mkdir(parents=True, exist_ok=True)
    config = GateConfig(
        state_dir=str(Path(tmp) / "state"),
        project_root=str(root),
        dispatch_script_path=str(Path(tmp) / "dispatch.sh"),
        control_api_bearer_token=TOKEN,
        completion_callback_url="http://example.invalid/callback",
        completion_callback_token="unused",
    )

    def require(auth: str | None) -> None:
        if auth != f"Bearer {TOKEN}":
            raise AssertionError("bad token")

    app.include_router(create_control_plane_router(config, require))
    return TestClient(app)


class OperatorStatusTests(unittest.TestCase):
    def test_operator_stage_translates_core_lifecycle_rows(self) -> None:
        cases = [
            ({"status": "queued"}, "ready_queue", "idea_queued", False),
            ({"status": "awaiting_wake"}, "running", "running", False),
            ({"status": "completed", "last_run_state": "wake_ready", "next_action_hint": "draft_paper_or_select_next_project"}, "complete_no_paper", "run_complete_no_paper", False),
            ({"status": "completed", "last_run_state": "session_finished_ready", "next_action_hint": "select_next_project"}, "complete_no_paper", "run_complete_no_paper", False),
            ({"status": "completed", "last_run_state": "wake_ready", "next_action_hint": "draft_paper_or_select_next_project", "decision_summary": "finalize_negative", "research_outcome": "useful_signal", "hypothesis_status": "supported", "evidence_strength": "moderate", "claim_scope": "toy baseline", "scale_limits": "local toy evidence only"}, "useful_signal", "useful_signal", False),
            ({"status": "completed", "last_run_state": "wake_ready", "next_action_hint": "draft_paper_or_select_next_project", "decision_summary": "finalize_negative", "research_outcome": "promising_if_scaled", "hypothesis_status": "supported", "evidence_strength": "moderate", "compute_scale_blocked": True, "scale_limits": "requires datacenter validation"}, "compute_scale_blocked", "compute_scale_blocked", False),
            ({"status": "completed", "last_run_state": "wake_ready", "next_action_hint": "draft_paper_or_select_next_project", "decision_summary": "finalize_negative", "followup_recommended": True, "followup_type": "deepen", "followup_title": "Adjacent test", "followup_hypothesis": "A bounded adjacent hypothesis.", "followup_required_evidence": ["baseline", "metrics"], "followup_success_threshold": "beat baseline", "followup_stop_condition": "stop on miss"}, "followup_investigation", "followup_candidate", False),
            ({"paper_id": "paper-1", "paper_status": "draft_review"}, "automate_publication", "draft_created", False),
            ({"paper_id": "paper-2", "paper_status": "publication_draft", "review_status": "finalized", "finalization_package_path": "package.json", "draft_markdown_path": "paper.md", "evidence_bundle_path": "evidence.json", "claim_ledger_path": "claims.json", "manifest_path": "manifest.json"}, "ready_to_publish", "ready_to_publish", False),
            ({"paper_id": "paper-finalized-missing-evidence", "paper_status": "publication_draft", "review_status": "finalized", "finalization_package_path": "package.json", "draft_markdown_path": "paper.md", "manifest_path": "manifest.json"}, "automate_publication", "finalization_needed", False),
            ({"paper_id": "paper-imported", "paper_status": "publication_draft", "review_status": "finalized", "finalization_package_path": "package.json", "corpus_imported": True}, "published", "published", False),
            ({"paper_id": "paper-approved", "paper_status": "publication_draft", "review_status": "approved_for_finalization"}, "automate_publication", "finalization_needed", False),
            ({"paper_id": "paper-finalized-no-package", "paper_status": "publication_draft", "review_status": "finalized"}, "automate_publication", "finalization_needed", False),
            ({"paper_id": "paper-missing-review", "paper_status": "publication_draft"}, "automate_publication", "finalization_needed", False),
            ({"paper_id": "paper-3", "paper_status": "publication_draft", "review_status": "unreviewed"}, "automate_publication", "finalization_needed", False),
            ({"status": "blocked"}, "needs_operator", "blocked_needs_operator", True),
            ({"status": "paused"}, "paused", "paused_work", False),
            ({"status": "canceled"}, "historical", "historical", False),
        ]
        for row, lane, detail_stage, attention in cases:
            with self.subTest(row=row):
                translated = operator_stage_for_record(row)
                self.assertIn(translated["operator_stage"], {item.value for item in OperatorLane})
                self.assertEqual(translated["operator_stage"], lane)
                self.assertEqual(translated["operator_lane"], lane)
                self.assertEqual(translated["operator_detail_stage"], detail_stage)
                self.assertIs(translated["operator_attention"], attention)

    def test_operator_stage_normalizes_status_like_fields(self) -> None:
        cases = [
            ({"status": "Queued"}, "ready_queue", "idea_queued"),
            ({"status": "Awaiting Wake"}, "running", "running"),
            (
                {
                    "status": "Completed",
                    "last_run_state": "Wake Ready",
                    "next_action_hint": "Draft Paper Or Select Next Project",
                },
                "complete_no_paper",
                "run_complete_no_paper",
            ),
            (
                {
                    "paper_id": "paper-2",
                    "paper_status": "Publication Draft",
                    "review_status": "Finalized",
                    "finalization_package_path": "package.json",
                    "draft_markdown_path": "paper.md",
                    "evidence_bundle_path": "evidence.json",
                    "claim_ledger_path": "claims.json",
                    "manifest_path": "manifest.json",
                },
                "ready_to_publish",
                "ready_to_publish",
            ),
            (
                {"paper_id": "paper-archived", "paper_status": "Archived"},
                "complete_no_paper",
                "run_complete_no_paper",
            ),
        ]
        for row, lane, detail_stage in cases:
            with self.subTest(row=row):
                translated = operator_stage_for_record(row)
                self.assertEqual(translated["operator_stage"], lane)
                self.assertEqual(translated["operator_detail_stage"], detail_stage)


    def test_row_age_seconds_handles_naive_database_timestamps(self) -> None:
        age = row_age_seconds({"updated_at": "2026-05-17 13:25:57.966354"})
        self.assertIsInstance(age, int)
        self.assertGreaterEqual(age, 0)

    def test_read_model_links_url_encode_path_segments(self) -> None:
        queue = queue_links({"project_id": "project/with spaces?x=1", "current_run_id": "run/../evil"})
        self.assertEqual(queue["project"], "/control/api/v1/projects/project%2Fwith%20spaces%3Fx%3D1")
        self.assertEqual(queue["run"], "/control/api/v1/runs/run%2F..%2Fevil")
        self.assertEqual(queue["legacy_project"], "/control/api/projects/project%2Fwith%20spaces%3Fx%3D1")
        self.assertEqual(queue["legacy_run"], "/control/api/runs/run%2F..%2Fevil")

        paper = paper_links({"paper_id": "paper/one", "project_id": "project space", "run_id": "run#frag"})
        self.assertEqual(paper["paper"], "/control/api/v1/papers/paper%2Fone")
        self.assertEqual(paper["project"], "/control/api/v1/projects/project%20space")
        self.assertEqual(paper["run"], "/control/api/v1/runs/run%23frag")
        self.assertEqual(paper["legacy_paper"], "/control/api/papers/paper%2Fone")

    def test_operator_labels_use_grade_school_vocabulary(self) -> None:
        expected_lane_labels = {
            "running": "Running",
            "ready_queue": "Ready",
            "needs_operator": "Needs Attention",
            "complete_no_paper": "Done / No Paper",
            "useful_signal": "Useful Signal",
            "compute_scale_blocked": "Scale Blocked",
            "followup_investigation": "Investigate Next",
            "write_paper": "Write Paper",
            "automate_publication": "Finalize Draft",
            "ready_to_publish": "Publish / Import",
            "published": "Published",
            "paused": "Paused",
            "historical": "Historical",
        }
        self.assertEqual(OPERATOR_LANE_LABELS, expected_lane_labels)
        risky_words = ("Review", "Approved", "Wake", "Session", "Draft Needed", "Run Complete")
        for row in (
            {"status": "queued"},
            {"status": "blocked"},
            {"status": "completed", "last_run_state": "wake_ready", "next_action_hint": "draft_paper_or_select_next_project"},
            {"status": "completed", "last_run_state": "wake_ready", "next_action_hint": "draft_paper_or_select_next_project", "followup_recommended": True, "followup_type": "deepen", "followup_title": "Adjacent test", "followup_hypothesis": "A bounded adjacent hypothesis.", "followup_required_evidence": ["baseline", "metrics"], "followup_success_threshold": "beat baseline", "followup_stop_condition": "stop on miss"},
            {"paper_id": "paper-1", "paper_status": "publication_draft"},
            {"paper_id": "paper-2", "paper_status": "publication_draft", "review_status": "finalized", "finalization_package_path": "package.json", "draft_markdown_path": "paper.md", "evidence_bundle_path": "evidence.json", "claim_ledger_path": "claims.json", "manifest_path": "manifest.json"},
            {"paper_id": "paper-imported", "paper_status": "publication_draft", "review_status": "finalized", "finalization_package_path": "package.json", "corpus_imported": True},
        ):
            translated = operator_stage_for_record(row)
            labels = (translated["operator_stage_label"], translated["operator_detail_stage_label"])
            for label in labels:
                for word in risky_words:
                    self.assertNotIn(word, label)
        for raw_detail, label in OPERATOR_DETAIL_LABELS.items():
            if "_" in raw_detail:
                self.assertNotIn(raw_detail.replace("_", " ").title(), label)

    def test_v1_endpoints_expose_operator_status_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            project_dir = Path(tmp) / "projects" / "idea-ready"
            project_dir.mkdir(parents=True)
            _write_decision(project_dir, "finalize_positive")
            _write_publication_artifacts(project_dir)
            imported = client.post("/control/import/legacy-snapshot", headers=headers, json={
                "idempotency_key": "operator-status-import",
                "queue_rows": [
                    {
                        "project_id": "idea-draft-needed",
                        "project_name": "Draft Needed",
                        "project_dir": str(project_dir),
                        "status": "completed",
                        "last_run_state": "wake_ready",
                        "next_action_hint": "draft_paper_or_select_next_project",
                        "current_run_id": "run-draft-needed",
                    },
                    {
                        "project_id": "idea-ready",
                        "project_name": "Ready Paper",
                        "project_dir": str(project_dir),
                        "status": "completed",
                        "last_run_state": "wake_ready",
                        "next_action_hint": "draft_paper_or_select_next_project",
                        "current_run_id": "run-ready",
                    },
                    {
                        "project_id": "idea-unreviewed",
                        "project_name": "Unreviewed Paper",
                        "project_dir": str(project_dir),
                        "status": "completed",
                        "last_run_state": "session_finished_ready",
                        "next_action_hint": "draft_paper_or_select_next_project",
                        "current_run_id": "run-unreviewed",
                    },
                ],
                "paper_rows": [
                    {
                        "paper_id": "paper-ready",
                        "project_id": "idea-ready",
                        "run_id": "run-ready",
                        "paper_status": "publication_draft",
                        "draft_markdown_path": "paper.md",
                        "draft_latex_path": "paper.tex",
                        "evidence_bundle_path": "evidence_bundle.json",
                        "claim_ledger_path": "claim_ledger.json",
                        "manifest_path": "paper_manifest.json",
                    },
                    {
                        "paper_id": "paper-unreviewed",
                        "project_id": "idea-unreviewed",
                        "run_id": "run-unreviewed",
                        "paper_status": "publication_draft",
                        "draft_markdown_path": "paper.md",
                        "draft_latex_path": "paper.tex",
                        "evidence_bundle_path": "evidence_bundle.json",
                        "claim_ledger_path": "claim_ledger.json",
                        "manifest_path": "paper_manifest.json",
                    },
                ],
            })
            self.assertEqual(imported.status_code, 200)
            backfill = client.post("/control/api/paper-reviews/backfill", headers=headers, json={
                "idempotency_key": "operator-status-backfill",
                "dry_run": False,
            })
            self.assertEqual(backfill.status_code, 200, backfill.text)
            approved_paper = client.get("/control/api/v1/papers/paper-ready", headers=headers).json()
            self.assertEqual(approved_paper["paper"]["operator_detail_stage"], "finalization_needed")
            finalized = client.post("/control/api/paper-reviews/paper-ready/prepare-finalization-package", headers=headers, json={
                "idempotency_key": "operator-status-finalized",
                "requested_by": "test",
                "target_label": "operator-status",
                "dry_run": False,
            })
            self.assertEqual(finalized.status_code, 200, finalized.text)

            overview = client.get("/control/api/v1/overview", headers=headers).json()
            self.assertIn("operator_counts", overview)
            self.assertIn("operator_model", overview)
            self.assertEqual(overview["operator_counts"]["ready_to_publish"], 1)
            self.assertEqual(overview["operator_detail_counts"]["run_complete_draft_needed"], 1)
            self.assertIn("paper_pipeline", overview)
            self.assertIn("write_needed", overview["paper_pipeline"])
            self.assertEqual(overview["paper_pipeline"]["publish_ready"], 1)
            self.assertEqual(overview["operator_counts"].get("needs_attention", 0), 0)

            queue = client.get("/control/api/v1/queue?page_size=3&sort=name", headers=headers).json()
            stages = {row["project_id"]: row["operator_stage"] for row in queue["rows"]}
            detail_stages = {row["project_id"]: row["operator_detail_stage"] for row in queue["rows"]}
            self.assertEqual(stages["idea-draft-needed"], "write_paper")
            self.assertEqual(detail_stages["idea-draft-needed"], "run_complete_draft_needed")
            self.assertIn("operator_next_step", queue["rows"][0])

            papers = client.get("/control/api/v1/papers?page_size=10", headers=headers).json()
            paper_stages = {row["paper_id"]: row["operator_stage"] for row in papers["rows"]}
            paper_detail_stages = {row["paper_id"]: row["operator_detail_stage"] for row in papers["rows"]}
            self.assertEqual(paper_stages["paper-ready"], "ready_to_publish")
            self.assertEqual(paper_stages["paper-unreviewed"], "automate_publication")
            self.assertEqual(paper_detail_stages["paper-unreviewed"], "finalization_needed")

            detail = client.get("/control/api/v1/projects/idea-ready", headers=headers).json()
            self.assertEqual(detail["queue_item"]["operator_stage"], "ready_to_publish")
            self.assertEqual(detail["queue_item"]["related_paper_id"], "paper-ready")
            self.assertEqual(detail["papers"][0]["operator_stage"], "ready_to_publish")

    def test_corpus_import_ledger_removes_publication_draft_from_publish_work(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            project_dir = Path(tmp) / "projects" / "idea-imported"
            project_dir.mkdir(parents=True)
            _write_decision(project_dir, "finalize_positive")
            _write_publication_artifacts(project_dir)
            imported = client.post("/control/import/legacy-snapshot", headers=headers, json={
                "idempotency_key": "operator-imported-ledger-import",
                "queue_rows": [{
                    "project_id": "idea-imported",
                    "project_name": "Imported Paper",
                    "project_dir": str(project_dir),
                    "status": "completed",
                    "last_run_state": "wake_ready",
                    "next_action_hint": "draft_paper_or_select_next_project",
                    "current_run_id": "run-imported",
                }],
                "paper_rows": [{
                    "paper_id": "paper-imported",
                    "project_id": "idea-imported",
                    "run_id": "run-imported",
                    "paper_status": "publication_draft",
                    "draft_markdown_path": "paper.md",
                    "draft_latex_path": "paper.tex",
                    "evidence_bundle_path": "evidence_bundle.json",
                    "claim_ledger_path": "claim_ledger.json",
                    "manifest_path": "paper_manifest.json",
                }],
            })
            self.assertEqual(imported.status_code, 200, imported.text)
            backfill = client.post("/control/api/paper-reviews/backfill", headers=headers, json={
                "idempotency_key": "operator-imported-ledger-backfill",
                "paper_ids": ["paper-imported"],
                "dry_run": False,
            })
            self.assertEqual(backfill.status_code, 200, backfill.text)
            finalized = client.post("/control/api/paper-reviews/paper-imported/prepare-finalization-package", headers=headers, json={
                "idempotency_key": "operator-imported-ledger-finalized",
                "requested_by": "test",
                "target_label": "operator-imported-ledger",
                "dry_run": False,
            })
            self.assertEqual(finalized.status_code, 200, finalized.text)

            with sqlite3.connect(Path(tmp) / "state" / "control_plane.sqlite3") as conn:
                conn.execute(
                    """INSERT INTO corpus_imports(
                        paper_id, corpus_repo, artifact_slug, commit_sha, manifest_path, manifest_hash,
                        source_record_fingerprint, public_artifact_id, public_index_path, hf_dataset_synced,
                        hf_dataset_url, imported_at, created_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        "paper-imported",
                        "enoch-ai-research-corpus",
                        "imported-paper",
                        "abc123",
                        "papers/imported-paper/paper_manifest.json",
                        "def456",
                        paper_source_fingerprint("paper-imported"),
                        "imported-paper",
                        "papers/index.json",
                        1,
                        "https://huggingface.co/datasets/aliasocracy/enoch-ai-research-corpus",
                        "2026-05-06T21:00:00+00:00",
                        "2026-05-06T21:00:00+00:00",
                    ),
                )

            overview = client.get("/control/api/v1/overview", headers=headers).json()
            self.assertEqual(overview["operator_counts"].get("ready_to_publish", 0), 0)
            self.assertEqual(overview["operator_counts"].get("published", 0), 1)
            self.assertEqual(overview["paper_pipeline"]["publish_ready"], 0)
            self.assertEqual(overview["paper_pipeline"]["missing_from_corpus"], 0)
            self.assertEqual(overview["paper_pipeline"]["published_imported"], 1)
            self.assertEqual(overview["paper_pipeline"]["publication_ready_total"], 1)

            detail = client.get("/control/api/v1/projects/idea-imported", headers=headers).json()
            self.assertEqual(detail["queue_item"]["operator_stage"], "published")
            self.assertEqual(detail["papers"][0]["operator_stage"], "published")

    def test_overview_suppresses_stale_queue_without_run_id_by_project_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            project_dir = Path(tmp) / "projects" / "idea-no-run"
            project_dir.mkdir(parents=True)
            _write_decision(project_dir, "finalize_positive")
            imported = client.post("/control/import/legacy-snapshot", headers=headers, json={
                "idempotency_key": "operator-no-run-import",
                "queue_rows": [{
                    "project_id": "idea-no-run",
                    "project_name": "No Run Queue",
                    "project_dir": str(project_dir),
                    "status": "completed",
                    "last_run_state": "wake_ready",
                    "next_action_hint": "draft_paper_or_select_next_project",
                }],
                "paper_rows": [{
                    "paper_id": "paper-with-run",
                    "project_id": "idea-no-run",
                    "run_id": "run-known-paper",
                    "paper_status": "publication_draft",
                }],
            })
            self.assertEqual(imported.status_code, 200, imported.text)

            overview = client.get("/control/api/v1/overview", headers=headers).json()
            self.assertNotIn("run_complete_draft_needed", overview["operator_counts"])
            self.assertNotIn("run_complete_draft_needed", overview.get("operator_detail_counts", {}))
            self.assertEqual(overview["operator_counts"].get("needs_attention", 0), 0)

    def test_overview_suppresses_project_level_duplicate_draft_needed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            project_dir = Path(tmp) / "projects" / "idea-rerun"
            project_dir.mkdir(parents=True)
            _write_decision(project_dir, "finalize_positive")
            imported = client.post("/control/import/legacy-snapshot", headers=headers, json={
                "idempotency_key": "operator-rerun-import",
                "queue_rows": [{
                    "project_id": "idea-rerun",
                    "project_name": "Rerun Project",
                    "project_dir": str(project_dir),
                    "status": "completed",
                    "last_run_state": "wake_ready",
                    "next_action_hint": "draft_paper_or_select_next_project",
                    "current_run_id": "run-new",
                }],
                "paper_rows": [{
                    "paper_id": "paper-old",
                    "project_id": "idea-rerun",
                    "run_id": "run-old",
                    "paper_status": "publication_draft",
                }],
            })
            self.assertEqual(imported.status_code, 200, imported.text)

            overview = client.get("/control/api/v1/overview", headers=headers).json()
            self.assertNotIn("run_complete_draft_needed", overview.get("operator_detail_counts", {}))
            self.assertEqual(overview["paper_pipeline"]["write_needed"], 0)
            self.assertEqual(overview["operator_counts"].get("needs_attention", 0), 0)

    def test_overview_counts_unbackfilled_publication_drafts_and_suppresses_stale_queue_actions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            project_dir = Path(tmp) / "projects" / "idea-unbackfilled"
            project_dir.mkdir(parents=True)
            _write_decision(project_dir, "finalize_positive")
            _write_publication_artifacts(project_dir)
            imported = client.post("/control/import/legacy-snapshot", headers=headers, json={
                "idempotency_key": "operator-unbackfilled-import",
                "queue_rows": [
                    {
                        "project_id": "idea-unbackfilled",
                        "project_name": "Unbackfilled Paper",
                        "project_dir": str(project_dir),
                        "status": "completed",
                        "last_run_state": "wake_ready",
                        "next_action_hint": "draft_paper_or_select_next_project",
                        "current_run_id": "run-unbackfilled",
                    },
                    {
                        "project_id": "idea-ready-stale",
                        "project_name": "Ready But Stale Queue",
                        "project_dir": str(project_dir),
                        "status": "completed",
                        "last_run_state": "wake_ready",
                        "next_action_hint": "draft_paper_or_select_next_project",
                        "current_run_id": "run-ready-stale",
                    },
                ],
                "paper_rows": [
                    {
                        "paper_id": "paper-unbackfilled",
                        "project_id": "idea-unbackfilled",
                        "run_id": "run-unbackfilled",
                        "paper_status": "publication_draft",
                        "draft_markdown_path": "paper.md",
                        "draft_latex_path": "paper.tex",
                        "evidence_bundle_path": "evidence_bundle.json",
                        "claim_ledger_path": "claim_ledger.json",
                        "manifest_path": "paper_manifest.json",
                    },
                    {
                        "paper_id": "paper-ready-stale",
                        "project_id": "idea-ready-stale",
                        "run_id": "run-ready-stale",
                        "paper_status": "publication_draft",
                        "draft_markdown_path": "paper.md",
                        "draft_latex_path": "paper.tex",
                        "evidence_bundle_path": "evidence_bundle.json",
                        "claim_ledger_path": "claim_ledger.json",
                        "manifest_path": "paper_manifest.json",
                    },
                ],
            })
            self.assertEqual(imported.status_code, 200, imported.text)
            with sqlite3.connect(Path(tmp) / "state" / "control_plane.sqlite3") as conn:
                conn.execute(
                    """INSERT INTO runs(run_id, project_id, session_id, state, dispatch_mode, started_at, ended_at, last_callback_at, gate_state, current_activity, idempotency_key, updated_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                    ("run-with-paper", "idea-with-paper", "session-with-paper", "wake_ready", "live", "2026-05-04T12:00:00+00:00", "2026-05-04T12:10:00+00:00", "2026-05-04T12:10:00+00:00", "wake_ready", "worker_callback", "run-with-paper-key", "2026-05-04T12:10:00+00:00"),
                )
            backfill = client.post("/control/api/paper-reviews/backfill", headers=headers, json={
                "idempotency_key": "operator-ready-stale-backfill",
                "paper_ids": ["paper-ready-stale"],
                "dry_run": False,
            })
            self.assertEqual(backfill.status_code, 200, backfill.text)
            finalized = client.post("/control/api/paper-reviews/paper-ready-stale/prepare-finalization-package", headers=headers, json={
                "idempotency_key": "operator-ready-stale-finalized",
                "requested_by": "test",
                "target_label": "operator-ready-stale",
                "dry_run": False,
            })
            self.assertEqual(finalized.status_code, 200, finalized.text)

            overview = client.get("/control/api/v1/overview", headers=headers).json()
            self.assertEqual(overview["operator_counts"].get("needs_attention", 0), 0)
            self.assertEqual(overview["operator_counts"]["ready_to_publish"], 1)
            self.assertNotIn("run_complete_draft_needed", overview["operator_counts"])
            self.assertNotIn("run_complete_draft_needed", overview.get("operator_detail_counts", {}))

            papers = client.get("/control/api/v1/papers?page_size=10", headers=headers).json()
            paper_stages = {row["paper_id"]: row["operator_stage"] for row in papers["rows"]}
            paper_detail_stages = {row["paper_id"]: row["operator_detail_stage"] for row in papers["rows"]}
            self.assertEqual(paper_stages["paper-unbackfilled"], "automate_publication")
            self.assertEqual(paper_detail_stages["paper-unbackfilled"], "finalization_needed")
            self.assertEqual(paper_stages["paper-ready-stale"], "ready_to_publish")



    def test_existing_finalized_paper_controls_queue_and_run_stage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            project_dir = Path(tmp) / "projects" / "idea-with-paper"
            project_dir.mkdir(parents=True)
            _write_decision(project_dir, "provisional_positive_continue")
            _write_publication_artifacts(project_dir)
            imported = client.post("/control/import/legacy-snapshot", headers=headers, json={
                "idempotency_key": "operator-existing-paper-import",
                "queue_rows": [{
                    "project_id": "idea-with-paper",
                    "project_name": "Existing Paper",
                    "project_dir": str(project_dir),
                    "status": "completed",
                    "last_run_state": "wake_ready",
                    "next_action_hint": "draft_paper_or_select_next_project",
                    "current_run_id": "run-with-paper",
                }],
                "run_rows": [{
                    "run_id": "run-with-paper",
                    "project_id": "idea-with-paper",
                    "state": "wake_ready",
                    "gate_state": "wake_ready",
                    "current_activity": "worker_callback",
                }],
                "paper_rows": [{
                    "paper_id": "paper-existing",
                    "project_id": "idea-with-paper",
                    "run_id": "run-with-paper",
                    "paper_status": "publication_draft",
                    "draft_markdown_path": "paper.md",
                    "draft_latex_path": "paper.tex",
                    "evidence_bundle_path": "evidence_bundle.json",
                    "claim_ledger_path": "claim_ledger.json",
                    "manifest_path": "paper_manifest.json",
                }],
            })
            self.assertEqual(imported.status_code, 200, imported.text)
            with sqlite3.connect(Path(tmp) / "state" / "control_plane.sqlite3") as conn:
                conn.execute(
                    """INSERT INTO runs(run_id, project_id, session_id, state, dispatch_mode, started_at, ended_at, last_callback_at, gate_state, current_activity, idempotency_key, updated_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                    ("run-with-paper", "idea-with-paper", "session-with-paper", "wake_ready", "live", "2026-05-04T12:00:00+00:00", "2026-05-04T12:10:00+00:00", "2026-05-04T12:10:00+00:00", "wake_ready", "worker_callback", "run-with-paper-key", "2026-05-04T12:10:00+00:00"),
                )
            backfill = client.post("/control/api/paper-reviews/backfill", headers=headers, json={
                "idempotency_key": "operator-existing-paper-backfill",
                "paper_ids": ["paper-existing"],
                "dry_run": False,
            })
            self.assertEqual(backfill.status_code, 200, backfill.text)
            finalized = client.post("/control/api/paper-reviews/paper-existing/prepare-finalization-package", headers=headers, json={
                "idempotency_key": "operator-existing-paper-finalized",
                "requested_by": "test",
                "target_label": "operator-existing-paper",
                "dry_run": False,
            })
            self.assertEqual(finalized.status_code, 200, finalized.text)

            detail = client.get("/control/api/v1/projects/idea-with-paper", headers=headers).json()
            self.assertEqual(detail["queue_item"]["operator_stage"], "ready_to_publish")
            self.assertEqual(detail["queue_item"]["related_paper_id"], "paper-existing")
            runs = client.get("/control/api/v1/runs?search=run-with-paper", headers=headers).json()
            self.assertEqual(runs["rows"][0]["operator_stage"], "ready_to_publish")
            overview = client.get("/control/api/v1/overview", headers=headers).json()
            self.assertNotIn("run_complete_draft_needed", overview["operator_counts"])
            self.assertNotIn("run_complete_draft_needed", overview.get("operator_detail_counts", {}))
            self.assertEqual(overview["operator_counts"]["ready_to_publish"], 1)

    def test_negative_decision_artifact_is_no_paper_not_draft_needed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            project_dir = Path(tmp) / "projects" / "idea-negative"
            project_dir.mkdir(parents=True)
            _write_decision(project_dir, "negative_result")
            imported = client.post("/control/import/legacy-snapshot", headers=headers, json={
                "idempotency_key": "operator-negative-import",
                "queue_rows": [{
                    "project_id": "idea-negative",
                    "project_name": "Negative Result",
                    "project_dir": str(project_dir),
                    "status": "completed",
                    "last_run_state": "wake_ready",
                    "next_action_hint": "draft_paper_or_select_next_project",
                    "current_run_id": "run-negative",
                }],
            })
            self.assertEqual(imported.status_code, 200, imported.text)

            detail = client.get("/control/api/v1/projects/idea-negative", headers=headers).json()
            queue_item = detail["queue_item"]
            self.assertEqual(queue_item["operator_stage"], "complete_no_paper")
            self.assertFalse(queue_item["paper_draft_eligible"])
            self.assertEqual(queue_item["project_decision_summary"], "negative_result (project decision is not positive)")
            self.assertIn("No paper draft is needed", queue_item["operator_next_step"])

            overview = client.get("/control/api/v1/overview", headers=headers).json()
            self.assertNotIn("run_complete_draft_needed", overview["operator_counts"])
            self.assertNotIn("run_complete_draft_needed", overview.get("operator_detail_counts", {}))
            self.assertEqual(overview["operator_counts"]["complete_no_paper"], 1)

    def test_missing_project_dir_uses_project_id_evidence_fallback_for_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            fallback_dir = Path(tmp) / "projects" / "idea-fallback"
            fallback_dir.mkdir(parents=True)
            (fallback_dir / ".omx").mkdir()
            (fallback_dir / ".omx" / "project_decision.json").write_text(
                '{"decision":"continue","hypothesis_status":"mixed"}\n',
                encoding="utf-8",
            )
            config_path = Path(tmp) / "config.json"
            config_path.write_text(f'{{"project_root": "{Path(tmp) / "projects"}"}}\n', encoding="utf-8")
            with patch.dict("os.environ", {"ENOCH_CONFIG": str(config_path)}):
                imported = client.post("/control/import/legacy-snapshot", headers=headers, json={
                    "idempotency_key": "operator-fallback-import",
                    "queue_rows": [{
                        "project_id": "idea-fallback",
                        "project_name": "Fallback Mixed Result",
                        "project_dir": "",
                        "status": "completed",
                        "last_run_state": "wake_ready",
                        "next_action_hint": "draft_paper_or_select_next_project",
                        "current_run_id": "run-fallback",
                        "last_result_summary": "worker completed with artifacts",
                    }],
                })
                self.assertEqual(imported.status_code, 200, imported.text)

                detail = client.get("/control/api/v1/projects/idea-fallback", headers=headers).json()
                queue_item = detail["queue_item"]
                self.assertEqual(queue_item["operator_stage"], "complete_no_paper")
                self.assertFalse(queue_item["paper_draft_eligible"])
                self.assertEqual(
                    queue_item["project_decision_summary"],
                    "continue (continue decision is not paper-positive)",
                )

                overview = client.get("/control/api/v1/overview", headers=headers).json()
            pipeline = overview["paper_pipeline"]
            self.assertEqual(pipeline["write_needed"], 0)
            self.assertEqual(pipeline["raw_completed_no_paper_candidates"], 1)
            self.assertEqual(pipeline["not_writable_by_decision_gate"], 1)
            self.assertEqual(overview["operator_counts"].get("write_paper", 0), 0)

    def test_missing_project_dir_and_missing_decision_is_not_draft_needed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            config_path = Path(tmp) / "config.json"
            config_path.write_text(f'{{"project_root": "{Path(tmp) / "projects"}"}}\n', encoding="utf-8")
            with patch.dict("os.environ", {"ENOCH_CONFIG": str(config_path)}):
                imported = client.post("/control/import/legacy-snapshot", headers=headers, json={
                    "idempotency_key": "operator-missing-decision-import",
                    "queue_rows": [{
                        "project_id": "idea-missing-decision",
                        "project_name": "Missing Decision",
                        "project_dir": "",
                        "status": "completed",
                        "last_run_state": "wake_ready",
                        "next_action_hint": "draft_paper_or_select_next_project",
                        "current_run_id": "run-missing-decision",
                        "last_result_summary": "worker completed with artifacts",
                    }],
                })
                self.assertEqual(imported.status_code, 200, imported.text)

                overview = client.get("/control/api/v1/overview", headers=headers).json()
            pipeline = overview["paper_pipeline"]
            self.assertEqual(pipeline["write_needed"], 0)
            self.assertEqual(pipeline["raw_completed_no_paper_candidates"], 1)
            self.assertEqual(pipeline["not_writable_by_decision_gate"], 1)
            self.assertEqual(overview["operator_counts"].get("write_paper", 0), 0)
            self.assertEqual(
                pipeline["gate_rejected_sample"][0]["gate_reason"],
                "missing project decision artifact",
            )

    def test_dashboard_prefers_operator_columns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            html = client.get("/control/dashboard").text
            self.assertIn("operator_stage_label", html)
            self.assertIn("What do I need to know?", html)
            self.assertIn("What needs me?", html)
            self.assertIn("What is running?", html)
            self.assertIn("What can be written?", html)
            self.assertIn("Needs another investigation?", html)
            self.assertIn("What can be published?", html)
            self.assertIn("What is done / no paper?", html)
            self.assertIn("Raw states stay in drill-down/debug views", html)
            self.assertIn("Paper pipeline", html)
            self.assertIn("Debug paper counts", html)
            self.assertIn("1. Write papers", html)
            self.assertIn("2. Finalize drafts", html)
            self.assertIn("3. Publish/import", html)
            self.assertIn("Last import result", html)
            self.assertIn("Import validation", html)
            self.assertIn("Investigation follow-ups", html)
            self.assertIn("Launch follow-up", html)
            self.assertIn("operatorQuestionCards(counts={},operators={},pipeline={},investigation={})", html)
            self.assertIn("workState(counts,operators={},pipeline={},investigation={})", html)
            self.assertIn("const previousCommandPanel=hasOverview?$('commandPanel')?.outerHTML||'':''", html)
            self.assertIn("${previousCommandPanel||operatorCommandPanel(counts)}", html)
            self.assertIn("project_decision_summary", html)
            self.assertIn("['operator_stage_label','project_id','run_id','related_paper_id','operator_next_step','updated_at']", html)
            self.assertIn("operators.ready_queue", html)
            self.assertIn("Publication drafts", html)
            self.assertNotIn("Publication-ready drafts", html)
            self.assertIn("publication_draft:'Publication draft'", html)
            self.assertIn("['publication_draft','archived']", html)
            self.assertIn("['queued','claimed','blocked','finalized','deferred','rejected']", html)


if __name__ == "__main__":
    unittest.main()
