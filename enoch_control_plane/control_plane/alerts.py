from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
from typing import Any
from urllib import parse, request

from ..config import GateConfig
from ..enoch_core.store import IdempotencyConflict
from ..models import utc_now
from ..research_quality.status import (
    DEFAULT_AUTOPILOT_HISTORY_PATH,
    DEFAULT_REPORT_PATHS,
    DEFAULT_WINDOW_REPORT_PATH,
    load_latest_quality_status,
)
from ..timeutils import parse_utc_datetime
from ..url_safety import validate_http_url
from .models import DashboardFinding, DashboardStatusResponse
from .read_models import (
    research_output_readiness_contract,
    research_signal_quality_snapshot,
)
from .research_quality_freshness import research_quality_report_freshness
from .store import ControlPlaneStore


DISPATCH_RACE_GRACE_SEC = 180
DISPATCH_TRANSITION_EVENTS = {
    "controller.dispatch_claimed",
    "controller.live_dispatch",
    "followup.launch",
}
CONTROL_PLANE_DB_WORKER_PREFLIGHT_SOURCE = "control_plane_db+worker_preflight"


@dataclass(frozen=True)
class PushoverResult:
    attempted: bool
    ok: bool
    status_code: int | None = None
    detail: str = ""


@dataclass(frozen=True)
class WebhookResult:
    attempted: bool
    ok: bool
    status_code: int | None = None
    detail: str = ""


def _parse_ts(raw: str | None) -> datetime | None:
    return parse_utc_datetime(raw)


def _observed_at_text(raw: Any) -> str | None:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw.isoformat()
    return str(raw)


def _event_payload_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]


def _fingerprint(findings: list[DashboardFinding]) -> str:
    parts = [f"{item.severity}|{item.source}|{item.message}" for item in findings]
    return hashlib.sha256("\n".join(sorted(parts)).encode("utf-8")).hexdigest()[:16]


def _coerce_observation_value(value: Any) -> Any:
    if isinstance(value, (dict, list)) or not hasattr(value, "model_dump"):
        return value
    try:
        return value.model_dump(mode="json")
    except TypeError:
        return value.model_dump()


def _append_worker_runs_from_dict(
    value: dict[str, Any], runs: list[dict[str, Any]]
) -> None:
    maybe_runs = value.get("runs")
    if isinstance(maybe_runs, list):
        runs.extend(item for item in maybe_runs if isinstance(item, dict))


def _accumulate_worker_runs_from_observation(
    value: Any, runs: list[dict[str, Any]]
) -> None:
    value = _coerce_observation_value(value)
    if isinstance(value, dict):
        _append_worker_runs_from_dict(value, runs)
        for nested_key in ("body", "payload", "data"):
            nested = value.get(nested_key)
            if nested is not value:
                _accumulate_worker_runs_from_observation(nested, runs)
        checks = value.get("checks")
        if isinstance(checks, list):
            for check in checks:
                _accumulate_worker_runs_from_observation(check, runs)
        return
    if isinstance(value, list):
        for item in value:
            _accumulate_worker_runs_from_observation(item, runs)


def _observed_worker_runs(status: DashboardStatusResponse) -> list[dict[str, Any]]:
    observations = getattr(status, "observations", {}) or {}
    runs: list[dict[str, Any]] = []
    if not isinstance(observations, dict):
        return runs
    for source in ("worker_preflight", "worker_dashboard_api"):
        _accumulate_worker_runs_from_observation(observations.get(source), runs)
    return runs


def _has_live_worker_run(status: DashboardStatusResponse, run_id: str | None) -> bool:
    if not run_id:
        return False
    for run in _observed_worker_runs(status):
        if str(run.get("run_id") or "") != str(run_id):
            continue
        if run.get("is_live") is True:
            return True
        if str(run.get("lifecycle_state") or "").lower() == "active":
            return True
        try:
            if int(run.get("active_process_count") or 0) > 0:
                return True
        except (TypeError, ValueError):
            pass
    return False


def _lane_has_dispatchable_queued_work(lane: dict[str, Any]) -> bool:
    return (
        bool(lane.get("dispatch_available")) and int(lane.get("queued_count") or 0) > 0
    )


def _worker_lane_dicts(status: DashboardStatusResponse) -> list[dict[str, Any]]:
    worker_lanes = getattr(status, "worker_lanes", []) or []
    if not isinstance(worker_lanes, list):
        return []
    return [lane for lane in worker_lanes if isinstance(lane, dict)]


def _has_idle_lane_dispatch_opportunity(status: DashboardStatusResponse) -> bool:
    if getattr(status, "next_candidate", None):
        return True
    return any(
        _lane_has_dispatchable_queued_work(lane) for lane in _worker_lane_dicts(status)
    )


def _skip_active_lane_alert_for_live_run(
    status: DashboardStatusResponse, row: dict[str, Any]
) -> bool:
    return _has_live_worker_run(status, str(row.get("current_run_id") or ""))


def _stale_active_lane_finding(
    row: dict[str, Any], status: DashboardStatusResponse
) -> DashboardFinding | None:
    stale_at = _parse_ts(row.get("stale_after"))
    if stale_at is None or datetime.now(timezone.utc) <= stale_at:
        return None
    if _skip_active_lane_alert_for_live_run(status, row):
        return None
    return DashboardFinding(
        severity="warn",
        source="control_plane_db",
        authority="queue_items.stale_after",
        message="active queue item exceeded its stale_after timestamp",
        observed_at=_observed_at_text(row.get("stale_after")),
        suggested_action="inspect run detail and reconcile the queue item",
        data={
            "project_id": row.get("project_id"),
            "run_id": row.get("current_run_id"),
        },
    )


