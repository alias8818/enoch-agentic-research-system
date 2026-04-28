#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
usage: scripts/install-worker.sh [--config-dir ~/.config/enoch-worker] [--state-dir ~/.local/state/enoch-worker]

Installs dependencies for a worker/wake-gate node and writes a local example config if absent.
Use this on the machine that will run agent jobs and expose a wake-gate API to the control plane.
USAGE
}

CONFIG_DIR="$HOME/.config/enoch-worker"
STATE_DIR="$HOME/.local/state/enoch-worker"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --config-dir) CONFIG_DIR="$2"; shift 2 ;;
    --state-dir) STATE_DIR="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown arg: $1" >&2; usage; exit 2 ;;
  esac
done

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required. Install from https://docs.astral.sh/uv/ before running this script." >&2
  exit 3
fi
cd "$ROOT"
uv venv --python /usr/bin/python3 .venv
uv pip install --python .venv/bin/python -e .
uv run pytest -q
mkdir -p "$CONFIG_DIR" "$STATE_DIR/projects" "$STATE_DIR/state"
if [[ ! -f "$CONFIG_DIR/config.json" ]]; then
  cp config.example.json "$CONFIG_DIR/config.json"
  python3 - <<PY
import json, pathlib
p=pathlib.Path('$CONFIG_DIR/config.json')
data=json.loads(p.read_text())
data['state_dir']='$STATE_DIR/state'
data['project_root']='$STATE_DIR/projects'
data['dispatch_script_path']='$ROOT/deploy/enoch_omx_dispatch.sh'
data['completion_callback_url']='http://127.0.0.1:8787/omx/event'
p.write_text(json.dumps(data, indent=2)+"\n")
PY
fi
cat <<EOF2
Worker dependency install complete.

Edit: $CONFIG_DIR/config.json
Run worker wake gate:
  OMX_WAKE_GATE_CONFIG=$CONFIG_DIR/config.json uv run uvicorn omx_wake_gate.app:app --host 0.0.0.0 --port 8787
EOF2
