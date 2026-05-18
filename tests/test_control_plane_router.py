from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from enoch_control_plane.config import GateConfig
from enoch_control_plane.control_plane.router import _project_prompt, _write_deterministic_paper, create_control_plane_router
from enoch_control_plane.control_plane.store import ControlPlaneStore
from enoch_control_plane.control_plane.models import ImportSnapshotRequest, PaperRecord, PaperReviewBackfillRequest, WorkerPreflightCheck, WorkerPreflightResponse
from enoch_control_plane.control_plane.worker_adapter import HttpResult
from enoch_control_plane.enoch_core.store import IdempotencyConflict


TOKEN = "test-token"


def _config(tmp: str) -> GateConfig:
    root = Path(tmp) / "projects"
    root.mkdir(parents=True, exist_ok=True)
    return GateConfig(
        state_dir=str(Path(tmp) / "state"),
        project_root=str(root),
        dispatch_script_path=str(Path(tmp) / "dispatch.sh"),
        control_api_bearer_token=TOKEN,
        completion_callback_url="http://example.invalid/callback",
        completion_callback_token="unused",
    )


def _live_config(tmp: str) -> GateConfig:
    base = _config(tmp)
    return base.model_copy(update={"live_dispatch_enabled": True, "worker_wake_gate_bearer_token": "worker-token"})


def _client(tmp: str) -> TestClient:
    app = FastAPI()
    config = _config(tmp)
    def require(auth: str | None) -> None:
        if auth != f"Bearer {TOKEN}":
            raise AssertionError("bad token")
    app.include_router(create_control_plane_router(config, require))
    return TestClient(app)


def _client_with_config(config: GateConfig) -> TestClient:
    app = FastAPI()

    def require(auth: str | None) -> None:
        if auth != f"Bearer {TOKEN}":
            raise AssertionError("bad token")

    app.include_router(create_control_plane_router(config, require))
    return TestClient(app)


def _write_publication_artifacts(project_dir: Path, *, evidence_path: str, claim_path: str, manifest_path: str) -> None:
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "paper.md").write_text("Measured result improved over baseline.", encoding="utf-8")
    (project_dir / "paper.tex").write_text("content", encoding="utf-8")
    evidence = {
        "schema_version": "evidence_bundle.v2",
        "public_evidence_files": [{
            "path": "evidence/run_notes.md",
            "source_path": "run_notes.md",
            "content": "Measured result improved over baseline.",
            "sha256": "abc",
        }],
    }
    claims = {
        "schema_version": "claim_ledger.v2",
        "ledger_status": "claims_reference_evidence",
        "claims": [{
            "id": "C1",
            "claim": "Measured result improved over baseline.",
            "support_status": "supported",
            "evidence_refs": [{"path": "evidence/run_notes.md", "source_path": "run_notes.md", "match_score": 1.0}],
        }],
        "unsupported_claim_count": 0,
    }
    manifest = {"evidence_file_count": 1, "claim_count": 1, "claim_ledger_status": "claims_reference_evidence"}
    for rel, payload in ((evidence_path, evidence), (claim_path, claims), (manifest_path, manifest)):
        target = project_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload), encoding="utf-8")


