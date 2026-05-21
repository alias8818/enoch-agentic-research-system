# Dashboard redesign plan

Status: first vertical slice shipped. This document defines the dashboard contract so the UI does not drift back into raw backend-state exposure.

Current paused TODO tracker: [`dashboard-v2-todo-2026-05-21.md`](dashboard-v2-todo-2026-05-21.md).

## Goal

Make `/control/dashboard` feel like a professional shadcn-style operator console while preserving Enoch's new state model:

- answer operator questions first;
- keep raw database states in drill-down/debug areas;
- use bounded database-backed read-model endpoints by default;
- make paper work decision-gated and corpus-ledger aware;
- keep unattended token-spend actions explicit, bounded, and visible.

## Information architecture

Primary navigation:

1. **Overview** — operator cards, paper pipeline, active lane, health, recent events.
2. **Projects** — searchable project index and project detail drill-down.
3. **Active / Queued / Blocked** — queue-focused slices.
4. **Runs** — run list and run detail.
5. **Papers** — paper list and paper detail.
6. **Corpus Import** — finalized draft import gap, ledger-backed publish/import readiness, and imported-publication counts.
7. **Events** — bounded event log with payload summaries by default.
8. **Publication automation** — explicit rewrite/finalization lane; no human-approval framing.
9. **Ideas** — control-plane intake/workbench status; Notion is provenance only.
10. **Observability** — route/memory/worker freshness and debug health.

## Visual direction

The target is shadcn-like, not a copied template:

- sidebar navigation;
- top search + token/refresh controls;
- cards with light/dark color-scheme support;
- rounded borders, restrained shadows, table hover states;
- muted secondary metadata;
- status badges for actionable lanes only.

## API contract

The redesign must prefer bounded v1 endpoints:

- `/control/api/v1/overview`
- `/control/api/v1/queue`
- `/control/api/v1/runs`
- `/control/api/v1/projects/{project_id}`
- `/control/api/v1/papers`
- `/control/api/v1/events`
- `/control/api/v1/observability/health`
- `/control/api/v1/observability/memory`

Avoid defaulting to legacy heavy payload endpoints such as `/control/api/status`.

## Operator vocabulary

Lead with these labels:

- Needs attention
- Running now
- Ready to dispatch
- Write papers
- Finalize drafts
- Publish/import
- Published/imported
- Done / no paper

Raw states such as `wake_ready`, `draft_review`, `approved_for_finalization`, and `unreviewed` are allowed only in detail/debug views or API documentation as compatibility states.

## First vertical slice

The first shipped slice is the redesigned shell and overview experience:

- sidebar + topbar shell;
- shadcn-like cards/tables/theme variables;
- global search that routes to the projects view;
- token-required landing state that avoids unauthenticated API spam;
- bounded overview endpoint retained as source of truth;
- no new frontend build dependency.

## Follow-up slices

- **Trust guards (2026-05-21):** post-deploy GET/API smoke via [`scripts/dashboard_v2_smoke.py`](../scripts/dashboard_v2_smoke.py), dashboard Vitest in CI, DOM regression guards for collapsed raw JSON and detail hero titles, and deploy notes in [`dashboard-v2-deploy.md`](dashboard-v2-deploy.md). Rendering invariants stay in Vitest; smoke proves shell/assets/API health only.
- **Detail operator sections (2026-05-21):** entity-specific operator question grids, related entity link chips, and intake admission sections via [`detailOperatorSummary.ts`](../dashboard/src/detailOperatorSummary.ts) + Vitest acceptance tests in [`DetailPanel.test.tsx`](../dashboard/src/components/DetailPanel.test.tsx).
- **Compact secondary headers (2026-05-21):** shared [`PageHeader.tsx`](../dashboard/src/components/PageHeader.tsx) for list/detail/research/automation pages; command center keeps the large [`CommandHero`](../dashboard/src/components/CommandHero.tsx) treatment only on overview.
- **Operator-first tables (2026-05-21):** column specs and derived dispatch/evidence labels via [`tablePresentation.ts`](../dashboard/src/tablePresentation.ts); IDs render as compact chips with subtle copy controls in [`DataTable.tsx`](../dashboard/src/components/DataTable.tsx).
- **Error and empty states (2026-05-21):** endpoint-specific failure cards and composed idle/filtered/blocked table empties via [`resourceStatePresentation.ts`](../dashboard/src/resourceStatePresentation.ts) + [`ResourceStateCards.tsx`](../dashboard/src/components/ResourceStateCards.tsx); Vitest guards in [`resourceStatePresentation.test.ts`](../dashboard/src/resourceStatePresentation.test.ts) and [`ResourcePages.test.tsx`](../dashboard/src/components/ResourcePages.test.tsx).
- **Route policy (2026-05-21):** audited route catalog, alias canonicalization (`#reviews` → `#automation`, `#candidate:` → `#research:`, legacy `#status` → `#overview`), detail breadcrumbs, and parent-nav highlighting via [`routePolicy.ts`](../dashboard/src/routePolicy.ts) + [`routes.ts`](../dashboard/src/routes.ts).
- Extract the inline dashboard into static assets or a small frontend package if the UI keeps growing.
- Expand the corpus import view with direct links to public corpus artifacts and release-validator evidence.
- Add keyboard shortcut help and saved filters.
- Add screenshot-based visual regression for the dashboard shell.

## Performance slices

- The dashboard shell loads the bounded overview read model first and renders the primary operator cards before secondary observability/health calls complete.
- Route changes abort stale in-flight dashboard fetches so old overview responses cannot overwrite the newly selected tab and do not continue consuming backend work after navigation.
- Secondary tabs use their own bounded endpoints on demand; the shell does not call legacy `/control/api/status?refresh_worker=true` or broad unbounded list endpoints during initial render.
- The ideas page uses a batched read path and omits the large latest-intake payload by default.
