# Dashboard redesign plan

Status: **P0–P7, Phase 2, and Phase 3 complete on `main`** (2026-05-21). V2 at `/control/dashboard-v2` is the canonical operator console; legacy `/control/dashboard` redirects with hash preserved. This document is the long-lived contract so the UI does not drift back into raw backend-state exposure.

Active checklist (ongoing discipline only): [`dashboard-v2-todo-2026-05-21.md`](dashboard-v2-todo-2026-05-21.md).

## Goal

Make `/control/dashboard-v2` feel like a professional shadcn-style operator console while preserving Enoch's new state model:

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
- **Styling cleanup (2026-05-21):** CSS-only filter select polish, tighter tables, detail-panel scroll containment, two-line primary title clamp, shared focus rings, and keyboard row selection in [`style.css`](../dashboard/src/style.css) + [`styleGuards.test.ts`](../dashboard/src/styleGuards.test.ts).
- **Framework (2026-05-21):** stay on Vite SPA; Next.js is not justified for the operator console — see [`dashboard-v2-framework-decision.md`](dashboard-v2-framework-decision.md).
- **Component system (2026-05-21):** shared UI primitives — [`dashboard-v2-component-system.md`](dashboard-v2-component-system.md), #98.
- **DTO boundaries (2026-05-21):** read-model DTO validation at API boundaries — #97.
- **Phase 2 command center (2026-05-21):** hero/readiness matrix (#84), dynamic movement title (#85), lane backlog depth (#86), single primary CTA (#88, #94), lane-owned dispatch/feed (#96), decorative movement strip removed (#99), hero state strip filtered (#101).
- **Phase 2 detail audits (2026-05-21):** project (#87), run (#100), paper (#104), event (#105), idea/intake (#106), research candidate (#108) — structured summaries via [`detailOperatorSummary.ts`](../dashboard/src/detailOperatorSummary.ts).
- **Phase 3 landed (2026-05-21):** narrow Playwright visual baselines (#109), corpus drill-down links ([`corpusLinks.ts`](../dashboard/src/corpusLinks.ts)), automation/research soft parity on dedicated pages, Phase 2 doc guards (#107), operator chrome — keyboard shortcut help ([`keyboardShortcuts.ts`](../dashboard/src/keyboardShortcuts.ts), [`KeyboardShortcutHelp.tsx`](../dashboard/src/components/KeyboardShortcutHelp.tsx)) and queue saved table filters in localStorage ([`savedTableFilters.ts`](../dashboard/src/savedTableFilters.ts)).
- Extract the inline dashboard into static assets or a small frontend package if the UI keeps growing (already done via `dashboard/` → committed `dashboard_v2/`).
- **Phase 3 complete (#110–#113, #109):** cutover audit doc sync, operator chrome, queue visual baseline, workbench KPI de-noise. **Ongoing:** read-model DTO hardening — see [`dashboard-v2-todo-2026-05-21.md`](dashboard-v2-todo-2026-05-21.md).

## Performance slices

- The dashboard shell loads the bounded overview read model first and renders the primary operator cards before secondary observability/health calls complete.
- Route changes abort stale in-flight dashboard fetches so old overview responses cannot overwrite the newly selected tab and do not continue consuming backend work after navigation.
- Secondary tabs use their own bounded endpoints on demand; the shell does not call legacy `/control/api/status?refresh_worker=true` or broad unbounded list endpoints during initial render.
- The ideas page uses a batched read path and omits the large latest-intake payload by default.
