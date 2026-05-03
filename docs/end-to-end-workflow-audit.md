# End-to-end Enoch workflow audit

Date: 2026-05-03

Scope: Notion intake through queue dispatch, wake callback decisions, branch/discard/paper drafting, paper review/rewrite, and publication packaging. This audit uses the context snapshot `.omx/context/end-to-end-workflow-audit-20260503T081947Z.md` and preserves public-repo constraints: no private LAN defaults, secrets, or retired private workflow material.

## Executive summary

The released workflow has a coherent control-plane spine: Notion rows are normalized into queue candidates, dispatch is paused/preflight/single-lane guarded, wake callbacks map worker outcomes into durable queue states, positive research outcomes can draft papers only when evidence and decision gates pass, publication rewrites preserve provenance policy, and finalization packaging requires review approval plus readable artifacts.

Safe bounded fixes applied during this audit: `worker_callback.session_started` keeps the queue item active instead of falling through to the completed/default branch, unknown direct-store callbacks require manual review, and the paper-positive gate now uses exact decision/support tokens so negated words such as `not_positive`, `nonpositive`, `non-positive`, `unsupported`, and `not_supported` do not pass by substring. Regression tests lock these behaviors.

1. Notion intake idempotency replay now returns without rewriting queue rows after the event has already been recorded.
2. Worker callback idempotency replay/conflict is checked before queue/run mutation, so duplicate callbacks are no-op replays and conflicting callback payloads return `409` without overwriting the prior terminal state.
3. `session_started` callbacks are explicitly treated as active `running` rows with `await_callback`, unknown direct-store callbacks require manual review, and the positive paper gate rejects negated/substr-only tokens such as `not_positive`, `nonpositive`, `non-positive`, `unsupported`, and `not_supported`.

## State and sequence map

```mermaid
flowchart TD
  A[LLM scout / operator idea] --> B[Notion idea database]
  B --> C[notion_sync.py reads Notion rows]
  C --> D[/control/intake/notion-ideas]
  D -->|dry_run| D0[Candidate preview only]
  D -->|commit + idempotency event| E[(projects + queue_items)]
  E --> F[/control/projections/notion/execution-updates]
  F --> B
  E --> G{dispatch safe?}
  G -->|paused / active lane / alert| H[No dispatch; operator-visible blocker]
  G -->|safe| I[/control/dispatch-next]
  I --> J[worker preflight + live dispatch]
  J --> K[GB10 wake gate / Codex OMX run]
  K --> L[/control/api/worker-callback]
  L -->|session_started| LS[running + await_callback]
  L -->|question_pending| M[needs_review + answer_worker_question]
  L -->|gate_timeout/gate_error| N[blocked + inspect_worker_gate_failure]
  L -->|wake_ready/session_finished_ready| O[completed + draft_paper_or_select_next_project]
  L -->|unknown callback| UR[needs_review + inspect_unknown_worker_callback]
  O --> Q{paper draft candidate?}
  Q -->|manual review / duplicate / no evidence| P[select/dispatch next project]
  Q -->|positive decision + evidence| R[/control/papers/draft-next]
  R --> S[paper artifacts + paper.drafted event]
  S --> T[paper_review.backfill]
  T --> U[review queue]
  U --> V{review loop}
  V -->|claim / checklist / changes_requested| U
  V -->|rewrite draft| W[/control/api/paper-reviews/:id/rewrite-draft]
  W --> X[publication_draft + AI provenance policy]
  X --> U
  U -->|approve_finalization with final_human_approval pass| Y[approved_for_finalization]
  Y --> Z[/prepare-finalization-package]
  Z --> AA[finalized package manifest; no submission side effects]
```

## Key state machine and deterministic decision audit

### Queue safety and dispatch

