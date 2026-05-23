from __future__ import annotations

import json
import importlib.util
import os
import subprocess
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def _load_queue_pump_module():
    spec = importlib.util.spec_from_file_location(
        "enoch_queue_alert_check", ROOT / "deploy" / "enoch_queue_alert_check.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_research_autopilot_module():
    spec = importlib.util.spec_from_file_location(
        "enoch_research_autopilot", ROOT / "deploy" / "enoch_research_autopilot.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_corpus_import_autopilot_module():
    spec = importlib.util.spec_from_file_location(
        "enoch_corpus_import_autopilot",
        ROOT / "deploy" / "enoch_corpus_import_autopilot.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_legacy_notion_sync_unit_is_disabled_and_non_dispatching() -> None:
    service = (ROOT / "deploy" / "enoch-notion-sync.service").read_text(
        encoding="utf-8"
    )
    script = (ROOT / "deploy" / "enoch_notion_sync.sh").read_text(encoding="utf-8")
    assert "OBSOLETE" in service
    assert "legacy Notion sync has been removed from the runtime path" in script
    assert "NOTION_TOKEN" not in script
    assert "/control/intake/ideas" in script
    assert "/control/dispatch-next" not in service + script
    assert "192.168.1.77" not in service + script


def test_paper_draft_unit_is_opt_in_and_never_dispatches() -> None:
    service = (ROOT / "deploy" / "enoch-paper-draft-next.service").read_text(
        encoding="utf-8"
    )
    script = (ROOT / "deploy" / "enoch_paper_draft_next.sh").read_text(encoding="utf-8")
    combined = service + script
    assert "Environment=ENOCH_ENABLE_PAPER_DRAFT_NEXT=0" in service
    assert "ENOCH_ENABLE_PAPER_DRAFT_NEXT:-0" in script
    assert "paper draft automation disabled" in script
    assert script.index("paper draft automation disabled") < script.index(
        "control_api_bearer_token"
    )
    assert "curl --config" in script
    assert "trap cleanup_curl_temp_files EXIT HUP INT TERM" in script
    assert "curl -fsS -X POST" not in script
    assert "/control/papers/draft-next" in combined
    assert "/control/api/publication-automation/$paper_path/rewrite-draft" in script
    assert "/control/dispatch-next" not in combined
    assert "192.168.1.77" not in combined


def test_paper_drain_is_bounded_opt_in_and_does_not_run_broad_rewrite_batches() -> None:
    script = (ROOT / "deploy" / "enoch_paper_drain_until_noop.py").read_text(
        encoding="utf-8"
    )
    assert "ENOCH_ENABLE_PAPER_DRAIN" in script
    assert "ENOCH_PAPER_DRAIN_MAX_RUNS" in script
    assert "ENOCH_PAPER_DRAIN_FAIL_LIMIT" in script
    assert "/control/papers/draft-next" in script
    assert "/control/api/publication-automation/{encoded}/rewrite-draft" in script
    assert "/control/api/publication-automation/rewrite-batch" not in script
    assert "/control/dispatch-next" not in script
    assert "192.168.1." not in script


def test_research_autopilot_unit_is_opt_in_and_bounded(tmp_path, capsys) -> None:
    autopilot = _load_research_autopilot_module()
    service = (ROOT / "deploy" / "enoch-research-autopilot.service").read_text(
        encoding="utf-8"
    )
    script = (ROOT / "deploy" / "enoch_research_autopilot.py").read_text(
        encoding="utf-8"
    )
    combined = service + script
    assert "Environment=ENOCH_ENABLE_RESEARCH_AUTOPILOT=0" in service
    assert "EnvironmentFile=-/etc/enoch-control-plane/postgres.env" in service
    assert "EnvironmentFile=-/etc/enoch-control-plane/supabase.env" not in service
    assert (
        "Environment=ENOCH_RESEARCH_QUALITY_REPORT_PATH=/var/lib/enoch-control-plane/research-quality/latest-report.json"
        in service
    )
    assert "Environment=ENOCH_RESEARCH_QUALITY_LIMIT=100" in service
    assert "ENOCH_ENABLE_RESEARCH_AUTOPILOT" in script
    assert "/control/api/research/run-cycle" in script
    assert "scripts" in script and "dspy_research_quality.py" in script
    assert "ENOCH_RESEARCH_QUALITY_REFRESH_ONLY" in script
    assert "max_provider_requests_per_run" in script
    assert "max_promotions_per_run" in script
    assert "max_dispatches_per_run" in script
    assert "max_paper_drafts_per_run" in script
    assert "max_publication_rewrites_per_run" in script
    assert "/control/dispatch-next" not in combined
    assert "/control/papers/draft-next" not in combined
    assert "192.168.1." not in combined

    with (
        patch.dict("os.environ", {"ENOCH_ENABLE_RESEARCH_AUTOPILOT": "0"}, clear=False),
        patch.object(autopilot, "_post_json") as post_json,
    ):
        assert autopilot.main() == 0
    post_json.assert_not_called()
    assert json.loads(capsys.readouterr().out)["action"] == "skipped"


def test_research_autopilot_calls_bounded_run_cycle_when_enabled(
    tmp_path, capsys
) -> None:
    autopilot = _load_research_autopilot_module()
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps({"control_api_bearer_token": "token"}), encoding="utf-8"
    )
    calls: list[dict] = []

    def fake_post(
        base_url: str, path: str, token: str, payload: dict, *, timeout: int
    ) -> dict:
        calls.append(
            {
                "base_url": base_url,
                "path": path,
                "token": token,
                "payload": payload,
                "timeout": timeout,
            }
        )
        return {"ok": True, "action": "research_cycle", "paper_drafted_count": 0}

    with (
        patch.dict(
            "os.environ",
            {"ENOCH_CONFIG": str(config), "ENOCH_ENABLE_RESEARCH_AUTOPILOT": "1"},
            clear=False,
        ),
        patch.object(autopilot, "_post_json", side_effect=fake_post),
    ):
        assert autopilot.main() == 0
    assert calls[0]["path"] == "/control/api/research/run-cycle"
    assert calls[0]["payload"]["enabled"] is True
    assert calls[0]["payload"]["max_provider_requests_per_run"] == 1
    assert calls[0]["payload"]["max_promotions_per_run"] == 10
    assert calls[0]["payload"]["max_candidates"] == 5
    assert calls[0]["payload"]["min_queue_depth_per_lane"] == 25
    assert calls[0]["payload"]["max_dispatches_per_run"] == 2
    assert calls[0]["payload"]["max_paper_drafts_per_run"] == 1
    assert calls[0]["payload"]["max_publication_rewrites_per_run"] == 1
    assert json.loads(capsys.readouterr().out)["ok"] is True


def test_corpus_import_autopilot_unit_is_opt_in_and_capped(capsys) -> None:
    autopilot = _load_corpus_import_autopilot_module()
    service = (ROOT / "deploy" / "enoch-corpus-import-autopilot.service").read_text(
        encoding="utf-8"
    )
    timer = (ROOT / "deploy" / "enoch-corpus-import-autopilot.timer").read_text(
        encoding="utf-8"
    )
    script = (ROOT / "deploy" / "enoch_corpus_import_autopilot.py").read_text(
        encoding="utf-8"
    )
    combined = service + timer + script
    assert "Environment=HOME=/root" in service
    assert "Environment=ENOCH_ENABLE_CORPUS_IMPORT_AUTOPILOT=0" in service
    assert "EnvironmentFile=-/etc/enoch-control-plane/postgres.env" in service
    assert "EnvironmentFile=-/etc/enoch-control-plane/supabase.env" not in service
    assert "Environment=ENOCH_CORPUS_IMPORT_LIMIT=1" in service
    assert "Environment=ENOCH_CORPUS_IMPORT_PREFLIGHT_ONLY=1" in service
    assert "Environment=ENOCH_CORPUS_IMPORT_AUTOCOMMIT=0" in service
    assert "Environment=ENOCH_CORPUS_IMPORT_PUSH=0" in service
    assert "Environment=ENOCH_CORPUS_IMPORT_UPDATE_GITHUB_METADATA=0" in service
    assert (
        "Environment=ENOCH_GITHUB_TOKEN_FILE=/root/.config/enoch/github-token"
        in service
    )
    assert "Environment=ENOCH_CORPUS_IMPORT_SYNC_LEDGER=0" in service
    assert "max 1" not in combined.lower()
    assert "scripts/import_from_control_plane.py" in script
    assert "scripts/update_public_release_counts.py" in script
    assert "ENOCH_CORPUS_IMPORT_AUTOCOMMIT" in script
    assert "ENOCH_CORPUS_IMPORT_PUSH" in script
    assert "ENOCH_CORPUS_IMPORT_UPDATE_GITHUB_METADATA" in script
    assert "ENOCH_CORPUS_IMPORT_SYNC_LEDGER" in script
    assert "sync_corpus_import_ledger.py" in script
    assert "skip_github_metadata=True" in script
    assert "--dry-run" in script
    assert "audit_claim_evidence_contract.py" in script
    assert "quality_scan.py" in script
    assert "build_index.py" in script
    assert "validate_public_trust_surfaces.py" in script
    assert "validate_public_release.py" in script
    assert "ENOCH_CORPUS_IMPORT_LIMIT" in script
    assert autopilot._bounded_int("ENOCH_CORPUS_IMPORT_LIMIT", 1, 1, 2) == 1
    with patch.dict("os.environ", {"ENOCH_CORPUS_IMPORT_LIMIT": "99"}, clear=False):
        assert autopilot._bounded_int("ENOCH_CORPUS_IMPORT_LIMIT", 1, 1, 2) == 2
    assert "192.168.1." not in combined

    with (
        patch.dict(
            "os.environ", {"ENOCH_ENABLE_CORPUS_IMPORT_AUTOPILOT": "0"}, clear=False
        ),
        patch.object(autopilot, "_run") as run,
    ):
        assert autopilot.main() == 0
    run.assert_not_called()
    assert json.loads(capsys.readouterr().out)["action"] == "skipped"


def test_corpus_import_autopilot_commits_only_dirty_repos_after_validation(
    tmp_path,
) -> None:
    autopilot = _load_corpus_import_autopilot_module()
    for name in autopilot.REPO_NAMES:
        repo = tmp_path / name
        repo.mkdir()
        autopilot._run(["git", "init", "-q"], cwd=repo)
        autopilot._run(["git", "config", "user.email", "test@example.com"], cwd=repo)
        autopilot._run(["git", "config", "user.name", "Test User"], cwd=repo)
        (repo / "README.md").write_text("initial\n", encoding="utf-8")
        autopilot._run(["git", "add", "README.md"], cwd=repo)
        autopilot._run(["git", "commit", "-q", "-m", "initial"], cwd=repo)

    (tmp_path / "enoch-ai-research-corpus" / "README.md").write_text(
        "changed corpus\n", encoding="utf-8"
    )
    (tmp_path / "alias8818" / "README.md").write_text(
        "changed profile\n", encoding="utf-8"
    )

    commits = autopilot._commit_changed_repos(
        tmp_path,
        {"imported": 1},
        {"stats": {"artifact_count": 378}},
    )
    assert [item["repo"] for item in commits] == [
        "enoch-ai-research-corpus",
        "alias8818",
    ]
    assert autopilot._git_changed_repos(tmp_path) == []
    corpus_subject = autopilot._run(
        ["git", "log", "-1", "--pretty=%s"], cwd=tmp_path / "enoch-ai-research-corpus"
    ).stdout.strip()
    profile_subject = autopilot._run(
        ["git", "log", "-1", "--pretty=%s"], cwd=tmp_path / "alias8818"
    ).stdout.strip()
    corpus_body = autopilot._run(
        ["git", "log", "-1", "--pretty=%B"], cwd=tmp_path / "enoch-ai-research-corpus"
    ).stdout
    assert corpus_subject == "Import 1 Enoch corpus artifact"
    assert profile_subject == "Refresh Enoch corpus release counts"
    assert "Corpus artifact count after validation: 378." in corpus_body


def test_queue_pump_dispatches_without_paper_draft_by_default(tmp_path, capsys) -> None:
    pump = _load_queue_pump_module()

    config = tmp_path / "config.json"
    config.write_text(
        json.dumps({"control_api_bearer_token": "token", "queue_pump_enabled": True}),
        encoding="utf-8",
    )
    calls: list[tuple[str, dict]] = []

    def fake_post(
        base_url: str, path: str, token: str, payload: dict, *, timeout: int = 30
    ) -> dict:
        calls.append((path, payload))
        if path == "/control/api/preflight":
            return {"ok": True, "checks": []}
        if path == "/control/api/alerts/queue-check":
            return {"should_alert": False}
        if path == "/control/dispatch-next":
            return {"action": "dispatched", "project_id": "queued"}
        raise AssertionError(f"unexpected post {path}")

    with (
        patch.dict("os.environ", {"ENOCH_CONFIG": str(config)}, clear=False),
        patch.object(
            pump,
            "_get_json",
            return_value={
                "dispatch_safe": True,
                "active_items": [],
                "next_candidate": {"project_id": "queued"},
            },
        ),
        patch.object(pump, "_post_json", side_effect=fake_post),
    ):
        assert pump.main() == 0
    assert "/control/papers/draft-next" not in [path for path, _payload in calls]
    assert "/control/dispatch-next" in [path for path, _payload in calls]
    output = json.loads(capsys.readouterr().out)
    assert output["paper_draft"]["reason"] == "queue pump paper drafting disabled"
    assert output["followup_launch"]["reason"] == "queued candidate already present"


def test_queue_pump_can_opt_into_drafting_before_dispatch(tmp_path, capsys) -> None:
    pump = _load_queue_pump_module()

    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "control_api_bearer_token": "token",
                "queue_pump_enabled": True,
                "queue_pump_paper_draft_enabled": True,
            }
        ),
        encoding="utf-8",
    )
    calls: list[tuple[str, dict]] = []

    def fake_post(
        base_url: str, path: str, token: str, payload: dict, *, timeout: int = 30
    ) -> dict:
        calls.append((path, payload))
        if path == "/control/api/preflight":
            return {"ok": True, "checks": []}
        if path == "/control/api/alerts/queue-check":
            return {"should_alert": False}
        if path == "/control/papers/draft-next":
            return {"action": "drafted", "paper": {"paper_id": "p:r:arxiv_draft"}}
        if (
            path
            == "/control/api/publication-automation/p%3Ar%3Aarxiv_draft/rewrite-draft"
        ):
            return {"rewritten": 1, "failed": 0}
        raise AssertionError(f"unexpected post {path}")

    with (
        patch.dict("os.environ", {"ENOCH_CONFIG": str(config)}, clear=False),
        patch.object(
            pump,
            "_get_json",
            return_value={
                "dispatch_safe": True,
                "active_items": [],
                "next_candidate": {"project_id": "queued"},
            },
        ),
        patch.object(pump, "_post_json", side_effect=fake_post),
    ):
        assert pump.main() == 0
    assert "/control/papers/draft-next" in [path for path, _payload in calls]
    assert "/control/api/publication-automation/p%3Ar%3Aarxiv_draft/rewrite-draft" in [
        path for path, _payload in calls
    ]
    assert "/control/dispatch-next" not in [path for path, _payload in calls]
    assert (
        json.loads(capsys.readouterr().out)["dispatch"]["reason"]
        == "paper drafted before dispatch"
    )


