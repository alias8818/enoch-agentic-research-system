from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from hypothesis import example, given, settings, strategies as st
from unittest.mock import patch

from enoch_control_plane.config import GateConfig
from enoch_control_plane.control_plane.router import _local_artifact_root, _local_paper_evidence_present, _remote_evidence_dir, _sync_worker_http_evidence
from enoch_control_plane.control_plane.store import ControlPlaneStore
from enoch_control_plane.control_plane.models import ImportSnapshotRequest
from enoch_control_plane.control_plane.worker_adapter import HttpResult
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


run_id_text = st.from_regex(r"[A-Za-z0-9][A-Za-z0-9._-]{0,31}", fullmatch=True)


@given(current_run_id=run_id_text, callback_run_id=run_id_text)
@settings(max_examples=80, deadline=None)
def test_stale_worker_callback_cannot_complete_different_active_run(current_run_id: str, callback_run_id: str) -> None:
    if current_run_id == callback_run_id:
        return
    with TemporaryDirectory() as tmp:
        store = ControlPlaneStore(Path(tmp) / "control.sqlite3")
        store.import_snapshot(
            ImportSnapshotRequest(
                idempotency_key="callback-mismatch-import",
                queue_rows=[{
                    "project_id": "idea-callback-mismatch",
                    "project_name": "Callback Mismatch",
                    "project_dir": "idea-callback-mismatch",
                    "status": "running",
                    "current_run_id": current_run_id,
                    "current_session_id": "session-current",
                    "last_run_state": "running",
                    "next_action_hint": "await_callback",
                }],
                paper_rows=[],
            )
        )

        _event_id, inserted, row = store.record_worker_callback({
            "event_type": "wake_ready",
            "run_id": callback_run_id,
            "session_id": "session-stale",
            "project_id": "idea-callback-mismatch",
            "gate_state": "wake_ready",
            "reason": "stale callback from an older run",
            "idempotency_key": f"stale:{current_run_id}:{callback_run_id}",
        })

        assert inserted is True
        assert row["status"] == "running"
        assert row["current_run_id"] == current_run_id
        assert row["current_session_id"] == "session-current"
        assert row["next_action_hint"] == "await_callback"
        assert row["last_run_state"] == "running"
        events = store.event_rows(limit=1, entity_type="run", entity_id=callback_run_id)
        assert events[0]["payload"]["stale_callback_ignored"] is True
        assert events[0]["payload"]["current_run_id"] == current_run_id


@given(evidence_kind=st.sampled_from(["high_enoch", "high_omx", "paper_bundle", "paper_ledger", "result_json"]))
@settings(max_examples=20, deadline=None)
def test_local_paper_evidence_never_counts_symlinked_files(evidence_kind: str) -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        project_dir = root / "project"
        external = root / "external"
        project_dir.mkdir()
        external.mkdir()

        if evidence_kind.startswith("high_"):
            (project_dir / ".enoch").mkdir()
            (project_dir / ".omx").mkdir()
            (external / "run_notes.md").write_text("outside notes", encoding="utf-8")
            (external / "decision.json").write_text('{"project_decision":"finalize_positive"}', encoding="utf-8")
            (project_dir / "run_notes.md").symlink_to(external / "run_notes.md")
            decision_dir = ".enoch" if evidence_kind == "high_enoch" else ".omx"
            (project_dir / decision_dir / "project_decision.json").symlink_to(external / "decision.json")
        elif evidence_kind in {"paper_bundle", "paper_ledger"}:
            paper_dir = project_dir / "papers" / "run-1"
            paper_dir.mkdir(parents=True)
            name = "evidence_bundle.json" if evidence_kind == "paper_bundle" else "claim_ledger.json"
            (external / name).write_text("{}", encoding="utf-8")
            (paper_dir / name).symlink_to(external / name)
        else:
            results_dir = project_dir / "results"
            results_dir.mkdir()
            (external / "smoke.json").write_text("{}", encoding="utf-8")
            (results_dir / "smoke.json").symlink_to(external / "smoke.json")

        assert _local_paper_evidence_present(project_dir) is False


callback_event_type = st.sampled_from([
    "session_started",
    "wake_ready",
    "session_finished_ready",
    "gate_timeout",
    "gate_error",
    "question_pending",
])