def _hang_active_lane_finding(
    row: dict[str, Any],
    status: DashboardStatusResponse,
    *,
    hang_after_sec: int,
) -> DashboardFinding | None:
    if _parse_ts(row.get("stale_after")) is not None:
        return None
    updated = _parse_ts(row.get("updated_at") or row.get("last_dispatch_at"))
    if updated is None:
        return None
    if datetime.now(timezone.utc) <= updated + timedelta(seconds=hang_after_sec):
        return None
    if _skip_active_lane_alert_for_live_run(status, row):
        return None
    return DashboardFinding(
        severity="warn",
        source="control_plane_db",
        authority="queue_items.updated_at",
        message=f"active queue item has not updated for more than {hang_after_sec} seconds",
        observed_at=_observed_at_text(
            row.get("updated_at") or row.get("last_dispatch_at")
        ),
        suggested_action="inspect GB10 wake gate and active run detail",
        data={
            "project_id": row.get("project_id"),
            "run_id": row.get("current_run_id"),
        },
    )


def _collect_active_lane_findings(
    status: DashboardStatusResponse, *, hang_after_sec: int
) -> list[DashboardFinding]:
    """Warn findings for active queue items past stale_after or the hang window."""
    findings: list[DashboardFinding] = []
    for row in status.active_items:
        finding = _stale_active_lane_finding(row, status)
        if finding is None:
            finding = _hang_active_lane_finding(
                row, status, hang_after_sec=hang_after_sec
            )
        if finding is not None:
            findings.append(finding)
    return findings


_WORKER_WARNING_SOURCES = frozenset(
    {
        "worker_preflight",
        "worker_dashboard_api",
        "worker_settling",
        CONTROL_PLANE_DB_WORKER_PREFLIGHT_SOURCE,
    }
)
_WORKER_STALE_FRESHNESS_SOURCES = frozenset(
    {"worker_preflight", "worker_dashboard_api"}
)


def _should_suppress_worker_warning(
    *,
    active_lane_present: bool,
    active_lane_unhealthy: bool,
    idle_lane_dispatch_opportunity: bool,
) -> bool:
    return (
        active_lane_present
        and not active_lane_unhealthy
        and not idle_lane_dispatch_opportunity
    )


def _append_queue_warning_findings(
    status: DashboardStatusResponse,
    findings: list[DashboardFinding],
    *,
    suppress_worker_warning: bool,
) -> None:
    for item in status.warnings:
        if item.source == "worker_resource_policy":
            findings.append(item)
            continue
        if item.source not in _WORKER_WARNING_SOURCES:
            continue
        if suppress_worker_warning and item.source in _WORKER_STALE_FRESHNESS_SOURCES:
            continue
        findings.append(item)


def _append_stale_worker_source_freshness_findings(
    status: DashboardStatusResponse,
    findings: list[DashboardFinding],
    *,
    suppress_worker_warning: bool,
) -> None:
    for source, freshness in status.source_freshness.items():
        if source not in _WORKER_STALE_FRESHNESS_SOURCES or not freshness.stale:
            continue
        if suppress_worker_warning:
            continue
        findings.append(
            DashboardFinding(
                severity="warn",
                source=source,
                authority=freshness.authority,
                message=f"{source} is stale or missing while live dispatch is enabled",
                observed_at=_observed_at_text(freshness.observed_at),
                suggested_action="refresh /control/api/preflight and verify GB10 worker health",
            )
        )


def _collect_live_dispatch_alert_findings(
    status: DashboardStatusResponse, *, hang_after_sec: int
) -> list[DashboardFinding]:
    findings: list[DashboardFinding] = []
    active_lane_findings = _collect_active_lane_findings(
        status, hang_after_sec=hang_after_sec
    )
    suppress_worker_warning = _should_suppress_worker_warning(
        active_lane_present=bool(status.active_items),
        active_lane_unhealthy=bool(active_lane_findings),
        idle_lane_dispatch_opportunity=_has_idle_lane_dispatch_opportunity(status),
    )
    _append_queue_warning_findings(
        status, findings, suppress_worker_warning=suppress_worker_warning
    )
    _append_stale_worker_source_freshness_findings(
        status, findings, suppress_worker_warning=suppress_worker_warning
    )
    findings.extend(active_lane_findings)
    return findings


def _dedupe_alert_findings(findings: list[DashboardFinding]) -> list[DashboardFinding]:
    deduped: dict[str, DashboardFinding] = {}
    for item in findings:
        key = f"{item.severity}|{item.source}|{item.message}"
        deduped.setdefault(key, item)
    return list(deduped.values())


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _safe_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _research_quality_report_paths(status: DashboardStatusResponse) -> tuple[str, ...]:
    configured = os.environ.get("ENOCH_RESEARCH_QUALITY_REPORT_PATH", "").strip()
    if configured:
        return (configured, *DEFAULT_REPORT_PATHS)
    state_dir = str(getattr(status.config, "state_dir", "") or "").strip()
    if state_dir:
        return (str(Path(state_dir) / "research-quality" / "latest-report.json"),)
    return DEFAULT_REPORT_PATHS


