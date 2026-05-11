# Enoch state model contract

Status: active operator contract as of 2026-05-10.

The control plane owns the runtime ledger. In production, that ledger now lives in local Postgres on `enoch-core`; older Supabase names remain in migrations, adapter code, and historical docs. The control plane keeps detailed raw states for callbacks, backfills, provenance, and audit, but users and agents should reason from a small deterministic operator model. See [`current-runtime-snapshot.md`](current-runtime-snapshot.md) for canonical current runtime facts, [`docs/state-transition-map.md`](state-transition-map.md) for the lifecycle transition map, and [`docs/state-vocabulary-reduction-plan.md`](state-vocabulary-reduction-plan.md) for the small target vocabulary plus raw-state cleanup mapping.

## What to trust

Trust these surfaces in this order:

1. **Dashboard operator lanes** for current action: what needs attention, what is running, what can be written, what can be finalized, what is ready to publish, and what is already imported.
2. **`operator_counts`, `operator_detail_counts`, paper pipeline definitions, and investigation pipeline definitions** for aggregate counts. Do not replace them with ad hoc raw-status counts.
3. **Raw state surfaces** only when debugging a row. Raw values explain evidence; they are not the user workflow.
4. **`docs/state-reduction-audit.md`** for the generated raw-value disposition table. Do not hand-edit that audit unless regenerating it from `state_contract.py`.

Do not trust `wake_ready`, `session_finished_ready`, `completed`, `draft_review`, or legacy review-like fields as standalone signals for paper work or publication readiness.

## Derived operator lanes

The dashboard and assistant should answer simple questions with these lanes:

| Operator lane | Meaning | User action |
| --- | --- | --- |
| `ready_queue` | Work is eligible to dispatch when the system is unpaused. | None unless changing priority. |
| `running` | Work is dispatching, running, writing, finalizing, or waiting for wake callback. | Wait. |
| `needs_operator` | A blocker, worker question, dispatch/gate failure, manual-action flag, or automation blocker exists. | Resolve the blocker/question. |
| `complete_no_paper` | Worker delivery is complete, but the paper decision gate is not actionable-positive. | Select the next project. |
| `followup_investigation` | Worker delivery is no-paper, but the decision artifact recommends a specific bounded adjacent test. | Launch a follow-up only if the next investigation is still worth worker time. |
| `write_paper` | A completed run has no live paper row and passes the positive paper decision gate. | Run bounded/explicit paper drafting only. |
| `automate_publication` | A paper exists and still needs automated rewrite/finalization/package work. | Let automation finalize or inspect artifacts if automation failed. |
| `ready_to_publish` | A publication draft has a finalized automation package and no corpus-import ledger row. | Import/sync to public corpus. |
| `published` | Corpus import ledger records the paper. | No action. |
| `paused` | Work is intentionally held by maintenance or policy. | Resume only after policy decision. |
| `historical` | Terminal, provenance, debug, or imported evidence that is not current operator work. | No action. |

These lanes are derived, not directly stored as the lifecycle source of truth. In v1 dashboard/API rows, `operator_stage` and `operator_lane` are the canonical lane names above. More specific compatibility detail, such as `run_complete_draft_needed` or `finalization_needed`, belongs in `operator_detail_stage` and should be treated as drill-down context rather than the primary workflow vocabulary.

Operator-facing labels must stay grade-school simple even when raw keys remain stable API/debug fields:

| Operator/debug key | User-facing label |
| --- | --- |
| `running` | Running |
| `ready_queue` | Ready |
| `needs_operator` / `blocked_needs_operator` | Needs Attention |
| `complete_no_paper` / `run_complete_no_paper` | Done / No Paper |
| `followup_investigation` / `followup_candidate` | Investigate Next |
| `write_paper` / `run_complete_draft_needed` | Write Paper |
| `automate_publication` / `finalization_needed` | Finalize Draft |
| `ready_to_publish` | Publish / Import |
| `published` | Published |
| `paused` | Paused |
| `historical` | Historical |

