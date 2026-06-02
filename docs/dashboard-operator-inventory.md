# Dashboard operator inventory

Status: active inventory for Dashboard V2 surface consolidation.

Linear source: ALI-108 under ALI-105.

This inventory exists to prevent Dashboard V2 from drifting back into a data
explorer. Every route, card, table, and detail/debug surface should answer a
concrete operator question before it earns visible space.

## Inventory contract

Each operator surface is tracked by:

- Surface: route, card, table, detail panel, or debug payload.
- Source: component, read model, or API that feeds it.
- Entity: the dominant work item, state, or evidence type.
- Operator question: the question answered for the operator.
- Disposition: keep above fold, keep primary, keep secondary, demote, collapse,
  or merge later.
- Proof: deterministic test or validator that prevents silent drift.

The route ownership contract lives in `dashboard/src/routePolicy.ts`. This
inventory adds card/table/detail coverage for ALI-108.

## Route inventory

| Surface | Source | Entity | Operator question | Disposition | Proof |
| --- | --- | --- | --- | --- | --- |
| `#overview` | `overviewPage.tsx`, `/control/api/v1/overview`, `/control/api/v1/automation-readiness`, `/control/api/status` | lane, queue, alert, paper pipeline | Can I leave this running, and what is the safest next action? | Keep as command center | `routePolicy.test.ts`, `App.test.tsx`, this inventory validator |
| `#projects` | `ResourcePages.tsx`, projects read model | project/work item | What project or work item needs operator review? | Keep as Work Queue-owned list | `routePolicy.test.ts`, `DataTable.test.tsx` |
| `#queue` | `ResourcePages.tsx`, queue read model, dispatch commands | queued row, lane, dispatch | What queued work is safe to dispatch or unblock? | Keep as primary work-queue list | `routePolicy.test.ts`, command-center tests |
| `#research` | `ResearchPage.tsx`, research facility rows | candidate, promotion | Which generated candidates can be promoted into the queue? | Keep as queue-owned subworkflow; merge later when read models support it | `routePolicy.test.ts`, `App.test.tsx` |
| `#intake` | `ResourcePages.tsx`, intake projection | imported idea, candidate, queue row | Which imported ideas can be admitted into queued work? | Keep as queue-owned subworkflow; merge later when read models support it | `routePolicy.test.ts`, `App.test.tsx` |
| `#runs` | `ResourcePages.tsx`, runs read model | dispatch run, artifact | What is running or recently ran, and what did it produce? | Keep as primary run-history list | `routePolicy.test.ts`, `DetailPanel.test.tsx` |
| `#papers` | `ResourcePages.tsx`, papers read model | paper draft, package, import | Is this paper ready to finalize, package, import, or inspect? | Keep as primary paper workflow | `routePolicy.test.ts`, `DetailPanel.test.tsx` |
| `#corpus` | `ResourcePages.tsx`, corpus import rows | publication draft, corpus import | Which publication-ready drafts still need corpus import? | Keep as Papers compatibility subworkflow; merge later into Papers tabs | `routePolicy.test.ts`, `App.test.tsx` |
| `#automation` | `AutomationPage.tsx`, paper automation rows | paper action, checklist, package gate | What paper action is safe to run next? | Keep as Papers compatibility subworkflow; merge later into Papers tabs | `routePolicy.test.ts`, command-center tests |
| `#events` | `ResourcePages.tsx`, events read model | event, alert, audit evidence | What changed recently and what alert evidence supports it? | Keep as primary event evidence list | `routePolicy.test.ts`, `DetailPanel.test.tsx` |
| `#observability` | `ResourcePages.tsx`, LLM/model/route/memory observability APIs | model health, provider health, route health, memory | Which model, provider, worker, memory, or route signal needs attention? | Keep as debug/support route below command center priority | `routePolicy.test.ts`, model observability tests |
| `#settings` | settings route, LLM settings APIs | provider config, model pools, feature gates | Which configuration controls dispatch, providers, model pools, or gates? | Keep as debug/support route; do not use for operational health truth | `routePolicy.test.ts`, LLM settings tests |
| `#project:...` | `DetailPanel.tsx`, project detail read model | project/work item | What evidence explains this project state? | Keep as structured detail route | `DetailPanel.test.tsx` |
| `#run:...` | `DetailPanel.tsx`, run detail read model | run, artifact, callback | What happened in this run and what evidence did it produce? | Keep as structured detail route | `DetailPanel.test.tsx` |
| `#paper:...` | `DetailPanel.tsx`, paper detail read model | paper, package, import | Is this paper ready or blocked, and why? | Keep as structured detail route | `DetailPanel.test.tsx` |
| `#event:...` | `DetailPanel.tsx`, event detail read model | event, alert payload | What evidence proves this event or alert? | Keep as structured detail route | `DetailPanel.test.tsx` |
| `#research:...` | `ResearchPage.tsx`, selected candidate panel | generated candidate | Which candidate evidence supports promotion or rejection? | Keep as list selection, not a standalone route | `routePolicy.test.ts` |
| `#intake:...` | `ResourcePages.tsx`, selected intake panel | imported idea | Which imported idea evidence supports admission or rejection? | Keep as list selection, not a standalone route | `routePolicy.test.ts` |
| `#automation:...` | `AutomationPage.tsx`, selected paper action panel | paper automation row | Which paper action evidence supports the next safe step? | Keep as list selection, not a standalone route | `routePolicy.test.ts` |

