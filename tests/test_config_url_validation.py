from __future__ import annotations

import pytest
from pydantic import ValidationError

from enoch_control_plane.config import GateConfig, WorkerTargetConfig


def _config_kwargs() -> dict[str, str]:
    return {
        "control_api_bearer_token": "control-token",
        "completion_callback_url": "https://automation.example.com/webhook/enoch",
        "completion_callback_token": "callback-token",
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("completion_callback_url", "file:///etc/passwd"),
        ("n8n_callback_url", "file:///etc/passwd"),
        ("worker_wake_gate_url", "file:///etc/passwd"),
        ("pushover_api_url", "file:///etc/passwd"),
        ("hermes_alert_webhook_url", "file:///etc/passwd"),
        ("paper_writer_base_url", "file:///etc/passwd"),
    ],
)
def test_gate_config_rejects_non_http_url_fields(field: str, value: str) -> None:
    kwargs = _config_kwargs()
    kwargs[field] = value

    with pytest.raises(ValidationError, match="must use http or https"):
        GateConfig.model_validate(kwargs)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("completion_callback_url", "http://169.254.169.254/latest/meta-data"),
        ("n8n_callback_url", "http://127.0.0.1:8787/callback"),
        ("pushover_api_url", "http://10.0.0.5/pushover"),
        ("paper_writer_base_url", "http://172.16.0.10/openai/v1"),
    ],
)
def test_external_outbound_config_urls_reject_private_targets(
    field: str, value: str
) -> None:
    kwargs = _config_kwargs()
    kwargs[field] = value
    if field == "n8n_callback_url":
        kwargs["completion_callback_url"] = ""

    with pytest.raises(ValidationError, match="private address"):
        GateConfig.model_validate(kwargs)


def test_worker_gate_and_local_hermes_webhook_allow_private_http_targets() -> None:
    config = GateConfig.model_validate(
        {
            **_config_kwargs(),
            "worker_wake_gate_url": "http://192.168.1.77:8787",
            "hermes_alert_webhook_url": "http://127.0.0.1:8644/webhooks/enoch-alert",
        }
    )
    target = WorkerTargetConfig(wake_gate_url="http://10.0.0.42:8787")

    assert config.worker_wake_gate_url == "http://192.168.1.77:8787"
    assert (
        config.hermes_alert_webhook_url == "http://127.0.0.1:8644/webhooks/enoch-alert"
    )
    assert target.wake_gate_url == "http://10.0.0.42:8787"


def test_worker_target_rejects_non_http_url() -> None:
    with pytest.raises(ValidationError, match="must use http or https"):
        WorkerTargetConfig(wake_gate_url="file:///etc/passwd")
