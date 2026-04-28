# Enoch Core Failure-Mode Playbook

## Idempotency conflict (`409`)

Meaning: n8n reused an idempotency key with different payload content.

Action:
1. Do not retry with the same key.
2. Inspect n8n execution data for payload drift.
3. Generate a new idempotency key only if this is truly a new snapshot.

## Candidate endpoint returns `noop`

Meaning: no proposal exists from the latest local snapshot.

Action:
1. Verify snapshot freshness in `/enoch-core/projections/queue`.
2. Confirm n8n posted both `queue_rows` and `paper_rows`.
3. If n8n has a candidate but core does not, compare fields: `status`, `last_run_state`, `manual_review_required`, `project_id`, `current_run_id`, `paper_id`.

## Projection has multiple active rows warning

Meaning: latest snapshot has more than one row with `dispatching`, `awaiting_wake`, or `running`.

Action:
1. Treat this as a single-lane safety violation.
2. Compare wake gate dashboard, n8n queue row, and live process table before starting new GB10 work.
3. Reconcile the stale row first; do not dispatch competing GPU-heavy work.

## `branch_queued` invariant failure

Meaning: a row claims branch queued without concrete successor evidence.

Action:
1. Do not mark parent as safely closed.
2. Confirm successor `project_id` and Notion URL exist.
3. Re-run branch queue workflow or repair via authenticated Notion/data-table path.

## SQLite lock timeout

Meaning: concurrent requests exceeded SQLite busy timeout.

Action:
1. Retry with the same idempotency key.
2. Check whether an n8n workflow is flooding snapshot posts.
3. If recurring, reduce snapshot frequency or batch snapshots.

## Shadow vs n8n disagreement

Meaning: n8n selected a different candidate than `enoch_core`.

Action:
1. Keep n8n as side-effect authority in Phase 1.
2. Record the disagreement as evidence.
3. Compare field normalization and stale snapshot timing.
4. Add a regression test before changing either selector.
