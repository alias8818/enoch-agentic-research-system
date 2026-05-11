#!/usr/bin/env python3
"""Run one bounded Research Facility automation tick.

The service is inert unless ENOCH_ENABLE_RESEARCH_AUTOPILOT=1 is set.  A live
tick is intentionally small: at most one provider request, one promotion, one
dispatch, one positive-gated paper draft, and one automated finalization.
"""
from __future__ import annotations

import json
from http.client import RemoteDisconnected
import os
from pathlib import Path
import subprocess
import sys
import time
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


def _get_json(base_url: str, path: str, token: str, *, timeout: int) -> dict:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    req = request.Request(f"{base_url}{path}", method="GET", headers=headers)
    with request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - local/operator-configured control URL
        return json.loads(resp.read().decode("utf-8"))


def _control_plane_recovered(base_url: str, token: str) -> bool:
    """Return true when the local control API is reachable after a dropped tick.

    A deploy or service restart can close the long-running run-cycle request
    while a worker is still healthy or after the bounded tick already made
    progress. Do not retry the POST because it is not idempotent; just verify
    the control plane recovered so the next timer tick can continue safely.
    """

    for _ in range(3):
        time.sleep(2)
        try:
            health = _get_json(base_url, "/healthz", token, timeout=5)
        except (OSError, TimeoutError, error.URLError, json.JSONDecodeError):
            continue
        if health.get("ok"):
            return True
    return False


def _truthy(name: str, default: str = "0") -> bool:
    return str(os.environ.get(name, default)).strip().lower() in {"1", "true", "yes", "on"}


