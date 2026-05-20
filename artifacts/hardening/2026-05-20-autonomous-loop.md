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
