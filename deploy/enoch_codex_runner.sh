#!/usr/bin/env bash
set -euo pipefail

RUN_ID=""
PROJECT_ID=""
PROJECT_DIR=""
PROMPT_FILE=""
MODE="exec"
SESSION_ID=""
USE_LAST=0
MODEL=""
REASONING_EFFORT="medium"
SANDBOX="danger-full-access"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --run-id) RUN_ID="$2"; shift 2 ;;
    --project-id) PROJECT_ID="$2"; shift 2 ;;
    --project-dir) PROJECT_DIR="$2"; shift 2 ;;
    --prompt-file) PROMPT_FILE="$2"; shift 2 ;;
    --mode) MODE="$2"; shift 2 ;;
    --session-id) SESSION_ID="$2"; shift 2 ;;
    --last) USE_LAST=1; shift ;;
    --model) MODEL="$2"; shift 2 ;;
    --reasoning-effort) REASONING_EFFORT="$2"; shift 2 ;;
    --sandbox) SANDBOX="$2"; shift 2 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

if [[ -z "$RUN_ID" || -z "$PROJECT_DIR" || -z "$PROMPT_FILE" ]]; then
  echo "missing --run-id, --project-dir, or --prompt-file" >&2
  exit 2
fi

case "$REASONING_EFFORT" in
  low|medium|high|xhigh) ;;
  *) echo "invalid --reasoning-effort: $REASONING_EFFORT" >&2; exit 2 ;;
esac
case "$MODE" in
  exec|resume) ;;
  *) echo "invalid --mode: $MODE" >&2; exit 2 ;;
esac

CALLBACK_URL="${ENOCH_COMPLETION_CALLBACK_URL:-}"
CALLBACK_TOKEN="${ENOCH_COMPLETION_CALLBACK_TOKEN:-}"
CALLBACK_TIMEOUT="${ENOCH_COMPLETION_CALLBACK_TIMEOUT_SEC:-120}"
WORKER_STATE_DIR="${ENOCH_WORKER_STATE_DIR:-$PROJECT_DIR/.enoch/state}"
# Keep callback credentials out of the untrusted Codex/tool environment.
unset ENOCH_COMPLETION_CALLBACK_URL ENOCH_COMPLETION_CALLBACK_TOKEN ENOCH_COMPLETION_CALLBACK_TIMEOUT_SEC

mkdir -p "$PROJECT_DIR/.enoch/logs" "$PROJECT_DIR/.enoch/state" "$PROJECT_DIR/.omx/logs" "$PROJECT_DIR/.omx/state"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
callback_outbox() {
  (cd "$REPO_ROOT" && PYTHONPATH="$REPO_ROOT:${PYTHONPATH:-}" python3 -m enoch_control_plane.callback_outbox "$@")
}

