# Dashboard V2 cutover audit (legacy vs V2)

**Date:** 2026-05-21 (Phase 1 parity audit); **Phase 3 doc sync:** 2026-05-21
**Scope:** Phase 1 parity audit (Agent 1). Compared inline legacy shell (formerly `CONTROL_DASHBOARD_HTML` in `router.py`, removed after Phase 2 cutover) against V2 (`dashboard/src/routes.ts`, `routePolicy.ts`, components). Phase 3 update re-verifies gate table B1–B8 against landed V2 on `main`.
**Out of scope:** Backend redirect/cutover (Phase 2, merged), deploy.

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
| `#automation`, `#automation?…`, `#automation:{paperId}` | `AutomationPage` | Covered |
| `#reviews`, `#reviews?…`, `#review:{paperId}` | Aliased → `#automation…` | Covered (alias; `#reviews?…` fixed 2026-05-21) |
| `#intake`, `#idea:{id}`, `#intake:{id}` | `IntakePage` | Covered |
| `#research`, `#candidate:{id}`, `#research:{id}` | `ResearchPage` | Covered |
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
| Pause / resume queue | `POST /control/pause`, `/control/resume` | `SafetyBar.tsx` | Covered — pause sends `maintenance_mode: true`; resume sends `maintenance_mode: false` (see B7 VM verification) |
| Dry-run / live dispatch next | `POST /control/dispatch-next` | `PrimaryAction.tsx`, `WorkerLanes.tsx` | Covered |
| Dry-run / live dispatch one | `POST /control/dispatch-one` | `QueuePage.tsx`, `WorkerLanes.tsx` | Covered |
| Launch follow-up | `POST /control/api/v1/followups/launch-next` | `PrimaryAction.tsx` | Covered |
| Feed idle lane / bounded research cycle | `POST /control/api/research/run-cycle` | `WorkerLanes.tsx`, `ResearchPage.tsx` | Covered — V2 cycle payloads disable dispatch/wait/papers by default (`researchCyclePayloads.ts`) |
| Draft next paper | `POST /control/papers/draft-next` | `PrimaryAction.tsx` | Covered |
| Live rewrite batch (finalize lane) | `POST /control/api/paper-reviews/rewrite-batch` | `PrimaryAction.tsx`, `PaperMiniStrip.tsx` | Covered on overview — not on automation detail page |
| Provider budget check | `GET /control/api/research/provider-budget` | `ResearchPage.tsx` | Covered |
| Promote candidate | `POST /control/api/research/promote-candidate` | `ResearchPage.tsx` | Covered |
| Generate smoke / provider batches | `POST …/generate-batch`, `…/generate-provider-batch` | `ResearchPage.tsx` | Covered — dry-run → confirm → live on research workbench |
| Theme cycle light/dark | localStorage | `App.tsx` + `theme.ts` | Covered — light/dark toggle in app header |
| Global header search → `#projects?search=` | inline JS | `GlobalSearchForm` in `App.tsx` | Covered |

## Publication automation parity (explicit)

Legacy: `reviewsPage()` + `reviewDetail()` in `router.py` (~lines 299–310).
V2: `AutomationPage.tsx`.

| Capability | Legacy | V2 | Verdict |
|------------|--------|-----|---------|
| List rows | `GET /control/api/publication-automation` with search, review_status, paper_status, sort, page_size, pagination | `ListFilterBar` + bounded query (`page_size`, `search`, `review_status`, cursor pagination) | Covered |
| Open next publication-ready | `GET …/publication-automation/next` → `#automation:{id}` | `openNextReady()` on `AutomationPage` | Covered |
| Live GLM rewrite batch (10 papers) | `POST …/publication-automation/rewrite-batch` (`dry_run:false`, `force:true`) | Dry-run batch on automation page; live batch also on overview via `PrimaryAction` / `PaperMiniStrip` | Covered — per-paper live rewrite on automation detail |
| Per-paper live rewrite draft | `POST …/publication-automation/{id}/rewrite-draft` | `rewriteDraft` mutation on `AutomationPage` (confirm → live) | Covered |
| Per-paper live finalization package | `POST …/publication-automation/{id}/prepare-finalization-package` (`dry_run:false`) | Dry-run via `paper-reviews/{id}/…`; live via `publication-automation/{id}/prepare-finalization-package` after dry-run gate | Covered |
| Per-paper dry-run finalization | — (legacy live default) | Dry-run on `AutomationPage` | V2-only improvement |
| Checklist: pass / fail / accepted_risk | `POST …/checklist/{itemId}` all three | Pass, fail, and accepted_risk on `AutomationDetailCard` | Covered |
| Reject automation | `POST …/status` (`rejected`) | `rejectPaper` mutation on `AutomationPage` | Covered |
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
- Per-paper live rewrite, finalization, reject, and full checklist statuses on `AutomationPage`.
- Research generate-batch and generate-provider-batch with dry-run gates on `ResearchPage`.
- Global search and light/dark theme toggle in `App.tsx`.
- Unsupported routes show V2 suggestions only — **no legacy escape hatch** (removed Phase 2).

