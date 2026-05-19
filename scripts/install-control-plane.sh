#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
usage: scripts/install-control-plane.sh [--prefix /opt/enoch-control-plane] [--config-dir /etc/enoch-control-plane] [--state-dir /var/lib/enoch-control-plane] [--user enoch]

Installs Python dependencies, creates config/state directories, and optionally installs systemd units when run with sudo/root privileges.
It never writes real secrets. Edit the generated config before starting live dispatch.
USAGE
}

PREFIX="/opt/enoch-control-plane"
CONFIG_DIR="/etc/enoch-control-plane"
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
text = text.replace("/opt/enoch-control-plane", prefix)
text = text.replace("/etc/enoch-control-plane/config.json", config)
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
data['dispatch_script_path']='$PREFIX/deploy/enoch_codex_dispatch.sh'
p.write_text(json.dumps(data, indent=2)+"\n")
PY
  fi
  chown -R "$SERVICE_USER:$SERVICE_USER" "$STATE_DIR"
  write_unit "$PREFIX/deploy/enoch-worker-gate.service" /etc/systemd/system/enoch-control-plane.service
  write_unit "$PREFIX/deploy/enoch-queue-alert-check.service" /etc/systemd/system/enoch-queue-alert-check.service
  write_unit "$PREFIX/deploy/enoch-source-lineage-check.service" /etc/systemd/system/enoch-source-lineage-check.service
  if [[ "${ENOCH_INSTALL_LEGACY_NOTION_UNITS:-0}" == "1" ]]; then
    write_unit "$PREFIX/deploy/enoch-notion-sync.service" /etc/systemd/system/enoch-notion-sync.service
  fi
  if [[ "${ENOCH_INSTALL_PAPER_DRAFT_NEXT_UNITS:-0}" == "1" ]]; then
    write_unit "$PREFIX/deploy/enoch-paper-draft-next.service" /etc/systemd/system/enoch-paper-draft-next.service
  fi
  if [[ "${ENOCH_INSTALL_RESEARCH_AUTOPILOT_UNITS:-0}" == "1" ]]; then
    write_unit "$PREFIX/deploy/enoch-research-autopilot.service" /etc/systemd/system/enoch-research-autopilot.service
  fi
  cp "$PREFIX/deploy/enoch-queue-alert-check.timer" /etc/systemd/system/enoch-queue-alert-check.timer
  cp "$PREFIX/deploy/enoch-source-lineage-check.timer" /etc/systemd/system/enoch-source-lineage-check.timer
  if [[ "${ENOCH_INSTALL_LEGACY_NOTION_UNITS:-0}" == "1" ]]; then
    cp "$PREFIX/deploy/enoch-notion-sync.timer" /etc/systemd/system/enoch-notion-sync.timer
  fi
  if [[ "${ENOCH_INSTALL_PAPER_DRAFT_NEXT_UNITS:-0}" == "1" ]]; then
    cp "$PREFIX/deploy/enoch-paper-draft-next.timer" /etc/systemd/system/enoch-paper-draft-next.timer
  fi
  if [[ "${ENOCH_INSTALL_RESEARCH_AUTOPILOT_UNITS:-0}" == "1" ]]; then
    cp "$PREFIX/deploy/enoch-research-autopilot.timer" /etc/systemd/system/enoch-research-autopilot.timer
  fi
  systemctl daemon-reload
  echo "Installed systemd units. Edit $CONFIG_DIR/config.json, then run:"
  echo "  sudo systemctl enable --now enoch-control-plane.service"
  echo "  sudo systemctl enable --now enoch-source-lineage-check.timer       # provenance guard"
  echo "  Supabase-native /control/intake/ideas is the supported intake path; legacy Notion units are not installed by default."
  echo "  ENOCH_INSTALL_PAPER_DRAFT_NEXT_UNITS=1 sudo -E scripts/install-control-plane.sh  # install opt-in draft-only paper units"
  echo "  sudo systemctl edit enoch-paper-draft-next.service             # set ENOCH_ENABLE_PAPER_DRAFT_NEXT=1 before intentional drafting"
  echo "  ENOCH_INSTALL_RESEARCH_AUTOPILOT_UNITS=1 sudo -E scripts/install-control-plane.sh  # install opt-in bounded research autopilot units"
  echo "  sudo systemctl edit enoch-research-autopilot.service          # set ENOCH_ENABLE_RESEARCH_AUTOPILOT=1 before autonomous cycles"
  echo "  sudo systemctl enable --now enoch-queue-alert-check.timer   # optional Pushover/queue alerts + dispatch pump"
else
  echo "Dependency install complete. Run with sudo/root to copy this checkout to $PREFIX, create $CONFIG_DIR and $STATE_DIR, and install systemd units."
fi
