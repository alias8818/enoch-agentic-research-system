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
draft_response="$(curl -fsS -X POST \
  -H "Authorization: Bearer $CONTROL_TOKEN" \
  -H "Content-Type: application/json" \
  "$CONTROL_URL/control/papers/draft-next" \
  -d "{\"force\":false,\"requested_by\":\"systemd:enoch-paper-draft-next\"}")"
draft_action="$(python3 -c 'import json,sys; print(json.load(sys.stdin).get("action",""))' <<<"$draft_response")"
paper_id="$(python3 -c 'import json,sys; print((json.load(sys.stdin).get("paper") or {}).get("paper_id",""))' <<<"$draft_response")"
rewrite_response='{"ok":true,"action":"skipped","reason":"no paper drafted"}'
if [[ "$draft_action" == "drafted" && -n "$paper_id" ]]; then
  paper_path="$(python3 - "$paper_id" <<'PY'
from urllib.parse import quote
import sys
print(quote(sys.argv[1], safe=""))
PY
)"
  rewrite_response="$(curl -fsS -X POST \
    -H "Authorization: Bearer $CONTROL_TOKEN" \
    -H "Content-Type: application/json" \
    "$CONTROL_URL/control/api/paper-reviews/$paper_path/rewrite-draft" \
    -d "{\"idempotency_key\":\"paper-publication-pipeline:$paper_id:$(date -u +%Y%m%dT%H%M%SZ)\",\"requested_by\":\"systemd:enoch-paper-draft-next\",\"force\":true}")"
fi
python3 - "$draft_response" "$rewrite_response" <<'PY'
import json, sys
print(json.dumps({"draft": json.loads(sys.argv[1]), "publication_rewrite": json.loads(sys.argv[2])}, sort_keys=True))
PY
