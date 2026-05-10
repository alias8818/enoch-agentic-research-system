# Local Postgres runtime runbook

Status: current topology note as of 2026-05-10. This file keeps earlier Supabase cutover evidence because it explains the migration path, but Supabase Cloud is no longer the active production database.

The current production control plane runs on `enoch-core` from `/opt/enoch-control-plane` with local Postgres database `enoch_control`. Older `control_plane_store_backend=supabase`, `supabase_database_url`, and `ENOCH_SUPABASE_DATABASE_URL` names remain in compatibility code, migration scripts, and historical evidence. Treat them as adapter/migration names unless live config proves otherwise. Notion is not an active runtime dependency; legacy Notion control-plane endpoints should return `410`, and Notion sync units should remain masked.

For day-to-day operation, prefer [`operator-runbook.md`](operator-runbook.md). This file is the cutover/migration evidence trail plus local-Postgres operational notes.

## Safety invariants

Before resuming any work on the current local-Postgres deployment:

- `/control/health` and `/enoch-core/health` point at the configured local control-plane store, not the old `.166` host.
- local Postgres is reachable on `enoch-core` and the `enoch_control` database has current queue/paper counts.
- `/control/state` reports the intended pause/maintenance posture for the operation being performed.
- `/control/api/intake/notion` returns `410`.
- `/control/projections/notion/queue` returns `410`.
- `enoch-notion-sync.timer` and `enoch-notion-sync.service` are masked and inactive.
- timer state matches policy: Research Facility, queue pump, paper drafting, and corpus import timers are checked separately and not inferred from one another.
- `write_needed=0`; raw completed/no-paper candidates must be explained by the decision gate.

## Readiness check

For the current deployment, use the long-haul readiness surface:

```bash
python scripts/check_longhaul_readiness.py --live \
  --config /etc/enoch-control-plane/config.json
```

For historical Supabase-resume validation from the repo checkout:

```bash
ENOCH_CONTROL_PLANE_TOKEN="$(ssh root@192.168.1.166 'cat /root/enoch-control-plane-token.txt')" \
uv run python scripts/validate_supabase_resume_readiness.py \
  --ssh-host root@192.168.1.166
```

Expected historical result: `ok: true` with `store_backend=supabase`, Notion `410`, and disabled/inactive timers. Do not use this as proof of current `enoch-core` local-Postgres readiness.

If running directly on the control-plane host, omit `--ssh-host` and verify timers with local `systemctl`:

```bash
cd /opt/enoch-control-plane
ENOCH_CONTROL_PLANE_TOKEN="$(cat /root/enoch-control-plane-token.txt)" \
.venv/bin/python scripts/supabase_controlled_resume_drill.py \
  --control-url http://127.0.0.1:8787

systemctl is-enabled enoch-notion-sync.timer enoch-notion-sync.service enoch-paper-draft-next.timer enoch-queue-alert-check.timer 2>/dev/null || true
systemctl is-active enoch-notion-sync.timer enoch-notion-sync.service enoch-paper-draft-next.timer enoch-queue-alert-check.timer 2>/dev/null || true
```

## Controlled one-dispatch drill

Historical Supabase-era drill: do not enable timers for the first resume. Use the fail-closed script:

```bash
ENOCH_CONTROL_PLANE_TOKEN="$(ssh root@192.168.1.166 'cat /root/enoch-control-plane-token.txt')" \
uv run python scripts/supabase_controlled_resume_drill.py \
  --ssh-host root@192.168.1.166 \
  --apply
```

The script refuses `--apply` if there is no queued candidate. If it does run, it unpauses, dispatches exactly one candidate, waits for an active lane, and re-pauses unless `--leave-unpaused` is explicitly provided.

## If no queued candidate exists

Do not unpause just to test empty dispatch. Add or import a control-plane idea first via `/control/intake/ideas`, then rerun readiness and the controlled drill.

## What not to do

