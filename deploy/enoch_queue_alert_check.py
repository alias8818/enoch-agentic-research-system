#!/usr/bin/env python3
"""Refresh worker evidence and run queue hang/stoppage alert checks."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from urllib import error, request


def _load_config() -> dict:
    path = Path(os.environ.get("OMX_WAKE_GATE_CONFIG", "/etc/omx-wake-gate/config.json"))
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
    with request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _post_json(base_url: str, path: str, token: str, payload: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(
        f"{base_url}{path}",
        data=data,
        method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
    )
    with request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    config = _load_config()
    token = str(config.get("omx_inbound_bearer_token") or "")
    if not token:
        print("omx_inbound_bearer_token is not configured", file=sys.stderr)
        return 2
    base_url = _base_url(config)
    preflight_payload = {
        "wake_gate_url": config.get("worker_wake_gate_url") or "http://worker.example:8787",
        "bearer_token": config.get("worker_wake_gate_bearer_token") or "",
        "require_paused": False,
        "strict": False,
    }
    try:
        preflight = _post_json(base_url, "/control/api/preflight", token, preflight_payload)
    except (error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        preflight = {"ok": False, "error": f"preflight request failed: {type(exc).__name__}: {exc}"}
    alert = _post_json(
        base_url,
        "/control/api/alerts/queue-check",
        token,
        {"dry_run": False, "requested_by": "systemd:enoch-queue-alert-check"},
    )
    status = _get_json(base_url, "/control/api/status", token)
    queue_pump_enabled = bool(config.get("queue_pump_enabled", config.get("live_dispatch_enabled", False)))
    dispatch = {"action": "skipped", "reason": "queue pump disabled"}
    if queue_pump_enabled:
        if alert.get("should_alert"):
            dispatch = {"action": "skipped", "reason": "alert findings present; operator reconciliation required first"}
        elif not status.get("dispatch_safe"):
            dispatch = {"action": "skipped", "reason": "dispatch not safe", "blockers": status.get("dispatch_blockers") or []}
        elif not status.get("next_candidate"):
            dispatch = {"action": "skipped", "reason": "no queued candidate"}
        else:
            dispatch = _post_json(
                base_url,
                "/control/dispatch-next",
                token,
                {"dry_run": False, "requested_by": "systemd:queue-pump", "force_preflight": True},
            )
    print(json.dumps({"preflight": preflight, "alert": alert, "status": {"dispatch_safe": status.get("dispatch_safe"), "dispatch_blockers": status.get("dispatch_blockers"), "active_count": len(status.get("active_items") or []), "next_candidate": (status.get("next_candidate") or {}).get("project_id")}, "dispatch": dispatch}, sort_keys=True))
    return 1 if alert.get("should_alert") and not (alert.get("sent") or alert.get("suppressed_by_cooldown") or not alert.get("alerts_enabled")) else 0


if __name__ == "__main__":
    raise SystemExit(main())
