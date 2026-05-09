#!/usr/bin/env python3
"""Refresh worker evidence and run queue hang/stoppage alert checks."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from urllib.parse import quote
from urllib import error, request


def _load_config() -> dict:
    path = Path(os.environ.get("ENOCH_CONFIG") or os.environ.get("OMX_WAKE_GATE_CONFIG", "/etc/enoch/config.json"))
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


def _post_json(base_url: str, path: str, token: str, payload: dict, *, timeout: int = 30) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(
        f"{base_url}{path}",
        data=data,
        method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
    )
    with request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _preflight_summary(preflight: dict) -> dict:
    checks = preflight.get("checks") if isinstance(preflight.get("checks"), list) else []
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


def main() -> int:
    config = _load_config()
    token = str(config.get("control_api_bearer_token") or config.get("omx_inbound_bearer_token") or "")
    if not token:
        print("control_api_bearer_token is not configured", file=sys.stderr)
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
    paper_draft_before_dispatch_enabled = bool(config.get("queue_pump_paper_draft_enabled", False))
    followup_launch_enabled = bool(config.get("queue_pump_followup_launch_enabled", False))
    dispatch = {"action": "skipped", "reason": "queue pump disabled"}
    paper_draft = {"action": "skipped", "reason": "queue pump disabled"}
    followup_dry_run = {"action": "skipped", "reason": "queue pump disabled"}
    followup_launch = {"action": "skipped", "reason": "queue pump disabled"}
    publication_rewrite = {"action": "skipped", "reason": "no paper drafted"}
    if queue_pump_enabled:
        only_no_candidate_blocker = _only_no_candidate_blocker(status)
        if alert.get("should_alert"):
            dispatch = {"action": "skipped", "reason": "alert findings present; operator reconciliation required first"}
            followup_dry_run = {"action": "skipped", "reason": "alert findings present; operator reconciliation required first"}
            followup_launch = {"action": "skipped", "reason": "alert findings present; operator reconciliation required first"}
        elif not status.get("dispatch_safe") and not only_no_candidate_blocker:
            dispatch = {"action": "skipped", "reason": "dispatch not safe", "blockers": status.get("dispatch_blockers") or []}
            followup_dry_run = {"action": "skipped", "reason": "dispatch not safe", "blockers": status.get("dispatch_blockers") or []}
            followup_launch = {"action": "skipped", "reason": "dispatch not safe", "blockers": status.get("dispatch_blockers") or []}
        elif status.get("active_items"):
            dispatch = {"action": "skipped", "reason": "active worker lane present"}
            followup_dry_run = {"action": "skipped", "reason": "active worker lane present"}
            followup_launch = {"action": "skipped", "reason": "active worker lane present"}
        else:
            if not paper_draft_before_dispatch_enabled:
                paper_draft = {"action": "skipped", "reason": "queue pump paper drafting disabled"}
            else:
                paper_draft = _post_json(
                    base_url,
                    "/control/papers/draft-next",
                    token,
                    {"dry_run": False, "requested_by": "systemd:queue-pump-before-dispatch"},
                )
            if paper_draft.get("action") == "drafted":
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
                dispatch = {"action": "skipped", "reason": "paper drafted before dispatch"}
            elif not status.get("next_candidate"):
                if not followup_launch_enabled:
                    followup_dry_run = {"action": "skipped", "reason": "queue pump follow-up launch disabled"}
                    followup_launch = {"action": "skipped", "reason": "queue pump follow-up launch disabled"}
                    dispatch = {"action": "skipped", "reason": "no queued candidate"}
                else:
                    followup_dry_run = _post_json(
                        base_url,
                        "/control/api/v1/followups/launch-next",
                        token,
                        {"dry_run": True, "requested_by": "systemd:queue-pump-followup", "max_followup_depth": 2},
                    )
                    if followup_dry_run.get("action") != "dry_run_followup":
                        followup_launch = {
                            "action": "skipped",
                            "reason": "no follow-up candidate selected by dry-run",
                            "dry_run_action": followup_dry_run.get("action"),
                        }
                        dispatch = {
                            "action": "skipped",
                            "reason": "no queued candidate and no follow-up candidate",
                            "followup_action": followup_dry_run.get("action"),
                        }
                    else:
                        followup_launch = _post_json(
                            base_url,
                            "/control/api/v1/followups/launch-next",
                            token,
                            {"dry_run": False, "requested_by": "systemd:queue-pump-followup", "max_followup_depth": 2},
                        )
                        if followup_launch.get("action") == "followup_queued":
                            dispatch = _post_json(
                                base_url,
                                "/control/dispatch-next",
                                token,
                                {"dry_run": False, "requested_by": "systemd:queue-pump", "force_preflight": True},
                            )
                        else:
                            dispatch = {
                                "action": "skipped",
                                "reason": "no queued candidate and no follow-up queued",
                                "followup_action": followup_launch.get("action"),
                            }
            else:
                followup_dry_run = {"action": "skipped", "reason": "queued candidate already present"}
                followup_launch = {"action": "skipped", "reason": "queued candidate already present"}
                dispatch = _post_json(
                    base_url,
                    "/control/dispatch-next",
                    token,
                    {"dry_run": False, "requested_by": "systemd:queue-pump", "force_preflight": True},
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
        "status": status_summary,
        "paper_draft": paper_draft,
        "followup_dry_run": followup_dry_run,
        "followup_launch": followup_launch,
        "publication_rewrite": publication_rewrite,
        "dispatch": dispatch,
    }
    print(json.dumps(output, sort_keys=True))
    return 1 if alert.get("should_alert") and not (alert.get("sent") or alert.get("suppressed_by_cooldown") or not alert.get("alerts_enabled")) else 0


if __name__ == "__main__":
    raise SystemExit(main())
