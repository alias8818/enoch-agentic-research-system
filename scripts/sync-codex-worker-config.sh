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

echo "backing up CPU Codex home on $cpu_host"
ssh "$cpu_host" "set -euo pipefail; stamp=\$(date -u +%Y%m%dT%H%M%SZ); parent=\$(dirname '$cpu_codex_home'); name=\$(basename '$cpu_codex_home'); backup=\"\$parent/codex-backup-pre-gb10-sync-\$stamp.tgz\"; tar -C \"\$parent\" -czf \"\$backup\" \"\$name\"; chmod 600 \"\$backup\"; echo \"backup=\$backup\""

if [[ "$preserve_cpu_projects" == "1" ]]; then
  echo "preserving CPU project trust entries"
  ssh "$cpu_host" "set -euo pipefail; python3 - <<'PY'
from pathlib import Path
cfg = Path('$cpu_codex_home/config.toml')
out = Path('$cpu_codex_home/cpu-projects-preserve.toml')
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
            if not blocks[-1].endswith('\\n'):
                blocks[-1] += '\\n'
            blocks.append('\\n')
        continue
    i += 1
out.write_text(''.join(blocks))
print(f'cpu_project_blocks={sum(1 for line in blocks if line.startswith(\"[projects.\"))}')
PY"
fi

echo "copying GB10 Codex runtime surface to CPU"
printf '%s\n' "${runtime_paths[@]}" \
  | ssh "$gb10_host" "set -euo pipefail; cd '$gb10_codex_home'; keep=\$(mktemp); trap 'rm -f \"\$keep\"' EXIT; while IFS= read -r path; do
      [[ -e \"\$path\" ]] || continue
      if [[ -L \"\$path\" ]]; then echo \"error: symlink entries are not allowed in sync payload: \$path\" >&2; exit 1; fi
      if [[ -f \"\$path\" && \$(stat -c %h \"\$path\") -gt 1 ]]; then echo \"error: hardlink entries are not allowed in sync payload: \$path\" >&2; exit 1; fi
      if [[ -d \"\$path\" ]]; then
        if find \"\$path\" -type l -print -quit | grep -q .; then echo \"error: symlink entries are not allowed in sync payload: \$path\" >&2; exit 1; fi
        if find \"\$path\" -type f -links +1 -print -quit | grep -q .; then echo \"error: hardlink entries are not allowed in sync payload: \$path\" >&2; exit 1; fi
      elif [[ ! -f \"\$path\" ]]; then
        echo \"error: unsupported sync payload entry type: \$path\" >&2
        exit 1
      fi
      printf '%s\n' \"\$path\" >> \"\$keep\"
    done
    [[ -f auth.json ]] || { echo 'error: auth.json must be a regular file' >&2; exit 1; }
    [[ -f config.toml ]] || { echo 'error: config.toml must be a regular file' >&2; exit 1; }
    tar -cf - -T \"\$keep\"" \
  | ssh "$cpu_host" "set -euo pipefail; stage=\$(mktemp -d); trap 'rm -rf \"\$stage\"' EXIT; tar -C \"\$stage\" -xf -; if find \"\$stage\" -type l -print -quit | grep -q .; then echo 'error: symlink entries are not allowed in sync payload' >&2; exit 1; fi; if find \"\$stage\" -type f -links +1 -print -quit | grep -q .; then echo 'error: hardlink entries are not allowed in sync payload' >&2; exit 1; fi; [[ -f \"\$stage/auth.json\" ]] || { echo 'error: auth.json must be a regular file' >&2; exit 1; }; [[ -f \"\$stage/config.toml\" ]] || { echo 'error: config.toml must be a regular file' >&2; exit 1; }; mkdir -p '$cpu_codex_home' '$cpu_codex_home/.tmp'; while IFS= read -r path; do rm -rf '$cpu_codex_home/'\"\$path\"; if [[ -e \"\$stage/\$path\" ]]; then parent=\$(dirname '$cpu_codex_home/'\"\$path\"); mkdir -p \"\$parent\"; mv \"\$stage/\$path\" '$cpu_codex_home/'\"\$path\"; fi; done <<'EOF'
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
EOF"

if [[ "$preserve_cpu_projects" == "1" ]]; then
  echo "appending preserved CPU project trust entries"
  ssh "$cpu_host" "set -euo pipefail; preserve='$cpu_codex_home/cpu-projects-preserve.toml'; if [[ -s \"\$preserve\" ]]; then printf '\n# Preserved CPU worker project trust entries from pre-sync config.\n' >> '$cpu_codex_home/config.toml'; cat \"\$preserve\" >> '$cpu_codex_home/config.toml'; fi"
fi

echo "repairing ownership and validating TOML"
ssh "$cpu_host" "set -euo pipefail; chown -R '$cpu_user:$cpu_user' '$cpu_codex_home'; chmod 700 '$cpu_codex_home'; chmod 600 '$cpu_codex_home/auth.json' '$cpu_codex_home/config.toml'; sudo -u '$cpu_user' -H bash -lc 'export HOME=/var/lib/enoch-cpu-worker; python3 - <<PY
import tomllib
from pathlib import Path
data = tomllib.loads(Path(\"$cpu_codex_home/config.toml\").read_text())
print(\"config_ok\")
print(\"projects\", len(data.get(\"projects\", {})))
print(\"plugins\", sorted((data.get(\"plugins\") or {}).keys()))
PY'"

echo "Codex worker config sync complete"
