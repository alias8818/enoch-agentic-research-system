from __future__ import annotations

import json
from pathlib import Path

from scripts import research_provider_budget


SYNTHETIC_QUOTA = {
    "subscription": {
        "limit": 2500,
        "requests": 0,
        "renewsAt": "2026-05-09T19:24:53.192Z",
    },
    "weeklyTokenLimit": {
        "remainingCredits": "$119.77",
        "maxCredits": "$120.00",
        "nextRegenAt": "2026-05-09T15:31:04.000Z",
        "nextRegenCredits": "$2.40",
    },
    "rollingFiveHourLimit": {
        "remaining": 2500,
        "max": 2500,
        "limited": False,
        "nextTickAt": "2026-05-09T14:30:46.000Z",
    },
}


def test_synthetic_budget_accepts_healthy_quota() -> None:
    result = research_provider_budget.synthetic_budget_status(
        SYNTHETIC_QUOTA,
        min_remaining_credits=5.0,
        min_rolling_remaining=10,
        estimated_requests=4,
        reserve_requests=4,
    )

    assert result["ok"] is True
    assert result["remaining_credits"] == 119.77
    assert result["rolling_remaining"] == 2500
    assert result["failures"] == []


def test_synthetic_budget_fails_closed_on_malformed_sections() -> None:
    result = research_provider_budget.synthetic_budget_status(
        {"weeklyTokenLimit": True, "rollingFiveHourLimit": "bad", "subscription": []},
        min_remaining_credits=1.0,
        min_rolling_remaining=1,
        estimated_requests=1,
        reserve_requests=1,
    )

    assert result["ok"] is False
    assert result["failures"]
    assert any("malformed" in item for item in result["failures"])


def test_synthetic_budget_fails_closed_on_malformed_numeric_values() -> None:
    payload = json.loads(json.dumps(SYNTHETIC_QUOTA))
    payload["rollingFiveHourLimit"]["remaining"] = "not-a-number"
    payload["rollingFiveHourLimit"]["max"] = "also-bad"
    payload["subscription"]["limit"] = "bad-limit"
    payload["subscription"]["requests"] = "bad-requests"

    result = research_provider_budget.synthetic_budget_status(
        payload,
        min_remaining_credits=5.0,
        min_rolling_remaining=10,
        estimated_requests=1,
        reserve_requests=1,
    )

    assert result["ok"] is False
    assert any(
        "malformed rollingFiveHourLimit.remaining" in failure
        for failure in result["failures"]
    )
    assert any(
        "malformed subscription.limit" in failure for failure in result["failures"]
    )


def test_synthetic_budget_fails_closed_when_low_or_limited() -> None:
    payload = json.loads(json.dumps(SYNTHETIC_QUOTA))
    payload["weeklyTokenLimit"]["remainingCredits"] = "$1.00"
    payload["rollingFiveHourLimit"]["remaining"] = 3
    payload["rollingFiveHourLimit"]["limited"] = True

    result = research_provider_budget.synthetic_budget_status(
        payload,
        min_remaining_credits=5.0,
        min_rolling_remaining=10,
        estimated_requests=4,
        reserve_requests=4,
    )

    assert result["ok"] is False
    assert any("weekly remaining credits" in failure for failure in result["failures"])
    assert any("rolling five-hour limit" in failure for failure in result["failures"])
    assert any("rolling remaining" in failure for failure in result["failures"])


def test_synthetic_budget_fails_when_subscription_allowance_exhausted() -> None:
    payload = json.loads(json.dumps(SYNTHETIC_QUOTA))
    payload["subscription"]["limit"] = 100
    payload["subscription"]["requests"] = 100

    result = research_provider_budget.synthetic_budget_status(
        payload,
        min_remaining_credits=5.0,
        min_rolling_remaining=10,
        estimated_requests=1,
        reserve_requests=1,
    )

    assert result["ok"] is False
    assert any(
        "subscription request allowance" in failure for failure in result["failures"]
    )


def test_budget_cli_uses_offline_payload(tmp_path: Path) -> None:
    payload = tmp_path / "quota.json"
    output = tmp_path / "budget.json"
    payload.write_text(json.dumps(SYNTHETIC_QUOTA), encoding="utf-8")

    assert (
        research_provider_budget.main(
            ["--input-json", str(payload), "--output", str(output)]
        )
        == 0
    )

    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["ok"] is True
    assert result["provider"] == "synthetic"


def test_budget_cli_missing_key_can_emit_json_without_secret(
    monkeypatch, capsys
) -> None:
    monkeypatch.delenv("SYNTHETIC_API_KEY", raising=False)

    assert research_provider_budget.main(["--allow-missing-key"]) == 0

    output = capsys.readouterr().out
    assert "SYNTHETIC_API_KEY" in output
    assert "syn_" not in output


def test_budget_cli_can_use_exedev_proxy_without_local_api_key(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    output = tmp_path / "budget.json"
    calls: list[tuple[str, str]] = []

    def fake_fetch(url: str, *, api_key: str = "", timeout: int) -> dict:
        calls.append((url, api_key))
        return SYNTHETIC_QUOTA

    monkeypatch.delenv("SYNTHETIC_API_KEY", raising=False)
    monkeypatch.setattr(research_provider_budget, "fetch_json", fake_fetch)

    assert (
        research_provider_budget.main(
            [
                "--base-url",
                "https://synthetic.int.exe.xyz",
                "--no-auth",
                "--output",
                str(output),
            ]
        )
        == 0
    )

    result = json.loads(output.read_text(encoding="utf-8"))
    console = json.loads(capsys.readouterr().out)
    assert calls == [("https://synthetic.int.exe.xyz/v2/quotas", "")]
    assert result["ok"] is True
    assert result["auth_mode"] == "exe_http_proxy"
    assert result["base_url"] == "https://synthetic.int.exe.xyz"
    assert "base_url" not in console
    assert "payload_json" not in console


def test_fetch_json_rejects_non_http_url_before_urlopen(monkeypatch) -> None:
    def fake_urlopen(*_args, **_kwargs):
        raise AssertionError("urlopen should not run for unsafe provider URL")

    monkeypatch.setattr(
        research_provider_budget.urllib.request, "urlopen", fake_urlopen
    )
    try:
        research_provider_budget.fetch_json("file:///etc/passwd", timeout=1)
    except ValueError as exc:
        assert "provider url must use http or https" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected unsafe provider URL rejection")
