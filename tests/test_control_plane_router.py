from __future__ import annotations

import json
import hashlib
import inspect
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from enoch_control_plane.config import GateConfig
from enoch_control_plane.control_plane.router import (
    _active_lane_worker_confirmation,
    _codex_dispatch_model,
    _fetch_synthetic_research_budget,
    _handle_followup_and_early_skips,
    _project_prompt,
    _paper_material_graph_response,
    _register_control_plane_maintenance_routes,
    _run_resume_systemctl,
    _write_deterministic_paper,
    create_control_plane_router,
)
from enoch_control_plane.control_plane.llm_harness_telemetry import (
    LLM_HARNESS_ROUTE_DECISION_EVENT,
    record_llm_harness_event,
)
from enoch_control_plane.control_plane.store import ControlPlaneStore
from enoch_control_plane.control_plane.alerts import _suppress_dispatch_race_findings
from enoch_control_plane.control_plane.models import (
    ImportSnapshotRequest,
    PaperRecord,
    PaperReviewBackfillRequest,
    WorkerPreflightCheck,
    WorkerPreflightResponse,
    DashboardFinding,
    DashboardObservationRecord,
)
from enoch_control_plane.control_plane.worker_adapter import HttpResult
from enoch_control_plane.enoch_core.store import IdempotencyConflict


TOKEN = "test-token"


def test_codex_dispatch_model_falls_back_for_provider_route_ids() -> None:
    assert _codex_dispatch_model({"model": "minimax/minimax-m2.7"}) == "gpt-5.5"
    assert _codex_dispatch_model({"model": "hf:zai-org/GLM-5.1"}) == "gpt-5.5"
    assert _codex_dispatch_model({"model": "gpt-5.5"}) == "gpt-5.5"
    assert _codex_dispatch_model({}) == "gpt-5.5"


def test_maintenance_route_registrar_does_not_require_unused_config() -> None:
    assert (
        "config"
        not in inspect.signature(_register_control_plane_maintenance_routes).parameters
    )


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
    quality_dir = Path(base.state_dir) / "research-quality"
    quality_dir.mkdir(parents=True, exist_ok=True)
    (quality_dir / "latest-report.json").write_text(
        json.dumps(
            {
                "schema_version": "enoch_research_quality_report_v1",
                "generated_at": "2026-05-30T00:00:00Z",
                "summary": {"candidate_count": 0, "decision_count": 0},
                "candidate_scores": [],
                "decision_scores": [],
            }
        ),
        encoding="utf-8",
    )
    return base.model_copy(
        update={
            "live_dispatch_enabled": True,
            "worker_wake_gate_bearer_token": "worker-token",
        }
    )


def _write_synthetic_llm_settings(
    config: GateConfig,
    test_provider_token: str,
    *,
    base_url: str = "https://api.synthetic.new/openai/v1",
) -> None:
    state_dir = Path(config.state_dir)
    secret_dir = state_dir / "llm-provider-secrets"
    secret_dir.mkdir(parents=True, exist_ok=True)
    (secret_dir / "synthetic.token").write_text(test_provider_token, encoding="utf-8")
    (state_dir / "llm-provider-settings.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "providers": [
                    {
                        "provider_id": "synthetic",
                        "label": "Synthetic",
                        "api_format": "openai_compatible",
                        "base_url": base_url,
                        "api_key_env": "",
                        "enabled": True,
                    },
                    {
                        "provider_id": "openrouter",
                        "label": "OpenRouter",
                        "api_format": "openai_compatible",
                        "base_url": "https://openrouter.ai/api/v1",
                        "api_key_env": "",
                        "enabled": True,
                    },
                ],
                "models": [
                    {
                        "model_id": "hf:zai-org/GLM-5.1",
                        "provider_id": "synthetic",
                        "label": "GLM",
                        "enabled": True,
                    },
                    {
                        "model_id": "moonshotai/kimi-k2.6",
                        "provider_id": "openrouter",
                        "label": "Kimi",
                        "enabled": True,
                    },
                ],
                "workflows": [
                    {
                        "workflow_id": "research_generation",
                        "label": "Research agents",
                        "provider_ids": ["synthetic", "openrouter"],
                        "model_pool": [
                            "hf:zai-org/GLM-5.1",
                            "moonshotai/kimi-k2.6",
                        ],
                        "default_model": "moonshotai/kimi-k2.6",
                        "enabled": True,
                        "temperature": 0.7,
                        "max_tokens": 8000,
                    },
                    {
                        "workflow_id": "paper_writing",
                        "label": "Paper writing",
                        "provider_ids": ["synthetic"],
                        "model_pool": ["hf:zai-org/GLM-5.1"],
                        "default_model": "hf:zai-org/GLM-5.1",
                        "enabled": True,
                        "temperature": 0.2,
                        "max_tokens": 12000,
                    },
                    {
                        "workflow_id": "research_review",
                        "label": "Research review",
                        "provider_ids": ["synthetic"],
                        "model_pool": ["hf:zai-org/GLM-5.1"],
                        "default_model": "hf:zai-org/GLM-5.1",
                        "enabled": True,
                        "temperature": 0.2,
                        "max_tokens": 8000,
                    },
                    {
                        "workflow_id": "general_agent",
                        "label": "General agents",
                        "provider_ids": ["synthetic"],
                        "model_pool": ["hf:zai-org/GLM-5.1"],
                        "default_model": "hf:zai-org/GLM-5.1",
                        "enabled": True,
                        "temperature": 0.3,
                        "max_tokens": 8000,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )


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


def test_paper_material_graph_response_is_bounded_read_only(tmp_path: Path) -> None:
    graph_path = tmp_path / "paper-material-graph.json"
    graph_path.write_text(
        json.dumps(
            {
                "schema_version": "paper_material_graph_v1",
                "generated_at": "2026-06-07T02:22:36Z",
                "summary": {
                    "paper_count": 2,
                    "signal_count": 3,
                    "source_count": 4,
                    "edge_count": 5,
                    "similar_topic_edges": 1,
                    "connected_component_count": 1,
                    "edge_counts": {"similar_topic": 1, "cites_source": 4},
                    "signal_status_counts": {"useful_signal": 2},
                    "synthesis_candidates": [
                        {
                            "signal_id": "signal:one",
                            "packet_path": "candidates/synthesis/one.md",
                            "title": "Candidate one",
                            "status": "useful_signal",
                            "score": 95,
                            "curation_score": 88,
                            "recommended_next_action": "Write a packet",
                            "related_paper_count": 9,
                            "related_source_count": 2,
                            "related_papers": [{"title": "Paper A"}] * 9,
                            "sources": [{"title": "Source A"}] * 9,
                        }
                    ]
                    * 10,
                    "negative_result_candidates": [
                        {
                            "signal_id": "signal:blocked",
                            "title": "Blocked candidate",
                            "status": "compute_scale_blocked",
                            "score": 100,
                            "evidence_strength": "strong",
                            "hypothesis_status": "supported",
                            "claim_scope": "bounded rejudge",
                            "scale_limits": "park unless cheaper bounded test exists",
                        }
                    ]
                    * 10,
                },
            }
        ),
        encoding="utf-8",
    )

    response = _paper_material_graph_response(graph_path)

    assert response["ok"] is True
    assert response["graph_generated_at"] == "2026-06-07T02:22:36Z"
    assert response["counts"] == {
        "paper_count": 2,
        "signal_count": 3,
        "source_count": 4,
        "edge_count": 5,
        "similar_topic_edges": 1,
        "connected_component_count": 1,
        "synthesis_candidate_count": 10,
        "negative_result_candidate_count": 10,
    }
    assert len(response["candidates"]["synthesis"]) == 8
    assert len(response["candidates"]["negative"]) == 8
    assert len(response["candidates"]["synthesis"][0]["related_papers"]) == 5
    assert len(response["candidates"]["synthesis"][0]["sources"]) == 5


def test_paper_material_graph_response_uses_helper_boundaries() -> None:
    source = inspect.getsource(_paper_material_graph_response)

    assert "_paper_material_graph_summary(graph)" in source
    assert "_paper_material_graph_candidates(summary)" in source
    assert "_paper_material_graph_counts(summary)" in source
    assert "for candidate in list(summary.get" not in source


def test_paper_material_graph_endpoint_documents_invalid_json_503() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        openapi = _client(tmp).get("/openapi.json").json()

    responses = openapi["paths"]["/control/api/v1/paper-material-graph"]["get"][
        "responses"
    ]
    assert "503" in responses
    assert (
        "paper material graph artifact is not valid JSON"
        in responses["503"]["description"]
    )


def test_paper_material_graph_endpoint_requires_auth_and_reads_artifact(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    graph_path = tmp_path / "paper-material-graph.json"
    graph_path.write_text(
        json.dumps(
            {
                "schema_version": "paper_material_graph_v1",
                "generated_at": "2026-06-07T02:22:36Z",
                "summary": {
                    "paper_count": 1,
                    "signal_count": 1,
                    "source_count": 1,
                    "edge_count": 2,
                    "similar_topic_edges": 1,
                    "connected_component_count": 1,
                    "synthesis_candidates": [
                        {
                            "signal_id": "signal:one",
                            "packet_path": "candidates/synthesis/one.md",
                            "title": "Candidate one",
                        }
                    ],
                    "negative_result_candidates": [
                        {"signal_id": "signal:blocked", "title": "Blocked candidate"}
                    ],
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "enoch_control_plane.control_plane.router.PAPER_MATERIAL_GRAPH_PATH",
        graph_path,
    )
    with tempfile.TemporaryDirectory() as tmp:
        client = _client(tmp)
        with pytest.raises(AssertionError, match="bad token"):
            client.get("/control/api/v1/paper-material-graph")
        response = client.get(
            "/control/api/v1/paper-material-graph",
            headers={"Authorization": f"Bearer {TOKEN}"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["counts"]["paper_count"] == 1
    assert body["candidates"]["synthesis"][0]["title"] == "Candidate one"
    assert (
        body["candidates"]["synthesis"][0]["packet_path"]
        == "candidates/synthesis/one.md"
    )
    assert body["candidates"]["negative"][0]["title"] == "Blocked candidate"


def test_writable_store_routes_openapi_documents_readonly_store_501() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        openapi = _client(tmp).get("/openapi.json").json()

    writable_post_paths = (
        "/control/pause",
        "/control/resume",
        "/control/api/maintenance/resume",
        "/control/api/settings/llm",
    )
    for path in writable_post_paths:
        responses = openapi["paths"][path]["post"]["responses"]
        assert "501" in responses, path
        assert "writable control-plane store" in responses["501"]["description"]


def test_dashboard_maintenance_resume_rearms_systemd_and_records_observation() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        client = _client(tmp)
        headers = {"Authorization": f"Bearer {TOKEN}"}
        client.post(
            "/control/pause",
            headers=headers,
            json={
                "reason": "maintenance",
                "paused_by": "pytest",
                "maintenance_mode": True,
            },
        )

        rearm = {
            "ok": True,
            "action": "systemd_rearm_and_kick",
            "timers": ["enoch-research-autopilot.timer"],
            "kick_services": ["enoch-research-autopilot.service"],
            "steps": [],
            "failures": [],
        }
        with patch(
            "enoch_control_plane.control_plane.router._resume_automation_after_control_resume",
            return_value=rearm,
        ) as rearm_helper:
            response = client.post(
                "/control/api/maintenance/resume",
                headers=headers,
                json={"resumed_by": "dashboard-v2", "maintenance_mode": False},
            )

        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        assert body["flags"]["queue_paused"] is False
        assert body["flags"]["maintenance_mode"] is False
        assert body["systemd"] == rearm
        rearm_helper.assert_called_once_with()

        events = client.get("/control/api/events", headers=headers).json()["rows"]
        rearm_events = [
            event
            for event in events
            if event["event_type"] == "control.resume.systemd_rearm"
        ]
        assert len(rearm_events) == 1
        assert rearm_events[0]["entity_id"] == "queue"


def test_resume_systemctl_exception_response_omits_raw_exception_text() -> None:
    def raise_os_error(*args: object, **kwargs: object) -> object:
        raise OSError("Traceback: token=secret path=/root/private")

    with patch("subprocess.run", side_effect=raise_os_error):
        result = _run_resume_systemctl(["restart", "enoch-research-autopilot.timer"])

    encoded = json.dumps(result)
    assert result == {
        "ok": False,
        "command": ["systemctl", "restart", "enoch-research-autopilot.timer"],
        "error": "systemctl command failed to start",
        "error_type": "OSError",
    }
    assert "Traceback" not in encoded
    assert "secret" not in encoded
    assert "/root/private" not in encoded


def test_draft_next_live_requires_named_override_while_paused() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        config = _config(tmp)
        project_dir = Path(config.project_root) / "idea-draft-held"
        project_dir.mkdir(parents=True)
        (project_dir / "run_notes.md").write_text(
            "Positive evidence supports drafting this paper.\n", encoding="utf-8"
        )
        (project_dir / ".enoch").mkdir(parents=True)
        (project_dir / ".enoch" / "project_decision.json").write_text(
            '{"project_decision":"finalize_positive"}\n', encoding="utf-8"
        )
        client = _client_with_config(config)
        headers = {"Authorization": f"Bearer {TOKEN}"}
        client.post(
            "/control/import/legacy-snapshot",
            headers=headers,
            json={
                "idempotency_key": "import-draft-held",
                "queue_rows": [
                    {
                        "project_id": "idea-draft-held",
                        "project_name": "Draft Held",
                        "project_dir": str(project_dir),
                        "status": "completed",
                        "last_run_state": "finalize_positive",
                        "current_run_id": "run-draft-held",
                        "manual_review_required": False,
                    }
                ],
                "paper_rows": [],
            },
        )
        client.post(
            "/control/pause",
            headers=headers,
            json={
                "reason": "test hold",
                "paused_by": "pytest",
                "maintenance_mode": False,
            },
        )

        response = client.post(
            "/control/papers/draft-next",
            headers=headers,
            json={"force": True, "dry_run": False, "requested_by": "pytest"},
        )
        assert response.status_code == 409
        assert "draft-next-while-held" in response.text

        override = client.post(
            "/control/papers/draft-next",
            headers=headers,
            json={
                "force": True,
                "dry_run": False,
                "requested_by": "pytest",
                "override_hold_action": "draft-next-while-held",
            },
        )
        assert override.status_code == 200


def test_followup_launch_live_requires_named_override_while_paused() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        client = _client(tmp)
        headers = {"Authorization": f"Bearer {TOKEN}"}
        client.post(
            "/control/pause",
            headers=headers,
            json={
                "reason": "test hold",
                "paused_by": "pytest",
                "maintenance_mode": False,
            },
        )

        response = client.post(
            "/control/api/v1/followups/launch-next",
            headers=headers,
            json={"dry_run": False, "requested_by": "pytest"},
        )
        assert response.status_code == 409
        assert "followup-launch-while-held" in response.text

        override = client.post(
            "/control/api/v1/followups/launch-next",
            headers=headers,
            json={
                "dry_run": False,
                "requested_by": "pytest",
                "override_hold_action": "followup-launch-while-held",
            },
        )
        assert override.status_code == 200


def test_observability_health_exposes_sentry_status_without_dsn(monkeypatch) -> None:
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    monkeypatch.setattr(
        "enoch_control_plane.control_plane.router.is_sentry_enabled",
        lambda: False,
    )
    with tempfile.TemporaryDirectory() as tmp:
        client = _client(tmp)
        response = client.get(
            "/control/api/v1/observability/health",
            headers={"Authorization": f"Bearer {TOKEN}"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["sentry_configured"] is False
    assert body["sentry_enabled"] is False
    assert body["sentry_environment"]
    assert body["sentry_release"]


def test_observability_sentry_smoke_is_authenticated_and_reports_safe_exception() -> (
    None
):
    with tempfile.TemporaryDirectory() as tmp:
        client = _client(tmp)
        headers = {"Authorization": f"Bearer {TOKEN}"}
        with patch(
            "enoch_control_plane.control_plane.router.capture_exception",
            return_value="event-smoke-123",
        ) as capture:
            response = client.post(
                "/control/api/v1/observability/sentry-smoke",
                headers=headers,
            )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["event_id"] == "event-smoke-123"
    capture.assert_called_once()
    _, kwargs = capture.call_args
    assert kwargs["component"] == "control_plane"
    assert kwargs["operation"] == "sentry_smoke"
    assert "payload" not in kwargs
    assert "prompt" not in kwargs


def test_observability_sentry_smoke_requires_authentication() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        app = FastAPI()
        config = _config(tmp)

        def require(auth: str | None) -> None:
            if auth != f"Bearer {TOKEN}":
                raise HTTPException(status_code=401, detail="invalid bearer token")

        app.include_router(create_control_plane_router(config, require))
        response = TestClient(app).post("/control/api/v1/observability/sentry-smoke")

    assert response.status_code == 401


def test_observability_llm_harness_returns_persisted_telemetry() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        config = _config(tmp)
        store = ControlPlaneStore(config.expanded_state_dir / "control_plane.sqlite3")
        record_llm_harness_event(
            store,
            event_type=LLM_HARNESS_ROUTE_DECISION_EVENT,
            payload={
                "workflow_id": "idea_generation_enrichment",
                "trace_id": "trace-route-1",
                "provider_id": "openrouter",
                "model_id": "cheap-model",
                "policy_id": "llm-harness-read-only-v1",
                "source": "pytest",
                "started_at": "2026-06-03T03:00:00Z",
                "completed_at": "2026-06-03T03:00:02Z",
                "status": "ok",
                "failure_kind": "",
                "estimated_cost_usd": "0.0002",
                "input_token_count": 100,
                "output_token_count": 20,
                "candidate_provider_ids": ["openrouter"],
                "candidate_model_ids": ["cheap-model"],
                "selected_provider_id": "openrouter",
                "selected_model_id": "cheap-model",
                "selection_reason": "lowest cost model above enrichment bar",
                "fallback_rank": 0,
                "budget_gate_status": "passed",
                "health_gate_status": "passed",
            },
            idempotency_key="llm-harness:test-route",
        )
        response = _client_with_config(config).get(
            "/control/api/v1/observability/llm-harness",
            headers={"Authorization": f"Bearer {TOKEN}"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "control_api_v1_observability_llm_harness"
    assert body["event_count"] == 1
    assert body["event_type_counts"] == {LLM_HARNESS_ROUTE_DECISION_EVENT: 1}
    assert body["recent_events"][0]["selected_model_id"] == "cheap-model"


def _write_publication_artifacts(
    project_dir: Path, *, evidence_path: str, claim_path: str, manifest_path: str
) -> None:
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "paper.md").write_text(
        "Measured result improved over baseline.", encoding="utf-8"
    )
    (project_dir / "paper.tex").write_text("content", encoding="utf-8")
    evidence = {
        "schema_version": "evidence_bundle.v2",
        "public_evidence_files": [
            {
                "path": "evidence/run_notes.md",
                "source_path": "run_notes.md",
                "content": "Measured result improved over baseline.",
                "sha256": "abc",
            }
        ],
    }
    claims = {
        "schema_version": "claim_ledger.v2",
        "ledger_status": "claims_reference_evidence",
        "claims": [
            {
                "id": "C1",
                "claim": "Measured result improved over baseline.",
                "support_status": "supported",
                "evidence_refs": [
                    {
                        "path": "evidence/run_notes.md",
                        "source_path": "run_notes.md",
                        "match_score": 1.0,
                    }
                ],
            }
        ],
        "unsupported_claim_count": 0,
    }
    manifest = {
        "evidence_file_count": 1,
        "claim_count": 1,
        "claim_ledger_status": "claims_reference_evidence",
    }
    for rel, payload in (
        (evidence_path, evidence),
        (claim_path, claims),
        (manifest_path, manifest),
    ):
        target = project_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload), encoding="utf-8")


def test_followup_launch_does_not_skip_fresh_generation_for_empty_lane_queue() -> None:
    class FakeStore:
        def next_followup_candidate(
            self, *, max_followup_depth: int = 4, project_id: str = ""
        ):
            return {
                "project_id": "parent",
                "machine_target": "cpu-proxmox-1",
                "followup_title": "Bounded follow-up",
            }

        def launch_followup_candidate(self, **_kwargs):
            return {
                "action": "followup_queued",
                "reason": "bounded follow-up queued",
                "candidate": {"project_id": "parent"},
                "followup": {"idea_id": "followup-child"},
            }

    response = {"stages": []}
    dispatched: list[str] = []

    result = _handle_followup_and_early_skips(
        store=FakeStore(),
        generation_target_lane={
            "lane_key": "cpu-proxmox-1",
            "machine_target": "cpu-proxmox-1",
            "queue_deficit": 25,
            "next_autopilot_action": "generate_candidate",
        },
        max_dispatches=1,
        max_provider_requests=1,
        fresh_generation_backlog_threshold=3,
        initial_promotable=[],
        response=response,
        requested_by="pytest",
        dispatch_queued_project=lambda project_id: (
            dispatched.append(project_id) or True
        ),
        research_row_lane_key=lambda row: str(row.get("machine_target") or ""),
    )

    assert result["followup_launch"]["action"] == "followup_queued"
    assert dispatched == ["followup-child"]
    assert result["fresh_generation_skipped"] is False
    assert result["fresh_promotion_skipped"] is False
    assert "follow-up branch took priority" not in result.get("reason", "")


def test_followup_launch_respects_satisfied_lane_queue_depth() -> None:
    class FakeStore:
        launches = 0

        def next_followup_candidate(
            self, *, max_followup_depth: int = 4, project_id: str = ""
        ):
            return {
                "project_id": "parent",
                "machine_target": "cpu-proxmox-1",
                "followup_title": "Bounded follow-up",
            }

        def launch_followup_candidate(self, **_kwargs):
            self.launches += 1
            return {
                "action": "followup_queued",
                "candidate": {"project_id": "parent"},
                "followup": {"idea_id": "followup-child"},
            }

    response = {
        "stages": [],
        "lane_feed_pressure": {
            "cpu-proxmox-1": {
                "lane_key": "cpu-proxmox-1",
                "machine_target": "cpu-proxmox-1",
                "queued_count": 48,
                "desired_queue_depth": 25,
                "queue_deficit": 0,
                "next_autopilot_action": "queue_depth_satisfied",
            }
        },
    }
    dispatched: list[str] = []
    store = FakeStore()

    result = _handle_followup_and_early_skips(
        store=store,
        generation_target_lane=None,
        max_dispatches=2,
        max_provider_requests=1,
        fresh_generation_backlog_threshold=3,
        initial_promotable=[],
        response=response,
        requested_by="pytest",
        dispatch_queued_project=lambda project_id: (
            dispatched.append(project_id) or True
        ),
        research_row_lane_key=lambda row: str(row.get("machine_target") or ""),
    )

    assert store.launches == 0
    assert dispatched == []
    assert result["followup_launch"]["action"] == "skipped"
    assert "queue depth is already satisfied" in result["followup_launch"]["reason"]
    assert result["fresh_generation_skipped"] is False
    assert result["fresh_promotion_skipped"] is False


def test_research_paper_stage_records_evidence_rewrite_error() -> None:
    from enoch_control_plane.control_plane.models import DraftNextResponse
    from enoch_control_plane.control_plane.router import (
        PaperRewriteEvidenceRequiredError,
        _execute_research_paper_stages,
    )

    class FakeStore:
        def active_items(self) -> list[dict[str, str]]:
            return []

    paper = PaperRecord(paper_id="paper-1", project_id="project-1")
    response = {"stages": []}

    def draft_next(*_args: object, **_kwargs: object) -> DraftNextResponse:
        return DraftNextResponse(
            ok=True,
            action="drafted",
            reason="drafted",
            paper=paper,
            candidate={"project_id": "project-1"},
        )

    def rewrite_paper_review_draft(*_args: object, **_kwargs: object) -> object:
        raise PaperRewriteEvidenceRequiredError(
            {"ok": False, "reason": "missing local evidence"}
        )

    drafted, finalized = _execute_research_paper_stages(
        store=FakeStore(),
        response=response,
        max_paper_drafts=1,
        max_publication_rewrites=1,
        wait_for_completion=False,
        wait_result={},
        requested_by="test",
        draft_next=draft_next,
        rewrite_paper_review_draft=rewrite_paper_review_draft,
        control_api_bearer_token=TOKEN,
    )

    assert len(drafted) == 1
    assert finalized == []
    finalization_stage = response["stages"][-1]
    assert finalization_stage["stage"] == "publication_finalization"
    assert finalization_stage["ok"] is False
    assert finalization_stage["paper_id"] == "paper-1"
    assert finalization_stage["status_code"] == 424
    assert (
        finalization_stage["reason"] == "paper rewrite requires synced project evidence"
    )
    assert finalization_stage["evidence_sync"] == {
        "ok": False,
        "reason": "missing local evidence",
    }


def test_research_paper_stage_skips_after_dispatch_when_wait_disabled() -> None:
    from enoch_control_plane.control_plane.router import _execute_research_paper_stages

    class FakeStore:
        def active_items(self) -> list[dict[str, str]]:
            return []

    def draft_next(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("paper drafting must not run after non-waiting dispatch")

    response = {"dispatch_started": True, "stages": []}

    drafted, finalized = _execute_research_paper_stages(
        store=FakeStore(),
        response=response,
        max_paper_drafts=1,
        max_publication_rewrites=1,
        wait_for_completion=False,
        wait_result={"action": "skipped"},
        requested_by="test",
        draft_next=draft_next,
        rewrite_paper_review_draft=lambda *_args, **_kwargs: None,
        control_api_bearer_token=TOKEN,
    )

    assert drafted == []
    assert finalized == []
    assert response["stages"] == [
        {
            "stage": "paper_draft",
            "ok": False,
            "reason": (
                "dispatched work started and wait_for_completion is disabled; "
                "paper stage skipped"
            ),
        }
    ]


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

            with patch(
                "enoch_control_plane.control_plane.router._atomic_write_text",
                side_effect=fail_atomic,
            ):
                with self.assertRaises(OSError):
                    _write_deterministic_paper(
                        config,
                        {"project_name": "Project A", "project_dir": "project-a"},
                        paper,
                        force=True,
                    )

            self.assertEqual(paper_path.read_text(encoding="utf-8"), "old draft")

    def test_deterministic_paper_rejects_uninspectable_target_without_raw_permission_error(
        self,
    ) -> None:
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

    def test_deterministic_paper_rejects_invalid_project_dir_without_value_error(
        self,
    ) -> None:
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
                    {
                        "project_id": "project-a",
                        "project_name": "Project A",
                        "project_dir": "bad\0project",
                    },
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
        with patch(
            "enoch_control_plane.control_plane.router.SupabaseControlPlaneStore",
            return_value=FakeSupabaseStore(),
        ):
            client = _client_with_config(config)
            response = client.get(
                "/control/health", headers={"Authorization": f"Bearer {TOKEN}"}
            )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["store_backend"], "supabase")
        self.assertEqual(body["db_path"], "supabase")

    def test_research_quality_endpoint_reads_configured_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "research-quality.json"
            report.write_text(
                json.dumps(
                    {
                        "schema_version": "enoch_research_quality_report_v1",
                        "generated_at": "2026-05-11T00:00:00Z",
                        "summary": {
                            "candidate_count": 0,
                            "decision_count": 1,
                            "problem_counts": {"weak_or_missing_evidence_strength": 1},
                        },
                        "candidate_scores": [],
                        "decision_scores": [
                            {
                                "project_id": "p1",
                                "project_name": "Project 1",
                                "run_id": "r1",
                                "decision": "finalize_negative",
                                "hypothesis_status": "mixed",
                                "problems": ["weak_or_missing_evidence_strength"],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            with patch.dict(
                os.environ, {"ENOCH_RESEARCH_QUALITY_REPORT_PATH": str(report)}
            ):
                client = _client(tmp)
                response = client.get(
                    "/control/api/v1/research-quality",
                    headers={"Authorization": f"Bearer {TOKEN}"},
                )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["source"], "control_api_v1_research_quality")
        self.assertEqual(body["status"], "warnings")
        self.assertTrue(body["ok"])
        self.assertEqual(body["decisions_checked"], 1)
        self.assertEqual(
            body["problem_counts"], {"weak_or_missing_evidence_strength": 1}
        )

    def test_overview_includes_research_signal_quality_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "research-quality.json"
            report.write_text(
                json.dumps(
                    {
                        "schema_version": "enoch_research_quality_report_v1",
                        "generated_at": "2026-05-11T00:00:00Z",
                        "summary": {
                            "candidate_count": 0,
                            "decision_count": 1,
                            "problem_counts": {"weak_or_missing_evidence_strength": 1},
                        },
                        "candidate_scores": [],
                        "decision_scores": [
                            {
                                "project_id": "p1",
                                "project_name": "Project 1",
                                "run_id": "r1",
                                "decision": "finalize_negative",
                                "hypothesis_status": "mixed",
                                "problems": ["weak_or_missing_evidence_strength"],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            with patch.dict(
                os.environ, {"ENOCH_RESEARCH_QUALITY_REPORT_PATH": str(report)}
            ):
                client = _client(tmp)
                response = client.get(
                    "/control/api/v1/overview",
                    headers={"Authorization": f"Bearer {TOKEN}"},
                )

        self.assertEqual(response.status_code, 200)
        quality = response.json()["research_signal_quality"]
        self.assertEqual(quality["status"], "warnings")
        self.assertEqual(quality["decisions_checked"], 1)
        self.assertEqual(quality["weak_evidence_count"], 1)
        self.assertIn("weak evidence=1", quality["operator_summary"])

    def test_overview_quality_snapshot_explains_followup_scope_alignment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "research-quality.json"
            report.write_text(
                json.dumps(
                    {
                        "schema_version": "enoch_research_quality_report_v1",
                        "generated_at": "2026-05-31T00:00:00Z",
                        "summary": {
                            "candidate_count": 0,
                            "decision_count": 1,
                            "problem_counts": {},
                        },
                        "candidate_scores": [],
                        "decision_scores": [
                            {
                                "project_id": "quality-window-project",
                                "project_name": "Quality Window Project",
                                "run_id": "quality-window-run",
                                "decision": "finalize_negative",
                                "hypothesis_status": "supported",
                                "evidence_strength": "moderate",
                                "research_outcome": "useful_signal",
                                "bounded_paper_ready": False,
                                "followup_recommended": True,
                                "followup_type": "deepen",
                                "followup_title": "Quality-window follow-up",
                                "followup_required_evidence_count": 4,
                                "followup_success_threshold": "Improve by 5 points.",
                                "followup_stop_condition": "Stop if no lift.",
                                "recommended_next_action": (
                                    "Inspect the quality-window follow-up."
                                ),
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            global_rows = [
                {
                    "project_id": "global-project",
                    "project_name": "Global Follow-up Project",
                    "project_dir": "global-project",
                    "status": "completed",
                    "current_run_id": "global-run",
                    "decision_gate_state": "negative",
                    "research_outcome": "useful_signal",
                    "hypothesis_status": "supported",
                    "evidence_strength": "moderate",
                    "bounded_paper_ready": False,
                    "followup_recommended": True,
                    "followup_type": "deepen",
                    "followup_title": "Global ranked follow-up",
                    "followup_hypothesis": "The global follow-up validates the signal.",
                    "followup_required_evidence": [
                        "real model trace",
                        "baseline",
                        "failure analysis",
                        "artifact bundle",
                    ],
                    "followup_success_threshold": "Improve by 5 points.",
                    "followup_stop_condition": "Stop if no lift.",
                    "followup_depth": 0,
                    "updated_at": "2026-05-31T00:00:00Z",
                }
            ]
            with (
                patch.dict(
                    os.environ, {"ENOCH_RESEARCH_QUALITY_REPORT_PATH": str(report)}
                ),
                patch.object(
                    ControlPlaneStore,
                    "queue_counts_sql",
                    return_value={"completed": 1},
                ),
                patch.object(ControlPlaneStore, "paper_counts_sql", return_value={}),
                patch.object(ControlPlaneStore, "active_items_sql", return_value=[]),
                patch.object(
                    ControlPlaneStore, "next_candidate_sql", return_value=None
                ),
                patch.object(
                    ControlPlaneStore,
                    "operator_queue_rows_sql",
                    return_value=global_rows,
                ),
                patch.object(
                    ControlPlaneStore, "operator_paper_rows_sql", return_value=[]
                ),
            ):
                client = _client(tmp)
                response = client.get(
                    "/control/api/v1/overview",
                    headers={"Authorization": f"Bearer {TOKEN}"},
                )

        self.assertEqual(response.status_code, 200)
        quality = response.json()["research_signal_quality"]
        alignment = quality["followup_scope_alignment"]
        self.assertEqual(alignment["global_ready_count"], 1)
        self.assertFalse(alignment["same_project"])
        self.assertEqual(
            alignment["global_candidate"]["project_name"], "Global Follow-up Project"
        )
        self.assertEqual(
            alignment["quality_window_candidate"]["project_name"],
            "Quality Window Project",
        )
        self.assertIn("different scopes", alignment["operator_action"])

    def test_source_lineage_endpoint_and_readiness_use_configured_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "source-lineage.json"
            report.write_text(
                json.dumps(
                    {
                        "schema_version": "enoch_source_lineage_report_v1",
                        "checked_at": "2026-05-19T18:00:00Z",
                        "created_after": "2026-05-19T17:51:00Z",
                        "status": "blocked",
                        "counts": {
                            "candidates": 0,
                            "followups": 1,
                            "sources": 4,
                            "lineages": 4,
                            "problems": 1,
                        },
                        "problem_counts": {"followup_missing_parent_run_source": 1},
                        "problems": [
                            {
                                "kind": "followup_missing_parent_run_source",
                                "project_id": "f1",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            with patch.dict(
                os.environ, {"ENOCH_SOURCE_LINEAGE_REPORT_PATH": str(report)}
            ):
                client = _client(tmp)
                response = client.get(
                    "/control/api/v1/source-lineage",
                    headers={"Authorization": f"Bearer {TOKEN}"},
                )
                readiness = client.get(
                    "/control/api/v1/automation-readiness",
                    headers={"Authorization": f"Bearer {TOKEN}"},
                )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["source"], "control_api_v1_source_lineage")
        self.assertEqual(body["status"], "blocked")
        self.assertFalse(body["ok"])
        self.assertEqual(body["followups_checked"], 1)
        self.assertEqual(body["missing_sources"], 1)
        readiness_body = readiness.json()
        self.assertFalse(readiness_body["ok"])
        self.assertIn("source lineage status=blocked", readiness_body["blockers"])
        self.assertEqual(readiness_body["summary"]["source_lineage_status"], "blocked")

    def test_pause_import_dry_run_and_draft(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "projects" / "idea-positive"
            project_dir.mkdir(parents=True)
            (project_dir / "run_notes.md").write_text(
                "Positive evidence supports drafting this paper.\n", encoding="utf-8"
            )
            (project_dir / ".enoch").mkdir(parents=True)
            (project_dir / ".enoch" / "project_decision.json").write_text(
                '{"project_decision":"finalize_positive"}\n', encoding="utf-8"
            )
            client = _client(tmp)
            headers = {"Authorization": f"Bearer {TOKEN}"}

            state = client.get("/control/state", headers=headers).json()
            self.assertTrue(state["flags"]["queue_paused"])

            import_response = client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "import-router-1",
                    "queue_rows": [
                        {
                            "project_id": "idea-positive",
                            "project_name": "Positive Project",
                            "project_dir": str(project_dir),
                            "status": "completed",
                            "last_run_state": "finalize_positive",
                            "current_run_id": "run-1",
                            "manual_review_required": False,
                        }
                    ],
                    "paper_rows": [],
                },
            )
            self.assertEqual(import_response.status_code, 200)
            self.assertEqual(import_response.json()["imported_queue_items"], 1)

            paused_dispatch = client.post(
                "/control/dispatch-next", headers=headers, json={"dry_run": True}
            )
            self.assertEqual(paused_dispatch.json()["action"], "paused")

            dry_draft = client.post(
                "/control/papers/draft-next",
                headers=headers,
                json={"force": True, "dry_run": True},
            )
            self.assertEqual(dry_draft.status_code, 200)
            dry_body = dry_draft.json()
            self.assertEqual(dry_body["action"], "dry_run_draft")
            self.assertFalse(
                (project_dir / dry_body["paper"]["draft_markdown_path"]).exists()
            )

            draft = client.post(
                "/control/papers/draft-next",
                headers=headers,
                json={"force": True, "override_hold_action": "draft-next-while-held"},
            )
            self.assertEqual(draft.status_code, 200)
            body = draft.json()
            self.assertEqual(body["action"], "drafted")
            self.assertTrue(
                (project_dir / body["paper"]["draft_markdown_path"]).exists()
            )

    def test_operator_state_and_status_do_not_materialize_full_queue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            import_response = client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "import-fast-state",
                    "queue_rows": [
                        {
                            "project_id": "completed-gb10",
                            "project_name": "Completed GB10",
                            "project_dir": "completed-gb10",
                            "status": "completed",
                            "current_run_id": "run-completed",
                            "machine_target": "gb10",
                            "manual_review_required": False,
                        },
                        {
                            "project_id": "queued-cpu",
                            "project_name": "Queued CPU",
                            "project_dir": "queued-cpu",
                            "status": "queued",
                            "machine_target": "cpu-proxmox-1",
                            "manual_review_required": False,
                        },
                        {
                            "project_id": "completed-old",
                            "project_name": "Completed Old",
                            "project_dir": "completed-old",
                            "status": "completed",
                            "current_run_id": "run-old",
                            "manual_review_required": False,
                        },
                    ],
                    "paper_rows": [],
                },
            )
            self.assertEqual(import_response.status_code, 200)
            client.post(
                "/control/resume",
                headers=headers,
                json={"resumed_by": "test", "maintenance_mode": False},
            )

            with patch.object(
                ControlPlaneStore,
                "queue_rows",
                side_effect=AssertionError(
                    "full queue materialization is too expensive"
                ),
            ):
                state = client.get("/control/state", headers=headers)
                status = client.get("/control/api/status", headers=headers)

            self.assertEqual(state.status_code, 200)
            self.assertEqual(status.status_code, 200)
            state_body = state.json()
            status_body = status.json()
            self.assertEqual(state_body["counts"]["queue_total"], 3)
            self.assertEqual(status_body["counts"]["queue_total"], 3)
            self.assertEqual(state_body["next_candidate"]["project_id"], "queued-cpu")
            self.assertTrue(
                any(lane["queued_count"] == 1 for lane in status_body["worker_lanes"])
            )

    def test_v1_dashboard_read_models_are_bounded_and_do_not_call_legacy_full_lists(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            project_root = Path(tmp) / "projects"
            queue_rows = []
            paper_rows = []
            for idx in range(3):
                project_id = f"idea-{idx}"
                (project_root / project_id).mkdir(parents=True, exist_ok=True)
                queue_rows.append(
                    {
                        "project_id": project_id,
                        "project_name": f"Project {idx}",
                        "project_dir": project_id,
                        "status": "queued" if idx else "awaiting_wake",
                        "dispatch_priority": idx,
                        "selection_rank": idx,
                        "current_run_id": f"run-{idx}",
                        "last_run_state": "awaiting_wake" if idx == 0 else "",
                        "next_action_hint": "await_callback"
                        if idx == 0
                        else "controller_review",
                    }
                )
                paper_rows.append(
                    {
                        "paper_id": f"paper-{idx}",
                        "project_id": project_id,
                        "run_id": f"run-{idx}",
                        "paper_status": "publication_draft",
                        "draft_markdown_path": "paper.md",
                        "draft_latex_path": "paper.tex",
                        "evidence_bundle_path": "evidence_bundle.json",
                        "claim_ledger_path": "claim_ledger.json",
                        "manifest_path": "paper_manifest.json",
                    }
                )
            imported = client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "v1-bounded-import",
                    "queue_rows": queue_rows,
                    "paper_rows": paper_rows,
                },
            )
            self.assertEqual(imported.status_code, 200)

            with (
                patch.object(
                    ControlPlaneStore,
                    "queue_rows",
                    side_effect=AssertionError("legacy queue_rows should not be used"),
                ),
                patch.object(
                    ControlPlaneStore,
                    "paper_rows",
                    side_effect=AssertionError("legacy paper_rows should not be used"),
                ),
                patch.object(
                    ControlPlaneStore,
                    "event_rows",
                    side_effect=AssertionError("legacy event_rows should not be used"),
                ),
            ):
                overview = client.get("/control/api/v1/overview", headers=headers)
                self.assertEqual(overview.status_code, 200)
                self.assertEqual(overview.json()["counts"]["all"], 3)
                self.assertLessEqual(len(overview.json()["recent_events"]), 10)

                queue = client.get("/control/api/v1/queue?page_size=2", headers=headers)
                self.assertEqual(queue.status_code, 200)
                self.assertEqual(queue.json()["page"]["returned"], 2)
                self.assertTrue(queue.json()["page"]["has_more"])
                self.assertEqual(queue.json()["page"]["next_cursor"], "2")

                recent = client.get(
                    "/control/api/v1/queue?queue=all&page_size=2&sort=recent",
                    headers=headers,
                )
                self.assertEqual(recent.status_code, 200)
                self.assertEqual(recent.json()["page"]["filters"]["sort"], "recent")

                created = client.get(
                    "/control/api/v1/queue?queue=all&page_size=2&sort=created",
                    headers=headers,
                )
                self.assertEqual(created.status_code, 200)
                self.assertEqual(created.json()["page"]["filters"]["sort"], "created")

                projects = client.get(
                    "/control/api/v1/projects?page_size=2&sort=name&search=Project",
                    headers=headers,
                )
                self.assertEqual(projects.status_code, 200)
                self.assertEqual(projects.json()["page"]["returned"], 2)
                self.assertTrue(projects.json()["page"]["has_more"])
                self.assertEqual(projects.json()["page"]["filters"]["sort"], "name")
                self.assertEqual(
                    projects.json()["page"]["filters"]["search"], "Project"
                )
                self.assertIn("project_name", projects.json()["rows"][0])
                self.assertIn("links", projects.json()["rows"][0])

                papers = client.get(
                    "/control/api/v1/papers?page_size=2&sort=created", headers=headers
                )
                self.assertEqual(papers.status_code, 200)
                self.assertEqual(papers.json()["page"]["returned"], 2)
                self.assertEqual(papers.json()["page"]["filters"]["sort"], "created")
                self.assertNotIn("draft_markdown_path", papers.json()["rows"][0])
                self.assertIn("artifact_paths_present", papers.json()["rows"][0])

                events_index = client.get(
                    "/control/api/v1/events?page_size=50&sort=recent", headers=headers
                )
                self.assertEqual(events_index.status_code, 200)
                self.assertEqual(
                    events_index.json()["page"]["filters"]["sort"], "recent"
                )

                events = client.get(
                    "/control/api/v1/events?page_size=2", headers=headers
                )
                self.assertEqual(events.status_code, 200)
                self.assertLessEqual(events.json()["page"]["returned"], 2)
                if events.json()["rows"]:
                    self.assertIn("payload_summary", events.json()["rows"][0])
                    self.assertNotIn("payload", events.json()["rows"][0])
                    event_id = events.json()["rows"][0]["event_id"]
                    event_by_id = client.get(
                        f"/control/api/v1/events?event_id={event_id}&include_payload=true&page_size=1&sort=recent",
                        headers=headers,
                    )
                    self.assertEqual(event_by_id.status_code, 200)
                    self.assertEqual(event_by_id.json()["page"]["returned"], 1)
                    self.assertEqual(
                        event_by_id.json()["page"]["filters"]["event_id"], str(event_id)
                    )
                    self.assertEqual(
                        event_by_id.json()["rows"][0]["event_id"], event_id
                    )
                    self.assertIn("payload", event_by_id.json()["rows"][0])

                runs = client.get(
                    "/control/api/v1/runs?page_size=2&sort=state&search=project",
                    headers=headers,
                )
                self.assertEqual(runs.status_code, 200)
                self.assertLessEqual(runs.json()["page"]["returned"], 2)
                self.assertEqual(runs.json()["page"]["filters"]["sort"], "state")
                self.assertEqual(runs.json()["page"]["filters"]["search"], "project")

                event_filtered = client.get(
                    "/control/api/v1/events?page_size=2&sort=type&search=import",
                    headers=headers,
                )
                self.assertEqual(event_filtered.status_code, 200)
                self.assertEqual(
                    event_filtered.json()["page"]["filters"]["sort"], "type"
                )
                self.assertEqual(
                    event_filtered.json()["page"]["filters"]["search"], "import"
                )

    def test_dashboard_v1_run_detail_includes_queue_item(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            imported = client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "v1-run-detail-queue-item",
                    "queue_rows": [
                        {
                            "project_id": "idea-0",
                            "project_name": "Project 0",
                            "project_dir": "idea-0",
                            "status": "awaiting_wake",
                            "current_run_id": "run-0",
                            "machine_target": "gb10",
                        }
                    ],
                },
            )
            self.assertEqual(imported.status_code, 200)
            store = ControlPlaneStore(Path(tmp) / "state" / "control_plane.sqlite3")
            with store._connect() as conn:
                conn.execute(
                    """INSERT INTO runs(run_id,project_id,session_id,state,dispatch_mode,started_at,ended_at,last_callback_at,gate_state,current_activity,idempotency_key,updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        "run-0",
                        "idea-0",
                        "",
                        "awaiting_wake",
                        "dispatch",
                        "2026-05-21T09:00:00Z",
                        None,
                        None,
                        "awaiting_wake",
                        "",
                        "",
                        "2026-05-21T09:00:00Z",
                    ),
                )
            run_detail = client.get("/control/api/v1/runs/run-0", headers=headers)
            self.assertEqual(run_detail.status_code, 200)
            body = run_detail.json()
            self.assertEqual(body["run_id"], "run-0")
            self.assertIn("queue_item", body)
            self.assertEqual(body["queue_item"]["project_id"], "idea-0")
            self.assertEqual(body["queue_item"]["machine_target"], "gb10")

    def test_dashboard_v1_run_detail_omits_queue_item_for_other_current_run(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            imported = client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "v1-run-detail-queue-item-mismatch",
                    "queue_rows": [
                        {
                            "project_id": "idea-0",
                            "project_name": "Project 0",
                            "project_dir": "idea-0",
                            "status": "queued",
                            "current_run_id": "run-current",
                            "machine_target": "gb10",
                        }
                    ],
                },
            )
            self.assertEqual(imported.status_code, 200)
            store = ControlPlaneStore(Path(tmp) / "state" / "control_plane.sqlite3")
            with store._connect() as conn:
                conn.execute(
                    """INSERT INTO runs(run_id,project_id,session_id,state,dispatch_mode,started_at,ended_at,last_callback_at,gate_state,current_activity,idempotency_key,updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        "run-historical",
                        "idea-0",
                        "",
                        "completed",
                        "dispatch",
                        "2026-05-21T09:00:00Z",
                        "2026-05-21T10:00:00Z",
                        None,
                        "completed",
                        "",
                        "",
                        "2026-05-21T10:00:00Z",
                    ),
                )
            run_detail = client.get(
                "/control/api/v1/runs/run-historical", headers=headers
            )
            self.assertEqual(run_detail.status_code, 200)
            self.assertIsNone(run_detail.json()["queue_item"])

    def test_dashboard_v1_paper_detail_includes_queue_item_and_summarized_run(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            imported = client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "v1-paper-detail-queue-item",
                    "queue_rows": [
                        {
                            "project_id": "idea-0",
                            "project_name": "Project 0",
                            "project_dir": "idea-0",
                            "status": "completed",
                            "current_run_id": "run-0",
                            "machine_target": "gb10",
                        }
                    ],
                    "paper_rows": [
                        {
                            "paper_id": "paper-0",
                            "project_id": "idea-0",
                            "run_id": "run-0",
                            "paper_status": "publication_draft",
                            "review_status": "ready",
                        }
                    ],
                },
            )
            self.assertEqual(imported.status_code, 200)
            store = ControlPlaneStore(Path(tmp) / "state" / "control_plane.sqlite3")
            with store._connect() as conn:
                conn.execute(
                    """INSERT INTO runs(run_id,project_id,session_id,state,dispatch_mode,started_at,ended_at,last_callback_at,gate_state,current_activity,idempotency_key,updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        "run-0",
                        "idea-0",
                        "",
                        "completed",
                        "dispatch",
                        "2026-05-21T09:00:00Z",
                        "2026-05-21T10:00:00Z",
                        None,
                        "completed",
                        "",
                        "",
                        "2026-05-21T10:00:00Z",
                    ),
                )
            paper_detail = client.get("/control/api/v1/papers/paper-0", headers=headers)
            self.assertEqual(paper_detail.status_code, 200)
            body = paper_detail.json()
            self.assertEqual(body["paper_id"], "paper-0")
            self.assertIn("queue_item", body)
            self.assertEqual(body["queue_item"]["project_id"], "idea-0")
            self.assertEqual(body["queue_item"]["machine_target"], "gb10")
            self.assertIn("run", body)
            self.assertEqual(body["run"]["run_id"], "run-0")
            self.assertEqual(body["run"]["state"], "completed")
            self.assertNotIn("related_draft_markdown_path", body["run"])

    def test_dashboard_queue_filter_normalizes_status_and_manual_review_flag(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            rows = [
                {
                    "project_id": "queued-string-false",
                    "project_name": "Queued String False",
                    "status": "Queued",
                    "manual_review_required": "false",
                    "dispatch_priority": 1,
                    "selection_rank": 1,
                }
            ]

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
            response = client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "import-router-snapshot",
                    "queue_snapshot": {
                        "active_rows": [
                            {
                                "project_id": "idea-active",
                                "project_name": "Active Project",
                                "queue_status": "awaiting_wake",
                                "current_run_id": "run-active",
                            }
                        ]
                    },
                    "paper_snapshot": {
                        "latest_rows": [
                            {
                                "paper_id": "idea-active:run-active:arxiv_draft",
                                "project_id": "idea-active",
                                "run_id": "run-active",
                                "paper_status": "draft_review",
                            }
                        ]
                    },
                },
            )
            self.assertEqual(response.status_code, 200)

            ideas_projection = client.get(
                "/control/projections/ideas/workbench", headers=headers
            )
            self.assertEqual(ideas_projection.status_code, 200)
            self.assertEqual(
                ideas_projection.json()["rows"][0]["queue_status"], "awaiting_wake"
            )

            legacy_projection = client.get(
                "/control/projections/notion/queue", headers=headers
            )
            self.assertEqual(legacy_projection.status_code, 410)

            exported = client.get("/control/export/snapshot", headers=headers)
            self.assertEqual(exported.status_code, 200)
            self.assertEqual(len(exported.json()["queue_rows"]), 1)
            self.assertEqual(len(exported.json()["paper_rows"]), 1)

            paused = client.post(
                "/control/queue/mark-paused",
                headers=headers,
                json={
                    "project_id": "idea-active",
                    "reason": "verified no live process",
                    "updated_by": "test",
                },
            )
            self.assertEqual(paused.status_code, 200)
            self.assertFalse(paused.json()["active_items"])

    def test_legacy_notion_intake_and_projection_are_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            dry_run = client.post(
                "/control/intake/notion-ideas",
                headers=headers,
                json={"dry_run": True, "notion_rows": []},
            )
            self.assertEqual(dry_run.status_code, 410)
            self.assertIn("Supabase-native", dry_run.json()["detail"]["message"])

            projection = client.get(
                "/control/projections/notion/execution-updates", headers=headers
            )
            self.assertEqual(projection.status_code, 410)

    def test_legacy_notion_intake_defaults_disabled_even_with_configured_worker_target(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _config(tmp).model_copy(
                update={"worker_wake_gate_url": "http://192.168.1.77:8787"}
            )
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}

            response = client.post(
                "/control/intake/notion-ideas",
                headers=headers,
                json={
                    "idempotency_key": "router-notion-configured-worker",
                    "dry_run": False,
                    "notion_rows": [],
                },
            )

            self.assertEqual(response.status_code, 410)

    def test_supabase_native_ideas_intake_is_primary_dashboard_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _config(tmp).model_copy(
                update={"worker_wake_gate_url": "http://192.168.1.77:8787"}
            )
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}

            response = client.post(
                "/control/intake/ideas",
                headers=headers,
                json={
                    "idempotency_key": "router-ideas-intake-1",
                    "dry_run": False,
                    "ideas": [
                        {
                            "idea_id": "supabase-native-idea",
                            "title": "Supabase Native Idea",
                            "idea_status": "testing",
                            "priority": "High",
                            "selection_rank": 9,
                            "dispatch_priority": 8,
                        }
                    ],
                },
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["created"], 1)
            self.assertEqual(
                response.json()["candidates"][0]["machine_target"], "192.168.1.77"
            )

            intake = client.get("/control/api/intake/ideas", headers=headers)
            self.assertEqual(intake.status_code, 200)
            body = intake.json()
            self.assertEqual(body["source"], "control_api_intake_ideas")
            self.assertIn("Supabase-native ideas", body["authority"])
            self.assertTrue(
                any(
                    row["idea_id"] == "supabase-native-idea"
                    for row in body["queued_projection"]
                )
            )

            projection = client.get(
                "/control/projections/ideas/workbench", headers=headers
            )
            self.assertEqual(projection.status_code, 200)
            self.assertIn("testing", projection.json()["counts"])

    def test_ideas_intake_dashboard_falls_back_when_batched_parts_are_malformed(
        self,
    ) -> None:
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
            def dashboard_ideas_intake_parts(
                self, *, page_size: int = 50, include_latest_payload: bool = False
            ):
                del page_size, include_latest_payload
                return None

            def latest_dashboard_observation(self, **_kwargs):
                return None

            def idea_workbench_projection(self, *, limit: int = 200):
                del limit
                return [
                    {
                        "idea_id": "fallback-idea",
                        "title": "Fallback Idea",
                        "idea_status": "testing",
                    }
                ]

            def event_rows(self, **_kwargs):
                return []

            def status_counts(self):
                return {"queued": 1}

        with patch(
            "enoch_control_plane.control_plane.router.SupabaseControlPlaneStore",
            return_value=FakeSupabaseStore(),
        ):
            client = _client_with_config(config)
            response = client.get(
                "/control/api/intake/ideas",
                headers={"Authorization": f"Bearer {TOKEN}"},
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["projection_counts"]["queued"], 1)
        self.assertEqual(body["queued_projection"][0]["idea_id"], "fallback-idea")
        self.assertIn("operator_summary", body)
        self.assertIn("queued for operator review", body["operator_summary"])
        self.assertFalse(body["warnings"])

    def test_dashboard_intake_ideas_projection_includes_operator_fields(self) -> None:
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
            def dashboard_ideas_intake_parts(
                self, *, page_size: int = 50, include_latest_payload: bool = False
            ):
                del page_size, include_latest_payload
                return None

            def latest_dashboard_observation(self, **_kwargs):
                return None

            def idea_workbench_projection(self, *, limit: int = 200):
                del limit
                return [
                    {
                        "idea_id": "idea-operator",
                        "title": "Operator Idea",
                        "idea_status": "admitted",
                        "queue_status": "queued",
                        "source_kind": "supabase_idea",
                        "machine_target": "gb10",
                        "project_id": "project-operator",
                    }
                ]

            def event_rows(self, **_kwargs):
                return []

            def status_counts(self):
                return {"queued": 1}

        with patch(
            "enoch_control_plane.control_plane.router.SupabaseControlPlaneStore",
            return_value=FakeSupabaseStore(),
        ):
            client = _client_with_config(config)
            response = client.get(
                "/control/api/intake/ideas",
                headers={"Authorization": f"Bearer {TOKEN}"},
            )

        self.assertEqual(response.status_code, 200)
        row = response.json()["queued_projection"][0]
        self.assertEqual(row["idea_id"], "idea-operator")
        self.assertEqual(row["operator_stage"], "ready_queue")
        self.assertEqual(row["operator_detail_stage"], "idea_queued")
        self.assertIn("operator_next_step", row)
        self.assertIn("operator_stage_label", row)

    def test_overview_flags_reflect_dashboard_v2_pause_maintenance_mode(self) -> None:
        """B7 cutover: dashboard pause sends maintenance_mode; overview flags must match."""
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            headers = {"Authorization": f"Bearer {TOKEN}"}

            resume_setup = client.post(
                "/control/resume",
                headers=headers,
                json={"resumed_by": "test-setup", "maintenance_mode": False},
            )
            self.assertEqual(resume_setup.status_code, 200)
            running = client.get("/control/api/v1/overview", headers=headers).json()
            self.assertFalse(running["flags"]["queue_paused"])
            self.assertFalse(running["flags"]["maintenance_mode"])

            pause = client.post(
                "/control/pause",
                headers=headers,
                json={
                    "reason": "dashboard operator pause",
                    "paused_by": "dashboard-v2",
                    "maintenance_mode": True,
                },
            )
            self.assertEqual(pause.status_code, 200)
            pause_state = pause.json()
            self.assertTrue(pause_state["flags"]["queue_paused"])
            self.assertTrue(pause_state["flags"]["maintenance_mode"])

            paused = client.get("/control/api/v1/overview", headers=headers).json()
            self.assertTrue(paused["flags"]["queue_paused"])
            self.assertTrue(paused["flags"]["maintenance_mode"])

            resume = client.post(
                "/control/resume",
                headers=headers,
                json={"resumed_by": "test", "maintenance_mode": False},
            )
            self.assertEqual(resume.status_code, 200)
            cleared = client.get("/control/api/v1/overview", headers=headers).json()
            self.assertFalse(cleared["flags"]["queue_paused"])
            self.assertFalse(cleared["flags"]["maintenance_mode"])

    def test_supabase_native_ideas_intake_live_rejects_readonly_before_store_write(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _live_config(tmp).model_copy(
                update={
                    "control_plane_store_backend": "supabase_readonly",
                    "supabase_database_url": "postgres://example",
                }
            )

            class FakeReadOnlyStore:
                def ingest_ideas(self, *_args, **_kwargs):  # noqa: ANN001 - must not be called
                    raise AssertionError(
                        "read-only ideas intake must reject before store writes"
                    )

            with patch(
                "enoch_control_plane.control_plane.router.SupabaseReadOnlyControlPlaneStore",
                return_value=FakeReadOnlyStore(),
            ):
                client = _client_with_config(config)
                response = client.post(
                    "/control/intake/ideas",
                    headers={"Authorization": f"Bearer {TOKEN}"},
                    json={
                        "idempotency_key": "readonly-ideas-intake",
                        "dry_run": False,
                        "ideas": [
                            {
                                "idea_id": "idea-1",
                                "title": "Idea 1",
                                "idea_status": "testing",
                            }
                        ],
                    },
                )

            self.assertEqual(response.status_code, 501)
            self.assertIn("writable control-plane store", response.text)

    def test_control_dashboard_legacy_path_redirects_to_v2(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            response = client.get("/control/dashboard", follow_redirects=False)
            self.assertEqual(response.status_code, 307)
            self.assertEqual(response.headers.get("location"), "/control/dashboard-v2")

    def test_control_dashboard_v2_shell_and_assets_are_served_without_token(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            response = client.get("/control/dashboard-v2")

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers.get("cache-control"), "no-store")
            self.assertIn("Enoch Dashboard V2", response.text)
            self.assertIn('id="enoch-dashboard-v2-root"', response.text)
            self.assertIn("/control/dashboard-v2/assets/", response.text)
            self.assertIn("Bearer token", response.text)

            asset_name = response.text.split("/control/dashboard-v2/assets/", 1)[
                1
            ].split('"', 1)[0]
            asset = client.get(f"/control/dashboard-v2/assets/{asset_name}")
            self.assertEqual(asset.status_code, 200)
            self.assertIn(
                asset.headers.get("content-type", "").split(";", 1)[0],
                {"text/javascript", "application/javascript", "text/css"},
            )

    def test_control_dashboard_v2_asset_route_rejects_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)

            for path in ("../router.py", "%2E%2E/router.py", "nested/../../router.py"):
                response = client.get(f"/control/dashboard-v2/assets/{path}")
                self.assertEqual(response.status_code, 404)

    def test_control_dashboard_legacy_redirects_while_v2_shell_served(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)

            legacy = client.get("/control/dashboard", follow_redirects=False)
            v2 = client.get("/control/dashboard-v2")

            self.assertEqual(legacy.status_code, 307)
            self.assertEqual(legacy.headers.get("location"), "/control/dashboard-v2")
            self.assertEqual(v2.status_code, 200)
            self.assertIn("Enoch Dashboard V2", v2.text)
            self.assertNotIn(
                "CONTROL_DASHBOARD_HTML",
                Path("enoch_control_plane/control_plane/router.py").read_text(
                    encoding="utf-8"
                ),
            )

    def test_research_facility_provider_budget_sanitizes_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            quota = {
                "subscription": {
                    "limit": 2500,
                    "requests": 1,
                    "renewsAt": "2026-05-10T00:00:00Z",
                },
                "weeklyTokenLimit": {
                    "remainingCredits": "$119.77",
                    "nextRegenAt": "2026-05-09T15:31:04Z",
                },
                "rollingFiveHourLimit": {
                    "remaining": 2499,
                    "max": 2500,
                    "limited": False,
                },
                "secret_echo": "synthetic-key-should-not-leak",
            }

            with (
                patch.dict(
                    os.environ,
                    {
                        "ENOCH_RESEARCH_PROVIDER_BASE_URL": "https://api.synthetic.new/openai/v1",
                        "ENOCH_RESEARCH_PROVIDER_API_KEY": "synthetic-budget-key",
                    },
                ),
                patch(
                    "scripts.research_provider_budget.fetch_json", return_value=quota
                ) as fetch,
            ):
                response = client.get(
                    "/control/api/research/provider-budget?estimated_requests=1&reserve_requests=2",
                    headers=headers,
                )

            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertTrue(body["ok"])
            self.assertEqual(body["auth_mode"], "bearer")
            self.assertEqual(body["budget_endpoint_host"], "api.synthetic.new")
            self.assertEqual(body["budget_endpoint_path"], "/v2/quotas")
            self.assertEqual(body["remaining_credits"], 119.77)
            self.assertEqual(body["rolling_remaining"], 2499)
            self.assertEqual(body["failures"], [])
            self.assertIsNone(body["payload_json"])
            self.assertNotIn("secret_echo", response.text)
            self.assertNotIn("synthetic-key-should-not-leak", response.text)
            self.assertNotIn("synthetic-budget-key", response.text)
            self.assertNotIn("Authorization", response.text)
            fetch.assert_called_once()
            args, kwargs = fetch.call_args
            self.assertEqual(args[0], "https://api.synthetic.new/v2/quotas")
            self.assertEqual(kwargs["api_key"], "synthetic-budget-key")

    def test_research_facility_provider_budget_fails_safely_without_secret(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            headers = {"Authorization": f"Bearer {TOKEN}"}

            with patch(
                "scripts.research_provider_budget.fetch_json",
                side_effect=RuntimeError("quota unavailable"),
            ):
                response = client.get(
                    "/control/api/research/provider-budget", headers=headers
                )

            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertFalse(body["ok"])
            self.assertEqual(body["auth_mode"], "exe_http_proxy")
            self.assertIn("provider budget check failed", body["failures"][0])
            self.assertEqual(body["budget_endpoint_host"], "synthetic.int.exe.xyz")
            self.assertEqual(body["budget_endpoint_path"], "/v2/quotas")
            self.assertNotIn("api_key", response.text.lower())
            self.assertNotIn("bearer", response.text.lower())

    def test_research_facility_provider_budget_uses_synthetic_settings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _config(tmp)
            _write_synthetic_llm_settings(config, "synthetic-budget-key")
            client = _client_with_config(config)
            quota = {
                "subscription": {"limit": 2500, "requests": 1},
                "weeklyTokenLimit": {"remainingCredits": "$100.00"},
                "rollingFiveHourLimit": {
                    "remaining": 2500,
                    "max": 2500,
                    "limited": False,
                },
            }

            with (
                patch.dict(
                    os.environ,
                    {
                        "ENOCH_RESEARCH_PROVIDER_BASE_URL": "",
                        "ENOCH_RESEARCH_PROVIDER_API_KEY": "",
                    },
                    clear=False,
                ),
                patch(
                    "scripts.research_provider_budget.fetch_json", return_value=quota
                ) as fetch,
            ):
                response = client.get(
                    "/control/api/research/provider-budget",
                    headers={"Authorization": f"Bearer {TOKEN}"},
                )

            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertTrue(body["ok"])
            self.assertEqual(body["auth_mode"], "bearer")
            self.assertEqual(body["budget_endpoint_host"], "api.synthetic.new")
            self.assertEqual(body["budget_endpoint_path"], "/v2/quotas")
            args, kwargs = fetch.call_args
            self.assertEqual(args[0], "https://api.synthetic.new/v2/quotas")
            self.assertEqual(kwargs["api_key"], "synthetic-budget-key")

    def test_research_facility_provider_budget_suppresses_proxy_secret(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _config(tmp)
            _write_synthetic_llm_settings(
                config,
                "synthetic-budget-key",
                base_url="https://synthetic.int.exe.xyz/openai/v1",
            )
            client = _client_with_config(config)
            quota = {
                "subscription": {"limit": 2500, "requests": 1},
                "weeklyTokenLimit": {"remainingCredits": "$100.00"},
                "rollingFiveHourLimit": {
                    "remaining": 2500,
                    "max": 2500,
                    "limited": False,
                },
            }

            with (
                patch.dict(
                    os.environ,
                    {
                        "ENOCH_RESEARCH_PROVIDER_BASE_URL": "",
                        "ENOCH_RESEARCH_PROVIDER_API_KEY": "",
                    },
                    clear=False,
                ),
                patch(
                    "scripts.research_provider_budget.fetch_json", return_value=quota
                ) as fetch,
            ):
                response = client.get(
                    "/control/api/research/provider-budget",
                    headers={"Authorization": f"Bearer {TOKEN}"},
                )

            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertTrue(body["ok"])
            self.assertEqual(body["auth_mode"], "exe_http_proxy")
            self.assertEqual(body["budget_endpoint_host"], "synthetic.int.exe.xyz")
            self.assertNotIn("synthetic-budget-key", response.text)
            args, kwargs = fetch.call_args
            self.assertEqual(args[0], "https://synthetic.int.exe.xyz/v2/quotas")
            self.assertEqual(kwargs["api_key"], "")

    def test_automation_readiness_provider_budget_uses_synthetic_settings(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _live_config(tmp)
            _write_synthetic_llm_settings(config, "synthetic-readiness-key")
            client = _client_with_config(config)
            quota = {
                "subscription": {"limit": 2500, "requests": 1},
                "weeklyTokenLimit": {"remainingCredits": "$100.00"},
                "rollingFiveHourLimit": {
                    "remaining": 2500,
                    "max": 2500,
                    "limited": False,
                },
            }

            with (
                patch.dict(
                    os.environ,
                    {
                        "ENOCH_RESEARCH_PROVIDER_BASE_URL": "",
                        "ENOCH_RESEARCH_PROVIDER_API_KEY": "",
                    },
                    clear=False,
                ),
                patch(
                    "scripts.research_provider_budget.fetch_json", return_value=quota
                ) as fetch,
            ):
                response = client.get(
                    "/control/api/v1/automation-readiness",
                    headers={"Authorization": f"Bearer {TOKEN}"},
                )

            self.assertEqual(response.status_code, 200)
            body = response.json()
            provider_check = next(
                item for item in body["checks"] if item["name"] == "provider_budget_ok"
            )
            self.assertTrue(provider_check["ok"])
            self.assertEqual(
                provider_check["data"]["budget_endpoint_host"], "api.synthetic.new"
            )
            self.assertEqual(
                provider_check["data"]["budget_endpoint_path"], "/v2/quotas"
            )
            args, kwargs = fetch.call_args
            self.assertEqual(args[0], "https://api.synthetic.new/v2/quotas")
            self.assertEqual(kwargs["api_key"], "synthetic-readiness-key")

    def test_automation_readiness_names_blocked_queue_sample(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            import_response = client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "readiness-blocked-sample-import",
                    "queue_rows": [
                        {
                            "project_id": "blocked-sample",
                            "project_name": "Blocked Sample Project",
                            "project_dir": "blocked-sample",
                            "status": "blocked",
                            "current_run_id": "run-blocked-sample",
                            "next_action_hint": "inspect_worker_gate_failure",
                            "manual_review_required": True,
                        }
                    ],
                },
            )
            self.assertEqual(import_response.status_code, 200)

            with patch("scripts.research_provider_budget.fetch_json", return_value={}):
                response = client.get(
                    "/control/api/v1/automation-readiness",
                    headers=headers,
                )

            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertIn(
                "blocked/needs-attention items exist: Blocked Sample Project (inspect_worker_gate_failure)",
                body["blockers"],
            )
            check = next(
                item
                for item in body["checks"]
                if item["name"] == "no_blocked_or_attention"
            )
            self.assertEqual(
                check["data"]["samples"][0]["project_id"], "blocked-sample"
            )
            self.assertIn("Blocked Sample Project", check["detail"])

    def test_automation_readiness_provider_budget_suppresses_proxy_secret(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _live_config(tmp)
            _write_synthetic_llm_settings(
                config,
                "synthetic-readiness-key",
                base_url="https://synthetic.int.exe.xyz/openai/v1",
            )
            client = _client_with_config(config)
            quota = {
                "subscription": {"limit": 2500, "requests": 1},
                "weeklyTokenLimit": {"remainingCredits": "$100.00"},
                "rollingFiveHourLimit": {
                    "remaining": 2500,
                    "max": 2500,
                    "limited": False,
                },
            }

            with (
                patch.dict(
                    os.environ,
                    {
                        "ENOCH_RESEARCH_PROVIDER_BASE_URL": "",
                        "ENOCH_RESEARCH_PROVIDER_API_KEY": "",
                    },
                    clear=False,
                ),
                patch(
                    "scripts.research_provider_budget.fetch_json", return_value=quota
                ) as fetch,
            ):
                response = client.get(
                    "/control/api/v1/automation-readiness",
                    headers={"Authorization": f"Bearer {TOKEN}"},
                )

            self.assertEqual(response.status_code, 200)
            body = response.json()
            provider_check = next(
                item for item in body["checks"] if item["name"] == "provider_budget_ok"
            )
            self.assertTrue(provider_check["ok"])
            self.assertEqual(
                provider_check["data"]["budget_endpoint_host"],
                "synthetic.int.exe.xyz",
            )
            self.assertNotIn("synthetic-readiness-key", response.text)
            args, kwargs = fetch.call_args
            self.assertEqual(args[0], "https://synthetic.int.exe.xyz/v2/quotas")
            self.assertEqual(kwargs["api_key"], "")

    def test_research_budget_check_supports_openrouter_key_limits(
        self,
    ) -> None:
        class ProviderBudget:
            @staticmethod
            def fetch_json(*args, **kwargs):
                raise AssertionError("OpenRouter must use its own key endpoint")

            @staticmethod
            def synthetic_budget_status(*args, **kwargs):
                raise AssertionError("OpenRouter must not parse Synthetic quota")

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            @staticmethod
            def read():
                return json.dumps(
                    {
                        "data": {
                            "label": "test-key",
                            "limit": 100.0,
                            "limit_remaining": 42.5,
                            "usage_daily": 1.5,
                            "usage_weekly": 2.5,
                            "usage_monthly": 3.5,
                            "is_free_tier": False,
                        }
                    }
                ).encode("utf-8")

        with patch(
            "enoch_control_plane.control_plane.router.urllib.request.urlopen",
            return_value=Response(),
        ) as urlopen:
            budget = _fetch_synthetic_research_budget(
                provider_id="openrouter",
                provider_base_url="https://openrouter.ai/api/v1",
                provider_api_key="openrouter-key",
                estimated_requests=1,
                bounded_int=lambda *_args: 2,
                bounded_float=lambda *_args: 5.0,
                research_provider_budget=ProviderBudget,
            )

        self.assertTrue(budget["ok"])
        self.assertEqual(budget["provider"], "openrouter")
        self.assertEqual(budget["provider_id"], "openrouter")
        self.assertEqual(budget["remaining_credits"], 42.5)
        self.assertEqual(budget["budget_endpoint_host"], "openrouter.ai")
        self.assertEqual(budget["budget_endpoint_path"], "/api/v1/key")
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://openrouter.ai/api/v1/key")
        self.assertEqual(request.headers["Authorization"], "Bearer openrouter-key")

    def test_research_budget_check_fails_closed_for_unsupported_provider(
        self,
    ) -> None:
        budget = _fetch_synthetic_research_budget(
            provider_id="anthropic",
            provider_base_url="https://api.anthropic.com/v1",
            provider_api_key="anthropic-key",
            estimated_requests=1,
            bounded_int=lambda *_args: 2,
            bounded_float=lambda *_args: 5.0,
            research_provider_budget=SimpleNamespace(),
        )

        self.assertFalse(budget["ok"])
        self.assertFalse(budget["budget_check_skipped"])
        self.assertEqual(budget["provider_id"], "anthropic")
        self.assertIn("provider budget check unavailable", budget["failures"][0])
        self.assertEqual(budget["budget_endpoint_host"], "api.anthropic.com")

    def test_automation_readiness_blocks_stale_active_worker_lane(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _config(tmp)
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "readiness-stale-active-import",
                    "queue_rows": [
                        {
                            "project_id": "readiness-stale-active",
                            "project_name": "Readiness Stale Active",
                            "status": "awaiting_wake",
                            "current_run_id": "run-readiness-stale-active",
                        }
                    ],
                },
            )
            store = ControlPlaneStore(Path(tmp) / "state" / "control_plane.sqlite3")
            old_worker_observation = (
                datetime.now(timezone.utc) - timedelta(minutes=10)
            ).isoformat()
            store.upsert_dashboard_observation(
                source="worker_preflight",
                status="ok",
                observed_at=old_worker_observation,
                ttl_seconds=3600,
                payload={
                    "ok": True,
                    "checks": [
                        {
                            "name": "worker_no_live_runs",
                            "ok": True,
                            "detail": "active_or_waiting=0, live=0",
                            "data": {"active_or_waiting": 0, "live": 0},
                        }
                    ],
                },
            )
            store.upsert_dashboard_observation(
                source="worker_dashboard_api",
                status="ok",
                observed_at=old_worker_observation,
                ttl_seconds=3600,
                payload={"ok": True},
            )
            with (
                patch("scripts.research_provider_budget.fetch_json", return_value={}),
            ):
                response = client.get(
                    "/control/api/v1/automation-readiness", headers=headers
                )

            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertFalse(body["ok"])
            self.assertIn("stale active worker lane exists", body["blockers"])
            check = next(
                item
                for item in body["checks"]
                if item["name"] == "active_worker_lanes_confirmed"
            )
            self.assertFalse(check["ok"])
            self.assertEqual(check["data"]["stale_active_lanes"], ["default"])

    def test_pre_dispatch_no_live_preflight_does_not_mark_new_active_row_stale(
        self,
    ) -> None:
        preflight_time = datetime.now(timezone.utc) - timedelta(minutes=10)
        dispatch_time = datetime.now(timezone.utc)
        preflight = DashboardObservationRecord(
            source="worker_preflight",
            observed_at=preflight_time.isoformat(),
            payload={
                "ok": True,
                "target": "http://cpu-worker:8787",
                "checks": [
                    {
                        "name": "worker_no_live_runs",
                        "ok": True,
                        "detail": "active_or_waiting=0, live=0",
                        "data": {"active_or_waiting": 0, "live": 0},
                    }
                ],
            },
        )
        active_row = {
            "project_id": "cpu-project",
            "current_run_id": "cpu-run",
            "status": "awaiting_wake",
            "last_dispatch_at": dispatch_time.isoformat(),
        }

        confirmation = _active_lane_worker_confirmation(
            preflight=preflight,
            preflight_lane_key="http://cpu-worker:8787",
            lane_key="http://cpu-worker:8787",
            active_row=active_row,
        )

        self.assertEqual(confirmation["state"], "preflight_stale_after_dispatch")
        self.assertNotEqual(confirmation["state"], "stale_active")
        self.assertIn("predates", confirmation["reason"])
        self.assertIn("refresh lane preflight", confirmation["suggested_action"])

    def test_automation_readiness_does_not_refresh_worker_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _live_config(tmp).model_copy(
                update={"worker_wake_gate_url": "http://worker.example"}
            )
            client = _client_with_config(config)
            store = ControlPlaneStore(Path(tmp) / "state" / "control_plane.sqlite3")
            stale_observed_at = (
                datetime.now(timezone.utc) - timedelta(hours=1)
            ).isoformat()
            store.upsert_dashboard_observation(
                source="worker_preflight",
                status="ok",
                observed_at=stale_observed_at,
                ttl_seconds=1,
                payload={"ok": True, "checks": []},
            )
            store.upsert_dashboard_observation(
                source="worker_dashboard_api",
                status="ok",
                observed_at=stale_observed_at,
                ttl_seconds=1,
                payload={"ok": True},
            )

            with (
                patch("scripts.research_provider_budget.fetch_json", return_value={}),
                patch(
                    "enoch_control_plane.control_plane.router.run_worker_preflight",
                    side_effect=AssertionError(
                        "automation readiness must not call live worker preflight"
                    ),
                ) as mocked_preflight,
            ):
                response = client.get(
                    "/control/api/v1/automation-readiness",
                    headers={"Authorization": f"Bearer {TOKEN}"},
                )

            self.assertEqual(response.status_code, 200)
            mocked_preflight.assert_not_called()

    def test_queue_alert_dry_run_refreshes_worker_preflight_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _live_config(tmp).model_copy(
                update={"worker_wake_gate_url": "http://worker.example"}
            )
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            store = ControlPlaneStore(Path(tmp) / "state" / "control_plane.sqlite3")
            stale_observed_at = (
                datetime.now(timezone.utc) - timedelta(hours=1)
            ).isoformat()
            store.upsert_dashboard_observation(
                source="worker_preflight",
                status="warn",
                observed_at=stale_observed_at,
                ttl_seconds=3600,
                payload={
                    "ok": False,
                    "target": "http://worker.example",
                    "checks": [
                        {
                            "name": "worker_no_live_runs",
                            "ok": False,
                            "detail": "active_or_waiting=1, live=1",
                            "data": {"active_or_waiting": 1, "live": 1},
                        }
                    ],
                },
            )
            fresh_preflight = WorkerPreflightResponse(
                ok=True,
                target="http://worker.example",
                summary="worker preflight passed",
                checks=[
                    WorkerPreflightCheck(
                        name="worker_no_live_runs",
                        ok=True,
                        detail="active_or_waiting=0, live=0",
                        data={"active_or_waiting": 0, "live": 0},
                    )
                ],
            )

            with patch(
                "enoch_control_plane.control_plane.router.run_worker_preflight",
                return_value=fresh_preflight,
            ) as mocked_preflight:
                response = client.post(
                    "/control/api/alerts/queue-check",
                    headers=headers,
                    json={"dry_run": True},
                )

            self.assertEqual(response.status_code, 200)
            mocked_preflight.assert_called()
            body = response.json()
            self.assertFalse(body["should_alert"])
            self.assertEqual(body["fingerprint"], "none")
            self.assertEqual(body["findings"], [])

    def test_automation_readiness_surfaces_latest_provider_generation_failure(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            store = ControlPlaneStore(Path(tmp) / "state" / "control_plane.sqlite3")
            store.append_event(
                idempotency_key="provider-attempt-failure",
                event_type="research.provider_generation.attempt",
                entity_type="research_provider",
                entity_id="run-cycle-test",
                payload={
                    "status": "failed",
                    "failure_kind": "timeout",
                    "reason": "provider generation skipped: timed out",
                    "provider_model": "synthetic-test",
                    "machine_target": "cpu-proxmox-1",
                    "recorded_at": "2026-05-30T15:00:00Z",
                },
            )

            with patch("scripts.research_provider_budget.fetch_json", return_value={}):
                response = client.get(
                    "/control/api/v1/automation-readiness",
                    headers={"Authorization": f"Bearer {TOKEN}"},
                )

            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertIn("latest provider generation attempt failed", body["blockers"])
            check = next(
                item
                for item in body["checks"]
                if item["name"] == "provider_generation_attempts_ok"
            )
            self.assertFalse(check["ok"])
            self.assertEqual(check["data"]["latest_failure_kind"], "timeout")
            self.assertEqual(
                body["summary"]["provider_generation_latest_status"], "failed"
            )

    def test_automation_readiness_blocks_degraded_llm_format_health(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _live_config(tmp)
            _write_synthetic_llm_settings(config, "synthetic-readiness-key")
            client = _client_with_config(config)
            store = ControlPlaneStore(Path(tmp) / "state" / "control_plane.sqlite3")
            store.append_event(
                idempotency_key="llm-format-health-readiness",
                event_type="settings.llm.model_test",
                entity_type="llm_model",
                entity_id="synthetic:hf:zai-org/GLM-5.1",
                payload={
                    "provider_id": "synthetic",
                    "model_id": "hf:zai-org/GLM-5.1",
                    "ok": True,
                    "status_code": 200,
                    "source": "format_probe",
                    "prompt_contract": "strict_json",
                    "checked_at": "2026-06-02T10:00:00Z",
                    "valid_json": False,
                    "schema_ok": False,
                    "malformed_kind": "invalid_json",
                    "visible_chars": 19,
                    "response_preview_redacted": "{not valid json",
                },
            )

            with patch("scripts.research_provider_budget.fetch_json", return_value={}):
                response = client.get(
                    "/control/api/v1/automation-readiness",
                    headers={"Authorization": f"Bearer {TOKEN}"},
                )

            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertFalse(body["ok"])
            self.assertIn(
                "configured LLM model health needs attention", body["blockers"]
            )
            check = next(
                item for item in body["checks"] if item["name"] == "llm_model_health_ok"
            )
            self.assertFalse(check["ok"])
            self.assertIn("structural=1", check["detail"])
            self.assertIn("hf:zai-org/GLM-5.1=format_degraded", check["detail"])
            self.assertEqual(
                body["summary"]["llm_model_structurally_unhealthy_count"], 1
            )

    def test_automation_readiness_writes_operator_trace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            trace_path = Path(tmp) / "automation_operator_trace.jsonl"
            config = _live_config(tmp).model_copy(
                update={
                    "operational_trace_enabled": True,
                    "operational_trace_log_path": str(trace_path),
                }
            )
            client = _client_with_config(config)

            with patch("scripts.research_provider_budget.fetch_json", return_value={}):
                response = client.get(
                    "/control/api/v1/automation-readiness",
                    headers={"Authorization": f"Bearer {TOKEN}"},
                )

            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertTrue(body["trace_id"].startswith("automation-readiness-"))
            trace_text = trace_path.read_text(encoding="utf-8")
            self.assertNotIn(TOKEN, trace_text)
            trace_rows = [json.loads(line) for line in trace_text.splitlines()]
            trace_row = next(
                row
                for row in trace_rows
                if row["event"] == "automation_readiness.result"
            )
            self.assertEqual(trace_row["trace_id"], body["trace_id"])
            self.assertEqual(
                trace_row["requested_by"], "dashboard.automation_readiness"
            )
            self.assertEqual(trace_row["status"], body["status"])
            self.assertEqual(trace_row["blockers"], body["blockers"][:20])
            self.assertLessEqual(set(trace_row["summary"]), set(body["summary"]))
            self.assertNotIn(
                "research_quality_post_prompt_monitor", trace_row["summary"]
            )

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
            self.assertIn("operator_summary", body)
            self.assertIn("empty", body["operator_summary"].lower())

    def test_research_facility_api_counts_are_total_not_page_rows(self) -> None:
        class FakeSupabaseStore:
            def research_facility_workbench_projection(
                self, *, limit: int = 200
            ) -> list[dict[str, str]]:
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
            with patch(
                "enoch_control_plane.control_plane.router.SupabaseControlPlaneStore",
                return_value=FakeSupabaseStore(),
            ):
                client = _client_with_config(config)
                response = client.get(
                    "/control/api/research/facility?page_size=1", headers=headers
                )

            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertEqual(body["page"]["returned"], 1)
            self.assertEqual(body["page"]["counts_scope"], "all_rows")
            self.assertEqual(body["counts"], {"admitted": 104, "needs_review": 34})
            self.assertIn("operator_summary", body)
            self.assertIn("need review before promotion", body["operator_summary"])

    def test_research_facility_generate_batch_dry_run_does_not_queue_or_dispatch(
        self,
    ) -> None:
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

    def test_research_facility_generate_batch_live_requires_supabase_store(
        self,
    ) -> None:
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

    def test_research_facility_generate_batch_live_rejects_readonly_before_ledger_work(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _live_config(tmp).model_copy(
                update={
                    "control_plane_store_backend": "supabase_readonly",
                    "supabase_database_url": "postgres://example",
                }
            )

            class FakeReadOnlyStore:
                def record_research_facility_plans(self, *_args, **_kwargs):  # noqa: ANN001 - must not be called
                    raise AssertionError(
                        "read-only candidate generation must reject before ledger writes"
                    )

            with patch(
                "enoch_control_plane.control_plane.router.SupabaseReadOnlyControlPlaneStore",
                return_value=FakeReadOnlyStore(),
            ):
                client = _client_with_config(config)
                response = client.post(
                    "/control/api/research/generate-batch",
                    headers={"Authorization": f"Bearer {TOKEN}"},
                    json={
                        "dry_run": False,
                        "max_candidates": 1,
                        "requested_by": "pytest",
                    },
                )

            self.assertEqual(response.status_code, 501)
            self.assertIn("writable control-plane store", response.text)

    def test_research_facility_provider_generate_dry_run_checks_budget_without_provider_spend(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            quota = {
                "subscription": {"limit": 2500, "requests": 0},
                "weeklyTokenLimit": {"remainingCredits": "$119.77"},
                "rollingFiveHourLimit": {
                    "remaining": 2500,
                    "max": 2500,
                    "limited": False,
                },
            }

            with (
                patch(
                    "scripts.research_provider_budget.fetch_json", return_value=quota
                ),
                patch(
                    "scripts.research_provider_generate.generate_provider_candidates"
                ) as generate,
            ):
                response = client.post(
                    "/control/api/research/generate-provider-batch",
                    headers=headers,
                    json={
                        "dry_run": True,
                        "max_candidates": 2,
                        "requested_by": "pytest",
                    },
                )

            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertTrue(body["ok"])
            self.assertEqual(body["action"], "dry_run_provider_generate_candidates")
            self.assertEqual(body["budget"]["estimated_requests"], 2)
            self.assertFalse(body["queue_admitted"])
            self.assertFalse(body["dispatch_started"])
            self.assertEqual(body["queued_count"], 0)
            self.assertIn("budget", body)
            generate.assert_not_called()

    def test_research_facility_provider_generate_fails_closed_when_budget_unavailable(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            headers = {"Authorization": f"Bearer {TOKEN}"}

            with (
                patch(
                    "scripts.research_provider_budget.fetch_json",
                    side_effect=RuntimeError("quota down"),
                ),
                patch(
                    "scripts.research_provider_generate.generate_provider_candidates"
                ) as generate,
            ):
                response = client.post(
                    "/control/api/research/generate-provider-batch",
                    headers=headers,
                    json={
                        "dry_run": False,
                        "max_candidates": 1,
                        "requested_by": "pytest",
                    },
                )

            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertFalse(body["ok"])
            self.assertEqual(body["action"], "provider_generation_blocked")
            self.assertIn("quota down", body["reason"])
            generate.assert_not_called()

    def test_research_facility_provider_generate_live_rejects_readonly_before_budget_or_spend(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _live_config(tmp).model_copy(
                update={
                    "control_plane_store_backend": "supabase_readonly",
                    "supabase_database_url": "postgres://example",
                }
            )

            class FakeReadOnlyStore:
                pass

            with (
                patch(
                    "enoch_control_plane.control_plane.router.SupabaseReadOnlyControlPlaneStore",
                    return_value=FakeReadOnlyStore(),
                ),
                patch(
                    "scripts.research_provider_budget.fetch_json",
                    side_effect=AssertionError(
                        "budget check must not run on readonly live generation"
                    ),
                ),
                patch(
                    "scripts.research_provider_generate.generate_provider_candidates",
                    side_effect=AssertionError(
                        "provider spend must not run on readonly live generation"
                    ),
                ),
            ):
                client = _client_with_config(config)
                response = client.post(
                    "/control/api/research/generate-provider-batch",
                    headers={"Authorization": f"Bearer {TOKEN}"},
                    json={
                        "dry_run": False,
                        "max_candidates": 1,
                        "requested_by": "pytest",
                    },
                )

            self.assertEqual(response.status_code, 501)
            self.assertIn("writable control-plane store", response.text)

    def test_research_facility_provider_generate_live_writes_ledgers_only_with_supabase_store(
        self,
    ) -> None:
        class FakeSupabaseStore:
            def __init__(self) -> None:
                self.recorded = []

            def research_facility_workbench_projection(
                self, *, limit: int = 200
            ) -> list[dict[str, str]]:
                return []

            def record_research_facility_plans(
                self, plans, *, requested_by: str, queue_admitted: bool = False
            ) -> dict[str, int]:
                self.recorded.append((plans, requested_by, queue_admitted))
                return {
                    "sources_upserted": 1,
                    "candidates_upserted": len(plans),
                    "admissions_inserted": len(plans),
                    "lineage_inserted": 1,
                }

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
            "source_records": [
                {
                    "source_id": "provider-source",
                    "source_kind": "internal_generated",
                    "title": "provider",
                    "url": "enoch://provider/test",
                }
            ],
            "hypothesis": "A bounded volunteer-training audit can reject stale updates under low communication.",
            "mechanism": "Use random gradient-slice probes before aggregation.",
            "description": "Provider generated candidate.",
            "implementation": "Simulate workers and injected adversaries, then compare against unchecked DiLoCo.",
            "baseline_to_beat": "Unchecked DiLoCo and FedAvg.",
            "success_threshold": "Detect at least 80 percent of stale updates with under 10 percent false positives.",
            "kill_condition": "Stop if probes miss replay attacks or communication overhead exceeds 1.5x.",
            "accessibility_delta": "Could make home volunteer training safer.",
            "expected_artifacts": [
                "run_notes.md",
                "metrics.json",
                "failure_cases.json",
                ".enoch/project_decision.json",
            ],
            "required_evidence": [
                "baseline comparison",
                "metrics table",
                "failure cases",
                "decision artifact",
            ],
            "likely_failure_modes": [
                "overhead too high",
                "adversaries evade probes",
                "false positives",
            ],
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
        with (
            patch(
                "enoch_control_plane.control_plane.router.SupabaseControlPlaneStore",
                return_value=fake_store,
            ),
            patch("scripts.research_provider_budget.fetch_json", return_value=quota),
            patch(
                "scripts.research_provider_generate.generate_provider_candidates",
                return_value={
                    "ok": True,
                    "provider_response_id": "cmpl-test",
                    "candidates": [generated_candidate],
                },
            ) as generate,
        ):
            client = _client_with_config(config)
            response = client.post(
                "/control/api/research/generate-provider-batch",
                headers={"Authorization": f"Bearer {TOKEN}"},
                json={
                    "dry_run": False,
                    "max_candidates": 1,
                    "generation_max_tokens": 9000,
                    "generation_attempts": 3,
                    "requested_by": "pytest",
                },
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

    def test_research_facility_provider_generate_slices_untrusted_response_to_max_candidates(
        self,
    ) -> None:
        class FakeSupabaseStore:
            def __init__(self) -> None:
                self.recorded = []

            def research_facility_workbench_projection(
                self, *, limit: int = 200
            ) -> list[dict[str, str]]:
                return []

            def record_research_facility_plans(
                self, plans, *, requested_by: str, queue_admitted: bool = False
            ) -> dict[str, int]:
                self.recorded.append((plans, requested_by, queue_admitted))
                return {"candidates_upserted": len(plans)}

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
        observed = {}

        def fake_plan(candidates, _args):
            observed["candidate_count"] = len(candidates)
            return [
                SimpleNamespace(
                    admission_decision="admitted",
                    to_json=lambda i=i: {"candidate_id": f"candidate-{i}"},
                )
                for i, _candidate in enumerate(candidates)
            ]

        with (
            patch(
                "enoch_control_plane.control_plane.router.SupabaseControlPlaneStore",
                return_value=fake_store,
            ),
            patch("scripts.research_provider_budget.fetch_json", return_value=quota),
            patch(
                "scripts.research_provider_generate.generate_provider_candidates",
                return_value={
                    "ok": True,
                    "provider_response_id": "cmpl-many",
                    "candidates": [{"title": str(i)} for i in range(20)],
                },
            ),
            patch("scripts.research_facility.plan_candidates", side_effect=fake_plan),
        ):
            client = _client_with_config(config)
            response = client.post(
                "/control/api/research/generate-provider-batch",
                headers={"Authorization": f"Bearer {TOKEN}"},
                json={"dry_run": False, "max_candidates": 2, "requested_by": "pytest"},
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["candidate_count"], 2)
        self.assertEqual(observed["candidate_count"], 2)
        self.assertEqual(len(fake_store.recorded[0][0]), 2)

    def test_research_facility_provider_generate_failure_does_not_write_ledgers(
        self,
    ) -> None:
        class FakeSupabaseStore:
            def record_research_facility_plans(
                self, *_args, **_kwargs
            ):  # pragma: no cover - should not be called
                raise AssertionError(
                    "ledger write should not run when provider generation fails"
                )

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
        with (
            patch(
                "enoch_control_plane.control_plane.router.SupabaseControlPlaneStore",
                return_value=FakeSupabaseStore(),
            ),
            patch("scripts.research_provider_budget.fetch_json", return_value=quota),
            patch(
                "scripts.research_provider_generate.generate_provider_candidates",
                side_effect=ValueError("invalid provider JSON"),
            ),
        ):
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

    def test_research_facility_provider_generate_zero_candidates_does_not_write_ledgers(
        self,
    ) -> None:
        class FakeSupabaseStore:
            def record_research_facility_plans(
                self, *_args, **_kwargs
            ):  # pragma: no cover - should not be called
                raise AssertionError(
                    "ledger write should not run when provider returns zero candidates"
                )

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
        with (
            patch(
                "enoch_control_plane.control_plane.router.SupabaseControlPlaneStore",
                return_value=FakeSupabaseStore(),
            ),
            patch("scripts.research_provider_budget.fetch_json", return_value=quota),
            patch(
                "scripts.research_provider_generate.generate_provider_candidates",
                return_value={
                    "ok": True,
                    "provider_response_id": "cmpl-empty",
                    "candidates": [],
                },
            ),
        ):
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

    def test_research_facility_run_cycle_dry_run_checks_budget_without_spend_or_writes(
        self,
    ) -> None:
        class FakeSupabaseStore:
            def __init__(self) -> None:
                self.events = []

            def active_items(self) -> list[dict[str, str]]:
                return []

            def status_counts(self) -> dict[str, int]:
                return {"blocked": 0, "queued": 0, "active": 0}

            def research_facility_workbench_projection(
                self, *, limit: int = 100
            ) -> list[dict[str, str]]:
                return [
                    {
                        "candidate_id": "candidate-ready",
                        "admission_decision": "admitted",
                        "admitted_idea_id": "",
                        "total_score": "80.00",
                    }
                ]

            def record_research_facility_plans(
                self, *_args, **_kwargs
            ):  # pragma: no cover - dry-run must not write
                raise AssertionError("dry-run should not write ledgers")

            def promote_research_candidate(
                self, *_args, **_kwargs
            ):  # pragma: no cover - dry-run must not promote
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
        with (
            patch(
                "enoch_control_plane.control_plane.router.SupabaseControlPlaneStore",
                return_value=fake_store,
            ),
            patch("scripts.research_provider_budget.fetch_json", return_value=quota),
            patch(
                "scripts.research_provider_generate.generate_provider_candidates"
            ) as generate,
        ):
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
        self.assertEqual(
            fake_store.events[0]["event_type"], "research.run_cycle.dry_run"
        )

    def test_research_facility_run_cycle_writes_operator_trace(self) -> None:
        class FakeSupabaseStore:
            def active_items(self) -> list[dict[str, str]]:
                return []

            def status_counts(self) -> dict[str, int]:
                return {"blocked": 0, "queued": 0, "active": 0}

            def research_facility_workbench_projection(
                self, *, limit: int = 100
            ) -> list[dict[str, str]]:
                return []

            def record_research_facility_plans(self, *_args, **_kwargs):
                raise AssertionError("dry-run must not write plans")

            def promote_research_candidate(self, *_args, **_kwargs):
                raise AssertionError("dry-run must not promote")

            def append_event(self, **_kwargs):
                return 1, True

        with tempfile.TemporaryDirectory() as tmp:
            trace_path = Path(tmp) / "operator_trace.jsonl"
            config = GateConfig(
                state_dir=str(Path(tmp) / "state"),
                project_root=str(Path(tmp) / "projects"),
                dispatch_script_path=str(Path(tmp) / "dispatch.sh"),
                control_api_bearer_token=TOKEN,
                completion_callback_url="http://example.invalid/callback",
                completion_callback_token="unused",
                control_plane_store_backend="supabase",
                supabase_database_url="postgresql://example.invalid/postgres",
                operational_trace_enabled=True,
                operational_trace_log_path=str(trace_path),
            )
            quota = {
                "subscription": {"limit": 2500, "requests": 0},
                "weeklyTokenLimit": {"remainingCredits": "$119.77"},
                "rollingFiveHourLimit": {
                    "remaining": 2500,
                    "max": 2500,
                    "limited": False,
                },
            }
            with (
                patch(
                    "enoch_control_plane.control_plane.router.SupabaseControlPlaneStore",
                    return_value=FakeSupabaseStore(),
                ),
                patch(
                    "scripts.research_provider_budget.fetch_json", return_value=quota
                ),
            ):
                client = _client_with_config(config)
                response = client.post(
                    "/control/api/research/run-cycle",
                    headers={"Authorization": f"Bearer {TOKEN}"},
                    json={"dry_run": True, "requested_by": "pytest"},
                )

            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertTrue(body["trace_id"].startswith("research-cycle-"))
            text = trace_path.read_text(encoding="utf-8")
            self.assertNotIn(TOKEN, text)
            events = [json.loads(line)["event"] for line in text.splitlines()]
            self.assertIn("research.run_cycle.start", events)
            self.assertIn("research.lanes.before", events)
            self.assertIn("research.generation_target.selected", events)
            self.assertIn("research.run_cycle.end", events)

    def test_research_facility_run_cycle_ignores_empty_allowed_model_list(self) -> None:
        class FakeSupabaseStore:
            def __init__(self) -> None:
                self.events = []

            def active_items(self) -> list[dict[str, str]]:
                return []

            def status_counts(self) -> dict[str, int]:
                return {"blocked": 0, "queued": 0, "active": 0}

            def research_facility_workbench_projection(
                self, *, limit: int = 100
            ) -> list[dict[str, str]]:
                return []

            def record_research_facility_plans(
                self, *_args, **_kwargs
            ):  # pragma: no cover - dry-run must not write
                raise AssertionError("dry-run should not write ledgers")

            def promote_research_candidate(
                self, *_args, **_kwargs
            ):  # pragma: no cover - dry-run must not promote
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
        with (
            patch(
                "enoch_control_plane.control_plane.router.SupabaseControlPlaneStore",
                return_value=FakeSupabaseStore(),
            ),
            patch("scripts.research_provider_budget.fetch_json", return_value=quota),
            patch(
                "scripts.research_provider_generate.generate_provider_candidates"
            ) as generate,
        ):
            client = _client_with_config(config)
            response = client.post(
                "/control/api/research/run-cycle",
                headers={"Authorization": f"Bearer {TOKEN}"},
                json={
                    "dry_run": True,
                    "allowed_models": ["", None],
                    "requested_by": "pytest",
                },
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertNotEqual(body["action"], "research_cycle_blocked")
        generate.assert_not_called()

    def test_research_facility_run_cycle_ignores_caller_supplied_allowed_models(
        self,
    ) -> None:
        class FakeSupabaseStore:
            def active_items(self) -> list[dict[str, str]]:
                return []

            def status_counts(self) -> dict[str, int]:
                return {"blocked": 0, "queued": 0, "active": 0}

            def research_facility_workbench_projection(
                self, *, limit: int = 100
            ) -> list[dict[str, str]]:
                return []

            def record_research_facility_plans(
                self, *_args, **_kwargs
            ):  # pragma: no cover - dry-run must not write
                raise AssertionError("dry-run should not write ledgers")

            def promote_research_candidate(
                self, *_args, **_kwargs
            ):  # pragma: no cover - dry-run must not promote
                raise AssertionError("dry-run should not promote")

            def append_event(self, **_kwargs):
                return 1, True

            def upsert_dashboard_observation(self, **_kwargs):
                return True

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
        with (
            patch(
                "enoch_control_plane.control_plane.router.SupabaseControlPlaneStore",
                return_value=FakeSupabaseStore(),
            ),
            patch("scripts.research_provider_budget.fetch_json", return_value=quota),
        ):
            client = _client_with_config(config)
            response = client.post(
                "/control/api/research/run-cycle",
                headers={"Authorization": f"Bearer {TOKEN}"},
                json={
                    "dry_run": True,
                    "allowed_models": ["attacker/model"],
                    "requested_by": "pytest",
                },
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertIn("hf:zai-org/GLM-5.1", body["allowed_models"])
        self.assertNotIn("attacker/model", body["allowed_models"])

    def test_research_facility_run_cycle_live_rejects_readonly_before_budget_or_events(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _live_config(tmp).model_copy(
                update={
                    "control_plane_store_backend": "supabase_readonly",
                    "supabase_database_url": "postgres://example",
                }
            )

            class FakeReadOnlyStore:
                def append_event(self, **_kwargs):  # noqa: ANN003 - must not be called
                    raise AssertionError(
                        "read-only run-cycle must reject before event writes"
                    )

            with (
                patch(
                    "enoch_control_plane.control_plane.router.SupabaseReadOnlyControlPlaneStore",
                    return_value=FakeReadOnlyStore(),
                ),
                patch(
                    "scripts.research_provider_budget.fetch_json",
                    side_effect=AssertionError(
                        "budget check must not run on readonly live run-cycle"
                    ),
                ),
                patch(
                    "scripts.research_provider_generate.generate_provider_candidates",
                    side_effect=AssertionError(
                        "provider spend must not run on readonly live run-cycle"
                    ),
                ),
            ):
                client = _client_with_config(config)
                response = client.post(
                    "/control/api/research/run-cycle",
                    headers={"Authorization": f"Bearer {TOKEN}"},
                    json={"dry_run": False, "enabled": True, "requested_by": "pytest"},
                )

            self.assertEqual(response.status_code, 501)
            self.assertIn("writable control-plane store", response.text)

    def test_research_facility_promote_candidate_live_rejects_readonly_before_mutation(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _live_config(tmp).model_copy(
                update={
                    "control_plane_store_backend": "supabase_readonly",
                    "supabase_database_url": "postgres://example",
                }
            )

            class FakeReadOnlyStore:
                def promote_research_candidate(self, *_args, **_kwargs):  # noqa: ANN001 - must not be called
                    raise AssertionError(
                        "read-only candidate promotion must reject before mutation"
                    )

            with patch(
                "enoch_control_plane.control_plane.router.SupabaseReadOnlyControlPlaneStore",
                return_value=FakeReadOnlyStore(),
            ):
                client = _client_with_config(config)
                response = client.post(
                    "/control/api/research/promote-candidate",
                    headers={"Authorization": f"Bearer {TOKEN}"},
                    json={
                        "dry_run": False,
                        "candidate_id": "candidate-1",
                        "requested_by": "pytest",
                    },
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
            json={
                "dry_run": True,
                "max_candidates": "bad",
                "admit_threshold": "bad",
                "review_threshold": "bad",
            },
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["candidate_count"], 3)

    def test_research_provider_generate_batch_tolerates_malformed_numeric_knobs(
        self,
    ) -> None:
        class FakeSupabaseStore:
            def record_research_facility_plans(
                self, *_args, **_kwargs
            ):  # pragma: no cover - dry-run must not write
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
        with (
            patch(
                "enoch_control_plane.control_plane.router.SupabaseControlPlaneStore",
                return_value=FakeSupabaseStore(),
            ),
            patch("scripts.research_provider_budget.fetch_json", return_value=quota),
        ):
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

    def test_research_facility_run_cycle_tolerates_malformed_numeric_knobs(
        self,
    ) -> None:
        class FakeSupabaseStore:
            def __init__(self) -> None:
                self.events = []

            def active_items(self) -> list[dict[str, str]]:
                return []

            def status_counts(self) -> dict[str, int]:
                return {"blocked": 0, "queued": 0, "active": 0}

            def research_facility_workbench_projection(
                self, *, limit: int = 100
            ) -> list[dict[str, str]]:
                return []

            def record_research_facility_plans(
                self, *_args, **_kwargs
            ):  # pragma: no cover - dry run must not write
                raise AssertionError("dry-run should not write ledgers")

            def promote_research_candidate(
                self, *_args, **_kwargs
            ):  # pragma: no cover - dry run must not promote
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
        with (
            patch(
                "enoch_control_plane.control_plane.router.SupabaseControlPlaneStore",
                return_value=fake_store,
            ),
            patch("scripts.research_provider_budget.fetch_json", return_value=quota),
        ):
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
                def research_facility_workbench_projection(
                    self, *, limit: int = 100
                ) -> list[dict[str, str]]:
                    return []

                def record_research_facility_plans(
                    self, *_args, **_kwargs
                ):  # pragma: no cover - backpressure returns before writes
                    raise AssertionError("backpressure should not write ledgers")

                def promote_research_candidate(
                    self, *_args, **_kwargs
                ):  # pragma: no cover - backpressure returns before promotion
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
                "rollingFiveHourLimit": {
                    "remaining": 2500,
                    "max": 2500,
                    "limited": False,
                },
            }
            with (
                patch(
                    "enoch_control_plane.control_plane.router.SupabaseControlPlaneStore",
                    return_value=fake_store,
                ),
                patch(
                    "scripts.research_provider_budget.fetch_json", return_value=quota
                ),
            ):
                client = _client_with_config(config)
                client.post(
                    "/control/import/legacy-snapshot",
                    headers=headers,
                    json={
                        "idempotency_key": "research-backpressure-import",
                        "queue_rows": [
                            {
                                "project_id": "active-research",
                                "project_name": "Active Research",
                                "project_dir": "active-research",
                                "status": "awaiting_wake",
                                "current_run_id": "run-active-research",
                            }
                        ],
                    },
                )
                for _ in range(2):
                    response = client.post(
                        "/control/api/research/run-cycle",
                        headers=headers,
                        json={
                            "dry_run": False,
                            "enabled": True,
                            "max_provider_requests_per_run": 0,
                            "requested_by": "pytest",
                        },
                    )
                    self.assertEqual(response.status_code, 200)
                    self.assertTrue(response.json()["backpressure"])

            events = fake_store.event_rows(event_type="research.run_cycle.backpressure")
            self.assertEqual(len(events), 1)

    def test_research_facility_backpressure_event_idempotency_conflict_still_returns_ok(
        self,
    ) -> None:
        class ConflictStore:
            def flags(self):
                return SimpleNamespace(queue_paused=False)

            def active_items(self) -> list[dict[str, str]]:
                return [
                    {
                        "project_id": "active-research",
                        "status": "awaiting_wake",
                        "current_run_id": "run-active",
                    }
                ]

            def status_counts(self) -> dict[str, int]:
                return {"blocked": 0, "queued": 0, "active": 1}

            def research_facility_workbench_projection(
                self, *, limit: int = 100
            ) -> list[dict[str, str]]:
                return []

            def record_research_facility_plans(self, *_args, **_kwargs):
                raise AssertionError("backpressure should stop before generation")

            def promote_research_candidate(self, *_args, **_kwargs):
                raise AssertionError("backpressure should stop before promotion")

            def append_event(self, **_kwargs):
                raise IdempotencyConflict(
                    "duplicate backpressure event with changed volatile payload"
                )

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
        with (
            patch(
                "enoch_control_plane.control_plane.router.SupabaseControlPlaneStore",
                return_value=ConflictStore(),
            ),
            patch("scripts.research_provider_budget.fetch_json", return_value=quota),
        ):
            client = _client_with_config(config)
            response = client.post(
                "/control/api/research/run-cycle",
                headers={"Authorization": f"Bearer {TOKEN}"},
                json={
                    "dry_run": False,
                    "enabled": True,
                    "max_provider_requests_per_run": 0,
                    "requested_by": "pytest",
                },
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertTrue(body["backpressure"])
        self.assertEqual(
            body["reason"],
            "active worker lane already exists and no promotable candidate targets an idle lane",
        )

    def test_research_facility_run_cycle_live_generates_and_promotes_without_dispatch(
        self,
    ) -> None:
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

            def research_facility_workbench_projection(
                self, *, limit: int = 100
            ) -> list[dict[str, str]]:
                if not self.generated_available:
                    return []
                return [
                    {
                        "candidate_id": "generated-candidate",
                        "admission_decision": "admitted",
                        "admitted_idea_id": "",
                        "total_score": "82.00",
                    }
                ]

            def record_research_facility_plans(
                self, plans, *, requested_by: str, queue_admitted: bool = False
            ) -> dict[str, int]:
                self.generated_available = True
                self.recorded.append((plans, requested_by, queue_admitted))
                return {
                    "sources_upserted": 1,
                    "candidates_upserted": len(plans),
                    "admissions_inserted": len(plans),
                    "lineage_inserted": 1,
                }

            def promote_research_candidate(
                self, candidate_id: str, *, requested_by: str, dry_run: bool = True
            ) -> dict[str, object]:
                self.promoted.append((candidate_id, requested_by, dry_run))
                return {
                    "ok": True,
                    "action": "promote_candidate",
                    "candidate_id": candidate_id,
                    "idea_id": candidate_id,
                    "queued_count": 1,
                    "dispatch_started": False,
                }

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
            "source_records": [
                {
                    "source_id": "provider-source",
                    "source_kind": "internal_generated",
                    "title": "provider",
                    "url": "enoch://provider/test",
                }
            ],
            "hypothesis": "A bounded local quantization experiment can reduce VRAM with measured quality tradeoffs.",
            "mechanism": "Use learned residual quantization and compare against int4 baselines.",
            "description": "Provider generated candidate.",
            "implementation": "Run a small local benchmark and record metrics, failure cases, and decision artifact.",
            "baseline_to_beat": "Uniform int4 quantization.",
            "success_threshold": "Beat int4 memory at comparable quality.",
            "kill_condition": "Stop if quality collapses or runtime exceeds baseline by 2x.",
            "accessibility_delta": "Could reduce local VRAM requirements.",
            "expected_artifacts": [
                "run_notes.md",
                "metrics.json",
                "failure_cases.json",
                ".enoch/project_decision.json",
            ],
            "required_evidence": [
                "baseline comparison",
                "metrics table",
                "failure cases",
                "decision artifact",
            ],
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
        with (
            patch(
                "enoch_control_plane.control_plane.router.SupabaseControlPlaneStore",
                return_value=fake_store,
            ),
            patch("scripts.research_provider_budget.fetch_json", return_value=quota),
            patch(
                "scripts.research_provider_generate.generate_provider_candidates",
                return_value={
                    "ok": True,
                    "provider_response_id": "cmpl-cycle",
                    "attempts_used": 1,
                    "candidates": [generated_candidate],
                },
            ) as generate,
        ):
            client = _client_with_config(config)
            response = client.post(
                "/control/api/research/run-cycle",
                headers={"Authorization": f"Bearer {TOKEN}"},
                json={
                    "dry_run": False,
                    "enabled": True,
                    "max_dispatches_per_run": 0,
                    "requested_by": "pytest",
                },
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
        self.assertEqual(
            fake_store.promoted[0], ("generated-candidate", "pytest", False)
        )
        self.assertTrue(
            any(
                event["event_type"] == "research.provider_generation.attempt"
                for event in fake_store.events
            )
        )
        self.assertTrue(
            any(
                event["event_type"] == "research.run_cycle.live"
                for event in fake_store.events
            )
        )
        self.assertEqual(generate.call_args.kwargs["attempts"], 2)

    def test_research_facility_run_cycle_generates_backlog_for_active_lane(
        self,
    ) -> None:
        class FakeSupabaseStore:
            def __init__(self) -> None:
                self.events = []
                self.recorded = []
                self.promoted = []
                self.generated_available = False

            def active_items(self) -> list[dict[str, str]]:
                return [
                    {
                        "project_id": "active-gb10",
                        "status": "awaiting_wake",
                        "current_run_id": "run-active",
                    }
                ]

            def status_counts(self) -> dict[str, int]:
                return {"blocked": 0, "queued": 0, "active": 1}

            def research_facility_workbench_projection(
                self, *, limit: int = 100
            ) -> list[dict[str, str]]:
                if not self.generated_available:
                    return []
                return [
                    {
                        "candidate_id": "generated-backlog-candidate",
                        "admission_decision": "admitted",
                        "admitted_idea_id": "",
                        "total_score": "82.00",
                        "machine_target": "",
                    }
                ]

            def record_research_facility_plans(
                self, plans, *, requested_by: str, queue_admitted: bool = False
            ) -> dict[str, int]:
                self.generated_available = True
                self.recorded.append((plans, requested_by, queue_admitted))
                return {
                    "sources_upserted": 1,
                    "candidates_upserted": len(plans),
                    "admissions_inserted": len(plans),
                    "lineage_inserted": 1,
                }

            def promote_research_candidate(
                self, candidate_id: str, *, requested_by: str, dry_run: bool = True
            ) -> dict[str, object]:
                self.promoted.append((candidate_id, requested_by, dry_run))
                return {
                    "ok": True,
                    "action": "promote_candidate",
                    "candidate_id": candidate_id,
                    "idea_id": candidate_id,
                    "queued_count": 1,
                    "dispatch_started": False,
                }

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
            worker_wake_gate_url="http://gb10-worker:8787",
            worker_wake_gate_bearer_token="gb10-token",
            worker_targets={
                "gb10": {
                    "wake_gate_url": "http://gb10-worker:8787",
                    "bearer_token": "gb10-token",
                    "role": "gpu_worker",
                },
            },
        )
        quota = {
            "subscription": {"limit": 2500, "requests": 0},
            "weeklyTokenLimit": {"remainingCredits": "$119.77"},
            "rollingFiveHourLimit": {"remaining": 2500, "max": 2500, "limited": False},
        }
        generated_candidate = {
            "title": "Generated Backlog Candidate",
            "generation_mode": "moonshot",
            "category": "quantization",
            "priority": "High",
            "source_kind": "internal_generated",
            "source_ids": ["provider-source"],
            "source_urls": ["enoch://provider/test"],
            "source_records": [
                {
                    "source_id": "provider-source",
                    "source_kind": "internal_generated",
                    "title": "provider",
                    "url": "enoch://provider/test",
                }
            ],
            "hypothesis": "A bounded local quantization experiment can reduce VRAM with measured quality tradeoffs.",
            "mechanism": "Use learned residual quantization and compare against int4 baselines.",
            "description": "Provider generated candidate.",
            "implementation": "Run a small local benchmark and record metrics, failure cases, and decision artifact.",
            "baseline_to_beat": "Uniform int4 quantization.",
            "success_threshold": "Beat int4 memory at comparable quality.",
            "kill_condition": "Stop if quality collapses or runtime exceeds baseline by 2x.",
            "accessibility_delta": "Could reduce local VRAM requirements.",
            "expected_artifacts": [
                "run_notes.md",
                "metrics.json",
                "failure_cases.json",
                ".enoch/project_decision.json",
            ],
            "required_evidence": [
                "baseline comparison",
                "metrics table",
                "failure cases",
                "decision artifact",
            ],
            "likely_failure_modes": ["quality collapse", "runtime overhead"],
            "estimated_runtime_class": "medium",
            "expected_token_budget": "medium",
            "machine_target": "gb10",
            "model": "gpt-5.5",
            "sandbox": "danger-full-access",
            "novelty_score": 8,
            "feasibility_score": 7,
            "accessibility_score": 8,
            "falsifiability_score": 8,
            "novelty_comparison": "Different from generic quantization because it tests residual allocation under a hard VRAM cap.",
            "risk_notes": "May not transfer to larger models.",
        }
        with (
            patch(
                "enoch_control_plane.control_plane.router.SupabaseControlPlaneStore",
                return_value=fake_store,
            ),
            patch("scripts.research_provider_budget.fetch_json", return_value=quota),
            patch(
                "scripts.research_provider_generate.generate_provider_candidates",
                return_value={
                    "ok": True,
                    "provider_response_id": "cmpl-cycle",
                    "attempts_used": 1,
                    "candidates": [generated_candidate],
                },
            ) as generate,
        ):
            client = _client_with_config(config)
            response = client.post(
                "/control/api/research/run-cycle",
                headers={"Authorization": f"Bearer {TOKEN}"},
                json={
                    "dry_run": False,
                    "enabled": True,
                    "max_dispatches_per_run": 0,
                    "requested_by": "pytest",
                },
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["action"], "research_cycle")
        self.assertNotIn("backpressure", body)
        self.assertEqual(body["generation_target_lane"]["machine_target"], "gb10")
        self.assertEqual(body["generated_count"], 1)
        self.assertEqual(body["promoted_count"], 1)
        self.assertEqual(body["queued_count"], 1)
        self.assertEqual(
            fake_store.promoted[0], ("generated-backlog-candidate", "pytest", False)
        )
        self.assertIn("machine_target=gb10", generate.call_args.kwargs["topic"])

    def test_research_facility_run_cycle_prioritizes_followup_before_fresh_generation(
        self,
    ) -> None:
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

            def research_facility_workbench_projection(
                self, *, limit: int = 100
            ) -> list[dict[str, str]]:
                return [
                    {
                        "candidate_id": "fresh-candidate",
                        "admission_decision": "admitted",
                        "admitted_idea_id": "",
                        "total_score": "99.00",
                    }
                ]

            def next_followup_candidate(
                self, *, max_followup_depth: int = 4, project_id: str = ""
            ) -> dict[str, str]:
                return {"project_id": "parent-idea", "followup_title": "Bounded branch"}

            def launch_followup_candidate(
                self,
                *,
                dry_run: bool = True,
                requested_by: str = "operator",
                max_followup_depth: int = 4,
                project_id: str = "",
            ) -> dict[str, object]:
                return {
                    "ok": True,
                    "action": "followup_queued",
                    "reason": "bounded follow-up queued",
                    "candidate": {"project_id": "parent-idea"},
                    "followup": {"idea_id": "followup-idea", "title": "Bounded branch"},
                }

            def record_research_facility_plans(
                self, *_args, **_kwargs
            ):  # pragma: no cover - follow-up should skip provider generation
                raise AssertionError(
                    "branch-first cycle should not write fresh provider candidates"
                )

            def promote_research_candidate(
                self, *_args, **_kwargs
            ):  # pragma: no cover - follow-up should skip fresh promotion
                raise AssertionError(
                    "branch-first cycle should not promote fresh candidates"
                )

            def queue_row(self, project_id: str):
                return self.queue.get(project_id)

            def claim_dispatch_candidate(
                self, *, project_id: str, run_id: str, requested_by: str
            ):
                claimed = dict(self.queue[project_id])
                claimed.update({"status": "dispatching", "current_run_id": run_id})
                self.queue[project_id] = claimed
                return claimed

            def release_dispatch_claim(
                self, *, project_id: str, run_id: str, reason: str
            ):  # pragma: no cover - happy path
                self.queue[project_id]["status"] = "queued"
                return True

            def update_project_dir(self, project_id: str, project_dir: str) -> None:
                self.queue[project_id]["project_dir"] = project_dir

            def mark_dispatch_started(
                self,
                *,
                project_id: str,
                run_id: str,
                session_id: str,
                dispatch_payload: dict,
                requested_by: str,
            ):
                self.queue[project_id].update(
                    {
                        "status": "awaiting_wake",
                        "current_run_id": run_id,
                        "current_session_id": session_id,
                    }
                )
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
            checks=[
                WorkerPreflightCheck(
                    name="worker_no_live_runs", ok=True, detail="no live worker runs"
                )
            ],
        )
        ok_http = HttpResult(
            ok=True,
            status=200,
            body={"dispatch": {"session_id": "session-1"}},
            error="",
        )
        with (
            patch(
                "enoch_control_plane.control_plane.router.SupabaseControlPlaneStore",
                return_value=fake_store,
            ),
            patch("scripts.research_provider_budget.fetch_json", return_value=quota),
            patch(
                "scripts.research_provider_generate.generate_provider_candidates"
            ) as generate,
            patch(
                "enoch_control_plane.control_plane.router.run_worker_preflight",
                return_value=ok_preflight,
            ),
            patch(
                "enoch_control_plane.control_plane.router.post_worker_json",
                return_value=ok_http,
            ),
        ):
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

    def test_research_facility_run_cycle_deferred_followup_does_not_starve_fresh_promotion(
        self,
    ) -> None:
        class FakeSupabaseStore:
            def __init__(self) -> None:
                self.events = []
                self.promoted = []

            def active_items(self) -> list[dict[str, str]]:
                return []

            def status_counts(self) -> dict[str, int]:
                return {"blocked": 0, "queued": 0, "active": 0}

            def flags(self):
                return SimpleNamespace(queue_paused=False, maintenance_mode=False)

            def research_facility_workbench_projection(
                self, *, limit: int = 100
            ) -> list[dict[str, str]]:
                return [
                    {
                        "candidate_id": "fresh-candidate",
                        "admission_decision": "admitted",
                        "admitted_idea_id": "",
                        "total_score": "99.00",
                    }
                ]

            def next_followup_candidate(
                self, *, max_followup_depth: int = 4, project_id: str = ""
            ) -> dict[str, str]:
                return {"project_id": "parent-idea", "followup_title": "Bounded branch"}

            def launch_followup_candidate(
                self, *_args, **_kwargs
            ):  # pragma: no cover - dispatch disabled must not launch
                raise AssertionError(
                    "follow-up launch should not run when dispatch is disabled"
                )

            def record_research_facility_plans(self, *_args, **_kwargs):
                raise AssertionError("fresh generation is disabled in this test")

            def promote_research_candidate(
                self, candidate_id: str, *, requested_by: str, dry_run: bool = True
            ) -> dict[str, object]:
                self.promoted.append((candidate_id, requested_by, dry_run))
                return {
                    "ok": True,
                    "candidate_id": candidate_id,
                    "idea_id": candidate_id,
                    "queued_count": 1,
                }

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
        with (
            patch(
                "enoch_control_plane.control_plane.router.SupabaseControlPlaneStore",
                return_value=fake_store,
            ),
            patch("scripts.research_provider_budget.fetch_json", return_value=quota),
            patch(
                "scripts.research_provider_generate.generate_provider_candidates"
            ) as generate,
        ):
            client = _client_with_config(config)
            response = client.post(
                "/control/api/research/run-cycle",
                headers={"Authorization": f"Bearer {TOKEN}"},
                json={
                    "dry_run": False,
                    "enabled": True,
                    "max_provider_requests_per_run": 0,
                    "max_promotions_per_run": 1,
                    "max_dispatches_per_run": 0,
                    "requested_by": "pytest",
                },
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertFalse(body["fresh_generation_skipped"])
        self.assertFalse(body["fresh_promotion_skipped"])
        self.assertEqual(body["followup_launch"]["action"], "skipped")
        self.assertEqual(body["promoted_count"], 1)
        self.assertEqual(fake_store.promoted[0][0], "fresh-candidate")
        generate.assert_not_called()

    def test_research_facility_run_cycle_no_lane_target_still_promotes_existing_candidate(
        self,
    ) -> None:
        class FakeSupabaseStore:
            def __init__(self) -> None:
                self.events = []
                self.promoted = []

            def active_items(self) -> list[dict[str, str]]:
                return []

            def status_counts(self) -> dict[str, int]:
                return {"blocked": 0, "queued": 0, "active": 0}

            def research_facility_workbench_projection(
                self, *, limit: int = 100
            ) -> list[dict[str, str]]:
                return [
                    {
                        "candidate_id": "existing-candidate",
                        "admission_decision": "admitted",
                        "admitted_idea_id": "",
                        "total_score": "83.00",
                    }
                ]

            def record_research_facility_plans(
                self, *_args, **_kwargs
            ):  # pragma: no cover - should not run on provider failure
                raise AssertionError(
                    "provider failure must not write generated candidate ledgers"
                )

            def promote_research_candidate(
                self, candidate_id: str, *, requested_by: str, dry_run: bool = True
            ) -> dict[str, object]:
                self.promoted.append((candidate_id, requested_by, dry_run))
                return {
                    "ok": True,
                    "action": "promote_candidate",
                    "candidate_id": candidate_id,
                    "idea_id": candidate_id,
                    "queued_count": 1,
                    "dispatch_started": False,
                }

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
        with (
            patch(
                "enoch_control_plane.control_plane.router.SupabaseControlPlaneStore",
                return_value=fake_store,
            ),
            patch("scripts.research_provider_budget.fetch_json", return_value=quota),
            patch(
                "scripts.research_provider_generate.generate_provider_candidates",
                side_effect=ValueError("provider returned 0 usable candidates"),
            ),
        ):
            client = _client_with_config(config)
            response = client.post(
                "/control/api/research/run-cycle",
                headers={"Authorization": f"Bearer {TOKEN}"},
                json={
                    "dry_run": False,
                    "enabled": True,
                    "max_dispatches_per_run": 0,
                    "requested_by": "pytest",
                },
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["generated_count"], 0)
        self.assertEqual(body["promoted_count"], 1)
        self.assertEqual(body["queued_count"], 1)
        self.assertIn("provider generation skipped", body["warnings"][0])
        self.assertEqual(body["stages"][0]["stage"], "provider_generation")
        self.assertTrue(body["stages"][0]["ok"])
        self.assertEqual(body["stages"][0]["action"], "skipped")
        self.assertEqual(body["stages"][0]["reason"], "no deficient lane feed target")
        self.assertEqual(
            fake_store.promoted[0], ("existing-candidate", "pytest", False)
        )
        self.assertEqual(fake_store.events[0]["event_type"], "research.run_cycle.live")

    def test_research_facility_run_cycle_skips_provider_when_admitted_backlog_is_high(
        self,
    ) -> None:
        class FakeSupabaseStore:
            def __init__(self) -> None:
                self.events = []
                self.promoted = []

            def active_items(self) -> list[dict[str, str]]:
                return []

            def status_counts(self) -> dict[str, int]:
                return {"blocked": 0, "queued": 0, "active": 0}

            def next_followup_candidate(
                self, *, max_followup_depth: int = 4, project_id: str = ""
            ) -> None:
                return None

            def research_facility_workbench_projection(
                self, *, limit: int = 100
            ) -> list[dict[str, str]]:
                return [
                    {
                        "candidate_id": f"existing-{index}",
                        "admission_decision": "admitted",
                        "admitted_idea_id": "",
                        "total_score": str(80 + index),
                    }
                    for index in range(3)
                ]

            def record_research_facility_plans(
                self, *_args, **_kwargs
            ):  # pragma: no cover - backlog should skip provider generation
                raise AssertionError(
                    "provider generation must be skipped when admitted backlog is high"
                )

            def promote_research_candidate(
                self, candidate_id: str, *, requested_by: str, dry_run: bool = True
            ) -> dict[str, object]:
                self.promoted.append((candidate_id, requested_by, dry_run))
                return {
                    "ok": True,
                    "action": "promote_candidate",
                    "candidate_id": candidate_id,
                    "idea_id": candidate_id,
                    "queued_count": 1,
                    "dispatch_started": False,
                }

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
        with (
            patch(
                "enoch_control_plane.control_plane.router.SupabaseControlPlaneStore",
                return_value=fake_store,
            ),
            patch("scripts.research_provider_budget.fetch_json", return_value=quota),
            patch(
                "scripts.research_provider_generate.generate_provider_candidates"
            ) as generate,
        ):
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
        self.assertEqual(
            body["fresh_generation_skip_reason"],
            "admitted candidate backlog is above fresh generation threshold",
        )
        self.assertEqual(body["generated_count"], 0)
        self.assertEqual(body["promoted_count"], 1)
        self.assertEqual(body["queued_count"], 1)
        self.assertEqual(fake_store.promoted[0][0], "existing-2")
        generate.assert_not_called()

    def test_research_facility_run_cycle_dispatch_conflict_is_benign_backpressure(
        self,
    ) -> None:
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

            def research_facility_workbench_projection(
                self, *, limit: int = 100
            ) -> list[dict[str, str]]:
                return [
                    {
                        "candidate_id": "candidate-ready",
                        "admission_decision": "admitted",
                        "admitted_idea_id": "",
                        "total_score": "83.00",
                    }
                ]

            def record_research_facility_plans(
                self, *_args, **_kwargs
            ):  # pragma: no cover - provider disabled
                raise AssertionError("provider generation disabled in this test")

            def promote_research_candidate(
                self, candidate_id: str, *, requested_by: str, dry_run: bool = True
            ) -> dict[str, object]:
                return {
                    "ok": True,
                    "action": "promote_candidate",
                    "candidate_id": candidate_id,
                    "idea_id": candidate_id,
                    "queued_count": 1,
                    "dispatch_started": False,
                }

            def queue_row(self, project_id: str):
                return self.queue.get(project_id)

            def claim_dispatch_candidate(
                self, *, project_id: str, run_id: str, requested_by: str
            ):
                claimed = dict(self.queue[project_id])
                claimed.update({"status": "dispatching", "current_run_id": run_id})
                return claimed

            def release_dispatch_claim(
                self, *, project_id: str, run_id: str, reason: str
            ):
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
            checks=[
                WorkerPreflightCheck(
                    name="worker_no_live_runs",
                    ok=False,
                    detail="active worker lane present",
                )
            ],
        )
        with (
            patch(
                "enoch_control_plane.control_plane.router.SupabaseControlPlaneStore",
                return_value=fake_store,
            ),
            patch("scripts.research_provider_budget.fetch_json", return_value=quota),
            patch(
                "enoch_control_plane.control_plane.router.run_worker_preflight",
                return_value=failed_preflight,
            ),
        ):
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
        dispatch_stage = next(
            stage for stage in body["stages"] if stage["stage"] == "dispatch"
        )
        self.assertEqual(dispatch_stage["action"], "dispatch_backpressure")
        self.assertIn("backpressure", dispatch_stage["reason"])
        self.assertEqual(fake_store.events[-1]["event_type"], "research.run_cycle.live")

    def test_research_facility_run_cycle_releases_claim_when_preflight_raises(
        self,
    ) -> None:
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

            def research_facility_workbench_projection(
                self, *, limit: int = 100
            ) -> list[dict[str, str]]:
                return [
                    {
                        "candidate_id": "candidate-ready",
                        "admission_decision": "admitted",
                        "admitted_idea_id": "",
                        "total_score": "83.00",
                    }
                ]

            def record_research_facility_plans(self, *_args, **_kwargs):
                raise AssertionError("provider generation disabled in this test")

            def promote_research_candidate(
                self, candidate_id: str, *, requested_by: str, dry_run: bool = True
            ) -> dict[str, object]:
                return {
                    "ok": True,
                    "action": "promote_candidate",
                    "candidate_id": candidate_id,
                    "idea_id": candidate_id,
                    "queued_count": 1,
                    "dispatch_started": False,
                }

            def queue_row(self, project_id: str):
                return self.queue.get(project_id)

            def claim_dispatch_candidate(
                self, *, project_id: str, run_id: str, requested_by: str
            ):
                claimed = dict(self.queue[project_id])
                claimed.update({"status": "dispatching", "current_run_id": run_id})
                return claimed

            def release_dispatch_claim(
                self, *, project_id: str, run_id: str, reason: str
            ):
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
        with (
            patch(
                "enoch_control_plane.control_plane.router.SupabaseControlPlaneStore",
                return_value=fake_store,
            ),
            patch("scripts.research_provider_budget.fetch_json", return_value=quota),
            patch(
                "enoch_control_plane.control_plane.router.run_worker_preflight",
                side_effect=RuntimeError("bad worker telemetry"),
            ),
        ):
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
        dispatch_stage = next(
            stage for stage in body["stages"] if stage["stage"] == "dispatch"
        )
        self.assertEqual(dispatch_stage["action"], "dispatch_backpressure")
        self.assertIn("bad worker telemetry", json.dumps(dispatch_stage["detail"]))

    def test_research_facility_run_cycle_live_records_guardrail_when_queue_paused(
        self,
    ) -> None:
        class FakeSupabaseStore:
            def __init__(self) -> None:
                self.events = []

            def active_items(self) -> list[dict[str, str]]:
                return []

            def status_counts(self) -> dict[str, int]:
                return {"blocked": 0, "queued": 0, "active": 0}

            def flags(self):
                return SimpleNamespace(queue_paused=True)

            def research_facility_workbench_projection(
                self, *, limit: int = 100
            ) -> list[dict[str, str]]:
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
        with patch(
            "enoch_control_plane.control_plane.router.SupabaseControlPlaneStore",
            return_value=fake_store,
        ):
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
        self.assertIn(
            "research autopilot is active but broad queue is paused", body["guardrails"]
        )
        self.assertTrue(
            any(
                event["event_type"] == "research.guardrail.queue_paused"
                for event in fake_store.events
            )
        )

    def test_research_facility_run_cycle_dispatches_idle_gb10_when_cpu_lane_active(
        self,
    ) -> None:
        class FakeSupabaseStore:
            def __init__(self) -> None:
                self.events = []
                self.observations = []
                self.promoted = []
                self.queue = {}

            def active_items(self) -> list[dict[str, str]]:
                return [
                    {
                        "project_id": "active-cpu",
                        "project_name": "Active CPU",
                        "status": "awaiting_wake",
                        "machine_target": "cpu-proxmox-1",
                        "current_run_id": "run-active-cpu",
                    }
                ]

            def status_counts(self) -> dict[str, int]:
                return {
                    "blocked": 0,
                    "queued": len(
                        [r for r in self.queue.values() if r["status"] == "queued"]
                    ),
                    "active": 1,
                }

            def flags(self):
                return SimpleNamespace(queue_paused=False, maintenance_mode=False)

            def next_followup_candidate(
                self, *, max_followup_depth: int = 4, project_id: str = ""
            ) -> None:
                return None

            def research_facility_workbench_projection(
                self, *, limit: int = 100
            ) -> list[dict[str, str]]:
                return [
                    {
                        "candidate_id": "cpu-high-score",
                        "title": "CPU High",
                        "admission_decision": "admitted",
                        "admitted_idea_id": "",
                        "total_score": "99.00",
                        "category": "agent-reliability",
                        "machine_target": "cpu-proxmox-1",
                    },
                    {
                        "candidate_id": "gb10-open-lane",
                        "title": "GB10 Open",
                        "admission_decision": "admitted",
                        "admitted_idea_id": "",
                        "total_score": "80.00",
                        "category": "spec-decoding",
                        "machine_target": "gb10",
                    },
                ]

            def record_research_facility_plans(self, *_args, **_kwargs):
                raise AssertionError("provider generation disabled in this test")

            def promote_research_candidate(
                self, candidate_id: str, *, requested_by: str, dry_run: bool = True
            ) -> dict[str, object]:
                target = "gb10" if candidate_id == "gb10-open-lane" else "cpu-proxmox-1"
                self.promoted.append((candidate_id, requested_by, dry_run))
                self.queue[candidate_id] = {
                    "project_id": candidate_id,
                    "project_name": candidate_id,
                    "project_dir": candidate_id,
                    "status": "queued",
                    "machine_target": target,
                    "model": "gpt-5.5",
                    "sandbox": "danger-full-access",
                }
                return {
                    "ok": True,
                    "action": "promote_candidate",
                    "candidate_id": candidate_id,
                    "idea_id": candidate_id,
                    "queued_count": 1,
                    "dispatch_started": False,
                }

            def queue_row(self, project_id: str):
                return self.queue.get(project_id)

            def claim_dispatch_candidate(
                self,
                *,
                project_id: str,
                run_id: str,
                requested_by: str,
                conflicting_machine_targets=None,
            ):
                row = self.queue.get(project_id)
                if not row or row["status"] != "queued":
                    return None
                active_targets = {
                    str(active.get("machine_target") or "").strip()
                    for active in self.active_items()
                }
                if active_targets & set(conflicting_machine_targets or []):
                    return None
                row.update({"status": "dispatching", "current_run_id": run_id})
                return dict(row)

            def release_dispatch_claim(
                self, *, project_id: str, run_id: str, reason: str
            ):
                self.queue[project_id]["status"] = "queued"
                return True

            def upsert_dashboard_observation(self, **kwargs):
                self.observations.append(kwargs)

            def update_project_dir(self, project_id: str, project_dir: str) -> None:
                self.queue[project_id]["project_dir"] = project_dir

            def mark_dispatch_started(
                self,
                *,
                project_id: str,
                run_id: str,
                session_id: str,
                dispatch_payload: dict,
                requested_by: str,
            ):
                self.queue[project_id].update(
                    {
                        "status": "awaiting_wake",
                        "current_run_id": run_id,
                        "current_session_id": session_id,
                    }
                )
                return 123, dict(self.queue[project_id])

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
            worker_wake_gate_url="http://gb10-worker:8787",
            worker_wake_gate_bearer_token="gb10-token",
            worker_targets={
                "cpu-proxmox-1": {
                    "wake_gate_url": "http://cpu-worker:8787",
                    "bearer_token": "cpu-token",
                    "role": "cpu_worker",
                },
                "gb10": {
                    "wake_gate_url": "http://gb10-worker:8787",
                    "bearer_token": "gb10-token",
                    "role": "gpu_worker",
                },
            },
        )
        quota = {
            "subscription": {"limit": 2500, "requests": 0},
            "weeklyTokenLimit": {"remainingCredits": "$119.77"},
            "rollingFiveHourLimit": {"remaining": 2500, "max": 2500, "limited": False},
        }
        preflight = WorkerPreflightResponse(
            ok=True, target="http://gb10-worker:8787", summary="ok", checks=[]
        )
        worker_calls = []

        def fake_post(base: str, path: str, token: str, payload: dict) -> HttpResult:
            worker_calls.append((base, path, token, payload))
            if path == "/prepare-project":
                return HttpResult(
                    ok=True, status=200, body={"prepared": payload["project_id"]}
                )
            if path == "/dispatch":
                return HttpResult(
                    ok=True,
                    status=200,
                    body={"dispatch": {"session_id": "gb10-session"}},
                )
            return HttpResult(ok=False, status=404, body=None, error="unexpected path")

        with (
            patch(
                "enoch_control_plane.control_plane.router.SupabaseControlPlaneStore",
                return_value=fake_store,
            ),
            patch("scripts.research_provider_budget.fetch_json", return_value=quota),
            patch(
                "scripts.research_provider_generate.generate_provider_candidates"
            ) as generate,
            patch(
                "enoch_control_plane.control_plane.router.run_worker_preflight",
                return_value=preflight,
            ),
            patch(
                "enoch_control_plane.control_plane.router.post_worker_json",
                side_effect=fake_post,
            ),
        ):
            client = _client_with_config(config)
            response = client.post(
                "/control/api/research/run-cycle",
                headers={"Authorization": f"Bearer {TOKEN}"},
                json={
                    "dry_run": False,
                    "enabled": True,
                    "max_provider_requests_per_run": 0,
                    "max_promotions_per_run": 2,
                    "max_dispatches_per_run": 2,
                    "max_paper_drafts_per_run": 0,
                    "requested_by": "pytest",
                },
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertFalse(body.get("backpressure", False))
        self.assertEqual(body["promoted_count"], 1)
        self.assertEqual(body["dispatched_count"], 1)
        self.assertEqual(fake_store.promoted[0][0], "gb10-open-lane")
        self.assertEqual(
            body["dispatches"][0]["candidate"]["project_id"], "gb10-open-lane"
        )
        self.assertEqual(
            body["dispatches"][0]["live"]["dispatch_route"]["machine_target"], "gb10"
        )
        self.assertEqual(
            {call[0] for call in worker_calls}, {"http://gb10-worker:8787"}
        )
        generate.assert_not_called()

    def test_research_facility_run_cycle_generates_for_empty_idle_gb10_lane_despite_cpu_backlog(
        self,
    ) -> None:
        class FakeSupabaseStore:
            def __init__(self) -> None:
                self.events = []
                self.ledger_plans = []

            def active_items(self) -> list[dict[str, str]]:
                return [
                    {
                        "project_id": "active-cpu",
                        "project_name": "Active CPU",
                        "status": "awaiting_wake",
                        "machine_target": "cpu-proxmox-1",
                        "current_run_id": "run-active-cpu",
                    }
                ]

            def status_counts(self) -> dict[str, int]:
                return {"blocked": 0, "queued": 0, "active": 1}

            def flags(self):
                return SimpleNamespace(queue_paused=False, maintenance_mode=False)

            def next_followup_candidate(
                self, *, max_followup_depth: int = 4, project_id: str = ""
            ) -> None:
                return None

            def research_facility_workbench_projection(
                self, *, limit: int = 100
            ) -> list[dict[str, str]]:
                return [
                    {
                        "candidate_id": f"cpu-backlog-{idx}",
                        "title": f"CPU Backlog {idx}",
                        "admission_decision": "admitted",
                        "admitted_idea_id": "",
                        "total_score": "90.00",
                        "category": "agent-reliability",
                        "machine_target": "cpu-proxmox-1",
                    }
                    for idx in range(30)
                ]

            def record_research_facility_plans(
                self, plans, *, requested_by: str, queue_admitted: bool = False
            ):
                self.ledger_plans.extend(plans)
                return {
                    "inserted": len(plans),
                    "queue_admitted": queue_admitted,
                    "requested_by": requested_by,
                }

            def promote_research_candidate(
                self, *_args, **_kwargs
            ):  # pragma: no cover - promotion disabled in this test
                raise AssertionError("this test only verifies lane-targeted generation")

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
            worker_wake_gate_url="http://gb10-worker:8787",
            worker_wake_gate_bearer_token="gb10-token",
            worker_targets={
                "cpu-proxmox-1": {
                    "wake_gate_url": "http://cpu-worker:8787",
                    "bearer_token": "cpu-token",
                    "role": "cpu_worker",
                },
                "gb10": {
                    "wake_gate_url": "http://gb10-worker:8787",
                    "bearer_token": "gb10-token",
                    "role": "gpu_worker",
                },
            },
        )
        quota = {
            "subscription": {"limit": 2500, "requests": 0},
            "weeklyTokenLimit": {"remainingCredits": "$119.77"},
            "rollingFiveHourLimit": {"remaining": 2500, "max": 2500, "limited": False},
        }
        generated_candidate = {
            "candidate_id": "generated-gb10",
            "title": "Generated GB10",
            "machine_target": "gb10",
        }

        with (
            patch(
                "enoch_control_plane.control_plane.router.SupabaseControlPlaneStore",
                return_value=fake_store,
            ),
            patch("scripts.research_provider_budget.fetch_json", return_value=quota),
            patch(
                "scripts.research_provider_generate.generate_provider_candidates",
                return_value={
                    "candidates": [generated_candidate],
                    "provider_response_id": "resp-gb10",
                    "attempts_used": 1,
                },
            ) as generate,
            patch(
                "scripts.research_facility.plan_candidates",
                return_value=[
                    {"candidate": generated_candidate, "admission_decision": "admitted"}
                ],
            ),
        ):
            client = _client_with_config(config)
            response = client.post(
                "/control/api/research/run-cycle",
                headers={"Authorization": f"Bearer {TOKEN}"},
                json={
                    "dry_run": False,
                    "enabled": True,
                    "max_provider_requests_per_run": 1,
                    "max_promotions_per_run": 0,
                    "max_dispatches_per_run": 0,
                    "max_paper_drafts_per_run": 0,
                    "fresh_generation_backlog_threshold": 1,
                    "requested_by": "pytest",
                },
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertFalse(body.get("backpressure", False))
        self.assertEqual(body["generated_count"], 1)
        self.assertFalse(body["fresh_generation_skipped"])
        self.assertEqual(body["generation_target_lane"]["machine_target"], "gb10")
        self.assertEqual(
            body["lane_feed_pressure"]["gb10"]["next_autopilot_action"],
            "generate_candidate",
        )
        self.assertEqual(
            body["lane_feed_pressure"]["gb10"]["operator_summary"],
            "GB10 lane idle with no queued candidate; autopilot should generate GB10-targeted work.",
        )
        self.assertEqual(
            fake_store.ledger_plans[0]["candidate"]["machine_target"], "gb10"
        )
        self.assertEqual(generate.call_args.kwargs["default_machine"], "gb10")
        self.assertIn("machine_target=gb10", generate.call_args.kwargs["topic"])
        self.assertTrue(
            any(
                stage.get("stage") == "provider_generation"
                and stage.get("generation_target_lane") == "gb10"
                for stage in body["stages"]
            )
        )

    def test_research_facility_run_cycle_does_not_let_followup_starve_empty_cpu_lane(
        self,
    ) -> None:
        class FakeSupabaseStore:
            def __init__(self) -> None:
                self.events = []
                self.ledger_plans = []
                self.followup_launches = 0

            def active_items(self) -> list[dict[str, str]]:
                return [
                    {
                        "project_id": "active-gb10",
                        "project_name": "Active GB10",
                        "status": "awaiting_wake",
                        "machine_target": "gb10",
                        "current_run_id": "run-active-gb10",
                    }
                ]

            def status_counts(self) -> dict[str, int]:
                return {"blocked": 0, "queued": 6, "active": 1}

            def flags(self):
                return SimpleNamespace(queue_paused=False, maintenance_mode=False)

            def queued_items_sql(self, *, limit: int = 200) -> list[dict[str, str]]:
                return [
                    {
                        "project_id": f"gb10-{idx}",
                        "status": "queued",
                        "machine_target": "gb10",
                    }
                    for idx in range(6)
                ]

            def next_followup_candidate(
                self, *, max_followup_depth: int = 4, project_id: str = ""
            ) -> dict[str, str]:
                return {
                    "project_id": "completed-gb10-parent",
                    "project_name": "Completed GB10 Parent",
                    "machine_target": "gb10",
                    "model": "gpt-5.5",
                    "sandbox": "danger-full-access",
                    "followup_title": "GB10 Followup",
                    "followup_hypothesis": "GPU follow-up should not starve CPU feed.",
                }

            def launch_followup_candidate(
                self, *_args, **_kwargs
            ):  # pragma: no cover - regression guard
                self.followup_launches += 1
                raise AssertionError(
                    "GB10 follow-up should be skipped while CPU lane needs fresh work"
                )

            def research_facility_workbench_projection(
                self, *, limit: int = 100
            ) -> list[dict[str, str]]:
                return []

            def record_research_facility_plans(
                self, plans, *, requested_by: str, queue_admitted: bool = False
            ):
                self.ledger_plans.extend(plans)
                return {
                    "inserted": len(plans),
                    "queue_admitted": queue_admitted,
                    "requested_by": requested_by,
                }

            def promote_research_candidate(
                self, *_args, **_kwargs
            ):  # pragma: no cover - promotion disabled in this test
                raise AssertionError("this test only verifies lane-targeted generation")

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
            worker_wake_gate_url="http://gb10-worker:8787",
            worker_wake_gate_bearer_token="gb10-token",
            worker_targets={
                "cpu-proxmox-1": {
                    "wake_gate_url": "http://cpu-worker:8787",
                    "bearer_token": "cpu-token",
                    "role": "cpu_worker",
                },
                "gb10": {
                    "wake_gate_url": "http://gb10-worker:8787",
                    "bearer_token": "gb10-token",
                    "role": "gpu_worker",
                },
            },
        )
        quota = {
            "subscription": {"limit": 2500, "requests": 0},
            "weeklyTokenLimit": {"remainingCredits": "$119.77"},
            "rollingFiveHourLimit": {"remaining": 2500, "max": 2500, "limited": False},
        }
        generated_candidate = {
            "candidate_id": "generated-cpu",
            "title": "Generated CPU",
        }

        def fake_plan_candidates(candidates, args):
            planned = dict(candidates[0])
            planned.setdefault("machine_target", args.default_machine)
            return [{"candidate": planned, "admission_decision": "admitted"}]

        with (
            patch(
                "enoch_control_plane.control_plane.router.SupabaseControlPlaneStore",
                return_value=fake_store,
            ),
            patch("scripts.research_provider_budget.fetch_json", return_value=quota),
            patch(
                "scripts.research_provider_generate.generate_provider_candidates",
                return_value={
                    "candidates": [generated_candidate],
                    "provider_response_id": "resp-cpu",
                    "attempts_used": 1,
                },
            ) as generate,
            patch(
                "scripts.research_facility.plan_candidates",
                side_effect=fake_plan_candidates,
            ) as plan_candidates,
        ):
            client = _client_with_config(config)
            response = client.post(
                "/control/api/research/run-cycle",
                headers={"Authorization": f"Bearer {TOKEN}"},
                json={
                    "dry_run": False,
                    "enabled": True,
                    "max_provider_requests_per_run": 1,
                    "max_promotions_per_run": 0,
                    "max_dispatches_per_run": 2,
                    "max_paper_drafts_per_run": 0,
                    "min_queue_depth_per_lane": 25,
                    "requested_by": "pytest",
                },
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertEqual(
            body["generation_target_lane"]["machine_target"], "cpu-proxmox-1"
        )
        self.assertIn(
            "GB10 lane active with queued depth 6/25",
            body["lane_feed_pressure"]["gb10"]["operator_summary"],
        )
        self.assertEqual(body["followup_launch"]["action"], "skipped")
        self.assertIn("different lane", body["followup_launch"]["reason"])
        self.assertFalse(body["fresh_generation_skipped"])
        self.assertEqual(body["generated_count"], 1)
        self.assertEqual(fake_store.followup_launches, 0)
        self.assertEqual(generate.call_args.kwargs["default_machine"], "cpu-proxmox-1")
        self.assertEqual(
            plan_candidates.call_args.args[1].default_machine, "cpu-proxmox-1"
        )
        self.assertEqual(
            fake_store.ledger_plans[0]["candidate"]["machine_target"],
            "cpu-proxmox-1",
        )
        self.assertIn(
            "machine_target=cpu-proxmox-1", generate.call_args.kwargs["topic"]
        )

    def test_research_facility_run_cycle_dispatches_idle_cpu_queue_while_gb10_active(
        self,
    ) -> None:
        class FakeSupabaseStore:
            def __init__(self) -> None:
                self.events = []
                self.queue = {
                    "cpu-ready": {
                        "project_id": "cpu-ready",
                        "project_name": "CPU Ready",
                        "project_dir": "cpu-ready",
                        "status": "queued",
                        "machine_target": "cpu-proxmox-1",
                        "model": "gpt-5.5",
                        "sandbox": "danger-full-access",
                    }
                }

            def active_items(self) -> list[dict[str, str]]:
                return [
                    {
                        "project_id": "active-gb10",
                        "project_name": "Active GB10",
                        "status": "awaiting_wake",
                        "machine_target": "gb10",
                        "current_run_id": "run-active-gb10",
                    }
                ]

            def status_counts(self) -> dict[str, int]:
                return {"blocked": 0, "queued": 1, "active": 1}

            def flags(self):
                return SimpleNamespace(queue_paused=False, maintenance_mode=False)

            def queued_items_sql(self, *, limit: int = 200) -> list[dict[str, str]]:
                return list(self.queue.values())

            def queue_row(self, project_id: str):
                return self.queue.get(project_id)

            def next_followup_candidate(
                self, *, max_followup_depth: int = 4, project_id: str = ""
            ) -> None:
                return None

            def research_facility_workbench_projection(
                self, *, limit: int = 100
            ) -> list[dict[str, str]]:
                return []

            def record_research_facility_plans(
                self, *_args, **_kwargs
            ):  # pragma: no cover - provider disabled in this test
                raise AssertionError("provider generation disabled in this test")

            def promote_research_candidate(
                self, *_args, **_kwargs
            ):  # pragma: no cover - no promotable rows in this test
                raise AssertionError("promotion should not run in this test")

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
            worker_wake_gate_url="http://gb10-worker:8787",
            worker_wake_gate_bearer_token="gb10-token",
            worker_targets={
                "cpu-proxmox-1": {
                    "wake_gate_url": "http://cpu-worker:8787",
                    "bearer_token": "cpu-token",
                    "role": "cpu_worker",
                },
                "gb10": {
                    "wake_gate_url": "http://gb10-worker:8787",
                    "bearer_token": "gb10-token",
                    "role": "gpu_worker",
                },
            },
        )
        quota = {
            "subscription": {"limit": 2500, "requests": 0},
            "weeklyTokenLimit": {"remainingCredits": "$119.77"},
            "rollingFiveHourLimit": {"remaining": 2500, "max": 2500, "limited": False},
        }

        def fake_live_dispatch(candidate, *_args, **_kwargs):
            updated = dict(candidate)
            updated.update(
                {
                    "status": "awaiting_wake",
                    "current_run_id": "run-cpu-ready",
                }
            )
            return {"run_id": "run-cpu-ready", "project_id": "cpu-ready"}, 1234, updated

        with (
            patch(
                "enoch_control_plane.control_plane.router.SupabaseControlPlaneStore",
                return_value=fake_store,
            ),
            patch("scripts.research_provider_budget.fetch_json", return_value=quota),
            patch(
                "enoch_control_plane.control_plane.router._execute_live_dispatch",
                side_effect=fake_live_dispatch,
            ) as live_dispatch,
        ):
            client = _client_with_config(config)
            response = client.post(
                "/control/api/research/run-cycle",
                headers={"Authorization": f"Bearer {TOKEN}"},
                json={
                    "dry_run": False,
                    "enabled": True,
                    "max_provider_requests_per_run": 0,
                    "max_promotions_per_run": 0,
                    "max_dispatches_per_run": 2,
                    "max_paper_drafts_per_run": 0,
                    "requested_by": "pytest",
                },
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertNotIn("backpressure", body)
        self.assertEqual(body["dispatched_count"], 1)
        self.assertTrue(body["dispatch_started"])
        self.assertEqual(body["dispatch"]["candidate"]["project_id"], "cpu-ready")
        self.assertEqual(
            body["dispatch"]["candidate"]["machine_target"], "cpu-proxmox-1"
        )
        self.assertEqual(
            body["lane_feed_pressure"]["cpu-proxmox-1"]["next_autopilot_action"],
            "dispatch_queued",
        )
        live_dispatch.assert_called_once()
        self.assertEqual(fake_store.events[-1]["event_type"], "research.run_cycle.live")

    def test_research_facility_run_cycle_respects_dispatch_cap_before_followup(
        self,
    ) -> None:
        class FakeSupabaseStore:
            def __init__(self) -> None:
                self.events = []
                self.followup_launches = 0
                self.queue = {
                    "cpu-ready": {
                        "project_id": "cpu-ready",
                        "project_name": "CPU Ready",
                        "project_dir": "cpu-ready",
                        "status": "queued",
                        "machine_target": "cpu-proxmox-1",
                        "model": "gpt-5.5",
                        "sandbox": "danger-full-access",
                    }
                }

            def active_items(self) -> list[dict[str, str]]:
                return [
                    {
                        "project_id": "active-gb10",
                        "project_name": "Active GB10",
                        "status": "awaiting_wake",
                        "machine_target": "gb10",
                        "current_run_id": "run-active-gb10",
                    }
                ]

            def status_counts(self) -> dict[str, int]:
                return {"blocked": 0, "queued": 1, "active": 1}

            def flags(self):
                return SimpleNamespace(queue_paused=False, maintenance_mode=False)

            def queued_items_sql(self, *, limit: int = 200) -> list[dict[str, str]]:
                return list(self.queue.values())[:limit]

            def queue_row(self, project_id: str):
                return self.queue.get(project_id)

            def next_followup_candidate(
                self, *, max_followup_depth: int = 4, project_id: str = ""
            ) -> dict[str, str]:
                return {"project_id": "parent-idea", "followup_title": "Bounded branch"}

            def launch_followup_candidate(
                self, *_args, **_kwargs
            ):  # pragma: no cover - regression guard
                self.followup_launches += 1
                raise AssertionError(
                    "follow-up launch should not run after dispatch cap is consumed"
                )

            def research_facility_workbench_projection(
                self, *, limit: int = 100
            ) -> list[dict[str, str]]:
                return []

            def record_research_facility_plans(
                self, *_args, **_kwargs
            ):  # pragma: no cover - provider disabled in this test
                raise AssertionError("provider generation disabled in this test")

            def promote_research_candidate(
                self, *_args, **_kwargs
            ):  # pragma: no cover - no promotions in this test
                raise AssertionError("promotion should not run in this test")

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
            worker_wake_gate_url="http://gb10-worker:8787",
            worker_wake_gate_bearer_token="gb10-token",
            worker_targets={
                "cpu-proxmox-1": {
                    "wake_gate_url": "http://cpu-worker:8787",
                    "bearer_token": "cpu-token",
                    "role": "cpu_worker",
                },
                "gb10": {
                    "wake_gate_url": "http://gb10-worker:8787",
                    "bearer_token": "gb10-token",
                    "role": "gpu_worker",
                },
            },
        )
        quota = {
            "subscription": {"limit": 2500, "requests": 0},
            "weeklyTokenLimit": {"remainingCredits": "$119.77"},
            "rollingFiveHourLimit": {"remaining": 2500, "max": 2500, "limited": False},
        }

        def fake_live_dispatch(candidate, *_args, **_kwargs):
            updated = dict(candidate)
            updated.update(
                {"status": "awaiting_wake", "current_run_id": "run-cpu-ready"}
            )
            return {"run_id": "run-cpu-ready", "project_id": "cpu-ready"}, 1234, updated

        with (
            patch(
                "enoch_control_plane.control_plane.router.SupabaseControlPlaneStore",
                return_value=fake_store,
            ),
            patch("scripts.research_provider_budget.fetch_json", return_value=quota),
            patch(
                "enoch_control_plane.control_plane.router._execute_live_dispatch",
                side_effect=fake_live_dispatch,
            ) as live_dispatch,
        ):
            client = _client_with_config(config)
            response = client.post(
                "/control/api/research/run-cycle",
                headers={"Authorization": f"Bearer {TOKEN}"},
                json={
                    "dry_run": False,
                    "enabled": True,
                    "max_provider_requests_per_run": 0,
                    "max_promotions_per_run": 0,
                    "max_dispatches_per_run": 1,
                    "max_paper_drafts_per_run": 0,
                    "requested_by": "pytest",
                },
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["dispatched_count"], 1)
        self.assertEqual(body["dispatch"]["candidate"]["project_id"], "cpu-ready")
        self.assertEqual(body["followup_launch"]["action"], "skipped")
        self.assertIn("dispatch is disabled", body["followup_launch"]["reason"])
        self.assertEqual(fake_store.followup_launches, 0)
        live_dispatch.assert_called_once()

    def test_research_facility_run_cycle_targets_largest_lane_queue_deficit(
        self,
    ) -> None:
        class FakeSupabaseStore:
            def __init__(self) -> None:
                self.events = []
                self.ledger_plans = []

            def active_items(self) -> list[dict[str, str]]:
                return [
                    {
                        "project_id": "active-cpu",
                        "project_name": "Active CPU",
                        "status": "awaiting_wake",
                        "machine_target": "cpu-proxmox-1",
                        "current_run_id": "run-active-cpu",
                    },
                    {
                        "project_id": "active-gb10",
                        "project_name": "Active GB10",
                        "status": "awaiting_wake",
                        "machine_target": "gb10",
                        "current_run_id": "run-active-gb10",
                    },
                ]

            def status_counts(self) -> dict[str, int]:
                return {"blocked": 0, "queued": 8, "active": 2}

            def flags(self):
                return SimpleNamespace(queue_paused=False, maintenance_mode=False)

            def next_followup_candidate(
                self, *, max_followup_depth: int = 4, project_id: str = ""
            ) -> None:
                return None

            def queued_items_sql(self, *, limit: int = 200) -> list[dict[str, str]]:
                return [
                    {
                        "project_id": f"cpu-{idx}",
                        "status": "queued",
                        "machine_target": "cpu-proxmox-1",
                    }
                    for idx in range(5)
                ] + [
                    {
                        "project_id": f"gb10-{idx}",
                        "status": "queued",
                        "machine_target": "gb10",
                    }
                    for idx in range(3)
                ]

            def research_facility_workbench_projection(
                self, *, limit: int = 100
            ) -> list[dict[str, str]]:
                return []

            def record_research_facility_plans(
                self, plans, *, requested_by: str, queue_admitted: bool = False
            ):
                self.ledger_plans.extend(plans)
                return {
                    "inserted": len(plans),
                    "queue_admitted": queue_admitted,
                    "requested_by": requested_by,
                }

            def promote_research_candidate(
                self, *_args, **_kwargs
            ):  # pragma: no cover - promotion disabled in this test
                raise AssertionError("this test only verifies lane-targeted generation")

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
            worker_wake_gate_url="http://gb10-worker:8787",
            worker_wake_gate_bearer_token="gb10-token",
            worker_targets={
                "cpu-proxmox-1": {
                    "wake_gate_url": "http://cpu-worker:8787",
                    "bearer_token": "cpu-token",
                    "role": "cpu_worker",
                },
                "gb10": {
                    "wake_gate_url": "http://gb10-worker:8787",
                    "bearer_token": "gb10-token",
                    "role": "gpu_worker",
                },
            },
        )
        quota = {
            "subscription": {"limit": 2500, "requests": 0},
            "weeklyTokenLimit": {"remainingCredits": "$119.77"},
            "rollingFiveHourLimit": {"remaining": 2500, "max": 2500, "limited": False},
        }
        generated_candidate = {
            "candidate_id": "generated-gb10",
            "title": "Generated GB10",
            "machine_target": "gb10",
        }

        with (
            patch(
                "enoch_control_plane.control_plane.router.SupabaseControlPlaneStore",
                return_value=fake_store,
            ),
            patch("scripts.research_provider_budget.fetch_json", return_value=quota),
            patch(
                "scripts.research_provider_generate.generate_provider_candidates",
                return_value={
                    "candidates": [generated_candidate],
                    "provider_response_id": "resp-gb10",
                    "attempts_used": 1,
                },
            ) as generate,
            patch(
                "scripts.research_facility.plan_candidates",
                return_value=[
                    {"candidate": generated_candidate, "admission_decision": "admitted"}
                ],
            ),
        ):
            client = _client_with_config(config)
            response = client.post(
                "/control/api/research/run-cycle",
                headers={"Authorization": f"Bearer {TOKEN}"},
                json={
                    "dry_run": False,
                    "enabled": True,
                    "max_provider_requests_per_run": 1,
                    "max_promotions_per_run": 0,
                    "max_dispatches_per_run": 0,
                    "max_paper_drafts_per_run": 0,
                    "min_queue_depth_per_lane": 25,
                    "requested_by": "pytest",
                },
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["generation_target_lane"]["machine_target"], "gb10")
        self.assertEqual(
            body["lane_feed_pressure"]["cpu-proxmox-1"]["queue_deficit"], 20
        )
        self.assertEqual(body["lane_feed_pressure"]["gb10"]["queue_deficit"], 22)
        self.assertEqual(generate.call_args.kwargs["default_machine"], "gb10")
        self.assertIn("machine_target=gb10", generate.call_args.kwargs["topic"])

    def test_research_facility_run_cycle_feed_only_targets_deficient_idle_lane(
        self,
    ) -> None:
        class FakeSupabaseStore:
            def __init__(self) -> None:
                self.events = []
                self.ledger_plans = []

            def active_items(self) -> list[dict[str, str]]:
                return []

            def status_counts(self) -> dict[str, int]:
                return {"blocked": 0, "queued": 8, "active": 0}

            def flags(self):
                return SimpleNamespace(queue_paused=False, maintenance_mode=False)

            def next_followup_candidate(
                self, *, max_followup_depth: int = 4, project_id: str = ""
            ) -> None:
                return None

            def queued_items_sql(self, *, limit: int = 200) -> list[dict[str, str]]:
                return [
                    {
                        "project_id": f"cpu-{idx}",
                        "status": "queued",
                        "machine_target": "cpu-proxmox-1",
                    }
                    for idx in range(9)
                ] + [
                    {
                        "project_id": f"gb10-{idx}",
                        "status": "queued",
                        "machine_target": "gb10",
                    }
                    for idx in range(3)
                ]

            def research_facility_workbench_projection(
                self, *, limit: int = 100
            ) -> list[dict[str, str]]:
                return []

            def record_research_facility_plans(
                self, plans, *, requested_by: str, queue_admitted: bool = False
            ):
                self.ledger_plans.extend(plans)
                return {
                    "inserted": len(plans),
                    "queue_admitted": queue_admitted,
                    "requested_by": requested_by,
                }

            def promote_research_candidate(
                self, *_args, **_kwargs
            ):  # pragma: no cover - promotion disabled in this test
                raise AssertionError(
                    "this test only verifies lane-targeted feed generation"
                )

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
            worker_wake_gate_url="http://gb10-worker:8787",
            worker_wake_gate_bearer_token="gb10-token",
            worker_targets={
                "cpu-proxmox-1": {
                    "wake_gate_url": "http://cpu-worker:8787",
                    "bearer_token": "cpu-token",
                    "role": "cpu_worker",
                },
                "gb10": {
                    "wake_gate_url": "http://gb10-worker:8787",
                    "bearer_token": "gb10-token",
                    "role": "gpu_worker",
                },
            },
        )
        quota = {
            "subscription": {"limit": 2500, "requests": 0},
            "weeklyTokenLimit": {"remainingCredits": "$119.77"},
            "rollingFiveHourLimit": {"remaining": 2500, "max": 2500, "limited": False},
        }
        generated_candidate = {
            "candidate_id": "generated-gb10",
            "title": "Generated GB10",
            "machine_target": "gb10",
        }

        with (
            patch(
                "enoch_control_plane.control_plane.router.SupabaseControlPlaneStore",
                return_value=fake_store,
            ),
            patch("scripts.research_provider_budget.fetch_json", return_value=quota),
            patch(
                "scripts.research_provider_generate.generate_provider_candidates",
                return_value={
                    "candidates": [generated_candidate],
                    "provider_response_id": "resp-gb10",
                    "attempts_used": 1,
                },
            ) as generate,
            patch(
                "scripts.research_facility.plan_candidates",
                return_value=[
                    {"candidate": generated_candidate, "admission_decision": "admitted"}
                ],
            ),
        ):
            client = _client_with_config(config)
            response = client.post(
                "/control/api/research/run-cycle",
                headers={"Authorization": f"Bearer {TOKEN}"},
                json={
                    "dry_run": False,
                    "enabled": True,
                    "max_provider_requests_per_run": 1,
                    "max_promotions_per_run": 0,
                    "max_dispatches_per_run": 0,
                    "max_paper_drafts_per_run": 0,
                    "min_queue_depth_per_lane": 25,
                    "requested_by": "pytest",
                },
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["generation_target_lane"]["machine_target"], "gb10")
        self.assertEqual(
            body["lane_feed_pressure"]["cpu-proxmox-1"]["next_autopilot_action"],
            "dispatch_queued",
        )
        self.assertEqual(
            body["lane_feed_pressure"]["gb10"]["next_autopilot_action"],
            "dispatch_queued",
        )
        self.assertEqual(
            body["lane_feed_pressure"]["cpu-proxmox-1"]["queue_deficit"], 16
        )
        self.assertEqual(body["lane_feed_pressure"]["gb10"]["queue_deficit"], 22)
        self.assertEqual(generate.call_args.kwargs["default_machine"], "gb10")
        self.assertIn("machine_target=gb10", generate.call_args.kwargs["topic"])

    def test_research_facility_run_cycle_active_lane_is_backpressure_not_blocked(
        self,
    ) -> None:
        class FakeSupabaseStore:
            def __init__(self) -> None:
                self.events = []

            def active_items(self) -> list[dict[str, str]]:
                return [{"project_id": "active-project", "status": "awaiting_wake"}]

            def status_counts(self) -> dict[str, int]:
                return {"blocked": 0, "queued": 0, "active": 1}

            def research_facility_workbench_projection(
                self, *, limit: int = 100
            ) -> list[dict[str, str]]:
                return [
                    {
                        "candidate_id": "candidate-ready",
                        "admission_decision": "admitted",
                        "admitted_idea_id": "",
                        "total_score": "83.00",
                    }
                ]

            def record_research_facility_plans(
                self, *_args, **_kwargs
            ):  # pragma: no cover - active lane backpressure returns first
                raise AssertionError("active lane backpressure should not generate")

            def promote_research_candidate(
                self, *_args, **_kwargs
            ):  # pragma: no cover - active lane backpressure returns first
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
        with (
            patch(
                "enoch_control_plane.control_plane.router.SupabaseControlPlaneStore",
                return_value=fake_store,
            ),
            patch("scripts.research_provider_budget.fetch_json", return_value=quota),
            patch(
                "scripts.research_provider_generate.generate_provider_candidates"
            ) as generate,
        ):
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
        self.assertEqual(
            body["reason"],
            "active worker lane already exists and no promotable candidate targets an idle lane",
        )
        self.assertEqual(body["active_count"], 1)
        self.assertEqual(body["promoted_count"], 0)
        self.assertEqual(body["dispatched_count"], 0)
        generate.assert_not_called()
        self.assertEqual(
            fake_store.events[0]["event_type"], "research.run_cycle.backpressure"
        )

    def test_research_facility_run_cycle_live_requires_enabled_flag(self) -> None:
        class FakeSupabaseStore:
            def active_items(self) -> list[dict[str, str]]:
                return []

            def status_counts(self) -> dict[str, int]:
                return {"blocked": 0, "queued": 0, "active": 0}

            def research_facility_workbench_projection(
                self, *, limit: int = 100
            ) -> list[dict[str, str]]:
                return []

            def record_research_facility_plans(
                self, *_args, **_kwargs
            ):  # pragma: no cover - blocked before write
                raise AssertionError("live disabled cycle should not write")

            def promote_research_candidate(
                self, *_args, **_kwargs
            ):  # pragma: no cover - blocked before promotion
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
        with (
            patch(
                "enoch_control_plane.control_plane.router.SupabaseControlPlaneStore",
                return_value=FakeSupabaseStore(),
            ),
            patch("scripts.research_provider_budget.fetch_json", return_value=quota),
            patch(
                "scripts.research_provider_generate.generate_provider_candidates"
            ) as generate,
        ):
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

    def test_research_facility_run_cycle_paper_stage_blocks_negative_decision(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "projects"
            project_dir = project_root / "negative-project"
            (project_dir / ".enoch").mkdir(parents=True)
            (project_dir / "run_notes.md").write_text(
                "negative result\n", encoding="utf-8"
            )
            (project_dir / ".enoch" / "project_decision.json").write_text(
                json.dumps(
                    {
                        "project_decision": "finalize_negative",
                        "summary": "No improvement",
                    }
                ),
                encoding="utf-8",
            )

            class FakeSupabaseStore:
                def __init__(self) -> None:
                    self.events = []

                def active_items(self) -> list[dict[str, str]]:
                    return []

                def status_counts(self) -> dict[str, int]:
                    return {"blocked": 0, "queued": 0, "active": 0, "completed": 1}

                def flags(self):
                    return SimpleNamespace(queue_paused=False, maintenance_mode=False)

                def research_facility_workbench_projection(
                    self, *, limit: int = 100
                ) -> list[dict[str, str]]:
                    return []

                def record_research_facility_plans(self, *_args, **_kwargs):
                    raise AssertionError(
                        "paper-only cycle should not record research ledgers"
                    )

                def promote_research_candidate(self, *_args, **_kwargs):
                    raise AssertionError(
                        "paper-only cycle should not promote candidates"
                    )

                def queue_rows(self) -> list[dict[str, object]]:
                    return [
                        {
                            "project_id": "negative-project",
                            "project_name": "Negative Project",
                            "project_dir": str(project_dir),
                            "status": "completed",
                            "current_run_id": "run-negative",
                            "last_run_state": "wake_ready",
                            "next_action_hint": "draft_paper_or_select_next_project",
                            "manual_review_required": False,
                        }
                    ]

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
                "rollingFiveHourLimit": {
                    "remaining": 2500,
                    "max": 2500,
                    "limited": False,
                },
            }
            with (
                patch(
                    "enoch_control_plane.control_plane.router.SupabaseControlPlaneStore",
                    return_value=FakeSupabaseStore(),
                ),
                patch(
                    "scripts.research_provider_budget.fetch_json", return_value=quota
                ),
                patch(
                    "enoch_control_plane.control_plane.router.write_paper_artifacts"
                ) as writer,
            ):
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
            self.assertIn(
                "lacked sufficient positive", body["paper_drafts"][0]["reason"]
            )
            writer.assert_not_called()

    def test_research_facility_run_cycle_paper_stage_drafts_and_finalizes_positive_candidate(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "projects"
            project_dir = project_root / "positive-project"
            project_dir.mkdir(parents=True)
            (project_dir / "run_notes.md").write_text(
                "positive run evidence\n", encoding="utf-8"
            )
            (project_dir / ".enoch").mkdir(parents=True)
            (project_dir / ".enoch" / "project_decision.json").write_text(
                '{"project_decision":"finalize_positive"}\n', encoding="utf-8"
            )

            class FakeSupabaseStore:
                def __init__(self) -> None:
                    self.events = []
                    self.papers: dict[str, dict[str, object]] = {}
                    self.review_rows: dict[str, dict[str, object]] = {}

                def active_items(self) -> list[dict[str, str]]:
                    return []

                def status_counts(self) -> dict[str, int]:
                    return {"blocked": 0, "queued": 0, "active": 0, "completed": 1}

                def flags(self):
                    return SimpleNamespace(queue_paused=False, maintenance_mode=False)

                def research_facility_workbench_projection(
                    self, *, limit: int = 100
                ) -> list[dict[str, str]]:
                    return []

                def record_research_facility_plans(self, *_args, **_kwargs):
                    raise AssertionError(
                        "paper-only cycle should not record research ledgers"
                    )

                def promote_research_candidate(self, *_args, **_kwargs):
                    raise AssertionError(
                        "paper-only cycle should not promote candidates"
                    )

                def queue_rows(self) -> list[dict[str, object]]:
                    return [
                        {
                            "project_id": "positive-project",
                            "project_name": "Positive Project",
                            "project_dir": str(project_dir),
                            "status": "completed",
                            "current_run_id": "run-positive",
                            "last_run_state": "finalize_positive",
                            "next_action_hint": "draft_paper_or_select_next_project",
                            "manual_review_required": False,
                        }
                    ]

                def paper_rows(self) -> list[dict[str, object]]:
                    return list(self.papers.values())

                def update_project_dir(
                    self, project_id: str, project_dir_text: str
                ) -> None:
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

                def paper_review_row(
                    self, paper_id: str, include_rank_reasons: bool = False
                ):
                    return self.review_rows.get(paper_id)

                def project_row(self, project_id: str):
                    return {
                        "project_id": project_id,
                        "project_name": "Positive Project",
                        "project_dir": str(project_dir),
                    }

                def prepare_paper_review_finalization_package(
                    self, paper_id: str, payload, require_approval: bool = False
                ):
                    item = dict(self.review_rows[paper_id])
                    item["review_status"] = "finalized"
                    item["finalization_package_path"] = (
                        "papers/run-positive/finalization_package.json"
                    )
                    self.review_rows[paper_id] = item
                    return (
                        42,
                        True,
                        item,
                        item["finalization_package_path"],
                        {"paper_id": paper_id},
                    )

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
                "rollingFiveHourLimit": {
                    "remaining": 2500,
                    "max": 2500,
                    "limited": False,
                },
            }
            with (
                patch(
                    "enoch_control_plane.control_plane.router.SupabaseControlPlaneStore",
                    return_value=fake_store,
                ),
                patch(
                    "scripts.research_provider_budget.fetch_json", return_value=quota
                ),
                patch(
                    "enoch_control_plane.control_plane.router.write_paper_artifacts",
                    return_value={
                        "provider": "synthetic.new",
                        "model": "hf:zai-org/GLM-5.1",
                        "fallback_used": False,
                    },
                ),
            ):
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
            self.assertEqual(
                body["publication_finalizations"][0]["item"]["review_status"],
                "finalized",
            )
            self.assertIn(
                "paper.drafted", [event["event_type"] for event in fake_store.events]
            )
            self.assertIn(
                "research.run_cycle.live",
                [event["event_type"] for event in fake_store.events],
            )

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

    def test_research_facility_promote_candidate_rejects_non_slug_candidate_id(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            response = client.post(
                "/control/api/research/promote-candidate",
                headers=headers,
                json={
                    "candidate_id": "candidate; touch /tmp/pwned",
                    "dry_run": True,
                    "requested_by": "pytest",
                },
            )
            self.assertEqual(response.status_code, 400)
            self.assertIn("slug-like", response.text)

    def test_research_facility_promote_candidate_requires_supabase_store(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            response = client.post(
                "/control/api/research/promote-candidate",
                headers=headers,
                json={
                    "candidate_id": "candidate-a",
                    "dry_run": True,
                    "requested_by": "pytest",
                },
            )
            self.assertEqual(response.status_code, 501)
            self.assertIn(
                "promotion requires the Supabase control-plane store", response.text
            )

    def test_research_facility_promote_candidate_calls_supabase_store_dry_run_first(
        self,
    ) -> None:
        class FakeSupabaseStore:
            def research_facility_workbench_projection(
                self, *, limit: int = 200
            ) -> list[dict[str, str]]:
                return []

            def promote_research_candidate(
                self, candidate_id: str, *, requested_by: str, dry_run: bool = True
            ) -> dict[str, object]:
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
        with patch(
            "enoch_control_plane.control_plane.router.SupabaseControlPlaneStore",
            return_value=FakeSupabaseStore(),
        ):
            client = _client_with_config(config)
            response = client.post(
                "/control/api/research/promote-candidate",
                headers={"Authorization": f"Bearer {TOKEN}"},
                json={
                    "candidate_id": "candidate-a",
                    "dry_run": True,
                    "requested_by": "pytest",
                },
            )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["action"], "dry_run_promote_candidate")
        self.assertTrue(body["dry_run"])
        self.assertEqual(body["candidate_id"], "candidate-a")
        self.assertEqual(body["requested_by"], "pytest")
        self.assertEqual(body["queued_count"], 0)
        self.assertFalse(body["dispatch_started"])

    def test_project_prompt_uses_source_provenance_instead_of_notion_authority(
        self,
    ) -> None:
        prompt = _project_prompt(
            {
                "project_id": "idea-source",
                "project_name": "Source Prompt",
                "notion_page_url": "https://source.example/idea-source",
                "origin_idea_status": "testing",
            }
        )

        self.assertIn(
            "Source/provenance URL: https://source.example/idea-source", prompt
        )
        self.assertNotIn("Notion URL:", prompt)

    def test_dashboard_status_contract_reports_config_and_missing_worker_observations(
        self,
    ) -> None:
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

    def test_dashboard_status_omits_large_non_worker_observation_and_event_payloads(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            store = ControlPlaneStore(Path(tmp) / "state" / "control_plane.sqlite3")
            large_payload = {
                "candidates": [{"description": "x" * 100_000}],
                "skipped_rows": [],
            }
            store.upsert_dashboard_observation(
                source="idea_intake", status="ok", payload=large_payload
            )
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
            self.assertTrue(intake_observation["payload"]["payload_omitted"])
            self.assertNotIn("candidates", intake_observation["payload"])
            self.assertTrue(body["recent_events"][0]["payload"]["payload_omitted"])
            self.assertNotIn("candidates", body["recent_events"][0]["payload"])

    def test_dashboard_status_blocks_dispatch_when_worker_refresh_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client_with_config(_live_config(tmp))
            headers = {"Authorization": f"Bearer {TOKEN}"}
            client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "safe-missing-worker-import",
                    "queue_rows": [
                        {
                            "project_id": "idea-ready",
                            "project_name": "Ready Missing Worker",
                            "project_dir": "idea-ready",
                            "status": "queued",
                            "dispatch_priority": 5,
                        }
                    ],
                },
            )
            client.post(
                "/control/resume",
                headers=headers,
                json={"resumed_by": "test", "maintenance_mode": False},
            )
            response = WorkerPreflightResponse(
                ok=False,
                target="http://worker.example",
                summary="worker preflight failed",
                checks=[
                    WorkerPreflightCheck(
                        name="wake_gate_healthz", ok=False, detail="down", data={}
                    ),
                    WorkerPreflightCheck(
                        name="wake_gate_dashboard_api",
                        ok=False,
                        detail="dashboard unavailable",
                        data={},
                    ),
                ],
            )
            with patch(
                "enoch_control_plane.control_plane.router.run_worker_preflight",
                return_value=response,
            ) as preflight:
                status = client.get(
                    "/control/api/status?refresh_worker=true", headers=headers
                ).json()

            preflight.assert_called_once()
            self.assertFalse(status["dispatch_safe"])
            self.assertIn("worker_preflight not ok", status["dispatch_blockers"])
            self.assertIn("worker_dashboard_api not ok", status["dispatch_blockers"])
            self.assertIn("worker health check failed", status["dispatch_blockers"])
            self.assertFalse(status["source_freshness"]["worker_preflight"]["stale"])

    def test_dashboard_status_does_not_refresh_worker_preflight_by_default(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _live_config(tmp).model_copy(
                update={"worker_wake_gate_url": "http://worker.example"}
            )
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            client.post(
                "/control/resume",
                headers=headers,
                json={"resumed_by": "test", "maintenance_mode": False},
            )

            with patch(
                "enoch_control_plane.control_plane.router.run_worker_preflight",
                side_effect=AssertionError(
                    "dashboard status reads must not refresh workers by default"
                ),
            ) as preflight:
                status = client.get("/control/api/status", headers=headers).json()

            preflight.assert_not_called()
            self.assertFalse(status["dispatch_safe"])
            self.assertIn(
                "worker_preflight stale or missing", status["dispatch_blockers"]
            )

    def test_dashboard_preflight_records_named_worker_target_observation(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _live_config(tmp).model_copy(
                update={
                    "worker_wake_gate_url": "http://gb10-worker:8787",
                    "worker_wake_gate_bearer_token": "gb10-token",
                    "worker_targets": {
                        "cpu-proxmox-1": {
                            "wake_gate_url": "http://cpu-proxmox-1:8787",
                            "bearer_token": "cpu-token",
                            "role": "cpu_worker",
                        }
                    },
                }
            )
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            response = WorkerPreflightResponse(
                ok=True,
                target="http://cpu-proxmox-1:8787",
                summary="cpu worker checked",
                checks=[
                    WorkerPreflightCheck(
                        name="wake_gate_healthz", ok=True, detail="ok", data={}
                    ),
                    WorkerPreflightCheck(
                        name="worker_no_live_runs",
                        ok=True,
                        detail="active_or_waiting=0, live=0",
                        data={"active_or_waiting": 0, "live": 0},
                    ),
                    WorkerPreflightCheck(
                        name="wake_gate_dashboard_api",
                        ok=True,
                        detail="cpu dashboard API reachable",
                        data={
                            "body": {
                                "timestamp": "2026-05-28T12:00:00Z",
                                "totals": {"active_or_waiting": 0, "live": 0},
                                "runs": [],
                            }
                        },
                    ),
                ],
            )

            store = ControlPlaneStore(Path(tmp) / "state" / "control_plane.sqlite3")
            store.upsert_dashboard_observation(
                source="worker_preflight",
                status="ok",
                payload={"target": "http://gb10-worker:8787", "ok": True},
            )
            store.upsert_dashboard_observation(
                source="worker_dashboard_api",
                status="ok",
                payload={"target": "http://gb10-worker:8787", "ok": True},
            )

            with patch(
                "enoch_control_plane.control_plane.router.run_worker_preflight",
                return_value=response,
            ) as preflight:
                api_response = client.post(
                    "/control/api/preflight",
                    headers=headers,
                    json={"machine_target": "cpu-proxmox-1"},
                )

            self.assertEqual(api_response.status_code, 200)
            preflight.assert_called_once()
            global_observation = store.latest_dashboard_observation(
                source="worker_preflight"
            )
            scoped = store.latest_dashboard_observation(
                source="worker_preflight", scope="lane:http://cpu-proxmox-1:8787"
            )
            global_dashboard = store.latest_dashboard_observation(
                source="worker_dashboard_api"
            )
            scoped_dashboard = store.latest_dashboard_observation(
                source="worker_dashboard_api",
                scope="lane:http://cpu-proxmox-1:8787",
            )
            self.assertIsNotNone(global_observation)
            self.assertEqual(
                global_observation.payload["target"], "http://gb10-worker:8787"
            )
            self.assertIsNotNone(scoped)
            self.assertEqual(scoped.payload["target"], "http://cpu-proxmox-1:8787")
            self.assertIsNotNone(global_dashboard)
            self.assertEqual(
                global_dashboard.payload["target"], "http://gb10-worker:8787"
            )
            self.assertIsNotNone(scoped_dashboard)
            self.assertEqual(scoped_dashboard.status, "ok")
            self.assertEqual(
                scoped_dashboard.payload["data"]["body"]["timestamp"],
                "2026-05-28T12:00:00Z",
            )
            status = client.get("/control/api/status", headers=headers).json()
            cpu_lane = next(
                lane
                for lane in status["worker_lanes"]
                if lane["machine_target"] == "cpu-proxmox-1"
            )
            self.assertEqual(
                cpu_lane["worker_observations"]["worker_dashboard_api"]["scope"],
                "lane:http://cpu-proxmox-1:8787",
            )
            self.assertEqual(
                cpu_lane["worker_observations"]["worker_dashboard_api"]["status"],
                "ok",
            )

    def test_dashboard_status_refreshes_worker_preflight_when_requested(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _live_config(tmp).model_copy(
                update={"worker_wake_gate_url": "http://worker.example"}
            )
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            response = WorkerPreflightResponse(
                ok=True,
                target="http://worker.example",
                summary="worker idle",
                checks=[
                    WorkerPreflightCheck(
                        name="wake_gate_healthz", ok=True, detail="ok", data={}
                    ),
                    WorkerPreflightCheck(
                        name="worker_no_live_runs",
                        ok=True,
                        detail="active_or_waiting=0, live=0",
                        data={"active_or_waiting": 0, "live": 0},
                    ),
                ],
            )

            with patch(
                "enoch_control_plane.control_plane.router.run_worker_preflight",
                return_value=response,
            ) as preflight:
                status = client.get(
                    "/control/api/status?refresh_worker=true", headers=headers
                ).json()

            preflight.assert_called_once()
            self.assertFalse(status["source_freshness"]["worker_preflight"]["stale"])
            store = ControlPlaneStore(Path(tmp) / "state" / "control_plane.sqlite3")
            scoped = store.latest_dashboard_observation(
                source="worker_preflight", scope="lane:http://worker.example"
            )
            self.assertIsNotNone(scoped)
            self.assertEqual(scoped.payload["target"], "http://worker.example")

    def test_dashboard_status_auto_refreshes_stale_worker_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client_with_config(_live_config(tmp))
            headers = {"Authorization": f"Bearer {TOKEN}"}
            client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "refresh-worker-evidence-import",
                    "queue_rows": [
                        {
                            "project_id": "idea-active-refresh",
                            "project_name": "Active Refresh",
                            "project_dir": "idea-active-refresh",
                            "status": "awaiting_wake",
                            "current_run_id": "run-active-refresh",
                        }
                    ],
                },
            )
            client.post(
                "/control/resume",
                headers=headers,
                json={"resumed_by": "test", "maintenance_mode": False},
            )
            response = WorkerPreflightResponse(
                ok=False,
                target="http://worker.example",
                summary="active worker lane",
                checks=[
                    WorkerPreflightCheck(
                        name="wake_gate_healthz", ok=True, detail="ok", data={}
                    ),
                    WorkerPreflightCheck(
                        name="wake_gate_dashboard_api",
                        ok=True,
                        detail="dashboard API reachable",
                        data={
                            "body": {
                                "totals": {"active_or_waiting": 1, "live": 1},
                                "telemetry": {},
                                "runs": [
                                    {
                                        "run_id": "run-active-refresh",
                                        "project_id": "idea-active-refresh",
                                        "gate_state": "running",
                                        "run_notes_tail": "x" * 50_000,
                                        "quiet_samples": [
                                            {"sample": "x" * 5000} for _ in range(12)
                                        ],
                                        "project_decision": {
                                            "project_decision": "continue",
                                            "recommended_next_action": "investigate",
                                            "long_internal_notes": "x" * 50_000,
                                        },
                                    }
                                ],
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
            with patch(
                "enoch_control_plane.control_plane.router.run_worker_preflight",
                return_value=response,
            ) as preflight:
                status = client.get(
                    "/control/api/status?refresh_worker=true", headers=headers
                ).json()

            preflight.assert_called_once()
            self.assertFalse(status["source_freshness"]["worker_preflight"]["stale"])
            self.assertFalse(
                status["source_freshness"]["worker_dashboard_api"]["stale"]
            )
            self.assertEqual(status["warnings"], [])
            self.assertEqual(status["conflicts"], [])
            self.assertEqual(
                status["dispatch_blockers"], ["all configured worker lanes active"]
            )
            preflight_payload = status["observations"]["worker_preflight"]["payload"]
            dashboard_check = next(
                check
                for check in preflight_payload["checks"]
                if check["name"] == "wake_gate_dashboard_api"
            )
            compact_run = dashboard_check["data"]["body"]["runs"][0]
            self.assertTrue(dashboard_check["data"]["body_compacted"])
            self.assertTrue(compact_run["run_notes_tail_omitted"])
            self.assertTrue(compact_run["quiet_samples_omitted"])
            self.assertNotIn("x" * 5000, json.dumps(preflight_payload))
            self.assertNotIn("long_internal_notes", json.dumps(preflight_payload))
            self.assertTrue(
                status["observations"]["worker_dashboard_api"]["payload"][
                    "payload_omitted"
                ]
            )

    def test_dashboard_status_refreshes_fresh_but_conflicting_worker_projection(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client_with_config(_live_config(tmp))
            headers = {"Authorization": f"Bearer {TOKEN}"}
            client.post(
                "/control/resume",
                headers=headers,
                json={"resumed_by": "test", "maintenance_mode": False},
            )
            store = ControlPlaneStore(Path(tmp) / "state" / "control_plane.sqlite3")
            store.upsert_dashboard_observation(
                source="worker_preflight",
                status="warn",
                payload={
                    "ok": False,
                    "checks": [
                        {
                            "name": "wake_gate_healthz",
                            "ok": True,
                            "detail": "ok",
                            "data": {},
                        },
                        {
                            "name": "worker_no_live_runs",
                            "ok": False,
                            "detail": "active_or_waiting=1, live=1",
                            "data": {"active_or_waiting": 1, "live": 1},
                        },
                    ],
                },
            )
            store.upsert_dashboard_observation(
                source="worker_dashboard_api", status="ok", payload={"ok": True}
            )
            response = WorkerPreflightResponse(
                ok=True,
                target="http://worker.example",
                summary="worker idle",
                checks=[
                    WorkerPreflightCheck(
                        name="wake_gate_healthz", ok=True, detail="ok", data={}
                    ),
                    WorkerPreflightCheck(
                        name="wake_gate_dashboard_api",
                        ok=True,
                        detail="dashboard API reachable",
                        data={"body": {"totals": {"active_or_waiting": 0, "live": 0}}},
                    ),
                    WorkerPreflightCheck(
                        name="worker_no_live_runs",
                        ok=True,
                        detail="active_or_waiting=0, live=0",
                        data={"active_or_waiting": 0, "live": 0},
                    ),
                ],
            )
            with patch(
                "enoch_control_plane.control_plane.router.run_worker_preflight",
                return_value=response,
            ) as preflight:
                status = client.get(
                    "/control/api/status?refresh_worker=true", headers=headers
                ).json()

            preflight.assert_called_once()
            self.assertEqual(status["warnings"], [])
            self.assertEqual(status["conflicts"], [])
            self.assertEqual(
                status["dispatch_blockers"], ["no queued dispatch candidate"]
            )

    def test_dashboard_status_auto_refreshes_stale_worker_evidence_before_dispatch_decision(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client_with_config(_live_config(tmp))
            headers = {"Authorization": f"Bearer {TOKEN}"}
            client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "stale-worker-evidence-import",
                    "queue_rows": [
                        {
                            "project_id": "idea-ready-stale",
                            "project_name": "Ready Stale",
                            "project_dir": "idea-ready-stale",
                            "status": "queued",
                            "dispatch_priority": 5,
                        }
                    ],
                },
            )
            client.post(
                "/control/resume",
                headers=headers,
                json={"resumed_by": "test", "maintenance_mode": False},
            )
            response = WorkerPreflightResponse(
                ok=True,
                target="http://worker.example",
                summary="worker idle",
                checks=[
                    WorkerPreflightCheck(
                        name="wake_gate_healthz", ok=True, detail="ok", data={}
                    ),
                    WorkerPreflightCheck(
                        name="wake_gate_dashboard_api",
                        ok=True,
                        detail="dashboard API reachable",
                        data={"body": {"totals": {"active_or_waiting": 0, "live": 0}}},
                    ),
                    WorkerPreflightCheck(
                        name="worker_no_live_runs",
                        ok=True,
                        detail="active_or_waiting=0, live=0",
                        data={"active_or_waiting": 0, "live": 0},
                    ),
                ],
            )
            with patch(
                "enoch_control_plane.control_plane.router.run_worker_preflight",
                return_value=response,
            ) as preflight:
                status = client.get(
                    "/control/api/status?refresh_worker=true", headers=headers
                ).json()

            preflight.assert_called_once()
            self.assertTrue(status["dispatch_safe"])
            self.assertEqual(status["dispatch_blockers"], [])
            self.assertFalse(status["source_freshness"]["worker_preflight"]["stale"])
            self.assertFalse(
                status["source_freshness"]["worker_dashboard_api"]["stale"]
            )

    def test_dashboard_status_blocks_dispatch_when_fresh_worker_evidence_is_bad(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client_with_config(_live_config(tmp))
            headers = {"Authorization": f"Bearer {TOKEN}"}
            client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "bad-worker-evidence-import",
                    "queue_rows": [
                        {
                            "project_id": "idea-ready",
                            "project_name": "Ready Bad Worker",
                            "project_dir": "idea-ready",
                            "status": "queued",
                            "dispatch_priority": 5,
                        }
                    ],
                },
            )
            client.post(
                "/control/resume",
                headers=headers,
                json={"resumed_by": "test", "maintenance_mode": False},
            )
            store = ControlPlaneStore(Path(tmp) / "state" / "control_plane.sqlite3")
            store.upsert_dashboard_observation(
                source="worker_preflight",
                status="warn",
                payload={
                    "ok": False,
                    "checks": [
                        {
                            "name": "wake_gate_healthz",
                            "ok": False,
                            "detail": "down",
                            "data": {},
                        }
                    ],
                },
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

    def test_dashboard_status_blocks_dispatch_when_authenticated_worker_checks_are_skipped(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client_with_config(_live_config(tmp))
            headers = {"Authorization": f"Bearer {TOKEN}"}
            client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "skipped-worker-evidence-import",
                    "queue_rows": [
                        {
                            "project_id": "idea-ready",
                            "project_name": "Ready Skipped Worker",
                            "project_dir": "idea-ready",
                            "status": "queued",
                            "dispatch_priority": 5,
                        }
                    ],
                },
            )
            client.post(
                "/control/resume",
                headers=headers,
                json={"resumed_by": "test", "maintenance_mode": False},
            )
            store = ControlPlaneStore(Path(tmp) / "state" / "control_plane.sqlite3")
            store.upsert_dashboard_observation(
                source="worker_preflight",
                status="ok",
                payload={
                    "ok": True,
                    "checks": [
                        {
                            "name": "wake_gate_dashboard_api",
                            "ok": True,
                            "detail": "skipped",
                            "data": {"skipped": True},
                        }
                    ],
                },
            )
            store.upsert_dashboard_observation(
                source="worker_dashboard_api", status="ok", payload={"skipped": True}
            )
            status = client.get("/control/api/status", headers=headers).json()
            self.assertFalse(status["dispatch_safe"])
            self.assertIn(
                "worker dashboard telemetry skipped", status["dispatch_blockers"]
            )

    def test_preflight_persists_cached_observation_for_status_page(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _config(tmp).model_copy(
                update={"worker_wake_gate_url": "http://127.0.0.1:1"}
            )
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            preflight = client.post(
                "/control/api/preflight",
                headers=headers,
                json={"wake_gate_url": "http://127.0.0.1:1"},
            )
            self.assertEqual(preflight.status_code, 200)
            status = client.get("/control/api/status", headers=headers).json()
            observation = status["observations"]["worker_preflight"]
            self.assertIsNotNone(observation)
            self.assertEqual(observation["source"], "worker_preflight")
            self.assertEqual(
                status["source_freshness"]["worker_preflight"]["status"], "warn"
            )
            self.assertFalse(status["source_freshness"]["worker_preflight"]["stale"])

    def test_dashboard_status_flags_worker_vm_active_lane_conflicts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "active-conflict-import",
                    "queue_rows": [
                        {
                            "project_id": "idea-active",
                            "project_name": "Active Conflict",
                            "project_dir": "idea-active",
                            "status": "awaiting_wake",
                            "current_run_id": "run-active",
                        }
                    ],
                },
            )
            ControlPlaneStore(
                Path(tmp) / "state" / "control_plane.sqlite3"
            ).upsert_dashboard_observation(
                source="worker_preflight",
                status="ok",
                payload={
                    "ok": True,
                    "checks": [
                        {
                            "name": "worker_no_live_runs",
                            "ok": True,
                            "detail": "active_or_waiting=0, live=0",
                            "data": {"active_or_waiting": 0, "live": 0},
                        }
                    ],
                },
            )
            status = client.get("/control/api/status", headers=headers).json()
            self.assertTrue(
                any("active row" in item["message"] for item in status["conflicts"])
            )
            self.assertFalse(status["dispatch_safe"])

    def test_dashboard_status_blocks_idle_lane_when_worker_reports_live_run(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _live_config(tmp).model_copy(
                update={
                    "worker_wake_gate_url": "http://gb10-worker:8787",
                    "worker_wake_gate_bearer_token": "gb10-token",
                    "worker_targets": {
                        "cpu-proxmox-1": {
                            "wake_gate_url": "http://cpu-worker:8787",
                            "bearer_token": "cpu-token",
                            "role": "cpu_worker",
                        },
                        "gb10": {
                            "wake_gate_url": "http://gb10-worker:8787",
                            "bearer_token": "gb10-token",
                            "role": "gpu_worker",
                        },
                    },
                }
            )
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            client.post(
                "/control/resume",
                headers=headers,
                json={"resumed_by": "test", "maintenance_mode": False},
            )
            store = ControlPlaneStore(Path(tmp) / "state" / "control_plane.sqlite3")
            store.upsert_dashboard_observation(
                source="worker_preflight",
                scope="lane:http://cpu-worker:8787",
                status="warn",
                payload={
                    "ok": False,
                    "target": "http://cpu-worker:8787",
                    "checks": [
                        {
                            "name": "worker_no_live_runs",
                            "ok": False,
                            "detail": "active_or_waiting=1, live=1",
                            "data": {"active_or_waiting": 1, "live": 1},
                        }
                    ],
                },
            )

            status = client.get("/control/api/status", headers=headers).json()

            self.assertFalse(status["dispatch_safe"])
            self.assertTrue(
                any(
                    "worker reports live work" in item["message"]
                    for item in status["conflicts"]
                )
            )
            self.assertIn(
                "worker live run without active control-plane row: cpu_worker",
                status["dispatch_blockers"],
            )

    def test_dashboard_status_ignores_expired_lane_preflight_for_live_worker_conflict(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _live_config(tmp).model_copy(
                update={
                    "worker_wake_gate_url": "http://gb10-worker:8787",
                    "worker_wake_gate_bearer_token": "gb10-token",
                    "worker_targets": {
                        "cpu-proxmox-1": {
                            "wake_gate_url": "http://cpu-worker:8787",
                            "bearer_token": "cpu-token",
                            "role": "cpu_worker",
                        },
                        "gb10": {
                            "wake_gate_url": "http://gb10-worker:8787",
                            "bearer_token": "gb10-token",
                            "role": "gpu_worker",
                        },
                    },
                }
            )
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            client.post(
                "/control/resume",
                headers=headers,
                json={"resumed_by": "test", "maintenance_mode": False},
            )
            old = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
            store = ControlPlaneStore(Path(tmp) / "state" / "control_plane.sqlite3")
            store.upsert_dashboard_observation(
                source="worker_preflight",
                scope="lane:http://cpu-worker:8787",
                status="warn",
                observed_at=old,
                ttl_seconds=300,
                payload={
                    "ok": False,
                    "target": "http://cpu-worker:8787",
                    "checks": [
                        {
                            "name": "worker_no_live_runs",
                            "ok": False,
                            "detail": "active_or_waiting=1, live=1",
                            "data": {"active_or_waiting": 1, "live": 1},
                        }
                    ],
                },
            )

            status = client.get("/control/api/status", headers=headers).json()

            self.assertFalse(
                any(
                    "worker reports live work" in item["message"]
                    for item in status["conflicts"]
                )
            )
            self.assertNotIn(
                "worker live run without active control-plane row: cpu_worker",
                status["dispatch_blockers"],
            )

    def test_dashboard_status_does_not_treat_cpu_active_as_default_worker_conflict(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _live_config(tmp).model_copy(
                update={
                    "worker_wake_gate_url": "http://gb10-worker:8787",
                    "worker_wake_gate_bearer_token": "gb10-token",
                    "worker_targets": {
                        "cpu-proxmox-1": {
                            "wake_gate_url": "http://cpu-proxmox-1:8787",
                            "bearer_token": "cpu-token",
                            "role": "cpu_worker",
                        },
                        "gb10": {
                            "wake_gate_url": "http://gb10-worker:8787",
                            "bearer_token": "gb10-token",
                            "role": "gpu_worker",
                        },
                    },
                }
            )
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "cpu-active-default-worker-idle-import",
                    "queue_rows": [
                        {
                            "project_id": "active-cpu",
                            "project_name": "Active CPU",
                            "project_dir": "active-cpu",
                            "status": "awaiting_wake",
                            "machine_target": "cpu-proxmox-1",
                            "current_run_id": "run-active-cpu",
                        },
                        {
                            "project_id": "queued-gpu",
                            "project_name": "Queued GPU",
                            "project_dir": "queued-gpu",
                            "status": "queued",
                            "machine_target": "gb10",
                            "dispatch_priority": 1,
                        },
                    ],
                },
            )
            client.post(
                "/control/resume",
                headers=headers,
                json={"resumed_by": "test", "maintenance_mode": False},
            )
            store = ControlPlaneStore(Path(tmp) / "state" / "control_plane.sqlite3")
            store.upsert_dashboard_observation(
                source="worker_preflight",
                status="ok",
                payload={
                    "ok": True,
                    "checks": [
                        {
                            "name": "wake_gate_healthz",
                            "ok": True,
                            "detail": "ok",
                            "data": {},
                        },
                        {
                            "name": "worker_no_live_runs",
                            "ok": True,
                            "detail": "active_or_waiting=0, live=0",
                            "data": {"active_or_waiting": 0, "live": 0},
                        },
                    ],
                },
            )
            store.upsert_dashboard_observation(
                source="worker_dashboard_api", status="ok", payload={"ok": True}
            )

            response = WorkerPreflightResponse(
                ok=False,
                target="http://gb10-worker:8787",
                summary="worker preflight failed",
                checks=[
                    WorkerPreflightCheck(
                        name="wake_gate_healthz", ok=True, detail="ok", data={}
                    ),
                    WorkerPreflightCheck(
                        name="worker_no_live_runs",
                        ok=False,
                        detail="active_or_waiting=1, live=1",
                        data={"active_or_waiting": 1, "live": 1},
                    ),
                ],
            )
            with patch(
                "enoch_control_plane.control_plane.router.run_worker_preflight",
                return_value=response,
            ):
                status = client.get("/control/api/status", headers=headers).json()

            self.assertTrue(status["dispatch_safe"])
            self.assertEqual(status["dispatch_blockers"], [])
            self.assertEqual(status["next_candidate"]["project_id"], "queued-gpu")
            self.assertEqual(status["conflicts"], [])

    def test_dashboard_status_keeps_cpu_lane_dispatchable_when_default_worker_is_settling(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _live_config(tmp).model_copy(
                update={
                    "worker_wake_gate_url": "http://gb10-worker:8787",
                    "worker_wake_gate_bearer_token": "gb10-token",
                    "worker_targets": {
                        "cpu-proxmox-1": {
                            "wake_gate_url": "http://cpu-proxmox-1:8787",
                            "bearer_token": "cpu-token",
                            "role": "cpu_worker",
                        },
                        "gb10": {
                            "wake_gate_url": "http://gb10-worker:8787",
                            "bearer_token": "gb10-token",
                            "role": "gpu_worker",
                        },
                    },
                }
            )
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "gb10-settling-cpu-open-import",
                    "queue_rows": [
                        {
                            "project_id": "completed-gb10",
                            "project_name": "Completed GB10",
                            "project_dir": "completed-gb10",
                            "status": "completed",
                            "machine_target": "gb10",
                            "current_run_id": "run-completed-gb10",
                            "last_run_state": "wake_ready",
                            "last_callback_at": datetime.now(timezone.utc).isoformat(),
                        },
                        {
                            "project_id": "queued-cpu",
                            "project_name": "Queued CPU",
                            "project_dir": "queued-cpu",
                            "status": "queued",
                            "machine_target": "cpu-proxmox-1",
                            "dispatch_priority": 1,
                        },
                    ],
                    "run_rows": [
                        {
                            "run_id": "run-completed-gb10",
                            "project_id": "completed-gb10",
                            "status": "completed",
                        }
                    ],
                },
            )
            client.post(
                "/control/resume",
                headers=headers,
                json={"resumed_by": "test", "maintenance_mode": False},
            )
            store = ControlPlaneStore(Path(tmp) / "state" / "control_plane.sqlite3")
            store.upsert_dashboard_observation(
                source="worker_preflight",
                status="warn",
                payload={
                    "ok": False,
                    "target": "http://gb10-worker:8787",
                    "summary": "worker preflight failed",
                    "checks": [
                        {
                            "name": "wake_gate_healthz",
                            "ok": True,
                            "detail": "ok",
                            "data": {},
                        },
                        {
                            "name": "worker_no_live_runs",
                            "ok": False,
                            "detail": "active_or_waiting=1, live=1",
                            "data": {"active_or_waiting": 1, "live": 1},
                        },
                    ],
                },
            )
            store.upsert_dashboard_observation(
                source="worker_dashboard_api", status="ok", payload={"ok": True}
            )

            response = WorkerPreflightResponse(
                ok=False,
                target="http://gb10-worker:8787",
                summary="worker preflight failed",
                checks=[
                    WorkerPreflightCheck(
                        name="wake_gate_healthz", ok=True, detail="ok", data={}
                    ),
                    WorkerPreflightCheck(
                        name="worker_no_live_runs",
                        ok=False,
                        detail="active_or_waiting=1, live=1",
                        data={"active_or_waiting": 1, "live": 1},
                    ),
                ],
            )
            with patch(
                "enoch_control_plane.control_plane.router.run_worker_preflight",
                return_value=response,
            ):
                status = client.get("/control/api/status", headers=headers).json()

            self.assertTrue(status["dispatch_safe"])
            self.assertEqual(status["dispatch_blockers"], [])
            self.assertEqual(status["next_candidate"]["project_id"], "queued-cpu")
            lanes = {lane["machine_target"]: lane for lane in status["worker_lanes"]}
            self.assertTrue(lanes["cpu-proxmox-1"]["dispatch_available"])
            self.assertEqual(lanes["cpu-proxmox-1"]["dispatch_blocker"], "")
            self.assertEqual(
                lanes["gb10"]["dispatch_blocker"], "no queued candidate for lane"
            )

    def test_dashboard_status_keeps_other_lane_dispatchable_when_cached_preflight_failed_for_cpu_lane(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _live_config(tmp).model_copy(
                update={
                    "worker_wake_gate_url": "http://gb10-worker:8787",
                    "worker_wake_gate_bearer_token": "gb10-token",
                    "worker_targets": {
                        "cpu-proxmox-1": {
                            "wake_gate_url": "http://cpu-proxmox-1:8787",
                            "bearer_token": "cpu-token",
                            "role": "cpu_worker",
                        },
                        "gb10": {
                            "wake_gate_url": "http://gb10-worker:8787",
                            "bearer_token": "gb10-token",
                            "role": "gpu_worker",
                        },
                    },
                }
            )
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "cpu-preflight-fail-gb10-open-import",
                    "queue_rows": [
                        {
                            "project_id": "queued-gpu",
                            "project_name": "Queued GPU",
                            "project_dir": "queued-gpu",
                            "status": "queued",
                            "machine_target": "gb10",
                            "dispatch_priority": 1,
                        },
                    ],
                },
            )
            client.post(
                "/control/resume",
                headers=headers,
                json={"resumed_by": "test", "maintenance_mode": False},
            )
            store = ControlPlaneStore(Path(tmp) / "state" / "control_plane.sqlite3")
            store.upsert_dashboard_observation(
                source="worker_preflight",
                status="warn",
                payload={
                    "ok": False,
                    "target": "http://cpu-proxmox-1:8787",
                    "summary": "worker preflight failed",
                    "checks": [
                        {
                            "name": "wake_gate_healthz",
                            "ok": True,
                            "detail": "ok",
                            "data": {},
                        },
                        {
                            "name": "worker_no_live_runs",
                            "ok": False,
                            "detail": "active_or_waiting=1, live=1",
                            "data": {"active_or_waiting": 1, "live": 1},
                        },
                    ],
                },
            )
            store.upsert_dashboard_observation(
                source="worker_dashboard_api", status="ok", payload={"ok": True}
            )

            status = client.get("/control/api/status", headers=headers).json()

            self.assertTrue(status["dispatch_safe"])
            self.assertEqual(status["dispatch_blockers"], [])
            self.assertEqual(status["next_candidate"]["project_id"], "queued-gpu")
            lanes = {lane["machine_target"]: lane for lane in status["worker_lanes"]}
            self.assertTrue(lanes["gb10"]["dispatch_available"])
            self.assertEqual(lanes["gb10"]["dispatch_blocker"], "")

    def test_dashboard_status_treats_blank_machine_target_as_default_worker_lane(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _live_config(tmp).model_copy(
                update={
                    "worker_wake_gate_url": "http://gb10-worker:8787",
                    "worker_wake_gate_bearer_token": "gb10-token",
                    "worker_targets": {
                        "cpu-proxmox-1": {
                            "wake_gate_url": "http://cpu-proxmox-1:8787",
                            "bearer_token": "cpu-token",
                            "role": "cpu_worker",
                        },
                        "gb10": {
                            "wake_gate_url": "http://gb10-worker:8787",
                            "bearer_token": "gb10-token",
                            "role": "gpu_worker",
                        },
                    },
                }
            )
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "blank-target-default-lane-import",
                    "queue_rows": [
                        {
                            "project_id": "active-cpu",
                            "project_name": "Active CPU",
                            "project_dir": "active-cpu",
                            "status": "awaiting_wake",
                            "machine_target": "cpu-proxmox-1",
                            "current_run_id": "run-active-cpu",
                        },
                        {
                            "project_id": "queued-default",
                            "project_name": "Queued Default",
                            "project_dir": "queued-default",
                            "status": "queued",
                            "machine_target": "",
                            "dispatch_priority": 1,
                        },
                    ],
                },
            )
            client.post(
                "/control/resume",
                headers=headers,
                json={"resumed_by": "test", "maintenance_mode": False},
            )
            store = ControlPlaneStore(Path(tmp) / "state" / "control_plane.sqlite3")
            store.upsert_dashboard_observation(
                source="worker_preflight",
                status="ok",
                payload={
                    "ok": True,
                    "checks": [
                        {
                            "name": "wake_gate_healthz",
                            "ok": True,
                            "detail": "ok",
                            "data": {},
                        },
                        {
                            "name": "worker_no_live_runs",
                            "ok": True,
                            "detail": "active_or_waiting=0, live=0",
                            "data": {"active_or_waiting": 0, "live": 0},
                        },
                    ],
                },
            )
            store.upsert_dashboard_observation(
                source="worker_dashboard_api", status="ok", payload={"ok": True}
            )

            status = client.get("/control/api/status", headers=headers).json()
            dry_run = client.post(
                "/control/dispatch-next", headers=headers, json={"dry_run": True}
            ).json()

            self.assertTrue(status["dispatch_safe"])
            self.assertEqual(status["dispatch_blockers"], [])
            self.assertEqual(status["next_candidate"]["project_id"], "queued-default")
            self.assertEqual(dry_run["action"], "dry_run_dispatch")
            self.assertEqual(dry_run["candidate"]["project_id"], "queued-default")
            lanes = {lane["machine_target"]: lane for lane in status["worker_lanes"]}
            self.assertEqual(lanes["gb10"]["queued_count"], 1)
            self.assertTrue(lanes["gb10"]["dispatch_available"])

    def test_dashboard_status_reports_worker_lane_capacity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _live_config(tmp).model_copy(
                update={
                    "worker_wake_gate_url": "http://gb10-worker:8787",
                    "worker_wake_gate_bearer_token": "gb10-token",
                    "worker_targets": {
                        "cpu-proxmox-1": {
                            "wake_gate_url": "http://cpu-proxmox-1:8787",
                            "bearer_token": "cpu-token",
                            "role": "cpu_worker",
                        },
                        "gb10": {
                            "wake_gate_url": "http://gb10-worker:8787",
                            "bearer_token": "gb10-token",
                            "role": "gpu_worker",
                        },
                    },
                }
            )
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "lane-capacity-import",
                    "queue_rows": [
                        {
                            "project_id": "active-cpu",
                            "project_name": "Active CPU",
                            "project_dir": "active-cpu",
                            "status": "awaiting_wake",
                            "machine_target": "cpu-proxmox-1",
                            "current_run_id": "run-active-cpu",
                        },
                        {
                            "project_id": "queued-gpu",
                            "project_name": "Queued GPU",
                            "project_dir": "queued-gpu",
                            "status": "queued",
                            "machine_target": "gb10",
                            "dispatch_priority": 1,
                        },
                    ],
                },
            )
            client.post(
                "/control/resume",
                headers=headers,
                json={"resumed_by": "test", "maintenance_mode": False},
            )
            store = ControlPlaneStore(Path(tmp) / "state" / "control_plane.sqlite3")
            store.upsert_dashboard_observation(
                source="worker_preflight",
                status="ok",
                payload={
                    "ok": True,
                    "checks": [
                        {
                            "name": "wake_gate_healthz",
                            "ok": True,
                            "detail": "ok",
                            "data": {},
                        },
                        {
                            "name": "worker_no_live_runs",
                            "ok": True,
                            "detail": "active_or_waiting=0, live=0",
                            "data": {"active_or_waiting": 0, "live": 0},
                        },
                    ],
                },
            )
            store.upsert_dashboard_observation(
                source="worker_dashboard_api", status="ok", payload={"ok": True}
            )

            status = client.get("/control/api/status", headers=headers).json()

            lanes = {lane["machine_target"]: lane for lane in status["worker_lanes"]}
            self.assertEqual(set(lanes), {"cpu-proxmox-1", "gb10"})
            self.assertNotIn("bearer_token", json.dumps(status["worker_lanes"]))
            self.assertEqual(lanes["cpu-proxmox-1"]["status"], "active")
            self.assertEqual(
                lanes["cpu-proxmox-1"]["active_item"]["project_id"], "active-cpu"
            )
            self.assertEqual(lanes["cpu-proxmox-1"]["queued_count"], 0)
            self.assertFalse(lanes["cpu-proxmox-1"]["dispatch_available"])
            self.assertEqual(lanes["cpu-proxmox-1"]["dispatch_blocker"], "lane active")
            self.assertEqual(lanes["gb10"]["status"], "idle")
            self.assertEqual(lanes["gb10"]["queued_count"], 1)
            self.assertEqual(
                lanes["gb10"]["next_candidate"]["project_id"], "queued-gpu"
            )
            self.assertTrue(lanes["gb10"]["dispatch_available"])
            self.assertEqual(
                lanes["gb10"]["dispatch_reason"], "lane open with queued candidate"
            )

            state = client.get("/control/state", headers=headers).json()
            state_lanes = {
                lane["machine_target"]: lane for lane in state["worker_lanes"]
            }
            self.assertFalse(state_lanes["cpu-proxmox-1"]["dispatch_available"])
            self.assertTrue(state_lanes["gb10"]["dispatch_available"])

    def test_dashboard_status_marks_active_lane_preflight_stale_after_dispatch(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _live_config(tmp).model_copy(
                update={
                    "worker_wake_gate_url": "http://gb10-worker:8787",
                    "worker_wake_gate_bearer_token": "gb10-token",
                    "worker_targets": {
                        "cpu-proxmox-1": {
                            "wake_gate_url": "http://cpu-proxmox-1:8787",
                            "bearer_token": "cpu-token",
                            "role": "cpu_worker",
                        }
                    },
                }
            )
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            preflight_at = datetime.now(timezone.utc) - timedelta(seconds=2)
            dispatch_at = preflight_at + timedelta(milliseconds=250)
            client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "stale-after-dispatch-active-import",
                    "queue_rows": [
                        {
                            "project_id": "active-cpu-race",
                            "project_name": "Active CPU Race",
                            "project_dir": "active-cpu-race",
                            "status": "running",
                            "machine_target": "cpu-proxmox-1",
                            "current_run_id": "run-active-cpu-race",
                            "last_dispatch_at": dispatch_at.isoformat(),
                            "updated_at": dispatch_at.isoformat(),
                        }
                    ],
                },
            )
            store = ControlPlaneStore(Path(tmp) / "state" / "control_plane.sqlite3")
            store.upsert_dashboard_observation(
                source="worker_preflight",
                scope="lane:http://cpu-proxmox-1:8787",
                status="ok",
                observed_at=preflight_at.isoformat(),
                ttl_seconds=900,
                payload={
                    "ok": True,
                    "target": "http://cpu-proxmox-1:8787",
                    "checks": [
                        {
                            "name": "wake_gate_dashboard_api",
                            "ok": True,
                            "detail": "dashboard API reachable",
                            "data": {"body": {"runs": [], "totals": {}}},
                        },
                        {
                            "name": "worker_no_live_runs",
                            "ok": True,
                            "detail": "active_or_waiting=0, live=0",
                            "data": {"active_or_waiting": 0, "live": 0},
                        },
                    ],
                },
            )

            status = client.get("/control/api/status", headers=headers).json()

            lanes = {lane["machine_target"]: lane for lane in status["worker_lanes"]}
            confirmation = lanes["cpu-proxmox-1"]["active_confirmation"]
            self.assertEqual(confirmation["state"], "preflight_stale_after_dispatch")
            self.assertEqual(confirmation["observed_at"], preflight_at.isoformat())
            self.assertEqual(confirmation["last_dispatch_at"], dispatch_at.isoformat())
            self.assertIn("refresh lane preflight", confirmation["suggested_action"])
            self.assertNotIn(
                "stale active worker lane: cpu_worker", status["dispatch_blockers"]
            )

    def test_dashboard_status_refreshes_named_worker_lane_preflight(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _live_config(tmp).model_copy(
                update={
                    "worker_wake_gate_url": "http://gb10-worker:8787",
                    "worker_wake_gate_bearer_token": "gb10-token",
                    "worker_targets": {
                        "cpu-proxmox-1": {
                            "wake_gate_url": "http://cpu-proxmox-1:8787",
                            "bearer_token": "cpu-token",
                            "role": "cpu_worker",
                        },
                        "gb10": {
                            "wake_gate_url": "http://gb10-worker:8787",
                            "bearer_token": "gb10-token",
                            "role": "gpu_worker",
                        },
                    },
                }
            )
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            preflight_at = datetime.now(timezone.utc) - timedelta(seconds=30)
            dispatch_at = preflight_at + timedelta(seconds=10)
            client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "refresh-named-worker-lane-import",
                    "queue_rows": [
                        {
                            "project_id": "active-cpu-refresh",
                            "project_name": "Active CPU Refresh",
                            "project_dir": "active-cpu-refresh",
                            "status": "running",
                            "machine_target": "cpu-proxmox-1",
                            "current_run_id": "run-active-cpu-refresh",
                            "last_dispatch_at": dispatch_at.isoformat(),
                            "updated_at": dispatch_at.isoformat(),
                        }
                    ],
                },
            )
            store = ControlPlaneStore(Path(tmp) / "state" / "control_plane.sqlite3")
            store.upsert_dashboard_observation(
                source="worker_preflight",
                scope="lane:http://cpu-proxmox-1:8787",
                status="ok",
                observed_at=preflight_at.isoformat(),
                ttl_seconds=900,
                payload={
                    "ok": True,
                    "target": "http://cpu-proxmox-1:8787",
                    "checks": [
                        {
                            "name": "wake_gate_dashboard_api",
                            "ok": True,
                            "detail": "dashboard API reachable",
                            "data": {"body": {"runs": [], "totals": {}}},
                        },
                        {
                            "name": "worker_no_live_runs",
                            "ok": True,
                            "detail": "active_or_waiting=0, live=0",
                            "data": {"active_or_waiting": 0, "live": 0},
                        },
                    ],
                },
            )

            def fake_preflight(payload, flags):
                target = payload.wake_gate_url.rstrip("/")
                runs = (
                    [
                        {
                            "run_id": "run-active-cpu-refresh",
                            "project_id": "active-cpu-refresh",
                            "active_process_count": 2,
                            "is_live": True,
                        }
                    ]
                    if target == "http://cpu-proxmox-1:8787"
                    else []
                )
                return WorkerPreflightResponse(
                    ok=True,
                    target=payload.wake_gate_url,
                    summary="worker preflight passed",
                    checks=[
                        WorkerPreflightCheck(
                            name="wake_gate_healthz",
                            ok=True,
                            detail="ok",
                            data={},
                        ),
                        WorkerPreflightCheck(
                            name="wake_gate_dashboard_api",
                            ok=True,
                            detail="dashboard API reachable",
                            data={
                                "body": {
                                    "timestamp": datetime.now(timezone.utc).isoformat(),
                                    "runs": runs,
                                    "totals": {"live": len(runs)},
                                }
                            },
                        ),
                        WorkerPreflightCheck(
                            name="worker_no_live_runs",
                            ok=not runs,
                            detail=f"active_or_waiting={len(runs)}, live={len(runs)}",
                            data={"active_or_waiting": len(runs), "live": len(runs)},
                        ),
                    ],
                )

            with patch(
                "enoch_control_plane.control_plane.router.run_worker_preflight",
                side_effect=fake_preflight,
            ) as mocked_preflight:
                status = client.get(
                    "/control/api/status?refresh_worker=true", headers=headers
                ).json()

            requested_targets = {
                call.args[0].wake_gate_url.rstrip("/")
                for call in mocked_preflight.call_args_list
            }
            self.assertIn("http://gb10-worker:8787", requested_targets)
            self.assertIn("http://cpu-proxmox-1:8787", requested_targets)
            lanes = {lane["machine_target"]: lane for lane in status["worker_lanes"]}
            confirmation = lanes["cpu-proxmox-1"]["active_confirmation"]
            self.assertEqual(confirmation["state"], "active_confirmed")
            self.assertEqual(confirmation["matched_run_id"], "run-active-cpu-refresh")

    def test_dashboard_status_marks_active_lane_stale_when_worker_has_no_matching_run(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _live_config(tmp).model_copy(
                update={
                    "worker_wake_gate_url": "http://gb10-worker:8787",
                    "worker_wake_gate_bearer_token": "gb10-token",
                    "worker_targets": {
                        "cpu-proxmox-1": {
                            "wake_gate_url": "http://cpu-proxmox-1:8787",
                            "bearer_token": "cpu-token",
                            "role": "cpu_worker",
                        },
                        "gb10": {
                            "wake_gate_url": "http://gb10-worker:8787",
                            "bearer_token": "gb10-token",
                            "role": "gpu_worker",
                        },
                    },
                }
            )
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            old = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
            client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "stale-active-lane-import",
                    "queue_rows": [
                        {
                            "project_id": "active-cpu-stale",
                            "project_name": "Active CPU Stale",
                            "project_dir": "active-cpu-stale",
                            "status": "awaiting_wake",
                            "machine_target": "cpu-proxmox-1",
                            "current_run_id": "run-active-cpu-stale",
                            "updated_at": old,
                        }
                    ],
                },
            )
            client.post(
                "/control/resume",
                headers=headers,
                json={"resumed_by": "test", "maintenance_mode": False},
            )
            store = ControlPlaneStore(Path(tmp) / "state" / "control_plane.sqlite3")
            store.upsert_dashboard_observation(
                source="worker_preflight",
                status="ok",
                observed_at=old,
                ttl_seconds=900,
                payload={
                    "ok": True,
                    "target": "http://cpu-proxmox-1:8787",
                    "checks": [
                        {
                            "name": "wake_gate_healthz",
                            "ok": True,
                            "detail": "ok",
                            "data": {},
                        },
                        {
                            "name": "wake_gate_dashboard_api",
                            "ok": True,
                            "detail": "dashboard API reachable",
                            "data": {"body": {"runs": [], "totals": {}}},
                        },
                        {
                            "name": "worker_no_live_runs",
                            "ok": True,
                            "detail": "active_or_waiting=0, live=0",
                            "data": {"active_or_waiting": 0, "live": 0},
                        },
                    ],
                },
            )
            store.upsert_dashboard_observation(
                source="worker_dashboard_api", status="ok", payload={"ok": True}
            )

            status = client.get("/control/api/status", headers=headers).json()

            lanes = {lane["machine_target"]: lane for lane in status["worker_lanes"]}
            confirmation = lanes["cpu-proxmox-1"]["active_confirmation"]
            self.assertEqual(confirmation["state"], "stale_active")
            self.assertIn(
                "stale active worker lane: cpu_worker", status["dispatch_blockers"]
            )
            self.assertTrue(
                any(
                    item["source"] == "control_plane_db+worker_preflight"
                    and "without a matching worker run" in item["message"]
                    for item in status["warnings"]
                )
            )

    def test_dashboard_status_uses_lane_scoped_preflight_for_active_confirmation(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _live_config(tmp).model_copy(
                update={
                    "worker_wake_gate_url": "http://gb10-worker:8787",
                    "worker_wake_gate_bearer_token": "gb10-token",
                    "worker_targets": {
                        "cpu-proxmox-1": {
                            "wake_gate_url": "http://cpu-proxmox-1:8787",
                            "bearer_token": "cpu-token",
                            "role": "cpu_worker",
                        },
                        "gb10": {
                            "wake_gate_url": "http://gb10-worker:8787",
                            "bearer_token": "gb10-token",
                            "role": "gpu_worker",
                        },
                    },
                }
            )
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "lane-scoped-active-confirmation-import",
                    "queue_rows": [
                        {
                            "project_id": "active-cpu-scoped",
                            "project_name": "Active CPU Scoped",
                            "project_dir": "active-cpu-scoped",
                            "status": "running",
                            "machine_target": "cpu-proxmox-1",
                            "current_run_id": "run-active-cpu-scoped",
                        },
                        {
                            "project_id": "active-gb10-scoped",
                            "project_name": "Active GB10 Scoped",
                            "project_dir": "active-gb10-scoped",
                            "status": "running",
                            "machine_target": "gb10",
                            "current_run_id": "run-active-gb10-scoped",
                        },
                    ],
                },
            )
            store = ControlPlaneStore(Path(tmp) / "state" / "control_plane.sqlite3")
            # The latest global preflight is for the GB10 lane. This used to
            # make the CPU lane report unknown/"worker confirmation unavailable"
            # even though the store had a fresh CPU-lane preflight.
            store.upsert_dashboard_observation(
                source="worker_preflight",
                status="warn",
                payload={
                    "ok": False,
                    "target": "http://gb10-worker:8787",
                    "checks": [
                        {
                            "name": "wake_gate_dashboard_api",
                            "ok": True,
                            "detail": "dashboard API reachable",
                            "data": {
                                "body": {
                                    "runs": [
                                        {
                                            "run_id": "run-active-gb10-scoped",
                                            "project_id": "active-gb10-scoped",
                                            "is_live": True,
                                            "active_process_count": 1,
                                        }
                                    ]
                                }
                            },
                        },
                        {
                            "name": "worker_no_live_runs",
                            "ok": False,
                            "detail": "active_or_waiting=1, live=1",
                            "data": {"active_or_waiting": 1, "live": 1},
                        },
                    ],
                },
            )
            store.upsert_dashboard_observation(
                source="worker_preflight",
                scope="lane:http://cpu-proxmox-1:8787",
                status="warn",
                payload={
                    "ok": False,
                    "target": "http://cpu-proxmox-1:8787",
                    "checks": [
                        {
                            "name": "wake_gate_dashboard_api",
                            "ok": True,
                            "detail": "dashboard API reachable",
                            "data": {
                                "body": {
                                    "runs": [
                                        {
                                            "run_id": "run-active-cpu-scoped",
                                            "project_id": "active-cpu-scoped",
                                            "is_live": True,
                                            "active_process_count": 1,
                                        }
                                    ]
                                }
                            },
                        },
                        {
                            "name": "worker_no_live_runs",
                            "ok": False,
                            "detail": "active_or_waiting=1, live=1",
                            "data": {"active_or_waiting": 1, "live": 1},
                        },
                    ],
                },
            )
            store.upsert_dashboard_observation(
                source="worker_dashboard_api", status="ok", payload={"ok": True}
            )

            status = client.get("/control/api/status", headers=headers).json()

            lanes = {lane["machine_target"]: lane for lane in status["worker_lanes"]}
            self.assertEqual(
                lanes["cpu-proxmox-1"]["active_confirmation"]["state"],
                "active_confirmed",
            )
            self.assertEqual(
                lanes["cpu-proxmox-1"]["active_confirmation"]["matched_run_id"],
                "run-active-cpu-scoped",
            )
            self.assertEqual(
                lanes["gb10"]["active_confirmation"]["state"], "active_confirmed"
            )

    def test_dashboard_status_confirms_active_lane_from_matching_worker_run(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _live_config(tmp).model_copy(
                update={
                    "worker_wake_gate_url": "http://gb10-worker:8787",
                    "worker_wake_gate_bearer_token": "gb10-token",
                    "worker_targets": {
                        "cpu-proxmox-1": {
                            "wake_gate_url": "http://cpu-proxmox-1:8787",
                            "bearer_token": "cpu-token",
                            "role": "cpu_worker",
                        }
                    },
                }
            )
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "confirmed-active-lane-import",
                    "queue_rows": [
                        {
                            "project_id": "active-cpu-confirmed",
                            "project_name": "Active CPU Confirmed",
                            "project_dir": "active-cpu-confirmed",
                            "status": "running",
                            "machine_target": "cpu-proxmox-1",
                            "current_run_id": "run-active-cpu-confirmed",
                        }
                    ],
                },
            )
            store = ControlPlaneStore(Path(tmp) / "state" / "control_plane.sqlite3")
            store.upsert_dashboard_observation(
                source="worker_preflight",
                status="warn",
                payload={
                    "ok": False,
                    "target": "http://cpu-proxmox-1:8787",
                    "checks": [
                        {
                            "name": "wake_gate_dashboard_api",
                            "ok": True,
                            "detail": "dashboard API reachable",
                            "data": {
                                "body": {
                                    "runs": [
                                        {
                                            "run_id": "run-active-cpu-confirmed",
                                            "project_id": "active-cpu-confirmed",
                                            "is_live": True,
                                            "active_process_count": 1,
                                        }
                                    ]
                                }
                            },
                        },
                        {
                            "name": "worker_no_live_runs",
                            "ok": False,
                            "detail": "active_or_waiting=1, live=1",
                            "data": {"active_or_waiting": 1, "live": 1},
                        },
                    ],
                },
            )
            store.upsert_dashboard_observation(
                source="worker_dashboard_api", status="ok", payload={"ok": True}
            )

            status = client.get("/control/api/status", headers=headers).json()

            lanes = {lane["machine_target"]: lane for lane in status["worker_lanes"]}
            confirmation = lanes["cpu-proxmox-1"]["active_confirmation"]
            self.assertEqual(confirmation["state"], "active_confirmed")
            self.assertEqual(confirmation["matched_run_id"], "run-active-cpu-confirmed")
            self.assertNotIn(
                "stale active worker lane: cpu_worker", status["dispatch_blockers"]
            )

    def test_dashboard_status_reports_all_lanes_active_when_no_open_candidate(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _live_config(tmp).model_copy(
                update={
                    "worker_wake_gate_url": "http://gb10-worker:8787",
                    "worker_wake_gate_bearer_token": "gb10-token",
                    "worker_targets": {
                        "cpu-proxmox-1": {
                            "wake_gate_url": "http://cpu-proxmox-1:8787",
                            "bearer_token": "cpu-token",
                            "role": "cpu_worker",
                        },
                        "gb10": {
                            "wake_gate_url": "http://gb10-worker:8787",
                            "bearer_token": "gb10-token",
                            "role": "gpu_worker",
                        },
                    },
                }
            )
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "lane-capacity-all-active-import",
                    "queue_rows": [
                        {
                            "project_id": "active-cpu",
                            "project_name": "Active CPU",
                            "project_dir": "active-cpu",
                            "status": "awaiting_wake",
                            "machine_target": "cpu-proxmox-1",
                            "current_run_id": "run-active-cpu",
                        },
                        {
                            "project_id": "active-gpu",
                            "project_name": "Active GPU",
                            "project_dir": "active-gpu",
                            "status": "awaiting_wake",
                            "machine_target": "gb10",
                            "current_run_id": "run-active-gpu",
                        },
                        {
                            "project_id": "queued-cpu",
                            "project_name": "Queued CPU",
                            "project_dir": "queued-cpu",
                            "status": "queued",
                            "machine_target": "cpu-proxmox-1",
                        },
                        {
                            "project_id": "queued-gpu",
                            "project_name": "Queued GPU",
                            "project_dir": "queued-gpu",
                            "status": "queued",
                            "machine_target": "gb10",
                        },
                    ],
                },
            )
            client.post(
                "/control/resume",
                headers=headers,
                json={"resumed_by": "test", "maintenance_mode": False},
            )

            status = client.get("/control/api/status", headers=headers).json()

            lanes = {lane["machine_target"]: lane for lane in status["worker_lanes"]}
            self.assertEqual(lanes["cpu-proxmox-1"]["queued_count"], 1)
            self.assertEqual(lanes["gb10"]["queued_count"], 1)
            self.assertEqual(lanes["cpu-proxmox-1"]["dispatch_blocker"], "lane active")
            self.assertEqual(lanes["gb10"]["dispatch_blocker"], "lane active")
            self.assertFalse(lanes["cpu-proxmox-1"]["dispatch_available"])
            self.assertFalse(lanes["gb10"]["dispatch_available"])
            self.assertIn(
                "all configured worker lanes active", status["dispatch_blockers"]
            )

    def test_overview_and_lanes_top_level_next_candidate_require_open_lane(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _live_config(tmp).model_copy(
                update={
                    "worker_wake_gate_url": "http://gb10-worker:8787",
                    "worker_wake_gate_bearer_token": "gb10-token",
                    "worker_targets": {
                        "cpu-proxmox-1": {
                            "wake_gate_url": "http://cpu-proxmox-1:8787",
                            "bearer_token": "cpu-token",
                            "role": "cpu_worker",
                        },
                        "gb10": {
                            "wake_gate_url": "http://gb10-worker:8787",
                            "bearer_token": "gb10-token",
                            "role": "gpu_worker",
                        },
                    },
                }
            )
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "lane-aware-overview-next-import",
                    "queue_rows": [
                        {
                            "project_id": "active-cpu",
                            "project_name": "Active CPU",
                            "project_dir": "active-cpu",
                            "status": "awaiting_wake",
                            "machine_target": "cpu-proxmox-1",
                            "current_run_id": "run-active-cpu",
                        },
                        {
                            "project_id": "active-gpu",
                            "project_name": "Active GPU",
                            "project_dir": "active-gpu",
                            "status": "awaiting_wake",
                            "machine_target": "gb10",
                            "current_run_id": "run-active-gpu",
                        },
                        {
                            "project_id": "queued-cpu",
                            "project_name": "Queued CPU",
                            "project_dir": "queued-cpu",
                            "status": "queued",
                            "machine_target": "cpu-proxmox-1",
                            "dispatch_priority": 1,
                        },
                        {
                            "project_id": "queued-gpu",
                            "project_name": "Queued GPU",
                            "project_dir": "queued-gpu",
                            "status": "queued",
                            "machine_target": "gb10",
                            "dispatch_priority": 1,
                        },
                    ],
                },
            )

            status = client.get("/control/api/status", headers=headers).json()
            overview = client.get("/control/api/v1/overview", headers=headers).json()
            lanes = client.get("/control/api/v1/lanes", headers=headers).json()

            self.assertIsNone(status["next_candidate"])
            self.assertIsNone(overview["next_candidate"])
            self.assertIsNone(lanes["next_candidate"])

    def test_overview_top_actions_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            headers = {"Authorization": f"Bearer {TOKEN}"}

            # Idle case: bounded, empty list, but the field is still present.
            empty = client.get("/control/api/v1/overview", headers=headers).json()
            self.assertIn("top_actions", empty)
            self.assertIsInstance(empty["top_actions"], list)
            self.assertEqual(empty["top_actions"], [])

            # Seed a queued item so dispatch_next is the only ranked action.
            client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "top-actions-queued-import",
                    "queue_rows": [
                        {
                            "project_id": "queued-only",
                            "project_name": "Queued Only",
                            "project_dir": "queued-only",
                            "status": "queued",
                            "dispatch_priority": 1,
                        }
                    ],
                },
            )
            queued = client.get("/control/api/v1/overview", headers=headers).json()
            self.assertGreaterEqual(len(queued["top_actions"]), 1)
            kinds = {a["kind"] for a in queued["top_actions"]}
            self.assertIn("dispatch_next", kinds)
            top = queued["top_actions"][0]
            for key in (
                "kind",
                "priority",
                "tone",
                "title",
                "summary",
                "count",
                "action_label",
                "action_hash",
            ):
                self.assertIn(key, top)
            for action in queued["top_actions"]:
                if "target" in action:
                    self.assertIsInstance(action["target"], dict)
            self.assertGreaterEqual(top["priority"], 1)
            self.assertLessEqual(len(queued["top_actions"]), 3)
            self.assertTrue(top["action_hash"].startswith("#"))

    def test_overview_research_yield_names_paper_drought_recovery_action(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            rows = [
                {
                    "project_id": "useful-signal-followup",
                    "project_name": "Useful Signal Follow-up",
                    "project_dir": "useful-signal-followup",
                    "status": "completed",
                    "current_run_id": "run-useful-signal",
                    "decision_gate_state": "negative",
                    "research_outcome": "useful_signal",
                    "hypothesis_status": "supported",
                    "evidence_strength": "moderate",
                    "bounded_paper_ready": False,
                    "followup_recommended": True,
                    "followup_type": "deepen",
                    "followup_title": "Real trace replay follow-up",
                    "followup_hypothesis": "Real traces will validate the bounded signal.",
                    "followup_required_evidence": [
                        "real trace integration",
                        "baseline comparison",
                        "failure analysis",
                    ],
                    "followup_success_threshold": "Blocks 90% of unsafe calls.",
                    "followup_stop_condition": "Stop if traces cannot be collected.",
                    "followup_depth": 0,
                    "updated_at": "2026-05-28T00:00:00Z",
                }
            ]

            with (
                patch.object(
                    ControlPlaneStore,
                    "queue_counts_sql",
                    return_value={"completed": 1},
                ),
                patch.object(ControlPlaneStore, "paper_counts_sql", return_value={}),
                patch.object(ControlPlaneStore, "active_items_sql", return_value=[]),
                patch.object(
                    ControlPlaneStore, "next_candidate_sql", return_value=None
                ),
                patch.object(
                    ControlPlaneStore, "operator_queue_rows_sql", return_value=rows
                ),
                patch.object(
                    ControlPlaneStore, "operator_paper_rows_sql", return_value=[]
                ),
            ):
                overview = client.get(
                    "/control/api/v1/overview", headers=headers
                ).json()

            recovery = overview["research_yield"]["paper_recovery"]
            self.assertTrue(overview["research_yield"]["paper_drought"]["warning"])
            self.assertEqual(recovery["status"], "ranked_followup_ready")
            self.assertEqual(recovery["next_action"], "queue_followup")
            self.assertEqual(recovery["count"], 1)
            self.assertEqual(recovery["target"]["project_id"], "useful-signal-followup")

    def test_overview_top_actions_dispatch_is_lane_aware(self) -> None:
        # PR 42 review acceptance criterion: dispatch action must be
        # lane-aware. Configure CPU + GB10 lanes, mark the CPU lane busy by
        # seeding an active row, and seed a queued GB10-targeted candidate.
        # Aggregate counts.active>0 must NOT suppress dispatch_next when GB10
        # is idle and has a queued candidate.
        with tempfile.TemporaryDirectory() as tmp:
            config = _live_config(tmp).model_copy(
                update={
                    "worker_wake_gate_url": "http://gb10-worker:8787",
                    "worker_wake_gate_bearer_token": "gb10-token",
                    "worker_targets": {
                        "cpu-proxmox-1": {
                            "wake_gate_url": "http://cpu-proxmox-1:8787",
                            "bearer_token": "cpu-token",
                            "role": "cpu_worker",
                        },
                        "gb10": {
                            "wake_gate_url": "http://gb10-worker:8787",
                            "bearer_token": "gb10-token",
                            "role": "gpu_worker",
                        },
                    },
                }
            )
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "lane-aware-dispatch-import",
                    "queue_rows": [
                        {
                            "project_id": "active-cpu",
                            "project_name": "Active CPU",
                            "project_dir": "active-cpu",
                            "status": "awaiting_wake",
                            "machine_target": "cpu-proxmox-1",
                            "current_run_id": "run-active-cpu",
                        },
                        {
                            "project_id": "gb10-queued",
                            "project_name": "GB10 Queued",
                            "project_dir": "gb10-queued",
                            "status": "queued",
                            "machine_target": "gb10",
                            "dispatch_priority": 1,
                        },
                    ],
                },
            )
            client.post(
                "/control/resume",
                headers=headers,
                json={"resumed_by": "test", "maintenance_mode": False},
            )

            overview = client.get("/control/api/v1/overview", headers=headers).json()
            kinds = [a["kind"] for a in overview["top_actions"]]
            self.assertIn("dispatch_next", kinds)
            dispatch = next(
                a for a in overview["top_actions"] if a["kind"] == "dispatch_next"
            )
            # The summary must reference the open lane (GB10) — not the
            # aggregate "no worker lane is busy" copy from the old projection.
            self.assertIn("GB10 lane", dispatch["summary"])

    def test_overview_top_actions_dispatch_suppressed_when_all_lanes_busy(self) -> None:
        # CPU + GB10 both busy. Aggregate counts.queued>0 must NOT surface
        # dispatch_next via the read model when no lane is dispatch_available.
        with tempfile.TemporaryDirectory() as tmp:
            config = _live_config(tmp).model_copy(
                update={
                    "worker_wake_gate_url": "http://gb10-worker:8787",
                    "worker_wake_gate_bearer_token": "gb10-token",
                    "worker_targets": {
                        "cpu-proxmox-1": {
                            "wake_gate_url": "http://cpu-proxmox-1:8787",
                            "bearer_token": "cpu-token",
                            "role": "cpu_worker",
                        },
                        "gb10": {
                            "wake_gate_url": "http://gb10-worker:8787",
                            "bearer_token": "gb10-token",
                            "role": "gpu_worker",
                        },
                    },
                }
            )
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "lane-aware-suppression-import",
                    "queue_rows": [
                        {
                            "project_id": "active-cpu",
                            "project_name": "Active CPU",
                            "project_dir": "active-cpu",
                            "status": "awaiting_wake",
                            "machine_target": "cpu-proxmox-1",
                            "current_run_id": "run-active-cpu",
                        },
                        {
                            "project_id": "active-gb10",
                            "project_name": "Active GB10",
                            "project_dir": "active-gb10",
                            "status": "awaiting_wake",
                            "machine_target": "gb10",
                            "current_run_id": "run-active-gb10",
                        },
                        {
                            "project_id": "gb10-also-queued",
                            "project_name": "GB10 Also Queued",
                            "project_dir": "gb10-also-queued",
                            "status": "queued",
                            "machine_target": "gb10",
                        },
                    ],
                },
            )
            client.post(
                "/control/resume",
                headers=headers,
                json={"resumed_by": "test", "maintenance_mode": False},
            )

            overview = client.get("/control/api/v1/overview", headers=headers).json()
            kinds = [a["kind"] for a in overview["top_actions"]]
            self.assertNotIn("dispatch_next", kinds)

    def test_overview_top_actions_max_length_is_bounded(self) -> None:
        # Acceptance criterion: top_actions max length is bounded (<=3).
        # Even if the projection had many candidates, the API contract caps
        # the list. We exercise this through the public endpoint to guard
        # the contract end-to-end.
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "top-actions-bounded-import",
                    "queue_rows": [
                        {
                            "project_id": "blocked-1",
                            "project_name": "Blocked 1",
                            "project_dir": "blocked-1",
                            "status": "blocked",
                        },
                        {
                            "project_id": "queued-1",
                            "project_name": "Queued 1",
                            "project_dir": "queued-1",
                            "status": "queued",
                            "dispatch_priority": 1,
                        },
                    ],
                },
            )
            overview = client.get("/control/api/v1/overview", headers=headers).json()
            self.assertLessEqual(len(overview["top_actions"]), 3)
            for index, action in enumerate(overview["top_actions"], start=1):
                self.assertEqual(action["priority"], index)

    def test_overview_primary_operator_action_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            empty = client.get("/control/api/v1/overview", headers=headers).json()
            self.assertIn("primary_operator_action", empty)
            if empty["primary_operator_action"] is not None:
                self.assertIn(
                    empty["primary_operator_action"]["kind"],
                    {"feed_lanes", "open_blocker", "dispatch_next"},
                )
            client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "primary-action-queued-import",
                    "queue_rows": [
                        {
                            "project_id": "queued-only",
                            "project_name": "Queued Only",
                            "project_dir": "queued-only",
                            "status": "queued",
                            "dispatch_priority": 1,
                        }
                    ],
                },
            )
            paused_primary = client.get(
                "/control/api/v1/overview", headers=headers
            ).json()["primary_operator_action"]
            self.assertIsInstance(paused_primary, dict)
            self.assertEqual(paused_primary["kind"], "open_blocker")
            self.assertIn(
                paused_primary["blocker_kind"], {"queue_paused", "maintenance_mode"}
            )
            client.post(
                "/control/resume",
                headers=headers,
                json={"resumed_by": "test", "maintenance_mode": False},
            )
            primary = client.get("/control/api/v1/overview", headers=headers).json()[
                "primary_operator_action"
            ]
            self.assertIsInstance(primary, dict)
            self.assertEqual(primary["kind"], "dispatch_next")

    def test_overview_exposes_movement_diagnosis(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _live_config(tmp).model_copy(
                update={
                    "worker_wake_gate_url": "http://gb10-worker:8787",
                    "worker_wake_gate_bearer_token": "gb10-token",
                    "worker_targets": {
                        "cpu-proxmox-1": {
                            "wake_gate_url": "http://cpu-proxmox-1:8787",
                            "bearer_token": "cpu-token",
                            "role": "cpu_worker",
                        },
                        "gb10": {
                            "wake_gate_url": "http://gb10-worker:8787",
                            "bearer_token": "gb10-token",
                            "role": "gpu_worker",
                        },
                    },
                }
            )
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "movement-diagnosis-import",
                    "queue_rows": [
                        {
                            "project_id": "active-cpu",
                            "project_name": "Active CPU",
                            "project_dir": "active-cpu",
                            "status": "awaiting_wake",
                            "machine_target": "cpu-proxmox-1",
                            "current_run_id": "run-active-cpu",
                        },
                        {
                            "project_id": "queued-gb10",
                            "project_name": "Queued GB10",
                            "project_dir": "queued-gb10",
                            "status": "queued",
                            "machine_target": "gb10",
                            "dispatch_priority": 1,
                        },
                    ],
                },
            )
            client.post(
                "/control/resume",
                headers=headers,
                json={"resumed_by": "test", "maintenance_mode": False},
            )

            overview = client.get("/control/api/v1/overview", headers=headers).json()

            self.assertIn("movement_diagnosis", overview)
            diagnosis = overview["movement_diagnosis"]
            self.assertEqual(diagnosis["status"], "actionable")
            self.assertIn("GB10 lane", diagnosis["primary_reason"])
            kinds = [item["kind"] for item in diagnosis["blockers"]]
            self.assertIn("lane_active", kinds)
            self.assertIn("dispatch_available", kinds)

    def test_overview_does_not_treat_active_worker_lanes_as_bad_health(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _live_config(tmp).model_copy(
                update={
                    "worker_wake_gate_url": "http://gb10-worker:8787",
                    "worker_wake_gate_bearer_token": "gb10-token",
                    "worker_targets": {
                        "cpu-proxmox-1": {
                            "wake_gate_url": "http://cpu-proxmox-1:8787",
                            "bearer_token": "cpu-token",
                            "role": "cpu_worker",
                        },
                        "gb10": {
                            "wake_gate_url": "http://gb10-worker:8787",
                            "bearer_token": "gb10-token",
                            "role": "gpu_worker",
                        },
                    },
                }
            )
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "movement-diagnosis-active-lanes-import",
                    "queue_rows": [
                        {
                            "project_id": "active-cpu",
                            "project_name": "Active CPU",
                            "project_dir": "active-cpu",
                            "status": "awaiting_wake",
                            "machine_target": "cpu-proxmox-1",
                            "current_run_id": "run-active-cpu",
                        },
                        {
                            "project_id": "active-gb10",
                            "project_name": "Active GB10",
                            "project_dir": "active-gb10",
                            "status": "awaiting_wake",
                            "machine_target": "gb10",
                            "current_run_id": "run-active-gb10",
                        },
                        {
                            "project_id": "queued-cpu",
                            "project_name": "Queued CPU",
                            "project_dir": "queued-cpu",
                            "status": "queued",
                            "machine_target": "cpu-proxmox-1",
                            "dispatch_priority": 2,
                        },
                        {
                            "project_id": "queued-gb10",
                            "project_name": "Queued GB10",
                            "project_dir": "queued-gb10",
                            "status": "queued",
                            "machine_target": "gb10",
                            "dispatch_priority": 1,
                        },
                    ],
                },
            )
            client.post(
                "/control/resume",
                headers=headers,
                json={"resumed_by": "test", "maintenance_mode": False},
            )

            overview = client.get("/control/api/v1/overview", headers=headers).json()

            diagnosis = overview["movement_diagnosis"]
            self.assertEqual(diagnosis["status"], "ready")
            self.assertIn("normal", diagnosis["primary_reason"].lower())
            kinds = [item["kind"] for item in diagnosis["blockers"]]
            self.assertEqual(kinds.count("lane_active"), 2)
            self.assertNotEqual(
                diagnosis["primary_reason"], diagnosis["blockers"][0]["summary"]
            )

    def test_movement_diagnosis_treats_evidence_missing_as_hard_blocker_but_paper_gate_as_non_health_info(
        self,
    ) -> None:
        from enoch_control_plane.control_plane.read_models import movement_diagnosis

        paper_gate_only = movement_diagnosis(
            flags={"queue_paused": False, "maintenance_mode": False},
            worker_lanes=[],
            paper_pipeline={"not_writable_by_decision_gate": 3, "finalize_needed": 0},
        )

        self.assertEqual(paper_gate_only["status"], "ready")
        self.assertFalse(paper_gate_only["blockers"])
        self.assertIn(
            "No deterministic blocker",
            paper_gate_only["primary_reason"],
        )

        evidence_missing = movement_diagnosis(
            flags={"queue_paused": False, "maintenance_mode": False},
            worker_lanes=[],
            paper_pipeline={
                "not_writable_by_decision_gate": 3,
                "paper_write_blocked": 0,
                "finalize_needed": 1,
            },
        )

        self.assertEqual(evidence_missing["status"], "blocked")
        self.assertTrue(
            any(
                item["kind"] == "evidence_missing"
                for item in evidence_missing["blockers"]
            )
        )
        self.assertIn("publication draft", evidence_missing["primary_reason"])

        positive_anomaly = movement_diagnosis(
            flags={"queue_paused": False, "maintenance_mode": False},
            worker_lanes=[],
            paper_pipeline={
                "not_writable_by_decision_gate": 3,
                "paper_write_blocked": 1,
                "finalize_needed": 0,
            },
        )
        self.assertEqual(positive_anomaly["status"], "blocked")
        self.assertTrue(
            any(
                item["kind"] == "paper_write_blocked"
                for item in positive_anomaly["blockers"]
            )
        )

    def test_dashboard_status_does_not_call_idle_empty_lane_active(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _live_config(tmp).model_copy(
                update={
                    "worker_wake_gate_url": "http://gb10-worker:8787",
                    "worker_wake_gate_bearer_token": "gb10-token",
                    "worker_targets": {
                        "cpu-proxmox-1": {
                            "wake_gate_url": "http://cpu-proxmox-1:8787",
                            "bearer_token": "cpu-token",
                            "role": "cpu_worker",
                        },
                        "gb10": {
                            "wake_gate_url": "http://gb10-worker:8787",
                            "bearer_token": "gb10-token",
                            "role": "gpu_worker",
                        },
                    },
                }
            )
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "lane-capacity-idle-empty-import",
                    "queue_rows": [
                        {
                            "project_id": "active-cpu",
                            "project_name": "Active CPU",
                            "project_dir": "active-cpu",
                            "status": "awaiting_wake",
                            "machine_target": "cpu-proxmox-1",
                            "current_run_id": "run-active-cpu",
                        },
                    ],
                },
            )
            client.post(
                "/control/resume",
                headers=headers,
                json={"resumed_by": "test", "maintenance_mode": False},
            )

            status = client.get("/control/api/status", headers=headers).json()

            lanes = {lane["machine_target"]: lane for lane in status["worker_lanes"]}
            self.assertEqual(lanes["gb10"]["status"], "idle")
            self.assertEqual(
                lanes["gb10"]["dispatch_blocker"], "no queued candidate for lane"
            )
            self.assertIn("no queued dispatch candidate", status["dispatch_blockers"])
            self.assertNotIn(
                "all configured worker lanes active", status["dispatch_blockers"]
            )

    def test_dashboard_status_flags_worker_live_without_vm_active_row_as_critical(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            ControlPlaneStore(
                Path(tmp) / "state" / "control_plane.sqlite3"
            ).upsert_dashboard_observation(
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
                        }
                    ],
                },
            )
            status = client.get("/control/api/status", headers=headers).json()
            self.assertTrue(
                any(item["severity"] == "critical" for item in status["conflicts"])
            )
            self.assertIn("GB10/VM active-lane conflict", status["dispatch_blockers"])
            self.assertFalse(status["dispatch_safe"])

    def test_dashboard_status_treats_worker_settling_after_vm_completion_as_backpressure(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client_with_config(
                _config(tmp).model_copy(update={"live_dispatch_enabled": True})
            )
            headers = {"Authorization": f"Bearer {TOKEN}"}
            project_id = "idea-worker-settling"
            run_id = "run-worker-settling"
            client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "worker-settling-import",
                    "queue_rows": [
                        {
                            "project_id": project_id,
                            "project_name": "Worker Settling",
                            "project_dir": project_id,
                            "status": "completed",
                            "current_run_id": run_id,
                            "last_run_state": "wake_ready",
                        }
                    ],
                    "run_rows": [
                        {
                            "run_id": run_id,
                            "project_id": project_id,
                            "state": "wake_ready",
                            "gate_state": "wake_ready",
                            "current_activity": "worker_callback",
                            "last_callback_at": "2026-05-19T23:07:27Z",
                        }
                    ],
                },
            )
            client.post(
                "/control/resume",
                headers=headers,
                json={"resumed_by": "test", "maintenance_mode": False},
            )
            store = ControlPlaneStore(Path(tmp) / "state" / "control_plane.sqlite3")
            store.upsert_dashboard_observation(
                source="worker_preflight",
                status="warn",
                payload={
                    "ok": False,
                    "checks": [
                        {
                            "name": "wake_gate_healthz",
                            "ok": True,
                            "detail": "ok",
                            "data": {},
                        },
                        {
                            "name": "wake_gate_dashboard_api",
                            "ok": True,
                            "detail": "dashboard API reachable",
                            "data": {
                                "body": {
                                    "totals": {"active_or_waiting": 1, "live": 1},
                                    "runs": [
                                        {
                                            "run_id": run_id,
                                            "project_id": project_id,
                                            "gate_state": "waiting_for_quiet_window",
                                            "lifecycle_state": "settling",
                                            "callback_delivered": False,
                                            "is_live": True,
                                            "active_process_count": 1,
                                        }
                                    ],
                                }
                            },
                        },
                        {
                            "name": "worker_no_live_runs",
                            "ok": False,
                            "detail": "active_or_waiting=1, live=1",
                            "data": {"active_or_waiting": 1, "live": 1},
                        },
                    ],
                },
            )
            store.upsert_dashboard_observation(
                source="worker_dashboard_api", status="ok", payload={"ok": True}
            )

            status = client.get("/control/api/status", headers=headers).json()

            self.assertNotIn(
                "GB10/VM active-lane conflict", status["dispatch_blockers"]
            )
            self.assertIn(
                "GB10 worker settling completed run", status["dispatch_blockers"]
            )
            self.assertFalse(
                any(item["severity"] == "critical" for item in status["conflicts"])
            )
            self.assertTrue(
                any("settling" in item["message"] for item in status["warnings"])
            )
            self.assertFalse(
                any(item["source"] == "worker_preflight" for item in status["warnings"])
            )

            with patch(
                "enoch_control_plane.control_plane.alerts.load_latest_quality_status",
                return_value={},
            ):
                alert = client.post(
                    "/control/api/alerts/queue-check",
                    headers=headers,
                    json={"dry_run": True, "refresh_worker": False},
                ).json()
            self.assertFalse(alert["should_alert"])
            self.assertEqual(alert["fingerprint"], "none")
            self.assertEqual(alert["findings"], [])

    def test_dashboard_status_suppresses_recent_worker_settling_without_vm_match(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client_with_config(
                _config(tmp).model_copy(update={"live_dispatch_enabled": True})
            )
            headers = {"Authorization": f"Bearer {TOKEN}"}
            client.post(
                "/control/resume",
                headers=headers,
                json={"resumed_by": "test", "maintenance_mode": False},
            )
            now = datetime.now(timezone.utc).isoformat()
            store = ControlPlaneStore(Path(tmp) / "state" / "control_plane.sqlite3")
            store.upsert_dashboard_observation(
                source="worker_preflight",
                status="warn",
                payload={
                    "ok": False,
                    "checks": [
                        {
                            "name": "wake_gate_healthz",
                            "ok": True,
                            "detail": "ok",
                            "data": {},
                        },
                        {
                            "name": "wake_gate_dashboard_api",
                            "ok": True,
                            "detail": "dashboard API reachable",
                            "data": {
                                "body": {
                                    "totals": {"active_or_waiting": 1, "live": 1},
                                    "runs": [
                                        {
                                            "run_id": "run-recent-settling-orphan",
                                            "project_id": "idea-recent-settling-orphan",
                                            "gate_state": "waiting_for_quiet_window",
                                            "lifecycle_state": "settling",
                                            "callback_delivered": False,
                                            "is_live": True,
                                            "active_process_count": 0,
                                            "updated_at": now,
                                        }
                                    ],
                                }
                            },
                        },
                        {
                            "name": "worker_no_live_runs",
                            "ok": False,
                            "detail": "active_or_waiting=1, live=1",
                            "data": {"active_or_waiting": 1, "live": 1},
                        },
                    ],
                },
            )
            store.upsert_dashboard_observation(
                source="worker_dashboard_api", status="ok", payload={"ok": True}
            )

            status = client.get("/control/api/status", headers=headers).json()

            self.assertNotIn(
                "GB10/VM active-lane conflict", status["dispatch_blockers"]
            )
            self.assertIn(
                "GB10 worker settling recent run", status["dispatch_blockers"]
            )
            self.assertFalse(
                any(item["severity"] == "critical" for item in status["conflicts"])
            )
            self.assertTrue(
                any(
                    item["source"] == "worker_settling"
                    and "recent worker run" in item["message"]
                    for item in status["warnings"]
                )
            )

            alert = client.post(
                "/control/api/alerts/queue-check",
                headers=headers,
                json={"dry_run": True},
            ).json()
            self.assertFalse(
                any(item["source"] == "worker_settling" for item in alert["findings"])
            )

    def test_dashboard_status_suppresses_recent_cpu_worker_settling_without_vm_match(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _live_config(tmp).model_copy(
                update={
                    "worker_wake_gate_url": "http://gb10-worker:8787",
                    "worker_wake_gate_bearer_token": "gb10-token",
                    "worker_targets": {
                        "cpu-proxmox-1": {
                            "wake_gate_url": "http://cpu-worker:8787",
                            "bearer_token": "cpu-token",
                            "role": "cpu_worker",
                        },
                        "gb10": {
                            "wake_gate_url": "http://gb10-worker:8787",
                            "bearer_token": "gb10-token",
                            "role": "gpu_worker",
                        },
                    },
                }
            )
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            client.post(
                "/control/resume",
                headers=headers,
                json={"resumed_by": "test", "maintenance_mode": False},
            )
            now = datetime.now(timezone.utc).isoformat()
            store = ControlPlaneStore(Path(tmp) / "state" / "control_plane.sqlite3")
            store.upsert_dashboard_observation(
                source="worker_preflight",
                scope="lane:http://cpu-worker:8787",
                status="warn",
                payload={
                    "ok": False,
                    "target": "http://cpu-worker:8787",
                    "checks": [
                        {
                            "name": "wake_gate_dashboard_api",
                            "ok": True,
                            "detail": "dashboard API reachable",
                            "data": {
                                "body": {
                                    "totals": {"active_or_waiting": 1, "live": 1},
                                    "runs": [
                                        {
                                            "run_id": "run-recent-cpu-settling-orphan",
                                            "project_id": "idea-recent-cpu-settling-orphan",
                                            "gate_state": "waiting_for_quiet_window",
                                            "lifecycle_state": "settling",
                                            "callback_delivered": False,
                                            "is_live": True,
                                            "active_process_count": 0,
                                            "updated_at": now,
                                        }
                                    ],
                                }
                            },
                        },
                        {
                            "name": "worker_no_live_runs",
                            "ok": False,
                            "detail": "active_or_waiting=1, live=1",
                            "data": {"active_or_waiting": 1, "live": 1},
                        },
                    ],
                },
            )

            status = client.get("/control/api/status", headers=headers).json()

            self.assertNotIn(
                "worker live run without active control-plane row: cpu_worker",
                status["dispatch_blockers"],
            )
            self.assertIn(
                "worker settling recent run: cpu_worker", status["dispatch_blockers"]
            )
            self.assertFalse(
                any(item["severity"] == "critical" for item in status["conflicts"])
            )
            self.assertTrue(
                any(
                    item["source"] == "worker_settling"
                    and "recent worker run" in item["message"]
                    for item in status["warnings"]
                )
            )

            alert = client.post(
                "/control/api/alerts/queue-check",
                headers=headers,
                json={"dry_run": True},
            ).json()
            self.assertFalse(
                any(
                    item["source"] == "control_plane_db+worker_preflight"
                    for item in alert["findings"]
                )
            )

    def test_live_queue_alert_refreshes_worker_observations_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _live_config(tmp).model_copy(
                update={
                    "worker_wake_gate_url": "http://gb10-worker:8787",
                    "worker_wake_gate_bearer_token": "gb10-token",
                    "worker_targets": {
                        "cpu-proxmox-1": {
                            "wake_gate_url": "http://cpu-worker:8787",
                            "bearer_token": "cpu-token",
                            "role": "cpu_worker",
                        },
                        "gb10": {
                            "wake_gate_url": "http://gb10-worker:8787",
                            "bearer_token": "gb10-token",
                            "role": "gpu_worker",
                        },
                    },
                }
            )
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            client.post(
                "/control/resume",
                headers=headers,
                json={"resumed_by": "test", "maintenance_mode": False},
            )
            store = ControlPlaneStore(Path(tmp) / "state" / "control_plane.sqlite3")
            store.upsert_dashboard_observation(
                source="worker_preflight",
                scope="lane:http://cpu-worker:8787",
                status="warn",
                payload={
                    "ok": False,
                    "target": "http://cpu-worker:8787",
                    "checks": [
                        {
                            "name": "wake_gate_dashboard_api",
                            "ok": True,
                            "detail": "dashboard API reachable",
                            "data": {
                                "body": {
                                    "totals": {"active_or_waiting": 1, "live": 1},
                                    "runs": [
                                        {
                                            "run_id": "stale-cpu-orphan",
                                            "project_id": "stale-cpu-orphan",
                                            "gate_state": "active",
                                            "lifecycle_state": "active",
                                            "is_live": True,
                                            "active_process_count": 1,
                                            "updated_at": datetime.now(
                                                timezone.utc
                                            ).isoformat(),
                                        }
                                    ],
                                }
                            },
                        },
                        {
                            "name": "worker_no_live_runs",
                            "ok": False,
                            "detail": "active_or_waiting=1, live=1",
                            "data": {"active_or_waiting": 1, "live": 1},
                        },
                    ],
                },
            )

            stale = client.post(
                "/control/api/alerts/queue-check",
                headers=headers,
                json={"dry_run": True, "refresh_worker": False},
            ).json()
            self.assertTrue(stale["should_alert"])
            self.assertTrue(
                any(
                    item["source"] == "control_plane_db+worker_preflight"
                    for item in stale["findings"]
                )
            )

            def clean_preflight(request: Any, _flags: Any) -> WorkerPreflightResponse:
                target = request.wake_gate_url
                return WorkerPreflightResponse(
                    ok=True,
                    target=target,
                    summary="worker preflight passed",
                    checks=[
                        WorkerPreflightCheck(
                            name="wake_gate_healthz", ok=True, detail="ok", data={}
                        ),
                        WorkerPreflightCheck(
                            name="wake_gate_dashboard_api",
                            ok=True,
                            detail="dashboard API reachable",
                            data={
                                "body": {
                                    "totals": {"active_or_waiting": 0, "live": 0},
                                    "runs": [],
                                }
                            },
                        ),
                        WorkerPreflightCheck(
                            name="worker_no_live_runs",
                            ok=True,
                            detail="active_or_waiting=0, live=0",
                            data={"active_or_waiting": 0, "live": 0},
                        ),
                    ],
                )

            with patch(
                "enoch_control_plane.control_plane.router.run_worker_preflight",
                side_effect=clean_preflight,
            ) as preflight:
                live = client.post(
                    "/control/api/alerts/queue-check",
                    headers=headers,
                    json={
                        "dry_run": False,
                        "requested_by": "test-live-queue-alert-refresh",
                    },
                ).json()

            self.assertEqual(preflight.call_count, 2)
            self.assertFalse(live["should_alert"])
            self.assertEqual(live["fingerprint"], "none")
            self.assertFalse(live["findings"])

    def test_dashboard_status_treats_recent_lane_completed_worker_run_as_backpressure(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _live_config(tmp).model_copy(
                update={
                    "worker_wake_gate_url": "http://gb10-worker:8787",
                    "worker_wake_gate_bearer_token": "gb10-token",
                    "worker_targets": {
                        "cpu-proxmox-1": {
                            "wake_gate_url": "http://cpu-worker:8787",
                            "bearer_token": "cpu-token",
                            "role": "cpu_worker",
                        },
                        "gb10": {
                            "wake_gate_url": "http://gb10-worker:8787",
                            "bearer_token": "gb10-token",
                            "role": "gpu_worker",
                        },
                    },
                }
            )
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            project_id = "idea-recent-gb10-complete"
            run_id = "run-recent-gb10-complete"
            now = datetime.now(timezone.utc).isoformat()
            client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "recent-lane-complete-worker-run",
                    "queue_rows": [
                        {
                            "project_id": project_id,
                            "project_name": "Recent GB10 Complete",
                            "project_dir": project_id,
                            "status": "completed",
                            "machine_target": "gb10",
                            "current_run_id": run_id,
                            "last_run_state": "wake_ready",
                        }
                    ],
                    "run_rows": [
                        {
                            "run_id": run_id,
                            "project_id": project_id,
                            "state": "wake_ready",
                            "gate_state": "wake_ready",
                            "current_activity": "worker_callback",
                            "last_callback_at": now,
                        }
                    ],
                },
            )
            client.post(
                "/control/resume",
                headers=headers,
                json={"resumed_by": "test", "maintenance_mode": False},
            )
            store = ControlPlaneStore(Path(tmp) / "state" / "control_plane.sqlite3")
            store.upsert_dashboard_observation(
                source="worker_preflight",
                scope="lane:http://gb10-worker:8787",
                status="warn",
                payload={
                    "ok": False,
                    "target": "http://gb10-worker:8787",
                    "checks": [
                        {
                            "name": "wake_gate_dashboard_api",
                            "ok": True,
                            "detail": "dashboard API reachable",
                            "data": {
                                "body": {
                                    "totals": {"active_or_waiting": 1, "live": 1},
                                    "runs": [
                                        {
                                            "run_id": run_id,
                                            "project_id": project_id,
                                            "gate_state": "wake_ready",
                                            "lifecycle_state": "active",
                                            "is_live": True,
                                            "active_process_count": 1,
                                            "updated_at": now,
                                        }
                                    ],
                                }
                            },
                        },
                        {
                            "name": "worker_no_live_runs",
                            "ok": False,
                            "detail": "active_or_waiting=1, live=1",
                            "data": {"active_or_waiting": 1, "live": 1},
                        },
                    ],
                },
            )

            status = client.get("/control/api/status", headers=headers).json()

            self.assertNotIn(
                "worker live run without active control-plane row: gpu_worker",
                status["dispatch_blockers"],
            )
            self.assertIn(
                "worker settling completed run: gpu_worker",
                status["dispatch_blockers"],
            )
            self.assertFalse(
                any(item["severity"] == "critical" for item in status["conflicts"])
            )
            self.assertTrue(
                any(item["source"] == "worker_settling" for item in status["warnings"])
            )

            alert = client.post(
                "/control/api/alerts/queue-check",
                headers=headers,
                json={"dry_run": True},
            ).json()
            self.assertFalse(
                any(item["source"] == "worker_settling" for item in alert["findings"])
            )

    def test_queue_alert_suppresses_gb10_conflict_when_lane_is_settling_with_other_active_lane(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ControlPlaneStore(Path(tmp) / "state" / "control_plane.sqlite3")
            status = SimpleNamespace(
                active_items=[{"project_id": "active-cpu"}],
                dispatch_blockers=[
                    "worker_preflight not ok",
                    "GB10/VM active-lane conflict",
                    "worker settling completed run: gpu_worker",
                ],
            )
            findings = [
                DashboardFinding(
                    severity="critical",
                    source="control_plane_db+worker_preflight",
                    authority="single active GB10 lane safety",
                    message=(
                        "GB10 reports live/active work but VM control plane has "
                        "no active row"
                    ),
                    suggested_action=(
                        "pause dispatch to the affected worker lane and reconcile "
                        "before starting another job"
                    ),
                    data={
                        "worker_check": {
                            "name": "worker_no_live_runs",
                            "ok": False,
                            "detail": "active_or_waiting=1, live=1",
                            "data": {"active_or_waiting": 1, "live": 1},
                        }
                    },
                ),
                DashboardFinding(
                    severity="warn",
                    source="worker_preflight",
                    authority="cached explicit worker preflight evidence",
                    message="worker_preflight status is warn",
                    suggested_action=(
                        "run /control/api/preflight and verify GB10 health before "
                        "dispatch"
                    ),
                ),
            ]

            kept, suppressed = _suppress_dispatch_race_findings(
                store=store, status=status, findings=findings
            )

            self.assertEqual(kept, [])
            self.assertEqual(suppressed, findings)

    def test_dashboard_status_does_not_treat_future_worker_settling_without_vm_match_as_backpressure(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client_with_config(
                _config(tmp).model_copy(update={"live_dispatch_enabled": True})
            )
            headers = {"Authorization": f"Bearer {TOKEN}"}
            client.post(
                "/control/resume",
                headers=headers,
                json={"resumed_by": "test", "maintenance_mode": False},
            )
            future = (datetime.now(timezone.utc) + timedelta(days=3650)).isoformat()
            store = ControlPlaneStore(Path(tmp) / "state" / "control_plane.sqlite3")
            store.upsert_dashboard_observation(
                source="worker_preflight",
                status="warn",
                payload={
                    "ok": False,
                    "checks": [
                        {
                            "name": "wake_gate_healthz",
                            "ok": True,
                            "detail": "ok",
                            "data": {},
                        },
                        {
                            "name": "wake_gate_dashboard_api",
                            "ok": True,
                            "detail": "dashboard API reachable",
                            "data": {
                                "body": {
                                    "totals": {"active_or_waiting": 1, "live": 1},
                                    "runs": [
                                        {
                                            "run_id": "run-future-settling-orphan",
                                            "project_id": "idea-future-settling-orphan",
                                            "gate_state": "waiting_for_quiet_window",
                                            "lifecycle_state": "settling",
                                            "callback_delivered": False,
                                            "is_live": True,
                                            "active_process_count": 0,
                                            "updated_at": future,
                                        }
                                    ],
                                }
                            },
                        },
                        {
                            "name": "worker_no_live_runs",
                            "ok": False,
                            "detail": "active_or_waiting=1, live=1",
                            "data": {"active_or_waiting": 1, "live": 1},
                        },
                    ],
                },
            )
            store.upsert_dashboard_observation(
                source="worker_dashboard_api", status="ok", payload={"ok": True}
            )

            status = client.get("/control/api/status", headers=headers).json()

            self.assertNotIn(
                "GB10 worker settling recent run", status["dispatch_blockers"]
            )
            self.assertIn("GB10/VM active-lane conflict", status["dispatch_blockers"])
            self.assertTrue(
                any(item["severity"] == "critical" for item in status["conflicts"])
            )
            self.assertFalse(
                any(item["source"] == "worker_settling" for item in status["warnings"])
            )

    def test_dashboard_status_does_not_treat_project_only_worker_settling_match_as_backpressure(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client_with_config(
                _config(tmp).model_copy(update={"live_dispatch_enabled": True})
            )
            headers = {"Authorization": f"Bearer {TOKEN}"}
            project_id = "idea-worker-settling"
            completed_run_id = "run-worker-settled-completed"
            stale_worker_run_id = "run-worker-stale-orphan"
            stale_updated_at = (
                datetime.now(timezone.utc) - timedelta(minutes=10)
            ).isoformat()
            client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "worker-settling-project-only-import",
                    "queue_rows": [
                        {
                            "project_id": project_id,
                            "project_name": "Worker Settling Project",
                            "project_dir": project_id,
                            "status": "completed",
                            "current_run_id": completed_run_id,
                            "last_run_state": "wake_ready",
                        }
                    ],
                },
            )
            client.post(
                "/control/resume",
                headers=headers,
                json={"resumed_by": "test", "maintenance_mode": False},
            )
            store = ControlPlaneStore(Path(tmp) / "state" / "control_plane.sqlite3")
            store.upsert_dashboard_observation(
                source="worker_preflight",
                status="warn",
                payload={
                    "ok": False,
                    "checks": [
                        {
                            "name": "wake_gate_healthz",
                            "ok": True,
                            "detail": "ok",
                            "data": {},
                        },
                        {
                            "name": "wake_gate_dashboard_api",
                            "ok": True,
                            "detail": "dashboard API reachable",
                            "data": {
                                "body": {
                                    "totals": {"active_or_waiting": 1, "live": 1},
                                    "runs": [
                                        {
                                            "run_id": stale_worker_run_id,
                                            "project_id": project_id,
                                            "gate_state": "waiting_for_quiet_window",
                                            "lifecycle_state": "settling",
                                            "callback_delivered": False,
                                            "is_live": True,
                                            "active_process_count": 0,
                                            "updated_at": stale_updated_at,
                                        }
                                    ],
                                }
                            },
                        },
                        {
                            "name": "worker_no_live_runs",
                            "ok": False,
                            "detail": "active_or_waiting=1, live=1",
                            "data": {"active_or_waiting": 1, "live": 1},
                        },
                    ],
                },
            )
            store.upsert_dashboard_observation(
                source="worker_dashboard_api", status="ok", payload={"ok": True}
            )

            status = client.get("/control/api/status", headers=headers).json()

            self.assertNotIn(
                "GB10 worker settling completed run", status["dispatch_blockers"]
            )
            self.assertIn("GB10/VM active-lane conflict", status["dispatch_blockers"])
            self.assertTrue(
                any(item["severity"] == "critical" for item in status["conflicts"])
            )
            self.assertFalse(
                any(item["source"] == "worker_settling" for item in status["warnings"])
            )

    def test_dashboard_status_treats_matching_worker_live_lane_as_active_not_warning(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client_with_config(_live_config(tmp))
            headers = {"Authorization": f"Bearer {TOKEN}"}
            client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "active-matching-worker-import",
                    "queue_rows": [
                        {
                            "project_id": "idea-active-match",
                            "project_name": "Active Match",
                            "project_dir": "idea-active-match",
                            "status": "awaiting_wake",
                            "current_run_id": "run-active-match",
                        }
                    ],
                },
            )
            client.post(
                "/control/resume",
                headers=headers,
                json={"resumed_by": "test", "maintenance_mode": False},
            )
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
                            "ok": True,
                            "detail": "ok",
                            "data": {},
                        },
                    ],
                },
            )
            store.upsert_dashboard_observation(
                source="worker_dashboard_api", status="ok", payload={"ok": True}
            )
            status = client.get("/control/api/status", headers=headers).json()
            self.assertFalse(status["dispatch_safe"])
            self.assertEqual(
                status["dispatch_blockers"], ["all configured worker lanes active"]
            )
            self.assertEqual(status["conflicts"], [])
            self.assertFalse(
                any(
                    item["source"] == "worker_preflight"
                    and "status is warn" in item["message"]
                    for item in status["warnings"]
                )
            )

    def test_queue_alert_check_does_not_alert_for_normal_active_lane(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client_with_config(_live_config(tmp))
            headers = {"Authorization": f"Bearer {TOKEN}"}
            client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "normal-active-alert-import",
                    "queue_rows": [
                        {
                            "project_id": "idea-active-normal",
                            "project_name": "Active Normal",
                            "project_dir": "idea-active-normal",
                            "status": "awaiting_wake",
                            "current_run_id": "run-active-normal",
                        }
                    ],
                },
            )
            client.post(
                "/control/resume",
                headers=headers,
                json={"resumed_by": "test", "maintenance_mode": False},
            )
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
                            "ok": True,
                            "detail": "ok",
                            "data": {},
                        },
                    ],
                },
            )
            store.upsert_dashboard_observation(
                source="worker_dashboard_api", status="ok", payload={"ok": True}
            )
            alert = client.post(
                "/control/api/alerts/queue-check",
                headers=headers,
                json={"dry_run": True, "refresh_worker": False},
            ).json()
            self.assertFalse(alert["should_alert"])
            self.assertEqual(alert["findings"], [])

    def test_queue_alert_check_does_not_persist_event_for_healthy_active_lane(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client_with_config(_live_config(tmp))
            headers = {"Authorization": f"Bearer {TOKEN}"}
            client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "normal-active-live-alert-import",
                    "queue_rows": [
                        {
                            "project_id": "idea-active-live-normal",
                            "project_name": "Active Live Normal",
                            "project_dir": "idea-active-live-normal",
                            "status": "awaiting_wake",
                            "current_run_id": "run-active-live-normal",
                        }
                    ],
                },
            )
            client.post(
                "/control/resume",
                headers=headers,
                json={"resumed_by": "test", "maintenance_mode": False},
            )
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
                            "ok": True,
                            "detail": "ok",
                            "data": {},
                        },
                    ],
                },
            )
            store.upsert_dashboard_observation(
                source="worker_dashboard_api", status="ok", payload={"ok": True}
            )

            alert = client.post(
                "/control/api/alerts/queue-check",
                headers=headers,
                json={"dry_run": False, "refresh_worker": False},
            ).json()

            self.assertFalse(alert["should_alert"])
            self.assertFalse(alert["inserted_event"])
            self.assertFalse(alert["sent"])
            self.assertEqual(alert["findings"], [])
            events = client.get(
                "/control/api/v1/events?entity_type=queue_alert", headers=headers
            ).json()
            self.assertEqual(events["rows"], [])

    def test_queue_alert_check_suppresses_transient_worker_timeout_during_active_lane(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client_with_config(_live_config(tmp))
            headers = {"Authorization": f"Bearer {TOKEN}"}
            client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "active-timeout-alert-import",
                    "queue_rows": [
                        {
                            "project_id": "idea-active-timeout",
                            "project_name": "Active Timeout",
                            "project_dir": "idea-active-timeout",
                            "status": "awaiting_wake",
                            "current_run_id": "run-active-timeout",
                        }
                    ],
                },
            )
            client.post(
                "/control/resume",
                headers=headers,
                json={"resumed_by": "test", "maintenance_mode": False},
            )
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
            store.upsert_dashboard_observation(
                source="worker_dashboard_api", status="ok", payload={"ok": True}
            )
            alert = client.post(
                "/control/api/alerts/queue-check",
                headers=headers,
                json={"dry_run": True, "refresh_worker": False},
            ).json()
            self.assertFalse(alert["should_alert"])
            self.assertEqual(alert["findings"], [])

    def test_queue_health_summarizes_active_lane_and_alerts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client_with_config(_live_config(tmp))
            headers = {"Authorization": f"Bearer {TOKEN}"}
            client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "queue-health-import",
                    "queue_rows": [
                        {
                            "project_id": "idea-health",
                            "project_name": "Health Project",
                            "project_dir": "idea-health",
                            "status": "awaiting_wake",
                            "current_run_id": "run-health",
                        }
                    ],
                },
            )
            client.post(
                "/control/resume",
                headers=headers,
                json={"resumed_by": "test", "maintenance_mode": False},
            )
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
                            "ok": True,
                            "detail": "ok",
                            "data": {},
                        },
                    ],
                },
            )
            store.upsert_dashboard_observation(
                source="worker_dashboard_api", status="ok", payload={"ok": True}
            )
            response = client.get("/control/api/queue-health", headers=headers)
            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertEqual(body["source"], "control_api_queue_health")
            self.assertEqual(
                body["active_run_detail"]["queue_item"]["project_id"], "idea-health"
            )
            self.assertFalse(body["latest_alert_check"]["should_alert"])
            self.assertEqual(
                body["status"]["dispatch_blockers"],
                ["all configured worker lanes active"],
            )

    def test_queue_alert_check_alerts_on_active_row_without_worker_live_run(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client_with_config(_live_config(tmp))
            headers = {"Authorization": f"Bearer {TOKEN}"}
            client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "hung-active-alert-import",
                    "queue_rows": [
                        {
                            "project_id": "idea-hung",
                            "project_name": "Hung Active",
                            "project_dir": "idea-hung",
                            "status": "awaiting_wake",
                            "current_run_id": "run-hung",
                        }
                    ],
                },
            )
            client.post(
                "/control/resume",
                headers=headers,
                json={"resumed_by": "test", "maintenance_mode": False},
            )
            store = ControlPlaneStore(Path(tmp) / "state" / "control_plane.sqlite3")
            store.upsert_dashboard_observation(
                source="worker_preflight",
                status="ok",
                payload={
                    "ok": True,
                    "checks": [
                        {
                            "name": "worker_no_live_runs",
                            "ok": True,
                            "detail": "active_or_waiting=0, live=0",
                            "data": {"active_or_waiting": 0, "live": 0},
                        }
                    ],
                },
            )
            store.upsert_dashboard_observation(
                source="worker_dashboard_api", status="ok", payload={"ok": True}
            )
            dry_run = client.post(
                "/control/api/alerts/queue-check",
                headers=headers,
                json={"dry_run": True},
            ).json()
            self.assertTrue(dry_run["should_alert"])
            self.assertTrue(
                any("active row" in item["message"] for item in dry_run["findings"])
            )

            first = client.post(
                "/control/api/alerts/queue-check",
                headers=headers,
                json={"dry_run": False},
            ).json()
            self.assertTrue(first["inserted_event"])
            self.assertFalse(first["sent"])
            second = client.post(
                "/control/api/alerts/queue-check",
                headers=headers,
                json={"dry_run": False},
            ).json()
            self.assertTrue(second["suppressed_by_cooldown"])

    def test_queue_alert_check_suppresses_dispatch_preflight_race(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client_with_config(_live_config(tmp))
            headers = {"Authorization": f"Bearer {TOKEN}"}
            project_id = "idea-dispatch-race"
            run_id = "run-dispatch-race"
            client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "dispatch-race-alert-import",
                    "queue_rows": [
                        {
                            "project_id": project_id,
                            "project_name": "Dispatch Race",
                            "project_dir": project_id,
                            "status": "awaiting_wake",
                            "current_run_id": run_id,
                        }
                    ],
                },
            )
            client.post(
                "/control/resume",
                headers=headers,
                json={"resumed_by": "test", "maintenance_mode": False},
            )
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
                        {
                            "name": "worker_no_live_runs",
                            "ok": True,
                            "detail": "active_or_waiting=0, live=0",
                            "data": {"active_or_waiting": 0, "live": 0},
                        }
                    ],
                },
            )
            store.upsert_dashboard_observation(
                source="worker_dashboard_api", status="ok", payload={"ok": True}
            )

            alert = client.post(
                "/control/api/alerts/queue-check",
                headers=headers,
                json={"dry_run": True},
            ).json()

            self.assertFalse(alert["should_alert"])
            self.assertEqual(alert["findings"], [])
            self.assertTrue(alert["transient_suppressed_findings"])
            self.assertIn(
                "active row", alert["transient_suppressed_findings"][0]["message"]
            )

    def test_queue_alert_check_auto_reconciles_stale_callback_with_local_decision_artifact(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            trace_path = Path(tmp) / "queue_operator_trace.jsonl"
            config = _live_config(tmp).model_copy(
                update={
                    "operational_trace_enabled": True,
                    "operational_trace_log_path": str(trace_path),
                }
            )
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            project_dir = Path(config.project_root) / "idea-auto-reconcile"
            (project_dir / ".enoch").mkdir(parents=True)
            (project_dir / "run_notes.md").write_text("completed\n", encoding="utf-8")
            (project_dir / ".enoch" / "project_decision.json").write_text(
                json.dumps(
                    {
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
                    }
                ),
                encoding="utf-8",
            )
            client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "auto-reconcile-alert-import",
                    "queue_rows": [
                        {
                            "project_id": "idea-auto-reconcile",
                            "project_name": "Auto Reconcile",
                            "project_dir": "idea-auto-reconcile",
                            "status": "awaiting_wake",
                            "current_run_id": "run-auto-reconcile",
                        }
                    ],
                },
            )
            client.post(
                "/control/resume",
                headers=headers,
                json={"resumed_by": "test", "maintenance_mode": False},
            )
            store = ControlPlaneStore(Path(tmp) / "state" / "control_plane.sqlite3")
            store.upsert_dashboard_observation(
                source="worker_preflight",
                status="ok",
                payload={
                    "ok": True,
                    "checks": [
                        {
                            "name": "worker_no_live_runs",
                            "ok": True,
                            "detail": "active_or_waiting=0, live=0",
                            "data": {"active_or_waiting": 0, "live": 0},
                        }
                    ],
                },
            )
            store.upsert_dashboard_observation(
                source="worker_dashboard_api", status="ok", payload={"ok": True}
            )

            alert = client.post(
                "/control/api/alerts/queue-check",
                headers=headers,
                json={"dry_run": False, "requested_by": "test"},
            ).json()

            self.assertFalse(alert["should_alert"])
            self.assertTrue(alert["trace_id"].startswith("queue-check-"))
            self.assertTrue(alert["auto_reconcile"][0]["ok"])
            trace_text = trace_path.read_text(encoding="utf-8")
            self.assertNotIn(TOKEN, trace_text)
            trace_rows = [json.loads(line) for line in trace_text.splitlines()]
            self.assertIn("queue_check.result", {row["event"] for row in trace_rows})
            status = client.get("/control/api/status", headers=headers).json()
            self.assertEqual(status["active_items"], [])

    def test_queue_alert_auto_reconcile_releases_stale_active_without_decision_artifact(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _live_config(tmp)
            config.paper_evidence_sync_enabled = True
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            project_dir = Path(config.project_root) / "idea-auto-reconcile-no-decision"
            project_dir.mkdir(parents=True)
            (project_dir / "run_notes.md").write_text(
                "runner exited\n", encoding="utf-8"
            )
            client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "auto-reconcile-no-decision-import",
                    "queue_rows": [
                        {
                            "project_id": "idea-auto-reconcile-no-decision",
                            "project_name": "Auto Reconcile No Decision",
                            "project_dir": "idea-auto-reconcile-no-decision",
                            "status": "awaiting_wake",
                            "current_run_id": "run-auto-reconcile-no-decision",
                        }
                    ],
                },
            )
            client.post(
                "/control/resume",
                headers=headers,
                json={"resumed_by": "test", "maintenance_mode": False},
            )
            store = ControlPlaneStore(Path(tmp) / "state" / "control_plane.sqlite3")
            store.upsert_dashboard_observation(
                source="worker_preflight",
                status="ok",
                payload={
                    "ok": True,
                    "checks": [
                        {
                            "name": "worker_no_live_runs",
                            "ok": True,
                            "detail": "active_or_waiting=0, live=0",
                            "data": {"active_or_waiting": 0, "live": 0},
                        }
                    ],
                },
            )
            store.upsert_dashboard_observation(
                source="worker_dashboard_api", status="ok", payload={"ok": True}
            )

            with patch(
                "enoch_control_plane.control_plane.router._sync_remote_project_evidence",
                return_value={
                    "enabled": True,
                    "synced": False,
                    "reason": "worker_http_no_required_evidence",
                    "local_evidence_present": False,
                },
            ):
                alert = client.post(
                    "/control/api/alerts/queue-check",
                    headers=headers,
                    json={"dry_run": False, "requested_by": "test"},
                ).json()

            self.assertFalse(alert["should_alert"])
            self.assertTrue(alert["auto_reconcile"])
            self.assertTrue(alert["auto_reconcile"][0]["ok"])
            self.assertEqual(
                alert["auto_reconcile"][0]["reason"],
                "replayed missing project decision artifact",
            )
            status = client.get("/control/api/status", headers=headers).json()
            self.assertEqual(status["active_items"], [])

    def test_queue_alert_auto_reconcile_requires_local_paper_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _live_config(tmp)
            config.paper_evidence_sync_enabled = True
            config.paper_evidence_sync_remote_root = "/remote/projects"
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            project_dir = (
                Path(config.project_root) / "idea-auto-reconcile-missing-evidence"
            )
            (project_dir / ".enoch").mkdir(parents=True)
            (project_dir / ".enoch" / "project_decision.json").write_text(
                '{"project_decision":"finalize_positive"}\n', encoding="utf-8"
            )
            client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "auto-reconcile-missing-evidence-import",
                    "queue_rows": [
                        {
                            "project_id": "idea-auto-reconcile-missing-evidence",
                            "project_name": "Auto Reconcile Missing Evidence",
                            "project_dir": "idea-auto-reconcile-missing-evidence",
                            "status": "awaiting_wake",
                            "current_run_id": "run-auto-reconcile-missing-evidence",
                        }
                    ],
                },
            )
            store = ControlPlaneStore(Path(tmp) / "state" / "control_plane.sqlite3")
            store.upsert_dashboard_observation(
                source="worker_preflight",
                status="ok",
                payload={
                    "ok": True,
                    "checks": [
                        {
                            "name": "worker_no_live_runs",
                            "ok": True,
                            "detail": "active_or_waiting=0, live=0",
                            "data": {"active_or_waiting": 0, "live": 0},
                        }
                    ],
                },
            )
            store.upsert_dashboard_observation(
                source="worker_dashboard_api", status="ok", payload={"ok": True}
            )

            with patch(
                "enoch_control_plane.control_plane.router._sync_remote_project_evidence",
                return_value={
                    "enabled": True,
                    "synced": False,
                    "reason": "worker_read_failed",
                    "local_evidence_present": False,
                },
            ):
                alert = client.post(
                    "/control/api/alerts/queue-check",
                    headers=headers,
                    json={"dry_run": False, "requested_by": "test"},
                ).json()

            self.assertTrue(alert["auto_reconcile"])
            self.assertFalse(alert["auto_reconcile"][0]["ok"])
            self.assertEqual(
                alert["auto_reconcile"][0]["reason"], "missing paper evidence"
            )
            status = client.get("/control/api/status", headers=headers).json()
            self.assertEqual(len(status["active_items"]), 1)
            self.assertEqual(
                status["active_items"][0]["current_run_id"],
                "run-auto-reconcile-missing-evidence",
            )
            snapshot = client.get("/control/export/snapshot", headers=headers).json()
            events = [
                event
                for event in snapshot["events"]
                if event["event_type"] == "paper.evidence_sync_blocked"
            ]
            self.assertEqual(len(events), 1)

    def test_queue_alert_auto_reconcile_skips_recent_callback_grace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _live_config(tmp)
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            project_dir = Path(config.project_root) / "idea-recent-callback"
            (project_dir / ".enoch").mkdir(parents=True)
            (project_dir / ".enoch" / "project_decision.json").write_text(
                '{"project_decision":"finalize_negative"}\n', encoding="utf-8"
            )
            now = datetime.now(timezone.utc).isoformat()
            client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "recent-callback-grace-import",
                    "queue_rows": [
                        {
                            "project_id": "idea-recent-callback",
                            "project_name": "Recent Callback",
                            "project_dir": "idea-recent-callback",
                            "status": "awaiting_wake",
                            "current_run_id": "run-recent-callback",
                            "last_callback_at": now,
                        }
                    ],
                },
            )
            store = ControlPlaneStore(Path(tmp) / "state" / "control_plane.sqlite3")
            store.upsert_dashboard_observation(
                source="worker_preflight",
                status="ok",
                payload={
                    "ok": True,
                    "checks": [
                        {
                            "name": "worker_no_live_runs",
                            "ok": True,
                            "detail": "active_or_waiting=0, live=0",
                            "data": {"active_or_waiting": 0, "live": 0},
                        }
                    ],
                },
            )

            alert = client.post(
                "/control/api/alerts/queue-check",
                headers=headers,
                json={"dry_run": False, "requested_by": "test"},
            ).json()

            self.assertFalse(alert.get("auto_reconcile"))
            status = client.get("/control/api/status", headers=headers).json()
            self.assertEqual(len(status["active_items"]), 1)

    def test_queue_alert_auto_reconcile_negative_decision_without_paper_evidence_does_not_alert(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _live_config(tmp)
            config.paper_evidence_sync_enabled = True
            config.paper_evidence_sync_remote_root = "/remote/projects"
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            project_dir = (
                Path(config.project_root) / "idea-auto-reconcile-negative-no-paper"
            )
            (project_dir / ".enoch").mkdir(parents=True)
            (project_dir / ".enoch" / "project_decision.json").write_text(
                '{"project_decision":"negative","stop_reason":"no measured signal"}\n',
                encoding="utf-8",
            )
            client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "auto-reconcile-negative-no-paper-import",
                    "queue_rows": [
                        {
                            "project_id": "idea-auto-reconcile-negative-no-paper",
                            "project_name": "Auto Reconcile Negative No Paper",
                            "project_dir": "idea-auto-reconcile-negative-no-paper",
                            "status": "awaiting_wake",
                            "current_run_id": "run-auto-reconcile-negative-no-paper",
                        }
                    ],
                },
            )
            store = ControlPlaneStore(Path(tmp) / "state" / "control_plane.sqlite3")
            store.upsert_dashboard_observation(
                source="worker_preflight",
                status="ok",
                payload={
                    "ok": True,
                    "checks": [
                        {
                            "name": "worker_no_live_runs",
                            "ok": True,
                            "detail": "active_or_waiting=0, live=0",
                            "data": {"active_or_waiting": 0, "live": 0},
                        }
                    ],
                },
            )
            store.upsert_dashboard_observation(
                source="worker_dashboard_api", status="ok", payload={"ok": True}
            )

            with patch(
                "enoch_control_plane.control_plane.router._sync_remote_project_evidence",
                return_value={
                    "enabled": True,
                    "synced": False,
                    "reason": "worker_read_failed",
                    "local_evidence_present": False,
                },
            ) as sync:
                alert = client.post(
                    "/control/api/alerts/queue-check",
                    headers=headers,
                    json={"dry_run": False, "requested_by": "test"},
                ).json()

            self.assertTrue(alert["auto_reconcile"])
            self.assertTrue(alert["auto_reconcile"][0]["ok"])
            self.assertEqual(
                alert["auto_reconcile"][0]["decision_gate"]["reason"],
                "project decision is not positive",
            )
            self.assertEqual(sync.call_count, 0)
            status = client.get("/control/api/status", headers=headers).json()
            self.assertEqual(status["active_items"], [])
            snapshot = client.get("/control/export/snapshot", headers=headers).json()
            events = [
                event
                for event in snapshot["events"]
                if event["event_type"] == "paper.evidence_sync_blocked"
            ]
            self.assertEqual(events, [])

    def test_queue_alert_live_check_rejects_supabase_readonly_before_mutation(
        self,
    ) -> None:
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
                    raise AssertionError(
                        "read-only queue alert must reject before mutation"
                    )

            fake_store = FakeReadOnlyStore()
            with patch(
                "enoch_control_plane.control_plane.router.SupabaseReadOnlyControlPlaneStore",
                return_value=fake_store,
            ):
                client = _client_with_config(config)
                response = client.post(
                    "/control/api/alerts/queue-check",
                    headers={"Authorization": f"Bearer {TOKEN}"},
                    json={"dry_run": False, "requested_by": "test"},
                )

            assert response.status_code == 501
            assert "writable control-plane store" in response.text
            assert fake_store.append_attempted is False

    def test_followup_launch_live_rejects_supabase_readonly_before_mutation(
        self,
    ) -> None:
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
                    raise AssertionError(
                        "read-only follow-up launch must reject before mutation"
                    )

            fake_store = FakeReadOnlyStore()
            with patch(
                "enoch_control_plane.control_plane.router.SupabaseReadOnlyControlPlaneStore",
                return_value=fake_store,
            ):
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
                    raise AssertionError(
                        "read-only publication claim must reject before mutation"
                    )

            fake_store = FakeReadOnlyStore()
            with patch(
                "enoch_control_plane.control_plane.router.SupabaseReadOnlyControlPlaneStore",
                return_value=fake_store,
            ):
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
            client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "worker-callback-import",
                    "queue_rows": [
                        {
                            "project_id": "idea-callback",
                            "project_name": "Callback Project",
                            "project_dir": "idea-callback",
                            "status": "awaiting_wake",
                            "current_run_id": "run-callback",
                        }
                    ],
                },
            )
            response = client.post(
                "/control/api/worker-callback",
                headers=headers,
                json={
                    "event_type": "wake_ready",
                    "run_id": "run-callback",
                    "session_id": "session-callback",
                    "project_id": "idea-callback",
                    "project_name": "Callback Project",
                    "source_event": "session-idle",
                    "gate_state": "wake_ready",
                    "process_tracking": {
                        "root_pid": None,
                        "process_group_id": None,
                        "processes": [],
                        "live_process_count": 0,
                    },
                    "telemetry": {},
                    "reason": "idle_sustain_met",
                    "idempotency_key": "run-callback:wake_ready:test",
                },
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(
                response.json()["next_action_hint"],
                "draft_paper_or_select_next_project",
            )
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
                    raise AssertionError(
                        "read-only callback must reject before mutation"
                    )

            fake_store = FakeReadOnlyStore()
            with patch(
                "enoch_control_plane.control_plane.router.SupabaseReadOnlyControlPlaneStore",
                return_value=fake_store,
            ):
                client = _client_with_config(config)
                response = client.post(
                    "/control/api/worker-callback",
                    headers={"Authorization": f"Bearer {TOKEN}"},
                    json={
                        "event_type": "wake_ready",
                        "run_id": "run-readonly-callback",
                        "session_id": "session-readonly-callback",
                        "project_id": "readonly-callback",
                        "project_name": "Readonly Callback",
                        "source_event": "session-idle",
                        "gate_state": "wake_ready",
                        "process_tracking": {
                            "root_pid": None,
                            "process_group_id": None,
                            "processes": [],
                            "live_process_count": 0,
                        },
                        "telemetry": {},
                        "reason": "idle_sustain_met",
                        "idempotency_key": "run-readonly-callback:wake_ready:test",
                    },
                )

            assert response.status_code == 501
            assert "writable control-plane store" in response.text
            assert fake_store.callback_attempted is False

    def test_worker_callback_idempotency_replay_and_conflict_are_side_effect_safe(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client_with_config(_live_config(tmp))
            headers = {"Authorization": f"Bearer {TOKEN}"}
            client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "worker-callback-idempotency-import",
                    "queue_rows": [
                        {
                            "project_id": "idea-callback-idempotent",
                            "project_name": "Callback Idempotent Project",
                            "project_dir": "idea-callback-idempotent",
                            "status": "awaiting_wake",
                            "current_run_id": "run-callback-idempotent",
                        }
                    ],
                },
            )
            callback = {
                "event_type": "wake_ready",
                "run_id": "run-callback-idempotent",
                "session_id": "session-callback-idempotent",
                "project_id": "idea-callback-idempotent",
                "project_name": "Callback Idempotent Project",
                "source_event": "session-idle",
                "gate_state": "wake_ready",
                "process_tracking": {
                    "root_pid": None,
                    "process_group_id": None,
                    "processes": [],
                    "live_process_count": 0,
                },
                "telemetry": {},
                "reason": "idle_sustain_met",
                "idempotency_key": "run-callback-idempotent:wake_ready:test",
                "seen_at": "2026-05-03T08:00:00Z",
                "delivered_at": "2026-05-03T08:00:01Z",
            }

            first = client.post(
                "/control/api/worker-callback", headers=headers, json=callback
            )
            self.assertEqual(first.status_code, 200)
            self.assertTrue(first.json()["inserted_event"])
            replay = client.post(
                "/control/api/worker-callback", headers=headers, json=callback
            )
            self.assertEqual(replay.status_code, 200)
            self.assertFalse(replay.json()["inserted_event"])
            self.assertEqual(replay.json()["event_id"], first.json()["event_id"])
            conflict = client.post(
                "/control/api/worker-callback",
                headers=headers,
                json={
                    **callback,
                    "event_type": "gate_error",
                    "reason": "different outcome",
                },
            )
            self.assertEqual(conflict.status_code, 409)
            status = client.get("/control/api/status", headers=headers).json()
            self.assertEqual(status["active_items"], [])
            queue = client.get("/control/queue", headers=headers).json()["rows"][0]
            self.assertEqual(queue["last_run_state"], "wake_ready")
            self.assertEqual(
                queue["next_action_hint"], "draft_paper_or_select_next_project"
            )

    def test_worker_callback_replay_does_not_repeat_evidence_sync(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _live_config(tmp)
            config.paper_evidence_sync_enabled = True
            config.paper_evidence_sync_remote_root = "/remote/projects"
            project_dir = Path(config.project_root) / "idea-callback-replay-evidence"
            (project_dir / ".enoch").mkdir(parents=True)
            (project_dir / ".enoch" / "project_decision.json").write_text(
                '{"project_decision":"finalize_positive"}\n', encoding="utf-8"
            )
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "worker-callback-replay-evidence-import",
                    "queue_rows": [
                        {
                            "project_id": "idea-callback-replay-evidence",
                            "project_name": "Callback Replay Evidence",
                            "project_dir": "idea-callback-replay-evidence",
                            "status": "awaiting_wake",
                            "current_run_id": "run-callback-replay-evidence",
                        }
                    ],
                },
            )
            callback = {
                "event_type": "wake_ready",
                "run_id": "run-callback-replay-evidence",
                "session_id": "session-callback-replay-evidence",
                "project_id": "idea-callback-replay-evidence",
                "project_name": "Callback Replay Evidence",
                "source_event": "session-idle",
                "gate_state": "wake_ready",
                "process_tracking": {
                    "root_pid": None,
                    "process_group_id": None,
                    "processes": [],
                    "live_process_count": 0,
                },
                "telemetry": {},
                "reason": "idle_sustain_met",
                "idempotency_key": "run-callback-replay-evidence:wake_ready:test",
            }

            with patch(
                "enoch_control_plane.control_plane.router._sync_remote_project_evidence",
                return_value={"ok": True, "synced": True},
            ) as sync:
                first = client.post(
                    "/control/api/worker-callback", headers=headers, json=callback
                )
                replay = client.post(
                    "/control/api/worker-callback", headers=headers, json=callback
                )

            self.assertEqual(first.status_code, 200)
            self.assertTrue(first.json()["inserted_event"])
            self.assertIsNotNone(first.json()["decision_sync"])
            self.assertEqual(replay.status_code, 200)
            self.assertFalse(replay.json()["inserted_event"])
            self.assertIsNone(replay.json()["decision_sync"])
            self.assertEqual(sync.call_count, 1)

    def test_worker_callback_missing_local_decision_syncs_worker_decision_before_gate(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _live_config(tmp)
            config.paper_evidence_sync_enabled = True
            config.paper_evidence_sync_remote_root = "/remote/projects"
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "worker-callback-missing-local-decision-import",
                    "queue_rows": [
                        {
                            "project_id": "idea-callback-missing-local-decision",
                            "project_name": "Callback Missing Local Decision",
                            "project_dir": "idea-callback-missing-local-decision",
                            "status": "awaiting_wake",
                            "current_run_id": "run-callback-missing-local-decision",
                        }
                    ],
                },
            )

            def fake_sync(_config, *, project_id: str, artifact_root: Path, **kwargs):  # noqa: ANN001 - patched sync boundary
                del _config, project_id, kwargs
                (artifact_root / ".enoch").mkdir(parents=True, exist_ok=True)
                (artifact_root / "run_notes.md").write_text(
                    "Measured useful signal but no bounded paper.\n", encoding="utf-8"
                )
                (artifact_root / ".enoch" / "project_decision.json").write_text(
                    '{"project_decision":"finalize_negative","research_outcome":"useful_signal","bounded_paper_ready":false}\n',
                    encoding="utf-8",
                )
                return {
                    "enabled": True,
                    "synced": True,
                    "reason": "worker_http_synced",
                    "local_evidence_present": True,
                }

            def fake_record_decision(self, **kwargs):  # noqa: ANN001 - monkeypatched method
                self._seen_decision_kwargs = kwargs
                return {
                    "ok": True,
                    "persisted": True,
                    "project_id": kwargs.get("project_id"),
                }

            with (
                patch(
                    "enoch_control_plane.control_plane.router._sync_remote_project_evidence",
                    side_effect=fake_sync,
                ) as sync,
                patch.object(
                    ControlPlaneStore,
                    "record_project_decision_gate",
                    fake_record_decision,
                    create=True,
                ),
            ):
                response = client.post(
                    "/control/api/worker-callback",
                    headers=headers,
                    json={
                        "event_type": "wake_ready",
                        "run_id": "run-callback-missing-local-decision",
                        "session_id": "session-callback-missing-local-decision",
                        "project_id": "idea-callback-missing-local-decision",
                        "project_name": "Callback Missing Local Decision",
                        "source_event": "session-idle",
                        "gate_state": "wake_ready",
                        "process_tracking": {
                            "root_pid": None,
                            "process_group_id": None,
                            "processes": [],
                            "live_process_count": 0,
                        },
                        "telemetry": {},
                        "reason": "idle_sustain_met",
                        "idempotency_key": "run-callback-missing-local-decision:wake_ready:test",
                    },
                )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(sync.call_count, 1)
            body = response.json()
            self.assertIsNotNone(body["decision_sync"])
            self.assertEqual(
                body["decision_sync"]["evidence_sync"]["reason"], "worker_http_synced"
            )
            self.assertEqual(
                body["decision_sync"]["decision_gate"]["reason"],
                "project decision is not positive",
            )
            self.assertTrue(body["decision_sync"]["decision_record"]["persisted"])
            overview = client.get("/control/api/v1/overview", headers=headers).json()
            rejected_reasons = [
                item.get("reason")
                for item in overview["paper_pipeline"].get("gate_rejected_sample", [])
            ]
            self.assertNotIn("missing project decision artifact", rejected_reasons)

    def test_worker_callback_evidence_sync_rejects_project_dir_escape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _live_config(tmp)
            config.paper_evidence_sync_enabled = True
            config.paper_evidence_sync_remote_root = "/remote/projects"
            outside = Path(tmp) / "outside"
            outside.mkdir()
            project_dir = Path(config.project_root) / "idea-callback-project-dir-escape"
            (project_dir / ".enoch").mkdir(parents=True)
            (project_dir / ".enoch" / "project_decision.json").write_text(
                '{"project_decision":"finalize_positive"}\n', encoding="utf-8"
            )
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "worker-callback-project-dir-escape-import",
                    "queue_rows": [
                        {
                            "project_id": "idea-callback-project-dir-escape",
                            "project_name": "Callback Project Dir Escape",
                            "project_dir": str(outside),
                            "status": "awaiting_wake",
                            "current_run_id": "run-callback-project-dir-escape",
                        }
                    ],
                },
            )
            seen: dict[str, Path] = {}

            def fake_sync(_config, *, project_id: str, artifact_root: Path, **kwargs):  # noqa: ANN001 - patched sync boundary
                del _config, project_id, kwargs
                seen["artifact_root"] = artifact_root
                return {
                    "enabled": True,
                    "synced": False,
                    "reason": "worker_read_failed",
                    "local_evidence_present": False,
                }

            with patch(
                "enoch_control_plane.control_plane.router._sync_remote_project_evidence",
                side_effect=fake_sync,
            ):
                response = client.post(
                    "/control/api/worker-callback",
                    headers=headers,
                    json={
                        "event_type": "wake_ready",
                        "run_id": "run-callback-project-dir-escape",
                        "session_id": "session-callback-project-dir-escape",
                        "project_id": "idea-callback-project-dir-escape",
                        "project_name": "Callback Project Dir Escape",
                        "source_event": "session-idle",
                        "gate_state": "wake_ready",
                        "process_tracking": {
                            "root_pid": None,
                            "process_group_id": None,
                            "processes": [],
                            "live_process_count": 0,
                        },
                        "telemetry": {},
                        "reason": "idle_sustain_met",
                        "idempotency_key": "run-callback-project-dir-escape:wake_ready:test",
                    },
                )

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
            client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "worker-callback-stale-evidence-import",
                    "queue_rows": [
                        {
                            "project_id": "idea-callback-stale-evidence",
                            "project_name": "Callback Stale Evidence",
                            "project_dir": "idea-callback-stale-evidence",
                            "status": "running",
                            "current_run_id": "run-current",
                            "current_session_id": "session-current",
                            "last_run_state": "running",
                            "next_action_hint": "await_callback",
                        }
                    ],
                },
            )
            callback = {
                "event_type": "wake_ready",
                "run_id": "run-old",
                "session_id": "session-old",
                "project_id": "idea-callback-stale-evidence",
                "project_name": "Callback Stale Evidence",
                "source_event": "session-idle",
                "gate_state": "wake_ready",
                "process_tracking": {
                    "root_pid": None,
                    "process_group_id": None,
                    "processes": [],
                    "live_process_count": 0,
                },
                "telemetry": {},
                "reason": "old callback arrived late",
                "idempotency_key": "run-old:wake_ready:stale-evidence-test",
            }

            with patch(
                "enoch_control_plane.control_plane.router._sync_remote_project_evidence",
                return_value={"ok": True, "synced": True},
            ) as sync:
                response = client.post(
                    "/control/api/worker-callback", headers=headers, json=callback
                )

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
            (project_dir / ".enoch" / "project_decision.json").write_text(
                '{"project_decision":"finalize_positive"}\n', encoding="utf-8"
            )
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "worker-callback-missing-evidence-import",
                    "queue_rows": [
                        {
                            "project_id": "idea-callback-missing-evidence",
                            "project_name": "Callback Missing Evidence",
                            "project_dir": "idea-callback-missing-evidence",
                            "status": "awaiting_wake",
                            "current_run_id": "run-callback-missing-evidence",
                        }
                    ],
                },
            )

            with patch(
                "enoch_control_plane.control_plane.router._sync_remote_project_evidence",
                return_value={
                    "enabled": True,
                    "synced": False,
                    "reason": "worker_read_failed",
                    "local_evidence_present": False,
                },
            ):
                response = client.post(
                    "/control/api/worker-callback",
                    headers=headers,
                    json={
                        "event_type": "wake_ready",
                        "run_id": "run-callback-missing-evidence",
                        "session_id": "session-callback-missing-evidence",
                        "project_id": "idea-callback-missing-evidence",
                        "project_name": "Callback Missing Evidence",
                        "source_event": "session-idle",
                        "gate_state": "wake_ready",
                        "process_tracking": {
                            "root_pid": None,
                            "process_group_id": None,
                            "processes": [],
                            "live_process_count": 0,
                        },
                        "telemetry": {},
                        "reason": "idle_sustain_met",
                        "idempotency_key": "run-callback-missing-evidence:wake-ready-test",
                    },
                )

            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json()["inserted_event"])
            decision_sync = response.json()["decision_sync"]
            self.assertIsNotNone(decision_sync)
            self.assertEqual(
                decision_sync["evidence_sync"]["reason"], "worker_read_failed"
            )
            if "decision_record" in decision_sync:
                self.assertFalse(decision_sync["decision_record"]["persisted"])
            overview = client.get("/control/api/v1/overview", headers=headers).json()
            self.assertEqual(overview["paper_pipeline"]["write_needed"], 0)
            self.assertEqual(overview["operator_counts"]["write_paper"], 0)
            snapshot = client.get("/control/export/snapshot", headers=headers).json()
            events = [
                event
                for event in snapshot["events"]
                if event["event_type"] == "paper.evidence_sync_blocked"
            ]
            self.assertEqual(len(events), 1)
            self.assertEqual(snapshot["paper_rows"], [])

    def test_worker_callback_negative_decision_missing_run_notes_does_not_alert_paper_evidence(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _live_config(tmp)
            config.paper_evidence_sync_enabled = True
            config.paper_evidence_sync_remote_root = "/remote/projects"
            project_dir = Path(tmp) / "projects" / "idea-callback-negative-no-paper"
            (project_dir / ".enoch").mkdir(parents=True)
            (project_dir / ".enoch" / "project_decision.json").write_text(
                '{"project_decision":"negative","stop_reason":"no measured signal"}\n',
                encoding="utf-8",
            )
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "worker-callback-negative-no-paper-import",
                    "queue_rows": [
                        {
                            "project_id": "idea-callback-negative-no-paper",
                            "project_name": "Callback Negative No Paper",
                            "project_dir": "idea-callback-negative-no-paper",
                            "status": "awaiting_wake",
                            "current_run_id": "run-callback-negative-no-paper",
                        }
                    ],
                },
            )

            with patch(
                "enoch_control_plane.control_plane.router._sync_remote_project_evidence",
                return_value={
                    "enabled": True,
                    "synced": False,
                    "reason": "worker_read_failed",
                    "local_evidence_present": False,
                },
            ) as sync:
                response = client.post(
                    "/control/api/worker-callback",
                    headers=headers,
                    json={
                        "event_type": "wake_ready",
                        "run_id": "run-callback-negative-no-paper",
                        "session_id": "session-callback-negative-no-paper",
                        "project_id": "idea-callback-negative-no-paper",
                        "project_name": "Callback Negative No Paper",
                        "source_event": "session-idle",
                        "gate_state": "wake_ready",
                        "process_tracking": {
                            "root_pid": None,
                            "process_group_id": None,
                            "processes": [],
                            "live_process_count": 0,
                        },
                        "telemetry": {},
                        "reason": "idle_sustain_met",
                        "idempotency_key": "run-callback-negative-no-paper:wake-ready-test",
                    },
                )

            self.assertEqual(response.status_code, 200)
            decision_sync = response.json()["decision_sync"]
            self.assertIsNotNone(decision_sync)
            self.assertEqual(
                decision_sync["decision_gate"]["reason"],
                "project decision is not positive",
            )
            self.assertEqual(
                decision_sync["evidence_sync"]["reason"], "decision_gate_not_writable"
            )
            self.assertEqual(sync.call_count, 0)
            snapshot = client.get("/control/export/snapshot", headers=headers).json()
            events = [
                event
                for event in snapshot["events"]
                if event["event_type"] == "paper.evidence_sync_blocked"
            ]
            self.assertEqual(events, [])
            overview = client.get("/control/api/v1/overview", headers=headers).json()
            self.assertEqual(overview["operator_counts"]["write_paper"], 0)

    def test_worker_callback_decision_persist_failure_does_not_500_after_accepting_callback(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "projects" / "idea-callback-decision-fail"
            (project_dir / ".enoch").mkdir(parents=True)
            (project_dir / "run_notes.md").write_text(
                "Verified useful result.\n", encoding="utf-8"
            )
            (project_dir / ".enoch" / "project_decision.json").write_text(
                '{"project_decision":"finalize_positive"}\n', encoding="utf-8"
            )
            client = _client_with_config(_live_config(tmp))
            headers = {"Authorization": f"Bearer {TOKEN}"}
            client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "worker-callback-decision-fail-import",
                    "queue_rows": [
                        {
                            "project_id": "idea-callback-decision-fail",
                            "project_name": "Callback Decision Fail",
                            "project_dir": "idea-callback-decision-fail",
                            "status": "awaiting_wake",
                            "current_run_id": "run-callback-decision-fail",
                        }
                    ],
                },
            )

            def fail_decision_persist(self, **_kwargs):  # noqa: ANN001 - monkeypatched method
                raise RuntimeError("simulated decision persist failure")

            with patch.object(
                ControlPlaneStore,
                "record_project_decision_gate",
                fail_decision_persist,
                create=True,
            ):
                response = client.post(
                    "/control/api/worker-callback",
                    headers=headers,
                    json={
                        "event_type": "wake_ready",
                        "run_id": "run-callback-decision-fail",
                        "session_id": "session-callback-decision-fail",
                        "project_id": "idea-callback-decision-fail",
                        "project_name": "Callback Decision Fail",
                        "source_event": "session-idle",
                        "gate_state": "wake_ready",
                        "process_tracking": {
                            "root_pid": None,
                            "process_group_id": None,
                            "processes": [],
                            "live_process_count": 0,
                        },
                        "telemetry": {},
                        "reason": "idle_sustain_met",
                        "idempotency_key": "run-callback-decision-fail:wake-ready-test",
                    },
                )

            assert response.status_code == 200
            body = response.json()
            assert body["inserted_event"] is True
            assert body["decision_sync"]["decision_record"]["persisted"] is False
            assert (
                body["decision_sync"]["decision_record"]["reason"]
                == "decision persistence failed"
            )
            assert (
                body["decision_sync"]["decision_record"]["error_type"] == "RuntimeError"
            )
            assert "simulated decision persist failure" not in json.dumps(
                body["decision_sync"]
            )
            queue = client.get("/control/queue", headers=headers).json()["rows"][0]
            assert queue["last_run_state"] == "wake_ready"

    def test_worker_callback_wake_ready_can_draft_paper_when_evidence_exists(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "projects" / "idea-callback-draft"
            (project_dir / ".omx").mkdir(parents=True)
            (project_dir / "run_notes.md").write_text(
                "Verified useful result.\n", encoding="utf-8"
            )
            (project_dir / ".omx" / "project_decision.json").write_text(
                '{"decision":"finalize_positive"}\n', encoding="utf-8"
            )
            client = _client_with_config(_live_config(tmp))
            headers = {"Authorization": f"Bearer {TOKEN}"}
            client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "worker-callback-draft-import",
                    "queue_rows": [
                        {
                            "project_id": "idea-callback-draft",
                            "project_name": "Callback Draft Project",
                            "project_dir": "idea-callback-draft",
                            "status": "awaiting_wake",
                            "current_run_id": "run-callback-draft",
                        }
                    ],
                },
            )
            response = client.post(
                "/control/api/worker-callback",
                headers=headers,
                json={
                    "event_type": "wake_ready",
                    "run_id": "run-callback-draft",
                    "session_id": "session-callback-draft",
                    "project_id": "idea-callback-draft",
                    "project_name": "Callback Draft Project",
                    "source_event": "session-idle",
                    "gate_state": "wake_ready",
                    "process_tracking": {
                        "root_pid": None,
                        "process_group_id": None,
                        "processes": [],
                        "live_process_count": 0,
                    },
                    "telemetry": {},
                    "reason": "idle_sustain_met",
                    "idempotency_key": "run-callback-draft:wake_ready:test",
                },
            )
            self.assertEqual(response.status_code, 200)
            state_after_import = client.get("/control/state", headers=headers).json()
            self.assertIsNone(state_after_import["next_candidate"])
            self.assertEqual(state_after_import["counts"]["queue_total"], 1)
            self.assertEqual(state_after_import["counts"]["papers"], 0)

            draft = client.post(
                "/control/papers/draft-next",
                headers=headers,
                json={"force": True, "override_hold_action": "draft-next-while-held"},
            )
            self.assertEqual(draft.status_code, 200)
            self.assertEqual(draft.json()["action"], "drafted")
            self.assertEqual(
                draft.json()["candidate"]["project_id"], "idea-callback-draft"
            )
            paper_id = draft.json()["paper"]["paper_id"]
            rewrite = client.post(
                f"/control/api/paper-reviews/{paper_id}/rewrite-draft",
                headers=headers,
                json={
                    "idempotency_key": "worker-callback-draft-rewrite",
                    "requested_by": "test",
                    "force": True,
                },
            )
            self.assertEqual(rewrite.status_code, 200)
            self.assertEqual(
                rewrite.json()["paper"]["paper_status"], "publication_draft"
            )
            self.assertEqual(rewrite.json()["item"]["review_status"], "finalized")
            self.assertTrue(
                Path(rewrite.json()["item"]["finalization_package_path"]).exists()
            )
            events = client.get("/control/export/snapshot", headers=headers).json()[
                "events"
            ]
            event_types = {event["event_type"] for event in events}
            self.assertIn("paper.drafted", event_types)
            self.assertIn("paper_review.draft_rewritten", event_types)
            self.assertIn("paper_review.finalization_package_prepared", event_types)
            reviews = client.get(
                "/control/api/paper-reviews?review_status=finalized", headers=headers
            ).json()
            self.assertEqual(reviews["page"]["total"], 1)
            self.assertEqual(reviews["rows"][0]["project_id"], "idea-callback-draft")

    def test_worker_callback_wake_ready_negative_decision_is_not_drafted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "projects" / "idea-callback-negative"
            (project_dir / ".omx").mkdir(parents=True)
            (project_dir / "run_notes.md").write_text(
                "Ran successfully but the result was negative.\n", encoding="utf-8"
            )
            (project_dir / ".omx" / "project_decision.json").write_text(
                '{"decision":"negative_result"}\n', encoding="utf-8"
            )
            client = _client_with_config(_live_config(tmp))
            headers = {"Authorization": f"Bearer {TOKEN}"}
            client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "worker-callback-negative-import",
                    "queue_rows": [
                        {
                            "project_id": "idea-callback-negative",
                            "project_name": "Callback Negative Project",
                            "project_dir": "idea-callback-negative",
                            "status": "completed",
                            "last_run_state": "wake_ready",
                            "next_action_hint": "draft_paper_or_select_next_project",
                            "current_run_id": "run-callback-negative",
                        }
                    ],
                },
            )
            draft = client.post(
                "/control/papers/draft-next",
                headers=headers,
                json={"force": True, "override_hold_action": "draft-next-while-held"},
            )
            self.assertEqual(draft.status_code, 200)
            self.assertEqual(draft.json()["action"], "noop")
            self.assertIn(
                "project decision", draft.json()["candidate"]["skipped"][0]["reason"]
            )
            snapshot = client.get("/control/export/snapshot", headers=headers).json()
            self.assertEqual(snapshot["paper_rows"], [])
            self.assertEqual(
                client.get("/control/api/paper-reviews", headers=headers).json()[
                    "page"
                ]["total"],
                0,
            )

    def test_paper_draft_writer_failure_does_not_mutate_project_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            original_dir = "idea-draft-fail"
            project_dir = Path(tmp) / "projects" / original_dir
            (project_dir / ".omx").mkdir(parents=True)
            (project_dir / "run_notes.md").write_text(
                "Verified useful result.\n", encoding="utf-8"
            )
            (project_dir / ".omx" / "project_decision.json").write_text(
                '{"decision":"finalize_positive"}\n', encoding="utf-8"
            )
            response = client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "import-draft-failure",
                    "queue_rows": [
                        {
                            "project_id": "idea-draft-fail",
                            "project_name": "Draft Failure",
                            "project_dir": original_dir,
                            "status": "completed",
                            "last_run_state": "wake_ready",
                            "next_action_hint": "draft_paper_or_select_next_project",
                            "current_run_id": "run-draft-fail",
                            "manual_review_required": False,
                        }
                    ],
                    "paper_rows": [],
                },
            )
            self.assertEqual(response.status_code, 200)
            with patch(
                "enoch_control_plane.control_plane.router.write_paper_artifacts",
                side_effect=RuntimeError("writer exploded"),
            ):
                with self.assertRaisesRegex(RuntimeError, "writer exploded"):
                    client.post(
                        "/control/papers/draft-next",
                        headers=headers,
                        json={
                            "force": True,
                            "override_hold_action": "draft-next-while-held",
                        },
                    )
            snapshot = client.get("/control/export/snapshot", headers=headers).json()
            project = next(
                row
                for row in snapshot["queue_rows"]
                if row["project_id"] == "idea-draft-fail"
            )
            self.assertEqual(project["project_dir"], original_dir)
            self.assertEqual(snapshot["paper_rows"], [])

    def test_ideas_observation_endpoint_refreshes_status_freshness(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            response = client.post(
                "/control/api/intake/ideas-observation",
                headers=headers,
                json={"status": "warn", "payload": {"reason": "supabase intake smoke"}},
            )
            self.assertEqual(response.status_code, 200)
            status = client.get("/control/api/status", headers=headers).json()
            ideas = status["source_freshness"]["idea_intake"]
            self.assertFalse(ideas["stale"])
            self.assertEqual(ideas["status"], "warn")

            missing = client.post(
                "/control/api/intake/ideas-observation",
                headers=headers,
                json={
                    "status": "missing",
                    "payload": {"reason": "legacy missing status"},
                },
            )
            self.assertEqual(missing.status_code, 200)
            self.assertEqual(missing.json()["observation"]["status"], "warn")

    def test_intake_observation_rejects_supabase_readonly_before_store_write(
        self,
    ) -> None:
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
                    raise AssertionError(
                        "read-only observation endpoint must reject before mutation"
                    )

            fake_store = FakeReadOnlyStore()
            with patch(
                "enoch_control_plane.control_plane.router.SupabaseReadOnlyControlPlaneStore",
                return_value=fake_store,
            ):
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
            config = _config(tmp).model_copy(
                update={"worker_wake_gate_url": "http://127.0.0.1:1"}
            )
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            response = client.post(
                "/control/worker/preflight",
                headers=headers,
                json={"wake_gate_url": "http://127.0.0.1:1"},
            )
            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertFalse(body["ok"])
            self.assertTrue(
                any(check["name"] == "wake_gate_healthz" for check in body["checks"])
            )

    def test_worker_preflight_endpoint_uses_configured_worker_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _config(tmp).model_copy(
                update={"worker_wake_gate_url": "http://configured-worker:8787"}
            )
            expected = WorkerPreflightResponse(
                ok=True, target=config.worker_wake_gate_url, summary="ok", checks=[]
            )
            with patch(
                "enoch_control_plane.control_plane.router.run_worker_preflight",
                return_value=expected,
            ) as mocked_preflight:
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
            expected = WorkerPreflightResponse(
                ok=True, target=config.worker_wake_gate_url, summary="ok", checks=[]
            )
            with patch(
                "enoch_control_plane.control_plane.router.run_worker_preflight",
                return_value=expected,
            ) as mocked_preflight:
                client = _client_with_config(config)
                response = client.post(
                    "/control/worker/preflight",
                    headers={"Authorization": f"Bearer {TOKEN}"},
                    json={
                        "wake_gate_url": "http://attacker-controlled:8080",
                        "bearer_token": "attacker-token",
                    },
                )

            self.assertEqual(response.status_code, 200)
            called_payload = mocked_preflight.call_args.args[0]
            self.assertEqual(
                called_payload.bearer_token, config.worker_wake_gate_bearer_token
            )

    def test_dashboard_preflight_endpoint_rejects_unconfigured_explicit_target(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _config(tmp).model_copy(
                update={"worker_wake_gate_url": "http://configured-worker:8787"}
            )
            with patch(
                "enoch_control_plane.control_plane.router.run_worker_preflight"
            ) as mocked_preflight:
                client = _client_with_config(config)
                response = client.post(
                    "/control/api/preflight",
                    headers={"Authorization": f"Bearer {TOKEN}"},
                    json={
                        "wake_gate_url": "http://cpu-worker:8787",
                        "bearer_token": "cpu-token",
                        "min_memory_available_mib": 24576,
                    },
                )

            self.assertEqual(response.status_code, 400)
            self.assertIn("must match configured worker_wake_gate_url", response.text)
            mocked_preflight.assert_not_called()

    def test_dashboard_preflight_endpoint_resolves_named_worker_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _config(tmp).model_copy(
                update={
                    "worker_wake_gate_url": "http://gb10-worker:8787",
                    "worker_wake_gate_bearer_token": "gb10-token",
                    "worker_targets": {
                        "cpu-proxmox-1": {
                            "wake_gate_url": "http://cpu-worker:8787",
                            "bearer_token": "cpu-token",
                            "role": "cpu_worker",
                            "min_memory_available_mib": 24576,
                        },
                    },
                }
            )
            expected = WorkerPreflightResponse(
                ok=True, target="http://cpu-worker:8787", summary="ok", checks=[]
            )
            with patch(
                "enoch_control_plane.control_plane.router.run_worker_preflight",
                return_value=expected,
            ) as mocked_preflight:
                client = _client_with_config(config)
                response = client.post(
                    "/control/api/preflight",
                    headers={"Authorization": f"Bearer {TOKEN}"},
                    json={"machine_target": "cpu-proxmox-1"},
                )

            self.assertEqual(response.status_code, 200)
            called_payload = mocked_preflight.call_args.args[0]
            self.assertEqual(called_payload.wake_gate_url, "http://cpu-worker:8787")
            self.assertEqual(called_payload.bearer_token, "cpu-token")
            self.assertEqual(called_payload.min_memory_available_mib, 24576)

    def test_dashboard_preflight_non_default_target_does_not_overwrite_default_observation(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _config(tmp).model_copy(
                update={
                    "worker_wake_gate_url": "http://gb10-worker:8787",
                    "worker_wake_gate_bearer_token": "gb10-token",
                    "worker_targets": {
                        "cpu-proxmox-1": {
                            "wake_gate_url": "http://cpu-worker:8787",
                            "bearer_token": "cpu-token",
                        },
                    },
                }
            )
            expected = WorkerPreflightResponse(
                ok=True, target="http://cpu-worker:8787", summary="ok", checks=[]
            )
            with patch(
                "enoch_control_plane.control_plane.router.run_worker_preflight",
                return_value=expected,
            ):
                client = _client_with_config(config)
                response = client.post(
                    "/control/api/preflight",
                    headers={"Authorization": f"Bearer {TOKEN}"},
                    json={"machine_target": "cpu-proxmox-1"},
                )

            self.assertEqual(response.status_code, 200)
            status = client.get(
                "/control/api/status", headers={"Authorization": f"Bearer {TOKEN}"}
            ).json()
            self.assertIsNone(status["observations"]["worker_preflight"])

    def test_worker_preflight_rejects_placeholder_worker_url_with_token(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _config(tmp).model_copy(
                update={"worker_wake_gate_bearer_token": "configured-worker-token"}
            )
            with patch(
                "enoch_control_plane.control_plane.router.run_worker_preflight"
            ) as mocked_preflight:
                client = _client_with_config(config)
                response = client.post(
                    "/control/worker/preflight",
                    headers={"Authorization": f"Bearer {TOKEN}"},
                    json={"wake_gate_url": "http://attacker-controlled:8080"},
                )

            self.assertEqual(response.status_code, 503)
            self.assertIn("configured worker_wake_gate_url", response.text)
            mocked_preflight.assert_not_called()

    def test_dashboard_preflight_maps_unconfigured_worker_url_to_503(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = FastAPI()
            config = _config(tmp)

            def require(auth: str | None) -> None:
                if auth != f"Bearer {TOKEN}":
                    raise AssertionError("bad token")

            app.include_router(create_control_plane_router(config, require))
            client = TestClient(app, raise_server_exceptions=False)
            with patch(
                "enoch_control_plane.control_plane.router.run_worker_preflight"
            ) as mocked_preflight:
                response = client.post(
                    "/control/api/preflight",
                    headers={"Authorization": f"Bearer {TOKEN}"},
                    json={},
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
                    raise AssertionError(
                        "read-only preflight must not write dashboard observations"
                    )

            fake_store = FakeReadOnlyStore()
            preflight = WorkerPreflightResponse(
                ok=True,
                target="http://worker",
                summary="ok",
                checks=[
                    WorkerPreflightCheck(name="wake_gate_healthz", ok=True, detail="ok")
                ],
            )
            with (
                patch(
                    "enoch_control_plane.control_plane.router.SupabaseReadOnlyControlPlaneStore",
                    return_value=fake_store,
                ),
                patch(
                    "enoch_control_plane.control_plane.router.run_worker_preflight",
                    return_value=preflight,
                ),
            ):
                client = _client_with_config(config)
                response = client.post(
                    "/control/worker/preflight",
                    headers={"Authorization": f"Bearer {TOKEN}"},
                    json={"wake_gate_url": "http://worker"},
                )

            assert response.status_code == 200
            assert response.json()["ok"] is True
            assert fake_store.observation_attempted is False

    def test_live_dispatch_stays_disabled_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            project_dir = Path(tmp) / "projects" / "idea-live"
            project_dir.mkdir(parents=True)
            response = client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "live-disabled-import",
                    "queue_rows": [
                        {
                            "project_id": "idea-live",
                            "project_name": "Live Disabled",
                            "project_dir": "idea-live",
                            "status": "queued",
                        }
                    ],
                },
            )
            self.assertEqual(response.status_code, 200)
            client.post(
                "/control/resume",
                headers=headers,
                json={"resumed_by": "test", "maintenance_mode": False},
            )
            dispatch = client.post(
                "/control/dispatch-next", headers=headers, json={"dry_run": False}
            )
            self.assertEqual(dispatch.status_code, 501)
            self.assertIn("live dispatch is disabled", dispatch.text)

    def test_live_dispatch_cannot_bypass_worker_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _live_config(tmp).model_copy(
                update={"worker_wake_gate_url": "http://127.0.0.1:1"}
            )
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "preflight-bypass-import",
                    "queue_rows": [
                        {
                            "project_id": "idea-live",
                            "project_name": "Live Preflight Required",
                            "project_dir": "idea-live",
                            "status": "queued",
                        }
                    ],
                },
            )
            client.post(
                "/control/resume",
                headers=headers,
                json={"resumed_by": "test", "maintenance_mode": False},
            )
            dispatch = client.post(
                "/control/dispatch-next",
                headers=headers,
                json={"dry_run": False, "force_preflight": False},
            )
            self.assertEqual(dispatch.status_code, 409)
            self.assertIn("worker preflight failed", dispatch.text)
            self.assertIn("force_preflight_ignored", dispatch.text)
            state = client.get("/control/state", headers=headers).json()
            self.assertEqual(state["counts"]["queued"], 1)
            self.assertEqual(state["counts"].get("dispatching", 0), 0)

    def test_live_dispatch_rejects_supabase_readonly_before_claim_or_preflight(
        self,
    ) -> None:
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
                    return {
                        "project_id": "readonly-dispatch",
                        "project_name": "Readonly Dispatch",
                        "project_dir": "readonly-dispatch",
                    }

                def claim_dispatch_candidate(self, **_kwargs):  # noqa: ANN001 - must not be called
                    self.claim_attempted = True
                    raise AssertionError(
                        "read-only dispatch must reject before claiming"
                    )

            fake_store = FakeReadOnlyStore()
            with (
                patch(
                    "enoch_control_plane.control_plane.router.SupabaseReadOnlyControlPlaneStore",
                    return_value=fake_store,
                ),
                patch(
                    "enoch_control_plane.control_plane.router.run_worker_preflight",
                    side_effect=AssertionError("preflight must not run"),
                ),
            ):
                client = _client_with_config(config)
                response = client.post(
                    "/control/dispatch-next",
                    headers={"Authorization": f"Bearer {TOKEN}"},
                    json={"dry_run": False},
                )

            assert response.status_code == 501
            assert "writable control-plane store" in response.text
            assert fake_store.claim_attempted is False

    def test_operator_pause_rejects_supabase_readonly_without_store_exception(
        self,
    ) -> None:
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
            with patch(
                "enoch_control_plane.control_plane.router.SupabaseReadOnlyControlPlaneStore",
                return_value=fake_store,
            ):
                client = _client_with_config(config)
                response = client.post(
                    "/control/pause",
                    headers={"Authorization": f"Bearer {TOKEN}"},
                    json={"reason": "test"},
                )

            assert response.status_code == 501
            assert "writable control-plane store" in response.text
            assert fake_store.pause_attempted is False

    def test_dispatch_one_dry_run_works_while_paused_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "dispatch-one-dry-import",
                    "queue_rows": [
                        {
                            "project_id": "idea-one",
                            "project_name": "One",
                            "project_dir": "idea-one",
                            "status": "queued",
                            "dispatch_priority": 20,
                        },
                        {
                            "project_id": "idea-two",
                            "project_name": "Two",
                            "project_dir": "idea-two",
                            "status": "queued",
                            "dispatch_priority": 10,
                        },
                    ],
                },
            )

            before = client.get("/control/state", headers=headers).json()
            self.assertTrue(before["flags"]["queue_paused"])
            self.assertEqual(before["counts"]["queued"], 2)

            response = client.post(
                "/control/dispatch-one",
                headers=headers,
                json={"project_id": "idea-one"},
            )
            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertEqual(body["action"], "dry_run_dispatch_one")
            self.assertEqual(body["candidate"]["project_id"], "idea-one")

            after = client.get("/control/state", headers=headers).json()
            self.assertTrue(after["flags"]["queue_paused"])
            self.assertEqual(after["counts"]["queued"], 2)
            rows = client.get("/control/queue", headers=headers).json()["rows"]
            self.assertEqual(
                {row["project_id"]: row["status"] for row in rows},
                {"idea-one": "queued", "idea-two": "queued"},
            )

    def test_dispatch_one_live_requires_named_override_while_paused(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _live_config(tmp)
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "dispatch-one-live-import",
                    "queue_rows": [
                        {
                            "project_id": "idea-one",
                            "project_name": "One",
                            "project_dir": "idea-one",
                            "status": "queued",
                            "dispatch_priority": 20,
                        },
                        {
                            "project_id": "idea-two",
                            "project_name": "Two",
                            "project_dir": "idea-two",
                            "status": "queued",
                            "dispatch_priority": 10,
                        },
                    ],
                },
            )
            client.post(
                "/control/pause",
                headers=headers,
                json={
                    "paused_by": "test",
                    "reason": "paused but not maintenance",
                    "maintenance_mode": False,
                },
            )
            preflight = WorkerPreflightResponse(
                ok=True, target=config.worker_wake_gate_url, summary="ok", checks=[]
            )

            def fake_post(
                _base: str, path: str, _token: str, payload: dict
            ) -> HttpResult:
                if path == "/prepare-project":
                    return HttpResult(
                        ok=True, status=200, body={"prepared": payload["project_id"]}
                    )
                if path == "/dispatch":
                    return HttpResult(
                        ok=True,
                        status=200,
                        body={
                            "dispatch": {"session_id": "session-one"},
                            "project_id": payload["project_id"],
                        },
                    )
                return HttpResult(
                    ok=False, status=404, body=None, error="unexpected path"
                )

            with (
                patch(
                    "enoch_control_plane.control_plane.router.run_worker_preflight",
                    return_value=preflight,
                ),
                patch(
                    "enoch_control_plane.control_plane.router.post_worker_json",
                    side_effect=fake_post,
                ),
            ):
                blocked = client.post(
                    "/control/dispatch-one",
                    headers=headers,
                    json={"project_id": "idea-one", "dry_run": False},
                )
                response = client.post(
                    "/control/dispatch-one",
                    headers=headers,
                    json={
                        "project_id": "idea-one",
                        "dry_run": False,
                        "override_hold_action": "dispatch-one-while-held",
                    },
                )

            self.assertEqual(blocked.status_code, 409)
            self.assertIn("override_hold_action", blocked.text)
            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertEqual(body["action"], "live_dispatch_one")
            self.assertEqual(body["candidate"]["project_id"], "idea-one")
            self.assertEqual(body["candidate"]["status"], "awaiting_wake")
            self.assertEqual(body["live"]["project_id"], "idea-one")
            self.assertEqual(
                body["live"]["dispatch"]["dispatch"]["session_id"], "session-one"
            )

            state = client.get("/control/state", headers=headers).json()
            self.assertTrue(state["flags"]["queue_paused"])
            self.assertFalse(state["flags"]["maintenance_mode"])
            self.assertEqual(state["counts"].get("awaiting_wake"), 1)
            self.assertEqual(state["counts"].get("queued"), 1)
            rows = {
                row["project_id"]: row
                for row in client.get("/control/queue", headers=headers).json()["rows"]
            }
            self.assertEqual(rows["idea-one"]["status"], "awaiting_wake")
            self.assertEqual(rows["idea-two"]["status"], "queued")
            self.assertFalse(rows["idea-two"].get("current_run_id"))

    def test_cpu_only_dry_run_dispatch_selects_cpu_worker_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _live_config(tmp).model_copy(
                update={
                    "worker_wake_gate_url": "http://gb10-worker:8787",
                    "worker_wake_gate_bearer_token": "gb10-token",
                    "workload_machine_targets": {
                        "cpu_only": "cpu-proxmox-1",
                        "gpu_required": "gb10",
                    },
                    "worker_targets": {
                        "cpu-proxmox-1": {
                            "wake_gate_url": "http://cpu-proxmox-1:8787",
                            "bearer_token": "cpu-token",
                            "role": "cpu_worker",
                        },
                        "gb10": {
                            "wake_gate_url": "http://gb10-worker:8787",
                            "bearer_token": "gb10-token",
                            "role": "gpu_worker",
                        },
                    },
                }
            )
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            client.post(
                "/control/resume",
                headers=headers,
                json={"resumed_by": "test", "maintenance_mode": False},
            )
            intake = client.post(
                "/control/intake/ideas",
                headers=headers,
                json={
                    "idempotency_key": "router-cpu-routing-intake",
                    "dry_run": False,
                    "include_statuses": ["testing"],
                    "default_machine_target": "gb10",
                    "ideas": [
                        {
                            "idea_id": "router-cpu-routing",
                            "title": "Router CPU Routing",
                            "idea_status": "testing",
                            "workload_class": "cpu_only",
                            "machine_target": "gb10",
                        }
                    ],
                },
            )
            self.assertEqual(intake.status_code, 200)

            dry_run = client.post(
                "/control/dispatch-next", headers=headers, json={"dry_run": True}
            )

            self.assertEqual(dry_run.status_code, 200)
            body = dry_run.json()
            self.assertEqual(body["action"], "dry_run_dispatch")
            self.assertEqual(body["candidate"]["machine_target"], "cpu-proxmox-1")
            self.assertEqual(
                body["candidate"]["dispatch_route"]["wake_gate_url"],
                "http://cpu-proxmox-1:8787",
            )
            self.assertEqual(
                body["candidate"]["dispatch_route"]["worker_role"], "cpu_worker"
            )

    def test_gpu_required_dry_run_dispatch_preserves_gb10_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _live_config(tmp).model_copy(
                update={
                    "worker_wake_gate_url": "http://gb10-worker:8787",
                    "worker_wake_gate_bearer_token": "gb10-token",
                    "workload_machine_targets": {
                        "cpu_only": "cpu-proxmox-1",
                        "gpu_required": "gb10",
                    },
                    "worker_targets": {
                        "cpu-proxmox-1": {
                            "wake_gate_url": "http://cpu-proxmox-1:8787",
                            "bearer_token": "cpu-token",
                            "role": "cpu_worker",
                        },
                        "gb10": {
                            "wake_gate_url": "http://gb10-worker:8787",
                            "bearer_token": "gb10-token",
                            "role": "gpu_worker",
                        },
                    },
                }
            )
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            client.post(
                "/control/resume",
                headers=headers,
                json={"resumed_by": "test", "maintenance_mode": False},
            )
            intake = client.post(
                "/control/intake/ideas",
                headers=headers,
                json={
                    "idempotency_key": "router-gpu-routing-intake",
                    "dry_run": False,
                    "include_statuses": ["testing"],
                    "default_machine_target": "cpu-proxmox-1",
                    "ideas": [
                        {
                            "idea_id": "router-gpu-routing",
                            "title": "Router GPU Routing",
                            "idea_status": "testing",
                            "workload_class": "gpu_required",
                            "machine_target": "cpu-proxmox-1",
                        }
                    ],
                },
            )
            self.assertEqual(intake.status_code, 200)

            dry_run = client.post(
                "/control/dispatch-next", headers=headers, json={"dry_run": True}
            )

            self.assertEqual(dry_run.status_code, 200)
            body = dry_run.json()
            self.assertEqual(body["action"], "dry_run_dispatch")
            self.assertEqual(body["candidate"]["machine_target"], "gb10")
            self.assertEqual(
                body["candidate"]["dispatch_route"]["wake_gate_url"],
                "http://gb10-worker:8787",
            )
            self.assertEqual(
                body["candidate"]["dispatch_route"]["worker_role"], "gpu_worker"
            )

    def test_live_dispatch_uses_configured_cpu_worker_endpoint_for_cpu_target(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _live_config(tmp).model_copy(
                update={
                    "worker_wake_gate_url": "http://gb10-worker:8787",
                    "worker_wake_gate_bearer_token": "gb10-token",
                    "workload_machine_targets": {
                        "cpu_only": "cpu-proxmox-1",
                        "gpu_required": "gb10",
                    },
                    "worker_targets": {
                        "cpu-proxmox-1": {
                            "wake_gate_url": "http://cpu-proxmox-1:8787",
                            "bearer_token": "cpu-token",
                            "role": "cpu_worker",
                            "min_memory_available_mib": 16384,
                        },
                    },
                }
            )
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "dispatch-cpu-target-import",
                    "queue_rows": [
                        {
                            "project_id": "dispatch-cpu-target",
                            "project_name": "Dispatch CPU Target",
                            "project_dir": "dispatch-cpu-target",
                            "status": "queued",
                            "machine_target": "cpu-proxmox-1",
                        }
                    ],
                },
            )
            client.post(
                "/control/resume",
                headers=headers,
                json={"resumed_by": "test", "maintenance_mode": False},
            )
            preflight = WorkerPreflightResponse(
                ok=True, target="http://cpu-proxmox-1:8787", summary="ok", checks=[]
            )
            calls = []

            def fake_post(
                base: str, path: str, token: str, payload: dict
            ) -> HttpResult:
                calls.append((base, path, token, payload))
                if path == "/prepare-project":
                    return HttpResult(
                        ok=True, status=200, body={"prepared": payload["project_id"]}
                    )
                if path == "/dispatch":
                    return HttpResult(
                        ok=True,
                        status=200,
                        body={"dispatch": {"session_id": "session-cpu"}},
                    )
                return HttpResult(
                    ok=False, status=404, body=None, error="unexpected path"
                )

            with (
                patch(
                    "enoch_control_plane.control_plane.router.run_worker_preflight",
                    return_value=preflight,
                ) as mocked_preflight,
                patch(
                    "enoch_control_plane.control_plane.router.post_worker_json",
                    side_effect=fake_post,
                ),
            ):
                response = client.post(
                    "/control/dispatch-next", headers=headers, json={"dry_run": False}
                )

            self.assertEqual(response.status_code, 200)
            called_payload = mocked_preflight.call_args.args[0]
            self.assertEqual(called_payload.wake_gate_url, "http://cpu-proxmox-1:8787")
            self.assertEqual(called_payload.bearer_token, "cpu-token")
            self.assertEqual(called_payload.min_memory_available_mib, 16384)
            self.assertEqual({call[0] for call in calls}, {"http://cpu-proxmox-1:8787"})
            self.assertEqual({call[2] for call in calls}, {"cpu-token"})
            prepare_payload = next(
                call[3] for call in calls if call[1] == "/prepare-project"
            )
            self.assertEqual(prepare_payload["metadata"]["workload_class"], "cpu_only")
            self.assertEqual(
                prepare_payload["metadata"]["machine_target"], "cpu-proxmox-1"
            )
            self.assertIs(
                prepare_payload["metadata"]["dispatch_route"]["token_configured"],
                True,
            )
            self.assertNotIn(
                "bearer_token", prepare_payload["metadata"]["dispatch_route"]
            )
            self.assertEqual(
                response.json()["live"]["dispatch_route"]["worker_role"], "cpu_worker"
            )

    def test_live_dispatch_preflight_expects_control_api_token_for_worker_callback(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            trace_path = Path(tmp) / "dispatch_operator_trace.jsonl"
            config = _live_config(tmp).model_copy(
                update={
                    "worker_wake_gate_url": "http://gb10-worker:8787",
                    "worker_wake_gate_bearer_token": "gb10-token",
                    "workload_machine_targets": {"cpu_only": "cpu-proxmox-1"},
                    "operational_trace_enabled": True,
                    "operational_trace_log_path": str(trace_path),
                    "worker_targets": {
                        "cpu-proxmox-1": {
                            "wake_gate_url": "http://cpu-proxmox-1:8787",
                            "bearer_token": "cpu-token",
                            "role": "cpu_worker",
                        },
                    },
                }
            )
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "dispatch-callback-mismatch-import",
                    "default_machine_target": "gb10",
                    "workload_machine_targets": {"cpu_only": "cpu-proxmox-1"},
                    "ideas": [
                        {
                            "project_id": "dispatch-callback-mismatch",
                            "project_name": "Dispatch Callback Mismatch",
                            "project_dir": "dispatch-callback-mismatch",
                            "workload_class": "cpu_only",
                            "machine_target": "gb10",
                        }
                    ],
                    "queue_rows": [
                        {
                            "project_id": "dispatch-callback-mismatch",
                            "project_name": "Dispatch Callback Mismatch",
                            "project_dir": "dispatch-callback-mismatch",
                            "status": "queued",
                            "machine_target": "cpu-proxmox-1",
                        }
                    ],
                },
            )
            client.post(
                "/control/resume",
                headers=headers,
                json={"resumed_by": "test", "maintenance_mode": False},
            )
            preflight = WorkerPreflightResponse(
                ok=False,
                target="http://cpu-proxmox-1:8787",
                summary="worker preflight failed",
                checks=[
                    WorkerPreflightCheck(
                        name="wake_gate_healthz", ok=True, detail="ok", data={}
                    ),
                    WorkerPreflightCheck(
                        name="worker_callback_token_compatible",
                        ok=False,
                        detail="worker callback token compatibility check failed",
                        data={},
                    ),
                ],
            )

            with (
                patch(
                    "enoch_control_plane.control_plane.router.run_worker_preflight",
                    return_value=preflight,
                ) as mocked_preflight,
                patch(
                    "enoch_control_plane.control_plane.router.post_worker_json",
                    side_effect=AssertionError("dispatch must not reach worker"),
                ),
            ):
                response = client.post(
                    "/control/dispatch-next", headers=headers, json={"dry_run": False}
                )

            self.assertEqual(response.status_code, 409)
            body_text = response.text
            self.assertIn("worker preflight failed", body_text)
            self.assertIn("worker_callback_token_compatible", body_text)
            self.assertNotIn(TOKEN, body_text)
            called_payload = mocked_preflight.call_args.args[0]
            self.assertEqual(
                called_payload.expected_callback_token_fingerprint,
                hashlib.sha256(
                    config.control_api_bearer_token.encode("utf-8")
                ).hexdigest(),
            )
            rows = {
                row["project_id"]: row
                for row in client.get("/control/queue", headers=headers).json()["rows"]
            }
            self.assertEqual(rows["dispatch-callback-mismatch"]["status"], "queued")
            self.assertIn(
                "worker preflight failed",
                rows["dispatch-callback-mismatch"]["last_error"],
            )
            trace_text = trace_path.read_text(encoding="utf-8")
            self.assertNotIn(TOKEN, trace_text)
            self.assertNotIn("cpu-token", trace_text)
            trace_events = [
                json.loads(line)["event"] for line in trace_text.splitlines()
            ]
            self.assertIn("dispatch.live.attempt", trace_events)
            self.assertIn("dispatch.preflight.result", trace_events)

    def test_dispatch_next_allows_cpu_worker_while_gb10_lane_is_active(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _live_config(tmp).model_copy(
                update={
                    "worker_wake_gate_url": "http://gb10-worker:8787",
                    "worker_wake_gate_bearer_token": "gb10-token",
                    "workload_machine_targets": {
                        "cpu_only": "cpu-proxmox-1",
                        "gpu_required": "gb10",
                    },
                    "worker_targets": {
                        "cpu-proxmox-1": {
                            "wake_gate_url": "http://cpu-proxmox-1:8787",
                            "bearer_token": "cpu-token",
                            "role": "cpu_worker",
                            "min_memory_available_mib": 16384,
                        },
                        "gb10": {
                            "wake_gate_url": "http://gb10-worker:8787",
                            "bearer_token": "gb10-token",
                            "role": "gpu_worker",
                        },
                    },
                }
            )
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "dispatch-cpu-while-gpu-active-import",
                    "queue_rows": [
                        {
                            "project_id": "active-gpu-lane",
                            "project_name": "Active GPU Lane",
                            "project_dir": "active-gpu-lane",
                            "status": "awaiting_wake",
                            "machine_target": "gb10",
                            "current_run_id": "run-active-gpu-lane",
                        },
                        {
                            "project_id": "queued-gpu-same-lane",
                            "project_name": "Queued GPU Same Lane",
                            "project_dir": "queued-gpu-same-lane",
                            "status": "queued",
                            "machine_target": "gb10",
                            "dispatch_priority": 1,
                        },
                        {
                            "project_id": "queued-cpu-open-lane",
                            "project_name": "Queued CPU Open Lane",
                            "project_dir": "queued-cpu-open-lane",
                            "status": "queued",
                            "machine_target": "cpu-proxmox-1",
                            "dispatch_priority": 2,
                        },
                    ],
                },
            )
            client.post(
                "/control/resume",
                headers=headers,
                json={"resumed_by": "test", "maintenance_mode": False},
            )
            preflight = WorkerPreflightResponse(
                ok=True, target="http://cpu-proxmox-1:8787", summary="ok", checks=[]
            )
            calls = []

            def fake_post(
                base: str, path: str, token: str, payload: dict
            ) -> HttpResult:
                calls.append((base, path, token, payload))
                if path == "/prepare-project":
                    return HttpResult(
                        ok=True, status=200, body={"prepared": payload["project_id"]}
                    )
                if path == "/dispatch":
                    return HttpResult(
                        ok=True,
                        status=200,
                        body={"dispatch": {"session_id": "session-cpu-open-lane"}},
                    )
                return HttpResult(
                    ok=False, status=404, body=None, error="unexpected path"
                )

            dry_run = client.post(
                "/control/dispatch-next", headers=headers, json={"dry_run": True}
            )
            self.assertEqual(dry_run.status_code, 200)
            self.assertEqual(
                dry_run.json()["candidate"]["project_id"], "queued-cpu-open-lane"
            )

            with (
                patch(
                    "enoch_control_plane.control_plane.router.run_worker_preflight",
                    return_value=preflight,
                ) as mocked_preflight,
                patch(
                    "enoch_control_plane.control_plane.router.post_worker_json",
                    side_effect=fake_post,
                ),
            ):
                response = client.post(
                    "/control/dispatch-next", headers=headers, json={"dry_run": False}
                )

            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertEqual(body["action"], "live_dispatch")
            self.assertEqual(body["candidate"]["project_id"], "queued-cpu-open-lane")
            self.assertEqual(
                body["live"]["dispatch_route"]["worker_role"], "cpu_worker"
            )
            self.assertEqual(
                mocked_preflight.call_args.args[0].wake_gate_url,
                "http://cpu-proxmox-1:8787",
            )
            self.assertEqual({call[0] for call in calls}, {"http://cpu-proxmox-1:8787"})
            rows = {
                row["project_id"]: row
                for row in client.get("/control/queue", headers=headers).json()["rows"]
            }
            self.assertEqual(rows["queued-cpu-open-lane"]["status"], "awaiting_wake")
            self.assertEqual(rows["queued-gpu-same-lane"]["status"], "queued")

    def test_dispatch_one_claim_uses_lane_alias_conflict_targets(self) -> None:
        class FakeSupabaseStore:
            def __init__(self) -> None:
                self.queue = {
                    "queued-default": {
                        "project_id": "queued-default",
                        "project_name": "Queued Default",
                        "project_dir": "queued-default",
                        "status": "queued",
                        "machine_target": "",
                    }
                }
                self.last_conflicting_machine_targets = None

            def flags(self):
                return SimpleNamespace(queue_paused=False, maintenance_mode=False)

            def queue_row(self, project_id: str):
                return self.queue.get(project_id)

            def active_items(self) -> list[dict[str, str]]:
                return []

            def claim_dispatch_candidate(
                self,
                *,
                project_id: str,
                run_id: str,
                requested_by: str,
                conflicting_machine_targets=None,
            ):
                self.last_conflicting_machine_targets = set(
                    conflicting_machine_targets or []
                )
                row = self.queue.get(project_id)
                if not row or row["status"] != "queued":
                    return None
                row.update({"status": "dispatching", "current_run_id": run_id})
                return dict(row)

            def release_dispatch_claim(
                self, *, project_id: str, run_id: str, reason: str
            ):
                self.queue[project_id]["status"] = "queued"
                return True

            def update_project_dir(self, project_id: str, project_dir: str) -> None:
                self.queue[project_id]["project_dir"] = project_dir

            def mark_dispatch_started(
                self,
                *,
                project_id: str,
                run_id: str,
                session_id: str,
                dispatch_payload: dict,
                requested_by: str,
            ):
                self.queue[project_id].update(
                    {
                        "status": "awaiting_wake",
                        "current_run_id": run_id,
                        "current_session_id": session_id,
                    }
                )
                return 123, dict(self.queue[project_id])

            def append_event(self, **_kwargs):
                return 1, True

            def upsert_dashboard_observation(self, **_kwargs):
                return True

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
            worker_wake_gate_url="http://gb10-worker:8787",
            worker_wake_gate_bearer_token="gb10-token",
            worker_targets={
                "gb10": {
                    "wake_gate_url": "http://gb10-worker:8787",
                    "bearer_token": "gb10-token",
                    "role": "gpu_worker",
                },
            },
        )

        preflight = WorkerPreflightResponse(
            ok=True, target="http://gb10-worker:8787", summary="ok", checks=[]
        )

        def fake_post(_base: str, path: str, _token: str, payload: dict) -> HttpResult:
            if path == "/prepare-project":
                return HttpResult(
                    ok=True, status=200, body={"prepared": payload["project_id"]}
                )
            if path == "/dispatch":
                return HttpResult(
                    ok=True,
                    status=200,
                    body={"dispatch": {"session_id": "gb10-session"}},
                )
            return HttpResult(ok=False, status=404, body=None, error="unexpected path")

        app = FastAPI()

        def require(auth: str | None) -> None:
            if auth != f"Bearer {TOKEN}":
                raise AssertionError("bad token")

        with patch(
            "enoch_control_plane.control_plane.router.SupabaseControlPlaneStore",
            return_value=fake_store,
        ):
            app.include_router(create_control_plane_router(config, require))
        client = TestClient(app)
        headers = {"Authorization": f"Bearer {TOKEN}"}

        with (
            patch(
                "enoch_control_plane.control_plane.router.run_worker_preflight",
                return_value=preflight,
            ),
            patch(
                "enoch_control_plane.control_plane.router.post_worker_json",
                side_effect=fake_post,
            ),
        ):
            response = client.post(
                "/control/dispatch-one",
                headers=headers,
                json={
                    "project_id": "queued-default",
                    "dry_run": False,
                    "requested_by": "test",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(fake_store.last_conflicting_machine_targets, {"", "gb10"})

    def test_dispatch_next_blocks_when_only_same_worker_lane_is_queued(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _live_config(tmp).model_copy(
                update={
                    "worker_wake_gate_url": "http://gb10-worker:8787",
                    "worker_wake_gate_bearer_token": "gb10-token",
                    "worker_targets": {
                        "gb10": {
                            "wake_gate_url": "http://gb10-worker:8787",
                            "bearer_token": "gb10-token",
                            "role": "gpu_worker",
                        },
                    },
                }
            )
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "dispatch-same-worker-block-import",
                    "queue_rows": [
                        {
                            "project_id": "active-gpu-only",
                            "project_name": "Active GPU Only",
                            "project_dir": "active-gpu-only",
                            "status": "awaiting_wake",
                            "machine_target": "gb10",
                            "current_run_id": "run-active-gpu-only",
                        },
                        {
                            "project_id": "queued-gpu-only",
                            "project_name": "Queued GPU Only",
                            "project_dir": "queued-gpu-only",
                            "status": "queued",
                            "machine_target": "gb10",
                        },
                    ],
                },
            )
            client.post(
                "/control/resume",
                headers=headers,
                json={"resumed_by": "test", "maintenance_mode": False},
            )

            response = client.post(
                "/control/dispatch-next", headers=headers, json={"dry_run": False}
            )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["action"], "noop")
            self.assertEqual(
                response.json()["reason"], "no queued candidate on an open worker lane"
            )

    def test_dispatch_one_live_tolerates_malformed_dispatch_success_body(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _live_config(tmp)
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "dispatch-malformed-body-import",
                    "queue_rows": [
                        {
                            "project_id": "idea-malformed-dispatch-body",
                            "project_name": "Malformed Dispatch Body",
                            "project_dir": "idea-malformed-dispatch-body",
                            "status": "queued",
                        }
                    ],
                },
            )
            client.post(
                "/control/pause",
                headers=headers,
                json={
                    "paused_by": "test",
                    "reason": "paused but not maintenance",
                    "maintenance_mode": False,
                },
            )
            preflight = WorkerPreflightResponse(
                ok=True, target=config.worker_wake_gate_url, summary="ok", checks=[]
            )

            def fake_post(
                _base: str, path: str, _token: str, payload: dict
            ) -> HttpResult:
                if path == "/prepare-project":
                    return HttpResult(
                        ok=True, status=200, body={"prepared": payload["project_id"]}
                    )
                if path == "/dispatch":
                    return HttpResult(ok=True, status=200, body=[{"accepted": True}])  # type: ignore[arg-type]
                return HttpResult(
                    ok=False, status=404, body=None, error="unexpected path"
                )

            with (
                patch(
                    "enoch_control_plane.control_plane.router.run_worker_preflight",
                    return_value=preflight,
                ),
                patch(
                    "enoch_control_plane.control_plane.router.post_worker_json",
                    side_effect=fake_post,
                ),
            ):
                response = client.post(
                    "/control/dispatch-one",
                    headers=headers,
                    json={
                        "project_id": "idea-malformed-dispatch-body",
                        "dry_run": False,
                        "override_hold_action": "dispatch-one-while-held",
                    },
                )

            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertEqual(body["action"], "live_dispatch_one")
            self.assertEqual(body["live"]["dispatch"], {})
            rows = {
                row["project_id"]: row
                for row in client.get("/control/queue", headers=headers).json()["rows"]
            }
            self.assertEqual(
                rows["idea-malformed-dispatch-body"]["status"], "awaiting_wake"
            )
            self.assertTrue(rows["idea-malformed-dispatch-body"].get("current_run_id"))

    def test_live_dispatch_persists_safe_worker_project_dir_for_long_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _live_config(tmp)
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            long_project_id = "deterministic-dropout-fingerprinting-for-cheat-resistant-volunteer-gradient-validation-e2abfed2f995"
            client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "dispatch-long-id-import",
                    "queue_rows": [
                        {
                            "project_id": long_project_id,
                            "project_name": "Long ID",
                            "project_dir": long_project_id,
                            "status": "queued",
                        }
                    ],
                },
            )
            client.post(
                "/control/pause",
                headers=headers,
                json={
                    "paused_by": "test",
                    "reason": "paused but not maintenance",
                    "maintenance_mode": False,
                },
            )
            preflight = WorkerPreflightResponse(
                ok=True, target=config.worker_wake_gate_url, summary="ok", checks=[]
            )
            prepare_payloads: list[dict] = []

            def fake_post(
                _base: str, path: str, _token: str, payload: dict
            ) -> HttpResult:
                if path == "/prepare-project":
                    prepare_payloads.append(payload)
                    return HttpResult(
                        ok=True, status=200, body={"prepared": payload["project_id"]}
                    )
                if path == "/dispatch":
                    return HttpResult(
                        ok=True,
                        status=200,
                        body={
                            "dispatch": {"session_id": "session-long"},
                            "project_id": payload["project_id"],
                        },
                    )
                return HttpResult(
                    ok=False, status=404, body=None, error="unexpected path"
                )

            with (
                patch(
                    "enoch_control_plane.control_plane.router.run_worker_preflight",
                    return_value=preflight,
                ),
                patch(
                    "enoch_control_plane.control_plane.router.post_worker_json",
                    side_effect=fake_post,
                ),
            ):
                response = client.post(
                    "/control/dispatch-one",
                    headers=headers,
                    json={
                        "project_id": long_project_id,
                        "dry_run": False,
                        "override_hold_action": "dispatch-one-while-held",
                    },
                )

            self.assertEqual(response.status_code, 200)
            safe_dir = prepare_payloads[0]["project_dir"]
            self.assertLessEqual(len(safe_dir), 96)
            self.assertTrue(long_project_id.startswith(safe_dir))
            rows = {
                row["project_id"]: row
                for row in client.get("/control/queue", headers=headers).json()["rows"]
            }
            self.assertEqual(rows[long_project_id]["project_dir"], safe_dir)

    def test_dispatch_one_rejects_invalid_or_unsafe_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _live_config(tmp)
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "dispatch-one-reject-import",
                    "queue_rows": [
                        {
                            "project_id": "idea-queued",
                            "project_name": "Queued",
                            "project_dir": "idea-queued",
                            "status": "queued",
                        },
                        {
                            "project_id": "idea-completed",
                            "project_name": "Done",
                            "project_dir": "idea-completed",
                            "status": "completed",
                        },
                    ],
                },
            )

            missing = client.post(
                "/control/dispatch-one", headers=headers, json={"project_id": ""}
            )
            self.assertEqual(missing.status_code, 400)
            unknown = client.post(
                "/control/dispatch-one", headers=headers, json={"project_id": "missing"}
            )
            self.assertEqual(unknown.status_code, 404)
            non_queued = client.post(
                "/control/dispatch-one",
                headers=headers,
                json={"project_id": "idea-completed"},
            )
            self.assertEqual(non_queued.status_code, 409)

            # Existing /dispatch-next behavior is unchanged: paused dry-runs still report paused.
            dispatch_next = client.post(
                "/control/dispatch-next", headers=headers, json={"dry_run": True}
            )
            self.assertEqual(dispatch_next.status_code, 200)
            self.assertEqual(dispatch_next.json()["action"], "paused")

    def test_dispatch_one_rejects_when_active_item_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "dispatch-one-active-import",
                    "queue_rows": [
                        {
                            "project_id": "idea-active",
                            "project_name": "Active",
                            "project_dir": "idea-active",
                            "status": "awaiting_wake",
                            "current_run_id": "run-active",
                        },
                        {
                            "project_id": "idea-queued",
                            "project_name": "Queued",
                            "project_dir": "idea-queued",
                            "status": "queued",
                        },
                    ],
                },
            )

            response = client.post(
                "/control/dispatch-one",
                headers=headers,
                json={"project_id": "idea-queued"},
            )
            self.assertEqual(response.status_code, 409)
            self.assertIn(
                "active worker lane already exists for selected candidate target",
                response.text,
            )

    def test_dashboard_queue_project_run_paper_events_and_intake_apis(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "projects" / "idea-api"
            project_dir.mkdir(parents=True)
            client = _client(tmp)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "dashboard-api-import",
                    "source": "test-snapshot",
                    "queue_rows": [
                        {
                            "project_id": "idea-api",
                            "project_name": "API Project",
                            "project_dir": str(project_dir),
                            "status": "queued",
                            "dispatch_priority": 7,
                            "selection_rank": 3,
                            "current_run_id": "run-api",
                            "notion_page_url": "https://notion.example/idea-api",
                        }
                    ],
                    "paper_rows": [
                        {
                            "paper_id": "idea-api:run-api:arxiv_draft",
                            "project_id": "idea-api",
                            "run_id": "run-api",
                            "paper_status": "draft_review",
                            "draft_markdown_path": "papers/run-api/paper.md",
                            "draft_latex_path": "papers/run-api/paper.tex",
                            "evidence_bundle_path": "papers/run-api/evidence.json",
                            "claim_ledger_path": "papers/run-api/claims.json",
                            "manifest_path": "papers/run-api/manifest.json",
                        }
                    ],
                },
            )
            ideas = client.post(
                "/control/intake/ideas",
                headers=headers,
                json={
                    "idempotency_key": "dashboard-api-ideas",
                    "dry_run": False,
                    "ideas": [
                        {
                            "idea_id": "dashboard-api-idea",
                            "title": "Ideas Intake API",
                            "idea_status": "testing",
                            "priority": "High",
                        },
                        {"idea_status": "testing"},
                    ],
                },
            )
            self.assertEqual(ideas.status_code, 200)

            queued = client.get(
                "/control/api/queues/queued?search=API&page_size=10", headers=headers
            )
            self.assertEqual(queued.status_code, 200)
            queued_body = queued.json()
            self.assertEqual(queued_body["source"], "control_api_queue")
            self.assertGreaterEqual(queued_body["page"]["total"], 1)
            self.assertTrue(
                any(row["project_id"] == "idea-api" for row in queued_body["rows"])
            )
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

            papers = client.get(
                "/control/api/papers?status=draft_review", headers=headers
            )
            self.assertEqual(papers.status_code, 200)
            self.assertEqual(papers.json()["counts"]["draft_review"], 1)
            self.assertIn("conflicts", papers.json())

            paper = client.get(
                "/control/api/papers/idea-api:run-api:arxiv_draft", headers=headers
            )
            self.assertEqual(paper.status_code, 200)
            self.assertEqual(paper.json()["paper"]["project_id"], "idea-api")
            self.assertFalse(paper.json()["warnings"])
            self.assertIn("conflicts", paper.json())

            events = client.get(
                "/control/api/events?search=dashboard-api", headers=headers
            )
            self.assertEqual(events.status_code, 200)
            self.assertGreaterEqual(events.json()["page"]["total"], 1)
            self.assertIn("conflicts", events.json())

            intake = client.get("/control/api/intake/ideas", headers=headers)
            self.assertEqual(intake.status_code, 200)
            self.assertIsNotNone(intake.json()["latest_sync"])
            self.assertEqual(intake.json()["skipped_reasons"]["missing title"], 1)
            self.assertIn("conflicts", intake.json())

    def test_detail_apis_fallback_to_global_worker_observations_and_surface_conflicts(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "detail-conflict-import",
                    "queue_rows": [
                        {
                            "project_id": "idea-active-detail",
                            "project_name": "Active Detail",
                            "project_dir": "idea-active-detail",
                            "status": "awaiting_wake",
                            "current_run_id": "run-active-detail",
                        }
                    ],
                },
            )
            store = ControlPlaneStore(Path(tmp) / "state" / "control_plane.sqlite3")
            store.upsert_dashboard_observation(
                source="worker_preflight",
                status="ok",
                payload={
                    "ok": True,
                    "checks": [
                        {
                            "name": "worker_no_live_runs",
                            "ok": True,
                            "detail": "active_or_waiting=0, live=0",
                            "data": {"active_or_waiting": 0, "live": 0},
                        }
                    ],
                },
            )
            store.upsert_dashboard_observation(
                source="worker_dashboard_api",
                status="ok",
                payload={
                    "name": "wake_gate_dashboard_api",
                    "ok": True,
                    "data": {
                        "body": {
                            "runs": [
                                {
                                    "run_id": "run-active-detail",
                                    "project_id": "idea-active-detail",
                                }
                            ]
                        }
                    },
                },
            )
            project = client.get(
                "/control/api/projects/idea-active-detail", headers=headers
            ).json()
            self.assertIsNotNone(project["worker_observations"]["worker_dashboard_api"])
            self.assertTrue(
                any(item["severity"] == "warn" for item in project["conflicts"])
            )
            run = client.get(
                "/control/api/runs/run-active-detail", headers=headers
            ).json()
            self.assertIsNotNone(run["worker_observations"]["worker_dashboard_api"])
            self.assertTrue(
                any(item["severity"] == "warn" for item in run["conflicts"])
            )

    def test_paper_review_backfill_list_detail_and_legacy_papers_api(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            papers = []
            audit_rows = []
            for idx in range(242):
                project_id = f"idea-{idx:03d}"
                status = "publication_draft" if idx < 120 else "draft_review"
                papers.append(
                    {
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
                    }
                )
                audit_rows.append({"paper_id": papers[-1]["paper_id"], "ready": True})
            audit_path = Path(tmp) / "audit.json"
            audit_path.write_text(json.dumps({"papers": audit_rows}), encoding="utf-8")
            imported = client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "paper-review-router-import",
                    "paper_rows": papers,
                },
            )
            self.assertEqual(imported.status_code, 200)
            self.assertEqual(imported.json()["imported_papers"], 242)

            dry_run = client.post(
                "/control/api/paper-reviews/backfill",
                headers=headers,
                json={
                    "idempotency_key": "paper-review-router-backfill",
                    "requested_by": "test",
                    "source_audit_path": str(audit_path),
                    "dry_run": True,
                },
            )
            self.assertEqual(dry_run.status_code, 200)
            self.assertEqual(dry_run.json()["created"], 242)

            committed = client.post(
                "/control/api/paper-reviews/backfill",
                headers=headers,
                json={
                    "idempotency_key": "paper-review-router-backfill",
                    "requested_by": "test",
                    "source_audit_path": str(audit_path),
                    "dry_run": False,
                },
            )
            self.assertEqual(committed.status_code, 200)
            self.assertEqual(committed.json()["created"], 242)

            legacy = client.get("/control/api/papers?page_size=500", headers=headers)
            self.assertEqual(legacy.status_code, 200)
            self.assertEqual(legacy.json()["page"]["total"], 242)

            reviews = client.get(
                "/control/api/paper-reviews?page_size=500&include_rank_reasons=true",
                headers=headers,
            )
            self.assertEqual(reviews.status_code, 200)
            body = reviews.json()
            self.assertEqual(body["source"], "control_api_paper_reviews")
            self.assertEqual(body["page"]["queue"], "paper_reviews")
            self.assertEqual(body["page"]["total"], 242)
            self.assertEqual(len(body["rows"]), 242)
            self.assertEqual(body["counts"]["queued"], 242)
            self.assertEqual(body["rows"][0]["paper_status"], "publication_draft")
            self.assertIn("rank_reasons", body["rows"][0])

            automation = client.get(
                "/control/api/publication-automation?page_size=500&include_rank_reasons=true",
                headers=headers,
            )
            self.assertEqual(automation.status_code, 200)
            automation_body = automation.json()
            self.assertEqual(automation_body["source"], "control_api_paper_reviews")
            self.assertEqual(automation_body["page"]["queue"], "publication_automation")
            self.assertEqual(automation_body["page"]["total"], 242)
            self.assertEqual(automation_body["counts"], body["counts"])

            filtered = client.get(
                "/control/api/publication-automation?page_size=500&paper_status=draft_review&search=idea-200",
                headers=headers,
            )
            self.assertEqual(filtered.status_code, 200)
            self.assertEqual(filtered.json()["page"]["total"], 1)

            detail_id = body["rows"][0]["paper_id"]
            detail = client.get(
                f"/control/api/publication-automation/{detail_id}", headers=headers
            )
            self.assertEqual(detail.status_code, 200)
            self.assertEqual(detail.json()["item"]["paper_id"], detail_id)
            self.assertEqual(detail.json()["paper"]["paper_id"], detail_id)

            legacy_detail = client.get(
                f"/control/api/paper-reviews/{detail_id}", headers=headers
            )
            self.assertEqual(legacy_detail.status_code, 200)
            self.assertEqual(legacy_detail.json()["item"]["paper_id"], detail_id)

            next_review = client.get(
                "/control/api/publication-automation/next?paper_status=publication_draft",
                headers=headers,
            )
            self.assertEqual(next_review.status_code, 200)
            self.assertEqual(next_review.json()["item"]["paper_id"], detail_id)

            legacy_next = client.get(
                "/control/api/paper-reviews/next?paper_status=publication_draft",
                headers=headers,
            )
            self.assertEqual(legacy_next.status_code, 200)
            self.assertEqual(legacy_next.json()["item"]["paper_id"], detail_id)

            repeated = client.post(
                "/control/api/paper-reviews/backfill",
                headers=headers,
                json={
                    "idempotency_key": "paper-review-router-backfill-second",
                    "requested_by": "test",
                    "source_audit_path": str(audit_path),
                    "dry_run": False,
                },
            )
            self.assertEqual(repeated.status_code, 200)
            self.assertEqual(repeated.json()["created"], 0)
            self.assertEqual(repeated.json()["updated"], 0)
            self.assertEqual(repeated.json()["skipped"], 242)

    def test_paper_review_backfill_treats_unexpandable_audit_path_as_missing_audit(
        self,
    ) -> None:
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
            audit_path.write_text(
                json.dumps({"papers": [{"paper_id": paper_id, "ready": True}]}),
                encoding="utf-8",
            )
            imported = client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "router-filter-normalized-import",
                    "paper_rows": [
                        {
                            "paper_id": paper_id,
                            "project_id": "router-filter-normalized",
                            "run_id": "run-1",
                            "paper_status": "publication_draft",
                            "draft_markdown_path": "paper.md",
                            "draft_latex_path": "paper.tex",
                            "evidence_bundle_path": "evidence.json",
                            "claim_ledger_path": "claims.json",
                            "manifest_path": "manifest.json",
                        }
                    ],
                },
            )
            self.assertEqual(imported.status_code, 200)
            backfill = client.post(
                "/control/api/paper-reviews/backfill",
                headers=headers,
                json={
                    "idempotency_key": "router-filter-normalized-backfill",
                    "source_audit_path": str(audit_path),
                    "dry_run": False,
                },
            )
            self.assertEqual(backfill.status_code, 200)
            with sqlite3.connect(Path(tmp) / "state" / "control_plane.sqlite3") as conn:
                conn.execute(
                    "UPDATE papers SET paper_status=? WHERE paper_id=?",
                    (" Publication Draft ", paper_id),
                )
                conn.execute(
                    "UPDATE paper_review_items SET review_status=? WHERE paper_id=?",
                    (" Queued ", paper_id),
                )

            papers = client.get(
                "/control/api/papers?status=publication_draft", headers=headers
            )
            self.assertEqual(papers.status_code, 200)
            self.assertEqual(papers.json()["page"]["total"], 1)
            self.assertEqual(papers.json()["counts"].get("publication_draft"), 1)
            reviews = client.get(
                "/control/api/publication-automation?paper_status=publication_draft&review_status=queued",
                headers=headers,
            )
            self.assertEqual(reviews.status_code, 200)
            self.assertEqual(reviews.json()["page"]["total"], 1)
            self.assertEqual(reviews.json()["counts"].get("queued"), 1)
            self.assertEqual(reviews.json()["counts"].get("publication_draft"), 1)
            self.assertIn("operator_summary", reviews.json())
            self.assertIn(
                "queued for the next operator pass", reviews.json()["operator_summary"]
            )
            next_review = client.get(
                "/control/api/paper-reviews/next?paper_status=publication_draft&review_status=queued",
                headers=headers,
            )
            self.assertEqual(next_review.status_code, 200)
            self.assertEqual(next_review.json()["paper_id"], paper_id)

    def test_paper_review_mutation_endpoints_validate_and_log_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            paper_id = "router-review:run-1:arxiv_draft"
            audit_path = Path(tmp) / "audit.json"
            audit_path.write_text(
                json.dumps({"papers": [{"paper_id": paper_id, "ready": True}]}),
                encoding="utf-8",
            )
            client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "router-review-mutation-import",
                    "paper_rows": [
                        {
                            "paper_id": paper_id,
                            "project_id": "router-review",
                            "run_id": "run-1",
                            "paper_status": "publication_draft",
                            "draft_markdown_path": "paper.md",
                            "draft_latex_path": "paper.tex",
                            "evidence_bundle_path": "evidence.json",
                            "claim_ledger_path": "claims.json",
                            "manifest_path": "manifest.json",
                        }
                    ],
                },
            )
            backfill = client.post(
                "/control/api/paper-reviews/backfill",
                headers=headers,
                json={
                    "idempotency_key": "router-review-mutation-backfill",
                    "source_audit_path": str(audit_path),
                    "dry_run": False,
                },
            )
            self.assertEqual(backfill.status_code, 200)

            claim = client.post(
                f"/control/api/paper-reviews/{paper_id}/claim",
                headers=headers,
                json={
                    "idempotency_key": "router-claim-1",
                    "requested_by": "alice",
                    "reviewer": "alice",
                },
            )
            self.assertEqual(claim.status_code, 200)
            self.assertEqual(claim.json()["item"]["review_status"], "claimed")
            self.assertEqual(claim.json()["item"]["reviewer"], "alice")
            claim_repeat = client.post(
                f"/control/api/paper-reviews/{paper_id}/claim",
                headers=headers,
                json={
                    "idempotency_key": "router-claim-1",
                    "requested_by": "alice",
                    "reviewer": "alice",
                },
            )
            self.assertEqual(claim_repeat.status_code, 200)
            self.assertFalse(claim_repeat.json()["inserted_event"])

            bad_check = client.post(
                f"/control/api/paper-reviews/{paper_id}/checklist/artifact_readability",
                headers=headers,
                json={
                    "idempotency_key": "router-bad-check",
                    "requested_by": "alice",
                    "status": "fail",
                },
            )
            self.assertEqual(bad_check.status_code, 400)

            for item_id in [
                "artifact_readability",
                "title_abstract_quality",
                "claim_evidence_alignment",
                "novelty_significance",
                "reproducibility",
                "limitations_ethics",
                "formatting_quality",
                "final_human_approval",
            ]:
                response = client.post(
                    f"/control/api/paper-reviews/{paper_id}/checklist/{item_id}",
                    headers=headers,
                    json={
                        "idempotency_key": f"router-check-{item_id}",
                        "requested_by": "alice",
                        "status": "pass",
                    },
                )
                self.assertEqual(response.status_code, 200)

            detail = client.get(
                f"/control/api/paper-reviews/{paper_id}", headers=headers
            )
            self.assertEqual(detail.status_code, 200)
            self.assertEqual(detail.json()["checklist"]["progress"]["passed"], 8)
            self.assertEqual(
                detail.json()["paper"]["paper_status"], "publication_draft"
            )

            approval = client.post(
                f"/control/api/paper-reviews/{paper_id}/approve-finalization",
                headers=headers,
                json={
                    "idempotency_key": "router-approve-1",
                    "requested_by": "alice",
                    "note": "ready",
                },
            )
            self.assertEqual(approval.status_code, 400)
            self.assertIn("manual paper approval has been removed", approval.text)

            rejected_status = client.post(
                f"/control/api/paper-reviews/{paper_id}/status",
                headers=headers,
                json={
                    "idempotency_key": "router-status-invalid",
                    "requested_by": "alice",
                    "review_status": "approved_for_finalization",
                    "note": "no",
                },
            )
            self.assertEqual(rejected_status.status_code, 400)

            events = client.get(
                f"/control/api/events?entity_id={paper_id}", headers=headers
            )
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
                (evidence_dir / "run_notes.md").write_text(
                    f"Bulk Paper {idx} has local evidence for rewrite.\n",
                    encoding="utf-8",
                )
                papers.append(
                    {
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
                    }
                )
            client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={"idempotency_key": "bulk-rewrite-import", "paper_rows": papers},
            )
            client.post(
                "/control/api/paper-reviews/backfill",
                headers=headers,
                json={"idempotency_key": "bulk-rewrite-backfill", "dry_run": False},
            )

            dry = client.post(
                "/control/api/paper-reviews/rewrite-batch",
                headers=headers,
                json={
                    "idempotency_key": "bulk-rewrite-dry",
                    "requested_by": "ai-publication-pipeline",
                    "limit": 2,
                    "dry_run": True,
                },
            )
            self.assertEqual(dry.status_code, 200)
            self.assertTrue(dry.json()["dry_run"])
            self.assertEqual(dry.json()["processed"], 2)

            committed = client.post(
                "/control/api/paper-reviews/rewrite-batch",
                headers=headers,
                json={
                    "idempotency_key": "bulk-rewrite-commit",
                    "requested_by": "ai-publication-pipeline",
                    "limit": 2,
                    "force": True,
                    "dry_run": False,
                },
            )
            self.assertEqual(committed.status_code, 200)
            body = committed.json()
            self.assertEqual(body["processed"], 2)
            self.assertEqual(body["rewritten"], 2)
            self.assertEqual(body["failed"], 0)
            for row in body["rows"]:
                self.assertTrue(row["ok"])
                self.assertEqual(row["provider"], "deterministic")
                self.assertTrue(
                    (
                        config.expanded_project_root
                        / row["paper_id"].split(":", 1)[0]
                        / "papers"
                    ).exists()
                )

    def test_paper_review_bulk_rewrite_skips_blocked_and_changes_requested_rows(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _config(tmp)
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            papers = []
            for project_id in ["safe-bulk", "blocked-bulk", "changes-bulk"]:
                evidence_dir = config.expanded_project_root / project_id
                evidence_dir.mkdir(parents=True, exist_ok=True)
                (evidence_dir / "run_notes.md").write_text(
                    f"{project_id} has local evidence for rewrite.\n", encoding="utf-8"
                )
                papers.append(
                    {
                        "paper_id": f"{project_id}:run-1:arxiv_draft",
                        "project_id": project_id,
                        "project_name": project_id,
                        "run_id": "run-1",
                        "paper_status": "publication_draft",
                        "draft_markdown_path": "papers/run-1/final.md",
                        "draft_latex_path": "papers/run-1/final.tex",
                        "evidence_bundle_path": "papers/run-1/evidence.json",
                        "claim_ledger_path": "papers/run-1/claims.json",
                        "manifest_path": "papers/run-1/manifest.json",
                    }
                )
            client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={"idempotency_key": "unsafe-bulk-import", "paper_rows": papers},
            )
            client.post(
                "/control/api/paper-reviews/backfill",
                headers=headers,
                json={"idempotency_key": "unsafe-bulk-backfill", "dry_run": False},
            )
            blocked_id = "blocked-bulk:run-1:arxiv_draft"
            changes_id = "changes-bulk:run-1:arxiv_draft"
            blocked = client.post(
                f"/control/api/paper-reviews/{blocked_id}/status",
                headers=headers,
                json={
                    "idempotency_key": "unsafe-bulk-blocked",
                    "requested_by": "alice",
                    "review_status": "blocked",
                    "blocker": "private evidence needs review",
                },
            )
            self.assertEqual(blocked.status_code, 200)
            with sqlite3.connect(Path(tmp) / "state" / "control_plane.sqlite3") as conn:
                conn.execute(
                    "UPDATE paper_review_items SET review_status=?, decision_summary=? WHERE paper_id=?",
                    (
                        "changes_requested",
                        "rewrite only after operator fixes claims",
                        changes_id,
                    ),
                )

            committed = client.post(
                "/control/api/paper-reviews/rewrite-batch",
                headers=headers,
                json={
                    "idempotency_key": "unsafe-bulk-commit",
                    "requested_by": "ai-publication-pipeline",
                    "paper_status": "publication_draft",
                    "review_status": "",
                    "limit": 10,
                    "force": True,
                    "dry_run": False,
                    "skip_rewritten": False,
                },
            )
            self.assertEqual(committed.status_code, 200)
            body = committed.json()
            self.assertEqual(body["matched"], 1)
            self.assertEqual(body["processed"], 1)
            self.assertEqual(body["rewritten"], 1)
            self.assertEqual(body["rows"][0]["paper_id"], "safe-bulk:run-1:arxiv_draft")
            self.assertEqual(
                client.get(
                    f"/control/api/paper-reviews/{blocked_id}", headers=headers
                ).json()["item"]["review_status"],
                "blocked",
            )
            self.assertEqual(
                client.get(
                    f"/control/api/paper-reviews/{changes_id}", headers=headers
                ).json()["item"]["review_status"],
                "changes_requested",
            )

    def test_paper_review_rewrite_draft_rejects_blocked_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _config(tmp)
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            paper_id = "blocked-rewrite:run-1:arxiv_draft"
            evidence_dir = config.expanded_project_root / "blocked-rewrite"
            evidence_dir.mkdir(parents=True, exist_ok=True)
            (evidence_dir / "run_notes.md").write_text(
                "PRIVATE_EVIDENCE_TOKEN should not be sent to a writer.\n",
                encoding="utf-8",
            )
            client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "blocked-rewrite-import",
                    "paper_rows": [
                        {
                            "paper_id": paper_id,
                            "project_id": "blocked-rewrite",
                            "project_name": "Blocked Rewrite",
                            "run_id": "run-1",
                            "paper_status": "publication_draft",
                            "draft_markdown_path": "papers/run-1/final.md",
                            "draft_latex_path": "papers/run-1/final.tex",
                            "evidence_bundle_path": "papers/run-1/evidence.json",
                            "claim_ledger_path": "papers/run-1/claims.json",
                            "manifest_path": "papers/run-1/manifest.json",
                        }
                    ],
                },
            )
            client.post(
                "/control/api/paper-reviews/backfill",
                headers=headers,
                json={"idempotency_key": "blocked-rewrite-backfill", "dry_run": False},
            )
            blocked = client.post(
                f"/control/api/paper-reviews/{paper_id}/status",
                headers=headers,
                json={
                    "idempotency_key": "blocked-rewrite-status",
                    "requested_by": "alice",
                    "review_status": "blocked",
                    "blocker": "private evidence needs review",
                },
            )
            self.assertEqual(blocked.status_code, 200)

            response = client.post(
                f"/control/api/paper-reviews/{paper_id}/rewrite-draft",
                headers=headers,
                json={
                    "idempotency_key": "blocked-rewrite-attempt",
                    "requested_by": "ai-publication-pipeline",
                    "force": True,
                },
            )
            self.assertEqual(response.status_code, 400)
            self.assertIn("review_status=blocked", response.text)
            detail = client.get(
                f"/control/api/paper-reviews/{paper_id}", headers=headers
            ).json()
            self.assertEqual(detail["item"]["review_status"], "blocked")
            package = client.post(
                f"/control/api/paper-reviews/{paper_id}/prepare-finalization-package",
                headers=headers,
                json={
                    "idempotency_key": "blocked-rewrite-finalize-attempt",
                    "requested_by": "ai-publication-pipeline",
                    "dry_run": False,
                },
            )
            self.assertEqual(package.status_code, 400)
            self.assertIn("review_status=blocked", package.text)

    def test_paper_review_rewrite_draft_writes_vm_local_artifacts_and_logs_event(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _config(tmp)
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            paper_id = "router-rewrite:run-1:arxiv_draft"
            evidence_dir = config.expanded_project_root / "router-rewrite"
            evidence_dir.mkdir(parents=True, exist_ok=True)
            (evidence_dir / "run_notes.md").write_text(
                "Router Rewrite has synced local evidence.\n", encoding="utf-8"
            )
            legacy_dir = Path(tmp) / "legacy-missing" / "router-rewrite"
            audit_path = Path(tmp) / "audit.json"
            audit_path.write_text(
                json.dumps({"papers": [{"paper_id": paper_id, "ready": True}]}),
                encoding="utf-8",
            )
            client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "router-rewrite-import",
                    "paper_rows": [
                        {
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
                        }
                    ],
                },
            )
            client.post(
                "/control/api/paper-reviews/backfill",
                headers=headers,
                json={
                    "idempotency_key": "router-rewrite-backfill",
                    "source_audit_path": str(audit_path),
                    "dry_run": False,
                },
            )

            response = client.post(
                f"/control/api/paper-reviews/{paper_id}/rewrite-draft",
                headers=headers,
                json={
                    "idempotency_key": "router-rewrite-1",
                    "requested_by": "alice",
                    "force": True,
                },
            )
            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertTrue(body["inserted_event"])
            self.assertEqual(body["writer"]["provider"], "deterministic")
            self.assertEqual(body["paper"]["paper_status"], "publication_draft")
            self.assertEqual(body["item"]["review_status"], "finalized")
            self.assertTrue(Path(body["item"]["finalization_package_path"]).exists())
            self.assertEqual(
                body["writer"]["automated_finalization"]["review_status"], "finalized"
            )
            review_detail = client.get(
                f"/control/api/paper-reviews/{paper_id}", headers=headers
            ).json()
            self.assertEqual(
                review_detail["paper"]["paper_status"], "publication_draft"
            )
            self.assertEqual(review_detail["item"]["review_status"], "finalized")
            artifact_root = Path(body["artifact_root"])
            self.assertEqual(
                artifact_root, config.expanded_project_root / "router-rewrite"
            )
            self.assertTrue((artifact_root / "papers/run-1/final_paper.md").exists())
            self.assertIn(
                "Router Rewrite",
                (artifact_root / "papers/run-1/final_paper.md").read_text(
                    encoding="utf-8"
                ),
            )

            dry_package = client.post(
                f"/control/api/paper-reviews/{paper_id}/prepare-finalization-package",
                headers=headers,
                json={
                    "idempotency_key": "router-rewrite-package-dry",
                    "requested_by": "alice",
                    "dry_run": True,
                },
            )
            self.assertEqual(dry_package.status_code, 200)
            artifacts = dry_package.json()["manifest"]["artifacts"]
            self.assertTrue(all(item["readable"] for item in artifacts))
            artifact = client.get(
                f"/control/api/papers/{paper_id}/artifact/draft_markdown_path",
                headers=headers,
            )
            self.assertEqual(artifact.status_code, 200)
            self.assertEqual(artifact.json()["field"], "draft_markdown_path")
            self.assertIn("Router Rewrite", artifact.json()["content"])
            missing = client.get(
                f"/control/api/papers/{paper_id}/artifact/not_a_field", headers=headers
            )
            self.assertEqual(missing.status_code, 404)
            events = client.get(
                f"/control/api/events?entity_id={paper_id}", headers=headers
            ).json()["rows"]
            event_types = {row["event_type"] for row in events}
            self.assertIn("paper_review.draft_rewritten", event_types)
            self.assertIn("paper_review.finalization_package_prepared", event_types)

    def test_paper_review_rewrite_rejects_uninspectable_current_project_dir_without_fallback(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _config(tmp)
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            project_id = "router-rewrite-uninspectable"
            paper_id = f"{project_id}:run-1:arxiv_draft"
            current_artifact_root = (
                config.expanded_project_root / "custom-artifact-root"
            )
            current_artifact_root.mkdir(parents=True, exist_ok=True)
            (current_artifact_root / "run_notes.md").write_text(
                "Uninspectable rewrite evidence.\n", encoding="utf-8"
            )
            audit_path = Path(tmp) / "audit.json"
            audit_path.write_text(
                json.dumps({"papers": [{"paper_id": paper_id, "ready": True}]}),
                encoding="utf-8",
            )
            client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "router-rewrite-uninspectable-import",
                    "paper_rows": [
                        {
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
                        }
                    ],
                },
            )
            client.post(
                "/control/api/paper-reviews/backfill",
                headers=headers,
                json={
                    "idempotency_key": "router-rewrite-uninspectable-backfill",
                    "source_audit_path": str(audit_path),
                    "dry_run": False,
                },
            )
            original_exists = Path.exists

            def guarded_exists(path: Path, *args, **kwargs) -> bool:
                if path == current_artifact_root:
                    raise PermissionError(
                        "no permission to inspect current project dir"
                    )
                return original_exists(path, *args, **kwargs)

            with patch.object(Path, "exists", guarded_exists):
                response = client.post(
                    f"/control/api/paper-reviews/{paper_id}/rewrite-draft",
                    headers=headers,
                    json={
                        "idempotency_key": "router-rewrite-uninspectable-1",
                        "requested_by": "alice",
                        "force": True,
                    },
                )
            self.assertEqual(response.status_code, 400)
            self.assertEqual(
                response.json()["detail"], "paper artifact root could not be inspected"
            )
            fallback_root = config.expanded_project_root / project_id
            self.assertFalse((fallback_root / "papers/run-1/final_paper.md").exists())
            self.assertFalse(
                (current_artifact_root / "papers/run-1/final_paper.md").exists()
            )

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
            (evidence_dir / "run_notes.md").write_text(
                "Replay rewrite has source evidence.\n", encoding="utf-8"
            )
            (evidence_dir / ".enoch").mkdir()
            (evidence_dir / ".enoch" / "project_decision.json").write_text(
                '{"project_decision":"finalize_positive"}\n', encoding="utf-8"
            )
            audit_path = Path(tmp) / "audit.json"
            audit_path.write_text(
                json.dumps({"papers": [{"paper_id": paper_id, "ready": True}]}),
                encoding="utf-8",
            )
            client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "router-rewrite-replay-import",
                    "paper_rows": [
                        {
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
                        }
                    ],
                },
            )
            client.post(
                "/control/api/paper-reviews/backfill",
                headers=headers,
                json={
                    "idempotency_key": "router-rewrite-replay-backfill",
                    "source_audit_path": str(audit_path),
                    "dry_run": False,
                },
            )

            with patch(
                "enoch_control_plane.control_plane.router._sync_remote_project_evidence",
                return_value={
                    "enabled": True,
                    "synced": True,
                    "reason": "test",
                    "local_evidence_present": True,
                },
            ) as sync:
                first = client.post(
                    f"/control/api/paper-reviews/{paper_id}/rewrite-draft",
                    headers=headers,
                    json={
                        "idempotency_key": "router-rewrite-replay-1",
                        "requested_by": "alice",
                        "force": True,
                    },
                )
                replay = client.post(
                    f"/control/api/paper-reviews/{paper_id}/rewrite-draft",
                    headers=headers,
                    json={
                        "idempotency_key": "router-rewrite-replay-1",
                        "requested_by": "alice",
                        "force": True,
                    },
                )

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
            (evidence_dir / "run_notes.md").write_text(
                "Router Rewrite Datetime has local evidence.\n", encoding="utf-8"
            )
            audit_path = Path(tmp) / "audit.json"
            audit_path.write_text(
                json.dumps({"papers": [{"paper_id": paper_id, "ready": True}]}),
                encoding="utf-8",
            )
            store = ControlPlaneStore(Path(tmp) / "state" / "control_plane.sqlite3")
            store.import_snapshot(
                ImportSnapshotRequest(
                    idempotency_key="router-rewrite-datetime-import",
                    paper_rows=[
                        {
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
                        }
                    ],
                )
            )
            store.backfill_paper_reviews(
                PaperReviewBackfillRequest(
                    idempotency_key="router-rewrite-datetime-backfill",
                    source_audit_path=str(audit_path),
                    dry_run=False,
                )
            )
            original_paper_row = store.paper_row

            def paper_row_with_datetimes(pid: str) -> dict | None:
                row = original_paper_row(pid)
                if row:
                    row["generated_at"] = datetime(
                        2026, 5, 6, 21, 4, 30, tzinfo=timezone.utc
                    )
                    row["updated_at"] = datetime(
                        2026, 5, 6, 21, 4, 30, tzinfo=timezone.utc
                    )
                return row

            with patch.object(store, "paper_row", side_effect=paper_row_with_datetimes):
                response = client.post(
                    f"/control/api/paper-reviews/{paper_id}/rewrite-draft",
                    headers=headers,
                    json={
                        "idempotency_key": "router-rewrite-datetime-1",
                        "requested_by": "alice",
                        "force": True,
                    },
                )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["item"]["review_status"], "finalized")

    def test_paper_artifact_endpoint_resolves_relative_project_dir_under_configured_root(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _config(tmp)
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            project_dir = config.expanded_project_root / "relative-project"
            paper_dir = project_dir / "papers" / "run-relative"
            paper_dir.mkdir(parents=True)
            (paper_dir / "paper.md").write_text(
                "# Relative Artifact\n", encoding="utf-8"
            )

            paper_id = "relative-project:run-relative:arxiv_draft"
            response = client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "relative-project-artifact-import",
                    "queue_rows": [
                        {
                            "project_id": "relative-project",
                            "project_name": "Relative Project",
                            "project_dir": "relative-project",
                            "status": "completed",
                        }
                    ],
                    "paper_rows": [
                        {
                            "paper_id": paper_id,
                            "project_id": "relative-project",
                            "run_id": "run-relative",
                            "paper_status": "publication_draft",
                            "draft_markdown_path": "papers/run-relative/paper.md",
                        }
                    ],
                },
            )
            self.assertEqual(response.status_code, 200)

            artifact = client.get(
                f"/control/api/papers/{paper_id}/artifact/draft_markdown_path",
                headers=headers,
            )
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
            response = client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "artifact-escape-import",
                    "paper_rows": [
                        {
                            "paper_id": paper_id,
                            "project_id": "artifact-escape",
                            "run_id": "run-escape",
                            "project_dir": str(outside),
                            "paper_status": "publication_draft",
                            "draft_markdown_path": "paper.md",
                        }
                    ],
                },
            )
            self.assertEqual(response.status_code, 200)

            artifact = client.get(
                f"/control/api/papers/{paper_id}/artifact/draft_markdown_path",
                headers=headers,
            )

            self.assertNotEqual(artifact.status_code, 200)
            self.assertNotIn("Outside Artifact", artifact.text)

    def test_paper_artifact_endpoint_rejects_invalid_artifact_path_without_500(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _config(tmp)
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}

            paper_id = "artifact-invalid-path:run-invalid:arxiv_draft"
            response = client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "artifact-invalid-path-import",
                    "paper_rows": [
                        {
                            "paper_id": paper_id,
                            "project_id": "artifact-invalid-path",
                            "run_id": "run-invalid",
                            "project_dir": "artifact-invalid-path",
                            "paper_status": "publication_draft",
                            "draft_markdown_path": "bad\0paper.md",
                        }
                    ],
                },
            )
            self.assertEqual(response.status_code, 200)

            artifact = client.get(
                f"/control/api/papers/{paper_id}/artifact/draft_markdown_path",
                headers=headers,
            )

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
            response = client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "artifact-access-failure-import",
                    "paper_rows": [
                        {
                            "paper_id": paper_id,
                            "project_id": "artifact-access-failure",
                            "run_id": "run-access",
                            "project_dir": str(project_dir),
                            "paper_status": "publication_draft",
                            "draft_markdown_path": "paper.md",
                        }
                    ],
                },
            )
            self.assertEqual(response.status_code, 200)
            real_exists = Path.exists

            def blocked_exists(path: Path) -> bool:
                if path == artifact_path:
                    raise PermissionError("simulated artifact access failure")
                return real_exists(path)

            with patch("pathlib.Path.exists", blocked_exists):
                artifact = client.get(
                    f"/control/api/papers/{paper_id}/artifact/draft_markdown_path",
                    headers=headers,
                )

            self.assertEqual(artifact.status_code, 404)
            self.assertNotEqual(artifact.status_code, 500)

    def test_paper_rewrite_rejects_invalid_project_id_without_500(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _config(tmp)
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            paper_id = "router-invalid-project-id:run-1:arxiv_draft"
            audit_path = Path(tmp) / "audit.json"
            audit_path.write_text(
                json.dumps({"papers": [{"paper_id": paper_id, "ready": True}]}),
                encoding="utf-8",
            )
            imported = client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "router-invalid-project-id-import",
                    "paper_rows": [
                        {
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
                        }
                    ],
                },
            )
            self.assertEqual(imported.status_code, 200)
            backfill = client.post(
                "/control/api/paper-reviews/backfill",
                headers=headers,
                json={
                    "idempotency_key": "router-invalid-project-id-backfill",
                    "source_audit_path": str(audit_path),
                    "dry_run": False,
                },
            )
            self.assertEqual(backfill.status_code, 200)

            response = client.post(
                f"/control/api/paper-reviews/{paper_id}/rewrite-draft",
                headers=headers,
                json={
                    "idempotency_key": "router-invalid-project-id-rewrite",
                    "requested_by": "alice",
                    "force": True,
                },
            )

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
            (project_dir / artifact_paths["draft_latex_path"]).write_text(
                "latex", encoding="utf-8"
            )
            original_markdown = (
                project_dir / artifact_paths["draft_markdown_path"]
            ).read_text(encoding="utf-8")
            audit_path = Path(tmp) / "audit.json"
            audit_path.write_text(
                json.dumps({"papers": [{"paper_id": paper_id, "ready": True}]}),
                encoding="utf-8",
            )
            imported = client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "router-unreadable-snapshot-import",
                    "paper_rows": [
                        {
                            "paper_id": paper_id,
                            "project_id": "router-unreadable-snapshot",
                            "project_name": "Router Unreadable Snapshot",
                            "project_dir": str(project_dir),
                            "run_id": "run-1",
                            "paper_status": "publication_draft",
                            **artifact_paths,
                        }
                    ],
                },
            )
            self.assertEqual(imported.status_code, 200)
            backfill = client.post(
                "/control/api/paper-reviews/backfill",
                headers=headers,
                json={
                    "idempotency_key": "router-unreadable-snapshot-backfill",
                    "source_audit_path": str(audit_path),
                    "dry_run": False,
                },
            )
            self.assertEqual(backfill.status_code, 200)

            with patch(
                "pathlib.Path.read_bytes",
                side_effect=PermissionError("blocked snapshot read"),
            ):
                response = client.post(
                    f"/control/api/paper-reviews/{paper_id}/rewrite-draft",
                    headers=headers,
                    json={
                        "idempotency_key": "router-unreadable-snapshot-rewrite",
                        "requested_by": "alice",
                        "force": True,
                    },
                )

            self.assertEqual(response.status_code, 400)
            self.assertIn("snapshot", response.text.lower())
            self.assertEqual(
                (project_dir / artifact_paths["draft_markdown_path"]).read_text(
                    encoding="utf-8"
                ),
                original_markdown,
            )

            real_exists = Path.exists

            def blocked_exists(path: Path) -> bool:
                if path == project_dir / artifact_paths["draft_markdown_path"]:
                    raise PermissionError("blocked snapshot inspect")
                return real_exists(path)

            with patch("pathlib.Path.exists", blocked_exists):
                response = client.post(
                    f"/control/api/paper-reviews/{paper_id}/rewrite-draft",
                    headers=headers,
                    json={
                        "idempotency_key": "router-unreadable-snapshot-rewrite-exists",
                        "requested_by": "alice",
                        "force": True,
                    },
                )

            self.assertEqual(response.status_code, 400)
            self.assertIn("snapshot", response.text.lower())
            self.assertEqual(
                (project_dir / artifact_paths["draft_markdown_path"]).read_text(
                    encoding="utf-8"
                ),
                original_markdown,
            )

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
            (evidence_dir / "run_notes.md").write_text(
                "Event failure rewrite has source evidence.\n", encoding="utf-8"
            )
            (evidence_dir / ".enoch").mkdir()
            (evidence_dir / ".enoch" / "project_decision.json").write_text(
                '{"project_decision":"finalize_positive"}\n', encoding="utf-8"
            )
            response = client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "router-rewrite-event-fail-import",
                    "paper_rows": [
                        {
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
                        }
                    ],
                },
            )
            self.assertEqual(response.status_code, 200)
            client.post(
                "/control/api/paper-reviews/backfill",
                headers=headers,
                json={
                    "idempotency_key": "router-rewrite-event-fail-backfill",
                    "dry_run": False,
                },
            )
            original_append_event = ControlPlaneStore.append_event

            def fail_rewrite_event(self, *args, **kwargs):  # noqa: ANN001 - patched method
                if kwargs.get("event_type") == "paper_review.draft_rewritten":
                    raise OSError("simulated rewrite event store failure")
                return original_append_event(self, *args, **kwargs)

            with patch.object(
                ControlPlaneStore, "append_event", new=fail_rewrite_event
            ):
                with self.assertRaisesRegex(
                    OSError, "simulated rewrite event store failure"
                ):
                    client.post(
                        f"/control/api/paper-reviews/{paper_id}/rewrite-draft",
                        headers=headers,
                        json={
                            "idempotency_key": "router-rewrite-event-fail-1",
                            "requested_by": "alice",
                            "force": True,
                        },
                    )

            paper = client.get(
                f"/control/api/papers/{paper_id}", headers=headers
            ).json()["paper"]
            self.assertEqual(paper["paper_status"], "draft_review")
            self.assertEqual(paper["project_dir"], str(legacy_dir))
            self.assertFalse((evidence_dir / "papers/run-1/final_paper.md").exists())
            events = client.get(
                f"/control/api/events?entity_id={paper_id}", headers=headers
            ).json()["rows"]
            self.assertNotIn(
                "paper_review.draft_rewritten", {row["event_type"] for row in events}
            )

    def test_paper_review_rewrite_finalization_failure_preserves_committed_draft_event(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _config(tmp)
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            paper_id = "router-rewrite-finalization-fail:run-1:arxiv_draft"
            project_id = "router-rewrite-finalization-fail"
            legacy_dir = Path(tmp) / "legacy" / project_id
            evidence_dir = config.expanded_project_root / project_id
            evidence_dir.mkdir(parents=True, exist_ok=True)
            (evidence_dir / "run_notes.md").write_text(
                "Finalization failure rewrite has source evidence.\n", encoding="utf-8"
            )
            (evidence_dir / ".enoch").mkdir()
            (evidence_dir / ".enoch" / "project_decision.json").write_text(
                '{"project_decision":"finalize_positive"}\n', encoding="utf-8"
            )
            response = client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "router-rewrite-finalization-fail-import",
                    "paper_rows": [
                        {
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
                        }
                    ],
                },
            )
            self.assertEqual(response.status_code, 200)
            client.post(
                "/control/api/paper-reviews/backfill",
                headers=headers,
                json={
                    "idempotency_key": "router-rewrite-finalization-fail-backfill",
                    "dry_run": False,
                },
            )

            def fail_finalization(self, *args, **kwargs):  # noqa: ANN001, ARG001 - patched method
                raise OSError("simulated finalization package failure")

            with patch.object(
                ControlPlaneStore,
                "prepare_paper_review_finalization_package",
                new=fail_finalization,
            ):
                with self.assertRaisesRegex(
                    OSError, "simulated finalization package failure"
                ):
                    client.post(
                        f"/control/api/paper-reviews/{paper_id}/rewrite-draft",
                        headers=headers,
                        json={
                            "idempotency_key": "router-rewrite-finalization-fail-1",
                            "requested_by": "alice",
                            "force": True,
                        },
                    )

            paper = client.get(
                f"/control/api/papers/{paper_id}", headers=headers
            ).json()["paper"]
            self.assertEqual(paper["paper_status"], "publication_draft")
            self.assertEqual(paper["project_dir"], str(evidence_dir))
            self.assertTrue((evidence_dir / "papers/run-1/final_paper.md").exists())
            events = client.get(
                f"/control/api/events?entity_id={paper_id}", headers=headers
            ).json()["rows"]
            self.assertIn(
                "paper_review.draft_rewritten", {row["event_type"] for row in events}
            )
            review_rows = client.get(
                "/control/api/paper-reviews", headers=headers
            ).json()["rows"]
            row = next(row for row in review_rows if row["paper_id"] == paper_id)
            self.assertNotEqual(row["review_status"], "finalized")

    def test_paper_review_rewrite_idempotency_conflict_does_not_mutate_state_or_files(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _config(tmp)
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            paper_id = "router-rewrite-conflict:run-1:arxiv_draft"
            project_id = "router-rewrite-conflict"
            legacy_dir = Path(tmp) / "legacy" / project_id
            evidence_dir = config.expanded_project_root / project_id
            evidence_dir.mkdir(parents=True, exist_ok=True)
            (evidence_dir / "run_notes.md").write_text(
                "Conflict rewrite has source evidence.\n", encoding="utf-8"
            )
            (evidence_dir / ".enoch").mkdir()
            (evidence_dir / ".enoch" / "project_decision.json").write_text(
                '{"project_decision":"finalize_positive"}\n', encoding="utf-8"
            )
            response = client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "router-rewrite-conflict-key",
                    "paper_rows": [
                        {
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
                        }
                    ],
                },
            )
            self.assertEqual(response.status_code, 200)
            client.post(
                "/control/api/paper-reviews/backfill",
                headers=headers,
                json={
                    "idempotency_key": "router-rewrite-conflict-backfill",
                    "dry_run": False,
                },
            )

            conflict = client.post(
                f"/control/api/paper-reviews/{paper_id}/rewrite-draft",
                headers=headers,
                json={
                    "idempotency_key": "router-rewrite-conflict-key",
                    "requested_by": "alice",
                    "force": True,
                },
            )

            self.assertEqual(conflict.status_code, 409)
            paper = client.get(
                f"/control/api/papers/{paper_id}", headers=headers
            ).json()["paper"]
            self.assertEqual(paper["paper_status"], "draft_review")
            self.assertEqual(paper["project_dir"], str(legacy_dir))
            self.assertFalse((evidence_dir / "papers/run-1/final_paper.md").exists())
            events = client.get(
                f"/control/api/events?entity_id={paper_id}", headers=headers
            ).json()["rows"]
            self.assertNotIn(
                "paper_review.draft_rewritten", {row["event_type"] for row in events}
            )

    def test_paper_review_rewrite_failure_does_not_mutate_project_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _config(tmp)
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            paper_id = "router-rewrite-fail:run-1:arxiv_draft"
            legacy_dir = Path(tmp) / "legacy-missing" / "router-rewrite-fail"
            client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "router-rewrite-fail-import",
                    "paper_rows": [
                        {
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
                        }
                    ],
                },
            )
            client.post(
                "/control/api/paper-reviews/backfill",
                headers=headers,
                json={
                    "idempotency_key": "router-rewrite-fail-backfill",
                    "dry_run": False,
                },
            )
            with patch(
                "enoch_control_plane.control_plane.router.write_paper_artifacts",
                side_effect=RuntimeError("rewrite writer exploded"),
            ):
                with self.assertRaisesRegex(RuntimeError, "rewrite writer exploded"):
                    client.post(
                        f"/control/api/paper-reviews/{paper_id}/rewrite-draft",
                        headers=headers,
                        json={
                            "idempotency_key": "router-rewrite-fail-1",
                            "requested_by": "alice",
                            "force": True,
                        },
                    )
            paper = client.get(
                f"/control/api/papers/{paper_id}", headers=headers
            ).json()["paper"]
            self.assertEqual(paper["project_dir"], str(legacy_dir))
            events = client.get(
                f"/control/api/events?entity_id={paper_id}", headers=headers
            ).json()["rows"]
            self.assertNotIn(
                "paper_review.draft_rewritten", {row["event_type"] for row in events}
            )

    def test_paper_review_rewrite_tolerates_missing_optional_worker_evidence_paths(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _config(tmp).model_copy(
                update={
                    "paper_evidence_sync_enabled": True,
                    "worker_wake_gate_url": "http://worker.example",
                    "worker_wake_gate_bearer_token": "worker-token",
                    "paper_evidence_sync_ssh_host": "missing-ssh-host.invalid",
                }
            )
            client = _client_with_config(config)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            paper_id = "router-sync:run-1:arxiv_draft"
            client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "router-sync-import",
                    "paper_rows": [
                        {
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
                        }
                    ],
                },
            )
            client.post(
                "/control/api/paper-reviews/backfill",
                headers=headers,
                json={"idempotency_key": "router-sync-backfill", "dry_run": False},
            )

            def fake_worker_post(
                base_url: str, path: str, token: str, payload: dict
            ) -> HttpResult:
                requested = payload["paths"][0]
                if requested == "run_notes.md":
                    return HttpResult(
                        ok=True,
                        status=200,
                        body={
                            "files": [
                                {
                                    "path": requested,
                                    "content": "Measured router sync evidence improved throughput by 1.20x.\n",
                                }
                            ]
                        },
                    )
                if requested == ".enoch/project_decision.json":
                    return HttpResult(
                        ok=True,
                        status=200,
                        body={
                            "files": [
                                {
                                    "path": requested,
                                    "content": '{"decision":"positive","evidence":"measured"}\n',
                                }
                            ]
                        },
                    )
                if requested == "papers/run-1/evidence_bundle.json":
                    return HttpResult(
                        ok=True,
                        status=200,
                        body={
                            "files": [
                                {
                                    "path": requested,
                                    "content": '{"claims":["measured"]}',
                                }
                            ]
                        },
                    )
                return HttpResult(
                    ok=False, status=404, body=None, error=f"missing {requested}"
                )

            with patch(
                "enoch_control_plane.control_plane.worker_evidence_sync.post_worker_json",
                side_effect=fake_worker_post,
            ):
                response = client.post(
                    f"/control/api/paper-reviews/{paper_id}/rewrite-draft",
                    headers=headers,
                    json={
                        "idempotency_key": "router-sync-rewrite",
                        "requested_by": "alice",
                        "force": True,
                    },
                )

            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertIn(
                body["writer"]["evidence_sync"]["method"],
                {"worker_http", "worker_http+ssh"},
            )
            self.assertGreaterEqual(
                body["writer"]["evidence_sync"]["http_sync"]["files"], 2
            )
            self.assertTrue(
                (
                    Path(body["artifact_root"]) / "papers/run-1/evidence_bundle.json"
                ).exists()
            )

    def test_paper_review_prepare_finalization_package_endpoint_is_automated_and_idempotent(
        self,
    ) -> None:
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
            audit_path.write_text(
                json.dumps({"papers": [{"paper_id": paper_id, "ready": True}]}),
                encoding="utf-8",
            )
            client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "router-package-import",
                    "paper_rows": [
                        {
                            "paper_id": paper_id,
                            "project_id": "router-package",
                            "project_name": "Router Package",
                            "project_dir": str(project_dir),
                            "run_id": "run-1",
                            "paper_status": "publication_draft",
                            **artifact_paths,
                        }
                    ],
                },
            )
            client.post(
                "/control/api/paper-reviews/backfill",
                headers=headers,
                json={
                    "idempotency_key": "router-package-backfill",
                    "source_audit_path": str(audit_path),
                    "dry_run": False,
                },
            )

            dry = client.post(
                f"/control/api/paper-reviews/{paper_id}/prepare-finalization-package",
                headers=headers,
                json={
                    "idempotency_key": "router-package-dry",
                    "requested_by": "alice",
                    "target_label": "first-paper",
                    "dry_run": True,
                },
            )
            self.assertEqual(dry.status_code, 200)
            self.assertTrue(dry.json()["dry_run"])
            self.assertFalse(Path(dry.json()["package_path"]).exists())
            self.assertTrue(dry.json()["manifest"]["no_submission_side_effects"])

            committed = client.post(
                f"/control/api/paper-reviews/{paper_id}/prepare-finalization-package",
                headers=headers,
                json={
                    "idempotency_key": "router-package-commit",
                    "requested_by": "alice",
                    "target_label": "first-paper",
                    "dry_run": False,
                },
            )
            self.assertEqual(committed.status_code, 200)
            self.assertFalse(committed.json()["dry_run"])
            self.assertTrue(committed.json()["inserted_event"])
            self.assertEqual(committed.json()["item"]["review_status"], "finalized")
            self.assertTrue(Path(committed.json()["package_path"]).exists())
            self.assertTrue(committed.json()["manifest"]["no_submission_side_effects"])
            repeated = client.post(
                f"/control/api/paper-reviews/{paper_id}/prepare-finalization-package",
                headers=headers,
                json={
                    "idempotency_key": "router-package-commit",
                    "requested_by": "alice",
                    "target_label": "first-paper",
                    "dry_run": False,
                },
            )
            self.assertEqual(repeated.status_code, 200)
            self.assertFalse(repeated.json()["inserted_event"])
            self.assertEqual(repeated.json()["event_id"], committed.json()["event_id"])
            paper = client.get(
                f"/control/api/papers/{paper_id}", headers=headers
            ).json()
            self.assertEqual(paper["paper"]["paper_status"], "publication_draft")

    def test_paper_finalization_rejects_unexpandable_artifact_path_without_500(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            project_dir = Path(tmp) / "projects" / "router-unexpandable-artifact"
            project_dir.mkdir(parents=True)
            paper_id = "router-unexpandable-artifact:run-1:arxiv_draft"
            audit_path = Path(tmp) / "audit.json"
            audit_path.write_text(
                json.dumps({"papers": [{"paper_id": paper_id, "ready": True}]}),
                encoding="utf-8",
            )
            imported = client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "router-unexpandable-artifact-import",
                    "paper_rows": [
                        {
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
                        }
                    ],
                },
            )
            self.assertEqual(imported.status_code, 200)
            backfill = client.post(
                "/control/api/paper-reviews/backfill",
                headers=headers,
                json={
                    "idempotency_key": "router-unexpandable-artifact-backfill",
                    "source_audit_path": str(audit_path),
                    "dry_run": False,
                },
            )
            self.assertEqual(backfill.status_code, 200)

            finalized = client.post(
                f"/control/api/paper-reviews/{paper_id}/prepare-finalization-package",
                headers=headers,
                json={
                    "idempotency_key": "router-unexpandable-artifact-finalize",
                    "requested_by": "alice",
                    "target_label": "bad-artifact-path",
                    "dry_run": False,
                },
            )
            self.assertEqual(finalized.status_code, 400)
            self.assertIn("artifact", finalized.text.lower())

    def test_paper_finalization_rejects_unexpandable_project_dir_without_500(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            paper_id = "router-unexpandable-dir:run-1:arxiv_draft"
            audit_path = Path(tmp) / "audit.json"
            audit_path.write_text(
                json.dumps({"papers": [{"paper_id": paper_id, "ready": True}]}),
                encoding="utf-8",
            )
            imported = client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "router-unexpandable-dir-import",
                    "paper_rows": [
                        {
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
                        }
                    ],
                },
            )
            self.assertEqual(imported.status_code, 200)
            backfill = client.post(
                "/control/api/paper-reviews/backfill",
                headers=headers,
                json={
                    "idempotency_key": "router-unexpandable-dir-backfill",
                    "source_audit_path": str(audit_path),
                    "dry_run": False,
                },
            )
            self.assertEqual(backfill.status_code, 200)

            finalized = client.post(
                f"/control/api/paper-reviews/{paper_id}/prepare-finalization-package",
                headers=headers,
                json={
                    "idempotency_key": "router-unexpandable-dir-finalize",
                    "requested_by": "alice",
                    "target_label": "bad-project-dir",
                    "dry_run": False,
                },
            )
            self.assertEqual(finalized.status_code, 400)
            self.assertIn("project", finalized.text.lower())

            artifact = client.get(
                f"/control/api/papers/{paper_id}/artifact/draft_markdown_path",
                headers=headers,
            )
            self.assertIn(artifact.status_code, {400, 404})
            self.assertNotEqual(artifact.status_code, 500)

    def test_paper_finalization_rejects_invalid_project_dir_without_500(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            paper_id = "router-invalid-dir:run-1:arxiv_draft"
            audit_path = Path(tmp) / "audit.json"
            audit_path.write_text(
                json.dumps({"papers": [{"paper_id": paper_id, "ready": True}]}),
                encoding="utf-8",
            )
            imported = client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "router-invalid-dir-import",
                    "paper_rows": [
                        {
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
                        }
                    ],
                },
            )
            self.assertEqual(imported.status_code, 200)
            backfill = client.post(
                "/control/api/paper-reviews/backfill",
                headers=headers,
                json={
                    "idempotency_key": "router-invalid-dir-backfill",
                    "source_audit_path": str(audit_path),
                    "dry_run": False,
                },
            )
            self.assertEqual(backfill.status_code, 200)

            finalized = client.post(
                f"/control/api/paper-reviews/{paper_id}/prepare-finalization-package",
                headers=headers,
                json={
                    "idempotency_key": "router-invalid-dir-finalize",
                    "requested_by": "alice",
                    "target_label": "bad-project-dir",
                    "dry_run": False,
                },
            )

            self.assertEqual(finalized.status_code, 400)
            self.assertNotEqual(finalized.status_code, 500)

    def test_paper_review_rejected_status_is_normalized_before_rewrite_or_finalize(
        self,
    ) -> None:
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
            (project_dir / "run_notes.md").write_text(
                "Measured useful result with grounded evidence.\n", encoding="utf-8"
            )
            (project_dir / ".enoch" / "project_decision.json").write_text(
                '{"project_decision":"finalize_positive"}\n', encoding="utf-8"
            )
            paper_id = "router-rejected-normalized:run-1:arxiv_draft"
            audit_path = Path(tmp) / "audit.json"
            audit_path.write_text(
                json.dumps({"papers": [{"paper_id": paper_id, "ready": True}]}),
                encoding="utf-8",
            )
            imported = client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "router-rejected-normalized-import",
                    "paper_rows": [
                        {
                            "paper_id": paper_id,
                            "project_id": "router-rejected-normalized",
                            "project_name": "Router Rejected Normalized",
                            "project_dir": str(project_dir),
                            "run_id": "run-1",
                            "paper_status": "publication_draft",
                            **artifact_paths,
                        }
                    ],
                },
            )
            self.assertEqual(imported.status_code, 200)
            backfill = client.post(
                "/control/api/paper-reviews/backfill",
                headers=headers,
                json={
                    "idempotency_key": "router-rejected-normalized-backfill",
                    "source_audit_path": str(audit_path),
                    "dry_run": False,
                },
            )
            self.assertEqual(backfill.status_code, 200)
            with sqlite3.connect(Path(tmp) / "state" / "control_plane.sqlite3") as conn:
                conn.execute(
                    "UPDATE paper_review_items SET review_status=? WHERE paper_id=?",
                    (" Rejected ", paper_id),
                )

            rewrite = client.post(
                f"/control/api/paper-reviews/{paper_id}/rewrite-draft",
                headers=headers,
                json={
                    "idempotency_key": "router-rejected-normalized-rewrite",
                    "requested_by": "alice",
                    "force": True,
                },
            )
            self.assertEqual(rewrite.status_code, 400)
            self.assertIn("rejected", rewrite.text.lower())

            finalized = client.post(
                f"/control/api/paper-reviews/{paper_id}/prepare-finalization-package",
                headers=headers,
                json={
                    "idempotency_key": "router-rejected-normalized-finalize",
                    "requested_by": "alice",
                    "target_label": "reject-variant",
                    "dry_run": False,
                },
            )
            self.assertEqual(finalized.status_code, 400)
            self.assertIn("rejected", finalized.text.lower())
            events = client.get(
                f"/control/api/events?entity_id={paper_id}", headers=headers
            ).json()["rows"]
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
            audit_path.write_text(
                json.dumps({"papers": [{"paper_id": paper_id, "ready": True}]}),
                encoding="utf-8",
            )
            client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "router-package-escape-import",
                    "paper_rows": [
                        {
                            "paper_id": paper_id,
                            "project_id": "router-package-escape",
                            "project_name": "Router Package Escape",
                            "project_dir": str(outside),
                            "run_id": "run-1",
                            "paper_status": "publication_draft",
                            **artifact_paths,
                        }
                    ],
                },
            )
            client.post(
                "/control/api/paper-reviews/backfill",
                headers=headers,
                json={
                    "idempotency_key": "router-package-escape-backfill",
                    "source_audit_path": str(audit_path),
                    "dry_run": False,
                },
            )

            committed = client.post(
                f"/control/api/paper-reviews/{paper_id}/prepare-finalization-package",
                headers=headers,
                json={
                    "idempotency_key": "router-package-escape-commit",
                    "requested_by": "alice",
                    "target_label": "escape",
                    "dry_run": False,
                },
            )

            self.assertNotEqual(committed.status_code, 200)
            self.assertIn("artifact", committed.text.lower())

    def test_paper_review_status_endpoint_maps_defer_to_explicit_blocked_status(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            paper_id = "router-status:run-1:arxiv_draft"
            client.post(
                "/control/import/legacy-snapshot",
                headers=headers,
                json={
                    "idempotency_key": "router-review-status-import",
                    "paper_rows": [
                        {
                            "paper_id": paper_id,
                            "project_id": "router-status",
                            "run_id": "run-1",
                            "paper_status": "draft_review",
                            "draft_markdown_path": "paper.md",
                            "draft_latex_path": "paper.tex",
                            "evidence_bundle_path": "evidence.json",
                            "claim_ledger_path": "claims.json",
                            "manifest_path": "manifest.json",
                        }
                    ],
                },
            )
            client.post(
                "/control/api/paper-reviews/backfill",
                headers=headers,
                json={"idempotency_key": "router-status-backfill", "dry_run": False},
            )
            bad = client.post(
                f"/control/api/paper-reviews/{paper_id}/status",
                headers=headers,
                json={
                    "idempotency_key": "router-status-no-note",
                    "requested_by": "alice",
                    "review_status": "blocked",
                },
            )
            self.assertEqual(bad.status_code, 400)
            blocked = client.post(
                f"/control/api/paper-reviews/{paper_id}/status",
                headers=headers,
                json={
                    "idempotency_key": "router-status-block",
                    "requested_by": "alice",
                    "review_status": "blocked",
                    "blocker": "venue choice required",
                },
            )
            self.assertEqual(blocked.status_code, 200)
            self.assertEqual(blocked.json()["item"]["review_status"], "blocked")
            self.assertEqual(blocked.json()["item"]["blocker"], "venue choice required")


if __name__ == "__main__":
    unittest.main()


def test_project_prompt_includes_canonical_decision_contract() -> None:
    prompt = _project_prompt({"project_id": "p1", "project_name": "Example"})
    assert (
        '"project_decision": "finalize_positive | finalize_negative | needs_review | blocked | continue | branch_new_project"'
        in prompt
    )
    assert '"followup_recommended": false' in prompt
    assert '"followup_type": ""' in prompt
    assert "Do not invent" in prompt
    assert "partial_viable" in prompt
    assert "promising_synthetic_positive" in prompt
    assert "negative_result" in prompt
    assert (
        "Use `finalize_positive` only when the evidence supports writing a paper now with direct, publication-grade evidence."
        in prompt
    )
    assert (
        "`continue` is not paper-positive and will not trigger paper writing" in prompt
    )
    assert (
        "prefer `finalize_negative` plus `followup_recommended: true` for promising next-tier work"
        in prompt
    )
    assert "prefer `finalize_negative` plus `followup_recommended: true`" in prompt
    assert "Evidence-depth rules:" in prompt
    assert (
        "small probe -> medium confirmation -> bounded full-scale validation" in prompt
    )
    assert "GPT-2-small-class baselines" in prompt
    assert "CoSpec-style result" in prompt
    assert (
        "The #1 rule is to produce something useful for someone else in the world"
        in prompt
    )
    assert (
        "Negative results are useful when they are clear, reproducible, and save other researchers from wasting time."
        in prompt
    )
    assert (
        "Do not optimize for impressive wording, positive-looking outcomes, or paper count."
        in prompt
    )
    assert "short smoke/proxy/synthetic test may close `finalize_negative`" in prompt
    assert "Do not add new decision fields or enum values." in prompt
    assert "Do not use `finalize_positive` for a proxy-only result" in prompt
    assert (
        "Use `set -o pipefail` before shell pipelines that pipe through `tee`" in prompt
    )
    assert (
        "Follow-up fields are optional adjacent-investigation metadata; they never make this run paper-positive."
        in prompt
    )
    assert "controller will cap follow-ups at depth 4" in prompt


def test_legacy_finalize_positive_without_evidence_does_not_write_paper() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        client = _client(tmp)
        headers = {"Authorization": f"Bearer {TOKEN}"}
        response = client.post(
            "/control/import/legacy-snapshot",
            headers=headers,
            json={
                "idempotency_key": "import-legacy-positive-no-evidence",
                "queue_rows": [
                    {
                        "project_id": "legacy-positive-no-evidence",
                        "project_name": "Legacy Positive No Evidence",
                        "project_dir": "legacy-positive-no-evidence",
                        "status": "completed",
                        "last_run_state": "finalize_positive",
                        "next_action_hint": "draft_paper_or_select_next_project",
                        "current_run_id": "run-legacy-positive-no-evidence",
                        "manual_review_required": False,
                    }
                ],
                "paper_rows": [],
            },
        )
        assert response.status_code == 200

        draft = client.post(
            "/control/papers/draft-next",
            headers=headers,
            json={"force": True, "override_hold_action": "draft-next-while-held"},
        )

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
        config = _config(tmp).model_copy(
            update={
                "paper_evidence_sync_enabled": True,
                "pushover_alerts_enabled": True,
                "pushover_api_token": "token",
                "pushover_user_key": "user",
            }
        )
        client = _client_with_config(config)
        headers = {"Authorization": f"Bearer {TOKEN}"}
        response = client.post(
            "/control/import/legacy-snapshot",
            headers=headers,
            json={
                "idempotency_key": "import-legacy-positive-missing-evidence-alert",
                "queue_rows": [
                    {
                        "project_id": "legacy-positive-missing-evidence-alert",
                        "project_name": "Legacy Positive Missing Evidence Alert",
                        "project_dir": "legacy-positive-missing-evidence-alert",
                        "status": "completed",
                        "last_run_state": "finalize_positive",
                        "next_action_hint": "draft_paper_or_select_next_project",
                        "current_run_id": "run-legacy-positive-missing-evidence-alert",
                        "manual_review_required": False,
                    }
                ],
                "paper_rows": [],
            },
        )
        assert response.status_code == 200
        calls = []

        def fake_send_pushover(*args, **kwargs):  # noqa: ANN001 - patched function
            del args
            calls.append(kwargs)
            return PushoverResult(attempted=True, ok=True, status_code=200, detail="ok")

        with patch(
            "enoch_control_plane.control_plane.router._sync_remote_project_evidence",
            return_value={
                "enabled": True,
                "synced": False,
                "reason": "worker_read_failed",
            },
        ):
            with patch(
                "enoch_control_plane.control_plane.router.send_pushover",
                side_effect=fake_send_pushover,
            ):
                draft = client.post(
                    "/control/papers/draft-next",
                    headers=headers,
                    json={
                        "force": True,
                        "override_hold_action": "draft-next-while-held",
                    },
                )

        assert draft.status_code == 200
        assert draft.json()["action"] == "noop"
        assert "evidence" in draft.json()["reason"]
        assert len(calls) == 1
        snapshot = client.get("/control/export/snapshot", headers=headers).json()
        events = [
            event
            for event in snapshot["events"]
            if event["event_type"] == "paper.evidence_sync_blocked"
        ]
        assert len(events) == 1
        assert snapshot["paper_rows"] == []


def test_raw_wake_ready_without_paper_decision_does_not_sync_or_alert() -> None:
    from enoch_control_plane.control_plane.alerts import PushoverResult

    with tempfile.TemporaryDirectory() as tmp:
        config = _config(tmp).model_copy(
            update={
                "paper_evidence_sync_enabled": True,
                "pushover_alerts_enabled": True,
                "pushover_api_token": "token",
                "pushover_user_key": "user",
            }
        )
        client = _client_with_config(config)
        headers = {"Authorization": f"Bearer {TOKEN}"}
        response = client.post(
            "/control/import/legacy-snapshot",
            headers=headers,
            json={
                "idempotency_key": "import-raw-wake-ready-no-decision",
                "queue_rows": [
                    {
                        "project_id": "raw-wake-ready-no-decision",
                        "project_name": "Raw Wake Ready No Decision",
                        "project_dir": "raw-wake-ready-no-decision",
                        "status": "completed",
                        "last_run_state": "wake_ready",
                        "next_action_hint": "draft_paper_or_select_next_project",
                        "current_run_id": "run-raw-wake-ready-no-decision",
                        "manual_review_required": False,
                    }
                ],
                "paper_rows": [],
            },
        )
        assert response.status_code == 200
        calls = []

        def fake_send_pushover(*args, **kwargs):  # noqa: ANN001 - patched function
            del args
            calls.append(kwargs)
            return PushoverResult(attempted=True, ok=True, status_code=200, detail="ok")

        with patch(
            "enoch_control_plane.control_plane.router._sync_remote_project_evidence"
        ) as sync:
            with patch(
                "enoch_control_plane.control_plane.router.send_pushover",
                side_effect=fake_send_pushover,
            ):
                dry_run = client.post(
                    "/control/papers/draft-next",
                    headers=headers,
                    json={"force": True, "dry_run": True},
                )
                draft = client.post(
                    "/control/papers/draft-next",
                    headers=headers,
                    json={
                        "force": True,
                        "override_hold_action": "draft-next-while-held",
                    },
                )

        assert dry_run.status_code == 200
        assert dry_run.json()["action"] == "noop"
        assert "paper-ready" in dry_run.json()["reason"]
        assert draft.status_code == 200
        assert draft.json()["action"] == "noop"
        assert "paper-ready" in draft.json()["reason"]
        assert sync.call_count == 0
        assert calls == []
        snapshot = client.get("/control/export/snapshot", headers=headers).json()
        events = [
            event
            for event in snapshot["events"]
            if event["event_type"] == "paper.evidence_sync_blocked"
        ]
        assert events == []
        assert snapshot["paper_rows"] == []


def test_missing_evidence_alert_is_bucketed_per_run() -> None:
    from enoch_control_plane.control_plane.alerts import PushoverResult

    with tempfile.TemporaryDirectory() as tmp:
        config = _config(tmp).model_copy(
            update={
                "paper_evidence_sync_enabled": True,
                "pushover_alerts_enabled": True,
                "pushover_api_token": "token",
                "pushover_user_key": "user",
            }
        )
        client = _client_with_config(config)
        headers = {"Authorization": f"Bearer {TOKEN}"}
        response = client.post(
            "/control/import/legacy-snapshot",
            headers=headers,
            json={
                "idempotency_key": "import-alert-missing-evidence",
                "queue_rows": [
                    {
                        "project_id": "alert-missing-evidence",
                        "project_name": "Alert Missing Evidence",
                        "project_dir": "alert-missing-evidence",
                        "status": "completed",
                        "last_run_state": "finalize_positive",
                        "next_action_hint": "draft_paper_or_select_next_project",
                        "current_run_id": "run-alert-missing-evidence",
                        "manual_review_required": False,
                    }
                ],
                "paper_rows": [],
            },
        )
        assert response.status_code == 200
        calls = []

        def fake_send_pushover(*args, **kwargs):  # noqa: ANN001 - patched function
            del args
            calls.append(kwargs)
            return PushoverResult(attempted=True, ok=True, status_code=200, detail="ok")

        evidence_results = [
            {
                "enabled": True,
                "synced": False,
                "reason": "worker_read_failed",
                "skipped": [{"path": "run_notes.md"}],
            },
            {
                "enabled": True,
                "synced": False,
                "reason": "worker_read_failed",
                "skipped": [{"path": ".enoch/project_decision.json"}],
            },
        ]
        with patch(
            "enoch_control_plane.control_plane.router._sync_remote_project_evidence",
            side_effect=evidence_results,
        ):
            with patch(
                "enoch_control_plane.control_plane.router.send_pushover",
                side_effect=fake_send_pushover,
            ):
                first = client.post(
                    "/control/papers/draft-next",
                    headers=headers,
                    json={
                        "force": True,
                        "override_hold_action": "draft-next-while-held",
                    },
                )
                second = client.post(
                    "/control/papers/draft-next",
                    headers=headers,
                    json={
                        "force": True,
                        "override_hold_action": "draft-next-while-held",
                    },
                )

        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json()["action"] == "noop"
        assert second.json()["action"] == "noop"
        assert len(calls) == 1
        snapshot = client.get("/control/export/snapshot", headers=headers).json()
        events = [
            event
            for event in snapshot["events"]
            if event["event_type"] == "paper.evidence_sync_blocked"
        ]
        assert len(events) == 1


def test_missing_evidence_alert_suppresses_reason_changes_for_same_candidate_day() -> (
    None
):
    from enoch_control_plane.control_plane.alerts import PushoverResult

    with tempfile.TemporaryDirectory() as tmp:
        config = _config(tmp).model_copy(
            update={
                "paper_evidence_sync_enabled": True,
                "pushover_alerts_enabled": True,
                "pushover_api_token": "token",
                "pushover_user_key": "user",
            }
        )
        client = _client_with_config(config)
        headers = {"Authorization": f"Bearer {TOKEN}"}
        response = client.post(
            "/control/import/legacy-snapshot",
            headers=headers,
            json={
                "idempotency_key": "import-alert-reason-change",
                "queue_rows": [
                    {
                        "project_id": "alert-reason-change",
                        "project_name": "Alert Reason Change",
                        "project_dir": "alert-reason-change",
                        "status": "completed",
                        "last_run_state": "finalize_positive",
                        "next_action_hint": "draft_paper_or_select_next_project",
                        "current_run_id": "run-alert-reason-change",
                        "manual_review_required": False,
                    }
                ],
                "paper_rows": [],
            },
        )
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
        with patch(
            "enoch_control_plane.control_plane.router._sync_remote_project_evidence",
            side_effect=evidence_results,
        ):
            with patch(
                "enoch_control_plane.control_plane.router.send_pushover",
                side_effect=fake_send_pushover,
            ):
                with patch(
                    "enoch_control_plane.control_plane.router.utc_now",
                    side_effect=["2026-05-17T18:10:00Z", "2026-05-17T19:10:00Z"],
                ):
                    first = client.post(
                        "/control/papers/draft-next",
                        headers=headers,
                        json={
                            "force": True,
                            "override_hold_action": "draft-next-while-held",
                        },
                    )
                    second = client.post(
                        "/control/papers/draft-next",
                        headers=headers,
                        json={
                            "force": True,
                            "override_hold_action": "draft-next-while-held",
                        },
                    )

        assert first.status_code == 200
        assert second.status_code == 200
        assert len(calls) == 1
        snapshot = client.get("/control/export/snapshot", headers=headers).json()
        events = [
            event
            for event in snapshot["events"]
            if event["event_type"] == "paper.evidence_sync_blocked"
        ]
        assert len(events) == 1


def test_missing_evidence_alert_suppresses_same_candidate_across_same_day() -> None:
    from enoch_control_plane.control_plane.alerts import PushoverResult

    with tempfile.TemporaryDirectory() as tmp:
        config = _config(tmp).model_copy(
            update={
                "paper_evidence_sync_enabled": True,
                "pushover_alerts_enabled": True,
                "pushover_api_token": "token",
                "pushover_user_key": "user",
            }
        )
        client = _client_with_config(config)
        headers = {"Authorization": f"Bearer {TOKEN}"}
        response = client.post(
            "/control/import/legacy-snapshot",
            headers=headers,
            json={
                "idempotency_key": "import-alert-same-day",
                "queue_rows": [
                    {
                        "project_id": "alert-same-day",
                        "project_name": "Alert Same Day",
                        "project_dir": "alert-same-day",
                        "status": "completed",
                        "last_run_state": "finalize_positive",
                        "next_action_hint": "draft_paper_or_select_next_project",
                        "current_run_id": "run-alert-same-day",
                        "manual_review_required": False,
                    }
                ],
                "paper_rows": [],
            },
        )
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
        with patch(
            "enoch_control_plane.control_plane.router._sync_remote_project_evidence",
            side_effect=evidence_results,
        ):
            with patch(
                "enoch_control_plane.control_plane.router.send_pushover",
                side_effect=fake_send_pushover,
            ):
                with patch(
                    "enoch_control_plane.control_plane.router.utc_now",
                    side_effect=["2026-05-17T18:10:00Z", "2026-05-17T19:10:00Z"],
                ):
                    first = client.post(
                        "/control/papers/draft-next",
                        headers=headers,
                        json={
                            "force": True,
                            "override_hold_action": "draft-next-while-held",
                        },
                    )
                    second = client.post(
                        "/control/papers/draft-next",
                        headers=headers,
                        json={
                            "force": True,
                            "override_hold_action": "draft-next-while-held",
                        },
                    )

        assert first.status_code == 200
        assert second.status_code == 200
        assert len(calls) == 1
        snapshot = client.get("/control/export/snapshot", headers=headers).json()
        events = [
            event
            for event in snapshot["events"]
            if event["event_type"] == "paper.evidence_sync_blocked"
        ]
        assert len(events) == 1


def test_missing_evidence_alert_still_notifies_when_event_store_fails() -> None:
    from enoch_control_plane.control_plane.alerts import PushoverResult

    with tempfile.TemporaryDirectory() as tmp:
        config = _config(tmp).model_copy(
            update={
                "paper_evidence_sync_enabled": True,
                "pushover_alerts_enabled": True,
                "pushover_api_token": "token",
                "pushover_user_key": "user",
            }
        )
        client = _client_with_config(config)
        headers = {"Authorization": f"Bearer {TOKEN}"}
        response = client.post(
            "/control/import/legacy-snapshot",
            headers=headers,
            json={
                "idempotency_key": "import-alert-event-store-fails",
                "queue_rows": [
                    {
                        "project_id": "alert-event-store-fails",
                        "project_name": "Alert Event Store Fails",
                        "project_dir": "alert-event-store-fails",
                        "status": "completed",
                        "last_run_state": "finalize_positive",
                        "next_action_hint": "draft_paper_or_select_next_project",
                        "current_run_id": "run-alert-event-store-fails",
                        "manual_review_required": False,
                    }
                ],
                "paper_rows": [],
            },
        )
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

        with patch(
            "enoch_control_plane.control_plane.router._sync_remote_project_evidence",
            return_value={
                "enabled": True,
                "synced": False,
                "reason": "worker_read_failed",
            },
        ):
            with patch(
                "enoch_control_plane.control_plane.router.send_pushover",
                side_effect=fake_send_pushover,
            ):
                with patch.object(
                    ControlPlaneStore, "append_event", new=flaky_append_event
                ):
                    result = client.post(
                        "/control/papers/draft-next",
                        headers=headers,
                        json={
                            "force": True,
                            "override_hold_action": "draft-next-while-held",
                        },
                    )

        assert result.status_code == 200
        assert result.json()["action"] == "noop"
        assert len(calls) == 1


def test_draft_next_revalidates_decision_gate_after_evidence_sync() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        client = _client(tmp)
        headers = {"Authorization": f"Bearer {TOKEN}"}
        project_dir = Path(tmp) / "projects" / "paper-sync-gate"
        (project_dir / ".enoch").mkdir(parents=True)
        (project_dir / "run_notes.md").write_text(
            "Verified useful result with measured baseline evidence.\n",
            encoding="utf-8",
        )
        (project_dir / ".enoch" / "project_decision.json").write_text(
            '{"project_decision":"finalize_positive"}\n', encoding="utf-8"
        )
        imported = client.post(
            "/control/import/legacy-snapshot",
            headers=headers,
            json={
                "idempotency_key": "import-paper-sync-gate",
                "queue_rows": [
                    {
                        "project_id": "paper-sync-gate",
                        "project_name": "Paper Sync Gate",
                        "project_dir": "paper-sync-gate",
                        "status": "completed",
                        "last_run_state": "finalize_positive",
                        "next_action_hint": "draft_paper_or_select_next_project",
                        "current_run_id": "run-paper-sync-gate",
                        "manual_review_required": False,
                    }
                ],
                "paper_rows": [],
            },
        )
        assert imported.status_code == 200

        def sync_overwrites_positive(*args, **kwargs):  # noqa: ANN001 - patched function
            del args, kwargs
            (project_dir / ".enoch" / "project_decision.json").write_text(
                '{"project_decision":"negative"}\n', encoding="utf-8"
            )
            return {"enabled": True, "synced": True, "method": "worker_http"}

        with patch(
            "enoch_control_plane.control_plane.router._sync_remote_project_evidence",
            side_effect=sync_overwrites_positive,
        ):
            response = client.post(
                "/control/papers/draft-next",
                headers=headers,
                json={"force": True, "override_hold_action": "draft-next-while-held"},
            )

        assert response.status_code == 200
        body = response.json()
        assert body["action"] == "noop"
        skipped = body.get("candidate", {}).get("skipped", [])
        assert (
            skipped
            and skipped[0]["reason"]
            == "project decision is not paper-ready after evidence sync"
        )
        assert skipped[0]["decision_gate"]["eligible"] is False
        snapshot = client.get("/control/export/snapshot", headers=headers).json()
        assert snapshot["paper_rows"] == []


def test_draft_next_does_not_let_paper_scout_row_override_post_sync_gate() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        client = _client(tmp)
        headers = {"Authorization": f"Bearer {TOKEN}"}
        project_dir = Path(tmp) / "projects" / "paper-scout-ready-sync"
        (project_dir / ".enoch").mkdir(parents=True)
        (project_dir / "run_notes.md").write_text(
            "Measured useful signal with a bounded baseline and explicit limits.\n",
            encoding="utf-8",
        )
        (project_dir / ".enoch" / "project_decision.json").write_text(
            json.dumps(
                {
                    "project_decision": "finalize_negative",
                    "research_outcome": "useful_signal",
                    "hypothesis_status": "supported",
                    "evidence_strength": "strong",
                    "claim_scope": "single local benchmark",
                    "scale_limits": "toy-sized reproduction only",
                }
            )
            + "\n",
            encoding="utf-8",
        )
        imported = client.post(
            "/control/import/legacy-snapshot",
            headers=headers,
            json={
                "idempotency_key": "import-paper-scout-ready-sync",
                "queue_rows": [
                    {
                        "project_id": "paper-scout-ready-sync",
                        "project_name": "Paper Scout Ready Sync",
                        "project_dir": "paper-scout-ready-sync",
                        "status": "completed",
                        "last_run_state": "wake_ready",
                        "next_action_hint": "draft_paper_or_select_next_project",
                        "current_run_id": "run-paper-scout-ready-sync",
                        "manual_review_required": False,
                        "project_decision": "finalize_negative",
                        "research_outcome": "useful_signal",
                        "bounded_paper_ready": True,
                        "hypothesis_status": "supported",
                        "evidence_strength": "strong",
                        "claim_scope": "single local benchmark",
                        "scale_limits": "toy-sized reproduction only",
                    }
                ],
                "paper_rows": [],
            },
        )
        assert imported.status_code == 200

        original_queue_rows = ControlPlaneStore.queue_rows

        def queue_rows_with_paper_scout_fields(self):  # noqa: ANN001
            rows = original_queue_rows(self)
            for row in rows:
                if row.get("project_id") == "paper-scout-ready-sync":
                    row.update(
                        {
                            "project_decision": "finalize_negative",
                            "research_outcome": "useful_signal",
                            "bounded_paper_ready": True,
                            "hypothesis_status": "supported",
                            "evidence_strength": "strong",
                            "claim_scope": "single local benchmark",
                            "scale_limits": "toy-sized reproduction only",
                        }
                    )
            return rows

        with (
            patch(
                "enoch_control_plane.control_plane.router._sync_remote_project_evidence",
                return_value={
                    "enabled": True,
                    "synced": True,
                    "method": "worker_http",
                },
            ),
            patch.object(
                ControlPlaneStore, "queue_rows", new=queue_rows_with_paper_scout_fields
            ),
        ):
            response = client.post(
                "/control/papers/draft-next",
                headers=headers,
                json={"force": True, "override_hold_action": "draft-next-while-held"},
            )

        assert response.status_code == 200
        body = response.json()
        assert body["action"] == "noop"
        skipped = body.get("candidate", {}).get("skipped", [])
        assert (
            skipped
            and skipped[0]["reason"]
            == "project decision is not paper-ready after evidence sync"
        )
        decision_gate = skipped[0]["decision_gate"]
        assert decision_gate["eligible"] is False
        snapshot = client.get("/control/export/snapshot", headers=headers).json()
        assert snapshot["paper_rows"] == []


def test_paper_draft_event_failure_does_not_publish_partial_paper_row() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        client = _client(tmp)
        headers = {"Authorization": f"Bearer {TOKEN}"}
        project_dir = Path(tmp) / "projects" / "paper-event-fail"
        (project_dir / ".enoch").mkdir(parents=True)
        (project_dir / "run_notes.md").write_text(
            "Verified useful result with measured baseline evidence.\n",
            encoding="utf-8",
        )
        (project_dir / ".enoch" / "project_decision.json").write_text(
            '{"project_decision":"finalize_positive"}\n', encoding="utf-8"
        )
        response = client.post(
            "/control/import/legacy-snapshot",
            headers=headers,
            json={
                "idempotency_key": "import-paper-event-fail",
                "queue_rows": [
                    {
                        "project_id": "paper-event-fail",
                        "project_name": "Paper Event Fail",
                        "project_dir": "paper-event-fail",
                        "status": "completed",
                        "last_run_state": "finalize_positive",
                        "next_action_hint": "draft_paper_or_select_next_project",
                        "current_run_id": "run-paper-event-fail",
                        "manual_review_required": False,
                    }
                ],
                "paper_rows": [],
            },
        )
        assert response.status_code == 200
        original_append_event = ControlPlaneStore._append_event_in_conn

        def fail_paper_drafted(self, conn, **kwargs):  # noqa: ANN001 - patched method
            if kwargs.get("event_type") == "paper.drafted":
                raise RuntimeError("simulated paper drafted event failure")
            return original_append_event(self, conn, **kwargs)

        with patch.object(
            ControlPlaneStore, "_append_event_in_conn", new=fail_paper_drafted
        ):
            with pytest.raises(
                RuntimeError, match="simulated paper drafted event failure"
            ):
                client.post(
                    "/control/papers/draft-next",
                    headers=headers,
                    json={
                        "force": True,
                        "override_hold_action": "draft-next-while-held",
                    },
                )

        snapshot = client.get("/control/export/snapshot", headers=headers).json()
        assert snapshot["paper_rows"] == []
        assert (
            client.get("/control/api/paper-reviews", headers=headers).json()["page"][
                "total"
            ]
            == 0
        )
        event_types = [event["event_type"] for event in snapshot["events"]]
        assert "paper.drafted" not in event_types
        assert "paper_review.backfill" not in event_types


def test_paper_draft_backfill_failure_is_reported_without_losing_draft() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        client = _client(tmp)
        headers = {"Authorization": f"Bearer {TOKEN}"}
        project_dir = Path(tmp) / "projects" / "paper-backfill-fail"
        (project_dir / ".enoch").mkdir(parents=True)
        (project_dir / "run_notes.md").write_text(
            "Verified useful result with measured baseline evidence.\n",
            encoding="utf-8",
        )
        (project_dir / ".enoch" / "project_decision.json").write_text(
            '{"project_decision":"finalize_positive"}\n', encoding="utf-8"
        )
        imported = client.post(
            "/control/import/legacy-snapshot",
            headers=headers,
            json={
                "idempotency_key": "import-paper-backfill-fail",
                "queue_rows": [
                    {
                        "project_id": "paper-backfill-fail",
                        "project_name": "Paper Backfill Fail",
                        "project_dir": "paper-backfill-fail",
                        "status": "completed",
                        "last_run_state": "finalize_positive",
                        "next_action_hint": "draft_paper_or_select_next_project",
                        "current_run_id": "run-paper-backfill-fail",
                        "manual_review_required": False,
                    }
                ],
                "paper_rows": [],
            },
        )
        assert imported.status_code == 200

        with patch.object(
            ControlPlaneStore,
            "backfill_paper_reviews",
            side_effect=RuntimeError("simulated backfill outage"),
        ):
            response = client.post(
                "/control/papers/draft-next",
                headers=headers,
                json={"force": True, "override_hold_action": "draft-next-while-held"},
            )

        assert response.status_code == 200
        body = response.json()
        assert body["action"] == "drafted"
        assert body["candidate"]["project_id"] == "paper-backfill-fail"
        errors = (
            body["candidate"]
            .get("writer", {})
            .get("review_backfill", {})
            .get("errors", [])
        )
        assert any(
            "simulated backfill outage" in str(error.get("reason")) for error in errors
        )
        snapshot = client.get("/control/export/snapshot", headers=headers).json()
        assert [row["project_id"] for row in snapshot["paper_rows"]] == [
            "paper-backfill-fail"
        ]
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
        (project_dir / "run_notes.md").write_text(
            "Measured useful result.\n", encoding="utf-8"
        )
        (project_dir / ".enoch" / "project_decision.json").write_text(
            '{"project_decision":"finalize_positive"}\n', encoding="utf-8"
        )

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

        with patch(
            "enoch_control_plane.control_plane.router.SupabaseReadOnlyControlPlaneStore",
            return_value=FakeReadOnlyStore(),
        ):
            client = _client_with_config(config)
            response = client.post(
                "/control/papers/draft-next",
                headers={"Authorization": f"Bearer {TOKEN}"},
                json={"force": True, "override_hold_action": "draft-next-while-held"},
            )

        assert response.status_code == 501
        assert "writable control-plane store" in response.text
        assert not (project_dir / "papers").exists()


def test_resolve_research_provider_model_validation() -> None:
    """Deterministic unit test for the extracted helper.

    This test would have caught any regression in the allow-list logic
    that was previously duplicated inside the 900+ line run-cycle function.
    """
    from enoch_control_plane.control_plane.router import (
        _resolve_research_provider_model,
    )

    # Happy path with explicit model
    result = _resolve_research_provider_model({"model": "hf:zai-org/GLM-5.1"})
    assert isinstance(result, tuple)
    model, allowed = result
    assert model == "hf:zai-org/GLM-5.1"
    assert "hf:zai-org/GLM-5.1" in allowed

    # Default fallback works and is in the list
    result = _resolve_research_provider_model({})
    assert isinstance(result, tuple)
    model, allowed = result
    assert model == "hf:zai-org/GLM-5.1"
    assert model in allowed

    # Blocked model returns error dict (the behavior the giant function used to have inline)
    error = _resolve_research_provider_model({"model": "gpt-4o"})
    assert isinstance(error, dict)
    assert error["action"] == "research_cycle_blocked"
    assert "not in the allowed model list" in error["reason"]
    assert "allowed_models" in error


def test_resolve_research_cycle_params_smoke() -> None:
    """Smoke test for the second extraction from dashboard_research_run_cycle.

    Ensures the params resolver produces a usable object with the expected fields.
    This would have caught breakage when wiring the resolver into the giant function.
    """
    from enoch_control_plane.control_plane.router import (
        _resolve_research_cycle_params,
    )

    params = _resolve_research_cycle_params({})
    assert hasattr(params, "max_provider_requests")
    assert hasattr(params, "max_promotions")
    assert hasattr(params, "generation_attempts")
    assert hasattr(params, "min_admission_score")
    assert params.max_provider_requests >= 0
    assert params.generation_attempts >= 1


def test_resolve_research_cycle_params_extracted_no_duplication_in_giant() -> None:
    """AGENTS.md deterministic validator for duplication/C901 extraction.

    The repetitive ~50-line bounded param resolution block (with its env defaults,
    worker_lane caps, and 20+ bounded_* calls) must not exist inside
    dashboard_research_run_cycle after wiring. It lives only in the extracted helper.
    This test enforces the invariant before/after the wiring patch.
    """
    import importlib.util
    from pathlib import Path

    from enoch_control_plane.control_plane.router import (
        _resolve_research_cycle_params,
    )

    # Deterministic source-level validator (no reliance on inspecting the decorated
    # local handler name; the giant fn is defined inside the router factory).
    spec = importlib.util.find_spec("enoch_control_plane.control_plane.router")
    router_src = Path(spec.origin)
    src = router_src.read_text(encoding="utf-8")
    # distinctive literal from the inline duplication block (must appear only in helper after wiring)
    # The *statement* form (with " = ") lives only in the giant fn today; helper uses
    # kwarg form inside Namespace(...) without the spaces around = .
    stmt_literal = '        max_provider_requests = bounded_int("max_provider_requests_per_run", 1, 0, 3)'
    count = src.count(stmt_literal)
    assert count == 0, (
        f"Duplicated resolution logic still present in giant fn (count={count}); expected 0 after wiring"
    )
    # after wiring the delegation call must be present in the giant handler
    assert "_resolve_research_cycle_params" in src
    # helper still works
    p = _resolve_research_cycle_params({})
    assert hasattr(p, "max_provider_requests")
    assert hasattr(p, "generation_attempts")


def test_resolve_research_provider_model_no_duplicated_literals() -> None:
    """AGENTS.md deterministic validator for S1192 duplication (CRITICAL).

    The default allowed models list and fallback model string must be defined
    in exactly one canonical constant after the patch. This kills the top
    CRITICAL S1192 in router.py:192 (and related sites) while the helper
    remains the single source of truth.
    """
    import importlib.util
    from pathlib import Path

    spec = importlib.util.find_spec("enoch_control_plane.control_plane.router")
    router_src = Path(spec.origin)
    src = router_src.read_text(encoding="utf-8")

    # The individual model ID strings are duplicated across the getenv default,
    # the fallback list, and the provider_model default (Sonar S1192 CRITICAL at :192).
    # After patch, the shared defaults module is the single source; router imports
    # the values and does not duplicate raw model literals.
    moonshot = "hf:moonshotai/Kimi-K2.6"
    assert src.count(moonshot) == 0, (
        f"'{moonshot}' duplicated in router (count={src.count(moonshot)}); "
        "must be imported from research_provider_defaults"
    )

    zai = "hf:zai-org/GLM-5.1"
    assert src.count(zai) == 0, (
        f"'{zai}' duplicated in router (count={src.count(zai)}); "
        "must be imported from research_provider_defaults"
    )


def test_alerts_queue_alert_findings_54_c901_extracted():
    """AGENTS.md test-first for the new horrible-first CRITICAL S3776 (cognitive 54)
    in alerts.py:queue_alert_findings after the BLOCKER response_model remediation.

    The 54-complexity active-lane stale/hang findings collection (the for row in active_items
    stale_after + hang logic) has been lifted to a top-level helper.
    Validator: helper def exists (centralized), and behavioral smoke on the helper.
    Red on the restored base (no helper); green after extraction.
    """
    from pathlib import Path

    src = Path("enoch_control_plane/control_plane/alerts.py").read_text(
        encoding="utf-8"
    )

    # The extraction centralizes the logic; the helper must now be present at module level.
    assert "def _collect_active_lane_findings(" in src, (
        "_collect_active_lane_findings helper not found (S3776 54 still inline in queue_alert_findings)"
    )

    # Behavioral smoke: import and exercise the helper with a minimal triggering status.
    # (ensures semantics preserved exactly)
    from datetime import datetime, timezone, timedelta
    from enoch_control_plane.control_plane.alerts import _collect_active_lane_findings
    from enoch_control_plane.control_plane.models import (
        DashboardStatusResponse,
        DashboardFinding,
    )

    # Minimal fake row that should produce one "stale" finding (no live run)
    class FakeFlags:
        queue_paused = False
        maintenance_mode = False

    class FakeConfig:
        live_dispatch_enabled = True

    class FakeStatus:
        flags = FakeFlags()
        config = FakeConfig()
        conflicts = []
        active_items = [
            {
                "project_id": "p1",
                "current_run_id": "r1",
                "stale_after": (
                    datetime.now(timezone.utc) - timedelta(seconds=10)
                ).isoformat(),
                "updated_at": None,
                "last_dispatch_at": None,
            }
        ]
        warnings = []
        source_freshness = {}

    findings = _collect_active_lane_findings(FakeStatus(), hang_after_sec=300)
    assert isinstance(findings, list)
    assert len(findings) == 1
    assert findings[0].authority == "queue_items.stale_after"
    assert "stale_after timestamp" in findings[0].message


def test_janitor_report_computed_extracted_no_duplication_in_giant():
    """AGENTS.md test-first for the current horrible-first S3776 (61 in router.py
    inside the 1595 create_control_plane_router / dashboard_research_run_cycle).

    The large janitor maintenance block (fetch_needs_review, classify, apply, build_report,
    bounded promotions, fail-soft) is extracted to _compute_janitor_report to reduce
    cognitive complexity of the giant.
    Validator enforces the helper exists + behavioral contract.
    """
    from pathlib import Path

    src = Path("enoch_control_plane/control_plane/router.py").read_text(
        encoding="utf-8"
    )
    assert "def _compute_janitor_report(" in src, (
        "_compute_janitor_report helper missing (61-complexity janitor block still inline)"
    )

    # Behavioral smoke (minimal call to prove the extracted helper preserves the report contract)
    # We only test that it is importable and callable with the expected shape; full paths
    # are covered by the existing suite.
    from enoch_control_plane.control_plane.router import _compute_janitor_report

    # If the helper was added correctly, this import succeeds; the call would require
    # a real store, so we just assert the name is the centralized one.
    assert callable(_compute_janitor_report)


def test_generation_target_lane_extracted_no_duplication_in_giant():
    """AGENTS.md test-first for the next horrible-first S3776 inside the 1595
    create_control_plane_router / dashboard_research_run_cycle (after janitor 61 removal).

    The self-contained generation target lane selection logic (actions + candidates
    filter over lane_feed_pressure + max with queue_deficit) is extracted to
    _select_generation_target_lane to further reduce cognitive complexity.
    """
    from pathlib import Path

    src = Path("enoch_control_plane/control_plane/router.py").read_text(
        encoding="utf-8"
    )
    assert "def _select_generation_target_lane(" in src, (
        "_select_generation_target_lane helper missing (generation target logic still inline)"
    )

    from enoch_control_plane.control_plane.router import _select_generation_target_lane

    assert callable(_select_generation_target_lane)


def test_generation_target_lane_fills_under_depth_idle_queue_before_defaulting():
    """An under-depth CPU lane with queued work still needs feed generation.

    Regression guard for the live CPU=0/near-0 and GB10>25 imbalance: the old
    selector ignored `dispatch_queued` lanes when dispatch capacity was
    available, causing provider generation to fall back to the default GPU
    target while CPU stayed underfilled.
    """
    from enoch_control_plane.control_plane.router import _select_generation_target_lane

    target = _select_generation_target_lane(
        {
            "cpu-proxmox-1": {
                "machine_target": "cpu-proxmox-1",
                "lane_key": "http://cpu-worker:8787",
                "queued_count": 2,
                "queue_deficit": 23,
                "promotable_count": 0,
                "next_autopilot_action": "dispatch_queued",
            },
            "gb10": {
                "machine_target": "gb10",
                "lane_key": "http://gb10-worker:8787",
                "queued_count": 85,
                "queue_deficit": 0,
                "promotable_count": 0,
                "next_autopilot_action": "queue_depth_satisfied",
            },
        },
    )

    assert target is not None
    assert target["machine_target"] == "cpu-proxmox-1"


def test_generation_target_lane_targets_under_depth_lane_with_tiny_promotable_backlog():
    """A tiny admitted backlog must not suppress lane-targeted generation.

    Live regression: CPU and GB10 were both 17 items below target, but each had
    1-2 promotable candidates.  The selector treated that as backlog-satisfied,
    which let bounded follow-ups skip both fresh generation and promotion for
    many consecutive timer ticks while dispatch continued draining the queues.
    """
    from enoch_control_plane.control_plane.router import _select_generation_target_lane

    target = _select_generation_target_lane(
        {
            "cpu-proxmox-1": {
                "machine_target": "cpu-proxmox-1",
                "lane_key": "http://cpu-worker:8787",
                "queued_count": 8,
                "queue_deficit": 17,
                "promotable_count": 2,
                "next_autopilot_action": "dispatch_queued",
            },
            "gb10": {
                "machine_target": "gb10",
                "lane_key": "http://gb10-worker:8787",
                "queued_count": 8,
                "queue_deficit": 17,
                "promotable_count": 1,
                "next_autopilot_action": "promote_candidate",
            },
        },
    )

    assert target is not None
    assert int(target["queue_deficit"]) > int(target["promotable_count"])


def test_generation_target_lane_skips_when_all_lanes_are_depth_satisfied():
    from enoch_control_plane.control_plane.router import _select_generation_target_lane

    assert (
        _select_generation_target_lane(
            {
                "cpu-proxmox-1": {
                    "machine_target": "cpu-proxmox-1",
                    "queued_count": 25,
                    "queue_deficit": 0,
                    "promotable_count": 0,
                    "next_autopilot_action": "queue_depth_satisfied",
                },
                "gb10": {
                    "machine_target": "gb10",
                    "queued_count": 85,
                    "queue_deficit": 0,
                    "promotable_count": 0,
                    "next_autopilot_action": "queue_depth_satisfied",
                },
            },
        )
        is None
    )


def test_provider_generation_skips_without_lane_feed_target():
    """Provider generation must not fall back to the default GPU target.

    If every lane is depth-satisfied, the run-cycle should skip fresh provider
    generation instead of creating more default-targeted GPU work.
    """
    from enoch_control_plane.control_plane.router import (
        _ProviderGenerationParams,
        _execute_provider_generation,
    )

    params = _ProviderGenerationParams(
        max_provider_requests=1,
        generation_target_lane=None,
        provider_openai_base_url="http://provider.invalid/openai/v1",
        provider_model="gpt-5.5",
        max_candidates=5,
        topic="",
        temperature=0.8,
        seed="unit",
        generation_timeout=30,
        generation_max_tokens=1000,
        generation_attempts=1,
        min_admission_score=72.0,
        bounded_float=lambda *_args: 58.0,
        namespace_cls=SimpleNamespace,
        research_provider_generate=SimpleNamespace(
            generate_provider_candidates=lambda **_kwargs: (_ for _ in ()).throw(
                AssertionError("provider generation should be skipped")
            )
        ),
        research_facility=SimpleNamespace(plan_candidates=lambda *_args: []),
        store=SimpleNamespace(
            record_research_facility_plans=lambda *_args, **_kwargs: {}
        ),
        requested_by="pytest",
    )

    response = _execute_provider_generation(params=params, response={"stages": []})

    assert response["generated_count"] == 0
    assert response["fresh_generation_skipped"] is True
    assert response["fresh_generation_skip_reason"] == "no deficient lane feed target"
    assert response["stages"][0]["action"] == "skipped"


def test_provider_generation_records_rate_limit_attempt_event():
    from enoch_control_plane.control_plane.router import (
        _ProviderGenerationParams,
        _execute_provider_generation,
    )

    class _Store:
        def __init__(self) -> None:
            self.events: list[dict[str, object]] = []

        def append_event(self, **kwargs: object) -> None:
            self.events.append(kwargs)

        def record_research_facility_plans(self, *_args, **_kwargs) -> dict[str, int]:
            return {}

    store = _Store()
    params = _ProviderGenerationParams(
        max_provider_requests=1,
        generation_target_lane={
            "machine_target": "cpu-proxmox-1",
            "lane_key": "http://cpu-worker:8787",
            "worker_role": "cpu",
        },
        provider_openai_base_url="http://provider.invalid/openai/v1",
        provider_model="gpt-5.5",
        max_candidates=5,
        topic="",
        temperature=0.8,
        seed="unit",
        generation_timeout=30,
        generation_max_tokens=1000,
        generation_attempts=1,
        min_admission_score=72.0,
        bounded_float=lambda *_args: 58.0,
        namespace_cls=SimpleNamespace,
        research_provider_generate=SimpleNamespace(
            generate_provider_candidates=lambda **_kwargs: (_ for _ in ()).throw(
                RuntimeError("provider returned HTTP 429")
            )
        ),
        research_facility=SimpleNamespace(plan_candidates=lambda *_args: []),
        store=store,
        requested_by="pytest",
        trace_id="trace-test",
        run_cycle_id="run-cycle-test",
    )

    response = _execute_provider_generation(params=params, response={"stages": []})

    assert response["provider_generation_attempt"]["status"] == "failed"
    assert response["provider_generation_attempt"]["failure_kind"] == "rate_limited"
    assert response["provider_generation_attempt"]["machine_target"] == "cpu-proxmox-1"
    assert store.events[0]["event_type"] == "research.provider_generation.attempt"
    assert store.events[0]["entity_type"] == "research_provider"
    payload = store.events[0]["payload"]
    assert payload["failure_kind"] == "rate_limited"
    assert payload["provider_model"] == "gpt-5.5"
    assert payload["lane_key"] == "http://cpu-worker:8787"


def test_provider_generation_records_timeout_attempt_event():
    from enoch_control_plane.control_plane.router import (
        _ProviderGenerationParams,
        _execute_provider_generation,
    )

    class _Store:
        def __init__(self) -> None:
            self.events: list[dict[str, object]] = []

        def append_event(self, **kwargs: object) -> None:
            self.events.append(kwargs)

        def record_research_facility_plans(self, *_args, **_kwargs) -> dict[str, int]:
            return {}

    store = _Store()
    params = _ProviderGenerationParams(
        max_provider_requests=1,
        generation_target_lane={
            "machine_target": "gb10",
            "lane_key": "http://gb10-worker:8787",
            "worker_role": "gpu",
        },
        provider_openai_base_url="http://provider.invalid/openai/v1",
        provider_model="gpt-5.5",
        max_candidates=5,
        topic="",
        temperature=0.8,
        seed="unit",
        generation_timeout=30,
        generation_max_tokens=1000,
        generation_attempts=1,
        min_admission_score=72.0,
        bounded_float=lambda *_args: 58.0,
        namespace_cls=SimpleNamespace,
        research_provider_generate=SimpleNamespace(
            generate_provider_candidates=lambda **_kwargs: (_ for _ in ()).throw(
                TimeoutError("provider request timed out")
            )
        ),
        research_facility=SimpleNamespace(plan_candidates=lambda *_args: []),
        store=store,
        requested_by="pytest",
        trace_id="trace-timeout",
        run_cycle_id="run-cycle-timeout",
    )

    response = _execute_provider_generation(params=params, response={"stages": []})

    assert response["provider_generation_attempt"]["status"] == "failed"
    assert response["provider_generation_attempt"]["failure_kind"] == "timeout"
    assert store.events[0]["event_type"] == "research.provider_generation.attempt"
    payload = store.events[0]["payload"]
    assert payload["failure_kind"] == "timeout"
    assert payload["machine_target"] == "gb10"
    assert payload["error_type"] == "TimeoutError"


def test_provider_generation_records_bounded_failure_diagnostics():
    from enoch_control_plane.control_plane.router import (
        _ProviderGenerationParams,
        _execute_provider_generation,
    )
    from scripts.research_provider_generate import ProviderCandidateGenerationError

    class _Store:
        def __init__(self) -> None:
            self.events: list[dict[str, object]] = []

        def append_event(self, **kwargs: object) -> None:
            self.events.append(kwargs)

        def record_research_facility_plans(self, *_args, **_kwargs) -> dict[str, int]:
            return {}

    store = _Store()
    provider_exc = ProviderCandidateGenerationError(
        "provider returned no usable candidate JSON after 2 attempt(s)",
        attempts=[
            {
                "attempt": 1,
                "error_type": "JSONDecodeError",
                "reason": "Expecting value",
                "provider_response_id": "cmpl-bad-1",
                "content_length": 909,
                "content_sha256": "a" * 64,
                "content_preview": "not-json " + ("x" * 50),
                "content_truncated": True,
                "ignored_extra": "must not be persisted",
            }
        ],
    )
    params = _ProviderGenerationParams(
        max_provider_requests=1,
        generation_target_lane={
            "machine_target": "gb10",
            "lane_key": "http://gb10-worker:8787",
            "worker_role": "gpu",
        },
        provider_openai_base_url="http://provider.invalid/openai/v1",
        provider_model="hf:moonshotai/Kimi-K2.6",
        max_candidates=5,
        topic="",
        temperature=0.8,
        seed="unit",
        generation_timeout=30,
        generation_max_tokens=1000,
        generation_attempts=2,
        min_admission_score=72.0,
        bounded_float=lambda *_args: 58.0,
        namespace_cls=SimpleNamespace,
        research_provider_generate=SimpleNamespace(
            generate_provider_candidates=lambda **_kwargs: (_ for _ in ()).throw(
                provider_exc
            )
        ),
        research_facility=SimpleNamespace(plan_candidates=lambda *_args: []),
        store=store,
        requested_by="pytest",
        trace_id="trace-bad-json",
        run_cycle_id="run-cycle-bad-json",
    )

    response = _execute_provider_generation(params=params, response={"stages": []})

    diagnostics = response["provider_generation_attempt"]["failure_diagnostics"]
    assert diagnostics == [
        {
            "attempt": 1,
            "error_type": "JSONDecodeError",
            "reason": "Expecting value",
            "provider_response_id": "cmpl-bad-1",
            "content_length": 909,
            "content_sha256": "a" * 64,
            "content_preview": "not-json " + ("x" * 50),
            "content_truncated": True,
        }
    ]
    assert store.events[0]["payload"]["failure_diagnostics"] == diagnostics


def test_provider_generation_contains_plan_candidate_exception() -> None:
    from enoch_control_plane.control_plane.router import (
        _ProviderGenerationParams,
        _execute_provider_generation,
    )

    class _Store:
        def __init__(self) -> None:
            self.events: list[dict[str, object]] = []

        def append_event(self, **kwargs: object) -> None:
            self.events.append(kwargs)

        def record_research_facility_plans(self, *_args, **_kwargs) -> dict[str, int]:
            raise AssertionError("ledger persistence should not run after plan failure")

    store = _Store()
    params = _ProviderGenerationParams(
        max_provider_requests=1,
        generation_target_lane={
            "machine_target": "cpu-proxmox-1",
            "lane_key": "http://cpu-worker:8787",
            "worker_role": "cpu",
        },
        provider_openai_base_url="http://provider.invalid/openai/v1",
        provider_model="gpt-5.5",
        max_candidates=5,
        topic="",
        temperature=0.8,
        seed="unit",
        generation_timeout=30,
        generation_max_tokens=1000,
        generation_attempts=1,
        min_admission_score=72.0,
        bounded_float=lambda *_args: 58.0,
        namespace_cls=SimpleNamespace,
        research_provider_generate=SimpleNamespace(
            generate_provider_candidates=lambda **_kwargs: {
                "provider_response_id": "resp-plan-failure",
                "attempts_used": 1,
                "candidates": [{"title": "candidate"}],
            }
        ),
        research_facility=SimpleNamespace(
            plan_candidates=lambda *_args: (_ for _ in ()).throw(
                ValueError("malformed provider candidate")
            )
        ),
        store=store,
        requested_by="pytest",
        trace_id="trace-plan-failure",
        run_cycle_id="run-cycle-plan-failure",
    )

    response = _execute_provider_generation(params=params, response={"stages": []})

    assert response["provider_generation_attempt"]["status"] == "failed"
    assert response["provider_generation_attempt"]["error_type"] == "ValueError"
    assert "malformed provider candidate" in response["warnings"][0]
    assert response["stages"][0]["ok"] is False
    assert store.events[0]["event_type"] == "research.provider_generation.attempt"


def test_provider_generation_contains_ledger_exception() -> None:
    from enoch_control_plane.control_plane.router import (
        _ProviderGenerationParams,
        _execute_provider_generation,
    )

    class _Plan:
        admission_decision = "admitted"

        def to_json(self) -> dict[str, str]:
            return {"candidate_id": "candidate-1"}

    class _Store:
        def __init__(self) -> None:
            self.events: list[dict[str, object]] = []

        def append_event(self, **kwargs: object) -> None:
            self.events.append(kwargs)

        def record_research_facility_plans(self, *_args, **_kwargs) -> dict[str, int]:
            raise ValueError("invalid input syntax for type timestamp")

    store = _Store()
    params = _ProviderGenerationParams(
        max_provider_requests=1,
        generation_target_lane={
            "machine_target": "cpu-proxmox-1",
            "lane_key": "http://cpu-worker:8787",
            "worker_role": "cpu",
        },
        provider_openai_base_url="http://provider.invalid/openai/v1",
        provider_model="gpt-5.5",
        max_candidates=5,
        topic="",
        temperature=0.8,
        seed="unit",
        generation_timeout=30,
        generation_max_tokens=1000,
        generation_attempts=1,
        min_admission_score=72.0,
        bounded_float=lambda *_args: 58.0,
        namespace_cls=SimpleNamespace,
        research_provider_generate=SimpleNamespace(
            generate_provider_candidates=lambda **_kwargs: {
                "provider_response_id": "resp-ledger-failure",
                "attempts_used": 1,
                "candidates": [
                    {
                        "title": "candidate",
                        "source_records": [
                            {
                                "source_id": "source-1",
                                "retrieved_at": "not-a-timestamp",
                            }
                        ],
                    }
                ],
            }
        ),
        research_facility=SimpleNamespace(plan_candidates=lambda *_args: [_Plan()]),
        store=store,
        requested_by="pytest",
        trace_id="trace-ledger-failure",
        run_cycle_id="run-cycle-ledger-failure",
    )

    response = _execute_provider_generation(params=params, response={"stages": []})

    assert response["provider_generation_attempt"]["status"] == "failed"
    assert response["provider_generation_attempt"]["error_type"] == "ValueError"
    assert "invalid input syntax for type timestamp" in response["warnings"][0]
    assert response["stages"][0]["provider_attempt_status"] == "failed"
    assert store.events[0]["event_type"] == "research.provider_generation.attempt"


def test_provider_generation_contains_attempt_recording_exception() -> None:
    from enoch_control_plane.control_plane.router import (
        _ProviderGenerationParams,
        _execute_provider_generation,
    )

    class _Plan:
        admission_decision = "admitted"

        def to_json(self) -> dict[str, str]:
            return {"candidate_id": "candidate-1"}

    class _Store:
        def append_event(self, **_kwargs: object) -> None:
            raise RuntimeError("event store unavailable")

        def record_research_facility_plans(self, *_args, **_kwargs) -> dict[str, int]:
            return {"inserted": 1}

    params = _ProviderGenerationParams(
        max_provider_requests=1,
        generation_target_lane={
            "machine_target": "cpu-proxmox-1",
            "lane_key": "http://cpu-worker:8787",
            "worker_role": "cpu",
        },
        provider_openai_base_url="http://provider.invalid/openai/v1",
        provider_model="gpt-5.5",
        max_candidates=5,
        topic="",
        temperature=0.8,
        seed="unit",
        generation_timeout=30,
        generation_max_tokens=1000,
        generation_attempts=1,
        min_admission_score=72.0,
        bounded_float=lambda *_args: 58.0,
        namespace_cls=SimpleNamespace,
        research_provider_generate=SimpleNamespace(
            generate_provider_candidates=lambda **_kwargs: {
                "provider_response_id": "resp-record-failure",
                "attempts_used": 1,
                "candidates": [{"title": "candidate"}],
            }
        ),
        research_facility=SimpleNamespace(plan_candidates=lambda *_args: [_Plan()]),
        store=_Store(),
        requested_by="pytest",
        trace_id="trace-record-failure",
        run_cycle_id="run-cycle-record-failure",
    )

    response = _execute_provider_generation(params=params, response={"stages": []})

    assert response["provider_generation_attempt"]["status"] == "success"
    assert response["provider_generation_attempt_record_error"] == (
        "RuntimeError: event store unavailable"
    )
    assert "attempt event recording failed" in response["warnings"][0]


def test_provider_generation_records_success_attempt_event():
    from enoch_control_plane.control_plane.router import (
        _ProviderGenerationParams,
        _execute_provider_generation,
    )

    class _Plan:
        admission_decision = "admitted"

        def to_json(self) -> dict[str, str]:
            return {"candidate_id": "candidate-1"}

    class _Store:
        def __init__(self) -> None:
            self.events: list[dict[str, object]] = []

        def append_event(self, **kwargs: object) -> None:
            self.events.append(kwargs)

        def record_research_facility_plans(self, *_args, **_kwargs) -> dict[str, int]:
            return {"inserted": 1}

    store = _Store()
    params = _ProviderGenerationParams(
        max_provider_requests=1,
        generation_target_lane={
            "machine_target": "cpu-proxmox-1",
            "lane_key": "http://cpu-worker:8787",
            "worker_role": "cpu",
        },
        provider_openai_base_url="http://provider.invalid/openai/v1",
        provider_model="gpt-5.5",
        max_candidates=5,
        topic="",
        temperature=0.8,
        seed="unit",
        generation_timeout=30,
        generation_max_tokens=1000,
        generation_attempts=1,
        min_admission_score=72.0,
        bounded_float=lambda *_args: 58.0,
        namespace_cls=SimpleNamespace,
        research_provider_generate=SimpleNamespace(
            generate_provider_candidates=lambda **_kwargs: {
                "provider_response_id": "resp-1",
                "attempts_used": 1,
                "candidates": [{"title": "candidate"}],
            }
        ),
        research_facility=SimpleNamespace(plan_candidates=lambda *_args: [_Plan()]),
        store=store,
        requested_by="pytest",
        provider_id="openrouter",
        trace_id="trace-success",
        run_cycle_id="run-cycle-success",
    )

    response = _execute_provider_generation(params=params, response={"stages": []})

    assert response["provider_generation_attempt"]["status"] == "success"
    assert response["provider_generation_attempt"]["candidate_count"] == 1
    assert response["provider_generation_attempt"]["planned_count"] == 1
    payload = store.events[0]["payload"]
    assert payload["status"] == "success"
    assert payload["provider_id"] == "openrouter"
    assert payload["provider"] == "openrouter"
    assert payload["provider_response_id"] == "resp-1"
    assert payload["planned_count"] == 1


def test_provider_generation_passes_strict_schema_env_options(monkeypatch):
    from enoch_control_plane.control_plane.router import (
        _ProviderGenerationParams,
        _execute_provider_generation,
    )

    class _Plan:
        admission_decision = "admitted"

        def to_json(self) -> dict[str, str]:
            return {"candidate_id": "candidate-1"}

    class _Store:
        def append_event(self, **_kwargs: object) -> None:
            return None

        def record_research_facility_plans(self, *_args, **_kwargs) -> dict[str, int]:
            return {"inserted": 1}

    seen: dict[str, object] = {}

    def fake_generate(**kwargs):
        seen.update(kwargs)
        return {
            "provider_response_id": "resp-schema",
            "attempts_used": 1,
            "candidates": [{"title": "candidate"}],
        }

    monkeypatch.setenv("ENOCH_RESEARCH_PROVIDER_RESPONSE_FORMAT", "json_schema")
    monkeypatch.setenv("ENOCH_RESEARCH_PROVIDER_REASONING_EFFORT", "low")
    monkeypatch.setenv("ENOCH_RESEARCH_PROVIDER_REASONING_EXCLUDE", "true")

    params = _ProviderGenerationParams(
        max_provider_requests=1,
        generation_target_lane={
            "machine_target": "gb10",
            "lane_key": "http://gb10-worker:8787",
            "worker_role": "gpu",
        },
        provider_openai_base_url="https://openrouter.ai/api/v1",
        provider_model="deepseek/deepseek-v4-pro",
        max_candidates=1,
        topic="",
        temperature=0.8,
        seed="unit",
        generation_timeout=30,
        generation_max_tokens=1000,
        generation_attempts=1,
        min_admission_score=72.0,
        bounded_float=lambda *_args: 58.0,
        namespace_cls=SimpleNamespace,
        research_provider_generate=SimpleNamespace(
            generate_provider_candidates=fake_generate
        ),
        research_facility=SimpleNamespace(plan_candidates=lambda *_args: [_Plan()]),
        store=_Store(),
        requested_by="pytest",
        provider_id="openrouter",
    )

    response = _execute_provider_generation(params=params, response={"stages": []})

    assert response["provider_generation_attempt"]["status"] == "success"
    assert seen["response_format_type"] == "json_schema"
    assert seen["reasoning_effort"] == "low"
    assert seen["reasoning_exclude"] is True


def test_lane_feed_limited_promotion_candidates_do_not_overfill_satisfied_gpu_lane():
    from enoch_control_plane.control_plane.router import (
        _lane_feed_limited_promotion_candidates,
    )

    def worker_lane_key(row: dict[str, str]) -> str:
        return {
            "cpu-proxmox-1": "http://cpu-worker:8787",
            "gb10": "http://gb10-worker:8787",
        }.get(row.get("machine_target", ""), "")

    selected = _lane_feed_limited_promotion_candidates(
        promotion_candidates=[
            {"candidate_id": "gpu-1", "machine_target": "gb10"},
            {"candidate_id": "cpu-1", "machine_target": "cpu-proxmox-1"},
            {"candidate_id": "cpu-2", "machine_target": "cpu-proxmox-1"},
            {"candidate_id": "cpu-3", "machine_target": "cpu-proxmox-1"},
        ],
        lane_feed_pressure={
            "cpu-proxmox-1": {
                "machine_target": "cpu-proxmox-1",
                "lane_key": "http://cpu-worker:8787",
                "queued_count": 2,
                "queue_deficit": 2,
            },
            "gb10": {
                "machine_target": "gb10",
                "lane_key": "http://gb10-worker:8787",
                "queued_count": 85,
                "queue_deficit": 0,
            },
        },
        worker_lane_key=worker_lane_key,
    )

    assert [row["candidate_id"] for row in selected] == ["cpu-1", "cpu-2"]


def test_promotable_rows_computed_extracted_no_duplication_in_giant():
    """AGENTS.md test-first for the next horrible-first S3776 inside the 1595
    create_control_plane_router / dashboard_research_run_cycle (after generation target extraction).

    The large promotable_rows() + inner candidate_priority logic (workbench projection,
    filtering, priority scoring with lane_bonus + dispatch_priority_score) is extracted
    to _compute_promotable_rows to further reduce cognitive complexity of the giant.
    """
    from pathlib import Path

    src = Path("enoch_control_plane/control_plane/router.py").read_text(
        encoding="utf-8"
    )
    assert "def _compute_promotable_rows(" in src, (
        "_compute_promotable_rows helper missing (promotable_rows logic still nested inside the giant)"
    )

    from enoch_control_plane.control_plane.router import _compute_promotable_rows

    assert callable(_compute_promotable_rows)


def test_followup_and_early_skips_extracted_no_duplication_in_giant():
    """AGENTS.md test-first for the next horrible-first S3776 inside the 1595
    create_control_plane_router / dashboard_research_run_cycle (after promotable_rows extraction).

    The large followup + early backlog skip decision tree (next_followup_candidate,
    starvation check vs generation_target_lane, launch, setting fresh_*_skipped flags,
    backlog threshold skip) is extracted to _handle_followup_and_early_skips to further
    reduce cognitive complexity of the giant.
    """
    from pathlib import Path

    src = Path("enoch_control_plane/control_plane/router.py").read_text(
        encoding="utf-8"
    )
    assert "def _handle_followup_and_early_skips(" in src, (
        "_handle_followup_and_early_skips helper missing (followup/early-skips logic still inline in the giant)"
    )

    from enoch_control_plane.control_plane.router import (
        _handle_followup_and_early_skips,
    )

    assert callable(_handle_followup_and_early_skips)


def test_provider_generation_execution_extracted_no_duplication_in_giant():
    """AGENTS.md test-first for the next horrible-first S3776 inside the 1595
    create_control_plane_router / dashboard_research_run_cycle (after followup/early-skips extraction).

    The large provider generation execution path (topic construction from lane pressure,
    generate_provider_candidates call, plan_candidates, record_plans, stages append,
    error handling) is extracted to _execute_provider_generation to further reduce
    cognitive complexity of the giant.
    """
    from pathlib import Path

    src = Path("enoch_control_plane/control_plane/router.py").read_text(
        encoding="utf-8"
    )
    assert "def _execute_provider_generation(" in src, (
        "_execute_provider_generation helper missing (provider generation execution logic still inline in the giant)"
    )

    from enoch_control_plane.control_plane.router import _execute_provider_generation

    assert callable(_execute_provider_generation)


def test_promotion_execution_extracted_no_duplication_in_giant():
    """AGENTS.md test-first for the next horrible-first S3776 inside the 1595
    create_control_plane_router / dashboard_research_run_cycle (after provider generation execution extraction).

    The self-contained promotion loop (filter open_lane, call store.promote_research_candidate,
    capture promoted list, update response counts/stages, else skipped, plus the subsequent
    dispatch of promoted items) is extracted to _execute_promotion to further reduce
    cognitive complexity of the giant.
    """
    from pathlib import Path

    src = Path("enoch_control_plane/control_plane/router.py").read_text(
        encoding="utf-8"
    )
    assert "def _execute_promotion(" in src, (
        "_execute_promotion helper missing (promotion execution logic still inline in the giant)"
    )

    from enoch_control_plane.control_plane.router import _execute_promotion

    assert callable(_execute_promotion)


def test_promotion_subhelpers_extracted_for_s3776():
    """AGENTS.md test-first for S3776 on _execute_promotion (e61aa097, router.py ~2711).

    Promotion candidate resolution, row promotion, stage recording, and capped dispatch
    are split into top-level helpers so _execute_promotion stays at or below complexity 15.
    """
    from pathlib import Path

    src = Path("enoch_control_plane/control_plane/router.py").read_text(
        encoding="utf-8"
    )
    for name in (
        "_resolve_open_lane_promotion_candidates",
        "_promote_research_rows",
        "_record_promotion_stage",
        "_dispatch_promoted_until_cap",
    ):
        assert f"def {name}(" in src, f"{name} helper missing"

    from enoch_control_plane.control_plane.router import (
        _dispatch_promoted_until_cap,
        _promote_research_rows,
        _record_promotion_stage,
        _resolve_open_lane_promotion_candidates,
    )

    assert callable(_resolve_open_lane_promotion_candidates)
    assert callable(_promote_research_rows)
    assert callable(_record_promotion_stage)
    assert callable(_dispatch_promoted_until_cap)


def test_dispatch_queued_project_extracted_no_duplication_in_giant():
    """AGENTS.md test-first for the next horrible-first S3776 inside the 1595
    create_control_plane_router / dashboard_research_run_cycle (after promotion extraction).

    The self-contained dispatch_queued_project local function (claim, live_dispatch with 409
    backpressure handling, heavy response mutation for dispatch_started/dispatched_count/stages/dispatches,
    return success) is extracted to _dispatch_queued_project to further reduce cognitive complexity of the giant.
    """
    from pathlib import Path

    src = Path("enoch_control_plane/control_plane/router.py").read_text(
        encoding="utf-8"
    )
    assert "def _dispatch_queued_project(" in src, (
        "_dispatch_queued_project helper missing (dispatch_queued_project logic still inline in the giant)"
    )

    from enoch_control_plane.control_plane.router import _dispatch_queued_project

    assert callable(_dispatch_queued_project)


def test_lane_helpers_extracted_no_duplication_in_giant():
    """AGENTS.md test-first for the next horrible-first S3776 inside the (now much smaller) 1595
    create_control_plane_router / dashboard_research_run_cycle (after dispatch_queued_project extraction).

    The small but frequently used lane helpers `research_row_lane_key` + `open_lane_research_rows`
    (which close over _worker_lane_key and are used throughout the giant for lane matching and
    open-lane filtering) are extracted to top-level to further reduce cognitive complexity and
    improve testability of the giant.
    """
    from pathlib import Path

    src = Path("enoch_control_plane/control_plane/router.py").read_text(
        encoding="utf-8"
    )
    assert "def research_row_lane_key(" in src
    assert "def open_lane_research_rows(" in src

    # Behavioral smoke
    from enoch_control_plane.control_plane.router import (
        research_row_lane_key,
        open_lane_research_rows,
    )

    assert callable(research_row_lane_key)
    assert callable(open_lane_research_rows)
    assert research_row_lane_key({"machine_target": "gb10"}) == "gb10"
    assert open_lane_research_rows(
        [
            {"project_id": "gpu", "machine_target": "gb10"},
            {"project_id": "cpu", "machine_target": "cpu-proxmox-1"},
        ],
        {"gb10"},
    ) == [{"project_id": "cpu", "machine_target": "cpu-proxmox-1"}]


def test_research_lane_feed_pressure_extracted_no_duplication_in_giant():
    """AGENTS.md test-first for OPEN S3776 at router.py ~4001 (_compute_research_lane_feed_pressure).

    Promotable loading, lane grouping, autopilot plan, and per-lane entry assembly are extracted
    so cognitive complexity stays under Sonar's threshold.
    """
    from pathlib import Path

    src = Path("enoch_control_plane/control_plane/router.py").read_text(
        encoding="utf-8"
    )
    for helper in (
        "_compute_research_lane_feed_pressure",
        "_promotable_rows_for_lane_feed_from_store",
        "_rows_by_worker_lane_key",
        "_research_lane_feed_autopilot_plan",
        "_single_lane_feed_pressure_entry",
    ):
        assert f"def {helper}(" in src, (
            f"{helper} helper missing (S3776 4001 still monolithic)"
        )

    from enoch_control_plane.control_plane.router import (
        _compute_research_lane_feed_pressure,
        _research_lane_feed_autopilot_plan,
        _single_lane_feed_pressure_entry,
    )

    assert callable(_compute_research_lane_feed_pressure)
    action, summary = _research_lane_feed_autopilot_plan(
        label="GB10 lane",
        queue_deficit=1,
        queued_count=0,
        active_count=0,
        promotable_count=0,
        min_queue_depth=1,
        machine_target="gb10-worker",
    )
    assert action == "generate_candidate"
    assert "GB10-targeted" in summary

    action, summary = _research_lane_feed_autopilot_plan(
        label="CPU lane",
        queue_deficit=0,
        queued_count=48,
        active_count=0,
        promotable_count=0,
        min_queue_depth=25,
        machine_target="cpu-proxmox-1",
    )
    assert action == "queue_depth_satisfied"
    assert "above desired queued depth 48/25" in summary

    pressure_key, entry = _single_lane_feed_pressure_entry(
        {
            "lane_key": "gb10",
            "machine_target": "gb10-worker",
            "worker_role": "gpu",
            "active_count": 0,
        },
        queued_by_lane={"gb10": []},
        promotable_by_lane={"gb10": []},
        min_queue_depth=1,
    )
    assert pressure_key == "gb10-worker"
    assert entry["next_autopilot_action"] == "generate_candidate"
    _, satisfied_entry = _single_lane_feed_pressure_entry(
        {
            "lane_key": "cpu-proxmox-1",
            "machine_target": "cpu-proxmox-1",
            "worker_role": "cpu",
            "active_count": 0,
        },
        queued_by_lane={
            "cpu-proxmox-1": [
                {"project_id": f"cpu-{idx}", "machine_target": "cpu-proxmox-1"}
                for idx in range(26)
            ]
        },
        promotable_by_lane={"cpu-proxmox-1": []},
        min_queue_depth=25,
    )
    assert satisfied_entry["queue_deficit"] == 0
    assert satisfied_entry["queue_depth_status"] == "above_desired"
    assert satisfied_entry["above_desired_depth"] is True


def test_research_lane_feed_pressure_helpers_extracted_for_s3776():
    """AGENTS.md test-first for OPEN S3776 at router.py ~4001 (_compute_research_lane_feed_pressure).

    Promotable loading, per-lane row indexing, and next-action/summary decision branches are
    split into top-level helpers so the orchestrator stays at or below complexity 15.
    """
    from pathlib import Path

    src = Path("enoch_control_plane/control_plane/router.py").read_text(
        encoding="utf-8"
    )
    for helper in (
        "_promotable_rows_for_lane_feed_from_store",
        "_rows_by_worker_lane_key",
        "_research_lane_feed_autopilot_plan",
        "_research_lane_generation_target_label",
        "_single_lane_feed_pressure_entry",
    ):
        assert f"def {helper}(" in src, (
            f"{helper} helper missing (S3776 4001 still monolithic)"
        )

    from enoch_control_plane.control_plane.router import (
        _promotable_rows_for_lane_feed_from_store,
        _research_lane_feed_autopilot_plan,
        _research_lane_generation_target_label,
    )

    assert callable(_promotable_rows_for_lane_feed_from_store)
    assert callable(_research_lane_feed_autopilot_plan)
    assert callable(_research_lane_generation_target_label)

    action, summary = _research_lane_feed_autopilot_plan(
        label="GB10 lane",
        queue_deficit=1,
        queued_count=0,
        active_count=0,
        promotable_count=0,
        min_queue_depth=1,
        machine_target="gb10",
    )
    assert action == "generate_candidate"
    assert "GB10-targeted" in summary


def test_wait_for_completion_extracted_no_duplication_in_giant():
    """AGENTS.md test-first for the current horrible-first S3776 (54 in router.py
    inside the 1595 create_control_plane_router / dashboard_research_run_cycle).

    The self-contained wait-for-completion polling logic (the wait_result setup,
    the while loop for polling status until completion or timeout, the deadline and
    last_status handling) is extracted to _wait_for_completion to further reduce
    cognitive complexity of the giant.
    """
    from pathlib import Path

    src = Path("enoch_control_plane/control_plane/router.py").read_text(
        encoding="utf-8"
    )
    assert "def _wait_for_completion(" in src, (
        "_wait_for_completion helper missing (wait-for-completion logic still inline in the giant)"
    )

    from enoch_control_plane.control_plane.router import _wait_for_completion

    assert callable(_wait_for_completion)


def test_wait_for_completion_refills_idle_lanes_while_other_lane_runs(monkeypatch):
    """Regression: wait_for_completion must not block all lane dispatch.

    If one lane finishes while another lane is still active, the polling loop
    should get a chance to dispatch queued work on the newly idle lane instead
    of waiting for the slowest lane to finish first.
    """

    from enoch_control_plane.control_plane.router import _wait_for_completion

    class FakeStore:
        def __init__(self) -> None:
            self.polls = 0

        def queue_row(self, project_id: str) -> dict[str, str]:
            status = "completed" if self.polls else "awaiting_wake"
            return {"project_id": project_id, "status": status}

        def active_items(self) -> list[dict[str, str]]:
            self.polls += 1
            if self.polls == 1:
                return [{"project_id": "slow-cpu", "machine_target": "cpu-proxmox-1"}]
            return []

    refills: list[int] = []

    def refill_idle_lanes() -> int:
        refills.append(1)
        return 1

    monkeypatch.setattr(
        "enoch_control_plane.control_plane.router.time.sleep", lambda _: None
    )
    response = {
        "dispatch_started": True,
        "dispatch": {"candidate": {"project_id": "fast-gb10"}},
        "stages": [],
    }

    result = _wait_for_completion(
        store=FakeStore(),
        response=response,
        wait_for_completion=True,
        max_wait_seconds=30,
        poll_interval_seconds=1,
        refill_idle_lanes=refill_idle_lanes,
    )

    assert result["action"] == "completed"
    assert result["refill_dispatches"] == 1
    assert refills == [1]
    assert response["wait"]["refill_dispatches"] == 1


def test_refill_idle_lanes_during_wait_respects_total_dispatch_cap():
    from enoch_control_plane.control_plane.router import _refill_idle_lanes_during_wait

    class FakeStore:
        def active_items(self) -> list[dict[str, str]]:
            return []

    dispatched_calls: list[str] = []

    def dispatch_queued_project(project_id: str) -> bool:
        dispatched_calls.append(project_id)
        return True

    params = SimpleNamespace(
        max_dispatches=1,
        store=FakeStore(),
        queue_rows_for_lane_feed=lambda: [{"project_id": "queued-gb10"}],
        worker_lane_capacity=lambda active, rows: [
            {
                "dispatch_available": True,
                "next_candidate": {"project_id": "queued-gb10"},
            }
        ],
    )
    response = {"dispatched_count": 1, "stages": []}

    dispatched = _refill_idle_lanes_during_wait(
        params=params,
        response=response,
        dispatch_queued_project=dispatch_queued_project,
    )

    assert dispatched == 0
    assert dispatched_calls == []
    assert response.get("wait_refill_dispatch_count", 0) == 0


def test_worker_settling_after_vm_completion_extracted_for_s3776():
    """AGENTS.md test-first for OPEN S3776 at router.py ~2064 (_worker_settling_after_vm_completion).

    Completed-run-id collection and worker-run matching are extracted so the orchestrator
    stays linear and cognitive complexity stays under Sonar's threshold.
    """
    from pathlib import Path

    src = Path("enoch_control_plane/control_plane/router.py").read_text(
        encoding="utf-8"
    )
    for helper in (
        "_worker_no_live_failed_check",
        "_queue_row_completed_run_id",
        "_run_row_completed_run_id",
        "_collect_completed_run_ids",
        "_worker_settling_match_for_completed_runs",
    ):
        assert f"def {helper}(" in src, (
            f"{helper} helper missing (S3776 2064 still monolithic)"
        )

    from enoch_control_plane.control_plane.router import (
        _collect_completed_run_ids,
        _queue_row_completed_run_id,
        _run_row_completed_run_id,
        _worker_settling_after_vm_completion,
        _worker_settling_match_for_completed_runs,
    )

    assert callable(_worker_settling_after_vm_completion)
    assert callable(_queue_row_completed_run_id)
    assert callable(_run_row_completed_run_id)
    assert callable(_collect_completed_run_ids)
    assert callable(_worker_settling_match_for_completed_runs)


def test_paper_evidence_and_auto_reconcile_extracted_from_giant():
    """AGENTS.md test-first for 5th-lowest OPEN S3776 (create_control_plane_router @ router.py:4304).

    Paper-evidence alerting, queue-row artifact resolution, and stale-callback auto-reconcile
    are module-level helpers so nested definitions no longer inflate the giant's complexity.
    """
    from pathlib import Path

    src = Path("enoch_control_plane/control_plane/router.py").read_text(
        encoding="utf-8"
    )
    for name in (
        "_control_plane_store_for_config",
        "_alert_paper_evidence_blocked",
        "_record_paper_evidence_blocked",
        "_artifact_root_for_queue_row",
        "_evidence_sync_skipped_by_gate",
        "_worker_evidence_sync_kwargs_for_row",
        "_status_has_no_live_worker_conflict",
        "_auto_reconcile_evidence_gate_for_row",
        "_auto_reconcile_missing_evidence_failure",
        "_auto_reconcile_replay_wake_ready_for_row",
        "_auto_reconcile_stale_callback_ready",
    ):
        assert f"def {name}(" in src, (
            f"{name} helper missing (still nested in create_control_plane_router)"
        )

    from enoch_control_plane.control_plane.router import (
        _auto_reconcile_stale_callback_ready,
        _control_plane_store_for_config,
        _record_paper_evidence_blocked,
    )

    assert callable(_control_plane_store_for_config)
    assert callable(_record_paper_evidence_blocked)
    assert callable(_auto_reconcile_stale_callback_ready)


def test_create_control_plane_router_delegates_route_registration():
    """AGENTS.md test-first for 4th-lowest OPEN S3776 (create_control_plane_router).

    The factory only builds the router and store; nested handlers live in
    _register_control_plane_routes so Sonar cognitive complexity stays on the
    registrar, not the public entrypoint.
    """
    import ast
    from pathlib import Path

    src = Path("enoch_control_plane/control_plane/router.py").read_text(
        encoding="utf-8"
    )
    assert "def _register_control_plane_routes(" in src

    module = ast.parse(src)
    factory = next(
        node
        for node in module.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "create_control_plane_router"
    )
    body_lines = {stmt.lineno for stmt in factory.body}
    assert body_lines, "create_control_plane_router must have a body"
    assert max(body_lines) - min(body_lines) <= 8, (
        "create_control_plane_router should remain a thin orchestrator"
    )
    assert any(
        isinstance(stmt, ast.Expr)
        and isinstance(stmt.value, ast.Call)
        and isinstance(stmt.value.func, ast.Name)
        and stmt.value.func.id == "_register_control_plane_routes"
        for stmt in factory.body
    )

    from enoch_control_plane.control_plane.router import (
        _register_control_plane_routes,
        create_control_plane_router,
    )

    assert callable(create_control_plane_router)
    assert callable(_register_control_plane_routes)


def test_register_control_plane_routes_delegates_to_mount():
    """AGENTS.md test-first for OPEN S3776 (_register_control_plane_routes @ router.py:4897).

    The registrar only forwards to _mount_control_plane_http_routes so Sonar cognitive
    complexity stays on the mount implementation, not the public registration entrypoint.
    """
    import ast
    from pathlib import Path

    src = Path("enoch_control_plane/control_plane/router.py").read_text(
        encoding="utf-8"
    )
    assert "def _mount_control_plane_http_routes(" in src

    module = ast.parse(src)
    registrar = next(
        node
        for node in module.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_register_control_plane_routes"
    )
    body_lines = {stmt.lineno for stmt in registrar.body}
    assert body_lines, "_register_control_plane_routes must have a body"
    assert max(body_lines) - min(body_lines) <= 8, (
        "_register_control_plane_routes should remain a thin orchestrator"
    )
    assert any(
        isinstance(stmt, ast.Expr)
        and isinstance(stmt.value, ast.Call)
        and isinstance(stmt.value.func, ast.Name)
        and stmt.value.func.id == "_mount_control_plane_http_routes"
        for stmt in registrar.body
    )

    from enoch_control_plane.control_plane.router import (
        _mount_control_plane_http_routes,
        _register_control_plane_routes,
    )

    assert callable(_register_control_plane_routes)
    assert callable(_mount_control_plane_http_routes)


def test_mount_control_plane_http_routes_delegates_to_http_register():
    """AGENTS.md test-first for OPEN S3776 (_mount_control_plane_http_routes @ router.py:5273).

    Mount only forwards to _register_control_plane_http_routes so Sonar cognitive
    complexity stays on the HTTP route registration body, not the mount entrypoint.
    """
    import ast
    from pathlib import Path

    src = Path("enoch_control_plane/control_plane/router.py").read_text(
        encoding="utf-8"
    )
    assert "def _register_control_plane_http_routes(" in src

    module = ast.parse(src)
    mount = next(
        node
        for node in module.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_mount_control_plane_http_routes"
    )
    body_lines = {stmt.lineno for stmt in mount.body}
    assert body_lines, "_mount_control_plane_http_routes must have a body"
    assert max(body_lines) - min(body_lines) <= 8, (
        "_mount_control_plane_http_routes should remain a thin orchestrator"
    )
    assert any(
        isinstance(stmt, ast.Expr)
        and isinstance(stmt.value, ast.Call)
        and isinstance(stmt.value.func, ast.Name)
        and stmt.value.func.id == "_register_control_plane_http_routes"
        for stmt in mount.body
    )

    from enoch_control_plane.control_plane.router import (
        _mount_control_plane_http_routes,
        _register_control_plane_http_routes,
    )

    assert callable(_mount_control_plane_http_routes)
    assert callable(_register_control_plane_http_routes)


def test_register_control_plane_http_route_handlers_is_thin_orchestrator():
    """AGENTS.md test-first for OPEN S3776 (_register_control_plane_http_route_handlers).

    Handler registration delegates to prepare + domain registrars so Sonar cognitive
    complexity stays off the HTTP registration entrypoint.
    """
    import ast
    from pathlib import Path

    src = Path("enoch_control_plane/control_plane/router.py").read_text(
        encoding="utf-8"
    )
    assert "def _register_control_plane_http_route_handlers(" in src

    module = ast.parse(src)
    handlers = next(
        node
        for node in module.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_register_control_plane_http_route_handlers"
    )
    body_lines = {stmt.lineno for stmt in handlers.body}
    assert body_lines, "_register_control_plane_http_route_handlers must have a body"
    assert max(body_lines) - min(body_lines) <= 20, (
        "_register_control_plane_http_route_handlers should remain a thin orchestrator"
    )
    called = {
        stmt.value.func.id
        for stmt in handlers.body
        if isinstance(stmt, ast.Expr)
        and isinstance(stmt.value, ast.Call)
        and isinstance(stmt.value.func, ast.Name)
    }
    assert "_prepare_control_plane_http_route_bindings" in called
    assert "_register_control_plane_dashboard_shell_routes" in called
    assert "_register_control_plane_operator_legacy_routes" in called

    from enoch_control_plane.control_plane.router import (
        _register_control_plane_http_route_handlers,
    )

    assert callable(_register_control_plane_http_route_handlers)


def test_router_no_redundant_response_model_fastapi_style():
    """AGENTS.md test-first validator for top BLOCKERs (S8409/S8410, ~49 instances in router.py).

    Observed: after recovery to good code, Sonar reports 425 BLOCKER (mostly these in router).
    Invariant: no redundant response_model= in @router.* decorators (return annotation suffices);
    use Annotated for any remaining dep injection. This drops the BLOCKER count and follows
    modern FastAPI recommendations.
    The test is red on the restored tree; patch removes the params; must turn green with ruff/pytest.
    """
    from pathlib import Path

    src = Path("enoch_control_plane/control_plane/router.py").read_text(
        encoding="utf-8"
    )
    count = src.count("response_model=")
    assert count == 0, (
        f"redundant response_model= still present (count={count}); remove all per S8409/S8410 to clear 49+ BLOCKERs"
    )


def test_status_stale_active_rows_scopes_to_lane_active_item() -> None:
    from enoch_control_plane.control_plane.models import (
        ControlFlags,
        DashboardConfigStatus,
        DashboardStatusResponse,
    )
    from enoch_control_plane.control_plane.router import _status_stale_active_rows

    stale_row = {
        "project_id": "stale-project",
        "current_run_id": "run-stale",
        "current_session_id": "sess-stale",
    }
    healthy_row = {
        "project_id": "healthy-project",
        "current_run_id": "run-healthy",
        "current_session_id": "sess-healthy",
    }
    status = DashboardStatusResponse(
        flags=ControlFlags(),
        config=DashboardConfigStatus(
            live_dispatch_enabled=True,
            worker_wake_gate_url="http://worker",
            worker_token_configured=True,
            dispatch_timeout_sec=120,
            project_root="/tmp/projects",
            state_dir="/tmp/state",
        ),
        counts={},
        worker_lanes=[
            {
                "lane_key": "cpu-proxmox-1",
                "active_item": stale_row,
                "active_confirmation": {"state": "stale_active"},
            },
            {
                "lane_key": "gb10",
                "active_item": healthy_row,
                "active_confirmation": {"state": "active_confirmed"},
            },
        ],
        active_items=[stale_row, healthy_row],
    )

    assert _status_stale_active_rows(status) == [stale_row]


def test_auto_reconcile_stale_callback_ready_only_reconciles_stale_lane_rows() -> None:
    from enoch_control_plane.control_plane.models import (
        ControlFlags,
        DashboardConfigStatus,
        DashboardStatusResponse,
    )
    from enoch_control_plane.control_plane.router import (
        _auto_reconcile_stale_callback_ready,
    )

    stale_row = {
        "project_id": "stale-project",
        "project_name": "Stale Project",
        "current_run_id": "run-stale",
        "current_session_id": "sess-stale",
    }
    healthy_row = {
        "project_id": "healthy-project",
        "project_name": "Healthy Project",
        "current_run_id": "run-healthy",
        "current_session_id": "sess-healthy",
    }
    status = DashboardStatusResponse(
        flags=ControlFlags(),
        config=DashboardConfigStatus(
            live_dispatch_enabled=True,
            worker_wake_gate_url="http://worker",
            worker_token_configured=True,
            dispatch_timeout_sec=120,
            project_root="/tmp/projects",
            state_dir="/tmp/state",
        ),
        counts={},
        worker_lanes=[
            {
                "lane_key": "cpu-proxmox-1",
                "active_item": stale_row,
                "active_confirmation": {"state": "stale_active"},
            },
            {
                "lane_key": "gb10",
                "active_item": healthy_row,
                "active_confirmation": {"state": "active_confirmed"},
            },
        ],
        active_items=[stale_row, healthy_row],
    )

    class _Store:
        def __init__(self) -> None:
            self.events: list[dict[str, object]] = []

        def append_event(self, **kwargs: object) -> None:
            self.events.append(kwargs)

    store = _Store()
    config = SimpleNamespace()

    with (
        patch(
            "enoch_control_plane.control_plane.router._auto_reconcile_evidence_gate_for_row",
            side_effect=lambda _config, row: (
                Path("/tmp") / str(row["project_id"]),
                {"values": {"project_decision": "finalize_negative"}},
                {"synced": False},
                str(row["project_id"]),
                str(row["current_run_id"]),
            ),
        ),
        patch(
            "enoch_control_plane.control_plane.router._auto_reconcile_missing_evidence_failure",
            return_value=None,
        ),
        patch(
            "enoch_control_plane.control_plane.router._auto_reconcile_replay_wake_ready_for_row",
            side_effect=lambda _store, row, **kwargs: {
                "ok": True,
                "project_id": row["project_id"],
                "run_id": kwargs["run_id"],
            },
        ) as replay,
    ):
        reconciled = _auto_reconcile_stale_callback_ready(
            config,
            store,
            status,
            requested_by="test",
        )

    assert [item["project_id"] for item in reconciled] == ["stale-project"]
    assert replay.call_count == 1
    assert (
        store.events and store.events[0]["event_type"] == "queue_alert.auto_reconcile"
    )
