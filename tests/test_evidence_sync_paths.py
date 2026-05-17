from __future__ import annotations

import io
from pathlib import Path
import time
from tempfile import TemporaryDirectory
from unittest.mock import patch

from enoch_control_plane.config import GateConfig
from enoch_control_plane.control_plane.router import _local_artifact_root, _local_paper_evidence_present, _remote_evidence_dir, _sync_remote_project_evidence


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


def test_remote_evidence_dir_rejects_relative_escape(tmp_path) -> None:
    config = _config(tmp_path)

    assert _remote_evidence_dir(config, project_id="project", source_project_dir="../outside") == "/remote/projects/project"


def test_local_artifact_root_rejects_relative_project_dir_escape(tmp_path) -> None:
    config = _config(tmp_path)

    resolved = _local_artifact_root(config, project_id="project", project_dir_text="../outside")

    assert resolved == (config.expanded_project_root / "project").resolve()
    resolved.relative_to(config.expanded_project_root.resolve())


def test_local_artifact_root_rejects_unsafe_project_id_fallback(tmp_path) -> None:
    config = _config(tmp_path)

    resolved = _local_artifact_root(config, project_id="../evil project", project_dir_text="")

    assert resolved == (config.expanded_project_root / "evil-project").resolve()
    resolved.relative_to(config.expanded_project_root.resolve())


