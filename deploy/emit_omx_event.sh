#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "usage: $0 <event> <session_id> [project_path] [project_name] [tmux_session] [reason] [question]" >&2
  exit 2
fi

EVENT="$1"
SESSION_ID="$2"
PROJECT_PATH="${3:-}"
PROJECT_NAME="${4:-}"
TMUX_SESSION="${5:-}"
REASON="${6:-}"
QUESTION="${7:-}"

RUN_ID="${ENOCH_RUN_ID:-}"
PROJECT_ID="${ENOCH_PROJECT_ID:-}"
ROOT_PID="${OMX_LAUNCH_ROOT_PID:-}"
PROCESS_GROUP_ID="${OMX_LAUNCH_PGID:-}"
ENDPOINT="${OMX_WAKE_GATE_URL:-http://127.0.0.1:8787/omx/event}"
TOKEN="${OMX_WAKE_GATE_TOKEN:-}"

normalize_template_arg() {
  local value="${1:-}"
  if [[ "$value" =~ ^\{\{[A-Za-z0-9_]+\}\}$ ]]; then
    printf ''
    return
  fi
  printf '%s' "$value"
}

PROJECT_NAME="$(normalize_template_arg "$PROJECT_NAME")"
TMUX_SESSION="$(normalize_template_arg "$TMUX_SESSION")"
REASON="$(normalize_template_arg "$REASON")"
QUESTION="$(normalize_template_arg "$QUESTION")"

if [[ -z "$RUN_ID" ]]; then
  echo "missing ENOCH_RUN_ID" >&2
  exit 3
fi

if [[ -z "$TOKEN" ]]; then
  echo "missing OMX_WAKE_GATE_TOKEN" >&2
  exit 4
fi

json_string() {
  python3 - <<'PY' "$1"
import json, sys
print(json.dumps(sys.argv[1]))
PY
}

BODY="$(cat <<EOF
{
  "event": $(json_string "$EVENT"),
  "run_id": $(json_string "$RUN_ID"),
  "session_id": $(json_string "$SESSION_ID"),
  "project_id": $(json_string "$PROJECT_ID"),
  "project_name": $(json_string "${PROJECT_NAME:-$PROJECT_PATH}"),
  "root_pid": ${ROOT_PID:-null},
  "process_group_id": ${PROCESS_GROUP_ID:-null},
  "message": $(json_string "$REASON"),
  "question": $(json_string "$QUESTION"),
  "tmux_session": $(json_string "$TMUX_SESSION")
}
EOF
)"

curl -fsS \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -X POST \
  --data "$BODY" \
  "$ENDPOINT"
