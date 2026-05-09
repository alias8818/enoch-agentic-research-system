# Changelog

Enoch uses semantic versioning for the control-plane package and runtime. The canonical package version is stored in both `VERSION` and `pyproject.toml`; release work should update both, update this changelog, run validation, and then tag the commit when publishing.

## [0.2.0] - 2026-05-09

### Changed

- Renamed the installable package from `omx-wake-gate` to `enoch-control-plane`.
- Renamed the Python module from `omx_wake_gate` to `enoch_control_plane`.
- Updated the FastAPI app entrypoint to `enoch_control_plane.app:app`.
- Updated runtime/operator-facing console naming to **Enoch Control Plane**.
- Made `.enoch/project_decision.json` the preferred worker decision artifact path while preserving `.omx/project_decision.json` as a legacy compatibility fallback for existing project evidence.
- Added `ControlPlaneEvent` as the canonical event model name while keeping `OmxEvent` as a deprecated compatibility alias for the legacy `/omx/event` hook.

### Added

- Added version/release discipline through `VERSION`, this changelog, and `scripts/validate_versioning.py`.

### Compatibility

- Existing configs that still set `omx_inbound_bearer_token` continue to load through the deprecated compatibility alias; new configs should use `control_api_bearer_token`.
- Existing `.omx` project artifacts remain readable for historical runs and imported evidence.

## [0.1.0] - 2026-05-04

### Added

- Initial Enoch control-plane release with queue state, worker preflight, pause/resume controls, dashboard read models, paper pipeline gates, Supabase-backed runtime ledgers, and public-release validation tooling.