def test_queue_pump_dispatches_when_no_draft_candidate_exists(tmp_path) -> None:
    pump = _load_queue_pump_module()

    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "control_api_bearer_token": "token",
                "queue_pump_enabled": True,
                "queue_pump_paper_draft_enabled": True,
            }
        ),
        encoding="utf-8",
    )
    calls: list[str] = []

    def fake_post(
        base_url: str, path: str, token: str, payload: dict, *, timeout: int = 30
    ) -> dict:
        calls.append(path)
        if path == "/control/api/preflight":
            return {"ok": True, "checks": []}
        if path == "/control/api/alerts/queue-check":
            return {"should_alert": False}
        if path == "/control/papers/draft-next":
            return {
                "action": "noop",
                "reason": "no eligible completed paper-draft candidate without paper remains",
            }
        if path == "/control/dispatch-next":
            return {"action": "dispatched", "project_id": "queued"}
        raise AssertionError(f"unexpected post {path}")

    with (
        patch.dict("os.environ", {"ENOCH_CONFIG": str(config)}, clear=False),
        patch.object(
            pump,
            "_get_json",
            return_value={
                "dispatch_safe": True,
                "active_items": [],
                "next_candidate": {"project_id": "queued"},
            },
        ),
        patch.object(pump, "_post_json", side_effect=fake_post),
    ):
        assert pump.main() == 0
    assert calls.index("/control/papers/draft-next") < calls.index(
        "/control/dispatch-next"
    )


