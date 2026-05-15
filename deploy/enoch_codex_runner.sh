#!/usr/bin/env bash
set -euo pipefail

RUN_ID=""
PROJECT_ID=""
PROJECT_DIR=""
PROMPT_FILE=""
MODE="exec"
SESSION_ID=""
USE_LAST=0
MODEL=""
REASONING_EFFORT="medium"
SANDBOX="danger-full-access"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --run-id) RUN_ID="$2"; shift 2 ;;
    --project-id) PROJECT_ID="$2"; shift 2 ;;
    --project-dir) PROJECT_DIR="$2"; shift 2 ;;
    --prompt-file) PROMPT_FILE="$2"; shift 2 ;;
    --mode) MODE="$2"; shift 2 ;;
    --session-id) SESSION_ID="$2"; shift 2 ;;
    --last) USE_LAST=1; shift ;;
    --model) MODEL="$2"; shift 2 ;;
    --reasoning-effort) REASONING_EFFORT="$2"; shift 2 ;;
    --sandbox) SANDBOX="$2"; shift 2 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

if [[ -z "$RUN_ID" || -z "$PROJECT_DIR" || -z "$PROMPT_FILE" ]]; then
  echo "missing --run-id, --project-dir, or --prompt-file" >&2
  exit 2
fi

case "$REASONING_EFFORT" in
  low|medium|high|xhigh) ;;
  *) echo "invalid --reasoning-effort: $REASONING_EFFORT" >&2; exit 2 ;;
esac
case "$MODE" in
  exec|resume) ;;
  *) echo "invalid --mode: $MODE" >&2; exit 2 ;;
esac

mkdir -p "$PROJECT_DIR/.enoch/logs" "$PROJECT_DIR/.enoch/state" "$PROJECT_DIR/.omx/logs" "$PROJECT_DIR/.omx/state"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_DIR"

export ENOCH_RUN_ID="$RUN_ID"
export ENOCH_PROJECT_ID="$PROJECT_ID"
export ENOCH_PROJECT_DIR="$PROJECT_DIR"
export ENOCH_LAUNCH_ROOT_PID="$$"
export ENOCH_LAUNCH_PGID="$(ps -o pgid= -p $$ | tr -d ' ')"
export PATH="$HOME/.nvm/versions/node/v22.22.1/bin:$HOME/.local/bin:$PATH"
export PYTHONPATH="$REPO_ROOT:${PYTHONPATH:-}"
# Upstream Codex still recognizes this variable; keep disabled by default to avoid legacy OMX wrappers.
export USE_OMX_EXPLORE_CMD="${USE_OMX_EXPLORE_CMD:-0}"

CODEX_BIN="${CODEX_BIN:-$(command -v codex || true)}"
if [[ -z "$CODEX_BIN" ]]; then
  echo "codex binary not found in PATH" >&2
  exit 127
fi

JSON_LOG="$PROJECT_DIR/.enoch/logs/${RUN_ID}.codex.jsonl"
LAST_MESSAGE="$PROJECT_DIR/.enoch/last_message.md"
SESSION_FILE="$PROJECT_DIR/.enoch/session.json"
STARTED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
EXIT_CODE=0

build_common_args() {
  printf '%s\0' \
    "--skip-git-repo-check" \
    "--json" \
    "--output-last-message" "$LAST_MESSAGE" \
    "--sandbox" "$SANDBOX" \
    "-C" "$PROJECT_DIR" \
    "-c" "model_reasoning_effort=\"$REASONING_EFFORT\""
}

# Run Codex directly. OMX is intentionally not in this execution path.
if [[ "$MODE" == "resume" ]]; then
  cmd=("$CODEX_BIN" "exec" "resume")
  if [[ "$USE_LAST" -eq 1 ]]; then
    cmd+=("--last")
  elif [[ -n "$SESSION_ID" ]]; then
    cmd+=("$SESSION_ID")
  else
    echo "resume mode requires --session-id or --last" >&2
    exit 2
  fi
  cmd+=("--json" "--output-last-message" "$LAST_MESSAGE")
  if [[ -n "$MODEL" ]]; then cmd+=("--model" "$MODEL"); fi
  cmd+=("-" )
else
  cmd=("$CODEX_BIN" "exec" "--skip-git-repo-check" "--json" "--output-last-message" "$LAST_MESSAGE" "--sandbox" "$SANDBOX" "-C" "$PROJECT_DIR" "-c" "model_reasoning_effort=\"$REASONING_EFFORT\"")
  if [[ -n "$MODEL" ]]; then cmd+=("--model" "$MODEL"); fi
  cmd+=("-" )
fi

set +e
"${cmd[@]}" <"$PROMPT_FILE" >"$JSON_LOG" 2>"$PROJECT_DIR/.enoch/logs/${RUN_ID}.codex.stderr.log"
EXIT_CODE=$?
set -e
ENDED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

