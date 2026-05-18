from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest
from fastapi import HTTPException

import enoch_control_plane.app as appmod
from enoch_control_plane.models import GateState, ProcessInfo, RunRecord


def _record(**kwargs) -> RunRecord:
    base = {
        "run_id": "run-1",
        "session_id": "session-1",
        "project_id": "project-a",
        "project_name": "Project A",
        "gate_state": GateState.RUNNING,
    }
    base.update(kwargs)
    return RunRecord(**base)


def test_auth_helpers_accept_header_or_dashboard_token() -> None:
    token = appmod.config.control_api_bearer_token
    appmod._require_local_bearer(f"Bearer {token}")
    appmod._require_dashboard_bearer(None, token)
    with pytest.raises(HTTPException) as exc:
        appmod._require_local_bearer("Bearer wrong")
    assert exc.value.status_code == 401


def test_path_resolution_and_writes_are_safe(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    resolved = appmod._resolve_under_root("project/file.txt", root)
    assert resolved == (root / "project/file.txt").resolve()
    with pytest.raises(HTTPException) as exc:
        appmod._resolve_under_root("../escape", root)
    assert exc.value.status_code == 400
    with pytest.raises(HTTPException) as invalid:
        appmod._resolve_under_root("bad\0path", root)
    assert invalid.value.status_code == 400

    target = root / "out.txt"
    appmod._write_text(target, "first", overwrite=False)
    with pytest.raises(HTTPException) as conflict:
        appmod._write_text(target, "second", overwrite=False)
    assert conflict.value.status_code == 409
    appmod._write_text(target, "second", overwrite=True)
    assert target.read_text() == "second"


def test_project_metadata_prefers_enoch_and_validates_shape(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = tmp_path / "project-a"
    (project / ".omx").mkdir(parents=True)
    (project / ".enoch").mkdir(parents=True)
    (project / ".omx" / "project.json").write_text(json.dumps({"metadata": {"workload_class": "training"}}))
    (project / ".enoch" / "project.json").write_text(json.dumps({"metadata": {"workload_class": "control-plane"}}))

    metadata = appmod._load_project_metadata(project)
    assert metadata["metadata"]["workload_class"] == "control-plane"
    workload_class, _profile = appmod._resolve_workload_profile_for_project_dir(project)
    assert workload_class == "control_plane"

    (project / ".enoch" / "project.json").write_text(json.dumps({"metadata": "bad"}))
    with pytest.raises(HTTPException) as exc:
        appmod._resolve_workload_profile_for_project_dir(project)
    assert exc.value.status_code == 500


def test_assign_record_workload_profile_from_project_metadata(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = tmp_path / "project-a"
    (project / ".enoch").mkdir(parents=True)
    (project / ".enoch" / "project.json").write_text(json.dumps({"metadata": {"workload_class": "training"}}))
    monkeypatch.setattr(appmod.config, "project_root", str(tmp_path))

    record = _record(project_dir="project-a", workload_class=None, workload_profile=None)
    updated = appmod._assign_record_workload_profile(record)
    assert updated.workload_class == "training"
    assert updated.workload_profile is not None
    assert updated.project_dir == str(project.resolve())


def test_project_artifact_relative_paths_reject_escape(tmp_path: Path) -> None:
    project = tmp_path / "project-a"
    project.mkdir()
    good = appmod._resolve_project_relative_path(project, "paper/main.md")
    assert good == (project / "paper/main.md").resolve()
    for bad in ("", "/tmp/nope", "../escape"):
        with pytest.raises(HTTPException):
            appmod._resolve_project_relative_path(project, bad)



def test_project_metadata_access_failure_is_controlled_http_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = tmp_path / "project-a"
    enoch_metadata = project / ".enoch" / "project.json"
    enoch_metadata.parent.mkdir(parents=True)
    enoch_metadata.write_text(json.dumps({"metadata": {"workload_class": "training"}}), encoding="utf-8")
    real_exists = Path.exists

    def blocked_exists(path: Path) -> bool:
        if path == enoch_metadata:
            raise PermissionError("simulated metadata access failure")
        return real_exists(path)

    monkeypatch.setattr(Path, "exists", blocked_exists)

    with pytest.raises(HTTPException) as exc:
        appmod._load_project_metadata(project)
    assert exc.value.status_code == 500
    assert "project metadata" in str(exc.value.detail)


def test_project_decision_access_failure_returns_error_not_raw_exception(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = tmp_path / "p"
    decision_path = project / ".enoch" / "project_decision.json"
    decision_path.parent.mkdir(parents=True)
    decision_path.write_text(json.dumps({"project_decision": "finalize_negative"}), encoding="utf-8")
    real_exists = Path.exists

    def blocked_exists(path: Path) -> bool:
        if path == decision_path:
            raise PermissionError("simulated decision access failure")
        return real_exists(path)

    monkeypatch.setattr(Path, "exists", blocked_exists)

    decision, error = appmod._load_project_decision(project)
    assert decision is None
    assert error is not None
    assert "project decision" in error

def test_project_decision_loading_native_legacy_and_summary(tmp_path: Path) -> None:
    project = tmp_path / "p"
    (project / ".enoch").mkdir(parents=True)
    native_path = project / ".enoch" / "project_decision.json"
    native_path.write_text(json.dumps({"project_decision": "finalize_negative", "followup_required_evidence": "a\nb"}))
    decision, error = appmod._load_project_decision(project)
    assert error is None
    assert decision is not None
    assert decision.project_decision == "finalize_negative"
    assert decision.followup_required_evidence == ["a", "b"]

    native_path.write_text("not json")
    decision, error = appmod._load_project_decision(project)
    assert decision is None
    assert "invalid JSON" in str(error)

    native_path.unlink()
    summary_dir = project / "results" / "x" / "project_decision_summary"
    summary_dir.mkdir(parents=True)
    (summary_dir / "summary.json").write_text(json.dumps({
        "recommendation": "falsified by evidence",
        "native_phase": {"kill_condition_status": "supported"},
        "alternative_deployment_branch": {"status": "supported by proxy"},
    }))
    decision, error = appmod._load_project_decision(project)
    assert error is None
    assert decision is not None
    assert decision.project_decision == "finalize_negative"
    assert decision.branch_project_name == "Bonsai-Up Profile Variation Branch"

    none_decision, none_error = appmod._load_project_decision(project, include_summary_fallback=False)
    assert none_decision is None
    assert none_error is None


def test_file_discovery_helpers_ignore_internal_state(tmp_path: Path) -> None:
    project = tmp_path / "project-a"
    (project / "src").mkdir(parents=True)
    (project / "results").mkdir()
    (project / "artifacts").mkdir()
    (project / ".enoch" / "logs").mkdir(parents=True)
    (project / "src" / "main.py").write_text("print('ok')")
    (project / "results" / "metrics.json").write_text("{}")
    (project / "artifacts" / "claim.json").write_text("{}")
    (project / ".enoch" / "logs" / "session-history.jsonl").write_text(
        json.dumps({"session_id": "old", "run_id": "old", "timestamp": "2026-01-01T00:00:00Z"}) + "\n" +
        json.dumps({"session_id": "new", "run_id": "run", "timestamp": "2026-01-02T00:00:00Z"}) + "\n"
    )

    assert appmod._tail_lines(project / "src" / "main.py") == ["print('ok')"]
    assert appmod._recent_files(project, limit=10) == ["src/main.py"]
    assert set(appmod._result_files(project, limit=10)) == {"results/metrics.json", "artifacts/claim.json"}
    assert appmod._latest_session(project).session_id == "new"



def test_file_discovery_helpers_treat_access_failures_as_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = tmp_path / "project-a"
    results_dir = project / "results"
    src_dir = project / "src"
    results_dir.mkdir(parents=True)
    src_dir.mkdir()
    (results_dir / "metrics.json").write_text("{}", encoding="utf-8")
    (src_dir / "main.py").write_text("print('ok')", encoding="utf-8")
    real_exists = Path.exists
    real_stat = Path.stat

    def blocked_exists(path: Path) -> bool:
        if path == results_dir:
            raise PermissionError("simulated results access failure")
        return real_exists(path)

    def blocked_stat(path: Path, *args, **kwargs):  # noqa: ANN002, ANN003, ANN202 - pathlib-compatible test double
        if path == src_dir / "main.py":
            raise PermissionError("simulated file stat failure")
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "exists", blocked_exists)
    monkeypatch.setattr(Path, "stat", blocked_stat)

    assert appmod._result_files(project, limit=10) == []
    assert appmod._recent_files(project, limit=10) == []

def test_file_read_helpers_treat_access_failures_as_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = tmp_path / "project-a"
    log_dir = project / ".enoch" / "logs"
    log_dir.mkdir(parents=True)
    run_notes = project / "run_notes.md"
    session_history = log_dir / "session-history.jsonl"
    run_notes.write_text("notes", encoding="utf-8")
    session_history.write_text(json.dumps({"session_id": "new", "run_id": "run", "timestamp": "2026-01-02T00:00:00Z"}) + "\n")
    real_exists = Path.exists

    def blocked_exists(path: Path) -> bool:
        if path in {run_notes, session_history}:
            raise PermissionError("simulated filesystem access failure")
        return real_exists(path)

    monkeypatch.setattr(Path, "exists", blocked_exists)

    assert appmod._tail_lines(run_notes) == []
    assert appmod._latest_session(project) is None


def test_activity_and_event_helpers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert appmod._activity_from_processes([], "idle") == "idle"
    assert appmod._activity_from_processes([ProcessInfo(pid=1, cmdline="tail -f log"), ProcessInfo(pid=2, cmdline="python train.py")], "running") == "running python train.py"
    assert appmod._activity_from_processes([ProcessInfo(pid=3, cmdline="x" * 200)], None).endswith("...")

    event_log = tmp_path / "events.jsonl"
    event_log.write_text('{"kind":"one"}\nnot-json\n{"kind":"two"}\n')
    monkeypatch.setattr(appmod.store, "events_log", event_log)
    events = appmod._read_recent_events(limit=3)
    assert events[0]["kind"] == "two"
    assert events[1]["kind"] == "unparseable_event"
    assert events[2]["kind"] == "one"

    large = {"kind": "big", "payload": "x" * 5000, "run_id": "run"}
    trimmed = appmod._trim_event(large, max_chars=200)
    assert trimmed["truncated"] is True
    assert "raw_preview" in trimmed


def test_snapshot_and_event_reads_treat_access_failures_as_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state = tmp_path / "state"
    state.mkdir()
    queue_snapshot = state / "queue_snapshot.json"
    paper_snapshot = state / "paper_snapshot.json"
    events_log = state / "events.jsonl"
    queue_snapshot.write_text("{}", encoding="utf-8")
    paper_snapshot.write_text("{}", encoding="utf-8")
    events_log.write_text('{"kind":"event"}\n', encoding="utf-8")
    monkeypatch.setattr(appmod.config, "state_dir", str(state))
    monkeypatch.setattr(appmod.store, "events_log", events_log)
    real_exists = Path.exists

    def blocked_exists(path: Path) -> bool:
        if path in {queue_snapshot, paper_snapshot, events_log}:
            raise PermissionError("simulated snapshot access failure")
        return real_exists(path)

    monkeypatch.setattr(Path, "exists", blocked_exists)

    assert appmod._read_queue_snapshot() == {}
    assert appmod._read_paper_snapshot() == {}
    assert appmod._read_recent_events(limit=5) == []


def test_timestamp_and_dashboard_state_edges() -> None:
    assert appmod._parse_timestamp(None) is None
    assert appmod._parse_timestamp("not-a-date") is None
    assert appmod._parse_timestamp("2026-01-01T00:00:00").tzinfo is not None

    for state, lifecycle in [
        (GateState.PENDING_IDLE_GATE, "settling"),
        (GateState.WAITING_FOR_PROCESS_EXIT, "settling"),
        (GateState.WAITING_FOR_QUIET_WINDOW, "settling"),
        (GateState.FINISHED_PENDING_GATE, "settling"),
        (GateState.CANCELLED, "historical"),
    ]:
        assert appmod._dashboard_truth(_record(gate_state=state), [])["lifecycle_state"] == lifecycle

    finished = _record(gate_state=GateState.FINISHED_READY, last_idempotency_key="run-1:session_finished_ready:seen")
    assert appmod._dashboard_truth(finished, [])["lifecycle_state"] == "finished_delivered"


def test_paper_snapshot_summarizes_and_truncates_rows() -> None:
    snapshot = appmod._build_paper_snapshot({
        "source": "unit",
        "rows": [
            {
                "paper_id": "p1",
                "project_id": "proj",
                "project_name": "Project",
                "paper_status": "publication_draft",
                "paper_type": "research_note",
                "draft_markdown_path": "paper.md",
                "review_notes": "x" * 3000,
                "updated_at": "2026-01-02T00:00:00Z",
            },
            {"paper_id": "p2", "paper_status": "draft_review", "paper_type": "note", "updated_at": "2026-01-01T00:00:00Z"},
        ],
    })
    assert snapshot["total"] == 2
    assert snapshot["reviewable_count"] == 1
    assert snapshot["publication_count"] == 1
    assert snapshot["status_counts"] == {"publication_draft": 1, "draft_review": 1}
    assert snapshot["latest_rows"][0]["review_notes"].endswith("[truncated]")


def test_record_age_uses_updated_last_event_or_created() -> None:
    ts = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()
    age = appmod._record_age_seconds(_record(updated_at="", last_event_at=ts, created_at=""))
    assert age is not None and 0 <= age < 30


def test_write_text_preserves_existing_file_when_replace_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "paper.md"
    target.write_text("old", encoding="utf-8")

    def flaky_replace(src: Path | str, dst: Path | str) -> None:
        if Path(dst) == target:
            raise OSError("simulated atomic replace failure")
        appmod.os.replace(src, dst)

    monkeypatch.setattr(appmod.os, "replace", flaky_replace)

    with pytest.raises(OSError):
        appmod._write_text(target, "new", overwrite=True)

    assert target.read_text(encoding="utf-8") == "old"
    assert not list(tmp_path.glob(".paper.md.*.tmp"))



def test_write_text_rejects_uninspectable_target_without_raw_permission_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = (tmp_path / "paper.md").resolve()
    real_exists = appmod.Path.exists

    def blocked_exists(path, *args, **kwargs):  # noqa: ANN001 - monkeypatch-compatible Path method
        if path == target:
            raise PermissionError("simulated inaccessible target")
        return real_exists(path)

    monkeypatch.setattr(appmod.Path, "exists", blocked_exists)

    with pytest.raises(appmod.HTTPException) as raised:
        appmod._write_text(target, "new", overwrite=False)

    assert raised.value.status_code == 500
    assert "file target" in str(raised.value.detail)
    assert not real_exists(target)


def test_queue_snapshot_counts_all_active_lifecycle_statuses() -> None:
    snapshot = appmod._build_queue_snapshot({
        "rows": [
            {"project_id": "dispatching", "queue_status": "dispatching"},
            {"project_id": "awaiting", "queue_status": "awaiting_wake"},
            {"project_id": "running", "queue_status": "running"},
            {"project_id": "wake", "queue_status": "wake_received"},
            {"project_id": "reconciling", "queue_status": "reconciling"},
            {"project_id": "queued", "queue_status": "queued"},
        ],
    })

    assert snapshot["active_count"] == 5
    assert {row["project_id"] for row in snapshot["active_rows"]} == {
        "dispatching",
        "awaiting",
        "running",
        "wake",
        "reconciling",
    }