def _bounded_int(name: str, default: int, lower: int, upper: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError:
        value = default
    return max(lower, min(value, upper))


def _provider_model() -> str:
    explicit = os.environ.get("ENOCH_RESEARCH_PROVIDER_MODEL")
    if explicit:
        return explicit
    rotation = [
        item.strip()
        for item in os.environ.get("ENOCH_RESEARCH_PROVIDER_MODEL_ROTATION", "hf:zai-org/GLM-5.1,hf:moonshotai/Kimi-K2.6").split(",")
        if item.strip()
    ]
    if not rotation:
        return "hf:zai-org/GLM-5.1"
    window_seconds = _bounded_int("ENOCH_RESEARCH_PROVIDER_MODEL_ROTATION_SECONDS", 1200, 60, 86400)
    return rotation[int(time.time() // window_seconds) % len(rotation)]


def _topic() -> str:
    explicit = os.environ.get("ENOCH_RESEARCH_AUTOPILOT_TOPIC")
    if explicit:
        return explicit
    rotation = [
        item.strip()
        for item in os.environ.get(
            "ENOCH_RESEARCH_TOPIC_ROTATION",
            (
                "speculative decoding without extra draft-model VRAM,"
                "tiny-VRAM training and optimizer memory reduction,"
                "agent reliability with falsifiable evidence ledgers,"
                "distributed volunteer training with cheating-resistant validation,"
                "long-context memory with exact anchors and compressed state,"
                "extreme quantization with principled residual channels,"
                "local-serving routing and model cascades,"
                "data selection for tiny local pretraining"
            ),
        ).split(",")
        if item.strip()
    ]
    if not rotation:
        return ""
    window_seconds = _bounded_int("ENOCH_RESEARCH_TOPIC_ROTATION_SECONDS", 1800, 60, 86400)
    return rotation[int(time.time() // window_seconds) % len(rotation)]




def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _database_url() -> str:
    return (
        os.environ.get("ENOCH_RESEARCH_QUALITY_DATABASE_URL")
        or os.environ.get("ENOCH_SUPABASE_DATABASE_URL")
        or os.environ.get("ENOCH_CONTROL_DATABASE_URL")
        or os.environ.get("DATABASE_URL")
        or ""
    ).strip()


def refresh_research_quality_report() -> dict:
    """Refresh the read-only Research Facility quality report.

    This is intentionally fail-soft for the main autopilot tick: generating the
    report must never enqueue, dispatch, draft, or mutate database state. The
    dashboard readiness surface still exposes stale/missing reports as a
    separate operator-visible condition.
    """

    if _truthy("ENOCH_RESEARCH_QUALITY_REFRESH_DISABLED"):
        return {"ok": True, "action": "research_quality_refresh_skipped", "reason": "disabled"}

    database_url = _database_url()
    if not database_url:
        return {"ok": False, "action": "research_quality_refresh_skipped", "reason": "missing database URL"}

    output = Path(
        os.environ.get(
            "ENOCH_RESEARCH_QUALITY_REPORT_PATH",
            "/var/lib/enoch-control-plane/research-quality/latest-report.json",
        )
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    limit = _bounded_int("ENOCH_RESEARCH_QUALITY_LIMIT", 100, 1, 1000)
    timeout = _bounded_int("ENOCH_RESEARCH_QUALITY_TIMEOUT_SECONDS", 90, 10, 600)
    script = _repo_root() / "scripts" / "dspy_research_quality.py"
    cmd = [
        sys.executable,
        str(script),
        "--database-url",
        database_url,
        "--limit",
        str(limit),
        "--output",
        str(output),
        "--pretty",
    ]
    display_cmd = [*cmd]
    if database_url in display_cmd:
        display_cmd[display_cmd.index(database_url)] = "<redacted-database-url>"

    try:
        proc = subprocess.run(
            cmd,
            cwd=_repo_root(),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "action": "research_quality_refresh_failed",
            "reason": f"timeout after {timeout}s: {exc}",
            "command": display_cmd,
            "output": str(output),
        }
    except OSError as exc:
        return {
            "ok": False,
            "action": "research_quality_refresh_failed",
            "reason": f"{type(exc).__name__}: {exc}",
            "command": display_cmd,
            "output": str(output),
        }

    stdout = proc.stdout.strip()
    stderr = proc.stderr.strip()
    return {
        "ok": proc.returncode == 0,
        "action": "research_quality_refresh",
        "returncode": proc.returncode,
        "output": str(output),
        "limit": limit,
        "stdout": stdout[-2000:],
        "stderr": stderr[-2000:],
        "command": display_cmd,
    }


def _is_benign_skip_result(result: dict) -> bool:
    """Return true for normal long-haul idle/backpressure outcomes.

    The timer should not enter failed state just because a previous tick still
    has a worker lane active. That is expected bounded backpressure, not an
    automation failure.
    """

    reason = str(result.get("reason") or "").lower()
    action = str(result.get("action") or "").lower()
    return (
        "active worker lane already exists" in reason
        or action in {"skipped", "noop"}
    )


def main() -> int:
    if _truthy("ENOCH_RESEARCH_QUALITY_REFRESH_ONLY"):
        result = refresh_research_quality_report()
        print(json.dumps(result, sort_keys=True))
        return 0 if result.get("ok") else 1

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
        "model": _provider_model(),
        "topic": _topic(),
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
    base_url = _base_url(config)
    try:
        result = _post_json(
            base_url,
            "/control/api/research/run-cycle",
            token,
            payload,
            timeout=max(60, max_wait_seconds + 120),
        )
    except RemoteDisconnected as exc:
        if _control_plane_recovered(base_url, token):
            print(json.dumps({
                "ok": True,
                "action": "transient_disconnect",
                "reason": f"control plane disconnected during bounded research tick and recovered: {type(exc).__name__}: {exc}",
            }, sort_keys=True))
            return 0
        print(json.dumps({"ok": False, "action": "failed", "reason": f"research autopilot request failed: {type(exc).__name__}: {exc}"}, sort_keys=True), file=sys.stderr)
        return 1
    except (error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "action": "failed", "reason": f"research autopilot request failed: {type(exc).__name__}: {exc}"}, sort_keys=True), file=sys.stderr)
        return 1

    quality_result = refresh_research_quality_report()
    if isinstance(result, dict):
        result["research_quality_refresh"] = quality_result
    print(json.dumps(result, sort_keys=True))
    tick_ok = result.get("ok") or _is_benign_skip_result(result)
    return 0 if tick_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
