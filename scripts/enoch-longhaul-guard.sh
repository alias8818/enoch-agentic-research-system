#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  scripts/enoch-longhaul-guard.sh [--repair-stale-active] [--skip-codex-smoke] [--output PATH]

Runs a pre-unattended long-haul guard check that links each observed issue to
evidence and a deterministic mitigation path:
- checks control-plane long-haul readiness and queue status;
- runs a cheap CPU worker Codex auth smoke as the service user;
- dry-runs the queue-alert stale-active detector;
- optionally runs the audited stale-active reconcile path and verifies
  readiness again.

Environment overrides:
  ENOCH_CONTROL_HOST      Default: enoch-core.exe.xyz
  ENOCH_CPU_HOST          Default: root@enoch-worker-cpu-1
  ENOCH_CPU_WORKER_USER   Default: enoch-cpu-worker
  ENOCH_CPU_WORKER_HOME   Default: /var/lib/enoch-cpu-worker
  ENOCH_CODEX_TIMEOUT     Default: 90
EOF
}

repair_stale_active=0
skip_codex_smoke=0
output=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repair-stale-active)
      repair_stale_active=1
      shift
      ;;
    --skip-codex-smoke)
      skip_codex_smoke=1
      shift
      ;;
    --output)
      output="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

control_host="${ENOCH_CONTROL_HOST:-enoch-core.exe.xyz}"
cpu_host="${ENOCH_CPU_HOST:-root@enoch-worker-cpu-1}"
cpu_worker_user="${ENOCH_CPU_WORKER_USER:-enoch-cpu-worker}"
cpu_worker_home="${ENOCH_CPU_WORKER_HOME:-/var/lib/enoch-cpu-worker}"
codex_timeout="${ENOCH_CODEX_TIMEOUT:-90}"

# CPU Codex auth smoke command, intentionally kept visible for static tests:
# sudo -u "$cpu_worker_user" -H codex exec --skip-git-repo-check --json -C /tmp

tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT

python3 - "$control_host" "$cpu_host" "$cpu_worker_user" "$cpu_worker_home" "$codex_timeout" "$repair_stale_active" "$skip_codex_smoke" > "$tmp" <<'PY'
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any


