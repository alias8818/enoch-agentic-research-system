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

from enoch_control_plane.url_safety import secure_default_service_url
from enoch_control_plane.url_safety import urlopen_validated

# Documented on-prem control-plane host for the research-facility LAN.
LAB_CONTROL_PLANE_HOST = "192.168.1.166"  # NOSONAR python:S1313
DEFAULT_CONTROL_PLANE_URL = secure_default_service_url(LAB_CONTROL_PLANE_HOST, 8787)


@dataclass
class HttpResult:
    status: int
    body: Any


@dataclass
class ValidationResponses:
    health: HttpResult
    state: HttpResult
    overview: HttpResult
    core_health: HttpResult
    ideas: HttpResult
    workbench: HttpResult
    legacy_intake: HttpResult
    legacy_projection: HttpResult
    dispatch_dry: HttpResult
    idea_dry: HttpResult
    review_backfill_dry: HttpResult


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
        with urlopen_validated(
            req,
            timeout=20,
            field_name="scripts/validate_supabase_resume_readiness.py url",
            allow_private=True,
        ) as response:
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
    # Keep the SSH surface non-interactive and host-key pinned.  The remote side
    # is a root-owned helper script installed with the deployment, not an inline
    # shell snippet assembled by this local script.
    remote_script = "/opt/enoch/scripts/timer_check.sh"
    cmd = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        "UserKnownHostsFile=/etc/enoch/known_hosts",
        ssh_host,
        remote_script,
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


def _fetch_validation_responses(base: str, token: str) -> ValidationResponses:
    return ValidationResponses(
        health=_request("GET", f"{base}/control/health", token),
        state=_request("GET", f"{base}/control/state", token),
        overview=_request("GET", f"{base}/control/api/v1/overview", token),
        core_health=_request("GET", f"{base}/enoch-core/health", token),
        ideas=_request("GET", f"{base}/control/api/intake/ideas", token),
        workbench=_request("GET", f"{base}/control/projections/ideas/workbench", token),
        legacy_intake=_request("GET", f"{base}/control/api/intake/notion", token),
        legacy_projection=_request(
            "GET", f"{base}/control/projections/notion/queue", token
        ),
        dispatch_dry=_request(
            "POST",
            f"{base}/control/dispatch-next",
            token,
            {"dry_run": True, "requested_by": "supabase-resume-readiness"},
        ),
        idea_dry=_request(
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
        ),
        review_backfill_dry=_request(
            "POST",
            f"{base}/control/api/publication-automation/backfill",
            token,
            {
                "dry_run": True,
                "requested_by": "supabase-resume-readiness",
                "paper_ids": ["__resume_readiness_noop__"],
            },
        ),
    )


def _check_http_statuses(failures: list[str], responses: ValidationResponses) -> None:
    for label, result in (
        ("health", responses.health),
        ("state", responses.state),
        ("overview", responses.overview),
        ("enoch-core health", responses.core_health),
        ("ideas intake dashboard", responses.ideas),
        ("ideas workbench", responses.workbench),
        ("dispatch dry-run", responses.dispatch_dry),
        ("ideas dry-run", responses.idea_dry),
        (
            "publication automation backfill dry-run",
            responses.review_backfill_dry,
        ),
    ):
        _check_status(failures, result, 200, label)
    _check_status(failures, responses.legacy_intake, 410, "legacy Notion intake")
    _check_status(
        failures, responses.legacy_projection, 410, "legacy Notion projection"
    )


def _check_store_backends(
    failures: list[str], health: HttpResult, core_health: HttpResult
) -> None:
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


def _extract_state_flags(state: HttpResult) -> dict[str, Any]:
    return state.body.get("flags") if isinstance(state.body, dict) else {}


def _check_runtime_pause(failures: list[str], flags: dict[str, Any]) -> None:
    if not flags.get("queue_paused") or not flags.get("maintenance_mode"):
        failures.append(f"runtime is not safely paused for migration: flags={flags}")


def _extract_pipeline(overview: HttpResult) -> dict[str, Any]:
    if not isinstance(overview.body, dict):
        return {}
    return overview.body.get("paper_pipeline") or {}


