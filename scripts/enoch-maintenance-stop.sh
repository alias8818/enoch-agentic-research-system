#!/usr/bin/env bash
set -euo pipefail

CONFIG_PATH="${ENOCH_CONFIG:-${ENOCH_CONTROL_PLANE_CONFIG:-/etc/enoch-control-plane/config.json}}"
CONTROL_URL="${ENOCH_CONTROL_URL:-http://127.0.0.1:8787}"
CONTROL_TOKEN="${ENOCH_CONTROL_TOKEN:-}"
REQUESTED_BY="${ENOCH_MAINTENANCE_REQUESTED_BY:-operator:maintenance-stop}"
PAUSE_REASON="${ENOCH_MAINTENANCE_REASON:-operator maintenance hold}"

MAINTENANCE_TIMERS=(
  enoch-research-autopilot.timer
  enoch-corpus-import-autopilot.timer
  enoch-queue-alert-check.timer
  enoch-source-lineage-check.timer
  enoch-paper-draft-next.timer
)

MAINTENANCE_SERVICES=(
  enoch-research-autopilot.service
  enoch-corpus-import-autopilot.service
  enoch-queue-alert-check.service
  enoch-source-lineage-check.service
  enoch-paper-draft-next.service
)

WORKER_HOSTS=(
  ${ENOCH_MAINTENANCE_WORKER_HOSTS:-root@enoch-worker-cpu-1 jeremy@gx10-efe8}
)

if [[ -z "$CONTROL_TOKEN" && -r "$CONFIG_PATH" ]]; then
  CONTROL_TOKEN="$(python3 - "$CONFIG_PATH" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as fh:
    data=json.load(fh)
print(data.get("control_api_bearer_token") or data.get("omx_inbound_bearer_token") or "")
PY
)"
fi
if [[ -z "$CONTROL_TOKEN" ]]; then
  echo "missing control token; set ENOCH_CONTROL_TOKEN or ENOCH_CONFIG" >&2
  exit 2
fi

control_api() {
  local method="$1"
  local path="$2"
  local payload="${3:-}"
  if [[ "$method" == "GET" ]]; then
    curl -fsS \
      -H "Authorization: Bearer $CONTROL_TOKEN" \
      "$CONTROL_URL$path"
  else
    curl -fsS \
      -X "$method" \
      -H "Authorization: Bearer $CONTROL_TOKEN" \
      -H "Content-Type: application/json" \
      --data-binary "$payload" \
      "$CONTROL_URL$path"
  fi
}

pause_payload="$(python3 - "$PAUSE_REASON" "$REQUESTED_BY" <<'PY'
import json, sys
print(json.dumps({
    "reason": sys.argv[1],
    "paused_by": sys.argv[2],
    "maintenance_mode": True,
}))
PY
)"
pause_state="$(control_api POST /control/pause "$pause_payload")"

systemctl disable --now "${MAINTENANCE_TIMERS[@]}" "${MAINTENANCE_SERVICES[@]}" >/dev/null 2>&1 || true
systemctl reset-failed "${MAINTENANCE_SERVICES[@]}" >/dev/null 2>&1 || true

status_json="$(control_api GET /control/api/status)"
timer_enabled="$(systemctl is-enabled "${MAINTENANCE_TIMERS[@]}" 2>/dev/null || true)"
timer_active="$(systemctl is-active "${MAINTENANCE_TIMERS[@]}" 2>/dev/null || true)"
backup_timer_active="$(systemctl is-active enoch-postgres-backup.timer 2>/dev/null || true)"
backup_timer_enabled="$(systemctl is-enabled enoch-postgres-backup.timer 2>/dev/null || true)"

worker_checks_json="$(python3 - "${WORKER_HOSTS[@]}" <<'PY'
import json, os, subprocess, sys
checks = []
timeout_seconds = int(os.environ.get("ENOCH_MAINTENANCE_WORKER_SSH_TIMEOUT", "12"))
for host in sys.argv[1:]:
    cmd = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        "ConnectTimeout=8",
        host,
        "pgrep -af 'codex|enoch_codex_runner|enoch_codex_dispatch' || true",
    ]
    try:
        result = subprocess.run(
            cmd,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        checks.append({
            "host": host,
            "ok": False,
            "returncode": 124,
            "codex_processes": [],
            "stderr": f"worker ssh check timed out after {timeout_seconds}s",
            "stdout": (exc.stdout or "")[-500:],
        })
        continue
    lines = [
        line
        for line in result.stdout.splitlines()
        if "pgrep -af" not in line and "ssh " not in line
    ]
    checks.append({
        "host": host,
        "ok": result.returncode in {0, 1},
        "returncode": result.returncode,
        "codex_processes": lines,
        "stderr": result.stderr[-500:],
    })
print(json.dumps(checks, sort_keys=True))
PY
)"

python3 - "$pause_state" "$status_json" "$timer_enabled" "$timer_active" "$backup_timer_enabled" "$backup_timer_active" "$worker_checks_json" <<'PY'
import json, sys
pause_state = json.loads(sys.argv[1])
status = json.loads(sys.argv[2])
timer_enabled = [line for line in sys.argv[3].splitlines() if line]
timer_active = [line for line in sys.argv[4].splitlines() if line]
backup_timer_enabled = sys.argv[5].strip()
backup_timer_active = sys.argv[6].strip()
worker_checks = json.loads(sys.argv[7])
flags = status.get("flags") or {}
active_items = status.get("active_items") or []
failures = []
if not flags.get("queue_paused"):
    failures.append("queue_paused is not true")
if not flags.get("maintenance_mode"):
    failures.append("maintenance_mode is not true")
if active_items:
    failures.append(f"active rows remain: {len(active_items)}")
if any(value not in {"disabled", "masked", "not-found"} for value in timer_enabled):
    failures.append(f"maintenance timers not disabled: {timer_enabled}")
if any(value != "inactive" for value in timer_active):
    failures.append(f"maintenance timers not inactive: {timer_active}")
busy_workers = [item for item in worker_checks if item.get("codex_processes")]
if busy_workers:
    failures.append(f"worker Codex processes remain: {busy_workers}")
unreachable_workers = [item for item in worker_checks if not item.get("ok")]
if unreachable_workers:
    failures.append(f"worker process checks failed: {unreachable_workers}")
result = {
    "ok": not failures,
    "action": "maintenance_stop",
    "failures": failures,
    "pause_state": pause_state.get("flags") or pause_state,
    "status": {
        "queue_paused": bool(flags.get("queue_paused")),
        "maintenance_mode": bool(flags.get("maintenance_mode")),
        "active_count": len(active_items),
        "queued_count": int((status.get("counts") or {}).get("queued") or 0),
    },
    "maintenance_timers": {
        "enabled": timer_enabled,
        "active": timer_active,
    },
    "postgres_backup_timer": {
        "enabled": backup_timer_enabled,
        "active": backup_timer_active,
    },
    "worker_checks": worker_checks,
}
print(json.dumps(result, indent=2, sort_keys=True))
raise SystemExit(0 if result["ok"] else 1)
PY
