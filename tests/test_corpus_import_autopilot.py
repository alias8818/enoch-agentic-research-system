from __future__ import annotations

import importlib.util
import json
import os
import tempfile
from pathlib import Path
from subprocess import CalledProcessError, CompletedProcess
from typing import Any
from unittest.mock import patch

import pytest


MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "deploy" / "enoch_corpus_import_autopilot.py"
)
spec = importlib.util.spec_from_file_location(
    "enoch_corpus_import_autopilot", MODULE_PATH
)
assert spec and spec.loader
autopilot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(autopilot)


def test_base_url_uses_http_for_loopback_control_plane(monkeypatch):
    monkeypatch.delenv("ENOCH_CONTROL_URL", raising=False)

    assert autopilot._base_url({"listen_host": "0.0.0.0", "listen_port": 8787}) == (
        "http://127.0.0.1:8787"
    )
    assert autopilot._base_url({"listen_host": "127.0.0.1", "listen_port": 8787}) == (
        "http://127.0.0.1:8787"
    )


def test_base_url_allows_explicit_environment_override(monkeypatch):
    monkeypatch.setenv("ENOCH_CONTROL_URL", "https://control.example")

    assert autopilot._base_url({"listen_host": "0.0.0.0", "listen_port": 8787}) == (
        "https://control.example"
    )


def test_get_json_allows_loopback_control_plane_status_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args: object) -> bool:
            return False

        def read(self) -> bytes:
            return b'{"flags":{"queue_paused":false}}'

    calls = []

    def fake_urlopen_validated(
        req: Any, *, timeout: int, field_name: str, allow_private: bool
    ) -> FakeResponse:
        calls.append(
            {
                "url": req.full_url,
                "timeout": timeout,
                "field_name": field_name,
                "allow_private": allow_private,
            }
        )
        return FakeResponse()

    monkeypatch.setattr(autopilot, "urlopen_validated", fake_urlopen_validated)

    assert autopilot._get_json(
        "http://127.0.0.1:8787", "/control/api/status", "token"
    ) == {"flags": {"queue_paused": False}}
    assert calls == [
        {
            "url": "http://127.0.0.1:8787/control/api/status",
            "timeout": 30,
            "field_name": "deploy/enoch_corpus_import_autopilot.py url",
            "allow_private": True,
        }
    ]


def test_corpus_import_autopilot_skips_before_repo_work_during_control_hold(
    capsys, monkeypatch
):
    monkeypatch.setenv("ENOCH_ENABLE_CORPUS_IMPORT_AUTOPILOT", "1")

    with (
        patch.object(
            autopilot,
            "_load_config",
            return_value={"control_api_bearer_token": "token"},
        ),
        patch.object(autopilot, "_base_url", return_value="http://127.0.0.1:8787"),
        patch.object(
            autopilot,
            "_get_json",
            return_value={
                "flags": {
                    "queue_paused": True,
                    "maintenance_mode": True,
                    "pause_reason": "operator maintenance",
                    "paused_at": "2026-06-02T20:00:00Z",
                    "paused_by": "operator",
                }
            },
        ) as get_json,
        patch.object(
            autopilot,
            "_release_root",
            side_effect=AssertionError("release root must not be inspected"),
        ),
        patch.object(
            autopilot,
            "_run",
            side_effect=AssertionError("import commands must not run"),
        ),
    ):
        assert autopilot.main() == 0

    get_json.assert_called_once_with(
        "http://127.0.0.1:8787", "/control/api/status", "token", timeout=10
    )
    output = json.loads(capsys.readouterr().out)
    assert output["ok"] is True
    assert output["action"] == "skipped"
    assert "maintenance_mode" in output["reason"]
    assert output["hold_state"]["queue_paused"] is True
    assert output["hold_state"]["maintenance_mode"] is True


