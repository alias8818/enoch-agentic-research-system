from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

import enoch_control_plane.app as appmod
from enoch_control_plane.models import GateState, ProcessInfo, RunRecord, TelemetrySample


class FakeStore:
    def __init__(self, root: Path) -> None:
        self.events_log = root / "events.jsonl"
        self.events: list[dict] = []
        self.saved: dict[str, RunRecord] = {}
        self.records = [
            RunRecord(run_id="run-live", session_id="session-live", project_id="project-a", project_name="Project A", gate_state=GateState.RUNNING, project_dir=str(root / "project-a")),
            RunRecord(run_id="run-ready", session_id="session-ready", project_id="project-b", project_name="Project B", gate_state=GateState.WAKE_READY, last_event_at="2026-01-01T00:00:00Z"),
        ]
    def list_runs(self):
        return list(self.records)
    def load_run(self, run_id):
        return next((record for record in self.records if record.run_id == run_id), None)
    def save_run(self, record):
        self.saved[record.run_id] = record
    def append_event(self, event):
        self.events.append(event)


class FakeTracker:
    def describe_processes(self, record):
        if record.run_id == "run-live":
            return [ProcessInfo(pid=12, cmdline="python worker.py")]
        return []
    def snapshot(self, record, gpu_compute_pids=None):
        from enoch_control_plane.models import ProcessSnapshot
        return ProcessSnapshot()
    def reap_stale_project_processes(self, *args, **kwargs):
        return []


def _client(tmp_path: Path, monkeypatch) -> TestClient:
    token = appmod.config.control_api_bearer_token
    monkeypatch.setattr(appmod.config, "project_root", str(tmp_path))
    monkeypatch.setattr(appmod.config, "state_dir", str(tmp_path / "state"))
    fake_store = FakeStore(tmp_path)
    fake_store.events_log.parent.mkdir(parents=True, exist_ok=True)
    fake_store.events_log.write_text(json.dumps({"kind": "event", "run_id": "run-live", "payload": "x" * 2000}) + "\n")
    monkeypatch.setattr(appmod, "store", fake_store)
    monkeypatch.setattr(appmod.telemetry, "sample", lambda: TelemetrySample(cpu_pct=1, gpu_pct=2, memory_source="uma_meminfo", uma_allocatable_mib=1234))
    monkeypatch.setattr(appmod.gate, "process_tracker", FakeTracker())
    return TestClient(appmod.app), token


def test_dashboard_api_and_run_detail_endpoint(tmp_path: Path, monkeypatch) -> None:
    client, token = _client(tmp_path, monkeypatch)
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "queue_snapshot.json").write_text(json.dumps({"total": 1, "rows": []}))
    (tmp_path / "state" / "paper_snapshot.json").write_text(json.dumps({"total": 2, "rows": []}))

    unauthorized = client.get("/dashboard/api")
    assert unauthorized.status_code == 401
    response = client.get(f"/dashboard/api?token={token}&detail=true&event_limit=5")
    assert response.status_code == 200
    data = response.json()
    assert data["totals"]["runs"] == 2
    assert data["queue"]["total"] == 1
    assert data["papers"]["total"] == 2
    assert {row["run_id"] for row in data["runs"]} == {"run-live", "run-ready"}

    run = client.get("/dashboard/api/run/run-live", headers={"Authorization": f"Bearer {token}"})
    assert run.status_code == 200
    assert run.json()["run"]["run_id"] == "run-live"
    assert client.get("/dashboard/api/run/missing", headers={"Authorization": f"Bearer {token}"}).status_code == 404


def test_dashboard_run_detail_treats_unexpandable_project_dir_as_unreadable(tmp_path: Path, monkeypatch) -> None:
    client, token = _client(tmp_path, monkeypatch)
    fake_store = appmod.store
    fake_store.records.append(
        RunRecord(
            run_id="run-unexpandable",
            session_id="session-unexpandable",
            project_id="project-unexpandable",
            project_name="Project Unexpandable",
            gate_state=GateState.WAKE_READY,
            project_dir="~enoch-user-that-should-not-exist/project",
        )
    )

    run = client.get("/dashboard/api/run/run-unexpandable", headers={"Authorization": f"Bearer {token}"})

    assert run.status_code == 200
    body = run.json()["run"]
    assert body["run_id"] == "run-unexpandable"
    assert body["latest_session"] is None
    assert body["run_notes_tail"] == []


