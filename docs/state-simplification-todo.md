# State simplification TODO

Status: active next-phase backlog after the Supabase state-contract cleanup on 2026-05-06. State doctor command is implemented; corpus/publication/public-count reconciliation is clean across local corpus, GitHub public surfaces, and Hugging Face export.

The current state model is coherent and live-clean. The next work is to make the operator experience even simpler: actions first, raw states only as drill-down evidence.

## 1. Operator dashboard polish

- [ ] Rework overview cards around grade-school operator questions:
  - What needs me?
  - What is running?
  - What can be written?
  - What can be published?
  - What is done / no paper?
- [ ] Hide raw state/detail fields by default and keep them in debug/detail drawers only.
- [ ] Keep paper cards tied to `paper_pipeline.write_needed`, `finalize_needed`, and `publish_ready`, not raw paper statuses.

## 2. State transition map

- [ ] Add a one-page lifecycle map: Idea -> Queue -> Run -> Decision -> Paper -> Publication -> Corpus.
- [ ] For each transition, document:
  - source of truth;
  - writer/owner;
  - validation gate;
  - impossible/invalid transitions;
  - operator lane shown in the dashboard.
- [ ] Add tests or validators for any transition that is currently implicit.

## 3. Corpus/publication reconciliation

- [x] Reconcile `publication_draft`, `ready_to_publish`, corpus import ledger, and public repo count.
- [x] Verify/update Hugging Face count after the corpus repo commit is published.
- [x] Produce one canonical answer for: what is actually public locally.
- [x] Make stale public count drift fail validation/CI where possible.
- [x] Keep public labels/counts generated from a single source or deterministic manifest path.

## 4. Retire Notion assumptions

- [ ] Make Supabase `ideas` the primary editable intake/workbench source of truth.
- [ ] Keep Notion IDs/URLs as provenance only.
- [ ] Rename primary UI/docs language away from Notion where it is no longer the runtime owner.
- [ ] Audit import/re-ingest paths so source metadata cannot overwrite Supabase-owned runtime fields.

## 5. Add a state doctor command

- [x] Add one command/report that future agents run before answering state questions.
- [x] Include:
  - state contract validation;
  - normalization dry-run row count;
  - nonzero legacy/alias/migrate-after-freeze rows;
  - write-needed/raw/no-paper counts;
  - publication-ready/imported/public counts;
  - dashboard operator-count keys;
  - live service health/smoke status.
- [x] Fail loudly on mixed ledgers, stale public counts, or raw detail stages in primary operator counts.
- [x] Document the command in `docs/state-model.md` and the parent wiki.

## Preferred execution order

1. State doctor command. (done)
2. Corpus/publication reconciliation. (done)
3. Dashboard polish.
4. State transition map.
5. Notion-runtime retirement.

## Current known live baseline

Last verified on 2026-05-06:

- `write_needed = 0`
- `raw_completed_no_paper_candidates = 220`
- `not_writable_by_decision_gate = 220`
- `finalize_needed = 0`
- `publish_ready = 491`
- paper rows: `publication_draft = 494`, `archived = 2`, `all = 496`
- state normalization dry-run: `0` rows
- live state contract: OK
- state doctor: OK; corpus reconciliation reports 0 importable finalized publication drafts after local corpus import

## State doctor evidence

Command shape for the live validation artifact:

```bash
uv run python scripts/state_doctor.py \
  --database-url "$ENOCH_SUPABASE_DATABASE_URL" \
  --control-url "$ENOCH_CONTROL_URL" \
  --token-file /path/to/enoch-control-plane-token.txt \
  --corpus ../enoch-ai-research-corpus \
  --output path/to/state-doctor.json
```

Last observed state doctor result on 2026-05-06:

- exit code: `0`
- failure reason: none
- `state_contract.ok`: OK
- `normalization.total_rows`: `0`
- `control_plane.overview`: OK
- `paper_pipeline.write_needed`: `0`
- `paper_pipeline.raw_completed_no_paper_candidates`: `220`
- `paper_pipeline.not_writable_by_decision_gate`: `220`
- `paper_pipeline.finalize_needed`: `0`
- `paper_pipeline.publish_ready`: `491`
- `corpus_reconciliation.live_finalized_publication_draft_count`: `491`
- `corpus_reconciliation.public_corpus_count`: `495`
- `corpus_reconciliation.importable_finalized_count`: `0`

## Hugging Face evidence

Last verified on 2026-05-06 after publishing `aliasocracy/enoch-ai-research-corpus`:

- `dataset_summary.artifact_count`: `495`
- `dataset_summary.strict_claim_evidence_total_count`: `495`
- `data/artifacts.jsonl` rows: `495`