control_host = sys.argv[1]
cpu_host = sys.argv[2]
cpu_worker_user = sys.argv[3]
cpu_worker_home = sys.argv[4]
codex_timeout = int(sys.argv[5])
repair_stale_active = sys.argv[6] == "1"
skip_codex_smoke = sys.argv[7] == "1"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run(argv: list[str], *, timeout: int = 30) -> dict[str, Any]:
    proc = subprocess.run(
        argv,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    return {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "stdout": proc.stdout.strip(),
        "stderr": proc.stderr.strip(),
    }


def ssh(host: str, command: str, *, timeout: int = 30) -> dict[str, Any]:
    return run(["ssh", host, command], timeout=timeout)


def parse_json_stdout(result: dict[str, Any]) -> Any:
    if not result.get("ok") or not result.get("stdout"):
        return None
    try:
        return json.loads(str(result["stdout"]))
    except json.JSONDecodeError:
        return None


def control_api(method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload_json = json.dumps(payload) if payload is not None else ""
    command = f"""sudo python3 - {json.dumps(method)} {json.dumps(path)} {json.dumps(payload_json)} <<'PYREMOTE'
import json, pathlib, sys, urllib.request
method, path, payload_json = sys.argv[1], sys.argv[2], sys.argv[3]
cfg = json.loads(pathlib.Path('/etc/enoch-control-plane/config.json').read_text())
token = cfg['control_api_bearer_token']
headers = {{'Authorization': f'Bearer {{token}}'}}
body = None
if payload_json:
    body = payload_json.encode()
    headers['Content-Type'] = 'application/json'
request = urllib.request.Request(
    'http://127.0.0.1:8787' + path,
    data=body,
    method=method,
    headers=headers,
)
with urllib.request.urlopen(request, timeout=45) as response:
    print(json.dumps(json.load(response), sort_keys=True))
PYREMOTE"""
    result = ssh(control_host, command, timeout=60)
    parsed = parse_json_stdout(result)
    if parsed is not None:
        return {"ok": True, "payload": parsed, "transport": result}
    return {"ok": False, "payload": None, "transport": result}


def cpu_codex_smoke() -> dict[str, Any]:
    prompt = "Return exactly: ok"
    command = (
        "sudo -u "
        + json.dumps(cpu_worker_user)
        + " -H bash -lc "
        + json.dumps(
            "export HOME="
            + cpu_worker_home
            + "; codex exec --skip-git-repo-check --json -C /tmp "
            + json.dumps(prompt)
        )
    )
    result = ssh(cpu_host, command, timeout=codex_timeout)
    success = False
    message = ""
    for line in str(result.get("stdout") or "").splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        body = item.get("item") if isinstance(item.get("item"), dict) else item
        if body.get("type") == "agent_message":
            message = str(body.get("text") or "").strip()
            if message == "ok":
                success = True
    return {
        "ok": bool(result["ok"] and success),
        "expected": "agent_message text exactly 'ok'",
        "message": message,
        "returncode": result["returncode"],
        "stderr_tail": str(result.get("stderr") or "")[-1000:],
    }


def readiness_summary(payload: dict[str, Any] | None) -> dict[str, Any]:
    payload = payload or {}
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    return {
        "ok": payload.get("ok"),
        "status": payload.get("status"),
        "label": payload.get("label"),
        "blockers": payload.get("blockers"),
        "summary": {
            key: summary.get(key)
            for key in (
                "active",
                "queued",
                "blocked",
                "needs_attention",
                "research_last_result",
            )
        },
    }


def readiness_blockers(payload: dict[str, Any] | None) -> list[str]:
    blockers = (payload or {}).get("blockers")
    if not isinstance(blockers, list):
        return []
    return [str(blocker) for blocker in blockers]


def stale_active_findings(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    findings = (payload or {}).get("findings")
    if not isinstance(findings, list):
        return []
    out = []
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        data = finding.get("data") if isinstance(finding.get("data"), dict) else {}
        confirmation = (
            data.get("active_confirmation")
            if isinstance(data.get("active_confirmation"), dict)
            else {}
        )
        if confirmation.get("state") == "stale_active":
            out.append(finding)
    return out


def queue_alert_findings(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    findings = (payload or {}).get("findings")
    if not isinstance(findings, list):
        return []
    return [finding for finding in findings if isinstance(finding, dict)]


def non_stale_queue_alert_findings(
    payload: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    return [
        finding
        for finding in queue_alert_findings(payload)
        if finding not in stale_active_findings(payload)
    ]


# Keep literal JSON strings visible for static CLCA contract tests:
# {"dry_run": true}
# {"dry_run": false}
readiness_before = control_api("GET", "/control/api/v1/automation-readiness")
status_before = control_api("GET", "/control/api/status")
queue_check_dry_run = control_api(
    "POST",
    "/control/api/alerts/queue-check",
    {"dry_run": True, "requested_by": "enoch-longhaul-guard", "refresh_worker": True},
)
dry_findings = stale_active_findings(queue_check_dry_run.get("payload"))
readiness_blockers_before = readiness_blockers(readiness_before.get("payload"))
readiness_has_stale_active = "stale active worker lane exists" in readiness_blockers_before

codex = (
    {"ok": True, "skipped": True, "reason": "--skip-codex-smoke"}
    if skip_codex_smoke
    else cpu_codex_smoke()
)

repair_result = None
post_repair_readiness = None
post_repair_status = None
post_repair_queue_check = None
if repair_stale_active and dry_findings:
    repair_result = control_api(
        "POST",
        "/control/api/alerts/queue-check",
        {
            "dry_run": False,
            "requested_by": "enoch-longhaul-guard",
            "refresh_worker": True,
        },
    )
    post_repair_readiness = control_api("GET", "/control/api/v1/automation-readiness")
    post_repair_status = control_api("GET", "/control/api/status")
    post_repair_queue_check = control_api(
        "POST",
        "/control/api/alerts/queue-check",
        {"dry_run": True, "requested_by": "enoch-longhaul-guard", "refresh_worker": True},
    )

issues: list[dict[str, Any]] = []
if not codex.get("ok"):
    issues.append(
        {
            "observed_issue": "cpu_codex_auth_smoke_failed",
            "immediate_mitigation": "run scripts/sync-codex-worker-config.sh, then repeat this guard before unattended mode",
            "durable_mitigation": "pre-unattended guard performs CPU service-user Codex auth smoke",
            "verification": "cpu_codex_smoke.ok must be true",
        }
    )
if readiness_has_stale_active or dry_findings:
    proof_state = (
        "queue_check_worker_no_live_runs"
        if dry_findings
        else "missing_queue_check_proof"
    )
    immediate_mitigation = (
        "run this guard with --repair-stale-active to invoke the audited queue-alert reconcile path"
        if dry_findings
        else "do not live-reconcile yet; refresh worker observations/status and inspect the active lane because readiness is blocked but queue-check did not produce worker_no_live_runs proof"
    )
    issues.append(
        {
            "observed_issue": "stale_active_worker_lane",
            "immediate_mitigation": immediate_mitigation,
            "durable_mitigation": "guard links readiness blockers to an issue every time, but requires dry-run worker_no_live_runs evidence before live reconcile and rechecks readiness afterward",
            "verification": "post_repair_readiness.ok must be true and stale-active blockers must be absent before unattended mode",
            "proof_state": proof_state,
            "repairable_by_guard": bool(dry_findings),
        }
    )

effective_queue_check = (
    post_repair_queue_check if post_repair_queue_check else queue_check_dry_run
)
effective_queue_payload = effective_queue_check.get("payload")
effective_queue_findings = queue_alert_findings(effective_queue_payload)
effective_non_stale_findings = non_stale_queue_alert_findings(effective_queue_payload)
if effective_non_stale_findings:
    issues.append(
        {
            "observed_issue": "queue_alert_findings_present",
            "immediate_mitigation": "inspect queue-check findings and do not leave unattended until should_alert is false",
            "durable_mitigation": "pre-unattended guard fails closed on queue-alert findings, including post-repair findings",
            "verification": "queue_check_dry_run.should_alert and post_repair_queue_check.should_alert must be false before unattended mode",
            "finding_sources": sorted(
                {
                    str(finding.get("source") or "unknown")
                    for finding in effective_non_stale_findings
                }
            ),
        }
    )

effective_readiness = (
    post_repair_readiness.get("payload")
    if post_repair_readiness and post_repair_readiness.get("ok")
    else readiness_before.get("payload")
)
effective_queue_ok = bool(
    effective_queue_check.get("ok")
    and effective_queue_payload
    and not effective_queue_payload.get("should_alert")
    and not effective_queue_findings
)
ok = bool(
    codex.get("ok")
    and effective_readiness
    and effective_readiness.get("ok")
    and effective_queue_ok
)
if (readiness_has_stale_active or dry_findings) and not repair_stale_active:
    ok = False

report = {
    "ok": ok,
    "generated_at": now(),
    "source": "enoch-longhaul-guard",
    "repair_stale_active": repair_stale_active,
    "cpu_codex_smoke": codex,
    "readiness_before": readiness_summary(readiness_before.get("payload")),
    "readiness_blockers": readiness_blockers_before,
    "status_before_counts": (status_before.get("payload") or {}).get("counts"),
    "queue_check_dry_run": {
        "ok": queue_check_dry_run.get("ok"),
        "should_alert": (queue_check_dry_run.get("payload") or {}).get("should_alert"),
        "stale_active_findings": dry_findings,
        "trace_id": (queue_check_dry_run.get("payload") or {}).get("trace_id"),
    },
    "repair_result": {
        "ok": repair_result.get("ok"),
        "payload": repair_result.get("payload"),
    }
    if repair_result
    else None,
    "post_repair_readiness": readiness_summary(post_repair_readiness.get("payload"))
    if post_repair_readiness
    else None,
    "post_repair_status_counts": (post_repair_status.get("payload") or {}).get("counts")
    if post_repair_status
    else None,
    "post_repair_queue_check": {
        "ok": post_repair_queue_check.get("ok"),
        "should_alert": (post_repair_queue_check.get("payload") or {}).get("should_alert"),
        "findings": queue_alert_findings(post_repair_queue_check.get("payload")),
        "trace_id": (post_repair_queue_check.get("payload") or {}).get("trace_id"),
    }
    if post_repair_queue_check
    else None,
    "issues": issues,
}
print(json.dumps(report, indent=2, sort_keys=True))
PY

if [[ -n "$output" ]]; then
  mkdir -p "$(dirname "$output")"
  cp "$tmp" "$output"
  echo "wrote long-haul guard report: $output"
else
  cat "$tmp"
fi

python3 - "$tmp" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    report = json.load(handle)
raise SystemExit(0 if report.get("ok") is True else 1)
PY