def test_dashboard_run_detail_does_not_read_project_dir_outside_root(tmp_path: Path, monkeypatch) -> None:
    client, token = _client(tmp_path, monkeypatch)
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    try:
        (outside / "run_notes.md").write_text("outside secret note\n", encoding="utf-8")
        fake_store = appmod.store
        fake_store.records.append(
            RunRecord(
                run_id="run-outside",
                session_id="session-outside",
                project_id="project-outside",
                project_name="Project Outside",
                gate_state=GateState.WAKE_READY,
                project_dir=str(outside),
            )
        )

        run = client.get("/dashboard/api/run/run-outside", headers={"Authorization": f"Bearer {token}"})

        assert run.status_code == 200
        body = run.json()["run"]
        assert body["run_id"] == "run-outside"
        assert body["run_notes_tail"] == []
        assert body["recent_files"] == []
    finally:
        (outside / "run_notes.md").unlink(missing_ok=True)
        outside.rmdir()


def test_dashboard_snapshot_writes_preserve_existing_files_on_replace_failure(tmp_path: Path, monkeypatch) -> None:
    client, token = _client(tmp_path, monkeypatch)
    headers = {"Authorization": f"Bearer {token}"}
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    queue_path = state_dir / "queue_snapshot.json"
    paper_path = state_dir / "paper_snapshot.json"
    queue_path.write_text("old queue", encoding="utf-8")
    paper_path.write_text("old paper", encoding="utf-8")

    real_replace = appmod.os.replace

    def flaky_replace(src, dst) -> None:
        if Path(dst) in {queue_path, paper_path}:
            raise OSError("simulated atomic replace failure")
        real_replace(src, dst)

    monkeypatch.setattr(appmod.os, "replace", flaky_replace)

    failing = TestClient(appmod.app, raise_server_exceptions=False)
    queue_response = failing.post("/dashboard/queue-snapshot", headers=headers, json={"rows": [], "total": 0})
    paper_response = failing.post("/dashboard/paper-snapshot", headers=headers, json={"rows": [], "total": 0})

    assert queue_response.status_code == 500
    assert paper_response.status_code == 500
    assert queue_path.read_text(encoding="utf-8") == "old queue"
    assert paper_path.read_text(encoding="utf-8") == "old paper"
    assert not list(state_dir.glob(".queue_snapshot.json.*.tmp"))
    assert not list(state_dir.glob(".paper_snapshot.json.*.tmp"))


def test_prepare_project_metadata_preserves_existing_file_on_replace_failure(tmp_path: Path, monkeypatch) -> None:
    client, token = _client(tmp_path, monkeypatch)
    headers = {"Authorization": f"Bearer {token}"}
    project_dir = tmp_path / "project-a"
    metadata_path = project_dir / ".enoch" / "project.json"
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.write_text("old metadata", encoding="utf-8")

    real_replace = appmod.os.replace

    def flaky_replace(src, dst) -> None:
        if Path(dst) == metadata_path:
            raise OSError("simulated atomic replace failure")
        real_replace(src, dst)

    monkeypatch.setattr(appmod.os, "replace", flaky_replace)

    failing = TestClient(appmod.app, raise_server_exceptions=False)
    response = failing.post("/prepare-project", headers=headers, json={
        "run_id": "run-live",
        "project_id": "project-a",
        "project_name": "Project A",
        "project_dir": "project-a",
        "prompt_file": "project-a/prompt.md",
        "prompt_text": "Do work",
        "metadata": {"workload_class": "training"},
        "overwrite": True,
    })

    assert response.status_code == 500
    assert metadata_path.read_text(encoding="utf-8") == "old metadata"
    assert not list(metadata_path.parent.glob(".project.json.*.tmp"))


