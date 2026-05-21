# CLCA: Dashboard V2 committed asset drift in CI

Status: corrective + preventive action for recurring Code CI failures on PRs #84–#88 (2026-05-21).

## Problem statement

Dashboard V2 PRs passed Vitest, typecheck, lint, and E2E, then failed at **Validate dashboard V2 committed assets** with hash drift (`missing assets/index-*.js`, `unexpected built file`, `hash drift: index.html`).

Agents and humans changed `dashboard/` source but did not rebuild and commit static bundles under `enoch_control_plane/control_plane/dashboard_v2/`.

## Root cause

1. **Split build model**: Source lives in `dashboard/`; production assets are **committed** beside the control plane and served at `/control/dashboard-v2`.
2. **CI intentionally does not commit builds** — it rebuilds into a temp dir and compares SHA-256 hashes (`scripts/validate_dashboard_v2_assets.py`).
3. **Agent/human workflow gap**: Verification commands in Cursor instructions listed `npm test`, `typecheck`, and `lint` but not the mandatory **build + commit assets** step documented in [`dashboard-v2-deploy.md`](dashboard-v2-deploy.md).
4. **Late failure signal**: Hash validation runs after the full dashboard test suite, so the error looks like a mysterious CI failure rather than a missing commit step.

## Corrective action (immediate)

For each open dashboard PR:

1. Run `./scripts/rebuild_dashboard_v2_assets.sh` (or `cd dashboard && npm ci && npm run build`).
2. Commit all changes under `enoch_control_plane/control_plane/dashboard_v2/`.
3. Push; confirm **Validate dashboard V2 committed assets** passes.

## Preventive action (systemic)

| Control | Location | Purpose |
|---------|----------|---------|
| Fast pairing check | `scripts/check_dashboard_v2_source_asset_pair.py` | Fail early when `dashboard/` build-affecting paths change without `dashboard_v2/` changes in the same PR |
| Rebuild helper | `scripts/rebuild_dashboard_v2_assets.sh` | One command for agents and humans |
| CI ordering | `.github/workflows/ci.yml` | Run pairing check **before** hash validation |
| Agent instructions | `docs/dashboard-v2-cursor-instructions.md` | Mandatory verification block includes asset rebuild |
| Deploy doc cross-link | `docs/dashboard-v2-deploy.md` | Points to this CLCA |

## Invariant

> If a PR changes dashboard source that affects the production bundle, it must also change committed `dashboard_v2/` assets in the same PR.

Test-only changes under `dashboard/**/*.test.*` do not require asset commits (pairing check excludes them). Hash validation remains the final deterministic guard.

## Verification commands

```bash
# After any dashboard source change:
./scripts/rebuild_dashboard_v2_assets.sh
git add enoch_control_plane/control_plane/dashboard_v2/

# Before push:
python3 scripts/check_dashboard_v2_source_asset_pair.py --base origin/main
python3 scripts/validate_dashboard_v2_assets.py --skip-npm-ci

cd dashboard
npm test -- --run
npm run typecheck
npm run lint
```

## Escalation

If pairing check and hash validation disagree (e.g. test-only source change that still shifts bundle hashes), trust **hash validation** and commit the rebuilt assets anyway.
