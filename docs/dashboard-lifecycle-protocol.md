# Dashboard lifecycle protocol

Status: active route-policy contract for Dashboard V2.

Linear source: ALI-109 under ALI-105.

Dashboard V2 is an operator command center. Route ownership follows the work lifecycle, not the backend table or historical page name.

## Lifecycle chain

Every dashboard route should explain where an item sits in this chain:

```text
candidate -> queue row -> dispatch/run -> worker lane -> evidence/artifact -> paper/package/import -> event/alert
```

Definitions:

- `candidate`: generated or imported possible work that is not yet a queued dispatch row.
- `queue row`: admitted work with lane, target, priority, blocked/queued/active state, and dispatch readiness.
- `dispatch/run`: a concrete worker execution attempt or run history record.
- `worker lane`: CPU or GB10 lane telemetry, current worker confirmation, backlog pressure, and lane blockers.
- `evidence/artifact`: decision files, evidence bundles, run artifacts, package inputs, and inspection records.
- `paper/package/import`: paper draft, rewrite, finalization, package lint, corpus import, and publication-readiness state.
- `event/alert`: audit event, queue alert, conflict, notification, or operator-facing evidence of a state change.

## Route ownership

The code contract lives in `dashboard/src/routePolicy.ts` as `DASHBOARD_LIFECYCLE_CHAIN` and `ROUTE_CONSOLIDATION_MAP`.

| Route | Owner | Lifecycle stages | Operator question | Decision |
| --- | --- | --- | --- | --- |
| `#overview` | Command Center | worker lane, event/alert | Can I leave this running, and what is the safest next action? | Primary entrypoint |
| `#projects` | Work Queue | candidate, queue row, dispatch/run, evidence/artifact | What project or work item needs operator review? | Owned subworkflow |
| `#queue` | Work Queue | queue row, dispatch/run, worker lane | What queued work is safe to dispatch or unblock? | Primary work-queue surface |
| `#research` | Work Queue | candidate, queue row | Which generated candidates can be promoted into the queue? | Queue-owned subworkflow |
| `#intake` | Work Queue | candidate, queue row | Which imported ideas can be admitted into queued work? | Queue-owned subworkflow |
| `#runs` | Runs | dispatch/run, worker lane, evidence/artifact | What is running or recently ran, and what did it produce? | Primary run-history surface |
| `#papers` | Papers | evidence/artifact, paper/package/import | Is this paper ready to finalize, package, import, or inspect? | Primary paper workflow |
| `#corpus` | Papers | paper/package/import | Which publication-ready drafts still need corpus import? | Papers compatibility subworkflow |
| `#automation` | Papers | evidence/artifact, paper/package/import | What paper action is safe to run next? | Papers compatibility subworkflow |
| `#events` | Events and Alerts | event/alert | What changed recently and what alert evidence supports it? | Primary event surface |
| `#observability` | Models and Observability | event/alert | Which model, provider, worker, memory, or route signal needs attention? | Debug/support surface |
| `#settings` | Settings | candidate, queue row, dispatch/run, paper/package/import | Which configuration controls dispatch, providers, model pools, or gates? | Debug/support surface |

## Consolidation decisions

`#overview` remains the first-screen command center. It answers current posture, lane usefulness, backlog pressure, and the safest next action. It should not become a general metrics explorer.

`#queue` owns dispatchable work. `#research` and `#intake` stay available as compatibility workbenches for now, but their owner is Work Queue and their parent is `#queue`. Future UI slices should demote or merge them into queue-owned panels before adding new candidate/intake routes.

`#papers` owns the paper lifecycle. `#corpus` and `#automation` stay as compatibility hashes, but they are Papers subworkflows. The visible nav should keep Papers as the main route and expose paper workflow tabs inside that surface.

`#observability` is the destination for model and provider health from ALI-104. It should summarize health, format adherence, latency, error class, and recent degradation before exposing raw event payloads.

`#events` proves changes and alert evidence. It is not the first place an operator should go to decide whether automation can be left running.

`#settings` controls configuration only. It must not become the primary way to understand whether lanes, models, papers, or alerts are healthy.

## Deterministic invariants

- `DASHBOARD_LIFECYCLE_CHAIN` must preserve the exact ALI-109 chain.
- Every implemented top-level route in `ROUTE_AUDIT` must appear in `ROUTE_CONSOLIDATION_MAP`.
- Every route in the consolidation map must have one owner, at least one lifecycle stage, and a human operator question.
- `#research` and `#intake` are Work Queue-owned subworkflows with `#queue` as parent.
- `#corpus` and `#automation` are Papers-owned compatibility subworkflows with `#papers` as parent.
- Raw JSON remains debug evidence only and must stay inside collapsed details.

## Next slices

1. ALI-104: add deterministic model/provider observability under the Models and Observability owner instead of another unrelated dashboard page.
2. ALI-105/ALI-108: reduce duplicate Work Queue surfaces by folding candidate generation and idea intake into queue-owned panels when the read models support it.
3. Continue demoting implementation nouns from visible navigation; route names should describe operator jobs, not storage tables.
