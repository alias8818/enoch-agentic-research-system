from __future__ import annotations

from http.client import RemoteDisconnected
import importlib.util
import json
from pathlib import Path
from urllib import error
from unittest.mock import Mock, patch


MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "deploy" / "enoch_research_autopilot.py"
)
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
    assert (
        autopilot._is_benign_skip_result(
            {"ok": False, "reason": "active worker lane already exists"}
        )
        is True
    )
    assert (
        autopilot._is_benign_skip_result(
            {"ok": False, "reason": "provider budget unavailable"}
        )
        is False
    )


def test_remote_disconnect_is_success_when_control_plane_recovers(
    tmp_path, capsys, monkeypatch
):
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps({"control_api_bearer_token": "token"}), encoding="utf-8"
    )
    monkeypatch.setenv("ENOCH_CONFIG", str(config))
    monkeypatch.setenv("ENOCH_ENABLE_RESEARCH_AUTOPILOT", "1")
    monkeypatch.setattr(autopilot.time, "sleep", lambda _seconds: None)

    with (
        patch.object(
            autopilot, "_post_json", side_effect=RemoteDisconnected("restart")
        ),
        patch.object(
            autopilot,
            "_get_json",
            return_value={"ok": True, "service": "enoch_worker_gate"},
        ),
    ):
        assert autopilot.main() == 0

    result = json.loads(capsys.readouterr().out)
    assert result["ok"] is True
    assert result["action"] == "transient_disconnect"


def test_connection_refused_is_success_when_control_plane_recovers(
    tmp_path, capsys, monkeypatch
):
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps({"control_api_bearer_token": "token"}), encoding="utf-8"
    )
    monkeypatch.setenv("ENOCH_CONFIG", str(config))
    monkeypatch.setenv("ENOCH_ENABLE_RESEARCH_AUTOPILOT", "1")
    monkeypatch.setattr(autopilot.time, "sleep", lambda _seconds: None)

    refused = error.URLError(ConnectionRefusedError(111, "Connection refused"))
    with (
        patch.object(autopilot, "_post_json", side_effect=refused),
        patch.object(
            autopilot,
            "_get_json",
            return_value={"ok": True, "service": "enoch_worker_gate"},
        ),
    ):
        assert autopilot.main() == 0

    result = json.loads(capsys.readouterr().out)
    assert result["ok"] is True
    assert result["action"] == "transient_disconnect"


def test_http_error_is_not_masked_by_recovery_probe(tmp_path, capsys, monkeypatch):
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps({"control_api_bearer_token": "token"}), encoding="utf-8"
    )
    monkeypatch.setenv("ENOCH_CONFIG", str(config))
    monkeypatch.setenv("ENOCH_ENABLE_RESEARCH_AUTOPILOT", "1")

    http_error = error.HTTPError(
        url="http://127.0.0.1:8787/control/api/research/run-cycle",
        code=500,
        msg="Internal Server Error",
        hdrs={},
        fp=None,
    )
    with (
        patch.object(autopilot, "_post_json", side_effect=http_error),
        patch.object(
            autopilot,
            "_get_json",
            return_value={"ok": True, "service": "enoch_worker_gate"},
        ) as recovery_probe,
    ):
        assert autopilot.main() == 1

    recovery_probe.assert_not_called()
    result = json.loads(capsys.readouterr().err)
    assert result["ok"] is False
    assert result["action"] == "failed"
    assert "HTTPError" in result["reason"]