bootstrap_scaffold() {
  local enabled="${ENOCH_SCAFFOLD_BOOTSTRAP:-1}"
  case "$enabled" in
    1|true|TRUE|yes|YES) ;;
    *) return 0 ;;
  esac

  if [[ -f "$PROJECT_DIR/.scaffold-used.yaml" ]]; then
    return 0
  fi

  local token_file="${ENOCH_SCAFFOLD_TOKEN_FILE:-$HOME/.config/enoch-git/scaffold-reader-token}"
  local catalog_url="${ENOCH_SCAFFOLD_CATALOG_URL:-http://100.114.53.78:8000/scaffolds/scaffold-catalog.git}"
  local requested_scaffold="${ENOCH_SCAFFOLD_NAME:-}"
  local direct_scaffold_url="${ENOCH_SCAFFOLD_URL:-}"
  local direct_scaffold_commit="${ENOCH_SCAFFOLD_COMMIT:-}"
  local allowed_base_urls="${ENOCH_SCAFFOLD_ALLOWED_BASE_URLS:-http://100.114.53.78:8000/scaffolds/}"
  local allow_file_urls="${ENOCH_SCAFFOLD_ALLOW_FILE_URLS:-0}"
  local require_pin="${ENOCH_SCAFFOLD_REQUIRE_PIN:-1}"
  if [[ ! -s "$token_file" ]]; then
    echo "scaffold bootstrap skipped: token file missing: $token_file" >&2
    return 0
  fi
  if ! command -v git >/dev/null 2>&1; then
    echo "scaffold bootstrap skipped: git not found" >&2
    return 0
  fi

  local tmp_dir git_config scaffold_commit scaffold_url selected_scaffold selection expected_scaffold_commit catalog_commit routing_reason routing_deviation
  tmp_dir="$(mktemp -d "${TMPDIR:-/tmp}/enoch-scaffold-bootstrap.XXXXXX")"
  git_config="$tmp_dir/gitconfig"
  cleanup_scaffold_tmp() { rm -rf "$tmp_dir"; }
  trap cleanup_scaffold_tmp RETURN

  {
    printf '[http "http://100.114.53.78:8000/"]\n'
    printf '\textraHeader = Authorization: token %s\n' "$(tr -d '\n' <"$token_file")"
  } >"$git_config"
  chmod 600 "$git_config"

  if [[ -n "$direct_scaffold_url" ]]; then
    scaffold_url="$direct_scaffold_url"
    selected_scaffold="direct-url"
    expected_scaffold_commit="$direct_scaffold_commit"
    catalog_commit=""
    routing_reason="direct ENOCH_SCAFFOLD_URL override"
    routing_deviation="direct-url"
  else
    GIT_CONFIG_GLOBAL="$git_config" git clone --depth 1 "$catalog_url" "$tmp_dir/catalog" >&2
    catalog_commit="$(GIT_CONFIG_GLOBAL="$git_config" git -C "$tmp_dir/catalog" rev-parse HEAD)"
    if ! selection="$(python3 - <<'PY_SELECT_SCAFFOLD' "$tmp_dir/catalog" "$requested_scaffold" "$PROJECT_ID" "$PROJECT_DIR" "$PROMPT_FILE"
from __future__ import annotations
import json
import pathlib
import sys

catalog_root = pathlib.Path(sys.argv[1])
requested = sys.argv[2]
project_id = sys.argv[3]
project_dir = pathlib.Path(sys.argv[4])
prompt_file = pathlib.Path(sys.argv[5])

def _sanitize_field(value: object) -> str:
    return str(value).replace("\t", " ").replace("\n", " ").strip()

def _prompt_text(path: pathlib.Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:20000]
    except OSError:
        return ""

def route_scaffold(names: set[str], default: str) -> tuple[str, str, str]:
    if requested:
        return requested, "explicit ENOCH_SCAFFOLD_NAME override", "explicit-override"
    corpus = "\n".join([project_id, project_dir.name, str(project_dir), _prompt_text(prompt_file)]).lower()
    rules: list[tuple[str, str, tuple[str, ...]]] = [
        ("scaffold-enoch-agent-evidence-ledger", "matched evidence-ledger/falsifiable-claim/drift-trap intent", ("evidence-ledger", "evidence ledger", "falsifiable-claim", "falsifiable claim", "drift-trap", "drift trap")),
        ("scaffold-enoch-memory-agent-eval", "matched memory/retrieval/operator-doctrine/replay intent", ("memory", "retrieval", "operator-doctrine", "operator doctrine", "replay")),
        ("scaffold-enoch-gb10-gpu-experiment", "matched GB10/GPU/VRAM/CUDA/profiling intent", ("gb10", "gpu", "vram", "cuda", "profiling")),
        ("scaffold-enoch-speculative-decoding", "matched speculative-decoding/KV-cache/suffix/ngram/long-context-compression intent", ("speculative decoding", "speculative-decoding", "kv-cache", "kv cache", "suffix", "ngram", "n-gram", "long-context compression", "long context compression")),
        ("scaffold-enoch-benchmark-results", "matched benchmark/metrics/baseline/failure-cases intent", ("benchmark", "metrics", "baseline", "failure-cases", "failure cases")),
    ]
    for scaffold, reason, needles in rules:
        if scaffold in names and any(needle in corpus for needle in needles):
            return scaffold, reason, "none"
    if default in names:
        return default, "fallback to catalog default: no routing rule matched", "fallback-default"
    return "scaffold-enoch-worker-artifact", "fallback to worker artifact: no routing rule matched", "fallback-worker-artifact"

