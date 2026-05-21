# Dashboard V2 cutover audit (legacy vs V2)

**Date:** 2026-05-21  
**Scope:** Phase 1 parity audit (Agent 1). Compared inline legacy shell (formerly `CONTROL_DASHBOARD_HTML` in `router.py`, removed after Phase 2 cutover) against V2 (`dashboard/src/routes.ts`, `routePolicy.ts`, components).  
**Out of scope:** Backend redirect/cutover (Phase 2), deploy.

## Method

1. Inventory legacy nav hashes (`pages` array, `route()` switch) and inline commands (`postJson` / `api` calls).
2. Map each hash to V2 `parseDashboardRoute` + `canonicalDashboardHash`.
3. Compare operator commands page-by-page, with extra depth on **Publication automation** (`AutomationPage.tsx` vs legacy `reviewsPage` / `reviewDetail`).
4. Classify gaps into **covered**, **V2-only**, **legacy-only blockers**; resolve trivial hash aliases in `routes.ts` (`canonicalDashboardHash`).

## Route / navigation parity

| Legacy hash | V2 destination | Status |
|-------------|----------------|--------|
| `#overview` | Command center (`App.tsx` → `OverviewPage`) | Covered |
| `#projects`, `#projects?…` | `ProjectsPage` | Covered |
| `#queue:active`, `#queue:queued`, `#queue:blocked`, `#queue?…` | `QueuePage` (`#queue:{status}`) | Covered |
| `#runs`, `#runs?…`, `#runs:{state}` | `RunsPage` | Covered |
| `#papers`, `#papers?…` | `PapersPage` | Covered |
| `#corpus` | `CorpusPage` | Covered |
| `#events`, `#events?…` | `EventsPage` | Covered |
| `#automation`, `#automation?…`, `#automation:{paperId}` | `AutomationPage` | Covered (commands partial — see automation section) |
| `#reviews`, `#reviews?…`, `#review:{paperId}` | Aliased → `#automation…` | Covered (alias; `#reviews?…` fixed 2026-05-21) |
| `#intake`, `#idea:{id}`, `#intake:{id}` | `IntakePage` | Covered |
| `#research`, `#candidate:{id}`, `#research:{id}` | `ResearchPage` | Covered (commands partial) |
| `#observability` | `ObservabilityPage` | Covered |
| `#project:{id}`, `#run:{id}`, `#paper:{id}` | `DetailPage` (structured) | Covered — V2 **superset** (legacy detail was raw field dump) |
| `#event:{id}` | `DetailPage` (event) | **V2-only** — legacy had no `#event:` route (fell through to overview) |
| `#status`, `#status?…` | Aliased → `#overview` | Covered |
| `#dispatch`, `#dispatch-one`, `#dispatch?…` | Aliased → `#queue:queued` | Covered (dead legacy bookmark → queue) |
| `#workers`, `#workers?…` | Aliased → `#overview` | Covered |
| `#queue` (no slice) | `QueuePage` (empty status) | V2-only behavior — legacy treated unknown bare `#queue` as overview fallback |

### Hash aliases (canonical)

Implemented in `dashboard/src/routes.ts` → `canonicalDashboardHash`:

- `#review:` → `#automation:`
- `#reviews` / `#reviews?…` → `#automation` / `#automation?…`
- `#candidate:` → `#research:`
- `#idea:` → `#intake:`
- `#status` / `#status?…` → `#overview`
- `#dispatch*` → `#queue:queued`
- `#workers*` → `#overview`

`routePolicy.ts` classifies surfaces only; aliases live in `routes.ts`.

## Operator command parity (non-automation)