Do not show raw compatibility phrases such as `Run Complete Draft Needed`, `Wake Ready`, `Draft Review`, `Approved`, or `Review` as primary operator labels. They are implementation/debug evidence only.

Count fields follow the same split:

- `operator_counts` groups rows by canonical operator lane and keeps `operator_stage`/`operator_lane` vocabulary user-facing.
- `operator_detail_counts` groups rows by compatibility/detail stage for drill-down metrics and legacy counters.
- `paper_pipeline.write_needed`, `paper_pipeline.finalize_needed`, and `paper_pipeline.publish_ready` are the preferred actionable paper-work counters. `publish_ready` means finalized drafts missing a corpus-import ledger row, not all historical finalized drafts. `paper_pipeline.publication_ready_total` and `paper_pipeline.published_imported` are informational reconciliation counts.
- `investigation_pipeline.followup_needed` is the preferred actionable adjacent-investigation counter. It is separate from paper writing: a follow-up candidate is no-paper until its own independent run later produces a positive paper decision.

## Canonical lifecycle state surfaces

The canonical raw state contract is code-owned in `enoch_control_plane/control_plane/state_contract.py` and schema-owned in the Supabase constraint migrations. These are the lifecycle-bearing state surfaces:

| Surface | Lifecycle role | Operator rule |
| --- | --- | --- |
| `queue_items.status` | Primary project execution queue. | Use for dispatchable, active, paused, blocked, and terminal queue state. |
| `runs.state` | Worker run lifecycle/import state. | Use for run evidence and callbacks; historical/import values stay debug-only. |
| `queue_items.last_run_state` | Latest run/callback/detail copied onto the queue row. | Detail field; never treat it alone as an operator lane. |
| `runs.gate_state` | Wake-gate internal signal. | Detail/debug field; `wake_ready` means delivery completed, not paper polarity. |
| `papers.paper_status` | Paper artifact generation state. | A draft row is not publication-ready until automation finalization succeeds. |
| `publication_automation_items.automation_status` | Automated publication/finalization/package state. | Use automation language; legacy review-like values are compatibility/internal only. |
| `project_decisions.decision_gate_state` | Paper-writing decision gate. | Only `positive` can derive `write_paper`. |
| `project_decisions.followup_*` | Optional bounded adjacent-investigation metadata from worker decisions. | Can derive `followup_investigation`; never derives `write_paper`. |

Supabase constraints bound both primary state columns and detail/debug columns such as `queue_items.last_run_state` and `runs.gate_state`, so raw callback labels must be normalized before they enter persisted lifecycle columns. Superseded legacy `dispatch_accepted` run rows should normalize to `reconciled`, while current dispatch bridge rows normalize to `awaiting_wake`.

## Non-lifecycle flags, config, and provenance

`state_contract.py` also inventories state-like columns that are **not** canonical lifecycle surfaces. Keep these classes out of the user workflow:

| Class | Meaning | Operator treatment |
| --- | --- | --- |
| `system_flag` | Runtime policy/config switch. | Can pause or shape automation, but does not replace row lifecycle state. |
| `attention_flag` | Boolean/manual marker for operator attention. | Decorates a lifecycle row as `needs_operator`; not a separate review process. |
| `type_discriminator` | Record kind, artifact kind, dispatch mode, or snapshot kind. | Provenance/type metadata only. |
| `event_taxonomy` | Append-only event/action names. | Audit/debug metadata only. |
| `projection_metadata` | Observation health or cache/version metadata. | Dashboard/debug metadata only. |

Common examples:

