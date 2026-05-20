# Autonomous Hardening Loop Ledger — 2026-05-20

## Pass 1 — dashboard secondary request aborts

- **Target:** dashboard API timeout/abort/loading behavior.
- **Invariant:** stale route aborts must not render operator-facing error banners or replace fresh overview panels with false unavailable states.
- **Bug found:** yes. `route()` ignored `AbortError`, but secondary overview requests and `refreshCommandPanel()` caught aborted fetches and rendered fallback errors such as `Command state unavailable: signal is aborted without reason` or panel unavailable text.
- **Proof:** added `ControlPlaneRouterTests.test_dashboard_html_links_to_multiview_apis` assertion requiring abort guards in the route handler and every async secondary overview panel. The test failed before the patch.
- **Patch:** ignored `AbortError` in `refreshCommandPanel()`, worker-lane refresh, automation-readiness refresh, and overview-health refresh.
- **Verification:**
  - `uv run pytest -q tests/test_control_plane_router.py::ControlPlaneRouterTests::test_dashboard_html_links_to_multiview_apis` → `1 passed` after red failure.
  - `uv run pytest -q tests/test_control_plane_router.py tests/test_read_model_reconciliation.py tests/test_alerts.py -k 'dashboard_html_links_to_multiview_apis or dashboard_status or worker_lane or lane or overview'` → `177 passed, 31 deselected`.
  - `python3 -m py_compile enoch_control_plane/control_plane/router.py` → passed.
  - `git diff --check` → passed.
  - `uv run pytest -q` → `1011 passed, 4 warnings, 37 subtests passed`.
- **Live verification:** deployed `router.py` to `/opt/enoch-control-plane`, restarted `enoch-control-plane.service`, `/healthz` returned `ok: true`, and live `/control/dashboard` contains five `AbortError` guards.
- **Commit:** `2bfe533` (`fix(dashboard): ignore stale aborts in overview panels`).

## Pass 2 — long-haul queue consistency with open worker lanes

- **Target:** queue active/queued consistency and worker lane dispatch truth.
- **Invariant:** if queued work is dispatchable on an open worker lane, long-haul readiness must require a top-level `next_candidate`; `active > 0` is only acceptable backpressure when queued work is blocked behind busy lanes.
- **Bug found:** yes. `queue_counts_consistent` treated any `active > 0` as enough to make queued work with no `next_candidate` consistent, even when another lane was open and had queued dispatchable work.
- **Proof:** added `test_open_lane_queued_work_requires_top_level_next_candidate`; it failed before the patch.
- **Patch:** `evaluate_longhaul_readiness()` now derives `open_lane_has_queued_work` from `worker_lanes[].dispatch_available` and blocks readiness if that is true while `next_candidate` is missing.
- **Verification:**
  - `uv run pytest -q tests/test_longhaul_readiness.py::test_open_lane_queued_work_requires_top_level_next_candidate tests/test_longhaul_readiness.py::test_multi_lane_active_queue_counts_are_consistent_when_all_lanes_busy tests/test_longhaul_readiness.py::test_multi_active_without_lane_capacity_blocks_queue_count_consistency` → `3 passed`.
  - `python3 -m py_compile enoch_control_plane/control_plane/longhaul_readiness.py` → passed.
  - `git diff --check` → passed.
  - `uv run pytest -q tests/test_longhaul_readiness.py tests/test_control_plane_router.py -k 'queue_counts_consistent or dashboard_status_reports_worker_lane_capacity or overview_and_lanes_top_level_next_candidate_require_open_lane or dispatch_next_allows_cpu_worker_while_gb10_lane_is_active or dispatch_next_blocks_when_only_same_worker_lane_is_queued'` → `4 passed, 181 deselected`.
  - `uv run pytest -q` → `1012 passed, 4 warnings, 37 subtests passed`.
- **Live verification:** deployed `longhaul_readiness.py` to `/opt/enoch-control-plane`, restarted `enoch-control-plane.service`, `/healthz` returned `ok: true`, and `/control/api/v1/automation-readiness` reported `Long-haul mode: READY` with `queue_counts_consistent.ok=true` and `open_lane_has_queued_work=true` only because `has_next_candidate=true`.
- **Commit:** `d73bb34` (`fix(readiness): require next candidate for open lanes`).

## Pass 3 — Supabase worker callback run-ledger parity