def _latest_research_quality_status(
    status: DashboardStatusResponse,
) -> dict[str, Any]:
    paths = _research_quality_report_paths(status)
    try:
        return load_latest_quality_status(
            paths,
            window_report_path=os.environ.get(
                "ENOCH_RESEARCH_QUALITY_WINDOW_REPORT_PATH",
                DEFAULT_WINDOW_REPORT_PATH,
            ),
            autopilot_history_path=os.environ.get(
                "ENOCH_RESEARCH_AUTOPILOT_HISTORY_PATH",
                DEFAULT_AUTOPILOT_HISTORY_PATH,
            ),
        )
    except Exception as exc:
        return {
            "ok": False,
            "status": "blocked",
            "label": "Research quality: BLOCKED",
            "report_path": str(paths[0]) if paths else "",
            "report_mtime": "",
            "problem_counts": {"research_quality_status_load_failed": 1},
            "severity_counts": {"blocked": 1},
            "problem_details": [
                {
                    "section": "report",
                    "severity": "blocked",
                    "problem": "research_quality_status_load_failed",
                    "reason": str(exc),
                }
            ],
            "post_prompt_monitor": {},
        }


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _research_quality_signal_counts(quality: dict[str, Any]) -> dict[str, Any]:
    problem_counts = _safe_dict(quality.get("problem_counts"))
    severity_counts = _safe_dict(quality.get("severity_counts"))
    monitor = _safe_dict(quality.get("post_prompt_monitor"))
    return {
        "warning_problem_count": _safe_int(severity_counts.get("warning")),
        "blocked_problem_count": _safe_int(severity_counts.get("blocked")),
        "weak_evidence_count": _safe_int(
            problem_counts.get("weak_or_missing_evidence_strength")
        ),
        "malformed_provider_response_count": _safe_int(
            monitor.get("malformed_provider_response_count")
        ),
        "useful_adjacent_followup_delta": _safe_float(
            monitor.get("useful_adjacent_followup_delta")
        ),
    }


def _research_quality_degraded(status: str, counts: dict[str, Any]) -> bool:
    return (
        status in {"blocked", "warnings"}
        or counts["blocked_problem_count"] > 0
        or counts["warning_problem_count"] > 0
        or counts["malformed_provider_response_count"] > 0
        or counts["useful_adjacent_followup_delta"] < 0
    )


def _research_quality_ready_with_recovered_context(
    status: str,
    counts: dict[str, Any],
    signal: dict[str, Any],
    readiness: dict[str, Any],
) -> bool:
    if status != "clean":
        return False
    if counts["blocked_problem_count"] > 0 or counts["warning_problem_count"] > 0:
        return False
    if counts["useful_adjacent_followup_delta"] < 0:
        return False
    if signal.get("signal_verdict") != "defensible":
        return False
    if readiness.get("state") != "ready" or readiness.get("failed_invariants"):
        return False
    for reason in signal.get("signal_reasons") or []:
        if isinstance(reason, dict) and bool(reason.get("active", True)):
            return False
    return counts["malformed_provider_response_count"] > 0


def _research_quality_provider_recovery_grace_is_nonpaging(
    status: str,
    counts: dict[str, Any],
    signal: dict[str, Any],
    readiness: dict[str, Any],
) -> bool:
    if status != "clean":
        return False
    if counts["blocked_problem_count"] > 0 or counts["warning_problem_count"] > 0:
        return False
    if counts["useful_adjacent_followup_delta"] < 0:
        return False
    if readiness.get("failed_invariants"):
        return False
    active_reason_codes = {
        str(reason.get("code") or "")
        for reason in signal.get("signal_reasons") or []
        if isinstance(reason, dict) and bool(reason.get("active", True))
    }
    if active_reason_codes - {"malformed_provider_responses"}:
        return False
    health = _safe_dict(signal.get("provider_generation_health"))
    if health.get("malformed_history_status") != "active":
        return False
    if not bool(health.get("active_malformed_warning")):
        return False
    latest_tick = _safe_dict(health.get("latest_tick"))
    if str(latest_tick.get("status") or "").strip().lower() != "clean":
        return False
    if _safe_int(latest_tick.get("malformed_provider_response_count")) > 0:
        return False
    latest_yield_count = sum(
        _safe_int(latest_tick.get(key))
        for key in ("generated_count", "promoted_count", "dispatched_count")
    )
    return latest_yield_count > 0


def _provider_latest_tick_is_clean_and_yielding(signal: dict[str, Any]) -> bool:
    health = _safe_dict(signal.get("provider_generation_health"))
    latest_tick = _safe_dict(health.get("latest_tick"))
    if str(latest_tick.get("status") or "").strip().lower() != "clean":
        return False
    if _safe_int(latest_tick.get("malformed_provider_response_count")) > 0:
        return False
    latest_yield_count = sum(
        _safe_int(latest_tick.get(key))
        for key in ("generated_count", "promoted_count", "dispatched_count")
    )
    return latest_yield_count > 0


def _research_quality_no_paper_ready_is_nonpaging(
    status: str,
    counts: dict[str, Any],
    signal: dict[str, Any],
    readiness: dict[str, Any],
) -> bool:
    if status != "clean":
        return False
    if counts["blocked_problem_count"] > 0 or counts["warning_problem_count"] > 0:
        return False
    if counts["useful_adjacent_followup_delta"] < 0:
        return False
    failed_codes = {
        str(item.get("code") or "")
        for item in readiness.get("failed_invariants") or []
        if isinstance(item, dict)
    }
    if failed_codes != {"no_paper_ready_outputs"}:
        return False
    active_reason_codes = {
        str(reason.get("code") or "")
        for reason in signal.get("signal_reasons") or []
        if isinstance(reason, dict) and bool(reason.get("active", True))
    }
    if active_reason_codes - {"malformed_provider_responses"}:
        return False
    if counts["malformed_provider_response_count"] <= 0:
        return True
    return _provider_latest_tick_is_clean_and_yielding(signal)


