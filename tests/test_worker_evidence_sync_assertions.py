from __future__ import annotations

from pathlib import Path

import pytest

from enoch_control_plane.config import GateConfig
from enoch_control_plane.control_plane import worker_evidence_sync as sync


def _config(tmp_path: Path) -> GateConfig:
    return GateConfig(
        state_dir=str(tmp_path / "state"),
        project_root=str(tmp_path / "projects"),
        dispatch_script_path=str(tmp_path / "dispatch.sh"),
        control_api_bearer_token="control",
        completion_callback_url="http://callback",
        completion_callback_token="callback",
        worker_wake_gate_url="http://worker.invalid",
        worker_wake_gate_bearer_token="worker-token",
    )


def test_sync_worker_http_evidence_rejects_missing_prepared_artifact_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def broken_prepare(artifact_root: Path) -> tuple[None, None]:
        del artifact_root
        return None, None

    def no_evidence_paths(*, base_run: str) -> list[str]:
        del base_run
        return []

    monkeypatch.setattr(sync, "_prepare_worker_evidence_artifact_root", broken_prepare)
    monkeypatch.setattr(sync, "_worker_http_evidence_paths", no_evidence_paths)

    with pytest.raises(RuntimeError, match="missing prepared artifact root"):
        sync._sync_worker_http_evidence(
            _config(tmp_path),
            project_id="project-1",
            artifact_root=tmp_path / "artifact",
        )