| Legacy command | Endpoint | V2 surface | Status |
|----------------|----------|------------|--------|
| Pause / resume queue | `POST /control/pause`, `/control/resume` | `SafetyBar.tsx` | Covered — V2 pause omits explicit `maintenance_mode:true` (backend may still set; verify if pause semantics diverge) |
| Dry-run / live dispatch next | `POST /control/dispatch-next` | `PrimaryAction.tsx`, `WorkerLanes.tsx` | Covered |
| Dry-run / live dispatch one | `POST /control/dispatch-one` | `QueuePage.tsx`, `WorkerLanes.tsx` | Covered |
| Launch follow-up | `POST /control/api/v1/followups/launch-next` | `PrimaryAction.tsx` | Covered |
| Feed idle lane / bounded research cycle | `POST /control/api/research/run-cycle` | `WorkerLanes.tsx`, `ResearchPage.tsx` | Covered — V2 cycle payloads disable dispatch/wait/papers by default (`researchCyclePayloads.ts`) |
| Draft next paper | `POST /control/papers/draft-next` | `PrimaryAction.tsx` | Covered |
| Live rewrite batch (finalize lane) | `POST /control/api/paper-reviews/rewrite-batch` | `PrimaryAction.tsx`, `PaperMiniStrip.tsx` | Covered on overview — not on automation detail page |
| Provider budget check | `GET /control/api/research/provider-budget` | `ResearchPage.tsx` | Covered |
| Promote candidate | `POST /control/api/research/promote-candidate` | `ResearchPage.tsx` | Covered |
| Generate smoke / provider batches | `POST …/generate-batch`, `…/generate-provider-batch` | — | **Legacy-only** — accepted drop for cutover (use API/CLI; not daily operator path) |
| Theme cycle light/dark/auto | localStorage | — | **Legacy-only** — accepted drop (cosmetic) |
| Global header search → `#projects?search=` | inline JS | Projects page filter bar | **Legacy-only** UI — equivalent capability on list pages |

## Publication automation parity (explicit)

Legacy: `reviewsPage()` + `reviewDetail()` in `router.py` (~lines 299–310).  
V2: `AutomationPage.tsx`.

| Capability | Legacy | V2 | Verdict |
|------------|--------|-----|---------|
| List rows | `GET /control/api/publication-automation` with search, review_status, paper_status, sort, page_size, pagination | Fixed query: `page_size=50`, `paper_status=publication_draft`, `sort=-rank_score` | **Legacy-only** — accepted drop if operators rarely filter; otherwise post-cutover UX |
| Open next publication-ready | `GET …/publication-automation/next` → `#automation:{id}` | — | **Legacy-only** — accepted drop (manual row select) |
| Live GLM rewrite batch (10 papers) | `POST …/publication-automation/rewrite-batch` (`dry_run:false`, `force:true`) | Dry-run only on page; **live** batch on overview via `PrimaryAction` / `PaperMiniStrip` (`paper-reviews/rewrite-batch`) | **Partial** — live path moved to command center, not automation page |
| Per-paper live rewrite draft | `POST …/publication-automation/{id}/rewrite-draft` | — | **Legacy-only blocker** — no V2 equivalent |
| Per-paper live finalization package | `POST …/publication-automation/{id}/prepare-finalization-package` (`dry_run:false`) | Dry-run only via `paper-reviews/{id}/prepare-finalization-package` | **Legacy-only blocker** — live package prep missing |
| Per-paper dry-run finalization | — (legacy live default) | Dry-run on `AutomationPage` | V2-only improvement |
| Checklist: pass / fail / accepted_risk | `POST …/checklist/{itemId}` all three | Pass only | **Legacy-only** — fail/risk accepted drop unless policy requires |
| Reject automation | `POST …/status` (`rejected`) | — | **Legacy-only blocker** |
| Claim review | `POST …/claim` | — | **Legacy-only** — accepted drop (AI pipeline actor; rarely manual) |
| Artifact preview | `GET /control/api/papers/{id}/artifact/{field}` | Same | Covered |
| Detail checklist + rank reasons | Inline tables | `AutomationDetailCard` | Covered |

## Covered (ready for cutover redirect)