def _research_quality_alert_heading(
    quality: dict[str, Any],
    status: str,
    counts: dict[str, Any],
    signal: dict[str, Any],
    readiness: dict[str, Any],
) -> tuple[str, str]:
    if (
        status == "blocked"
        or counts["blocked_problem_count"] > 0
        or not quality.get("ok")
    ):
        return "critical", "research quality is blocked"
    if signal.get("signal_verdict") == "review_required":
        failed = readiness.get("failed_invariants") or []
        summary = _research_output_readiness_alert_summary(failed)
        if summary:
            return "warn", f"research signal requires review: {summary}"
        return "warn", "research signal requires review"
    return "warn", "research quality warnings present"


def _research_output_readiness_alert_summary(failed: list[Any]) -> str:
    by_code = {
        str(item.get("code") or ""): item for item in failed if isinstance(item, dict)
    }
    parts: list[str] = []
    followup = by_code.get("useful_followup_decline")
    if followup:
        parts.append(
            "Useful follow-up signal declined from "
            f"{_safe_int(followup.get('previous'))} to "
            f"{_safe_int(followup.get('current'))}"
        )
    if "no_paper_ready_outputs" in by_code:
        parts.append("no bounded paper-ready outputs are available")
    return "; ".join(parts)


def _research_quality_problem_details(quality: dict[str, Any]) -> list[dict[str, Any]]:
    details: list[dict[str, Any]] = []
    for detail in quality.get("problem_details") or []:
        if not isinstance(detail, dict):
            continue
        severity = str(detail.get("severity") or "").strip()
        if severity not in {"blocked", "warning"}:
            continue
        problem = str(detail.get("problem") or "").strip()
        if not problem:
            continue
        details.append(
            {
                "severity": severity,
                "problem": problem,
                "project_id": str(detail.get("project_id") or "").strip(),
                "run_id": str(detail.get("run_id") or "").strip(),
                "title": str(detail.get("title") or "").strip(),
            }
        )
        if len(details) >= 3:
            break
    return details


def _research_quality_alert_suggested_action(
    operator_recommendations: list[Any],
    readiness: dict[str, Any] | None = None,
) -> str:
    if readiness and readiness.get("operator_action"):
        return str(readiness.get("operator_action"))
    if operator_recommendations:
        return str(operator_recommendations[0])
    return "inspect the latest research-quality report before resuming unattended automation"


def _research_quality_alert_data(
    quality: dict[str, Any],
    *,
    status: str,
    report_path: str,
    counts: dict[str, Any],
    signal: dict[str, Any],
    operator_recommendations: list[Any],
    readiness: dict[str, Any],
) -> dict[str, Any]:
    return {
        "status": status,
        "label": quality.get("label") or "",
        "report_path": report_path,
        **research_quality_report_freshness(quality.get("report_mtime")),
        **counts,
        "top_problem_details": _research_quality_problem_details(quality),
        "signal_verdict": signal.get("signal_verdict"),
        "signal_label": signal.get("signal_label"),
        "signal_operator_action": signal.get("signal_operator_action"),
        "operator_summary": signal.get("operator_summary"),
        "research_output_readiness": readiness,
        "signal_reasons": signal.get("signal_reasons") or [],
        "operator_recommendations": operator_recommendations,
        "candidate_status_counts": signal.get("candidate_status_counts") or {},
        "decision_outcome_counts": signal.get("decision_outcome_counts") or [],
        "top_candidate_categories": signal.get("top_candidate_categories") or [],
        "candidate_status_samples": signal.get("candidate_status_samples") or {},
        "decision_outcome_samples": signal.get("decision_outcome_samples") or [],
        "quality_floor": signal.get("quality_floor") or {},
        "decision_posture": signal.get("decision_posture") or {},
        "followup_readiness": signal.get("followup_readiness") or {},
        "window_comparison": signal.get("window_comparison") or {},
        "provider_generation_health": signal.get("provider_generation_health") or {},
        "post_prompt_warning_details": signal.get("post_prompt_warning_details") or [],
        "recent_malformed_provider_responses": signal.get(
            "recent_malformed_provider_responses"
        )
        or [],
        "useful_adjacent_followup_evidence": signal.get(
            "useful_adjacent_followup_evidence"
        )
        or {"current": [], "previous": [], "delta": 0.0},
    }


def _research_quality_alert_finding(
    status: DashboardStatusResponse,
) -> DashboardFinding | None:
    quality = _latest_research_quality_status(status)
    report_path = str(quality.get("report_path") or "")
    if not report_path:
        return None
    quality_status = str(quality.get("status") or "unknown").strip().lower()
    counts = _research_quality_signal_counts(quality)
    if not _research_quality_degraded(quality_status, counts):
        return None
    signal = research_signal_quality_snapshot(quality)
    readiness = research_output_readiness_contract(
        signal,
        flags={
            "queue_paused": bool(status.flags.queue_paused),
            "maintenance_mode": bool(status.flags.maintenance_mode),
        },
    )
    signal["research_output_readiness"] = readiness
    if (
        _research_quality_ready_with_recovered_context(
            quality_status, counts, signal, readiness
        )
        or _research_quality_provider_recovery_grace_is_nonpaging(
            quality_status, counts, signal, readiness
        )
        or _research_quality_no_paper_ready_is_nonpaging(
            quality_status, counts, signal, readiness
        )
    ):
        return None
    severity, message = _research_quality_alert_heading(
        quality, quality_status, counts, signal, readiness
    )
    operator_recommendations = signal.get("operator_recommendations") or []
    return DashboardFinding(
        severity=severity,
        source="research_quality",
        authority="latest read-only DSPy/research-quality report",
        message=message,
        observed_at=str(quality.get("report_mtime") or ""),
        suggested_action=_research_quality_alert_suggested_action(
            operator_recommendations, readiness
        ),
        data=_research_quality_alert_data(
            quality,
            status=quality_status,
            report_path=report_path,
            counts=counts,
            signal=signal,
            operator_recommendations=operator_recommendations,
            readiness=readiness,
        ),
    )


