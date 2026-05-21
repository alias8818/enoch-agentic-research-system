# Dashboard V2 Cursor instructions

Status: living implementation guidance for Dashboard V2. **Phase 2 (command center semantics + detail route audits) is complete on `main` (2026-05-21).** Use with [`dashboard-v2-todo-2026-05-21.md`](dashboard-v2-todo-2026-05-21.md) (Phase 3 optional items) and [`current-runtime-snapshot.md`](current-runtime-snapshot.md); treat this file as the product/design intent for any new PR.

## North star

Dashboard V2 is not a data explorer. It is an operator command center for Enoch.

The first screen must answer, in plain English:

1. **Can I leave this running?**
2. **Are CPU and GB10 doing useful work?**
3. **If a lane is idle, why is it idle?**
4. **Is there enough queued backlog per lane?**
5. **What is the single safest next operator action?**

If a card, table column, route, or JSON field does not help answer one of those questions, it belongs below a fold, inside debug details, or not in the UI.

## Non-negotiable product rules

### 1. Active work is healthy

A worker lane being occupied is not a bad state. It usually means the system is working.

Correct examples:

- CPU active + GB10 active + queued backlog -> **healthy / ready / normal active work**.
- CPU active + GB10 idle + GB10 queued work -> **actionable: dispatch GB10**.
- CPU active + GB10 idle + no GB10 queued work -> **actionable: feed GB10**.
- CPU active + GB10 blocked by worker conflict -> **blocked for GB10 only**, not generic red system health.

Incorrect examples:

- Red hero because CPU is occupied.
- `Not yet` only because one lane is running.
- Treating `all configured worker lanes active` as unhealthy. That can be ideal.

### 2. Red means operator risk, not normal activity

Use red/bad/blocked only for conditions that make unattended operation unsafe or require intervention:

- queue paused when it should be running;
- maintenance mode on;
- stale/missing worker preflight for a lane that needs dispatch;
- worker active-lane conflict;
- no matching machine target;
- blocked queue rows;
- readiness check failed;
- provider budget unavailable when automation depends on it;
- evidence/package gate failure for a paper action the operator is trying to perform.

Do not use red for:

- active lane;
- empty paper lane when there are no papers ready;
- completed no-paper candidates rejected by the deterministic gate;
- large historical counts;
- paused/blocked rows that are intentionally archived unless they affect current readiness.

### 3. Backend read models are truth

The frontend should not infer operational truth from loose counts.

Preferred flow:

- Backend computes read models: `movement_diagnosis`, `worker_lanes`, `top_actions`, `paper_pipeline`, `automation-readiness`.
- Frontend renders those read models.
- If the read model is wrong, fix the backend read model and add a deterministic backend test.

Do not paper over backend semantic bugs with frontend-only wording unless it is purely presentational.

### 4. Raw JSON is debug evidence only

Raw JSON must never be the main visible content of a page or command result.

Allowed:

```text
<details class="raw-details">
  <summary>Raw payload</summary>
  <pre class="json-block">...</pre>
</details>
```

Not allowed:

- giant visible JSON blocks in the command center;
- detail pages that show only an ID/title and a raw payload;
- API field names as primary labels when an operator-friendly label exists.

### 5. Every route must earn its existence

A route should answer an entity-specific operator question.

If a route only displays a title/ID/raw object, either:

1. improve it into a structured operator page; or
2. redirect to the closest useful list/detail route.

## Above-the-fold command center contract

Keep the command center ruthless. The first screen should contain only:

1. **Hero: Can I leave this running?**
   - Answer: `Yes`, `Check readiness first`, `Action available`, or `Blocked`.
   - Reason: one plain-English sentence.
   - Do not show red just because work is running.

2. **Readiness check**
   - Explicit on-demand check is acceptable.
   - When checked and passing, show `Long-haul mode: READY`.
   - When not checked, say `Check readiness first`, not `Ready`.

3. **Worker lanes**
   - CPU lane card.
   - GB10 lane card.
   - Each lane should show:
     - active/idle;
     - current project if active;
     - queued count;
     - next candidate if idle;
     - feed action;
     - dispatch availability;
     - one reason if disabled.

