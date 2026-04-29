# Enoch Core Protocol Schema and Endpoints

All endpoints are authenticated with the existing wake-gate bearer token.

Base path: `/enoch-core`

## Common Candidate Response

```json
{
  "ok": true,
  "mode": "shadow",
  "action": "noop|draft|polish",
  "reason": "human-readable explanation",
  "candidate": null,
  "candidate_count": 0,
  "active_count": 0,
  "would_apply": false,
  "snapshot_captured_at": "2026-04-23T00:00:00Z",
  "projection_version": "enoch-core.candidate.v1"
}
```

Phase 0/1 candidate endpoints are proposal-only. `would_apply` is always false.

## `GET /enoch-core/health`

Returns service health, current mode, and SQLite path.

Example:

```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:8787/enoch-core/health
```

## `POST /enoch-core/snapshots/n8n-queue`

Records a local shadow snapshot of n8n queue rows and paper ledger rows.

Request:

```json
{
  "idempotency_key": "queue-snapshot-20260423T000000Z",
  "source": "n8n",
  "mode": "shadow",
  "captured_at": "2026-04-23T00:00:00Z",
  "queue_rows": [],
  "paper_rows": []
}
```

Rules:

- Same `idempotency_key` plus same payload is idempotent.
- Same `idempotency_key` plus different payload returns `409`.
- The endpoint writes only to local SQLite.
- It does not call Notion, mutate n8n, dispatch OMX, or trigger paper workflows.

Response:

```json
{
  "ok": true,
  "mode": "shadow",
  "inserted": true,
  "event_id": 1,
  "snapshot_id": 1,
  "queue_rows": 10,
  "paper_rows": 20,
  "would_apply": false,
  "message": "snapshot recorded locally only; no external side effects performed"
}
```

## `GET /enoch-core/projections/queue`

Returns a deterministic projection from the latest local snapshot.

Fields include queue status counts, run-state counts, active rows, and paper draft/polish candidate counts.

## `GET /enoch-core/candidates/paper-draft`

Proposes the next paper-draft candidate using the same core rules previously embedded in n8n:

- queue row has a project id,
- `status == completed`,
- `last_run_state == finalize_positive`,
- `manual_review_required` is false,
- no existing paper row for the project or run,
- obvious human-label/human-review rows are excluded.

No-op shape is returned if no candidate exists.

## `GET /enoch-core/candidates/paper-polish`

Proposes the next polish candidate:

- paper row status is `draft_review`,
- paper has project id, paper id, and markdown path,
- no corresponding `:publication_v1` paper exists.

No-op shape is returned if no candidate exists.

## SQLite Tables

- `schema_migrations(version, applied_at)`
- `events(id, idempotency_key UNIQUE, event_type, source, payload_json, payload_hash, created_at)`
- `snapshots(id, idempotency_key UNIQUE, snapshot_type, event_id, source, payload_json, created_at)`
- `decisions(id, decision_key UNIQUE, project_id, run_id, decision_type, payload_json, created_at)`
- `projection_cache(projection_key, projection_version, payload_json, rebuilt_at)`

SQLite uses WAL mode and a busy timeout for concurrent FastAPI access.