class ControlPlaneRouterTests(unittest.TestCase):

    def test_deterministic_paper_writes_are_atomic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _config(tmp)
            project_dir = Path(config.project_root) / "project-a"
            paper_path = project_dir / "papers" / "run-1" / "draft.md"
            paper_path.parent.mkdir(parents=True, exist_ok=True)
            paper_path.write_text("old draft", encoding="utf-8")
            paper = PaperRecord(
                paper_id="paper-1",
                project_id="project-a",
                run_id="run-1",
                draft_markdown_path="papers/run-1/draft.md",
                draft_latex_path="papers/run-1/draft.tex",
                evidence_bundle_path="papers/run-1/evidence_bundle.json",
                claim_ledger_path="papers/run-1/claim_ledger.json",
                manifest_path="papers/run-1/manifest.json",
            )

            def fail_atomic(path: Path, content: str) -> None:
                if path == paper_path.resolve():
                    raise OSError("simulated atomic write failure")
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")

            with patch("enoch_control_plane.control_plane.router._atomic_write_text", side_effect=fail_atomic):
                with self.assertRaises(OSError):
                    _write_deterministic_paper(
                        config,
                        {"project_name": "Project A", "project_dir": "project-a"},
                        paper,
                        force=True,
                    )

            self.assertEqual(paper_path.read_text(encoding="utf-8"), "old draft")


    def test_deterministic_paper_rejects_uninspectable_target_without_raw_permission_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _config(tmp)
            project_dir = Path(config.project_root) / "project-a"
            project_dir.mkdir(parents=True)
            paper = PaperRecord(
                paper_id="paper-1",
                project_id="project-a",
                run_id="run-1",
                draft_markdown_path="papers/run-1/draft.md",
                draft_latex_path="papers/run-1/draft.tex",
                evidence_bundle_path="papers/run-1/evidence_bundle.json",
                claim_ledger_path="papers/run-1/claim_ledger.json",
                manifest_path="papers/run-1/manifest.json",
            )
            target = (project_dir / "papers" / "run-1" / "draft.md").resolve()
            original_exists = Path.exists

            def fake_exists(path: Path) -> bool:
                if path == target:
                    raise PermissionError("denied")
                return original_exists(path)

            with patch.object(Path, "exists", fake_exists):
                with self.assertRaises(HTTPException) as raised:
                    _write_deterministic_paper(
                        config,
                        {"project_name": "Project A", "project_dir": "project-a"},
                        paper,
                        force=False,
                    )

            self.assertEqual(raised.exception.status_code, 400)
            self.assertIn("paper path", str(raised.exception.detail))
            self.assertFalse(target.exists())

    def test_deterministic_paper_rejects_invalid_project_dir_without_value_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _config(tmp)
            paper = PaperRecord(
                paper_id="paper-1",
                project_id="project-a",
                run_id="run-1",
            )

            with self.assertRaises(HTTPException) as raised:
                _write_deterministic_paper(
                    config,
                    {"project_id": "project-a", "project_name": "Project A", "project_dir": "bad\0project"},
                    paper,
                    force=True,
                )

            self.assertEqual(raised.exception.status_code, 400)
            self.assertIn("project_dir", str(raised.exception.detail))

    def test_health_supports_supabase_backend_without_sqlite_path(self) -> None:
        class FakeSupabaseStore:
            pass

        config = GateConfig(
            state_dir="/tmp/unused",
            project_root="/tmp/unused-projects",
            dispatch_script_path="/tmp/dispatch.sh",
            control_api_bearer_token=TOKEN,
            completion_callback_url="http://example.invalid/callback",
            completion_callback_token="unused",
            control_plane_store_backend="supabase",
            supabase_database_url="postgresql://example.invalid/postgres",
        )
        with patch("enoch_control_plane.control_plane.router.SupabaseControlPlaneStore", return_value=FakeSupabaseStore()):
            client = _client_with_config(config)
            response = client.get("/control/health", headers={"Authorization": f"Bearer {TOKEN}"})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["store_backend"], "supabase")
        self.assertEqual(body["db_path"], "supabase")


    def test_research_quality_endpoint_reads_configured_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "research-quality.json"
            report.write_text(json.dumps({
                "schema_version": "enoch_research_quality_report_v1",
                "generated_at": "2026-05-11T00:00:00Z",
                "summary": {"candidate_count": 0, "decision_count": 1, "problem_counts": {"weak_or_missing_evidence_strength": 1}},
                "candidate_scores": [],
                "decision_scores": [{
                    "project_id": "p1",
                    "project_name": "Project 1",
                    "run_id": "r1",
                    "decision": "finalize_negative",
                    "hypothesis_status": "mixed",
                    "problems": ["weak_or_missing_evidence_strength"],
                }],
            }), encoding="utf-8")
            with patch.dict(os.environ, {"ENOCH_RESEARCH_QUALITY_REPORT_PATH": str(report)}):
                client = _client(tmp)
                response = client.get("/control/api/v1/research-quality", headers={"Authorization": f"Bearer {TOKEN}"})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["source"], "control_api_v1_research_quality")
        self.assertEqual(body["status"], "warnings")
        self.assertTrue(body["ok"])
        self.assertEqual(body["decisions_checked"], 1)
        self.assertEqual(body["problem_counts"], {"weak_or_missing_evidence_strength": 1})

    def test_pause_import_dry_run_and_draft(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "projects" / "idea-positive"
            project_dir.mkdir(parents=True)
            (project_dir / "run_notes.md").write_text("Positive evidence supports drafting this paper.\n", encoding="utf-8")
            (project_dir / ".enoch").mkdir(parents=True)
            (project_dir / ".enoch" / "project_decision.json").write_text('{"project_decision":"finalize_positive"}\n', encoding="utf-8")
            client = _client(tmp)
            headers = {"Authorization": f"Bearer {TOKEN}"}

            state = client.get("/control/state", headers=headers).json()
            self.assertTrue(state["flags"]["queue_paused"])

            import_response = client.post("/control/import/legacy-snapshot", headers=headers, json={
                "idempotency_key": "import-router-1",
                "queue_rows": [{
                    "project_id": "idea-positive",
                    "project_name": "Positive Project",
                    "project_dir": str(project_dir),
                    "status": "completed",
                    "last_run_state": "finalize_positive",
                    "current_run_id": "run-1",
                    "manual_review_required": False,
                }],
                "paper_rows": [],
            })
            self.assertEqual(import_response.status_code, 200)
            self.assertEqual(import_response.json()["imported_queue_items"], 1)

            paused_dispatch = client.post("/control/dispatch-next", headers=headers, json={"dry_run": True})
            self.assertEqual(paused_dispatch.json()["action"], "paused")

            dry_draft = client.post("/control/papers/draft-next", headers=headers, json={"force": True, "dry_run": True})
            self.assertEqual(dry_draft.status_code, 200)
            dry_body = dry_draft.json()
            self.assertEqual(dry_body["action"], "dry_run_draft")
            self.assertFalse((project_dir / dry_body["paper"]["draft_markdown_path"]).exists())

            draft = client.post("/control/papers/draft-next", headers=headers, json={"force": True})
            self.assertEqual(draft.status_code, 200)
            body = draft.json()
            self.assertEqual(body["action"], "drafted")
            self.assertTrue((project_dir / body["paper"]["draft_markdown_path"]).exists())

    def test_v1_dashboard_read_models_are_bounded_and_do_not_call_legacy_full_lists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            project_root = Path(tmp) / "projects"
            queue_rows = []
            paper_rows = []
            for idx in range(3):
                project_id = f"idea-{idx}"
                (project_root / project_id).mkdir(parents=True, exist_ok=True)
                queue_rows.append({
                    "project_id": project_id,
                    "project_name": f"Project {idx}",
                    "project_dir": project_id,
                    "status": "queued" if idx else "awaiting_wake",
                    "dispatch_priority": idx,
                    "selection_rank": idx,
                    "current_run_id": f"run-{idx}",
                    "last_run_state": "awaiting_wake" if idx == 0 else "",
                    "next_action_hint": "await_callback" if idx == 0 else "controller_review",
                })
                paper_rows.append({
                    "paper_id": f"paper-{idx}",
                    "project_id": project_id,
                    "run_id": f"run-{idx}",
                    "paper_status": "publication_draft",
                    "draft_markdown_path": "paper.md",
                    "draft_latex_path": "paper.tex",
                    "evidence_bundle_path": "evidence_bundle.json",
                    "claim_ledger_path": "claim_ledger.json",
                    "manifest_path": "paper_manifest.json",
                })
            imported = client.post("/control/import/legacy-snapshot", headers=headers, json={
                "idempotency_key": "v1-bounded-import",
                "queue_rows": queue_rows,
                "paper_rows": paper_rows,
            })
            self.assertEqual(imported.status_code, 200)

            with patch.object(ControlPlaneStore, "queue_rows", side_effect=AssertionError("legacy queue_rows should not be used")), \
                 patch.object(ControlPlaneStore, "paper_rows", side_effect=AssertionError("legacy paper_rows should not be used")), \
                 patch.object(ControlPlaneStore, "event_rows", side_effect=AssertionError("legacy event_rows should not be used")):
                overview = client.get("/control/api/v1/overview", headers=headers)
                self.assertEqual(overview.status_code, 200)
                self.assertEqual(overview.json()["counts"]["all"], 3)
                self.assertLessEqual(len(overview.json()["recent_events"]), 10)

                queue = client.get("/control/api/v1/queue?page_size=2", headers=headers)
                self.assertEqual(queue.status_code, 200)
                self.assertEqual(queue.json()["page"]["returned"], 2)
                self.assertTrue(queue.json()["page"]["has_more"])
                self.assertEqual(queue.json()["page"]["next_cursor"], "2")

                recent = client.get("/control/api/v1/queue?queue=all&page_size=2&sort=recent", headers=headers)
                self.assertEqual(recent.status_code, 200)
                self.assertEqual(recent.json()["page"]["filters"]["sort"], "recent")

                created = client.get("/control/api/v1/queue?queue=all&page_size=2&sort=created", headers=headers)
                self.assertEqual(created.status_code, 200)
                self.assertEqual(created.json()["page"]["filters"]["sort"], "created")

                papers = client.get("/control/api/v1/papers?page_size=2&sort=created", headers=headers)
                self.assertEqual(papers.status_code, 200)
                self.assertEqual(papers.json()["page"]["returned"], 2)
                self.assertEqual(papers.json()["page"]["filters"]["sort"], "created")
                self.assertNotIn("draft_markdown_path", papers.json()["rows"][0])
                self.assertIn("artifact_paths_present", papers.json()["rows"][0])

                events = client.get("/control/api/v1/events?page_size=2", headers=headers)
                self.assertEqual(events.status_code, 200)
                self.assertLessEqual(events.json()["page"]["returned"], 2)
                if events.json()["rows"]:
                    self.assertIn("payload_summary", events.json()["rows"][0])
                    self.assertNotIn("payload", events.json()["rows"][0])

                runs = client.get("/control/api/v1/runs?page_size=2&sort=state&search=project", headers=headers)
                self.assertEqual(runs.status_code, 200)
                self.assertLessEqual(runs.json()["page"]["returned"], 2)
                self.assertEqual(runs.json()["page"]["filters"]["sort"], "state")
                self.assertEqual(runs.json()["page"]["filters"]["search"], "project")

                event_filtered = client.get("/control/api/v1/events?page_size=2&sort=type&search=import", headers=headers)
                self.assertEqual(event_filtered.status_code, 200)
                self.assertEqual(event_filtered.json()["page"]["filters"]["sort"], "type")
                self.assertEqual(event_filtered.json()["page"]["filters"]["search"], "import")

    def test_dashboard_queue_filter_normalizes_status_and_manual_review_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            rows = [{
                "project_id": "queued-string-false",
                "project_name": "Queued String False",
                "status": "Queued",
                "manual_review_required": "false",
                "dispatch_priority": 1,
                "selection_rank": 1,
            }]

            with patch.object(ControlPlaneStore, "queue_rows", return_value=rows):
                queued = client.get("/control/api/queues/queued", headers=headers)
                blocked = client.get("/control/api/queues/blocked", headers=headers)

            self.assertEqual(queued.status_code, 200)
            self.assertEqual(blocked.status_code, 200)
            self.assertEqual(queued.json()["page"]["total"], 1)
            self.assertEqual(blocked.json()["page"]["total"], 0)

    def test_export_and_native_ideas_projection_endpoints(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            response = client.post("/control/import/legacy-snapshot", headers=headers, json={
                "idempotency_key": "import-router-snapshot",
                "queue_snapshot": {
                    "active_rows": [{
                        "project_id": "idea-active",
                        "project_name": "Active Project",
                        "queue_status": "awaiting_wake",
                        "current_run_id": "run-active",
                    }]
                },
                "paper_snapshot": {
                    "latest_rows": [{
                        "paper_id": "idea-active:run-active:arxiv_draft",
                        "project_id": "idea-active",
                        "run_id": "run-active",
                        "paper_status": "draft_review",
                    }]
                },
            })
            self.assertEqual(response.status_code, 200)

            ideas_projection = client.get("/control/projections/ideas/workbench", headers=headers)
            self.assertEqual(ideas_projection.status_code, 200)
            self.assertEqual(ideas_projection.json()["rows"][0]["queue_status"], "awaiting_wake")

            legacy_projection = client.get("/control/projections/notion/queue", headers=headers)
            self.assertEqual(legacy_projection.status_code, 410)

            exported = client.get("/control/export/snapshot", headers=headers)
            self.assertEqual(exported.status_code, 200)
            self.assertEqual(len(exported.json()["queue_rows"]), 1)
            self.assertEqual(len(exported.json()["paper_rows"]), 1)

            paused = client.post("/control/queue/mark-paused", headers=headers, json={
                "project_id": "idea-active",
                "reason": "verified no live process",
                "updated_by": "test",
            })
            self.assertEqual(paused.status_code, 200)
            self.assertFalse(paused.json()["active_items"])

    def test_legacy_notion_intake_and_projection_are_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            dry_run = client.post("/control/intake/notion-ideas", headers=headers, json={"dry_run": True, "notion_rows": []})
            self.assertEqual(dry_run.status_code, 410)
            self.assertIn("Supabase-native", dry_run.json()["detail"]["message"])

            projection = client.get("/control/projections/notion/execution-updates", headers=headers)
            self.assertEqual(projection.status_code, 410)

    def test_legacy_notion_intake_defaults_disabled_even_with_configured_worker_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _config(tmp).model_copy(update={"worker_wake_gate_url": "http://192.168.1.77:8787"})
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}

            response = client.post("/control/intake/notion-ideas", headers=headers, json={"idempotency_key": "router-notion-configured-worker", "dry_run": False, "notion_rows": []})

            self.assertEqual(response.status_code, 410)

    def test_supabase_native_ideas_intake_is_primary_dashboard_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _config(tmp).model_copy(update={"worker_wake_gate_url": "http://192.168.1.77:8787"})
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}

            response = client.post("/control/intake/ideas", headers=headers, json={
                "idempotency_key": "router-ideas-intake-1",
                "dry_run": False,
                "ideas": [{
                    "idea_id": "supabase-native-idea",
                    "title": "Supabase Native Idea",
                    "idea_status": "testing",
                    "priority": "High",
                    "selection_rank": 9,
                    "dispatch_priority": 8,
                }],
            })
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["created"], 1)
            self.assertEqual(response.json()["candidates"][0]["machine_target"], "192.168.1.77")

            intake = client.get("/control/api/intake/ideas", headers=headers)
            self.assertEqual(intake.status_code, 200)
            body = intake.json()
            self.assertEqual(body["source"], "control_api_intake_ideas")
            self.assertIn("Supabase-native ideas", body["authority"])
            self.assertTrue(any(row["idea_id"] == "supabase-native-idea" for row in body["queued_projection"]))

            projection = client.get("/control/projections/ideas/workbench", headers=headers)
            self.assertEqual(projection.status_code, 200)
            self.assertIn("testing", projection.json()["counts"])

    def test_ideas_intake_dashboard_falls_back_when_batched_parts_are_malformed(self) -> None:
        config = GateConfig(
            state_dir="/tmp/unused",
            project_root="/tmp/unused-projects",
            dispatch_script_path="/tmp/dispatch.sh",
            control_api_bearer_token=TOKEN,
            completion_callback_url="http://example.invalid/callback",
            completion_callback_token="unused",
            control_plane_store_backend="supabase",
            supabase_database_url="postgresql://example.invalid/postgres",
        )

        class FakeSupabaseStore:
            def dashboard_ideas_intake_parts(self, *, page_size: int = 50, include_latest_payload: bool = False):
                del page_size, include_latest_payload
                return None

            def latest_dashboard_observation(self, **_kwargs):
                return None

            def idea_workbench_projection(self, *, limit: int = 200):
                del limit
                return [{"idea_id": "fallback-idea", "title": "Fallback Idea", "idea_status": "testing"}]

            def event_rows(self, **_kwargs):
                return []

            def status_counts(self):
                return {"queued": 1}

        with patch("enoch_control_plane.control_plane.router.SupabaseControlPlaneStore", return_value=FakeSupabaseStore()):
            client = _client_with_config(config)
            response = client.get("/control/api/intake/ideas", headers={"Authorization": f"Bearer {TOKEN}"})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["projection_counts"]["queued"], 1)
        self.assertEqual(body["queued_projection"][0]["idea_id"], "fallback-idea")
        self.assertFalse(body["warnings"])

    def test_supabase_native_ideas_intake_live_rejects_readonly_before_store_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _live_config(tmp).model_copy(
                update={
                    "control_plane_store_backend": "supabase_readonly",
                    "supabase_database_url": "postgres://example",
                }
            )

            class FakeReadOnlyStore:
                def ingest_ideas(self, *_args, **_kwargs):  # noqa: ANN001 - must not be called
                    raise AssertionError("read-only ideas intake must reject before store writes")

            with patch("enoch_control_plane.control_plane.router.SupabaseReadOnlyControlPlaneStore", return_value=FakeReadOnlyStore()):
                client = _client_with_config(config)
                response = client.post(
                    "/control/intake/ideas",
                    headers={"Authorization": f"Bearer {TOKEN}"},
                    json={
                        "idempotency_key": "readonly-ideas-intake",
                        "dry_run": False,
                        "ideas": [{"idea_id": "idea-1", "title": "Idea 1", "idea_status": "testing"}],
                    },
                )

            self.assertEqual(response.status_code, 501)
            self.assertIn("writable control-plane store", response.text)

    def test_control_dashboard_html_is_served_without_token(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            response = client.get("/control/dashboard")
            self.assertEqual(response.status_code, 200)
            self.assertIn("Enoch Control Status", response.text)
            self.assertIn("Professional operator console", response.text)
            self.assertIn("/control/api/v1/overview", response.text)
            self.assertIn("/control/api/v1/observability/memory", response.text)
            self.assertIn("/control/api/v1/observability/health", response.text)
            self.assertIn("Work is idle", response.text)
            self.assertIn("Needs attention", response.text)
            self.assertIn("/control/api/intake/ideas", response.text)
            self.assertIn("Research Facility", response.text)
            self.assertIn("/control/api/research/facility", response.text)
            self.assertIn("/control/api/research/provider-budget", response.text)
            self.assertIn("/control/api/v1/automation-readiness", response.text)
            self.assertIn("Long-haul mode", response.text)
            self.assertIn("Automation readiness", response.text)
            self.assertIn("Research quality", response.text)
            self.assertIn("Check provider budget", response.text)
            self.assertIn("Generated candidates", response.text)
            self.assertIn("Admitted ideas", response.text)
            self.assertIn("Queued ideas", response.text)
            self.assertIn("checkProviderBudget", response.text)
            self.assertIn("Generate smoke batch", response.text)
            self.assertIn("generateResearchSmokeBatch", response.text)
            self.assertIn("/control/api/research/generate-batch", response.text)
            self.assertIn("This will not queue or dispatch work", response.text)
            self.assertIn("Provider-backed generation", response.text)
            self.assertIn("Generate provider batch", response.text)
            self.assertIn("generateProviderCandidateBatch", response.text)
            self.assertIn("/control/api/research/generate-provider-batch", response.text)
            self.assertIn("writes Research Facility ledgers only", response.text)
            self.assertIn("Research Autopilot", response.text)
            self.assertIn("Dry-run bounded cycle", response.text)
            self.assertIn("Run one bounded cycle", response.text)
            self.assertIn("/control/api/research/run-cycle", response.text)
            self.assertIn("runResearchCycle", response.text)
            self.assertIn("Promote selected candidate", response.text)
            self.assertIn("Admitted candidates", response.text)
            self.assertIn("Dry-run promote selected", response.text)
            self.assertIn("selectResearchCandidate", response.text)
            self.assertIn("candidate_action", response.text)
            self.assertIn("data-research-candidate-id", response.text)
            self.assertIn("selectResearchCandidate(this.dataset.researchCandidateId)", response.text)
            self.assertNotIn("selectResearchCandidate('${esc(r.candidate_id)}')", response.text)
            self.assertIn("promoteResearchCandidate", response.text)
            self.assertIn("researchCandidateId", response.text)
            self.assertIn("/control/api/research/promote-candidate", response.text)
            self.assertIn("it does not dispatch work", response.text)
            self.assertIn("Commands", response.text)
            self.assertIn("Pause queue", response.text)
            self.assertIn("Resume queue", response.text)
            self.assertIn("Check next dispatch", response.text)
            self.assertIn("Start next queued item", response.text)
            self.assertIn("Controlled one-off dispatch", response.text)
            self.assertIn("Dispatch selected queued project", response.text)
            self.assertIn("dispatchSelectedProject", response.text)
            self.assertIn("dispatchOneProjectId", response.text)
            self.assertIn("/control/state", response.text)
            self.assertIn("/control/pause", response.text)
            self.assertIn("/control/resume", response.text)
            self.assertIn("/control/dispatch-next", response.text)
            self.assertIn("/control/dispatch-one", response.text)
            self.assertIn("Start next does a dry-run first", response.text)
            self.assertIn('href="/control/dashboard.css"', response.text)
            self.assertNotIn("<style>", response.text)
            self.assertIn('<dialog id="confirmDialog"', response.text)
            self.assertIn("confirmAction(", response.text)
            self.assertIn("title+'\\n\\n'+message", response.text)
            self.assertNotIn("confirm(`", response.text)
            self.assertIn("copyToClipboard", response.text)
            self.assertIn('class="copy-button"', response.text)
            self.assertIn('class="sparkline ', response.text)
            self.assertIn("sparklineTrend", response.text)
            css_response = client.get("/control/dashboard.css")
            self.assertEqual(css_response.status_code, 200)
            self.assertIn("text/css", css_response.headers.get("content-type", ""))
            self.assertIn(".copy-button", css_response.text)
            self.assertIn(".sparkline", css_response.text)
            self.assertIn("dialog::backdrop", css_response.text)
            self.assertIn('enoch_control_plane = ["control_plane/*.css"]', Path("pyproject.toml").read_text(encoding="utf-8"))
            self.assertIn("Supabase idea workbench", response.text)
            self.assertNotIn("Notion Intake", response.text)
            self.assertNotIn(">Notion</a>", response.text)
            self.assertIn(">Source</a>", response.text)
            self.assertIn("Recent activity", response.text)
            self.assertIn("System health", response.text)
            self.assertIn("Loading overview", response.text)
            self.assertIn("Refreshing overview", response.text)
            self.assertIn("hasOverview=app?.dataset?.page===", response.text)
            self.assertIn("if(!hasOverview)", response.text)
            self.assertIn("dataset.page='overview'", response.text)
            self.assertIn("delete $('app').dataset.page", response.text)
            self.assertIn("Secondary health checks load after the primary cards render", response.text)
            self.assertIn("AbortController", response.text)
            self.assertIn("All projects", response.text)
            self.assertIn("Corpus Import", response.text)
            self.assertIn("Ledger-backed publication view", response.text)
            self.assertIn("Missing corpus import", response.text)
            self.assertIn("Already imported", response.text)
            self.assertIn("Recently added", response.text)
            self.assertIn("Recently updated", response.text)
            self.assertIn("200 per page", response.text)
            self.assertEqual(response.headers.get("cache-control"), "no-store")
            self.assertIn("cache:'no-store'", response.text)
            self.assertIn("autoRefreshCurrentPage", response.text)
            self.assertIn("h==='observability'", response.text)
            initial_app = response.text.split('<div id="app"', 1)[1].split('</main>', 1)[0]
            self.assertNotIn("<pre", initial_app)
            self.assertIn('class="app-shell"', response.text)
            self.assertIn('class="sidebar"', response.text)
            self.assertIn('id="globalSearch"', response.text)
            self.assertIn("globalSearch()", response.text)
            self.assertIn("Token required", response.text)
            self.assertIn("does not call authenticated APIs until a token is saved", response.text)
            self.assertIn("<details><summary>", response.text)
            self.assertNotIn("overview ·", response.text)
            self.assertNotIn("Recent event summaries", response.text)
            self.assertNotIn("source ${", response.text)
            self.assertNotIn("authority ${", response.text)

    def test_research_facility_provider_budget_sanitizes_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            quota = {
                "subscription": {"limit": 2500, "requests": 1, "renewsAt": "2026-05-10T00:00:00Z"},
                "weeklyTokenLimit": {"remainingCredits": "$119.77", "nextRegenAt": "2026-05-09T15:31:04Z"},
                "rollingFiveHourLimit": {"remaining": 2499, "max": 2500, "limited": False},
                "secret_echo": "synthetic-key-should-not-leak",
            }

            with patch("scripts.research_provider_budget.fetch_json", return_value=quota) as fetch:
                response = client.get(
                    "/control/api/research/provider-budget?estimated_requests=1&reserve_requests=2",
                    headers=headers,
                )

            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertTrue(body["ok"])
            self.assertEqual(body["auth_mode"], "exe_http_proxy")
            self.assertEqual(body["remaining_credits"], 119.77)
            self.assertEqual(body["rolling_remaining"], 2499)
            self.assertEqual(body["failures"], [])
            self.assertIsNone(body["payload_json"])
            self.assertNotIn("secret_echo", response.text)
            self.assertNotIn("synthetic-key-should-not-leak", response.text)
            self.assertNotIn("Authorization", response.text)
            fetch.assert_called_once()
            _, kwargs = fetch.call_args
            self.assertEqual(kwargs["api_key"], "")

    def test_research_facility_provider_budget_fails_safely_without_secret(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            headers = {"Authorization": f"Bearer {TOKEN}"}

            with patch("scripts.research_provider_budget.fetch_json", side_effect=RuntimeError("quota unavailable")):
                response = client.get("/control/api/research/provider-budget", headers=headers)

            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertFalse(body["ok"])
            self.assertEqual(body["auth_mode"], "exe_http_proxy")
            self.assertIn("provider budget check failed", body["failures"][0])
            self.assertNotIn("api_key", response.text.lower())
            self.assertNotIn("bearer", response.text.lower())

    def test_research_facility_api_returns_ledger_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            response = client.get("/control/api/research/facility", headers=headers)
            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertTrue(body["ok"])
            self.assertIn("Research Facility ledgers", body["authority"])
            self.assertEqual(body["rows"], [])
            self.assertEqual(body["counts"], {})

    def test_research_facility_api_counts_are_total_not_page_rows(self) -> None:
        class FakeSupabaseStore:
            def research_facility_workbench_projection(self, *, limit: int = 200) -> list[dict[str, str]]:
                return [{"candidate_id": "newest-admitted", "status": "admitted"}]

            def research_facility_workbench_counts(self) -> dict[str, int]:
                return {"admitted": 104, "needs_review": 34}

        with tempfile.TemporaryDirectory() as tmp:
            config = _config(tmp).model_copy(
                update={
                    "control_plane_store_backend": "supabase",
                    "supabase_database_url": "postgresql://example.invalid/postgres",
                }
            )
            headers = {"Authorization": f"Bearer {TOKEN}"}
            with patch("enoch_control_plane.control_plane.router.SupabaseControlPlaneStore", return_value=FakeSupabaseStore()):
                client = _client_with_config(config)
                response = client.get("/control/api/research/facility?page_size=1", headers=headers)

            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertEqual(body["page"]["returned"], 1)
            self.assertEqual(body["page"]["counts_scope"], "all_rows")
            self.assertEqual(body["counts"], {"admitted": 104, "needs_review": 34})

    def test_research_facility_generate_batch_dry_run_does_not_queue_or_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            response = client.post(
                "/control/api/research/generate-batch",
                headers=headers,
                json={"dry_run": True, "max_candidates": 2, "requested_by": "pytest"},
            )
            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertTrue(body["ok"])
            self.assertEqual(body["action"], "dry_run_generate_candidates")
            self.assertTrue(body["dry_run"])
            self.assertFalse(body["queue_admitted"])
            self.assertEqual(body["candidate_count"], 2)
            self.assertEqual(body["queued_count"], 0)
            self.assertIn("plans", body)
            self.assertNotIn("ledger_result", body)
            state = client.get("/control/state", headers=headers).json()
            self.assertEqual(state["counts"].get("queued", 0), 0)
            self.assertEqual(state["counts"].get("active", 0), 0)

    def test_research_facility_generate_batch_live_requires_supabase_store(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            response = client.post(
                "/control/api/research/generate-batch",
                headers=headers,
                json={"dry_run": False, "max_candidates": 1, "requested_by": "pytest"},
            )
            self.assertEqual(response.status_code, 501)
            self.assertIn("Supabase control-plane store", response.text)

    def test_research_facility_generate_batch_live_rejects_readonly_before_ledger_work(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _live_config(tmp).model_copy(
                update={
                    "control_plane_store_backend": "supabase_readonly",
                    "supabase_database_url": "postgres://example",
                }
            )

            class FakeReadOnlyStore:
                def record_research_facility_plans(self, *_args, **_kwargs):  # noqa: ANN001 - must not be called
                    raise AssertionError("read-only candidate generation must reject before ledger writes")

            with patch("enoch_control_plane.control_plane.router.SupabaseReadOnlyControlPlaneStore", return_value=FakeReadOnlyStore()):
                client = _client_with_config(config)
                response = client.post(
                    "/control/api/research/generate-batch",
                    headers={"Authorization": f"Bearer {TOKEN}"},
                    json={"dry_run": False, "max_candidates": 1, "requested_by": "pytest"},
                )

            self.assertEqual(response.status_code, 501)
            self.assertIn("writable control-plane store", response.text)

    def test_research_facility_provider_generate_dry_run_checks_budget_without_provider_spend(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            quota = {
                "subscription": {"limit": 2500, "requests": 0},
                "weeklyTokenLimit": {"remainingCredits": "$119.77"},
                "rollingFiveHourLimit": {"remaining": 2500, "max": 2500, "limited": False},
            }

            with patch("scripts.research_provider_budget.fetch_json", return_value=quota), \
                 patch("scripts.research_provider_generate.generate_provider_candidates") as generate:
                response = client.post(
                    "/control/api/research/generate-provider-batch",
                    headers=headers,
                    json={"dry_run": True, "max_candidates": 2, "requested_by": "pytest"},
                )

            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertTrue(body["ok"])
            self.assertEqual(body["action"], "dry_run_provider_generate_candidates")
            self.assertFalse(body["queue_admitted"])
            self.assertFalse(body["dispatch_started"])
            self.assertEqual(body["queued_count"], 0)
            self.assertIn("budget", body)
            generate.assert_not_called()

    def test_research_facility_provider_generate_fails_closed_when_budget_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            headers = {"Authorization": f"Bearer {TOKEN}"}

            with patch("scripts.research_provider_budget.fetch_json", side_effect=RuntimeError("quota down")), \
                 patch("scripts.research_provider_generate.generate_provider_candidates") as generate:
                response = client.post(
                    "/control/api/research/generate-provider-batch",
                    headers=headers,
                    json={"dry_run": False, "max_candidates": 1, "requested_by": "pytest"},
                )

            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertFalse(body["ok"])
            self.assertEqual(body["action"], "provider_generation_blocked")
            self.assertIn("quota down", body["reason"])
            generate.assert_not_called()

    def test_research_facility_provider_generate_live_rejects_readonly_before_budget_or_spend(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _live_config(tmp).model_copy(
                update={
                    "control_plane_store_backend": "supabase_readonly",
                    "supabase_database_url": "postgres://example",
                }
            )

            class FakeReadOnlyStore:
                pass

            with patch("enoch_control_plane.control_plane.router.SupabaseReadOnlyControlPlaneStore", return_value=FakeReadOnlyStore()), \
                 patch("scripts.research_provider_budget.fetch_json", side_effect=AssertionError("budget check must not run on readonly live generation")), \
                 patch("scripts.research_provider_generate.generate_provider_candidates", side_effect=AssertionError("provider spend must not run on readonly live generation")):
                client = _client_with_config(config)
                response = client.post(
                    "/control/api/research/generate-provider-batch",
                    headers={"Authorization": f"Bearer {TOKEN}"},
                    json={"dry_run": False, "max_candidates": 1, "requested_by": "pytest"},
                )

            self.assertEqual(response.status_code, 501)
            self.assertIn("writable control-plane store", response.text)

    def test_research_facility_provider_generate_live_writes_ledgers_only_with_supabase_store(self) -> None:
        class FakeSupabaseStore:
            def __init__(self) -> None:
                self.recorded = []

            def research_facility_workbench_projection(self, *, limit: int = 200) -> list[dict[str, str]]:
                return []

            def record_research_facility_plans(self, plans, *, requested_by: str, queue_admitted: bool = False) -> dict[str, int]:
                self.recorded.append((plans, requested_by, queue_admitted))
                return {"sources_upserted": 1, "candidates_upserted": len(plans), "admissions_inserted": len(plans), "lineage_inserted": 1}

        fake_store = FakeSupabaseStore()
        config = GateConfig(
            state_dir="/tmp/unused",
            project_root="/tmp/unused-projects",
            dispatch_script_path="/tmp/dispatch.sh",
            control_api_bearer_token=TOKEN,
            completion_callback_url="http://example.invalid/callback",
            completion_callback_token="unused",
            control_plane_store_backend="supabase",
            supabase_database_url="postgresql://example.invalid/postgres",
        )
        quota = {
            "subscription": {"limit": 2500, "requests": 0},
            "weeklyTokenLimit": {"remainingCredits": "$119.77"},
            "rollingFiveHourLimit": {"remaining": 2500, "max": 2500, "limited": False},
        }
        generated_candidate = {
            "title": "Provider Candidate",
            "generation_mode": "moonshot",
            "category": "distributed-training",
            "priority": "High",
            "source_kind": "internal_generated",
            "source_ids": ["provider-source"],
            "source_urls": ["enoch://provider/test"],
            "source_records": [{"source_id": "provider-source", "source_kind": "internal_generated", "title": "provider", "url": "enoch://provider/test"}],
            "hypothesis": "A bounded volunteer-training audit can reject stale updates under low communication.",
            "mechanism": "Use random gradient-slice probes before aggregation.",
            "description": "Provider generated candidate.",
            "implementation": "Simulate workers and injected adversaries, then compare against unchecked DiLoCo.",
            "baseline_to_beat": "Unchecked DiLoCo and FedAvg.",
            "success_threshold": "Detect at least 80 percent of stale updates with under 10 percent false positives.",
            "kill_condition": "Stop if probes miss replay attacks or communication overhead exceeds 1.5x.",
            "accessibility_delta": "Could make home volunteer training safer.",
            "expected_artifacts": ["run_notes.md", "metrics.json", "failure_cases.json", ".enoch/project_decision.json"],
            "required_evidence": ["baseline comparison", "metrics table", "failure cases", "decision artifact"],
            "likely_failure_modes": ["overhead too high", "adversaries evade probes", "false positives"],
            "estimated_runtime_class": "medium",
            "expected_token_budget": "medium",
            "machine_target": "192.168.1.77",
            "model": "gpt-5.5",
            "sandbox": "danger-full-access",
            "novelty_score": 8,
            "feasibility_score": 7,
            "accessibility_score": 8,
            "falsifiability_score": 8,
            "novelty_comparison": "Different from generic distributed training because it audits stale updates with low-bandwidth probes.",
            "risk_notes": "Simulation may not transfer to real volunteer nodes.",
        }
        with patch("enoch_control_plane.control_plane.router.SupabaseControlPlaneStore", return_value=fake_store), \
             patch("scripts.research_provider_budget.fetch_json", return_value=quota), \
             patch("scripts.research_provider_generate.generate_provider_candidates", return_value={"ok": True, "provider_response_id": "cmpl-test", "candidates": [generated_candidate]}) as generate:
            client = _client_with_config(config)
            response = client.post(
                "/control/api/research/generate-provider-batch",
                headers={"Authorization": f"Bearer {TOKEN}"},
                json={"dry_run": False, "max_candidates": 1, "generation_max_tokens": 9000, "generation_attempts": 3, "requested_by": "pytest"},
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["action"], "provider_generate_candidates")
        self.assertEqual(body["generation_max_tokens"], 9000)
        self.assertEqual(body["generation_attempts"], 3)
        self.assertEqual(generate.call_args.kwargs["max_tokens"], 9000)
        self.assertEqual(generate.call_args.kwargs["attempts"], 3)
        self.assertFalse(body["queue_admitted"])
        self.assertFalse(body["dispatch_started"])
        self.assertEqual(body["queued_count"], 0)
        self.assertEqual(body["candidate_count"], 1)
        self.assertEqual(body["provider_response_id"], "cmpl-test")
        self.assertEqual(len(fake_store.recorded), 1)
        _, requested_by, queue_admitted = fake_store.recorded[0]
        self.assertEqual(requested_by, "pytest")
        self.assertFalse(queue_admitted)

    def test_research_facility_provider_generate_failure_does_not_write_ledgers(self) -> None:
        class FakeSupabaseStore:
            def record_research_facility_plans(self, *_args, **_kwargs):  # pragma: no cover - should not be called
                raise AssertionError("ledger write should not run when provider generation fails")

        config = GateConfig(
            state_dir="/tmp/unused",
            project_root="/tmp/unused-projects",
            dispatch_script_path="/tmp/dispatch.sh",
            control_api_bearer_token=TOKEN,
            completion_callback_url="http://example.invalid/callback",
            completion_callback_token="unused",
            control_plane_store_backend="supabase",
            supabase_database_url="postgresql://example.invalid/postgres",
        )
        quota = {
            "subscription": {"limit": 2500, "requests": 0},
            "weeklyTokenLimit": {"remainingCredits": "$119.77"},
            "rollingFiveHourLimit": {"remaining": 2500, "max": 2500, "limited": False},
        }
        with patch("enoch_control_plane.control_plane.router.SupabaseControlPlaneStore", return_value=FakeSupabaseStore()), \
             patch("scripts.research_provider_budget.fetch_json", return_value=quota), \
             patch("scripts.research_provider_generate.generate_provider_candidates", side_effect=ValueError("invalid provider JSON")):
            client = _client_with_config(config)
            response = client.post(
                "/control/api/research/generate-provider-batch",
                headers={"Authorization": f"Bearer {TOKEN}"},
                json={"dry_run": False, "max_candidates": 1, "requested_by": "pytest"},
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertFalse(body["ok"])
        self.assertEqual(body["action"], "provider_generation_failed")
        self.assertIn("invalid provider JSON", body["reason"])
        self.assertEqual(body["queued_count"], 0)
        self.assertFalse(body["dispatch_started"])

    def test_research_facility_provider_generate_zero_candidates_does_not_write_ledgers(self) -> None:
        class FakeSupabaseStore:
            def record_research_facility_plans(self, *_args, **_kwargs):  # pragma: no cover - should not be called
                raise AssertionError("ledger write should not run when provider returns zero candidates")

        config = GateConfig(
            state_dir="/tmp/unused",
            project_root="/tmp/unused-projects",
            dispatch_script_path="/tmp/dispatch.sh",
            control_api_bearer_token=TOKEN,
            completion_callback_url="http://example.invalid/callback",
            completion_callback_token="unused",
            control_plane_store_backend="supabase",
            supabase_database_url="postgresql://example.invalid/postgres",
        )
        quota = {
            "subscription": {"limit": 2500, "requests": 0},
            "weeklyTokenLimit": {"remainingCredits": "$119.77"},
            "rollingFiveHourLimit": {"remaining": 2500, "max": 2500, "limited": False},
        }
        with patch("enoch_control_plane.control_plane.router.SupabaseControlPlaneStore", return_value=FakeSupabaseStore()), \
             patch("scripts.research_provider_budget.fetch_json", return_value=quota), \
             patch("scripts.research_provider_generate.generate_provider_candidates", return_value={"ok": True, "provider_response_id": "cmpl-empty", "candidates": []}):
            client = _client_with_config(config)
            response = client.post(
                "/control/api/research/generate-provider-batch",
                headers={"Authorization": f"Bearer {TOKEN}"},
                json={"dry_run": False, "max_candidates": 1, "requested_by": "pytest"},
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertFalse(body["ok"])
        self.assertEqual(body["action"], "provider_generation_failed")
        self.assertIn("0 usable candidates", body["reason"])
        self.assertEqual(body["provider_response_id"], "cmpl-empty")
        self.assertEqual(body["candidate_count"], 0)
        self.assertEqual(body["queued_count"], 0)
        self.assertFalse(body["dispatch_started"])

    def test_research_facility_run_cycle_dry_run_checks_budget_without_spend_or_writes(self) -> None:
        class FakeSupabaseStore:
            def __init__(self) -> None:
                self.events = []

            def active_items(self) -> list[dict[str, str]]:
                return []

            def status_counts(self) -> dict[str, int]:
                return {"blocked": 0, "queued": 0, "active": 0}

            def research_facility_workbench_projection(self, *, limit: int = 100) -> list[dict[str, str]]:
                return [{"candidate_id": "candidate-ready", "admission_decision": "admitted", "admitted_idea_id": "", "total_score": "80.00"}]

            def record_research_facility_plans(self, *_args, **_kwargs):  # pragma: no cover - dry-run must not write
                raise AssertionError("dry-run should not write ledgers")

            def promote_research_candidate(self, *_args, **_kwargs):  # pragma: no cover - dry-run must not promote
                raise AssertionError("dry-run should not promote")

            def append_event(self, **kwargs):
                self.events.append(kwargs)
                return 1, True

        fake_store = FakeSupabaseStore()
        config = GateConfig(
            state_dir="/tmp/unused",
            project_root="/tmp/unused-projects",
            dispatch_script_path="/tmp/dispatch.sh",
            control_api_bearer_token=TOKEN,
            completion_callback_url="http://example.invalid/callback",
            completion_callback_token="unused",
            control_plane_store_backend="supabase",
            supabase_database_url="postgresql://example.invalid/postgres",
        )
        quota = {
            "subscription": {"limit": 2500, "requests": 0},
            "weeklyTokenLimit": {"remainingCredits": "$119.77"},
            "rollingFiveHourLimit": {"remaining": 2500, "max": 2500, "limited": False},
        }
        with patch("enoch_control_plane.control_plane.router.SupabaseControlPlaneStore", return_value=fake_store), \
             patch("scripts.research_provider_budget.fetch_json", return_value=quota), \
             patch("scripts.research_provider_generate.generate_provider_candidates") as generate:
            client = _client_with_config(config)
            response = client.post(
                "/control/api/research/run-cycle",
                headers={"Authorization": f"Bearer {TOKEN}"},
                json={"dry_run": True, "requested_by": "pytest"},
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["action"], "dry_run_research_cycle")
        self.assertEqual(body["planned_promotions"], ["candidate-ready"])
        self.assertTrue(body["would_generate"])
        self.assertFalse(body["dispatch_started"])
        self.assertEqual(body["queued_count"], 0)
        generate.assert_not_called()
        self.assertEqual(fake_store.events[0]["event_type"], "research.run_cycle.dry_run")

    def test_research_facility_run_cycle_ignores_empty_allowed_model_list(self) -> None:
        class FakeSupabaseStore:
            def __init__(self) -> None:
                self.events = []

            def active_items(self) -> list[dict[str, str]]:
                return []

            def status_counts(self) -> dict[str, int]:
                return {"blocked": 0, "queued": 0, "active": 0}

            def research_facility_workbench_projection(self, *, limit: int = 100) -> list[dict[str, str]]:
                return []

            def record_research_facility_plans(self, *_args, **_kwargs):  # pragma: no cover - dry-run must not write
                raise AssertionError("dry-run should not write ledgers")

            def promote_research_candidate(self, *_args, **_kwargs):  # pragma: no cover - dry-run must not promote
                raise AssertionError("dry-run should not promote")

            def append_event(self, **kwargs):
                self.events.append(kwargs)
                return 1, True

        config = GateConfig(
            state_dir="/tmp/unused",
            project_root="/tmp/unused-projects",
            dispatch_script_path="/tmp/dispatch.sh",
            control_api_bearer_token=TOKEN,
            completion_callback_url="http://example.invalid/callback",
            completion_callback_token="unused",
            control_plane_store_backend="supabase",
            supabase_database_url="postgresql://example.invalid/postgres",
        )
        quota = {
            "subscription": {"limit": 2500, "requests": 0},
            "weeklyTokenLimit": {"remainingCredits": "$119.77"},
            "rollingFiveHourLimit": {"remaining": 2500, "max": 2500, "limited": False},
        }
        with patch("enoch_control_plane.control_plane.router.SupabaseControlPlaneStore", return_value=FakeSupabaseStore()), \
             patch("scripts.research_provider_budget.fetch_json", return_value=quota), \
             patch("scripts.research_provider_generate.generate_provider_candidates") as generate:
            client = _client_with_config(config)
            response = client.post(
                "/control/api/research/run-cycle",
                headers={"Authorization": f"Bearer {TOKEN}"},
                json={"dry_run": True, "allowed_models": ["", None], "requested_by": "pytest"},
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertNotEqual(body["action"], "research_cycle_blocked")
        generate.assert_not_called()

    def test_research_facility_run_cycle_live_rejects_readonly_before_budget_or_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _live_config(tmp).model_copy(
                update={
                    "control_plane_store_backend": "supabase_readonly",
                    "supabase_database_url": "postgres://example",
                }
            )

            class FakeReadOnlyStore:
                def append_event(self, **_kwargs):  # noqa: ANN003 - must not be called
                    raise AssertionError("read-only run-cycle must reject before event writes")

            with patch("enoch_control_plane.control_plane.router.SupabaseReadOnlyControlPlaneStore", return_value=FakeReadOnlyStore()), \
                 patch("scripts.research_provider_budget.fetch_json", side_effect=AssertionError("budget check must not run on readonly live run-cycle")), \
                 patch("scripts.research_provider_generate.generate_provider_candidates", side_effect=AssertionError("provider spend must not run on readonly live run-cycle")):
                client = _client_with_config(config)
                response = client.post(
                    "/control/api/research/run-cycle",
                    headers={"Authorization": f"Bearer {TOKEN}"},
                    json={"dry_run": False, "enabled": True, "requested_by": "pytest"},
                )

            self.assertEqual(response.status_code, 501)
            self.assertIn("writable control-plane store", response.text)

    def test_research_facility_promote_candidate_live_rejects_readonly_before_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _live_config(tmp).model_copy(
                update={
                    "control_plane_store_backend": "supabase_readonly",
                    "supabase_database_url": "postgres://example",
                }
            )

            class FakeReadOnlyStore:
                def promote_research_candidate(self, *_args, **_kwargs):  # noqa: ANN001 - must not be called
                    raise AssertionError("read-only candidate promotion must reject before mutation")

            with patch("enoch_control_plane.control_plane.router.SupabaseReadOnlyControlPlaneStore", return_value=FakeReadOnlyStore()):
                client = _client_with_config(config)
                response = client.post(
                    "/control/api/research/promote-candidate",
                    headers={"Authorization": f"Bearer {TOKEN}"},
                    json={"dry_run": False, "candidate_id": "candidate-1", "requested_by": "pytest"},
                )

            self.assertEqual(response.status_code, 501)
            self.assertIn("writable control-plane store", response.text)

    def test_research_generate_batch_tolerates_malformed_numeric_knobs(self) -> None:
        config = GateConfig(
            state_dir="/tmp/unused",
            project_root="/tmp/unused-projects",
            dispatch_script_path="/tmp/dispatch.sh",
            control_api_bearer_token=TOKEN,
            completion_callback_url="http://example.invalid/callback",
            completion_callback_token="unused",
        )
        client = _client_with_config(config)
        response = client.post(
            "/control/api/research/generate-batch",
            headers={"Authorization": f"Bearer {TOKEN}"},
            json={"dry_run": True, "max_candidates": "bad", "admit_threshold": "bad", "review_threshold": "bad"},
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["candidate_count"], 3)

    def test_research_provider_generate_batch_tolerates_malformed_numeric_knobs(self) -> None:
        class FakeSupabaseStore:
            def record_research_facility_plans(self, *_args, **_kwargs):  # pragma: no cover - dry-run must not write
                raise AssertionError("dry-run should not write ledgers")

        config = GateConfig(
            state_dir="/tmp/unused",
            project_root="/tmp/unused-projects",
            dispatch_script_path="/tmp/dispatch.sh",
            control_api_bearer_token=TOKEN,
            completion_callback_url="http://example.invalid/callback",
            completion_callback_token="unused",
            control_plane_store_backend="supabase",
            supabase_database_url="postgresql://example.invalid/postgres",
        )
        quota = {
            "subscription": {"limit": 2500, "requests": 0},
            "weeklyTokenLimit": {"remainingCredits": "$119.77"},
            "rollingFiveHourLimit": {"remaining": 2500, "max": 2500, "limited": False},
        }
        with patch("enoch_control_plane.control_plane.router.SupabaseControlPlaneStore", return_value=FakeSupabaseStore()), \
             patch("scripts.research_provider_budget.fetch_json", return_value=quota):
            client = _client_with_config(config)
            response = client.post(
                "/control/api/research/generate-provider-batch",
                headers={"Authorization": f"Bearer {TOKEN}"},
                json={
                    "dry_run": True,
                    "max_candidates": "bad",
                    "temperature": "bad",
                    "reserve_requests": "bad",
                    "budget_timeout": "bad",
                    "generation_timeout": "bad",
                    "generation_max_tokens": "bad",
                    "generation_attempts": "bad",
                    "min_remaining_credits": "bad",
                    "min_rolling_remaining": "bad",
                },
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["max_candidates"], 2)
        self.assertEqual(body["temperature"], 0.8)
        self.assertEqual(body["generation_max_tokens"], 8000)
        self.assertEqual(body["generation_attempts"], 2)

    def test_research_facility_run_cycle_tolerates_malformed_numeric_knobs(self) -> None:
        class FakeSupabaseStore:
            def __init__(self) -> None:
                self.events = []

            def active_items(self) -> list[dict[str, str]]:
                return []

            def status_counts(self) -> dict[str, int]:
                return {"blocked": 0, "queued": 0, "active": 0}

            def research_facility_workbench_projection(self, *, limit: int = 100) -> list[dict[str, str]]:
                return []

            def record_research_facility_plans(self, *_args, **_kwargs):  # pragma: no cover - dry run must not write
                raise AssertionError("dry-run should not write ledgers")

            def promote_research_candidate(self, *_args, **_kwargs):  # pragma: no cover - dry run must not promote
                raise AssertionError("dry-run should not promote")

            def append_event(self, **kwargs):
                self.events.append(kwargs)
                return 1, True

        fake_store = FakeSupabaseStore()
        config = GateConfig(
            state_dir="/tmp/unused",
            project_root="/tmp/unused-projects",
            dispatch_script_path="/tmp/dispatch.sh",
            control_api_bearer_token=TOKEN,
            completion_callback_url="http://example.invalid/callback",
            completion_callback_token="unused",
            control_plane_store_backend="supabase",
            supabase_database_url="postgresql://example.invalid/postgres",
        )
        quota = {
            "subscription": {"limit": 2500, "requests": 0},
            "weeklyTokenLimit": {"remainingCredits": "$119.77"},
            "rollingFiveHourLimit": {"remaining": 2500, "max": 2500, "limited": False},
        }
        with patch("enoch_control_plane.control_plane.router.SupabaseControlPlaneStore", return_value=fake_store), \
             patch("scripts.research_provider_budget.fetch_json", return_value=quota):
            client = _client_with_config(config)
            response = client.post(
                "/control/api/research/run-cycle",
                headers={"Authorization": f"Bearer {TOKEN}"},
                json={
                    "dry_run": True,
                    "max_provider_requests_per_run": "not-an-int",
                    "max_promotions_per_run": None,
                    "max_wait_seconds": "bad",
                    "poll_interval_seconds": "also-bad",
                    "min_admission_score": "bad-float",
                    "max_candidates": "bad",
                    "generation_timeout": "bad",
                    "generation_max_tokens": "bad",
                    "generation_attempts": "bad",
                    "fresh_generation_backlog_threshold": "bad",
                    "temperature": "bad",
                    "budget_timeout": "bad",
                    "reserve_requests": "bad",
                    "min_remaining_credits": "bad",
                    "min_rolling_remaining": "bad",
                    "review_threshold": "bad",
                    "requested_by": "pytest",
                },
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["policy"]["max_provider_requests_per_run"], 1)
        self.assertEqual(body["policy"]["max_promotions_per_run"], 1)
        self.assertEqual(body["policy"]["min_admission_score"], 72.0)
        self.assertTrue(body["would_generate"])

    def test_research_facility_run_cycle_backpressure_event_is_bucketed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "state" / "control_plane.sqlite3"

            class FakeSupabaseStore(ControlPlaneStore):
                def research_facility_workbench_projection(self, *, limit: int = 100) -> list[dict[str, str]]:
                    return []

                def record_research_facility_plans(self, *_args, **_kwargs):  # pragma: no cover - backpressure returns before writes
                    raise AssertionError("backpressure should not write ledgers")

                def promote_research_candidate(self, *_args, **_kwargs):  # pragma: no cover - backpressure returns before promotion
                    raise AssertionError("backpressure should not promote")

            fake_store = FakeSupabaseStore(db_path)
            config = GateConfig(
                state_dir=str(Path(tmp) / "state"),
                project_root=str(Path(tmp) / "projects"),
                dispatch_script_path="/tmp/dispatch.sh",
                control_api_bearer_token=TOKEN,
                completion_callback_url="http://example.invalid/callback",
                completion_callback_token="unused",
                control_plane_store_backend="supabase",
                supabase_database_url="postgresql://example.invalid/postgres",
            )
            headers = {"Authorization": f"Bearer {TOKEN}"}
            quota = {
                "subscription": {"limit": 2500, "requests": 0},
                "weeklyTokenLimit": {"remainingCredits": "$119.77"},
                "rollingFiveHourLimit": {"remaining": 2500, "max": 2500, "limited": False},
            }
            with patch("enoch_control_plane.control_plane.router.SupabaseControlPlaneStore", return_value=fake_store), \
                 patch("scripts.research_provider_budget.fetch_json", return_value=quota):
                client = _client_with_config(config)
                client.post("/control/import/legacy-snapshot", headers=headers, json={
                    "idempotency_key": "research-backpressure-import",
                    "queue_rows": [{
                        "project_id": "active-research",
                        "project_name": "Active Research",
                        "project_dir": "active-research",
                        "status": "awaiting_wake",
                        "current_run_id": "run-active-research",
                    }],
                })
                for _ in range(2):
                    response = client.post(
                        "/control/api/research/run-cycle",
                        headers=headers,
                        json={"dry_run": False, "enabled": True, "requested_by": "pytest"},
                    )
                    self.assertEqual(response.status_code, 200)
                    self.assertTrue(response.json()["backpressure"])

            events = fake_store.event_rows(event_type="research.run_cycle.backpressure")
            self.assertEqual(len(events), 1)

    def test_research_facility_backpressure_event_idempotency_conflict_still_returns_ok(self) -> None:
        class ConflictStore:
            def flags(self):
                return SimpleNamespace(queue_paused=False)

            def active_items(self) -> list[dict[str, str]]:
                return [{"project_id": "active-research", "status": "awaiting_wake", "current_run_id": "run-active"}]

            def status_counts(self) -> dict[str, int]:
                return {"blocked": 0, "queued": 0, "active": 1}

            def research_facility_workbench_projection(self, *, limit: int = 100) -> list[dict[str, str]]:
                return []

            def record_research_facility_plans(self, *_args, **_kwargs):
                raise AssertionError("backpressure should stop before generation")

            def promote_research_candidate(self, *_args, **_kwargs):
                raise AssertionError("backpressure should stop before promotion")

            def append_event(self, **_kwargs):
                raise IdempotencyConflict("duplicate backpressure event with changed volatile payload")

        config = GateConfig(
            state_dir="/tmp/unused",
            project_root="/tmp/unused-projects",
            dispatch_script_path="/tmp/dispatch.sh",
            control_api_bearer_token=TOKEN,
            completion_callback_url="http://example.invalid/callback",
            completion_callback_token="unused",
            control_plane_store_backend="supabase",
            supabase_database_url="postgresql://example.invalid/postgres",
        )
        quota = {
            "subscription": {"limit": 2500, "requests": 0},
            "weeklyTokenLimit": {"remainingCredits": "$119.77"},
            "rollingFiveHourLimit": {"remaining": 2500, "max": 2500, "limited": False},
        }
        with patch("enoch_control_plane.control_plane.router.SupabaseControlPlaneStore", return_value=ConflictStore()), \
             patch("scripts.research_provider_budget.fetch_json", return_value=quota):
            client = _client_with_config(config)
            response = client.post(
                "/control/api/research/run-cycle",
                headers={"Authorization": f"Bearer {TOKEN}"},
                json={"dry_run": False, "enabled": True, "requested_by": "pytest"},
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertTrue(body["backpressure"])
        self.assertEqual(body["reason"], "active worker lane already exists")

    def test_research_facility_run_cycle_live_generates_and_promotes_without_dispatch(self) -> None:
        class FakeSupabaseStore:
            def __init__(self) -> None:
                self.events = []
                self.recorded = []
                self.promoted = []
                self.generated_available = False

            def active_items(self) -> list[dict[str, str]]:
                return []

            def status_counts(self) -> dict[str, int]:
                return {"blocked": 0, "queued": 0, "active": 0}

            def research_facility_workbench_projection(self, *, limit: int = 100) -> list[dict[str, str]]:
                if not self.generated_available:
                    return []
                return [{"candidate_id": "generated-candidate", "admission_decision": "admitted", "admitted_idea_id": "", "total_score": "82.00"}]

            def record_research_facility_plans(self, plans, *, requested_by: str, queue_admitted: bool = False) -> dict[str, int]:
                self.generated_available = True
                self.recorded.append((plans, requested_by, queue_admitted))
                return {"sources_upserted": 1, "candidates_upserted": len(plans), "admissions_inserted": len(plans), "lineage_inserted": 1}

            def promote_research_candidate(self, candidate_id: str, *, requested_by: str, dry_run: bool = True) -> dict[str, object]:
                self.promoted.append((candidate_id, requested_by, dry_run))
                return {"ok": True, "action": "promote_candidate", "candidate_id": candidate_id, "idea_id": candidate_id, "queued_count": 1, "dispatch_started": False}

            def append_event(self, **kwargs):
                self.events.append(kwargs)
                return 1, True

        fake_store = FakeSupabaseStore()
        config = GateConfig(
            state_dir="/tmp/unused",
            project_root="/tmp/unused-projects",
            dispatch_script_path="/tmp/dispatch.sh",
            control_api_bearer_token=TOKEN,
            completion_callback_url="http://example.invalid/callback",
            completion_callback_token="unused",
            control_plane_store_backend="supabase",
            supabase_database_url="postgresql://example.invalid/postgres",
        )
        quota = {
            "subscription": {"limit": 2500, "requests": 0},
            "weeklyTokenLimit": {"remainingCredits": "$119.77"},
            "rollingFiveHourLimit": {"remaining": 2500, "max": 2500, "limited": False},
        }
        generated_candidate = {
            "title": "Generated Candidate",
            "generation_mode": "moonshot",
            "category": "quantization",
            "priority": "High",
            "source_kind": "internal_generated",
            "source_ids": ["provider-source"],
            "source_urls": ["enoch://provider/test"],
            "source_records": [{"source_id": "provider-source", "source_kind": "internal_generated", "title": "provider", "url": "enoch://provider/test"}],
            "hypothesis": "A bounded local quantization experiment can reduce VRAM with measured quality tradeoffs.",
            "mechanism": "Use learned residual quantization and compare against int4 baselines.",
            "description": "Provider generated candidate.",
            "implementation": "Run a small local benchmark and record metrics, failure cases, and decision artifact.",
            "baseline_to_beat": "Uniform int4 quantization.",
            "success_threshold": "Beat int4 memory at comparable quality.",
            "kill_condition": "Stop if quality collapses or runtime exceeds baseline by 2x.",
            "accessibility_delta": "Could reduce local VRAM requirements.",
            "expected_artifacts": ["run_notes.md", "metrics.json", "failure_cases.json", ".enoch/project_decision.json"],
            "required_evidence": ["baseline comparison", "metrics table", "failure cases", "decision artifact"],
            "likely_failure_modes": ["quality collapse", "runtime overhead"],
            "estimated_runtime_class": "medium",
            "expected_token_budget": "medium",
            "machine_target": "192.168.1.77",
            "model": "gpt-5.5",
            "sandbox": "danger-full-access",
            "novelty_score": 8,
            "feasibility_score": 7,
            "accessibility_score": 8,
            "falsifiability_score": 8,
            "novelty_comparison": "Different from generic quantization because it tests residual allocation under a hard VRAM cap.",
            "risk_notes": "May not transfer to larger models.",
        }
        with patch("enoch_control_plane.control_plane.router.SupabaseControlPlaneStore", return_value=fake_store), \
             patch("scripts.research_provider_budget.fetch_json", return_value=quota), \
             patch("scripts.research_provider_generate.generate_provider_candidates", return_value={"ok": True, "provider_response_id": "cmpl-cycle", "attempts_used": 1, "candidates": [generated_candidate]}) as generate:
            client = _client_with_config(config)
            response = client.post(
                "/control/api/research/run-cycle",
                headers={"Authorization": f"Bearer {TOKEN}"},
                json={"dry_run": False, "enabled": True, "max_dispatches_per_run": 0, "requested_by": "pytest"},
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["action"], "research_cycle")
        self.assertEqual(body["generated_count"], 1)
        self.assertEqual(body["promoted_count"], 1)
        self.assertEqual(body["queued_count"], 1)
        self.assertEqual(body["dispatched_count"], 0)
        self.assertFalse(body["dispatch_started"])
        self.assertEqual(len(fake_store.recorded), 1)
        self.assertEqual(fake_store.promoted[0], ("generated-candidate", "pytest", False))
        self.assertEqual(fake_store.events[0]["event_type"], "research.run_cycle.live")
        self.assertEqual(generate.call_args.kwargs["attempts"], 2)

    def test_research_facility_run_cycle_prioritizes_followup_before_fresh_generation(self) -> None:
        class FakeSupabaseStore:
            def __init__(self) -> None:
                self.events = []
                self.observations = []
                self.queue = {
                    "followup-idea": {
                        "project_id": "followup-idea",
                        "project_name": "Follow-up Idea",
                        "project_dir": "followup-idea",
                        "status": "queued",
                        "model": "gpt-5.5",
                        "sandbox": "danger-full-access",
                    }
                }

            def active_items(self) -> list[dict[str, str]]:
                return []

            def status_counts(self) -> dict[str, int]:
                return {"blocked": 0, "queued": 0, "active": 0}

            def flags(self):
                return SimpleNamespace(queue_paused=False, maintenance_mode=False)

            def research_facility_workbench_projection(self, *, limit: int = 100) -> list[dict[str, str]]:
                return [{"candidate_id": "fresh-candidate", "admission_decision": "admitted", "admitted_idea_id": "", "total_score": "99.00"}]

            def next_followup_candidate(self, *, max_followup_depth: int = 4, project_id: str = "") -> dict[str, str]:
                return {"project_id": "parent-idea", "followup_title": "Bounded branch"}

            def launch_followup_candidate(self, *, dry_run: bool = True, requested_by: str = "operator", max_followup_depth: int = 4, project_id: str = "") -> dict[str, object]:
                return {
                    "ok": True,
                    "action": "followup_queued",
                    "reason": "bounded follow-up queued",
                    "candidate": {"project_id": "parent-idea"},
                    "followup": {"idea_id": "followup-idea", "title": "Bounded branch"},
                }

            def record_research_facility_plans(self, *_args, **_kwargs):  # pragma: no cover - follow-up should skip provider generation
                raise AssertionError("branch-first cycle should not write fresh provider candidates")

            def promote_research_candidate(self, *_args, **_kwargs):  # pragma: no cover - follow-up should skip fresh promotion
                raise AssertionError("branch-first cycle should not promote fresh candidates")

            def queue_row(self, project_id: str):
                return self.queue.get(project_id)

            def claim_dispatch_candidate(self, *, project_id: str, run_id: str, requested_by: str):
                claimed = dict(self.queue[project_id])
                claimed.update({"status": "dispatching", "current_run_id": run_id})
                self.queue[project_id] = claimed
                return claimed

            def release_dispatch_claim(self, *, project_id: str, run_id: str, reason: str):  # pragma: no cover - happy path
                self.queue[project_id]["status"] = "queued"
                return True

            def update_project_dir(self, project_id: str, project_dir: str) -> None:
                self.queue[project_id]["project_dir"] = project_dir

            def mark_dispatch_started(self, *, project_id: str, run_id: str, session_id: str, dispatch_payload: dict, requested_by: str):
                self.queue[project_id].update({"status": "awaiting_wake", "current_run_id": run_id, "current_session_id": session_id})
                return 11, self.queue[project_id]

            def upsert_dashboard_observation(self, **kwargs):
                self.observations.append(kwargs)

            def append_event(self, **kwargs):
                self.events.append(kwargs)
                return len(self.events), True

        fake_store = FakeSupabaseStore()
        config = GateConfig(
            state_dir="/tmp/unused",
            project_root="/tmp/unused-projects",
            dispatch_script_path="/tmp/dispatch.sh",
            control_api_bearer_token=TOKEN,
            completion_callback_url="http://example.invalid/callback",
            completion_callback_token="unused",
            control_plane_store_backend="supabase",
            supabase_database_url="postgresql://example.invalid/postgres",
            live_dispatch_enabled=True,
            worker_wake_gate_bearer_token="worker-token",
        )
        quota = {
            "subscription": {"limit": 2500, "requests": 0},
            "weeklyTokenLimit": {"remainingCredits": "$119.77"},
            "rollingFiveHourLimit": {"remaining": 2500, "max": 2500, "limited": False},
        }
        ok_preflight = WorkerPreflightResponse(
            ok=True,
            target="http://worker.invalid",
            summary="ok",
            checks=[WorkerPreflightCheck(name="worker_no_live_runs", ok=True, detail="no live worker runs")],
        )
        ok_http = HttpResult(ok=True, status=200, body={"dispatch": {"session_id": "session-1"}}, error="")
        with patch("enoch_control_plane.control_plane.router.SupabaseControlPlaneStore", return_value=fake_store), \
             patch("scripts.research_provider_budget.fetch_json", return_value=quota), \
             patch("scripts.research_provider_generate.generate_provider_candidates") as generate, \
             patch("enoch_control_plane.control_plane.router.run_worker_preflight", return_value=ok_preflight), \
             patch("enoch_control_plane.control_plane.router.post_worker_json", return_value=ok_http):
            client = _client_with_config(config)
            response = client.post(
                "/control/api/research/run-cycle",
                headers={"Authorization": f"Bearer {TOKEN}"},
                json={
                    "dry_run": False,
                    "enabled": True,
                    "max_provider_requests_per_run": 1,
                    "max_promotions_per_run": 1,
                    "max_dispatches_per_run": 1,
                    "max_paper_drafts_per_run": 0,
                    "requested_by": "pytest",
                },
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertTrue(body["fresh_generation_skipped"])
        self.assertEqual(body["followup_launch"]["action"], "followup_queued")
        self.assertEqual(body["generated_count"], 0)
        self.assertEqual(body["promoted_count"], 0)
        self.assertEqual(body["queued_count"], 1)
        self.assertEqual(body["dispatched_count"], 1)
        self.assertTrue(body["dispatch_started"])
        self.assertEqual(body["dispatch"]["candidate"]["project_id"], "followup-idea")
        self.assertIn("follow-up branch took priority", body["reason"])
        generate.assert_not_called()
        self.assertEqual(fake_store.events[-1]["event_type"], "research.run_cycle.live")

    def test_research_facility_run_cycle_provider_failure_still_promotes_existing_candidate(self) -> None:
        class FakeSupabaseStore:
            def __init__(self) -> None:
                self.events = []
                self.promoted = []

            def active_items(self) -> list[dict[str, str]]:
                return []

            def status_counts(self) -> dict[str, int]:
                return {"blocked": 0, "queued": 0, "active": 0}

            def research_facility_workbench_projection(self, *, limit: int = 100) -> list[dict[str, str]]:
                return [{"candidate_id": "existing-candidate", "admission_decision": "admitted", "admitted_idea_id": "", "total_score": "83.00"}]

            def record_research_facility_plans(self, *_args, **_kwargs):  # pragma: no cover - should not run on provider failure
                raise AssertionError("provider failure must not write generated candidate ledgers")

            def promote_research_candidate(self, candidate_id: str, *, requested_by: str, dry_run: bool = True) -> dict[str, object]:
                self.promoted.append((candidate_id, requested_by, dry_run))
                return {"ok": True, "action": "promote_candidate", "candidate_id": candidate_id, "idea_id": candidate_id, "queued_count": 1, "dispatch_started": False}

            def append_event(self, **kwargs):
                self.events.append(kwargs)
                return 1, True

        fake_store = FakeSupabaseStore()
        config = GateConfig(
            state_dir="/tmp/unused",
            project_root="/tmp/unused-projects",
            dispatch_script_path="/tmp/dispatch.sh",
            control_api_bearer_token=TOKEN,
            completion_callback_url="http://example.invalid/callback",
            completion_callback_token="unused",
            control_plane_store_backend="supabase",
            supabase_database_url="postgresql://example.invalid/postgres",
        )
        quota = {
            "subscription": {"limit": 2500, "requests": 0},
            "weeklyTokenLimit": {"remainingCredits": "$119.77"},
            "rollingFiveHourLimit": {"remaining": 2500, "max": 2500, "limited": False},
        }
        with patch("enoch_control_plane.control_plane.router.SupabaseControlPlaneStore", return_value=fake_store), \
             patch("scripts.research_provider_budget.fetch_json", return_value=quota), \
             patch("scripts.research_provider_generate.generate_provider_candidates", side_effect=ValueError("provider returned 0 usable candidates")):
            client = _client_with_config(config)
            response = client.post(
                "/control/api/research/run-cycle",
                headers={"Authorization": f"Bearer {TOKEN}"},
                json={"dry_run": False, "enabled": True, "max_dispatches_per_run": 0, "requested_by": "pytest"},
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["generated_count"], 0)
        self.assertEqual(body["promoted_count"], 1)
        self.assertEqual(body["queued_count"], 1)
        self.assertIn("provider generation skipped", body["warnings"][0])
        self.assertEqual(body["stages"][0]["stage"], "provider_generation")
        self.assertFalse(body["stages"][0]["ok"])
        self.assertEqual(fake_store.promoted[0], ("existing-candidate", "pytest", False))
        self.assertEqual(fake_store.events[0]["event_type"], "research.run_cycle.live")

    def test_research_facility_run_cycle_skips_provider_when_admitted_backlog_is_high(self) -> None:
        class FakeSupabaseStore:
            def __init__(self) -> None:
                self.events = []
                self.promoted = []

            def active_items(self) -> list[dict[str, str]]:
                return []

            def status_counts(self) -> dict[str, int]:
                return {"blocked": 0, "queued": 0, "active": 0}

            def next_followup_candidate(self, *, max_followup_depth: int = 4, project_id: str = "") -> None:
                return None

            def research_facility_workbench_projection(self, *, limit: int = 100) -> list[dict[str, str]]:
                return [
                    {"candidate_id": f"existing-{index}", "admission_decision": "admitted", "admitted_idea_id": "", "total_score": str(80 + index)}
                    for index in range(3)
                ]

            def record_research_facility_plans(self, *_args, **_kwargs):  # pragma: no cover - backlog should skip provider generation
                raise AssertionError("provider generation must be skipped when admitted backlog is high")

            def promote_research_candidate(self, candidate_id: str, *, requested_by: str, dry_run: bool = True) -> dict[str, object]:
                self.promoted.append((candidate_id, requested_by, dry_run))
                return {"ok": True, "action": "promote_candidate", "candidate_id": candidate_id, "idea_id": candidate_id, "queued_count": 1, "dispatch_started": False}

            def append_event(self, **kwargs):
                self.events.append(kwargs)
                return 1, True

        fake_store = FakeSupabaseStore()
        config = GateConfig(
            state_dir="/tmp/unused",
            project_root="/tmp/unused-projects",
            dispatch_script_path="/tmp/dispatch.sh",
            control_api_bearer_token=TOKEN,
            completion_callback_url="http://example.invalid/callback",
            completion_callback_token="unused",
            control_plane_store_backend="supabase",
            supabase_database_url="postgresql://example.invalid/postgres",
        )
        quota = {
            "subscription": {"limit": 2500, "requests": 0},
            "weeklyTokenLimit": {"remainingCredits": "$119.77"},
            "rollingFiveHourLimit": {"remaining": 2500, "max": 2500, "limited": False},
        }
        with patch("enoch_control_plane.control_plane.router.SupabaseControlPlaneStore", return_value=fake_store), \
             patch("scripts.research_provider_budget.fetch_json", return_value=quota), \
             patch("scripts.research_provider_generate.generate_provider_candidates") as generate:
            client = _client_with_config(config)
            response = client.post(
                "/control/api/research/run-cycle",
                headers={"Authorization": f"Bearer {TOKEN}"},
                json={
                    "dry_run": False,
                    "enabled": True,
                    "max_provider_requests_per_run": 1,
                    "max_promotions_per_run": 1,
                    "max_dispatches_per_run": 0,
                    "fresh_generation_backlog_threshold": 3,
                    "requested_by": "pytest",
                },
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertTrue(body["fresh_generation_skipped"])
        self.assertEqual(body["fresh_generation_skip_reason"], "admitted candidate backlog is above fresh generation threshold")
        self.assertEqual(body["generated_count"], 0)
        self.assertEqual(body["promoted_count"], 1)
        self.assertEqual(body["queued_count"], 1)
        self.assertEqual(fake_store.promoted[0][0], "existing-2")
        generate.assert_not_called()

    def test_research_facility_run_cycle_dispatch_conflict_is_benign_backpressure(self) -> None:
        class FakeSupabaseStore:
            def __init__(self) -> None:
                self.events = []
                self.observations = []
                self.claim_released = False
                self.queue = {
                    "candidate-ready": {
                        "project_id": "candidate-ready",
                        "project_name": "Candidate Ready",
                        "project_dir": "candidate-ready",
                        "status": "queued",
                        "model": "gpt-5.5",
                        "sandbox": "danger-full-access",
                    }
                }

            def active_items(self) -> list[dict[str, str]]:
                return []

            def status_counts(self) -> dict[str, int]:
                return {"blocked": 0, "queued": 1, "active": 0}

            def flags(self):
                return SimpleNamespace(queue_paused=False, maintenance_mode=False)

            def research_facility_workbench_projection(self, *, limit: int = 100) -> list[dict[str, str]]:
                return [{"candidate_id": "candidate-ready", "admission_decision": "admitted", "admitted_idea_id": "", "total_score": "83.00"}]

            def record_research_facility_plans(self, *_args, **_kwargs):  # pragma: no cover - provider disabled
                raise AssertionError("provider generation disabled in this test")

            def promote_research_candidate(self, candidate_id: str, *, requested_by: str, dry_run: bool = True) -> dict[str, object]:
                return {"ok": True, "action": "promote_candidate", "candidate_id": candidate_id, "idea_id": candidate_id, "queued_count": 1, "dispatch_started": False}

            def queue_row(self, project_id: str):
                return self.queue.get(project_id)

            def claim_dispatch_candidate(self, *, project_id: str, run_id: str, requested_by: str):
                claimed = dict(self.queue[project_id])
                claimed.update({"status": "dispatching", "current_run_id": run_id})
                return claimed

            def release_dispatch_claim(self, *, project_id: str, run_id: str, reason: str):
                self.claim_released = True
                self.queue[project_id]["status"] = "queued"
                return True

            def upsert_dashboard_observation(self, **kwargs):
                self.observations.append(kwargs)

            def append_event(self, **kwargs):
                self.events.append(kwargs)
                return len(self.events), True

        fake_store = FakeSupabaseStore()
        config = GateConfig(
            state_dir="/tmp/unused",
            project_root="/tmp/unused-projects",
            dispatch_script_path="/tmp/dispatch.sh",
            control_api_bearer_token=TOKEN,
            completion_callback_url="http://example.invalid/callback",
            completion_callback_token="unused",
            control_plane_store_backend="supabase",
            supabase_database_url="postgresql://example.invalid/postgres",
            live_dispatch_enabled=True,
            worker_wake_gate_bearer_token="worker-token",
        )
        quota = {
            "subscription": {"limit": 2500, "requests": 0},
            "weeklyTokenLimit": {"remainingCredits": "$119.77"},
            "rollingFiveHourLimit": {"remaining": 2500, "max": 2500, "limited": False},
        }
        failed_preflight = WorkerPreflightResponse(
            ok=False,
            target="http://worker.invalid",
            summary="worker reports active lane",
            checks=[WorkerPreflightCheck(name="worker_no_live_runs", ok=False, detail="active worker lane present")],
        )
        with patch("enoch_control_plane.control_plane.router.SupabaseControlPlaneStore", return_value=fake_store), \
             patch("scripts.research_provider_budget.fetch_json", return_value=quota), \
             patch("enoch_control_plane.control_plane.router.run_worker_preflight", return_value=failed_preflight):
            client = _client_with_config(config)
            response = client.post(
                "/control/api/research/run-cycle",
                headers={"Authorization": f"Bearer {TOKEN}"},
                json={
                    "dry_run": False,
                    "enabled": True,
                    "max_provider_requests_per_run": 0,
                    "max_promotions_per_run": 1,
                    "max_dispatches_per_run": 1,
                    "max_paper_drafts_per_run": 0,
                    "requested_by": "pytest",
                },
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["promoted_count"], 1)
        self.assertEqual(body["dispatched_count"], 0)
        self.assertFalse(body["dispatch_started"])
        self.assertTrue(fake_store.claim_released)
        dispatch_stage = next(stage for stage in body["stages"] if stage["stage"] == "dispatch")
        self.assertEqual(dispatch_stage["action"], "dispatch_backpressure")
        self.assertIn("backpressure", dispatch_stage["reason"])
        self.assertEqual(fake_store.events[-1]["event_type"], "research.run_cycle.live")

    def test_research_facility_run_cycle_releases_claim_when_preflight_raises(self) -> None:
        class FakeSupabaseStore:
            def __init__(self) -> None:
                self.events = []
                self.observations = []
                self.claim_released = False
                self.queue = {
                    "candidate-ready": {
                        "project_id": "candidate-ready",
                        "project_name": "Candidate Ready",
                        "project_dir": "candidate-ready",
                        "status": "queued",
                        "model": "gpt-5.5",
                        "sandbox": "danger-full-access",
                    }
                }

            def active_items(self) -> list[dict[str, str]]:
                return []

            def status_counts(self) -> dict[str, int]:
                return {"blocked": 0, "queued": 1, "active": 0}

            def flags(self):
                return SimpleNamespace(queue_paused=False, maintenance_mode=False)

            def research_facility_workbench_projection(self, *, limit: int = 100) -> list[dict[str, str]]:
                return [{"candidate_id": "candidate-ready", "admission_decision": "admitted", "admitted_idea_id": "", "total_score": "83.00"}]

            def record_research_facility_plans(self, *_args, **_kwargs):
                raise AssertionError("provider generation disabled in this test")

            def promote_research_candidate(self, candidate_id: str, *, requested_by: str, dry_run: bool = True) -> dict[str, object]:
                return {"ok": True, "action": "promote_candidate", "candidate_id": candidate_id, "idea_id": candidate_id, "queued_count": 1, "dispatch_started": False}

            def queue_row(self, project_id: str):
                return self.queue.get(project_id)

            def claim_dispatch_candidate(self, *, project_id: str, run_id: str, requested_by: str):
                claimed = dict(self.queue[project_id])
                claimed.update({"status": "dispatching", "current_run_id": run_id})
                return claimed

            def release_dispatch_claim(self, *, project_id: str, run_id: str, reason: str):
                self.claim_released = True
                self.queue[project_id]["status"] = "queued"
                self.queue[project_id]["last_error"] = reason
                return True

            def upsert_dashboard_observation(self, **kwargs):
                self.observations.append(kwargs)

            def append_event(self, **kwargs):
                self.events.append(kwargs)
                return len(self.events), True

        fake_store = FakeSupabaseStore()
        config = GateConfig(
            state_dir="/tmp/unused",
            project_root="/tmp/unused-projects",
            dispatch_script_path="/tmp/dispatch.sh",
            control_api_bearer_token=TOKEN,
            completion_callback_url="http://example.invalid/callback",
            completion_callback_token="unused",
            control_plane_store_backend="supabase",
            supabase_database_url="postgresql://example.invalid/postgres",
            live_dispatch_enabled=True,
            worker_wake_gate_bearer_token="worker-token",
        )
        quota = {
            "subscription": {"limit": 2500, "requests": 0},
            "weeklyTokenLimit": {"remainingCredits": "$119.77"},
            "rollingFiveHourLimit": {"remaining": 2500, "max": 2500, "limited": False},
        }
        with patch("enoch_control_plane.control_plane.router.SupabaseControlPlaneStore", return_value=fake_store), \
             patch("scripts.research_provider_budget.fetch_json", return_value=quota), \
             patch("enoch_control_plane.control_plane.router.run_worker_preflight", side_effect=RuntimeError("bad worker telemetry")):
            client = _client_with_config(config)
            response = client.post(
                "/control/api/research/run-cycle",
                headers={"Authorization": f"Bearer {TOKEN}"},
                json={
                    "dry_run": False,
                    "enabled": True,
                    "max_provider_requests_per_run": 0,
                    "max_promotions_per_run": 1,
                    "max_dispatches_per_run": 1,
                    "max_paper_drafts_per_run": 0,
                    "requested_by": "pytest",
                },
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["dispatched_count"], 0)
        self.assertTrue(fake_store.claim_released)
        dispatch_stage = next(stage for stage in body["stages"] if stage["stage"] == "dispatch")
        self.assertEqual(dispatch_stage["action"], "dispatch_backpressure")
        self.assertIn("bad worker telemetry", json.dumps(dispatch_stage["detail"]))


    def test_research_facility_run_cycle_live_records_guardrail_when_queue_paused(self) -> None:
        class FakeSupabaseStore:
            def __init__(self) -> None:
                self.events = []

            def active_items(self) -> list[dict[str, str]]:
                return []

            def status_counts(self) -> dict[str, int]:
                return {"blocked": 0, "queued": 0, "active": 0}

            def flags(self):
                return SimpleNamespace(queue_paused=True)

            def research_facility_workbench_projection(self, *, limit: int = 100) -> list[dict[str, str]]:
                return []

            def record_research_facility_plans(self, *_args, **_kwargs):
                raise AssertionError("provider generation disabled in this test")

            def promote_research_candidate(self, *_args, **_kwargs):
                raise AssertionError("no promotable rows in this test")

            def append_event(self, **kwargs):
                self.events.append(kwargs)
                return len(self.events), True

        fake_store = FakeSupabaseStore()
        config = GateConfig(
            state_dir="/tmp/unused",
            project_root="/tmp/unused-projects",
            dispatch_script_path="/tmp/dispatch.sh",
            control_api_bearer_token=TOKEN,
            completion_callback_url="http://example.invalid/callback",
            completion_callback_token="unused",
            control_plane_store_backend="supabase",
            supabase_database_url="postgresql://example.invalid/postgres",
        )
        with patch("enoch_control_plane.control_plane.router.SupabaseControlPlaneStore", return_value=fake_store):
            client = _client_with_config(config)
            response = client.post(
                "/control/api/research/run-cycle",
                headers={"Authorization": f"Bearer {TOKEN}"},
                json={
                    "dry_run": False,
                    "enabled": True,
                    "max_provider_requests_per_run": 0,
                    "max_promotions_per_run": 0,
                    "max_dispatches_per_run": 0,
                    "max_paper_drafts_per_run": 0,
                    "requested_by": "pytest",
                },
            )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("research autopilot is active but broad queue is paused", body["guardrails"])
        self.assertTrue(any(event["event_type"] == "research.guardrail.queue_paused" for event in fake_store.events))


    def test_research_facility_run_cycle_active_lane_is_backpressure_not_blocked(self) -> None:
        class FakeSupabaseStore:
            def __init__(self) -> None:
                self.events = []

            def active_items(self) -> list[dict[str, str]]:
                return [{"project_id": "active-project", "status": "awaiting_wake"}]

            def status_counts(self) -> dict[str, int]:
                return {"blocked": 0, "queued": 0, "active": 1}

            def research_facility_workbench_projection(self, *, limit: int = 100) -> list[dict[str, str]]:
                return [{"candidate_id": "candidate-ready", "admission_decision": "admitted", "admitted_idea_id": "", "total_score": "83.00"}]

            def record_research_facility_plans(self, *_args, **_kwargs):  # pragma: no cover - active lane backpressure returns first
                raise AssertionError("active lane backpressure should not generate")

            def promote_research_candidate(self, *_args, **_kwargs):  # pragma: no cover - active lane backpressure returns first
                raise AssertionError("active lane backpressure should not promote")

            def append_event(self, **kwargs):
                self.events.append(kwargs)
                return 1, True

        fake_store = FakeSupabaseStore()
        config = GateConfig(
            state_dir="/tmp/unused",
            project_root="/tmp/unused-projects",
            dispatch_script_path="/tmp/dispatch.sh",
            control_api_bearer_token=TOKEN,
            completion_callback_url="http://example.invalid/callback",
            completion_callback_token="unused",
            control_plane_store_backend="supabase",
            supabase_database_url="postgresql://example.invalid/postgres",
        )
        quota = {
            "subscription": {"limit": 2500, "requests": 0},
            "weeklyTokenLimit": {"remainingCredits": "$119.77"},
            "rollingFiveHourLimit": {"remaining": 2500, "max": 2500, "limited": False},
        }
        with patch("enoch_control_plane.control_plane.router.SupabaseControlPlaneStore", return_value=fake_store), \
             patch("scripts.research_provider_budget.fetch_json", return_value=quota), \
             patch("scripts.research_provider_generate.generate_provider_candidates") as generate:
            client = _client_with_config(config)
            response = client.post(
                "/control/api/research/run-cycle",
                headers={"Authorization": f"Bearer {TOKEN}"},
                json={"dry_run": False, "enabled": True, "requested_by": "pytest"},
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertTrue(body["backpressure"])
        self.assertEqual(body["action"], "research_cycle_backpressure")
        self.assertEqual(body["reason"], "active worker lane already exists")
        self.assertEqual(body["active_count"], 1)
        self.assertEqual(body["promoted_count"], 0)
        self.assertEqual(body["dispatched_count"], 0)
        generate.assert_not_called()
        self.assertEqual(fake_store.events[0]["event_type"], "research.run_cycle.backpressure")

    def test_research_facility_run_cycle_live_requires_enabled_flag(self) -> None:
        class FakeSupabaseStore:
            def active_items(self) -> list[dict[str, str]]:
                return []

            def status_counts(self) -> dict[str, int]:
                return {"blocked": 0, "queued": 0, "active": 0}

            def research_facility_workbench_projection(self, *, limit: int = 100) -> list[dict[str, str]]:
                return []

            def record_research_facility_plans(self, *_args, **_kwargs):  # pragma: no cover - blocked before write
                raise AssertionError("live disabled cycle should not write")

            def promote_research_candidate(self, *_args, **_kwargs):  # pragma: no cover - blocked before promotion
                raise AssertionError("live disabled cycle should not promote")

            def append_event(self, **_kwargs):
                return 1, True

        config = GateConfig(
            state_dir="/tmp/unused",
            project_root="/tmp/unused-projects",
            dispatch_script_path="/tmp/dispatch.sh",
            control_api_bearer_token=TOKEN,
            completion_callback_url="http://example.invalid/callback",
            completion_callback_token="unused",
            control_plane_store_backend="supabase",
            supabase_database_url="postgresql://example.invalid/postgres",
        )
        quota = {
            "subscription": {"limit": 2500, "requests": 0},
            "weeklyTokenLimit": {"remainingCredits": "$119.77"},
            "rollingFiveHourLimit": {"remaining": 2500, "max": 2500, "limited": False},
        }
        with patch("enoch_control_plane.control_plane.router.SupabaseControlPlaneStore", return_value=FakeSupabaseStore()), \
             patch("scripts.research_provider_budget.fetch_json", return_value=quota), \
             patch("scripts.research_provider_generate.generate_provider_candidates") as generate:
            client = _client_with_config(config)
            response = client.post(
                "/control/api/research/run-cycle",
                headers={"Authorization": f"Bearer {TOKEN}"},
                json={"dry_run": False, "requested_by": "pytest"},
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertFalse(body["ok"])
        self.assertIn("enabled=true", body["reason"])
        self.assertFalse(body["dispatch_started"])
        generate.assert_not_called()

    def test_research_facility_run_cycle_paper_stage_blocks_negative_decision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "projects"
            project_dir = project_root / "negative-project"
            (project_dir / ".enoch").mkdir(parents=True)
            (project_dir / "run_notes.md").write_text("negative result\n", encoding="utf-8")
            (project_dir / ".enoch" / "project_decision.json").write_text(
                json.dumps({"project_decision": "finalize_negative", "summary": "No improvement"}),
                encoding="utf-8",
            )

            class FakeSupabaseStore:
                def __init__(self) -> None:
                    self.events = []

                def active_items(self) -> list[dict[str, str]]:
                    return []

                def status_counts(self) -> dict[str, int]:
                    return {"blocked": 0, "queued": 0, "active": 0, "completed": 1}

                def research_facility_workbench_projection(self, *, limit: int = 100) -> list[dict[str, str]]:
                    return []

                def record_research_facility_plans(self, *_args, **_kwargs):
                    raise AssertionError("paper-only cycle should not record research ledgers")

                def promote_research_candidate(self, *_args, **_kwargs):
                    raise AssertionError("paper-only cycle should not promote candidates")

                def queue_rows(self) -> list[dict[str, object]]:
                    return [{
                        "project_id": "negative-project",
                        "project_name": "Negative Project",
                        "project_dir": str(project_dir),
                        "status": "completed",
                        "current_run_id": "run-negative",
                        "last_run_state": "wake_ready",
                        "next_action_hint": "draft_paper_or_select_next_project",
                        "manual_review_required": False,
                    }]

                def paper_rows(self) -> list[dict[str, object]]:
                    return []

                def append_event(self, **kwargs):
                    self.events.append(kwargs)
                    return 1, True

            config = GateConfig(
                state_dir=str(Path(tmp) / "state"),
                project_root=str(project_root),
                dispatch_script_path=str(Path(tmp) / "dispatch.sh"),
                control_api_bearer_token=TOKEN,
                completion_callback_url="http://example.invalid/callback",
                completion_callback_token="unused",
                control_plane_store_backend="supabase",
                supabase_database_url="postgresql://example.invalid/postgres",
            )
            quota = {
                "subscription": {"limit": 2500, "requests": 0},
                "weeklyTokenLimit": {"remainingCredits": "$119.77"},
                "rollingFiveHourLimit": {"remaining": 2500, "max": 2500, "limited": False},
            }
            with patch("enoch_control_plane.control_plane.router.SupabaseControlPlaneStore", return_value=FakeSupabaseStore()), \
                 patch("scripts.research_provider_budget.fetch_json", return_value=quota), \
                 patch("enoch_control_plane.control_plane.router.write_paper_artifacts") as writer:
                client = _client_with_config(config)
                response = client.post(
                    "/control/api/research/run-cycle",
                    headers={"Authorization": f"Bearer {TOKEN}"},
                    json={
                        "dry_run": False,
                        "enabled": True,
                        "max_provider_requests_per_run": 0,
                        "max_promotions_per_run": 0,
                        "max_dispatches_per_run": 0,
                        "max_paper_drafts_per_run": 1,
                        "max_publication_rewrites_per_run": 1,
                        "requested_by": "pytest",
                    },
                )

            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertTrue(body["ok"])
            self.assertEqual(body["paper_drafted_count"], 0)
            self.assertEqual(body["publication_finalized_count"], 0)
            self.assertEqual(body["paper_drafts"][0]["action"], "noop")
            self.assertIn("lacked sufficient positive", body["paper_drafts"][0]["reason"])
            writer.assert_not_called()

    def test_research_facility_run_cycle_paper_stage_drafts_and_finalizes_positive_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "projects"
            project_dir = project_root / "positive-project"
            project_dir.mkdir(parents=True)
            (project_dir / "run_notes.md").write_text("positive run evidence\n", encoding="utf-8")
            (project_dir / ".enoch").mkdir(parents=True)
            (project_dir / ".enoch" / "project_decision.json").write_text('{"project_decision":"finalize_positive"}\n', encoding="utf-8")

            class FakeSupabaseStore:
                def __init__(self) -> None:
                    self.events = []
                    self.papers: dict[str, dict[str, object]] = {}
                    self.review_rows: dict[str, dict[str, object]] = {}

                def active_items(self) -> list[dict[str, str]]:
                    return []

                def status_counts(self) -> dict[str, int]:
                    return {"blocked": 0, "queued": 0, "active": 0, "completed": 1}

                def research_facility_workbench_projection(self, *, limit: int = 100) -> list[dict[str, str]]:
                    return []

                def record_research_facility_plans(self, *_args, **_kwargs):
                    raise AssertionError("paper-only cycle should not record research ledgers")

                def promote_research_candidate(self, *_args, **_kwargs):
                    raise AssertionError("paper-only cycle should not promote candidates")

                def queue_rows(self) -> list[dict[str, object]]:
                    return [{
                        "project_id": "positive-project",
                        "project_name": "Positive Project",
                        "project_dir": str(project_dir),
                        "status": "completed",
                        "current_run_id": "run-positive",
                        "last_run_state": "finalize_positive",
                        "next_action_hint": "draft_paper_or_select_next_project",
                        "manual_review_required": False,
                    }]

                def paper_rows(self) -> list[dict[str, object]]:
                    return list(self.papers.values())

                def update_project_dir(self, project_id: str, project_dir_text: str) -> None:
                    self.updated_project_dir = (project_id, project_dir_text)

                def upsert_paper(self, paper) -> None:
                    self.papers[paper.paper_id] = paper.model_dump(mode="json")

                def backfill_paper_reviews(self, payload: PaperReviewBackfillRequest):
                    paper_id = payload.paper_ids[0]
                    self.review_rows[paper_id] = {
                        "paper_id": paper_id,
                        "project_id": "positive-project",
                        "project_name": "Positive Project",
                        "paper_status": "publication_draft",
                        "paper_type": "arxiv_draft",
                        "review_status": "queued",
                        "updated_at": "2026-05-09T00:00:00Z",
                    }
                    return True, 1, 0, 0, []

                def paper_row(self, paper_id: str):
                    return self.papers.get(paper_id)

                def paper_review_row(self, paper_id: str, include_rank_reasons: bool = False):
                    return self.review_rows.get(paper_id)

                def project_row(self, project_id: str):
                    return {"project_id": project_id, "project_name": "Positive Project", "project_dir": str(project_dir)}

                def prepare_paper_review_finalization_package(self, paper_id: str, payload, require_approval: bool = False):
                    item = dict(self.review_rows[paper_id])
                    item["review_status"] = "finalized"
                    item["finalization_package_path"] = "papers/run-positive/finalization_package.json"
                    self.review_rows[paper_id] = item
                    return 42, True, item, item["finalization_package_path"], {"paper_id": paper_id}

                def append_event(self, **kwargs):
                    self.events.append(kwargs)
                    return len(self.events), True

            fake_store = FakeSupabaseStore()
            config = GateConfig(
                state_dir=str(Path(tmp) / "state"),
                project_root=str(project_root),
                dispatch_script_path=str(Path(tmp) / "dispatch.sh"),
                control_api_bearer_token=TOKEN,
                completion_callback_url="http://example.invalid/callback",
                completion_callback_token="unused",
                control_plane_store_backend="supabase",
                supabase_database_url="postgresql://example.invalid/postgres",
            )
            quota = {
                "subscription": {"limit": 2500, "requests": 0},
                "weeklyTokenLimit": {"remainingCredits": "$119.77"},
                "rollingFiveHourLimit": {"remaining": 2500, "max": 2500, "limited": False},
            }
            with patch("enoch_control_plane.control_plane.router.SupabaseControlPlaneStore", return_value=fake_store), \
                 patch("scripts.research_provider_budget.fetch_json", return_value=quota), \
                 patch("enoch_control_plane.control_plane.router.write_paper_artifacts", return_value={"provider": "synthetic.new", "model": "hf:zai-org/GLM-5.1", "fallback_used": False}):
                client = _client_with_config(config)
                response = client.post(
                    "/control/api/research/run-cycle",
                    headers={"Authorization": f"Bearer {TOKEN}"},
                    json={
                        "dry_run": False,
                        "enabled": True,
                        "max_provider_requests_per_run": 0,
                        "max_promotions_per_run": 0,
                        "max_dispatches_per_run": 0,
                        "max_paper_drafts_per_run": 1,
                        "max_publication_rewrites_per_run": 1,
                        "requested_by": "pytest",
                    },
                )

            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertTrue(body["ok"])
            self.assertEqual(body["paper_drafted_count"], 1)
            self.assertEqual(body["publication_finalized_count"], 1)
            self.assertEqual(body["paper_drafts"][0]["action"], "drafted")
            self.assertEqual(body["publication_finalizations"][0]["item"]["review_status"], "finalized")
            self.assertIn("paper.drafted", [event["event_type"] for event in fake_store.events])
            self.assertIn("research.run_cycle.live", [event["event_type"] for event in fake_store.events])

    def test_research_facility_promote_candidate_requires_candidate_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            response = client.post(
                "/control/api/research/promote-candidate",
                headers=headers,
                json={"dry_run": True, "requested_by": "pytest"},
            )
            self.assertEqual(response.status_code, 400)
            self.assertIn("candidate_id is required", response.text)

    def test_research_facility_promote_candidate_requires_supabase_store(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            response = client.post(
                "/control/api/research/promote-candidate",
                headers=headers,
                json={"candidate_id": "candidate-a", "dry_run": True, "requested_by": "pytest"},
            )
            self.assertEqual(response.status_code, 501)
            self.assertIn("promotion requires the Supabase control-plane store", response.text)

    def test_research_facility_promote_candidate_calls_supabase_store_dry_run_first(self) -> None:
        class FakeSupabaseStore:
            def research_facility_workbench_projection(self, *, limit: int = 200) -> list[dict[str, str]]:
                return []

            def promote_research_candidate(self, candidate_id: str, *, requested_by: str, dry_run: bool = True) -> dict[str, object]:
                return {
                    "ok": True,
                    "action": "dry_run_promote_candidate",
                    "dry_run": dry_run,
                    "candidate_id": candidate_id,
                    "requested_by": requested_by,
                    "queued_count": 0,
                    "dispatch_started": False,
                }

        config = GateConfig(
            state_dir="/tmp/unused",
            project_root="/tmp/unused-projects",
            dispatch_script_path="/tmp/dispatch.sh",
            control_api_bearer_token=TOKEN,
            completion_callback_url="http://example.invalid/callback",
            completion_callback_token="unused",
            control_plane_store_backend="supabase",
            supabase_database_url="postgresql://example.invalid/postgres",
        )
        with patch("enoch_control_plane.control_plane.router.SupabaseControlPlaneStore", return_value=FakeSupabaseStore()):
            client = _client_with_config(config)
            response = client.post(
                "/control/api/research/promote-candidate",
                headers={"Authorization": f"Bearer {TOKEN}"},
                json={"candidate_id": "candidate-a", "dry_run": True, "requested_by": "pytest"},
            )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["action"], "dry_run_promote_candidate")
        self.assertTrue(body["dry_run"])
        self.assertEqual(body["candidate_id"], "candidate-a")
        self.assertEqual(body["requested_by"], "pytest")
        self.assertEqual(body["queued_count"], 0)
        self.assertFalse(body["dispatch_started"])

    def test_project_prompt_uses_source_provenance_instead_of_notion_authority(self) -> None:
        prompt = _project_prompt({
            "project_id": "idea-source",
            "project_name": "Source Prompt",
            "notion_page_url": "https://source.example/idea-source",
            "origin_idea_status": "testing",
        })

        self.assertIn("Source/provenance URL: https://source.example/idea-source", prompt)
        self.assertNotIn("Notion URL:", prompt)


    def test_dashboard_status_contract_reports_config_and_missing_worker_observations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            status = client.get("/control/api/status", headers=headers)
            self.assertEqual(status.status_code, 200)
            body = status.json()
            self.assertEqual(body["source"], "control_api_status")
            self.assertEqual(body["config"]["source"], "control_plane_config")
            self.assertFalse(body["config"]["live_dispatch_enabled"])
            self.assertFalse(body["config"]["pushover_alerts_enabled"])
            self.assertFalse(body["config"]["pushover_configured"])
            self.assertIn("control_plane_db", body["source_freshness"])
            self.assertIn("worker_preflight", body["source_freshness"])
            self.assertTrue(body["source_freshness"]["worker_preflight"]["stale"])
            self.assertIn("live dispatch disabled", body["dispatch_blockers"])
            self.assertIn("idea_intake", body["source_freshness"])
            self.assertIn("snapshot_mirror", body["source_freshness"])

    def test_dashboard_freshness_treats_naive_database_timestamps_as_utc(self) -> None:
        from enoch_control_plane.control_plane.router import _is_stale

        self.assertIs(_is_stale("2026-05-15 10:00:00", 1), True)

    def test_dashboard_status_omits_large_non_worker_observation_and_event_payloads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            store = ControlPlaneStore(Path(tmp) / "state" / "control_plane.sqlite3")
            large_payload = {"candidates": [{"description": "x" * 100_000}], "skipped_rows": []}
            store.upsert_dashboard_observation(source="idea_intake", status="ok", payload=large_payload)
            store.append_event(
                idempotency_key="large-status-event",
                event_type="ideas.intake",
                entity_type="snapshot",
                entity_id="idea_intake",
                payload=large_payload,
            )

            status = client.get("/control/api/status", headers=headers)
            self.assertEqual(status.status_code, 200)
            body = status.json()
            intake_observation = body["observations"]["idea_intake"]
            self.assertIsNotNone(intake_observation)
            self.assertEqual(intake_observation["payload"]["payload_omitted"], True)
            self.assertNotIn("candidates", intake_observation["payload"])
            self.assertEqual(body["recent_events"][0]["payload"]["payload_omitted"], True)
            self.assertNotIn("candidates", body["recent_events"][0]["payload"])


    def test_dashboard_status_blocks_dispatch_when_worker_refresh_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client_with_config(_live_config(tmp))
            headers = {"Authorization": f"Bearer {TOKEN}"}
            client.post("/control/import/legacy-snapshot", headers=headers, json={
                "idempotency_key": "safe-missing-worker-import",
                "queue_rows": [{
                    "project_id": "idea-ready",
                    "project_name": "Ready Missing Worker",
                    "project_dir": "idea-ready",
                    "status": "queued",
                    "dispatch_priority": 5,
                }],
            })
            client.post("/control/resume", headers=headers, json={"resumed_by": "test", "maintenance_mode": False})
            response = WorkerPreflightResponse(
                ok=False,
                target="http://worker.example",
                summary="worker preflight failed",
                checks=[
                    WorkerPreflightCheck(name="wake_gate_healthz", ok=False, detail="down", data={}),
                    WorkerPreflightCheck(name="wake_gate_dashboard_api", ok=False, detail="dashboard unavailable", data={}),
                ],
            )
            with patch("enoch_control_plane.control_plane.router.run_worker_preflight", return_value=response) as preflight:
                status = client.get("/control/api/status", headers=headers).json()

            preflight.assert_called_once()
            self.assertFalse(status["dispatch_safe"])
            self.assertIn("worker_preflight not ok", status["dispatch_blockers"])
            self.assertIn("worker_dashboard_api not ok", status["dispatch_blockers"])
            self.assertIn("worker health check failed", status["dispatch_blockers"])
            self.assertFalse(status["source_freshness"]["worker_preflight"]["stale"])


    def test_dashboard_status_auto_refreshes_stale_worker_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client_with_config(_live_config(tmp))
            headers = {"Authorization": f"Bearer {TOKEN}"}
            client.post("/control/import/legacy-snapshot", headers=headers, json={
                "idempotency_key": "refresh-worker-evidence-import",
                "queue_rows": [{
                    "project_id": "idea-active-refresh",
                    "project_name": "Active Refresh",
                    "project_dir": "idea-active-refresh",
                    "status": "awaiting_wake",
                    "current_run_id": "run-active-refresh",
                }],
            })
            client.post("/control/resume", headers=headers, json={"resumed_by": "test", "maintenance_mode": False})
            response = WorkerPreflightResponse(
                ok=False,
                target="http://worker.example",
                summary="active worker lane",
                checks=[
                    WorkerPreflightCheck(name="wake_gate_healthz", ok=True, detail="ok", data={}),
                    WorkerPreflightCheck(
                        name="wake_gate_dashboard_api",
                        ok=True,
                        detail="dashboard API reachable",
                        data={
                            "body": {
                                "totals": {"active_or_waiting": 1, "live": 1},
                                "telemetry": {},
                                "runs": [{
                                    "run_id": "run-active-refresh",
                                    "project_id": "idea-active-refresh",
                                    "gate_state": "running",
                                    "run_notes_tail": "x" * 50_000,
                                    "quiet_samples": [{"sample": "x" * 5000} for _ in range(12)],
                                    "project_decision": {
                                        "project_decision": "continue",
                                        "recommended_next_action": "investigate",
                                        "long_internal_notes": "x" * 50_000,
                                    },
                                }],
                            }
                        },
                    ),
                    WorkerPreflightCheck(
                        name="worker_no_live_runs",
                        ok=False,
                        detail="active_or_waiting=1, live=1",
                        data={"active_or_waiting": 1, "live": 1},
                    ),
                ],
            )
            with patch("enoch_control_plane.control_plane.router.run_worker_preflight", return_value=response) as preflight:
                status = client.get("/control/api/status", headers=headers).json()

            preflight.assert_called_once()
            self.assertFalse(status["source_freshness"]["worker_preflight"]["stale"])
            self.assertFalse(status["source_freshness"]["worker_dashboard_api"]["stale"])
            self.assertEqual(status["warnings"], [])
            self.assertEqual(status["conflicts"], [])
            self.assertEqual(status["dispatch_blockers"], ["active GB10 lane exists"])
            preflight_payload = status["observations"]["worker_preflight"]["payload"]
            dashboard_check = next(check for check in preflight_payload["checks"] if check["name"] == "wake_gate_dashboard_api")
            compact_run = dashboard_check["data"]["body"]["runs"][0]
            self.assertTrue(dashboard_check["data"]["body_compacted"])
            self.assertTrue(compact_run["run_notes_tail_omitted"])
            self.assertTrue(compact_run["quiet_samples_omitted"])
            self.assertNotIn("x" * 5000, json.dumps(preflight_payload))
            self.assertNotIn("long_internal_notes", json.dumps(preflight_payload))
            self.assertTrue(status["observations"]["worker_dashboard_api"]["payload"]["payload_omitted"])

    def test_dashboard_status_refreshes_fresh_but_conflicting_worker_projection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client_with_config(_live_config(tmp))
            headers = {"Authorization": f"Bearer {TOKEN}"}
            client.post("/control/resume", headers=headers, json={"resumed_by": "test", "maintenance_mode": False})
            store = ControlPlaneStore(Path(tmp) / "state" / "control_plane.sqlite3")
            store.upsert_dashboard_observation(
                source="worker_preflight",
                status="warn",
                payload={
                    "ok": False,
                    "checks": [
                        {"name": "wake_gate_healthz", "ok": True, "detail": "ok", "data": {}},
                        {"name": "worker_no_live_runs", "ok": False, "detail": "active_or_waiting=1, live=1", "data": {"active_or_waiting": 1, "live": 1}},
                    ],
                },
            )
            store.upsert_dashboard_observation(source="worker_dashboard_api", status="ok", payload={"ok": True})
            response = WorkerPreflightResponse(
                ok=True,
                target="http://worker.example",
                summary="worker idle",
                checks=[
                    WorkerPreflightCheck(name="wake_gate_healthz", ok=True, detail="ok", data={}),
                    WorkerPreflightCheck(name="wake_gate_dashboard_api", ok=True, detail="dashboard API reachable", data={"body": {"totals": {"active_or_waiting": 0, "live": 0}}}),
                    WorkerPreflightCheck(name="worker_no_live_runs", ok=True, detail="active_or_waiting=0, live=0", data={"active_or_waiting": 0, "live": 0}),
                ],
            )
            with patch("enoch_control_plane.control_plane.router.run_worker_preflight", return_value=response) as preflight:
                status = client.get("/control/api/status", headers=headers).json()

            preflight.assert_called_once()
            self.assertEqual(status["warnings"], [])
            self.assertEqual(status["conflicts"], [])
            self.assertEqual(status["dispatch_blockers"], ["no queued dispatch candidate"])


    def test_dashboard_status_auto_refreshes_stale_worker_evidence_before_dispatch_decision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client_with_config(_live_config(tmp))
            headers = {"Authorization": f"Bearer {TOKEN}"}
            client.post("/control/import/legacy-snapshot", headers=headers, json={
                "idempotency_key": "stale-worker-evidence-import",
                "queue_rows": [{
                    "project_id": "idea-ready-stale",
                    "project_name": "Ready Stale",
                    "project_dir": "idea-ready-stale",
                    "status": "queued",
                    "dispatch_priority": 5,
                }],
            })
            client.post("/control/resume", headers=headers, json={"resumed_by": "test", "maintenance_mode": False})
            response = WorkerPreflightResponse(
                ok=True,
                target="http://worker.example",
                summary="worker idle",
                checks=[
                    WorkerPreflightCheck(name="wake_gate_healthz", ok=True, detail="ok", data={}),
                    WorkerPreflightCheck(name="wake_gate_dashboard_api", ok=True, detail="dashboard API reachable", data={"body": {"totals": {"active_or_waiting": 0, "live": 0}}}),
                    WorkerPreflightCheck(name="worker_no_live_runs", ok=True, detail="active_or_waiting=0, live=0", data={"active_or_waiting": 0, "live": 0}),
                ],
            )
            with patch("enoch_control_plane.control_plane.router.run_worker_preflight", return_value=response) as preflight:
                status = client.get("/control/api/status", headers=headers).json()

            preflight.assert_called_once()
            self.assertTrue(status["dispatch_safe"])
            self.assertEqual(status["dispatch_blockers"], [])
            self.assertFalse(status["source_freshness"]["worker_preflight"]["stale"])
            self.assertFalse(status["source_freshness"]["worker_dashboard_api"]["stale"])


    def test_dashboard_status_blocks_dispatch_when_fresh_worker_evidence_is_bad(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client_with_config(_live_config(tmp))
            headers = {"Authorization": f"Bearer {TOKEN}"}
            client.post("/control/import/legacy-snapshot", headers=headers, json={
                "idempotency_key": "bad-worker-evidence-import",
                "queue_rows": [{
                    "project_id": "idea-ready",
                    "project_name": "Ready Bad Worker",
                    "project_dir": "idea-ready",
                    "status": "queued",
                    "dispatch_priority": 5,
                }],
            })
            client.post("/control/resume", headers=headers, json={"resumed_by": "test", "maintenance_mode": False})
            store = ControlPlaneStore(Path(tmp) / "state" / "control_plane.sqlite3")
            store.upsert_dashboard_observation(
                source="worker_preflight",
                status="warn",
                payload={"ok": False, "checks": [{"name": "wake_gate_healthz", "ok": False, "detail": "down", "data": {}}]},
            )
            store.upsert_dashboard_observation(
                source="worker_dashboard_api",
                status="unavailable",
                payload={"ok": False},
            )
            status = client.get("/control/api/status", headers=headers).json()
            self.assertFalse(status["dispatch_safe"])
            self.assertIn("worker_preflight not ok", status["dispatch_blockers"])
            self.assertIn("worker_dashboard_api not ok", status["dispatch_blockers"])
            self.assertIn("worker health check failed", status["dispatch_blockers"])


    def test_dashboard_status_blocks_dispatch_when_authenticated_worker_checks_are_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client_with_config(_live_config(tmp))
            headers = {"Authorization": f"Bearer {TOKEN}"}
            client.post("/control/import/legacy-snapshot", headers=headers, json={
                "idempotency_key": "skipped-worker-evidence-import",
                "queue_rows": [{
                    "project_id": "idea-ready",
                    "project_name": "Ready Skipped Worker",
                    "project_dir": "idea-ready",
                    "status": "queued",
                    "dispatch_priority": 5,
                }],
            })
            client.post("/control/resume", headers=headers, json={"resumed_by": "test", "maintenance_mode": False})
            store = ControlPlaneStore(Path(tmp) / "state" / "control_plane.sqlite3")
            store.upsert_dashboard_observation(
                source="worker_preflight",
                status="ok",
                payload={"ok": True, "checks": [{"name": "wake_gate_dashboard_api", "ok": True, "detail": "skipped", "data": {"skipped": True}}]},
            )
            store.upsert_dashboard_observation(source="worker_dashboard_api", status="ok", payload={"skipped": True})
            status = client.get("/control/api/status", headers=headers).json()
            self.assertFalse(status["dispatch_safe"])
            self.assertIn("worker dashboard telemetry skipped", status["dispatch_blockers"])


    def test_preflight_persists_cached_observation_for_status_page(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _config(tmp).model_copy(update={"worker_wake_gate_url": "http://127.0.0.1:1"})
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            preflight = client.post("/control/api/preflight", headers=headers, json={"wake_gate_url": "http://127.0.0.1:1"})
            self.assertEqual(preflight.status_code, 200)
            status = client.get("/control/api/status", headers=headers).json()
            observation = status["observations"]["worker_preflight"]
            self.assertIsNotNone(observation)
            self.assertEqual(observation["source"], "worker_preflight")
            self.assertEqual(status["source_freshness"]["worker_preflight"]["status"], "warn")
            self.assertFalse(status["source_freshness"]["worker_preflight"]["stale"])


    def test_dashboard_status_flags_worker_vm_active_lane_conflicts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            client.post("/control/import/legacy-snapshot", headers=headers, json={
                "idempotency_key": "active-conflict-import",
                "queue_rows": [{
                    "project_id": "idea-active",
                    "project_name": "Active Conflict",
                    "project_dir": "idea-active",
                    "status": "awaiting_wake",
                    "current_run_id": "run-active",
                }],
            })
            ControlPlaneStore(Path(tmp) / "state" / "control_plane.sqlite3").upsert_dashboard_observation(
                source="worker_preflight",
                status="ok",
                payload={
                    "ok": True,
                    "checks": [
                        {"name": "worker_no_live_runs", "ok": True, "detail": "active_or_waiting=0, live=0", "data": {"active_or_waiting": 0, "live": 0}}
                    ],
                },
            )
            status = client.get("/control/api/status", headers=headers).json()
            self.assertTrue(any("active row" in item["message"] for item in status["conflicts"]))
            self.assertFalse(status["dispatch_safe"])


    def test_dashboard_status_flags_worker_live_without_vm_active_row_as_critical(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            ControlPlaneStore(Path(tmp) / "state" / "control_plane.sqlite3").upsert_dashboard_observation(
                source="worker_preflight",
                status="warn",
                payload={
                    "ok": False,
                    "checks": [
                        {"name": "worker_no_live_runs", "ok": False, "detail": "active_or_waiting=1, live=1", "data": {"active_or_waiting": 1, "live": 1}}
                    ],
                },
            )
            status = client.get("/control/api/status", headers=headers).json()
            self.assertTrue(any(item["severity"] == "critical" for item in status["conflicts"]))
            self.assertIn("GB10/VM active-lane conflict", status["dispatch_blockers"])
            self.assertFalse(status["dispatch_safe"])


    def test_dashboard_status_treats_matching_worker_live_lane_as_active_not_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client_with_config(_live_config(tmp))
            headers = {"Authorization": f"Bearer {TOKEN}"}
            client.post("/control/import/legacy-snapshot", headers=headers, json={
                "idempotency_key": "active-matching-worker-import",
                "queue_rows": [{
                    "project_id": "idea-active-match",
                    "project_name": "Active Match",
                    "project_dir": "idea-active-match",
                    "status": "awaiting_wake",
                    "current_run_id": "run-active-match",
                }],
            })
            client.post("/control/resume", headers=headers, json={"resumed_by": "test", "maintenance_mode": False})
            store = ControlPlaneStore(Path(tmp) / "state" / "control_plane.sqlite3")
            store.upsert_dashboard_observation(
                source="worker_preflight",
                status="warn",
                payload={
                    "ok": False,
                    "checks": [
                        {"name": "worker_no_live_runs", "ok": False, "detail": "active_or_waiting=1, live=1", "data": {"active_or_waiting": 1, "live": 1}},
                        {"name": "wake_gate_healthz", "ok": True, "detail": "ok", "data": {}},
                    ],
                },
            )
            store.upsert_dashboard_observation(source="worker_dashboard_api", status="ok", payload={"ok": True})
            status = client.get("/control/api/status", headers=headers).json()
            self.assertFalse(status["dispatch_safe"])
            self.assertEqual(status["dispatch_blockers"], ["active GB10 lane exists"])
            self.assertEqual(status["conflicts"], [])
            self.assertFalse(any(item["source"] == "worker_preflight" and "status is warn" in item["message"] for item in status["warnings"]))

    def test_queue_alert_check_does_not_alert_for_normal_active_lane(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client_with_config(_live_config(tmp))
            headers = {"Authorization": f"Bearer {TOKEN}"}
            client.post("/control/import/legacy-snapshot", headers=headers, json={
                "idempotency_key": "normal-active-alert-import",
                "queue_rows": [{
                    "project_id": "idea-active-normal",
                    "project_name": "Active Normal",
                    "project_dir": "idea-active-normal",
                    "status": "awaiting_wake",
                    "current_run_id": "run-active-normal",
                }],
            })
            client.post("/control/resume", headers=headers, json={"resumed_by": "test", "maintenance_mode": False})
            store = ControlPlaneStore(Path(tmp) / "state" / "control_plane.sqlite3")
            store.upsert_dashboard_observation(
                source="worker_preflight",
                status="warn",
                payload={
                    "ok": False,
                    "checks": [
                        {"name": "worker_no_live_runs", "ok": False, "detail": "active_or_waiting=1, live=1", "data": {"active_or_waiting": 1, "live": 1}},
                        {"name": "wake_gate_healthz", "ok": True, "detail": "ok", "data": {}},
                    ],
                },
            )
            store.upsert_dashboard_observation(source="worker_dashboard_api", status="ok", payload={"ok": True})
            alert = client.post("/control/api/alerts/queue-check", headers=headers, json={"dry_run": True}).json()
            self.assertFalse(alert["should_alert"])
            self.assertEqual(alert["findings"], [])

    def test_queue_alert_check_does_not_persist_event_for_healthy_active_lane(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client_with_config(_live_config(tmp))
            headers = {"Authorization": f"Bearer {TOKEN}"}
            client.post("/control/import/legacy-snapshot", headers=headers, json={
                "idempotency_key": "normal-active-live-alert-import",
                "queue_rows": [{
                    "project_id": "idea-active-live-normal",
                    "project_name": "Active Live Normal",
                    "project_dir": "idea-active-live-normal",
                    "status": "awaiting_wake",
                    "current_run_id": "run-active-live-normal",
                }],
            })
            client.post("/control/resume", headers=headers, json={"resumed_by": "test", "maintenance_mode": False})
            store = ControlPlaneStore(Path(tmp) / "state" / "control_plane.sqlite3")
            store.upsert_dashboard_observation(
                source="worker_preflight",
                status="warn",
                payload={
                    "ok": False,
                    "checks": [
                        {"name": "worker_no_live_runs", "ok": False, "detail": "active_or_waiting=1, live=1", "data": {"active_or_waiting": 1, "live": 1}},
                        {"name": "wake_gate_healthz", "ok": True, "detail": "ok", "data": {}},
                    ],
                },
            )
            store.upsert_dashboard_observation(source="worker_dashboard_api", status="ok", payload={"ok": True})

            alert = client.post("/control/api/alerts/queue-check", headers=headers, json={"dry_run": False}).json()

            self.assertFalse(alert["should_alert"])
            self.assertFalse(alert["inserted_event"])
            self.assertFalse(alert["sent"])
            self.assertEqual(alert["findings"], [])
            events = client.get("/control/api/v1/events?entity_type=queue_alert", headers=headers).json()
            self.assertEqual(events["rows"], [])

    def test_queue_alert_check_suppresses_transient_worker_timeout_during_active_lane(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client_with_config(_live_config(tmp))
            headers = {"Authorization": f"Bearer {TOKEN}"}
            client.post("/control/import/legacy-snapshot", headers=headers, json={
                "idempotency_key": "active-timeout-alert-import",
                "queue_rows": [{
                    "project_id": "idea-active-timeout",
                    "project_name": "Active Timeout",
                    "project_dir": "idea-active-timeout",
                    "status": "awaiting_wake",
                    "current_run_id": "run-active-timeout",
                }],
            })
            client.post("/control/resume", headers=headers, json={"resumed_by": "test", "maintenance_mode": False})
            store = ControlPlaneStore(Path(tmp) / "state" / "control_plane.sqlite3")
            store.upsert_dashboard_observation(
                source="worker_preflight",
                status="warn",
                payload={
                    "ok": False,
                    "checks": [
                        {
                            "name": "worker_no_live_runs",
                            "ok": False,
                            "detail": "active_or_waiting=1, live=1",
                            "data": {"active_or_waiting": 1, "live": 1},
                        },
                        {
                            "name": "wake_gate_healthz",
                            "ok": False,
                            "detail": "wake gate health failed: URLError: <urlopen error timed out>",
                            "data": {},
                        },
                    ],
                },
            )
            store.upsert_dashboard_observation(source="worker_dashboard_api", status="ok", payload={"ok": True})
            alert = client.post("/control/api/alerts/queue-check", headers=headers, json={"dry_run": True}).json()
            self.assertFalse(alert["should_alert"])
            self.assertEqual(alert["findings"], [])

    def test_queue_health_summarizes_active_lane_and_alerts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client_with_config(_live_config(tmp))
            headers = {"Authorization": f"Bearer {TOKEN}"}
            client.post("/control/import/legacy-snapshot", headers=headers, json={
                "idempotency_key": "queue-health-import",
                "queue_rows": [{
                    "project_id": "idea-health",
                    "project_name": "Health Project",
                    "project_dir": "idea-health",
                    "status": "awaiting_wake",
                    "current_run_id": "run-health",
                }],
            })
            client.post("/control/resume", headers=headers, json={"resumed_by": "test", "maintenance_mode": False})
            store = ControlPlaneStore(Path(tmp) / "state" / "control_plane.sqlite3")
            store.upsert_dashboard_observation(
                source="worker_preflight",
                status="warn",
                payload={
                    "ok": False,
                    "checks": [
                        {"name": "worker_no_live_runs", "ok": False, "detail": "active_or_waiting=1, live=1", "data": {"active_or_waiting": 1, "live": 1}},
                        {"name": "wake_gate_healthz", "ok": True, "detail": "ok", "data": {}},
                    ],
                },
            )
            store.upsert_dashboard_observation(source="worker_dashboard_api", status="ok", payload={"ok": True})
            response = client.get("/control/api/queue-health", headers=headers)
            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertEqual(body["source"], "control_api_queue_health")
            self.assertEqual(body["active_run_detail"]["queue_item"]["project_id"], "idea-health")
            self.assertFalse(body["latest_alert_check"]["should_alert"])
            self.assertEqual(body["status"]["dispatch_blockers"], ["active GB10 lane exists"])

    def test_queue_alert_check_alerts_on_active_row_without_worker_live_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client_with_config(_live_config(tmp))
            headers = {"Authorization": f"Bearer {TOKEN}"}
            client.post("/control/import/legacy-snapshot", headers=headers, json={
                "idempotency_key": "hung-active-alert-import",
                "queue_rows": [{
                    "project_id": "idea-hung",
                    "project_name": "Hung Active",
                    "project_dir": "idea-hung",
                    "status": "awaiting_wake",
                    "current_run_id": "run-hung",
                }],
            })
            client.post("/control/resume", headers=headers, json={"resumed_by": "test", "maintenance_mode": False})
            store = ControlPlaneStore(Path(tmp) / "state" / "control_plane.sqlite3")
            store.upsert_dashboard_observation(
                source="worker_preflight",
                status="ok",
                payload={
                    "ok": True,
                    "checks": [
                        {"name": "worker_no_live_runs", "ok": True, "detail": "active_or_waiting=0, live=0", "data": {"active_or_waiting": 0, "live": 0}}
                    ],
                },
            )
            store.upsert_dashboard_observation(source="worker_dashboard_api", status="ok", payload={"ok": True})
            dry_run = client.post("/control/api/alerts/queue-check", headers=headers, json={"dry_run": True}).json()
            self.assertTrue(dry_run["should_alert"])
            self.assertTrue(any("active row" in item["message"] for item in dry_run["findings"]))

            first = client.post("/control/api/alerts/queue-check", headers=headers, json={"dry_run": False}).json()
            self.assertTrue(first["inserted_event"])
            self.assertFalse(first["sent"])
            second = client.post("/control/api/alerts/queue-check", headers=headers, json={"dry_run": False}).json()
            self.assertTrue(second["suppressed_by_cooldown"])

    def test_queue_alert_check_suppresses_dispatch_preflight_race(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client_with_config(_live_config(tmp))
            headers = {"Authorization": f"Bearer {TOKEN}"}
            project_id = "idea-dispatch-race"
            run_id = "run-dispatch-race"
            client.post("/control/import/legacy-snapshot", headers=headers, json={
                "idempotency_key": "dispatch-race-alert-import",
                "queue_rows": [{
                    "project_id": project_id,
                    "project_name": "Dispatch Race",
                    "project_dir": project_id,
                    "status": "awaiting_wake",
                    "current_run_id": run_id,
                }],
            })
            client.post("/control/resume", headers=headers, json={"resumed_by": "test", "maintenance_mode": False})
            store = ControlPlaneStore(Path(tmp) / "state" / "control_plane.sqlite3")
            store.append_event(
                idempotency_key="dispatch-race-live-dispatch",
                event_type="controller.live_dispatch",
                entity_type="project",
                entity_id=project_id,
                payload={"project_id": project_id, "run_id": run_id},
            )
            store.upsert_dashboard_observation(
                source="worker_preflight",
                status="ok",
                payload={
                    "ok": True,
                    "checks": [
                        {"name": "worker_no_live_runs", "ok": True, "detail": "active_or_waiting=0, live=0", "data": {"active_or_waiting": 0, "live": 0}}
                    ],
                },
            )
            store.upsert_dashboard_observation(source="worker_dashboard_api", status="ok", payload={"ok": True})

            alert = client.post("/control/api/alerts/queue-check", headers=headers, json={"dry_run": True}).json()

            self.assertFalse(alert["should_alert"])
            self.assertEqual(alert["findings"], [])
            self.assertTrue(alert["transient_suppressed_findings"])
            self.assertIn("active row", alert["transient_suppressed_findings"][0]["message"])

    def test_queue_alert_check_auto_reconciles_stale_callback_with_local_decision_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _live_config(tmp)
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            project_dir = Path(config.project_root) / "idea-auto-reconcile"
            (project_dir / ".enoch").mkdir(parents=True)
            (project_dir / "run_notes.md").write_text("completed\n", encoding="utf-8")
            (project_dir / ".enoch" / "project_decision.json").write_text(json.dumps({
                "project_decision": "finalize_negative",
                "hypothesis_status": "mixed",
                "confidence": "medium",
                "evidence_strength": "moderate",
                "novelty_progress": True,
                "results_changed": True,
                "recommended_next_action": "stop",
                "stop_reason": "negative",
                "followup_recommended": False,
                "followup_type": "",
                "followup_title": "",
                "followup_hypothesis": "",
                "followup_required_evidence": [],
                "followup_success_threshold": "",
                "followup_stop_condition": "",
                "followup_depth": 0,
            }), encoding="utf-8")
            client.post("/control/import/legacy-snapshot", headers=headers, json={
                "idempotency_key": "auto-reconcile-alert-import",
                "queue_rows": [{
                    "project_id": "idea-auto-reconcile",
                    "project_name": "Auto Reconcile",
                    "project_dir": "idea-auto-reconcile",
                    "status": "awaiting_wake",
                    "current_run_id": "run-auto-reconcile",
                }],
            })
            client.post("/control/resume", headers=headers, json={"resumed_by": "test", "maintenance_mode": False})
            store = ControlPlaneStore(Path(tmp) / "state" / "control_plane.sqlite3")
            store.upsert_dashboard_observation(
                source="worker_preflight",
                status="ok",
                payload={"ok": True, "checks": [{"name": "worker_no_live_runs", "ok": True, "detail": "active_or_waiting=0, live=0", "data": {"active_or_waiting": 0, "live": 0}}]},
            )
            store.upsert_dashboard_observation(source="worker_dashboard_api", status="ok", payload={"ok": True})

            alert = client.post("/control/api/alerts/queue-check", headers=headers, json={"dry_run": False, "requested_by": "test"}).json()

            self.assertFalse(alert["should_alert"])
            self.assertTrue(alert["auto_reconcile"][0]["ok"])
            status = client.get("/control/api/status", headers=headers).json()
            self.assertEqual(status["active_items"], [])

    def test_queue_alert_auto_reconcile_requires_local_paper_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _live_config(tmp)
            config.paper_evidence_sync_enabled = True
            config.paper_evidence_sync_remote_root = "/remote/projects"
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            project_dir = Path(config.project_root) / "idea-auto-reconcile-missing-evidence"
            (project_dir / ".enoch").mkdir(parents=True)
            (project_dir / ".enoch" / "project_decision.json").write_text('{"project_decision":"finalize_positive"}\n', encoding="utf-8")
            client.post("/control/import/legacy-snapshot", headers=headers, json={
                "idempotency_key": "auto-reconcile-missing-evidence-import",
                "queue_rows": [{
                    "project_id": "idea-auto-reconcile-missing-evidence",
                    "project_name": "Auto Reconcile Missing Evidence",
                    "project_dir": "idea-auto-reconcile-missing-evidence",
                    "status": "awaiting_wake",
                    "current_run_id": "run-auto-reconcile-missing-evidence",
                }],
            })
            store = ControlPlaneStore(Path(tmp) / "state" / "control_plane.sqlite3")
            store.upsert_dashboard_observation(
                source="worker_preflight",
                status="ok",
                payload={"ok": True, "checks": [{"name": "worker_no_live_runs", "ok": True, "detail": "active_or_waiting=0, live=0", "data": {"active_or_waiting": 0, "live": 0}}]},
            )
            store.upsert_dashboard_observation(source="worker_dashboard_api", status="ok", payload={"ok": True})

            with patch("enoch_control_plane.control_plane.router._sync_remote_project_evidence", return_value={"enabled": True, "synced": False, "reason": "worker_read_failed", "local_evidence_present": False}):
                alert = client.post("/control/api/alerts/queue-check", headers=headers, json={"dry_run": False, "requested_by": "test"}).json()

            self.assertTrue(alert["auto_reconcile"])
            self.assertFalse(alert["auto_reconcile"][0]["ok"])
            self.assertEqual(alert["auto_reconcile"][0]["reason"], "missing paper evidence")
            status = client.get("/control/api/status", headers=headers).json()
            self.assertEqual(len(status["active_items"]), 1)
            self.assertEqual(status["active_items"][0]["current_run_id"], "run-auto-reconcile-missing-evidence")
            snapshot = client.get("/control/export/snapshot", headers=headers).json()
            events = [event for event in snapshot["events"] if event["event_type"] == "paper.evidence_sync_blocked"]
            self.assertEqual(len(events), 1)


    def test_queue_alert_auto_reconcile_negative_decision_without_paper_evidence_does_not_alert(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _live_config(tmp)
            config.paper_evidence_sync_enabled = True
            config.paper_evidence_sync_remote_root = "/remote/projects"
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            project_dir = Path(config.project_root) / "idea-auto-reconcile-negative-no-paper"
            (project_dir / ".enoch").mkdir(parents=True)
            (project_dir / ".enoch" / "project_decision.json").write_text('{"project_decision":"negative","stop_reason":"no measured signal"}\n', encoding="utf-8")
            client.post("/control/import/legacy-snapshot", headers=headers, json={
                "idempotency_key": "auto-reconcile-negative-no-paper-import",
                "queue_rows": [{
                    "project_id": "idea-auto-reconcile-negative-no-paper",
                    "project_name": "Auto Reconcile Negative No Paper",
                    "project_dir": "idea-auto-reconcile-negative-no-paper",
                    "status": "awaiting_wake",
                    "current_run_id": "run-auto-reconcile-negative-no-paper",
                }],
            })
            store = ControlPlaneStore(Path(tmp) / "state" / "control_plane.sqlite3")
            store.upsert_dashboard_observation(
                source="worker_preflight",
                status="ok",
                payload={"ok": True, "checks": [{"name": "worker_no_live_runs", "ok": True, "detail": "active_or_waiting=0, live=0", "data": {"active_or_waiting": 0, "live": 0}}]},
            )
            store.upsert_dashboard_observation(source="worker_dashboard_api", status="ok", payload={"ok": True})

            with patch("enoch_control_plane.control_plane.router._sync_remote_project_evidence", return_value={"enabled": True, "synced": False, "reason": "worker_read_failed", "local_evidence_present": False}):
                alert = client.post("/control/api/alerts/queue-check", headers=headers, json={"dry_run": False, "requested_by": "test"}).json()

            self.assertTrue(alert["auto_reconcile"])
            self.assertTrue(alert["auto_reconcile"][0]["ok"])
            self.assertEqual(alert["auto_reconcile"][0]["decision_gate"]["reason"], "project decision is not positive")
            status = client.get("/control/api/status", headers=headers).json()
            self.assertEqual(status["active_items"], [])
            snapshot = client.get("/control/export/snapshot", headers=headers).json()
            events = [event for event in snapshot["events"] if event["event_type"] == "paper.evidence_sync_blocked"]
            self.assertEqual(events, [])

    def test_queue_alert_live_check_rejects_supabase_readonly_before_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _live_config(tmp).model_copy(
                update={
                    "control_plane_store_backend": "supabase_readonly",
                    "supabase_database_url": "postgres://example",
                }
            )

            class FakeReadOnlyStore:
                append_attempted = False

                def append_event(self, **_kwargs):  # noqa: ANN001 - must not be called
                    self.append_attempted = True
                    raise AssertionError("read-only queue alert must reject before mutation")

            fake_store = FakeReadOnlyStore()
            with patch("enoch_control_plane.control_plane.router.SupabaseReadOnlyControlPlaneStore", return_value=fake_store):
                client = _client_with_config(config)
                response = client.post(
                    "/control/api/alerts/queue-check",
                    headers={"Authorization": f"Bearer {TOKEN}"},
                    json={"dry_run": False, "requested_by": "test"},
                )

            assert response.status_code == 501
            assert "writable control-plane store" in response.text
            assert fake_store.append_attempted is False

    def test_followup_launch_live_rejects_supabase_readonly_before_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _live_config(tmp).model_copy(
                update={
                    "control_plane_store_backend": "supabase_readonly",
                    "supabase_database_url": "postgres://example",
                }
            )

            class FakeReadOnlyStore:
                launch_attempted = False

                def launch_followup_candidate(self, *_args, **_kwargs):  # noqa: ANN001 - must not be called
                    self.launch_attempted = True
                    raise AssertionError("read-only follow-up launch must reject before mutation")

            fake_store = FakeReadOnlyStore()
            with patch("enoch_control_plane.control_plane.router.SupabaseReadOnlyControlPlaneStore", return_value=fake_store):
                client = _client_with_config(config)
                response = client.post(
                    "/control/api/v1/followups/launch-next",
                    headers={"Authorization": f"Bearer {TOKEN}"},
                    json={"dry_run": False, "requested_by": "test"},
                )

            assert response.status_code == 501
            assert "writable control-plane store" in response.text
            assert fake_store.launch_attempted is False

    def test_publication_claim_rejects_supabase_readonly_before_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _live_config(tmp).model_copy(
                update={
                    "control_plane_store_backend": "supabase_readonly",
                    "supabase_database_url": "postgres://example",
                }
            )

            class FakeReadOnlyStore:
                claim_attempted = False

                def claim_paper_review(self, *_args, **_kwargs):  # noqa: ANN001 - must not be called
                    self.claim_attempted = True
                    raise AssertionError("read-only publication claim must reject before mutation")

            fake_store = FakeReadOnlyStore()
            with patch("enoch_control_plane.control_plane.router.SupabaseReadOnlyControlPlaneStore", return_value=fake_store):
                client = _client_with_config(config)
                response = client.post(
                    "/control/api/publication-automation/paper-1/claim",
                    headers={"Authorization": f"Bearer {TOKEN}"},
                    json={"requested_by": "test", "reviewer": "agent"},
                )

            assert response.status_code == 501
            assert "writable control-plane store" in response.text
            assert fake_store.claim_attempted is False

    def test_worker_callback_clears_active_lane(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client_with_config(_live_config(tmp))
            headers = {"Authorization": f"Bearer {TOKEN}"}
            client.post("/control/import/legacy-snapshot", headers=headers, json={
                "idempotency_key": "worker-callback-import",
                "queue_rows": [{
                    "project_id": "idea-callback",
                    "project_name": "Callback Project",
                    "project_dir": "idea-callback",
                    "status": "awaiting_wake",
                    "current_run_id": "run-callback",
                }],
            })
            response = client.post("/control/api/worker-callback", headers=headers, json={
                "event_type": "wake_ready",
                "run_id": "run-callback",
                "session_id": "session-callback",
                "project_id": "idea-callback",
                "project_name": "Callback Project",
                "source_event": "session-idle",
                "gate_state": "wake_ready",
                "process_tracking": {"root_pid": None, "process_group_id": None, "processes": [], "live_process_count": 0},
                "telemetry": {},
                "reason": "idle_sustain_met",
                "idempotency_key": "run-callback:wake_ready:test",
            })
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["next_action_hint"], "draft_paper_or_select_next_project")
            status = client.get("/control/api/status", headers=headers).json()
            self.assertEqual(status["active_items"], [])

    def test_worker_callback_rejects_supabase_readonly_before_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _live_config(tmp).model_copy(
                update={
                    "control_plane_store_backend": "supabase_readonly",
                    "supabase_database_url": "postgres://example",
                }
            )

            class FakeReadOnlyStore:
                callback_attempted = False

                def record_worker_callback(self, *_args, **_kwargs):  # noqa: ANN001 - must not be called
                    self.callback_attempted = True
                    raise AssertionError("read-only callback must reject before mutation")

            fake_store = FakeReadOnlyStore()
            with patch("enoch_control_plane.control_plane.router.SupabaseReadOnlyControlPlaneStore", return_value=fake_store):
                client = _client_with_config(config)
                response = client.post("/control/api/worker-callback", headers={"Authorization": f"Bearer {TOKEN}"}, json={
                    "event_type": "wake_ready",
                    "run_id": "run-readonly-callback",
                    "session_id": "session-readonly-callback",
                    "project_id": "readonly-callback",
                    "project_name": "Readonly Callback",
                    "source_event": "session-idle",
                    "gate_state": "wake_ready",
                    "process_tracking": {"root_pid": None, "process_group_id": None, "processes": [], "live_process_count": 0},
                    "telemetry": {},
                    "reason": "idle_sustain_met",
                    "idempotency_key": "run-readonly-callback:wake_ready:test",
                })

            assert response.status_code == 501
            assert "writable control-plane store" in response.text
            assert fake_store.callback_attempted is False

    def test_worker_callback_idempotency_replay_and_conflict_are_side_effect_safe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client_with_config(_live_config(tmp))
            headers = {"Authorization": f"Bearer {TOKEN}"}
            client.post("/control/import/legacy-snapshot", headers=headers, json={
                "idempotency_key": "worker-callback-idempotency-import",
                "queue_rows": [{
                    "project_id": "idea-callback-idempotent",
                    "project_name": "Callback Idempotent Project",
                    "project_dir": "idea-callback-idempotent",
                    "status": "awaiting_wake",
                    "current_run_id": "run-callback-idempotent",
                }],
            })
            callback = {
                "event_type": "wake_ready",
                "run_id": "run-callback-idempotent",
                "session_id": "session-callback-idempotent",
                "project_id": "idea-callback-idempotent",
                "project_name": "Callback Idempotent Project",
                "source_event": "session-idle",
                "gate_state": "wake_ready",
                "process_tracking": {"root_pid": None, "process_group_id": None, "processes": [], "live_process_count": 0},
                "telemetry": {},
                "reason": "idle_sustain_met",
                "idempotency_key": "run-callback-idempotent:wake_ready:test",
                "seen_at": "2026-05-03T08:00:00Z",
                "delivered_at": "2026-05-03T08:00:01Z",
            }

            first = client.post("/control/api/worker-callback", headers=headers, json=callback)
            self.assertEqual(first.status_code, 200)
            self.assertTrue(first.json()["inserted_event"])
            replay = client.post("/control/api/worker-callback", headers=headers, json=callback)
            self.assertEqual(replay.status_code, 200)
            self.assertFalse(replay.json()["inserted_event"])
            self.assertEqual(replay.json()["event_id"], first.json()["event_id"])
            conflict = client.post("/control/api/worker-callback", headers=headers, json={**callback, "event_type": "gate_error", "reason": "different outcome"})
            self.assertEqual(conflict.status_code, 409)
            status = client.get("/control/api/status", headers=headers).json()
            self.assertEqual(status["active_items"], [])
            queue = client.get("/control/queue", headers=headers).json()["rows"][0]
            self.assertEqual(queue["last_run_state"], "wake_ready")
            self.assertEqual(queue["next_action_hint"], "draft_paper_or_select_next_project")

    def test_worker_callback_replay_does_not_repeat_evidence_sync(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _live_config(tmp)
            config.paper_evidence_sync_enabled = True
            config.paper_evidence_sync_remote_root = "/remote/projects"
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            client.post("/control/import/legacy-snapshot", headers=headers, json={
                "idempotency_key": "worker-callback-replay-evidence-import",
                "queue_rows": [{
                    "project_id": "idea-callback-replay-evidence",
                    "project_name": "Callback Replay Evidence",
                    "project_dir": "idea-callback-replay-evidence",
                    "status": "awaiting_wake",
                    "current_run_id": "run-callback-replay-evidence",
                }],
            })
            callback = {
                "event_type": "wake_ready",
                "run_id": "run-callback-replay-evidence",
                "session_id": "session-callback-replay-evidence",
                "project_id": "idea-callback-replay-evidence",
                "project_name": "Callback Replay Evidence",
                "source_event": "session-idle",
                "gate_state": "wake_ready",
                "process_tracking": {"root_pid": None, "process_group_id": None, "processes": [], "live_process_count": 0},
                "telemetry": {},
                "reason": "idle_sustain_met",
                "idempotency_key": "run-callback-replay-evidence:wake_ready:test",
            }

            with patch("enoch_control_plane.control_plane.router._sync_remote_project_evidence", return_value={"ok": True, "synced": True}) as sync:
                first = client.post("/control/api/worker-callback", headers=headers, json=callback)
                replay = client.post("/control/api/worker-callback", headers=headers, json=callback)

            self.assertEqual(first.status_code, 200)
            self.assertTrue(first.json()["inserted_event"])
            self.assertIsNotNone(first.json()["decision_sync"])
            self.assertEqual(replay.status_code, 200)
            self.assertFalse(replay.json()["inserted_event"])
            self.assertIsNone(replay.json()["decision_sync"])
            self.assertEqual(sync.call_count, 1)

    def test_worker_callback_evidence_sync_rejects_project_dir_escape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _live_config(tmp)
            config.paper_evidence_sync_enabled = True
            config.paper_evidence_sync_remote_root = "/remote/projects"
            outside = Path(tmp) / "outside"
            outside.mkdir()
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            client.post("/control/import/legacy-snapshot", headers=headers, json={
                "idempotency_key": "worker-callback-project-dir-escape-import",
                "queue_rows": [{
                    "project_id": "idea-callback-project-dir-escape",
                    "project_name": "Callback Project Dir Escape",
                    "project_dir": str(outside),
                    "status": "awaiting_wake",
                    "current_run_id": "run-callback-project-dir-escape",
                }],
            })
            seen: dict[str, Path] = {}

            def fake_sync(_config, *, project_id: str, artifact_root: Path, **kwargs):  # noqa: ANN001 - patched sync boundary
                del _config, project_id, kwargs
                seen["artifact_root"] = artifact_root
                return {"enabled": True, "synced": False, "reason": "worker_read_failed", "local_evidence_present": False}

            with patch("enoch_control_plane.control_plane.router._sync_remote_project_evidence", side_effect=fake_sync):
                response = client.post("/control/api/worker-callback", headers=headers, json={
                    "event_type": "wake_ready",
                    "run_id": "run-callback-project-dir-escape",
                    "session_id": "session-callback-project-dir-escape",
                    "project_id": "idea-callback-project-dir-escape",
                    "project_name": "Callback Project Dir Escape",
                    "source_event": "session-idle",
                    "gate_state": "wake_ready",
                    "process_tracking": {"root_pid": None, "process_group_id": None, "processes": [], "live_process_count": 0},
                    "telemetry": {},
                    "reason": "idle_sustain_met",
                    "idempotency_key": "run-callback-project-dir-escape:wake_ready:test",
                })

            self.assertEqual(response.status_code, 200)
            artifact_root = seen["artifact_root"].resolve()
            artifact_root.relative_to(config.expanded_project_root.resolve())
            self.assertNotEqual(artifact_root, outside.resolve())
            self.assertIn("idea-callback-project-dir-escape", artifact_root.as_posix())

    def test_stale_worker_callback_does_not_trigger_evidence_sync(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _live_config(tmp)
            config.paper_evidence_sync_enabled = True
            config.paper_evidence_sync_remote_root = "/remote/projects"
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            client.post("/control/import/legacy-snapshot", headers=headers, json={
                "idempotency_key": "worker-callback-stale-evidence-import",
                "queue_rows": [{
                    "project_id": "idea-callback-stale-evidence",
                    "project_name": "Callback Stale Evidence",
                    "project_dir": "idea-callback-stale-evidence",
                    "status": "running",
                    "current_run_id": "run-current",
                    "current_session_id": "session-current",
                    "last_run_state": "running",
                    "next_action_hint": "await_callback",
                }],
            })
            callback = {
                "event_type": "wake_ready",
                "run_id": "run-old",
                "session_id": "session-old",
                "project_id": "idea-callback-stale-evidence",
                "project_name": "Callback Stale Evidence",
                "source_event": "session-idle",
                "gate_state": "wake_ready",
                "process_tracking": {"root_pid": None, "process_group_id": None, "processes": [], "live_process_count": 0},
                "telemetry": {},
                "reason": "old callback arrived late",
                "idempotency_key": "run-old:wake_ready:stale-evidence-test",
            }

            with patch("enoch_control_plane.control_plane.router._sync_remote_project_evidence", return_value={"ok": True, "synced": True}) as sync:
                response = client.post("/control/api/worker-callback", headers=headers, json=callback)

            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json()["inserted_event"])
            self.assertIsNone(response.json()["decision_sync"])
            self.assertEqual(sync.call_count, 0)
            queue = client.get("/control/queue", headers=headers).json()["rows"][0]
            self.assertEqual(queue["current_run_id"], "run-current")
            self.assertEqual(queue["last_run_state"], "running")
            self.assertEqual(queue["next_action_hint"], "await_callback")

    def test_worker_callback_missing_evidence_is_visible_but_not_writable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _live_config(tmp)
            config.paper_evidence_sync_enabled = True
            config.paper_evidence_sync_remote_root = "/remote/projects"
            project_dir = Path(tmp) / "projects" / "idea-callback-missing-evidence"
            (project_dir / ".enoch").mkdir(parents=True)
            (project_dir / ".enoch" / "project_decision.json").write_text('{"project_decision":"finalize_positive"}\n', encoding="utf-8")
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            client.post("/control/import/legacy-snapshot", headers=headers, json={
                "idempotency_key": "worker-callback-missing-evidence-import",
                "queue_rows": [{
                    "project_id": "idea-callback-missing-evidence",
                    "project_name": "Callback Missing Evidence",
                    "project_dir": "idea-callback-missing-evidence",
                    "status": "awaiting_wake",
                    "current_run_id": "run-callback-missing-evidence",
                }],
            })

            with patch("enoch_control_plane.control_plane.router._sync_remote_project_evidence", return_value={"enabled": True, "synced": False, "reason": "worker_read_failed", "local_evidence_present": False}):
                response = client.post("/control/api/worker-callback", headers=headers, json={
                    "event_type": "wake_ready",
                    "run_id": "run-callback-missing-evidence",
                    "session_id": "session-callback-missing-evidence",
                    "project_id": "idea-callback-missing-evidence",
                    "project_name": "Callback Missing Evidence",
                    "source_event": "session-idle",
                    "gate_state": "wake_ready",
                    "process_tracking": {"root_pid": None, "process_group_id": None, "processes": [], "live_process_count": 0},
                    "telemetry": {},
                    "reason": "idle_sustain_met",
                    "idempotency_key": "run-callback-missing-evidence:wake-ready-test",
                })

            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json()["inserted_event"])
            decision_sync = response.json()["decision_sync"]
            self.assertIsNotNone(decision_sync)
            self.assertEqual(decision_sync["evidence_sync"]["reason"], "worker_read_failed")
            if "decision_record" in decision_sync:
                self.assertEqual(decision_sync["decision_record"]["persisted"], False)
            overview = client.get("/control/api/v1/overview", headers=headers).json()
            self.assertEqual(overview["paper_pipeline"]["write_needed"], 0)
            self.assertEqual(overview["operator_counts"]["write_paper"], 0)
            snapshot = client.get("/control/export/snapshot", headers=headers).json()
            events = [event for event in snapshot["events"] if event["event_type"] == "paper.evidence_sync_blocked"]
            self.assertEqual(len(events), 1)
            self.assertEqual(snapshot["paper_rows"], [])


    def test_worker_callback_negative_decision_missing_run_notes_does_not_alert_paper_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _live_config(tmp)
            config.paper_evidence_sync_enabled = True
            config.paper_evidence_sync_remote_root = "/remote/projects"
            project_dir = Path(tmp) / "projects" / "idea-callback-negative-no-paper"
            (project_dir / ".enoch").mkdir(parents=True)
            (project_dir / ".enoch" / "project_decision.json").write_text('{"project_decision":"negative","stop_reason":"no measured signal"}\n', encoding="utf-8")
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            client.post("/control/import/legacy-snapshot", headers=headers, json={
                "idempotency_key": "worker-callback-negative-no-paper-import",
                "queue_rows": [{
                    "project_id": "idea-callback-negative-no-paper",
                    "project_name": "Callback Negative No Paper",
                    "project_dir": "idea-callback-negative-no-paper",
                    "status": "awaiting_wake",
                    "current_run_id": "run-callback-negative-no-paper",
                }],
            })

            with patch("enoch_control_plane.control_plane.router._sync_remote_project_evidence", return_value={"enabled": True, "synced": False, "reason": "worker_read_failed", "local_evidence_present": False}):
                response = client.post("/control/api/worker-callback", headers=headers, json={
                    "event_type": "wake_ready",
                    "run_id": "run-callback-negative-no-paper",
                    "session_id": "session-callback-negative-no-paper",
                    "project_id": "idea-callback-negative-no-paper",
                    "project_name": "Callback Negative No Paper",
                    "source_event": "session-idle",
                    "gate_state": "wake_ready",
                    "process_tracking": {"root_pid": None, "process_group_id": None, "processes": [], "live_process_count": 0},
                    "telemetry": {},
                    "reason": "idle_sustain_met",
                    "idempotency_key": "run-callback-negative-no-paper:wake-ready-test",
                })

            self.assertEqual(response.status_code, 200)
            decision_sync = response.json()["decision_sync"]
            self.assertIsNotNone(decision_sync)
            self.assertEqual(decision_sync["decision_gate"]["reason"], "project decision is not positive")
            snapshot = client.get("/control/export/snapshot", headers=headers).json()
            events = [event for event in snapshot["events"] if event["event_type"] == "paper.evidence_sync_blocked"]
            self.assertEqual(events, [])
            overview = client.get("/control/api/v1/overview", headers=headers).json()
            self.assertEqual(overview["operator_counts"]["write_paper"], 0)

    def test_worker_callback_decision_persist_failure_does_not_500_after_accepting_callback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "projects" / "idea-callback-decision-fail"
            (project_dir / ".enoch").mkdir(parents=True)
            (project_dir / "run_notes.md").write_text("Verified useful result.\n", encoding="utf-8")
            (project_dir / ".enoch" / "project_decision.json").write_text('{"project_decision":"finalize_positive"}\n', encoding="utf-8")
            client = _client_with_config(_live_config(tmp))
            headers = {"Authorization": f"Bearer {TOKEN}"}
            client.post("/control/import/legacy-snapshot", headers=headers, json={
                "idempotency_key": "worker-callback-decision-fail-import",
                "queue_rows": [{
                    "project_id": "idea-callback-decision-fail",
                    "project_name": "Callback Decision Fail",
                    "project_dir": "idea-callback-decision-fail",
                    "status": "awaiting_wake",
                    "current_run_id": "run-callback-decision-fail",
                }],
            })

            def fail_decision_persist(self, **_kwargs):  # noqa: ANN001 - monkeypatched method
                raise RuntimeError("simulated decision persist failure")

            with patch.object(ControlPlaneStore, "record_project_decision_gate", fail_decision_persist, create=True):
                response = client.post("/control/api/worker-callback", headers=headers, json={
                    "event_type": "wake_ready",
                    "run_id": "run-callback-decision-fail",
                    "session_id": "session-callback-decision-fail",
                    "project_id": "idea-callback-decision-fail",
                    "project_name": "Callback Decision Fail",
                    "source_event": "session-idle",
                    "gate_state": "wake_ready",
                    "process_tracking": {"root_pid": None, "process_group_id": None, "processes": [], "live_process_count": 0},
                    "telemetry": {},
                    "reason": "idle_sustain_met",
                    "idempotency_key": "run-callback-decision-fail:wake-ready-test",
                })

            assert response.status_code == 200
            body = response.json()
            assert body["inserted_event"] is True
            assert body["decision_sync"]["decision_record"]["persisted"] is False
            assert "simulated decision persist failure" in body["decision_sync"]["decision_record"]["reason"]
            queue = client.get("/control/queue", headers=headers).json()["rows"][0]
            assert queue["last_run_state"] == "wake_ready"

    def test_worker_callback_wake_ready_can_draft_paper_when_evidence_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "projects" / "idea-callback-draft"
            (project_dir / ".omx").mkdir(parents=True)
            (project_dir / "run_notes.md").write_text("Verified useful result.\n", encoding="utf-8")
            (project_dir / ".omx" / "project_decision.json").write_text('{"decision":"finalize_positive"}\n', encoding="utf-8")
            client = _client_with_config(_live_config(tmp))
            headers = {"Authorization": f"Bearer {TOKEN}"}
            client.post("/control/import/legacy-snapshot", headers=headers, json={
                "idempotency_key": "worker-callback-draft-import",
                "queue_rows": [{
                    "project_id": "idea-callback-draft",
                    "project_name": "Callback Draft Project",
                    "project_dir": "idea-callback-draft",
                    "status": "awaiting_wake",
                    "current_run_id": "run-callback-draft",
                }],
            })
            response = client.post("/control/api/worker-callback", headers=headers, json={
                "event_type": "wake_ready",
                "run_id": "run-callback-draft",
                "session_id": "session-callback-draft",
                "project_id": "idea-callback-draft",
                "project_name": "Callback Draft Project",
                "source_event": "session-idle",
                "gate_state": "wake_ready",
                "process_tracking": {"root_pid": None, "process_group_id": None, "processes": [], "live_process_count": 0},
                "telemetry": {},
                "reason": "idle_sustain_met",
                "idempotency_key": "run-callback-draft:wake_ready:test",
            })
            self.assertEqual(response.status_code, 200)
            state_after_import = client.get("/control/state", headers=headers).json()
            self.assertIsNone(state_after_import["next_candidate"])
            self.assertEqual(state_after_import["counts"]["queue_total"], 1)
            self.assertEqual(state_after_import["counts"]["papers"], 0)

            draft = client.post("/control/papers/draft-next", headers=headers, json={"force": True})
            self.assertEqual(draft.status_code, 200)
            self.assertEqual(draft.json()["action"], "drafted")
            self.assertEqual(draft.json()["candidate"]["project_id"], "idea-callback-draft")
            paper_id = draft.json()["paper"]["paper_id"]
            rewrite = client.post(f"/control/api/paper-reviews/{paper_id}/rewrite-draft", headers=headers, json={
                "idempotency_key": "worker-callback-draft-rewrite",
                "requested_by": "test",
                "force": True,
            })
            self.assertEqual(rewrite.status_code, 200)
            self.assertEqual(rewrite.json()["paper"]["paper_status"], "publication_draft")
            self.assertEqual(rewrite.json()["item"]["review_status"], "finalized")
            self.assertTrue(Path(rewrite.json()["item"]["finalization_package_path"]).exists())
            events = client.get("/control/export/snapshot", headers=headers).json()["events"]
            event_types = {event["event_type"] for event in events}
            self.assertIn("paper.drafted", event_types)
            self.assertIn("paper_review.draft_rewritten", event_types)
            self.assertIn("paper_review.finalization_package_prepared", event_types)
            reviews = client.get("/control/api/paper-reviews?review_status=finalized", headers=headers).json()
            self.assertEqual(reviews["page"]["total"], 1)
            self.assertEqual(reviews["rows"][0]["project_id"], "idea-callback-draft")

    def test_worker_callback_wake_ready_negative_decision_is_not_drafted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "projects" / "idea-callback-negative"
            (project_dir / ".omx").mkdir(parents=True)
            (project_dir / "run_notes.md").write_text("Ran successfully but the result was negative.\n", encoding="utf-8")
            (project_dir / ".omx" / "project_decision.json").write_text('{"decision":"negative_result"}\n', encoding="utf-8")
            client = _client_with_config(_live_config(tmp))
            headers = {"Authorization": f"Bearer {TOKEN}"}
            client.post("/control/import/legacy-snapshot", headers=headers, json={
                "idempotency_key": "worker-callback-negative-import",
                "queue_rows": [{
                    "project_id": "idea-callback-negative",
                    "project_name": "Callback Negative Project",
                    "project_dir": "idea-callback-negative",
                    "status": "completed",
                    "last_run_state": "wake_ready",
                    "next_action_hint": "draft_paper_or_select_next_project",
                    "current_run_id": "run-callback-negative",
                }],
            })
            draft = client.post("/control/papers/draft-next", headers=headers, json={"force": True})
            self.assertEqual(draft.status_code, 200)
            self.assertEqual(draft.json()["action"], "noop")
            self.assertIn("project decision", draft.json()["candidate"]["skipped"][0]["reason"])
            snapshot = client.get("/control/export/snapshot", headers=headers).json()
            self.assertEqual(snapshot["paper_rows"], [])
            self.assertEqual(client.get("/control/api/paper-reviews", headers=headers).json()["page"]["total"], 0)

    def test_paper_draft_writer_failure_does_not_mutate_project_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            original_dir = "idea-draft-fail"
            project_dir = Path(tmp) / "projects" / original_dir
            (project_dir / ".omx").mkdir(parents=True)
            (project_dir / "run_notes.md").write_text("Verified useful result.\n", encoding="utf-8")
            (project_dir / ".omx" / "project_decision.json").write_text('{"decision":"finalize_positive"}\n', encoding="utf-8")
            response = client.post("/control/import/legacy-snapshot", headers=headers, json={
                "idempotency_key": "import-draft-failure",
                "queue_rows": [{
                    "project_id": "idea-draft-fail",
                    "project_name": "Draft Failure",
                    "project_dir": original_dir,
                    "status": "completed",
                    "last_run_state": "wake_ready",
                    "next_action_hint": "draft_paper_or_select_next_project",
                    "current_run_id": "run-draft-fail",
                    "manual_review_required": False,
                }],
                "paper_rows": [],
            })
            self.assertEqual(response.status_code, 200)
            with patch("enoch_control_plane.control_plane.router.write_paper_artifacts", side_effect=RuntimeError("writer exploded")):
                with self.assertRaisesRegex(RuntimeError, "writer exploded"):
                    client.post("/control/papers/draft-next", headers=headers, json={"force": True})
            snapshot = client.get("/control/export/snapshot", headers=headers).json()
            project = next(row for row in snapshot["queue_rows"] if row["project_id"] == "idea-draft-fail")
            self.assertEqual(project["project_dir"], original_dir)
            self.assertEqual(snapshot["paper_rows"], [])

    def test_ideas_observation_endpoint_refreshes_status_freshness(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            response = client.post("/control/api/intake/ideas-observation", headers=headers, json={"status": "warn", "payload": {"reason": "supabase intake smoke"}})
            self.assertEqual(response.status_code, 200)
            status = client.get("/control/api/status", headers=headers).json()
            ideas = status["source_freshness"]["idea_intake"]
            self.assertFalse(ideas["stale"])
            self.assertEqual(ideas["status"], "warn")

            missing = client.post("/control/api/intake/ideas-observation", headers=headers, json={"status": "missing", "payload": {"reason": "legacy missing status"}})
            self.assertEqual(missing.status_code, 200)
            self.assertEqual(missing.json()["observation"]["status"], "warn")

    def test_intake_observation_rejects_supabase_readonly_before_store_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _live_config(tmp).model_copy(
                update={
                    "control_plane_store_backend": "supabase_readonly",
                    "supabase_database_url": "postgres://example",
                }
            )

            class FakeReadOnlyStore:
                observation_attempted = False

                def upsert_dashboard_observation(self, **_kwargs):  # noqa: ANN001 - must not be called
                    self.observation_attempted = True
                    raise AssertionError("read-only observation endpoint must reject before mutation")

            fake_store = FakeReadOnlyStore()
            with patch("enoch_control_plane.control_plane.router.SupabaseReadOnlyControlPlaneStore", return_value=fake_store):
                client = _client_with_config(config)
                response = client.post(
                    "/control/api/intake/ideas-observation",
                    headers={"Authorization": f"Bearer {TOKEN}"},
                    json={"status": "ok", "payload": {"reason": "test"}},
                )

            assert response.status_code == 501
            assert "writable control-plane store" in response.text
            assert fake_store.observation_attempted is False

    def test_worker_preflight_endpoint_requires_auth_and_returns_checks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _config(tmp).model_copy(update={"worker_wake_gate_url": "http://127.0.0.1:1"})
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            response = client.post("/control/worker/preflight", headers=headers, json={"wake_gate_url": "http://127.0.0.1:1"})
            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertFalse(body["ok"])
            self.assertTrue(any(check["name"] == "wake_gate_healthz" for check in body["checks"]))

    def test_worker_preflight_endpoint_uses_configured_worker_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _config(tmp).model_copy(update={"worker_wake_gate_url": "http://configured-worker:8787"})
            expected = WorkerPreflightResponse(ok=True, target=config.worker_wake_gate_url, summary="ok", checks=[])
            with patch("enoch_control_plane.control_plane.router.run_worker_preflight", return_value=expected) as mocked_preflight:
                client = _client_with_config(config)
                response = client.post(
                    "/control/worker/preflight",
                    headers={"Authorization": f"Bearer {TOKEN}"},
                    json={"wake_gate_url": "http://attacker-controlled:8080"},
                )

            self.assertEqual(response.status_code, 200)
            called_payload = mocked_preflight.call_args.args[0]
            self.assertEqual(called_payload.wake_gate_url, config.worker_wake_gate_url)
            self.assertEqual(response.json()["target"], config.worker_wake_gate_url)

    def test_worker_preflight_endpoint_uses_configured_worker_token(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _config(tmp).model_copy(
                update={
                    "worker_wake_gate_url": "http://configured-worker:8787",
                    "worker_wake_gate_bearer_token": "configured-worker-token",
                }
            )
            expected = WorkerPreflightResponse(ok=True, target=config.worker_wake_gate_url, summary="ok", checks=[])
            with patch("enoch_control_plane.control_plane.router.run_worker_preflight", return_value=expected) as mocked_preflight:
                client = _client_with_config(config)
                response = client.post(
                    "/control/worker/preflight",
                    headers={"Authorization": f"Bearer {TOKEN}"},
                    json={"wake_gate_url": "http://attacker-controlled:8080", "bearer_token": "attacker-token"},
                )

            self.assertEqual(response.status_code, 200)
            called_payload = mocked_preflight.call_args.args[0]
            self.assertEqual(called_payload.bearer_token, config.worker_wake_gate_bearer_token)

    def test_worker_preflight_rejects_placeholder_worker_url_with_token(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _config(tmp).model_copy(update={"worker_wake_gate_bearer_token": "configured-worker-token"})
            with patch("enoch_control_plane.control_plane.router.run_worker_preflight") as mocked_preflight:
                client = _client_with_config(config)
                response = client.post(
                    "/control/worker/preflight",
                    headers={"Authorization": f"Bearer {TOKEN}"},
                    json={"wake_gate_url": "http://attacker-controlled:8080"},
                )

            self.assertEqual(response.status_code, 503)
            self.assertIn("configured worker_wake_gate_url", response.text)
            mocked_preflight.assert_not_called()

    def test_worker_preflight_supabase_readonly_skips_observation_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _live_config(tmp).model_copy(
                update={
                    "control_plane_store_backend": "supabase_readonly",
                    "supabase_database_url": "postgres://example",
                    "worker_wake_gate_url": "http://worker",
                }
            )

            class FakeReadOnlyStore:
                observation_attempted = False

                def flags(self):
                    from enoch_control_plane.control_plane.models import ControlFlags

                    return ControlFlags(queue_paused=False, maintenance_mode=False)

                def upsert_dashboard_observation(self, **_kwargs):  # noqa: ANN001 - must not be called
                    self.observation_attempted = True
                    raise AssertionError("read-only preflight must not write dashboard observations")

            fake_store = FakeReadOnlyStore()
            preflight = WorkerPreflightResponse(
                ok=True,
                target="http://worker",
                summary="ok",
                checks=[WorkerPreflightCheck(name="wake_gate_healthz", ok=True, detail="ok")],
            )
            with (
                patch("enoch_control_plane.control_plane.router.SupabaseReadOnlyControlPlaneStore", return_value=fake_store),
                patch("enoch_control_plane.control_plane.router.run_worker_preflight", return_value=preflight),
            ):
                client = _client_with_config(config)
                response = client.post("/control/worker/preflight", headers={"Authorization": f"Bearer {TOKEN}"}, json={"wake_gate_url": "http://worker"})

            assert response.status_code == 200
            assert response.json()["ok"] is True
            assert fake_store.observation_attempted is False


    def test_live_dispatch_stays_disabled_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            project_dir = Path(tmp) / "projects" / "idea-live"
            project_dir.mkdir(parents=True)
            response = client.post("/control/import/legacy-snapshot", headers=headers, json={
                "idempotency_key": "live-disabled-import",
                "queue_rows": [{
                    "project_id": "idea-live",
                    "project_name": "Live Disabled",
                    "project_dir": "idea-live",
                    "status": "queued",
                }],
            })
            self.assertEqual(response.status_code, 200)
            client.post("/control/resume", headers=headers, json={"resumed_by": "test", "maintenance_mode": False})
            dispatch = client.post("/control/dispatch-next", headers=headers, json={"dry_run": False})
            self.assertEqual(dispatch.status_code, 501)
            self.assertIn("live dispatch is disabled", dispatch.text)


    def test_live_dispatch_cannot_bypass_worker_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _live_config(tmp).model_copy(update={"worker_wake_gate_url": "http://127.0.0.1:1"})
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            client.post("/control/import/legacy-snapshot", headers=headers, json={
                "idempotency_key": "preflight-bypass-import",
                "queue_rows": [{
                    "project_id": "idea-live",
                    "project_name": "Live Preflight Required",
                    "project_dir": "idea-live",
                    "status": "queued",
                }],
            })
            client.post("/control/resume", headers=headers, json={"resumed_by": "test", "maintenance_mode": False})
            dispatch = client.post("/control/dispatch-next", headers=headers, json={"dry_run": False, "force_preflight": False})
            self.assertEqual(dispatch.status_code, 409)
            self.assertIn("worker preflight failed", dispatch.text)
            self.assertIn("force_preflight_ignored", dispatch.text)
            state = client.get("/control/state", headers=headers).json()
            self.assertEqual(state["counts"]["queued"], 1)
            self.assertEqual(state["counts"].get("dispatching", 0), 0)

    def test_live_dispatch_rejects_supabase_readonly_before_claim_or_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _live_config(tmp).model_copy(
                update={
                    "control_plane_store_backend": "supabase_readonly",
                    "supabase_database_url": "postgres://example",
                }
            )

            class FakeReadOnlyStore:
                claim_attempted = False

                def active_items(self) -> list[dict[str, object]]:
                    return []

                def next_dispatch_candidate(self) -> dict[str, object]:
                    return {"project_id": "readonly-dispatch", "project_name": "Readonly Dispatch", "project_dir": "readonly-dispatch"}

                def claim_dispatch_candidate(self, **_kwargs):  # noqa: ANN001 - must not be called
                    self.claim_attempted = True
                    raise AssertionError("read-only dispatch must reject before claiming")

            fake_store = FakeReadOnlyStore()
            with (
                patch("enoch_control_plane.control_plane.router.SupabaseReadOnlyControlPlaneStore", return_value=fake_store),
                patch("enoch_control_plane.control_plane.router.run_worker_preflight", side_effect=AssertionError("preflight must not run")),
            ):
                client = _client_with_config(config)
                response = client.post("/control/dispatch-next", headers={"Authorization": f"Bearer {TOKEN}"}, json={"dry_run": False})

            assert response.status_code == 501
            assert "writable control-plane store" in response.text
            assert fake_store.claim_attempted is False

    def test_operator_pause_rejects_supabase_readonly_without_store_exception(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _live_config(tmp).model_copy(
                update={
                    "control_plane_store_backend": "supabase_readonly",
                    "supabase_database_url": "postgres://example",
                }
            )

            class FakeReadOnlyStore:
                pause_attempted = False

                def pause(self, **_kwargs):  # noqa: ANN001 - must not be called
                    self.pause_attempted = True
                    raise AssertionError("read-only pause must reject before mutation")

            fake_store = FakeReadOnlyStore()
            with patch("enoch_control_plane.control_plane.router.SupabaseReadOnlyControlPlaneStore", return_value=fake_store):
                client = _client_with_config(config)
                response = client.post("/control/pause", headers={"Authorization": f"Bearer {TOKEN}"}, json={"reason": "test"})

            assert response.status_code == 501
            assert "writable control-plane store" in response.text
            assert fake_store.pause_attempted is False

    def test_dispatch_one_dry_run_works_while_paused_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            client.post("/control/import/legacy-snapshot", headers=headers, json={
                "idempotency_key": "dispatch-one-dry-import",
                "queue_rows": [
                    {"project_id": "idea-one", "project_name": "One", "project_dir": "idea-one", "status": "queued", "dispatch_priority": 20},
                    {"project_id": "idea-two", "project_name": "Two", "project_dir": "idea-two", "status": "queued", "dispatch_priority": 10},
                ],
            })

            before = client.get("/control/state", headers=headers).json()
            self.assertTrue(before["flags"]["queue_paused"])
            self.assertEqual(before["counts"]["queued"], 2)

            response = client.post("/control/dispatch-one", headers=headers, json={"project_id": "idea-one"})
            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertEqual(body["action"], "dry_run_dispatch_one")
            self.assertEqual(body["candidate"]["project_id"], "idea-one")

            after = client.get("/control/state", headers=headers).json()
            self.assertTrue(after["flags"]["queue_paused"])
            self.assertEqual(after["counts"]["queued"], 2)
            rows = client.get("/control/queue", headers=headers).json()["rows"]
            self.assertEqual({row["project_id"]: row["status"] for row in rows}, {"idea-one": "queued", "idea-two": "queued"})


    def test_dispatch_one_live_works_while_paused_and_only_dispatches_specified_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _live_config(tmp)
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            client.post("/control/import/legacy-snapshot", headers=headers, json={
                "idempotency_key": "dispatch-one-live-import",
                "queue_rows": [
                    {"project_id": "idea-one", "project_name": "One", "project_dir": "idea-one", "status": "queued", "dispatch_priority": 20},
                    {"project_id": "idea-two", "project_name": "Two", "project_dir": "idea-two", "status": "queued", "dispatch_priority": 10},
                ],
            })
            client.post("/control/pause", headers=headers, json={"paused_by": "test", "reason": "paused but not maintenance", "maintenance_mode": False})
            preflight = WorkerPreflightResponse(ok=True, target=config.worker_wake_gate_url, summary="ok", checks=[])

            def fake_post(_base: str, path: str, _token: str, payload: dict) -> HttpResult:
                if path == "/prepare-project":
                    return HttpResult(ok=True, status=200, body={"prepared": payload["project_id"]})
                if path == "/dispatch":
                    return HttpResult(ok=True, status=200, body={"dispatch": {"session_id": "session-one"}, "project_id": payload["project_id"]})
                return HttpResult(ok=False, status=404, body=None, error="unexpected path")

            with patch("enoch_control_plane.control_plane.router.run_worker_preflight", return_value=preflight), \
                 patch("enoch_control_plane.control_plane.router.post_worker_json", side_effect=fake_post):
                response = client.post("/control/dispatch-one", headers=headers, json={"project_id": "idea-one", "dry_run": False})

            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertEqual(body["action"], "live_dispatch_one")
            self.assertEqual(body["candidate"]["project_id"], "idea-one")
            self.assertEqual(body["candidate"]["status"], "awaiting_wake")
            self.assertEqual(body["live"]["project_id"], "idea-one")
            self.assertEqual(body["live"]["dispatch"]["dispatch"]["session_id"], "session-one")

            state = client.get("/control/state", headers=headers).json()
            self.assertTrue(state["flags"]["queue_paused"])
            self.assertFalse(state["flags"]["maintenance_mode"])
            self.assertEqual(state["counts"].get("awaiting_wake"), 1)
            self.assertEqual(state["counts"].get("queued"), 1)
            rows = {row["project_id"]: row for row in client.get("/control/queue", headers=headers).json()["rows"]}
            self.assertEqual(rows["idea-one"]["status"], "awaiting_wake")
            self.assertEqual(rows["idea-two"]["status"], "queued")
            self.assertFalse(rows["idea-two"].get("current_run_id"))

    def test_dispatch_one_live_tolerates_malformed_dispatch_success_body(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _live_config(tmp)
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            client.post("/control/import/legacy-snapshot", headers=headers, json={
                "idempotency_key": "dispatch-malformed-body-import",
                "queue_rows": [{
                    "project_id": "idea-malformed-dispatch-body",
                    "project_name": "Malformed Dispatch Body",
                    "project_dir": "idea-malformed-dispatch-body",
                    "status": "queued",
                }],
            })
            client.post("/control/pause", headers=headers, json={"paused_by": "test", "reason": "paused but not maintenance", "maintenance_mode": False})
            preflight = WorkerPreflightResponse(ok=True, target=config.worker_wake_gate_url, summary="ok", checks=[])

            def fake_post(_base: str, path: str, _token: str, payload: dict) -> HttpResult:
                if path == "/prepare-project":
                    return HttpResult(ok=True, status=200, body={"prepared": payload["project_id"]})
                if path == "/dispatch":
                    return HttpResult(ok=True, status=200, body=[{"accepted": True}])  # type: ignore[arg-type]
                return HttpResult(ok=False, status=404, body=None, error="unexpected path")

            with patch("enoch_control_plane.control_plane.router.run_worker_preflight", return_value=preflight), \
                 patch("enoch_control_plane.control_plane.router.post_worker_json", side_effect=fake_post):
                response = client.post("/control/dispatch-one", headers=headers, json={"project_id": "idea-malformed-dispatch-body", "dry_run": False})

            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertEqual(body["action"], "live_dispatch_one")
            self.assertEqual(body["live"]["dispatch"], {})
            rows = {row["project_id"]: row for row in client.get("/control/queue", headers=headers).json()["rows"]}
            self.assertEqual(rows["idea-malformed-dispatch-body"]["status"], "awaiting_wake")
            self.assertTrue(rows["idea-malformed-dispatch-body"].get("current_run_id"))


    def test_live_dispatch_persists_safe_worker_project_dir_for_long_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _live_config(tmp)
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            long_project_id = "deterministic-dropout-fingerprinting-for-cheat-resistant-volunteer-gradient-validation-e2abfed2f995"
            client.post("/control/import/legacy-snapshot", headers=headers, json={
                "idempotency_key": "dispatch-long-id-import",
                "queue_rows": [{
                    "project_id": long_project_id,
                    "project_name": "Long ID",
                    "project_dir": long_project_id,
                    "status": "queued",
                }],
            })
            client.post("/control/pause", headers=headers, json={"paused_by": "test", "reason": "paused but not maintenance", "maintenance_mode": False})
            preflight = WorkerPreflightResponse(ok=True, target=config.worker_wake_gate_url, summary="ok", checks=[])
            prepare_payloads: list[dict] = []

            def fake_post(_base: str, path: str, _token: str, payload: dict) -> HttpResult:
                if path == "/prepare-project":
                    prepare_payloads.append(payload)
                    return HttpResult(ok=True, status=200, body={"prepared": payload["project_id"]})
                if path == "/dispatch":
                    return HttpResult(ok=True, status=200, body={"dispatch": {"session_id": "session-long"}, "project_id": payload["project_id"]})
                return HttpResult(ok=False, status=404, body=None, error="unexpected path")

            with patch("enoch_control_plane.control_plane.router.run_worker_preflight", return_value=preflight), \
                 patch("enoch_control_plane.control_plane.router.post_worker_json", side_effect=fake_post):
                response = client.post("/control/dispatch-one", headers=headers, json={"project_id": long_project_id, "dry_run": False})

            self.assertEqual(response.status_code, 200)
            safe_dir = prepare_payloads[0]["project_dir"]
            self.assertLessEqual(len(safe_dir), 96)
            self.assertTrue(long_project_id.startswith(safe_dir))
            rows = {row["project_id"]: row for row in client.get("/control/queue", headers=headers).json()["rows"]}
            self.assertEqual(rows[long_project_id]["project_dir"], safe_dir)


    def test_dispatch_one_rejects_invalid_or_unsafe_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _live_config(tmp)
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            client.post("/control/import/legacy-snapshot", headers=headers, json={
                "idempotency_key": "dispatch-one-reject-import",
                "queue_rows": [
                    {"project_id": "idea-queued", "project_name": "Queued", "project_dir": "idea-queued", "status": "queued"},
                    {"project_id": "idea-completed", "project_name": "Done", "project_dir": "idea-completed", "status": "completed"},
                ],
            })

            missing = client.post("/control/dispatch-one", headers=headers, json={"project_id": ""})
            self.assertEqual(missing.status_code, 400)
            unknown = client.post("/control/dispatch-one", headers=headers, json={"project_id": "missing"})
            self.assertEqual(unknown.status_code, 404)
            non_queued = client.post("/control/dispatch-one", headers=headers, json={"project_id": "idea-completed"})
            self.assertEqual(non_queued.status_code, 409)

            # Existing /dispatch-next behavior is unchanged: paused dry-runs still report paused.
            dispatch_next = client.post("/control/dispatch-next", headers=headers, json={"dry_run": True})
            self.assertEqual(dispatch_next.status_code, 200)
            self.assertEqual(dispatch_next.json()["action"], "paused")


    def test_dispatch_one_rejects_when_active_item_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            client.post("/control/import/legacy-snapshot", headers=headers, json={
                "idempotency_key": "dispatch-one-active-import",
                "queue_rows": [
                    {"project_id": "idea-active", "project_name": "Active", "project_dir": "idea-active", "status": "awaiting_wake", "current_run_id": "run-active"},
                    {"project_id": "idea-queued", "project_name": "Queued", "project_dir": "idea-queued", "status": "queued"},
                ],
            })

            response = client.post("/control/dispatch-one", headers=headers, json={"project_id": "idea-queued"})
            self.assertEqual(response.status_code, 409)
            self.assertIn("active GB10 lane already exists", response.text)


    def test_dashboard_queue_project_run_paper_events_and_intake_apis(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "projects" / "idea-api"
            project_dir.mkdir(parents=True)
            client = _client(tmp)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            client.post("/control/import/legacy-snapshot", headers=headers, json={
                "idempotency_key": "dashboard-api-import",
                "source": "test-snapshot",
                "queue_rows": [{
                    "project_id": "idea-api",
                    "project_name": "API Project",
                    "project_dir": str(project_dir),
                    "status": "queued",
                    "dispatch_priority": 7,
                    "selection_rank": 3,
                    "current_run_id": "run-api",
                    "notion_page_url": "https://notion.example/idea-api",
                }],
                "paper_rows": [{
                    "paper_id": "idea-api:run-api:arxiv_draft",
                    "project_id": "idea-api",
                    "run_id": "run-api",
                    "paper_status": "draft_review",
                    "draft_markdown_path": "papers/run-api/paper.md",
                    "draft_latex_path": "papers/run-api/paper.tex",
                    "evidence_bundle_path": "papers/run-api/evidence.json",
                    "claim_ledger_path": "papers/run-api/claims.json",
                    "manifest_path": "papers/run-api/manifest.json",
                }],
            })
            ideas = client.post("/control/intake/ideas", headers=headers, json={
                "idempotency_key": "dashboard-api-ideas",
                "dry_run": False,
                "ideas": [{
                    "idea_id": "dashboard-api-idea",
                    "title": "Ideas Intake API",
                    "idea_status": "testing",
                    "priority": "High",
                }, {"idea_status": "testing"}],
            })
            self.assertEqual(ideas.status_code, 200)

            queued = client.get("/control/api/queues/queued?search=API&page_size=10", headers=headers)
            self.assertEqual(queued.status_code, 200)
            queued_body = queued.json()
            self.assertEqual(queued_body["source"], "control_api_queue")
            self.assertGreaterEqual(queued_body["page"]["total"], 1)
            self.assertTrue(any(row["project_id"] == "idea-api" for row in queued_body["rows"]))
            self.assertIn("control_plane_db", queued_body["source_freshness"])
            self.assertIn("conflicts", queued_body)

            project = client.get("/control/api/projects/idea-api", headers=headers)
            self.assertEqual(project.status_code, 200)
            self.assertEqual(project.json()["queue_item"]["project_id"], "idea-api")
            self.assertEqual(len(project.json()["papers"]), 1)
            self.assertIn("conflicts", project.json())

            run = client.get("/control/api/runs/run-api", headers=headers)
            self.assertEqual(run.status_code, 200)
            self.assertEqual(run.json()["queue_item"]["current_run_id"], "run-api")
            self.assertIn("conflicts", run.json())

            papers = client.get("/control/api/papers?status=draft_review", headers=headers)
            self.assertEqual(papers.status_code, 200)
            self.assertEqual(papers.json()["counts"]["draft_review"], 1)
            self.assertIn("conflicts", papers.json())

            paper = client.get("/control/api/papers/idea-api:run-api:arxiv_draft", headers=headers)
            self.assertEqual(paper.status_code, 200)
            self.assertEqual(paper.json()["paper"]["project_id"], "idea-api")
            self.assertFalse(paper.json()["warnings"])
            self.assertIn("conflicts", paper.json())

            events = client.get("/control/api/events?search=dashboard-api", headers=headers)
            self.assertEqual(events.status_code, 200)
            self.assertGreaterEqual(events.json()["page"]["total"], 1)
            self.assertIn("conflicts", events.json())

            intake = client.get("/control/api/intake/ideas", headers=headers)
            self.assertEqual(intake.status_code, 200)
            self.assertIsNotNone(intake.json()["latest_sync"])
            self.assertEqual(intake.json()["skipped_reasons"]["missing title"], 1)
            self.assertIn("conflicts", intake.json())


    def test_detail_apis_fallback_to_global_worker_observations_and_surface_conflicts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            client.post("/control/import/legacy-snapshot", headers=headers, json={
                "idempotency_key": "detail-conflict-import",
                "queue_rows": [{
                    "project_id": "idea-active-detail",
                    "project_name": "Active Detail",
                    "project_dir": "idea-active-detail",
                    "status": "awaiting_wake",
                    "current_run_id": "run-active-detail",
                }],
            })
            store = ControlPlaneStore(Path(tmp) / "state" / "control_plane.sqlite3")
            store.upsert_dashboard_observation(
                source="worker_preflight",
                status="ok",
                payload={"ok": True, "checks": [{"name": "worker_no_live_runs", "ok": True, "detail": "active_or_waiting=0, live=0", "data": {"active_or_waiting": 0, "live": 0}}]},
            )
            store.upsert_dashboard_observation(
                source="worker_dashboard_api",
                status="ok",
                payload={"name": "wake_gate_dashboard_api", "ok": True, "data": {"body": {"runs": [{"run_id": "run-active-detail", "project_id": "idea-active-detail"}]}}},
            )
            project = client.get("/control/api/projects/idea-active-detail", headers=headers).json()
            self.assertIsNotNone(project["worker_observations"]["worker_dashboard_api"])
            self.assertTrue(any(item["severity"] == "warn" for item in project["conflicts"]))
            run = client.get("/control/api/runs/run-active-detail", headers=headers).json()
            self.assertIsNotNone(run["worker_observations"]["worker_dashboard_api"])
            self.assertTrue(any(item["severity"] == "warn" for item in run["conflicts"]))

    def test_paper_review_backfill_list_detail_and_legacy_papers_api(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            papers = []
            audit_rows = []
            for idx in range(242):
                project_id = f"idea-{idx:03d}"
                status = "publication_draft" if idx < 120 else "draft_review"
                papers.append({
                    "paper_id": f"{project_id}:run-{idx}:arxiv_draft",
                    "project_id": project_id,
                    "project_name": f"Idea {idx:03d}",
                    "run_id": f"run-{idx}",
                    "paper_status": status,
                    "paper_type": "arxiv_draft",
                    "draft_markdown_path": f"papers/run-{idx}/paper.md",
                    "draft_latex_path": f"papers/run-{idx}/paper.tex",
                    "evidence_bundle_path": f"papers/run-{idx}/evidence.json",
                    "claim_ledger_path": f"papers/run-{idx}/claims.json",
                    "manifest_path": f"papers/run-{idx}/manifest.json",
                    "updated_at": f"2026-04-28T12:{idx % 60:02d}:00+00:00",
                })
                audit_rows.append({"paper_id": papers[-1]["paper_id"], "ready": True})
            audit_path = Path(tmp) / "audit.json"
            audit_path.write_text(json.dumps({"papers": audit_rows}), encoding="utf-8")
            imported = client.post("/control/import/legacy-snapshot", headers=headers, json={
                "idempotency_key": "paper-review-router-import",
                "paper_rows": papers,
            })
            self.assertEqual(imported.status_code, 200)
            self.assertEqual(imported.json()["imported_papers"], 242)

            dry_run = client.post("/control/api/paper-reviews/backfill", headers=headers, json={
                "idempotency_key": "paper-review-router-backfill",
                "requested_by": "test",
                "source_audit_path": str(audit_path),
                "dry_run": True,
            })
            self.assertEqual(dry_run.status_code, 200)
            self.assertEqual(dry_run.json()["created"], 242)

            committed = client.post("/control/api/paper-reviews/backfill", headers=headers, json={
                "idempotency_key": "paper-review-router-backfill",
                "requested_by": "test",
                "source_audit_path": str(audit_path),
                "dry_run": False,
            })
            self.assertEqual(committed.status_code, 200)
            self.assertEqual(committed.json()["created"], 242)

            legacy = client.get("/control/api/papers?page_size=500", headers=headers)
            self.assertEqual(legacy.status_code, 200)
            self.assertEqual(legacy.json()["page"]["total"], 242)

            reviews = client.get("/control/api/paper-reviews?page_size=500&include_rank_reasons=true", headers=headers)
            self.assertEqual(reviews.status_code, 200)
            body = reviews.json()
            self.assertEqual(body["source"], "control_api_paper_reviews")
            self.assertEqual(body["page"]["queue"], "paper_reviews")
            self.assertEqual(body["page"]["total"], 242)
            self.assertEqual(len(body["rows"]), 242)
            self.assertEqual(body["counts"]["queued"], 242)
            self.assertEqual(body["rows"][0]["paper_status"], "publication_draft")
            self.assertIn("rank_reasons", body["rows"][0])

            automation = client.get("/control/api/publication-automation?page_size=500&include_rank_reasons=true", headers=headers)
            self.assertEqual(automation.status_code, 200)
            automation_body = automation.json()
            self.assertEqual(automation_body["source"], "control_api_paper_reviews")
            self.assertEqual(automation_body["page"]["queue"], "publication_automation")
            self.assertEqual(automation_body["page"]["total"], 242)
            self.assertEqual(automation_body["counts"], body["counts"])

            filtered = client.get("/control/api/publication-automation?page_size=500&paper_status=draft_review&search=idea-200", headers=headers)
            self.assertEqual(filtered.status_code, 200)
            self.assertEqual(filtered.json()["page"]["total"], 1)

            detail_id = body["rows"][0]["paper_id"]
            detail = client.get(f"/control/api/publication-automation/{detail_id}", headers=headers)
            self.assertEqual(detail.status_code, 200)
            self.assertEqual(detail.json()["item"]["paper_id"], detail_id)
            self.assertEqual(detail.json()["paper"]["paper_id"], detail_id)

            legacy_detail = client.get(f"/control/api/paper-reviews/{detail_id}", headers=headers)
            self.assertEqual(legacy_detail.status_code, 200)
            self.assertEqual(legacy_detail.json()["item"]["paper_id"], detail_id)

            next_review = client.get("/control/api/publication-automation/next?paper_status=publication_draft", headers=headers)
            self.assertEqual(next_review.status_code, 200)
            self.assertEqual(next_review.json()["item"]["paper_id"], detail_id)

            legacy_next = client.get("/control/api/paper-reviews/next?paper_status=publication_draft", headers=headers)
            self.assertEqual(legacy_next.status_code, 200)
            self.assertEqual(legacy_next.json()["item"]["paper_id"], detail_id)

            repeated = client.post("/control/api/paper-reviews/backfill", headers=headers, json={
                "idempotency_key": "paper-review-router-backfill-second",
                "requested_by": "test",
                "source_audit_path": str(audit_path),
                "dry_run": False,
            })
            self.assertEqual(repeated.status_code, 200)
            self.assertEqual(repeated.json()["created"], 0)
            self.assertEqual(repeated.json()["updated"], 0)
            self.assertEqual(repeated.json()["skipped"], 242)

    def test_paper_review_backfill_treats_unexpandable_audit_path_as_missing_audit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            imported = client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "paper-review-router-unexpandable-audit-import",
                    "paper_rows": [
                        {
                            "paper_id": "idea-audit-path:run-audit-path:arxiv_draft",
                            "project_id": "idea-audit-path",
                            "project_name": "Audit Path",
                            "run_id": "run-audit-path",
                            "paper_status": "publication_draft",
                            "paper_type": "arxiv_draft",
                            "draft_markdown_path": "papers/run-audit-path/paper.md",
                            "draft_latex_path": "papers/run-audit-path/paper.tex",
                            "evidence_bundle_path": "papers/run-audit-path/evidence.json",
                            "claim_ledger_path": "papers/run-audit-path/claims.json",
                            "manifest_path": "papers/run-audit-path/manifest.json",
                        }
                    ],
                },
            )
            self.assertEqual(imported.status_code, 200)

            response = client.post(
                "/control/api/paper-reviews/backfill",
                headers=headers,
                json={
                    "idempotency_key": "paper-review-router-unexpandable-audit",
                    "requested_by": "test",
                    "source_audit_path": "~enoch-user-that-should-not-exist/audit.json",
                    "dry_run": True,
                },
            )
            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertEqual(body["created"], 1)
            self.assertEqual(body["errors"], [])

    def test_paper_review_list_filters_normalize_status_variants(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            paper_id = "router-filter-normalized:run-1:arxiv_draft"
            audit_path = Path(tmp) / "audit.json"
            audit_path.write_text(json.dumps({"papers": [{"paper_id": paper_id, "ready": True}]}), encoding="utf-8")
            imported = client.post("/control/import/legacy-snapshot", headers=headers, json={
                "idempotency_key": "router-filter-normalized-import",
                "paper_rows": [{
                    "paper_id": paper_id,
                    "project_id": "router-filter-normalized",
                    "run_id": "run-1",
                    "paper_status": "publication_draft",
                    "draft_markdown_path": "paper.md",
                    "draft_latex_path": "paper.tex",
                    "evidence_bundle_path": "evidence.json",
                    "claim_ledger_path": "claims.json",
                    "manifest_path": "manifest.json",
                }],
            })
            self.assertEqual(imported.status_code, 200)
            backfill = client.post("/control/api/paper-reviews/backfill", headers=headers, json={
                "idempotency_key": "router-filter-normalized-backfill",
                "source_audit_path": str(audit_path),
                "dry_run": False,
            })
            self.assertEqual(backfill.status_code, 200)
            with sqlite3.connect(Path(tmp) / "state" / "control_plane.sqlite3") as conn:
                conn.execute("UPDATE papers SET paper_status=? WHERE paper_id=?", (" Publication Draft ", paper_id))
                conn.execute("UPDATE paper_review_items SET review_status=? WHERE paper_id=?", (" Queued ", paper_id))

            papers = client.get("/control/api/papers?status=publication_draft", headers=headers)
            self.assertEqual(papers.status_code, 200)
            self.assertEqual(papers.json()["page"]["total"], 1)
            self.assertEqual(papers.json()["counts"].get("publication_draft"), 1)
            reviews = client.get("/control/api/publication-automation?paper_status=publication_draft&review_status=queued", headers=headers)
            self.assertEqual(reviews.status_code, 200)
            self.assertEqual(reviews.json()["page"]["total"], 1)
            self.assertEqual(reviews.json()["counts"].get("queued"), 1)
            self.assertEqual(reviews.json()["counts"].get("publication_draft"), 1)
            next_review = client.get("/control/api/paper-reviews/next?paper_status=publication_draft&review_status=queued", headers=headers)
            self.assertEqual(next_review.status_code, 200)
            self.assertEqual(next_review.json()["paper_id"], paper_id)

    def test_paper_review_mutation_endpoints_validate_and_log_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            paper_id = "router-review:run-1:arxiv_draft"
            audit_path = Path(tmp) / "audit.json"
            audit_path.write_text(json.dumps({"papers": [{"paper_id": paper_id, "ready": True}]}), encoding="utf-8")
            client.post("/control/import/legacy-snapshot", headers=headers, json={
                "idempotency_key": "router-review-mutation-import",
                "paper_rows": [{
                    "paper_id": paper_id,
                    "project_id": "router-review",
                    "run_id": "run-1",
                    "paper_status": "publication_draft",
                    "draft_markdown_path": "paper.md",
                    "draft_latex_path": "paper.tex",
                    "evidence_bundle_path": "evidence.json",
                    "claim_ledger_path": "claims.json",
                    "manifest_path": "manifest.json",
                }],
            })
            backfill = client.post("/control/api/paper-reviews/backfill", headers=headers, json={
                "idempotency_key": "router-review-mutation-backfill",
                "source_audit_path": str(audit_path),
                "dry_run": False,
            })
            self.assertEqual(backfill.status_code, 200)

            claim = client.post(f"/control/api/paper-reviews/{paper_id}/claim", headers=headers, json={
                "idempotency_key": "router-claim-1",
                "requested_by": "alice",
                "reviewer": "alice",
            })
            self.assertEqual(claim.status_code, 200)
            self.assertEqual(claim.json()["item"]["review_status"], "claimed")
            self.assertEqual(claim.json()["item"]["reviewer"], "alice")
            claim_repeat = client.post(f"/control/api/paper-reviews/{paper_id}/claim", headers=headers, json={
                "idempotency_key": "router-claim-1",
                "requested_by": "alice",
                "reviewer": "alice",
            })
            self.assertEqual(claim_repeat.status_code, 200)
            self.assertFalse(claim_repeat.json()["inserted_event"])

            bad_check = client.post(f"/control/api/paper-reviews/{paper_id}/checklist/artifact_readability", headers=headers, json={
                "idempotency_key": "router-bad-check",
                "requested_by": "alice",
                "status": "fail",
            })
            self.assertEqual(bad_check.status_code, 400)

            for item_id in ["artifact_readability", "title_abstract_quality", "claim_evidence_alignment", "novelty_significance", "reproducibility", "limitations_ethics", "formatting_quality", "final_human_approval"]:
                response = client.post(f"/control/api/paper-reviews/{paper_id}/checklist/{item_id}", headers=headers, json={
                    "idempotency_key": f"router-check-{item_id}",
                    "requested_by": "alice",
                    "status": "pass",
                })
                self.assertEqual(response.status_code, 200)

            detail = client.get(f"/control/api/paper-reviews/{paper_id}", headers=headers)
            self.assertEqual(detail.status_code, 200)
            self.assertEqual(detail.json()["checklist"]["progress"]["passed"], 8)
            self.assertEqual(detail.json()["paper"]["paper_status"], "publication_draft")

            approval = client.post(f"/control/api/paper-reviews/{paper_id}/approve-finalization", headers=headers, json={
                "idempotency_key": "router-approve-1",
                "requested_by": "alice",
                "note": "ready",
            })
            self.assertEqual(approval.status_code, 400)
            self.assertIn("manual paper approval has been removed", approval.text)

            rejected_status = client.post(f"/control/api/paper-reviews/{paper_id}/status", headers=headers, json={
                "idempotency_key": "router-status-invalid",
                "requested_by": "alice",
                "review_status": "approved_for_finalization",
                "note": "no",
            })
            self.assertEqual(rejected_status.status_code, 400)

            events = client.get(f"/control/api/events?entity_id={paper_id}", headers=headers)
            self.assertEqual(events.status_code, 200)
            event_types = {row["event_type"] for row in events.json()["rows"]}
            self.assertIn("paper_review.claimed", event_types)
            self.assertIn("paper_review.checklist_updated", event_types)
            self.assertNotIn("paper_review.approved_for_finalization", event_types)

    def test_paper_review_bulk_rewrite_batches_publication_drafts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _config(tmp)
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            papers = []
            for idx in range(3):
                evidence_dir = config.expanded_project_root / f"bulk-{idx}"
                evidence_dir.mkdir(parents=True, exist_ok=True)
                (evidence_dir / "run_notes.md").write_text(f"Bulk Paper {idx} has local evidence for rewrite.\n", encoding="utf-8")
                papers.append({
                    "paper_id": f"bulk-{idx}:run-{idx}:arxiv_draft",
                    "project_id": f"bulk-{idx}",
                    "project_name": f"Bulk Paper {idx}",
                    "run_id": f"run-{idx}",
                    "paper_status": "publication_draft",
                    "draft_markdown_path": f"papers/run-{idx}/final.md",
                    "draft_latex_path": f"papers/run-{idx}/final.tex",
                    "evidence_bundle_path": f"papers/run-{idx}/evidence.json",
                    "claim_ledger_path": f"papers/run-{idx}/claims.json",
                    "manifest_path": f"papers/run-{idx}/manifest.json",
                })
            client.post("/control/import/legacy-snapshot", headers=headers, json={"idempotency_key": "bulk-rewrite-import", "paper_rows": papers})
            client.post("/control/api/paper-reviews/backfill", headers=headers, json={"idempotency_key": "bulk-rewrite-backfill", "dry_run": False})

            dry = client.post("/control/api/paper-reviews/rewrite-batch", headers=headers, json={
                "idempotency_key": "bulk-rewrite-dry",
                "requested_by": "ai-publication-pipeline",
                "limit": 2,
                "dry_run": True,
            })
            self.assertEqual(dry.status_code, 200)
            self.assertTrue(dry.json()["dry_run"])
            self.assertEqual(dry.json()["processed"], 2)

            committed = client.post("/control/api/paper-reviews/rewrite-batch", headers=headers, json={
                "idempotency_key": "bulk-rewrite-commit",
                "requested_by": "ai-publication-pipeline",
                "limit": 2,
                "force": True,
                "dry_run": False,
            })
            self.assertEqual(committed.status_code, 200)
            body = committed.json()
            self.assertEqual(body["processed"], 2)
            self.assertEqual(body["rewritten"], 2)
            self.assertEqual(body["failed"], 0)
            for row in body["rows"]:
                self.assertTrue(row["ok"])
                self.assertEqual(row["provider"], "deterministic")
                self.assertTrue((config.expanded_project_root / row["paper_id"].split(":", 1)[0] / "papers").exists())

    def test_paper_review_rewrite_draft_writes_vm_local_artifacts_and_logs_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _config(tmp)
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            paper_id = "router-rewrite:run-1:arxiv_draft"
            evidence_dir = config.expanded_project_root / "router-rewrite"
            evidence_dir.mkdir(parents=True, exist_ok=True)
            (evidence_dir / "run_notes.md").write_text("Router Rewrite has synced local evidence.\n", encoding="utf-8")
            legacy_dir = Path(tmp) / "legacy-missing" / "router-rewrite"
            audit_path = Path(tmp) / "audit.json"
            audit_path.write_text(json.dumps({"papers": [{"paper_id": paper_id, "ready": True}]}), encoding="utf-8")
            client.post("/control/import/legacy-snapshot", headers=headers, json={
                "idempotency_key": "router-rewrite-import",
                "paper_rows": [{
                    "paper_id": paper_id,
                    "project_id": "router-rewrite",
                    "project_name": "Router Rewrite",
                    "project_dir": str(legacy_dir),
                    "run_id": "run-1",
                    "paper_status": "draft_review",
                    "draft_markdown_path": "papers/run-1/final_paper.md",
                    "draft_latex_path": "papers/run-1/final_paper.tex",
                    "evidence_bundle_path": "papers/run-1/evidence.json",
                    "claim_ledger_path": "papers/run-1/claims.json",
                    "manifest_path": "papers/run-1/manifest.json",
                }],
            })
            client.post("/control/api/paper-reviews/backfill", headers=headers, json={"idempotency_key": "router-rewrite-backfill", "source_audit_path": str(audit_path), "dry_run": False})

            response = client.post(f"/control/api/paper-reviews/{paper_id}/rewrite-draft", headers=headers, json={
                "idempotency_key": "router-rewrite-1",
                "requested_by": "alice",
                "force": True,
            })
            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertTrue(body["inserted_event"])
            self.assertEqual(body["writer"]["provider"], "deterministic")
            self.assertEqual(body["paper"]["paper_status"], "publication_draft")
            self.assertEqual(body["item"]["review_status"], "finalized")
            self.assertTrue(Path(body["item"]["finalization_package_path"]).exists())
            self.assertEqual(body["writer"]["automated_finalization"]["review_status"], "finalized")
            review_detail = client.get(f"/control/api/paper-reviews/{paper_id}", headers=headers).json()
            self.assertEqual(review_detail["paper"]["paper_status"], "publication_draft")
            self.assertEqual(review_detail["item"]["review_status"], "finalized")
            artifact_root = Path(body["artifact_root"])
            self.assertEqual(artifact_root, config.expanded_project_root / "router-rewrite")
            self.assertTrue((artifact_root / "papers/run-1/final_paper.md").exists())
            self.assertIn("Router Rewrite", (artifact_root / "papers/run-1/final_paper.md").read_text(encoding="utf-8"))

            dry_package = client.post(f"/control/api/paper-reviews/{paper_id}/prepare-finalization-package", headers=headers, json={
                "idempotency_key": "router-rewrite-package-dry",
                "requested_by": "alice",
                "dry_run": True,
            })
            self.assertEqual(dry_package.status_code, 200)
            artifacts = dry_package.json()["manifest"]["artifacts"]
            self.assertTrue(all(item["readable"] for item in artifacts))
            artifact = client.get(f"/control/api/papers/{paper_id}/artifact/draft_markdown_path", headers=headers)
            self.assertEqual(artifact.status_code, 200)
            self.assertEqual(artifact.json()["field"], "draft_markdown_path")
            self.assertIn("Router Rewrite", artifact.json()["content"])
            missing = client.get(f"/control/api/papers/{paper_id}/artifact/not_a_field", headers=headers)
            self.assertEqual(missing.status_code, 404)
            events = client.get(f"/control/api/events?entity_id={paper_id}", headers=headers).json()["rows"]
            event_types = {row["event_type"] for row in events}
            self.assertIn("paper_review.draft_rewritten", event_types)
            self.assertIn("paper_review.finalization_package_prepared", event_types)

    def test_paper_review_rewrite_rejects_uninspectable_current_project_dir_without_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _config(tmp)
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            project_id = "router-rewrite-uninspectable"
            paper_id = f"{project_id}:run-1:arxiv_draft"
            current_artifact_root = config.expanded_project_root / "custom-artifact-root"
            current_artifact_root.mkdir(parents=True, exist_ok=True)
            (current_artifact_root / "run_notes.md").write_text("Uninspectable rewrite evidence.\n", encoding="utf-8")
            audit_path = Path(tmp) / "audit.json"
            audit_path.write_text(json.dumps({"papers": [{"paper_id": paper_id, "ready": True}]}), encoding="utf-8")
            client.post("/control/import/legacy-snapshot", headers=headers, json={
                "idempotency_key": "router-rewrite-uninspectable-import",
                "paper_rows": [{
                    "paper_id": paper_id,
                    "project_id": project_id,
                    "project_name": "Router Rewrite Uninspectable",
                    "project_dir": str(current_artifact_root),
                    "run_id": "run-1",
                    "paper_status": "draft_review",
                    "draft_markdown_path": "papers/run-1/final_paper.md",
                    "draft_latex_path": "papers/run-1/final_paper.tex",
                    "evidence_bundle_path": "papers/run-1/evidence.json",
                    "claim_ledger_path": "papers/run-1/claims.json",
                    "manifest_path": "papers/run-1/manifest.json",
                }],
            })
            client.post("/control/api/paper-reviews/backfill", headers=headers, json={
                "idempotency_key": "router-rewrite-uninspectable-backfill",
                "source_audit_path": str(audit_path),
                "dry_run": False,
            })
            original_exists = Path.exists

            def guarded_exists(path: Path, *args, **kwargs) -> bool:
                if path == current_artifact_root:
                    raise PermissionError("no permission to inspect current project dir")
                return original_exists(path, *args, **kwargs)

            with patch.object(Path, "exists", guarded_exists):
                response = client.post(f"/control/api/paper-reviews/{paper_id}/rewrite-draft", headers=headers, json={
                    "idempotency_key": "router-rewrite-uninspectable-1",
                    "requested_by": "alice",
                    "force": True,
                })
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json()["detail"], "paper artifact root could not be inspected")
            fallback_root = config.expanded_project_root / project_id
            self.assertFalse((fallback_root / "papers/run-1/final_paper.md").exists())
            self.assertFalse((current_artifact_root / "papers/run-1/final_paper.md").exists())

    def test_paper_review_rewrite_replay_does_not_repeat_evidence_sync(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _config(tmp)
            config.paper_evidence_sync_enabled = True
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            paper_id = "router-rewrite-replay:run-1:arxiv_draft"
            project_id = "router-rewrite-replay"
            evidence_dir = config.expanded_project_root / project_id
            evidence_dir.mkdir(parents=True, exist_ok=True)
            (evidence_dir / "run_notes.md").write_text("Replay rewrite has source evidence.\n", encoding="utf-8")
            (evidence_dir / ".enoch").mkdir()
            (evidence_dir / ".enoch" / "project_decision.json").write_text('{"project_decision":"finalize_positive"}\n', encoding="utf-8")
            audit_path = Path(tmp) / "audit.json"
            audit_path.write_text(json.dumps({"papers": [{"paper_id": paper_id, "ready": True}]}), encoding="utf-8")
            client.post("/control/import/legacy-snapshot", headers=headers, json={
                "idempotency_key": "router-rewrite-replay-import",
                "paper_rows": [{
                    "paper_id": paper_id,
                    "project_id": project_id,
                    "project_name": "Router Rewrite Replay",
                    "project_dir": str(evidence_dir),
                    "run_id": "run-1",
                    "paper_status": "publication_draft",
                    "draft_markdown_path": "papers/run-1/final_paper.md",
                    "draft_latex_path": "papers/run-1/final_paper.tex",
                    "evidence_bundle_path": "papers/run-1/evidence.json",
                    "claim_ledger_path": "papers/run-1/claims.json",
                    "manifest_path": "papers/run-1/manifest.json",
                }],
            })
            client.post("/control/api/paper-reviews/backfill", headers=headers, json={"idempotency_key": "router-rewrite-replay-backfill", "source_audit_path": str(audit_path), "dry_run": False})

            with patch("enoch_control_plane.control_plane.router._sync_remote_project_evidence", return_value={"enabled": True, "synced": True, "reason": "test", "local_evidence_present": True}) as sync:
                first = client.post(f"/control/api/paper-reviews/{paper_id}/rewrite-draft", headers=headers, json={
                    "idempotency_key": "router-rewrite-replay-1",
                    "requested_by": "alice",
                    "force": True,
                })
                replay = client.post(f"/control/api/paper-reviews/{paper_id}/rewrite-draft", headers=headers, json={
                    "idempotency_key": "router-rewrite-replay-1",
                    "requested_by": "alice",
                    "force": True,
                })

            self.assertEqual(first.status_code, 200)
            self.assertTrue(first.json()["inserted_event"])
            self.assertEqual(replay.status_code, 200)
            self.assertFalse(replay.json()["inserted_event"])
            self.assertEqual(sync.call_count, 1)

    def test_paper_review_rewrite_accepts_supabase_datetime_paper_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _config(tmp)
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            paper_id = "router-rewrite-datetime:run-1:arxiv_draft"
            evidence_dir = config.expanded_project_root / "router-rewrite-datetime"
            evidence_dir.mkdir(parents=True, exist_ok=True)
            (evidence_dir / "run_notes.md").write_text("Router Rewrite Datetime has local evidence.\n", encoding="utf-8")
            audit_path = Path(tmp) / "audit.json"
            audit_path.write_text(json.dumps({"papers": [{"paper_id": paper_id, "ready": True}]}), encoding="utf-8")
            store = ControlPlaneStore(Path(tmp) / "state" / "control_plane.sqlite3")
            store.import_snapshot(
                ImportSnapshotRequest(
                    idempotency_key="router-rewrite-datetime-import",
                    paper_rows=[{
                        "paper_id": paper_id,
                        "project_id": "router-rewrite-datetime",
                        "project_name": "Router Rewrite Datetime",
                        "project_dir": "router-rewrite-datetime",
                        "run_id": "run-1",
                        "paper_status": "publication_draft",
                        "draft_markdown_path": "papers/run-1/final_paper.md",
                        "draft_latex_path": "papers/run-1/final_paper.tex",
                        "evidence_bundle_path": "papers/run-1/evidence.json",
                        "claim_ledger_path": "papers/run-1/claims.json",
                        "manifest_path": "papers/run-1/manifest.json",
                    }],
                )
            )
            store.backfill_paper_reviews(PaperReviewBackfillRequest(idempotency_key="router-rewrite-datetime-backfill", source_audit_path=str(audit_path), dry_run=False))
            original_paper_row = store.paper_row

            def paper_row_with_datetimes(pid: str) -> dict | None:
                row = original_paper_row(pid)
                if row:
                    row["generated_at"] = datetime(2026, 5, 6, 21, 4, 30, tzinfo=timezone.utc)
                    row["updated_at"] = datetime(2026, 5, 6, 21, 4, 30, tzinfo=timezone.utc)
                return row

            with patch.object(store, "paper_row", side_effect=paper_row_with_datetimes):
                response = client.post(f"/control/api/paper-reviews/{paper_id}/rewrite-draft", headers=headers, json={
                    "idempotency_key": "router-rewrite-datetime-1",
                    "requested_by": "alice",
                    "force": True,
                })

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["item"]["review_status"], "finalized")

    def test_paper_artifact_endpoint_resolves_relative_project_dir_under_configured_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _config(tmp)
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            project_dir = config.expanded_project_root / "relative-project"
            paper_dir = project_dir / "papers" / "run-relative"
            paper_dir.mkdir(parents=True)
            (paper_dir / "paper.md").write_text("# Relative Artifact\n", encoding="utf-8")

            paper_id = "relative-project:run-relative:arxiv_draft"
            response = client.post("/control/import/legacy-snapshot", headers=headers, json={
                "idempotency_key": "relative-project-artifact-import",
                "queue_rows": [{
                    "project_id": "relative-project",
                    "project_name": "Relative Project",
                    "project_dir": "relative-project",
                    "status": "completed",
                }],
                "paper_rows": [{
                    "paper_id": paper_id,
                    "project_id": "relative-project",
                    "run_id": "run-relative",
                    "paper_status": "publication_draft",
                    "draft_markdown_path": "papers/run-relative/paper.md",
                }],
            })
            self.assertEqual(response.status_code, 200)

            artifact = client.get(f"/control/api/papers/{paper_id}/artifact/draft_markdown_path", headers=headers)
            self.assertEqual(artifact.status_code, 200)
            self.assertIn("Relative Artifact", artifact.json()["content"])



    def test_paper_artifact_endpoint_rejects_project_dir_escape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _config(tmp)
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            outside = Path(tmp) / "outside"
            outside.mkdir()
            (outside / "paper.md").write_text("# Outside Artifact\n", encoding="utf-8")

            paper_id = "artifact-escape:run-escape:arxiv_draft"
            response = client.post("/control/import/legacy-snapshot", headers=headers, json={
                "idempotency_key": "artifact-escape-import",
                "paper_rows": [{
                    "paper_id": paper_id,
                    "project_id": "artifact-escape",
                    "run_id": "run-escape",
                    "project_dir": str(outside),
                    "paper_status": "publication_draft",
                    "draft_markdown_path": "paper.md",
                }],
            })
            self.assertEqual(response.status_code, 200)

            artifact = client.get(f"/control/api/papers/{paper_id}/artifact/draft_markdown_path", headers=headers)

            self.assertNotEqual(artifact.status_code, 200)
            self.assertNotIn("Outside Artifact", artifact.text)

    def test_paper_artifact_endpoint_rejects_invalid_artifact_path_without_500(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _config(tmp)
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}

            paper_id = "artifact-invalid-path:run-invalid:arxiv_draft"
            response = client.post("/control/import/legacy-snapshot", headers=headers, json={
                "idempotency_key": "artifact-invalid-path-import",
                "paper_rows": [{
                    "paper_id": paper_id,
                    "project_id": "artifact-invalid-path",
                    "run_id": "run-invalid",
                    "project_dir": "artifact-invalid-path",
                    "paper_status": "publication_draft",
                    "draft_markdown_path": "bad\0paper.md",
                }],
            })
            self.assertEqual(response.status_code, 200)

            artifact = client.get(f"/control/api/papers/{paper_id}/artifact/draft_markdown_path", headers=headers)

            self.assertIn(artifact.status_code, {400, 404})
            self.assertNotEqual(artifact.status_code, 500)

    def test_paper_artifact_endpoint_rejects_access_failure_without_500(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _config(tmp)
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            project_dir = config.expanded_project_root / "artifact-access-failure"
            project_dir.mkdir(parents=True)
            artifact_path = project_dir / "paper.md"
            artifact_path.write_text("# Access Failure\n", encoding="utf-8")
            paper_id = "artifact-access-failure:run-access:arxiv_draft"
            response = client.post("/control/import/legacy-snapshot", headers=headers, json={
                "idempotency_key": "artifact-access-failure-import",
                "paper_rows": [{
                    "paper_id": paper_id,
                    "project_id": "artifact-access-failure",
                    "run_id": "run-access",
                    "project_dir": str(project_dir),
                    "paper_status": "publication_draft",
                    "draft_markdown_path": "paper.md",
                }],
            })
            self.assertEqual(response.status_code, 200)
            real_exists = Path.exists

            def blocked_exists(path: Path) -> bool:
                if path == artifact_path:
                    raise PermissionError("simulated artifact access failure")
                return real_exists(path)

            with patch("pathlib.Path.exists", blocked_exists):
                artifact = client.get(f"/control/api/papers/{paper_id}/artifact/draft_markdown_path", headers=headers)

            self.assertEqual(artifact.status_code, 404)
            self.assertNotEqual(artifact.status_code, 500)

    def test_paper_rewrite_rejects_invalid_project_id_without_500(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _config(tmp)
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            paper_id = "router-invalid-project-id:run-1:arxiv_draft"
            audit_path = Path(tmp) / "audit.json"
            audit_path.write_text(json.dumps({"papers": [{"paper_id": paper_id, "ready": True}]}), encoding="utf-8")
            imported = client.post("/control/import/legacy-snapshot", headers=headers, json={
                "idempotency_key": "router-invalid-project-id-import",
                "paper_rows": [{
                    "paper_id": paper_id,
                    "project_id": "bad\0router-invalid-project-id",
                    "project_name": "Router Invalid Project ID",
                    "run_id": "run-1",
                    "paper_status": "publication_draft",
                    "draft_markdown_path": "paper.md",
                    "draft_latex_path": "paper.tex",
                    "evidence_bundle_path": "evidence.json",
                    "claim_ledger_path": "claims.json",
                    "manifest_path": "manifest.json",
                }],
            })
            self.assertEqual(imported.status_code, 200)
            backfill = client.post("/control/api/paper-reviews/backfill", headers=headers, json={
                "idempotency_key": "router-invalid-project-id-backfill",
                "source_audit_path": str(audit_path),
                "dry_run": False,
            })
            self.assertEqual(backfill.status_code, 200)

            response = client.post(f"/control/api/paper-reviews/{paper_id}/rewrite-draft", headers=headers, json={
                "idempotency_key": "router-invalid-project-id-rewrite",
                "requested_by": "alice",
                "force": True,
            })

            self.assertEqual(response.status_code, 400)
            self.assertNotEqual(response.status_code, 500)

    def test_paper_rewrite_rejects_unreadable_snapshot_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _config(tmp)
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            paper_id = "router-unreadable-snapshot:run-1:arxiv_draft"
            project_dir = config.expanded_project_root / "router-unreadable-snapshot"
            artifact_paths = {
                "draft_markdown_path": "paper.md",
                "draft_latex_path": "paper.tex",
                "evidence_bundle_path": "evidence.json",
                "claim_ledger_path": "claims.json",
                "manifest_path": "manifest.json",
            }
            _write_publication_artifacts(
                project_dir,
                evidence_path=artifact_paths["evidence_bundle_path"],
                claim_path=artifact_paths["claim_ledger_path"],
                manifest_path=artifact_paths["manifest_path"],
            )
            (project_dir / artifact_paths["draft_latex_path"]).write_text("latex", encoding="utf-8")
            original_markdown = (project_dir / artifact_paths["draft_markdown_path"]).read_text(encoding="utf-8")
            audit_path = Path(tmp) / "audit.json"
            audit_path.write_text(json.dumps({"papers": [{"paper_id": paper_id, "ready": True}]}), encoding="utf-8")
            imported = client.post("/control/import/legacy-snapshot", headers=headers, json={
                "idempotency_key": "router-unreadable-snapshot-import",
                "paper_rows": [{
                    "paper_id": paper_id,
                    "project_id": "router-unreadable-snapshot",
                    "project_name": "Router Unreadable Snapshot",
                    "project_dir": str(project_dir),
                    "run_id": "run-1",
                    "paper_status": "publication_draft",
                    **artifact_paths,
                }],
            })
            self.assertEqual(imported.status_code, 200)
            backfill = client.post("/control/api/paper-reviews/backfill", headers=headers, json={
                "idempotency_key": "router-unreadable-snapshot-backfill",
                "source_audit_path": str(audit_path),
                "dry_run": False,
            })
            self.assertEqual(backfill.status_code, 200)

            with patch("pathlib.Path.read_bytes", side_effect=PermissionError("blocked snapshot read")):
                response = client.post(f"/control/api/paper-reviews/{paper_id}/rewrite-draft", headers=headers, json={
                    "idempotency_key": "router-unreadable-snapshot-rewrite",
                    "requested_by": "alice",
                    "force": True,
                })

            self.assertEqual(response.status_code, 400)
            self.assertIn("snapshot", response.text.lower())
            self.assertEqual((project_dir / artifact_paths["draft_markdown_path"]).read_text(encoding="utf-8"), original_markdown)

            real_exists = Path.exists

            def blocked_exists(path: Path) -> bool:
                if path == project_dir / artifact_paths["draft_markdown_path"]:
                    raise PermissionError("blocked snapshot inspect")
                return real_exists(path)

            with patch("pathlib.Path.exists", blocked_exists):
                response = client.post(f"/control/api/paper-reviews/{paper_id}/rewrite-draft", headers=headers, json={
                    "idempotency_key": "router-unreadable-snapshot-rewrite-exists",
                    "requested_by": "alice",
                    "force": True,
                })

            self.assertEqual(response.status_code, 400)
            self.assertIn("snapshot", response.text.lower())
            self.assertEqual((project_dir / artifact_paths["draft_markdown_path"]).read_text(encoding="utf-8"), original_markdown)


    def test_paper_review_rewrite_event_failure_restores_state_and_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _config(tmp)
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            paper_id = "router-rewrite-event-fail:run-1:arxiv_draft"
            project_id = "router-rewrite-event-fail"
            legacy_dir = Path(tmp) / "legacy" / project_id
            evidence_dir = config.expanded_project_root / project_id
            evidence_dir.mkdir(parents=True, exist_ok=True)
            (evidence_dir / "run_notes.md").write_text("Event failure rewrite has source evidence.\n", encoding="utf-8")
            (evidence_dir / ".enoch").mkdir()
            (evidence_dir / ".enoch" / "project_decision.json").write_text('{"project_decision":"finalize_positive"}\n', encoding="utf-8")
            response = client.post("/control/import/legacy-snapshot", headers=headers, json={
                "idempotency_key": "router-rewrite-event-fail-import",
                "paper_rows": [{
                    "paper_id": paper_id,
                    "project_id": project_id,
                    "project_name": "Router Rewrite Event Fail",
                    "project_dir": str(legacy_dir),
                    "run_id": "run-1",
                    "paper_status": "draft_review",
                    "draft_markdown_path": "papers/run-1/final_paper.md",
                    "draft_latex_path": "papers/run-1/final_paper.tex",
                    "evidence_bundle_path": "papers/run-1/evidence.json",
                    "claim_ledger_path": "papers/run-1/claims.json",
                    "manifest_path": "papers/run-1/manifest.json",
                }],
            })
            self.assertEqual(response.status_code, 200)
            client.post("/control/api/paper-reviews/backfill", headers=headers, json={"idempotency_key": "router-rewrite-event-fail-backfill", "dry_run": False})
            original_append_event = ControlPlaneStore.append_event

            def fail_rewrite_event(self, *args, **kwargs):  # noqa: ANN001 - patched method
                if kwargs.get("event_type") == "paper_review.draft_rewritten":
                    raise OSError("simulated rewrite event store failure")
                return original_append_event(self, *args, **kwargs)

            with patch.object(ControlPlaneStore, "append_event", new=fail_rewrite_event):
                with self.assertRaisesRegex(OSError, "simulated rewrite event store failure"):
                    client.post(f"/control/api/paper-reviews/{paper_id}/rewrite-draft", headers=headers, json={
                        "idempotency_key": "router-rewrite-event-fail-1",
                        "requested_by": "alice",
                        "force": True,
                    })

            paper = client.get(f"/control/api/papers/{paper_id}", headers=headers).json()["paper"]
            self.assertEqual(paper["paper_status"], "draft_review")
            self.assertEqual(paper["project_dir"], str(legacy_dir))
            self.assertFalse((evidence_dir / "papers/run-1/final_paper.md").exists())
            events = client.get(f"/control/api/events?entity_id={paper_id}", headers=headers).json()["rows"]
            self.assertNotIn("paper_review.draft_rewritten", {row["event_type"] for row in events})


    def test_paper_review_rewrite_finalization_failure_preserves_committed_draft_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _config(tmp)
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            paper_id = "router-rewrite-finalization-fail:run-1:arxiv_draft"
            project_id = "router-rewrite-finalization-fail"
            legacy_dir = Path(tmp) / "legacy" / project_id
            evidence_dir = config.expanded_project_root / project_id
            evidence_dir.mkdir(parents=True, exist_ok=True)
            (evidence_dir / "run_notes.md").write_text("Finalization failure rewrite has source evidence.\n", encoding="utf-8")
            (evidence_dir / ".enoch").mkdir()
            (evidence_dir / ".enoch" / "project_decision.json").write_text('{"project_decision":"finalize_positive"}\n', encoding="utf-8")
            response = client.post("/control/import/legacy-snapshot", headers=headers, json={
                "idempotency_key": "router-rewrite-finalization-fail-import",
                "paper_rows": [{
                    "paper_id": paper_id,
                    "project_id": project_id,
                    "project_name": "Router Rewrite Finalization Fail",
                    "project_dir": str(legacy_dir),
                    "run_id": "run-1",
                    "paper_status": "draft_review",
                    "draft_markdown_path": "papers/run-1/final_paper.md",
                    "draft_latex_path": "papers/run-1/final_paper.tex",
                    "evidence_bundle_path": "papers/run-1/evidence.json",
                    "claim_ledger_path": "papers/run-1/claims.json",
                    "manifest_path": "papers/run-1/manifest.json",
                }],
            })
            self.assertEqual(response.status_code, 200)
            client.post("/control/api/paper-reviews/backfill", headers=headers, json={"idempotency_key": "router-rewrite-finalization-fail-backfill", "dry_run": False})

            def fail_finalization(self, *args, **kwargs):  # noqa: ANN001, ARG001 - patched method
                raise OSError("simulated finalization package failure")

            with patch.object(ControlPlaneStore, "prepare_paper_review_finalization_package", new=fail_finalization):
                with self.assertRaisesRegex(OSError, "simulated finalization package failure"):
                    client.post(f"/control/api/paper-reviews/{paper_id}/rewrite-draft", headers=headers, json={
                        "idempotency_key": "router-rewrite-finalization-fail-1",
                        "requested_by": "alice",
                        "force": True,
                    })

            paper = client.get(f"/control/api/papers/{paper_id}", headers=headers).json()["paper"]
            self.assertEqual(paper["paper_status"], "publication_draft")
            self.assertEqual(paper["project_dir"], str(evidence_dir))
            self.assertTrue((evidence_dir / "papers/run-1/final_paper.md").exists())
            events = client.get(f"/control/api/events?entity_id={paper_id}", headers=headers).json()["rows"]
            self.assertIn("paper_review.draft_rewritten", {row["event_type"] for row in events})
            review_rows = client.get("/control/api/paper-reviews", headers=headers).json()["rows"]
            row = next(row for row in review_rows if row["paper_id"] == paper_id)
            self.assertNotEqual(row["review_status"], "finalized")


    def test_paper_review_rewrite_idempotency_conflict_does_not_mutate_state_or_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _config(tmp)
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            paper_id = "router-rewrite-conflict:run-1:arxiv_draft"
            project_id = "router-rewrite-conflict"
            legacy_dir = Path(tmp) / "legacy" / project_id
            evidence_dir = config.expanded_project_root / project_id
            evidence_dir.mkdir(parents=True, exist_ok=True)
            (evidence_dir / "run_notes.md").write_text("Conflict rewrite has source evidence.\n", encoding="utf-8")
            (evidence_dir / ".enoch").mkdir()
            (evidence_dir / ".enoch" / "project_decision.json").write_text('{"project_decision":"finalize_positive"}\n', encoding="utf-8")
            response = client.post("/control/import/legacy-snapshot", headers=headers, json={
                "idempotency_key": "router-rewrite-conflict-key",
                "paper_rows": [{
                    "paper_id": paper_id,
                    "project_id": project_id,
                    "project_name": "Router Rewrite Conflict",
                    "project_dir": str(legacy_dir),
                    "run_id": "run-1",
                    "paper_status": "draft_review",
                    "draft_markdown_path": "papers/run-1/final_paper.md",
                    "draft_latex_path": "papers/run-1/final_paper.tex",
                    "evidence_bundle_path": "papers/run-1/evidence.json",
                    "claim_ledger_path": "papers/run-1/claims.json",
                    "manifest_path": "papers/run-1/manifest.json",
                }],
            })
            self.assertEqual(response.status_code, 200)
            client.post("/control/api/paper-reviews/backfill", headers=headers, json={"idempotency_key": "router-rewrite-conflict-backfill", "dry_run": False})

            conflict = client.post(f"/control/api/paper-reviews/{paper_id}/rewrite-draft", headers=headers, json={
                "idempotency_key": "router-rewrite-conflict-key",
                "requested_by": "alice",
                "force": True,
            })

            self.assertEqual(conflict.status_code, 409)
            paper = client.get(f"/control/api/papers/{paper_id}", headers=headers).json()["paper"]
            self.assertEqual(paper["paper_status"], "draft_review")
            self.assertEqual(paper["project_dir"], str(legacy_dir))
            self.assertFalse((evidence_dir / "papers/run-1/final_paper.md").exists())
            events = client.get(f"/control/api/events?entity_id={paper_id}", headers=headers).json()["rows"]
            self.assertNotIn("paper_review.draft_rewritten", {row["event_type"] for row in events})


    def test_paper_review_rewrite_failure_does_not_mutate_project_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _config(tmp)
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            paper_id = "router-rewrite-fail:run-1:arxiv_draft"
            legacy_dir = Path(tmp) / "legacy-missing" / "router-rewrite-fail"
            client.post("/control/import/legacy-snapshot", headers=headers, json={
                "idempotency_key": "router-rewrite-fail-import",
                "paper_rows": [{
                    "paper_id": paper_id,
                    "project_id": "router-rewrite-fail",
                    "project_name": "Router Rewrite Fail",
                    "project_dir": str(legacy_dir),
                    "run_id": "run-1",
                    "paper_status": "publication_draft",
                    "draft_markdown_path": "papers/run-1/final_paper.md",
                    "draft_latex_path": "papers/run-1/final_paper.tex",
                    "evidence_bundle_path": "papers/run-1/evidence.json",
                    "claim_ledger_path": "papers/run-1/claims.json",
                    "manifest_path": "papers/run-1/manifest.json",
                }],
            })
            client.post("/control/api/paper-reviews/backfill", headers=headers, json={"idempotency_key": "router-rewrite-fail-backfill", "dry_run": False})
            with patch("enoch_control_plane.control_plane.router.write_paper_artifacts", side_effect=RuntimeError("rewrite writer exploded")):
                with self.assertRaisesRegex(RuntimeError, "rewrite writer exploded"):
                    client.post(f"/control/api/paper-reviews/{paper_id}/rewrite-draft", headers=headers, json={
                        "idempotency_key": "router-rewrite-fail-1",
                        "requested_by": "alice",
                        "force": True,
                    })
            paper = client.get(f"/control/api/papers/{paper_id}", headers=headers).json()["paper"]
            self.assertEqual(paper["project_dir"], str(legacy_dir))
            events = client.get(f"/control/api/events?entity_id={paper_id}", headers=headers).json()["rows"]
            self.assertNotIn("paper_review.draft_rewritten", {row["event_type"] for row in events})

    def test_paper_review_rewrite_tolerates_missing_optional_worker_evidence_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _config(tmp).model_copy(update={
                "paper_evidence_sync_enabled": True,
                "worker_wake_gate_url": "http://worker.example",
                "worker_wake_gate_bearer_token": "worker-token",
                "paper_evidence_sync_ssh_host": "missing-ssh-host.invalid",
            })
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            paper_id = "router-sync:run-1:arxiv_draft"
            client.post("/control/import/legacy-snapshot", headers=headers, json={
                "idempotency_key": "router-sync-import",
                "paper_rows": [{
                    "paper_id": paper_id,
                    "project_id": "router-sync",
                    "project_name": "Router Sync",
                    "project_dir": "/legacy/router-sync",
                    "run_id": "run-1",
                    "paper_status": "publication_draft",
                    "draft_markdown_path": "papers/run-1/final_paper.md",
                    "draft_latex_path": "papers/run-1/final_paper.tex",
                    "evidence_bundle_path": "papers/run-1/evidence_bundle.json",
                    "claim_ledger_path": "papers/run-1/claim_ledger.json",
                    "manifest_path": "papers/run-1/manifest.json",
                }],
            })
            client.post("/control/api/paper-reviews/backfill", headers=headers, json={"idempotency_key": "router-sync-backfill", "dry_run": False})

            def fake_worker_post(base_url: str, path: str, token: str, payload: dict) -> HttpResult:
                requested = payload["paths"][0]
                if requested == "run_notes.md":
                    return HttpResult(ok=True, status=200, body={"files": [{"path": requested, "content": "Measured router sync evidence improved throughput by 1.20x.\n"}]})
                if requested == ".enoch/project_decision.json":
                    return HttpResult(ok=True, status=200, body={"files": [{"path": requested, "content": "{\"decision\":\"positive\",\"evidence\":\"measured\"}\n"}]})
                if requested == "papers/run-1/evidence_bundle.json":
                    return HttpResult(ok=True, status=200, body={"files": [{"path": requested, "content": "{\"claims\":[\"measured\"]}"}]})
                return HttpResult(ok=False, status=404, body=None, error=f"missing {requested}")

            with patch("enoch_control_plane.control_plane.router.post_worker_json", side_effect=fake_worker_post):
                response = client.post(f"/control/api/paper-reviews/{paper_id}/rewrite-draft", headers=headers, json={
                    "idempotency_key": "router-sync-rewrite",
                    "requested_by": "alice",
                    "force": True,
                })

            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertIn(body["writer"]["evidence_sync"]["method"], {"worker_http", "worker_http+ssh"})
            self.assertGreaterEqual(body["writer"]["evidence_sync"]["http_sync"]["files"], 2)
            self.assertTrue((Path(body["artifact_root"]) / "papers/run-1/evidence_bundle.json").exists())

    def test_paper_review_prepare_finalization_package_endpoint_is_automated_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            project_dir = Path(tmp) / "projects" / "package-router"
            project_dir.mkdir(parents=True)
            artifact_paths = {
                "draft_markdown_path": "paper.md",
                "draft_latex_path": "paper.tex",
                "evidence_bundle_path": "evidence.json",
                "claim_ledger_path": "claims.json",
                "manifest_path": "manifest.json",
            }
            _write_publication_artifacts(
                project_dir,
                evidence_path=artifact_paths["evidence_bundle_path"],
                claim_path=artifact_paths["claim_ledger_path"],
                manifest_path=artifact_paths["manifest_path"],
            )
            paper_id = "router-package:run-1:arxiv_draft"
            audit_path = Path(tmp) / "audit.json"
            audit_path.write_text(json.dumps({"papers": [{"paper_id": paper_id, "ready": True}]}), encoding="utf-8")
            client.post("/control/import/legacy-snapshot", headers=headers, json={
                "idempotency_key": "router-package-import",
                "paper_rows": [{
                    "paper_id": paper_id,
                    "project_id": "router-package",
                    "project_name": "Router Package",
                    "project_dir": str(project_dir),
                    "run_id": "run-1",
                    "paper_status": "publication_draft",
                    **artifact_paths,
                }],
            })
            client.post("/control/api/paper-reviews/backfill", headers=headers, json={"idempotency_key": "router-package-backfill", "source_audit_path": str(audit_path), "dry_run": False})

            dry = client.post(f"/control/api/paper-reviews/{paper_id}/prepare-finalization-package", headers=headers, json={
                "idempotency_key": "router-package-dry",
                "requested_by": "alice",
                "target_label": "first-paper",
                "dry_run": True,
            })
            self.assertEqual(dry.status_code, 200)
            self.assertTrue(dry.json()["dry_run"])
            self.assertFalse(Path(dry.json()["package_path"]).exists())
            self.assertTrue(dry.json()["manifest"]["no_submission_side_effects"])

            committed = client.post(f"/control/api/paper-reviews/{paper_id}/prepare-finalization-package", headers=headers, json={
                "idempotency_key": "router-package-commit",
                "requested_by": "alice",
                "target_label": "first-paper",
                "dry_run": False,
            })
            self.assertEqual(committed.status_code, 200)
            self.assertFalse(committed.json()["dry_run"])
            self.assertTrue(committed.json()["inserted_event"])
            self.assertEqual(committed.json()["item"]["review_status"], "finalized")
            self.assertTrue(Path(committed.json()["package_path"]).exists())
            self.assertTrue(committed.json()["manifest"]["no_submission_side_effects"])
            repeated = client.post(f"/control/api/paper-reviews/{paper_id}/prepare-finalization-package", headers=headers, json={
                "idempotency_key": "router-package-commit",
                "requested_by": "alice",
                "target_label": "first-paper",
                "dry_run": False,
            })
            self.assertEqual(repeated.status_code, 200)
            self.assertFalse(repeated.json()["inserted_event"])
            self.assertEqual(repeated.json()["event_id"], committed.json()["event_id"])
            paper = client.get(f"/control/api/papers/{paper_id}", headers=headers).json()
            self.assertEqual(paper["paper"]["paper_status"], "publication_draft")

    def test_paper_finalization_rejects_unexpandable_artifact_path_without_500(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            project_dir = Path(tmp) / "projects" / "router-unexpandable-artifact"
            project_dir.mkdir(parents=True)
            paper_id = "router-unexpandable-artifact:run-1:arxiv_draft"
            audit_path = Path(tmp) / "audit.json"
            audit_path.write_text(json.dumps({"papers": [{"paper_id": paper_id, "ready": True}]}), encoding="utf-8")
            imported = client.post("/control/import/legacy-snapshot", headers=headers, json={
                "idempotency_key": "router-unexpandable-artifact-import",
                "paper_rows": [{
                    "paper_id": paper_id,
                    "project_id": "router-unexpandable-artifact",
                    "project_name": "Router Unexpandable Artifact",
                    "project_dir": str(project_dir),
                    "run_id": "run-1",
                    "paper_status": "publication_draft",
                    "draft_markdown_path": "~enoch-user-that-should-not-exist/paper.md",
                    "draft_latex_path": "paper.tex",
                    "evidence_bundle_path": "evidence.json",
                    "claim_ledger_path": "claims.json",
                    "manifest_path": "manifest.json",
                }],
            })
            self.assertEqual(imported.status_code, 200)
            backfill = client.post("/control/api/paper-reviews/backfill", headers=headers, json={
                "idempotency_key": "router-unexpandable-artifact-backfill",
                "source_audit_path": str(audit_path),
                "dry_run": False,
            })
            self.assertEqual(backfill.status_code, 200)

            finalized = client.post(f"/control/api/paper-reviews/{paper_id}/prepare-finalization-package", headers=headers, json={
                "idempotency_key": "router-unexpandable-artifact-finalize",
                "requested_by": "alice",
                "target_label": "bad-artifact-path",
                "dry_run": False,
            })
            self.assertEqual(finalized.status_code, 400)
            self.assertIn("artifact", finalized.text.lower())

    def test_paper_finalization_rejects_unexpandable_project_dir_without_500(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            paper_id = "router-unexpandable-dir:run-1:arxiv_draft"
            audit_path = Path(tmp) / "audit.json"
            audit_path.write_text(json.dumps({"papers": [{"paper_id": paper_id, "ready": True}]}), encoding="utf-8")
            imported = client.post("/control/import/legacy-snapshot", headers=headers, json={
                "idempotency_key": "router-unexpandable-dir-import",
                "paper_rows": [{
                    "paper_id": paper_id,
                    "project_id": "router-unexpandable-dir",
                    "project_name": "Router Unexpandable Dir",
                    "project_dir": "~enoch-user-that-should-not-exist/router-unexpandable-dir",
                    "run_id": "run-1",
                    "paper_status": "publication_draft",
                    "draft_markdown_path": "paper.md",
                    "draft_latex_path": "paper.tex",
                    "evidence_bundle_path": "evidence.json",
                    "claim_ledger_path": "claims.json",
                    "manifest_path": "manifest.json",
                }],
            })
            self.assertEqual(imported.status_code, 200)
            backfill = client.post("/control/api/paper-reviews/backfill", headers=headers, json={
                "idempotency_key": "router-unexpandable-dir-backfill",
                "source_audit_path": str(audit_path),
                "dry_run": False,
            })
            self.assertEqual(backfill.status_code, 200)

            finalized = client.post(f"/control/api/paper-reviews/{paper_id}/prepare-finalization-package", headers=headers, json={
                "idempotency_key": "router-unexpandable-dir-finalize",
                "requested_by": "alice",
                "target_label": "bad-project-dir",
                "dry_run": False,
            })
            self.assertEqual(finalized.status_code, 400)
            self.assertIn("project", finalized.text.lower())

            artifact = client.get(f"/control/api/papers/{paper_id}/artifact/draft_markdown_path", headers=headers)
            self.assertIn(artifact.status_code, {400, 404})
            self.assertNotEqual(artifact.status_code, 500)

    def test_paper_finalization_rejects_invalid_project_dir_without_500(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            paper_id = "router-invalid-dir:run-1:arxiv_draft"
            audit_path = Path(tmp) / "audit.json"
            audit_path.write_text(json.dumps({"papers": [{"paper_id": paper_id, "ready": True}]}), encoding="utf-8")
            imported = client.post("/control/import/legacy-snapshot", headers=headers, json={
                "idempotency_key": "router-invalid-dir-import",
                "paper_rows": [{
                    "paper_id": paper_id,
                    "project_id": "router-invalid-dir",
                    "project_name": "Router Invalid Dir",
                    "project_dir": "bad\0router-invalid-dir",
                    "run_id": "run-1",
                    "paper_status": "publication_draft",
                    "draft_markdown_path": "paper.md",
                    "draft_latex_path": "paper.tex",
                    "evidence_bundle_path": "evidence.json",
                    "claim_ledger_path": "claims.json",
                    "manifest_path": "manifest.json",
                }],
            })
            self.assertEqual(imported.status_code, 200)
            backfill = client.post("/control/api/paper-reviews/backfill", headers=headers, json={
                "idempotency_key": "router-invalid-dir-backfill",
                "source_audit_path": str(audit_path),
                "dry_run": False,
            })
            self.assertEqual(backfill.status_code, 200)

            finalized = client.post(f"/control/api/paper-reviews/{paper_id}/prepare-finalization-package", headers=headers, json={
                "idempotency_key": "router-invalid-dir-finalize",
                "requested_by": "alice",
                "target_label": "bad-project-dir",
                "dry_run": False,
            })

            self.assertEqual(finalized.status_code, 400)
            self.assertNotEqual(finalized.status_code, 500)

    def test_paper_review_rejected_status_is_normalized_before_rewrite_or_finalize(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            project_dir = Path(tmp) / "projects" / "router-rejected-normalized"
            project_dir.mkdir(parents=True)
            artifact_paths = {
                "draft_markdown_path": "paper.md",
                "draft_latex_path": "paper.tex",
                "evidence_bundle_path": "evidence.json",
                "claim_ledger_path": "claims.json",
                "manifest_path": "manifest.json",
            }
            _write_publication_artifacts(
                project_dir,
                evidence_path=artifact_paths["evidence_bundle_path"],
                claim_path=artifact_paths["claim_ledger_path"],
                manifest_path=artifact_paths["manifest_path"],
            )
            (project_dir / ".enoch").mkdir(parents=True, exist_ok=True)
            (project_dir / "run_notes.md").write_text("Measured useful result with grounded evidence.\n", encoding="utf-8")
            (project_dir / ".enoch" / "project_decision.json").write_text('{"project_decision":"finalize_positive"}\n', encoding="utf-8")
            paper_id = "router-rejected-normalized:run-1:arxiv_draft"
            audit_path = Path(tmp) / "audit.json"
            audit_path.write_text(json.dumps({"papers": [{"paper_id": paper_id, "ready": True}]}), encoding="utf-8")
            imported = client.post("/control/import/legacy-snapshot", headers=headers, json={
                "idempotency_key": "router-rejected-normalized-import",
                "paper_rows": [{
                    "paper_id": paper_id,
                    "project_id": "router-rejected-normalized",
                    "project_name": "Router Rejected Normalized",
                    "project_dir": str(project_dir),
                    "run_id": "run-1",
                    "paper_status": "publication_draft",
                    **artifact_paths,
                }],
            })
            self.assertEqual(imported.status_code, 200)
            backfill = client.post("/control/api/paper-reviews/backfill", headers=headers, json={
                "idempotency_key": "router-rejected-normalized-backfill",
                "source_audit_path": str(audit_path),
                "dry_run": False,
            })
            self.assertEqual(backfill.status_code, 200)
            with sqlite3.connect(Path(tmp) / "state" / "control_plane.sqlite3") as conn:
                conn.execute("UPDATE paper_review_items SET review_status=? WHERE paper_id=?", (" Rejected ", paper_id))

            rewrite = client.post(f"/control/api/paper-reviews/{paper_id}/rewrite-draft", headers=headers, json={
                "idempotency_key": "router-rejected-normalized-rewrite",
                "requested_by": "alice",
                "force": True,
            })
            self.assertEqual(rewrite.status_code, 400)
            self.assertIn("rejected", rewrite.text.lower())

            finalized = client.post(f"/control/api/paper-reviews/{paper_id}/prepare-finalization-package", headers=headers, json={
                "idempotency_key": "router-rejected-normalized-finalize",
                "requested_by": "alice",
                "target_label": "reject-variant",
                "dry_run": False,
            })
            self.assertEqual(finalized.status_code, 400)
            self.assertIn("rejected", finalized.text.lower())
            events = client.get(f"/control/api/events?entity_id={paper_id}", headers=headers).json()["rows"]
            event_types = {row["event_type"] for row in events}
            self.assertNotIn("paper_review.draft_rewritten", event_types)
            self.assertNotIn("paper_review.finalization_package_prepared", event_types)

    def test_paper_review_prepare_finalization_rejects_project_dir_escape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            outside = Path(tmp) / "outside"
            outside.mkdir()
            artifact_paths = {
                "draft_markdown_path": "paper.md",
                "draft_latex_path": "paper.tex",
                "evidence_bundle_path": "evidence.json",
                "claim_ledger_path": "claims.json",
                "manifest_path": "manifest.json",
            }
            _write_publication_artifacts(
                outside,
                evidence_path=artifact_paths["evidence_bundle_path"],
                claim_path=artifact_paths["claim_ledger_path"],
                manifest_path=artifact_paths["manifest_path"],
            )
            paper_id = "router-package-escape:run-1:arxiv_draft"
            audit_path = Path(tmp) / "audit.json"
            audit_path.write_text(json.dumps({"papers": [{"paper_id": paper_id, "ready": True}]}), encoding="utf-8")
            client.post("/control/import/legacy-snapshot", headers=headers, json={
                "idempotency_key": "router-package-escape-import",
                "paper_rows": [{
                    "paper_id": paper_id,
                    "project_id": "router-package-escape",
                    "project_name": "Router Package Escape",
                    "project_dir": str(outside),
                    "run_id": "run-1",
                    "paper_status": "publication_draft",
                    **artifact_paths,
                }],
            })
            client.post("/control/api/paper-reviews/backfill", headers=headers, json={"idempotency_key": "router-package-escape-backfill", "source_audit_path": str(audit_path), "dry_run": False})

            committed = client.post(f"/control/api/paper-reviews/{paper_id}/prepare-finalization-package", headers=headers, json={
                "idempotency_key": "router-package-escape-commit",
                "requested_by": "alice",
                "target_label": "escape",
                "dry_run": False,
            })

            self.assertNotEqual(committed.status_code, 200)
            self.assertIn("artifact", committed.text.lower())

    def test_paper_review_status_endpoint_maps_defer_to_explicit_blocked_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            paper_id = "router-status:run-1:arxiv_draft"
            client.post("/control/import/legacy-snapshot", headers=headers, json={
                "idempotency_key": "router-review-status-import",
                "paper_rows": [{
                    "paper_id": paper_id,
                    "project_id": "router-status",
                    "run_id": "run-1",
                    "paper_status": "draft_review",
                    "draft_markdown_path": "paper.md",
                    "draft_latex_path": "paper.tex",
                    "evidence_bundle_path": "evidence.json",
                    "claim_ledger_path": "claims.json",
                    "manifest_path": "manifest.json",
                }],
            })
            client.post("/control/api/paper-reviews/backfill", headers=headers, json={"idempotency_key": "router-status-backfill", "dry_run": False})
            bad = client.post(f"/control/api/paper-reviews/{paper_id}/status", headers=headers, json={
                "idempotency_key": "router-status-no-note",
                "requested_by": "alice",
                "review_status": "blocked",
            })
            self.assertEqual(bad.status_code, 400)
            blocked = client.post(f"/control/api/paper-reviews/{paper_id}/status", headers=headers, json={
                "idempotency_key": "router-status-block",
                "requested_by": "alice",
                "review_status": "blocked",
                "blocker": "venue choice required",
            })
            self.assertEqual(blocked.status_code, 200)
            self.assertEqual(blocked.json()["item"]["review_status"], "blocked")
            self.assertEqual(blocked.json()["item"]["blocker"], "venue choice required")

    def test_dashboard_html_links_to_multiview_apis(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            response = client.get("/control/dashboard")
            self.assertEqual(response.status_code, 200)
            for path in ["/control/api/v1/overview", "/control/api/v1/queue", "/control/api/v1/projects/", "/control/api/v1/runs", "/control/api/v1/papers", "/control/api/v1/events", "/control/api/v1/observability/memory", "/control/api/publication-automation", "/control/api/intake/ideas"]:
                self.assertIn(path, response.text)
            overview_pos = response.text.find("/control/api/v1/overview")
            memory_pos = response.text.find("/control/api/v1/observability/memory")
            self.assertGreater(memory_pos, overview_pos)
            self.assertNotIn("Promise.all([api('/control/api/v1/overview", response.text)
            self.assertIn("if(e.name==='AbortError')return", response.text)
            for stale_path in ["/control/api/status?refresh_worker=true", "/control/api/queues/", "/control/api/events?page_size=200", "/control/api/papers?page_size=100", "/control/api/paper-reviews", "#reviews", "#review:", "['event_id','event_type','entity_type','entity_id','created_at','payload_summary']"]:
                self.assertNotIn(stale_path, response.text)
            for ui_text in ["Publication Automation", "Automated rewrite/finalization lane", "prepare finalization package", "Formatted control-plane events", "Search, filter, sort, and page", "Recently added", "Find projects", "Find papers", "Find runs", "Find events", "choose 200 per page"]:
                self.assertIn(ui_text, response.text)
            for removed_manual_review_text in ["Auto-pass checklist", "approve-finalization", "Paper Review Queue", "Review queue backfilled"]:
                self.assertNotIn(removed_manual_review_text, response.text)
            for removed_raw_state_label in [
                "Needs Review",
                "Wake Ready",
                "Session Finished Ready",
                "Draft Review",
                "Approved For Finalization",
                "Unreviewed",
                "In Review",
                "Changes Requested",
            ]:
                self.assertNotIn(removed_raw_state_label, response.text)


if __name__ == "__main__":
    unittest.main()

def test_project_prompt_includes_canonical_decision_contract() -> None:
    prompt = _project_prompt({"project_id": "p1", "project_name": "Example"})
    assert '"project_decision": "finalize_positive | finalize_negative | needs_review | blocked | continue | branch_new_project"' in prompt
    assert '"followup_recommended": false' in prompt
    assert '"followup_type": ""' in prompt
    assert "Do not invent" in prompt
    assert "partial_viable" in prompt
    assert "promising_synthetic_positive" in prompt
    assert "negative_result" in prompt
    assert "Use `finalize_positive` only when the evidence supports writing a paper now with direct, publication-grade evidence." in prompt
    assert "`continue` is not paper-positive and will not trigger paper writing" in prompt
    assert "prefer `finalize_negative` plus `followup_recommended: true` for promising next-tier work" in prompt
    assert "prefer `finalize_negative` plus `followup_recommended: true`" in prompt
    assert "Evidence-depth rules:" in prompt
    assert "small probe -> medium confirmation -> bounded full-scale validation" in prompt
    assert "GPT-2-small-class baselines" in prompt
    assert "CoSpec-style result" in prompt
    assert "short smoke/proxy/synthetic test may close `finalize_negative`" in prompt
    assert "Do not add new decision fields or enum values." in prompt
    assert "Do not use `finalize_positive` for a proxy-only result" in prompt
    assert "Use `set -o pipefail` before shell pipelines that pipe through `tee`" in prompt
    assert "Follow-up fields are optional adjacent-investigation metadata; they never make this run paper-positive." in prompt
    assert "controller will cap follow-ups at depth 4" in prompt


def test_legacy_finalize_positive_without_evidence_does_not_write_paper() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        client = _client(tmp)
        headers = {"Authorization": f"Bearer {TOKEN}"}
        response = client.post("/control/import/legacy-snapshot", headers=headers, json={
            "idempotency_key": "import-legacy-positive-no-evidence",
            "queue_rows": [{
                "project_id": "legacy-positive-no-evidence",
                "project_name": "Legacy Positive No Evidence",
                "project_dir": "legacy-positive-no-evidence",
                "status": "completed",
                "last_run_state": "finalize_positive",
                "next_action_hint": "draft_paper_or_select_next_project",
                "current_run_id": "run-legacy-positive-no-evidence",
                "manual_review_required": False,
            }],
            "paper_rows": [],
        })
        assert response.status_code == 200

        draft = client.post("/control/papers/draft-next", headers=headers, json={"force": True})

        assert draft.status_code in {200, 424}
        if draft.status_code == 200:
            assert draft.json()["action"] == "noop"
            assert "evidence" in draft.json()["reason"]
        else:
            assert "evidence" in str(draft.json()).lower()
        snapshot = client.get("/control/export/snapshot", headers=headers).json()
        assert snapshot["paper_rows"] == []


def test_legacy_finalize_positive_missing_evidence_records_blocked_alert() -> None:
    from enoch_control_plane.control_plane.alerts import PushoverResult

    with tempfile.TemporaryDirectory() as tmp:
        config = _config(tmp).model_copy(update={
            "paper_evidence_sync_enabled": True,
            "pushover_alerts_enabled": True,
            "pushover_api_token": "token",
            "pushover_user_key": "user",
        })
        client = _client_with_config(config)
        headers = {"Authorization": f"Bearer {TOKEN}"}
        response = client.post("/control/import/legacy-snapshot", headers=headers, json={
            "idempotency_key": "import-legacy-positive-missing-evidence-alert",
            "queue_rows": [{
                "project_id": "legacy-positive-missing-evidence-alert",
                "project_name": "Legacy Positive Missing Evidence Alert",
                "project_dir": "legacy-positive-missing-evidence-alert",
                "status": "completed",
                "last_run_state": "finalize_positive",
                "next_action_hint": "draft_paper_or_select_next_project",
                "current_run_id": "run-legacy-positive-missing-evidence-alert",
                "manual_review_required": False,
            }],
            "paper_rows": [],
        })
        assert response.status_code == 200
        calls = []

        def fake_send_pushover(*args, **kwargs):  # noqa: ANN001 - patched function
            del args
            calls.append(kwargs)
            return PushoverResult(attempted=True, ok=True, status_code=200, detail="ok")

        with patch("enoch_control_plane.control_plane.router._sync_remote_project_evidence", return_value={"enabled": True, "synced": False, "reason": "worker_read_failed"}):
            with patch("enoch_control_plane.control_plane.router.send_pushover", side_effect=fake_send_pushover):
                draft = client.post("/control/papers/draft-next", headers=headers, json={"force": True})

        assert draft.status_code == 200
        assert draft.json()["action"] == "noop"
        assert "evidence" in draft.json()["reason"]
        assert len(calls) == 1
        snapshot = client.get("/control/export/snapshot", headers=headers).json()
        events = [event for event in snapshot["events"] if event["event_type"] == "paper.evidence_sync_blocked"]
        assert len(events) == 1
        assert snapshot["paper_rows"] == []


def test_missing_evidence_alert_is_bucketed_per_run() -> None:
    from enoch_control_plane.control_plane.alerts import PushoverResult

    with tempfile.TemporaryDirectory() as tmp:
        config = _config(tmp).model_copy(update={
            "paper_evidence_sync_enabled": True,
            "pushover_alerts_enabled": True,
            "pushover_api_token": "token",
            "pushover_user_key": "user",
        })
        client = _client_with_config(config)
        headers = {"Authorization": f"Bearer {TOKEN}"}
        response = client.post("/control/import/legacy-snapshot", headers=headers, json={
            "idempotency_key": "import-alert-missing-evidence",
            "queue_rows": [{
                "project_id": "alert-missing-evidence",
                "project_name": "Alert Missing Evidence",
                "project_dir": "alert-missing-evidence",
                "status": "completed",
                "last_run_state": "wake_ready",
                "next_action_hint": "draft_paper_or_select_next_project",
                "current_run_id": "run-alert-missing-evidence",
                "manual_review_required": False,
            }],
            "paper_rows": [],
        })
        assert response.status_code == 200
        calls = []

        def fake_send_pushover(*args, **kwargs):  # noqa: ANN001 - patched function
            del args
            calls.append(kwargs)
            return PushoverResult(attempted=True, ok=True, status_code=200, detail="ok")

        evidence_results = [
            {"enabled": True, "synced": False, "reason": "worker_read_failed", "skipped": [{"path": "run_notes.md"}]},
            {"enabled": True, "synced": False, "reason": "worker_read_failed", "skipped": [{"path": ".enoch/project_decision.json"}]},
        ]
        with patch("enoch_control_plane.control_plane.router._sync_remote_project_evidence", side_effect=evidence_results):
            with patch("enoch_control_plane.control_plane.router.send_pushover", side_effect=fake_send_pushover):
                first = client.post("/control/papers/draft-next", headers=headers, json={"force": True})
                second = client.post("/control/papers/draft-next", headers=headers, json={"force": True})

        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json()["action"] == "noop"
        assert second.json()["action"] == "noop"
        assert len(calls) == 1
        snapshot = client.get("/control/export/snapshot", headers=headers).json()
        events = [event for event in snapshot["events"] if event["event_type"] == "paper.evidence_sync_blocked"]
        assert len(events) == 1



def test_missing_evidence_alert_suppresses_reason_changes_for_same_candidate_day() -> None:
    from enoch_control_plane.control_plane.alerts import PushoverResult

    with tempfile.TemporaryDirectory() as tmp:
        config = _config(tmp).model_copy(update={
            "paper_evidence_sync_enabled": True,
            "pushover_alerts_enabled": True,
            "pushover_api_token": "token",
            "pushover_user_key": "user",
        })
        client = _client_with_config(config)
        headers = {"Authorization": f"Bearer {TOKEN}"}
        response = client.post("/control/import/legacy-snapshot", headers=headers, json={
            "idempotency_key": "import-alert-reason-change",
            "queue_rows": [{
                "project_id": "alert-reason-change",
                "project_name": "Alert Reason Change",
                "project_dir": "alert-reason-change",
                "status": "completed",
                "last_run_state": "wake_ready",
                "next_action_hint": "draft_paper_or_select_next_project",
                "current_run_id": "run-alert-reason-change",
                "manual_review_required": False,
            }],
            "paper_rows": [],
        })
        assert response.status_code == 200
        calls = []

        def fake_send_pushover(*args, **kwargs):  # noqa: ANN001 - patched function
            del args
            calls.append(kwargs)
            return PushoverResult(attempted=True, ok=True, status_code=200, detail="ok")

        evidence_results = [
            {"enabled": True, "synced": False, "reason": "worker_read_failed"},
            {"enabled": True, "synced": False, "reason": "timeout"},
        ]
        with patch("enoch_control_plane.control_plane.router._sync_remote_project_evidence", side_effect=evidence_results):
            with patch("enoch_control_plane.control_plane.router.send_pushover", side_effect=fake_send_pushover):
                with patch("enoch_control_plane.control_plane.router.utc_now", side_effect=["2026-05-17T18:10:00Z", "2026-05-17T19:10:00Z"]):
                    first = client.post("/control/papers/draft-next", headers=headers, json={"force": True})
                    second = client.post("/control/papers/draft-next", headers=headers, json={"force": True})

        assert first.status_code == 200
        assert second.status_code == 200
        assert len(calls) == 1
        snapshot = client.get("/control/export/snapshot", headers=headers).json()
        events = [event for event in snapshot["events"] if event["event_type"] == "paper.evidence_sync_blocked"]
        assert len(events) == 1

def test_missing_evidence_alert_suppresses_same_candidate_across_same_day() -> None:
    from enoch_control_plane.control_plane.alerts import PushoverResult

    with tempfile.TemporaryDirectory() as tmp:
        config = _config(tmp).model_copy(update={
            "paper_evidence_sync_enabled": True,
            "pushover_alerts_enabled": True,
            "pushover_api_token": "token",
            "pushover_user_key": "user",
        })
        client = _client_with_config(config)
        headers = {"Authorization": f"Bearer {TOKEN}"}
        response = client.post("/control/import/legacy-snapshot", headers=headers, json={
            "idempotency_key": "import-alert-same-day",
            "queue_rows": [{
                "project_id": "alert-same-day",
                "project_name": "Alert Same Day",
                "project_dir": "alert-same-day",
                "status": "completed",
                "last_run_state": "wake_ready",
                "next_action_hint": "draft_paper_or_select_next_project",
                "current_run_id": "run-alert-same-day",
                "manual_review_required": False,
            }],
            "paper_rows": [],
        })
        assert response.status_code == 200
        calls = []

        def fake_send_pushover(*args, **kwargs):  # noqa: ANN001 - patched function
            del args
            calls.append(kwargs)
            return PushoverResult(attempted=True, ok=True, status_code=200, detail="ok")

        evidence_results = [
            {"enabled": True, "synced": False, "reason": "worker_read_failed"},
            {"enabled": True, "synced": False, "reason": "worker_read_failed"},
        ]
        with patch("enoch_control_plane.control_plane.router._sync_remote_project_evidence", side_effect=evidence_results):
            with patch("enoch_control_plane.control_plane.router.send_pushover", side_effect=fake_send_pushover):
                with patch("enoch_control_plane.control_plane.router.utc_now", side_effect=["2026-05-17T18:10:00Z", "2026-05-17T19:10:00Z"]):
                    first = client.post("/control/papers/draft-next", headers=headers, json={"force": True})
                    second = client.post("/control/papers/draft-next", headers=headers, json={"force": True})

        assert first.status_code == 200
        assert second.status_code == 200
        assert len(calls) == 1
        snapshot = client.get("/control/export/snapshot", headers=headers).json()
        events = [event for event in snapshot["events"] if event["event_type"] == "paper.evidence_sync_blocked"]
        assert len(events) == 1


def test_missing_evidence_alert_still_notifies_when_event_store_fails() -> None:
    from enoch_control_plane.control_plane.alerts import PushoverResult

    with tempfile.TemporaryDirectory() as tmp:
        config = _config(tmp).model_copy(update={
            "paper_evidence_sync_enabled": True,
            "pushover_alerts_enabled": True,
            "pushover_api_token": "token",
            "pushover_user_key": "user",
        })
        client = _client_with_config(config)
        headers = {"Authorization": f"Bearer {TOKEN}"}
        response = client.post("/control/import/legacy-snapshot", headers=headers, json={
            "idempotency_key": "import-alert-event-store-fails",
            "queue_rows": [{
                "project_id": "alert-event-store-fails",
                "project_name": "Alert Event Store Fails",
                "project_dir": "alert-event-store-fails",
                "status": "completed",
                "last_run_state": "wake_ready",
                "next_action_hint": "draft_paper_or_select_next_project",
                "current_run_id": "run-alert-event-store-fails",
                "manual_review_required": False,
            }],
            "paper_rows": [],
        })
        assert response.status_code == 200
        calls = []

        def fake_send_pushover(*args, **kwargs):  # noqa: ANN001 - patched function
            del args
            calls.append(kwargs)
            return PushoverResult(attempted=True, ok=True, status_code=200, detail="ok")

        original_append_event = ControlPlaneStore.append_event

        def flaky_append_event(self, *args, **kwargs):  # noqa: ANN001 - patched method
            if kwargs.get("event_type") == "paper.evidence_sync_blocked":
                raise OSError("simulated event store failure")
            return original_append_event(self, *args, **kwargs)

        with patch("enoch_control_plane.control_plane.router._sync_remote_project_evidence", return_value={"enabled": True, "synced": False, "reason": "worker_read_failed"}):
            with patch("enoch_control_plane.control_plane.router.send_pushover", side_effect=fake_send_pushover):
                with patch.object(ControlPlaneStore, "append_event", new=flaky_append_event):
                    result = client.post("/control/papers/draft-next", headers=headers, json={"force": True})

        assert result.status_code == 200
        assert result.json()["action"] == "noop"
        assert len(calls) == 1

def test_paper_draft_event_failure_does_not_publish_partial_paper_row() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        client = _client(tmp)
        headers = {"Authorization": f"Bearer {TOKEN}"}
        project_dir = Path(tmp) / "projects" / "paper-event-fail"
        (project_dir / ".enoch").mkdir(parents=True)
        (project_dir / "run_notes.md").write_text("Verified useful result with measured baseline evidence.\n", encoding="utf-8")
        (project_dir / ".enoch" / "project_decision.json").write_text('{"project_decision":"finalize_positive"}\n', encoding="utf-8")
        response = client.post("/control/import/legacy-snapshot", headers=headers, json={
            "idempotency_key": "import-paper-event-fail",
            "queue_rows": [{
                "project_id": "paper-event-fail",
                "project_name": "Paper Event Fail",
                "project_dir": "paper-event-fail",
                "status": "completed",
                "last_run_state": "finalize_positive",
                "next_action_hint": "draft_paper_or_select_next_project",
                "current_run_id": "run-paper-event-fail",
                "manual_review_required": False,
            }],
            "paper_rows": [],
        })
        assert response.status_code == 200
        original_append_event = ControlPlaneStore._append_event_in_conn

        def fail_paper_drafted(self, conn, **kwargs):  # noqa: ANN001 - patched method
            if kwargs.get("event_type") == "paper.drafted":
                raise RuntimeError("simulated paper drafted event failure")
            return original_append_event(self, conn, **kwargs)

        with patch.object(ControlPlaneStore, "_append_event_in_conn", new=fail_paper_drafted):
            with pytest.raises(RuntimeError, match="simulated paper drafted event failure"):
                client.post("/control/papers/draft-next", headers=headers, json={"force": True})

        snapshot = client.get("/control/export/snapshot", headers=headers).json()
        assert snapshot["paper_rows"] == []
        assert client.get("/control/api/paper-reviews", headers=headers).json()["page"]["total"] == 0
        event_types = [event["event_type"] for event in snapshot["events"]]
        assert "paper.drafted" not in event_types
        assert "paper_review.backfill" not in event_types

def test_paper_draft_backfill_failure_is_reported_without_losing_draft() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        client = _client(tmp)
        headers = {"Authorization": f"Bearer {TOKEN}"}
        project_dir = Path(tmp) / "projects" / "paper-backfill-fail"
        (project_dir / ".enoch").mkdir(parents=True)
        (project_dir / "run_notes.md").write_text("Verified useful result with measured baseline evidence.\n", encoding="utf-8")
        (project_dir / ".enoch" / "project_decision.json").write_text('{"project_decision":"finalize_positive"}\n', encoding="utf-8")
        imported = client.post("/control/import/legacy-snapshot", headers=headers, json={
            "idempotency_key": "import-paper-backfill-fail",
            "queue_rows": [{
                "project_id": "paper-backfill-fail",
                "project_name": "Paper Backfill Fail",
                "project_dir": "paper-backfill-fail",
                "status": "completed",
                "last_run_state": "finalize_positive",
                "next_action_hint": "draft_paper_or_select_next_project",
                "current_run_id": "run-paper-backfill-fail",
                "manual_review_required": False,
            }],
            "paper_rows": [],
        })
        assert imported.status_code == 200

        with patch.object(ControlPlaneStore, "backfill_paper_reviews", side_effect=RuntimeError("simulated backfill outage")):
            response = client.post("/control/papers/draft-next", headers=headers, json={"force": True})

        assert response.status_code == 200
        body = response.json()
        assert body["action"] == "drafted"
        assert body["candidate"]["project_id"] == "paper-backfill-fail"
        errors = body["candidate"].get("writer", {}).get("review_backfill", {}).get("errors", [])
        assert any("simulated backfill outage" in str(error.get("reason")) for error in errors)
        snapshot = client.get("/control/export/snapshot", headers=headers).json()
        assert [row["project_id"] for row in snapshot["paper_rows"]] == ["paper-backfill-fail"]
        event_types = [event["event_type"] for event in snapshot["events"]]
        assert "paper.drafted" in event_types


def test_draft_next_live_rejects_supabase_readonly_before_artifact_writes() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        config = _config(tmp).model_copy(
            update={
                "control_plane_store_backend": "supabase_readonly",
                "supabase_database_url": "postgres://example",
            }
        )
        project_dir = config.expanded_project_root / "readonly-draft"
        (project_dir / ".enoch").mkdir(parents=True)
        (project_dir / "run_notes.md").write_text("Measured useful result.\n", encoding="utf-8")
        (project_dir / ".enoch" / "project_decision.json").write_text('{"project_decision":"finalize_positive"}\n', encoding="utf-8")

        class FakeReadOnlyStore:
            def queue_rows(self) -> list[dict[str, object]]:
                return [
                    {
                        "project_id": "readonly-draft",
                        "project_name": "Readonly Draft",
                        "project_dir": "readonly-draft",
                        "status": "completed",
                        "last_run_state": "finalize_positive",
                        "next_action_hint": "draft_paper_or_select_next_project",
                        "current_run_id": "run-readonly-draft",
                        "manual_review_required": False,
                    }
                ]

            def paper_rows(self) -> list[dict[str, object]]:
                return []

        with patch("enoch_control_plane.control_plane.router.SupabaseReadOnlyControlPlaneStore", return_value=FakeReadOnlyStore()):
            client = _client_with_config(config)
            response = client.post("/control/papers/draft-next", headers={"Authorization": f"Bearer {TOKEN}"}, json={"force": True})

        assert response.status_code == 501
        assert "writable control-plane store" in response.text
        assert not (project_dir / "papers").exists()