def load_catalog(path: pathlib.Path) -> dict[str, object]:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        try:
            return json.loads(text)
        except Exception as exc:  # pragma: no cover - exercised through shell integration.
            print(f"invalid scaffold catalog {path.name}: {exc}", file=sys.stderr)
            raise SystemExit(2) from exc

    # Minimal parser for the existing scaffold-catalog/catalog.yaml schema. Avoid
    # requiring PyYAML on production workers. Security invariant: only fields that
    # are direct children of a scaffold list item are accepted. More deeply nested
    # keys such as metadata.clone_url must never be promoted into the selected repo.
    catalog: dict[str, object] = {"scaffolds": []}
    scaffolds: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    in_scaffolds = False
    allowed_item_keys = {"name", "repo", "clone_url", "url", "commit", "scaffold_commit", "ref"}
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        stripped = line.strip()
        if not stripped:
            continue
        if not raw_line.startswith(" ") and stripped.endswith(":"):
            in_scaffolds = stripped == "scaffolds:"
            if not in_scaffolds and current is not None:
                scaffolds.append(current)
                current = None
            continue
        if not raw_line.startswith(" ") and ":" in stripped:
            key, value = stripped.split(":", 1)
            if key == "default":
                catalog["default"] = value.strip().strip('"\'')
            in_scaffolds = False
            continue
        if not in_scaffolds:
            continue
        if line.startswith("  - "):
            if current is not None:
                scaffolds.append(current)
            current = {}
            rest = line[4:].strip()
            if ":" in rest:
                key, value = rest.split(":", 1)
                key = key.strip()
                if key in allowed_item_keys:
                    current[key] = value.strip().strip('"\'')
            continue
        if current is not None and line.startswith("    ") and not line.startswith("     ") and ":" in stripped:
            key, value = stripped.split(":", 1)
            key = key.strip()
            if key in allowed_item_keys:
                current[key] = value.strip().strip('"\'')
    if current is not None:
        scaffolds.append(current)
    catalog["scaffolds"] = scaffolds
    return catalog

for relative in ("catalog.json", "scaffolds.json", ".scaffold-catalog.json", "catalog.yaml", "catalog.yml"):
    candidate = catalog_root / relative
    if candidate.is_file():
        catalog_path = candidate
        break
else:
    print("scaffold catalog missing catalog.json or catalog.yaml", file=sys.stderr)
    raise SystemExit(2)

catalog = load_catalog(catalog_path)
scaffolds = catalog.get("scaffolds")
if not isinstance(scaffolds, list):
    print("scaffold catalog must contain a scaffolds list", file=sys.stderr)
    raise SystemExit(2)

default_scaffold = str(catalog.get("default") or "scaffold-enoch-worker-artifact")
scaffold_names = {str(item.get("name")) for item in scaffolds if isinstance(item, dict) and item.get("name")}
wanted, routing_reason, routing_deviation = route_scaffold(scaffold_names, default_scaffold)

for item in scaffolds:
    if not isinstance(item, dict):
        continue
    if item.get("name") == wanted:
        repo = item.get("clone_url") or item.get("repo") or item.get("url")
        if not isinstance(repo, str) or not repo:
            print(f"scaffold {wanted} has no repo", file=sys.stderr)
            raise SystemExit(2)
        commit = item.get("commit") or item.get("scaffold_commit") or item.get("ref") or ""
        if commit is not None and not isinstance(commit, str):
            print(f"scaffold {wanted} has invalid commit pin", file=sys.stderr)
            raise SystemExit(2)
        print(f"{wanted}\t{repo}\t{commit}\t{_sanitize_field(routing_reason)}\t{_sanitize_field(routing_deviation)}")
        raise SystemExit(0)

print(f"unknown scaffold: {wanted}", file=sys.stderr)
raise SystemExit(2)
PY_SELECT_SCAFFOLD
)"; then
      return 2
    fi
    selected_scaffold="${selection%%$'\t'*}"
    selection="${selection#*$'\t'}"
    scaffold_url="${selection%%$'\t'*}"
    selection="${selection#*$'\t'}"
    expected_scaffold_commit="${selection%%$'\t'*}"
    selection="${selection#*$'\t'}"
    routing_reason="${selection%%$'\t'*}"
    if [[ "$selection" == *$'\t'* ]]; then
      routing_deviation="${selection#*$'\t'}"
    else
      routing_deviation="none"
    fi
  fi

  python3 - <<'PY_VALIDATE_SCAFFOLD_URL' "$scaffold_url" "$allowed_base_urls" "$allow_file_urls" "$require_pin" "$expected_scaffold_commit"
