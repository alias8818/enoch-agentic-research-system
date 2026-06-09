# Dashboard V2 deploy and smoke

This document covers building, deploying, and verifying the React Dashboard V2 shell at `/control/dashboard-v2` — the **canonical** operator console. Legacy `/control/dashboard` **redirects** here (hash preserved) after Phase 2 cutover (merged 2026-05-21).

## Build before deploy

Dashboard V2 source lives in [`dashboard/`](../dashboard/). Built static assets are committed under [`enoch_control_plane/control_plane/dashboard_v2/`](../enoch_control_plane/control_plane/dashboard_v2/) and packaged into the Python wheel.

When you change dashboard source, rebuild locally and commit the output:

```bash
cd dashboard
npm ci
npm run build
```

CI runs `npm test`, `npm run typecheck`, and `npm run lint` only. It does **not** run `npm run build`, because the build mutates committed assets and would create CI-only drift. Phase 1 adds an asset-drift validator (`scripts/validate_dashboard_v2_assets.py`) to fail merges when source and committed bundles diverge.

**Agent/human checklist:** any PR that changes build-affecting dashboard source must also commit rebuilt assets. Use `./scripts/rebuild_dashboard_v2_assets.sh`. See [`dashboard-v2-asset-clca.md`](dashboard-v2-asset-clca.md) for the corrective/preventive workflow and CI pairing check.

## Safe rsync to the control VM

Do not copy local dev artifacts into production. The exclude list below matches [`scripts/install-control-plane.sh`](../scripts/install-control-plane.sh) (`sync_to_prefix`) plus deploy-only paths that must never land on the runtime tree.

Reference host: **`enoch-core.exe.xyz`** at `/opt/enoch-control-plane` (see [`current-runtime-snapshot.md`](current-runtime-snapshot.md)).

From your source checkout on a machine that can reach the control VM:

```bash
cd /path/to/enoch-agentic-research-system
rsync -a --delete \
  --exclude '.git' \
  --exclude '.venv' \
  --exclude '.pytest_cache' \
  --exclude '__pycache__' \
  --exclude 'node_modules' \
  --exclude '.hypothesis' \
  --exclude '.coverage' \
  --exclude '*.egg-info' \
  --exclude 'targeted_paper_intakes' \
  ./ enoch-core.exe.xyz:/opt/enoch-control-plane/
```

`install-control-plane.sh` uses the same core excludes (`.git`, `.venv`, `.pytest_cache`, `__pycache__`, `*.egg-info`) when syncing to `--prefix`; manual rsync adds `node_modules`, `.hypothesis`, `.coverage`, and `targeted_paper_intakes` because those are never installed by the script but often exist in developer trees.

## Post-deploy checklist

For routine deployments, prefer the rollout wrapper from the source checkout:

```bash
ENOCH_CONTROL_SMOKE=1 scripts/deploy-enoch-runtime.sh --profile control
```

The wrapper performs rsync, installs with
`uv pip install --python .venv/bin/python -e .`, restarts the service, waits for
health, validates the copied runtime, and runs the dashboard smoke when
`ENOCH_CONTROL_SMOKE=1` is set. This avoids assuming the restored runtime
`.venv` has `pip` installed.

Manual verification on **`enoch-core.exe.xyz`** after a wrapper deploy:

1. **Validate** runtime files match the source checkout you intended to deploy:

```bash
ssh enoch-core.exe.xyz 'cd /opt/enoch-release/enoch-agentic-research-system && \
  python3 scripts/validate_runtime_deploy.py \
    --source /opt/enoch-release/enoch-agentic-research-system \
    --runtime /opt/enoch-control-plane \
    --expected-commit origin/main \
    --summary-only'
```

Expect `"ok": true`. Hash drift or commit mismatch means the service is not proven to match `main`.

2. **Smoke** Dashboard V2 shell, assets, and bounded v1 APIs:

```bash
ssh enoch-core.exe.xyz 'ENOCH_CONTROL_TOKEN="$(jq -r .control_api_bearer_token /etc/enoch-control-plane/config.json)" \
  python3 /opt/enoch-control-plane/scripts/dashboard_v2_smoke.py \
    --base-url http://127.0.0.1:8787 \
    --check-legacy-dashboard-redirect'
```

3. **Browser spot-check / rendered QA**: for small deploys, open `/control/dashboard-v2#overview` with a safe bearer-injecting access path and confirm overview loads without a first-screen raw JSON block. For information-architecture, visual polish, raw/debug placement, or state-card changes, run the full rendered QA route set in [`dashboard-v2-rendered-qa.md`](dashboard-v2-rendered-qa.md).

## Post-deploy verification (detail)

### GET/API smoke (deploy health)

[`scripts/dashboard_v2_smoke.py`](../scripts/dashboard_v2_smoke.py) performs GET-only checks:

| Check | Auth |
|-------|------|
| `/healthz` | None |
| `/control/dashboard-v2` contains `id="enoch-dashboard-v2-root"` | None |
| All `/control/dashboard-v2/assets/...` references from `index.html` (JS required, CSS included) | None |
| `/control/api/v1/overview` | Bearer |
| `/control/api/v1/events?page_size=50&sort=recent` | Bearer |
| Event detail for first index row | Bearer |

Full check with API token (local or remote base URL):

```bash
python3 scripts/dashboard_v2_smoke.py \
  --base-url "http://127.0.0.1:8787" \
  --token "$ENOCH_CONTROL_TOKEN"
```

Shell/assets only (no token):

```bash
python3 scripts/dashboard_v2_smoke.py \
  --base-url "http://127.0.0.1:8787" \
  --allow-unauthenticated-shell-only
```

Without a token, the default mode **fails** unless `--allow-unauthenticated-shell-only` is passed.

### Rendering invariants (CI)

The smoke script cannot prove operator UX rules such as “raw JSON only in collapsed debug sections.” Those invariants are enforced by Vitest DOM tests in [`dashboard/`](../dashboard/) and run in CI on every PR.

### Runtime hash validation

Confirm the deployed tree matches your source checkout (paths as on `enoch-core.exe.xyz`):

```bash
python3 scripts/validate_runtime_deploy.py \
  --source /opt/enoch-release/enoch-agentic-research-system \
  --runtime /opt/enoch-control-plane \
  --expected-commit origin/main \
  --summary-only
```

Local pytest also covers shell/asset serving in `tests/test_control_plane_router.py` (`test_control_dashboard_v2_shell_and_assets_are_served_without_token`).

## Related docs

- Canonical runtime facts: [`current-runtime-snapshot.md`](current-runtime-snapshot.md)
- Operator runbook (readiness, callbacks): [`operator-runbook.md`](operator-runbook.md)
- Operator checklist: [`dashboard-v2-todo-2026-05-21.md`](dashboard-v2-todo-2026-05-21.md)
- Redesign contract: [`dashboard-redesign-plan.md`](dashboard-redesign-plan.md)