def test_queue_pump_followup_launch_is_opt_in_and_dispatches_one_candidate(
    tmp_path, capsys
) -> None:
    pump = _load_queue_pump_module()

    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "control_api_bearer_token": "token",
                "queue_pump_enabled": True,
                "queue_pump_followup_launch_enabled": True,
            }
        ),
        encoding="utf-8",
    )
    calls: list[tuple[str, dict]] = []

    def fake_post(
        base_url: str, path: str, token: str, payload: dict, *, timeout: int = 30
    ) -> dict:
        calls.append((path, payload))
        if path == "/control/api/preflight":
            return {"ok": True, "checks": []}
        if path == "/control/api/alerts/queue-check":
            return {"should_alert": False}
        if path == "/control/api/v1/followups/launch-next":
            return {
                "action": "dry_run_followup"
                if payload.get("dry_run")
                else "followup_queued"
            }
        if path == "/control/dispatch-next":
            return {"action": "dispatched", "project_id": "followup"}
        raise AssertionError(f"unexpected post {path}")

    with (
        patch.dict("os.environ", {"ENOCH_CONFIG": str(config)}, clear=False),
        patch.object(
            pump,
            "_get_json",
            return_value={
                "dispatch_safe": False,
                "dispatch_blockers": ["no queued dispatch candidate"],
                "active_items": [],
                "next_candidate": None,
            },
        ),
        patch.object(pump, "_post_json", side_effect=fake_post),
    ):
        assert pump.main() == 0

    paths = [path for path, _payload in calls]
    followup_payloads = [
        payload
        for path, payload in calls
        if path == "/control/api/v1/followups/launch-next"
    ]
    assert followup_payloads == [
        {
            "dry_run": True,
            "requested_by": "systemd:queue-pump-followup",
            "max_followup_depth": 4,
        },
        {
            "dry_run": False,
            "requested_by": "systemd:queue-pump-followup",
            "max_followup_depth": 4,
        },
    ]
    assert paths[-1] == "/control/dispatch-next"
    output = json.loads(capsys.readouterr().out)
    assert output["followup_dry_run"]["action"] == "dry_run_followup"
    assert output["followup_launch"]["action"] == "followup_queued"
    assert output["dispatch"]["action"] == "dispatched"


