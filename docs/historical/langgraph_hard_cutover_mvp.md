# LangGraph Control Plane MVP

Date: 2026-04-28

This document records the first hard-cutover slice away from n8n control-plane ownership.

## Runtime placement

Recommended deployment split:

- VM / always-on server: FastAPI control plane, LangGraph controller graph, canonical SQLite DB, dashboard/API, Notion adapter later.
- GB10: OMX/Codex worker runtime, project files/artifacts, local inference/model serving, wake-gate/worker adapter.

The control plane defaults to `queue_paused=true` so creating the VM or starting the service cannot accidentally dispatch GB10 work.

## Implemented in this slice

- `omx_wake_gate.control_plane.models`: canonical records for projects, queue items, runs, papers, events, and pause/resume controls.
- `omx_wake_gate.control_plane.store`: SQLite canonical store with WAL, idempotent import events, pause/resume, dry-run dispatch selection, paper upsert, raw wake-gate snapshot normalization, export snapshots, Notion idea intake normalization, and Notion projection rows.
- `omx_wake_gate.control_plane.graphs`: MVP LangGraph dispatch graph with pause gate, single-lane gate, candidate selection, and dry-run eventing.
- `omx_wake_gate.control_plane.router`: `/control/*` API for health, state, pause, resume, legacy import, Notion intake, queue/paper reads, dry-run dispatch, deterministic paper draft-next, canonical export, and Notion projection reads.

## MVP endpoints

All endpoints use the existing wake-gate bearer token.

- `GET /control/dashboard` — canonical LangGraph dashboard HTML.
- `GET /control/health`
- `GET /control/state`
- `POST /control/pause`
- `POST /control/resume`
- `POST /control/import/legacy-snapshot` accepts normalized `queue_rows`/`paper_rows` or raw wake-gate `queue_snapshot`/`paper_snapshot` JSON.
- `POST /control/intake/notion-ideas` accepts Notion database rows, defaults to dry-run, and only commits queued canonical rows when `dry_run=false`.
- `POST /control/queue/mark-paused` records maintenance reconciliation for stale active rows after live process verification.
- `POST /control/worker/preflight` — non-mutating VM-to-GB10 readiness checks; no dispatch.
- `POST /control/dispatch-next` (`dry_run=true` only in this slice)
- `GET /control/queue`
- `GET /control/papers`
- `GET /control/export/snapshot`
- `GET /control/projections/notion/queue`
- `GET /control/projections/notion/papers`
- `GET /control/projections/notion/execution-updates`
- `POST /control/papers/draft-next`

## Safety gates

- Queue starts paused by default.
- Live dispatch returns `501`; only dry-run dispatch is implemented.
- Paper writes are constrained under the configured project root and selected project directory.
- Import is idempotent by `idempotency_key`; conflicting payload reuse returns/re-raises an idempotency conflict.

## Verification

Current verification:

```bash
cd omx_wake_gate
.venv/bin/pytest -q
```

Result on 2026-04-28 after guarded live-dispatch slice: `56 passed, 4 warnings, 12 subtests passed`.

## Guarded live dispatch

`POST /control/dispatch-next` can perform live dispatch only when all of these are true: the request sets `dry_run=false`, `live_dispatch_enabled=true` is configured, the control plane is resumed with maintenance mode off, no active lane exists, a queued candidate exists, and worker preflight passes. The live path prepares the project on the GB10 wake gate, dispatches exactly one run, then marks the canonical queue row `awaiting_wake`.

## Worker preflight

`POST /control/worker/preflight` verifies that the control plane is still paused, the GB10 wake gate is reachable, and—when a GB10 wake-gate bearer token is supplied—that worker telemetry is idle. It treats `SwapTotal=0` / `SwapFree=0` as healthy on GB10 when earlyoom is active. The endpoint never starts work and never mutates queue state.

Example minimal preflight:

```bash
curl -H "Authorization: Bearer $ENOCH_CONTROL_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"wake_gate_url":"http://worker.example:8787"}' \
  http://control-vm.example:8787/control/worker/preflight
```

For deeper telemetry checks, include a one-off `bearer_token` for the GB10 wake gate; otherwise authenticated dashboard checks are explicitly skipped and reported as such.

## GB10 memory posture

The GB10 worker is intentionally operated with swap disabled and `earlyoom` enabled. Do not treat `SwapTotal=0` or `SwapFree=0` as unhealthy by itself. UMA telemetry should use `MemAvailable` as the primary safe allocation signal; swap is only additive when deliberately configured. This avoids indefinite hangs under OOM pressure and lets earlyoom kill preferred memory-heavy processes.

## Notion sync runner

The sync runner is dependency-free and dry-run-first:

```bash
python -m omx_wake_gate.control_plane.notion_sync \
  --control-url http://control-vm.example:8787 \
  --control-token "$ENOCH_CONTROL_TOKEN" \
  --notion-token "$NOTION_TOKEN" \
  --notion-database-id "$NOTION_DATABASE_ID"
```

Default behavior reads Notion and posts `/control/intake/notion-ideas` with `dry_run=true`, then reads `/control/projections/notion/execution-updates`. It does not write to Notion and does not commit queue rows.

Explicit apply flags are separate:

- `--apply-intake`: commit eligible Notion ideas into canonical SQLite queue rows.
- `--apply-notion-updates`: PATCH Notion execution overlay properties from the projection endpoint.

The runner uses the current Notion API `Notion-Version: 2026-03-11`; when given an old parent database ID it first retrieves the database, resolves the first `data_sources[].id`, and then queries `POST /v1/data_sources/{data_source_id}/query`. You may bypass resolution with `NOTION_DATA_SOURCE_ID` / `--notion-data-source-id`.

## Next implementation slices

1. Import current GB10 wake-gate `queue_snapshot.json` and `paper_snapshot.json` into `/control/import/legacy-snapshot` on the VM.
2. Run Notion sync runner against live Notion in dry-run mode once credentials are available on the VM.
3. Add GB10 worker adapter for authenticated prepare/dispatch/status calls.
4. Implement live dispatch graph node behind the pause gate.
5. Implement wake callback reconciliation graph independent of n8n.
6. Rewire dashboard to prefer canonical `/control/state` projections.