- All legacy sidebar destinations have V2 pages.
- Core operator loop: overview hero, movement diagnosis, worker lanes, queue safety, primary action, queue/projects/runs/papers/events tables, structured detail pages.
- Dispatch and follow-up commands with dry-run → confirm → live pattern.
- Corpus import list, observability debug page, intake workbench, research facility (promote + bounded cycle).
- Legacy hash aliases for `#reviews`, `#review:`, `#candidate:`, `#idea:`, `#status`, `#dispatch*`, `#workers*`.
- Deep links `#project:`, `#run:`, `#paper:` — V2 is strictly better than legacy raw JSON detail.

## V2-only (improvements, not blockers)

- `#event:{id}` structured event detail (legacy had no route).
- Command result cards (`CommandResultSummary`) with severity and operator decision text.
- Structured detail operator summaries (`detailOperatorSummary.ts`).
- Compact page headers, empty/error cards, breadcrumbs.
- Readiness check card on overview (legacy loaded full card only in secondary fold).
- Dry-run-first automation commands on `AutomationPage` (safer default).
- Escape hatch link to legacy on unsupported routes (`App.tsx`) — **remove in Phase 2 (Agent 7)**.

## Legacy-only blockers

Each item needs **implement**, **alias/workaround**, or **explicit accept** before cutover gate.

| ID | Blocker | Resolution | Gate |
|----|---------|------------|------|
| B1 | Per-paper **live** rewrite draft on automation detail | **Accept for cutover** — use overview live finalize batch or direct API; document in runbook | Soft |
| B2 | Per-paper **live** finalization package on automation detail | **Accept for cutover** — dry-run on automation page; live via API if needed | Soft |
| B3 | Automation **reject** + checklist **fail/risk** | **Accept for cutover** — pass-only checklist covers happy path; edge policy via API | Soft |
| B4 | Automation list **filters/pagination** | **Accept for cutover** — fixed sort sufficient for ≤50 rows; revisit if queue grows | Soft |
| B5 | Research **generate-batch** / **generate-provider-batch** | **Accept for cutover** — research page keeps promote + bounded cycle; generation via API | Soft |
| B6 | Legacy **theme toggle** + **global search** chrome | **Accept for cutover** — cosmetic / duplicated on list filters | Soft |
| B7 | V2 pause payload omits `maintenance_mode:true` | **Verify backend** — if pause semantics differ, fix `SafetyBar` before cutover | Hard if confirmed |
| B8 | Read-model links still emit `/control/dashboard#…` | **Phase 2 (Agent 6)** — not a V2 frontend gap | Tracked |

### Cutover gate recommendation

| Gate criterion | Result |
|----------------|--------|
| Hash/route parity | **Pass** (with `#reviews?…` alias) |
| Daily dispatch / queue / papers | **Pass** |
| Automation page full legacy parity | **Fail soft** — B1–B4 accepted with operator note |
| Research generation UI | **Fail soft** — B5 accepted |
| Backend link targets | **Pass** — B8 resolved; read-model links use `/control/dashboard-v2#…` |

**Proceed to Phase 2 redirect** when product owner accepts B1–B6 as documented drops and B7 is verified (or patched). Hard blocker remains only if operators require per-paper live rewrite/finalize/reject exclusively from the automation detail page without API fallback.

## Files changed (Agent 1)

| File | Change |
|------|--------|
| `docs/dashboard-v2-cutover-audit.md` | Created (this document) |
| `dashboard/src/routes.ts` | `#reviews?…` → `#automation?…` in `canonicalDashboardHash` |
| `dashboard/src/routePolicy.test.ts` | Regression for `#reviews?…` alias |
| `dashboard/src/routes.test.ts` | `dashboardV2Href` coverage for `#reviews?search=` |

## Verification

```bash
cd dashboard && npm test -- --run src/routePolicy.test.ts src/routes.test.ts
```

## References

- Legacy shell: removed from `enoch_control_plane/control_plane/router.py` after Phase 2 redirect cutover; parity captured in this audit.
- V2 routes: `dashboard/src/routes.ts`, `dashboard/src/routePolicy.ts`
- Automation: `dashboard/src/components/AutomationPage.tsx`
- Phase 2 plan: `/home/jeremy/.cursor/plans/dashboard_v2_phase_2_a43293af.plan.md`
