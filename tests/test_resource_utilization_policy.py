from __future__ import annotations

from types import SimpleNamespace

from enoch_control_plane.control_plane.alerts import queue_alert_findings
from enoch_control_plane.control_plane.longhaul_readiness import (
    evaluate_longhaul_readiness,
)
from enoch_control_plane.control_plane.resource_utilization import (
    classify_low_utilization_runs,
)
from enoch_control_plane.control_plane.router import _project_prompt

from test_longhaul_readiness import NOW, _ready_payload


def _cpu_only_worker_body() -> dict:
    return {
        "timestamp": "2026-05-19T21:00:00Z",
        "telemetry": {"gpu_pct": 0.0, "gpu_compute_pids": []},
        "runs": [
            {
                "run_id": "run-cpu",
                "project_id": "project-cpu",
                "is_live": True,
                "lifecycle_state": "active",
                "active_process_count": 1,
                "active_processes": {
                    "items": [
                        {
                            "pid": 123,
                            "cmdline": "python3 experiments/alias_ledger_eval.py --scale medium",
                            "elapsed_sec": 1800,
                            "num_threads": 1,
                            "avg_cpu_pct": 99.2,
                        }
                    ]
                },
            }
        ],
    }


def test_classifies_long_single_thread_cpu_only_gb10_run() -> None:
    findings = classify_low_utilization_runs(
        _cpu_only_worker_body(), min_elapsed_sec=900
    )

    assert len(findings) == 1
    assert findings[0].source == "worker_resource_policy"
    assert "CPU-only single-thread" in findings[0].message
    assert findings[0].data["project_id"] == "project-cpu"
    assert findings[0].data["process"]["num_threads"] == 1


def test_does_not_classify_short_smoke_cpu_probe() -> None:
    body = _cpu_only_worker_body()
    body["runs"][0]["active_processes"]["items"][0]["elapsed_sec"] = 120

    assert classify_low_utilization_runs(body, min_elapsed_sec=900) == []


def test_queue_alerts_surface_low_utilization_even_when_worker_is_live() -> None:
    finding = classify_low_utilization_runs(
        _cpu_only_worker_body(), min_elapsed_sec=900
    )[0]
    status = SimpleNamespace(
        flags=SimpleNamespace(queue_paused=False, maintenance_mode=False),
        config=SimpleNamespace(live_dispatch_enabled=True),
        conflicts=[],
        active_items=[{"project_id": "project-cpu", "current_run_id": "run-cpu"}],
        warnings=[finding],
        source_freshness={},
        observations={
            "worker_preflight": {
                "payload": {
                    "checks": [
                        {
                            "name": "wake_gate_runs",
                            "data": {
                                "body": {
                                    "runs": [
                                        {
                                            "run_id": "run-cpu",
                                            "is_live": True,
                                            "lifecycle_state": "active",
                                            "active_process_count": 1,
                                        }
                                    ]
                                }
                            },
                        }
                    ]
                }
            }
        },
    )

    findings = queue_alert_findings(status, hang_after_sec=3600)  # type: ignore[arg-type]

    assert any(item.source == "worker_resource_policy" for item in findings)


def test_longhaul_readiness_blocks_on_low_utilization_policy_finding() -> None:
    payload = _ready_payload()
    finding = classify_low_utilization_runs(
        _cpu_only_worker_body(), min_elapsed_sec=900
    )[0]

    result = evaluate_longhaul_readiness(
        now=NOW,
        resource_utilization={"ok": False, "findings": [finding.model_dump()]},
        **payload,
    )

    assert result["ok"] is False
    assert "worker resource policy has active findings" in result["blockers"]
    assert result["summary"]["resource_utilization_status"] == "blocked"
    assert result["summary"]["resource_utilization_findings"] == 1


def test_project_prompt_requires_resource_calibration_and_checkpoints() -> None:
    prompt = _project_prompt({"project_id": "p1", "project_name": "Example"})

    assert "Enoch-controlled autonomous worker run" in prompt
    assert "use the `enoch-worker` Codex skill" in prompt
    assert "Resource-efficiency contract" in prompt
    assert "write a resource calibration note" in prompt
    assert "CPU-only, no-GPU, single-thread" in prompt
    assert "do not spend more than 15 minutes" in prompt
    assert "checkpoint partial metrics" in prompt
