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
