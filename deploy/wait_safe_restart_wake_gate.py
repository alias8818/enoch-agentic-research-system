#!/usr/bin/env python3
"""Wait for a safe wake-gate restart window, then restart the user service.

This intentionally restarts only ``enoch-worker-gate.service``. It does not reboot
the host. Safe means the dashboard truth sources show no live gate work and the
process table has no project-owned Codex execution still running.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


ACTIVE_QUEUE_STATUSES = {"dispatching", "awaiting_wake", "running"}
LIVE_LIFECYCLES = {
    "active",
    "settling",
    "question_pending",
    "callback_pending",
    "stale_callback_ready",
}
PROJECT_PROCESS_MARKERS = ("/projects/idea-", "codex exec")


def load_token(config_path: Path) -> str:
    data = json.loads(config_path.expanduser().read_text(encoding="utf-8"))
    token = str(data.get("control_api_bearer_token") or "").strip()
    if not token:
        raise SystemExit(f"missing control_api_bearer_token in {config_path}")
    return token


def fetch_dashboard(api_url: str, token: str, timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(
        api_url, headers={"Authorization": f"Bearer {token}"}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = json.load(response)
    if not isinstance(data, dict):
        raise RuntimeError("dashboard API returned non-object JSON")
    return data


def project_exec_processes(project_root: str) -> list[str]:
    result = subprocess.run(
        ["ps", "-eo", "pid=,ppid=,stat=,etime=,args="],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "ps failed")

    matches: list[str] = []
    for line in result.stdout.splitlines():
        if "wait_safe_restart_wake_gate.py" in line:
            continue
        if project_root and project_root in line and "codex exec" in line:
            matches.append(line.strip())
            continue
        if all(marker in line for marker in PROJECT_PROCESS_MARKERS):
            matches.append(line.strip())
    return matches


def _check_live_totals(totals: dict[str, Any], reasons: list[str]) -> None:
    """Extracted checker for live gate count (part of C901 reduction for safe_report)."""
    live = int(totals.get("live") or totals.get("active_or_waiting") or 0)
    if live:
        reasons.append(f"live gate runs={live}")


def _check_active_queue(queue: dict[str, Any], reasons: list[str]) -> None:
    """Extracted checker for active queue rows and status counts (C901 reduction)."""
    status_counts = (
        queue.get("status_counts")
        if isinstance(queue.get("status_counts"), dict)
        else {}
    )
    active_rows = (
        queue.get("active_rows") if isinstance(queue.get("active_rows"), list) else []
    )
    if active_rows:
        labels = [
            f"{row.get('project_name') or row.get('project_id') or 'unknown'}:{row.get('queue_status') or 'unknown'}"
            for row in active_rows[:5]
            if isinstance(row, dict)
        ]
        reasons.append(f"queue active_rows={len(active_rows)} ({', '.join(labels)})")
    active_status_total = sum(
        int(status_counts.get(status) or 0) for status in ACTIVE_QUEUE_STATUSES
    )
    if active_status_total:
        reasons.append(f"active queue status count={active_status_total}")


def _check_live_runs(runs: list[dict[str, Any]], reasons: list[str]) -> None:
    """Extracted checker for live lifecycle runs (C901 reduction for safe_report)."""
    live_runs = [
        run
        for run in runs
        if isinstance(run, dict)
        and str(run.get("lifecycle_state") or "") in LIVE_LIFECYCLES
    ]
    if live_runs:
        labels = [
            f"{run.get('project_name') or run.get('project_id') or run.get('run_id')}:{run.get('lifecycle_state')}"
            for run in live_runs[:5]
        ]
        reasons.append(f"live run rows={len(live_runs)} ({', '.join(labels)})")


def safe_report(
    data: dict[str, Any], project_processes: list[str]
) -> tuple[bool, list[str]]:
    """Return (is_safe, reasons) after checking dashboard snapshot + process table.

    Refactored with three small pure checkers to reduce cognitive complexity from 17
    to well under the 15 threshold (AGENTS.md + Sonar S3776).
    """
    reasons: list[str] = []
    totals = data.get("totals") if isinstance(data.get("totals"), dict) else {}
    queue = data.get("queue") if isinstance(data.get("queue"), dict) else {}
    runs = data.get("runs") if isinstance(data.get("runs"), list) else []

    _check_live_totals(totals, reasons)
    _check_active_queue(queue, reasons)
    _check_live_runs(runs, reasons)

    if project_processes:
        reasons.append(f"project Codex processes={len(project_processes)}")

    return not reasons, reasons


def restart_service(service: str, verify_url: str, token: str, timeout: float) -> None:
    subprocess.run(["systemctl", "--user", "restart", service], check=True)
    deadline = time.monotonic() + timeout
    last_error = ""
    while time.monotonic() < deadline:
        active = subprocess.run(
            ["systemctl", "--user", "is-active", service],
            capture_output=True,
            text=True,
            check=False,
        )
        try:
            fetch_dashboard(verify_url, token, timeout=5)
            if active.stdout.strip() == "active":
                return
            last_error = (
                f"service state={active.stdout.strip() or active.stderr.strip()}"
            )
        except (OSError, urllib.error.URLError, TimeoutError, RuntimeError) as exc:
            last_error = str(exc)
        time.sleep(2)
    raise RuntimeError(
        f"{service} did not verify healthy within {timeout:.0f}s: {last_error}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        default="~/enoch/config/enoch-worker-gate.json",
        help="wake-gate config path containing control_api_bearer_token",
    )
    parser.add_argument(
        "--api-url",
        default="http://127.0.0.1:8787/dashboard/api?limit=20&event_limit=5",
    )
    parser.add_argument("--project-root", default="~/enoch/projects")
    parser.add_argument("--service", default="enoch-worker-gate.service")
    parser.add_argument("--interval-sec", type=float, default=30)
    parser.add_argument("--request-timeout-sec", type=float, default=8)
    parser.add_argument("--verify-timeout-sec", type=float, default=60)
    parser.add_argument(
        "--max-wait-sec", type=float, default=0, help="0 means wait forever"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="exit 0 when safe instead of restarting"
    )
    args = parser.parse_args()

    token = load_token(Path(args.config))
    started = time.monotonic()
    attempt = 0
    while True:
        attempt += 1
        try:
            data = fetch_dashboard(args.api_url, token, args.request_timeout_sec)
            processes = project_exec_processes(
                str(Path(args.project_root).expanduser())
            )
            safe, reasons = safe_report(data, processes)
        except Exception as exc:
            safe = False
            reasons = [f"probe failed: {type(exc).__name__}: {exc}"]

        stamp = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        if safe:
            print(
                f"{stamp} safe restart window reached after {attempt} probes",
                flush=True,
            )
            if args.dry_run:
                print(
                    f"{stamp} dry-run enabled; not restarting {args.service}",
                    flush=True,
                )
                return 0
            restart_service(args.service, args.api_url, token, args.verify_timeout_sec)
            print(f"{stamp} restarted and verified {args.service}", flush=True)
            return 0

        print(f"{stamp} not safe: {'; '.join(reasons)}", flush=True)
        if args.max_wait_sec and time.monotonic() - started >= args.max_wait_sec:
            print(
                f"{stamp} max wait exceeded; {args.service} was not restarted",
                file=sys.stderr,
                flush=True,
            )
            return 2
        time.sleep(max(1.0, args.interval_sec))


if __name__ == "__main__":
    raise SystemExit(main())
