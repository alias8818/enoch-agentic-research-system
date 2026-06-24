from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi import FastAPI
from fastapi.testclient import TestClient
from hypothesis import example, given, settings, strategies as st
from unittest.mock import patch

from enoch_control_plane.config import GateConfig
from enoch_control_plane.control_plane import read_models
from enoch_control_plane.control_plane.router import (
    _local_artifact_root,
    _local_paper_evidence_present,
    _remote_evidence_dir,
    _sync_worker_http_evidence,
    create_control_plane_router,
)
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


def _client(config: GateConfig) -> TestClient:
    app = FastAPI()

    def require(_auth: str | None) -> None:
        return None

    app.include_router(create_control_plane_router(config, require))
    return TestClient(app)


unsafe_text = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",), blacklist_characters="\x00"),
    min_size=0,
    max_size=80,
)


@example(project_id="project", project_dir="~unknown-user/project")
@example(project_id="../evil", project_dir="")
@given(project_id=unsafe_text, project_dir=unsafe_text)
@settings(max_examples=80, deadline=None)
def test_local_artifact_root_stays_under_project_root(
    project_id: str, project_dir: str
) -> None:
    with TemporaryDirectory() as tmp:
        config = _config(Path(tmp))

        artifact_root = _local_artifact_root(
            config, project_id=project_id, project_dir_text=project_dir
        )

        artifact_root.resolve().relative_to(config.expanded_project_root.resolve())


@example(project_id="project", project_dir="~unknown-user/project")
@example(project_id="../evil", project_dir="")
@given(project_id=unsafe_text, project_dir=unsafe_text)
@settings(max_examples=80, deadline=None)
def test_process_tracker_project_dir_stays_under_project_root_or_none(
    project_id: str, project_dir: str
) -> None:
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
@example(project_id="..", source_project_dir="")
@example(project_id="../evil project", source_project_dir="")
@given(project_id=unsafe_text, source_project_dir=unsafe_text)
@settings(max_examples=80, deadline=None)
def test_remote_evidence_dir_never_contains_parent_traversal(
    project_id: str, source_project_dir: str
) -> None:
    with TemporaryDirectory() as tmp:
        config = _config(Path(tmp))

        remote = _remote_evidence_dir(
            config, project_id=project_id, source_project_dir=source_project_dir
        )

        assert ".." not in Path(remote).parts


def test_remote_evidence_dir_rejects_absolute_source_outside_project_root() -> None:
    with TemporaryDirectory() as tmp:
        config = _config(Path(tmp))

        remote = _remote_evidence_dir(
            config,
            project_id="safe-project",
            source_project_dir="/var/log/enoch",
        )

        assert remote == "/remote/projects/safe-project"


run_id_text = st.from_regex(r"[A-Za-z0-9][A-Za-z0-9._-]{0,31}", fullmatch=True)


@given(current_run_id=run_id_text, callback_run_id=run_id_text)
@settings(max_examples=80, deadline=None)
def test_stale_worker_callback_cannot_complete_different_active_run(
    current_run_id: str, callback_run_id: str
) -> None:
    if current_run_id == callback_run_id:
        raise unittest.SkipTest("hypothesis pre-filter: identical run ids")
    with TemporaryDirectory() as tmp:
        store = ControlPlaneStore(Path(tmp) / "control.sqlite3")
        store.import_snapshot(
            ImportSnapshotRequest(
                idempotency_key="callback-mismatch-import",
                queue_rows=[
                    {
                        "project_id": "idea-callback-mismatch",
                        "project_name": "Callback Mismatch",
                        "project_dir": "idea-callback-mismatch",
                        "status": "running",
                        "current_run_id": current_run_id,
                        "current_session_id": "session-current",
                        "last_run_state": "running",
                        "next_action_hint": "await_callback",
                    }
                ],
                paper_rows=[],
            )
        )

        _event_id, inserted, row = store.record_worker_callback(
            {
                "event_type": "wake_ready",
                "run_id": callback_run_id,
                "session_id": "session-stale",
                "project_id": "idea-callback-mismatch",
                "gate_state": "wake_ready",
                "reason": "stale callback from an older run",
                "idempotency_key": f"stale:{current_run_id}:{callback_run_id}",
            }
        )

        assert inserted is True
        assert row["status"] == "running"
        assert row["current_run_id"] == current_run_id
        assert row["current_session_id"] == "session-current"
        assert row["next_action_hint"] == "await_callback"
        assert row["last_run_state"] == "running"
        events = store.event_rows(limit=1, entity_type="run", entity_id=callback_run_id)
        assert events[0]["payload"]["stale_callback_ignored"] is True
        assert events[0]["payload"]["current_run_id"] == current_run_id


