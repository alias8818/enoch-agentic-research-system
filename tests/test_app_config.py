from __future__ import annotations

import json
from pathlib import Path

import pytest

import enoch_control_plane.app as appmod


def _minimal_config() -> dict[str, object]:
    return {
        "control_api_bearer_token": "control",
        "completion_callback_url": "http://example.invalid/callback",
        "completion_callback_token": "callback",
    }


def test_load_config_loads_valid_operator_config(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(_minimal_config()), encoding="utf-8")

    config = appmod.load_config(config_path)

    assert config.control_api_bearer_token == "control"


def test_load_config_wraps_malformed_json_with_operator_path(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text("{", encoding="utf-8")

    with pytest.raises(
        RuntimeError, match=f"failed to load config .*{config_path.name}"
    ):
        appmod.load_config(config_path)


def test_load_config_wraps_missing_file_with_operator_path(tmp_path: Path) -> None:
    config_path = tmp_path / "missing-config.json"

    with pytest.raises(
        RuntimeError, match=f"failed to load config .*{config_path.name}"
    ):
        appmod.load_config(config_path)


def test_load_config_wraps_schema_validation_with_operator_path(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config.json"
    data = _minimal_config()
    data["dispatch_timeout_sec"] = 1
    config_path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(
        RuntimeError, match=f"failed to load config .*{config_path.name}"
    ):
        appmod.load_config(config_path)
