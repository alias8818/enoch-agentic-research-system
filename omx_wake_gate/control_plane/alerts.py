from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from typing import Any
from urllib import parse, request

from ..config import GateConfig
from ..models import utc_now
from .models import DashboardFinding, DashboardStatusResponse
from .store import ControlPlaneStore


@dataclass(frozen=True)
class PushoverResult:
    attempted: bool
    ok: bool
    status_code: int | None = None
    detail: str = ""


def _parse_ts(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None


def _event_payload_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()[:16]


def _fingerprint(findings: list[DashboardFinding]) -> str:
    parts = [f"{item.severity}|{item.source}|{item.message}" for item in findings]
    return hashlib.sha256("\n".join(sorted(parts)).encode("utf-8")).hexdigest()[:16]


def queue_alert_findings(status: DashboardStatusResponse, *, hang_after_sec: int) -> list[DashboardFinding]:
    flags = status.flags
    intentional_hold = flags.queue_paused or flags.maintenance_mode
    findings: list[DashboardFinding] = []

    for item in status.conflicts:
        findings.append(item)

    if not intentional_hold and status.config.live_dispatch_enabled:
        for item in status.warnings:
            if item.source in {"worker_preflight", "worker_dashboard_api", "control_plane_db+worker_preflight"}:
                findings.append(item)

        for source, freshness in status.source_freshness.items():
            if source in {"worker_preflight", "worker_dashboard_api"} and freshness.stale:
                findings.append(DashboardFinding(
                    severity="warn",
                    source=source,
                    authority=freshness.authority,
                    message=f"{source} is stale or missing while live dispatch is enabled",
                    observed_at=freshness.observed_at,
                    suggested_action="refresh /control/api/preflight and verify GB10 worker health",
                ))

        for row in status.active_items:
            stale_at = _parse_ts(row.get("stale_after"))
            if stale_at and datetime.now(timezone.utc) > stale_at:
                findings.append(DashboardFinding(
                    severity="warn",
                    source="control_plane_db",
                    authority="queue_items.stale_after",
                    message="active queue item exceeded its stale_after timestamp",
                    observed_at=row.get("stale_after"),
                    suggested_action="inspect run detail and reconcile the queue item",
                    data={"project_id": row.get("project_id"), "run_id": row.get("current_run_id")},
                ))
            elif not stale_at:
                updated = _parse_ts(row.get("updated_at") or row.get("last_dispatch_at"))
                if updated and datetime.now(timezone.utc) > updated + timedelta(seconds=hang_after_sec):
                    findings.append(DashboardFinding(
                        severity="warn",
                        source="control_plane_db",
                        authority="queue_items.updated_at",
                        message=f"active queue item has not updated for more than {hang_after_sec} seconds",
                        observed_at=row.get("updated_at") or row.get("last_dispatch_at"),
                        suggested_action="inspect GB10 wake gate and active run detail",
                        data={"project_id": row.get("project_id"), "run_id": row.get("current_run_id")},
                    ))

    deduped: dict[str, DashboardFinding] = {}
    for item in findings:
        key = f"{item.severity}|{item.source}|{item.message}"
        deduped.setdefault(key, item)
    return list(deduped.values())


def send_pushover(config: GateConfig, *, title: str, message: str, priority: int = 0) -> PushoverResult:
    token = config.pushover_app_token or os.environ.get("PUSHOVER_APP_TOKEN", "")
    user = config.pushover_user_key or os.environ.get("PUSHOVER_USER_KEY", "")
    if not token or not user:
        return PushoverResult(attempted=False, ok=False, detail="pushover token/user key not configured")
    data = parse.urlencode({
        "token": token,
        "user": user,
        "title": title,
        "message": message,
        "priority": str(priority),
    }).encode("utf-8")
    try:
        req = request.Request(config.pushover_api_url, data=data, method="POST")
        with request.urlopen(req, timeout=10) as resp:
            body = resp.read(2048).decode("utf-8", errors="replace")
            return PushoverResult(attempted=True, ok=200 <= resp.status < 300, status_code=resp.status, detail=body)
    except Exception as exc:  # pragma: no cover - exercised by integration/runtime
        return PushoverResult(attempted=True, ok=False, detail=f"{type(exc).__name__}: {exc}")


def evaluate_and_notify_queue_alerts(
    *,
    config: GateConfig,
    store: ControlPlaneStore,
    status: DashboardStatusResponse,
    dry_run: bool,
    force_notify: bool,
    requested_by: str,
) -> dict[str, Any]:
    findings = queue_alert_findings(status, hang_after_sec=config.queue_alert_hang_after_sec)
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
        "dispatch_safe": status.dispatch_safe,
        "dispatch_blockers": status.dispatch_blockers,
        "active_count": len(status.active_items),
    }
    sent = False
    suppressed = False
    notification = PushoverResult(attempted=False, ok=False, detail="no alert findings")
    event_id = None
    inserted = False
    if should_alert:
        message_lines = [
            "Enoch queue alert: possible stoppage/hang",
            f"Severity: {'critical' if any(f.severity == 'critical' for f in findings) else 'warn'}",
            f"Active: {len(status.active_items)} | Blockers: {', '.join(status.dispatch_blockers) or 'none'}",
            "Findings:",
        ]
        for item in findings[:5]:
            message_lines.append(f"- {item.severity.upper()} {item.source}: {item.message}")
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
            except Exception:
                # If the same alert already exists with an older payload shape, avoid spamming.
                inserted = False
            if inserted or force_notify:
                if config.pushover_alerts_enabled or force_notify:
                    notification = send_pushover(config, title="Enoch queue alert", message=message, priority=1 if any(f.severity == "critical" for f in findings) else 0)
                    sent = notification.ok
                else:
                    notification = PushoverResult(attempted=False, ok=False, detail="pushover alerts disabled")
            else:
                suppressed = True
                notification = PushoverResult(attempted=False, ok=True, detail="cooldown duplicate suppressed")
    return {
        "ok": not should_alert or dry_run or sent or suppressed or not (config.pushover_alerts_enabled or force_notify),
        "source": "control_api_queue_alert_check",
        "generated_at": utc_now(),
        "dry_run": dry_run,
        "should_alert": should_alert,
        "sent": sent,
        "suppressed_by_cooldown": suppressed,
        "fingerprint": fingerprint,
        "event_id": event_id,
        "inserted_event": inserted,
        "alerts_enabled": config.pushover_alerts_enabled,
        "pushover_configured": bool((config.pushover_app_token or os.environ.get("PUSHOVER_APP_TOKEN")) and (config.pushover_user_key or os.environ.get("PUSHOVER_USER_KEY"))),
        "notification": notification.__dict__,
        "findings": [item.model_dump(mode="json") for item in findings],
    }
