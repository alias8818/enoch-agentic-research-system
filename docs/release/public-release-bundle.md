# Public release bundle push protocol

Use `scripts/push_public_release_bundle.py` when a corpus-count or public-release change touches more than one repo.

Why this exists: the corpus repo's **Public release integrity** workflow checks out the system, docs, profile, and profile-site repos from their current `main` branches. If the corpus repo is pushed before those sibling repos are visible on GitHub, CI can report false manifest/count drift even though the local bundle is internally consistent.

## Safe workflow

From `enoch-agentic-research-system`:

```bash
python3 scripts/push_public_release_bundle.py
```

If the change includes corpus imports and you need dashboard publish/import counts updated at the same time, include the ledger sync during preflight:

```bash
python3 scripts/push_public_release_bundle.py --sync-corpus-ledger --ledger-use-linked
```

Use `--ledger-database-url` or `ENOCH_CONTROL_DATABASE_URL` when a direct Postgres URL is available. Older `ENOCH_SUPABASE_DATABASE_URL` naming is compatibility-only. The ledger sync reads `../enoch-ai-research-corpus/papers/index.json`, matches live paper rows by `source_record_fingerprint`, and updates `corpus_imports` so `publish_ready` means missing-corpus work only.

This preflight:

- requires all release repos to be on `main`, clean, and not behind `origin/main`
- validates current-runtime snapshot links in the system docs
- runs the docs repo validator, including Mintlify navigation and runtime snapshot-link checks
- regenerates the ecosystem manifest from the local corpus/docs state
- validates public release copy and counts across local repos
- prints the planned race-safe order

When preflight passes:

```bash
python3 scripts/push_public_release_bundle.py --sync-corpus-ledger --ledger-use-linked --push --watch
```

The script pushes and verifies remote SHAs in this order:

1. `enoch-agentic-research-system`
2. `enoch-docs`
3. `alias8818`
4. `alias8818.github.io`
5. `enoch-ai-research-corpus`

The corpus repo is intentionally last because its cross-repo workflow reads the other repos from remote `main`.


## One-command corpus release workflow

For the broader agentic path from finalized control-plane papers to public corpus/HF/dashboard accounting, use:

```bash
python3 scripts/run_public_corpus_release.py \
  --import-from-control-plane \
  --build-hf \
  --reconcile-control-plane \
  --sync-corpus-ledger \
  --ledger-use-linked
```

Add `--publish-hf` only when the Hugging Face write token is present and you intend to publish. Run with `--dry-run` first when changing flags. This workflow does not push git repos; use `push_public_release_bundle.py --sync-corpus-ledger --push --watch` after reviewing and committing the changed release surfaces.

## Corpus ledger reconciliation gate

Before saying the public corpus is current, reconcile the finalized publication-draft lane against the corpus index:

```bash
ENOCH_CONTROL_TOKEN="$TOKEN" \
  python3 scripts/reconcile_paper_ledgers.py \
  --control-url http://<control-plane-host>:8787 \
  --corpus ../enoch-ai-research-corpus \
  --require-synced
```

This check compares finalized control-plane `publication_draft` rows and the public corpus index. A nonzero exit means the corpus import lane is not aligned; do not claim the release count is final until the report is clean. If the report is clean but the dashboard still shows publish/import work, run the bundle script with `--sync-corpus-ledger` so the control-plane `corpus_imports` ledger catches up to the public index.

Do not mix old-system finalized `draft_review` rows into the publish backlog; they are historical automation records, not current corpus work. Use `--paper-status '' --verbose` only when deliberately auditing legacy exact-fingerprint drift. Use `--include-draft-candidate` only when separately checking whether new papers still need to be written.

## Stop rule

Do not manually push the corpus repo first during a multi-repo count update. If the script fails, fix the indicated repo state and rerun it; do not rerun noisy CI until the remote SHAs are synchronized.
