# Supabase runtime cutover runbook

Status: active as of 2026-05-06.

The control plane is expected to run with `control_plane_store_backend=supabase`, and `/enoch-core/health` should report `store_backend: supabase` because its shadow/proposal snapshots now follow the Supabase control-plane backend. Notion is not an active runtime dependency; legacy Notion control-plane endpoints should return `410`, and Notion sync units should remain masked.

## Safety invariants

Before resuming any work:

- `/control/health` reports `store_backend: supabase`.
- `/enoch-core/health` reports `store_backend: supabase` and `db_path: supabase`; `enoch_core.sqlite3` must not be the live shadow/proposal ledger.
- `/control/state` reports `queue_paused=true` and `maintenance_mode=true` until the controlled drill starts.
- `/control/api/intake/notion` returns `410`.
- `/control/projections/notion/queue` returns `410`.
- `enoch-notion-sync.timer` and `enoch-notion-sync.service` are masked and inactive.
- `enoch-paper-draft-next.timer` and `enoch-queue-alert-check.timer` are disabled and inactive.
- `write_needed=0`; raw completed/no-paper candidates must be explained by the decision gate.

## Readiness check

From the repo checkout:

```bash
ENOCH_CONTROL_PLANE_TOKEN="$(ssh root@192.168.1.166 'cat /root/enoch-control-plane-token.txt')" \
uv run python scripts/validate_supabase_resume_readiness.py \
  --ssh-host root@192.168.1.166
```

Expected result: `ok: true` with `store_backend=supabase`, Notion `410`, and disabled/inactive timers.

If running directly on the control-plane host, omit `--ssh-host` and verify timers with local `systemctl`:

```bash
cd /opt/omx-wake-gate
ENOCH_CONTROL_PLANE_TOKEN="$(cat /root/enoch-control-plane-token.txt)" \
.venv/bin/python scripts/supabase_controlled_resume_drill.py \
  --control-url http://127.0.0.1:8787

systemctl is-enabled enoch-notion-sync.timer enoch-notion-sync.service enoch-paper-draft-next.timer enoch-queue-alert-check.timer 2>/dev/null || true
systemctl is-active enoch-notion-sync.timer enoch-notion-sync.service enoch-paper-draft-next.timer enoch-queue-alert-check.timer 2>/dev/null || true
```

## Controlled one-dispatch drill

Do not enable timers for the first resume. Use the fail-closed script:

```bash
ENOCH_CONTROL_PLANE_TOKEN="$(ssh root@192.168.1.166 'cat /root/enoch-control-plane-token.txt')" \
uv run python scripts/supabase_controlled_resume_drill.py \
  --ssh-host root@192.168.1.166 \
  --apply
```

The script refuses `--apply` if there is no queued candidate. If it does run, it unpauses, dispatches exactly one candidate, waits for an active lane, and re-pauses unless `--leave-unpaused` is explicitly provided.

## If no queued candidate exists

Do not unpause just to test empty dispatch. Add or import a Supabase-native idea first via `/control/intake/ideas`, then rerun readiness and the controlled drill.

## What not to do

- Do not re-enable Notion sync.
- Do not re-enable paper or queue timers before the one-dispatch drill passes.
- Do not use dashboard clicks as the first resume proof; use the scripted drill so the evidence is bounded and repeatable.
