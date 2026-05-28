from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any, Callable

from fastapi import HTTPException

from enoch_control_plane.config import GateConfig
from enoch_control_plane.enoch_core.models import QueueSnapshotRequest
from enoch_control_plane.enoch_core.router import create_enoch_core_router


class EnochCoreRouterTests(unittest.TestCase):
    def make_endpoints(self, tmp: str) -> dict[str, Callable[..., Any]]:
        config = GateConfig(
            state_dir=tmp,
            project_root=tmp,
            dispatch_script_path=str(Path(tmp) / "dispatch.sh"),
            control_api_bearer_token="secret",
            completion_callback_url="http://127.0.0.1/callback",
            completion_callback_token="callback-token",
        )

        def require_bearer(authorization: str | None) -> None:
            if authorization != "Bearer secret":
                raise HTTPException(status_code=401, detail="invalid bearer token")

        router = create_enoch_core_router(config, require_bearer)
        return {route.path: route.endpoint for route in router.routes}  # type: ignore[attr-defined]

    def test_health_requires_auth_and_reports_shadow_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            endpoints = self.make_endpoints(tmp)
            with self.assertRaises(HTTPException):
                endpoints["/enoch-core/health"](authorization=None)
            response = endpoints["/enoch-core/health"](authorization="Bearer secret")
            self.assertEqual(response.mode, "shadow")

    def test_snapshot_projection_and_candidates_are_proposal_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            endpoints = self.make_endpoints(tmp)
            payload = QueueSnapshotRequest(
                idempotency_key="snap-1",
                source="test",
                queue_rows=[
                    {
                        "project_id": "p1",
                        "project_name": "Ready Project",
                        "status": "completed",
                        "last_run_state": "finalize_positive",
                        "current_run_id": "r1",
                    }
                ],
                paper_rows=[
                    {
                        "paper_id": "p2:r2:arxiv_draft",
                        "project_id": "p2",
                        "project_name": "Draft Project",
                        "run_id": "r2",
                        "paper_status": "draft_review",
                        "draft_markdown_path": "papers/r2/paper.md",
                        "evidence_bundle_path": "papers/r2/evidence_bundle.json",
                        "claim_ledger_path": "papers/r2/claim_ledger.json",
                        "manifest_path": "papers/r2/paper_manifest.json",
                    }
                ],
            )
            ingest = endpoints["/enoch-core/snapshots/n8n-queue"](
                payload=payload, authorization="Bearer secret"
            )
            self.assertFalse(ingest.would_apply)
            self.assertEqual(ingest.queue_rows, 1)

            projection = endpoints["/enoch-core/projections/queue"](
                authorization="Bearer secret", mode=None
            )
            self.assertEqual(projection.draft_candidate_count, 1)
            self.assertEqual(projection.polish_candidate_count, 1)

            draft = endpoints["/enoch-core/candidates/paper-draft"](
                authorization="Bearer secret", mode=None
            )
            self.assertEqual(draft.action, "draft")
            self.assertFalse(draft.would_apply)
            self.assertEqual(draft.candidate["draft_payload"]["project_id"], "p1")

            polish = endpoints["/enoch-core/candidates/paper-polish"](
                authorization="Bearer secret", mode=None
            )
            self.assertEqual(polish.action, "polish")
            self.assertFalse(polish.would_apply)
            self.assertEqual(
                polish.candidate["polish_payload"]["paper_id"], "p2:r2:arxiv_draft"
            )

    def test_snapshot_idempotency_conflict_raises_409(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            endpoints = self.make_endpoints(tmp)
            payload = QueueSnapshotRequest(
                idempotency_key="snap-1", source="test", queue_rows=[], paper_rows=[]
            )
            endpoints["/enoch-core/snapshots/n8n-queue"](
                payload=payload, authorization="Bearer secret"
            )
            changed = QueueSnapshotRequest(
                idempotency_key="snap-1",
                source="test",
                queue_rows=[{"project_id": "changed"}],
                paper_rows=[],
            )
            with self.assertRaises(HTTPException) as raised:
                endpoints["/enoch-core/snapshots/n8n-queue"](
                    payload=changed, authorization="Bearer secret"
                )
            self.assertEqual(raised.exception.status_code, 409)

    def test_no_candidate_returns_noop_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            endpoints = self.make_endpoints(tmp)
            body = endpoints["/enoch-core/candidates/paper-draft"](
                authorization="Bearer secret", mode=None
            )
            self.assertEqual(body.action, "noop")
            self.assertIsNone(body.candidate)
            self.assertFalse(body.would_apply)

    def test_paper_draft_endpoint_uses_db_gated_projection_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            endpoints = self.make_endpoints(tmp)
            payload = QueueSnapshotRequest(
                idempotency_key="snap-paper-gated",
                source="test",
                queue_rows=[
                    {
                        "project_id": "raw-wake",
                        "project_name": "Raw Wake",
                        "project_dir": "raw-wake",
                        "status": "completed",
                        "last_run_state": "wake_ready",
                        "next_action_hint": "draft_paper_or_select_next_project",
                        "current_run_id": "run-raw",
                    },
                    {
                        "project_id": "scout-ready",
                        "project_name": "Scout Ready",
                        "project_dir": "scout-ready",
                        "status": "completed",
                        "last_run_state": "wake_ready",
                        "next_action_hint": "draft_paper_or_select_next_project",
                        "current_run_id": "run-scout",
                        "decision_gate_state": "negative",
                        "project_decision": "finalize_negative",
                        "research_outcome": "useful_signal",
                        "bounded_paper_ready": True,
                        "hypothesis_status": "supported",
                        "evidence_strength": "strong",
                        "claim_scope": "single local benchmark",
                        "scale_limits": "toy-sized reproduction only",
                    },
                ],
                paper_rows=[],
            )
            endpoints["/enoch-core/snapshots/n8n-queue"](
                payload=payload, authorization="Bearer secret"
            )

            projection = endpoints["/enoch-core/projections/queue"](
                authorization="Bearer secret", mode=None
            )
            draft = endpoints["/enoch-core/candidates/paper-draft"](
                authorization="Bearer secret", mode=None
            )

            self.assertEqual(projection.draft_candidate_count, 1)
            self.assertEqual(draft.action, "draft")
            self.assertEqual(draft.candidate_count, 1)
            self.assertEqual(draft.candidate["project_id"], "scout-ready")


if __name__ == "__main__":
    unittest.main()


class EnochCoreSupabaseBackendRoutingTests(unittest.TestCase):
    def test_control_plane_backend_can_route_enoch_core_to_supabase(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = GateConfig(
                state_dir=tmp,
                project_root=tmp,
                dispatch_script_path=str(Path(tmp) / "dispatch.sh"),
                control_api_bearer_token="secret",
                completion_callback_url="http://127.0.0.1/callback",
                completion_callback_token="callback-token",
                control_plane_store_backend="supabase",
                supabase_database_url="postgresql://example.invalid/postgres",
            )

            class FakeStore:
                def rebuild_queue_projection(self) -> dict[str, Any]:
                    return {
                        "source": "none",
                        "queue_rows": [],
                        "paper_rows": [],
                        "captured_at": None,
                    }

            def require_bearer(authorization: str | None) -> None:
                if authorization != "Bearer secret":
                    raise HTTPException(status_code=401, detail="invalid bearer token")

            from unittest.mock import patch

            with patch(
                "enoch_control_plane.enoch_core.router.SupabaseEnochCoreStore",
                return_value=FakeStore(),
            ) as supabase_store:
                router = create_enoch_core_router(config, require_bearer)
                endpoints = {route.path: route.endpoint for route in router.routes}  # type: ignore[attr-defined]
                response = endpoints["/enoch-core/health"](
                    authorization="Bearer secret"
                )

            supabase_store.assert_called_once_with(
                "postgresql://example.invalid/postgres"
            )
            self.assertEqual(response.store_backend, "supabase")
            self.assertEqual(response.db_path, "supabase")

    def test_enoch_core_backend_can_be_pinned_to_sqlite_during_tests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = GateConfig(
                state_dir=tmp,
                project_root=tmp,
                dispatch_script_path=str(Path(tmp) / "dispatch.sh"),
                control_api_bearer_token="secret",
                completion_callback_url="http://127.0.0.1/callback",
                completion_callback_token="callback-token",
                control_plane_store_backend="supabase",
                enoch_core_store_backend="sqlite",
                supabase_database_url="postgresql://example.invalid/postgres",
            )

            def require_bearer(authorization: str | None) -> None:
                if authorization != "Bearer secret":
                    raise HTTPException(status_code=401, detail="invalid bearer token")

            router = create_enoch_core_router(config, require_bearer)
            endpoints = {route.path: route.endpoint for route in router.routes}  # type: ignore[attr-defined]
            response = endpoints["/enoch-core/health"](authorization="Bearer secret")
            self.assertEqual(response.store_backend, "sqlite")
            self.assertTrue(response.db_path.endswith("enoch_core.sqlite3"))
