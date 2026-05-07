# Dashboard redesign plan

Status: first vertical slice shipped. This document defines the dashboard contract so the UI does not drift back into raw backend-state exposure.

## Goal

Make `/control/dashboard` feel like a professional shadcn-style operator console while preserving Enoch's new state model:

- answer operator questions first;
- keep raw database states in drill-down/debug areas;
- use bounded Supabase read-model endpoints by default;
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
9. **Ideas** — Supabase-native intake/workbench status; Notion is provenance only.
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

- Extract the inline dashboard into static assets or a small frontend package if the UI keeps growing.
- Add dedicated project/run/paper detail layouts instead of generic detail sections.
- Expand the corpus import view with direct links to public corpus artifacts and release-validator evidence.
- Add keyboard shortcut help and saved filters.
- Add screenshot-based visual regression for the dashboard shell.

## Performance slices

- The dashboard shell loads the bounded overview read model first and renders the primary operator cards before secondary observability/health calls complete.
- Route changes abort stale in-flight dashboard fetches so old overview responses cannot overwrite the newly selected tab and do not continue consuming backend work after navigation.
- Secondary tabs use their own bounded endpoints on demand; the shell does not call legacy `/control/api/status?refresh_worker=true` or broad unbounded list endpoints during initial render.
- The Supabase ideas page uses a batched read path and omits the large latest-intake payload by default.
