from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from enoch_control_plane.config import GateConfig, WorkerTargetConfig


def _base_config(tmp_path: Path) -> dict[str, object]:
    return {
        "state_dir": str(tmp_path / "state"),
        "project_root": str(tmp_path / "projects"),
        "dispatch_script_path": str(tmp_path / "dispatch.sh"),
        "control_api_bearer_token": "token",
        "completion_callback_url": "https://callback.example/callback",
        "completion_callback_token": "callback-token",
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("completion_callback_url", "file:///etc/passwd"),
        ("n8n_callback_url", "gopher://example.invalid/"),
        ("worker_wake_gate_url", "http://user:password@example.invalid"),
        ("pushover_api_url", "file:///tmp/pushover"),
        ("hermes_alert_webhook_url", "http://example.com/\nInjected: yes"),
        ("paper_writer_base_url", "http://10.0.0.2/openai/v1"),
    ],
)
def test_gate_config_rejects_unsafe_outbound_urls(
    tmp_path: Path, field: str, value: str
) -> None:
    payload = {**_base_config(tmp_path), field: value}

    with pytest.raises(ValidationError):
        GateConfig.model_validate(payload)


def test_gate_config_accepts_https_outbound_urls(tmp_path: Path) -> None:
    config = GateConfig.model_validate(
        {
            **_base_config(tmp_path),
            "worker_wake_gate_url": "https://worker.example:8787",
            "hermes_alert_webhook_url": "https://alerts.example/webhooks/enoch",
            "paper_writer_base_url": "https://api.synthetic.new/openai/v1",
        }
    )

    assert config.worker_wake_gate_url == "https://worker.example:8787"
    assert config.hermes_alert_webhook_url == "https://alerts.example/webhooks/enoch"


def test_gate_config_allows_private_control_plane_service_urls(tmp_path: Path) -> None:
    config = GateConfig.model_validate(
        {
            **_base_config(tmp_path),
            "completion_callback_url": "http://127.0.0.1:8787/callback",
            "worker_wake_gate_url": "http://127.0.0.1:8788",
            "hermes_alert_webhook_url": "http://localhost:8644/webhooks/enoch-alert",
        }
    )

    assert config.completion_callback_url == "http://127.0.0.1:8787/callback"


def test_worker_target_rejects_unsafe_wake_gate_url() -> None:
    with pytest.raises(ValidationError):
        WorkerTargetConfig(wake_gate_url="file:///tmp/socket")
