# Enoch next-batch policy

Status: active operator policy as of 2026-05-07.

This policy controls when Enoch can leave the idle/cleanup posture and dispatch new research work after the Supabase cutover and canonical paper-gate fixes.

## Current operating posture

Default posture: **controlled small batches only**.

Do not broad-unfreeze the queue into a large backlog until all of the following are true:

1. The live dashboard is quiet except for intentionally documented blockers.
2. `state_doctor.py` reports `ok=true`, no failures, and no warnings.
3. `paper_pipeline.write_needed = 0`, `finalize_needed = 0`, and `publish_ready = 0` before the batch starts.
4. The batch has an explicit size, source, and expected stopping point.
5. Paper drafting remains explicit/bounded; unattended timer drafting stays disabled.

## Allowed ideas

Prefer ideas with high upside for local, affordable, or distributed AI:

- long-context memory or SSM/Mamba mechanisms;
- KV-cache compression, eviction, routing, or quantization;
- speculative decoding or non-neural drafter mechanisms;
- low-bit quantization with a clear mechanism;
- home/low-VRAM fine-tuning or inference improvements;
- distributed/volunteer training validation;
- agent reliability, evidence ledgers, or reproducibility tooling;
- adjacent infrastructure that makes the research pipeline more deterministic.

Do not fill a batch with tiny incremental tweaks unless they are needed as controls or baselines for a larger idea.

## Batch size

Default next real batch size: **3 to 5 ideas**.

Use a larger batch only after one full 3-5 idea batch proves:

- exact canonical decision labels;
- no near-synonym leakage;
- no unintended paper drafting;
- stable dashboard counts;
- clean state-doctor output after completion.

## Dispatch requirements

A dispatch-ready idea must have:

- a row in `enoch.ideas`;
- a matching row in `enoch.projects`;
- a matching `enoch.queue_items` row with `status = 'queued'`;
- clear `machine_target`, `model`, and `sandbox` values;
- baseline, kill condition, expected artifacts, and source metadata;
- `max_continues = 0` unless a specific continuation budget is approved.

Use control-plane dry-run dispatch before live dispatch when introducing a new source or batch shape.

## Required project decision labels

Workers must emit exact canonical decision values in `.enoch/project_decision.json`; `.omx/project_decision.json` remains a legacy compatibility path for old artifacts:

```json
{
  "project_decision": "finalize_positive | finalize_negative | needs_review | blocked | continue | branch_new_project"
}
```

Only exact `finalize_positive` creates actionable `write_needed` work for a new local decision artifact.

Compatibility exception: `continue` can become writable only when paired with exact supported evidence in a supporting decision field as already implemented by the paper gate.

These are not paper-positive decisions:

- `partial_viable`
- `promising_synthetic_positive`
- `promising_continue`
- `viable`
- `proceed`
- `validated_with_limitations`
- `negative_result`

Treat those as research notes. They should map to `complete_no_paper` unless a later canonical decision is produced.

## Paper drafting policy

`finalize_positive` should **queue `write_needed`**, not silently draft in the background.

Allowed drafting path:

1. Confirm `paper_pipeline.write_needed` and `next_write_candidate`.
2. Run `/control/papers/draft-next` with `dry_run=true`.
3. If the dry run selects the intended candidate, run the bounded explicit draft action.
4. Verify `write_needed` decreases and `finalize_needed` increases.
5. Run automated rewrite/finalization explicitly.
6. Verify `finalize_needed` decreases and `publish_ready` changes as expected.

Unattended drafting timers and queue-pump paper drafting must remain disabled unless there is a separate explicit policy change.

## Public corpus import policy

A finalized paper qualifies for public corpus import only when it is a real research artifact, not an operational smoke or state-machine test.

Import to public corpus when:

- the project decision is canonical `finalize_positive`;
- the artifact has synchronized evidence, claim ledger, manifest, and finalization package;
- the paper is not a duplicate or internal smoke;
- sanitization passes;
- public release validation and count reconciliation pass.

Archive/reject internally when:

- the row was created as a control-plane smoke;
- the artifact exists only to prove dispatch/drafting/finalization mechanics;
- evidence is synthetic in a way that should not be public research output;
- publication would create count noise or misleading public claims.

## Batch completion checks

After every batch, verify:

```text
active = 0
queued = 0
write_needed = 0 unless intentionally waiting for explicit drafting
finalize_needed = 0 unless intentionally waiting for explicit finalization
publish_ready = 0 unless intentionally waiting for corpus import
raw_completed_no_paper_candidates = write_needed + not_writable_by_decision_gate
```

Then run:

```bash
uv run python scripts/state_doctor.py \
  --database-url "$ENOCH_SUPABASE_DATABASE_URL" \
  --control-url "$ENOCH_CONTROL_URL" \
  --token-file /path/to/enoch-control-plane-token.txt \
  --corpus ../enoch-ai-research-corpus
```

For public release changes, also run the ecosystem manifest and public release validators.
