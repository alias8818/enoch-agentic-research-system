#!/usr/bin/env python3
"""Run one bounded Research Facility automation tick.

The service is inert unless ENOCH_ENABLE_RESEARCH_AUTOPILOT=1 is set.  A live
tick is intentionally small: at most one provider request, one promotion, one
dispatch, one positive-gated paper draft, and one automated finalization.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from urllib import error, request


def _load_config() -> dict:
    path = Path(os.environ.get("ENOCH_CONFIG") or os.environ.get("ENOCH_CONTROL_PLANE_CONFIG", "/etc/enoch-control-plane/config.json"))
    return json.loads(path.read_text(encoding="utf-8"))


def _base_url(config: dict) -> str:
    host = str(config.get("listen_host") or "127.0.0.1")
    if host in {"0.0.0.0", "::"}:
        host = "127.0.0.1"
    return os.environ.get("ENOCH_CONTROL_URL") or f"http://{host}:{int(config.get('listen_port') or 8787)}"


def _post_json(base_url: str, path: str, token: str, payload: dict, *, timeout: int) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(
        f"{base_url}{path}",
        data=data,
        method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
    )
    with request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - local/operator-configured control URL
        return json.loads(resp.read().decode("utf-8"))


def _truthy(name: str, default: str = "0") -> bool:
    return str(os.environ.get(name, default)).strip().lower() in {"1", "true", "yes", "on"}


def _bounded_int(name: str, default: int, lower: int, upper: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError:
        value = default
    return max(lower, min(value, upper))


def main() -> int:
    if not _truthy("ENOCH_ENABLE_RESEARCH_AUTOPILOT"):
        print(json.dumps({"ok": True, "action": "skipped", "reason": "research autopilot disabled; set ENOCH_ENABLE_RESEARCH_AUTOPILOT=1"}, sort_keys=True))
        return 0

    config = _load_config()
    token = os.environ.get("ENOCH_CONTROL_TOKEN") or str(config.get("control_api_bearer_token") or config.get("omx_inbound_bearer_token") or "")
    if not token:
        print(json.dumps({"ok": False, "action": "skipped", "reason": "missing control-plane token"}, sort_keys=True), file=sys.stderr)
        return 2

    wait_for_completion = _truthy("ENOCH_RESEARCH_AUTOPILOT_WAIT", "1")
    max_wait_seconds = _bounded_int("ENOCH_RESEARCH_AUTOPILOT_MAX_WAIT_SECONDS", 900, 0, 1800)
    payload = {
        "enabled": True,
        "dry_run": False,
        "requested_by": os.environ.get("ENOCH_RESEARCH_AUTOPILOT_REQUESTED_BY", "systemd:enoch-research-autopilot"),
        "model": os.environ.get("ENOCH_RESEARCH_PROVIDER_MODEL", "hf:zai-org/GLM-5.1"),
        "topic": os.environ.get("ENOCH_RESEARCH_AUTOPILOT_TOPIC", ""),
        "temperature": float(os.environ.get("ENOCH_RESEARCH_AUTOPILOT_TEMPERATURE", "0.6")),
        "generation_max_tokens": _bounded_int("ENOCH_RESEARCH_PROVIDER_MAX_TOKENS", 8000, 1000, 16000),
        "generation_attempts": _bounded_int("ENOCH_RESEARCH_PROVIDER_ATTEMPTS", 2, 1, 3),
        "max_provider_requests_per_run": _bounded_int("ENOCH_RESEARCH_AUTOPILOT_PROVIDER_REQUESTS", 1, 0, 1),
        "max_promotions_per_run": _bounded_int("ENOCH_RESEARCH_AUTOPILOT_PROMOTIONS", 1, 0, 1),
        "max_dispatches_per_run": 1 if _truthy("ENOCH_RESEARCH_AUTOPILOT_DISPATCH", "1") else 0,
        "wait_for_completion": wait_for_completion,
        "max_wait_seconds": max_wait_seconds if wait_for_completion else 0,
        "poll_interval_seconds": _bounded_int("ENOCH_RESEARCH_AUTOPILOT_POLL_SECONDS", 10, 2, 60),
        "max_paper_drafts_per_run": 1 if _truthy("ENOCH_RESEARCH_AUTOPILOT_PAPERS", "1") else 0,
        "max_publication_rewrites_per_run": 1 if _truthy("ENOCH_RESEARCH_AUTOPILOT_PAPERS", "1") else 0,
        "min_remaining_credits": float(os.environ.get("ENOCH_RESEARCH_AUTOPILOT_MIN_CREDITS", "5.0")),
        "min_rolling_remaining": _bounded_int("ENOCH_RESEARCH_AUTOPILOT_MIN_ROLLING", 10, 0, 2500),
        "reserve_requests": _bounded_int("ENOCH_RESEARCH_AUTOPILOT_RESERVE_REQUESTS", 2, 0, 100),
    }
    try:
        result = _post_json(
            _base_url(config),
            "/control/api/research/run-cycle",
            token,
            payload,
            timeout=max(60, max_wait_seconds + 120),
        )
    except (error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "action": "failed", "reason": f"research autopilot request failed: {type(exc).__name__}: {exc}"}, sort_keys=True), file=sys.stderr)
        return 1

    print(json.dumps(result, sort_keys=True))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
