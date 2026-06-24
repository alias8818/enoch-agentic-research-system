from __future__ import annotations

import io
import subprocess
import tarfile
import sys
import threading
from pathlib import Path
import time
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from enoch_control_plane.config import GateConfig
from enoch_control_plane.control_plane.router import (
    _extract_safe_tar_bytes,
    UnresolvableArtifactRootsError,
    _local_artifact_root,
    _local_paper_evidence_present,
    _remote_evidence_dir,
    _sync_remote_project_evidence,
)


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


def _tar_bytes(
    entries: dict[str, bytes],
    *,
    symlinks: dict[str, str] | None = None,
    hardlinks: dict[str, str] | None = None,
) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tf:
        for name, content in entries.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            tf.addfile(info, io.BytesIO(content))
        for name, target in (symlinks or {}).items():
            info = tarfile.TarInfo(name)
            info.type = tarfile.SYMTYPE
            info.linkname = target
            tf.addfile(info)
        for name, target in (hardlinks or {}).items():
            info = tarfile.TarInfo(name)
            info.type = tarfile.LNKTYPE
            info.linkname = target
            tf.addfile(info)
    return buffer.getvalue()


def test_safe_tar_extract_rejects_too_many_members(tmp_path) -> None:
    artifact_root = tmp_path / "artifact"
    entries = {f"file_{index}.txt": b"x" for index in range(600)}
    payload = _tar_bytes(entries)

    result = _extract_safe_tar_bytes(payload, artifact_root, max_entries=512)

    assert result["ok"] is False
    assert any(item["status"] == "too_many_members" for item in result["skipped"])


def test_safe_tar_extract_rejects_traversal_and_symlinks(tmp_path) -> None:
    artifact_root = tmp_path / "artifact"
    outside = tmp_path / "outside.txt"
    payload = _tar_bytes(
        {
            "run_notes.md": b"safe notes",
            "../outside.txt": b"escape",
        },
        symlinks={"results/link.json": "../outside.txt"},
    )

    result = _extract_safe_tar_bytes(payload, artifact_root)

    assert result["ok"] is True
    assert (artifact_root / "run_notes.md").read_text(encoding="utf-8") == "safe notes"
    assert not outside.exists()
    assert any(item["status"] == "unsafe_path" for item in result["skipped"])
    assert any(item["status"] == "unsupported_member" for item in result["skipped"])