## Cutover gate table (B1–B8)

Phase 3 re-verification against landed V2 on `main` (2026-05-21). Source files: `SafetyBar.tsx`, `AutomationPage.tsx`, `ResearchPage.tsx`, `App.tsx`, `router.py`.

| ID | Original blocker | Phase 3 status | Evidence | Gate |
|----|------------------|----------------|----------|------|
| B1 | Per-paper **live** rewrite draft on automation detail | **Resolved** | `AutomationPage.tsx` → `POST …/publication-automation/{id}/rewrite-draft` (`rewriteDraft`, confirm dialog) | Pass |
| B2 | Per-paper **live** finalization package on automation detail | **Resolved** | `AutomationPage.tsx` → dry-run then `POST …/publication-automation/{id}/prepare-finalization-package` (`dry_run: false`) | Pass |
| B3 | Automation **reject** + checklist **fail/risk** | **Resolved** | `rejectPaper` + checklist pass/fail/accepted_risk on `AutomationDetailCard` | Pass |
| B4 | Automation list **filters/pagination** | **Resolved** | `ListFilterBar` (search, review_status, page cursor) on `AutomationPage` | Pass |
| B5 | Research **generate-batch** / **generate-provider-batch** | **Resolved** | `ResearchPage.tsx` dry-run → confirm → live for both endpoints | Pass |
| B6 | Legacy **theme toggle** + **global search** chrome | **Resolved** | `GlobalSearchForm` + `theme.ts` in `App.tsx`; no `Open legacy dashboard` link | Pass |
| B7 | V2 pause payload omits `maintenance_mode:true` | **Resolved (code)** — **operator VM check pending** | `SafetyBar.tsx` sends `maintenance_mode: true` on pause; Vitest guard in `CommandCenter.test.tsx`. Operators should confirm pause/resume on reference VM ([`current-runtime-snapshot.md`](current-runtime-snapshot.md), SSH `enoch-core.exe.xyz`) during deploy smoke. | Pass pending VM |
| B8 | Read-model links still emit `/control/dashboard#…` | **Resolved** | `router.py` `_enrich_queue_row` emits `/control/dashboard-v2#…`; legacy `/control/dashboard` 307-redirects to V2 | Pass |

### Cutover gate recommendation

| Gate criterion | Result |
|----------------|--------|
| Hash/route parity | **Pass** (with `#reviews?…` alias) |
| Daily dispatch / queue / papers | **Pass** |
| Automation page full legacy parity | **Pass** — B1–B4 resolved on `AutomationPage` |
| Research generation UI | **Pass** — B5 resolved on `ResearchPage` |
| Operator chrome (search, theme, no legacy escape) | **Pass** — B6 resolved |
| Pause / maintenance semantics | **Pass (code)** — B7 patched; confirm on live VM before declaring ops-ready |
| Backend link targets | **Pass** — B8 resolved |

**Cutover complete on `main`.** Remaining operator step: run B7 VM verification (pause queue → confirm `maintenance_mode` in overview flags → resume) on the reference control VM during the next deploy smoke. Only residual legacy-only gap: manual **claim review** on automation rows (AI pipeline actor; accepted drop).

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
cd dashboard && npm test -- --run src/components/AutomationPage.test.tsx src/components/CommandCenter.test.tsx src/App.test.tsx
uv run pytest tests/test_dashboard_v2_phase2_complete.py tests/test_control_plane_router.py::TestControlPlaneRouter::test_control_dashboard_legacy_path_redirects_to_v2 -q
```

**B7 operator VM step (not automated in CI):** on reference VM after deploy ([`current-runtime-snapshot.md`](current-runtime-snapshot.md)), pause queue from V2 command center, confirm overview shows `maintenance on`, then resume and confirm dispatch eligibility returns.

## References

- Reference control VM: [`current-runtime-snapshot.md`](current-runtime-snapshot.md) (SSH `enoch-core.exe.xyz`).
- Legacy shell: removed from `enoch_control_plane/control_plane/router.py` after Phase 2 redirect cutover; parity captured in this audit.
- V2 routes: `dashboard/src/routes.ts`, `dashboard/src/routePolicy.ts`
- Automation: `dashboard/src/components/AutomationPage.tsx`
- Phase 2 plan: `/home/jeremy/.cursor/plans/dashboard_v2_phase_2_a43293af.plan.md`
