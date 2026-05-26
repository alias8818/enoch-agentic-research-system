from __future__ import annotations

import json

from scripts import check_longhaul_readiness


def test_config_token_does_not_follow_env_control_url(monkeypatch, tmp_path):
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "listen_host": "0.0.0.0",
                "listen_port": 8787,
                "control_api_bearer_token": "config-token",
            }
        ),
        encoding="utf-8",
    )
    observed = {}

    def fake_get_json(url: str, token: str, timeout: int = 30) -> dict:
        observed["url"] = url
        observed["token"] = token
        return {"ok": True}

    monkeypatch.setenv("ENOCH_CONTROL_URL", "https://attacker.invalid")
    monkeypatch.setattr(check_longhaul_readiness, "_get_json", fake_get_json)

    assert check_longhaul_readiness.main(["--live", "--config", str(config)]) == 0
    assert observed == {
        "url": "http://127.0.0.1:8787/control/api/v1/automation-readiness",
        "token": "config-token",
    }


def test_explicit_token_may_use_env_control_url(monkeypatch, tmp_path):
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps({"listen_host": "0.0.0.0", "listen_port": 8787}), encoding="utf-8"
    )
    observed = {}

    def fake_get_json(url: str, token: str, timeout: int = 30) -> dict:
        observed["url"] = url
        observed["token"] = token
        return {"ok": True}

    monkeypatch.setenv("ENOCH_CONTROL_URL", "https://operator.example")
    monkeypatch.setattr(check_longhaul_readiness, "_get_json", fake_get_json)

    assert (
        check_longhaul_readiness.main(
            ["--live", "--config", str(config), "--token", "explicit-token"]
        )
        == 0
    )
    assert observed == {
        "url": "https://operator.example/control/api/v1/automation-readiness",
        "token": "explicit-token",
    }