- **Single active dispatch lane.** `ControlPlaneStore.next_dispatch_candidate()` refuses a candidate when the queue is paused or `active_items()` is non-empty, and sorts queued items by `dispatch_priority`, `selection_rank`, then `updated_at` (`omx_wake_gate/control_plane/store.py:1198-1207`). `/control/dispatch-next` repeats the active/candidate checks before live dispatch (`omx_wake_gate/control_plane/router.py:1506-1517`).
- **Dispatch start is durable.** Accepted live dispatch updates the queue row to `awaiting_wake`, sets `current_run_id`, clears stale error/result fields, creates/updates the run row, and appends a `controller.live_dispatch` event (`omx_wake_gate/control_plane/store.py:1427-1469`).
- **Wake callbacks are state-shaping and auditable.** `question_pending` goes to `needs_review`, gate failures go to `blocked`, ready callbacks go to `completed` with `draft_paper_or_select_next_project`, and unknown direct-store callback events go to manual review (`omx_wake_gate/control_plane/store.py:1471-1530`). The audit fix adds the missing `session_started -> running/await_callback` branch.
- **Paper draft eligibility is deterministic.** Candidates must be `completed`, paper-ready by final positive or wake-ready next-action, not manual-review, not already drafted by project or run, and not in excluded human-label benchmark categories (`omx_wake_gate/enoch_core/logic.py:155-204`).
- **Paper-positive gate is conservative.** For LangGraph wake-ready rows, `/control/papers/draft-next` requires local/synced evidence plus `paper_draft_decision_gate()`; the gate blocks negative, inconclusive, needs-review, caveat-only, and negated-positive decisions before accepting exact positive/proceed/viable tokens (`omx_wake_gate/control_plane/router.py:1602-1651`, `omx_wake_gate/enoch_core/logic.py:86-116`).
- **Publication review has an explicit transition table.** Review statuses and allowed transitions are centralized in `ALLOWED_STATUS_TRANSITIONS`; approval/finalization are reserved for dedicated endpoints (`omx_wake_gate/control_plane/store.py:110-123`, `omx_wake_gate/control_plane/store.py:925-980`).
- **Finalization is package-only.** Preparing finalization requires `approved_for_finalization`, readable artifacts, writes a local manifest, and records `no_submission_side_effects=true` (`omx_wake_gate/control_plane/store.py:1004-1056`).

Risk: `ACTIVE_QUEUE_STATUSES` in `omx_wake_gate/enoch_core/logic.py:9` is narrower than control-plane `ACTIVE_STATUSES` in `omx_wake_gate/control_plane/store.py:22`, which also includes `wake_received` and `reconciling`. This is low-to-medium risk because projection warnings can under-report transitional active states even if dispatch itself uses the control-plane store.

Suggested hardening: align projection active statuses with control-plane active statuses or add an explicit test that explains why the sets intentionally differ.

### Wake callback decisions

- `omx_wake_gate/control_plane/store.py:1473-1535` maps worker callback events to durable queue state:
  - `session_started` -> `running`, `await_callback`, active lane retained.
  - `question_pending` -> `needs_review`, `answer_worker_question`, manual review required.
  - `gate_timeout` / `gate_error` -> `blocked`, `inspect_worker_gate_failure`, manual review required.
  - `wake_ready` / `session_finished_ready` -> `completed`, `draft_paper_or_select_next_project`.
  - unknown direct-store callback events -> `needs_review`, `inspect_unknown_worker_callback`.
- The callback endpoint now converts idempotency conflicts to HTTP `409` in `omx_wake_gate/control_plane/router.py:884-904`.

Fix applied: callback idempotency is now checked before queue/run mutation, preventing conflicting callback replay from overwriting prior state. Existing `session_started` hardening keeps the queue row active instead of defaulting to a terminal completion.

### Branch/discard decisions

- Branch successor audit support exists in `omx_wake_gate/enoch_core/logic.py:139-152`: `branch_queued` rows require successor project ID evidence and a Notion successor URL.
- Discard/no-paper paths are represented by completed rows that do not pass the paper-draft candidate and decision gates.

Risk: branch successor validation is currently a projection/helper invariant, not a control-plane transition gate. Historical rows can therefore remain ambiguous unless import/reconciliation explicitly runs the validator.

Suggested hardening: expose branch successor validation in dashboard findings and add endpoint-level regression coverage for `branch_queued` imports.

## Notion intake, projection, and idempotency audit

