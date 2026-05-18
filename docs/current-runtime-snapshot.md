# Current Runtime Snapshot

Status: canonical current-runtime reference as of 2026-05-10.

Use this page as the short source of truth for Enoch runtime facts. Longer
runbooks may explain procedures or historical migrations, but if runtime facts
drift, update this page first.

## Runtime hosts

| Host | Role | Path | Notes |
| --- | --- | --- | --- |
| `enoch-core` | Control plane | `/opt/enoch-control-plane` | Runs the FastAPI control plane, dashboard/API, local Postgres runtime storage, automation timers, and paper/corpus tooling. |
| GB10 | Worker gate | `~/projects/enoch_testing_ground/enoch-control-plane` | Runs native Codex worker execution, process/telemetry tracking, project workspaces, evidence, and worker callbacks. |

## Storage/source of truth

Local Postgres/control-plane storage on `enoch-core` is the current runtime
source of truth for ideas, projects, queue items, runs, papers, events, and the
corpus import ledger. Notion is a legacy provenance/intake compatibility path.
Supabase Cloud is not current runtime intake or storage; `supabase_*` names in
code and scripts are compatibility or migration-adapter naming.

## Worker execution path

Research Facility/admitted idea -> control-plane queue -> preflight -> one
selected dispatch -> GB10 worker gate -> Codex run -> evidence/project
artifacts -> callback -> decision sync -> optional paper/corpus lanes.

The worker gate proves operational completion. It does not prove scientific
correctness or novelty.

## Project decision artifact contract

The native project decision artifact is `.enoch/project_decision.json`.
`.omx/project_decision.json` is a compatibility-only fallback. Do not invent
new enum values in docs or automation. The paper gate treats exact
`finalize_positive` as the normal positive path; non-positive, missing,
malformed, or ambiguous decisions remain no-paper unless a later independent
run becomes positive.

## Research Facility automation

Research Facility can generate, admit, promote, and dispatch candidates, but
each tick is bounded. A live tick can spend at most one provider request,
promote at most one candidate, dispatch at most one selected queued item when
dispatch is enabled, and optionally draft/finalize at most one positive-gated
paper. It is not a broad queue drain.

## Paper pipeline boundaries

`write_needed` means decision-gated positive paper work only.
Negative/non-positive runs become no-paper rows, not papers to write.
`finalize_needed` is automation/package work for an existing draft.
`publish_ready` means required evidence paths and finalized package exist, but the corpus import ledger row is missing.

## Callback/reconnect behavior

Worker callbacks to `/control/api/worker-callback` are idempotent by
idempotency key. Callback-ready states without delivered keys retry after
network or control-plane flaps. Startup reconciliation can recover missing
idle/finished observations. Worker-process death mid-run before a decision
artifact exists is a separate failure class and is not fully solved by callback
retry.

## Automation readiness meaning

READY means queue policy, maintenance mode, timers, recent ticks, provider
budget, blocked/attention counts, queue consistency, and positive-gated paper
counters satisfy long-haul criteria. BLOCKED means at least one criterion
failed; inspect the first blocker and do not widen automation until understood.

## Historical/compatibility-only

- Notion runtime intake/projection.
- Supabase Cloud as active runtime database.
- `.omx/project_decision.json` as the primary artifact.
- `wake_gate` naming outside raw config/API compatibility.
- Raw states such as `wake_ready`, `draft_review`, and `approved_for_corpus`
  as operator workflow labels.
- Broad queue drains or paper writing from negative/non-positive rows.