def queue_alert_findings(
    status: DashboardStatusResponse, *, hang_after_sec: int
) -> list[DashboardFinding]:
    findings: list[DashboardFinding] = list(status.conflicts)
    flags = status.flags
    intentional_hold = flags.queue_paused or flags.maintenance_mode
    research_quality_finding = _research_quality_alert_finding(status)
    if (
        research_quality_finding is not None
        and research_quality_finding.severity == "critical"
    ):
        findings.append(research_quality_finding)
    if intentional_hold:
        return _dedupe_alert_findings(findings)

    if status.config.live_dispatch_enabled:
        findings.extend(
            _collect_live_dispatch_alert_findings(status, hang_after_sec=hang_after_sec)
        )
        findings = [item for item in findings if item.source != "worker_settling"]

    return _dedupe_alert_findings(findings)


def _is_recent_dispatch_transition_row(row: dict[str, Any], cutoff: datetime) -> bool:
    event_type = str(row.get("event_type") or "")
    if event_type not in DISPATCH_TRANSITION_EVENTS:
        return False
    created_at = _parse_ts(str(row.get("created_at") or ""))
    if created_at is None:
        return False
    return created_at >= cutoff


def _project_ids_from_dispatch_transition_row(row: dict[str, Any]) -> set[str]:
    projects: set[str] = set()
    entity_type = str(row.get("entity_type") or "")
    entity_id = str(row.get("entity_id") or "")
    if entity_type == "project" and entity_id:
        projects.add(entity_id)
    payload = row.get("payload")
    if isinstance(payload, dict):
        project_id = str(payload.get("project_id") or "")
        if project_id:
            projects.add(project_id)
    return projects


def _recent_dispatch_transition_projects(
    store: ControlPlaneStore, *, grace_sec: int = DISPATCH_RACE_GRACE_SEC
) -> set[str]:
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=grace_sec)
    projects: set[str] = set()
    try:
        rows = store.event_rows(limit=100)
    except Exception:
        return projects
    for row in rows:
        if not _is_recent_dispatch_transition_row(row, cutoff):
            continue
        projects.update(_project_ids_from_dispatch_transition_row(row))
    return projects


def _is_active_row_worker_preflight_race(finding: DashboardFinding) -> bool:
    if finding.source != CONTROL_PLANE_DB_WORKER_PREFLIGHT_SOURCE:
        return False
    return "active row" in finding.message.lower() and (
        "no live worker run" in finding.message.lower()
        or "without a matching worker run" in finding.message.lower()
        or "unconfirmed during worker reconcile grace" in finding.message.lower()
    )


def _is_worker_live_without_vm_active_row(finding: DashboardFinding) -> bool:
    if finding.source != CONTROL_PLANE_DB_WORKER_PREFLIGHT_SOURCE:
        return False
    message = finding.message.lower()
    return "live" in message and "control plane has no active row" in message


def _is_cached_worker_preflight_warning(finding: DashboardFinding) -> bool:
    return finding.source == "worker_preflight" and finding.message.lower().startswith(
        "worker_preflight status is "
    )


def _worker_settling_backpressure_matches_finding(
    status: DashboardStatusResponse, finding: DashboardFinding
) -> bool:
    message = finding.message.lower()
    blockers = [
        str(blocker).lower()
        for blocker in status.dispatch_blockers
        if "worker settling" in str(blocker).lower()
    ]
    if not blockers:
        return False
    if "gb10" in message or "gpu" in message:
        return any("gb10" in blocker or "gpu_worker" in blocker for blocker in blockers)
    if "cpu_worker" in message or "cpu" in message:
        return any("cpu_worker" in blocker or "cpu" in blocker for blocker in blockers)
    return True


def _active_project_ids(status: DashboardStatusResponse) -> set[str]:
    return {str(row.get("project_id") or "") for row in status.active_items}


def _should_apply_dispatch_race_suppression(
    *,
    store: ControlPlaneStore,
    status: DashboardStatusResponse,
    findings: list[DashboardFinding],
) -> bool:
    if not findings or not status.active_items:
        return False
    recent_projects = _recent_dispatch_transition_projects(store)
    if not recent_projects:
        return False
    return bool(_active_project_ids(status) & recent_projects)


def _partition_dispatch_race_findings(
    findings: list[DashboardFinding],
    *,
    status: DashboardStatusResponse,
    suppress_settling_backpressure: bool = False,
    suppress_dispatch_race: bool = True,
) -> tuple[list[DashboardFinding], list[DashboardFinding]]:
    kept: list[DashboardFinding] = []
    suppressed: list[DashboardFinding] = []
    for finding in findings:
        if suppress_dispatch_race and _is_active_row_worker_preflight_race(finding):
            suppressed.append(finding)
            continue
        if suppress_settling_backpressure and (
            _is_cached_worker_preflight_warning(finding)
            or (
                _is_worker_live_without_vm_active_row(finding)
                and _worker_settling_backpressure_matches_finding(status, finding)
            )
        ):
            suppressed.append(finding)
            continue
        kept.append(finding)
    return kept, suppressed


