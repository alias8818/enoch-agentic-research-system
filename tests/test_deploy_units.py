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


def test_notion_sync_unit_is_credential_gated_and_non_dispatching() -> None:
    service = (ROOT / "deploy" / "enoch-notion-sync.service").read_text(encoding="utf-8")
    script = (ROOT / "deploy" / "enoch_notion_sync.sh").read_text(encoding="utf-8")
    assert "EnvironmentFile=-/etc/enoch/notion-sync.env" in service
    assert "notion_sync" in script
    assert "NOTION_TOKEN" in script
    assert "/control/dispatch-next" not in service + script
    assert "192.168.1.77" not in service + script


def test_paper_draft_unit_never_dispatches() -> None:
    service = (ROOT / "deploy" / "enoch-paper-draft-next.service").read_text(encoding="utf-8")
    script = (ROOT / "deploy" / "enoch_paper_draft_next.sh").read_text(encoding="utf-8")
    combined = service + script
    assert "/control/papers/draft-next" in combined
    assert "/control/api/paper-reviews/$paper_path/rewrite-draft" in script
    assert "/control/dispatch-next" not in combined
    assert "192.168.1.77" not in combined


def test_queue_pump_drafts_before_dispatch_when_candidate_exists(tmp_path, capsys) -> None:
    pump = _load_queue_pump_module()

    config = tmp_path / "config.json"
    config.write_text(json.dumps({"omx_inbound_bearer_token": "token", "queue_pump_enabled": True}), encoding="utf-8")
    calls: list[tuple[str, dict]] = []

    def fake_post(base_url: str, path: str, token: str, payload: dict, *, timeout: int = 30) -> dict:
        calls.append((path, payload))
        if path == "/control/api/preflight":
            return {"ok": True, "checks": []}
        if path == "/control/api/alerts/queue-check":
            return {"should_alert": False}
        if path == "/control/papers/draft-next":
            return {"action": "drafted", "paper": {"paper_id": "p:r:arxiv_draft"}}
        if path == "/control/api/paper-reviews/p%3Ar%3Aarxiv_draft/rewrite-draft":
            return {"rewritten": 1, "failed": 0}
        raise AssertionError(f"unexpected post {path}")

    with patch.dict("os.environ", {"OMX_WAKE_GATE_CONFIG": str(config)}, clear=False), patch.object(pump, "_get_json", return_value={"dispatch_safe": True, "active_items": [], "next_candidate": {"project_id": "queued"}}), patch.object(pump, "_post_json", side_effect=fake_post):
        assert pump.main() == 0
    assert "/control/papers/draft-next" in [path for path, _payload in calls]
    assert "/control/api/paper-reviews/p%3Ar%3Aarxiv_draft/rewrite-draft" in [path for path, _payload in calls]
    assert "/control/dispatch-next" not in [path for path, _payload in calls]
    assert json.loads(capsys.readouterr().out)["dispatch"]["reason"] == "paper drafted before dispatch"


def test_queue_pump_dispatches_when_no_draft_candidate_exists(tmp_path) -> None:
    pump = _load_queue_pump_module()

    config = tmp_path / "config.json"
    config.write_text(json.dumps({"omx_inbound_bearer_token": "token", "queue_pump_enabled": True}), encoding="utf-8")
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

    with patch.dict("os.environ", {"OMX_WAKE_GATE_CONFIG": str(config)}, clear=False), patch.object(pump, "_get_json", return_value={"dispatch_safe": True, "active_items": [], "next_candidate": {"project_id": "queued"}}), patch.object(pump, "_post_json", side_effect=fake_post):
        assert pump.main() == 0
    assert calls.index("/control/papers/draft-next") < calls.index("/control/dispatch-next")


def test_install_script_installs_sync_and_draft_units() -> None:
    install = (ROOT / "scripts" / "install-control-plane.sh").read_text(encoding="utf-8")
    for name in ["enoch-notion-sync.service", "enoch-notion-sync.timer", "enoch-paper-draft-next.service", "enoch-paper-draft-next.timer"]:
        assert name in install
