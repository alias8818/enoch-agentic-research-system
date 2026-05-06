# Enoch state model contract

Status: active migration contract as of 2026-05-06.

This document separates **raw persisted states** from the small **operator vocabulary**. Raw states exist so callbacks, historical imports, paper artifacts, and Supabase ledgers remain auditable. Operator views must not lead with those raw values unless the user opens evidence/debug details.

## Operator vocabulary

The dashboard and assistant should answer simple questions with these lanes:

| Operator lane | Meaning | Primary source | User action |
| --- | --- | --- | --- |
| `ready_queue` | Work is eligible to dispatch when the system is unpaused. | `queue_items.status = queued` | None unless changing priority. |
| `running` | Work is dispatching, running, or waiting for wake callback. | `queue_items.status`, wake-gate run records | Wait. |
| `needs_operator` | A blocker, worker question, dispatch error, or explicit manual flag exists. | `queue_items.status`, `manual_review_required`, error/blocker fields | Resolve the blocker/question. |
| `complete_no_paper` | Worker completed, but paper gate says no actionable positive paper. | `paper_eligibility`, project decisions | Select next project. |
| `write_paper` | Worker completed and decision gate is positive with no existing paper. | `paper_eligibility.write_needed` | Run bounded/explicit paper drain only. |
| `automate_publication` | A paper exists but automated finalization/package is not done. | `papers`, `publication_automation_items` | Let automation finalize; no paper approval step. |
| `ready_to_publish` | Publication draft has finalized automation package. | `papers.paper_status = publication_draft` plus finalized package | Import/sync to public corpus if not already present. |
| `published` | Corpus import ledger records the paper. | `corpus_imports` | No action. |
| `paused` | Work intentionally held by maintenance/pause policy. | `control_flags`, queue row | Resume only after policy decision. |
| `historical` | Old evidence row that is not live work or attention. | run/history ledgers | No action. |

## Raw state surfaces

The canonical raw state contract is code-owned in `omx_wake_gate/control_plane/state_contract.py` and schema-owned in `supabase/migrations/20260506165512_enoch_state_contract_constraints.sql`. The reduction/disposition table for every raw value is generated in `docs/state-reduction-audit.md`.

| Surface | Meaning | Notes |
| --- | --- | --- |
| `ideas.idea_status` | Supabase-native idea workbench state. | Provenance/triage only; execution state starts in `queue_items`. |
| `projects.origin_idea_status` | Source idea status copied onto project records. | Provenance only; do not infer work status from it. |
| `queue_items.status` | Control-plane project execution lane. | Primary persisted work queue state. |
| `queue_items.last_run_state` | Last worker/callback/project evidence state. | Detail field, not operator lane. |
| `runs.state` | Worker run lifecycle/import state. | Includes historical values such as `unknown` and `dispatch_accepted`. |
| `runs.gate_state` | Wake-gate internal signal. | Detail field for debug/evidence. |
| `project_decisions.decision_gate_state` | Paper-writing decision gate. | Only `positive` can count as `write_paper`. |
| `papers.paper_status` | Paper artifact generation state. | Public readiness also needs finalized automation package. |
| `publication_automation_items.automation_status` | Automated finalization/package state. | Replaces operator-facing paper approval language. Legacy review-like values remain internal for backfill parity. |

## Hard rules

1. `write_needed` means actionable positive paper work only.
2. Raw completed/no-paper candidates are informational and must not be presented as papers to write.
3. Negative, missing, malformed, unknown, or needs-review project decisions are not writable.
4. `wake_ready` means worker delivery completed; it does not mean the result was positive.
5. Publication readiness means `publication_draft` plus finalized automation package, not a draft row by itself.
6. Human/operator paper approval is not a normal workflow state. Use automated finalization/package wording.
7. Notion/source idea status is provenance only now that Supabase owns the runtime ledger.
8. New raw state strings require updating `state_contract.py`, the Supabase constraint migration, and `scripts/validate_state_contract.py` coverage.

## Validation

Run:

```bash
uv run python scripts/validate_state_contract.py
uv run python scripts/validate_state_contract.py --database-url "$ENOCH_SUPABASE_DATABASE_URL"
uv run python scripts/generate_state_reduction_audit.py --database-url "$ENOCH_SUPABASE_DATABASE_URL"
```

The live check fails if any persisted state value falls outside the contract or if a raw state value lacks an operator-lane/disposition decision.