| Surface | Type | How to use it |
| --- | --- | --- |
| `queue_items.manual_review_required` | Flag | Forces `needs_operator` until cleared; do not model it as a separate review workflow. |
| `queue_items.blocked_reason` / `last_error` | Evidence fields | Explain why an item needs operator action. |
| `queue_items.next_action_hint` | Hint | Helps derive paper drafting only with completed delivery and a positive decision gate. |
| `control_flags` | Runtime config | Pause/maintenance policy; it can hold work but does not replace row lifecycle state. |
| `ideas.idea_status` | Source/provenance | Intake provenance only after the control-plane runtime cutover. |
| `projects.origin_idea_status` | Source/provenance | Copied source status; do not infer current work status from it. |
| `corpus_imports` | Publication provenance | Import ledger for `published`; it is not a paper-writing or finalization state. |
| `dashboard_observations` / telemetry | Observability | Freshness/debug evidence only; do not use as lifecycle truth. |

## Paper decision gate

`write_paper` is intentionally narrow:

- The worker delivery must be complete.
- There must be no live paper row for that project/run.
- The current project decision gate must be `positive`.
- A new project-local decision artifact becomes `positive` only from exact canonical `finalize_positive`, except the explicit compatibility path where `continue` is paired with exact supported evidence in a supporting field.

Near-synonyms such as `partial_viable`, `promising_synthetic_positive`, `promising_continue`, `viable`, or `proceed` are research notes, not operator state. They must map to `complete_no_paper` unless a later canonical decision artifact is produced.

`negative`, `missing`, `malformed`, `unknown`, and ambiguous legacy decision values map to `complete_no_paper`. Raw completed/no-paper rows that fail the gate are informational, not a backlog of papers to write.

## Follow-up investigation gate

Follow-up branching is intentionally a separate lane from paper writing:

- A follow-up can be shown only when a completed no-paper row has `followup_recommended = true` in the parsed project decision artifact.
- The worker must provide concrete adjacent-test metadata: `followup_type`, title, hypothesis, required evidence, success threshold, and stop condition.
- The control plane queues a new project only through an explicit bounded launch action (`max_followup_depth` defaults to `4`).
- Already-launched parents are not shown again as actionable follow-up work.
- The effective follow-up depth is the maximum of the worker decision artifact depth and controller-owned source lineage depth, so a worker cannot reset a depth-2 branch back to depth 1.
- Follow-up launch creates queued investigation work; it does not create a paper, mark the parent positive, or bypass the paper decision gate.
- Hard negatives, weak speculation, missing evidence, and ordinary incremental tweaks should leave `followup_recommended = false`.

## Publication automation

Publication is a separate automation lane after a paper exists:

| State question | Trust this |
| --- | --- |
| Is there a draft to finalize/package? | `papers.paper_status = publication_draft` without a finalized automation package. |
| Is publication automation active or queued? | `publication_automation_items.automation_status in ('queued', 'claimed')`. |
| Is the paper finalized? | `papers.paper_status = publication_draft` plus `publication_automation_items.automation_status = finalized` plus a finalization package path. |
| Is the paper ready for corpus import? | Finalized paper evidence above and no matching `corpus_imports` ledger row. |
| Is it already public/corpus-imported? | `corpus_imports` ledger. |

Avoid user-facing paper review/approval wording. Old values such as `draft_review`, `human_review_required`, `in_review`, `unreviewed`, `changes_requested`, and `approved_for_finalization` are compatibility or migration states, not the normal operator workflow.

## Dashboard guidance

The dashboard should lead with operator questions:

- **What needs my attention?** `needs_operator` / `needs_attention`.
- **What is running or queued?** `running` and `ready_queue`.
- **What paper work is actionable?** `write_needed`, not raw completed/no-paper candidates.
- **What needs another investigation?** `investigation_pipeline.followup_needed`, not raw negative rows.
- **What needs automated finalization?** `finalize_needed` / `publication_automation_pending`.
- **What is ready to publish?** finalized publication drafts that are missing a corpus-import ledger row.
- **What is already published?** corpus import ledger.