4. **One primary action**
   - Not three competing cards.
   - Examples: `Dispatch GB10`, `Feed idle lanes`, `Check readiness`, `Open blocker`.

5. **Tiny paper pipeline strip**
   - write -> finalize -> publish/import.
   - Do not show historical/no-paper/archive metrics above the fold.

Everything else goes below a hard fold or in route-specific pages.

## Worker lane semantics

Think lane-first, not global queue-first.

### Lane fields that matter

From `/control/api/status`:

- `worker_lanes[].machine_target`
- `worker_lanes[].status`
- `worker_lanes[].active_item`
- `worker_lanes[].queued_count`
- `worker_lanes[].next_candidate`
- `worker_lanes[].dispatch_available`
- `worker_lanes[].dispatch_blocker`
- `worker_lanes[].feed_pressure`

### Required lane behavior

- CPU lane and GB10 lane should be visible even if one is active.
- An active CPU lane must not hide GB10 dispatch availability.
- An active GB10 lane must not hide CPU dispatch availability.
- A worker preflight blocker should apply to the lane it came from, not globally, unless it is truly global.
- The queue should maintain backlog per lane; target default is currently 25 queued per lane.
- The dashboard should expose whether each lane is below desired queue depth.

### Plain-English disabled reasons

Use one reason, not a stack trace:

- `lane active`
- `queue paused`
- `maintenance mode`
- `no queued candidate for lane`
- `worker preflight stale`
- `worker conflict`
- `no matching machine target`
- `feed cycle needed`
- `readiness check required`

## Movement diagnosis semantics

`movement_diagnosis` answers: **why is work not moving, or what operator action is available?**

It should not be treated as synonymous with health.

Recommended status meanings:

- `ready`: no harmful blocker; active lanes are normal; unattended running is plausible if readiness passes.
- `actionable`: there is safe operator work to start, such as dispatching an idle queued lane.
- `blocked`: a real guardrail prevents safe progress.

Important distinction:

- `lane_active` is informational.
- `dispatch_available` is actionable.
- `lane_blocked`, `queue_paused`, `maintenance_mode`, `no_matching_machine_target`, `no_admitted_candidates`, and `lane_queue_empty` can be blockers.

If the hero uses `movement_diagnosis`, it must combine it with automation readiness semantics carefully:

- readiness unchecked -> `Check readiness first`;
- readiness failed -> `Blocked` / `Not yet`;
- readiness passed + movement ready -> `Yes — leave it running`;
- readiness passed + movement actionable -> `Action available`, not red;
- readiness passed + active lanes only -> `Yes — active work is running`.

## Automation readiness semantics

`/control/api/v1/automation-readiness` is the source for unattended/overnight safety.

Do not claim unattended readiness from movement diagnosis alone.

Good hero behavior:

| Readiness state | Movement state | Hero answer |
|---|---|---|
| unchecked | any | Check readiness first |
| checking | any | Checking readiness |
| failed | any | Not yet |
| ready | ready | Yes — leave it running |
| ready | actionable | Yes, but action is available |
| ready | blocked | Not yet |

Readiness blockers should be shown as concrete checks, not generic red state.

## Detail page contract

Each detail page needs a structured operator summary before any debug payload.

### Project detail page must answer

- What is this project?
- What is the current state?
- Which lane/machine owns it?
- What is the latest/current run?
- What happened most recently?
- Is action needed now?
- Is there a paper/publication path?

### Run detail page must answer

- Which project did this run execute?
- What is the current run/gate state?
- Which worker/lane/machine ran it?
- When did it start/update/finish?
- What is the current activity?
- Did it finish, fail, or wait for wake?
- Are artifacts/evidence available?
- What is the next safe action?

### Paper detail page must answer

- What is the paper status?
- Is evidence present?
- Is claim ledger present?
- Is finalization/package complete?
- Is it imported/published?
- What blocks publication?
- What is the next safe paper action?

### Event detail page must answer

- What happened?
- When?
- Which entity did it affect?
- What project/run/paper links relate to it?
- What does the payload prove? Keep payload collapsed.

### Idea/intake detail page must answer

