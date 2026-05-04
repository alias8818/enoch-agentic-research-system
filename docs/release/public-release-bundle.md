# Public release bundle push protocol

Use `scripts/push_public_release_bundle.py` when a corpus-count or public-release change touches more than one repo.

Why this exists: the corpus repo's **Public release integrity** workflow checks out the system, docs, profile, and profile-site repos from their current `main` branches. If the corpus repo is pushed before those sibling repos are visible on GitHub, CI can report false manifest/count drift even though the local bundle is internally consistent.

## Safe workflow

From `enoch-agentic-research-system`:

```bash
python3 scripts/push_public_release_bundle.py
```

This preflight:

- requires all release repos to be on `main`, clean, and not behind `origin/main`
- regenerates the ecosystem manifest from the local corpus/docs state
- validates public release copy and counts across local repos
- prints the planned race-safe order

When preflight passes:

```bash
python3 scripts/push_public_release_bundle.py --push --watch
```

The script pushes and verifies remote SHAs in this order:

1. `enoch-agentic-research-system`
2. `enoch-docs`
3. `alias8818`
4. `alias8818.github.io`
5. `enoch-ai-research-corpus`

The corpus repo is intentionally last because its cross-repo workflow reads the other repos from remote `main`.

## Paper ledger reconciliation gate

Before saying the corpus is current or that there are no papers left to write, reconcile the separate ledgers explicitly:

```bash
ENOCH_CONTROL_TOKEN="$TOKEN" \
  python3 scripts/reconcile_paper_ledgers.py \
  --control-url http://192.168.1.166:8787 \
  --corpus ../enoch-ai-research-corpus \
  --require-synced
```

This check compares live draft eligibility, finalized control-plane review rows, and the public corpus index. A nonzero exit means at least one ledger is not aligned; do not claim the release count is final until the report is clean.

## Stop rule

Do not manually push the corpus repo first during a multi-repo count update. If the script fails, fix the indicated repo state and rerun it; do not rerun noisy CI until the remote SHAs are synchronized.
