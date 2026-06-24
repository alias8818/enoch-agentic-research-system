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
CONTROL_CURL_CONFIG="$(mktemp)"
PREFLIGHT_JSON="$(mktemp)"
DISPATCH_JSON="$(mktemp)"
chmod 600 "$CONTROL_CURL_CONFIG" "$PREFLIGHT_JSON" "$DISPATCH_JSON"
trap 'rm -f "$STATUS_JSON" "$CONTROL_CURL_CONFIG" "$PREFLIGHT_JSON" "$DISPATCH_JSON"' EXIT

cat >"$CONTROL_CURL_CONFIG" <<EOF
header = "Authorization: Bearer $TOKEN"
EOF

cat >"$PREFLIGHT_JSON" <<EOF
{"require_paused":false,"strict":false}
EOF

cat >"$DISPATCH_JSON" <<'EOF'
{"dry_run":true,"requested_by":"smoke-test"}
EOF

echo "status ($STATUS_ENDPOINT)"
curl -fsS "${CURL_TIMEOUT_ARGS[@]}" --config "$CONTROL_CURL_CONFIG" "$BASE_URL$STATUS_ENDPOINT" | python3 -m json.tool >"$STATUS_JSON"
cat "$STATUS_JSON"

if [[ "$SKIP_PREFLIGHT" == "1" || "$SKIP_PREFLIGHT" == "true" || "$SKIP_PREFLIGHT" == "yes" ]]; then
  echo "preflight skipped (ENOCH_SMOKE_SKIP_PREFLIGHT=$SKIP_PREFLIGHT)"
else
  echo "preflight (non-strict self-check)"
  curl -fsS "${CURL_TIMEOUT_ARGS[@]}" --config "$CONTROL_CURL_CONFIG" -H 'Content-Type: application/json' \
    --data-binary "@$PREFLIGHT_JSON" \
    "$BASE_URL/control/worker/preflight" | python3 -m json.tool
fi

echo "dispatch dry run"
curl -fsS "${CURL_TIMEOUT_ARGS[@]}" --config "$CONTROL_CURL_CONFIG" -H 'Content-Type: application/json' \
  --data-binary "@$DISPATCH_JSON" \
  "$BASE_URL/control/dispatch-next" | python3 -m json.tool