## Command center inventory

Above the fold is intentionally narrow. It may answer readiness, lane usefulness,
lane idleness, queue depth, one safest action, and paper-pipeline posture.

| Surface | Source | Entity | Operator question | Disposition | Proof |
| --- | --- | --- | --- | --- | --- |
| Can I leave this running? | `CommandHero` in `overviewPage.tsx` | readiness, blockers, lane state | Can I leave this running? | Keep above fold | `App.test.tsx` command-center assertions |
| Readiness check | `ReadinessCheckCard`, `/control/api/v1/automation-readiness` | readiness gate, provider budget, LLM health, stale lanes | Can I leave this running? What is blocked? | Keep above fold | `test_longhaul_readiness.py`, `test_control_plane_router.py` |
| CPU / GB10 command surface | `WorkerLanes`, `/control/api/status?refresh_worker=true` | worker lane, queue count, active row, preflight | Are CPU and GB10 doing useful work? If idle, why? | Keep above fold | `CommandCenter.test.tsx` |
| Primary action | `PrimaryAction`, `primary_operator_action` | dispatch, feed, paper action, readiness action | What should I do next? | Keep one primary CTA above fold | `CommandCenter.test.tsx` |
| Write -> Finalize -> Publish | paper mini strip in `overviewPage.tsx` | paper pipeline | Is the paper pipeline ready or blocked? | Keep tiny above fold | `App.test.tsx` |
| Top actions | `TopActionsCard` in `overviewPage.tsx` | ranked operator actions | What should I consider after the primary action? | Keep secondary below fold | `App.test.tsx` |
| Research signal quality | `ResearchSignalQualityCard` in `overviewPage.tsx` | quality-window summary, provider malformed/yield, useful trend | What changed recently in research quality? | Keep secondary below fold; format as fields, not raw semicolon text | `App.test.tsx` |
| Research yield | `ResearchYieldCard` in `overviewPage.tsx` | generated/promoted/paper-ready counts | What changed recently in output volume? | Keep secondary below fold | `App.test.tsx` |
| Recent activity stream | `RecentActivityStream` in `overviewPage.tsx` | event/activity rows | What changed recently? | Keep secondary below fold; details route owns debug evidence | `App.test.tsx` |
| Active work snapshot | `ActiveWorkSnapshot` in `overviewPage.tsx` | active queue rows, runs, lane state | What is running now? | Keep secondary below fold | `App.test.tsx` |
| Automation readiness | `AutomationReadinessSummary` in `overviewPage.tsx` | blockers and readiness details | What blocks unattended operation? | Keep secondary below fold; hero/readiness own above-fold answer | readiness tests |

## Resource page inventory

| Surface | Source | Entity | Operator question | Disposition | Proof |
| --- | --- | --- | --- | --- | --- |
| DataTable | `DataTable.tsx` | project, queue row, run, paper, event, candidate, intake row | Which row needs inspection or action? | Keep as list primitive; human title/state before IDs | `DataTable.test.tsx` |
| DetailPanel | `DetailPanel.tsx` | selected project, run, paper, event | What structured evidence explains the selected row? | Keep as detail primitive; structured summary before debug payload | `DetailPanel.test.tsx` |
| CandidateDetailPanel | `ResearchPage.tsx` | generated candidate | Is this candidate promotable or why not? | Keep as queue-owned detail panel | `routePolicy.test.ts` |
| Intake idea detail | `ResourcePages.tsx` | imported idea | Should this idea be admitted or ignored? | Keep as queue-owned detail panel | `routePolicy.test.ts` |
| Automation detail | `AutomationPage.tsx` | paper action row | What paper action is safe and what gate blocks it? | Keep as Papers-owned detail panel | `routePolicy.test.ts` |
| RawJsonDetails | `components/ui/RawDetails.tsx` | raw backend payload | What evidence/debug payload proves this? | Collapse by default inside `details.raw-details` only | `componentSystem.test.tsx` |

## Demotion and merge decisions

- `#research` and `#intake` are not independent product areas. They are Work
  Queue-owned candidate admission workbenches. Future UI work should merge them
  into queue-owned panels when the read models support it.
- `#corpus` and `#automation` are not independent product areas. They are
  Papers-owned package/import/action workbenches. Future UI work should merge
  them into Papers-owned tabs when the read models support it.
- `#observability` and `#settings` are debug/support surfaces. They should never
  replace command-center readiness as the answer to "Can I leave this running?"
- Raw JSON is evidence, not primary UX. It belongs only in `RawJsonDetails`
  inside collapsed `details.raw-details`.

## Deterministic invariants

- Every top-level implemented route in `ROUTE_AUDIT` appears in this inventory.
- Every supported detail route family appears in this inventory.
- Every major command-center card appears in this inventory with an operator
  question and disposition.
- Every shared table, detail, and raw-debug primitive appears in this inventory.
- Compatibility routes have explicit owner and merge-later decisions.
- Raw JSON remains represented only as collapsed debug evidence.
