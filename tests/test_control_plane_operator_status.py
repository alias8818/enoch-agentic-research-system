from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from omx_wake_gate.config import GateConfig
from omx_wake_gate.control_plane.read_models import operator_stage_for_record
from omx_wake_gate.control_plane.store import REVIEW_CHECKLIST_DEFINITION
from omx_wake_gate.control_plane.router import create_control_plane_router


TOKEN = "test-token"


def _write_decision(project_dir: Path, decision: str) -> None:
    decision_dir = project_dir / ".omx"
    decision_dir.mkdir(parents=True, exist_ok=True)
    (decision_dir / "project_decision.json").write_text(f'{{"decision":"{decision}"}}\n', encoding="utf-8")


def _client(tmp: str) -> TestClient:
    app = FastAPI()
    root = Path(tmp) / "projects"
    root.mkdir(parents=True, exist_ok=True)
    config = GateConfig(
        state_dir=str(Path(tmp) / "state"),
        project_root=str(root),
        dispatch_script_path=str(Path(tmp) / "dispatch.sh"),
        omx_inbound_bearer_token=TOKEN,
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
            ({"status": "queued"}, "idea_queued", False),
            ({"status": "awaiting_wake"}, "running", False),
            ({"status": "completed", "last_run_state": "wake_ready", "next_action_hint": "draft_paper_or_select_next_project"}, "run_complete_no_paper", False),
            ({"status": "completed", "last_run_state": "session_finished_ready", "next_action_hint": "select_next_project"}, "run_complete_no_paper", False),
            ({"paper_id": "paper-1", "paper_status": "draft_review"}, "draft_created", False),
            ({"paper_id": "paper-2", "paper_status": "publication_draft", "review_status": "finalized", "finalization_package_path": "package.json"}, "ready_to_publish", False),
            ({"paper_id": "paper-approved", "paper_status": "publication_draft", "review_status": "approved_for_finalization"}, "finalization_needed", False),
            ({"paper_id": "paper-finalized-no-package", "paper_status": "publication_draft", "review_status": "finalized"}, "finalization_needed", False),
            ({"paper_id": "paper-missing-review", "paper_status": "publication_draft"}, "finalization_needed", False),
            ({"paper_id": "paper-3", "paper_status": "publication_draft", "review_status": "unreviewed"}, "finalization_needed", False),
            ({"status": "blocked"}, "blocked_needs_operator", True),
            ({"status": "paused"}, "paused_work", False),
        ]
        for row, stage, attention in cases:
            with self.subTest(row=row):
                translated = operator_stage_for_record(row)
                self.assertEqual(translated["operator_stage"], stage)
                self.assertIs(translated["operator_attention"], attention)

    def test_v1_endpoints_expose_operator_status_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            project_dir = Path(tmp) / "projects" / "idea-ready"
            project_dir.mkdir(parents=True)
            _write_decision(project_dir, "finalize_positive")
            for artifact_name in ("paper.md", "paper.tex", "evidence_bundle.json", "claim_ledger.json", "paper_manifest.json"):
                (project_dir / artifact_name).write_text("{}" if artifact_name.endswith(".json") else "paper", encoding="utf-8")
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
            for status in ("triage_ready", "in_review"):
                updated = client.post("/control/api/paper-reviews/paper-ready/status", headers=headers, json={
                    "idempotency_key": f"operator-status-{status}",
                    "requested_by": "test",
                    "review_status": status,
                })
                self.assertEqual(updated.status_code, 200, updated.text)
            for item_id, _label, required in REVIEW_CHECKLIST_DEFINITION:
                if not required:
                    continue
                checklist = client.post(f"/control/api/paper-reviews/paper-ready/checklist/{item_id}", headers=headers, json={
                    "idempotency_key": f"operator-status-checklist-{item_id}",
                    "requested_by": "test",
                    "status": "pass",
                })
                self.assertEqual(checklist.status_code, 200, checklist.text)
            approved = client.post("/control/api/paper-reviews/paper-ready/approve-finalization", headers=headers, json={
                "idempotency_key": "operator-status-approved",
                "requested_by": "test",
            })
            self.assertEqual(approved.status_code, 200, approved.text)
            approved_paper = client.get("/control/api/v1/papers/paper-ready", headers=headers).json()
            self.assertEqual(approved_paper["paper"]["operator_stage"], "finalization_needed")
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
            self.assertEqual(overview["operator_counts"]["run_complete_draft_needed"], 1)
            self.assertIn("paper_pipeline", overview)
            self.assertIn("write_needed", overview["paper_pipeline"])
            self.assertEqual(overview["paper_pipeline"]["publish_ready"], 1)
            self.assertEqual(overview["operator_counts"].get("needs_attention", 0), 0)

            queue = client.get("/control/api/v1/queue?page_size=3&sort=name", headers=headers).json()
            stages = {row["project_id"]: row["operator_stage"] for row in queue["rows"]}
            self.assertEqual(stages["idea-draft-needed"], "run_complete_draft_needed")
            self.assertIn("operator_next_step", queue["rows"][0])

            papers = client.get("/control/api/v1/papers?page_size=10", headers=headers).json()
            paper_stages = {row["paper_id"]: row["operator_stage"] for row in papers["rows"]}
            self.assertEqual(paper_stages["paper-ready"], "ready_to_publish")
            self.assertEqual(paper_stages["paper-unreviewed"], "finalization_needed")

            detail = client.get("/control/api/v1/projects/idea-ready", headers=headers).json()
            self.assertEqual(detail["queue_item"]["operator_stage"], "ready_to_publish")
            self.assertEqual(detail["queue_item"]["related_paper_id"], "paper-ready")
            self.assertEqual(detail["papers"][0]["operator_stage"], "ready_to_publish")

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
            self.assertEqual(overview["operator_counts"].get("needs_attention", 0), 0)

    def test_overview_keeps_new_run_draft_needed_when_older_project_paper_exists(self) -> None:
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
            self.assertEqual(overview["operator_counts"]["run_complete_draft_needed"], 1)
            self.assertEqual(overview["operator_counts"].get("needs_attention", 0), 0)

    def test_overview_counts_unbackfilled_publication_drafts_and_suppresses_stale_queue_actions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            project_dir = Path(tmp) / "projects" / "idea-unbackfilled"
            project_dir.mkdir(parents=True)
            _write_decision(project_dir, "finalize_positive")
            for artifact_name in ("paper.md", "paper.tex", "evidence_bundle.json", "claim_ledger.json", "paper_manifest.json"):
                (project_dir / artifact_name).write_text("{}" if artifact_name.endswith(".json") else "paper", encoding="utf-8")
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
            for status in ("triage_ready", "in_review"):
                updated = client.post("/control/api/paper-reviews/paper-ready-stale/status", headers=headers, json={
                    "idempotency_key": f"operator-ready-stale-{status}",
                    "requested_by": "test",
                    "review_status": status,
                })
                self.assertEqual(updated.status_code, 200, updated.text)
            for item_id, _label, required in REVIEW_CHECKLIST_DEFINITION:
                if not required:
                    continue
                checklist = client.post(f"/control/api/paper-reviews/paper-ready-stale/checklist/{item_id}", headers=headers, json={
                    "idempotency_key": f"operator-ready-stale-checklist-{item_id}",
                    "requested_by": "test",
                    "status": "pass",
                })
                self.assertEqual(checklist.status_code, 200, checklist.text)
            approved = client.post("/control/api/paper-reviews/paper-ready-stale/approve-finalization", headers=headers, json={
                "idempotency_key": "operator-ready-stale-approved",
                "requested_by": "test",
            })
            self.assertEqual(approved.status_code, 200, approved.text)
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

            papers = client.get("/control/api/v1/papers?page_size=10", headers=headers).json()
            paper_stages = {row["paper_id"]: row["operator_stage"] for row in papers["rows"]}
            self.assertEqual(paper_stages["paper-unbackfilled"], "finalization_needed")
            self.assertEqual(paper_stages["paper-ready-stale"], "ready_to_publish")



    def test_existing_finalized_paper_controls_queue_and_run_stage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            project_dir = Path(tmp) / "projects" / "idea-with-paper"
            project_dir.mkdir(parents=True)
            _write_decision(project_dir, "provisional_positive_continue")
            for artifact_name in ("paper.md", "paper.tex", "evidence_bundle.json", "claim_ledger.json", "paper_manifest.json"):
                (project_dir / artifact_name).write_text("{}" if artifact_name.endswith(".json") else "paper", encoding="utf-8")
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
            for status in ("triage_ready", "in_review"):
                updated = client.post("/control/api/paper-reviews/paper-existing/status", headers=headers, json={
                    "idempotency_key": f"operator-existing-paper-{status}",
                    "requested_by": "test",
                    "review_status": status,
                })
                self.assertEqual(updated.status_code, 200, updated.text)
            for item_id, _label, required in REVIEW_CHECKLIST_DEFINITION:
                if required:
                    checklist = client.post(f"/control/api/paper-reviews/paper-existing/checklist/{item_id}", headers=headers, json={
                        "idempotency_key": f"operator-existing-paper-checklist-{item_id}",
                        "requested_by": "test",
                        "status": "pass",
                    })
                    self.assertEqual(checklist.status_code, 200, checklist.text)
            approved = client.post("/control/api/paper-reviews/paper-existing/approve-finalization", headers=headers, json={
                "idempotency_key": "operator-existing-paper-approved",
                "requested_by": "test",
            })
            self.assertEqual(approved.status_code, 200, approved.text)
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
            self.assertEqual(queue_item["operator_stage"], "run_complete_no_paper")
            self.assertFalse(queue_item["paper_draft_eligible"])
            self.assertEqual(queue_item["project_decision_summary"], "negative_result (project decision is not positive)")
            self.assertIn("No paper draft is needed", queue_item["operator_next_step"])

            overview = client.get("/control/api/v1/overview", headers=headers).json()
            self.assertNotIn("run_complete_draft_needed", overview["operator_counts"])
            self.assertEqual(overview["operator_counts"]["run_complete_no_paper"], 1)

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
            with patch.dict("os.environ", {"OMX_WAKE_GATE_CONFIG": str(config_path)}):
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
                self.assertEqual(queue_item["operator_stage"], "run_complete_no_paper")
                self.assertFalse(queue_item["paper_draft_eligible"])
                self.assertEqual(
                    queue_item["project_decision_summary"],
                    "project decision lacks positive draft signal",
                )

                overview = client.get("/control/api/v1/overview", headers=headers).json()
            pipeline = overview["paper_pipeline"]
            self.assertEqual(pipeline["write_needed"], 0)
            self.assertEqual(pipeline["raw_completed_no_paper_candidates"], 1)
            self.assertEqual(pipeline["not_writable_by_decision_gate"], 1)

    def test_missing_project_dir_and_missing_decision_is_not_draft_needed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            config_path = Path(tmp) / "config.json"
            config_path.write_text(f'{{"project_root": "{Path(tmp) / "projects"}"}}\n', encoding="utf-8")
            with patch.dict("os.environ", {"OMX_WAKE_GATE_CONFIG": str(config_path)}):
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
            self.assertEqual(
                pipeline["gate_rejected_sample"][0]["gate_reason"],
                "missing project decision artifact",
            )

    def test_dashboard_prefers_operator_columns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            html = client.get("/control/dashboard").text
            self.assertIn("operator_stage_label", html)
            self.assertIn("Paper pipeline", html)
            self.assertIn("1. Write papers", html)
            self.assertIn("2. Finalize drafts", html)
            self.assertIn("3. Publish/import", html)
            self.assertIn("workState(counts,operators={},pipeline={})", html)
            self.assertIn("project_decision_summary", html)
            self.assertIn("['operator_stage_label','project_id','run_id','related_paper_id','operator_next_step','updated_at']", html)


if __name__ == "__main__":
    unittest.main()
