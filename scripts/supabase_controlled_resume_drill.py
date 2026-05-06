#!/usr/bin/env python3
"""Run a fail-closed one-dispatch Supabase resume drill.

Default mode is dry-run only. With --apply, the script:
1. runs resume-readiness checks while paused;
2. resumes the control plane with maintenance_mode=false;
3. dispatches exactly one candidate with /control/dispatch-next dry_run=false;
4. waits for an active queue item/run to appear;
5. re-pauses immediately unless --leave-unpaused is explicitly passed;
6. prints a structured report.

It refuses to run broad timers or loops. This script does not enable systemd
timers and does not draft papers.
"""

from __future__ import annotations

import argparse
import json
import os
import time
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.validate_supabase_resume_readiness import validate as validate_resume_readiness


class DrillError(RuntimeError):
    pass


def _load_token(path: str) -> str:
    explicit = os.environ.get("ENOCH_CONTROL_PLANE_TOKEN", "").strip()
    if explicit:
        return explicit
    try:
        return open(path, encoding="utf-8").read().strip()
    except OSError:
        return ""


def _request(method: str, url: str, token: str, payload: dict[str, Any] | None = None, *, timeout: int = 30) -> tuple[int, Any]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Accept", "application/json")
    if body is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:  # noqa: S310 - operator-provided LAN URL
            text = response.read().decode("utf-8")
            return response.status, json.loads(text) if text else {}
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8")
        try:
            return exc.code, json.loads(text) if text else {}
        except json.JSONDecodeError:
            return exc.code, {"raw": text}


def _require_200(label: str, response: tuple[int, Any]) -> Any:
    status, body = response
    if status != 200:
        raise DrillError(f"{label} returned HTTP {status}: {body}")
    return body


def _get_state(base: str, token: str) -> dict[str, Any]:
    return _require_200("state", _request("GET", f"{base}/control/state", token))


def _get_overview(base: str, token: str) -> dict[str, Any]:
    return _require_200("overview", _request("GET", f"{base}/control/api/v1/overview", token))


def _wait_for_active(base: str, token: str, *, timeout_seconds: float) -> dict[str, Any] | None:
    deadline = time.monotonic() + timeout_seconds
    last: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        overview = _get_overview(base, token)
        active = ((overview.get("lanes") or {}).get("active") or [])
        if active:
            return active[0]
        last = overview
        time.sleep(2)
    return {"timeout": True, "last_overview_counts": (last or {}).get("counts", {})}


def drill(args: argparse.Namespace) -> dict[str, Any]:
    token = _load_token(args.token_file)
    if not token:
        raise DrillError("missing control-plane token; set ENOCH_CONTROL_PLANE_TOKEN or --token-file")
    base = args.control_url.rstrip("/")

    readiness_args = argparse.Namespace(control_url=args.control_url, token_file=args.token_file, ssh_host=args.ssh_host, output="")
    readiness = validate_resume_readiness(readiness_args)
    if not readiness.get("ok"):
        raise DrillError(f"resume readiness failed: {readiness.get('failures')}")

    state_before = _get_state(base, token)
    flags_before = state_before.get("flags") or {}
    if not flags_before.get("queue_paused") or not flags_before.get("maintenance_mode"):
        raise DrillError(f"expected paused maintenance before drill, got flags={flags_before}")

    dry_dispatch = _require_200(
        "dispatch dry-run",
        _request("POST", f"{base}/control/dispatch-next", token, {"dry_run": True, "requested_by": "supabase-controlled-resume-drill"}),
    )
    if dry_dispatch.get("action") != "paused" or dry_dispatch.get("event_id") is not None:
        raise DrillError(f"paused dry-run dispatch is not side-effect-free: {dry_dispatch}")

    report: dict[str, Any] = {
        "ok": True,
        "applied": bool(args.apply),
        "readiness": {
            "workbench_rows": readiness.get("workbench_rows"),
            "paper_pipeline": readiness.get("paper_pipeline"),
            "timer_check": readiness.get("timer_check"),
        },
        "state_before": flags_before,
        "dry_dispatch_before": dry_dispatch,
    }
    if not args.apply:
        report["next"] = "rerun with --apply to dispatch exactly one candidate, then re-pause"
        return report

    resumed = _require_200(
        "resume",
        _request(
            "POST",
            f"{base}/control/resume",
            token,
            {"resumed_by": "supabase-controlled-resume-drill", "maintenance_mode": False},
        ),
    )
    report["resume"] = resumed.get("flags") or resumed
    try:
        live_dispatch = _require_200(
            "live dispatch",
            _request(
                "POST",
                f"{base}/control/dispatch-next",
                token,
                {"dry_run": False, "requested_by": "supabase-controlled-resume-drill", "force_preflight": True},
                timeout=args.dispatch_timeout,
            ),
        )
        report["live_dispatch"] = live_dispatch
        if live_dispatch.get("action") != "live_dispatch":
            raise DrillError(f"expected exactly one live_dispatch, got {live_dispatch}")
        report["active_after_dispatch"] = _wait_for_active(base, token, timeout_seconds=args.active_wait_seconds)
        return report
    finally:
        if not args.leave_unpaused:
            paused = _request(
                "POST",
                f"{base}/control/pause",
                token,
                {
                    "reason": "Re-paused after one-dispatch Supabase controlled resume drill.",
                    "paused_by": "supabase-controlled-resume-drill",
                    "maintenance_mode": True,
                },
            )
            report["re_pause"] = paused[1] if paused[0] == 200 else {"status": paused[0], "body": paused[1]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--control-url", default=os.environ.get("ENOCH_CONTROL_PLANE_URL", "http://192.168.1.166:8787"))
    parser.add_argument("--token-file", default=os.environ.get("ENOCH_CONTROL_PLANE_TOKEN_FILE", "/root/enoch-control-plane-token.txt"))
    parser.add_argument("--ssh-host", default=os.environ.get("ENOCH_CONTROL_PLANE_SSH_HOST", ""))
    parser.add_argument("--apply", action="store_true", help="actually unpause and dispatch exactly one candidate")
    parser.add_argument("--leave-unpaused", action="store_true", help="do not automatically re-pause after the one dispatch")
    parser.add_argument("--dispatch-timeout", type=int, default=90)
    parser.add_argument("--active-wait-seconds", type=float, default=45.0)
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    try:
        result = drill(args)
    except Exception as exc:
        result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    text = json.dumps(result, indent=2, sort_keys=True)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
    print(text)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
