#!/usr/bin/env bash
set -euo pipefail

CONFIG_PATH="${ENOCH_CONFIG:-${ENOCH_CONTROL_PLANE_CONFIG:-/etc/enoch-control-plane/config.json}}"
CONTROL_URL="${ENOCH_CONTROL_URL:-http://127.0.0.1:8787}"
CONTROL_TOKEN="${ENOCH_CONTROL_TOKEN:-}"
REQUESTED_BY="${ENOCH_MAINTENANCE_REQUESTED_BY:-operator:maintenance-resume}"
CONFIRM="${ENOCH_MAINTENANCE_RESUME_CONFIRM:-}"

if [[ "${1:-}" == "--confirm" ]]; then
  CONFIRM="resume-enoch-automation"
fi
if [[ "$CONFIRM" != "resume-enoch-automation" ]]; then
  echo '{"ok":false,"action":"maintenance_resume_blocked","reason":"pass --confirm or set ENOCH_MAINTENANCE_RESUME_CONFIRM=resume-enoch-automation"}'
  exit 2
fi

MAINTENANCE_TIMERS=(
  enoch-research-autopilot.timer
  enoch-corpus-import-autopilot.timer
  enoch-queue-alert-check.timer
  enoch-source-lineage-check.timer
)

OPTIONAL_TIMERS=(
  enoch-paper-draft-next.timer
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
CONTROL_CURL_CONFIG="$(mktemp)"
chmod 600 "$CONTROL_CURL_CONFIG"
trap 'rm -f "$CONTROL_CURL_CONFIG"' EXIT
python3 - "$CONTROL_TOKEN" "$CONTROL_CURL_CONFIG" <<'PY'
import sys
token, path = sys.argv[1], sys.argv[2]
escaped = token.replace("\\", "\\\\").replace('"', '\\"')
with open(path, "w", encoding="utf-8") as fh:
    fh.write(f'header = "Authorization: Bearer {escaped}"\n')
    fh.write('header = "Content-Type: application/json"\n')
PY

control_api() {
  local method="$1"
  local path="$2"
  local payload="${3:-}"
  if [[ "$method" == "GET" ]]; then
    curl -fsS \
      --config "$CONTROL_CURL_CONFIG" \
      --url "$CONTROL_URL$path"
  else
    curl -fsS \
      -X "$method" \
      --config "$CONTROL_CURL_CONFIG" \
      --data-binary "$payload" \
      --url "$CONTROL_URL$path"
  fi
}

before_status="$(control_api GET /control/api/status)"
python3 - "$before_status" <<'PY'
import json, sys
status = json.loads(sys.argv[1])
active = status.get("active_items") or []
if active:
    print(json.dumps({
        "ok": False,
        "action": "maintenance_resume_blocked",
        "reason": f"active rows remain: {len(active)}",
        "active": active[:10],
    }, sort_keys=True))
    raise SystemExit(1)
PY

resume_payload="$(python3 - "$REQUESTED_BY" <<'PY'
import json, sys
print(json.dumps({"resumed_by": sys.argv[1], "maintenance_mode": False}))
PY
)"
resume_state="$(control_api POST /control/resume "$resume_payload")"

systemctl enable --now "${MAINTENANCE_TIMERS[@]}" >/dev/null 2>&1 || true
if [[ "${ENOCH_MAINTENANCE_RESUME_ENABLE_PAPER_DRAFT:-0}" == "1" ]]; then
  systemctl enable --now "${OPTIONAL_TIMERS[@]}" >/dev/null 2>&1 || true
fi

status_json="$(control_api GET /control/api/status)"
timer_enabled="$(systemctl is-enabled "${MAINTENANCE_TIMERS[@]}" 2>/dev/null || true)"
timer_active="$(systemctl is-active "${MAINTENANCE_TIMERS[@]}" 2>/dev/null || true)"
paper_timer_enabled="$(systemctl is-enabled "${OPTIONAL_TIMERS[@]}" 2>/dev/null || true)"
paper_timer_active="$(systemctl is-active "${OPTIONAL_TIMERS[@]}" 2>/dev/null || true)"
backup_timer_active="$(systemctl is-active enoch-postgres-backup.timer 2>/dev/null || true)"
backup_timer_enabled="$(systemctl is-enabled enoch-postgres-backup.timer 2>/dev/null || true)"

python3 - "$resume_state" "$status_json" "$timer_enabled" "$timer_active" "$paper_timer_enabled" "$paper_timer_active" "$backup_timer_enabled" "$backup_timer_active" <<'PY'
import json, sys
resume_state = json.loads(sys.argv[1])
status = json.loads(sys.argv[2])
timer_enabled = [line for line in sys.argv[3].splitlines() if line]
timer_active = [line for line in sys.argv[4].splitlines() if line]
paper_timer_enabled = [line for line in sys.argv[5].splitlines() if line]
paper_timer_active = [line for line in sys.argv[6].splitlines() if line]
backup_timer_enabled = sys.argv[7].strip()
backup_timer_active = sys.argv[8].strip()
flags = status.get("flags") or {}
failures = []
if flags.get("queue_paused"):
    failures.append("queue_paused is still true")
if flags.get("maintenance_mode"):
    failures.append("maintenance_mode is still true")
if any(value != "enabled" for value in timer_enabled):
    failures.append(f"maintenance timers not enabled: {timer_enabled}")
if any(value != "active" for value in timer_active):
    failures.append(f"maintenance timers not active: {timer_active}")
result = {
    "ok": not failures,
    "action": "maintenance_resume",
    "failures": failures,
    "resume_state": resume_state.get("flags") or resume_state,
    "status": {
        "queue_paused": bool(flags.get("queue_paused")),
        "maintenance_mode": bool(flags.get("maintenance_mode")),
        "active_count": len(status.get("active_items") or []),
        "queued_count": int((status.get("counts") or {}).get("queued") or 0),
    },
    "maintenance_timers": {
        "enabled": timer_enabled,
        "active": timer_active,
    },
    "paper_draft_timer": {
        "enabled": paper_timer_enabled,
        "active": paper_timer_active,
    },
    "postgres_backup_timer": {
        "enabled": backup_timer_enabled,
        "active": backup_timer_active,
    },
}
print(json.dumps(result, indent=2, sort_keys=True))
raise SystemExit(0 if result["ok"] else 1)
PY
