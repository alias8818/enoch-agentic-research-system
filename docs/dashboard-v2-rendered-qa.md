# Dashboard V2 rendered QA runbook

Rendered QA is required for dashboard information-architecture/polish changes where static asset smoke or API checks cannot prove the visual hierarchy. The goal is to verify that `/control/dashboard-v2` remains a human-first operator console while raw identifiers, callback internals, packet paths, and JSON diagnostics remain available only as bounded evidence.

Runtime topology reference: [current runtime snapshot](current-runtime-snapshot.md). Static build/deploy reference: [dashboard-v2 deploy](dashboard-v2-deploy.md).

## Scope

Run this pass for changes that touch Overview, Projects, Queue, Runs, Papers, briefing cards, raw/debug disclosures, empty/loading/error/stale states, or visual regression baselines.

Minimum rendered route set:

- `#overview`
- `#projects`
- `#queue:queued`
- `#runs`
- `#papers`

## Access path

Prefer a real rendered path. Do **not** store the production bearer token in browser local storage. Use either direct Tailscale/control-host access with a safe bearer-injecting setup, or an SSH tunnel plus a local proxy that injects the bearer upstream while the browser only stores a dummy dashboard token.

Reference tunnel/proxy pattern used for `enoch-core.exe.xyz` QA:

```bash
ssh -N -L 127.0.0.1:18787:127.0.0.1:8787 enoch-core.exe.xyz
```

Then run a local bearer-injecting proxy on `127.0.0.1:18087` that forwards to `http://127.0.0.1:18787` and adds the real control token server-side. Browser URL examples:

```text
http://127.0.0.1:18087/control/dashboard-v2?v=<commit>#overview
http://127.0.0.1:18087/control/dashboard-v2?v=<commit>#projects
http://127.0.0.1:18087/control/dashboard-v2?v=<commit>#queue:queued
http://127.0.0.1:18087/control/dashboard-v2?v=<commit>#runs
http://127.0.0.1:18087/control/dashboard-v2?v=<commit>#papers
```

Use the cache-busting `?v=<commit>` query after static asset deploys.

## Preflight

Before browser QA, prove the shell/assets/API are healthy:

```bash
npm --prefix dashboard run build
python3 scripts/validate_dashboard_v2_assets.py
python3 scripts/check_dashboard_v2_source_asset_pair.py
ENOCH_CONTROL_TOKEN="$TOKEN" python3 scripts/dashboard_v2_smoke.py --base-url http://127.0.0.1:8787 --token "$TOKEN"
```

For live host checks, run the smoke on `enoch-core` or through the SSH tunnel. The smoke is GET-only/read-only.

## Browser pass checklist

For each route in the scope:

1. Navigate to the cache-busted rendered URL.
2. Verify the expected briefing layer appears above filters/tables.
3. Verify there is no visible clipping, overlap, unreadable text, or misleading risk color.
4. Check the browser console. The pass requires `0` JavaScript errors.
5. Confirm top-level normal operator regions do **not** expose high-risk raw/debug fields:
   - `worker_callback`
   - raw `run_id` values as card headings
   - raw `project_id` values as card headings when a human title exists
   - raw composite `paper_id` values as publication artifact headings
   - packet or artifact paths such as `/opt/enoch-control-plane/...`
   - raw JSON outside collapsed raw/detail disclosures
6. Confirm forensic access still exists in bounded evidence areas:
   - table rows
   - copy-ID controls
   - row/detail panels
   - `details.raw-details` or equivalent raw disclosures
7. Capture screenshots or notes for the final acceptance pass.

## Deterministic CI guards

Rendered QA is backed by CI-friendly checks that do not require production mutation:

```bash
npm --prefix dashboard run test:e2e
npm --prefix dashboard run test -- --run src/components/ResourcePages.test.tsx
```

The Playwright guard `resource briefing regions demote raw identifiers and internals to table/detail evidence` uses fixture data containing raw IDs, `worker_callback`, and a packet-like path. It asserts these values do not appear in Projects/Runs/Papers briefing card regions while copy controls/table evidence still expose them.

## Acceptance evidence format

Record the following in Linear before closing a dashboard QA/hardening issue:

- commit SHA and deployed asset refs
- local test/build/asset validation results
- Playwright result count
- smoke URL or host and read-only result
- rendered QA timestamp, access path, and routes checked
- console error count
- screenshots/notes when applicable
- explicit note that production queue/config/runtime state was not changed unless it actually was