def test_prepare_project_status_and_paper_artifact_endpoints(tmp_path: Path, monkeypatch) -> None:
    client, token = _client(tmp_path, monkeypatch)
    headers = {"Authorization": f"Bearer {token}"}
    payload = {
        "run_id": "run-live",
        "project_id": "project-a",
        "project_name": "Project A",
        "project_dir": "project-a",
        "prompt_file": "project-a/prompt.md",
        "prompt_text": "Do work",
        "resume_prompt_file": "project-a/resume.md",
        "resume_prompt_text": "Resume work",
        "metadata": {"workload_class": "training"},
        "overwrite": True,
    }
    prepared = client.post("/prepare-project", headers=headers, json=payload)
    assert prepared.status_code == 200
    project_dir = tmp_path / "project-a"
    assert (project_dir / ".enoch" / "project.json").exists()
    (project_dir / "run_notes.md").write_text("line1\nline2\n")
    (project_dir / ".enoch" / "project_decision.json").write_text(json.dumps({"project_decision": "continue"}))

    status = client.get("/project-status/project-a", headers=headers)
    assert status.status_code == 200
    body = status.json()
    assert body["available"] is True
    assert body["current_activity"] == "running python worker.py"
    assert body["project_decision"]["project_decision"] == "continue"

    written = client.post("/project-paper/project-a", headers=headers, json={"run_id": "run-live", "paper_id": "paper-1", "files": [{"path": "papers/run-live/draft.md", "content": "# Draft"}], "overwrite": False})
    assert written.status_code == 200
    assert written.json()["manifest_path"] == "papers/run-live/paper_manifest.json"

    escaped_manifest = client.post("/project-paper/project-a", headers=headers, json={"run_id": "../escape", "paper_id": "paper-escape", "files": [], "overwrite": True})
    assert escaped_manifest.status_code == 400
    assert not (tmp_path / "escape" / "paper_manifest.json").exists()

    read = client.post("/project-paper/project-a/read", headers=headers, json={"paths": ["papers/run-live/draft.md"], "max_bytes_per_file": 1000})
    assert read.status_code == 200
    assert read.json()["files"][0]["content"] == "# Draft"

    preview = client.get(f"/dashboard/api/paper-artifact/project-a?token={token}&path=papers/run-live/draft.md")
    assert preview.status_code == 200
    assert preview.json()["content"] == "# Draft"
    bad_preview = client.get(f"/dashboard/api/paper-artifact/project-a?token={token}&path=bad%00path")
    assert bad_preview.status_code == 400
    html = client.get(f"/dashboard/paper-artifact/project-a?token={token}&path=papers/run-live/draft.md")
    assert html.status_code == 200
    assert "# Draft" in html.text


def test_dispatch_endpoint_handles_success_and_bad_output(tmp_path: Path, monkeypatch) -> None:
    client, token = _client(tmp_path, monkeypatch)
    headers = {"Authorization": f"Bearer {token}"}
    project = tmp_path / "project-a"
    (project / ".enoch").mkdir(parents=True)
    (project / ".enoch" / "project.json").write_text(json.dumps({"metadata": {"workload_class": "training"}}))
    prompt = project / "prompt.md"
    prompt.write_text("prompt")
    script = tmp_path / "dispatch.sh"
    script.write_text("#!/bin/sh\n")
    script.chmod(0o755)
    monkeypatch.setattr(appmod.config, "dispatch_script_path", str(script))

    monkeypatch.setattr(appmod.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=json.dumps({"pid": 123, "pgid": 456}), stderr=""))
    response = client.post("/dispatch", headers=headers, json={"run_id": "run-live", "project_id": "project-a", "project_dir": "project-a", "prompt_file": "project-a/prompt.md", "mode": "exec"})
    assert response.status_code == 200
    assert response.json()["dispatch"]["pid"] == 123

    monkeypatch.setattr(appmod.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=2, stdout="", stderr="bad"))
    failed = client.post("/dispatch", headers=headers, json={"run_id": "run-live", "project_id": "project-a", "project_dir": "project-a", "prompt_file": "project-a/prompt.md", "mode": "exec"})
    assert failed.status_code == 502

    monkeypatch.setattr(appmod.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="not-json", stderr=""))
    bad_json = client.post("/dispatch", headers=headers, json={"run_id": "run-live", "project_id": "project-a", "project_dir": "project-a", "prompt_file": "project-a/prompt.md", "mode": "exec"})
    assert bad_json.status_code == 502