Raw tables, raw statuses, and legacy labels belong in detail/debug drawers, not first-screen workflow language.

## Hard rules

1. `write_needed` means actionable positive paper work only.
2. Raw completed/no-paper candidates are informational and must not be presented as papers to write.
3. Negative, missing, malformed, unknown, or ambiguous project decisions are not writable.
4. `wake_ready` means worker delivery completed; it does not mean the result was positive.
5. Follow-up recommendations are adjacent-investigation work only; they do not make a parent run writable.
6. Finalization readiness means `publication_draft` plus finalized automation package, not a draft row by itself; actionable publication/import readiness additionally requires no corpus-import ledger row.
7. Human/operator paper approval is not a normal workflow state. Use automated finalization/package wording.
8. Notion/source idea status is provenance only now that the control plane owns the runtime ledger.
9. New raw state strings or new state-like persisted columns require updating `state_contract.py`, the Supabase constraint migration when applicable, `scripts/validate_state_contract.py` coverage, this document, and `docs/state-model.md`, and public docs.

## State doctor

Run the state doctor before answering live operator state/count questions or before changing dashboard/paper automation semantics:

```bash
uv run python scripts/state_doctor.py \
  --database-url "$ENOCH_CONTROL_DATABASE_URL" \
  --control-url "$ENOCH_CONTROL_URL" \
  --token-file /path/to/enoch-control-plane-token.txt \
  --corpus ../enoch-ai-research-corpus \
  --output path/to/state-doctor.json
```

The report combines the state contract, normalization dry-run, live reduction-drift rows, dashboard operator-count keys, paper-pipeline boundaries, control-plane health, and optional corpus reconciliation. It fails if:

- a persisted state falls outside the contract;
- normalization would still rewrite live rows;
- alias or migrate-after-freeze rows remain live;
- raw detail stages appear in primary `operator_counts`;
- `paper_pipeline` no longer satisfies `raw_completed_no_paper_candidates = write_needed + not_writable_by_decision_gate`;
- required paper-pipeline fields are missing;
- required investigation-pipeline fields are missing;
- `--corpus` is checked and finalized publication drafts are absent from the public corpus. Use `--warn-only-corpus` only for exploratory runs where known corpus backlog should not make the command nonzero.

Legacy-internal rows such as provenance-only `unknown` values remain visible in `legacy_runtime_context`. They are not warnings when the doctor can classify them as `historical_or_attention_residue` with `active_queue = 0`; they become failures if attached to active runtime work, and they remain warnings only when unclassified.

For a live state answer, record these evidence fields from the JSON report:

| Evidence field | Clean value |
| --- | --- |
| `ok` | `true` |
| `state_contract.ok` | `true` |
| `normalization.total_rows` | `0` |
| `live_reduction_drift.hard_rows` | empty |
| `control_plane.overview.raw_detail_keys_in_operator_counts` | empty |
| `control_plane.overview.paper_pipeline` | includes all required paper-count keys |
| `control_plane.overview.investigation_pipeline` | includes `followup_needed` and `max_followup_depth` |
| `corpus_reconciliation.importable_finalized_count` | `0` when `--corpus` is checked without `--warn-only-corpus` |

## Validation

Run:

```bash
uv run python scripts/validate_state_contract.py
uv run python scripts/validate_state_contract.py --database-url "$ENOCH_CONTROL_DATABASE_URL"
uv run python scripts/generate_state_reduction_audit.py --database-url "$ENOCH_CONTROL_DATABASE_URL"
uv run python scripts/normalize_state_surfaces.py --database-url "$ENOCH_CONTROL_DATABASE_URL"
```

`normalize_state_surfaces.py` is dry-run by default. Use `--apply` only after the generated change counts match the state-reduction audit and the system is intentionally in the automation freeze window.

The live check fails if any persisted state value falls outside the contract or if a raw state value lacks an operator-lane/disposition decision.