def test_corpus_import_autopilot_skips_when_hold_status_unreachable(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ENOCH_ENABLE_CORPUS_IMPORT_AUTOPILOT", "1")

    with (
        patch.object(
            autopilot,
            "_load_config",
            return_value={"control_api_bearer_token": "token"},
        ),
        patch.object(autopilot, "_base_url", return_value="http://127.0.0.1:8787"),
        patch.object(autopilot, "_get_json", side_effect=OSError("offline")),
        patch.object(
            autopilot,
            "_release_root",
            side_effect=AssertionError("release root must not be inspected"),
        ),
        patch.object(
            autopilot,
            "_run",
            side_effect=AssertionError("import commands must not run"),
        ),
    ):
        assert autopilot.main() == 0

    output = json.loads(capsys.readouterr().out)
    assert output["action"] == "skipped"
    assert output["control_status_unreachable"] is True
    assert "could not be verified" in output["reason"]


def test_dry_run_transient_failure_retries_before_blocking(tmp_path, capsys):
    for name in autopilot.REPO_NAMES:
        (tmp_path / name).mkdir()

    dry_payload = {
        "failed": 0,
        "imported": 0,
        "updated": 0,
        "errors": [],
        "seen": 388,
        "skipped": 388,
    }
    calls = {"count": 0}

    def fake_run(cmd, *, cwd, env=None):
        assert "scripts/import_from_control_plane.py" in cmd
        assert "--token" not in cmd
        assert "token" not in cmd
        assert env is not None
        assert env.get("ENOCH_CONTROL_TOKEN") == ""
        token_file = Path(env["ENOCH_CONTROL_TOKEN_FILE"])
        assert token_file.read_text(encoding="utf-8") == "token"
        assert token_file.stat().st_mode & 0o777 == 0o600
        calls["count"] += 1
        if calls["count"] == 1:
            raise CalledProcessError(1, cmd, output="", stderr="connection refused")
        return CompletedProcess(cmd, 0, stdout=json.dumps(dry_payload), stderr="")

    with (
        patch.dict(
            "os.environ",
            {
                "ENOCH_ENABLE_CORPUS_IMPORT_AUTOPILOT": "1",
                "ENOCH_CORPUS_IMPORT_SYNC_LEDGER": "0",
                "ENOCH_CORPUS_IMPORT_RUN_WHILE_HELD": "1",
                "ENOCH_CORPUS_IMPORT_DRY_RUN_RETRIES": "2",
                "ENOCH_CORPUS_IMPORT_DRY_RUN_RETRY_DELAY_SEC": "0",
            },
            clear=False,
        ),
        patch.object(autopilot, "_release_root", return_value=tmp_path),
        patch.object(autopilot, "_git_clean", return_value=True),
        patch.object(
            autopilot,
            "_load_config",
            return_value={"control_api_bearer_token": "token"},
        ),
        patch.object(autopilot, "_base_url", return_value="http://127.0.0.1:8787"),
        patch.object(autopilot, "_run", side_effect=fake_run),
    ):
        assert autopilot.main() == 0

    assert calls["count"] == 2
    output = json.loads(capsys.readouterr().out)
    assert output["action"] == "skipped"
    assert output["dry_run_attempts"] == 2


def test_dry_run_failure_redacts_control_token(tmp_path, capsys):
    for name in autopilot.REPO_NAMES:
        (tmp_path / name).mkdir()

    def fake_run(cmd, *, cwd, env=None):
        assert "--token" not in cmd
        assert "super-secret-token" not in cmd
        assert env is not None
        assert env.get("ENOCH_CONTROL_TOKEN") == ""
        assert (
            Path(env["ENOCH_CONTROL_TOKEN_FILE"]).read_text(encoding="utf-8")
            == "super-secret-token"
        )
        raise CalledProcessError(1, cmd, output="", stderr="connection refused")

    with (
        patch.dict(
            "os.environ",
            {
                "ENOCH_ENABLE_CORPUS_IMPORT_AUTOPILOT": "1",
                "ENOCH_CORPUS_IMPORT_DRY_RUN_RETRIES": "1",
                "ENOCH_CORPUS_IMPORT_RUN_WHILE_HELD": "1",
            },
            clear=False,
        ),
        patch.object(autopilot, "_release_root", return_value=tmp_path),
        patch.object(autopilot, "_git_clean", return_value=True),
        patch.object(
            autopilot,
            "_load_config",
            return_value={"control_api_bearer_token": "super-secret-token"},
        ),
        patch.object(autopilot, "_base_url", return_value="http://127.0.0.1:8787"),
        patch.object(autopilot, "_run", side_effect=fake_run),
    ):
        assert autopilot.main() == 1

    captured = capsys.readouterr()
    assert "super-secret-token" not in captured.err
    assert "--token" not in captured.err
    payload = json.loads(captured.err)
    assert payload["action"] == "dry_run_failed"


def test_clean_noop_dry_run_is_successful_timer_idle():
    payload = {
        "failed": 0,
        "imported": 0,
        "updated": 0,
        "errors": [],
        "seen": 384,
        "skipped": 384,
    }
    assert autopilot._is_clean_noop_dry_run(payload) is True


def test_failed_or_error_dry_run_is_not_clean_noop():
    assert (
        autopilot._is_clean_noop_dry_run(
            {"failed": 1, "imported": 0, "updated": 0, "errors": []}
        )
        is False
    )
    assert (
        autopilot._is_clean_noop_dry_run(
            {"failed": 0, "imported": 0, "updated": 0, "errors": ["bad"]}
        )
        is False
    )


def test_clean_noop_syncs_ledger_when_enabled(tmp_path, capsys):
    for name in autopilot.REPO_NAMES:
        (tmp_path / name).mkdir()

    dry_payload = {
        "failed": 0,
        "imported": 0,
        "updated": 0,
        "errors": [],
        "seen": 385,
        "skipped": 384,
        "skipped_existing_slug": 1,
    }

    def fake_run(cmd, *, cwd, env=None):
        assert "scripts/import_from_control_plane.py" in cmd
        assert "--token" not in cmd
        assert "token" not in cmd
        assert env is not None
        assert env.get("ENOCH_CONTROL_TOKEN") == ""
        assert (
            Path(env["ENOCH_CONTROL_TOKEN_FILE"]).read_text(encoding="utf-8") == "token"
        )
        return CompletedProcess(cmd, 0, stdout=json.dumps(dry_payload), stderr="")

    with (
        patch.dict(
            "os.environ",
            {
                "ENOCH_ENABLE_CORPUS_IMPORT_AUTOPILOT": "1",
                "ENOCH_CORPUS_IMPORT_SYNC_LEDGER": "1",
                "ENOCH_CORPUS_IMPORT_RUN_WHILE_HELD": "1",
            },
            clear=False,
        ),
        patch.object(autopilot, "_release_root", return_value=tmp_path),
        patch.object(autopilot, "_git_clean", return_value=True),
        patch.object(
            autopilot,
            "_load_config",
            return_value={"control_api_bearer_token": "token"},
        ),
        patch.object(autopilot, "_base_url", return_value="http://127.0.0.1:8787"),
        patch.object(autopilot, "_run", side_effect=fake_run),
        patch.object(
            autopilot,
            "_sync_corpus_ledger",
            return_value={"ok": True, "publication_ready": 0},
        ) as sync,
    ):
        assert autopilot.main() == 0

    sync.assert_called_once()
    output = json.loads(capsys.readouterr().out)
    assert output["action"] == "skipped"
    assert output["fast_forwarded"] == []
    assert output["ledger_sync"] == {"ok": True, "publication_ready": 0}


def test_clean_noop_refreshes_promising_signals_and_pushes_changed_repos(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    for name in autopilot.REPO_NAMES:
        (tmp_path / name).mkdir()

    dry_payload = {
        "failed": 0,
        "imported": 0,
        "updated": 0,
        "errors": [],
        "seen": 385,
        "skipped": 384,
        "skipped_existing_slug": 1,
    }

    with (
        patch.dict(
            "os.environ",
            {
                "ENOCH_ENABLE_CORPUS_IMPORT_AUTOPILOT": "1",
                "ENOCH_CORPUS_IMPORT_PUSH": "1",
                "ENOCH_CORPUS_IMPORT_AUTOCOMMIT": "1",
                "ENOCH_CORPUS_IMPORT_RUN_WHILE_HELD": "1",
            },
            clear=False,
        ),
        patch.object(autopilot, "_release_root", return_value=tmp_path),
        patch.object(autopilot, "_git_clean", return_value=True),
        patch.object(
            autopilot,
            "_load_config",
            return_value={"control_api_bearer_token": "token"},
        ),
        patch.object(autopilot, "_base_url", return_value="http://127.0.0.1:8787"),
        patch.object(
            autopilot,
            "_run",
            return_value=CompletedProcess(
                ["import"], 0, stdout=json.dumps(dry_payload), stderr=""
            ),
        ),
        patch.object(
            autopilot,
            "_refresh_promising_signals",
            return_value={
                "ok": True,
                "action": "promising_signals_refreshed",
                "manifest_record_count": 6376,
            },
        ) as refresh,
        patch.object(
            autopilot,
            "_update_public_counts",
            return_value={"stats": {"artifact_count": 393}},
        ) as update_counts,
        patch.object(
            autopilot,
            "_validate_release",
            return_value={"generate_stdout": "", "validate_stdout": ""},
        ) as validate,
        patch.object(
            autopilot,
            "_git_changed_repos",
            return_value=["enoch-promising-signals"],
        ),
        patch.object(
            autopilot,
            "_autocommit_and_push",
            return_value=(
                [{"repo": "enoch-promising-signals", "sha": "abc123"}],
                [{"repo": "enoch-promising-signals", "sha": "abc123"}],
            ),
        ) as commit_push,
    ):
        assert autopilot.main() == 0

    refresh.assert_called_once_with(
        tmp_path / "enoch-agentic-research-system", tmp_path
    )
    update_counts.assert_called_once()
    validate.assert_called_once()
    commit_push.assert_called_once()
    output = json.loads(capsys.readouterr().out)
    assert output["action"] == "skipped"
    assert output["promising_signals"]["manifest_record_count"] == 6376
    assert output["changed_repos"] == ["enoch-promising-signals"]
    assert output["pushed"] == [{"repo": "enoch-promising-signals", "sha": "abc123"}]


def test_preflight_none_fails_closed_without_assert(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    for name in autopilot.REPO_NAMES:
        (tmp_path / name).mkdir()

    dry_payload = {
        "failed": 0,
        "imported": 1,
        "updated": 0,
        "errors": [],
        "seen": 1,
        "skipped": 0,
    }

    with (
        patch.dict(
            "os.environ",
            {
                "ENOCH_ENABLE_CORPUS_IMPORT_AUTOPILOT": "1",
                "ENOCH_CORPUS_IMPORT_PREFLIGHT_ONLY": "1",
                "ENOCH_CORPUS_IMPORT_RUN_WHILE_HELD": "1",
            },
            clear=False,
        ),
        patch.object(autopilot, "_release_root", return_value=tmp_path),
        patch.object(autopilot, "_git_clean", return_value=True),
        patch.object(
            autopilot,
            "_load_config",
            return_value={"control_api_bearer_token": "token"},
        ),
        patch.object(autopilot, "_base_url", return_value="http://127.0.0.1:8787"),
        patch.object(
            autopilot,
            "_run_dry_run_import",
            return_value=(dry_payload, 1),
        ),
        patch.object(autopilot, "_run_preflight_import", return_value=(None, None)),
    ):
        assert autopilot.main() == 1

    error = json.loads(capsys.readouterr().err)
    assert error == {
        "action": "preflight_import_failed",
        "ok": False,
        "reason": "preflight returned no result",
    }


def test_clean_noop_does_not_sync_ledger_without_opt_in(tmp_path, capsys):
    for name in autopilot.REPO_NAMES:
        (tmp_path / name).mkdir()

    dry_payload = {
        "failed": 0,
        "imported": 0,
        "updated": 0,
        "errors": [],
        "seen": 385,
        "skipped": 384,
        "skipped_existing_slug": 1,
    }

    with (
        patch.dict(
            "os.environ",
            {
                "ENOCH_ENABLE_CORPUS_IMPORT_AUTOPILOT": "1",
                "ENOCH_CORPUS_IMPORT_SYNC_LEDGER": "0",
                "ENOCH_CORPUS_IMPORT_RUN_WHILE_HELD": "1",
            },
            clear=False,
        ),
        patch.object(autopilot, "_release_root", return_value=tmp_path),
        patch.object(autopilot, "_git_clean", return_value=True),
        patch.object(
            autopilot,
            "_load_config",
            return_value={"control_api_bearer_token": "token"},
        ),
        patch.object(autopilot, "_base_url", return_value="http://127.0.0.1:8787"),
        patch.object(
            autopilot,
            "_run",
            return_value=CompletedProcess(
                ["import"], 0, stdout=json.dumps(dry_payload), stderr=""
            ),
        ),
        patch.object(autopilot, "_sync_corpus_ledger") as sync,
    ):
        assert autopilot.main() == 0

    sync.assert_not_called()
    assert json.loads(capsys.readouterr().out)["ledger_sync"] == {}


def test_ecosystem_manifest_path_honors_override(tmp_path):
    manifest = tmp_path / "manifest.json"
    with patch.dict(
        "os.environ", {"ENOCH_ECOSYSTEM_MANIFEST": str(manifest)}, clear=False
    ):
        assert autopilot._ecosystem_manifest_path() == manifest


def test_ecosystem_manifest_path_default_uses_private_temp_file():
    with patch.dict("os.environ", {}, clear=False):
        os.environ.pop("ENOCH_ECOSYSTEM_MANIFEST", None)
        path = autopilot._ecosystem_manifest_path()
    try:
        assert path.name.startswith("enoch-ecosystem.generated.")
        assert path.suffix == ".json"
        assert path.parent == Path(tempfile.gettempdir())
        assert path.stat().st_mode & 0o777 == 0o600
    finally:
        path.unlink(missing_ok=True)


def test_validate_release_includes_promising_signals_repo_when_present(tmp_path):
    system = tmp_path / "enoch-agentic-research-system"
    corpus = tmp_path / "enoch-ai-research-corpus"
    docs = tmp_path / "enoch-docs"
    profile = tmp_path / "alias8818.github.io"
    owner = tmp_path / "alias8818"
    personal = tmp_path / "jeremyblankenship.dev"
    promising = tmp_path / "enoch-promising-signals"
    for path in [system, corpus, docs, profile, owner, personal, promising]:
        path.mkdir()
    manifest = tmp_path / "ecosystem.json"
    calls = []

    def fake_run(cmd, *, cwd, env=None):
        del env
        calls.append((cmd, cwd))
        return CompletedProcess(cmd, 0, stdout="", stderr="")

    with patch.object(autopilot, "_run", side_effect=fake_run):
        autopilot._validate_release(
            system,
            tmp_path,
            corpus,
            manifest,
            skip_github_metadata=True,
        )

    generate_cmd, validate_cmd = calls[0][0], calls[1][0]
    assert "--promising" in generate_cmd
    assert str(promising) in generate_cmd
    assert "--promising" in validate_cmd
    assert str(promising) in validate_cmd


def test_refresh_paper_material_graph_uses_control_plane_and_release_roots(
    tmp_path: Path,
) -> None:
    root = tmp_path / "release"
    control_plane = tmp_path / "control-plane"
    (control_plane / "deploy").mkdir(parents=True)
    root.mkdir()
    calls: list[dict[str, Any]] = []

    def fake_run(cmd, *, cwd, env=None):
        calls.append({"cmd": cmd, "cwd": cwd, "env": env})
        return CompletedProcess(
            cmd,
            0,
            stdout=json.dumps({"ok": True, "paper_count": 393}),
            stderr="",
        )

    with (
        patch.dict(
            "os.environ",
            {
                "ENOCH_CONTROL_PLANE_ROOT": str(control_plane),
                "ENOCH_CORPUS_IMPORT_REFRESH_PAPER_MATERIAL_GRAPH": "1",
            },
            clear=False,
        ),
        patch.object(autopilot, "_run", side_effect=fake_run),
    ):
        result = autopilot._refresh_paper_material_graph(root)

    assert result == {
        "ok": True,
        "paper_count": 393,
        "action": "paper_material_graph_refreshed",
    }
    assert calls == [
        {
            "cmd": [str(control_plane / "deploy" / "enoch_paper_material_graph.sh")],
            "cwd": control_plane.resolve(),
            "env": {
                "ENOCH_ENABLE_PAPER_MATERIAL_GRAPH": "1",
                "ENOCH_RELEASE_ROOT": str(root),
                "ENOCH_CONTROL_PLANE_ROOT": str(control_plane.resolve()),
                "ENOCH_PAPER_MATERIAL_GRAPH_DIR": str(
                    root
                    / "enoch-agentic-research-system"
                    / "docs"
                    / "paper-material-graph"
                ),
            },
        }
    ]


def test_push_commits_records_auth_failure_without_raising(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    commits = [{"repo": "repo", "sha": "abc123"}]
    with patch.object(
        autopilot,
        "_run",
        side_effect=CalledProcessError(
            128,
            ["git", "push"],
            output="",
            stderr="fatal: could not read Username for 'https://github.com'",
        ),
    ):
        pushed = autopilot._push_commits(tmp_path, commits)

    assert pushed[0]["repo"] == "repo"
    assert pushed[0]["sha"] == "abc123"
    assert pushed[0]["ok"] == "false"
    assert pushed[0]["action"] == "push_skipped"
    assert "could not read Username" in pushed[0]["error"]


def test_maybe_github_metadata_reports_unavailable_token_without_failing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ENOCH_CORPUS_IMPORT_UPDATE_GITHUB_METADATA", "1")
    with patch.object(
        autopilot,
        "_update_github_metadata",
        side_effect=RuntimeError("missing GitHub token for metadata update"),
    ):
        payload = autopilot._maybe_github_metadata(
            {"stats": {"artifact_count": 393, "promising_signal_count": 6379}}
        )

    assert payload["ok"] is False
    assert payload["action"] == "skipped"
    assert payload["reason"] == "github metadata update unavailable"
    assert "RuntimeError" in payload["error"]


def test_live_import_refreshes_paper_material_graph_before_reporting_success(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path
    system = root / "enoch-agentic-research-system"
    corpus = root / "enoch-ai-research-corpus"
    system.mkdir()
    corpus.mkdir()
    dry_payload = {"failed": 0, "imported": 1, "updated": 0, "errors": []}
    import_payload = {"failed": 0, "imported": 1, "updated": 0, "errors": []}

    with (
        patch.object(
            autopilot,
            "_run",
            return_value=CompletedProcess(
                ["import"], 0, stdout=json.dumps(import_payload), stderr=""
            ),
        ),
        patch.object(autopilot, "_corpus_rebuild", return_value=[]),
        patch.object(
            autopilot,
            "_update_public_counts",
            return_value={"stats": {"artifact_count": 393}},
        ),
        patch.object(autopilot, "_corpus_trust_checks", return_value=[]),
        patch.object(autopilot, "_maybe_github_metadata", return_value={}),
        patch.object(autopilot, "_validate_release", return_value={"ok": True}),
        patch.object(
            autopilot,
            "_refresh_paper_material_graph",
            return_value={
                "ok": True,
                "action": "paper_material_graph_refreshed",
                "paper_count": 393,
            },
        ) as refresh,
        patch.object(autopilot, "_git_changed_repos", return_value=[]),
        patch.object(autopilot, "_autocommit_and_push", return_value=([], [])),
        patch.object(autopilot, "_maybe_ledger_sync", return_value={}),
    ):
        assert (
            autopilot._execute_live_corpus_import(
                root=root,
                system=system,
                corpus=corpus,
                base_url="http://127.0.0.1:8787",
                limit=1,
                token_file=tmp_path / "token",
                skip_github=True,
                dry_payload=dry_payload,
                dry_run_attempts=1,
                fast_forwarded=[],
            )
            == 0
        )

    refresh.assert_called_once_with(root)
    output = json.loads(capsys.readouterr().out)
    assert output["paper_material_graph"] == {
        "ok": True,
        "action": "paper_material_graph_refreshed",
        "paper_count": 393,
    }
