#!/usr/bin/env python3
"""Refresh worker evidence and run queue hang/stoppage alert checks."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hmac
import json
import os
import hashlib
from pathlib import Path
import sys
import time
from urllib.parse import quote, urlencode
from urllib import error, request
from enoch_control_plane.url_safety import urlopen_validated

# Centralized skip reasons (eliminates S1192 string duplication across the
# alert/dispatch decision dicts at module and runtime level).
ALERT_FINDINGS_PRESENT_REASON = (
    "alert findings present; operator reconciliation required first"
)
DISPATCH_NOT_SAFE_REASON = "dispatch not safe"
ACTIVE_WORKER_LANE_PRESENT_REASON = "active worker lane present"
QUEUE_PUMP_DISABLED_REASON = "queue pump disabled"
CONTROL_HELD_REASON = "control plane held"
CLI_DRY_RUN_REASON = "cli dry-run"
READINESS_ALERT_STATE = "longhaul-readiness-alert.json"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_now() -> str:
    return _utc_now().isoformat().replace("+00:00", "Z")


def _load_config() -> dict:
    path = Path(
        os.environ.get("ENOCH_CONFIG")
        or os.environ.get(
            "ENOCH_CONTROL_PLANE_CONFIG", "/etc/enoch-control-plane/config.json"
        )
    )
    return json.loads(path.read_text(encoding="utf-8"))


def _base_url(config: dict) -> str:
    host = str(config.get("listen_host") or "127.0.0.1")
    if host in {"0.0.0.0", "::"}:
        host = "127.0.0.1"
    return f"http://{host}:{int(config.get('listen_port') or 8787)}"


def _get_json(base_url: str, path: str, token: str) -> dict:
    req = request.Request(
        f"{base_url}{path}",
        method="GET",
        headers={"Authorization": f"Bearer {token}"},
    )
    with urlopen_validated(
        req,
        timeout=30,
        field_name="deploy/enoch_queue_alert_check.py url",
        allow_private=True,
    ) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _post_json(
    base_url: str, path: str, token: str, payload: dict, *, timeout: int = 30
) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(
        f"{base_url}{path}",
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
    )
    with urlopen_validated(
        req,
        timeout=timeout,
        field_name="deploy/enoch_queue_alert_check.py url",
        allow_private=True,
    ) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _state_dir(config: dict) -> Path:
    return Path(str(config.get("state_dir") or "/var/lib/enoch-control-plane"))


def _readiness_fingerprint(readiness: dict) -> str:
    blockers = (
        readiness.get("blockers") if isinstance(readiness.get("blockers"), list) else []
    )
    payload = {"label": readiness.get("label"), "blockers": blockers}
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]


def _readiness_message(readiness: dict) -> str:
    blockers = (
        readiness.get("blockers") if isinstance(readiness.get("blockers"), list) else []
    )
    label = str(readiness.get("label") or "Long-haul mode blocked")
    shown = "; ".join(str(item) for item in blockers[:3])
    if len(blockers) > 3:
        shown += f"; +{len(blockers) - 3} more"
    return f"{label}. blockers={shown or 'unknown'}"


def _cooldown_suppressed(config: dict, fingerprint: str, *, now: datetime) -> bool:
    cooldown = int(config.get("queue_alert_cooldown_sec") or 1800)
    path = _state_dir(config) / READINESS_ALERT_STATE
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if str(state.get("fingerprint") or "") != fingerprint:
        return False
    try:
        sent_at = datetime.fromisoformat(
            str(state.get("last_sent_at") or "").replace("Z", "+00:00")
        )
    except ValueError:
        return False
    return (now - sent_at).total_seconds() < cooldown


def _record_readiness_alert(config: dict, fingerprint: str, *, now: datetime) -> None:
    path = _state_dir(config) / READINESS_ALERT_STATE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "fingerprint": fingerprint,
                "last_sent_at": now.isoformat().replace("+00:00", "Z"),
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _post_pushover(config: dict, *, title: str, message: str) -> dict:
    token = str(
        config.get("pushover_app_token") or os.environ.get("PUSHOVER_APP_TOKEN") or ""
    )
    user = str(
        config.get("pushover_user_key") or os.environ.get("PUSHOVER_USER_KEY") or ""
    )
    if not token or not user:
        return {
            "attempted": False,
            "ok": False,
            "detail": "pushover token/user key not configured",
        }
    data = urlencode(
        {
            "token": token,
            "user": user,
            "title": title,
            "message": message,
            "priority": "1",
        }
    ).encode("utf-8")
    try:
        req = request.Request(
            str(
                config.get("pushover_api_url")
                or "https://api.pushover.net/1/messages.json"
            ),
            data=data,
            method="POST",
        )
        with urlopen_validated(req, timeout=10, field_name="pushover api url") as resp:
            return {
                "attempted": True,
                "ok": 200 <= resp.status < 300,
                "status_code": resp.status,
                "detail": resp.read(512).decode("utf-8", errors="replace"),
            }
    except Exception as exc:  # pragma: no cover - live network failure path
        return {
            "attempted": True,
            "ok": False,
            "detail": f"{type(exc).__name__}: {exc}",
        }


def _post_hermes_webhook(
    config: dict, *, fingerprint: str, message: str, readiness: dict
) -> dict:
    webhook_url = str(
        config.get("hermes_alert_webhook_url")
        or os.environ.get("HERMES_ALERT_WEBHOOK_URL")
        or ""
    )
    if not webhook_url:
        return {
            "attempted": False,
            "ok": False,
            "detail": "hermes alert webhook url not configured",
        }
    payload = {
        "source": "enoch-control-plane",
        "service": "enoch-longhaul-readiness",
        "severity": "critical",
        "title": "Enoch long-haul readiness blocked",
        "fingerprint": fingerprint,
        "message": message,
        "readiness": {
            "ok": readiness.get("ok"),
            "label": readiness.get("label"),
            "blockers": readiness.get("blockers") or [],
            "status": readiness.get("status"),
        },
        "generated_at": _iso_now(),
    }
    data = json.dumps(payload, sort_keys=True).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "X-Enoch-Alert-Fingerprint": fingerprint,
    }
    secret = str(
        config.get("hermes_alert_webhook_secret")
        or os.environ.get("HERMES_ALERT_WEBHOOK_SECRET")
        or ""
    )
    if secret:
        signature = hmac.new(secret.encode(), data, hashlib.sha256).hexdigest()
        headers["X-Hub-Signature-256"] = f"sha256={signature}"
    try:
        req = request.Request(webhook_url, data=data, method="POST", headers=headers)
        with urlopen_validated(
            req,
            timeout=int(config.get("hermes_alert_webhook_timeout_sec") or 8),
            field_name="hermes alert webhook url",
            allow_private=True,
        ) as resp:
            return {
                "attempted": True,
                "ok": 200 <= resp.status < 300,
                "status_code": resp.status,
                "detail": resp.read(512).decode("utf-8", errors="replace"),
            }
    except Exception as exc:  # pragma: no cover - live network failure path
        return {
            "attempted": True,
            "ok": False,
            "detail": f"{type(exc).__name__}: {exc}",
        }


def _check_and_notify_readiness(
    config: dict, base_url: str, token: str, *, dry_run: bool
) -> dict:
    retry_delay = float(config.get("readiness_endpoint_retry_delay_sec") or 5.0)
    retry_attempts = max(1, int(config.get("readiness_endpoint_retry_attempts") or 8))
    last_exc: Exception | None = None
    readiness: dict[str, object] | None = None
    for attempt in range(retry_attempts):
        try:
            readiness = _get_json(
                base_url, "/control/api/v1/automation-readiness", token
            )
            break
        except (error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_exc = exc
            if retry_delay <= 0 or attempt >= retry_attempts - 1:
                break
            time.sleep(retry_delay)

    if readiness is None:
        assert last_exc is not None
        retry_word = "retry" if retry_attempts <= 2 else f"{retry_attempts} attempts"
        readiness = {
            "ok": False,
            "label": "Long-haul readiness check failed",
            "blockers": [
                f"readiness endpoint failed after {retry_word}: "
                f"{type(last_exc).__name__}: {last_exc}"
            ],
        }
    if readiness.get("ok") is True:
        return {"ok": True, "should_alert": False, "readiness_ok": True}
    fingerprint = _readiness_fingerprint(readiness)
    message = _readiness_message(readiness)
    now = _utc_now()
    if dry_run:
        return {
            "ok": True,
            "should_alert": True,
            "dry_run": True,
            "fingerprint": fingerprint,
            "message": message,
            "notification": {
                "attempted": False,
                "ok": False,
                "detail": CLI_DRY_RUN_REASON,
            },
            "hermes_webhook": {
                "attempted": False,
                "ok": False,
                "detail": CLI_DRY_RUN_REASON,
            },
        }
    if _cooldown_suppressed(config, fingerprint, now=now):
        return {
            "ok": True,
            "should_alert": True,
            "suppressed_by_cooldown": True,
            "fingerprint": fingerprint,
            "message": message,
            "notification": {
                "attempted": False,
                "ok": True,
                "detail": "cooldown suppressed",
            },
            "hermes_webhook": {
                "attempted": False,
                "ok": True,
                "detail": "cooldown suppressed",
            },
        }
    pushover = (
        _post_pushover(
            config, title="Enoch long-haul readiness blocked", message=message
        )
        if bool(config.get("pushover_alerts_enabled"))
        else {"attempted": False, "ok": False, "detail": "pushover alerts disabled"}
    )
    webhook = (
        _post_hermes_webhook(
            config, fingerprint=fingerprint, message=message, readiness=readiness
        )
        if bool(config.get("hermes_alert_webhook_enabled"))
        else {"attempted": False, "ok": False, "detail": "hermes webhook disabled"}
    )
    if pushover.get("ok") or webhook.get("ok"):
        _record_readiness_alert(config, fingerprint, now=now)
    return {
        "ok": True,
        "should_alert": True,
        "suppressed_by_cooldown": False,
        "fingerprint": fingerprint,
        "message": message,
        "notification": pushover,
        "hermes_webhook": webhook,
    }


def _preflight_summary(preflight: dict) -> dict:
    checks = (
        preflight.get("checks") if isinstance(preflight.get("checks"), list) else []
    )
    return {
        "ok": preflight.get("ok"),
        "target": preflight.get("target"),
        "summary": preflight.get("summary"),
        "failed_checks": [
            {"name": check.get("name"), "detail": check.get("detail")}
            for check in checks
            if isinstance(check, dict) and not check.get("ok")
        ],
        "check_count": len(checks),
    }


def _only_no_candidate_blocker(status: dict) -> bool:
    blockers = status.get("dispatch_blockers") or []
    return blockers == ["no queued dispatch candidate"]


def _skipped(reason: str, **extra: object) -> dict:
    return {"action": "skipped", "reason": reason, **extra}


def _control_hold_state(status: dict) -> dict:
    flags = status.get("flags") if isinstance(status.get("flags"), dict) else {}
    held_by: list[str] = []
    if bool(flags.get("maintenance_mode")):
        held_by.append("maintenance_mode")
    if bool(flags.get("queue_paused")):
        held_by.append("queue_paused")
    return {
        "held": bool(held_by),
        "held_by": held_by,
        "queue_paused": bool(flags.get("queue_paused")),
        "maintenance_mode": bool(flags.get("maintenance_mode")),
        "pause_reason": str(flags.get("pause_reason") or ""),
    }


def _held_skip(reason: str, status: dict) -> dict:
    hold = _control_hold_state(status)
    return _skipped(
        reason,
        held_by=hold["held_by"],
        queue_paused=hold["queue_paused"],
        maintenance_mode=hold["maintenance_mode"],
        pause_reason=hold["pause_reason"],
    )


def _skip_dispatch_followup_bundle(
    reason: str, *, blockers: list | None = None
) -> tuple[dict, dict, dict]:
    extra = {"blockers": blockers} if blockers is not None else {}
    dispatch = _skipped(reason, **extra)
    followup_dry_run = _skipped(reason, **extra)
    followup_launch = _skipped(reason, **extra)
    return dispatch, followup_dry_run, followup_launch


def _run_paper_draft_step(
    base_url: str, token: str, paper_draft_before_dispatch_enabled: bool
) -> dict:
    if not paper_draft_before_dispatch_enabled:
        return _skipped("queue pump paper drafting disabled")
    try:
        return _post_json(
            base_url,
            "/control/papers/draft-next",
            token,
            {
                "dry_run": False,
                "requested_by": "systemd:queue-pump-before-dispatch",
            },
        )
    except (error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        return {
            "action": "error",
            "reason": f"paper draft-next failed before dispatch: {type(exc).__name__}: {exc}",
        }


def _publication_rewrite_after_draft(
    base_url: str, token: str, paper_draft: dict
) -> tuple[dict, dict]:
    paper_id = str((paper_draft.get("paper") or {}).get("paper_id") or "")
    publication_rewrite = _post_json(
        base_url,
        f"/control/api/publication-automation/{quote(paper_id, safe='')}/rewrite-draft",
        token,
        {
            "idempotency_key": f"paper-publication-pipeline:{paper_id or 'unknown'}",
            "requested_by": "systemd:queue-pump-before-dispatch",
            "force": True,
        },
        timeout=int(os.environ.get("ENOCH_PAPER_REWRITE_TIMEOUT_SEC", "900")),
    )
    dispatch = _skipped("paper drafted before dispatch")
    return publication_rewrite, dispatch


def _run_followup_launch_chain(base_url: str, token: str) -> tuple[dict, dict, dict]:
    followup_dry_run = _post_json(
        base_url,
        "/control/api/v1/followups/launch-next",
        token,
        {
            "dry_run": True,
            "requested_by": "systemd:queue-pump-followup",
            "max_followup_depth": 4,
        },
    )
    if followup_dry_run.get("action") != "dry_run_followup":
        followup_launch = _skipped(
            "no follow-up candidate selected by dry-run",
            dry_run_action=followup_dry_run.get("action"),
        )
        dispatch = _skipped(
            "no queued candidate and no follow-up candidate",
            followup_action=followup_dry_run.get("action"),
        )
        return dispatch, followup_dry_run, followup_launch

    followup_launch = _post_json(
        base_url,
        "/control/api/v1/followups/launch-next",
        token,
        {
            "dry_run": False,
            "requested_by": "systemd:queue-pump-followup",
            "max_followup_depth": 4,
        },
    )
    if followup_launch.get("action") == "followup_queued":
        dispatch = _post_json(
            base_url,
            "/control/dispatch-next",
            token,
            {
                "dry_run": False,
                "requested_by": "systemd:queue-pump",
                "force_preflight": True,
            },
        )
    else:
        dispatch = _skipped(
            "no queued candidate and no follow-up queued",
            followup_action=followup_launch.get("action"),
        )
    return dispatch, followup_dry_run, followup_launch


def _pump_when_no_next_candidate(
    base_url: str,
    token: str,
    status: dict,
    *,
    followup_launch_enabled: bool,
) -> tuple[dict, dict, dict]:
    if status.get("active_items"):
        return _skip_dispatch_followup_bundle(ACTIVE_WORKER_LANE_PRESENT_REASON)
    if not followup_launch_enabled:
        return (
            _skipped("no queued candidate"),
            _skipped("queue pump follow-up launch disabled"),
            _skipped("queue pump follow-up launch disabled"),
        )
    return _run_followup_launch_chain(base_url, token)


def _http_error_body_metadata(exc: error.HTTPError) -> dict[str, object]:
    try:
        body = exc.read()
    except (OSError, ValueError):
        body = b""
    if not isinstance(body, bytes):
        body = str(body).encode("utf-8", errors="replace")
    return {
        "response_body_bytes": len(body),
        "response_body_sha256": hashlib.sha256(body).hexdigest() if body else "",
    }


def _dispatch_error_summary(exc: error.HTTPError) -> dict[str, object]:
    return _skipped(
        DISPATCH_NOT_SAFE_REASON,
        http_status=exc.code,
        error_type=type(exc).__name__,
        detail=str(exc),
        **_http_error_body_metadata(exc),
    )


def _pump_when_candidate_present(base_url: str, token: str) -> tuple[dict, dict, dict]:
    followup_dry_run = _skipped("queued candidate already present")
    followup_launch = _skipped("queued candidate already present")
    try:
        dispatch = _post_json(
            base_url,
            "/control/dispatch-next",
            token,
            {
                "dry_run": False,
                "requested_by": "systemd:queue-pump",
                "force_preflight": True,
            },
        )
    except error.HTTPError as exc:
        dispatch = _dispatch_error_summary(exc)
    return dispatch, followup_dry_run, followup_launch


def _execute_queue_pump(
    *,
    base_url: str,
    token: str,
    status: dict,
    alert: dict,
    paper_draft_before_dispatch_enabled: bool,
    followup_launch_enabled: bool,
) -> tuple[dict, dict, dict, dict, dict]:
    """Run enabled queue-pump actions (extracted from main for S3776)."""
    pump_disabled = _skipped(QUEUE_PUMP_DISABLED_REASON)
    publication_rewrite = _skipped("no paper drafted")
    paper_draft = pump_disabled

    if _control_hold_state(status)["held"]:
        dispatch, followup_dry_run, followup_launch = _skip_dispatch_followup_bundle(
            CONTROL_HELD_REASON,
            blockers=[*(_control_hold_state(status)["held_by"] or [])],
        )
        paper_draft = _held_skip(CONTROL_HELD_REASON, status)
        publication_rewrite = _held_skip(CONTROL_HELD_REASON, status)
        return (
            dispatch,
            paper_draft,
            followup_dry_run,
            followup_launch,
            publication_rewrite,
        )

    if alert.get("should_alert"):
        dispatch, followup_dry_run, followup_launch = _skip_dispatch_followup_bundle(
            ALERT_FINDINGS_PRESENT_REASON
        )
        return (
            dispatch,
            paper_draft,
            followup_dry_run,
            followup_launch,
            publication_rewrite,
        )

    if not status.get("dispatch_safe") and not _only_no_candidate_blocker(status):
        blockers = status.get("dispatch_blockers") or []
        dispatch, followup_dry_run, followup_launch = _skip_dispatch_followup_bundle(
            DISPATCH_NOT_SAFE_REASON, blockers=blockers
        )
        return (
            dispatch,
            paper_draft,
            followup_dry_run,
            followup_launch,
            publication_rewrite,
        )

    paper_draft = _run_paper_draft_step(
        base_url, token, paper_draft_before_dispatch_enabled
    )
    if paper_draft.get("action") == "drafted":
        publication_rewrite, dispatch = _publication_rewrite_after_draft(
            base_url, token, paper_draft
        )
        return (
            dispatch,
            paper_draft,
            pump_disabled,
            pump_disabled,
            publication_rewrite,
        )

    if not status.get("next_candidate"):
        dispatch, followup_dry_run, followup_launch = _pump_when_no_next_candidate(
            base_url,
            token,
            status,
            followup_launch_enabled=followup_launch_enabled,
        )
        return (
            dispatch,
            paper_draft,
            followup_dry_run,
            followup_launch,
            publication_rewrite,
        )

    dispatch, followup_dry_run, followup_launch = _pump_when_candidate_present(
        base_url, token
    )
    return dispatch, paper_draft, followup_dry_run, followup_launch, publication_rewrite


def _exit_code_for_alert(alert: dict) -> int:
    if not alert.get("should_alert"):
        return 0
    if alert.get("sent") or alert.get("suppressed_by_cooldown"):
        return 0
    if not alert.get("alerts_enabled"):
        return 0
    return 1


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Refresh worker evidence and run Enoch queue alert checks."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Run alert checks without notifications or queue-pump side effects. "
            "This mode never dispatches, drafts papers, or launches follow-ups."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON output (currently the only output format).",
    )
    args, _unknown = parser.parse_known_args(argv)
    return args


def main() -> int:
    args = _parse_args()
    cli_dry_run = bool(args.dry_run)
    config = _load_config()
    token = str(
        config.get("control_api_bearer_token")
        or config.get("omx_inbound_bearer_token")
        or ""
    )
    if not token:
        print("control_api_bearer_token is not configured", file=sys.stderr)
        return 2
    base_url = _base_url(config)
    preflight_payload = {
        "wake_gate_url": config.get("worker_wake_gate_url")
        or "https://worker.example:8787",
        "bearer_token": config.get("worker_wake_gate_bearer_token") or "",
        "require_paused": False,
        "strict": False,
    }
    try:
        preflight = _post_json(
            base_url, "/control/api/preflight", token, preflight_payload
        )
    except (error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        preflight = {
            "ok": False,
            "error": f"preflight request failed: {type(exc).__name__}: {exc}",
        }
    status = _get_json(base_url, "/control/api/status?refresh_worker=true", token)
    if _control_hold_state(status)["held"]:
        alert = {
            "should_alert": False,
            "sent": False,
            "alerts_enabled": False,
            "action": "skipped",
            "reason": CONTROL_HELD_REASON,
            "hold_state": _control_hold_state(status),
        }
    else:
        alert = _post_json(
            base_url,
            "/control/api/alerts/queue-check",
            token,
            {
                "dry_run": cli_dry_run,
                "refresh_worker": True,
                "requested_by": (
                    "cli:enoch-queue-alert-check-dry-run"
                    if cli_dry_run
                    else "systemd:enoch-queue-alert-check"
                ),
            },
        )
    readiness_alert = _check_and_notify_readiness(
        config, base_url, token, dry_run=cli_dry_run
    )
    queue_pump_enabled = bool(
        config.get("queue_pump_enabled", config.get("live_dispatch_enabled", False))
    )
    paper_draft_before_dispatch_enabled = bool(
        config.get("queue_pump_paper_draft_enabled", False)
    )
    followup_launch_enabled = bool(
        config.get("queue_pump_followup_launch_enabled", False)
    )
    dispatch = _skipped(QUEUE_PUMP_DISABLED_REASON)
    paper_draft = _skipped(QUEUE_PUMP_DISABLED_REASON)
    followup_dry_run = _skipped(QUEUE_PUMP_DISABLED_REASON)
    followup_launch = _skipped(QUEUE_PUMP_DISABLED_REASON)
    publication_rewrite = _skipped("no paper drafted")
    if cli_dry_run:
        dispatch = _skipped(CLI_DRY_RUN_REASON)
        paper_draft = _skipped(CLI_DRY_RUN_REASON)
        followup_dry_run = _skipped(CLI_DRY_RUN_REASON)
        followup_launch = _skipped(CLI_DRY_RUN_REASON)
        publication_rewrite = _skipped(CLI_DRY_RUN_REASON)
    elif queue_pump_enabled:
        (
            dispatch,
            paper_draft,
            followup_dry_run,
            followup_launch,
            publication_rewrite,
        ) = _execute_queue_pump(
            base_url=base_url,
            token=token,
            status=status,
            alert=alert,
            paper_draft_before_dispatch_enabled=paper_draft_before_dispatch_enabled,
            followup_launch_enabled=followup_launch_enabled,
        )
    status_summary = {
        "dispatch_safe": status.get("dispatch_safe"),
        "dispatch_blockers": status.get("dispatch_blockers"),
        "active_count": len(status.get("active_items") or []),
        "next_candidate": (status.get("next_candidate") or {}).get("project_id"),
    }
    output = {
        "preflight": _preflight_summary(preflight),
        "alert": alert,
        "readiness_alert": readiness_alert,
        "status": status_summary,
        "paper_draft": paper_draft,
        "followup_dry_run": followup_dry_run,
        "followup_launch": followup_launch,
        "publication_rewrite": publication_rewrite,
        "dispatch": dispatch,
    }
    print(json.dumps(output, sort_keys=True))
    return _exit_code_for_alert(alert)


if __name__ == "__main__":
    raise SystemExit(main())
