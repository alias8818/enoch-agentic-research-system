#!/usr/bin/env bash
set -euo pipefail
CONFIG_PATH="${OMX_WAKE_GATE_CONFIG:-/etc/enoch/config.json}"
ENV_PATH="${ENOCH_NOTION_SYNC_ENV:-/etc/enoch/notion-sync.env}"
if [[ -f "$ENV_PATH" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_PATH"
  set +a
fi
CONTROL_URL="${ENOCH_CONTROL_URL:-http://127.0.0.1:8787}"
CONTROL_TOKEN="${ENOCH_CONTROL_TOKEN:-}"
if [[ -z "$CONTROL_TOKEN" && -r "$CONFIG_PATH" ]]; then
  CONTROL_TOKEN="$(python3 - "$CONFIG_PATH" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as fh:
    print(json.load(fh).get("omx_inbound_bearer_token", ""))
PY
)"
fi
NOTION_AUTH="${NOTION_TOKEN:-${NOTION_API_KEY:-}}"
if [[ -z "$CONTROL_TOKEN" || -z "$NOTION_AUTH" || ( -z "${NOTION_DATABASE_ID:-}" && -z "${NOTION_DATA_SOURCE_ID:-}" ) ]]; then
  control_token_configured=false
  notion_token_configured=false
  notion_database_configured=false
  [[ -n "$CONTROL_TOKEN" ]] && control_token_configured=true
  [[ -n "$NOTION_AUTH" ]] && notion_token_configured=true
  [[ -n "${NOTION_DATABASE_ID:-}" || -n "${NOTION_DATA_SOURCE_ID:-}" ]] && notion_database_configured=true
  result="$(CONTROL_TOKEN_CONFIGURED="$control_token_configured" NOTION_TOKEN_CONFIGURED="$notion_token_configured" NOTION_DATABASE_CONFIGURED="$notion_database_configured" python3 - <<'PY'
import json, os
print(json.dumps({
  "ok": True,
  "action": "skipped",
  "reason": "missing required Notion sync credentials",
  "required_env": ["NOTION_TOKEN or NOTION_API_KEY", "NOTION_DATABASE_ID or NOTION_DATA_SOURCE_ID"],
  "control_token_configured": os.environ.get("CONTROL_TOKEN_CONFIGURED") == "true",
  "notion_token_configured": os.environ.get("NOTION_TOKEN_CONFIGURED") == "true",
  "notion_database_configured": os.environ.get("NOTION_DATABASE_CONFIGURED") == "true",
}, sort_keys=True))
PY
)"
  echo "$result"
  if [[ -n "$CONTROL_TOKEN" ]]; then
    observation_payload="$(RESULT_JSON="$result" python3 - <<'PY'
import json, os
print(json.dumps({"status": "warn", "payload": json.loads(os.environ["RESULT_JSON"])}))
PY
)"
    curl -fsS -X POST \
      -H "Authorization: Bearer $CONTROL_TOKEN" \
      -H "Content-Type: application/json" \
      "$CONTROL_URL/control/api/intake/notion-observation" \
      -d "$observation_payload" >/dev/null || true
  fi
  exit 0
fi
cd "${ENOCH_INSTALL_DIR:-/opt/enoch-agentic-research-system}"
PYTHON_BIN="${ENOCH_PYTHON:-.venv/bin/python}"
args=(
  -m omx_wake_gate.control_plane.notion_sync
  --control-url "$CONTROL_URL"
  --notion-database-id "${NOTION_DATABASE_ID:-}"
  --idempotency-key "notion-sync:$(date -u +%Y%m%dT%H%M%SZ)"
  --apply-intake
  --apply-notion-updates
  --max-updates "${NOTION_SYNC_MAX_UPDATES:-500}"
)
if [[ -n "${NOTION_DATA_SOURCE_ID:-}" ]]; then
  args+=(--notion-data-source-id "$NOTION_DATA_SOURCE_ID")
fi
stdout_file="$(mktemp)"
stderr_file="$(mktemp)"
set +e
ENOCH_CONTROL_TOKEN="$CONTROL_TOKEN" NOTION_TOKEN="$NOTION_AUTH" $PYTHON_BIN "${args[@]}" >"$stdout_file" 2>"$stderr_file"
run_status=$?
set -e
run_stderr="$(cat "$stderr_file")"
rm -f "$stderr_file"
if [[ $run_status -eq 0 ]]; then
  python3 - "$stdout_file" <<'PY2'
import json, sys
with open(sys.argv[1], encoding="utf-8") as fh:
    r = json.load(fh)
print(json.dumps({
  "ok": r.get("ok"),
  "notion_rows_read": r.get("notion_rows_read"),
  "intake_created": (r.get("intake") or {}).get("created"),
  "intake_updated": (r.get("intake") or {}).get("updated"),
  "intake_skipped": (r.get("intake") or {}).get("skipped"),
  "execution_projection_count": r.get("execution_projection_count"),
  "notion_updates_applied_count": r.get("notion_updates_applied_count"),
  "notion_updates_skipped_count": r.get("notion_updates_skipped_count"),
}, sort_keys=True))
PY2
  rm -f "$stdout_file"
  exit 0
fi
run_stdout_tail="$(tail -c 4000 "$stdout_file" 2>/dev/null || true)"
rm -f "$stdout_file"
printf '%s
' "$run_stderr" >&2
result="$(RUN_STATUS="$run_status" RUN_STDOUT="$run_stdout_tail" RUN_STDERR="$run_stderr" python3 - <<'PY2'
import json, os
print(json.dumps({
  "ok": False,
  "action": "failed",
  "reason": "notion sync runner failed",
  "exit_status": int(os.environ.get("RUN_STATUS") or 1),
  "stdout_tail": os.environ.get("RUN_STDOUT", "")[-4000:],
  "stderr_tail": os.environ.get("RUN_STDERR", "")[-4000:],
}, sort_keys=True))
PY2
)"
echo "$result"
observation_payload="$(RESULT_JSON="$result" python3 - <<'PY2'
import json, os
print(json.dumps({"status": "warn", "payload": json.loads(os.environ["RESULT_JSON"])}))
PY2
)"
curl -fsS -X POST \
  -H "Authorization: Bearer $CONTROL_TOKEN" \
  -H "Content-Type: application/json" \
  "$CONTROL_URL/control/api/intake/notion-observation" \
  -d "$observation_payload" >/dev/null || true
exit "$run_status"
