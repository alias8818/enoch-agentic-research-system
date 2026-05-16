from __future__ import annotations

from enoch_control_plane.config import GateConfig
from enoch_control_plane.control_plane.router import _remote_evidence_dir


def _config(tmp_path) -> GateConfig:
    return GateConfig(
        state_dir=str(tmp_path / "state"),
        project_root=str(tmp_path / "projects"),
        dispatch_script_path=str(tmp_path / "dispatch.sh"),
        control_api_bearer_token="control",
        completion_callback_url="http://callback",
        completion_callback_token="callback",
        paper_evidence_sync_enabled=True,
        paper_evidence_sync_remote_root="/remote/projects",
    )


def test_remote_evidence_dir_uses_relative_project_dir_over_project_id(tmp_path) -> None:
    config = _config(tmp_path)

    assert _remote_evidence_dir(
        config,
        project_id="very-long-project-id-with-extra-hash",
        source_project_dir="very-long-project-id-with-extra",
    ) == "/remote/projects/very-long-project-id-with-extra"


def test_remote_evidence_dir_preserves_worker_absolute_and_ignores_local_absolute(tmp_path) -> None:
    config = _config(tmp_path)
    local_project = config.expanded_project_root / "local-artifact"
    local_project.mkdir(parents=True)

    assert _remote_evidence_dir(config, project_id="project", source_project_dir="/home/jeremy/projects/project") == "/home/jeremy/projects/project"
    assert _remote_evidence_dir(config, project_id="project", source_project_dir=str(local_project)) == "/remote/projects/project"
    assert _remote_evidence_dir(config, project_id="project", source_project_dir="") == "/remote/projects/project"

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from enoch_control_plane.control_plane.router import create_control_plane_router


TOKEN = "test-token"


def test_draft_next_dry_run_does_not_sync_evidence() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp) / "projects"
        project_dir = root / "paper-positive"
        project_dir.mkdir(parents=True)
        config = GateConfig(
            state_dir=str(Path(tmp) / "state"),
            project_root=str(root),
            dispatch_script_path=str(Path(tmp) / "dispatch.sh"),
            control_api_bearer_token=TOKEN,
            completion_callback_url="http://callback",
            completion_callback_token="callback",
            paper_evidence_sync_enabled=True,
            paper_evidence_sync_remote_root="/remote/projects",
        )
        fastapi_app = FastAPI()
        fastapi_app.include_router(create_control_plane_router(config, lambda authorization: None))
        app = TestClient(fastapi_app)
        app.post("/control/import/legacy-snapshot", json={
            "idempotency_key": "dry-run-no-sync",
            "queue_rows": [{
                "project_id": "paper-positive",
                "project_name": "Paper Positive",
                "project_dir": str(project_dir),
                "status": "completed",
                "last_run_state": "finalize_positive",
                "current_run_id": "run-1",
                "manual_review_required": False,
            }],
            "paper_rows": [],
        })
        with patch("enoch_control_plane.control_plane.router._sync_remote_project_evidence", side_effect=AssertionError("dry run must not sync evidence")):
            response = app.post("/control/papers/draft-next", json={"dry_run": True, "force": True})
        assert response.status_code == 200
        body = response.json()
        assert body["action"] == "dry_run_draft"
        assert body["candidate"]["evidence_sync"] == {"enabled": True, "skipped": True, "reason": "dry_run"}
