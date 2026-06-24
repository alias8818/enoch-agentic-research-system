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
  --exclude='.codegraph'
  --exclude='.codegraph/*'
  --exclude='.local'
  --exclude='.local/*'
  --exclude='__pycache__'
  --exclude='__pycache__/*'
  --exclude='*/__pycache__'
  --exclude='*/__pycache__/*'
  --exclude='private-notes'
  --exclude='private-notes/*'
  --exclude='*.db'
  --exclude='*.db-*'
  --exclude='*.sqlite'
  --exclude='*.sqlite-*'
  --exclude='*.sqlite3'
  --exclude='*.sqlite3-*'
  --exclude='*.log'
  --exclude='*.tar.gz'
  --exclude='*.tgz'
  --exclude='*.zip'
  --exclude='*.whl'
  --exclude='*.egg-info'
  --exclude='*.egg-info/*'
  --exclude='node_modules'
  --exclude='node_modules/*'
  --exclude='*/node_modules'
  --exclude='*/node_modules/*'
  --exclude='build'
  --exclude='build/*'
  --exclude='.pytest_cache'
  --exclude='.pytest_cache/*'
  --exclude='.ruff_cache'
  --exclude='.ruff_cache/*'
  --exclude='.mypy_cache'
  --exclude='.mypy_cache/*'
  --exclude='.hypothesis'
  --exclude='.hypothesis/*'
  --exclude='.coverage'
  --exclude='.enoch'
  --exclude='.enoch/*'
  --exclude='.env'
  --exclude='.env.*'
  --exclude='config.json'
  --exclude='config.example.json'
  --exclude='state'
  --exclude='state/*'
  --exclude='logs'
  --exclude='logs/*'
  --exclude='secrets'
  --exclude='secrets/*'
  --exclude='dist'
  --exclude='dist/*'
)

tar "${EXCLUDES[@]}" --transform "s#^.#$PREFIX#" -czf "$ARCHIVE_PATH" .

for pattern in '/.git/' '/.venv/' '/.omx/' '/.scan-results/' '/.codegraph/' '/.local/' '/__pycache__/' '/private-notes/' '.db' '.db-' '.sqlite' '.sqlite-' '.sqlite3' '.sqlite3-' '.log' '.tar.gz' '.tgz' '.zip' '.whl' '.egg-info' '/node_modules/' '/build/' '/.pytest_cache/' '/.ruff_cache/' '/.mypy_cache/' '/.hypothesis/' '/.coverage' '/.enoch/' '/.env' '/config.json' '/config.example.json' '/state/' '/logs/' '/secrets/'; do
  if tar -tzf "$ARCHIVE_PATH" | grep -F -- "$pattern" >/dev/null; then
    echo "FAIL archive contains forbidden pattern: $pattern" >&2
    exit 1
  fi
done

echo "$ARCHIVE_PATH"
