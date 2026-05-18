from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from subprocess import CalledProcessError, CompletedProcess
from unittest.mock import patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "deploy" / "enoch_corpus_import_autopilot.py"
spec = importlib.util.spec_from_file_location("enoch_corpus_import_autopilot", MODULE_PATH)
assert spec and spec.loader
autopilot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(autopilot)




def test_dry_run_transient_failure_retries_before_blocking(tmp_path, capsys):
    for name in autopilot.REPO_NAMES:
        (tmp_path / name).mkdir()

    dry_payload = {"failed": 0, "imported": 0, "updated": 0, "errors": [], "seen": 388, "skipped": 388}
    calls = {"count": 0}

    def fake_run(cmd, *, cwd, env=None):
        assert "scripts/import_from_control_plane.py" in cmd
        calls["count"] += 1
        if calls["count"] == 1:
            raise CalledProcessError(1, cmd, output="", stderr="connection refused")
        return CompletedProcess(cmd, 0, stdout=json.dumps(dry_payload), stderr="")

    with (
        patch.dict("os.environ", {"ENOCH_ENABLE_CORPUS_IMPORT_AUTOPILOT": "1", "ENOCH_CORPUS_IMPORT_SYNC_LEDGER": "0", "ENOCH_CORPUS_IMPORT_DRY_RUN_RETRIES": "2", "ENOCH_CORPUS_IMPORT_DRY_RUN_RETRY_DELAY_SEC": "0"}, clear=False),
        patch.object(autopilot, "_release_root", return_value=tmp_path),
        patch.object(autopilot, "_git_clean", return_value=True),
        patch.object(autopilot, "_load_config", return_value={"control_api_bearer_token": "token"}),
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
        raise CalledProcessError(1, cmd, output="", stderr="connection refused")

    with (
        patch.dict("os.environ", {"ENOCH_ENABLE_CORPUS_IMPORT_AUTOPILOT": "1", "ENOCH_CORPUS_IMPORT_DRY_RUN_RETRIES": "1"}, clear=False),
        patch.object(autopilot, "_release_root", return_value=tmp_path),
        patch.object(autopilot, "_git_clean", return_value=True),
        patch.object(autopilot, "_load_config", return_value={"control_api_bearer_token": "super-secret-token"}),
        patch.object(autopilot, "_base_url", return_value="http://127.0.0.1:8787"),
        patch.object(autopilot, "_run", side_effect=fake_run),
    ):
        assert autopilot.main() == 1

    captured = capsys.readouterr()
    assert "super-secret-token" not in captured.err
    assert "<redacted>" in captured.err
    payload = json.loads(captured.err)
    assert payload["action"] == "dry_run_failed"


def test_clean_noop_dry_run_is_successful_timer_idle():
    payload = {"failed": 0, "imported": 0, "updated": 0, "errors": [], "seen": 384, "skipped": 384}
    assert autopilot._is_clean_noop_dry_run(payload) is True


def test_failed_or_error_dry_run_is_not_clean_noop():
    assert autopilot._is_clean_noop_dry_run({"failed": 1, "imported": 0, "updated": 0, "errors": []}) is False
    assert autopilot._is_clean_noop_dry_run({"failed": 0, "imported": 0, "updated": 0, "errors": ["bad"]}) is False


def test_clean_noop_syncs_ledger_when_enabled(tmp_path, capsys):
    for name in autopilot.REPO_NAMES:
        (tmp_path / name).mkdir()

    dry_payload = {"failed": 0, "imported": 0, "updated": 0, "errors": [], "seen": 385, "skipped": 384, "skipped_existing_slug": 1}

    def fake_run(cmd, *, cwd, env=None):
        assert "scripts/import_from_control_plane.py" in cmd
        return CompletedProcess(cmd, 0, stdout=json.dumps(dry_payload), stderr="")

    with (
        patch.dict("os.environ", {"ENOCH_ENABLE_CORPUS_IMPORT_AUTOPILOT": "1", "ENOCH_CORPUS_IMPORT_SYNC_LEDGER": "1"}, clear=False),
        patch.object(autopilot, "_release_root", return_value=tmp_path),
        patch.object(autopilot, "_git_clean", return_value=True),
        patch.object(autopilot, "_load_config", return_value={"control_api_bearer_token": "token"}),
        patch.object(autopilot, "_base_url", return_value="http://127.0.0.1:8787"),
        patch.object(autopilot, "_run", side_effect=fake_run),
        patch.object(autopilot, "_sync_corpus_ledger", return_value={"ok": True, "publication_ready": 0}) as sync,
    ):
        assert autopilot.main() == 0

    sync.assert_called_once()
    output = json.loads(capsys.readouterr().out)
    assert output["action"] == "skipped"
    assert output["fast_forwarded"] == []
    assert output["ledger_sync"] == {"ok": True, "publication_ready": 0}


def test_clean_noop_does_not_sync_ledger_without_opt_in(tmp_path, capsys):
    for name in autopilot.REPO_NAMES:
        (tmp_path / name).mkdir()

    dry_payload = {"failed": 0, "imported": 0, "updated": 0, "errors": [], "seen": 385, "skipped": 384, "skipped_existing_slug": 1}

    with (
        patch.dict("os.environ", {"ENOCH_ENABLE_CORPUS_IMPORT_AUTOPILOT": "1", "ENOCH_CORPUS_IMPORT_SYNC_LEDGER": "0"}, clear=False),
        patch.object(autopilot, "_release_root", return_value=tmp_path),
        patch.object(autopilot, "_git_clean", return_value=True),
        patch.object(autopilot, "_load_config", return_value={"control_api_bearer_token": "token"}),
        patch.object(autopilot, "_base_url", return_value="http://127.0.0.1:8787"),
        patch.object(autopilot, "_run", return_value=CompletedProcess(["import"], 0, stdout=json.dumps(dry_payload), stderr="")),
        patch.object(autopilot, "_sync_corpus_ledger") as sync,
    ):
        assert autopilot.main() == 0

    sync.assert_not_called()
    assert json.loads(capsys.readouterr().out)["ledger_sync"] == {}
