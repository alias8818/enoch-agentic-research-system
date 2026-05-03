#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

OUT_DIR="${ENOCH_ARCHIVE_OUT_DIR:-$ROOT/dist}"
ARCHIVE_NAME="${ENOCH_ARCHIVE_NAME:-enoch-agentic-research-system-public.tar.gz}"
ARCHIVE_PATH="$OUT_DIR/$ARCHIVE_NAME"
PREFIX="${ENOCH_ARCHIVE_PREFIX:-enoch-agentic-research-system}"
mkdir -p "$OUT_DIR"
rm -f "$ARCHIVE_PATH"

EXCLUDES=(
  --exclude='.git'
  --exclude='.git/*'
  --exclude='.venv'
  --exclude='.venv/*'
  --exclude='.omx'
  --exclude='.omx/*'
  --exclude='.scan-results'
  --exclude='.scan-results/*'
  --exclude='.local'
  --exclude='.local/*'
  --exclude='private-notes'
  --exclude='private-notes/*'
  --exclude='*.db'
  --exclude='*.sqlite'
  --exclude='*.sqlite3'
  --exclude='*.log'
  --exclude='.env'
  --exclude='.env.*'
  --exclude='dist'
  --exclude='dist/*'
)

tar "${EXCLUDES[@]}" --transform "s#^.#$PREFIX#" -czf "$ARCHIVE_PATH" .

for pattern in '/.git/' '/.venv/' '/.omx/' '/.scan-results/' '/.local/' '/private-notes/' '.db' '.sqlite' '.sqlite3' '.log' '/.env'; do
  if tar -tzf "$ARCHIVE_PATH" | grep -F -- "$pattern" >/dev/null; then
    echo "FAIL archive contains forbidden pattern: $pattern" >&2
    exit 1
  fi
done

echo "$ARCHIVE_PATH"
