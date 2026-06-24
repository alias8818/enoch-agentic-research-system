from __future__ import annotations

from typing import Any

from .models import DashboardFinding


DEFAULT_LOW_UTILIZATION_MIN_ELAPSED_SEC = 15 * 60
DEFAULT_CPU_BOUND_AVG_PCT = 80.0
DEFAULT_GPU_IDLE_PCT = 5.0

_CPU_SCRIPT_MARKERS = (
    "python ",
    "python3 ",
    ".py",
    "pytest",
    "node ",
    "uv run",
)
_SUPERVISOR_MARKERS = (
    "codex exec",
    "codex.js exec",
    "enoch_codex_runner.sh",
    "/bin/bash -c",
    " tee ",
)


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _list_items(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict) and isinstance(value.get("items"), list):
        return [item for item in value["items"] if isinstance(item, dict)]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def _runs_from_worker_dashboard(body: dict[str, Any]) -> list[dict[str, Any]]:
    runs = body.get("runs")
    if isinstance(runs, list):
        return [run for run in runs if isinstance(run, dict)]
    return []


def _is_gpu_idle(body: dict[str, Any], *, max_gpu_pct: float) -> bool:
    telemetry = body.get("telemetry") if isinstance(body.get("telemetry"), dict) else {}
    gpu_pct = _as_float(telemetry.get("gpu_pct"), 0.0)
    gpu_pids = telemetry.get("gpu_compute_pids")
    return gpu_pct <= max_gpu_pct and not (
        gpu_pids if isinstance(gpu_pids, list) else []
    )


def _looks_like_cpu_script(cmdline: str) -> bool:
    lowered = f" {cmdline.lower()} "
    if any(marker in lowered for marker in _SUPERVISOR_MARKERS):
        return False
    return any(marker in lowered for marker in _CPU_SCRIPT_MARKERS)


def _low_utilization_process(
    processes: list[dict[str, Any]], *, min_elapsed_sec: int, cpu_bound_avg_pct: float
) -> dict[str, Any] | None:
    candidates: list[dict[str, Any]] = []
    for proc in processes:
        elapsed = _as_int(proc.get("elapsed_sec"), 0)
        num_threads = _as_int(proc.get("num_threads"), 0)
        avg_cpu_pct = _as_float(proc.get("avg_cpu_pct"), 0.0)
        cmdline = str(proc.get("cmdline") or "")
        if elapsed < min_elapsed_sec:
            continue
        if num_threads > 1:
            continue
        if avg_cpu_pct < cpu_bound_avg_pct:
            continue
        if not _looks_like_cpu_script(cmdline):
            continue
        candidates.append(proc)
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda item: (
            _as_int(item.get("elapsed_sec"), 0),
            _as_float(item.get("avg_cpu_pct"), 0.0),
        ),
    )


def classify_low_utilization_runs(
    worker_dashboard_body: dict[str, Any],
    *,
    min_elapsed_sec: int = DEFAULT_LOW_UTILIZATION_MIN_ELAPSED_SEC,
    cpu_bound_avg_pct: float = DEFAULT_CPU_BOUND_AVG_PCT,
    max_gpu_pct: float = DEFAULT_GPU_IDLE_PCT,
) -> list[DashboardFinding]:
    """Find live GB10 runs that are using it like a single-core CPU VM.

    This is an operator-safety classifier, not a scientific judgment.  It only
    flags long-running active worker jobs that have no GPU compute evidence and
    whose hot project process is single-thread CPU-bound.  Short smoke probes
    are intentionally allowed.
    """

    if not isinstance(worker_dashboard_body, dict):
        return []
    if not _is_gpu_idle(worker_dashboard_body, max_gpu_pct=max_gpu_pct):
        return []
    findings: list[DashboardFinding] = []
    for run in _runs_from_worker_dashboard(worker_dashboard_body):
        if (
            run.get("is_live") is not True
            and str(run.get("lifecycle_state") or "").lower() != "active"
        ):
            continue
        process = _low_utilization_process(
            _list_items(run.get("active_processes")),
            min_elapsed_sec=min_elapsed_sec,
            cpu_bound_avg_pct=cpu_bound_avg_pct,
        )
        if process is None:
            continue
        findings.append(
            DashboardFinding(
                severity="warn",
                source="worker_resource_policy",
                authority="GB10 worker telemetry and process metadata",
                message="GB10 active run is CPU-only single-thread work beyond the bounded smoke window",
                observed_at=str(worker_dashboard_body.get("timestamp") or ""),
                suggested_action=(
                    "pause dispatch; checkpoint/stop the run, route CPU-only scaling to CPU workers, "
                    "or justify and bound the GB10 exception"
                ),
                data={
                    "project_id": run.get("project_id"),
                    "run_id": run.get("run_id"),
                    "min_elapsed_sec": min_elapsed_sec,
                    "cpu_bound_avg_pct": cpu_bound_avg_pct,
                    "max_gpu_pct": max_gpu_pct,
                    "process": {
                        "pid": process.get("pid"),
                        "elapsed_sec": process.get("elapsed_sec"),
                        "num_threads": process.get("num_threads"),
                        "avg_cpu_pct": process.get("avg_cpu_pct"),
                        "cmdline": str(process.get("cmdline") or "")[:500],
                    },
                },
            )
        )
    return findings


_SEVERITY_ORDER: dict[str, int] = {"info": 0, "warn": 1, "critical": 2}


def resource_utilization_status(findings: list[DashboardFinding]) -> dict[str, Any]:
    """Classify resource findings into an operator-safety status.

    The previous implementation collapsed every non-empty ``findings`` list
    into ``status="blocked"`` regardless of the per-finding ``severity``.
    That made it impossible to distinguish informational ``warn`` findings
    (advisory) from hard ``critical`` findings (halt-worthy) at the API
    surface, and forced operators into the manual-review flow even when the
    only signals were advisory.

    Status semantics after this fix:
      * ``"clean"`` — no findings.
      * ``"warn"`` — at least one finding, none ``critical``.
      * ``"blocked"`` — at least one ``critical`` finding.

    ``ok`` continues to be ``False`` for any non-empty findings list so that
    downstream readiness checks (which use ``ok``) do not silently flip
    semantics. ``ok`` is therefore about "any active signal" while
    ``status`` is about the worst severity seen.
    """
    if not findings:
        status = "clean"
        highest_severity = "info"
        severity_counts: dict[str, int] = {"info": 0, "warn": 0, "critical": 0}
    else:
        severity_counts = {"info": 0, "warn": 0, "critical": 0}
        highest_severity = "info"
        for finding in findings:
            severity = finding.severity
            severity_counts[severity] = severity_counts.get(severity, 0) + 1
            if _SEVERITY_ORDER.get(severity, 0) > _SEVERITY_ORDER.get(
                highest_severity, 0
            ):
                highest_severity = severity
        status = "blocked" if highest_severity == "critical" else "warn"

    return {
        "ok": not findings,
        "status": status,
        "highest_severity": highest_severity,
        "severity_counts": severity_counts,
        "findings": [finding.model_dump(mode="json") for finding in findings],
        "finding_count": len(findings),
    }
