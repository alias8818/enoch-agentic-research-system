#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
DEST="$CODEX_HOME/skills/enoch-worker"
mkdir -p "$DEST"
cp "$ROOT/codex-skills/enoch-worker/SKILL.md" "$DEST/SKILL.md"
cat <<EOF
Installed Enoch worker Codex skill:
  $DEST/SKILL.md
EOF