from __future__ import annotations
import re
import sys
from urllib.parse import urlparse

url, allowed_bases_raw, allow_file_raw, require_pin_raw, expected_commit = sys.argv[1:]
allow_file = allow_file_raw.lower() in {"1", "true", "yes"}
require_pin = require_pin_raw.lower() not in {"0", "false", "no"}
parsed = urlparse(url)
if parsed.scheme == "file":
    if not allow_file:
        print("untrusted scaffold URL: file URLs disabled", file=sys.stderr)
        raise SystemExit(2)
elif parsed.scheme in {"http", "https"}:
    if parsed.username or parsed.password:
        print("untrusted scaffold URL: credentials in URL are forbidden", file=sys.stderr)
        raise SystemExit(2)
    allowed_bases = [base.strip().rstrip("/") + "/" for base in allowed_bases_raw.split(",") if base.strip()]
    if not any(url.startswith(base) for base in allowed_bases):
        print(f"untrusted scaffold URL: {url}", file=sys.stderr)
        raise SystemExit(2)
else:
    print(f"untrusted scaffold URL scheme: {parsed.scheme or 'missing'}", file=sys.stderr)
    raise SystemExit(2)
if expected_commit and not re.fullmatch(r"[0-9a-fA-F]{40}", expected_commit):
    print("invalid scaffold commit pin: expected full 40-character hex commit", file=sys.stderr)
    raise SystemExit(2)
if require_pin and parsed.scheme != "file" and not expected_commit:
    print("scaffold commit pin required for non-file scaffold URL", file=sys.stderr)
    raise SystemExit(2)
PY_VALIDATE_SCAFFOLD_URL

  echo "scaffold selected: $selected_scaffold -> $scaffold_url" >&2
  GIT_CONFIG_GLOBAL="$git_config" git clone --depth 1 "$scaffold_url" "$tmp_dir/scaffold" >&2
  scaffold_commit="$(GIT_CONFIG_GLOBAL="$git_config" git -C "$tmp_dir/scaffold" rev-parse HEAD)"
  if [[ -n "$expected_scaffold_commit" && "$scaffold_commit" != "$expected_scaffold_commit" ]]; then
    echo "scaffold commit mismatch: expected $expected_scaffold_commit got $scaffold_commit" >&2
    return 2
  fi

  (cd "$tmp_dir/scaffold" && tar --exclude .git -cf - .) | (cd "$PROJECT_DIR" && tar -xf -)
  if [[ -x "$PROJECT_DIR/.scaffold/bootstrap.sh" ]]; then
    (cd "$PROJECT_DIR" && bash .scaffold/bootstrap.sh) >&2
  fi
  if [[ -x "$PROJECT_DIR/.scaffold/smoke.sh" ]]; then
    (cd "$PROJECT_DIR" && bash .scaffold/smoke.sh) >&2
  fi
  python3 - <<'PY_SCAFFOLD_USED' "$PROJECT_DIR/.scaffold-used.yaml" "$scaffold_url" "$scaffold_commit" "$selected_scaffold" "$catalog_commit" "$routing_reason" "$routing_deviation"
from __future__ import annotations
import pathlib, sys
path = pathlib.Path(sys.argv[1])
scaffold_url = sys.argv[2]
scaffold_commit = sys.argv[3]
selected_scaffold = sys.argv[4]
catalog_commit = sys.argv[5]
routing_reason = sys.argv[6]
routing_deviation = sys.argv[7]
text = path.read_text(encoding="utf-8") if path.exists() else ""
values = {
    "scaffold_commit": scaffold_commit,
    "scaffold_source_url": scaffold_url,
    "scaffold_selected_name": selected_scaffold,
    "scaffold_catalog_commit": catalog_commit or "none",
    "scaffold_routing_reason": routing_reason or "none",
    "scaffold_routing_deviation": routing_deviation or "none",
}
lines = []
seen: set[str] = set()
for line in text.splitlines():
    key = line.split(":", 1)[0]
    if key in values:
        lines.append(f"{key}: {values[key]}")
        seen.add(key)
    else:
        lines.append(line)
for key, value in values.items():
    if key not in seen:
        lines.append(f"{key}: {value}")
path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
PY_SCAFFOLD_USED
  echo "scaffold bootstrap ok: $scaffold_url@$scaffold_commit" >&2
}

