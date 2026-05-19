# Notion Source Backfill Review

Purpose: test whether the old Notion `Enoch’s Ideas` database can repair the `sources:required` failures from the promising-signal export audit.

## Inputs

- Notion database: `https://www.notion.so/324e3677f1c6806390f1dee4aad15cca`
- Notion data source: `collection://324e3677-f1c6-80a7-8e51-000b5502abdc`
- Notion view: `view://324e3677-f1c6-805c-aee2-000c80915f53`
- Missing-source project rows checked: 70

## Result

| Check | Count |
| --- | ---: |
| child project rows found | 70 |
| child rows with notion page url | 0 |
| parent followup title matches | 70 |
| parent rows with notion page url | 0 |
| parent rows with idea source external url | 0 |
| parent rows with research source records | 0 |
| deterministically backfillable from notion or parent sources | 0 |

## Determination

The old Notion database is useful as historical/operator context, but it is not a deterministic source-provenance backfill for these rows.

Reasons:

- The Notion schema has a system page `url` and OMX tracking/status fields, but no explicit research source/provenance URL property.
- Exact live-control-plane mapping found all 70 child projects and all 70 parent follow-up decisions by `paper_eligibility.followup_title`, but neither child nor parent project rows have Notion page URLs.
- Parent rows also have no `idea_workbench.source_external_url` and no `research_lineage`/`research_sources` records.
- Therefore, using Notion page URLs or semantic title matches as `sources` would turn historical bookkeeping into publication provenance, which violates the project rule that system truth needs a deterministic enforceable source.

## Safe next step

Backfill should use deterministic control-plane lineage and explicit `research_sources` records only. For these 70 rows, the repair is not to infer from Notion; it is to add/repair source capture at candidate generation/follow-up launch time, then rerun future exports. Existing rows can only be exported after a real source record is attached through a deterministic migration with auditable evidence.

## Sample matched rows

- `acceptance-aware-gpt-2-small-early-exit-heads-for-exact-se-bc1a42be2d` ← parent `end-to-end-gpt-2-small-self-speculative-decoding-with-trai-f29c835448`; child Notion URL=False; parent Notion URL=False; parent source records=0
- `activation-aware-calibration-for-static-residual-adapters-08e1f264dc` ← parent `static-parameter-matched-residual-adapters-for-1-bit-recov-8ee68488ea`; child Notion URL=False; parent Notion URL=False; parent source records=0
- `adaptive-or-periodically-corrected-low-rank-adamw-for-smal-afbae3b446` ← parent `efficient-hybrid-low-rank-adamw-update-for-small-lm-traini-c8a1d93ce9`; child Notion URL=False; parent Notion URL=False; parent source records=0
- `adaptive-rank-anchor-kv-compression-on-gpt-2-small-class-l-003174ac4a` ← parent `rank-anchor-frontier-for-quality-bounded-low-rank-kv-compr-4a9a64cb1e`; child Notion URL=False; parent Notion URL=False; parent source records=0
- `behavior-aware-learned-kv-residual-prediction-for-exact-an-b76f7664e0` ← parent `adaptive-exact-anchors-with-learned-cross-layer-kv-residua-ebc41d5055`; child Notion URL=False; parent Notion URL=False; parent source records=0
- `blockwise-stabilized-4-bit-adam-second-moment-on-a-small-t-d75abbd657` ← parent `stabilized-4-bit-adam-second-moment-with-nonzero-floors-or-edf4b768b1`; child Notion URL=False; parent Notion URL=False; parent source records=0
- `bounded-full-scale-commit-reveal-replay-auditing-on-a-real-3eddb3740f` ← parent `medium-scale-commit-reveal-replay-auditing-on-a-larger-opt-dd9c25b0da`; child Notion URL=False; parent Notion URL=False; parent source records=0
- `bounded-full-scale-memory-pressure-validation-for-streamed-6f56b891a0` ← parent `real-corpus-medium-validation-for-streamed-adam-moment-sto-3a0d2e995a`; child Notion URL=False; parent Notion URL=False; parent source records=0
- `bounded-scale-gap-validation-of-calibrated-ppl-gates-for-n-08c789374b` ← parent `medium-validation-of-deployable-ppl-uncertainty-gates-for-05dff99f7d`; child Notion URL=False; parent Notion URL=False; parent source records=0
- `calibrated-evidence-ledger-jury-with-larger-real-data-cove-0937d49bc3` ← parent `real-dataset-small-model-evidence-ledger-jury-benchmark-4e95f7d83d`; child Notion URL=False; parent Notion URL=False; parent source records=0
