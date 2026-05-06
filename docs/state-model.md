# Enoch state model contract

Status: active migration contract as of 2026-05-06.

Supabase owns the runtime ledger. The control plane keeps detailed raw states for callbacks, backfills, provenance, and audit, but users and agents should reason from a small deterministic operator model.

## What to trust

Trust these surfaces in this order:

1. **Dashboard operator lanes** for current action: what needs attention, what is running, what can be written, what can be finalized, what is ready to publish, and what is already imported.
2. **`operator_counts`, `operator_detail_counts`, and paper pipeline definitions** for aggregate counts. Do not replace them with ad hoc raw-status counts.
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
| `write_paper` | A completed run has no live paper row and passes the positive paper decision gate. | Run bounded/explicit paper drafting only. |
| `automate_publication` | A paper exists and still needs automated rewrite/finalization/package work. | Let automation finalize or inspect artifacts if automation failed. |
| `ready_to_publish` | A publication draft has a finalized automation package. | Import/sync to public corpus if not already present. |
| `published` | Corpus import ledger records the paper. | No action. |
| `paused` | Work is intentionally held by maintenance or policy. | Resume only after policy decision. |
| `historical` | Terminal, provenance, debug, or imported evidence that is not current operator work. | No action. |

These lanes are derived, not directly stored as the lifecycle source of truth. In v1 dashboard/API rows, `operator_stage` and `operator_lane` are the canonical lane names above. More specific compatibility detail, such as `run_complete_draft_needed` or `finalization_needed`, belongs in `operator_detail_stage` and should be treated as drill-down context rather than the primary workflow vocabulary.

Count fields follow the same split:

- `operator_counts` groups rows by canonical operator lane and keeps `operator_stage`/`operator_lane` vocabulary user-facing.
- `operator_detail_counts` groups rows by compatibility/detail stage for drill-down metrics and legacy counters.
- `paper_pipeline.write_needed`, `paper_pipeline.finalize_needed`, and `paper_pipeline.publish_ready` are the preferred paper-work counters. They intentionally combine lane and detail evidence so dashboards do not infer paper work from raw statuses alone.

## Canonical lifecycle state surfaces

The canonical raw state contract is code-owned in `omx_wake_gate/control_plane/state_contract.py` and schema-owned in the Supabase constraint migrations. These are the lifecycle-bearing state surfaces:

| Surface | Lifecycle role | Operator rule |
| --- | --- | --- |
| `queue_items.status` | Primary project execution queue. | Use for dispatchable, active, paused, blocked, and terminal queue state. |
| `runs.state` | Worker run lifecycle/import state. | Use for run evidence and callbacks; historical/import values stay debug-only. |
| `queue_items.last_run_state` | Latest run/callback/detail copied onto the queue row. | Detail field; never treat it alone as an operator lane. |
| `runs.gate_state` | Wake-gate internal signal. | Detail/debug field; `wake_ready` means delivery completed, not paper polarity. |
| `papers.paper_status` | Paper artifact generation state. | A draft row is not publication-ready until automation finalization succeeds. |
| `publication_automation_items.automation_status` | Automated publication/finalization/package state. | Use automation language; legacy review-like values are compatibility/internal only. |
| `project_decisions.decision_gate_state` | Paper-writing decision gate. | Only `positive` can derive `write_paper`. |

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
| `ideas.idea_status` | Source/provenance | Intake provenance only after Supabase cutover. |
| `projects.origin_idea_status` | Source/provenance | Copied source status; do not infer current work status from it. |
| `corpus_imports` | Publication provenance | Import ledger for `published`; it is not a paper-writing or finalization state. |
| `dashboard_observations` / telemetry | Observability | Freshness/debug evidence only; do not use as lifecycle truth. |

## Paper decision gate

`write_paper` is intentionally narrow:

- The worker delivery must be complete.
- There must be no live paper row for that project/run.
- The current project decision gate must be `positive`.

`negative`, `missing`, `malformed`, `unknown`, and ambiguous legacy decision values map to `complete_no_paper`. Raw completed/no-paper rows that fail the gate are informational, not a backlog of papers to write.

## Publication automation

Publication is a separate automation lane after a paper exists:

| State question | Trust this |
| --- | --- |
| Is there a draft to finalize/package? | `papers.paper_status = publication_draft` without a finalized automation package. |
| Is publication automation active or queued? | `publication_automation_items.automation_status in ('queued', 'claimed')`. |
| Is the paper ready for corpus import? | `papers.paper_status = publication_draft` plus `publication_automation_items.automation_status = finalized` plus a finalization package path. |
| Is it already public/corpus-imported? | `corpus_imports` ledger. |

Avoid user-facing paper review/approval wording. Old values such as `draft_review`, `human_review_required`, `in_review`, `unreviewed`, `changes_requested`, and `approved_for_finalization` are compatibility or migration states, not the normal operator workflow.

## Dashboard guidance

The dashboard should lead with operator questions:

- **What needs my attention?** `needs_operator` / `needs_attention`.
- **What is running or queued?** `running` and `ready_queue`.
- **What paper work is actionable?** `write_needed`, not raw completed/no-paper candidates.
- **What needs automated finalization?** `finalize_needed` / `publication_automation_pending`.
- **What is ready to publish?** finalized publication drafts only.
- **What is already published?** corpus import ledger.

Raw tables, raw statuses, and legacy labels belong in detail/debug drawers, not first-screen workflow language.

## Hard rules

1. `write_needed` means actionable positive paper work only.
2. Raw completed/no-paper candidates are informational and must not be presented as papers to write.
3. Negative, missing, malformed, unknown, or ambiguous project decisions are not writable.
4. `wake_ready` means worker delivery completed; it does not mean the result was positive.
5. Publication readiness means `publication_draft` plus finalized automation package, not a draft row by itself.
6. Human/operator paper approval is not a normal workflow state. Use automated finalization/package wording.
7. Notion/source idea status is provenance only now that Supabase owns the runtime ledger.
8. New raw state strings or new state-like persisted columns require updating `state_contract.py`, the Supabase constraint migration when applicable, `scripts/validate_state_contract.py` coverage, this document, and the parent release wiki at `/home/jeremy/Desktop/projects/enoch-release/.omx/wiki/state-model-contract.md`.

## Validation

Run:

```bash
uv run python scripts/validate_state_contract.py
uv run python scripts/validate_state_contract.py --database-url "$ENOCH_SUPABASE_DATABASE_URL"
uv run python scripts/generate_state_reduction_audit.py --database-url "$ENOCH_SUPABASE_DATABASE_URL"
uv run python scripts/normalize_state_surfaces.py --database-url "$ENOCH_SUPABASE_DATABASE_URL"
```

`normalize_state_surfaces.py` is dry-run by default. Use `--apply` only after the generated change counts match the state-reduction audit and the system is intentionally in the automation freeze window.

The live check fails if any persisted state value falls outside the contract or if a raw state value lacks an operator-lane/disposition decision.
