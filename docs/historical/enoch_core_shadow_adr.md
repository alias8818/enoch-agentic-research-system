# ADR: Enoch Core Shadow Protocol Runtime

## Status
Accepted for Phase 0/1 shadow mode.

## Context
The Enoch/OMX/n8n stack has accumulated durable control-plane logic in n8n workflows: queue lifecycle transitions, branch handoff checks, paper candidate selection, dashboard snapshots, and recovery heuristics. n8n remains valuable for schedules, credentials, Notion, and operator-facing automations, but recent failures showed that complex state-machine logic is hard to test and easy to split across workflow paths.

The existing `omx_wake_gate` service already owns the machine-truth seam: local process liveness, telemetry, wake readiness, project status, dashboard state, and paper artifact reads/writes. That makes it the lowest-risk place to add a small code-tested protocol/projection layer.

## Decision
Add `omx_wake_gate.omx_wake_gate.enoch_core` as a shadow-only protocol runtime. Phase 0/1 records local snapshots/events, rebuilds projections, and proposes candidates. It does not mutate n8n, Notion, OMX, or paper workflows.

## Authority Matrix

| Surface | Authority |
| --- | --- |
| Wake gate | GB10 process/liveness truth, quiet-window telemetry, wake callbacks |
| `enoch_core` Phase 0/1 | Local append-only protocol events, pure transition helpers, derived projections, candidate proposals |
| n8n | Schedules, credentials, Notion/data-table writes, paper workflow invocation, OMX dispatch side effects |
| Notion | Human-facing research/project/paper projection |

## Modes

- `off`: disabled by caller/policy.
- `shadow`: default; local append-only writes only, proposal responses only.
- `compare`: future mode for comparing n8n decisions with core proposals.
- `enforce`: future mode; not approved in Phase 0/1.

In Phase 0/1 every candidate response returns `would_apply: false`.

## Alternatives Considered

1. **Keep all logic in n8n.** Fastest operationally, but preserves workflow-path fragility and poor unit-testability.
2. **Move fully to LangGraph/CrewAI.** Premature; the current problem is ownership/protocol determinism, not agent-role orchestration.
3. **Create a separate service.** Cleaner boundary, but adds deployment/auth/network overhead. Embedding under the existing wake gate reuses the current trusted local sidecar.

## Consequences

- Adds a small SQLite store under the wake-gate state directory.
- Enables deterministic tests for idempotency, projections, candidates, and invariants.
- Avoids big-bang replacement of n8n.
- Phase 2/3 require separate approval before any side-effect ownership moves from n8n to `enoch_core`.
