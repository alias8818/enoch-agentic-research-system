from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from enoch_control_plane.config import GateConfig, GateThresholdProfile


def _gate_config(**overrides: Any) -> GateConfig:
    data: dict[str, Any] = {
        "control_api_bearer_token": "control",
        "completion_callback_url": "http://example.invalid/callback",
        "completion_callback_token": "callback",
    }
    data.update(overrides)
    return GateConfig(**data)


@pytest.mark.parametrize(
    "ssh_host",
    [
        "worker-user@worker.example",
        "worker_user@worker-01.home.aliasocracy.com",
        "worker.example",
    ],
)
def test_gate_config_accepts_safe_paper_evidence_sync_ssh_hosts(
    ssh_host: str,
) -> None:
    config = _gate_config(paper_evidence_sync_ssh_host=ssh_host)

    assert config.paper_evidence_sync_ssh_host == ssh_host


@pytest.mark.parametrize(
    "ssh_host",
    [
        "worker-user@worker.example\n-oProxyCommand=sh",
        "worker-user@worker.example -oProxyCommand=sh",
        "-oProxyCommand=sh",
        "worker@example@other",
        "@worker.example",
        "worker-user@",
        "",
    ],
)
def test_gate_config_rejects_unsafe_paper_evidence_sync_ssh_hosts(
    ssh_host: str,
) -> None:
    with pytest.raises(ValidationError, match="paper_evidence_sync_ssh_host"):
        _gate_config(paper_evidence_sync_ssh_host=ssh_host)


def test_gate_config_normalizes_legacy_callback_and_token_aliases() -> None:
    config = _gate_config(
        completion_callback_url="",
        completion_callback_token="",
        control_api_bearer_token="",
        n8n_callback_url="http://example.invalid/n8n",
        n8n_bearer_token="n8n-token",
        n8n_callback_timeout_sec=42,
        omx_inbound_bearer_token="legacy-control",
    )

    assert config.completion_callback_url == "http://example.invalid/n8n"
    assert config.completion_callback_token == "n8n-token"
    assert config.completion_callback_timeout_sec == 42
    assert config.control_api_bearer_token == "legacy-control"
    assert config.omx_inbound_bearer_token == "legacy-control"


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        (
            "control_plane_store_backend",
            "unknown",
            "control_plane_store_backend must be sqlite",
        ),
        (
            "enoch_core_store_backend",
            "unknown",
            "enoch_core_store_backend must be control_plane",
        ),
        ("completion_callback_url", "", "completion_callback_url is required"),
        ("completion_callback_token", "", "completion_callback_token is required"),
        ("control_api_bearer_token", "", "control_api_bearer_token is required"),
    ],
)
def test_gate_config_rejects_invalid_required_or_backend_values(
    field: str,
    value: str,
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        _gate_config(**{field: value})


def test_gate_config_expands_paths_and_resolves_workload_profiles(
    tmp_path: Path,
) -> None:
    custom_profile = GateThresholdProfile(
        idle_sustain_sec=60,
        cpu_idle_threshold_pct=12.5,
        gpu_idle_avg_threshold_pct=1.0,
        gpu_idle_peak_threshold_pct=2.0,
        vram_delta_threshold_mib=128,
    )
    config = _gate_config(
        state_dir=str(tmp_path / "state"),
        project_root=str(tmp_path / "projects"),
        workload_profiles={"cpu_only": custom_profile},
    )

    workload_class, profile = config.resolve_workload_profile("cpu-only")

    assert config.expanded_state_dir == tmp_path / "state"
    assert config.expanded_project_root == tmp_path / "projects"
    assert workload_class == "cpu_only"
    assert profile == custom_profile
    assert config.normalize_workload_class(None) == "inference_eval"


def test_gate_config_rejects_unknown_workload_classes() -> None:
    config = _gate_config()

    with pytest.raises(ValueError, match="unsupported workload_class"):
        config.normalize_workload_class("nope")

    invalid_profile_config = _gate_config(
        workload_profiles={
            "nope": {
                "idle_sustain_sec": 60,
                "cpu_idle_threshold_pct": 12.5,
                "gpu_idle_avg_threshold_pct": 1.0,
                "gpu_idle_peak_threshold_pct": 2.0,
                "vram_delta_threshold_mib": 128,
            }
        }
    )
    with pytest.raises(ValueError, match="unsupported workload_class profile"):
        invalid_profile_config.workload_profile_map()


def test_gate_config_resolves_worker_targets_and_workload_mappings() -> None:
    config = _gate_config(
        worker_wake_gate_url="http://default.invalid/wake",
        worker_wake_gate_bearer_token="default-token",
        worker_targets={
            "gpu-box": {
                "wake_gate_url": "http://gpu.invalid/wake",
                "role": "gpu",
                "min_memory_available_mib": 2048,
            }
        },
        workload_machine_targets={"gpu_required": "gpu-box"},
    )

    worker = config.resolved_worker_target("gpu-box")
    fallback = config.resolved_worker_target(None)

    assert worker.wake_gate_url == "http://gpu.invalid/wake"
    assert worker.bearer_token == "default-token"
    assert worker.role == "gpu"
    assert worker.min_memory_available_mib == 2048
    assert fallback.wake_gate_url == "http://default.invalid/wake"
    assert fallback.role == "default"
    assert config.workload_class_for_machine_target("gpu-box") == "gpu_required"
    assert (
        config.workload_class_for_machine_target("other", raw="cpu-only") == "cpu_only"
    )
    assert config.workload_class_for_machine_target("other") == "inference_eval"