def _check_pipeline_invariants(failures: list[str], pipeline: dict[str, Any]) -> None:
    if int(pipeline.get("write_needed") or 0) != 0:
        failures.append(
            f"write_needed={pipeline.get('write_needed')}, expected 0 before resume"
        )
    raw_count = int(pipeline.get("raw_completed_no_paper_candidates") or 0)
    gated_count = int(pipeline.get("not_writable_by_decision_gate") or 0)
    if raw_count != gated_count:
        failures.append(
            "raw completed/no-paper candidates do not match decision-gated non-writable count: "
            f"raw={pipeline.get('raw_completed_no_paper_candidates')} gated={pipeline.get('not_writable_by_decision_gate')}"
        )


def _check_ideas_surface(
    failures: list[str], ideas: HttpResult, workbench: HttpResult
) -> None:
    if ideas.status == 200 and "Supabase-native" not in str(
        ideas.body.get("authority", "")
    ):
        failures.append(
            f"ideas authority does not identify Supabase-native source: {ideas.body.get('authority')!r}"
        )
    if workbench.status == 200 and not workbench.body.get("rows"):
        failures.append("ideas workbench returned no rows")


def _check_dry_run_surface(
    failures: list[str],
    dispatch_dry: HttpResult,
    idea_dry: HttpResult,
    review_backfill_dry: HttpResult,
) -> None:
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


def _check_ssh_timers(failures: list[str], ssh_host: str) -> dict[str, Any] | None:
    if not ssh_host:
        return None
    timer_check = _run_ssh_timer_check(ssh_host)
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
    return timer_check


def _build_validation_report(
    failures: list[str],
    responses: ValidationResponses,
    flags: dict[str, Any],
    pipeline: dict[str, Any],
    timer_check: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "ok": not failures,
        "failures": failures,
        "health": {"status": responses.health.status, "body": responses.health.body},
        "state_flags": flags,
        "paper_pipeline": pipeline,
        "enoch_core": {
            "status": responses.core_health.status,
            "store_backend": responses.core_health.body.get("store_backend")
            if isinstance(responses.core_health.body, dict)
            else "",
            "db_path": responses.core_health.body.get("db_path")
            if isinstance(responses.core_health.body, dict)
            else "",
        },
        "ideas": {
            "status": responses.ideas.status,
            "authority": responses.ideas.body.get("authority")
            if isinstance(responses.ideas.body, dict)
            else "",
        },
        "workbench_rows": len(responses.workbench.body.get("rows") or [])
        if isinstance(responses.workbench.body, dict)
        else 0,
        "legacy": {
            "intake_status": responses.legacy_intake.status,
            "projection_status": responses.legacy_projection.status,
        },
        "dry_runs": {
            "dispatch": responses.dispatch_dry.body,
            "ideas_created": responses.idea_dry.body.get("created")
            if isinstance(responses.idea_dry.body, dict)
            else None,
            "publication_automation_backfill": responses.review_backfill_dry.body,
        },
        "timer_check": timer_check,
    }


def validate(args: argparse.Namespace) -> dict[str, Any]:
    token = _load_token(args.token_file)
    if not token:
        return {
            "ok": False,
            "failures": [
                "missing control-plane token; set ENOCH_CONTROL_PLANE_TOKEN or --token-file"
            ],
        }

    failures: list[str] = []
    responses = _fetch_validation_responses(args.control_url.rstrip("/"), token)
    _check_http_statuses(failures, responses)
    _check_store_backends(failures, responses.health, responses.core_health)
    flags = _extract_state_flags(responses.state)
    _check_runtime_pause(failures, flags)
    pipeline = _extract_pipeline(responses.overview)
    _check_pipeline_invariants(failures, pipeline)
    _check_ideas_surface(failures, responses.ideas, responses.workbench)
    _check_dry_run_surface(
        failures,
        responses.dispatch_dry,
        responses.idea_dry,
        responses.review_backfill_dry,
    )
    timer_check = _check_ssh_timers(failures, args.ssh_host)
    return _build_validation_report(failures, responses, flags, pipeline, timer_check)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--control-url",
        default=os.environ.get("ENOCH_CONTROL_URL")
        or os.environ.get("ENOCH_CONTROL_PLANE_URL")
        or DEFAULT_CONTROL_PLANE_URL,
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
        help="optional host for systemd timer checks, e.g. root@control-plane-host",
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
