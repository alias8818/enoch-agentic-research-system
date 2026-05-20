from __future__ import annotations

from typing import Any


WORKLOAD_FIELD_NAMES = (
    "workload_class",
    "compute_class",
    "runtime_class",
    "expected_workload_class",
    "property_workload_class",
)


def normalize_workload_class(raw: Any, *, default: str = "unknown") -> str:
    value = str(raw or "").strip().lower().replace("-", "_").replace(" ", "_")
    if not value:
        return default
    aliases = {
        "cpu": "cpu_only",
        "cpu_bound": "cpu_only",
        "cpu_only": "cpu_only",
        "no_gpu": "cpu_only",
        "single_thread_cpu": "cpu_only",
        "gpu": "gpu_required",
        "cuda": "gpu_required",
        "gpu_required": "gpu_required",
        "needs_gpu": "gpu_required",
        "training": "training",
        "inference": "inference_eval",
        "inference_eval": "inference_eval",
        "agent_harness": "agent_harness",
        "control_plane": "control_plane",
        "unknown": "unknown",
    }
    return aliases.get(value, default)


def workload_class_from_row(row: dict[str, Any]) -> str:
    for name in WORKLOAD_FIELD_NAMES:
        if name in row and row.get(name) not in (None, ""):
            return normalize_workload_class(row.get(name))
    needs_cuda = row.get("needs_cuda")
    if needs_cuda is True or str(needs_cuda).strip().lower() in {"1", "true", "yes"}:
        return "gpu_required"
    if needs_cuda is False or str(needs_cuda).strip().lower() in {"0", "false", "no"}:
        return "cpu_only"
    return "unknown"


def route_machine_target(
    row: dict[str, Any],
    *,
    default_machine_target: str,
    workload_machine_targets: dict[str, str] | None = None,
) -> dict[str, str]:
    """Return deterministic machine routing for a candidate row.

    Explicit workload class wins over any stale machine_target.  This prevents
    a CPU-only candidate from silently inheriting the GB10 default.
    """

    workload_class = workload_class_from_row(row)
    explicit_target = str(row.get("machine_target") or row.get("default_machine_target") or "").strip()
    fallback_target = explicit_target or default_machine_target
    target_map = {str(k).strip().lower().replace("-", "_"): str(v).strip() for k, v in (workload_machine_targets or {}).items() if str(v).strip()}
    mapped = target_map.get(workload_class)
    if mapped:
        return {
            "machine_target": mapped,
            "workload_class": workload_class,
            "routing_reason": f"workload_class:{workload_class}",
        }
    return {
        "machine_target": fallback_target,
        "workload_class": workload_class,
        "routing_reason": "explicit_or_default_machine_target",
    }
