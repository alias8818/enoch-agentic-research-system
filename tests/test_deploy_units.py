from __future__ import annotations

import json
import importlib.util
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def _load_queue_pump_module():
    spec = importlib.util.spec_from_file_location("enoch_queue_alert_check", ROOT / "deploy" / "enoch_queue_alert_check.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_legacy_notion_sync_unit_is_disabled_and_non_dispatching() -> None:
    service = (ROOT / "deploy" / "enoch-notion-sync.service").read_text(encoding="utf-8")
    script = (ROOT / "deploy" / "enoch_notion_sync.sh").read_text(encoding="utf-8")
    assert "OBSOLETE" in service
    assert "legacy Notion sync has been removed from the runtime path" in script
    assert "NOTION_TOKEN" not in script
    assert "/control/intake/ideas" in script
    assert "/control/dispatch-next" not in service + script
    assert "192.168.1.77" not in service + script


def test_paper_draft_unit_is_opt_in_and_never_dispatches() -> None:
    service = (ROOT / "deploy" / "enoch-paper-draft-next.service").read_text(encoding="utf-8")
    script = (ROOT / "deploy" / "enoch_paper_draft_next.sh").read_text(encoding="utf-8")
    combined = service + script
    assert "Environment=ENOCH_ENABLE_PAPER_DRAFT_NEXT=0" in service
    assert "ENOCH_ENABLE_PAPER_DRAFT_NEXT:-0" in script
    assert "paper draft automation disabled" in script
    assert script.index("paper draft automation disabled") < script.index("control_api_bearer_token")
    assert "curl --config" in script
    assert "trap cleanup_curl_temp_files EXIT HUP INT TERM" in script
    assert 'curl -fsS -X POST' not in script
    assert "/control/papers/draft-next" in combined
    assert "/control/api/publication-automation/$paper_path/rewrite-draft" in script
    assert "/control/dispatch-next" not in combined
    assert "192.168.1.77" not in combined


def test_paper_drain_is_bounded_opt_in_and_does_not_run_broad_rewrite_batches() -> None:
    script = (ROOT / "deploy" / "enoch_paper_drain_until_noop.py").read_text(encoding="utf-8")
    assert "ENOCH_ENABLE_PAPER_DRAIN" in script
    assert "ENOCH_PAPER_DRAIN_MAX_RUNS" in script
    assert "ENOCH_PAPER_DRAIN_FAIL_LIMIT" in script
    assert "/control/papers/draft-next" in script
    assert "/control/api/publication-automation/{encoded}/rewrite-draft" in script
    assert "/control/api/publication-automation/rewrite-batch" not in script
    assert "/control/dispatch-next" not in script
    assert "192.168.1." not in script


def test_queue_pump_dispatches_without_paper_draft_by_default(tmp_path, capsys) -> None:
    pump = _load_queue_pump_module()

    config = tmp_path / "config.json"
    config.write_text(json.dumps({"control_api_bearer_token": "token", "queue_pump_enabled": True}), encoding="utf-8")
    calls: list[tuple[str, dict]] = []

    def fake_post(base_url: str, path: str, token: str, payload: dict, *, timeout: int = 30) -> dict:
        calls.append((path, payload))
        if path == "/control/api/preflight":
            return {"ok": True, "checks": []}
        if path == "/control/api/alerts/queue-check":
            return {"should_alert": False}
        if path == "/control/dispatch-next":
            return {"action": "dispatched", "project_id": "queued"}
        raise AssertionError(f"unexpected post {path}")

    with patch.dict("os.environ", {"ENOCH_CONFIG": str(config)}, clear=False), patch.object(pump, "_get_json", return_value={"dispatch_safe": True, "active_items": [], "next_candidate": {"project_id": "queued"}}), patch.object(pump, "_post_json", side_effect=fake_post):
        assert pump.main() == 0
    assert "/control/papers/draft-next" not in [path for path, _payload in calls]
    assert "/control/dispatch-next" in [path for path, _payload in calls]
    output = json.loads(capsys.readouterr().out)
    assert output["paper_draft"]["reason"] == "queue pump paper drafting disabled"
    assert output["followup_launch"]["reason"] == "queued candidate already present"


def test_queue_pump_can_opt_into_drafting_before_dispatch(tmp_path, capsys) -> None:
    pump = _load_queue_pump_module()

    config = tmp_path / "config.json"
    config.write_text(json.dumps({"control_api_bearer_token": "token", "queue_pump_enabled": True, "queue_pump_paper_draft_enabled": True}), encoding="utf-8")
    calls: list[tuple[str, dict]] = []

    def fake_post(base_url: str, path: str, token: str, payload: dict, *, timeout: int = 30) -> dict:
        calls.append((path, payload))
        if path == "/control/api/preflight":
            return {"ok": True, "checks": []}
        if path == "/control/api/alerts/queue-check":
            return {"should_alert": False}
        if path == "/control/papers/draft-next":
            return {"action": "drafted", "paper": {"paper_id": "p:r:arxiv_draft"}}
        if path == "/control/api/publication-automation/p%3Ar%3Aarxiv_draft/rewrite-draft":
            return {"rewritten": 1, "failed": 0}
        raise AssertionError(f"unexpected post {path}")

    with patch.dict("os.environ", {"ENOCH_CONFIG": str(config)}, clear=False), patch.object(pump, "_get_json", return_value={"dispatch_safe": True, "active_items": [], "next_candidate": {"project_id": "queued"}}), patch.object(pump, "_post_json", side_effect=fake_post):
        assert pump.main() == 0
    assert "/control/papers/draft-next" in [path for path, _payload in calls]
    assert "/control/api/publication-automation/p%3Ar%3Aarxiv_draft/rewrite-draft" in [path for path, _payload in calls]
    assert "/control/dispatch-next" not in [path for path, _payload in calls]
    assert json.loads(capsys.readouterr().out)["dispatch"]["reason"] == "paper drafted before dispatch"


def test_queue_pump_dispatches_when_no_draft_candidate_exists(tmp_path) -> None:
    pump = _load_queue_pump_module()

    config = tmp_path / "config.json"
    config.write_text(json.dumps({"control_api_bearer_token": "token", "queue_pump_enabled": True, "queue_pump_paper_draft_enabled": True}), encoding="utf-8")
    calls: list[str] = []

    def fake_post(base_url: str, path: str, token: str, payload: dict, *, timeout: int = 30) -> dict:
        calls.append(path)
        if path == "/control/api/preflight":
            return {"ok": True, "checks": []}
        if path == "/control/api/alerts/queue-check":
            return {"should_alert": False}
        if path == "/control/papers/draft-next":
            return {"action": "noop", "reason": "no eligible completed paper-draft candidate without paper remains"}
        if path == "/control/dispatch-next":
            return {"action": "dispatched", "project_id": "queued"}
        raise AssertionError(f"unexpected post {path}")

    with patch.dict("os.environ", {"ENOCH_CONFIG": str(config)}, clear=False), patch.object(pump, "_get_json", return_value={"dispatch_safe": True, "active_items": [], "next_candidate": {"project_id": "queued"}}), patch.object(pump, "_post_json", side_effect=fake_post):
        assert pump.main() == 0
    assert calls.index("/control/papers/draft-next") < calls.index("/control/dispatch-next")


def test_queue_pump_followup_launch_is_opt_in_and_dispatches_one_candidate(tmp_path, capsys) -> None:
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

    def fake_post(base_url: str, path: str, token: str, payload: dict, *, timeout: int = 30) -> dict:
        calls.append((path, payload))
        if path == "/control/api/preflight":
            return {"ok": True, "checks": []}
        if path == "/control/api/alerts/queue-check":
            return {"should_alert": False}
        if path == "/control/api/v1/followups/launch-next":
            return {"action": "dry_run_followup" if payload.get("dry_run") else "followup_queued"}
        if path == "/control/dispatch-next":
            return {"action": "dispatched", "project_id": "followup"}
        raise AssertionError(f"unexpected post {path}")

    with patch.dict("os.environ", {"ENOCH_CONFIG": str(config)}, clear=False), patch.object(pump, "_get_json", return_value={"dispatch_safe": False, "dispatch_blockers": ["no queued dispatch candidate"], "active_items": [], "next_candidate": None}), patch.object(pump, "_post_json", side_effect=fake_post):
        assert pump.main() == 0

    paths = [path for path, _payload in calls]
    followup_payloads = [payload for path, payload in calls if path == "/control/api/v1/followups/launch-next"]
    assert followup_payloads == [
        {"dry_run": True, "requested_by": "systemd:queue-pump-followup", "max_followup_depth": 2},
        {"dry_run": False, "requested_by": "systemd:queue-pump-followup", "max_followup_depth": 2},
    ]
    assert paths[-1] == "/control/dispatch-next"
    output = json.loads(capsys.readouterr().out)
    assert output["followup_dry_run"]["action"] == "dry_run_followup"
    assert output["followup_launch"]["action"] == "followup_queued"
    assert output["dispatch"]["action"] == "dispatched"


def test_queue_pump_followup_launch_stays_disabled_by_default(tmp_path, capsys) -> None:
    pump = _load_queue_pump_module()

    config = tmp_path / "config.json"
    config.write_text(json.dumps({"control_api_bearer_token": "token", "queue_pump_enabled": True}), encoding="utf-8")
    calls: list[tuple[str, dict]] = []

    def fake_post(base_url: str, path: str, token: str, payload: dict, *, timeout: int = 30) -> dict:
        calls.append((path, payload))
        if path == "/control/api/preflight":
            return {"ok": True, "checks": []}
        if path == "/control/api/alerts/queue-check":
            return {"should_alert": False}
        raise AssertionError(f"unexpected post {path}")

    with patch.dict("os.environ", {"ENOCH_CONFIG": str(config)}, clear=False), patch.object(pump, "_get_json", return_value={"dispatch_safe": True, "active_items": [], "next_candidate": None}), patch.object(pump, "_post_json", side_effect=fake_post):
        assert pump.main() == 0

    assert "/control/api/v1/followups/launch-next" not in [path for path, _payload in calls]
    assert "/control/dispatch-next" not in [path for path, _payload in calls]
    output = json.loads(capsys.readouterr().out)
    assert output["followup_launch"]["reason"] == "queue pump follow-up launch disabled"
    assert output["dispatch"]["reason"] == "no queued candidate"


def test_install_script_keeps_draft_units_opt_in() -> None:
    install = (ROOT / "scripts" / "install-control-plane.sh").read_text(encoding="utf-8")
    assert "ENOCH_INSTALL_LEGACY_NOTION_UNITS:-0" in install
    assert "Supabase-native /control/intake/ideas is the supported intake path" in install
    assert "ENOCH_INSTALL_PAPER_DRAFT_NEXT_UNITS:-0" in install
    assert "enoch-paper-draft-next.service" in install
    assert "enoch-paper-draft-next.timer" in install


def test_codex_runner_disables_spark_backed_explore_by_default() -> None:
    script = (ROOT / "deploy" / "enoch_codex_runner.sh").read_text(encoding="utf-8")
    assert 'export USE_OMX_EXPLORE_CMD="${USE_OMX_EXPLORE_CMD:-0}"' in script
    assert 'omx exec' not in script
    assert 'codex exec' in script or 'CODEX_BIN' in script
    assert script.index('export USE_OMX_EXPLORE_CMD=') < script.index('"${cmd[@]}"')


def test_codex_dispatch_resolves_runner_relative_to_deploy_script() -> None:
    script = (ROOT / "deploy" / "enoch_codex_dispatch.sh").read_text(encoding="utf-8")
    assert 'SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"' in script
    assert 'RUNNER_SCRIPT="${ENOCH_CODEX_RUNNER_SCRIPT:-$SCRIPT_DIR/enoch_codex_runner.sh}"' in script
    assert '$HOME/projects/enoch-agentic-research-system/deploy/enoch_codex_runner.sh' not in script