@given(
    evidence_kind=st.sampled_from(
        ["high_enoch", "high_omx", "paper_bundle", "paper_ledger", "result_json"]
    )
)
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
            (external / "decision.json").write_text(
                '{"project_decision":"finalize_positive"}', encoding="utf-8"
            )
            (project_dir / "run_notes.md").symlink_to(external / "run_notes.md")
            decision_dir = ".enoch" if evidence_kind == "high_enoch" else ".omx"
            (project_dir / decision_dir / "project_decision.json").symlink_to(
                external / "decision.json"
            )
        elif evidence_kind in {"paper_bundle", "paper_ledger"}:
            paper_dir = project_dir / "papers" / "run-1"
            paper_dir.mkdir(parents=True)
            name = (
                "evidence_bundle.json"
                if evidence_kind == "paper_bundle"
                else "claim_ledger.json"
            )
            (external / name).write_text("{}", encoding="utf-8")
            (paper_dir / name).symlink_to(external / name)
        else:
            results_dir = project_dir / "results"
            results_dir.mkdir()
            (external / "smoke.json").write_text("{}", encoding="utf-8")
            (results_dir / "smoke.json").symlink_to(external / "smoke.json")

        assert _local_paper_evidence_present(project_dir) is False


callback_event_type = st.sampled_from(
    [
        "session_started",
        "wake_ready",
        "session_finished_ready",
        "gate_timeout",
        "gate_error",
        "question_pending",
    ]
)


