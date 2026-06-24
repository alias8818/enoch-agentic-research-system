#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  scripts/sync-codex-worker-config.sh

Synchronizes the Codex runtime surface from the GB10 worker account to the CPU
worker service account. The CPU worker's existing .codex directory is backed up
first, and CPU project trust entries are preserved by default.

Environment overrides:
  GB10_HOST              Source SSH host. Default: gx10-efe8
  GB10_CODEX_HOME        Source Codex home. Default: /home/jeremy/.codex
  CPU_HOST               Destination SSH host. Default: root@enoch-worker-cpu-1
  CPU_CODEX_HOME         Destination Codex home. Default: /var/lib/enoch-cpu-worker/.codex
  CPU_WORKER_USER        Destination service user. Default: enoch-cpu-worker
  PRESERVE_CPU_PROJECTS  Preserve CPU project trust entries. Default: 1
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

gb10_host="${GB10_HOST:-gx10-efe8}"
gb10_codex_home="${GB10_CODEX_HOME:-/home/jeremy/.codex}"
cpu_host="${CPU_HOST:-root@enoch-worker-cpu-1}"
cpu_codex_home="${CPU_CODEX_HOME:-/var/lib/enoch-cpu-worker/.codex}"
cpu_user="${CPU_WORKER_USER:-enoch-cpu-worker}"
preserve_cpu_projects="${PRESERVE_CPU_PROJECTS:-1}"

validate_ssh_host() {
  local value="$1"
  local name="$2"
  if [[ -z "$value" || "$value" == -* || ! "$value" =~ ^[A-Za-z0-9._@:-]+$ || "$value" == *@@* || "$value" == *@ || "$value" == @* ]]; then
    echo "error: unsafe $name: $value" >&2
    exit 2
  fi
}