import asyncio
from enoch_control_plane.models import GateCallback, ProcessSnapshot, SourceEvent
from enoch_control_plane import callback_outbox



def test_dispatch_rejects_unsafe_run_id_and_log_dir_escape(tmp_path: Path, monkeypatch) -> None:
    client, token = _client(tmp_path, monkeypatch)
    headers = {"Authorization": f"Bearer {token}"}
    project = tmp_path / "project-a"
    (project / ".enoch").mkdir(parents=True)
    (project / "prompt.md").write_text("prompt")
    script = tmp_path / "dispatch.sh"
    script.write_text("#!/bin/sh\n")
    script.chmod(0o755)
    monkeypatch.setattr(appmod.config, "dispatch_script_path", str(script))
    monkeypatch.setattr(appmod.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=json.dumps({"pid": 1, "pgid": 1}), stderr=""))

    unsafe_run = client.post(
        "/dispatch",
        headers=headers,
        json={
            "run_id": "../escape",
            "project_id": "project-a",
            "project_dir": "project-a",
            "prompt_file": "project-a/prompt.md",
            "mode": "exec",
        },
    )
    assert unsafe_run.status_code == 422

    escaped_log_dir = client.post(
        "/dispatch",
        headers=headers,
        json={
            "run_id": "run-live",
            "project_id": "project-a",
            "project_dir": "project-a",
            "prompt_file": "project-a/prompt.md",
            "mode": "exec",
            "log_dir": "../outside-logs",
        },
    )
    assert escaped_log_dir.status_code == 400

def test_callback_outbox_replay_and_reaper_async_helpers(tmp_path: Path, monkeypatch) -> None:
    client, token = _client(tmp_path, monkeypatch)
    fake_store = appmod.store
    results = [callback_outbox.DeliveryResult(ok=True, status_code=200, detail="ok", path="p")]
    monkeypatch.setattr(appmod.callback_outbox, "replay_pending", lambda **kwargs: results)
    asyncio.run(appmod._replay_callback_outbox_once())
    assert fake_store.events[-1]["kind"] == "callback_outbox_replay"

    monkeypatch.setattr(appmod.gate, "reap_stale_project_processes", lambda record: [{"pid": 99, "cmdline": "python"}])
    asyncio.run(appmod._reap_and_log_stale_project_processes(RunRecord(run_id="run", session_id="s", project_id="p")))
    assert fake_store.events[-1]["kind"] == "stale_project_process_reaped"

    monkeypatch.setattr(appmod.gate, "reap_stale_project_processes", lambda record: [])
    count = len(fake_store.events)
    asyncio.run(appmod._reap_and_log_stale_project_processes(RunRecord(run_id="run", session_id="s", project_id="p")))
    assert len(fake_store.events) == count


