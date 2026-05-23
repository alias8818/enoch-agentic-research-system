#!/usr/bin/env python3
"""Validate that the live Enoch control plane is safe to resume after Supabase cutover.

This is an operator-safe live smoke: it requires the control plane to be using
Supabase, keeps pause/maintenance asserted, verifies legacy Notion APIs are gone,
and exercises only dry-run/no-side-effect write surfaces.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass
class HttpResult:
    status: int
    body: Any


def _load_token(path: str) -> str:
    explicit = os.environ.get("ENOCH_CONTROL_PLANE_TOKEN", "").strip()
    if explicit:
        return explicit
    try:
        return open(path, encoding="utf-8").read().strip()
    except OSError:
        return ""


def _request(
    method: str, url: str, token: str, payload: dict[str, Any] | None = None
) -> HttpResult:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Accept", "application/json")
    if body is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=20) as response:  # noqa: S310 - operator-provided LAN URL
            text = response.read().decode("utf-8")
            return HttpResult(response.status, json.loads(text) if text else {})
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8")
        try:
            body_obj: Any = json.loads(text) if text else {}
        except json.JSONDecodeError:
            body_obj = {"raw": text}
        return HttpResult(exc.code, body_obj)


def _check_status(
    failures: list[str], result: HttpResult, expected: int, label: str
) -> None:
    if result.status != expected:
        failures.append(
            f"{label} returned HTTP {result.status}, expected {expected}: {result.body}"
        )


def _run_ssh_timer_check(ssh_host: str) -> dict[str, Any]:
    cmd = [
        "ssh",
        ssh_host,
        "systemctl is-enabled enoch-notion-sync.timer enoch-notion-sync.service enoch-paper-draft-next.timer enoch-queue-alert-check.timer 2>/dev/null || true; "
        "echo --active--; "
        "systemctl is-active enoch-notion-sync.timer enoch-notion-sync.service enoch-paper-draft-next.timer enoch-queue-alert-check.timer 2>/dev/null || true",
    ]
    completed = subprocess.run(
        cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False
    )
    lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    marker = lines.index("--active--") if "--active--" in lines else len(lines)
    return {
        "returncode": completed.returncode,
        "enabled": lines[:marker],
        "active": lines[marker + 1 :],
        "raw": completed.stdout,
    }


def validate(args: argparse.Namespace) -> dict[str, Any]:
    failures: list[str] = []
    token = _load_token(args.token_file)
    if not token:
        return {
            "ok": False,
            "failures": [
                "missing control-plane token; set ENOCH_CONTROL_PLANE_TOKEN or --token-file"
            ],
        }
    base = args.control_url.rstrip("/")

    health = _request("GET", f"{base}/control/health", token)
    state = _request("GET", f"{base}/control/state", token)
    overview = _request("GET", f"{base}/control/api/v1/overview", token)
    core_health = _request("GET", f"{base}/enoch-core/health", token)
    ideas = _request("GET", f"{base}/control/api/intake/ideas", token)
    workbench = _request("GET", f"{base}/control/projections/ideas/workbench", token)
    legacy_intake = _request("GET", f"{base}/control/api/intake/notion", token)
    legacy_projection = _request(
        "GET", f"{base}/control/projections/notion/queue", token
    )
    dispatch_dry = _request(
        "POST",
        f"{base}/control/dispatch-next",
        token,
        {"dry_run": True, "requested_by": "supabase-resume-readiness"},
    )
    idea_dry = _request(
        "POST",
        f"{base}/control/intake/ideas",
        token,
        {
            "dry_run": True,
            "ideas": [
                {
                    "idea_id": "resume-readiness-smoke",
                    "title": "Resume Readiness Smoke",
                    "idea_status": "testing",
                }
            ],
        },
    )
    review_backfill_dry = _request(
        "POST",
        f"{base}/control/api/publication-automation/backfill",
        token,
        {
            "dry_run": True,
            "requested_by": "supabase-resume-readiness",
            "paper_ids": ["__resume_readiness_noop__"],
        },
    )

    for label, result in (
        ("health", health),
        ("state", state),
        ("overview", overview),
        ("enoch-core health", core_health),
        ("ideas intake dashboard", ideas),
        ("ideas workbench", workbench),
        ("dispatch dry-run", dispatch_dry),
        ("ideas dry-run", idea_dry),
        ("publication automation backfill dry-run", review_backfill_dry),
    ):
        _check_status(failures, result, 200, label)
    _check_status(failures, legacy_intake, 410, "legacy Notion intake")
    _check_status(failures, legacy_projection, 410, "legacy Notion projection")

    if health.status == 200 and health.body.get("store_backend") != "supabase":
        failures.append(
            f"health store_backend={health.body.get('store_backend')!r}, expected 'supabase'"
        )
    if (
        core_health.status == 200
        and core_health.body.get("store_backend") != "supabase"
    ):
        failures.append(
            f"enoch-core store_backend={core_health.body.get('store_backend')!r}, expected 'supabase'"
        )
    flags = state.body.get("flags") if isinstance(state.body, dict) else {}
    if not flags.get("queue_paused") or not flags.get("maintenance_mode"):
        failures.append(f"runtime is not safely paused for migration: flags={flags}")
    pipeline = (
        (overview.body.get("paper_pipeline") or {})
        if isinstance(overview.body, dict)
        else {}
    )
    if int(pipeline.get("write_needed") or 0) != 0:
        failures.append(
            f"write_needed={pipeline.get('write_needed')}, expected 0 before resume"
        )
    if int(pipeline.get("raw_completed_no_paper_candidates") or 0) != int(
        pipeline.get("not_writable_by_decision_gate") or 0
    ):
        failures.append(
            "raw completed/no-paper candidates do not match decision-gated non-writable count: "
            f"raw={pipeline.get('raw_completed_no_paper_candidates')} gated={pipeline.get('not_writable_by_decision_gate')}"
        )
    if ideas.status == 200 and "Supabase-native" not in str(
        ideas.body.get("authority", "")
    ):
        failures.append(
            f"ideas authority does not identify Supabase-native source: {ideas.body.get('authority')!r}"
        )
    if workbench.status == 200 and not workbench.body.get("rows"):
        failures.append("ideas workbench returned no rows")
    if dispatch_dry.status == 200 and dispatch_dry.body.get("action") != "paused":
        failures.append(
            f"dispatch dry-run action={dispatch_dry.body.get('action')!r}, expected paused while migration pause is active"
        )
    if dispatch_dry.status == 200 and dispatch_dry.body.get("event_id") is not None:
        failures.append(
            f"dispatch dry-run recorded an event_id={dispatch_dry.body.get('event_id')}; dry-runs must be side-effect-free"
        )
    if idea_dry.status == 200 and (
        not idea_dry.body.get("dry_run")
        or idea_dry.body.get("created") not in (0, None)
    ):
        failures.append(f"ideas dry-run was not side-effect-free: {idea_dry.body}")
    if review_backfill_dry.status == 200 and not review_backfill_dry.body.get(
        "dry_run"
    ):
        failures.append(
            f"publication automation backfill did not remain dry-run: {review_backfill_dry.body}"
        )

    timer_check: dict[str, Any] | None = None
    if args.ssh_host:
        timer_check = _run_ssh_timer_check(args.ssh_host)
        if timer_check["returncode"] != 0:
            failures.append(f"timer ssh check failed: {timer_check['raw']}")
        enabled = timer_check.get("enabled") or []
        active = timer_check.get("active") or []
        if enabled[:2] != ["masked", "masked"]:
            failures.append(f"Notion sync units are not masked: enabled={enabled}")
        if enabled[2:] != ["disabled", "disabled"]:
            failures.append(f"paper/queue timers are not disabled: enabled={enabled}")
        if active != ["inactive", "inactive", "inactive", "inactive"]:
            failures.append(f"migration-sensitive timers are active: active={active}")

    return {
        "ok": not failures,
        "failures": failures,
        "health": {"status": health.status, "body": health.body},
        "state_flags": flags,
        "paper_pipeline": pipeline,
        "enoch_core": {
            "status": core_health.status,
            "store_backend": core_health.body.get("store_backend")
            if isinstance(core_health.body, dict)
            else "",
            "db_path": core_health.body.get("db_path")
            if isinstance(core_health.body, dict)
            else "",
        },
        "ideas": {
            "status": ideas.status,
            "authority": ideas.body.get("authority")
            if isinstance(ideas.body, dict)
            else "",
        },
        "workbench_rows": len(workbench.body.get("rows") or [])
        if isinstance(workbench.body, dict)
        else 0,
        "legacy": {
            "intake_status": legacy_intake.status,
            "projection_status": legacy_projection.status,
        },
        "dry_runs": {
            "dispatch": dispatch_dry.body,
            "ideas_created": idea_dry.body.get("created")
            if isinstance(idea_dry.body, dict)
            else None,
            "publication_automation_backfill": review_backfill_dry.body,
        },
        "timer_check": timer_check,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--control-url",
        default=os.environ.get("ENOCH_CONTROL_PLANE_URL", "http://192.168.1.166:8787"),
    )
    parser.add_argument(
        "--token-file",
        default=os.environ.get(
            "ENOCH_CONTROL_PLANE_TOKEN_FILE", "/root/enoch-control-plane-token.txt"
        ),
    )
    parser.add_argument(
        "--ssh-host",
        default=os.environ.get("ENOCH_CONTROL_PLANE_SSH_HOST", ""),
        help="optional host for systemd timer checks, e.g. root@192.168.1.166",
    )
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    result = validate(args)
    text = json.dumps(result, indent=2, sort_keys=True)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
    print(text)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