validate_remote_path() {
  local value="$1"
  local name="$2"
  if [[ -z "$value" || "$value" != /* || ! "$value" =~ ^/[A-Za-z0-9._/@:+-]+$ ]]; then
    echo "error: unsafe $name: $value" >&2
    exit 2
  fi
}

validate_remote_user() {
  local value="$1"
  local name="$2"
  if [[ -z "$value" || ! "$value" =~ ^[A-Za-z_][A-Za-z0-9_-]*[$]?$ ]]; then
    echo "error: unsafe $name: $value" >&2
    exit 2
  fi
}

validate_flag() {
  local value="$1"
  local name="$2"
  if [[ "$value" != "0" && "$value" != "1" ]]; then
    echo "error: unsafe $name: $value" >&2
    exit 2
  fi
}

validate_ssh_host "$gb10_host" "GB10_HOST"
validate_ssh_host "$cpu_host" "CPU_HOST"
validate_remote_path "$gb10_codex_home" "GB10_CODEX_HOME"
validate_remote_path "$cpu_codex_home" "CPU_CODEX_HOME"
validate_remote_user "$cpu_user" "CPU_WORKER_USER"
validate_flag "$preserve_cpu_projects" "PRESERVE_CPU_PROJECTS"

echo "backing up CPU Codex home on $cpu_host"
ssh "$cpu_host" bash -s -- "$cpu_codex_home" <<'REMOTE'
set -euo pipefail
cpu_codex_home="$1"
stamp=$(date -u +%Y%m%dT%H%M%SZ)
parent=$(dirname "$cpu_codex_home")
name=$(basename "$cpu_codex_home")
backup="$parent/codex-backup-pre-gb10-sync-$stamp.tgz"
tar -C "$parent" -czf "$backup" "$name"
chmod 600 "$backup"
echo "backup=$backup"
REMOTE

if [[ "$preserve_cpu_projects" == "1" ]]; then
  echo "preserving CPU project trust entries"
  ssh "$cpu_host" bash -s -- "$cpu_codex_home" <<'REMOTE'
set -euo pipefail
cpu_codex_home="$1"
python3 - "$cpu_codex_home" <<'PY'
import sys
from pathlib import Path
cpu_codex_home = Path(sys.argv[1])
cfg = cpu_codex_home / 'config.toml'
out = cpu_codex_home / 'cpu-projects-preserve.toml'
if not cfg.exists():
    out.write_text('')
    raise SystemExit
lines = cfg.read_text().splitlines(keepends=True)
blocks = []
i = 0
while i < len(lines):
    line = lines[i]
    if line.startswith('[projects.'):
        block = [line]
        i += 1
        while i < len(lines) and not (lines[i].startswith('[') and lines[i].rstrip().endswith(']')):
            block.append(lines[i])
            i += 1
        if '/var/lib/enoch-cpu-worker/projects/' in block[0]:
            blocks.extend(block)
            if not blocks[-1].endswith('\n'):
                blocks[-1] += '\n'
            blocks.append('\n')
        continue
    i += 1
out.write_text(''.join(blocks))
print(f'cpu_project_blocks={sum(1 for line in blocks if line.startswith("[projects."))}')
PY
REMOTE
fi

echo "copying GB10 Codex runtime surface to CPU"
ssh "$gb10_host" bash -s -- "$gb10_codex_home" <<'REMOTE' \
  | ssh "$cpu_host" bash -c '
set -euo pipefail
cpu_codex_home="$1"
stage=$(mktemp -d)
trap '\''rm -rf "$stage"'\'' EXIT
tar -C "$stage" -xf -
if find "$stage" -type l -print -quit | grep -q .; then echo '\''error: symlink entries are not allowed in sync payload'\'' >&2; exit 1; fi
if find "$stage" -type f -links +1 -print -quit | grep -q .; then echo '\''error: hardlink entries are not allowed in sync payload'\'' >&2; exit 1; fi
[[ -f "$stage/auth.json" ]] || { echo '\''error: auth.json must be a regular file'\'' >&2; exit 1; }
[[ -f "$stage/config.toml" ]] || { echo '\''error: config.toml must be a regular file'\'' >&2; exit 1; }
mkdir -p "$cpu_codex_home" "$cpu_codex_home/.tmp"
root=$(realpath -m "$cpu_codex_home")
stage_root=$(realpath -m "$stage")
while IFS= read -r path; do
  case "$path" in ""|/*|-*|*".."*) echo "error: rejecting unsafe sync payload path: $path" >&2; exit 1 ;; esac
  target=$(realpath -m "$cpu_codex_home/$path")
  source=$(realpath -m "$stage/$path")
  case "$target" in "$root"/*) ;; *) echo "error: rejecting unsafe sync payload path: $path" >&2; exit 1 ;; esac
  case "$source" in "$stage_root"/*) ;; *) echo "error: rejecting unsafe sync payload path: $path" >&2; exit 1 ;; esac
  rm -rf -- "$target"
  if [[ -e "$source" ]]; then
    parent=$(dirname "$target")
    mkdir -p "$parent"
    mv "$source" "$target"
  fi
done <<'\''EOF'\''
auth.json
config.toml
models_cache.json
version.json
installation_id
skills
plugins
.tmp/plugins
.tmp/plugins.sha
packages
vendor_imports
rules
superpowers
prompts
EOF
' bash "$cpu_codex_home"
set -euo pipefail
gb10_codex_home="$1"
cd "$gb10_codex_home"
keep=$(mktemp)
trap 'rm -f "$keep"' EXIT
runtime_paths=(
  auth.json
  config.toml
  models_cache.json
  version.json
  installation_id
  skills
  plugins
  .tmp/plugins
  .tmp/plugins.sha
  packages
  vendor_imports
  rules
  superpowers
  prompts
)
for path in "${runtime_paths[@]}"; do
  [[ -e "$path" ]] || continue
  if [[ -L "$path" ]]; then echo "error: symlink entries are not allowed in sync payload: $path" >&2; exit 1; fi
  if [[ -f "$path" && $(stat -c %h "$path") -gt 1 ]]; then echo "error: hardlink entries are not allowed in sync payload: $path" >&2; exit 1; fi
  if [[ -d "$path" ]]; then
    if find "$path" -type l -print -quit | grep -q .; then echo "error: symlink entries are not allowed in sync payload: $path" >&2; exit 1; fi
    if find "$path" -type f -links +1 -print -quit | grep -q .; then echo "error: hardlink entries are not allowed in sync payload: $path" >&2; exit 1; fi
  elif [[ ! -f "$path" ]]; then
    echo "error: unsupported sync payload entry type: $path" >&2
    exit 1
  fi
  printf '%s\n' "$path" >> "$keep"
done
[[ -f auth.json ]] || { echo 'error: auth.json must be a regular file' >&2; exit 1; }
[[ -f config.toml ]] || { echo 'error: config.toml must be a regular file' >&2; exit 1; }
tar -cf - -T "$keep"
REMOTE

if [[ "$preserve_cpu_projects" == "1" ]]; then
  echo "appending preserved CPU project trust entries"
  ssh "$cpu_host" bash -s -- "$cpu_codex_home" <<'REMOTE'
set -euo pipefail
cpu_codex_home="$1"
preserve="$cpu_codex_home/cpu-projects-preserve.toml"
if [[ -s "$preserve" ]]; then
  printf '\n# Preserved CPU worker project trust entries from pre-sync config.\n' >> "$cpu_codex_home/config.toml"
  cat "$preserve" >> "$cpu_codex_home/config.toml"
fi
REMOTE
fi

echo "repairing ownership and validating TOML"
ssh "$cpu_host" bash -s -- "$cpu_codex_home" "$cpu_user" <<'REMOTE'
set -euo pipefail
cpu_codex_home="$1"
cpu_user="$2"
chown -R "$cpu_user:$cpu_user" "$cpu_codex_home"
chmod 700 "$cpu_codex_home"
chmod 600 "$cpu_codex_home/auth.json" "$cpu_codex_home/config.toml"
sudo -u "$cpu_user" -H bash -s -- "$cpu_codex_home" <<'INNER'
set -euo pipefail
export HOME=/var/lib/enoch-cpu-worker
python3 - "$1" <<'PY'
import tomllib
import sys
from pathlib import Path
data = tomllib.loads((Path(sys.argv[1]) / "config.toml").read_text())
print("config_ok")
print("projects", len(data.get("projects", {})))
print("plugins", sorted((data.get("plugins") or {}).keys()))
PY
INNER
REMOTE

echo "Codex worker config sync complete"