def test_evaluate_until_ready_retry_timeout_and_callback_paths(tmp_path: Path, monkeypatch) -> None:
    _client(tmp_path, monkeypatch)
    fake_store = appmod.store

    async def _ok(callback):
        return True, "200:ok"

    async def _fail(callback):
        return False, "500:bad"

    # Callback-ready retry path.
    retry_record = RunRecord(run_id="retry", session_id="s", project_id="p", gate_state=GateState.WAKE_READY, last_event_at="seen")
    fake_store.records = [retry_record]
    monkeypatch.setattr(appmod, "_deliver_callback", _ok)
    asyncio.run(appmod._evaluate_until_ready("retry"))
    assert fake_store.saved["retry"].last_idempotency_key == "retry:wake_ready:seen"
    assert any(event["kind"] == "callback_retry" for event in fake_store.events)

    # Timeout path.
    timeout_record = RunRecord(run_id="timeout", session_id="s", project_id="p", gate_state=GateState.PENDING_IDLE_GATE, idle_seen_at="2026-01-01T00:00:00+00:00", last_event_at="seen")
    fake_store.records = [timeout_record]
    fake_store.events.clear()
    monkeypatch.setattr(appmod, "_deliver_callback", _fail)
    asyncio.run(appmod._evaluate_until_ready("timeout"))
    assert fake_store.saved["timeout"].gate_state == GateState.ERROR
    assert any(event["event_type"] == "gate_timeout" for event in fake_store.events)

    # Normal gate callback path.
    callback_record = RunRecord(run_id="callback", session_id="s", project_id="p", gate_state=GateState.PENDING_IDLE_GATE, idle_seen_at="idle", last_event_at="idle", last_event=SourceEvent.SESSION_IDLE)
    gate_callback = GateCallback(
        event_type="wake_ready",
        run_id="callback",
        session_id="s",
        project_id="p",
        project_name="P",
        source_event="session-idle",
        gate_state="wake_ready",
        idle_seen_at="idle",
        process_tracking=ProcessSnapshot(),
        telemetry={},
        reason="quiet",
        idempotency_key="callback:wake_ready:idle",
    )
    fake_store.records = [callback_record]
    fake_store.events.clear()
    monkeypatch.setattr(appmod.gate, "is_timed_out", lambda record: False)
    monkeypatch.setattr(appmod.gate, "evaluate", lambda record: (record.model_copy(update={"gate_state": GateState.WAKE_READY}), gate_callback))
    monkeypatch.setattr(appmod, "_deliver_callback", _ok)
    asyncio.run(appmod._evaluate_until_ready("callback"))
    assert fake_store.saved["callback"].last_idempotency_key == "callback:wake_ready:idle"
    assert any(event["kind"] == "callback_attempt" for event in fake_store.events)

    # Missing run exits cleanly and pops task registry if present.
    fake_store.records = []
    appmod.evaluation_tasks["missing"] = SimpleNamespace(done=lambda: True)
    asyncio.run(appmod._evaluate_until_ready("missing"))
    assert "missing" not in appmod.evaluation_tasks