def _suppress_dispatch_race_findings(
    *,
    store: ControlPlaneStore,
    status: DashboardStatusResponse,
    findings: list[DashboardFinding],
) -> tuple[list[DashboardFinding], list[DashboardFinding]]:
    suppress_settling_backpressure = any(
        "worker settling" in str(blocker).lower()
        for blocker in status.dispatch_blockers
    )
    if _should_apply_dispatch_race_suppression(
        store=store, status=status, findings=findings
    ):
        return _partition_dispatch_race_findings(
            findings,
            status=status,
            suppress_settling_backpressure=suppress_settling_backpressure,
            suppress_dispatch_race=True,
        )
    if suppress_settling_backpressure:
        return _partition_dispatch_race_findings(
            findings,
            status=status,
            suppress_settling_backpressure=True,
            suppress_dispatch_race=False,
        )
    return findings, []


def send_pushover(
    config: GateConfig, *, title: str, message: str, priority: int = 0
) -> PushoverResult:
    token = config.pushover_app_token or os.environ.get("PUSHOVER_APP_TOKEN", "")
    user = config.pushover_user_key or os.environ.get("PUSHOVER_USER_KEY", "")
    if not token or not user:
        return PushoverResult(
            attempted=False, ok=False, detail="pushover token/user key not configured"
        )
    data = parse.urlencode(
        {
            "token": token,
            "user": user,
            "title": title,
            "message": message,
            "priority": str(priority),
        }
    ).encode("utf-8")
    try:
        safe_url = validate_http_url(
            config.pushover_api_url, field_name="pushover api url"
        )
        req = request.Request(safe_url, data=data, method="POST")
        with request.urlopen(req, timeout=10) as resp:
            body = resp.read(2048).decode("utf-8", errors="replace")
            return PushoverResult(
                attempted=True,
                ok=200 <= resp.status < 300,
                status_code=resp.status,
                detail=body,
            )
    except Exception as exc:  # pragma: no cover - exercised by integration/runtime
        return PushoverResult(
            attempted=True, ok=False, detail=f"{type(exc).__name__}: {exc}"
        )


def _hermes_webhook_configured(config: GateConfig) -> bool:
    return bool(
        config.hermes_alert_webhook_url or os.environ.get("HERMES_ALERT_WEBHOOK_URL")
    )


def _queue_alert_webhook_payload(
    *,
    fingerprint: str,
    event_id: str | None,
    message: str,
    findings: list[DashboardFinding],
    payload: dict[str, Any],
) -> dict[str, Any]:
    return {
        "source": "enoch-control-plane",
        "service": "enoch-queue-alert-check",
        "severity": "critical" if _findings_include_critical(findings) else "warning",
        "title": "Enoch queue alert",
        "fingerprint": fingerprint,
        "event_id": event_id,
        "message": message,
        "queue_alert": payload,
    }


def send_hermes_alert_webhook(
    config: GateConfig,
    *,
    fingerprint: str,
    event_id: str | None,
    message: str,
    findings: list[DashboardFinding],
    payload: dict[str, Any],
) -> WebhookResult:
    webhook_url = config.hermes_alert_webhook_url or os.environ.get(
        "HERMES_ALERT_WEBHOOK_URL", ""
    )
    if not webhook_url:
        return WebhookResult(
            attempted=False, ok=False, detail="hermes alert webhook url not configured"
        )
    data = json.dumps(
        _queue_alert_webhook_payload(
            fingerprint=fingerprint,
            event_id=event_id,
            message=message,
            findings=findings,
            payload=payload,
        ),
        sort_keys=True,
    ).encode("utf-8")
    try:
        safe_url = validate_http_url(webhook_url, field_name="hermes alert webhook url")
        headers = {
            "Content-Type": "application/json",
            "X-Enoch-Alert-Fingerprint": fingerprint,
        }
        secret = config.hermes_alert_webhook_secret or os.environ.get(
            "HERMES_ALERT_WEBHOOK_SECRET", ""
        )
        if secret:
            signature = hmac.new(secret.encode(), data, hashlib.sha256).hexdigest()
            headers["X-Hub-Signature-256"] = f"sha256={signature}"
        req = request.Request(safe_url, data=data, method="POST", headers=headers)
        with request.urlopen(
            req, timeout=config.hermes_alert_webhook_timeout_sec
        ) as resp:
            body = resp.read(2048).decode("utf-8", errors="replace")
            return WebhookResult(
                attempted=True,
                ok=200 <= resp.status < 300,
                status_code=resp.status,
                detail=body,
            )
    except Exception as exc:  # pragma: no cover - exercised by integration/runtime
        return WebhookResult(
            attempted=True, ok=False, detail=f"{type(exc).__name__}: {exc}"
        )


def _findings_include_critical(findings: list[DashboardFinding]) -> bool:
    return any(f.severity == "critical" for f in findings)


def _maintenance_mode_active(status: DashboardStatusResponse) -> bool:
    return bool(getattr(status.flags, "maintenance_mode", False))


def _pushover_configured(config: GateConfig) -> bool:
    return bool(
        (config.pushover_app_token or os.environ.get("PUSHOVER_APP_TOKEN"))
        and (config.pushover_user_key or os.environ.get("PUSHOVER_USER_KEY"))
    )


