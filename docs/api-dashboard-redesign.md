# API and dashboard redesign plan

This plan captures the next architectural lane for the private Enoch operator API and dashboard. It is intentionally conservative: first make the read paths bounded and observable, then replace the raw-output dashboard with a professional operator experience.

## Why this exists

The control-plane/dashboard process has shown memory-pressure behavior on the 8 GiB controller VM. The current dashboard also exposes too much raw JSON/log output as first-screen content, which makes the system look patchworked and harder to operate.

The redesign target is:

- bounded API read models;
- clear command/read separation;
- a professional dashboard organized around operator tasks;
- memory and response-size observability;
- a migration path that does not break dispatch, wake callbacks, paper production, or Notion sync.

## Current risk surfaces

- `omx_wake_gate/app.py` serves the wake-gate dashboard and `/dashboard/api` from a large monolithic FastAPI module.
- `/dashboard/api` calls `store.list_runs()`, computes truth for all run records, sorts all records, samples telemetry, reads queue and paper snapshots, and returns recent events.
- `/dashboard/api/run/{run_id}` loads one run but still calls `store.list_runs()` to calculate supersession state.
- `StateStore.list_runs()` parses every `state/runs/*.json` file.
- `control_plane/router.py` has useful API structure, but dashboard-facing endpoints still commonly fetch all queue, paper, or event rows and then filter/page in Python.
- `ControlPlaneStore.queue_rows()`, `paper_rows()`, and `run_rows()` return full tables. `status_counts()` and `active_items()` currently depend on full queue reads.
- Raw artifact/event responses are valuable for debugging, but they should not be the primary UI.

## Target API shape

Keep command APIs stable and explicit:

- queue pause/resume;
- dispatch-next;
- worker-callback;
- Notion intake;
- paper draft/review/finalization mutations;
- preflight/alerts.

Add a bounded, versioned dashboard read API:

```text
/control/api/v1/overview
/control/api/v1/lanes
/control/api/v1/queue?page_size=&cursor=&status=&search=
/control/api/v1/runs?page_size=&cursor=&state=&lifecycle=&project_id=
/control/api/v1/runs/{run_id}
/control/api/v1/papers?page_size=&cursor=&status=&search=
/control/api/v1/papers/{paper_id}
/control/api/v1/events?page_size=&cursor=&entity_id=&event_type=&search=
/control/api/v1/observability/memory
/control/api/v1/observability/health
```

Rules:

- Dashboard list endpoints are bounded before Python processing.
- Default page size is small; hard cap is explicit.
- Overview returns aggregate cards and the top actionable items only.
- Detail endpoints lazy-load expensive sections.
- Raw payloads and artifacts require deliberate debug/detail requests and byte caps.

## Proposed module boundaries

```text
omx_wake_gate/
  app.py                         # app factory and router mounting only
  dashboard/
    router.py                    # HTML shell and dashboard API facade
    read_models.py               # bounded dashboard projections
    serializers.py               # redacted stable DTOs
    static/                      # CSS/JS or generated assets
  control_plane/
    router.py                    # canonical command/read APIs
    read_models.py               # SQL-backed bounded projections
    store.py                     # mutations and low-level queries
  wake_gate/
    router.py                    # wake-gate run/event API
    read_models.py               # bounded run projections
  observability/
    memory.py                    # RSS/tracemalloc/psutil snapshots
    middleware.py                # route timing/size/memory deltas
```

## Dashboard UX model

Primary navigation:

1. **Overview** — Controller, GB10, Queue, Paper lane, Notion sync, Memory, and one “needs attention” list.
2. **Work Queue** — paginated projects with status, priority, last state, next action, and age.
3. **GB10 / Wake Gate** — active lane, quiet-window/callback status, attention items, and bounded history.
4. **Papers** — draft/review/finalized lanes and artifact status, with raw artifacts hidden by default.
5. **Events** — bounded searchable audit log with summaries first and payloads expandable.
6. **Observability** — memory trend, request latency, response sizes, route errors, and restart evidence.

UX principles:

- status and next action before raw evidence;
- warnings include source, authority, observed time, and suggested action;
- raw JSON/logs are collapsed under evidence/debug panels;
- normal views redact secrets and absolute private paths;
- copy uses consistent operational vocabulary.

## Implementation roadmap

### Phase 0: Baseline and observability

- Add a memory smoke script for dashboard/control endpoints. Initial tool: `scripts/dashboard_memory_smoke.py`.
- Measure RSS before and after repeated calls to current dashboard endpoints.
- Add route timing and response-size middleware behind a config flag. Initial module: `omx_wake_gate.observability.RouteObservationMiddleware`.
- Document route ownership and data growth risks.

### Phase 1: Bounded read models

- Add SQL-backed bounded queries for queue, papers, events, active rows, and counts.
- Add a wake-gate run index so list views do not parse every run JSON file.
- Add `/control/api/v1/*` read-model endpoints.
- Lock these endpoints with unit and API tests.

### Phase 2: Dashboard shell redesign

- Replace first-screen raw output with professional cards/tables/drawers.
- Move raw JSON/log views behind explicit evidence/debug affordances.
- Keep legacy endpoints available during migration.

### Phase 3: Migration and compatibility

- Move dashboard data loading to v1 endpoints.
- Mark heavyweight legacy endpoints as deprecated or debug-only.
- Update deployment docs and operator screenshots.

### Phase 4: Retention and memory hardening

- Add retention/rotation for wake-gate events and historical run projections.
- Add controller memory guardrails after bounded endpoints are proven.
- Add scheduled or CI memory regression checks with large fixtures.

## Acceptance criteria

- Repeated dashboard polling does not grow RSS unboundedly under a fixture dataset at least as large as production.
- The primary dashboard does not show raw JSON/log dumps as first-screen content.
- v1 list endpoints enforce hard caps and return page/cursor metadata.
- Overview loads from aggregate read models and does not parse all run JSON files.
- Active lane, queue health, paper lane, GB10 state, and memory pressure are human-readable.
- Existing dispatch, callback, paper, Notion, and preflight tests continue passing.
- Auth remains required and normal dashboard responses do not leak secrets or absolute private paths.

## Test plan summary

- Store/read-model tests for bounded queue, paper, event, run, active, and count queries.
- API contract tests for every `/control/api/v1/*` endpoint.
- Memory regression fixture with thousands of runs/events and repeated endpoint polling.
- UX/static checks that first-screen dashboard content is card/table based, not raw `<pre>` output.
- Security tests for auth, token redaction, path redaction, traversal rejection, and artifact truncation.
- Live smoke on the controller after deployment: health, timers, GB10 status, endpoint polling, and before/after RSS.
