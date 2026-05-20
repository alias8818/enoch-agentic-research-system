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