@dataclass(frozen=True)
class _QueueAlertPrepared:
    requested_by: str
    dry_run: bool
    force_notify: bool
    fingerprint: str
    cooldown_bucket: int
    cooldown_sec: int
    findings: list[DashboardFinding]
    transient_suppressed_findings: list[DashboardFinding]
    status: DashboardStatusResponse
    should_alert: bool
    idempotency_key: str

    @property
    def payload(self) -> dict[str, Any]:
        return {
            "requested_by": self.requested_by,
            "dry_run": self.dry_run,
            "force_notify": self.force_notify,
            "fingerprint": self.fingerprint,
            "cooldown_bucket": self.cooldown_bucket,
            "cooldown_sec": self.cooldown_sec,
            "generated_at": utc_now(),
            "findings": [item.model_dump(mode="json") for item in self.findings],
            "transient_suppressed_findings": [
                item.model_dump(mode="json")
                for item in self.transient_suppressed_findings
            ],
            "transient_suppression": {
                "enabled": True,
                "grace_sec": DISPATCH_RACE_GRACE_SEC,
                "reason": "recent dispatch transition can precede worker preflight visibility",
            },
            "dispatch_safe": self.status.dispatch_safe,
            "dispatch_blockers": self.status.dispatch_blockers,
            "active_count": len(self.status.active_items),
        }