def test_safe_tar_extract_python311_fallback_rejects_links(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    artifact_root = tmp_path / "artifact"
    outside = tmp_path / "outside.txt"
    payload = _tar_bytes(
        {"run_notes.md": b"safe notes"},
        symlinks={"nested/link.txt": "../outside.txt"},
        hardlinks={"nested/hardlink.txt": "run_notes.md"},
    )

    monkeypatch.delattr(tarfile, "data_filter", raising=False)

    result = _extract_safe_tar_bytes(payload, artifact_root)

    assert result["ok"] is True
    assert (artifact_root / "run_notes.md").read_text(encoding="utf-8") == "safe notes"
    assert not outside.exists()
    assert not (artifact_root / "nested" / "link.txt").exists()
    assert not (artifact_root / "nested" / "hardlink.txt").exists()
    assert len(result["skipped"]) == 2
    assert all(item["status"] == "unsafe_path" for item in result["skipped"])


def test_remote_evidence_dir_uses_relative_project_dir_over_project_id(
    tmp_path,
) -> None:
    config = _config(tmp_path)

    assert (
        _remote_evidence_dir(
            config,
            project_id="very-long-project-id-with-extra-hash",
            source_project_dir="very-long-project-id-with-extra",
        )
        == "/remote/projects/very-long-project-id-with-extra"
    )


def test_remote_evidence_dir_rejects_worker_absolute_and_ignores_local_absolute(
    tmp_path,
) -> None:
    config = _config(tmp_path)
    local_project = config.expanded_project_root / "local-artifact"
    local_project.mkdir(parents=True)

    assert (
        _remote_evidence_dir(
            config,
            project_id="project",
            source_project_dir="/home/jeremy/projects/project",
        )
        == "/remote/projects/project"
    )
    assert (
        _remote_evidence_dir(
            config, project_id="project", source_project_dir=str(local_project)
        )
        == "/remote/projects/project"
    )
    assert (
        _remote_evidence_dir(config, project_id="project", source_project_dir="")
        == "/remote/projects/project"
    )


def test_remote_evidence_dir_rejects_relative_escape(tmp_path) -> None:
    config = _config(tmp_path)

    assert (
        _remote_evidence_dir(
            config, project_id="project", source_project_dir="../outside"
        )
        == "/remote/projects/project"
    )


def test_local_artifact_root_rejects_relative_project_dir_escape(tmp_path) -> None:
    config = _config(tmp_path)

    resolved = _local_artifact_root(
        config, project_id="project", project_dir_text="../outside"
    )

    assert resolved == (config.expanded_project_root / "project").resolve()
    resolved.relative_to(config.expanded_project_root.resolve())


def test_local_artifact_root_rejects_unsafe_project_id_fallback(tmp_path) -> None:
    config = _config(tmp_path)

    resolved = _local_artifact_root(
        config, project_id="../evil project", project_dir_text=""
    )

    assert resolved == (config.expanded_project_root / "evil-project").resolve()
    resolved.relative_to(config.expanded_project_root.resolve())


def test_local_artifact_root_rejects_symlinked_project_id_fallback(tmp_path) -> None:
    config = _config(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    config.expanded_project_root.mkdir(parents=True)
    (config.expanded_project_root / "project").symlink_to(
        outside, target_is_directory=True
    )

    resolved = _local_artifact_root(config, project_id="project", project_dir_text="")

    resolved.relative_to(config.expanded_project_root.resolve())
    assert resolved != outside.resolve()
    assert not (
        config.expanded_project_root
        / resolved.relative_to(config.expanded_project_root.resolve()).parts[0]
    ).is_symlink()


def test_local_artifact_root_rejects_symlinked_project_dir(tmp_path) -> None:
    config = _config(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    config.expanded_project_root.mkdir(parents=True)
    (config.expanded_project_root / "runtime-link").symlink_to(
        outside, target_is_directory=True
    )

    resolved = _local_artifact_root(
        config, project_id="project", project_dir_text="runtime-link"
    )

    resolved.relative_to(config.expanded_project_root.resolve())
    assert resolved != outside.resolve()


def test_local_artifact_root_fails_closed_when_project_and_state_roots_unresolvable(
    tmp_path, monkeypatch
) -> None:
    config = _config(tmp_path)

    def fail_resolve(self):  # noqa: ANN001 - monkeypatch Path boundary
        raise OSError("unresolvable")

    monkeypatch.setattr(Path, "resolve", fail_resolve)
    with pytest.raises(UnresolvableArtifactRootsError) as exc:
        _local_artifact_root(config, project_id="project", project_dir_text="")

    assert "artifact roots" in str(exc.value)


def test_local_paper_evidence_rejects_symlinked_high_signal_files(tmp_path) -> None:
    project_dir = tmp_path / "project"
    external = tmp_path / "external"
    (project_dir / ".enoch").mkdir(parents=True)
    external.mkdir()
    (external / "run_notes.md").write_text("external notes", encoding="utf-8")
    (external / "project_decision.json").write_text(
        '{"project_decision":"finalize_positive"}', encoding="utf-8"
    )
    (project_dir / "run_notes.md").symlink_to(external / "run_notes.md")
    (project_dir / ".enoch" / "project_decision.json").symlink_to(
        external / "project_decision.json"
    )

    assert _local_paper_evidence_present(project_dir) is False


def test_local_paper_evidence_rejects_symlinked_paper_and_result_files(
    tmp_path,
) -> None:
    project_dir = tmp_path / "project"
    external = tmp_path / "external"
    (project_dir / "papers" / "run-1").mkdir(parents=True)
    (project_dir / "results").mkdir()
    external.mkdir()
    (external / "evidence_bundle.json").write_text("{}", encoding="utf-8")
    (external / "smoke.json").write_text("{}", encoding="utf-8")
    (project_dir / "papers" / "run-1" / "evidence_bundle.json").symlink_to(
        external / "evidence_bundle.json"
    )
    (project_dir / "results" / "smoke.json").symlink_to(external / "smoke.json")

    assert _local_paper_evidence_present(project_dir) is False


def test_local_paper_evidence_treats_uninspectable_paper_dir_as_absent(
    tmp_path, monkeypatch
) -> None:
    project_dir = tmp_path / "project"
    papers_dir = project_dir / "papers"
    papers_dir.mkdir(parents=True)
    real_exists = Path.exists

    def blocked_exists(path: Path) -> bool:
        if path == papers_dir:
            raise PermissionError("simulated paper dir access failure")
        return real_exists(path)

    monkeypatch.setattr(Path, "exists", blocked_exists)

    assert _local_paper_evidence_present(project_dir) is False


def test_local_paper_evidence_treats_uninspectable_results_dir_as_absent(
    tmp_path, monkeypatch
) -> None:
    project_dir = tmp_path / "project"
    (project_dir / "run_notes.md").parent.mkdir(parents=True)
    (project_dir / "run_notes.md").write_text("measured notes", encoding="utf-8")
    results_dir = project_dir / "results"
    results_dir.mkdir()
    real_exists = Path.exists

    def blocked_exists(path: Path) -> bool:
        if path == results_dir:
            raise PermissionError("simulated results dir access failure")
        return real_exists(path)

    monkeypatch.setattr(Path, "exists", blocked_exists)

    assert _local_paper_evidence_present(project_dir) is False


def test_local_paper_evidence_rejects_empty_high_signal_files(tmp_path) -> None:
    project_dir = tmp_path / "project"
    (project_dir / ".enoch").mkdir(parents=True)
    (project_dir / "run_notes.md").write_text("", encoding="utf-8")
    (project_dir / ".enoch" / "project_decision.json").write_text("", encoding="utf-8")

    assert _local_paper_evidence_present(project_dir) is False


def test_local_paper_evidence_requires_notes_with_result_files(tmp_path) -> None:
    project_dir = tmp_path / "project"
    (project_dir / "results").mkdir(parents=True)
    (project_dir / "results" / "smoke.json").write_text("{}", encoding="utf-8")

    assert _local_paper_evidence_present(project_dir) is False

    (project_dir / "run_notes.md").write_text("measured result notes", encoding="utf-8")

    assert _local_paper_evidence_present(project_dir) is True


def test_sync_remote_evidence_skips_ssh_after_http_sync_has_required_local_evidence(
    tmp_path,
) -> None:
    config = _config(tmp_path)
    artifact_root = tmp_path / "artifact"

    def fake_http_sync(
        config, *, project_id: str, artifact_root, source_run_id: str = "", **_kwargs
    ):
        del config, project_id, source_run_id
        (artifact_root / ".enoch").mkdir(parents=True)
        (artifact_root / "run_notes.md").write_text(
            "measured evidence\n", encoding="utf-8"
        )
        (artifact_root / ".enoch" / "project_decision.json").write_text(
            '{"decision":"positive"}', encoding="utf-8"
        )
        return {"ok": True, "reason": "worker_http_synced", "files": 2}

    with patch(
        "enoch_control_plane.control_plane.router._sync_worker_http_evidence",
        side_effect=fake_http_sync,
    ):
        with patch(
            "enoch_control_plane.control_plane.router.subprocess.Popen",
            side_effect=AssertionError(
                "ssh should not run after complete HTTP evidence sync"
            ),
        ):
            result = _sync_remote_project_evidence(
                config, project_id="project", artifact_root=artifact_root
            )

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


def test_sync_remote_evidence_kills_started_ssh_on_timeout(tmp_path) -> None:
    config = _config(tmp_path)
    artifact_root = tmp_path / "artifact"

    class TimeoutSshProcess(_FakeStartedProcess):
        def communicate(self, timeout=None):  # noqa: ANN001 - subprocess-compatible test double
            raise subprocess.TimeoutExpired("ssh", timeout)

    import subprocess

    ssh_proc = TimeoutSshProcess()

    with patch(
        "enoch_control_plane.control_plane.router._sync_worker_http_evidence",
        return_value={"ok": False, "reason": "worker_read_failed"},
    ):
        with patch(
            "enoch_control_plane.control_plane.router.subprocess.Popen",
            return_value=ssh_proc,
        ):
            result = _sync_remote_project_evidence(
                config, project_id="project", artifact_root=artifact_root
            )

    assert result["reason"] == "timeout"
    assert ssh_proc.killed is True


def test_sync_remote_evidence_timeout_bounds_stalled_real_stdout_pipe(tmp_path) -> None:
    config = _config(tmp_path)
    config.paper_evidence_sync_timeout_sec = 1
    artifact_root = tmp_path / "artifact"
    original_popen = subprocess.Popen
    child: subprocess.Popen | None = None
    result: dict[str, object] = {}

    def fake_popen(_cmd, stdout=None, stderr=None):  # noqa: ANN001 - subprocess-compatible test double
        nonlocal child
        assert stdout is subprocess.PIPE
        child = original_popen(
            [
                sys.executable,
                "-c",
                "import sys,time; sys.stdout.buffer.write(b'abcde'); sys.stdout.flush(); time.sleep(30)",
            ],
            stdout=stdout,
            stderr=stderr,
        )
        return child

    def run_sync() -> None:
        result.update(
            _sync_remote_project_evidence(
                config, project_id="project", artifact_root=artifact_root
            )
        )

    with patch(
        "enoch_control_plane.control_plane.router._sync_worker_http_evidence",
        return_value={"ok": False, "reason": "worker_read_failed"},
    ):
        with patch(
            "enoch_control_plane.control_plane.router.subprocess.Popen",
            side_effect=fake_popen,
        ):
            start = time.monotonic()
            thread = threading.Thread(target=run_sync, daemon=True)
            thread.start()
            thread.join(timeout=3)
            elapsed = time.monotonic() - start
            if thread.is_alive():
                if child is not None:
                    child.kill()
                thread.join(timeout=2)
            assert not thread.is_alive(), (
                "SSH evidence sync must not block past configured timeout"
            )

    assert elapsed < 3
    assert result["reason"] == "timeout"
    assert child is not None
    assert child.poll() is not None


def test_sync_remote_evidence_extracts_successful_real_stdout_pipe(tmp_path) -> None:
    config = _config(tmp_path)
    config.paper_evidence_sync_timeout_sec = 5
    artifact_root = tmp_path / "artifact"
    payload = _tar_bytes(
        {
            "run_notes.md": b"measured evidence\n",
            ".enoch/project_decision.json": b'{"project_decision":"finalize_positive"}',
        }
    )
    original_popen = subprocess.Popen

    def fake_popen(_cmd, stdout=None, stderr=None):  # noqa: ANN001 - subprocess-compatible test double
        assert stdout is subprocess.PIPE
        return original_popen(
            [sys.executable, "-c", f"import sys; sys.stdout.buffer.write({payload!r})"],
            stdout=stdout,
            stderr=stderr,
        )

    with patch(
        "enoch_control_plane.control_plane.router._sync_worker_http_evidence",
        return_value={"ok": False, "reason": "worker_read_failed"},
    ):
        with patch(
            "enoch_control_plane.control_plane.router.subprocess.Popen",
            side_effect=fake_popen,
        ):
            result = _sync_remote_project_evidence(
                config, project_id="project", artifact_root=artifact_root
            )

    assert result["reason"] == "synced"
    assert result["local_evidence_present"] is True
    assert (artifact_root / "run_notes.md").read_text(
        encoding="utf-8"
    ) == "measured evidence\n"


def test_sync_remote_evidence_reports_unusable_artifact_root_before_ssh(
    tmp_path,
) -> None:
    config = _config(tmp_path)
    artifact_root = tmp_path / "artifact"
    artifact_root.write_text("not a directory", encoding="utf-8")

    with patch(
        "enoch_control_plane.control_plane.router._sync_worker_http_evidence",
        return_value={"ok": False, "reason": "artifact_root_unusable"},
    ):
        with patch(
            "enoch_control_plane.control_plane.router.subprocess.Popen",
            side_effect=AssertionError("ssh must not run for unusable artifact root"),
        ):
            result = _sync_remote_project_evidence(
                config, project_id="project", artifact_root=artifact_root
            )

    assert result["enabled"] is True
    assert result["synced"] is False
    assert result["reason"] == "artifact_root_unusable"


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
        fastapi_app.include_router(
            create_control_plane_router(config, lambda authorization: None)
        )
        app = TestClient(fastapi_app)
        app.post(
            "/control/import/legacy-snapshot",
            json={
                "idempotency_key": "dry-run-no-sync",
                "queue_rows": [
                    {
                        "project_id": "paper-positive",
                        "project_name": "Paper Positive",
                        "project_dir": str(project_dir),
                        "status": "completed",
                        "last_run_state": "finalize_positive",
                        "current_run_id": "run-1",
                        "manual_review_required": False,
                    }
                ],
                "paper_rows": [],
            },
        )
        with patch(
            "enoch_control_plane.control_plane.router._sync_remote_project_evidence",
            side_effect=AssertionError("dry run must not sync evidence"),
        ):
            response = app.post(
                "/control/papers/draft-next", json={"dry_run": True, "force": True}
            )
        assert response.status_code == 200
        body = response.json()
        assert body["action"] == "dry_run_draft"
        assert body["candidate"]["evidence_sync"] == {
            "enabled": True,
            "skipped": True,
            "reason": "dry_run",
        }


def test_sync_worker_http_evidence_can_use_routed_worker_credentials(
    tmp_path, monkeypatch
) -> None:
    from enoch_control_plane.control_plane import router

    calls = []

    def fake_worker_json(base_url, path, token, payload, *, timeout_seconds):  # noqa: ANN001 - patched request boundary
        calls.append(
            {
                "base_url": base_url,
                "path": path,
                "token": token,
                "payload": payload,
                "timeout_seconds": timeout_seconds,
            }
        )
        requested_path = payload["paths"][0]
        return router.HttpResult(
            ok=True,
            status=200,
            body={"files": [{"path": requested_path, "content": "content"}]},
            error=None,
        )

    monkeypatch.setattr(
        "enoch_control_plane.control_plane.worker_evidence_sync._worker_json_request",
        fake_worker_json,
    )
    config = GateConfig(
        state_dir=str(tmp_path / "state"),
        project_root=str(tmp_path / "projects"),
        dispatch_script_path=str(tmp_path / "dispatch.sh"),
        control_api_bearer_token="token",
        completion_callback_url="http://example.invalid/callback",
        completion_callback_token="unused",
        worker_wake_gate_url="http://gb10.example:8787",
        worker_wake_gate_bearer_token="gb10-token",
    )

    result = router._sync_worker_http_evidence(
        config,
        project_id="cpu-project",
        artifact_root=tmp_path / "artifact",
        worker_wake_gate_url="http://cpu.example:8787",
        worker_bearer_token="cpu-token",
    )

    assert result["ok"] is True
    assert calls
    assert {call["base_url"] for call in calls} == {"http://cpu.example:8787"}
    assert {call["token"] for call in calls} == {"cpu-token"}


def test_sync_worker_http_evidence_rejects_worker_returned_escape_paths(
    tmp_path,
) -> None:
    from enoch_control_plane.control_plane.router import _sync_worker_http_evidence
    from enoch_control_plane.control_plane.worker_adapter import HttpResult

    config = _config(tmp_path)
    config.worker_wake_gate_bearer_token = "worker-token"
    config.worker_wake_gate_url = "http://worker"
    artifact_root = tmp_path / "artifact"
    outside = tmp_path / "outside.txt"

    def fake_post_worker_json(base_url, path, token, payload):  # noqa: ANN001 - matches patched function
        del base_url, path, token, payload
        return HttpResult(
            ok=True,
            status=200,
            body={"files": [{"path": "../outside.txt", "content": "escape"}]},
        )

    with patch(
        "enoch_control_plane.control_plane.worker_evidence_sync.post_worker_json",
        side_effect=fake_post_worker_json,
    ):
        result = _sync_worker_http_evidence(
            config, project_id="project", artifact_root=artifact_root
        )

    assert result["ok"] is False
    assert result["reason"] == "worker_read_failed"
    assert not outside.exists()
    assert any(item["status"] == "unsafe_path" for item in result["skipped"])


def test_sync_remote_evidence_reports_failed_when_successful_tar_has_no_required_evidence(
    tmp_path,
) -> None:
    config = _config(tmp_path)
    artifact_root = tmp_path / "artifact"

    class FakeSshProcess:
        def __init__(self) -> None:
            self.returncode = 0

        def communicate(self, timeout=None):  # noqa: ANN001 - subprocess-compatible test double
            del timeout
            return _tar_bytes({}, symlinks={}), b""

        def wait(self, timeout=None):  # noqa: ANN001 - subprocess-compatible test double
            del timeout
            return 0

        def poll(self):
            return 0

    with patch(
        "enoch_control_plane.control_plane.router._sync_worker_http_evidence",
        return_value={"ok": False, "reason": "worker_read_failed"},
    ):
        with patch(
            "enoch_control_plane.control_plane.router.subprocess.Popen",
            return_value=FakeSshProcess(),
        ):
            result = _sync_remote_project_evidence(
                config, project_id="project", artifact_root=artifact_root
            )

    assert result["method"] == "worker_http+ssh"
    assert result["synced"] is False
    assert result["local_evidence_present"] is False
    assert result["reason"] == "no_safe_tar_evidence"


def test_sync_worker_http_evidence_skips_empty_worker_paths(tmp_path) -> None:
    from enoch_control_plane.control_plane.router import _sync_worker_http_evidence
    from enoch_control_plane.control_plane.worker_adapter import HttpResult

    config = _config(tmp_path)
    config.worker_wake_gate_bearer_token = "worker-token"
    config.worker_wake_gate_url = "http://worker"
    artifact_root = tmp_path / "artifact"

    def fake_post_worker_json(base_url, path, token, payload):  # noqa: ANN001 - matches patched function
        del base_url, path, token, payload
        return HttpResult(
            ok=True,
            status=200,
            body={
                "files": [
                    {"path": "", "content": "bad"},
                    {"path": ".", "content": "bad"},
                ]
            },
        )

    with patch(
        "enoch_control_plane.control_plane.worker_evidence_sync.post_worker_json",
        side_effect=fake_post_worker_json,
    ):
        result = _sync_worker_http_evidence(
            config, project_id="project", artifact_root=artifact_root
        )

    assert result["ok"] is False
    assert result["reason"] == "worker_read_failed"
    assert any(item["status"] == "unsafe_path" for item in result["skipped"])


def test_apply_worker_evidence_file_skips_missing_resolver_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from enoch_control_plane.control_plane import worker_evidence_sync as sync

    def missing_target(artifact_root: Path, rel: str):  # noqa: ANN202 - test double
        del artifact_root, rel
        return None, None

    monkeypatch.setattr(sync, "_resolve_worker_evidence_target", missing_target)
    written: list[str] = []
    skipped: list[dict[str, object]] = []

    sync._apply_worker_evidence_file(
        tmp_path,
        "run_notes.md",
        {"path": "run_notes.md", "content": "notes"},
        written=written,
        skipped=skipped,
    )

    assert written == []
    assert skipped == [
        {
            "path": "run_notes.md",
            "status": "invalid_target",
            "error": "worker evidence target resolver returned no target",
        }
    ]


def test_sync_worker_http_evidence_skips_invalid_worker_path_bytes(tmp_path) -> None:
    from enoch_control_plane.control_plane.router import _sync_worker_http_evidence
    from enoch_control_plane.control_plane.worker_adapter import HttpResult

    config = _config(tmp_path)
    config.worker_wake_gate_bearer_token = "worker-token"
    config.worker_wake_gate_url = "http://worker"

    def fake_post_worker_json(base_url, path, token, payload):  # noqa: ANN001 - matches patched function
        del base_url, path, token, payload
        return HttpResult(
            ok=True,
            status=200,
            body={"files": [{"path": "bad\x00file.json", "content": "bad"}]},
        )

    with patch(
        "enoch_control_plane.control_plane.worker_evidence_sync.post_worker_json",
        side_effect=fake_post_worker_json,
    ):
        result = _sync_worker_http_evidence(
            config, project_id="project", artifact_root=tmp_path / "artifact"
        )

    assert result["ok"] is False
    assert any(item["status"] == "unsafe_path" for item in result["skipped"])


def test_sync_worker_http_evidence_reports_unusable_artifact_root(tmp_path) -> None:
    from enoch_control_plane.control_plane.router import _sync_worker_http_evidence

    config = _config(tmp_path)
    config.worker_wake_gate_bearer_token = "worker-token"
    config.worker_wake_gate_url = "http://worker"
    artifact_root = tmp_path / "artifact"
    artifact_root.write_text("not a directory", encoding="utf-8")

    result = _sync_worker_http_evidence(
        config, project_id="project", artifact_root=artifact_root
    )

    assert result["ok"] is False
    assert result["reason"] == "artifact_root_unusable"


def test_sync_worker_http_evidence_reports_unresolvable_artifact_root(tmp_path) -> None:
    from enoch_control_plane.control_plane.router import _sync_worker_http_evidence

    config = _config(tmp_path)
    config.worker_wake_gate_bearer_token = "worker-token"
    config.worker_wake_gate_url = "http://worker"

    result = _sync_worker_http_evidence(
        config, project_id="project", artifact_root=tmp_path / "bad\0artifact"
    )

    assert result["ok"] is False
    assert result["reason"] == "artifact_root_unusable"


def test_extract_safe_tar_reports_unresolvable_artifact_root(tmp_path) -> None:
    from enoch_control_plane.control_plane.router import _extract_safe_tar_bytes

    result = _extract_safe_tar_bytes(b"not-a-tar", tmp_path / "bad\0artifact")

    assert result["ok"] is False
    assert result["reason"] == "artifact_root_unusable"


def test_sync_worker_http_evidence_removes_existing_file_when_worker_returns_empty_content(
    tmp_path,
) -> None:
    from enoch_control_plane.control_plane.router import _sync_worker_http_evidence
    from enoch_control_plane.control_plane.worker_adapter import HttpResult

    config = _config(tmp_path)
    config.worker_wake_gate_bearer_token = "worker-token"
    config.worker_wake_gate_url = "http://worker"
    artifact_root = tmp_path / "artifact"
    artifact_root.mkdir()
    target = artifact_root / "run_notes.md"
    target.write_text("existing measured evidence", encoding="utf-8")

    def fake_post_worker_json(base_url, path, token, payload):  # noqa: ANN001 - matches patched function
        del base_url, path, token, payload
        return HttpResult(
            ok=True,
            status=200,
            body={"files": [{"path": "run_notes.md", "content": ""}]},
        )

    with patch(
        "enoch_control_plane.control_plane.worker_evidence_sync.post_worker_json",
        side_effect=fake_post_worker_json,
    ):
        result = _sync_worker_http_evidence(
            config, project_id="project", artifact_root=artifact_root
        )

    assert result["ok"] is False
    assert result["reason"] == "worker_read_failed"
    assert any(item["status"] == "empty_content" for item in result["skipped"])
    assert not target.exists()


def test_sync_worker_http_evidence_skips_uninspectable_worker_target(
    tmp_path, monkeypatch
) -> None:
    from enoch_control_plane.control_plane import router, worker_evidence_sync

    config = _config(tmp_path)
    config.worker_wake_gate_bearer_token = "worker-token"
    config.worker_wake_gate_url = "http://worker"
    artifact_root = tmp_path / "artifact"
    artifact_root.mkdir()
    target = (artifact_root / "run_notes.md").resolve()
    real_exists = Path.exists

    class Result:
        ok = True
        status = 200
        error = ""
        body = {"files": [{"path": "run_notes.md", "content": "new evidence"}]}

    def blocked_exists(path: Path) -> bool:
        if path == target:
            raise PermissionError("simulated target access failure")
        return real_exists(path)

    monkeypatch.setattr(
        worker_evidence_sync, "post_worker_json", lambda *args, **kwargs: Result()
    )
    monkeypatch.setattr(Path, "exists", blocked_exists)

    result = router._sync_worker_http_evidence(
        config, project_id="project", artifact_root=artifact_root
    )

    assert result["ok"] is False
    assert result["reason"] == "worker_read_failed"
    assert any(
        item["status"] == "unsafe_path" and "could not be inspected" in item["error"]
        for item in result["skipped"]
    )
    assert not real_exists(target)


def test_sync_worker_http_evidence_preserves_existing_file_when_write_fails(
    tmp_path, monkeypatch
) -> None:
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

    from enoch_control_plane.control_plane import router, worker_evidence_sync

    monkeypatch.setattr(
        worker_evidence_sync, "post_worker_json", lambda *args, **kwargs: Result()
    )
    monkeypatch.setattr(
        worker_evidence_sync,
        "_atomic_write_text",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            OSError("simulated evidence write failure")
        ),
    )

    result = router._sync_worker_http_evidence(
        config, project_id="project", artifact_root=artifact_root
    )

    assert result["ok"] is False
    assert result["reason"] == "worker_read_failed"
    assert any(item["status"] == "write_failed" for item in result["skipped"])
    assert target.read_text(encoding="utf-8") == "old evidence"


def test_sync_worker_http_evidence_skips_malformed_success_bodies(tmp_path) -> None:
    from enoch_control_plane.control_plane.router import _sync_worker_http_evidence
    from enoch_control_plane.control_plane.worker_adapter import HttpResult

    config = _config(tmp_path)
    config.worker_wake_gate_bearer_token = "worker-token"
    config.worker_wake_gate_url = "http://worker"
    artifact_root = tmp_path / "artifact"
    responses = [
        HttpResult(ok=True, status=200, body={"files": "not-a-list"}),
        HttpResult(ok=True, status=200, body={"files": ["not-a-dict"]}),
        HttpResult(ok=True, status=200, body=[]),  # type: ignore[arg-type]
    ]

    def fake_post_worker_json(base_url, path, token, payload):  # noqa: ANN001 - matches patched function
        del base_url, path, token, payload
        return (
            responses.pop(0)
            if responses
            else HttpResult(ok=False, status=404, body=None, error="missing")
        )

    with patch(
        "enoch_control_plane.control_plane.worker_evidence_sync.post_worker_json",
        side_effect=fake_post_worker_json,
    ):
        result = _sync_worker_http_evidence(
            config, project_id="project", artifact_root=artifact_root
        )

    assert result["ok"] is False
    assert result["reason"] == "worker_read_failed"
    statuses = [item.get("status") for item in result["skipped"]]
    assert "malformed_response" in statuses
    assert "malformed_file" in statuses


def test_worker_http_evidence_sync_times_out_slow_worker_reads(tmp_path, monkeypatch):
    from enoch_control_plane.config import GateConfig
    from enoch_control_plane.control_plane import router
    from enoch_control_plane.control_plane.worker_adapter import HttpResult

    calls = []

    def timed_out_worker_json(*args, **kwargs):  # noqa: ANN001 - patched worker transport
        calls.append((args, kwargs))
        return HttpResult(
            ok=False,
            status=None,
            body=None,
            error="TimeoutError: worker request exceeded 0.010s",
        )

    monkeypatch.setattr(
        "enoch_control_plane.control_plane.worker_evidence_sync._worker_json_request",
        timed_out_worker_json,
    )
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

    result = router._sync_worker_http_evidence(
        config,
        project_id="slow-project",
        artifact_root=tmp_path / "artifact-root",
        per_request_timeout_seconds=0.01,
        overall_timeout_seconds=0.05,
    )

    assert result["ok"] is False
    assert result["reason"] == "no_worker_http_evidence"
    assert result["timeouts"] >= 1
    assert any(item.get("status") == "timeout" for item in result["skipped"])