def test_queue_pump_followup_launch_stays_disabled_by_default(tmp_path, capsys) -> None:
    pump = _load_queue_pump_module()

    config = tmp_path / "config.json"
    config.write_text(
        json.dumps({"control_api_bearer_token": "token", "queue_pump_enabled": True}),
        encoding="utf-8",
    )
    calls: list[tuple[str, dict]] = []

    def fake_post(
        base_url: str, path: str, token: str, payload: dict, *, timeout: int = 30
    ) -> dict:
        calls.append((path, payload))
        if path == "/control/api/preflight":
            return {"ok": True, "checks": []}
        if path == "/control/api/alerts/queue-check":
            return {"should_alert": False}
        raise AssertionError(f"unexpected post {path}")

    with (
        patch.dict("os.environ", {"ENOCH_CONFIG": str(config)}, clear=False),
        patch.object(
            pump,
            "_get_json",
            return_value={
                "dispatch_safe": True,
                "active_items": [],
                "next_candidate": None,
            },
        ),
        patch.object(pump, "_post_json", side_effect=fake_post),
    ):
        assert pump.main() == 0

    assert "/control/api/v1/followups/launch-next" not in [
        path for path, _payload in calls
    ]
    assert "/control/dispatch-next" not in [path for path, _payload in calls]
    output = json.loads(capsys.readouterr().out)
    assert output["followup_launch"]["reason"] == "queue pump follow-up launch disabled"
    assert output["dispatch"]["reason"] == "no queued candidate"


def test_install_script_keeps_draft_units_opt_in() -> None:
    install = (ROOT / "scripts" / "install-control-plane.sh").read_text(
        encoding="utf-8"
    )
    assert "ENOCH_INSTALL_LEGACY_NOTION_UNITS:-0" in install
    assert (
        "Supabase-native /control/intake/ideas is the supported intake path" in install
    )
    assert "ENOCH_INSTALL_PAPER_DRAFT_NEXT_UNITS:-0" in install
    assert "enoch-paper-draft-next.service" in install
    assert "enoch-paper-draft-next.timer" in install