bootstrap_scaffold
cd "$PROJECT_DIR"

export ENOCH_RUN_ID="$RUN_ID"
export ENOCH_PROJECT_ID="$PROJECT_ID"
export ENOCH_PROJECT_DIR="$PROJECT_DIR"
export ENOCH_LAUNCH_ROOT_PID="$$"
export ENOCH_LAUNCH_PGID="$(ps -o pgid= -p $$ | tr -d ' ')"
export PATH="$HOME/.nvm/versions/node/v22.22.1/bin:$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"
export PYTHONPATH="$REPO_ROOT:${PYTHONPATH:-}"
# Upstream Codex still recognizes this variable; keep disabled by default to avoid legacy OMX wrappers.
export USE_OMX_EXPLORE_CMD="${USE_OMX_EXPLORE_CMD:-0}"

CODEX_BIN="${CODEX_BIN:-$(command -v codex || true)}"
if [[ -z "$CODEX_BIN" ]]; then
  echo "codex binary not found in PATH" >&2
  exit 127
fi
case "$CODEX_BIN" in
  "$PROJECT_DIR"/*|./*|../*|codex)
    echo "refusing project-relative codex binary: $CODEX_BIN" >&2
    exit 126
    ;;
esac
CODEX_BIN="$(readlink -f "$CODEX_BIN")"
case "$CODEX_BIN" in
  "$PROJECT_DIR"/*)
    echo "refusing project-local codex binary: $CODEX_BIN" >&2
    exit 126
    ;;
esac

JSON_LOG="$PROJECT_DIR/.enoch/logs/${RUN_ID}.codex.jsonl"
LAST_MESSAGE="$PROJECT_DIR/.enoch/last_message.md"
SESSION_FILE="$PROJECT_DIR/.enoch/session.json"
STARTED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
EXIT_CODE=0

build_common_args() {
  printf '%s\0' \
    "--skip-git-repo-check" \
    "--json" \
    "--output-last-message" "$LAST_MESSAGE" \
    "--sandbox" "$SANDBOX" \
    "-C" "$PROJECT_DIR" \
    "-c" "model_reasoning_effort=\"$REASONING_EFFORT\""
}

# Run Codex directly. OMX is intentionally not in this execution path.
if [[ "$MODE" == "resume" ]]; then
  cmd=("$CODEX_BIN" "exec" "resume")
  if [[ "$USE_LAST" -eq 1 ]]; then
    cmd+=("--last")
  elif [[ -n "$SESSION_ID" ]]; then
    cmd+=("$SESSION_ID")
  else
    echo "resume mode requires --session-id or --last" >&2
    exit 2
  fi
  cmd+=("--json" "--output-last-message" "$LAST_MESSAGE")
  if [[ -n "$MODEL" ]]; then cmd+=("--model" "$MODEL"); fi
  cmd+=("-" )
else
  cmd=("$CODEX_BIN" "exec" "--skip-git-repo-check" "--json" "--output-last-message" "$LAST_MESSAGE" "--sandbox" "$SANDBOX" "-C" "$PROJECT_DIR" "-c" "model_reasoning_effort=\"$REASONING_EFFORT\"")
  if [[ -n "$MODEL" ]]; then cmd+=("--model" "$MODEL"); fi
  cmd+=("-" )
fi

set +e
"${cmd[@]}" <"$PROMPT_FILE" >"$JSON_LOG" 2>"$PROJECT_DIR/.enoch/logs/${RUN_ID}.codex.stderr.log"
EXIT_CODE=$?
set -e
ENDED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

python3 - <<'PY' "$JSON_LOG" "$SESSION_FILE" "$RUN_ID" "$PROJECT_ID" "$STARTED_AT" "$ENDED_AT" "$EXIT_CODE"
import json, sys
log_path, session_file, run_id, project_id, started_at, ended_at, exit_code = sys.argv[1:]
session_id = ""
last_type = ""
try:
    with open(log_path, "r", encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            try:
                obj = json.loads(line)
            except Exception:
                continue
            last_type = str(obj.get("type") or obj.get("event") or last_type)
            for key in ("session_id", "conversation_id", "thread_id"):
                value = obj.get(key)
                if isinstance(value, str) and value:
                    session_id = value
            payload = obj.get("payload")
            if isinstance(payload, dict):
                for key in ("session_id", "conversation_id", "thread_id"):
                    value = payload.get(key)
                    if isinstance(value, str) and value:
                        session_id = value
except FileNotFoundError:
    pass
if not session_id:
    session_id = f"codex-native:{run_id}"
with open(session_file, "w", encoding="utf-8") as fh:
    json.dump({
        "runner": "codex",
        "run_id": run_id,
        "project_id": project_id,
        "session_id": session_id,
        "started_at": started_at,
        "ended_at": ended_at,
        "exit_code": int(exit_code),
        "json_log": log_path,
        "last_event_type": last_type,
    }, fh, indent=2, sort_keys=True)
    fh.write("\n")
print(session_id)
PY
SESSION_ID_EFFECTIVE="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("session_id", ""))' "$SESSION_FILE")"

# Legacy artifact readers may still inspect .omx. Keep the decision file path compatible
# while the canonical worker output moves to .enoch.
if [[ -f "$PROJECT_DIR/.enoch/project_decision.json" && ! -f "$PROJECT_DIR/.omx/project_decision.json" ]]; then
  cp "$PROJECT_DIR/.enoch/project_decision.json" "$PROJECT_DIR/.omx/project_decision.json"
fi
if [[ -f "$PROJECT_DIR/.enoch/metrics.json" && ! -f "$PROJECT_DIR/.omx/metrics.json" ]]; then
  cp "$PROJECT_DIR/.enoch/metrics.json" "$PROJECT_DIR/.omx/metrics.json"
fi

CALLBACK_EVENT="wake_ready"
CALLBACK_GATE="wake_ready"
CALLBACK_REASON="codex runner completed"
if [[ "$EXIT_CODE" -ne 0 ]]; then
  CALLBACK_EVENT="gate_error"
  CALLBACK_GATE="gate_error"
  CALLBACK_REASON="codex runner exited nonzero: $EXIT_CODE"
fi

if [[ -n "$CALLBACK_URL" && -n "$CALLBACK_TOKEN" ]]; then
  CALLBACK_PAYLOAD_FILE="$PROJECT_DIR/.enoch/state/${RUN_ID}.callback_payload.json"
  python3 - <<'PY_CALLBACK_PAYLOAD' "$CALLBACK_PAYLOAD_FILE" "$RUN_ID" "$SESSION_ID_EFFECTIVE" "$PROJECT_ID" "$CALLBACK_EVENT" "$CALLBACK_GATE" "$CALLBACK_REASON" "$EXIT_CODE" "$PROJECT_DIR" "$STARTED_AT" "$ENDED_AT"
import json, pathlib, sys
(
    payload_file, run_id, session_id, project_id, event_type, gate_state,
    reason, exit_code, project_dir, started_at, ended_at,
) = sys.argv[1:]
payload = {
    "event_type": event_type,
    "run_id": run_id,
    "session_id": session_id,
    "project_id": project_id,
    "project_name": project_id,
    "source_event": "codex-runner-exit",
    "gate_state": gate_state,
    "process_tracking": {
        "root_pid": None,
        "process_group_id": None,
        "processes": [],
        "live_process_count": 0,
    },
    "telemetry": {
        "runner": "codex",
        "exit_code": int(exit_code),
        "project_dir": project_dir,
        "started_at": started_at,
        "ended_at": ended_at,
    },
    "reason": reason,
    "idempotency_key": f"{run_id}:{event_type}:codex-runner:{ended_at}",
}
path = pathlib.Path(payload_file)
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY_CALLBACK_PAYLOAD
  callback_outbox write --state-dir "$WORKER_STATE_DIR" --payload-file "$CALLBACK_PAYLOAD_FILE" >/dev/null
  if printf '%s' "$CALLBACK_TOKEN" | callback_outbox deliver --state-dir "$WORKER_STATE_DIR" --run-id "$RUN_ID" --url "$CALLBACK_URL" --token-stdin --timeout "$CALLBACK_TIMEOUT"; then
    true
  else
    echo "callback delivery failed; durable callback outbox will retry: $WORKER_STATE_DIR/callback_outbox/${RUN_ID}.json" >&2
  fi
else
  echo "completion callback not configured; leaving local artifacts only" >&2
fi

exit "$EXIT_CODE"