def _prepare_queue_alert(
    *,
    config: GateConfig,
    store: ControlPlaneStore,
    status: DashboardStatusResponse,
    requested_by: str,
    dry_run: bool,
    force_notify: bool,
) -> _QueueAlertPrepared:
    raw_findings = queue_alert_findings(
        status, hang_after_sec=config.queue_alert_hang_after_sec
    )
    findings, transient_suppressed_findings = _suppress_dispatch_race_findings(
        store=store, status=status, findings=raw_findings
    )
    fingerprint = _fingerprint(findings) if findings else "none"
    now = datetime.now(timezone.utc)
    cooldown_bucket = int(now.timestamp() // config.queue_alert_cooldown_sec)
    return _QueueAlertPrepared(
        requested_by=requested_by,
        dry_run=dry_run,
        force_notify=force_notify,
        fingerprint=fingerprint,
        cooldown_bucket=cooldown_bucket,
        cooldown_sec=config.queue_alert_cooldown_sec,
        findings=findings,
        transient_suppressed_findings=transient_suppressed_findings,
        status=status,
        should_alert=bool(findings),
        idempotency_key=f"queue-alert:{fingerprint}:{cooldown_bucket}",
    )


def _format_queue_alert_message(
    status: DashboardStatusResponse, findings: list[DashboardFinding]
) -> str:
    severity_label = "critical" if _findings_include_critical(findings) else "warn"
    blockers = ", ".join(status.dispatch_blockers) or "none"
    message_lines = [
        "Enoch queue alert: possible stoppage/hang",
        f"Severity: {severity_label}",
        f"Active: {len(status.active_items)} | Blockers: {blockers}",
        "Findings:",
    ]
    for item in findings[:5]:
        message_lines.append(f"- {item.severity.upper()} {item.source}: {item.message}")
    if len(findings) > 5:
        message_lines.append(f"- +{len(findings) - 5} more")
    return "\n".join(message_lines)[:1024]


def _append_queue_alert_event(
    store: ControlPlaneStore,
    *,
    idempotency_key: str,
    fingerprint: str,
    payload: dict[str, Any],
) -> tuple[str | None, bool, str]:
    event_id: str | None = None
    inserted = False
    event_append_error = ""
    try:
        event_id, inserted = store.append_event(
            idempotency_key=idempotency_key,
            event_type="queue_alert.detected",
            entity_type="queue_alert",
            entity_id=fingerprint,
            payload={**payload, "payload_hash": _event_payload_hash(payload)},
        )
    except IdempotencyConflict:
        inserted = False
    except Exception as exc:
        event_append_error = f"{type(exc).__name__}: {exc}"
        inserted = False
    return event_id, inserted, event_append_error


def _dispatch_queue_alert_notification(
    config: GateConfig,
    *,
    findings: list[DashboardFinding],
    message: str,
    force_notify: bool,
    inserted: bool,
    event_append_error: str,
) -> tuple[bool, bool, PushoverResult]:
    if not (inserted or force_notify or event_append_error):
        return (
            False,
            True,
            PushoverResult(
                attempted=False, ok=True, detail="cooldown duplicate suppressed"
            ),
        )
    if not (config.pushover_alerts_enabled or force_notify):
        return (
            False,
            False,
            PushoverResult(
                attempted=False, ok=False, detail="pushover alerts disabled"
            ),
        )
    notification = send_pushover(
        config,
        title="Enoch queue alert",
        message=message,
        priority=1 if _findings_include_critical(findings) else 0,
    )
    return notification.ok, False, notification


def _dispatch_queue_alert_webhook(
    config: GateConfig,
    *,
    findings: list[DashboardFinding],
    message: str,
    force_notify: bool,
    inserted: bool,
    event_id: str | None,
    fingerprint: str,
    payload: dict[str, Any],
) -> WebhookResult:
    if not (inserted or force_notify):
        return WebhookResult(
            attempted=False, ok=True, detail="cooldown duplicate suppressed"
        )
    if not (config.hermes_alert_webhook_enabled or force_notify):
        return WebhookResult(
            attempted=False, ok=False, detail="hermes alert webhook disabled"
        )
    return send_hermes_alert_webhook(
        config,
        fingerprint=fingerprint,
        event_id=event_id,
        message=message,
        findings=findings,
        payload=payload,
    )


def _queue_alert_result_ok(
    *,
    should_alert: bool,
    dry_run: bool,
    sent: bool,
    suppressed: bool,
    config: GateConfig,
    force_notify: bool,
) -> bool:
    return (
        not should_alert
        or dry_run
        or sent
        or suppressed
        or not (config.pushover_alerts_enabled or force_notify)
    )


@dataclass(frozen=True)
class _QueueAlertDeliveryState:
    sent: bool
    suppressed: bool
    notification: PushoverResult
    hermes_webhook: WebhookResult
    event_id: str | None
    inserted: bool
    event_append_error: str
    suppression_reason: str = ""


_NO_ALERT_DELIVERY = _QueueAlertDeliveryState(
    sent=False,
    suppressed=False,
    notification=PushoverResult(attempted=False, ok=False, detail="no alert findings"),
    hermes_webhook=WebhookResult(attempted=False, ok=False, detail="no alert findings"),
    event_id=None,
    inserted=False,
    event_append_error="",
)


def _build_queue_alert_result(
    *,
    config: GateConfig,
    dry_run: bool,
    force_notify: bool,
    should_alert: bool,
    fingerprint: str,
    delivery: _QueueAlertDeliveryState,
    findings: list[DashboardFinding],
    transient_suppressed_findings: list[DashboardFinding],
) -> dict[str, Any]:
    return {
        "ok": _queue_alert_result_ok(
            should_alert=should_alert,
            dry_run=dry_run,
            sent=delivery.sent,
            suppressed=delivery.suppressed,
            config=config,
            force_notify=force_notify,
        )
        and (
            not should_alert
            or dry_run
            or delivery.suppressed
            or not config.hermes_alert_webhook_enabled
            or delivery.hermes_webhook.ok
        ),
        "source": "control_api_queue_alert_check",
        "generated_at": utc_now(),
        "dry_run": dry_run,
        "should_alert": should_alert,
        "sent": delivery.sent,
        "suppressed": delivery.suppressed,
        "suppressed_by_cooldown": delivery.suppression_reason == "cooldown",
        "suppression_reason": delivery.suppression_reason,
        "fingerprint": fingerprint,
        "event_id": delivery.event_id,
        "inserted_event": delivery.inserted,
        "event_append_error": delivery.event_append_error,
        "alerts_enabled": config.pushover_alerts_enabled,
        "pushover_configured": _pushover_configured(config),
        "notification": delivery.notification.__dict__,
        "hermes_alert_webhook_enabled": config.hermes_alert_webhook_enabled,
        "hermes_alert_webhook_configured": _hermes_webhook_configured(config),
        "hermes_webhook": delivery.hermes_webhook.__dict__,
        "findings": [item.model_dump(mode="json") for item in findings],
        "transient_suppressed_findings": [
            item.model_dump(mode="json") for item in transient_suppressed_findings
        ],
    }


def _deliver_queue_alert(
    *,
    config: GateConfig,
    store: ControlPlaneStore,
    status: DashboardStatusResponse,
    dry_run: bool,
    force_notify: bool,
    findings: list[DashboardFinding],
    idempotency_key: str,
    fingerprint: str,
    payload: dict[str, Any],
) -> _QueueAlertDeliveryState:
    message = _format_queue_alert_message(status, findings)
    if dry_run:
        return _QueueAlertDeliveryState(
            sent=False,
            suppressed=False,
            notification=PushoverResult(attempted=False, ok=True, detail="dry run"),
            hermes_webhook=WebhookResult(attempted=False, ok=True, detail="dry run"),
            event_id=None,
            inserted=False,
            event_append_error="",
        )
    if _maintenance_mode_active(status):
        return _QueueAlertDeliveryState(
            sent=False,
            suppressed=True,
            notification=PushoverResult(
                attempted=False,
                ok=True,
                detail="maintenance mode suppresses pushover alert delivery",
            ),
            hermes_webhook=WebhookResult(
                attempted=False,
                ok=True,
                detail="maintenance mode suppresses hermes alert webhook delivery",
            ),
            event_id=None,
            inserted=False,
            event_append_error="",
            suppression_reason="maintenance_mode",
        )
    event_id, inserted, event_append_error = _append_queue_alert_event(
        store,
        idempotency_key=idempotency_key,
        fingerprint=fingerprint,
        payload=payload,
    )
    sent, suppressed, notification = _dispatch_queue_alert_notification(
        config,
        findings=findings,
        message=message,
        force_notify=force_notify,
        inserted=inserted,
        event_append_error=event_append_error,
    )
    hermes_webhook = _dispatch_queue_alert_webhook(
        config,
        findings=findings,
        message=message,
        force_notify=force_notify,
        inserted=inserted,
        event_id=event_id,
        fingerprint=fingerprint,
        payload=payload,
    )
    return _QueueAlertDeliveryState(
        sent=sent,
        suppressed=suppressed,
        notification=notification,
        suppression_reason="cooldown" if suppressed else "",
        hermes_webhook=hermes_webhook,
        event_id=event_id,
        inserted=inserted,
        event_append_error=event_append_error,
    )


def evaluate_and_notify_queue_alerts(
    *,
    config: GateConfig,
    store: ControlPlaneStore,
    status: DashboardStatusResponse,
    dry_run: bool,
    force_notify: bool,
    requested_by: str,
) -> dict[str, Any]:
    prepared = _prepare_queue_alert(
        config=config,
        store=store,
        status=status,
        requested_by=requested_by,
        dry_run=dry_run,
        force_notify=force_notify,
    )
    delivery = (
        _deliver_queue_alert(
            config=config,
            store=store,
            status=prepared.status,
            dry_run=prepared.dry_run,
            force_notify=prepared.force_notify,
            findings=prepared.findings,
            idempotency_key=prepared.idempotency_key,
            fingerprint=prepared.fingerprint,
            payload=prepared.payload,
        )
        if prepared.should_alert
        else _NO_ALERT_DELIVERY
    )
    return _build_queue_alert_result(
        config=config,
        dry_run=prepared.dry_run,
        force_notify=prepared.force_notify,
        should_alert=prepared.should_alert,
        fingerprint=prepared.fingerprint,
        delivery=delivery,
        findings=prepared.findings,
        transient_suppressed_findings=prepared.transient_suppressed_findings,
    )
