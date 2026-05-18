from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from enoch_control_plane.app import load_config


def _write_config(path: Path, token: str) -> Path:
    path.write_text(
        json.dumps(
            {
                "control_api_bearer_token": token,
                "completion_callback_url": "https://automation.example.test/callback",
                "completion_callback_token": f"{token}-callback",
            }
        ),
        encoding="utf-8",
    )
    return path


def test_load_config_honors_legacy_omx_wake_gate_config(tmp_path: Path) -> None:
    legacy_config = _write_config(tmp_path / "legacy.json", "legacy-secret")

    with patch.dict(
        "os.environ",
        {
            "OMX_WAKE_GATE_CONFIG": str(legacy_config),
        },
        clear=True,
    ):
        config = load_config()

    assert config.control_api_bearer_token == "legacy-secret"
    assert config.completion_callback_token == "legacy-secret-callback"


def test_load_config_prefers_enoch_config_over_legacy_omx_config(tmp_path: Path) -> None:
    current_config = _write_config(tmp_path / "current.json", "current-secret")
    legacy_config = _write_config(tmp_path / "legacy.json", "legacy-secret")

    with patch.dict(
        "os.environ",
        {
            "ENOCH_CONFIG": str(current_config),
            "OMX_WAKE_GATE_CONFIG": str(legacy_config),
        },
        clear=True,
    ):
        config = load_config()

    assert config.control_api_bearer_token == "current-secret"
    assert config.completion_callback_token == "current-secret-callback"
