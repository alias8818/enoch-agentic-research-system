from __future__ import annotations

from http.client import RemoteDisconnected
import importlib.util
import json
from pathlib import Path
from unittest.mock import patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "deploy" / "enoch_research_autopilot.py"
spec = importlib.util.spec_from_file_location("enoch_research_autopilot", MODULE_PATH)
assert spec and spec.loader
autopilot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(autopilot)


def test_topic_rotation_respects_explicit_topic(monkeypatch):
    monkeypatch.setenv("ENOCH_RESEARCH_AUTOPILOT_TOPIC", "explicit lane")
    monkeypatch.setenv("ENOCH_RESEARCH_TOPIC_ROTATION", "lane a,lane b")
    assert autopilot._topic() == "explicit lane"


def test_topic_rotation_uses_time_window(monkeypatch):
    monkeypatch.delenv("ENOCH_RESEARCH_AUTOPILOT_TOPIC", raising=False)
    monkeypatch.setenv("ENOCH_RESEARCH_TOPIC_ROTATION", "lane a,lane b,lane c")
    monkeypatch.setenv("ENOCH_RESEARCH_TOPIC_ROTATION_SECONDS", "60")
    monkeypatch.setattr(autopilot.time, "time", lambda: 121.0)
    assert autopilot._topic() == "lane c"


def test_active_worker_lane_is_benign_timer_backpressure():
    assert autopilot._is_benign_skip_result({"ok": False, "reason": "active worker lane already exists"}) is True
    assert autopilot._is_benign_skip_result({"ok": False, "reason": "provider budget unavailable"}) is False


def test_remote_disconnect_is_success_when_control_plane_recovers(tmp_path, capsys, monkeypatch):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"control_api_bearer_token": "token"}), encoding="utf-8")
    monkeypatch.setenv("ENOCH_CONFIG", str(config))
    monkeypatch.setenv("ENOCH_ENABLE_RESEARCH_AUTOPILOT", "1")
    monkeypatch.setattr(autopilot.time, "sleep", lambda _seconds: None)

    with (
        patch.object(autopilot, "_post_json", side_effect=RemoteDisconnected("restart")),
        patch.object(autopilot, "_get_json", return_value={"ok": True, "service": "enoch_worker_gate"}),
    ):
        assert autopilot.main() == 0

    result = json.loads(capsys.readouterr().out)
    assert result["ok"] is True
    assert result["action"] == "transient_disconnect"