def test_misc_endpoint_error_branches(tmp_path: Path, monkeypatch) -> None:
    client, token = _client(tmp_path, monkeypatch)
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/healthz").json()["ok"] is True
    assert client.get("/dashboard").status_code == 200
    assert client.get("/favicon.ico").status_code in {200, 204}

    project = tmp_path / "project-a"
    (project / ".enoch").mkdir(parents=True)
    (project / ".enoch" / "project.json").write_text(json.dumps({"metadata": {"workload_class": "training"}}))
    (project / "prompt.md").write_text("prompt")

    monkeypatch.setattr(appmod.config, "dispatch_script_path", str(tmp_path / "missing-dispatch.sh"))
    missing_script = client.post("/dispatch", headers=headers, json={"run_id": "run-live", "project_id": "project-a", "project_dir": "project-a", "prompt_file": "project-a/prompt.md", "mode": "exec"})
    assert missing_script.status_code == 500

    script = tmp_path / "dispatch.sh"
    script.write_text("#!/bin/sh\n")
    script.chmod(0o755)
    monkeypatch.setattr(appmod.config, "dispatch_script_path", str(script))
    def _timeout(*args, **kwargs):
        raise appmod.subprocess.TimeoutExpired(cmd="dispatch", timeout=1)
    monkeypatch.setattr(appmod.subprocess, "run", _timeout)
    timed_out = client.post("/dispatch", headers=headers, json={"run_id": "run-live", "project_id": "project-a", "project_dir": "project-a", "prompt_file": "project-a/prompt.md", "mode": "exec"})
    assert timed_out.status_code == 504

    assert client.post("/project-paper/project-a/read", headers=headers, json={"paths": ["x"] * 21}).status_code == 400
    assert client.post("/project-paper/project-a/read", headers=headers, json={"paths": ["missing.md"]}).status_code == 404
    big = project / "big.md"
    big.write_text("abcdef")
    assert client.post("/project-paper/project-a/read", headers=headers, json={"paths": ["big.md"], "max_bytes_per_file": 1}).status_code == 413
    binary = project / "binary.md"
    binary.write_bytes(b"\xff\xfe")
    assert client.post("/project-paper/project-a/read", headers=headers, json={"paths": ["binary.md"]}).status_code == 415

    unreadable = project / "unreadable.md"
    unreadable.write_text("secret", encoding="utf-8")
    real_read_text = appmod.Path.read_text

    def blocked_read_text(path, *args, **kwargs):  # noqa: ANN001 - monkeypatch-compatible Path method
        if path == unreadable:
            raise PermissionError("simulated unreadable paper artifact")
        return real_read_text(path, *args, **kwargs)

    monkeypatch.setattr(appmod.Path, "read_text", blocked_read_text)
    unreadable_response = client.post("/project-paper/project-a/read", headers=headers, json={"paths": ["unreadable.md"]})
    assert unreadable_response.status_code == 403

    monkeypatch.setattr(appmod.Path, "read_text", real_read_text)
    real_stat = appmod.Path.stat

    def blocked_stat(path, *args, **kwargs):  # noqa: ANN001 - monkeypatch-compatible Path method
        if path == unreadable:
            raise PermissionError("simulated unreadable paper artifact stat")
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(appmod.Path, "stat", blocked_stat)
    unreadable_preview = client.get(f"/dashboard/api/paper-artifact/project-a?token={token}&path=unreadable.md")
    assert unreadable_preview.status_code == 403

    monkeypatch.setattr(appmod.Path, "stat", real_stat)
    monkeypatch.setattr(appmod.Path, "read_text", blocked_read_text)
    unreadable_preview_body = client.get(f"/dashboard/api/paper-artifact/project-a?token={token}&path=unreadable.md")
    assert unreadable_preview_body.status_code == 403

    assert client.post("/project-paper/missing", headers=headers, json={"run_id": "run", "paper_id": "paper", "files": []}).status_code == 404
    assert client.post("/project-paper/project-a", headers=headers, json={"run_id": "run", "paper_id": "paper", "files": [{"path": f"p{i}.md", "content": "x"} for i in range(21)]}).status_code == 400
    assert client.post("/project-paper/project-a", headers=headers, json={"run_id": "run", "paper_id": "paper", "files": [{"path": "too-big.md", "content": "x" * 2_000_001}]}).status_code == 413



def test_paper_artifact_endpoints_reject_uninspectable_project_dir_without_raw_error(tmp_path: Path, monkeypatch) -> None:
    _, token = _client(tmp_path, monkeypatch)
    project = tmp_path / "project-a"
    project.mkdir(parents=True)
    real_exists = appmod.Path.exists
    resolved_project = project.resolve()

    def blocked_exists(path, *args, **kwargs):  # noqa: ANN001 - monkeypatch-compatible Path method
        if path == resolved_project:
            raise PermissionError("simulated inaccessible project dir")
        return real_exists(path)

    monkeypatch.setattr(appmod.Path, "exists", blocked_exists)
    client = TestClient(appmod.app, raise_server_exceptions=False)

    read_response = client.post(
        "/project-paper/project-a/read",
        headers={"Authorization": f"Bearer {token}"},
        json={"paths": ["paper.md"]},
    )
    preview_response = client.get(f"/dashboard/api/paper-artifact/project-a?token={token}&path=paper.md")

    assert read_response.status_code == 403
    assert "project directory" in read_response.json()["detail"]
    assert preview_response.status_code == 403
    assert "project directory" in preview_response.json()["detail"]


def test_evaluator_registry_does_not_duplicate_running_task(monkeypatch) -> None:
    class RunningTask:
        def __init__(self):
            self.created = 0
        def done(self):
            return False
    task = RunningTask()
    appmod.evaluation_tasks["run"] = task
    appmod._ensure_evaluator("run")
    assert appmod.evaluation_tasks["run"] is task
    appmod.evaluation_tasks.pop("run", None)
