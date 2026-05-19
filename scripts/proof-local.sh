#!/usr/bin/env bash
set -euo pipefail

if [[ "${ENOCH_PROOF_TIMEOUT_CHILD:-0}" != "1" ]]; then
  exec timeout "${ENOCH_PROOF_TIMEOUT:-90s}" env ENOCH_PROOF_TIMEOUT_CHILD=1 "$0" "$@"
fi

CURL_TIMEOUT_ARGS=(--connect-timeout "${ENOCH_CURL_CONNECT_TIMEOUT:-3}" --max-time "${ENOCH_CURL_MAX_TIME:-10}")

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PORT="${ENOCH_PROOF_PORT:-8787}"
HOST="127.0.0.1"
BASE_URL="http://${HOST}:${PORT}"
LOCAL_DIR="$ROOT/.local"
CONFIG_DIR="$LOCAL_DIR/config"
STATE_DIR="$LOCAL_DIR/state"
PROJECTS_DIR="$LOCAL_DIR/projects"
BIN_DIR="$LOCAL_DIR/bin"
CONFIG_PATH="$CONFIG_DIR/config.json"
LOG_PATH="$LOCAL_DIR/proof-local.log"
TOKEN="${ENOCH_CONTROL_TOKEN:-$(python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(32))
PY
)}"
CALLBACK_TOKEN="$(python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(24))
PY
)"

mkdir -p "$CONFIG_DIR" "$STATE_DIR" "$PROJECTS_DIR" "$BIN_DIR"
cat > "$BIN_DIR/enoch_codex_dispatch.sh" <<'SHIM'
#!/usr/bin/env bash
set -euo pipefail
echo "proof-local dispatch shim: dry-run safe"
SHIM
chmod +x "$BIN_DIR/enoch_codex_dispatch.sh"

python3 - <<'PY' "$ROOT/config.example.json" "$CONFIG_PATH" "$STATE_DIR" "$PROJECTS_DIR" "$BIN_DIR/enoch_codex_dispatch.sh" "$TOKEN" "$CALLBACK_TOKEN" "$PORT"
import json, sys
from pathlib import Path
src, dst, state_dir, projects_dir, dispatch_script, token, callback_token, port = sys.argv[1:]
config = json.load(open(src, encoding="utf-8"))
config.update({
    "listen_host": "127.0.0.1",
    "listen_port": int(port),
    "state_dir": state_dir,
    "project_root": projects_dir,
    "dispatch_script_path": dispatch_script,
    "control_api_bearer_token": token,
    "completion_callback_url": f"http://127.0.0.1:{port}/healthz",
    "completion_callback_token": callback_token,
    "worker_wake_gate_url": f"http://127.0.0.1:{port}",
    "worker_wake_gate_bearer_token": token,
    "live_dispatch_enabled": False,
    "pushover_alerts_enabled": False,
    "queue_pump_enabled": False,
    "paper_evidence_sync_enabled": False,
    "paper_writer_api_key": "",
})
Path(dst).write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY

if curl -fsS "${CURL_TIMEOUT_ARGS[@]}" "$BASE_URL/healthz" >/dev/null 2>&1; then
  echo "Port ${PORT} is already serving /healthz; stop that process or set ENOCH_PROOF_PORT." >&2
  exit 2
fi

cleanup() {
  if [[ -n "${SERVER_PID:-}" ]] && kill -0 "$SERVER_PID" >/dev/null 2>&1; then
    kill "$SERVER_PID" >/dev/null 2>&1 || true
    wait "$SERVER_PID" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

: > "$LOG_PATH"
ENOCH_CONFIG="$CONFIG_PATH" uv run uvicorn enoch_control_plane.app:app --host "$HOST" --port "$PORT" >"$LOG_PATH" 2>&1 &
SERVER_PID=$!

for _ in $(seq 1 60); do
  if curl -fsS "${CURL_TIMEOUT_ARGS[@]}" "$BASE_URL/healthz" >/dev/null 2>&1; then
    echo "PASS healthz"
    break
  fi
  if ! kill -0 "$SERVER_PID" >/dev/null 2>&1; then
    echo "proof-local server exited early; log follows" >&2
    cat "$LOG_PATH" >&2
    exit 1
  fi
  sleep 0.5
done

if ! curl -fsS "${CURL_TIMEOUT_ARGS[@]}" "$BASE_URL/healthz" >/dev/null 2>&1; then
  echo "timed out waiting for $BASE_URL/healthz; log follows" >&2
  cat "$LOG_PATH" >&2
  exit 1
fi

SMOKE_OUTPUT="$(ENOCH_BASE_URL="$BASE_URL" ENOCH_CONTROL_TOKEN="$TOKEN" ENOCH_STATUS_ENDPOINT="/control/api/status" scripts/smoke-test-local.sh)"
printf '%s\n' "$SMOKE_OUTPUT"

grep -q '"dispatch_safe"' <<<"$SMOKE_OUTPUT" || { echo "FAIL control status" >&2; exit 1; }
echo "PASS control status"
grep -q 'wake_gate_healthz' <<<"$SMOKE_OUTPUT" || { echo "FAIL wake gate healthz self-check" >&2; exit 1; }
echo "PASS wake gate healthz self-check"
if ! grep -q '"action": "paused"' <<<"$SMOKE_OUTPUT" || ! grep -q '"live": null' <<<"$SMOKE_OUTPUT"; then
  echo "FAIL dispatch dry-run" >&2
  exit 1
fi
echo "PASS dispatch dry-run"
echo "Dashboard: ${BASE_URL}/dashboard"
