#!/usr/bin/env bash
set -euo pipefail

CONFIG="${OMX_WAKE_GATE_CONFIG:-}"
BASE_URL="${ENOCH_BASE_URL:-http://127.0.0.1:8787}"
TOKEN="${ENOCH_CONTROL_TOKEN:-}"

if [[ -n "$CONFIG" && -z "$TOKEN" ]]; then
  TOKEN="$(python3 - <<'PY' "$CONFIG"
import json, sys
print(json.load(open(sys.argv[1]))['omx_inbound_bearer_token'])
PY
)"
fi
if [[ -z "$TOKEN" ]]; then
  echo "Set ENOCH_CONTROL_TOKEN or OMX_WAKE_GATE_CONFIG" >&2
  exit 2
fi

echo "healthz"
curl -fsS "$BASE_URL/healthz" | python3 -m json.tool

STATUS_JSON="$(mktemp)"
trap 'rm -f "$STATUS_JSON"' EXIT

echo "status"
curl -fsS -H "Authorization: Bearer $TOKEN" "$BASE_URL/control/api/status" | python3 -m json.tool >"$STATUS_JSON"
cat "$STATUS_JSON"

echo "preflight (non-strict self-check)"
curl -fsS -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d "{\"wake_gate_url\":\"$BASE_URL\",\"bearer_token\":\"$TOKEN\",\"require_paused\":false,\"strict\":false}" \
  "$BASE_URL/control/api/preflight" | python3 -m json.tool

echo "dispatch dry run"
curl -fsS -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"dry_run":true,"requested_by":"smoke-test"}' \
  "$BASE_URL/control/dispatch-next" | python3 -m json.tool