def test_codex_runner_scrubs_callback_secret_from_codex_environment(tmp_path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    prompt = tmp_path / "prompt.md"
    prompt.write_text("hello", encoding="utf-8")
    fake_codex = tmp_path / "fake-codex"
    fake_codex.write_text(
        """#!/usr/bin/env bash
env | sort > "$ENOCH_PROJECT_DIR/.enoch/codex-env.txt"
printf '{"type":"session","session_id":"fake-session"}\n'
""",
        encoding="utf-8",
    )
    fake_codex.chmod(0o755)
    env = os.environ.copy()
    env.update(
        {
            "CODEX_BIN": str(fake_codex),
            "ENOCH_COMPLETION_CALLBACK_URL": "http://127.0.0.1/callback",
            "ENOCH_COMPLETION_CALLBACK_TOKEN": "super-secret-callback-token",
            "ENOCH_COMPLETION_CALLBACK_TIMEOUT_SEC": "1",
            "ENOCH_WORKER_STATE_DIR": str(tmp_path / "state"),
        }
    )

    result = subprocess.run(
        [
            str(ROOT / "deploy" / "enoch_codex_runner.sh"),
            "--run-id",
            "run-1",
            "--project-id",
            "project-1",
            "--project-dir",
            str(project),
            "--prompt-file",
            str(prompt),
        ],
        env=env,
        text=True,
        capture_output=True,
        timeout=15,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    codex_env = (project / ".enoch" / "codex-env.txt").read_text(encoding="utf-8")
    assert "ENOCH_COMPLETION_CALLBACK_TOKEN" not in codex_env
    assert "super-secret-callback-token" not in codex_env
    assert "ENOCH_COMPLETION_CALLBACK_URL" not in codex_env


def test_codex_runner_disables_spark_backed_explore_by_default() -> None:
    script = (ROOT / "deploy" / "enoch_codex_runner.sh").read_text(encoding="utf-8")
    assert 'export USE_OMX_EXPLORE_CMD="${USE_OMX_EXPLORE_CMD:-0}"' in script
    assert "omx exec" not in script
    assert "codex exec" in script or "CODEX_BIN" in script
    assert script.index("export USE_OMX_EXPLORE_CMD=") < script.index('"${cmd[@]}"')


def test_codex_dispatch_resolves_runner_relative_to_deploy_script() -> None:
    script = (ROOT / "deploy" / "enoch_codex_dispatch.sh").read_text(encoding="utf-8")
    assert 'SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"' in script
    assert (
        'RUNNER_SCRIPT="${ENOCH_CODEX_RUNNER_SCRIPT:-$SCRIPT_DIR/enoch_codex_runner.sh}"'
        in script
    )
    assert (
        "$HOME/projects/enoch-agentic-research-system/deploy/enoch_codex_runner.sh"
        not in script
    )


def test_codex_runner_uses_durable_callback_outbox() -> None:
    runner = (ROOT / "deploy" / "enoch_codex_runner.sh").read_text(encoding="utf-8")
    app = (ROOT / "enoch_control_plane" / "app.py").read_text(encoding="utf-8")
    outbox = (ROOT / "enoch_control_plane" / "callback_outbox.py").read_text(
        encoding="utf-8"
    )
    assert '"ENOCH_WORKER_STATE_DIR": str(config.expanded_state_dir)' in app
    assert "callback_outbox write" in runner
    assert 'export PYTHONPATH="$REPO_ROOT:${PYTHONPATH:-}"' in runner
    assert "callback_outbox deliver" in runner
    assert "--token-stdin" in runner
    assert '--token "$CALLBACK_TOKEN"' not in runner
    assert 'cd "$REPO_ROOT"' in runner
    assert "callback delivery failed; durable callback outbox will retry" in runner
    assert "def _mark_local_worker_state_delivered" in outbox
    assert 'record["last_idempotency_key"] = payload.get("idempotency_key")' in outbox
    assert "await _replay_callback_outbox_once()" in app


def test_codex_runner_uses_fixed_system_path_before_resolving_codex_binary() -> None:
    script = (ROOT / "deploy" / "enoch_codex_runner.sh").read_text(encoding="utf-8")
    assert (
        'export PATH="$HOME/.nvm/versions/node/v22.22.1/bin:$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"'
        in script
    )
    assert 'CODEX_BIN="${CODEX_BIN:-$(command -v codex || true)}"' in script
    assert "refusing project-relative codex binary" in script
    assert "refusing project-local codex binary" in script
    assert script.index(
        'export PATH="$HOME/.nvm/versions/node/v22.22.1/bin:$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"'
    ) < script.index('CODEX_BIN="${CODEX_BIN:-$(command -v codex || true)}"')


def test_proof_local_uses_status_endpoint_that_matches_its_grep_assertions() -> None:
    script = (ROOT / "scripts" / "proof-local.sh").read_text(encoding="utf-8")

    assert 'ENOCH_STATUS_ENDPOINT="/control/api/status"' in script
    assert "grep -q '\"dispatch_safe\"'" in script


def test_enoch_worker_skill_uses_codex_description_frontmatter() -> None:
    skill = (ROOT / "codex-skills" / "enoch-worker" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    header = skill.split("---", 2)[1]
    assert "description:" in header
    assert "summary:" not in header


def test_control_plane_service_has_bounded_shutdown_for_deploy_restarts() -> None:
    service = (ROOT / "deploy" / "enoch-worker-gate.service").read_text(
        encoding="utf-8"
    )
    assert "TimeoutStopSec=10" in service
    assert "KillMode=mixed" in service
    assert "FinalKillSignal=SIGKILL" in service


def test_source_lineage_check_unit_is_post_cutover_guard() -> None:
    service = (ROOT / "deploy" / "enoch-source-lineage-check.service").read_text(
        encoding="utf-8"
    )
    timer = (ROOT / "deploy" / "enoch-source-lineage-check.timer").read_text(
        encoding="utf-8"
    )
    script = (ROOT / "deploy" / "enoch_source_lineage_check.py").read_text(
        encoding="utf-8"
    )
    combined = service + timer + script
    assert "scripts/validate_source_lineage.py" not in service
    assert "deploy/enoch_source_lineage_check.py --json" in service
    assert "EnvironmentFile=-/etc/enoch-control-plane/postgres.env" in service
    assert "User=enoch" in service
    assert "Group=enoch" in service
    assert "EnvironmentFile=-/etc/enoch-control-plane/supabase.env" in service
    assert (
        "Environment=ENOCH_SOURCE_LINEAGE_CREATED_AFTER=2026-05-19T17:51:00Z" in service
    )
    assert (
        "Environment=ENOCH_SOURCE_LINEAGE_REPORT_PATH=/var/lib/enoch-control-plane/source-lineage/latest-report.json"
        in service
    )
    assert "OnUnitActiveSec=10min" in timer
    assert "last-alert-fingerprint" in script
    assert "send_pushover" in script
    install = (ROOT / "scripts" / "install-control-plane.sh").read_text(
        encoding="utf-8"
    )
    assert "enoch-source-lineage-check.service" in install
    assert "enoch-source-lineage-check.timer" in install
    assert "notion" not in combined.lower()


def test_source_lineage_check_runs_as_direct_deploy_script(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            os.sys.executable,
            str(ROOT / "deploy" / "enoch_source_lineage_check.py"),
            "--help",
        ],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert "source-lineage" in result.stdout


def test_research_default_machine_is_consistent_and_no_longer_hardcoded_ip() -> None:
    """Regression guard for the inconsistent ENOCH_RESEARCH_DEFAULT_MACHINE fix.

    The old hardcoded 192.168.1.77 must no longer appear as a fallback default
    for research machine target in the router (all paths must use the
    placeholder "research-facility-node" or an explicit env var).
    """
    router_source = (
        ROOT / "enoch_control_plane" / "control_plane" / "router.py"
    ).read_text(encoding="utf-8")
    # Must not contain the old IP as a default value for the research machine
    assert 'ENOCH_RESEARCH_DEFAULT_MACHINE", "192.168.1.77"' not in router_source
    assert "ENOCH_RESEARCH_DEFAULT_MACHINE', '192.168.1.77'" not in router_source
    # The new canonical placeholder must be present in the research paths
    assert router_source.count("research-facility-node") >= 6


def test_deploy_queue_alert_check_reasons_centralized_no_s1192_duplication() -> None:
    """AGENTS.md deterministic validator for top CRITICAL S1192 duplication in deploy scripts.

    The repeated "reason" string literals in enoch_queue_alert_check.py must be
    defined exactly once (as module constants) after extraction. This directly
    targets the current top duplication findings (multiple occurrences of the
    same alert/dispatch/active reasons).
    """
    script_source = (ROOT / "deploy" / "enoch_queue_alert_check.py").read_text(
        encoding="utf-8"
    )

    # Each of these reasons currently appears 3+ times; must be 1 after const extraction
    for reason in [
        "alert findings present; operator reconciliation required first",
        "dispatch not safe",
        "active worker lane present",
    ]:
        count = script_source.count(f'"{reason}"')
        assert count == 1, (
            f"reason {reason!r} still duplicated (count={count}); extract to const"
        )


def test_deploy_research_autopilot_missing_database_url_centralized() -> None:
    """AGENTS.md validator for current top S1192 (enoch_research_autopilot.py:204).

    "missing database URL" (flagged in latest Sonar top duplication) must appear
    exactly once after const extraction.
    """
    script_source = (ROOT / "deploy" / "enoch_research_autopilot.py").read_text(
        encoding="utf-8"
    )
    lit = "missing database URL"
    count = script_source.count(f'"{lit}"')
    assert count == 1, (
        f"{lit!r} still duplicated in autopilot (count={count}); extract to const"
    )


def test_app_py_project_directory_label_centralized_no_s1192_duplication() -> None:
    """AGENTS.md validator for current top S1192 (enoch_control_plane/app.py:2182).

    The literal "project directory" (used as label in _checked_exists/_checked_is_dir)
    is duplicated 7 times per Sonar. Must be 1 after const extraction.
    """
    src = (ROOT / "enoch_control_plane" / "app.py").read_text(encoding="utf-8")
    lit = "project directory"
    count = src.count(f'"{lit}"')
    assert count == 1, (
        f"{lit!r} still duplicated in app.py (count={count}); extract to const"
    )


def test_read_models_missing_project_decision_artifact_centralized() -> None:
    """AGENTS.md validator for current top S1192 (read_models.py:303).

    "missing project decision artifact" (flagged in latest Sonar top duplication, 4x)
    must appear exactly once after const extraction.
    """
    src = (ROOT / "enoch_control_plane" / "control_plane" / "read_models.py").read_text(
        encoding="utf-8"
    )
    lit = "missing project decision artifact"
    count = src.count(f'"{lit}"')
    assert count == 1, (
        f"{lit!r} still duplicated in read_models (count={count}); extract to const"
    )


def test_router_synthetic_base_url_centralized_no_s1192_duplication() -> None:
    """AGENTS.md validator for current top S1192 (router.py:280).

    "https://synthetic.int.exe.xyz" (flagged in latest Sonar top duplication, 4x in
    _resolve_research_cycle_params getenv defaults and f-string fallback)
    must appear exactly once after const extraction.
    """
    src = (ROOT / "enoch_control_plane" / "control_plane" / "router.py").read_text(
        encoding="utf-8"
    )
    lit = "https://synthetic.int.exe.xyz"
    count = src.count(f'"{lit}"')
    assert count == 1, (
        f"{lit!r} still duplicated in router (count={count}); extract to const"
    )


def test_router_worker_preflight_failed_centralized_no_s1192_duplication() -> None:
    """AGENTS.md validator for current top S1192 in router.py (line 2365).

    "worker preflight failed" (flagged in latest Sonar top duplication, 3x in
    error reasons and messages) must appear exactly once after const extraction.
    """
    src = (ROOT / "enoch_control_plane" / "control_plane" / "router.py").read_text(
        encoding="utf-8"
    )
    lit = "worker preflight failed"
    count = src.count(f'"{lit}"')
    assert count == 1, (
        f"{lit!r} still duplicated in router (count={count}); extract to const"
    )


def test_router_research_facility_ledger_supabase_centralized_no_s1192_duplication() -> (
    None
):
    """AGENTS.md validator for current top S1192 (router.py:146).

    "Research Facility ledger writes require the Supabase control-plane store"
    (3x in _HTTP_501_SUPABASE_LEDGER and HTTPException detail paths) must appear
    exactly once after const extraction.
    """
    src = (ROOT / "enoch_control_plane" / "control_plane" / "router.py").read_text(
        encoding="utf-8"
    )
    lit = "Research Facility ledger writes require the Supabase control-plane store"
    count = src.count(f'"{lit}"')
    assert count == 1, (
        f"{lit!r} still duplicated in router (count={count}); extract to const"
    )


def test_router_paper_review_draft_rewritten_centralized_no_s1192_duplication() -> None:
    """AGENTS.md validator for current top remaining S1192 in router.py (line 5092).

    "paper_review.draft_rewritten" (flagged in latest Sonar top duplication, 3x in
    comparisons and event_type strings) must appear exactly once after const extraction.
    """
    src = (ROOT / "enoch_control_plane" / "control_plane" / "router.py").read_text(
        encoding="utf-8"
    )
    lit = "paper_review.draft_rewritten"
    count = src.count(f'"{lit}"')
    assert count == 1, (
        f"{lit!r} still duplicated in router (count={count}); extract to const"
    )


def test_router_control_plane_db_worker_preflight_centralized_no_s1192_duplication() -> (
    None
):
    """AGENTS.md validator for S1192 in router.py (~4922).

    "control_plane_db+worker_preflight" (5x in DashboardFinding source fields and
    conflict checks) must appear exactly once after const extraction.
    """
    src = (ROOT / "enoch_control_plane" / "control_plane" / "router.py").read_text(
        encoding="utf-8"
    )
    lit = "control_plane_db+worker_preflight"
    count = src.count(f'"{lit}"')
    assert count == 1, (
        f"{lit!r} still duplicated in router (count={count}); extract to const"
    )


def test_router_supabase_native_ideas_workbench_centralized_no_s1192_duplication() -> (
    None
):
    """AGENTS.md validator for S1192 in router.py (ideas workbench authority).

    "Supabase-native ideas workbench" (3x in authority and db_freshness paths) must
    appear exactly once after const extraction.
    """
    src = (ROOT / "enoch_control_plane" / "control_plane" / "router.py").read_text(
        encoding="utf-8"
    )
    lit = "Supabase-native ideas workbench"
    count = src.count(f'"{lit}"')
    assert count == 1, (
        f"{lit!r} still duplicated in router (count={count}); extract to const"
    )


def test_router_publication_automation_item_not_found_centralized_no_s1192_duplication() -> (
    None
):
    """AGENTS.md validator for S1192 in router.py (line 845).

    "publication automation item not found" (5x in PublicationAutomationNotFoundError
    and HTTPException detail paths) must appear exactly once after const extraction.
    """
    src = (ROOT / "enoch_control_plane" / "control_plane" / "router.py").read_text(
        encoding="utf-8"
    )
    lit = "publication automation item not found"
    count = src.count(f'"{lit}"')
    assert count == 1, (
        f"{lit!r} still duplicated in router (count={count}); extract to const"
    )


def test_state_contract_source_provenance_status_only_centralized_no_s1192_duplication() -> (
    None
):
    """AGENTS.md validator for current top S1192 (state_contract.py:670).

    "source/provenance status only" (flagged in latest Sonar top duplication, 5x)
    must appear exactly once after const extraction.
    """
    src = (
        ROOT / "enoch_control_plane" / "control_plane" / "state_contract.py"
    ).read_text(encoding="utf-8")
    lit = "source/provenance status only"
    count = src.count(f'"{lit}"')
    assert count == 1, (
        f"{lit!r} still duplicated in state_contract (count={count}); extract to const"
    )


def test_supabase_store_sql_status_count_query_centralized_no_s1192_duplication() -> (
    None
):
    """AGENTS.md validator for current top S1192 (supabase_store.py:744).

    The SQL literal "select status, count(*) as count from queue_items group by status"
    (flagged in latest Sonar top duplication, 3x) must appear exactly once after const extraction.
    """
    src = (
        ROOT / "enoch_control_plane" / "control_plane" / "supabase_store.py"
    ).read_text(encoding="utf-8")
    lit = "select status, count(*) as count from queue_items group by status"
    count = src.count(f'"{lit}"')
    assert count == 1, (
        f"{lit!r} still duplicated in supabase_store (count={count}); extract to const"
    )


def test_supabase_store_queue_status_equals_param_centralized_no_s1192_duplication() -> (
    None
):
    """AGENTS.md validator for S1192 (supabase_store.py:1598, issue 4dc0fd65).

    "q.status = %s" (flagged 5x) must appear exactly once after const extraction.
    """
    src = (
        ROOT / "enoch_control_plane" / "control_plane" / "supabase_store.py"
    ).read_text(encoding="utf-8")
    lit = "q.status = %s"
    count = src.count(f'"{lit}"')
    assert count == 1, (
        f"{lit!r} still duplicated in supabase_store (count={count}); extract to const"
    )


def test_backfill_project_decision_json_centralized_no_s1192_duplication() -> None:
    """AGENTS.md validator for current top S1192 (backfill_control_plane_to_supabase.py:289).

    "project_decision.json" (flagged in latest Sonar top duplication, 5x)
    must appear exactly once after const extraction.
    """
    src = (ROOT / "scripts" / "backfill_control_plane_to_supabase.py").read_text(
        encoding="utf-8"
    )
    lit = "project_decision.json"
    count = src.count(f'"{lit}"')
    assert count == 1, (
        f"{lit!r} still duplicated in backfill (count={count}); extract to const"
    )


def test_generate_state_vocabulary_plan_queue_items_status_centralized_no_s1192_duplication() -> (
    None
):
    """AGENTS.md validator for current top S1192 (generate_state_vocabulary_plan.py:41).

    "queue_items.status" (flagged in latest Sonar top duplication, 13x)
    must appear exactly once after const extraction.
    """
    src = (ROOT / "scripts" / "generate_state_vocabulary_plan.py").read_text(
        encoding="utf-8"
    )
    lit = "queue_items.status"
    count = src.count(f'"{lit}"')
    assert count == 1, (
        f"{lit!r} still duplicated in vocabulary plan (count={count}); extract to const"
    )


def test_generate_state_vocabulary_plan_project_decisions_decision_gate_state_centralized_no_s1192_duplication() -> (
    None
):
    """AGENTS.md validator for current top remaining S1192 in generate_state_vocabulary_plan.py (line 46).

    "project_decisions.decision_gate_state" (flagged in latest Sonar top duplication, 7x)
    must appear exactly once after const extraction.
    """
    src = (ROOT / "scripts" / "generate_state_vocabulary_plan.py").read_text(
        encoding="utf-8"
    )
    lit = "project_decisions.decision_gate_state"
    count = src.count(f'"{lit}"')
    assert count == 1, (
        f"{lit!r} still duplicated in vocabulary plan (count={count}); extract to const"
    )


def test_generate_state_vocabulary_plan_runs_state_centralized_no_s1192_duplication() -> (
    None
):
    """AGENTS.md validator for current top remaining S1192 in generate_state_vocabulary_plan.py (line 81).

    "runs.state" (flagged in latest Sonar top duplication, ~20x)
    must appear exactly once after const extraction.
    """
    src = (ROOT / "scripts" / "generate_state_vocabulary_plan.py").read_text(
        encoding="utf-8"
    )
    lit = "runs.state"
    count = src.count(f'"{lit}"')
    assert count == 1, (
        f"{lit!r} still duplicated in vocabulary plan (count={count}); extract to const"
    )


def test_generate_state_vocabulary_plan_papers_paper_status_centralized_no_s1192_duplication() -> (
    None
):
    """AGENTS.md validator for current top remaining S1192 in generate_state_vocabulary_plan.py (line 83).

    "papers.paper_status" (flagged in latest Sonar top duplication, 10x)
    must appear exactly once after const extraction.
    """
    src = (ROOT / "scripts" / "generate_state_vocabulary_plan.py").read_text(
        encoding="utf-8"
    )
    lit = "papers.paper_status"
    count = src.count(f'"{lit}"')
    assert count == 1, (
        f"{lit!r} still duplicated in vocabulary plan (count={count}); extract to const"
    )


def test_generate_state_vocabulary_plan_publication_automation_items_automation_status_centralized_no_s1192_duplication() -> (
    None
):
    """AGENTS.md validator for current top remaining S1192 in generate_state_vocabulary_plan.py (line 88).

    "publication_automation_items.automation_status" (flagged in latest Sonar top duplication, 12x)
    must appear exactly once after const extraction.
    """
    src = (ROOT / "scripts" / "generate_state_vocabulary_plan.py").read_text(
        encoding="utf-8"
    )
    lit = "publication_automation_items.automation_status"
    count = src.count(f'"{lit}"')
    assert count == 1, (
        f"{lit!r} still duplicated in vocabulary plan (count={count}); extract to const"
    )


def test_push_public_release_bundle_public_release_integrity_centralized_no_s1192_duplication() -> (
    None
):
    """AGENTS.md validator for current top S1192 (push_public_release_bundle.py:457).

    "Public release integrity" (flagged in latest Sonar top duplication, 4x)
    must appear exactly once after const extraction.
    """
    src = (ROOT / "scripts" / "push_public_release_bundle.py").read_text(
        encoding="utf-8"
    )
    lit = "Public release integrity"
    count = src.count(f'"{lit}"')
    assert count == 1, (
        f"{lit!r} still duplicated in push_public_release_bundle (count={count}); extract to const"
    )


def test_validate_supabase_readonly_adapter_draft_md_centralized_no_s1192_duplication() -> (
    None
):
    """AGENTS.md validator for current top S1192 (validate_supabase_readonly_adapter.py:228).

    "draft.md" (flagged in latest Sonar top duplication, 3x)
    must appear exactly once after const extraction.
    """
    src = (ROOT / "scripts" / "validate_supabase_readonly_adapter.py").read_text(
        encoding="utf-8"
    )
    lit = "draft.md"
    count = src.count(f'"{lit}"')
    assert count == 1, (
        f"{lit!r} still duplicated in validate_supabase_readonly_adapter (count={count}); extract to const"
    )


def test_validate_supabase_readonly_adapter_draft_tex_centralized_no_s1192_duplication() -> (
    None
):
    """AGENTS.md validator for current top remaining S1192 in validate_supabase_readonly_adapter.py (line 233).

    "draft.tex" (flagged in latest Sonar top duplication, 3x)
    must appear exactly once after const extraction.
    """
    src = (ROOT / "scripts" / "validate_supabase_readonly_adapter.py").read_text(
        encoding="utf-8"
    )
    lit = "draft.tex"
    count = src.count(f'"{lit}"')
    assert count == 1, (
        f"{lit!r} still duplicated in validate_supabase_readonly_adapter (count={count}); extract to const"
    )


def test_validate_supabase_readonly_adapter_evidence_json_centralized_no_s1192_duplication() -> (
    None
):
    """AGENTS.md validator for current top remaining S1192 in validate_supabase_readonly_adapter.py (line 234).

    "evidence.json" (flagged in latest Sonar top duplication, 3x)
    must appear exactly once after const extraction.
    """
    src = (ROOT / "scripts" / "validate_supabase_readonly_adapter.py").read_text(
        encoding="utf-8"
    )
    lit = "evidence.json"
    count = src.count(f'"{lit}"')
    assert count == 1, (
        f"{lit!r} still duplicated in validate_supabase_readonly_adapter (count={count}); extract to const"
    )


def test_validate_supabase_readonly_adapter_claims_json_centralized_no_s1192_duplication() -> (
    None
):
    """AGENTS.md validator for current top remaining S1192 in validate_supabase_readonly_adapter.py (line 235).

    "claims.json" (flagged in latest Sonar top duplication, 3x)
    must appear exactly once after const extraction.
    """
    src = (ROOT / "scripts" / "validate_supabase_readonly_adapter.py").read_text(
        encoding="utf-8"
    )
    lit = "claims.json"
    count = src.count(f'"{lit}"')
    assert count == 1, (
        f"{lit!r} still duplicated in validate_supabase_readonly_adapter (count={count}); extract to const"
    )


def test_validate_supabase_readonly_adapter_manifest_json_centralized_no_s1192_duplication() -> (
    None
):
    """AGENTS.md validator for current top remaining S1192 in validate_supabase_readonly_adapter.py (line 236).

    "manifest.json" (flagged in latest Sonar top duplication, 3x)
    must appear exactly once after const extraction.
    """
    src = (ROOT / "scripts" / "validate_supabase_readonly_adapter.py").read_text(
        encoding="utf-8"
    )
    lit = "manifest.json"
    count = src.count(f'"{lit}"')
    assert count == 1, (
        f"{lit!r} still duplicated in validate_supabase_readonly_adapter (count={count}); extract to const"
    )


def test_research_facility_sql_guard_select_centralized_no_s1192_duplication() -> None:
    """AGENTS.md validator for S1192 (research_facility.py:792).

    "    select 1" (sql_raise_if_exists guard fragment in emit_sql) must appear
    exactly once after const extraction to _SQL_GUARD_EXISTS_SELECT.
    """
    src = (ROOT / "scripts" / "research_facility.py").read_text(encoding="utf-8")
    lit = "    select 1"
    count = src.count(f'"{lit}"')
    assert count == 1, (
        f"{lit!r} still duplicated in research_facility (count={count}); extract to const"
    )
    assert src.count("_SQL_GUARD_EXISTS_SELECT") >= 7, (
        "emit_sql guards must reference _SQL_GUARD_EXISTS_SELECT"
    )


def test_research_facility_sql_guard_and_close_centralized_no_s1192_duplication() -> (
    None
):
    """AGENTS.md validator for S1192 (de91349f, research_facility.py emit_sql).

    "      )" (closing paren for identity-conflict guards) must appear exactly
    once after const extraction to _SQL_GUARD_AND_CLOSE.
    """
    src = (ROOT / "scripts" / "research_facility.py").read_text(encoding="utf-8")
    lit = "      )"
    count = src.count(f'"{lit}"')
    assert count == 1, (
        f"{lit!r} still duplicated in research_facility (count={count}); extract to const"
    )
    assert src.count("_SQL_GUARD_AND_CLOSE") >= 7, (
        "emit_sql guards must reference _SQL_GUARD_AND_CLOSE"
    )