def test_local_artifact_root_rejects_symlinked_project_id_fallback(tmp_path) -> None:
    config = _config(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    config.expanded_project_root.mkdir(parents=True)
    (config.expanded_project_root / "project").symlink_to(outside, target_is_directory=True)

    resolved = _local_artifact_root(config, project_id="project", project_dir_text="")

    resolved.relative_to(config.expanded_project_root.resolve())
    assert resolved != outside.resolve()
    assert not (config.expanded_project_root / resolved.relative_to(config.expanded_project_root.resolve()).parts[0]).is_symlink()


def test_local_artifact_root_rejects_symlinked_project_dir(tmp_path) -> None:
    config = _config(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    config.expanded_project_root.mkdir(parents=True)
    (config.expanded_project_root / "runtime-link").symlink_to(outside, target_is_directory=True)

    resolved = _local_artifact_root(config, project_id="project", project_dir_text="runtime-link")

    resolved.relative_to(config.expanded_project_root.resolve())
    assert resolved != outside.resolve()




def test_local_paper_evidence_rejects_symlinked_high_signal_files(tmp_path) -> None:
    project_dir = tmp_path / "project"
    external = tmp_path / "external"
    (project_dir / ".enoch").mkdir(parents=True)
    external.mkdir()
    (external / "run_notes.md").write_text("external notes", encoding="utf-8")
    (external / "project_decision.json").write_text('{"project_decision":"finalize_positive"}', encoding="utf-8")
    (project_dir / "run_notes.md").symlink_to(external / "run_notes.md")
    (project_dir / ".enoch" / "project_decision.json").symlink_to(external / "project_decision.json")

    assert _local_paper_evidence_present(project_dir) is False


def test_local_paper_evidence_rejects_symlinked_paper_and_result_files(tmp_path) -> None:
    project_dir = tmp_path / "project"
    external = tmp_path / "external"
    (project_dir / "papers" / "run-1").mkdir(parents=True)
    (project_dir / "results").mkdir()
    external.mkdir()
    (external / "evidence_bundle.json").write_text("{}", encoding="utf-8")
    (external / "smoke.json").write_text("{}", encoding="utf-8")
    (project_dir / "papers" / "run-1" / "evidence_bundle.json").symlink_to(external / "evidence_bundle.json")
    (project_dir / "results" / "smoke.json").symlink_to(external / "smoke.json")

    assert _local_paper_evidence_present(project_dir) is False

def test_local_paper_evidence_requires_notes_with_result_files(tmp_path) -> None:
    project_dir = tmp_path / "project"
    (project_dir / "results").mkdir(parents=True)
    (project_dir / "results" / "smoke.json").write_text("{}", encoding="utf-8")

    assert _local_paper_evidence_present(project_dir) is False

    (project_dir / "run_notes.md").write_text("measured result notes", encoding="utf-8")

    assert _local_paper_evidence_present(project_dir) is True


def test_sync_remote_evidence_skips_ssh_after_http_sync_has_required_local_evidence(tmp_path) -> None:
    config = _config(tmp_path)
    artifact_root = tmp_path / "artifact"

    def fake_http_sync(config, *, project_id: str, artifact_root, source_run_id: str = ""):
        del config, project_id, source_run_id
        (artifact_root / ".enoch").mkdir(parents=True)
        (artifact_root / "run_notes.md").write_text("measured evidence\n", encoding="utf-8")
        (artifact_root / ".enoch" / "project_decision.json").write_text('{"decision":"positive"}', encoding="utf-8")
        return {"ok": True, "reason": "worker_http_synced", "files": 2}

    with patch("enoch_control_plane.control_plane.router._sync_worker_http_evidence", side_effect=fake_http_sync):
        with patch("enoch_control_plane.control_plane.router.subprocess.Popen", side_effect=AssertionError("ssh should not run after complete HTTP evidence sync")):
            result = _sync_remote_project_evidence(config, project_id="project", artifact_root=artifact_root)

    assert result["synced"] is True
    assert result["reason"] == "worker_http_synced"
    assert result["method"] == "worker_http"


class _FakeStartedProcess:
    def __init__(self) -> None:
        self.stdout = io.BytesIO(b"")
        self.stderr = io.BytesIO(b"")
        self.killed = False

    def kill(self) -> None:
        self.killed = True

    def poll(self):
        return -9 if self.killed else None

    def wait(self, timeout=None):  # noqa: ANN001 - subprocess-compatible test double
        del timeout
        return -9 if self.killed else 0


def test_sync_remote_evidence_kills_started_ssh_when_tar_spawn_fails(tmp_path) -> None:
    config = _config(tmp_path)
    artifact_root = tmp_path / "artifact"
    ssh_proc = _FakeStartedProcess()

    with patch("enoch_control_plane.control_plane.router._sync_worker_http_evidence", return_value={"ok": False, "reason": "worker_read_failed"}):
        with patch("enoch_control_plane.control_plane.router.subprocess.Popen", side_effect=[ssh_proc, OSError("tar missing")]):
            result = _sync_remote_project_evidence(config, project_id="project", artifact_root=artifact_root)

    assert result["reason"] == "spawn_failed"
    assert ssh_proc.killed is True

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


def test_sync_worker_http_evidence_rejects_worker_returned_escape_paths(tmp_path) -> None:
    from enoch_control_plane.control_plane.router import _sync_worker_http_evidence
    from enoch_control_plane.control_plane.worker_adapter import HttpResult

    config = _config(tmp_path)
    config.worker_wake_gate_bearer_token = "worker-token"
    config.worker_wake_gate_url = "http://worker"
    artifact_root = tmp_path / "artifact"
    outside = tmp_path / "outside.txt"

    def fake_post_worker_json(base_url, path, token, payload):  # noqa: ANN001 - matches patched function
        del base_url, path, token, payload
        return HttpResult(ok=True, status=200, body={"files": [{"path": "../outside.txt", "content": "escape"}]})

    with patch("enoch_control_plane.control_plane.router.post_worker_json", side_effect=fake_post_worker_json):
        result = _sync_worker_http_evidence(config, project_id="project", artifact_root=artifact_root)

    assert result["ok"] is False
    assert result["reason"] == "worker_read_failed"
    assert not outside.exists()
    assert any(item["status"] == "unsafe_path" for item in result["skipped"])


def test_sync_remote_evidence_reports_failed_when_successful_tar_has_no_required_evidence(tmp_path) -> None:
    config = _config(tmp_path)
    artifact_root = tmp_path / "artifact"

    class FakeSshProcess:
        def __init__(self) -> None:
            self.stdout = io.BytesIO(b"")
            self.stderr = io.BytesIO(b"")
            self.returncode = 0

        def wait(self, timeout=None):  # noqa: ANN001 - subprocess-compatible test double
            del timeout
            return 0

        def poll(self):
            return 0

    class FakeTarProcess:
        def __init__(self) -> None:
            self.returncode = 0

        def communicate(self, timeout=None):  # noqa: ANN001 - subprocess-compatible test double
            del timeout
            return b"", b""

        def wait(self, timeout=None):  # noqa: ANN001 - subprocess-compatible test double
            del timeout
            return 0

        def poll(self):
            return 0

    with patch("enoch_control_plane.control_plane.router._sync_worker_http_evidence", return_value={"ok": False, "reason": "worker_read_failed"}):
        with patch("enoch_control_plane.control_plane.router.subprocess.Popen", side_effect=[FakeSshProcess(), FakeTarProcess()]):
            result = _sync_remote_project_evidence(config, project_id="project", artifact_root=artifact_root)

    assert result["method"] == "worker_http+ssh"
    assert result["synced"] is False
    assert result["local_evidence_present"] is False
    assert result["reason"] == "synced_without_required_evidence"


def test_sync_worker_http_evidence_skips_empty_worker_paths(tmp_path) -> None:
    from enoch_control_plane.control_plane.router import _sync_worker_http_evidence
    from enoch_control_plane.control_plane.worker_adapter import HttpResult

    config = _config(tmp_path)
    config.worker_wake_gate_bearer_token = "worker-token"
    config.worker_wake_gate_url = "http://worker"
    artifact_root = tmp_path / "artifact"

    def fake_post_worker_json(base_url, path, token, payload):  # noqa: ANN001 - matches patched function
        del base_url, path, token, payload
        return HttpResult(ok=True, status=200, body={"files": [{"path": "", "content": "bad"}, {"path": ".", "content": "bad"}]})

    with patch("enoch_control_plane.control_plane.router.post_worker_json", side_effect=fake_post_worker_json):
        result = _sync_worker_http_evidence(config, project_id="project", artifact_root=artifact_root)

    assert result["ok"] is False
    assert result["reason"] == "worker_read_failed"
    assert any(item["status"] == "unsafe_path" for item in result["skipped"])


def test_sync_worker_http_evidence_skips_invalid_worker_path_bytes(tmp_path) -> None:
    from enoch_control_plane.control_plane.router import _sync_worker_http_evidence
    from enoch_control_plane.control_plane.worker_adapter import HttpResult

    config = _config(tmp_path)
    config.worker_wake_gate_bearer_token = "worker-token"
    config.worker_wake_gate_url = "http://worker"

    def fake_post_worker_json(base_url, path, token, payload):  # noqa: ANN001 - matches patched function
        del base_url, path, token, payload
        return HttpResult(ok=True, status=200, body={"files": [{"path": "bad\x00file.json", "content": "bad"}]})

    with patch("enoch_control_plane.control_plane.router.post_worker_json", side_effect=fake_post_worker_json):
        result = _sync_worker_http_evidence(config, project_id="project", artifact_root=tmp_path / "artifact")

    assert result["ok"] is False
    assert any(item["status"] == "unsafe_path" for item in result["skipped"])


def test_sync_worker_http_evidence_reports_unusable_artifact_root(tmp_path) -> None:
    from enoch_control_plane.control_plane.router import _sync_worker_http_evidence

    config = _config(tmp_path)
    config.worker_wake_gate_bearer_token = "worker-token"
    config.worker_wake_gate_url = "http://worker"
    artifact_root = tmp_path / "artifact"
    artifact_root.write_text("not a directory", encoding="utf-8")

    result = _sync_worker_http_evidence(config, project_id="project", artifact_root=artifact_root)

    assert result["ok"] is False
    assert result["reason"] == "artifact_root_unusable"


def test_sync_worker_http_evidence_preserves_existing_file_when_write_fails(tmp_path, monkeypatch) -> None:
    config = _config(tmp_path)
    config.worker_wake_gate_bearer_token = "worker-token"
    artifact_root = tmp_path / "artifact"
    artifact_root.mkdir()
    target = artifact_root / "run_notes.md"
    target.write_text("old evidence", encoding="utf-8")

    class Result:
        ok = True
        status = 200
        error = ""
        body = {"files": [{"path": "run_notes.md", "content": "new evidence"}]}

    import enoch_control_plane.control_plane.router as router

    monkeypatch.setattr(router, "post_worker_json", lambda *args, **kwargs: Result())
    monkeypatch.setattr(router, "_atomic_write_text", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("simulated evidence write failure")))

    try:
        router._sync_worker_http_evidence(config, project_id="project", artifact_root=artifact_root)
    except OSError:
        pass

    assert target.read_text(encoding="utf-8") == "old evidence"


def test_worker_http_evidence_sync_times_out_slow_worker_reads(tmp_path, monkeypatch):
    from enoch_control_plane.config import GateConfig
    from enoch_control_plane.control_plane import router
    from enoch_control_plane.control_plane.worker_adapter import HttpResult

    calls = []

    def slow_post_worker_json(*args, **kwargs):  # noqa: ANN001 - patched worker transport
        calls.append((args, kwargs))
        time.sleep(0.2)
        return HttpResult(ok=True, status=200, body={"files": []})

    monkeypatch.setattr(router, "post_worker_json", slow_post_worker_json)
    config = GateConfig(
        state_dir=str(tmp_path / "state"),
        project_root=str(tmp_path / "projects"),
        dispatch_script_path=str(tmp_path / "dispatch.sh"),
        control_api_bearer_token="token",
        completion_callback_url="http://example.invalid/callback",
        completion_callback_token="unused",
        worker_wake_gate_url="http://worker.example:8787",
        worker_wake_gate_bearer_token="worker-token",
    )

    started = time.monotonic()
    result = router._sync_worker_http_evidence(
        config,
        project_id="slow-project",
        artifact_root=tmp_path / "artifact-root",
        per_request_timeout_seconds=0.01,
        overall_timeout_seconds=0.05,
    )
    elapsed = time.monotonic() - started

    assert elapsed < 0.15
    assert result["ok"] is False
    assert result["reason"] == "no_worker_http_evidence"
    assert result["timeouts"] >= 1
    assert any(item.get("status") == "timeout" for item in result["skipped"])
