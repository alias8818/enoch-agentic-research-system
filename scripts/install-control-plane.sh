#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
usage: scripts/install-control-plane.sh [--prefix /opt/enoch-agentic-research-system] [--config-dir /etc/enoch] [--state-dir /var/lib/enoch-control-plane] [--user enoch]

Installs Python dependencies, creates config/state directories, and optionally installs systemd units when run with sudo/root privileges.
It never writes real secrets. Edit the generated config before starting live dispatch.
USAGE
}

PREFIX="/opt/enoch-agentic-research-system"
CONFIG_DIR="/etc/enoch"
STATE_DIR="/var/lib/enoch-control-plane"
SERVICE_USER="enoch"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --prefix) PREFIX="$2"; shift 2 ;;
    --config-dir) CONFIG_DIR="$2"; shift 2 ;;
    --state-dir) STATE_DIR="$2"; shift 2 ;;
    --user) SERVICE_USER="$2"; shift 2 ;;
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

sync_to_prefix() {
  if [[ "$ROOT" == "$PREFIX" ]]; then
    return 0
  fi
  mkdir -p "$PREFIX"
  if command -v rsync >/dev/null 2>&1; then
    rsync -a --delete \
      --exclude .git \
      --exclude .venv \
      --exclude .pytest_cache \
      --exclude __pycache__ \
      --exclude "*.egg-info" \
      "$ROOT/" "$PREFIX/"
  else
    find "$PREFIX" -mindepth 1 -maxdepth 1 -exec rm -rf {} +
    tar -C "$ROOT" \
      --exclude .git \
      --exclude .venv \
      --exclude .pytest_cache \
      --exclude __pycache__ \
      --exclude "*.egg-info" \
      -cf - . | tar -C "$PREFIX" -xf -
  fi
}

write_unit() {
  local src="$1" dst="$2"
  python3 - "$src" "$dst" "$PREFIX" "$CONFIG_DIR/config.json" "$SERVICE_USER" <<'PY'
import pathlib, sys
src, dst, prefix, config, user = sys.argv[1:]
text = pathlib.Path(src).read_text()
text = text.replace("/opt/enoch-agentic-research-system", prefix)
text = text.replace("/etc/enoch/config.json", config)
text = text.replace("/etc/enoch/notion-sync.env", str(pathlib.Path(config).with_name("notion-sync.env")))
text = text.replace("User=enoch", f"User={user}")
text = text.replace("Group=enoch", f"Group={user}")
pathlib.Path(dst).write_text(text)
PY
}

if [[ "$(id -u)" -eq 0 ]]; then
  id -u "$SERVICE_USER" >/dev/null 2>&1 || useradd --system --home-dir "$STATE_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
  sync_to_prefix
  cd "$PREFIX"
  uv venv --python /usr/bin/python3 .venv
  uv pip install --python .venv/bin/python -e .
  mkdir -p "$CONFIG_DIR" "$STATE_DIR" "$STATE_DIR/projects" "$STATE_DIR/state"
  if [[ ! -f "$CONFIG_DIR/config.json" ]]; then
    cp "$ROOT/config.example.json" "$CONFIG_DIR/config.json"
    python3 - <<PY
import json, pathlib
p=pathlib.Path('$CONFIG_DIR/config.json')
data=json.loads(p.read_text())
data['state_dir']='$STATE_DIR/state'
data['project_root']='$STATE_DIR/projects'
data['dispatch_script_path']='$PREFIX/deploy/enoch_omx_dispatch.sh'
p.write_text(json.dumps(data, indent=2)+"\n")
PY
  fi
  chown -R "$SERVICE_USER:$SERVICE_USER" "$STATE_DIR"
  write_unit "$PREFIX/deploy/omx-wake-gate.service" /etc/systemd/system/enoch-control-plane.service
  write_unit "$PREFIX/deploy/enoch-queue-alert-check.service" /etc/systemd/system/enoch-queue-alert-check.service
  write_unit "$PREFIX/deploy/enoch-notion-sync.service" /etc/systemd/system/enoch-notion-sync.service
  write_unit "$PREFIX/deploy/enoch-paper-draft-next.service" /etc/systemd/system/enoch-paper-draft-next.service
  cp "$PREFIX/deploy/enoch-queue-alert-check.timer" /etc/systemd/system/enoch-queue-alert-check.timer
  cp "$PREFIX/deploy/enoch-notion-sync.timer" /etc/systemd/system/enoch-notion-sync.timer
  cp "$PREFIX/deploy/enoch-paper-draft-next.timer" /etc/systemd/system/enoch-paper-draft-next.timer
  systemctl daemon-reload
  echo "Installed systemd units. Edit $CONFIG_DIR/config.json, then run:"
  echo "  sudo systemctl enable --now enoch-control-plane.service"
  echo "  sudo systemctl enable --now enoch-notion-sync.timer         # optional Notion intake/projection sync"
  echo "  sudo systemctl enable --now enoch-paper-draft-next.timer    # optional draft-only paper production"
  echo "  sudo systemctl enable --now enoch-queue-alert-check.timer   # optional Pushover/queue alerts + dispatch pump"
else
  echo "Dependency install complete. Run with sudo/root to copy this checkout to $PREFIX, create $CONFIG_DIR and $STATE_DIR, and install systemd units."
fi