- Do not re-enable Notion sync.
- Do not re-enable paper or queue timers before the one-dispatch drill passes.
- Do not use dashboard clicks as the first resume proof; use the scripted drill so the evidence is bounded and repeatable.

## Controlled drill evidence from 2026-05-07

The first post-cutover drill used one Supabase-native idea and one dispatch only:

- idea: `controlled-lifecycle-drill-20260507T084447Z`
- project: `controlled-lifecycle-drill-20260507t084447z`
- run: `controlled-lifecycle-drill-20260507t084447z-20260507T084644940726+0000`
- public corpus artifact: `enoch-paper-0497`, slug `controlled-supabase-lifecycle-drill`

The drill exposed four trust-relevant defects that are now part of the regression surface:

1. A queued item with no run yet produced noisy `last_run_state` warnings in `state_doctor`.
2. Dispatch-start still wrote the legacy internal surface `dispatch_accepted` instead of the operator-safe `awaiting_wake`.
3. `/control/papers/draft-next` ignored `dry_run` and could write a paper during a preview call.
4. Supabase corpus ledger sync used `extensions.digest(...)`, which is not callable by the runtime database user.

After fixes and corpus ledger sync, `state_doctor` reported `overall: OK`, `write_needed=0`, `finalize_needed=0`, `publish_ready=0`, and `importable=0` with the public corpus count at `497`.

## Post-drill unfreeze evidence from 2026-05-07

After the controlled drill and corpus import ledger reached a clean state, the control plane was resumed for wider batch execution while keeping paper drafting and Notion sync disabled:

- `/control/state`: `queue_paused=false`, `maintenance_mode=false`, `paused_by=completion-audit-unfreeze`
- `/etc/enoch-control-plane/config.json`: `queue_pump_enabled=true`, `queue_pump_paper_draft_enabled=false`, `live_dispatch_enabled=true`
- systemd: `enoch-queue-alert-check.timer` enabled/active; `enoch-paper-draft-next.timer` disabled/inactive; Notion sync units masked/inactive
- manual `enoch-queue-alert-check.service` smoke exited successfully and skipped dispatch because no queued candidate existed
- `state_doctor`: `overall: OK`, `write_needed=0`, `finalize_needed=0`, `publish_ready=0`, `importable=0`

This is an execution-only unfreeze. Paper drafting remains explicit/decision-gated and is not timer-driven.

## exe.dev local-Postgres migration evidence from 2026-05-09

The runtime control plane and database were moved off Supabase Cloud to `enoch-core.exe.xyz` to stop cloud egress growth from dashboard/status polling.

Current intended topology:

- `enoch-core.exe.xyz` / Tailscale `100.98.147.24`
  - Postgres 17 on `127.0.0.1:5432`, database `enoch_control`, private schema `enoch`.
  - `enoch-control-plane.service` serving FastAPI/Uvicorn on `0.0.0.0:8787`.
  - `enoch-queue-alert-check.timer` enabled; queue remains paused until explicitly resumed.
  - `enoch-postgres-backup.timer` creates local compressed custom-format dumps under `/var/backups/enoch-postgres` with 7-day retention.
- GB10 worker / Tailscale `100.92.44.26`
  - Worker execution only.
  - Project artifacts stay under `/home/jeremy/projects/enoch_testing_ground/projects` on the GB10 USB storage.
  - Worker callback URL now targets `http://100.98.147.24:8787/control/api/worker-callback`.
- Former `.166` control-plane host
  - `enoch-control-plane.service` and `enoch-queue-alert-check.timer` disabled/inactive after parity checks.

Cutover verification commands used:

