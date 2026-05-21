# Dashboard V2 TODO checklist

Status: **Phase 2 complete; Phase 3 in progress on `main`** (2026-05-21). P0–P7, command-center semantics (#84–#96, #99–#101), detail-route audits (#87, #100, #104–#106), research candidate panel (#108), Phase 2 doc guards (#107), and narrow visual-regression foundation (#109) are merged. Dashboard V2 at `/control/dashboard-v2` is the canonical operator console on the reference control VM ([`current-runtime-snapshot.md`](current-runtime-snapshot.md), SSH `enoch-core.exe.xyz`). Remaining work is optional Phase 3 polish below — several items below were already landed but are now marked `[x]` so this doc stays the source of truth.

Screenshot evidence reviewed from:

```text
~/Pictures/Screenshots/new-enoch-dashboard-5-21/
```

## Current baseline

What is already live as of 2026-05-21:

- V2 command center is deployed under `/control/dashboard-v2`.
- PR #74 fixed the worst scaffold issues:
  - command results now show summarized operator fields before raw JSON;
  - raw payloads are collapsed under debug sections;
  - detail page headers use cleaner title/subtitle/short ID structure;
  - project/run/paper/event detail views include current-state and next-safe-action summaries;
  - `/control/api/v1/events?page_size=50&sort=recent` and event detail queries return 200 in live smoke tests.
- Live smoke after deploy (current bundle on `main`):
  - `/healthz` returned OK;
  - V2 static asset `index-BX2lBAxQ.js` was present (see `enoch_control_plane/control_plane/dashboard_v2/index.html`);
  - events index returned 200;
  - event detail by `event_id` returned 200.

## Cursor implementation guidance

For future Dashboard V2 work, start with [`dashboard-v2-cursor-instructions.md`](dashboard-v2-cursor-instructions.md). It captures the operator semantics, lane/readiness rules, anti-patterns, and suggested narrow PR sequence for Cursor-driven work.

## Product rule

Do not add another page or panel unless it answers an operator question.

If a view only dumps JSON, echoes an ID, or exposes raw backend state without interpretation, either:

1. replace it with a structured operator summary, or
2. remove/redirect the route to the nearest useful table/panel.

Raw JSON is allowed only as collapsed debug evidence.

## Priority 0 — keep the dashboard trustworthy

- [x] Add a small dashboard smoke script that checks the live V2 build after deployment:
  - [x] `/control/dashboard-v2` loads;
  - [x] current asset referenced by `index.html` exists (all JS/CSS refs parsed and GET-checked);
  - [x] `/control/api/v1/overview` returns 200;
  - [x] `/control/api/v1/events?page_size=50&sort=recent` returns 200;
  - [x] event detail with `event_id=...&include_payload=true&page_size=1&sort=recent` returns 200;
  - [x] no first-screen raw JSON block is visible in the command center — Vitest DOM guard in [`App.test.tsx`](../dashboard/src/App.test.tsx) (GET smoke cannot prove rendering).
- [x] Document the safe deploy command for V2 so rsync does not copy `.hypothesis`, `.coverage`, `.venv`, `.egg-info`, or `node_modules`. See [`dashboard-v2-deploy.md`](dashboard-v2-deploy.md).
- [x] Add a regression test that raw JSON labels are always inside collapsed `<details class="raw-details">` blocks (Vitest DOM inspection).
- [x] Add a regression test that detail hero `<h1>` values are human titles and never start with `project:`, `paper:`, `run:`, or `event:`.
- [x] Wire dashboard Vitest into CI (`npm ci`, `npm test -- --run`, `npm run typecheck`, `npm run lint` — no `npm run build` in CI).
- [x] Modest route policy tests: canonical hashes map to implemented pages (not a full P6 audit).

## Priority 1 — command result UX

Problem seen in screenshots: dispatch dry-run produced a giant JSON block in the main viewport. PR #74 improved this; P1 centralizes decisive titles/severity in [`commandResultPresentation.ts`](../dashboard/src/commandResultPresentation.ts).

- [x] Replace generic command-result titles like `Primary action dry-run` with action-specific titles:
  - [x] `Dispatch dry-run passed`;
  - [x] `Dispatch blocked`;
  - [x] `Paper finalize dry-run passed`;
  - [x] `Paper action blocked`.
- [x] Add explicit result severity styling:
  - [x] passed;
  - [x] dry-run only;
  - [x] blocked;
  - [x] failed;
  - [x] stale state.
- [x] Include the exact operator decision in each result card:
  - [x] `Safe to dispatch`;
  - [x] `Do not dispatch`;
  - [x] `Refresh and check again`;
  - [x] `Fix blocker first`.
- [x] Collapse or remove fields that are mostly backend implementation details (`Backend action` removed from primary grid).
- [x] Keep raw JSON in collapsed debug details only.

Acceptance test idea:

```text
Given a dry-run dispatch response,
when the result renders,
then the visible card contains result, selected project, lane/target, reason, and next action,
and the raw candidate JSON is visible only after expanding Raw JSON.
```

## Priority 2 — detail pages must become real pages

Problem seen in screenshots: direct routes showed huge raw IDs/slugs as hero text and minimal useful detail.

- [x] Project detail page should answer:
  - [x] What is this project?
  - [x] Is it queued, running, completed, blocked, or paper-ready?
  - [x] Which lane/machine target owns it?
  - [x] What is the current/latest run?
  - [x] What happened most recently?
  - [x] Is action needed now?
  - [x] Is there a paper row or publication status?
- [x] Run detail page should answer:
  - [x] What project did this run execute?
  - [x] Current state and gate state;
  - [x] worker/lane/machine target;
  - [x] start/update/finish timestamps;
  - [x] current activity;
  - [x] final reason/error if stopped;
  - [x] artifacts/evidence available;
  - [x] recent events for this run.
- [x] Paper detail page should answer:
  - [x] paper status;
  - [x] evidence/claim-ledger availability;
  - [x] draft/finalization/import status;
  - [x] artifact preview buttons;
  - [x] blocking checklist items;
  - [x] next safe paper action.
- [x] Event detail page should answer:
  - [x] event type;
  - [x] entity type and entity ID;
  - [x] timestamp;
  - [x] concise summary;
  - [x] related project/run/paper links;
  - [x] payload collapsed.
- [x] Intake idea detail page should answer:
  - [x] source and lineage;
  - [x] admission/promote/queue state;
  - [x] why it was or was not queued;
  - [x] related project if promoted;
  - [x] next operator action.

Acceptance test idea:

```text
For each detail kind, render a representative payload and assert visible text includes Current state, Next safe action, related IDs as chips/links, and no raw full ID in the hero h1.
```

## Priority 3 — reduce visual noise

The V2 direction is better, but the dashboard still has too much chrome and duplicated framing.

- [x] Re-evaluate the huge hero typography on secondary pages. It still consumes too much vertical space for operator work.
- [x] Use compact page headers for list/detail pages:
  - [x] title;
  - [x] short subtitle;
  - [x] refresh timestamp/action.
- [x] Reduce repeated `Enoch Dashboard V2 / Operator command center` branding on every page.
- [x] Keep the command center as the only page with a large hero treatment.
- [x] Move debug/meta labels such as endpoint names into small muted text or help details.
- [x] Avoid card nesting where a section inside a card contains more cards that look equally important.

## Priority 4 — table/list usefulness

Problem seen in screenshots: tables are usable but still expose raw IDs and backend-ish columns too prominently.

- [x] Projects table:
  - [x] primary visible column should be project title/name;
  - [x] project ID should be secondary/copy chip;
  - [x] show lane/target, status, latest run state, paper status, updated age;
  - [x] row click opens structured detail panel;
  - [x] copy button should not be the most visually prominent item.
- [x] Queue table:
  - [x] show dispatch readiness and lane match clearly;
  - [x] expose why a queued row can/cannot dispatch;
  - [x] make selected-row command card concise.
- [x] Runs table:
  - [x] show project title, run state, gate state, lane, updated age, current activity;
  - [x] hide raw run ID behind copy chip unless needed.
- [x] Papers table:
  - [x] show title, paper status, evidence availability, finalization/import status;
  - [x] direct action buttons should be contextual, not global.
- [x] Events table:
  - [x] event type and summary first;
  - [x] entity link second;
  - [x] payload never inline by default.

## Priority 5 — error and empty states

Problem seen in screenshots: `V2 data unavailable: endpoint -> 500` is technically true but operationally weak.

- [x] Replace generic API error cards with endpoint-specific guidance:
  - [x] what failed;
  - [x] whether dispatch is affected;
  - [x] what to check next;
  - [x] link/action to refresh;
  - [x] optional log command for operator runbook (`journalctl -u enoch-control-plane.service -n 160 --no-pager`).
- [x] Add composed empty states for:
  - [x] no queued work;
  - [x] no active runs;
  - [x] no paper actions;
  - [x] no events matching filters;
  - [x] no admitted/promoted ideas.
- [x] Empty state should answer whether the system is idle by design or blocked.

## Priority 6 — navigation and route policy

- [x] Audit every V2 route and classify:
  - [x] command center;
  - [x] list page;
  - [x] structured detail page;
  - [x] debug-only page;
  - [x] dead route to remove.
- [x] Any route that cannot be made useful should redirect to the relevant list page with a selected row/panel.
- [x] Add a visible back/breadcrumb affordance on detail pages.
- [x] Preserve deep links for project/run/paper/event IDs, but make the destination useful.

## Priority 7 — styling cleanup

Lower priority than operator usefulness.

- [x] Native select dropdowns are ugly; replace only if it can be done without adding fragile complexity.
- [x] Tighten table density and column spacing.
- [x] Improve right-side detail panel overflow behavior.
- [x] Ensure long titles wrap cleanly without dominating the screen.
- [x] Verify keyboard focus states after any custom control work.

## Parking lot — larger redesign questions

- [x] Decide whether Vite remains sufficient or whether a future Next.js app is justified. — [`dashboard-v2-framework-decision.md`](dashboard-v2-framework-decision.md); guarded by [`test_dashboard_v2_framework_decision.py`](../tests/test_dashboard_v2_framework_decision.py).
- [x] If staying with Vite, define a small component system instead of one-off page components. See [`dashboard-v2-component-system.md`](dashboard-v2-component-system.md) and [`components/ui/`](../dashboard/src/components/ui/).
- [x] Consider a dedicated `/dashboard-smoke` Playwright suite using captured fixtures (wired in CI via `npm run test:e2e`).
- [x] Consider screenshot/visual regression only after the information architecture stabilizes. — **Decision (2026-05-21):** IA is stable (P0–P7 + Phase 2 detail audits merged). Implemented a **narrow foundation** only: fixture-driven Playwright `toHaveScreenshot` for token gate + command center overview (`dashboard/e2e/visual.spec.ts`), deterministic locale/timezone/viewport in `playwright.config.ts`. **Deferred:** full route screenshot matrix until hero/movement copy polish settles; detail/list pages remain covered by Vitest + behavioral e2e.
- [x] Consider extracting API DTO schemas so frontend rendering cannot drift from backend read models.

## Completed — P0–P7 resume order

All items below merged to `main` before Phase 2:

1. ~~Add/verify dashboard smoke script and route policy tests.~~ (P0)
2. ~~Make command results decisive and less generic.~~ (P1)
3. ~~Make project/run/paper/event/idea detail pages answer the entity-specific operator questions.~~ (P2 — [`detailOperatorSummary.ts`](../dashboard/src/detailOperatorSummary.ts))
4. ~~Reduce secondary page hero/header footprint.~~ (P3 — [`PageHeader.tsx`](../dashboard/src/components/PageHeader.tsx))
5. ~~Improve tables and empty/error states.~~ (P4 table pass — [`tablePresentation.ts`](../dashboard/src/tablePresentation.ts); P5 error/empty cards — [`resourceStatePresentation.ts`](../dashboard/src/resourceStatePresentation.ts))
6. ~~Audit routes, canonicalize aliases, and add detail breadcrumbs.~~ (P6 — [`routePolicy.ts`](../dashboard/src/routePolicy.ts))
7. ~~Polish table density, panel overflow, title wrapping, and focus rings.~~ (P7 — [`style.css`](../dashboard/src/style.css), [`styleGuards.test.ts`](../dashboard/src/styleGuards.test.ts))

## Phase 2 — command center operator semantics (complete)

Merged per [`dashboard-v2-cursor-instructions.md`](dashboard-v2-cursor-instructions.md) PR sequence (2026-05-21).

- [x] PR A — Hero semantics and copy ([`CommandHero.tsx`](../dashboard/src/components/CommandHero.tsx), #84)
- [x] PR B — Movement panel dynamic title ([`movementPanelCopy.ts`](../dashboard/src/components/movementPanelCopy.ts), #85)
- [x] PR C — Lane backlog depth clarity ([`WorkerLanes.tsx`](../dashboard/src/components/WorkerLanes.tsx), #86)
- [x] PR D — Single primary operator action ([`PrimaryAction.tsx`](../dashboard/src/components/PrimaryAction.tsx), #88, #94)
- [x] PR E — Project detail route audit (#87)
- [x] PR F — Lane cards own dispatch/feed; collapse global bulk lane commands behind disclosure ([`WorkerLanes.tsx`](../dashboard/src/components/WorkerLanes.tsx), #96)
- [x] Remove static movement `reason-strip` chip row from [`MovementDiagnosis.tsx`](../dashboard/src/components/MovementDiagnosis.tsx) (decorative, not backend-driven; #99)
- [x] Filter hero state strip to active/queued only; keep paper counts in [`PaperMiniStrip`](../dashboard/src/components/PaperMiniStrip.tsx) (#101)
- [x] Detail route audit follow-up: run detail page (#100)
- [x] Detail route audit follow-up: paper detail page (worker-4b-retry, #104)
- [x] Detail route audit follow-up: event detail page (worker-4c, #105)
- [x] Detail route audit follow-up: idea detail page (worker-idea-detail-audit, #106)
- [x] Detail route audit follow-up: research facility candidate panel ([`deriveResearchCandidateOperatorSummary`](../dashboard/src/detailOperatorSummary.ts), #108)

## Phase 3 — optional follow-ups

No blocking gate. Pick one narrow PR at a time; keep [`dashboard-v2-cursor-instructions.md`](dashboard-v2-cursor-instructions.md) product rules.

### Visual regression

- [x] Narrow foundation: fixture-driven Playwright `toHaveScreenshot` for token gate + command center overview (#109, [`visual.spec.ts`](../dashboard/e2e/visual.spec.ts)).
- [ ] One list-page baseline — add `#projects` or `#queue:queued` screenshot only; defer full route matrix until hero/movement copy settles.

### Workbench and corpus UX

- [x] Corpus import drill-down — public corpus index, per-paper URLs, and release-validator links on `#corpus` ([`corpusLinks.ts`](../dashboard/src/corpusLinks.ts), [`ResourcePages.tsx`](../dashboard/src/components/ResourcePages.tsx); tests in [`corpusLinks.test.ts`](../dashboard/src/corpusLinks.test.ts)).
- [ ] **Workbench KPI noise (narrow PR)** — replace decorative `count-grid` / `count-card` rows on Intake, Research, and Automation workbench pages (and optionally soften Corpus summary cards) with one backend-driven operator sentence or collapse counts below the table fold. Anti-pattern: decorative KPI cards ([`dashboard-v2-cursor-instructions.md`](dashboard-v2-cursor-instructions.md) § Visual design).

### Cutover audit and legacy parity

- [x] B7 pause semantics in UI — [`SafetyBar.tsx`](../dashboard/src/components/SafetyBar.tsx) sends `maintenance_mode: true` on pause (verify on live VM during doc closure).
- [x] B8 read-model dashboard links — backend emits `/control/dashboard-v2#…` ([`router.py`](../enoch_control_plane/control_plane/router.py)); legacy `/control/dashboard` 307-redirects to V2.
- [x] Automation parity (soft, B1–B3) — per-paper live rewrite, finalization package, and reject on [`AutomationPage.tsx`](../dashboard/src/components/AutomationPage.tsx) (dry-run first).
- [x] Research generate-batch UI (B5) — dry-run + live generate/provider batch on [`ResearchPage.tsx`](../dashboard/src/components/ResearchPage.tsx).
- [x] Global search + theme toggle (B6) — [`GlobalSearchForm`](../dashboard/src/App.tsx), light/dark theme in [`theme.ts`](../dashboard/src/theme.ts); no legacy escape hatch.
- [ ] **Cutover audit doc sync** — update [`dashboard-v2-cutover-audit.md`](dashboard-v2-cutover-audit.md) gate table (B1–B8) to reflect landed V2 behavior; note VM verification for B7.

### Operator chrome and discipline

- [ ] Keyboard shortcut help and saved table filters ([`dashboard-redesign-plan.md`](dashboard-redesign-plan.md) follow-up).
- [ ] Read-model hardening (ongoing) — extend DTO boundary tests ([#97](../dashboard/src/api/readModelSchemas.ts)) when adding overview/lane/intake fields; fix semantics in backend first per cursor instructions.

