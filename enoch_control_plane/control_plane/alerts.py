from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from typing import Any
from urllib import parse, request

from ..config import GateConfig
from ..enoch_core.store import IdempotencyConflict
from ..models import utc_now
from ..timeutils import parse_utc_datetime
from ..url_safety import validate_http_url
from .models import DashboardFinding, DashboardStatusResponse
from .store import ControlPlaneStore


DISPATCH_RACE_GRACE_SEC = 180
DISPATCH_TRANSITION_EVENTS = {
    "controller.dispatch_claimed",
    "controller.live_dispatch",
    "followup.launch",
}


@dataclass(frozen=True)
class PushoverResult:
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


def _has_idle_lane_dispatch_opportunity(status: DashboardStatusResponse) -> bool:
    if getattr(status, "next_candidate", None):
        return True
    worker_lanes = getattr(status, "worker_lanes", []) or []
    if not isinstance(worker_lanes, list):
        return False
    for lane in worker_lanes:
        if not isinstance(lane, dict):
            continue
        if (
            bool(lane.get("dispatch_available"))
            and int(lane.get("queued_count") or 0) > 0
        ):
            return True
    return False


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
        "control_plane_db+worker_preflight",
        "worker_settling",
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


def queue_alert_findings(
    status: DashboardStatusResponse, *, hang_after_sec: int
) -> list[DashboardFinding]:
    flags = status.flags
    intentional_hold = flags.queue_paused or flags.maintenance_mode
    findings: list[DashboardFinding] = list(status.conflicts)

    if not intentional_hold and status.config.live_dispatch_enabled:
        findings.extend(
            _collect_live_dispatch_alert_findings(status, hang_after_sec=hang_after_sec)
        )

    return _dedupe_alert_findings(findings)


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
        event_type = str(row.get("event_type") or "")
        if event_type not in DISPATCH_TRANSITION_EVENTS:
            continue
        created_at = _parse_ts(str(row.get("created_at") or ""))
        if created_at is None or created_at < cutoff:
            continue
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


def _is_active_row_worker_preflight_race(finding: DashboardFinding) -> bool:
    if finding.source != "control_plane_db+worker_preflight":
        return False
    return (
        "active row" in finding.message.lower()
        and "no live worker run" in finding.message.lower()
    )


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
) -> tuple[list[DashboardFinding], list[DashboardFinding]]:
    kept: list[DashboardFinding] = []
    suppressed: list[DashboardFinding] = []
    for finding in findings:
        if _is_active_row_worker_preflight_race(finding):
            suppressed.append(finding)
        else:
            kept.append(finding)
    return kept, suppressed


def _suppress_dispatch_race_findings(
    *,
    store: ControlPlaneStore,
    status: DashboardStatusResponse,
    findings: list[DashboardFinding],
) -> tuple[list[DashboardFinding], list[DashboardFinding]]:
    if not _should_apply_dispatch_race_suppression(
        store=store, status=status, findings=findings
    ):
        return findings, []
    return _partition_dispatch_race_findings(findings)


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


def _findings_include_critical(findings: list[DashboardFinding]) -> bool:
    return any(f.severity == "critical" for f in findings)


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
    event_id: str | None
    inserted: bool
    event_append_error: str


_NO_ALERT_DELIVERY = _QueueAlertDeliveryState(
    sent=False,
    suppressed=False,
    notification=PushoverResult(attempted=False, ok=False, detail="no alert findings"),
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
        ),
        "source": "control_api_queue_alert_check",
        "generated_at": utc_now(),
        "dry_run": dry_run,
        "should_alert": should_alert,
        "sent": delivery.sent,
        "suppressed_by_cooldown": delivery.suppressed,
        "fingerprint": fingerprint,
        "event_id": delivery.event_id,
        "inserted_event": delivery.inserted,
        "event_append_error": delivery.event_append_error,
        "alerts_enabled": config.pushover_alerts_enabled,
        "pushover_configured": _pushover_configured(config),
        "notification": delivery.notification.__dict__,
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
            event_id=None,
            inserted=False,
            event_append_error="",
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
    return _QueueAlertDeliveryState(
        sent=sent,
        suppressed=suppressed,
        notification=notification,
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
