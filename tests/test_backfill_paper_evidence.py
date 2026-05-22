from __future__ import annotations

from pathlib import Path

from enoch_control_plane.config import GateConfig
from scripts.backfill_paper_evidence import artifact_root_for_row


def _config(tmp_path: Path) -> GateConfig:
    return GateConfig(
        state_dir=str(tmp_path / "state"),
        project_root=str(tmp_path / "projects"),
        dispatch_script_path=str(tmp_path / "dispatch.sh"),
        control_api_bearer_token="control",
        completion_callback_url="http://callback",
        completion_callback_token="callback",
    )


def test_backfill_artifact_root_rejects_unsafe_project_id_fallback(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)

    artifact_root = artifact_root_for_row(
        config, {"project_id": "../outside", "project_dir": ""}
    )

    artifact_root.relative_to(config.expanded_project_root.resolve())
    assert (
        artifact_root
        != (config.expanded_project_root.resolve().parent / "outside").resolve()
    )


def test_backfill_artifact_root_rejects_project_dir_escape(tmp_path: Path) -> None:
    config = _config(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()

    artifact_root = artifact_root_for_row(
        config,
        {"project_id": "safe-project", "project_dir": str(outside)},
    )

    artifact_root.relative_to(config.expanded_project_root.resolve())
    assert artifact_root != outside.resolve()
