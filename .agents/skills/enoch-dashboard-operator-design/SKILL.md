---
name: enoch-dashboard-operator-design
description: Use before changing Enoch Dashboard V2 UI, routes, cards, tables, command results, detail pages, navigation, dashboard copy, read-model presentation, or dashboard assets. Prevents page sprawl, raw backend-state exposure, and non-operator dashboard clutter.
---

# Enoch Dashboard Operator Design

Use this skill before making any Enoch Dashboard V2 UI or dashboard read-model
presentation change.

## Core Rule

Dashboard V2 is an operator command center, not a data explorer.

Do not add a page, panel, card, table column, badge, route, metric, or visible
JSON field unless it answers a concrete operator question.

The first screen must answer:

1. Can I leave this running?
2. Are CPU and GB10 doing useful work?
3. If a lane is idle, why is it idle?
4. Is there enough queued backlog per lane?
5. What is the single safest next operator action?

If the proposed UI does not answer one of those, move it below the fold, put it
inside collapsed debug details, merge it into an existing route, or remove it.

## Required Design Review Before Coding

Before writing code, produce this short design review:

### 1. Symptom

What operator pain or failure is being fixed?

### 2. Operator Question

Pick the question the change answers:

- Can I leave this running?
- What is running now?
- Why is a lane idle?
- What is blocked?
- What should I do next?
- Is this safe to dispatch?
- Is this paper ready to finalize/import?
- What changed recently?
- What evidence/debug payload proves this?

### 3. Proposed Surface

Choose exactly one by default:

- existing command center section
- existing table/list
- existing detail panel
- existing detail route
- collapsed debug details
- route redirect/removal

Avoid new routes unless the route has a distinct operator job that cannot fit an
existing route.

### 4. Delete Or Demote

List what will be removed, hidden, collapsed, or demoted to secondary text.
Every addition should usually be paired with a deletion or demotion.

### 5. Invariant

State the deterministic invariant that prevents regression. Examples:

- raw JSON appears only inside `details.raw-details`
- command center renders one primary CTA above the fold
- red is used only for operator risk, not normal active work
- project/run/paper/event detail pages render structured summaries before debug payloads
- hero titles never start with raw backend prefixes like `project:`, `run:`, `paper:`, or `event:`

### 6. Test Plan

Pick the smallest tests that enforce the invariant.

Frontend:

```bash
cd dashboard
npm test -- --run
npm run typecheck
npm run lint
```

If dashboard source changes affect committed assets:

```bash
./scripts/rebuild_dashboard_v2_assets.sh
git add enoch_control_plane/control_plane/dashboard_v2/
python3 scripts/check_dashboard_v2_source_asset_pair.py --base origin/main
python3 scripts/validate_dashboard_v2_assets.py --skip-npm-ci
```

Backend/read-model semantics:

```bash
uv run pytest tests/test_control_plane_router.py -k "overview or dashboard or movement or lane" -q
uv run ruff check enoch_control_plane/control_plane/read_models.py enoch_control_plane/control_plane/router.py tests/test_control_plane_router.py
```

## UI Rules

Above the fold, the command center may show only:

1. Hero answer: `Yes`, `Check readiness first`, `Action available`, or `Blocked`
2. Readiness check state
3. CPU lane card
4. GB10 lane card
5. One primary action
6. Tiny paper pipeline strip

Everything else goes below the fold or into route-specific pages.

Red means operator risk only. Do not use red for normal active work, idle lanes
with no queued work, historical counts, completed no-paper items, or archived
blocked rows that do not affect current readiness.

Raw JSON is debug evidence only and must be inside collapsed `details.raw-details`.
Do not show giant visible JSON blocks, raw backend field names as primary labels,
or detail pages that only display an ID plus raw payload.

Every route must earn its existence. If a route only displays a title, ID, raw
object, or backend state dump, improve it into a structured operator page or
redirect to the nearest useful list/detail route.

Tables prioritize human-readable title, operator state, lane/target, next action
or blocker, updated age, and compact ID copy. IDs are never the main content.

## Required Final Report

At the end of dashboard work, report:

- files changed
- operator question answered
- UI removed, demoted, or collapsed
- invariant added or preserved
- exact tests run and results
- remaining risk