@given(run_id=run_id_text, event_type=callback_event_type)
@settings(max_examples=80, deadline=None)
def test_worker_callback_idempotency_replay_preserves_queue_state(run_id: str, event_type: str) -> None:
    project_id = "idea-callback-idempotency"
    with TemporaryDirectory() as tmp:
        store = ControlPlaneStore(Path(tmp) / "control.sqlite3")
        store.import_snapshot(
            ImportSnapshotRequest(
                idempotency_key=f"idempotency-import:{run_id}",
                queue_rows=[{
                    "project_id": project_id,
                    "project_name": "Callback Idempotency",
                    "project_dir": project_id,
                    "status": "running",
                    "current_run_id": run_id,
                    "current_session_id": "session-current",
                    "last_run_state": "running",
                    "next_action_hint": "await_callback",
                }],
                paper_rows=[],
            )
        )

        callback = {
            "event_type": event_type,
            "run_id": run_id,
            "session_id": "session-callback",
            "project_id": project_id,
            "gate_state": event_type,
            "reason": "idempotency replay",
            "idempotency_key": f"callback-idempotency:{run_id}:{event_type}",
        }
        first_event_id, first_inserted, first_row = store.record_worker_callback(callback)
        second_event_id, second_inserted, second_row = store.record_worker_callback(callback)

        assert first_event_id == second_event_id
        assert first_inserted is True
        assert second_inserted is False
        assert second_row == first_row
        events = store.event_rows(limit=10, entity_type="run", entity_id=run_id)
        assert [event["event_id"] for event in events].count(first_event_id) == 1


@given(current_run_id=run_id_text, imported_run_id=st.one_of(st.just(""), run_id_text))
@settings(max_examples=80, deadline=None)
def test_import_snapshot_does_not_blank_active_queue_run_fields(current_run_id: str, imported_run_id: str) -> None:
    project_id = "idea-import-active-preserve"
    with TemporaryDirectory() as tmp:
        store = ControlPlaneStore(Path(tmp) / "control.sqlite3")
        store.import_snapshot(
            ImportSnapshotRequest(
                idempotency_key=f"active-import-current:{current_run_id}",
                queue_rows=[{
                    "project_id": project_id,
                    "project_name": "Import Active Preserve",
                    "project_dir": project_id,
                    "status": "running",
                    "current_run_id": current_run_id,
                    "current_session_id": "session-current",
                    "last_run_state": "running",
                    "next_action_hint": "await_callback",
                }],
                paper_rows=[],
            )
        )
        store.import_snapshot(
            ImportSnapshotRequest(
                idempotency_key=f"active-import-stale:{current_run_id}:{imported_run_id}",
                queue_rows=[{
                    "project_id": project_id,
                    "project_name": "Import Active Preserve",
                    "project_dir": project_id,
                    "status": "queued",
                    "current_run_id": imported_run_id,
                    "current_session_id": "",
                    "last_run_state": "",
                    "next_action_hint": "",
                }],
                paper_rows=[],
            )
        )

        row = store.queue_row(project_id)
        assert row is not None
        assert row["project_id"] == project_id
        assert row["status"] == "running"
        assert row["current_run_id"] == current_run_id
        assert row["current_session_id"] == "session-current"
        assert row["last_run_state"] == "running"
        assert row["next_action_hint"] == "await_callback"


worker_returned_path = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",), blacklist_characters="\x00"),
    min_size=0,
    max_size=80,
)


@example(rel_path="../escape.txt")
@example(rel_path="/tmp/escape.txt")
@example(rel_path="safe/result.json")
@given(rel_path=worker_returned_path)
@settings(max_examples=80, deadline=None)
def test_worker_http_evidence_sync_never_writes_outside_artifact_root(rel_path: str) -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        artifact_root = root / "artifact"
        config = _config(root)
        config.worker_wake_gate_bearer_token = "worker-token"
        config.worker_wake_gate_url = "http://worker"

        def fake_post_worker_json(base_url, path, token, payload):  # noqa: ANN001 - patched transport-compatible fake
            del base_url, path, token, payload
            return HttpResult(ok=True, status=200, body={"files": [{"path": rel_path, "content": "evidence"}]})

        with patch("enoch_control_plane.control_plane.router.post_worker_json", side_effect=fake_post_worker_json):
            _sync_worker_http_evidence(config, project_id="project", artifact_root=artifact_root)

        for path in root.rglob("*"):
            if path.is_file():
                path.resolve().relative_to(artifact_root.resolve())
