# n8n Migration Guide for Enoch Core

## Phase 0/1: Shadow Only

n8n may POST snapshots to `POST /enoch-core/snapshots/n8n-queue` and compare candidate proposals with current workflow decisions.

n8n must continue to own all side effects:

- Notion writes
- queue/data-table writes
- paper workflow invocation
- OMX dispatch/resume
- branch handoff calls

Recommended n8n pattern:

1. Read queue and paper data tables.
2. POST both row sets to `/enoch-core/snapshots/n8n-queue` with a stable idempotency key.
3. Optionally call `/enoch-core/candidates/paper-draft` or `/enoch-core/candidates/paper-polish`.
4. Log/compare the proposal.
5. Continue using existing n8n decision nodes for side effects until Phase 2 approval.

## Phase 2: Proposal Consumption

n8n may use candidate proposal endpoints to choose a paper draft/polish row, but n8n remains the executor. A workflow may call the proposal endpoint and then invoke its existing draft/polish workflow only after checking:

- `ok == true`
- `action == draft|polish`
- `candidate != null`
- `would_apply == false` in shadow/compare mode

## Phase 3: Invariant-by-Invariant Authority Migration

Only migrate one invariant at a time behind an explicit feature flag. Candidate invariants:

- single active GB10 lane
- branch queued requires concrete successor id and URL
- no-candidate paper paths return no-op, not 500
- duplicate callback idempotency

Each migration requires tests, snapshot parity, and rollback instructions.