python3 - <<'PY' "$JSON_LOG" "$SESSION_FILE" "$RUN_ID" "$PROJECT_ID" "$STARTED_AT" "$ENDED_AT" "$EXIT_CODE"
import json, sys
log_path, session_file, run_id, project_id, started_at, ended_at, exit_code = sys.argv[1:]
session_id = ""
last_type = ""
try:
    with open(log_path, "r", encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            try:
                obj = json.loads(line)
            except Exception:
                continue
            last_type = str(obj.get("type") or obj.get("event") or last_type)
            for key in ("session_id", "conversation_id", "thread_id"):
                value = obj.get(key)
                if isinstance(value, str) and value:
                    session_id = value
            payload = obj.get("payload")
            if isinstance(payload, dict):
                for key in ("session_id", "conversation_id", "thread_id"):
                    value = payload.get(key)
                    if isinstance(value, str) and value:
                        session_id = value
except FileNotFoundError:
    pass
if not session_id:
    session_id = f"codex-native:{run_id}"
with open(session_file, "w", encoding="utf-8") as fh:
    json.dump({
        "runner": "codex",
        "run_id": run_id,
        "project_id": project_id,
        "session_id": session_id,
        "started_at": started_at,
        "ended_at": ended_at,
        "exit_code": int(exit_code),
        "json_log": log_path,
        "last_event_type": last_type,
    }, fh, indent=2, sort_keys=True)
    fh.write("\n")
print(session_id)
PY
SESSION_ID_EFFECTIVE="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("session_id", ""))' "$SESSION_FILE")"

# Legacy artifact readers may still inspect .omx. Keep the decision file path compatible
# while the canonical worker output moves to .enoch.
if [[ -f "$PROJECT_DIR/.enoch/project_decision.json" && ! -f "$PROJECT_DIR/.omx/project_decision.json" ]]; then
  cp "$PROJECT_DIR/.enoch/project_decision.json" "$PROJECT_DIR/.omx/project_decision.json"
fi
if [[ -f "$PROJECT_DIR/.enoch/metrics.json" && ! -f "$PROJECT_DIR/.omx/metrics.json" ]]; then
  cp "$PROJECT_DIR/.enoch/metrics.json" "$PROJECT_DIR/.omx/metrics.json"
fi

CALLBACK_URL="${ENOCH_COMPLETION_CALLBACK_URL:-}"
CALLBACK_TOKEN="${ENOCH_COMPLETION_CALLBACK_TOKEN:-}"
CALLBACK_TIMEOUT="${ENOCH_COMPLETION_CALLBACK_TIMEOUT_SEC:-120}"
WORKER_STATE_DIR="${ENOCH_WORKER_STATE_DIR:-$PROJECT_DIR/.enoch/state}"
CALLBACK_EVENT="wake_ready"
CALLBACK_GATE="wake_ready"
CALLBACK_REASON="codex runner completed"
if [[ "$EXIT_CODE" -ne 0 ]]; then
  CALLBACK_EVENT="gate_error"
  CALLBACK_GATE="gate_error"
  CALLBACK_REASON="codex runner exited nonzero: $EXIT_CODE"
fi

if [[ -n "$CALLBACK_URL" && -n "$CALLBACK_TOKEN" ]]; then
  CALLBACK_PAYLOAD_FILE="$PROJECT_DIR/.enoch/state/${RUN_ID}.callback_payload.json"
  python3 - <<'PY_CALLBACK_PAYLOAD' "$CALLBACK_PAYLOAD_FILE" "$RUN_ID" "$SESSION_ID_EFFECTIVE" "$PROJECT_ID" "$CALLBACK_EVENT" "$CALLBACK_GATE" "$CALLBACK_REASON" "$EXIT_CODE" "$PROJECT_DIR" "$STARTED_AT" "$ENDED_AT"
import json, pathlib, sys
(
    payload_file, run_id, session_id, project_id, event_type, gate_state,
    reason, exit_code, project_dir, started_at, ended_at,
) = sys.argv[1:]
payload = {
    "event_type": event_type,
    "run_id": run_id,
    "session_id": session_id,
    "project_id": project_id,
    "project_name": project_id,
    "source_event": "codex-runner-exit",
    "gate_state": gate_state,
    "process_tracking": {
        "root_pid": None,
        "process_group_id": None,
        "processes": [],
        "live_process_count": 0,
    },
    "telemetry": {
        "runner": "codex",
        "exit_code": int(exit_code),
        "project_dir": project_dir,
        "started_at": started_at,
        "ended_at": ended_at,
    },
    "reason": reason,
    "idempotency_key": f"{run_id}:{event_type}:codex-runner:{ended_at}",
}
path = pathlib.Path(payload_file)
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY_CALLBACK_PAYLOAD
  python3 -m enoch_control_plane.callback_outbox write --state-dir "$WORKER_STATE_DIR" --payload-file "$CALLBACK_PAYLOAD_FILE" >/dev/null
  if python3 -m enoch_control_plane.callback_outbox deliver --state-dir "$WORKER_STATE_DIR" --run-id "$RUN_ID" --url "$CALLBACK_URL" --token "$CALLBACK_TOKEN" --timeout "$CALLBACK_TIMEOUT"; then
    true
  else
    echo "callback delivery failed; durable callback outbox will retry: $WORKER_STATE_DIR/callback_outbox/${RUN_ID}.json" >&2
  fi
else
  echo "completion callback not configured; leaving local artifacts only" >&2
fi

exit "$EXIT_CODE"