- Notion page normalization and current API data-source querying are in `omx_wake_gate/control_plane/notion_sync.py:65-120`.
- Execution update projection shapes safe Notion properties in `omx_wake_gate/control_plane/notion_sync.py:149-225`; it requires explicit `page_id` and filters PATCH payloads to existing Notion page properties.
- Control-plane intake normalizes titles/status/page IDs/priorities in `omx_wake_gate/control_plane/store.py:87-128` and creates deterministic project IDs from page IDs in `omx_wake_gate/control_plane/store.py:1224-1258`.
- Intake commit records an idempotent event before table mutation in `omx_wake_gate/control_plane/store.py:1261-1273`.
- Execution update rows map queue/paper state back to Notion overlay fields in `omx_wake_gate/control_plane/store.py:1319-1355`.

Fix applied: repeated Notion intake with the same idempotency key and identical payload no longer rewrites `projects` / `queue_items` timestamps or metadata. Reusing the key with different payload still raises `IdempotencyConflict` via `append_event` at `omx_wake_gate/control_plane/store.py:485-498`.

Risk: Notion intake can update non-active queue rows on a new intake event. That is useful for priority refresh, but it also means Notion remains a planning surface that can reshape queued metadata. Runtime state protection is preserved for active statuses.

Suggested hardening: add an operator-visible diff summary to Notion intake responses for updated rows.

## Paper drafting, review, rewrite, duplicate, and positive-gate audit

### Draft candidate and positive gate

- Draft candidate logic in `omx_wake_gate/enoch_core/logic.py:161-204` requires completed status, positive legacy state or wake-ready + `draft_paper_or_select_next_project`, run evidence, no manual review, and no existing paper for either project or run.
- Positive decision parsing in `omx_wake_gate/enoch_core/logic.py:86-116` reads `.omx/project_decision.json` or `project_decision.json`, blocks negative/reject/inconclusive/caveat tokens, allows positive tokens, and allows `continue` only with supporting evidence.
- `omx_wake_gate/control_plane/router.py:1605-1659` additionally requires local/synced evidence for wake-driven rows, skips non-positive decisions, writes paper artifacts, backfills review items, and logs `paper.drafted`.

Risk: legacy `last_run_state == finalize_positive` intentionally bypasses modern decision artifact checks. That preserves backward compatibility, but it is a deterministic bypass path.

Suggested hardening: require decision artifacts for all newly-created rows while allowing legacy imported rows through an explicit `legacy_finalize_positive` reason.

### Review, rewrite, and finalization

- Review status and checklist definitions are explicit in `omx_wake_gate/control_plane/store.py:131-150`.
- Review mutations are idempotent/event-logged in `omx_wake_gate/control_plane/store.py:880-982`.
- Finalization packaging in `omx_wake_gate/control_plane/store.py:1004-1055` requires `approved_for_finalization`, readable artifacts for non-dry-run, includes checklist/artifact manifest, and records `no_submission_side_effects: true`.
- Publication rewrite in `omx_wake_gate/control_plane/router.py:1156-1223` uses a VM-local artifact root when needed, syncs evidence, preserves an AI-generated/no-human-credit publication policy, writes updated artifacts, and sets `publication_draft`.
- Batch rewrite in `omx_wake_gate/control_plane/router.py:1225-1259` skips finalized/rejected rows and can skip already rewritten rows by checking `paper_review.draft_rewritten` events.

Risk: the dashboard helper can auto-pass all checklist items from UI JavaScript, including final human approval. The server enforces that final approval must be `pass`, but it cannot prove the actor is human beyond `requested_by` metadata. For a public release, this is acceptable only if documented as an operator responsibility, not peer review.

Suggested hardening: require a distinct non-default reviewer identity and note for `final_human_approval` pass, and consider disabling dashboard auto-pass for that item.

## Findings ranked by risk