def test_research_quality_refresh_only_runs_read_only_report(
    tmp_path, capsys, monkeypatch
):
    output = tmp_path / "reports" / "latest-report.json"
    calls: list[dict] = []

    def fake_run(cmd, *, cwd, text, stdout, stderr, timeout, check, env):
        calls.append(
            {"cmd": cmd, "cwd": cwd, "timeout": timeout, "check": check, "env": env}
        )
        return Mock(returncode=0, stdout='{"ok": true}', stderr="")

    monkeypatch.setenv("ENOCH_RESEARCH_QUALITY_REFRESH_ONLY", "1")
    monkeypatch.setenv(
        "ENOCH_SUPABASE_DATABASE_URL", "postgresql://user:secret@host/db"
    )
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
    assert "--database-url" not in cmd
    assert "postgresql://user:secret@host/db" not in cmd
    assert calls[0]["env"]["DATABASE_URL"] == "postgresql://user:secret@host/db"
    assert "ENOCH_SUPABASE_DATABASE_URL" not in calls[0]["env"]
    assert "--limit" in cmd
    assert "7" in cmd
    assert calls[0]["timeout"] == 90
    assert "postgresql://user:secret@host/db" not in json.dumps(result["command"])
    assert "--database-url" not in result["command"]


def test_research_quality_refresh_uses_configured_database_url(tmp_path, monkeypatch):
    config = tmp_path / "config.json"
    output = tmp_path / "latest-report.json"
    secret = "postgresql://user:config-secret@host/db"
    calls: list[dict] = []

    def fake_run(cmd, *, cwd, text, stdout, stderr, timeout, check, env):
        calls.append(
            {"cmd": cmd, "cwd": cwd, "timeout": timeout, "check": check, "env": env}
        )
        return Mock(returncode=0, stdout='{"ok": true}', stderr="")

    config.write_text(json.dumps({"supabase_database_url": secret}), encoding="utf-8")
    monkeypatch.setenv("ENOCH_CONFIG", str(config))
    monkeypatch.delenv("ENOCH_RESEARCH_QUALITY_DATABASE_URL", raising=False)
    monkeypatch.delenv("ENOCH_SUPABASE_DATABASE_URL", raising=False)
    monkeypatch.delenv("ENOCH_CONTROL_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("ENOCH_RESEARCH_QUALITY_REPORT_PATH", str(output))
    monkeypatch.setattr(autopilot.subprocess, "run", fake_run)

    result = autopilot.refresh_research_quality_report()

    assert result["ok"] is True
    assert result["action"] == "research_quality_refresh"
    assert calls[0]["env"]["DATABASE_URL"] == secret
    assert secret not in json.dumps(result["command"])
    assert "--database-url" not in result["command"]


def test_research_quality_refresh_timeout_does_not_report_secret(tmp_path, monkeypatch):
    secret = "postgresql://user:timeout-secret@host/db"

    def fake_run(cmd, *, cwd, text, stdout, stderr, timeout, check, env):
        raise autopilot.subprocess.TimeoutExpired(cmd=cmd + [secret], timeout=timeout)

    monkeypatch.setenv("ENOCH_SUPABASE_DATABASE_URL", secret)
    monkeypatch.setenv(
        "ENOCH_RESEARCH_QUALITY_REPORT_PATH", str(tmp_path / "latest-report.json")
    )
    monkeypatch.setattr(autopilot.subprocess, "run", fake_run)

    result = autopilot.refresh_research_quality_report()

    encoded = json.dumps(result)
    assert result["ok"] is False
    assert result["reason"] == "timeout after 90s"
    assert secret not in encoded
    assert "--database-url" not in result["command"]


def test_research_quality_refresh_records_missing_database_status(
    tmp_path, monkeypatch
):
    status_path = tmp_path / "latest-refresh.json"
    output = tmp_path / "latest-report.json"

    monkeypatch.delenv("ENOCH_RESEARCH_QUALITY_DATABASE_URL", raising=False)
    monkeypatch.delenv("ENOCH_SUPABASE_DATABASE_URL", raising=False)
    monkeypatch.delenv("ENOCH_CONTROL_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("ENOCH_RESEARCH_QUALITY_REFRESH_STATUS_PATH", str(status_path))
    monkeypatch.setenv("ENOCH_RESEARCH_QUALITY_REPORT_PATH", str(output))

    result = autopilot.refresh_research_quality_report()

    assert result["ok"] is False
    assert result["reason"] == "missing database URL"
    payload = json.loads(status_path.read_text(encoding="utf-8"))
    assert payload["ok"] is False
    assert payload["action"] == "research_quality_refresh_skipped"
    assert payload["reason"] == "missing database URL"
    assert payload["output"] == str(output)
    assert payload["recorded_at"]


def test_research_autopilot_includes_quality_refresh_result(
    tmp_path, capsys, monkeypatch
):
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps({"control_api_bearer_token": "token"}), encoding="utf-8"
    )
    monkeypatch.setenv("ENOCH_CONFIG", str(config))
    monkeypatch.setenv("ENOCH_ENABLE_RESEARCH_AUTOPILOT", "1")
    monkeypatch.setenv(
        "ENOCH_RESEARCH_AUTOPILOT_HISTORY_PATH", str(tmp_path / "history.jsonl")
    )

    with (
        patch.object(
            autopilot,
            "_post_json",
            return_value={"ok": True, "action": "research_cycle"},
        ),
        patch.object(
            autopilot,
            "refresh_research_quality_report",
            return_value={"ok": True, "action": "research_quality_refresh"},
        ) as refresh,
        patch.object(
            autopilot,
            "refresh_research_quality_window_comparison",
            return_value={"ok": True, "action": "research_quality_window_comparison"},
        ) as window,
    ):
        assert autopilot.main() == 0

    refresh.assert_called_once_with()
    window.assert_called_once_with()
    result = json.loads(capsys.readouterr().out)
    assert result["ok"] is True
    assert result["research_quality_refresh"] == {
        "ok": True,
        "action": "research_quality_refresh",
    }
    assert result["research_quality_window_comparison"] == {
        "ok": True,
        "action": "research_quality_window_comparison",
    }
    assert result["research_autopilot_history"]["ok"] is True


def test_research_autopilot_retries_stale_rotation_model_without_model() -> None:
    rejected = {
        "ok": False,
        "action": "research_cycle_blocked",
        "reason": (
            "provider model 'hf:moonshotai/Kimi-K2.6' is not in the allowed model "
            "list; research provider settings invalid: model "
            "'hf:moonshotai/Kimi-K2.6' is not in workflow 'research_generation' model_pool"
        ),
    }
    accepted = {
        "ok": True,
        "action": "research_cycle",
        "provider_model": "moonshotai/kimi-k2.6",
    }
    post = Mock(side_effect=[rejected, accepted])
    payload = {"enabled": True, "dry_run": False, "model": "hf:moonshotai/Kimi-K2.6"}

    with patch.object(autopilot, "_post_json", post):
        exit_code, result = autopilot._post_research_run_cycle(
            "http://control.example", "token", payload, 0
        )

    assert exit_code is None
    assert result == {
        **accepted,
        "autopilot_model_retry": {
            "retried_without_model": True,
            "rejected_model": "hf:moonshotai/Kimi-K2.6",
            "rejection_reason": rejected["reason"],
        },
    }
    assert post.call_count == 2
    first_payload = post.call_args_list[0].args[3]
    retry_payload = post.call_args_list[1].args[3]
    assert first_payload["model"] == "hf:moonshotai/Kimi-K2.6"
    assert "model" not in retry_payload


def test_llm_model_health_checks_respect_cooldown_for_unhealthy_models(monkeypatch):
    monkeypatch.setenv("ENOCH_LLM_MODEL_HEALTH_CHECKS_ENABLED", "1")
    monkeypatch.setenv("ENOCH_LLM_MODEL_HEALTH_CHECK_LIMIT", "2")
    monkeypatch.setenv("ENOCH_LLM_MODEL_HEALTH_MIN_INTERVAL_SECONDS", "3600")

    settings_payload = {
        "ok": True,
        "settings": {
            "providers": [
                {"provider_id": "synthetic", "enabled": True},
                {"provider_id": "openrouter", "enabled": True},
            ],
            "models": [
                {
                    "provider_id": "synthetic",
                    "model_id": "hf:zai-org/GLM-5.1",
                    "enabled": True,
                },
                {
                    "provider_id": "openrouter",
                    "model_id": "moonshotai/kimi-k2.6",
                    "enabled": True,
                },
                {
                    "provider_id": "openrouter",
                    "model_id": "openrouter/owl-alpha",
                    "enabled": True,
                },
            ],
        },
        "model_health": {
            "models": [
                {
                    "provider_id": "synthetic",
                    "model_id": "hf:zai-org/GLM-5.1",
                    "status": "healthy",
                    "latest_checked_at": "2026-06-01T20:30:00Z",
                },
                {
                    "provider_id": "openrouter",
                    "model_id": "moonshotai/kimi-k2.6",
                    "status": "unhealthy",
                    "latest_checked_at": "2026-06-01T21:00:00Z",
                    "latest_failure_kind": "rate_limited",
                },
                {
                    "provider_id": "openrouter",
                    "model_id": "openrouter/owl-alpha",
                    "status": "stale",
                    "latest_checked_at": "",
                },
            ]
        },
    }
    posts: list[dict] = []

    def fake_post(
        _base_url: str, _path: str, _token: str, payload: dict, *, timeout: int
    ) -> dict:
        posts.append(payload)
        return {
            "ok": True,
            "provider_id": payload["provider_id"],
            "model_id": payload["model_id"],
            "source": payload["source"],
            "status_code": 200,
        }

    with (
        patch.object(autopilot, "_get_json", return_value=settings_payload),
        patch.object(autopilot, "_post_json", side_effect=fake_post),
        patch.object(autopilot, "time") as fake_time,
    ):
        fake_time.time.return_value = 1_759_339_200.0
        result = autopilot.run_llm_model_health_checks("http://control", "token")
        second_result = autopilot.run_llm_model_health_checks("http://control", "token")

    assert result["ok"] is True
    assert result["checked_count"] == 1
    assert result["skipped_count"] == 2
    assert result["selected_reasons"] == {"openrouter/owl-alpha": "stale_health_check"}
    assert second_result["ok"] is True
    assert second_result["checked_count"] == 1
    assert second_result["skipped_count"] == 2
    assert second_result["selected_reasons"] == {
        "openrouter/owl-alpha": "stale_health_check"
    }
    assert posts == [
        {
            "provider_id": "openrouter",
            "model_id": "openrouter/owl-alpha",
            "source": "autopilot",
        },
        {
            "provider_id": "openrouter",
            "model_id": "openrouter/owl-alpha",
            "source": "autopilot",
        },
    ]


def test_llm_model_health_check_reason_retries_unhealthy_after_cooldown() -> None:
    latest = "2026-06-01T21:00:00Z"
    latest_ts = autopilot._parse_health_checked_at(latest)  # noqa: SLF001

    assert (
        autopilot._llm_model_health_check_reason(  # noqa: SLF001
            {
                "status": "unhealthy",
                "latest_checked_at": latest,
                "latest_failure_kind": "timeout",
            },
            now=latest_ts + 3599,
            min_interval_seconds=3600,
        )
        == ""
    )
    assert (
        autopilot._llm_model_health_check_reason(  # noqa: SLF001
            {
                "status": "unhealthy",
                "latest_checked_at": latest,
                "latest_failure_kind": "timeout",
            },
            now=latest_ts + 3600,
            min_interval_seconds=3600,
        )
        == "unhealthy:timeout"
    )
    assert (
        autopilot._llm_model_health_check_reason(  # noqa: SLF001
            {"status": "stale", "latest_checked_at": latest},
            now=latest_ts,
            min_interval_seconds=3600,
        )
        == "stale_health_check"
    )
    assert (
        autopilot._llm_model_health_check_reason(  # noqa: SLF001
            None,
            now=latest_ts,
            min_interval_seconds=3600,
        )
        == "stale_health_check"
    )


def test_autopilot_history_counts_malformed_provider_responses(tmp_path, monkeypatch):
    history = tmp_path / "history.jsonl"
    monkeypatch.setenv("ENOCH_RESEARCH_AUTOPILOT_HISTORY_PATH", str(history))
    result = {
        "ok": True,
        "budget": {"checked_at": "2026-05-11T11:17:08Z"},
        "provider_model": "hf:moonshotai/Kimi-K2.6",
        "generated_count": 0,
        "promoted_count": 1,
        "dispatched_count": 1,
        "initial_promotable_count": 8,
        "trace_id": "research-cycle-trace-123",
        "run_cycle_id": "run-cycle-123",
        "stages": [
            {
                "stage": "provider_generation",
                "ok": False,
                "reason": "provider generation skipped: provider returned no usable candidate JSON after 2 attempt(s): Unterminated string",
            }
        ],
    }

    append = autopilot.append_research_autopilot_history(result)

    assert append["ok"] is True
    row = json.loads(history.read_text(encoding="utf-8"))
    assert row["checked_at"] == "2026-05-11T11:17:08Z"
    assert row["trace_id"] == "research-cycle-trace-123"
    assert row["run_cycle_id"] == "run-cycle-123"
    assert row["malformed_provider_response_count"] == 1
    assert row["generated_count"] == 0


def test_research_quality_window_comparison_runs_read_only_script(
    tmp_path, monkeypatch
):
    output = tmp_path / "window.json"
    calls: list[dict] = []

    def fake_run(cmd, *, cwd, text, stdout, stderr, timeout, check, env):
        calls.append(
            {"cmd": cmd, "cwd": cwd, "timeout": timeout, "check": check, "env": env}
        )
        return Mock(returncode=0, stdout='{"ok": true}', stderr="")

    monkeypatch.setenv(
        "ENOCH_SUPABASE_DATABASE_URL", "postgresql://user:secret@host/db"
    )
    monkeypatch.setenv("ENOCH_RESEARCH_QUALITY_WINDOW_CUTOFF", "2026-05-11T09:58:00Z")
    monkeypatch.setenv("ENOCH_RESEARCH_QUALITY_WINDOW_REPORT_PATH", str(output))
    monkeypatch.setattr(autopilot.subprocess, "run", fake_run)

    result = autopilot.refresh_research_quality_window_comparison()

    assert result["ok"] is True
    assert result["action"] == "research_quality_window_comparison"
    assert result["output"] == str(output)
    assert calls
    cmd = calls[0]["cmd"]
    assert (
        str(MODULE_PATH.parents[1] / "scripts" / "compare_research_quality_windows.py")
        in cmd
    )
    assert "--cutoff" in cmd
    assert "2026-05-11T09:58:00Z" in cmd
    assert "postgresql://user:secret@host/db" not in json.dumps(result["command"])
    assert "--database-url" not in result["command"]
    assert calls[0]["env"]["DATABASE_URL"] == "postgresql://user:secret@host/db"
    assert "ENOCH_SUPABASE_DATABASE_URL" not in calls[0]["env"]


def test_research_quality_refresh_missing_database_url_is_fail_soft(monkeypatch):
    monkeypatch.delenv("ENOCH_RESEARCH_QUALITY_DATABASE_URL", raising=False)
    monkeypatch.delenv("ENOCH_SUPABASE_DATABASE_URL", raising=False)
    monkeypatch.delenv("ENOCH_CONTROL_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    result = autopilot.refresh_research_quality_report()
    assert result["ok"] is False
    assert result["action"] == "research_quality_refresh_skipped"
    assert result["reason"] == "missing database URL"


def test_janitor_llm_review_disabled_by_default(monkeypatch):
    monkeypatch.delenv("ENOCH_RESEARCH_JANITOR_LLM_REVIEW_ENABLED", raising=False)
    assert autopilot.run_quota_gated_janitor_llm_review() == {
        "ok": True,
        "action": "research_janitor_llm_review_skipped",
        "reason": "disabled",
    }


def test_janitor_llm_review_runs_quota_gated_script(tmp_path, monkeypatch):
    output = tmp_path / "janitor-llm.json"
    config_path = tmp_path / "config.json"
    state_dir = tmp_path / "state"
    secret_dir = state_dir / "llm-provider-secrets"
    secret_dir.mkdir(parents=True)
    (secret_dir / "synthetic.token").write_text("synthetic-secret", encoding="utf-8")
    (state_dir / "llm-provider-settings.json").write_text(
        json.dumps(
            {
                "providers": [
                    {
                        "provider_id": "synthetic",
                        "base_url": "https://api.synthetic.new/openai/v1",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    config_path.write_text(json.dumps({"state_dir": str(state_dir)}), encoding="utf-8")
    calls: list[dict] = []

    def fake_run(cmd, *, cwd, text, stdout, stderr, timeout, check, env):
        calls.append(
            {"cmd": cmd, "cwd": cwd, "timeout": timeout, "check": check, "env": env}
        )
        output.write_text(
            json.dumps(
                {
                    "ok": True,
                    "action": "reviewed",
                    "batch_count": 3,
                    "decision_count": 3,
                    "decision_counts": {"rewrite_contract": 2, "keep_for_later": 1},
                    "budget": {
                        "ok": True,
                        "rolling_remaining": 1000,
                        "weekly_percent_remaining": 90.0,
                    },
                    "apply_result": {"dry_run": True},
                }
            ),
            encoding="utf-8",
        )
        return Mock(returncode=0, stdout="", stderr="")

    monkeypatch.setenv("ENOCH_RESEARCH_JANITOR_LLM_REVIEW_ENABLED", "1")
    monkeypatch.setenv("ENOCH_CONFIG", str(config_path))
    monkeypatch.setenv(
        "ENOCH_SUPABASE_DATABASE_URL", "postgresql://user:secret@host/db"
    )
    monkeypatch.setenv("ENOCH_RESEARCH_JANITOR_LLM_REPORT_PATH", str(output))
    monkeypatch.setenv("ENOCH_RESEARCH_JANITOR_LLM_BATCH_SIZE", "3")
    monkeypatch.setenv("ENOCH_RESEARCH_JANITOR_LLM_MIN_ROLLING", "150")
    monkeypatch.setattr(autopilot.subprocess, "run", fake_run)

    result = autopilot.run_quota_gated_janitor_llm_review()

    assert result["ok"] is True
    assert result["action"] == "reviewed"
    assert result["summary"]["decision_counts"] == {
        "rewrite_contract": 2,
        "keep_for_later": 1,
    }
    assert calls
    cmd = calls[0]["cmd"]
    assert (
        str(MODULE_PATH.parents[1] / "scripts" / "research_facility_llm_review.py")
        in cmd
    )
    assert "--min-rolling-remaining" in cmd
    assert "150" in cmd
    assert "postgresql://user:secret@host/db" not in json.dumps(result["command"])
    assert "--database-url" not in result["command"]
    assert "synthetic-secret" not in json.dumps(result["command"])
    assert "--provider-base-url" in cmd
    assert "https://api.synthetic.new" in cmd
    assert "--openai-base-url" in cmd
    assert "https://api.synthetic.new/openai/v1" in cmd
    assert calls[0]["env"]["DATABASE_URL"] == "postgresql://user:secret@host/db"
    assert calls[0]["env"]["SYNTHETIC_API_KEY"] == "synthetic-secret"
    assert "ENOCH_SUPABASE_DATABASE_URL" not in calls[0]["env"]
