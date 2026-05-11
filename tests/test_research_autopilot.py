from __future__ import annotations

from http.client import RemoteDisconnected
import importlib.util
import json
from pathlib import Path
from unittest.mock import Mock, patch


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


def test_research_quality_refresh_only_runs_read_only_report(tmp_path, capsys, monkeypatch):
    output = tmp_path / "reports" / "latest-report.json"
    calls: list[dict] = []

    def fake_run(cmd, *, cwd, text, stdout, stderr, timeout, check):
        calls.append({"cmd": cmd, "cwd": cwd, "timeout": timeout, "check": check})
        return Mock(returncode=0, stdout='{"ok": true}', stderr="")

    monkeypatch.setenv("ENOCH_RESEARCH_QUALITY_REFRESH_ONLY", "1")
    monkeypatch.setenv("ENOCH_SUPABASE_DATABASE_URL", "postgresql://user:secret@host/db")
    monkeypatch.setenv("ENOCH_RESEARCH_QUALITY_REPORT_PATH", str(output))
    monkeypatch.setenv("ENOCH_RESEARCH_QUALITY_LIMIT", "7")
    monkeypatch.setattr(autopilot.subprocess, "run", fake_run)

    assert autopilot.main() == 0
    result = json.loads(capsys.readouterr().out)
    assert result["ok"] is True
    assert result["action"] == "research_quality_refresh"
    assert result["output"] == str(output)
    assert output.parent.exists()
    assert calls
    cmd = calls[0]["cmd"]
    assert str(MODULE_PATH.parents[1] / "scripts" / "dspy_research_quality.py") in cmd
    assert "--database-url" in cmd
    assert "postgresql://user:secret@host/db" in cmd
    assert "--limit" in cmd
    assert "7" in cmd
    assert calls[0]["timeout"] == 90
    assert "postgresql://user:secret@host/db" not in json.dumps(result["command"])
    assert "<redacted-database-url>" in result["command"]


def test_research_autopilot_includes_quality_refresh_result(tmp_path, capsys, monkeypatch):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"control_api_bearer_token": "token"}), encoding="utf-8")
    monkeypatch.setenv("ENOCH_CONFIG", str(config))
    monkeypatch.setenv("ENOCH_ENABLE_RESEARCH_AUTOPILOT", "1")

    with (
        patch.object(autopilot, "_post_json", return_value={"ok": True, "action": "research_cycle"}),
        patch.object(autopilot, "refresh_research_quality_report", return_value={"ok": True, "action": "research_quality_refresh"}) as refresh,
    ):
        assert autopilot.main() == 0

    refresh.assert_called_once_with()
    result = json.loads(capsys.readouterr().out)
    assert result["ok"] is True
    assert result["research_quality_refresh"] == {"ok": True, "action": "research_quality_refresh"}


def test_research_quality_refresh_missing_database_url_is_fail_soft(monkeypatch):
    monkeypatch.delenv("ENOCH_RESEARCH_QUALITY_DATABASE_URL", raising=False)
    monkeypatch.delenv("ENOCH_SUPABASE_DATABASE_URL", raising=False)
    monkeypatch.delenv("ENOCH_CONTROL_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    result = autopilot.refresh_research_quality_report()
    assert result == {"ok": False, "action": "research_quality_refresh_skipped", "reason": "missing database URL"}
