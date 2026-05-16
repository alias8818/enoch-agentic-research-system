from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from hypothesis import example, given, settings, strategies as st

from enoch_control_plane.config import GateConfig
from enoch_control_plane.control_plane.router import _local_artifact_root, _remote_evidence_dir
from enoch_control_plane.models import RunRecord
from enoch_control_plane.process_tracker import ProcessTracker


def _config(tmp_path: Path) -> GateConfig:
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


unsafe_text = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",), blacklist_characters="\x00"),
    min_size=0,
    max_size=80,
)


@example(project_id="project", project_dir="~unknown-user/project")
@example(project_id="../evil", project_dir="")
@given(project_id=unsafe_text, project_dir=unsafe_text)
@settings(max_examples=80, deadline=None)
def test_local_artifact_root_stays_under_project_root(project_id: str, project_dir: str) -> None:
    with TemporaryDirectory() as tmp:
        config = _config(Path(tmp))

        artifact_root = _local_artifact_root(config, project_id=project_id, project_dir_text=project_dir)

        artifact_root.resolve().relative_to(config.expanded_project_root.resolve())


@example(project_id="project", project_dir="~unknown-user/project")
@example(project_id="../evil", project_dir="")
@given(project_id=unsafe_text, project_dir=unsafe_text)
@settings(max_examples=80, deadline=None)
def test_process_tracker_project_dir_stays_under_project_root_or_none(project_id: str, project_dir: str) -> None:
    with TemporaryDirectory() as tmp:
        config = _config(Path(tmp))
        tracker = ProcessTracker(config.expanded_project_root)
        record = RunRecord(
            project_id=project_id,
            project_name="property-test",
            project_dir=project_dir,
            run_id="run-property",
            session_id="session-property",
        )

        resolved = tracker._project_dir(record)

        if resolved is not None:
            resolved.resolve().relative_to(config.expanded_project_root.resolve())


@example(project_id="project", source_project_dir="/remote/../evil")
@example(project_id="project", source_project_dir="~unknown-user/project")
@given(project_id=unsafe_text, source_project_dir=unsafe_text)
@settings(max_examples=80, deadline=None)
def test_remote_evidence_dir_never_contains_parent_traversal(project_id: str, source_project_dir: str) -> None:
    with TemporaryDirectory() as tmp:
        config = _config(Path(tmp))

        remote = _remote_evidence_dir(config, project_id=project_id, source_project_dir=source_project_dir)

        assert ".." not in Path(remote).parts
