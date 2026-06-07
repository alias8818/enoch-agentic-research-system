#!/usr/bin/env bash
set -euo pipefail

ENABLE_GRAPH="${ENOCH_ENABLE_PAPER_MATERIAL_GRAPH:-0}"
if [[ "$ENABLE_GRAPH" != "1" ]]; then
  echo '{"ok":true,"action":"skipped","reason":"paper material graph disabled; set ENOCH_ENABLE_PAPER_MATERIAL_GRAPH=1 to run intentionally"}'
  exit 0
fi

RELEASE_ROOT="${ENOCH_RELEASE_ROOT:-/opt/enoch-release}"
CONTROL_PLANE_ROOT="${ENOCH_CONTROL_PLANE_ROOT:-/opt/enoch-control-plane}"
CORPUS_REPO="${ENOCH_CORPUS_REPO:-$RELEASE_ROOT/enoch-ai-research-corpus}"
PROMISING_REPO="${ENOCH_PROMISING_REPO:-$RELEASE_ROOT/enoch-promising-signals}"
OUTPUT_DIR="${ENOCH_PAPER_MATERIAL_GRAPH_DIR:-$CONTROL_PLANE_ROOT/docs/paper-material-graph}"
MIN_SHARED_TERMS="${ENOCH_PAPER_MATERIAL_GRAPH_MIN_SHARED_TERMS:-2}"
MAX_SIMILAR_PER_NODE="${ENOCH_PAPER_MATERIAL_GRAPH_MAX_SIMILAR_PER_NODE:-8}"
PYTHON_BIN="${ENOCH_PYTHON:-$CONTROL_PLANE_ROOT/.venv/bin/python}"

mkdir -p "$OUTPUT_DIR"
exec "$PYTHON_BIN" "$CONTROL_PLANE_ROOT/scripts/build_paper_material_graph.py" \
  --corpus-repo "$CORPUS_REPO" \
  --promising-repo "$PROMISING_REPO" \
  --json-output "$OUTPUT_DIR/paper-material-graph.json" \
  --markdown-output "$OUTPUT_DIR/README.md" \
  --min-shared-terms "$MIN_SHARED_TERMS" \
  --max-similar-per-node "$MAX_SIMILAR_PER_NODE"
