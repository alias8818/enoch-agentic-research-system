from __future__ import annotations

from typing import Any


WORKLOAD_FIELD_NAMES = (
    "workload_class",
    "compute_class",
    "runtime_class",
    "expected_workload_class",
    "property_workload_class",
)

TEXT_FIELD_NAMES = (
    "title",
    "project_name",
    "category",
    "description",
    "implementation",
    "baseline_to_beat",
    "kill_condition",
    "accessibility_delta",
    "experiment_design",
    "required_evidence",
    "expected_runtime_class",
    "estimated_runtime_class",
)

GPU_REQUIRED_TERMS = (
    "cuda",
    "gpu",
    "vram",
)
GPU_STRONG_POSITIVE_TERMS = (
    "cuda",
    "vram",
)

NEGATED_GPU_TERMS = (
    "no gpu",
    "non-gpu",
)

TRAINING_TERMS = (
    "pretraining",
    "pre-train",
    "pretrain",
    "fine-tuning",
    "finetuning",
    "train a model",
    "training",
    "gradient",
)

CONTROL_PLANE_TERMS = (
    "control plane",
    "dashboard",
    "validator",
    "schema check",
    "release gate",
)

AGENT_HARNESS_TERMS = (
    "agent state",
    "agent integrity",
    "agent reliability",
    "evidence ledger",
    "tool-use",
    "tool use",
    "hallucination detection",
    "replay consistency",
)

CPU_ONLY_TERMS = (
    "cpu-only",
    "cpu only",
    "cpu-bound",
    "cpu bound",
    "no gpu",
    "non-gpu",
    "regex",
    "sqlite",
    "property-based",
    "hypothesis",
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


def _field_text(row: dict[str, Any]) -> str:
    parts: list[str] = []
    for name in TEXT_FIELD_NAMES:
        value = row.get(name)
        if isinstance(value, (list, tuple, set)):
            parts.extend(str(item) for item in value)
        elif isinstance(value, dict):
            parts.extend(str(item) for item in value.values())
        elif value not in (None, ""):
            parts.append(str(value))
    return " ".join(parts).strip().lower().replace("_", " ")


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def infer_workload_class_from_text(row: dict[str, Any]) -> str:
    text = _field_text(row)
    if not text:
        return "unknown"
    has_negated_gpu = _contains_any(text, NEGATED_GPU_TERMS)
    has_gpu_required = _contains_any(text, GPU_REQUIRED_TERMS)
    has_strong_gpu_positive = _contains_any(text, GPU_STRONG_POSITIVE_TERMS)
    has_training = _contains_any(text, TRAINING_TERMS)

    if has_strong_gpu_positive:
        return "gpu_required"
    if has_training:
        return "training"
    if has_negated_gpu:
        return "cpu_only"
    if has_gpu_required:
        return "gpu_required"
    if _contains_any(text, CONTROL_PLANE_TERMS):
        return "control_plane"
    if _contains_any(text, AGENT_HARNESS_TERMS):
        return "agent_harness"
    if _contains_any(text, CPU_ONLY_TERMS):
        return "cpu_only"
    return "unknown"


def workload_class_from_row(row: dict[str, Any]) -> str:
    for name in WORKLOAD_FIELD_NAMES:
        if name in row and row.get(name) not in (None, ""):
            return normalize_workload_class(row.get(name))
    needs_cuda = row.get("needs_cuda")
    if needs_cuda is True or str(needs_cuda).strip().lower() in {"1", "true", "yes"}:
        return "gpu_required"
    if needs_cuda is False or str(needs_cuda).strip().lower() in {"0", "false", "no"}:
        return "cpu_only"
    inferred = infer_workload_class_from_text(row)
    if inferred != "unknown":
        return inferred
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
