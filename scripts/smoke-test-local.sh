#!/usr/bin/env bash
set -euo pipefail

CONFIG="${ENOCH_CONFIG:-}"
BASE_URL="${ENOCH_BASE_URL:-http://127.0.0.1:8787}"
CURL_TIMEOUT_ARGS=(--connect-timeout "${ENOCH_CURL_CONNECT_TIMEOUT:-3}" --max-time "${ENOCH_CURL_MAX_TIME:-30}")
STATUS_ENDPOINT="${ENOCH_STATUS_ENDPOINT:-/control/api/v1/overview?active_limit=5&event_limit=5}"
SKIP_PREFLIGHT="${ENOCH_SMOKE_SKIP_PREFLIGHT:-0}"
TOKEN="${ENOCH_CONTROL_TOKEN:-}"

if [[ -n "$CONFIG" && -z "$TOKEN" ]]; then
  TOKEN="$(python3 - <<'PY' "$CONFIG"
import json, sys
print(json.load(open(sys.argv[1]))['control_api_bearer_token'])
PY
)"
fi
if [[ -z "$TOKEN" ]]; then
  echo "Set ENOCH_CONTROL_TOKEN or ENOCH_CONFIG" >&2
  exit 2
fi

echo "healthz"
curl -fsS "${CURL_TIMEOUT_ARGS[@]}" "$BASE_URL/healthz" | python3 -m json.tool

STATUS_JSON="$(mktemp)"
trap 'rm -f "$STATUS_JSON"' EXIT

echo "status ($STATUS_ENDPOINT)"
curl -fsS "${CURL_TIMEOUT_ARGS[@]}" -H "Authorization: Bearer $TOKEN" "$BASE_URL$STATUS_ENDPOINT" | python3 -m json.tool >"$STATUS_JSON"
cat "$STATUS_JSON"

if [[ "$SKIP_PREFLIGHT" == "1" || "$SKIP_PREFLIGHT" == "true" || "$SKIP_PREFLIGHT" == "yes" ]]; then
  echo "preflight skipped (ENOCH_SMOKE_SKIP_PREFLIGHT=$SKIP_PREFLIGHT)"
else
  echo "preflight (non-strict self-check)"
  curl -fsS "${CURL_TIMEOUT_ARGS[@]}" -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
    -d "{\"wake_gate_url\":\"$BASE_URL\",\"bearer_token\":\"$TOKEN\",\"require_paused\":false,\"strict\":false}" \
    "$BASE_URL/control/api/preflight" | python3 -m json.tool
fi

echo "dispatch dry run"
curl -fsS "${CURL_TIMEOUT_ARGS[@]}" -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"dry_run":true,"requested_by":"smoke-test"}' \
  "$BASE_URL/control/dispatch-next" | python3 -m json.tool