| Risk | Finding | Evidence | Recommendation |
| --- | --- | --- | --- |
| Queue/run state vocabulary | Queue, run, paper, and review states are centralized as enums. | `omx_wake_gate/control_plane/models.py:11`, `omx_wake_gate/control_plane/models.py:26`, `omx_wake_gate/control_plane/models.py:40`, `omx_wake_gate/control_plane/models.py:50` | Good: public state names are explicit. Hardening: add a transition table for queue statuses equivalent to the paper-review transition table so callback/import paths cannot introduce impossible queue edges. |
| Single active lane | Active rows are `dispatching`, `awaiting_wake`, and `running`; dispatch dry-run/live paths refuse a second active lane. | `omx_wake_gate/enoch_core/logic.py:9`, `omx_wake_gate/enoch_core/logic.py:127`, `omx_wake_gate/control_plane/store.py:1214`, `omx_wake_gate/control_plane/router.py:1507` | Good safety invariant. Hardening: include `wake_received`/`reconciling` consistently across all active-lane helpers or document why the core helper intentionally excludes them. |
| Dispatch candidate selection | Dispatch checks pause flags, active lane, and queued candidate before starting worker work. | `omx_wake_gate/control_plane/store.py:1210`, `omx_wake_gate/control_plane/router.py:1507` | Add tests that `manual_review_required=True`, blocked statuses, and active dry-runs cannot write dispatch events. |
| Wake callback branch | `question_pending` becomes `needs_review`; gate errors/timeouts become `blocked`; `wake_ready` and `session_finished_ready` complete the queue row with `draft_paper_or_select_next_project`; unknown direct-store callbacks require manual review. | `omx_wake_gate/control_plane/store.py:1471` | Deterministic for known callback event types. Hardening: move this branch table into an explicit transition map and assert every `GateCallback` literal is covered. |
| Branch successor evidence | Branch validation requires successor project id and Notion URL evidence. | `omx_wake_gate/enoch_core/logic.py:139` | Good invariant but appears as projection logic, not a control-plane transition gate. Add store/router tests that `branch_queued` rows without successor evidence remain non-dispatch and non-draft. |
| Paper-positive gate | Wake-ready completions must have local/synced evidence and a positive project decision artifact before drafting; negative/caveat/needs-review tokens block drafts. | `omx_wake_gate/enoch_core/logic.py:86`, `omx_wake_gate/enoch_core/logic.py:161`, `omx_wake_gate/control_plane/router.py:1603` | Strong gate. Hardening: expand tests for `continue + supported`, malformed decision JSON, conflicting `.omx/project_decision.json` vs `project_decision.json`, and caveat-only decisions. |
| Review loop | Review statuses have an explicit transition table; approval requires required checklist items and `final_human_approval=pass`; finalization requires readable artifacts. | `omx_wake_gate/control_plane/store.py:145`, `omx_wake_gate/control_plane/store.py:925`, `omx_wake_gate/control_plane/store.py:950`, `omx_wake_gate/control_plane/store.py:1004` | Good deterministic publication gate. Hardening: document finalization as package-only and add tests proving no external submission side effects. |

## Test coverage summary and missing checks

Existing coverage includes Notion normalization/sync, control-plane intake/projections, idempotent snapshot import, queue pump ordering, dispatch safety, wake-ready positive/negative paper drafting, paper artifact writing, review mutation validation, rewrite behavior, finalization package idempotency, and core positive/duplicate gates.

Recommended additional regressions:

- Endpoint-level branch successor validation for `branch_queued` rows.
- Active-status parity between control-plane and enoch-core projections.
- Decision artifact schema edge cases: malformed JSON, supporting-only fields, mixed-case blocked tokens, and positive + blocked token conflict.
- Draft-next duplicate prevention in an integration loop that calls `draft-next` twice after callback.
- Manual-review precedence for wake-ready + positive evidence at route level.
- Final human approval requiring a distinct reviewer/note and not dashboard auto-pass.

## Bounded fixes completed

- `omx_wake_gate/control_plane/store.py` — Notion intake replay no-op after existing idempotency event; worker callback replay/conflict check before queue/run mutation; `session_started` stays active as `running` / `await_callback`.
- `omx_wake_gate/control_plane/router.py` — worker callback idempotency conflicts return HTTP `409`.
- `tests/test_control_plane_store.py` — regression for Notion intake replay and conflict behavior.
- `tests/test_control_plane_router.py` — regression for callback replay/no-op, conflict, and preserved wake-ready state.

## Subagent findings integrated

- Test probe: mapped existing coverage and highlighted missing Notion idempotency, callback replay, branch, duplicate draft, manual-review, and dispatch-race checks.
- Publication/paper-flow probe: confirmed draft/review/rewrite/publication sequence, duplicate controls, positive-gate behavior, and documentation/diagram gaps.
- Review probe: integrated callback contract, atomicity, branch persistence, dispatch ordering, and orphan-callback risks into the findings and recommended tests.