```bash
# New control plane status over Tailscale.
curl -H "Authorization: Bearer $ENOCH_CONTROL_PLANE_TOKEN" \
  http://100.98.147.24:8787/control/api/status

# New overview parity.
curl -H "Authorization: Bearer $ENOCH_CONTROL_PLANE_TOKEN" \
  'http://100.98.147.24:8787/control/api/v1/overview?active_limit=5&event_limit=5'

# Worker preflight from new control plane to GB10.
curl -X POST -H "Authorization: Bearer $ENOCH_CONTROL_PLANE_TOKEN" \
  -H 'Content-Type: application/json' \
  http://100.98.147.24:8787/control/api/preflight \
  -d '{"wake_gate_url":"http://100.92.44.26:8787","bearer_token":"<worker-token>","require_paused":false,"strict":false}'
```

Observed parity at cutover:

- `counts`: `completed=608`, `all=617`, `paused=9`, `active=0`, `queued=0`, `blocked=0`, `papers=500`.
- `operator_counts`: `complete_no_paper=468`, `followup_investigation=6`, `published=376`, `needs_attention=0`, `ready_to_publish=0`, `write_paper=0`.
- `paper_pipeline`: `write_needed=0`, `finalize_needed=0`, `publish_ready=0`, `published_imported=376`, `raw_completed_no_paper_candidates=350`, `not_writable_by_decision_gate=350`.
- Queue remained paused: `dispatch_blockers=["queue paused"]`.
- Queue timer smoke on `enoch-core` skipped dispatch because the queue was paused and worker preflight passed.

Operational notes:

- Use `http://100.98.147.24:8787/control/dashboard` for direct Tailscale access.
- `https://enoch-core.exe.xyz/` is configured as a private exe.dev proxy to port `8787`; exe.dev authentication may be required before the application bearer token is evaluated.
- Do not point dashboard/API traffic back at Supabase Cloud unless intentionally rolling back.

## Reconnect and callback resilience

Current callback path:

```text
GB10 worker gate -> Tailscale -> enoch-core /control/api/worker-callback
```

The callback contract is idempotent by idempotency key. Callback-ready states without delivered idempotency keys are retried by the worker gate, and startup reconciliation can recover missing idle/finished observations. Dashboard states such as `callback_pending` and `stale_callback_ready` remain operator attention signals when retry/reconciliation does not clear the condition.

Still not covered: a worker process killed mid-run before a decision artifact exists. Inspect the GB10 project directory, logs, and process evidence before reconciling that queue row.

## Long-haul / 24x7 readiness check

Do not infer overnight readiness from scattered dashboard cards or active timers. The canonical readiness surface is:

```bash
python scripts/check_longhaul_readiness.py --live \
  --config /etc/enoch-control-plane/config.json
```

Expected ready output:

```text
PASS long-haul ready
```

Blocked output is intentionally loud and exact, for example:

```text
FAIL queue_paused=true
FAIL research timer inactive
FAIL publish_ready=2 but latest corpus tick is stale or missing
```

The dashboard mirrors the same endpoint as **Automation readiness** and must show one of:

```text
Long-haul mode: READY
Long-haul mode: BLOCKED — <first blocker>
```

Before telling the operator the system is ready for overnight or 24x7 unattended work, verify this readiness surface plus the underlying live state:

```bash
curl -H "Authorization: Bearer $ENOCH_CONTROL_PLANE_TOKEN" \
  http://127.0.0.1:8787/control/state

curl -H "Authorization: Bearer $ENOCH_CONTROL_PLANE_TOKEN" \
  http://127.0.0.1:8787/control/api/v1/automation-readiness

systemctl show enoch-research-autopilot.timer enoch-corpus-import-autopilot.timer \
  -p ActiveState -p LastTriggerUSec -p NextElapseUSecRealtime --no-pager
```

The readiness endpoint checks queue pause, maintenance mode, research/corpus autopilot timers, latest timer ticks, provider budget, blocked/attention counts, queue consistency, and the positive-gated paper-writing counters. If the Research Facility cycle runs while the broad queue is paused, the control plane emits the guardrail event `research.guardrail.queue_paused` with the message `research autopilot is active but broad queue is paused`.
