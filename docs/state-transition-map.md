# Enoch state transition map

Status: active operator contract as of 2026-05-06.

This is the grade-school lifecycle map for ideas, projects, runs, papers, publication, and corpus import. It is intentionally smaller than the raw database vocabulary. Raw states remain compatibility/detail evidence; operator lanes answer what a human or agent should do next.

```text
Idea -> Queue -> Run -> Decision -> Paper -> Publication -> Corpus
```

## Transition table

| Step | From -> To | Source of truth | Writer/owner | Validation gate | Invalid/impossible transition | Operator lane shown |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | Idea -> Queue | `ideas` and `queue_items` in Supabase | Supabase idea importer / queue projection | Queue row has stable `project_id`, title, priority, machine/model/sandbox policy | Notion/source metadata overwriting Supabase-owned runtime fields | `ready_queue` or `paused` |
| 2 | Queue -> Run | `queue_items.current_run_id`, `runs` | Control-plane dispatch path | Queue is not paused, worker preflight passes, dispatch writes a run id | Dispatch while maintenance/paused or without fresh worker evidence | `running` |
| 3 | Run -> Decision | `runs`, project-local `.omx/project_decision.json`, `project_decisions` | Worker callback reconciliation | Wake/callback delivery is recorded and decision artifact is parsed/synced | Treating `wake_ready`, `completed`, or `session_finished_ready` as positive by itself | `complete_no_paper` until a positive decision gate exists |
| 4 | Decision -> Paper | `project_decisions.decision_gate_state` plus paper ledger absence | Explicit bounded paper drafting | Decision gate is `positive` and no live paper row exists for the project/run | Negative, missing, malformed, unknown, ambiguous, or already-papered work becoming writable | `write_paper` only when positive/actionable |
| 5 | Paper -> Publication | `papers.paper_status`, `publication_automation_items` | Publication automation / finalizer | Draft exists and automation produces a finalization package | Human approval/review vocabulary as the normal path | `automate_publication` |
| 6 | Publication -> Corpus | `publication_automation_items.finalized` plus `corpus_imports` ledger | Corpus import script and public release validator | Publication draft has finalized package; public corpus index includes sanitized artifact by source fingerprint; Supabase ledger records the import | Counting all finalized rows as actionable publish/import work | `ready_to_publish` only while missing corpus import, then `published`/public corpus evidence |
| 7 | Corpus -> Public release/HF | `papers/index.json`, `quality/*`, `site/ecosystem.json`, HF `dataset_summary.json` | Public release bundle push and HF export | Generated manifest and public release validation pass; HF JSONL row count matches | Hand-edited public counts or stale GitHub/HF metadata | Public/corpus count, not active operator work |

## Hard invariants

1. `write_paper` requires a positive project decision gate and no existing live paper row.
2. `complete_no_paper` is the correct operator lane for negative, missing, malformed, unknown, or ambiguous decisions.
3. `wake_ready` and `session_finished_ready` mean worker delivery, not outcome polarity.
4. `publication_draft` alone is not public; corpus import is separate from finalization.
5. `paper_pipeline.raw_completed_no_paper_candidates` is informational only; it must equal `write_needed + not_writable_by_decision_gate`.
6. Dashboard `operator_counts` may contain canonical operator lanes and aggregate keys only; detail stages belong in `operator_detail_counts` or debug drill-downs.
7. Public counts come from `papers/index.json` through `generate_ecosystem_manifest.py` and `validate_public_release.py`, then the Hugging Face export must match the same count.

## Operator question mapping

| Operator question | Trust this field/surface | Do not substitute |
| --- | --- | --- |
| What needs me? | `operator_counts.needs_attention` and `needs_operator` rows | Raw `needs_review` strings |
| What is running? | `counts.active`, `operator_counts.running`, active rows | Stale historical `runs.state` values |
| What can be written? | `paper_pipeline.write_needed` | Raw completed/no-paper candidates |
| What can be finalized? | `paper_pipeline.finalize_needed` | Draft row existence alone |
| What can be published/imported? | `paper_pipeline.publish_ready` / `missing_from_corpus` | `publication_draft` count or all finalized rows |
| What is already public? | `paper_pipeline.published_imported`, `corpus_imports`, public corpus `papers/index.json`, `site/ecosystem.json`, HF `dataset_summary.json` | Control-plane paper row count |

## Validation commands

```bash
uv run pytest -q tests/test_state_transition_map.py tests/test_control_plane_operator_status.py tests/test_state_doctor.py
uv run python scripts/state_doctor.py --database-url "$ENOCH_SUPABASE_DATABASE_URL" --control-url "$ENOCH_CONTROL_URL" --token-file /path/to/token --corpus ../enoch-ai-research-corpus
python3 scripts/generate_ecosystem_manifest.py --corpus ../enoch-ai-research-corpus --docs ../enoch-docs --output /tmp/enoch-ecosystem.generated.json
python3 scripts/sync_corpus_import_ledger.py --corpus ../enoch-ai-research-corpus --sql-output /tmp/enoch-sync-corpus-imports.sql
python3 scripts/validate_public_release.py --system . --corpus ../enoch-ai-research-corpus --docs ../enoch-docs --profile ../alias8818.github.io --owner-profile ../alias8818 --generated-manifest /tmp/enoch-ecosystem.generated.json
```
