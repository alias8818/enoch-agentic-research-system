# Changelog

Enoch uses semantic versioning for the control-plane package and runtime. The canonical package version is stored in both `VERSION` and `pyproject.toml`; release work should update both, update this changelog, run validation, and then tag the commit when publishing.

## [1.4.17] - 2026-05-28

### Changed

- Released the 1.4.17 control-plane metadata update.

## [1.4.16] - 2026-05-28

### Changed

- Released the 1.4.16 control-plane metadata update.

## [1.4.15] - 2026-05-28

### Changed

- Released the 1.4.15 control-plane metadata update.

## [1.4.14] - 2026-05-28

### Changed

- Released the 1.4.14 control-plane metadata update.

## [1.4.13] - 2026-05-27

### Changed

- Released the 1.4.13 control-plane metadata update.

## [1.4.12] - 2026-05-27

### Changed

- Released the 1.4.12 control-plane metadata update.

## [1.4.11] - 2026-05-27

### Changed

- Released the 1.4.11 control-plane metadata update.

## [1.4.10] - 2026-05-27

### Changed

- Released the 1.4.10 control-plane metadata update.

## [1.4.9] - 2026-05-27

### Changed

- Released the 1.4.9 control-plane metadata update.

## [1.4.8] - 2026-05-27

### Changed

- Released the 1.4.8 control-plane metadata update.

## [1.4.5] - 2026-05-26

### Changed

- Released the 1.4.5 control-plane metadata update.

## [1.4.4] - 2026-05-26

### Changed

- Released the 1.4.4 control-plane metadata update.

## [1.4.3] - 2026-05-26

### Changed

- Released the 1.4.3 control-plane metadata update.

## [1.4.2] - 2026-05-26

### Fixed

- Kept the queue pump bound to the configured local control-plane listener so token-bearing requests cannot be redirected by environment URL overrides.
- Released the 1.4.2 control-plane metadata update.

## [1.4.1] - 2026-05-26

### Changed

- Released the 1.4.1 control-plane metadata update.

## [1.4.0] - 2026-05-26

### Added

- Added the paper-readiness state contract, evidence maturity axis, hard paper gate, claim ledger evaluation, and research-yield read-model coverage.

### Fixed

- Suppressed expected shutdown cancellation noise from the control-plane lifespan task.
- Blocked negative or rejected project decisions from being overridden by v2 paper-readiness fields.
- Enforced the shared per-run dispatch cap during wait-time idle-lane refills.

## [1.3.1] - 2026-05-25

### Fixed

- Balanced lane queue feed targets so queued research work stays aligned with worker-lane capacity.

## [1.3.0] - 2026-05-25

### Changed

- Released the 1.3.0 control-plane metadata update.

## [1.0.1] - 2026-05-24

### Changed

- Agent readiness infrastructure, release workflow hardening, and CI dependency pin updates.

## [0.3.0] - 2026-05-15

### Added

- Added durable worker callback outbox and replay support so completed worker runs can survive transient control-plane or network callback failures.
- Added queue-alert auto-reconciliation for stale active lanes when a completed decision artifact is present, reducing false Pushover alerts and manual recovery work.
- Added Research Facility quality signals, post-prompt diagnostics, bounded-follow-up prioritization, and janitor candidate review support.
- Added escalation-ladder and dedupe-loss audit policy for deciding when negative results should branch instead of being discarded.

### Changed

- Prioritized bounded follow-up branches ahead of fresh idea generation when existing no-paper evidence indicates a plausible next investigation.
- Tightened paper-production gates so only explicit positive decisions can enter the write-needed lane.
- Made Research Facility generation and janitor review more conservative under backlog, quota, or active-lane backpressure.
- Normalized public corpus count handling and release validation around the current launch/corpus surfaces.

### Fixed

- Fixed stale active-lane and freshness timestamp handling in queue alerts.
- Fixed database connection lock release behavior in the control-plane store.
- Fixed janitor run-cycle integration and candidate review loop closure.
- Fixed corpus ledger sync to remain idempotent on no-op ticks.
- Fixed release validation drift for current launch assets and public corpus counts.

### Security

- Updated vulnerable dependency locks, including urllib3 and langsmith.
- Removed vulnerable DSPy transitive dependencies from the active lockfile while preserving DSPy/GEPA as a future research-policy item.
- Pinned GitHub Actions away from floating major tags and moved workflows off Node 20 actions where required.

### Operations

- Deployed the callback hardening path to the native Enoch/Codex control-plane runtime.
- Documented the callback-timeout CLCA path in the operator runbook.

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