- **Target:** callback/store idempotency and stale-run handling.
- **Invariant:** Supabase callback handling must preserve SQLite's run-ledger upsert semantics, so a valid callback cannot complete a queue item while silently failing to create a missing run row.
- **Bug found:** yes. SQLite used `INSERT INTO runs ... ON CONFLICT(run_id) DO UPDATE`, but Supabase callback handling only issued `UPDATE runs WHERE run_id = %s`.
- **Proof:** added `test_supabase_worker_callback_upserts_missing_run_row_like_sqlite`; it failed before the patch.
- **Patch:** changed Supabase `record_worker_callback()` to insert/upsert the run row on callback with the same conflict-update fields as the SQLite store.
- **Verification:**
  - `uv run pytest -q tests/test_supabase_store_helpers_more.py::test_supabase_worker_callback_upserts_missing_run_row_like_sqlite tests/test_supabase_store_helpers_more.py::test_supabase_worker_callback_append_failure_does_not_mutate_runtime_state` → `2 passed`.
  - `python3 -m py_compile enoch_control_plane/control_plane/supabase_store.py` → passed.
  - `git diff --check` → passed.
  - `uv run pytest -q tests/test_supabase_store_helpers_more.py tests/test_supabase_runtime_cutover.py tests/test_control_plane_store.py -k 'worker_callback or runtime_store_exposes_dashboard_and_dispatch_methods'` → `23 passed, 136 deselected`.
  - `uv run pytest -q` → `1013 passed, 4 warnings, 37 subtests passed`.
- **Live verification:** live enoch-core backend reports `control_plane_store_backend=supabase`; `/opt/enoch-control-plane/enoch_control_plane/control_plane/supabase_store.py` contains the callback run-row upsert patch and the service has been restarted since the patched file was present.
- **Commit:** `d0a043b` (`fix(supabase): upsert callback run rows`).

## Pass 4 — dispatch command panel lane-specific launch truth

- **Target:** dashboard command panel launch controls and worker-lane operator truth.
- **Invariant:** when Start next is disabled, the dashboard must explain lane-specific capacity: active lane, queued count per lane, and whether any queued item is dispatchable on an open lane.
- **Bug found:** yes. Live state had CPU lane active with two CPU-targeted queued items and GB10 idle with zero GB10-targeted queued items. Backend scheduling was correct, but the command panel gave a coarse disabled reason that made it appear GB10 idleness was ignored.
- **Proof:** extended `test_dashboard_html_links_to_multiview_apis` to require `laneCommandSummary`, explicit `No queued item is dispatchable on an open worker lane.`, and CPU/GB10 lane wording. The test failed before the patch.
- **Patch:** added `laneCommandSummary()` to the dashboard JS and rendered per-lane command status inside the command panel. Disabled Start next now says no queued item is dispatchable on an open worker lane, not that every lane is generically unavailable.
- **Verification:**
  - `uv run pytest -q tests/test_control_plane_router.py::ControlPlaneRouterTests::test_dashboard_html_links_to_multiview_apis` → `1 passed` after red failure.
  - `python3 -m py_compile enoch_control_plane/control_plane/router.py` → passed.
  - `git diff --check` → passed.
  - `uv run pytest -q tests/test_control_plane_router.py -k 'dashboard_html_links_to_multiview_apis or overview_and_lanes_top_level_next_candidate_require_open_lane or dashboard_status_reports_worker_lane_capacity'` → `3 passed, 167 deselected`.
  - `uv run pytest -q` → `1013 passed, 4 warnings, 37 subtests passed`.
- **Live verification:** deployed `router.py`, restarted `enoch-control-plane.service`, `/healthz` returned `ok: true`, and live `/control/dashboard` contains `laneCommandSummary` plus the explicit open-lane disabled reason.
- **Commit:** `2bf43ea` (`fix(dashboard): show lane-specific dispatch blockers`).

## Pass 5 - Lane dispatch disabled-state clarity

Symptom/risk: The command panel could look like it was ignoring an idle GB10 lane when the only queued work belonged to an active CPU lane.

Invariant: Start-next is enabled only when at least one queued item matches an idle worker lane; an idle lane with no queued candidate must be described explicitly instead of implying a global active-count block.

Deterministic guard:
- `tests/test_control_plane_router.py` asserts the dashboard bundle includes the explicit disabled-state copy: `No queued item matches an idle worker lane`.
- Existing lane-capacity/router tests assert CPU-active plus GB10-queued remains dispatch-safe and GB10 dispatchable.

Verification:
- `uv run pytest -q tests/test_control_plane_router.py` -> 170 passed.
- `uv run pytest -q` -> 1013 passed, 4 warnings, 37 subtests passed.
- Live deploy to `enoch-core.exe.xyz` restarted `enoch-control-plane.service`; `/healthz` returned ok.
- Live state after deploy: CPU lane active with 1 CPU queued item; GB10 lane idle with 0 queued GB10 items; `next_candidate=null` is therefore correct.