@given(run_id=run_id_text, event_type=callback_event_type)
@settings(max_examples=80, deadline=None)
def test_worker_callback_idempotency_replay_preserves_queue_state(
    run_id: str, event_type: str
) -> None:
    project_id = "idea-callback-idempotency"
    with TemporaryDirectory() as tmp:
        store = ControlPlaneStore(Path(tmp) / "control.sqlite3")
        store.import_snapshot(
            ImportSnapshotRequest(
                idempotency_key=f"idempotency-import:{run_id}",
                queue_rows=[
                    {
                        "project_id": project_id,
                        "project_name": "Callback Idempotency",
                        "project_dir": project_id,
                        "status": "running",
                        "current_run_id": run_id,
                        "current_session_id": "session-current",
                        "last_run_state": "running",
                        "next_action_hint": "await_callback",
                    }
                ],
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
        first_event_id, first_inserted, first_row = store.record_worker_callback(
            callback
        )
        second_event_id, second_inserted, second_row = store.record_worker_callback(
            callback
        )

        assert first_event_id == second_event_id
        assert first_inserted is True
        assert second_inserted is False
        assert second_row == first_row
        events = store.event_rows(limit=10, entity_type="run", entity_id=run_id)
        assert [event["event_id"] for event in events].count(first_event_id) == 1


late_callback_event_type = st.sampled_from(
    [
        "session_started",
        "gate_timeout",
        "gate_error",
        "question_pending",
    ]
)


@given(run_id=run_id_text, late_event_type=late_callback_event_type)
@settings(max_examples=80, deadline=None)
def test_late_worker_callbacks_cannot_downgrade_completed_success(
    run_id: str, late_event_type: str
) -> None:
    project_id = "idea-callback-terminal-precedence"
    with TemporaryDirectory() as tmp:
        store = ControlPlaneStore(Path(tmp) / "control.sqlite3")
        store.import_snapshot(
            ImportSnapshotRequest(
                idempotency_key=f"terminal-precedence-import:{run_id}",
                queue_rows=[
                    {
                        "project_id": project_id,
                        "project_name": "Callback Terminal Precedence",
                        "project_dir": project_id,
                        "status": "running",
                        "current_run_id": run_id,
                        "current_session_id": "session-current",
                        "last_run_state": "running",
                        "next_action_hint": "await_callback",
                    }
                ],
                paper_rows=[],
            )
        )
        store.record_worker_callback(
            {
                "event_type": "wake_ready",
                "run_id": run_id,
                "session_id": "session-current",
                "project_id": project_id,
                "gate_state": "wake_ready",
                "reason": "terminal success",
                "idempotency_key": f"terminal-precedence-success:{run_id}",
            }
        )

        _event_id, _inserted, row = store.record_worker_callback(
            {
                "event_type": late_event_type,
                "run_id": run_id,
                "session_id": "session-current",
                "project_id": project_id,
                "gate_state": late_event_type,
                "reason": "late lower-precedence callback",
                "idempotency_key": f"terminal-precedence-late:{run_id}:{late_event_type}",
            }
        )

        assert row["status"] == "completed"
        assert row["last_run_state"] == "wake_ready"
        assert row["next_action_hint"] == "draft_paper_or_select_next_project"
        assert row["manual_review_required"] in (0, False)
        events = store.event_rows(limit=1, entity_type="run", entity_id=run_id)
        assert events[0]["payload"]["late_callback_ignored"] is True
        assert events[0]["payload"]["ignore_reason"] == "terminal_success_precedence"


@given(current_run_id=run_id_text, imported_run_id=st.one_of(st.just(""), run_id_text))
@settings(max_examples=80, deadline=None)
def test_import_snapshot_does_not_blank_active_queue_run_fields(
    current_run_id: str, imported_run_id: str
) -> None:
    project_id = "idea-import-active-preserve"
    with TemporaryDirectory() as tmp:
        store = ControlPlaneStore(Path(tmp) / "control.sqlite3")
        store.import_snapshot(
            ImportSnapshotRequest(
                idempotency_key=f"active-import-current:{current_run_id}",
                queue_rows=[
                    {
                        "project_id": project_id,
                        "project_name": "Import Active Preserve",
                        "project_dir": project_id,
                        "status": "running",
                        "current_run_id": current_run_id,
                        "current_session_id": "session-current",
                        "last_run_state": "running",
                        "next_action_hint": "await_callback",
                    }
                ],
                paper_rows=[],
            )
        )
        store.import_snapshot(
            ImportSnapshotRequest(
                idempotency_key=f"active-import-stale:{current_run_id}:{imported_run_id}",
                queue_rows=[
                    {
                        "project_id": project_id,
                        "project_name": "Import Active Preserve",
                        "project_dir": project_id,
                        "status": "queued",
                        "current_run_id": imported_run_id,
                        "current_session_id": "",
                        "last_run_state": "",
                        "next_action_hint": "",
                    }
                ],
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
def test_worker_http_evidence_sync_never_writes_outside_artifact_root(
    rel_path: str,
) -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        artifact_root = root / "artifact"
        config = _config(root)
        config.worker_wake_gate_bearer_token = "worker-token"
        config.worker_wake_gate_url = "http://worker"

        def fake_post_worker_json(base_url, path, token, payload):  # noqa: ANN001 - patched transport-compatible fake
            del base_url, path, token, payload
            return HttpResult(
                ok=True,
                status=200,
                body={"files": [{"path": rel_path, "content": "evidence"}]},
            )

        with patch(
            "enoch_control_plane.control_plane.worker_evidence_sync.post_worker_json",
            side_effect=fake_post_worker_json,
        ):
            _sync_worker_http_evidence(
                config, project_id="project", artifact_root=artifact_root
            )

        for path in root.rglob("*"):
            if path.is_file():
                path.resolve().relative_to(artifact_root.resolve())


stale_related_paper_status = st.sampled_from(
    [
        "publication_draft",
        "draft_review",
        "finalized",
        "approved_for_corpus",
    ]
)


@given(
    related_paper_id=st.one_of(st.just(""), run_id_text),
    related_paper_status=stale_related_paper_status,
    related_review_status=st.sampled_from(
        ["", "finalized", "approved_for_finalization"]
    ),
    has_finalization_package=st.booleans(),
)
@settings(max_examples=40, deadline=None)
def test_operator_counts_ignore_stale_related_paper_references_without_matching_paper_row(
    related_paper_id: str,
    related_paper_status: str,
    related_review_status: str,
    has_finalization_package: bool,
) -> None:
    queue_row = read_models.summarize_queue_row(
        {
            "project_id": "stale-related-paper",
            "project_name": "Stale Related Paper",
            "status": "completed",
            "last_run_state": "wake_ready",
            "next_action_hint": "select_next_project",
            "related_paper_id": related_paper_id,
            "related_paper_status": related_paper_status,
            "related_review_status": related_review_status,
            "related_finalization_package_path": "package.json"
            if has_finalization_package
            else "",
        }
    )

    operator_counts = read_models.operator_counts_from_rows([queue_row])
    detail_counts = read_models.operator_detail_counts_from_rows([queue_row])

    assert operator_counts.get("ready_to_publish", 0) == 0
    assert operator_counts.get("automate_publication", 0) == 0
    assert operator_counts.get("published", 0) == 0
    assert detail_counts.get("ready_to_publish", 0) == 0
    assert detail_counts.get("finalization_needed", 0) == 0
    assert detail_counts.get("draft_created", 0) == 0


active_queue_status = st.sampled_from(
    ["dispatching", "running", "awaiting_wake", "wake_received", "reconciling"]
)


@given(active_status=active_queue_status)
@settings(max_examples=25, deadline=None)
def test_operator_reconciler_prefers_active_duplicate_queue_row(
    active_status: str,
) -> None:
    completed_row = read_models.summarize_queue_row(
        {
            "project_id": "duplicate-project",
            "project_name": "Duplicate Project",
            "status": "completed",
            "last_run_state": "wake_ready",
            "next_action_hint": "select_next_project",
        }
    )
    active_row = read_models.summarize_queue_row(
        {
            "project_id": "duplicate-project",
            "project_name": "Duplicate Project",
            "status": active_status,
            "last_run_state": active_status,
            "current_run_id": "active-run",
            "next_action_hint": "await_callback",
        }
    )

    counts = read_models.operator_counts_from_rows([completed_row, active_row])
    detail_counts = read_models.operator_detail_counts_from_rows(
        [completed_row, active_row]
    )

    assert counts["total_operator_items"] == 1
    assert counts.get("running", 0) == 1
    assert counts.get("complete_no_paper", 0) == 0
    assert detail_counts.get("running", 0) == 1
    assert detail_counts.get("run_complete_no_paper", 0) == 0


@given(paper_status=st.sampled_from(["publication_draft", "draft_review"]))
@settings(max_examples=10, deadline=None)
def test_operator_reconciler_drops_completed_queue_row_superseded_by_paper_identity(
    paper_status: str,
) -> None:
    queue_row = read_models.summarize_queue_row(
        {
            "project_id": "paper-backed-project",
            "project_name": "Paper Backed Project",
            "status": "completed",
            "last_run_state": "wake_ready",
            "current_run_id": "paper-run",
            "next_action_hint": "draft_paper_or_select_next_project",
            "decision_gate_state": "positive",
            "decision_summary": "positive",
        }
    )
    paper_row = read_models.summarize_paper_row(
        {
            "paper_id": "paper-backed-project:paper-run:arxiv_draft",
            "project_id": "paper-backed-project",
            "project_name": "Paper Backed Project",
            "run_id": "paper-run",
            "paper_type": "arxiv_draft",
            "paper_status": paper_status,
        }
    )

    counts = read_models.operator_counts_from_rows([queue_row, paper_row])
    detail_counts = read_models.operator_detail_counts_from_rows([queue_row, paper_row])

    assert counts["total_operator_items"] == 1
    assert counts.get("write_paper", 0) == 0
    assert counts.get("complete_no_paper", 0) == 0
    assert counts.get("automate_publication", 0) == 1
    assert detail_counts.get("run_complete_draft_needed", 0) == 0
    assert (
        detail_counts.get("finalization_needed", 0)
        + detail_counts.get("draft_created", 0)
        == 1
    )


def test_summarize_paper_row_batches_publication_artifact_readability(
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    finalization_package = project_dir / "package.json"
    finalization_package.write_text("{}", encoding="utf-8")
    for name in (
        "draft.md",
        "draft.tex",
        "evidence.json",
        "claims.json",
        "manifest.json",
    ):
        (project_dir / name).write_text("artifact", encoding="utf-8")

    with patch.object(
        read_models,
        "_artifact_file_is_readable",
        side_effect=AssertionError("per-field readability helper should not be called"),
    ):
        summary = read_models.summarize_paper_row(
            {
                "paper_id": "paper-backed-project:paper-run:arxiv_draft",
                "project_id": "paper-backed-project",
                "project_dir": str(project_dir),
                "finalization_package_path": str(finalization_package),
                "draft_markdown_path": "draft.md",
                "draft_latex_path": "draft.tex",
                "evidence_bundle_path": "evidence.json",
                "claim_ledger_path": "claims.json",
                "manifest_path": "manifest.json",
            }
        )

    assert summary["artifact_paths_present"] == {
        "finalization_package_path": True,
        "draft_markdown_path": True,
        "draft_latex_path": True,
        "evidence_bundle_path": True,
        "claim_ledger_path": True,
        "manifest_path": True,
    }


def test_publication_artifact_flags_reject_absolute_finalization_escape(
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    outside_package = tmp_path / "package.json"
    outside_package.write_text("{}", encoding="utf-8")

    summary = read_models.summarize_paper_row(
        {
            "paper_id": "paper-backed-project:paper-run:arxiv_draft",
            "project_id": "paper-backed-project",
            "project_dir": str(project_dir),
            "finalization_package_path": str(outside_package),
        }
    )

    assert summary["artifact_paths_present"]["finalization_package_path"] is False


def test_publication_artifact_flags_treat_missing_project_root_as_unreadable(
    tmp_path: Path,
) -> None:
    missing_project_dir = tmp_path / "missing-project"

    summary = read_models.summarize_paper_row(
        {
            "paper_id": "paper-backed-project:paper-run:arxiv_draft",
            "project_id": "paper-backed-project",
            "project_dir": str(missing_project_dir),
            "finalization_package_path": "package.json",
        }
    )

    assert summary["artifact_paths_present"]["finalization_package_path"] is False


def test_configured_project_root_rejects_env_config_outside_own_boundary(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "attacker-config.json"
    config_path.write_text('{"project_root":"/etc"}\n', encoding="utf-8")

    with patch.dict("os.environ", {"ENOCH_CONFIG": str(config_path)}, clear=False):
        assert read_models._configured_project_root_path() is None


def test_configured_project_root_accepts_local_config_sibling_root(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "projects"
    config_path = tmp_path / "control-plane-config.json"
    config_path.write_text(
        json.dumps({"project_root": str(project_root)}) + "\n",
        encoding="utf-8",
    )

    with patch.dict("os.environ", {"ENOCH_CONFIG": str(config_path)}, clear=False):
        assert read_models._configured_project_root_path() == project_root


def test_gated_write_candidates_uses_row_decision_before_artifact_gate() -> None:
    with patch.object(
        read_models,
        "_paper_draft_gate_for_row",
        side_effect=AssertionError("artifact gate should not run for row decisions"),
    ):
        write_candidates, gate_rejected = read_models._gated_write_candidates(
            [
                {
                    "project_id": "paper-backed-project",
                    "decision_gate_state": "positive",
                    "decision_summary": "approved",
                }
            ]
        )

    assert [row["project_id"] for row in write_candidates] == ["paper-backed-project"]
    assert gate_rejected == []


partial_evidence_kind = st.sampled_from(
    [
        "none",
        "run_notes_only",
        "decision_only",
        "result_only",
        "paper_bundle_only",
        "paper_ledger_only",
    ]
)


def _write_partial_evidence(project_dir: Path, kind: str) -> None:
    if kind == "run_notes_only":
        project_dir.mkdir(parents=True, exist_ok=True)
        (project_dir / "run_notes.md").write_text(
            "notes without decision or result artifacts\n", encoding="utf-8"
        )
    elif kind == "decision_only":
        (project_dir / ".enoch").mkdir(parents=True, exist_ok=True)
        (project_dir / ".enoch" / "project_decision.json").write_text(
            '{"project_decision":"finalize_positive"}\n', encoding="utf-8"
        )
    elif kind == "result_only":
        (project_dir / "results").mkdir(parents=True, exist_ok=True)
        (project_dir / "results" / "smoke.json").write_text(
            '{"ok":true}\n', encoding="utf-8"
        )
    elif kind == "paper_bundle_only":
        (project_dir / "papers" / "run-missing-evidence").mkdir(
            parents=True, exist_ok=True
        )
        (
            project_dir / "papers" / "run-missing-evidence" / "evidence_bundle.json"
        ).write_text("{}\n", encoding="utf-8")
    elif kind == "paper_ledger_only":
        (project_dir / "papers" / "run-missing-evidence").mkdir(
            parents=True, exist_ok=True
        )
        (
            project_dir / "papers" / "run-missing-evidence" / "claim_ledger.json"
        ).write_text("{}\n", encoding="utf-8")


@given(kind=partial_evidence_kind, existing_paper=st.booleans())
@settings(max_examples=24, deadline=None)
def test_draft_next_partial_evidence_never_creates_or_advances_paper(
    kind: str, existing_paper: bool
) -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        config = _config(root).model_copy(update={"paper_evidence_sync_enabled": False})
        client = _client(config)
        project_dir = config.expanded_project_root / "missing-evidence"
        _write_partial_evidence(project_dir, kind)
        paper_rows = []
        if existing_paper:
            paper_rows.append(
                {
                    "paper_id": "existing:other-run:arxiv_draft",
                    "project_id": "other-project",
                    "run_id": "other-run",
                    "paper_status": "publication_draft",
                    "draft_markdown_path": "papers/other/paper.md",
                    "draft_latex_path": "papers/other/paper.tex",
                    "evidence_bundle_path": "papers/other/evidence_bundle.json",
                    "claim_ledger_path": "papers/other/claim_ledger.json",
                    "manifest_path": "papers/other/manifest.json",
                }
            )
        imported = client.post(
            "/control/import/legacy-snapshot",
            json={
                "idempotency_key": f"partial-evidence:{kind}:{existing_paper}",
                "queue_rows": [
                    {
                        "project_id": "missing-evidence",
                        "project_name": "Missing Evidence",
                        "project_dir": "missing-evidence",
                        "status": "completed",
                        "last_run_state": "wake_ready",
                        "next_action_hint": "draft_paper_or_select_next_project",
                        "current_run_id": "run-missing-evidence",
                        "manual_review_required": False,
                        "bounded_paper_ready": True,
                        "evidence_strength": "strong",
                        "claim_scope": "local",
                        "hypothesis_status": "supported",
                    }
                ],
                "paper_rows": paper_rows,
            },
        )
        assert imported.status_code == 200
        before = client.get("/control/export/snapshot").json()
        before_files = sorted(
            str(path.relative_to(project_dir))
            for path in project_dir.rglob("*")
            if path.is_file()
        )

        response = client.post(
            "/control/papers/draft-next",
            json={"force": True, "override_hold_action": "draft-next-while-held"},
        )
        after = client.get("/control/export/snapshot").json()
        after_files = sorted(
            str(path.relative_to(project_dir))
            for path in project_dir.rglob("*")
            if path.is_file()
        )

        assert response.status_code == 200
        assert response.json()["action"] == "noop"
        assert after["paper_rows"] == before["paper_rows"]
        assert after_files == before_files


def test_draft_next_skips_partial_evidence_candidate_and_drafts_later_valid_candidate() -> (
    None
):
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        config = _config(root).model_copy(update={"paper_evidence_sync_enabled": False})
        client = _client(config)
        partial_dir = config.expanded_project_root / "partial-candidate"
        valid_dir = config.expanded_project_root / "valid-candidate"
        _write_partial_evidence(partial_dir, "run_notes_only")
        (valid_dir / ".enoch").mkdir(parents=True)
        (valid_dir / "run_notes.md").write_text(
            "measured positive result with local baseline evidence\n", encoding="utf-8"
        )
        (valid_dir / ".enoch" / "project_decision.json").write_text(
            '{"project_decision":"finalize_positive"}\n', encoding="utf-8"
        )

        imported = client.post(
            "/control/import/legacy-snapshot",
            json={
                "idempotency_key": "mixed-partial-valid-evidence",
                "queue_rows": [
                    {
                        "project_id": "partial-candidate",
                        "project_name": "Partial Candidate",
                        "project_dir": "partial-candidate",
                        "status": "completed",
                        "last_run_state": "wake_ready",
                        "next_action_hint": "draft_paper_or_select_next_project",
                        "current_run_id": "run-partial",
                        "bounded_paper_ready": True,
                        "evidence_strength": "strong",
                        "claim_scope": "local",
                        "hypothesis_status": "supported",
                        "updated_at": "2026-05-17T00:00:00Z",
                    },
                    {
                        "project_id": "valid-candidate",
                        "project_name": "Valid Candidate",
                        "project_dir": "valid-candidate",
                        "status": "completed",
                        "last_run_state": "wake_ready",
                        "next_action_hint": "draft_paper_or_select_next_project",
                        "current_run_id": "run-valid",
                        "bounded_paper_ready": True,
                        "evidence_strength": "strong",
                        "claim_scope": "local",
                        "hypothesis_status": "supported",
                        "updated_at": "2026-05-17T00:01:00Z",
                    },
                ],
                "paper_rows": [],
            },
        )
        assert imported.status_code == 200

        response = client.post(
            "/control/papers/draft-next",
            json={"force": True, "override_hold_action": "draft-next-while-held"},
        )
        snapshot = client.get("/control/export/snapshot").json()

        assert response.status_code == 200
        body = response.json()
        assert body["action"] == "drafted"
        assert body["candidate"]["project_id"] == "valid-candidate"
        assert [row["project_id"] for row in snapshot["paper_rows"]] == [
            "valid-candidate"
        ]
        assert not list(partial_dir.glob("papers/run-partial/*"))
