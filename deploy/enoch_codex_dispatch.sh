#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
usage: enoch_codex_dispatch.sh --run-id ID --project-dir DIR --prompt-file FILE [options]

options:
  --project-id ID
  --mode exec|resume   (default: exec)
  --session-id ID      (optional resume/session hint)
  --last               (resume the most recent session)
  --model MODEL
  --reasoning-effort low|medium|high|xhigh   (default: medium)
  --sandbox MODE       (default: danger-full-access)
  --log-dir DIR
  --runner-script PATH
EOF
}

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
LOG_DIR=""
RUNNER_SCRIPT_OVERRIDE=""

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
    --log-dir) LOG_DIR="$2"; shift 2 ;;
    --runner-script) RUNNER_SCRIPT_OVERRIDE="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown arg: $1" >&2; usage; exit 2 ;;
  esac
done

if [[ -z "$RUN_ID" || -z "$PROJECT_DIR" || -z "$PROMPT_FILE" ]]; then
  usage
  exit 2
fi

if [[ -z "$LOG_DIR" ]]; then
  LOG_DIR="$PROJECT_DIR/.enoch/logs/worker"
fi
mkdir -p "$LOG_DIR"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNNER_SCRIPT="${ENOCH_CODEX_RUNNER_SCRIPT:-$SCRIPT_DIR/enoch_codex_runner.sh}"
if [[ -n "$RUNNER_SCRIPT_OVERRIDE" ]]; then
  RUNNER_SCRIPT="$RUNNER_SCRIPT_OVERRIDE"
fi

STDOUT_LOG="$LOG_DIR/${RUN_ID}.stdout.log"
STDERR_LOG="$LOG_DIR/${RUN_ID}.stderr.log"

cmd=("$RUNNER_SCRIPT"
  "--run-id" "$RUN_ID"
  "--project-id" "$PROJECT_ID"
  "--project-dir" "$PROJECT_DIR"
  "--prompt-file" "$PROMPT_FILE"
  "--mode" "$MODE"
  "--reasoning-effort" "$REASONING_EFFORT"
  "--sandbox" "$SANDBOX"
)

if [[ -n "$SESSION_ID" ]]; then
  cmd+=("--session-id" "$SESSION_ID")
fi
if [[ "$USE_LAST" -eq 1 ]]; then
  cmd+=("--last")
fi
if [[ -n "$MODEL" ]]; then
  cmd+=("--model" "$MODEL")
fi

setsid "${cmd[@]}" >"$STDOUT_LOG" 2>"$STDERR_LOG" &
PID=$!
PGID="$(ps -o pgid= -p "$PID" | tr -d ' ')"

cat <<EOF
{"runner":"codex","run_id":"$RUN_ID","project_id":"$PROJECT_ID","project_dir":"$PROJECT_DIR","pid":$PID,"pgid":$PGID,"stdout_log":"$STDOUT_LOG","stderr_log":"$STDERR_LOG"}
EOF
