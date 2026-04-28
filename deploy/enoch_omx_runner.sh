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
OMX_BIN=""
OMX_WAKE_GATE_URL=""
OMX_WAKE_GATE_TOKEN_FILE=""
OMX_NOTIFY_GATEWAY_NAME=""

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
    --omx-bin) OMX_BIN="$2"; shift 2 ;;
    --omx-wake-gate-url) OMX_WAKE_GATE_URL="$2"; shift 2 ;;
    --omx-wake-gate-token-file) OMX_WAKE_GATE_TOKEN_FILE="$2"; shift 2 ;;
    --notify-gateway-name) OMX_NOTIFY_GATEWAY_NAME="$2"; shift 2 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

export OMX_NOTIFY_VERBOSITY="${OMX_NOTIFY_VERBOSITY:-agent}"
export ENOCH_RUN_ID="$RUN_ID"
export ENOCH_PROJECT_ID="$PROJECT_ID"
export ENOCH_PROJECT_DIR="$PROJECT_DIR"
export OMX_LAUNCH_ROOT_PID="$$"
export OMX_LAUNCH_PGID="$(ps -o pgid= -p $$ | tr -d ' ')"

if [[ -z "$OMX_NOTIFY_GATEWAY_NAME" ]]; then
  OMX_NOTIFY_GATEWAY_NAME="${OMX_NOTIFY_GATEWAY_NAME:-local-gate}"
fi

if [[ -z "$OMX_WAKE_GATE_URL" ]]; then
  OMX_WAKE_GATE_URL="${OMX_WAKE_GATE_URL:-http://127.0.0.1:8787/omx/event}"
fi

if [[ -z "$OMX_WAKE_GATE_TOKEN_FILE" ]]; then
  OMX_WAKE_GATE_TOKEN_FILE="${OMX_WAKE_GATE_TOKEN_FILE:-$HOME/projects/enoch_testing_ground/config/.omx_hook_token}"
fi

if [[ -z "${OMX_WAKE_GATE_TOKEN:-}" && -f "$OMX_WAKE_GATE_TOKEN_FILE" ]]; then
  export OMX_WAKE_GATE_TOKEN="$(<"$OMX_WAKE_GATE_TOKEN_FILE")"
fi

export OMX_WAKE_GATE_URL

cd "$PROJECT_DIR"

# systemd starts the wake gate without the operator's login-shell PATH.
# Pin the interactive toolchain path so omx spawns the current Codex CLI
# instead of the stale /usr/bin/codex fallback.
export PATH="$HOME/.nvm/versions/node/v22.22.1/bin:$HOME/.local/bin:$PATH"

common_args=(
  "--notify-temp"
  "--custom" "$OMX_NOTIFY_GATEWAY_NAME"
  "--skip-git-repo-check"
  "-c" "model_reasoning_effort=\"$REASONING_EFFORT\""
)

case "$REASONING_EFFORT" in
  low|medium|high|xhigh) ;;
  *) echo "invalid --reasoning-effort: $REASONING_EFFORT" >&2; exit 2 ;;
 esac

exec_args=("${common_args[@]}" "--sandbox" "$SANDBOX" "-C" "$PROJECT_DIR")
resume_args_base=("${common_args[@]}")

if [[ -n "$MODEL" ]]; then
  exec_args+=("--model" "$MODEL")
  resume_args_base+=("--model" "$MODEL")
fi

if [[ "$MODE" == "resume" ]]; then
  resume_args=("exec" "resume")
  if [[ "$USE_LAST" -eq 1 ]]; then
    resume_args+=("--last")
  elif [[ -n "$SESSION_ID" ]]; then
    resume_args+=("$SESSION_ID")
  else
    echo "resume mode requires --session-id or --last" >&2
    exit 2
  fi
  exec "$OMX_BIN" "${resume_args[@]}" "${resume_args_base[@]}" - <"$PROMPT_FILE"
fi

exec "$OMX_BIN" exec "${exec_args[@]}" - <"$PROMPT_FILE"
