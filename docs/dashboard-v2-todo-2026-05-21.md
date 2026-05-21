# Dashboard V2 TODO checklist

Status: **P0–P7 landing** — branch `feat/dashboard-v2-trust-guards` (2026-05-21). Dashboard V2 operator pass complete through styling cleanup; parking-lot items deferred.

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
- Live smoke after deploy:
  - `/healthz` returned OK;
  - V2 static asset `index-gHvwIXhi.js` was present;
  - events index returned 200;
  - event detail by `event_id` returned 200.

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

- [ ] Decide whether Vite remains sufficient or whether a future Next.js app is justified.
- [ ] If staying with Vite, define a small component system instead of one-off page components.
- [ ] Consider a dedicated `/dashboard-smoke` Playwright suite using captured fixtures.
- [ ] Consider screenshot/visual regression only after the information architecture stabilizes.
- [ ] Consider extracting API DTO schemas so frontend rendering cannot drift from backend read models.

## Resume order

When work resumes, do this sequence:

1. ~~Add/verify dashboard smoke script and route policy tests.~~ (P0)
2. ~~Make command results decisive and less generic.~~ (P1)
3. ~~Make project/run/paper/event/idea detail pages answer the entity-specific operator questions.~~ (P2 — [`detailOperatorSummary.ts`](../dashboard/src/detailOperatorSummary.ts))
4. ~~Reduce secondary page hero/header footprint.~~ (P3 — [`PageHeader.tsx`](../dashboard/src/components/PageHeader.tsx))
5. ~~Improve tables and empty/error states.~~ (P4 table pass — [`tablePresentation.ts`](../dashboard/src/tablePresentation.ts); P5 error/empty cards — [`resourceStatePresentation.ts`](../dashboard/src/resourceStatePresentation.ts))
6. ~~Audit routes, canonicalize aliases, and add detail breadcrumbs.~~ (P6 — [`routePolicy.ts`](../dashboard/src/routePolicy.ts))
7. ~~Polish table density, panel overflow, title wrapping, and focus rings.~~ (P7 — [`style.css`](../dashboard/src/style.css), [`styleGuards.test.ts`](../dashboard/src/styleGuards.test.ts))

