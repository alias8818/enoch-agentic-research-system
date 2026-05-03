from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from omx_wake_gate.config import GateConfig
from omx_wake_gate.control_plane.router import create_control_plane_router
from omx_wake_gate.control_plane.store import ControlPlaneStore
from omx_wake_gate.control_plane.models import WorkerPreflightCheck, WorkerPreflightResponse
from omx_wake_gate.control_plane.worker_adapter import HttpResult


TOKEN = "test-token"


def _config(tmp: str) -> GateConfig:
    root = Path(tmp) / "projects"
    root.mkdir(parents=True, exist_ok=True)
    return GateConfig(
        state_dir=str(Path(tmp) / "state"),
        project_root=str(root),
        dispatch_script_path=str(Path(tmp) / "dispatch.sh"),
        omx_inbound_bearer_token=TOKEN,
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


class ControlPlaneRouterTests(unittest.TestCase):
    def test_pause_import_dry_run_and_draft(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "projects" / "idea-positive"
            project_dir.mkdir(parents=True)
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

            draft = client.post("/control/papers/draft-next", headers=headers, json={"force": True})
            self.assertEqual(draft.status_code, 200)
            body = draft.json()
            self.assertEqual(body["action"], "drafted")
            self.assertTrue((project_dir / body["paper"]["draft_markdown_path"]).exists())

    def test_export_and_notion_projection_endpoints(self) -> None:
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

            queue_projection = client.get("/control/projections/notion/queue", headers=headers)
            self.assertEqual(queue_projection.status_code, 200)
            self.assertEqual(queue_projection.json()["rows"][0]["queue_status"], "awaiting_wake")

            papers_projection = client.get("/control/projections/notion/papers", headers=headers)
            self.assertEqual(papers_projection.status_code, 200)
            self.assertEqual(papers_projection.json()["counts"]["draft_review"], 1)

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

    def test_notion_intake_and_execution_update_projection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            dry_run = client.post("/control/intake/notion-ideas", headers=headers, json={
                "dry_run": True,
                "notion_rows": [{
                    "id": "00000000-0000-4000-8000-000000000001",
                    "property_idea": "Dynamic Context Window Training",
                    "property_status": "exploring",
                    "property_priority": "High",
                    "url": "https://www.notion.so/Dynamic-Context-Window-Training-00000000000040008000000000000001",
                }],
            })
            self.assertEqual(dry_run.status_code, 200)
            self.assertTrue(dry_run.json()["dry_run"])
            self.assertEqual(dry_run.json()["created"], 0)
            self.assertEqual(len(dry_run.json()["candidates"]), 1)

            commit = client.post("/control/intake/notion-ideas", headers=headers, json={
                "idempotency_key": "router-notion-intake-1",
                "dry_run": False,
                "notion_rows": [{
                    "id": "00000000-0000-4000-8000-000000000001",
                    "property_idea": "Dynamic Context Window Training",
                    "property_status": "testing",
                    "property_priority": "Medium",
                    "url": "https://www.notion.so/Dynamic-Context-Window-Training-00000000000040008000000000000001",
                }],
            })
            self.assertEqual(commit.status_code, 200)
            self.assertEqual(commit.json()["created"], 1)

            projection = client.get("/control/projections/notion/execution-updates", headers=headers)
            self.assertEqual(projection.status_code, 200)
            self.assertEqual(projection.json()["counts"]["updates"], 1)
            row = projection.json()["rows"][0]
            self.assertEqual(row["page_id"], "00000000-0000-4000-8000-000000000001")
            props = row["properties"]
            self.assertEqual(props["Execution State"], "queued")
            self.assertEqual(props["Current Run ID"], "")
            self.assertEqual(props["OMX Project ID"], "00000000000040008000000000000001")
            self.assertEqual(props["OMX Queue Status"], "queued")

    def test_control_dashboard_html_is_served_without_token(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            response = client.get("/control/dashboard")
            self.assertEqual(response.status_code, 200)
            self.assertIn("Enoch Control Status", response.text)
            self.assertIn("/control/api/status", response.text)
            self.assertIn("Queue Health", response.text)
            self.assertEqual(response.headers.get("cache-control"), "no-store")
            self.assertIn("cache:'no-store'", response.text)
            self.assertIn("autoRefreshCurrentPage", response.text)
            self.assertIn("h==='health'", response.text)


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
            self.assertIn("notion_sync", body["source_freshness"])
            self.assertIn("snapshot_mirror", body["source_freshness"])


    def test_dashboard_status_blocks_dispatch_without_fresh_worker_evidence(self) -> None:
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
            status = client.get("/control/api/status", headers=headers).json()
            self.assertFalse(status["dispatch_safe"])
            self.assertIn("worker_preflight stale or missing", status["dispatch_blockers"])
            self.assertIn("worker_dashboard_api stale or missing", status["dispatch_blockers"])
            self.assertTrue(status["source_freshness"]["worker_preflight"]["stale"])


    def test_dashboard_status_refreshes_stale_worker_evidence_when_requested(self) -> None:
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
                        data={"body": {"totals": {"active_or_waiting": 1, "live": 1}, "telemetry": {}}},
                    ),
                    WorkerPreflightCheck(
                        name="worker_no_live_runs",
                        ok=False,
                        detail="active_or_waiting=1, live=1",
                        data={"active_or_waiting": 1, "live": 1},
                    ),
                ],
            )
            with patch("omx_wake_gate.control_plane.router.run_worker_preflight", return_value=response) as preflight:
                status = client.get("/control/api/status?refresh_worker=true", headers=headers).json()

            preflight.assert_called_once()
            self.assertFalse(status["source_freshness"]["worker_preflight"]["stale"])
            self.assertFalse(status["source_freshness"]["worker_dashboard_api"]["stale"])
            self.assertEqual(status["warnings"], [])
            self.assertEqual(status["conflicts"], [])
            self.assertEqual(status["dispatch_blockers"], ["active GB10 lane exists"])

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
            with patch("omx_wake_gate.control_plane.router.run_worker_preflight", return_value=response) as preflight:
                status = client.get("/control/api/status?refresh_worker=true", headers=headers).json()

            preflight.assert_called_once()
            self.assertEqual(status["warnings"], [])
            self.assertEqual(status["conflicts"], [])
            self.assertEqual(status["dispatch_blockers"], ["no queued dispatch candidate"])


    def test_dashboard_status_without_refresh_preserves_dispatch_safety_for_stale_worker_evidence(self) -> None:
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
            with patch("omx_wake_gate.control_plane.router.run_worker_preflight") as preflight:
                status = client.get("/control/api/status", headers=headers).json()

            preflight.assert_not_called()
            self.assertIn("worker_preflight stale or missing", status["dispatch_blockers"])
            self.assertIn("worker_dashboard_api stale or missing", status["dispatch_blockers"])


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
            client = _client(tmp)
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
            with patch("omx_wake_gate.control_plane.router.write_paper_artifacts", side_effect=RuntimeError("writer exploded")):
                with self.assertRaisesRegex(RuntimeError, "writer exploded"):
                    client.post("/control/papers/draft-next", headers=headers, json={"force": True})
            snapshot = client.get("/control/export/snapshot", headers=headers).json()
            project = next(row for row in snapshot["queue_rows"] if row["project_id"] == "idea-draft-fail")
            self.assertEqual(project["project_dir"], original_dir)
            self.assertEqual(snapshot["paper_rows"], [])

    def test_notion_observation_endpoint_refreshes_status_freshness(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            response = client.post("/control/api/intake/notion-observation", headers=headers, json={"status": "warn", "payload": {"reason": "missing credentials"}})
            self.assertEqual(response.status_code, 200)
            status = client.get("/control/api/status", headers=headers).json()
            notion = status["source_freshness"]["notion_sync"]
            self.assertFalse(notion["stale"])
            self.assertEqual(notion["status"], "warn")

            missing = client.post("/control/api/intake/notion-observation", headers=headers, json={"status": "missing", "payload": {"reason": "legacy missing status"}})
            self.assertEqual(missing.status_code, 200)
            self.assertEqual(missing.json()["observation"]["status"], "warn")

    def test_worker_preflight_endpoint_requires_auth_and_returns_checks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            response = client.post("/control/worker/preflight", headers=headers, json={"wake_gate_url": "http://127.0.0.1:1"})
            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertFalse(body["ok"])
            self.assertTrue(any(check["name"] == "wake_gate_healthz" for check in body["checks"]))


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
            notion = client.post("/control/intake/notion-ideas", headers=headers, json={
                "idempotency_key": "dashboard-api-notion",
                "dry_run": False,
                "notion_rows": [{
                    "id": "11111111-2222-3333-4444-555555555555",
                    "property_idea": "Notion Intake API",
                    "property_status": "testing",
                    "property_priority": "High",
                    "url": "https://notion.example/intake",
                }, {"property_status": "testing"}],
            })
            self.assertEqual(notion.status_code, 200)

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

            intake = client.get("/control/api/intake/notion", headers=headers)
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
            self.assertEqual(body["page"]["total"], 242)
            self.assertEqual(len(body["rows"]), 242)
            self.assertEqual(body["counts"]["triage_ready"], 242)
            self.assertEqual(body["rows"][0]["paper_status"], "publication_draft")
            self.assertIn("rank_reasons", body["rows"][0])

            filtered = client.get("/control/api/paper-reviews?page_size=500&paper_status=draft_review&search=idea-200", headers=headers)
            self.assertEqual(filtered.status_code, 200)
            self.assertEqual(filtered.json()["page"]["total"], 1)

            detail_id = body["rows"][0]["paper_id"]
            detail = client.get(f"/control/api/paper-reviews/{detail_id}", headers=headers)
            self.assertEqual(detail.status_code, 200)
            self.assertEqual(detail.json()["item"]["paper_id"], detail_id)
            self.assertEqual(detail.json()["paper"]["paper_id"], detail_id)

            next_review = client.get("/control/api/paper-reviews/next?paper_status=publication_draft", headers=headers)
            self.assertEqual(next_review.status_code, 200)
            self.assertEqual(next_review.json()["item"]["paper_id"], detail_id)

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
            self.assertEqual(claim.json()["item"]["review_status"], "in_review")
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
            self.assertEqual(approval.status_code, 200)
            self.assertEqual(approval.json()["item"]["review_status"], "approved_for_finalization")
            approval_repeat = client.post(f"/control/api/paper-reviews/{paper_id}/approve-finalization", headers=headers, json={
                "idempotency_key": "router-approve-1",
                "requested_by": "alice",
                "note": "ready",
            })
            self.assertEqual(approval_repeat.status_code, 200)
            self.assertFalse(approval_repeat.json()["inserted_event"])
            self.assertEqual(approval_repeat.json()["event_id"], approval.json()["event_id"])

            rejected_status = client.post(f"/control/api/paper-reviews/{paper_id}/status", headers=headers, json={
                "idempotency_key": "router-status-invalid",
                "requested_by": "alice",
                "review_status": "rejected",
                "note": "no",
            })
            self.assertEqual(rejected_status.status_code, 400)

            events = client.get(f"/control/api/events?entity_id={paper_id}", headers=headers)
            self.assertEqual(events.status_code, 200)
            event_types = {row["event_type"] for row in events.json()["rows"]}
            self.assertIn("paper_review.claimed", event_types)
            self.assertIn("paper_review.checklist_updated", event_types)
            self.assertIn("paper_review.approved_for_finalization", event_types)

    def test_paper_review_bulk_rewrite_batches_publication_drafts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _config(tmp)
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            papers = []
            for idx in range(3):
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
            with patch("omx_wake_gate.control_plane.router.write_paper_artifacts", side_effect=RuntimeError("rewrite writer exploded")):
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
                if requested == "papers/run-1/evidence_bundle.json":
                    return HttpResult(ok=True, status=200, body={"files": [{"path": requested, "content": "{\"claims\":[\"measured\"]}"}]})
                return HttpResult(ok=False, status=404, body=None, error=f"missing {requested}")

            with patch("omx_wake_gate.control_plane.router.post_worker_json", side_effect=fake_worker_post):
                response = client.post(f"/control/api/paper-reviews/{paper_id}/rewrite-draft", headers=headers, json={
                    "idempotency_key": "router-sync-rewrite",
                    "requested_by": "alice",
                    "force": True,
                })

            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertEqual(body["writer"]["evidence_sync"]["method"], "worker_http")
            self.assertEqual(body["writer"]["evidence_sync"]["http_sync"]["files"], 1)
            self.assertTrue((Path(body["artifact_root"]) / "papers/run-1/evidence_bundle.json").exists())

    def test_paper_review_prepare_finalization_package_endpoint_is_guarded_and_idempotent(self) -> None:
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
            for rel in artifact_paths.values():
                (project_dir / rel).write_text("{}" if rel.endswith(".json") else "content", encoding="utf-8")
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

            blocked = client.post(f"/control/api/paper-reviews/{paper_id}/prepare-finalization-package", headers=headers, json={
                "idempotency_key": "router-package-blocked",
                "requested_by": "alice",
                "dry_run": False,
            })
            self.assertEqual(blocked.status_code, 400)

            client.post(f"/control/api/paper-reviews/{paper_id}/claim", headers=headers, json={"idempotency_key": "router-package-claim", "requested_by": "alice", "reviewer": "alice"})
            for item_id in ["artifact_readability", "title_abstract_quality", "claim_evidence_alignment", "novelty_significance", "reproducibility", "limitations_ethics", "formatting_quality", "final_human_approval"]:
                response = client.post(f"/control/api/paper-reviews/{paper_id}/checklist/{item_id}", headers=headers, json={
                    "idempotency_key": f"router-package-check-{item_id}",
                    "requested_by": "alice",
                    "status": "pass",
                })
                self.assertEqual(response.status_code, 200)
            approval = client.post(f"/control/api/paper-reviews/{paper_id}/approve-finalization", headers=headers, json={"idempotency_key": "router-package-approve", "requested_by": "alice"})
            self.assertEqual(approval.status_code, 200)
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
            for path in ["/control/api/queues/", "/control/api/projects/", "/control/api/runs/", "/control/api/papers", "/control/api/paper-reviews", "/control/api/events", "/control/api/intake/notion"]:
                self.assertIn(path, response.text)
            for ui_text in ["Publication Review", "publication_review_v1 checklist", "approve-finalization", "prepare-finalization-package", "review queue"]:
                self.assertIn(ui_text, response.text)


if __name__ == "__main__":
    unittest.main()