- Where did the idea come from?
- Was it admitted, rejected, promoted, queued, or stale?
- Why?
- What project did it become, if promoted?
- What is the next operator action?

## Tables and lists

Tables should prioritize human-readable titles and operator state.

General rule:

- primary column: human title/name;
- secondary: status/lane/updated age;
- IDs: compact copy chip, not the main content;
- raw slugs: never hero titles;
- actions: contextual, not global.

### Projects table

Show:

- project title;
- status;
- lane/machine target;
- latest run state;
- paper status;
- updated age;
- compact ID chip.

### Queue table

Show:

- title;
- lane target;
- dispatch readiness;
- why it can/cannot dispatch;
- priority/rank;
- manual review state if relevant.

### Runs table

Show:

- project title;
- run state;
- gate state;
- lane;
- current activity;
- updated age;
- compact run ID chip.

### Papers table

Show:

- title;
- paper status;
- evidence availability;
- claim ledger availability;
- finalization/import state;
- next safe paper action.

### Events table

Show:

- event type;
- summary;
- entity link;
- timestamp;
- payload collapsed only in detail.

## Visual design direction

This should feel like a compact industrial operator console, not a SaaS analytics dashboard.

Use:

- dense but readable spacing;
- strong hierarchy;
- plain English labels;
- calm colors for normal operation;
- red only for real intervention;
- amber for pending/actionable;
- green/neutral for healthy running;
- compact cards over huge hero blocks except the command center hero.

Avoid:

- decorative KPI cards;
- generic “Done / no paper” cards on the main screen;
- historical/archive metrics above the fold;
- gradients and huge typography on every route;
- repeated branding blocks;
- nested cards with equal visual weight;
- raw backend field names as UX copy.

## Implementation discipline

Follow the Enoch operating rule:

> Never let an LLM interpretation become system truth unless a deterministic test, schema, or validator can enforce it later.

For every behavior change:

1. State the symptom.
2. Identify the invariant.
3. Add a failing deterministic test.
4. Patch the smallest root cause.
5. Run verification and report exact evidence.

## Testing expectations

### Backend/read-model changes

Use backend tests when semantics change.

Typical commands:

```bash
uv run pytest tests/test_control_plane_router.py -k "overview or dashboard or movement or lane" -q
uv run ruff check enoch_control_plane/control_plane/read_models.py enoch_control_plane/control_plane/router.py tests/test_control_plane_router.py
```

If touching readiness:

```bash
uv run pytest tests/test_longhaul_readiness.py tests/test_check_longhaul_readiness.py -q
```

### Frontend changes

From `dashboard/`:

```bash
npm test -- --run
npm run typecheck
npm run lint
```

If you changed **build-affecting** dashboard source (`dashboard/src/`, `package.json`, `vite.config.ts`, etc.), also rebuild and commit committed assets:

```bash
./scripts/rebuild_dashboard_v2_assets.sh
git add enoch_control_plane/control_plane/dashboard_v2/
python3 scripts/check_dashboard_v2_source_asset_pair.py --base origin/main
python3 scripts/validate_dashboard_v2_assets.py --skip-npm-ci
```

See [`dashboard-v2-asset-clca.md`](dashboard-v2-asset-clca.md). Test-only files (`*.test.ts(x)`) do not require asset commits, but hash validation is the final guard.

If changing route behavior, include route tests.

If changing rendering of command results or details, ensure:

- `.json-block` exists only inside `details.raw-details`;
- detail hero `h1` does not begin with `project:`, `run:`, `paper:`, or `event:`;
- empty/error states have operator guidance.

### Build/deploy note

CI intentionally does not rebuild assets. For live V2 deploy work, build manually:

```bash
cd dashboard
npm ci
npm run build
```

Then deploy per [`dashboard-v2-deploy.md`](dashboard-v2-deploy.md), and run smoke checks.

## Phase 2 outcomes (merged — do not re-open without new symptom)

These were the pre-Phase-2 gaps; each has a merged PR on `main`:

| Area | Merged PRs | Key files |
|------|------------|-----------|
| Hero / readiness matrix | #84 | `CommandHero.tsx` |
| Movement panel title | #85 | `movementPanelCopy.ts`, `MovementDiagnosis.tsx` |
| Lane backlog depth | #86 | `WorkerLanes.tsx` |
| Single primary CTA | #88, #94 | `PrimaryAction.tsx` |
| Lane-owned dispatch/feed | #96, #99 | `WorkerLanes.tsx`, `MovementDiagnosis.tsx` |
| Hero state strip filter | #101 | command center hero |
| Detail route audits | #87, #100, #104–#106 | `detailOperatorSummary.ts`, detail routes |

Resume with **Phase 3** items in [`dashboard-v2-todo-2026-05-21.md`](dashboard-v2-todo-2026-05-21.md), not by redoing PR A–F.

## Archived — Phase 2 Cursor PR sequence (complete)

Keep PRs narrow. Do not let Cursor do a “big dashboard cleanup” all at once. The sequence below is **done**; retained for audit trail.

### PR A — Hero semantics and copy

Goal: make the hero answer operational health correctly.

Scope:

- frontend `CommandHero` only unless backend read model is wrong;
- use readiness + movement status matrix above;
- update tests in `dashboard/src/App.test.tsx`.

Acceptance:

- active lanes + readiness ready -> not red;
- active lanes + readiness unchecked -> asks to check readiness;
- dispatch available + readiness ready -> action available, not blocked;
- real readiness blocker -> red/not yet.

### PR B — Movement panel dynamic title

Goal: stop showing “Why no work is moving?” when work is moving.

Scope:

- `MovementDiagnosis.tsx`;
- maybe small helper mapping status/blocker kinds to title/subtitle.

Acceptance:

- active lanes -> `What is moving now?`;
- dispatch available -> `What can I do next?`;
- real blockers -> `Why no work is moving?`.

### PR C — Lane backlog depth clarity

Goal: make queues understandable per lane.

Scope:

- `WorkerLanes.tsx`;
- render desired queue depth from `feed_pressure.desired_queue_depth`;
- show `queued / desired`;
- one feed reason per lane.

Acceptance:

- CPU and GB10 cards show `queued / desired`;
- below-depth lanes explain feed action;
- active lanes still show backlog waiting.

### PR D — Single primary action selector

Goal: one main CTA above the fold.

Scope:

- backend read model if needed: add/adjust a single `primary_operator_action`;
- frontend renders one CTA, not ranked cards.

Acceptance:

- if a lane can dispatch, primary action is dispatch that lane;
- if no lane can dispatch but a lane needs feed, primary action is feed;
- if readiness unchecked, primary action is readiness check;
- if blocked, primary action opens blocker context.

### PR E — Detail route audit follow-up

Goal: remove useless detail pages.

Scope:

- one entity kind per PR: project, run, paper, event, or idea.

Acceptance:

- page answers required detail-page questions;
- raw payload collapsed;
- no giant raw title/ID hero.

## Cursor prompt template

Use this when starting a dashboard PR:

```text
You are working in /home/jeremy/Desktop/projects/enoch-release/enoch-agentic-research-system.
Read AGENTS.md, docs/dashboard-v2-cursor-instructions.md, and docs/dashboard-v2-todo-2026-05-21.md first.

Task: <specific narrow PR goal>.

Rules:
- Do not add broad polish.
- Do not add more above-the-fold panels.
- Active worker lanes are healthy, not red/bad.
- Raw JSON only belongs in collapsed details.raw-details.
- Backend read models are truth; if semantics are wrong, fix backend and add deterministic tests.
- Keep the PR narrow and update tests.

Before implementing, summarize:
1. symptom;
2. invariant;
3. files you expect to touch;
4. tests you will add/update.

After implementing, run the relevant tests and report exact commands/results.
```

## Final mental model

The dashboard should not make the operator decode Enoch.

It should say:

- `Both lanes are running. Queue depth is healthy. You can leave this running.`
- `GB10 is idle with 14 queued. Dispatch GB10.`
- `CPU has no queued work. Feed CPU.`
- `Queue is paused. Resume queue before unattended operation.`
- `Worker conflict on GB10. Reconcile before dispatching GB10.`

That is the bar. Everything else is secondary.
