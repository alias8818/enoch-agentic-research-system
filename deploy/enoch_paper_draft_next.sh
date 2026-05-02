#!/usr/bin/env bash
set -euo pipefail
CONFIG_PATH="${OMX_WAKE_GATE_CONFIG:-/etc/enoch/config.json}"
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
if [[ -z "$CONTROL_TOKEN" ]]; then
  echo '{"ok":false,"action":"skipped","reason":"missing ENOCH_CONTROL_TOKEN and unreadable control config"}'
  exit 2
fi
exec curl -fsS -X POST \
  -H "Authorization: Bearer $CONTROL_TOKEN" \
  -H "Content-Type: application/json" \
  "$CONTROL_URL/control/papers/draft-next" \
  -d "{\"force\":false,\"requested_by\":\"systemd:enoch-paper-draft-next\"}"
