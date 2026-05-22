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


def _observed_worker_runs(status: DashboardStatusResponse) -> list[dict[str, Any]]:
    observations = getattr(status, "observations", {}) or {}
    runs: list[dict[str, Any]] = []
    if not isinstance(observations, dict):
        return runs

    def add_from(value: Any) -> None:
        if not isinstance(value, (dict, list)) and hasattr(value, "model_dump"):
            try:
                value = value.model_dump(mode="json")
            except TypeError:
                value = value.model_dump()
        if isinstance(value, dict):
            maybe_runs = value.get("runs")
            if isinstance(maybe_runs, list):
                runs.extend(item for item in maybe_runs if isinstance(item, dict))
            for nested_key in ("body", "payload", "data"):
                nested = value.get(nested_key)
                if nested is not value:
                    add_from(nested)
            checks = value.get("checks")
            if isinstance(checks, list):
                for check in checks:
                    add_from(check)
        elif isinstance(value, list):
            for item in value:
                add_from(item)

    for source in ("worker_preflight", "worker_dashboard_api"):
        add_from(observations.get(source))
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


def queue_alert_findings(
    status: DashboardStatusResponse, *, hang_after_sec: int
) -> list[DashboardFinding]:
    flags = status.flags
    intentional_hold = flags.queue_paused or flags.maintenance_mode
    findings: list[DashboardFinding] = []
    active_lane_findings: list[DashboardFinding] = []

    for item in status.conflicts:
        findings.append(item)

    if not intentional_hold and status.config.live_dispatch_enabled:
        for row in status.active_items:
            stale_at = _parse_ts(row.get("stale_after"))
            if stale_at and datetime.now(timezone.utc) > stale_at:
                if _has_live_worker_run(status, str(row.get("current_run_id") or "")):
                    continue
                active_lane_findings.append(
                    DashboardFinding(
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
                )
            elif not stale_at:
                updated = _parse_ts(
                    row.get("updated_at") or row.get("last_dispatch_at")
                )
                if updated and datetime.now(timezone.utc) > updated + timedelta(
                    seconds=hang_after_sec
                ):
                    if _has_live_worker_run(
                        status, str(row.get("current_run_id") or "")
                    ):
                        continue
                    active_lane_findings.append(
                        DashboardFinding(
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
                    )

        active_lane_present = bool(status.active_items)
        active_lane_unhealthy = bool(active_lane_findings)
        idle_lane_dispatch_opportunity = _has_idle_lane_dispatch_opportunity(status)

        for item in status.warnings:
            if item.source == "worker_resource_policy":
                findings.append(item)
                continue
            if item.source in {
                "worker_preflight",
                "worker_dashboard_api",
                "control_plane_db+worker_preflight",
                "worker_settling",
            }:
                if (
                    active_lane_present
                    and not active_lane_unhealthy
                    and not idle_lane_dispatch_opportunity
                    and item.source in {"worker_preflight", "worker_dashboard_api"}
                ):
                    continue
                findings.append(item)

        for source, freshness in status.source_freshness.items():
            if (
                source in {"worker_preflight", "worker_dashboard_api"}
                and freshness.stale
            ):
                if (
                    active_lane_present
                    and not active_lane_unhealthy
                    and not idle_lane_dispatch_opportunity
                ):
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

        findings.extend(active_lane_findings)

    deduped: dict[str, DashboardFinding] = {}
    for item in findings:
        key = f"{item.severity}|{item.source}|{item.message}"
        deduped.setdefault(key, item)
    return list(deduped.values())


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


def _suppress_dispatch_race_findings(
    *,
    store: ControlPlaneStore,
    status: DashboardStatusResponse,
    findings: list[DashboardFinding],
) -> tuple[list[DashboardFinding], list[DashboardFinding]]:
    if not findings or not status.active_items:
        return findings, []
    recent_projects = _recent_dispatch_transition_projects(store)
    if not recent_projects:
        return findings, []
    active_projects = {str(row.get("project_id") or "") for row in status.active_items}
    if not (active_projects & recent_projects):
        return findings, []
    kept: list[DashboardFinding] = []
    suppressed: list[DashboardFinding] = []
    for finding in findings:
        if _is_active_row_worker_preflight_race(finding):
            suppressed.append(finding)
        else:
            kept.append(finding)
    return kept, suppressed


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


def evaluate_and_notify_queue_alerts(
    *,
    config: GateConfig,
    store: ControlPlaneStore,
    status: DashboardStatusResponse,
    dry_run: bool,
    force_notify: bool,
    requested_by: str,
) -> dict[str, Any]:
    raw_findings = queue_alert_findings(
        status, hang_after_sec=config.queue_alert_hang_after_sec
    )
    findings, transient_suppressed_findings = _suppress_dispatch_race_findings(
        store=store, status=status, findings=raw_findings
    )
    fingerprint = _fingerprint(findings) if findings else "none"
    now = datetime.now(timezone.utc)
    cooldown_bucket = int(now.timestamp() // config.queue_alert_cooldown_sec)
    idempotency_key = f"queue-alert:{fingerprint}:{cooldown_bucket}"
    should_alert = bool(findings)
    payload = {
        "requested_by": requested_by,
        "dry_run": dry_run,
        "force_notify": force_notify,
        "fingerprint": fingerprint,
        "cooldown_bucket": cooldown_bucket,
        "cooldown_sec": config.queue_alert_cooldown_sec,
        "generated_at": utc_now(),
        "findings": [item.model_dump(mode="json") for item in findings],
        "transient_suppressed_findings": [
            item.model_dump(mode="json") for item in transient_suppressed_findings
        ],
        "transient_suppression": {
            "enabled": True,
            "grace_sec": DISPATCH_RACE_GRACE_SEC,
            "reason": "recent dispatch transition can precede worker preflight visibility",
        },
        "dispatch_safe": status.dispatch_safe,
        "dispatch_blockers": status.dispatch_blockers,
        "active_count": len(status.active_items),
    }
    sent = False
    suppressed = False
    notification = PushoverResult(attempted=False, ok=False, detail="no alert findings")
    event_id = None
    inserted = False
    event_append_error = ""
    if should_alert:
        message_lines = [
            "Enoch queue alert: possible stoppage/hang",
            f"Severity: {'critical' if any(f.severity == 'critical' for f in findings) else 'warn'}",
            f"Active: {len(status.active_items)} | Blockers: {', '.join(status.dispatch_blockers) or 'none'}",
            "Findings:",
        ]
        for item in findings[:5]:
            message_lines.append(
                f"- {item.severity.upper()} {item.source}: {item.message}"
            )
        if len(findings) > 5:
            message_lines.append(f"- +{len(findings) - 5} more")
        message = "\n".join(message_lines)[:1024]
        if dry_run:
            notification = PushoverResult(attempted=False, ok=True, detail="dry run")
        else:
            try:
                event_id, inserted = store.append_event(
                    idempotency_key=idempotency_key,
                    event_type="queue_alert.detected",
                    entity_type="queue_alert",
                    entity_id=fingerprint,
                    payload={**payload, "payload_hash": _event_payload_hash(payload)},
                )
            except IdempotencyConflict:
                # Same alert bucket with a non-identical timestamp/payload shape; treat as cooldown.
                inserted = False
            except Exception as exc:
                event_append_error = f"{type(exc).__name__}: {exc}"
                inserted = False
            if inserted or force_notify or event_append_error:
                if config.pushover_alerts_enabled or force_notify:
                    notification = send_pushover(
                        config,
                        title="Enoch queue alert",
                        message=message,
                        priority=1
                        if any(f.severity == "critical" for f in findings)
                        else 0,
                    )
                    sent = notification.ok
                else:
                    notification = PushoverResult(
                        attempted=False, ok=False, detail="pushover alerts disabled"
                    )
            else:
                suppressed = True
                notification = PushoverResult(
                    attempted=False, ok=True, detail="cooldown duplicate suppressed"
                )
    return {
        "ok": not should_alert
        or dry_run
        or sent
        or suppressed
        or not (config.pushover_alerts_enabled or force_notify),
        "source": "control_api_queue_alert_check",
        "generated_at": utc_now(),
        "dry_run": dry_run,
        "should_alert": should_alert,
        "sent": sent,
        "suppressed_by_cooldown": suppressed,
        "fingerprint": fingerprint,
        "event_id": event_id,
        "inserted_event": inserted,
        "event_append_error": event_append_error,
        "alerts_enabled": config.pushover_alerts_enabled,
        "pushover_configured": bool(
            (config.pushover_app_token or os.environ.get("PUSHOVER_APP_TOKEN"))
            and (config.pushover_user_key or os.environ.get("PUSHOVER_USER_KEY"))
        ),
        "notification": notification.__dict__,
        "findings": [item.model_dump(mode="json") for item in findings],
        "transient_suppressed_findings": [
            item.model_dump(mode="json") for item in transient_suppressed_findings
        ],
    }
