#!/usr/bin/env bash
set -euo pipefail

# Applies GitHub repository hardening after the repositories are public or the
# account/organization has branch-protection support for private repositories.
# This script intentionally does not change repository visibility.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SYSTEM_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ECOSYSTEM_MANIFEST="${ECOSYSTEM_MANIFEST:-$SYSTEM_ROOT/site/ecosystem.json}"

CODE_REPO="${CODE_REPO:-alias8818/enoch-agentic-research-system}"
CORPUS_REPO="${CORPUS_REPO:-alias8818/enoch-ai-research-corpus}"
PROMISING_REPO="${PROMISING_REPO:-alias8818/enoch-promising-signals}"

manifest_count() {
  local key="$1"
  python3 - "$ECOSYSTEM_MANIFEST" "$key" <<'PY'
import json
import sys
from pathlib import Path

manifest_path = Path(sys.argv[1])
key = sys.argv[2]
if not manifest_path.exists():
    raise SystemExit(f"ecosystem manifest not found: {manifest_path}")
value = json.loads(manifest_path.read_text(encoding="utf-8")).get(key)
if not isinstance(value, int) or value < 0:
    raise SystemExit(f"ecosystem manifest key {key!r} must be a non-negative integer")
print(value)
PY
}

CORPUS_COUNT="${CORPUS_COUNT:-$(manifest_count artifact_count)}"
PROMISING_SIGNAL_COUNT="${PROMISING_SIGNAL_COUNT:-$(manifest_count promising_signal_count)}"

repo_edit() {
  local repo="$1" desc="$2" topics="$3"
  gh repo edit "$repo" \
    --description "$desc" \
    --enable-issues=true \
    --enable-projects=false \
    --enable-wiki=false \
    --enable-discussions=true \
    --delete-branch-on-merge=true \
    --allow-update-branch=true \
    --enable-squash-merge=true \
    --squash-merge-commit-message pr-title-description \
    --enable-merge-commit=false \
    --enable-rebase-merge=false \
    --add-topic "$topics"
  gh api -X PUT "repos/$repo/vulnerability-alerts" --silent || true
  gh api -X PUT "repos/$repo/private-vulnerability-reporting" --silent || true
  gh repo edit "$repo" --enable-secret-scanning 2>/dev/null || true
  gh repo edit "$repo" --enable-secret-scanning-push-protection 2>/dev/null || true
}

protect_branch() {
  local repo="$1" contexts_json="$2"
  python3 - "$contexts_json" <<'PY' >/tmp/enoch-branch-protection.json
import json, sys
contexts=json.loads(sys.argv[1])
print(json.dumps({
  "required_status_checks": {"strict": True, "contexts": contexts},
  "enforce_admins": True,
  "required_pull_request_reviews": {
    "dismiss_stale_reviews": True,
    "require_code_owner_reviews": True,
    "required_approving_review_count": 1,
    "require_last_push_approval": False
  },
  "restrictions": None,
  "required_linear_history": True,
  "allow_force_pushes": False,
  "allow_deletions": False,
  "required_conversation_resolution": True,
  "lock_branch": False,
  "allow_fork_syncing": True
}))
PY
  gh api -X PUT "repos/$repo/branches/main/protection" --input /tmp/enoch-branch-protection.json
}

repo_edit "$CODE_REPO" \
  "Agentic research control plane: queue state, worker preflight, wake-gated execution, evidence sync, dashboard, alerts, and AI-generated paper packaging." \
  "agentic-ai,research-automation,control-plane,langgraph,wake-gate,local-ai"
repo_edit "$CORPUS_REPO" \
  "$CORPUS_COUNT AI-generated research artifacts produced by Enoch, packaged with provenance metadata, evidence bundles, claim ledgers, manifests, and packaging/provenance reports." \
  "ai-generated,research-corpus,agentic-ai,provenance,claim-ledger,local-ai"
repo_edit "$PROMISING_REPO" \
  "$PROMISING_SIGNAL_COUNT bounded Enoch promising signals preserved for larger-compute follow-up; not validated papers, not peer reviewed, and separate from the paper corpus." \
  "ai-generated,research-signals,agentic-ai,local-ai,research-automation,provenance"

protect_branch "$CODE_REPO" '["tests", "public-release-integrity", "secret-scan"]'
protect_branch "$CORPUS_REPO" '["quality", "public-release-integrity", "secret-scan"]'
protect_branch "$PROMISING_REPO" '["quality", "public-release-integrity", "secret-scan"]'
