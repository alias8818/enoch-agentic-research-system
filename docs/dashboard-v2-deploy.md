# Dashboard V2 deploy and smoke

This document covers building, deploying, and verifying the React Dashboard V2 shell at `/control/dashboard-v2`.

## Build before deploy

Dashboard V2 source lives in [`dashboard/`](../dashboard/). Built static assets are committed under [`enoch_control_plane/control_plane/dashboard_v2/`](../enoch_control_plane/control_plane/dashboard_v2/) and packaged into the Python wheel.

When you change dashboard source, rebuild locally and commit the output:

```bash
cd dashboard
npm ci
npm run build
```

CI runs `npm test`, `npm run typecheck`, and `npm run lint` only. It does **not** run `npm run build`, because the build mutates committed assets and would create CI-only drift.

## Safe rsync to the control VM

Do not copy local dev artifacts into production. Exclude test caches, virtualenvs, and frontend `node_modules`:

```bash
rsync -a --delete \
  --exclude '.git' \
  --exclude '.venv' \
  --exclude 'node_modules' \
  --exclude '.hypothesis' \
  --exclude '.coverage' \
  --exclude '*.egg-info' \
  --exclude 'targeted_paper_intakes' \
  ./ user@enoch-core:/opt/enoch-control-plane/
```

After rsync, reinstall/restart using your normal control-plane deploy path (see [`deployment-guide.md`](deployment-guide.md)).

## Post-deploy verification

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

Full check with API token:

```bash
python3 scripts/dashboard_v2_smoke.py \
  --base-url "https://<control-host>" \
  --token "$ENOCH_CONTROL_TOKEN"
```

Shell/assets only (no token):

```bash
python3 scripts/dashboard_v2_smoke.py \
  --base-url "https://<control-host>" \
  --allow-unauthenticated-shell-only
```

Without a token, the default mode **fails** unless `--allow-unauthenticated-shell-only` is passed.

### Rendering invariants (CI)

The smoke script cannot prove operator UX rules such as “raw JSON only in collapsed debug sections.” Those invariants are enforced by Vitest DOM tests in [`dashboard/`](../dashboard/) and run in CI on every PR.

### Runtime hash validation

Confirm the deployed tree matches your source checkout:

```bash
python3 scripts/validate_runtime_deploy.py \
  --source . \
  --runtime /opt/enoch-control-plane
```

Local pytest also covers shell/asset serving in `tests/test_control_plane_router.py` (`test_control_dashboard_v2_shell_and_assets_are_served_without_token`).

## Related docs

- Operator checklist: [`dashboard-v2-todo-2026-05-21.md`](dashboard-v2-todo-2026-05-21.md)
- Redesign contract: [`dashboard-redesign-plan.md`](dashboard-redesign-plan.md)
