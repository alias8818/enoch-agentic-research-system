from __future__ import annotations

from enoch_control_plane.control_plane.workload_routing import route_machine_target, workload_class_from_row


def test_agent_integrity_ledger_routes_to_agent_harness_cpu_worker() -> None:
    row = {
        "title": "Hash-Chain Evidence Ledger for Agent State Integrity Verification",
        "category": "agent-reliability",
        "machine_target": "gb10",
    }

    routing = route_machine_target(
        row,
        default_machine_target="gb10",
        workload_machine_targets={"agent_harness": "cpu-proxmox-1", "gpu_required": "gb10"},
    )

    assert routing == {
        "machine_target": "cpu-proxmox-1",
        "workload_class": "agent_harness",
        "routing_reason": "workload_class:agent_harness",
    }


def test_training_terms_keep_model_training_on_gpu() -> None:
    row = {
        "title": "Geometry-based core-set selection for tiny LM pretraining",
        "category": "home-training",
        "machine_target": "cpu-proxmox-1",
    }

    routing = route_machine_target(
        row,
        default_machine_target="cpu-proxmox-1",
        workload_machine_targets={"training": "gb10", "agent_harness": "cpu-proxmox-1"},
    )

    assert routing["workload_class"] == "training"
    assert routing["machine_target"] == "gb10"


def test_explicit_workload_class_still_wins_over_title_heuristics() -> None:
    row = {
        "title": "CPU-only evidence ledger",
        "category": "agent-reliability",
        "workload_class": "gpu_required",
    }

    assert workload_class_from_row(row) == "gpu_required"



def test_negated_gpu_phrase_routes_to_cpu_only() -> None:
    row = {
        "title": "CPU-only no GPU regex validator",
        "machine_target": "gb10",
    }

    routing = route_machine_target(
        row,
        default_machine_target="gb10",
        workload_machine_targets={"cpu_only": "cpu-proxmox-1", "gpu_required": "gb10"},
    )

    assert routing == {
        "machine_target": "cpu-proxmox-1",
        "workload_class": "cpu_only",
        "routing_reason": "workload_class:cpu_only",
    }


def test_negated_gpu_phrase_does_not_override_cuda_signal() -> None:
    row = {
        "title": "CUDA training; no GPU fallback exists",
        "machine_target": "gb10",
    }

    routing = route_machine_target(
        row,
        default_machine_target="gb10",
        workload_machine_targets={"cpu_only": "cpu-proxmox-1", "gpu_required": "gb10", "training": "gb10"},
    )

    assert routing["workload_class"] == "gpu_required"
    assert routing["machine_target"] == "gb10"


def test_non_gpu_baseline_phrase_does_not_override_cuda_signal() -> None:
    row = {
        "title": "non-GPU baseline plus CUDA benchmark",
        "machine_target": "gb10",
    }

    routing = route_machine_target(
        row,
        default_machine_target="gb10",
        workload_machine_targets={"cpu_only": "cpu-proxmox-1", "gpu_required": "gb10"},
    )

    assert routing["workload_class"] == "gpu_required"
    assert routing["machine_target"] == "gb10"


def test_negated_cuda_phrase_overrides_cuda_substring_signal() -> None:
    row = {
        "title": "no CUDA and no GPU required; CPU-only regex validator",
        "machine_target": "gb10",
    }

    routing = route_machine_target(
        row,
        default_machine_target="gb10",
        workload_machine_targets={"cpu_only": "cpu-proxmox-1", "gpu_required": "gb10", "training": "gb10"},
    )

    assert routing["workload_class"] == "cpu_only"
    assert routing["machine_target"] == "cpu-proxmox-1"


def test_negated_training_phrase_with_no_gpu_routes_to_cpu_only() -> None:
    row = {
        "title": "no GPU training-free baseline; CPU-only sqlite benchmark",
        "machine_target": "gb10",
    }

    routing = route_machine_target(
        row,
        default_machine_target="gb10",
        workload_machine_targets={"cpu_only": "cpu-proxmox-1", "gpu_required": "gb10", "training": "gb10"},
    )

    assert routing["workload_class"] == "cpu_only"
    assert routing["machine_target"] == "cpu-proxmox-1"

def test_non_cuda_gpu_benchmark_stays_gpu_required() -> None:
    row = {"title": "non-CUDA GPU benchmark", "machine_target": "gb10"}
    routing = route_machine_target(
        row,
        default_machine_target="gb10",
        workload_machine_targets={"cpu_only": "cpu-proxmox-1", "gpu_required": "gb10"},
    )
    assert routing["workload_class"] == "gpu_required"
    assert routing["machine_target"] == "gb10"


def test_training_free_without_no_gpu_routes_to_cpu_only() -> None:
    row = {"title": "training-free baseline; CPU-only sqlite benchmark", "machine_target": "gb10"}
    routing = route_machine_target(
        row,
        default_machine_target="gb10",
        workload_machine_targets={"cpu_only": "cpu-proxmox-1", "gpu_required": "gb10", "training": "gb10"},
    )
    assert routing["workload_class"] == "cpu_only"
    assert routing["machine_target"] == "cpu-proxmox-1"



def test_training_free_gpu_inference_stays_gpu_required() -> None:
    row = {"title": "training-free GPU inference benchmark", "machine_target": "gb10"}
    routing = route_machine_target(
        row,
        default_machine_target="gb10",
        workload_machine_targets={"cpu_only": "cpu-proxmox-1", "gpu_required": "gb10", "training": "gb10"},
    )
    assert routing["workload_class"] == "gpu_required"
    assert routing["machine_target"] == "gb10"
