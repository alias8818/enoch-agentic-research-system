# State reduction audit

Status: generated from `enoch_control_plane/control_plane/state_contract.py`.

This audit is the bridge from the broad compatibility contract to the small user/operator model. Every raw persisted state is classified as one of:

- `keep`: still a useful raw state.
- `alias`: allowed, but semantically duplicates another raw state.
- `legacy_internal`: allowed for history/compatibility, but not a current workflow state.
- `migrate_after_freeze`: safe candidate to rewrite or collapse after the current automation freeze.

Operator-facing surfaces should lead with the operator lane, not the raw value.

## Operator lanes

| Lane | Meaning |
| --- | --- |
| `running` | Work is dispatching, running, writing, finalizing, or waiting on a callback. |
| `ready_queue` | Work is eligible to dispatch when pause policy allows it. |
| `needs_operator` | A blocker, dispatch/gate failure, or worker question needs explicit operator action. |
| `complete_no_paper` | Worker delivery is complete, but the paper decision gate is not actionable-positive. |
| `useful_signal` | Worker delivery found a bounded useful signal, but it is not yet a paper-positive write candidate. |
| `compute_scale_blocked` | Worker delivery found a promising signal whose next validation exceeds local compute/time limits. |
| `followup_investigation` | Worker delivery is complete and evidence supports an adjacent bounded investigation, not a paper yet. |
| `write_paper` | A positive completed run has no paper yet and can be drafted by explicit bounded automation. |
| `automate_publication` | A paper artifact exists and should flow through automated rewrite/finalization/package steps. |
| `ready_to_publish` | A publication draft has required evidence paths, a finalized automation package, and no corpus-import ledger row. |
| `published` | The paper is represented by a public/corpus import ledger. |
| `paused` | Work is intentionally held by maintenance or policy. |
| `historical` | Terminal, provenance, debug, or imported evidence that is not current operator work. |

## Hard reduction rules

1. `write_paper` is only derived from positive project decisions with no existing paper.
2. `wake_ready` and `session_finished_ready` are delivery signals, not positive/negative outcomes.
3. Negative, unknown, malformed, missing, or ambiguous project decisions map to `complete_no_paper`, not paper work.
4. Publication readiness is `publication_draft` plus required evidence paths and finalized publication automation package.
5. Review/approval-like paper terms are compatibility/internal only; users see publication automation or artifact inspection.
6. Idea/project source status is provenance. Runtime execution state lives in `queue_items`.

## State-like surface inventory

The schema also contains state-like flags, hints, event names, type discriminators, and provenance fields. These are classified here so they do not get promoted into lifecycle states by accident.

| Surface | Class | Contract surface | Operator lane | Reason |
| --- | --- | --- | --- | --- |
| `control_events.entity_type` | `event_taxonomy` |  | `historical` | event target taxonomy for audit/logging |
| `control_events.event_type` | `event_taxonomy` |  | `historical` | append-only event taxonomy for audit/logging |
| `control_flags.maintenance_mode` | `system_flag` |  | `paused` | global maintenance policy flag |
| `control_flags.pause_reason` | `provenance_text` |  | `paused` | pause explanation text; queue_paused is the state-bearing flag |
| `control_flags.paused_by` | `provenance_text` |  | `paused` | pause actor audit field |
| `control_flags.queue_paused` | `system_flag` |  | `paused` | global dispatch pause switch, not a per-project lifecycle |
| `core_decisions.decision_key` | `type_discriminator` |  | `historical` | domain decision lookup key; not a lifecycle state |
| `core_decisions.decision_type` | `type_discriminator` |  | `historical` | core decision kind; domain-specific payload owns details |
| `core_events.event_type` | `event_taxonomy` |  | `historical` | Enoch core shadow/proposal event taxonomy |
| `core_projection_cache.projection_version` | `projection_metadata` |  | `historical` | cache schema/version metadata |
| `core_snapshots.snapshot_type` | `type_discriminator` |  | `historical` | snapshot/projection kind |
| `idea_events.event_type` | `event_taxonomy` |  | `historical` | Supabase-native idea workbench event taxonomy |
| `ideas.idea_status` | `canonical_lifecycle` | `ideas.idea_status` | `historical` | raw persisted lifecycle/detail state with explicit allowed values |
| `operator_observations.status` | `projection_metadata` |  | `historical` | health/observation status, not work lifecycle |
| `papers.paper_status` | `canonical_lifecycle` | `papers.paper_status` | `historical` | raw persisted lifecycle/detail state with explicit allowed values |
| `papers.paper_type` | `type_discriminator` |  | `historical` | artifact kind such as arxiv draft; paper lifecycle lives in paper_status |
| `project_decisions.artifact_path` | `provenance_text` |  | `historical` | decision artifact provenance path |
| `project_decisions.decision_gate_state` | `canonical_lifecycle` | `project_decisions.decision_gate_state` | `historical` | raw persisted lifecycle/detail state with explicit allowed values |
| `project_decisions.decision_summary` | `provenance_text` |  | `historical` | human-readable decision summary; actionability lives in decision_gate_state |
| `project_decisions.decision_type` | `type_discriminator` |  | `historical` | decision record kind; paper polarity lives in decision_gate_state |
| `projects.origin_idea_status` | `canonical_lifecycle` | `projects.origin_idea_status` | `historical` | raw persisted lifecycle/detail state with explicit allowed values |
| `publication_automation_items.automation_status` | `canonical_lifecycle` | `publication_automation_items.automation_status` | `historical` | raw persisted lifecycle/detail state with explicit allowed values |
| `publication_automation_items.decision_summary` | `provenance_text` |  | `historical` | automation decision summary; lifecycle lives in automation_status |
| `queue_items.auto_continue` | `system_flag` |  | `running` | automation policy flag; lifecycle still comes from queue status |
| `queue_items.blocked_reason` | `diagnostic_context` |  | `needs_operator` | blocker explanation text, not a finite state vocabulary |
| `queue_items.last_error` | `diagnostic_context` |  | `needs_operator` | error explanation text, not a finite state vocabulary |
| `queue_items.last_event_type` | `event_taxonomy` |  | `historical` | last callback/event taxonomy for evidence only |
| `queue_items.last_result_summary` | `provenance_text` |  | `historical` | worker result summary/provenance text |
| `queue_items.last_run_state` | `canonical_lifecycle` | `queue_items.last_run_state` | `historical` | raw persisted lifecycle/detail state with explicit allowed values |
| `queue_items.manual_review_required` | `attention_flag` |  | `needs_operator` | explicit operator-attention boolean that decorates queue status |
| `queue_items.next_action_hint` | `operator_hint` |  | `historical` | planner hint; paper actionability is still derived from decision gate and paper ledgers |
| `queue_items.status` | `canonical_lifecycle` | `queue_items.status` | `historical` | raw persisted lifecycle/detail state with explicit allowed values |
| `research_candidates.generation_mode` | `type_discriminator` |  | `historical` | Research Facility candidate generation strategy, not runtime lifecycle |
| `research_candidates.status` | `derived_operator` |  | `ready_queue` | candidate admission state before queue promotion; runtime action lives in queue_items |
| `research_lineage.relation_type` | `type_discriminator` |  | `historical` | Research Facility lineage relationship kind |
| `research_lineage.source_type` | `type_discriminator` |  | `historical` | Research Facility lineage endpoint kind |
| `research_lineage.target_type` | `type_discriminator` |  | `historical` | Research Facility lineage endpoint kind |
| `runs.current_activity` | `provenance_text` |  | `running` | free-form worker activity label |
| `runs.dispatch_mode` | `type_discriminator` |  | `historical` | dispatch strategy/provenance, not lifecycle |
| `runs.gate_state` | `canonical_lifecycle` | `runs.gate_state` | `historical` | raw persisted lifecycle/detail state with explicit allowed values |
| `runs.state` | `canonical_lifecycle` | `runs.state` | `historical` | raw persisted lifecycle/detail state with explicit allowed values |

## Surface-by-surface audit

### `ideas.idea_status`

| Raw value | Live rows | Operator lane | Disposition | Replacement | Reason |
| --- | ---: | --- | --- | --- | --- |
| `deprecated` |  | `historical` | `keep` |  | source/provenance status only |
| `discarded` |  | `historical` | `keep` |  | source/provenance status only |
| `exploring` |  | `ready_queue` | `keep` |  | included by default intake policy |
| `parked` |  | `historical` | `keep` |  | source/provenance status only |
| `testing` |  | `ready_queue` | `keep` |  | included by default intake policy |
| `unknown` |  | `historical` | `legacy_internal` |  | source/provenance status only |
| `validated` |  | `historical` | `keep` |  | source/provenance status only |

### `papers.paper_status`

| Raw value | Live rows | Operator lane | Disposition | Replacement | Reason |
| --- | ---: | --- | --- | --- | --- |
| `approved_for_corpus` |  | `published` | `legacy_internal` | `corpus import ledger` | old flattened public-import state |
| `archived` |  | `historical` | `keep` |  | terminal no-action paper state |
| `draft_generating` |  | `running` | `keep` |  | draft writer is active |
| `draft_review` |  | `automate_publication` | `migrate_after_freeze` | `publication_draft or archived when automation rejected` | legacy first-draft label; operator should see first draft or automation |
| `eligible` |  | `write_paper` | `legacy_internal` | `draft_generating` | paper eligibility now lives in paper_eligibility/write_needed |
| `finalized` |  | `ready_to_publish` | `legacy_internal` | `publication_draft + publication_automation.finalized` | old flattened paper readiness state |
| `human_review_required` |  | `needs_operator` | `migrate_after_freeze` | `blocked` | manual paper review is not a normal workflow |
| `publication_draft` |  | `automate_publication` | `keep` |  | publication readiness also requires required evidence paths and finalized automation package |
| `publication_generating` |  | `running` | `keep` |  | publication rewrite/finalization is active |

### `project_decisions.decision_gate_state`

| Raw value | Live rows | Operator lane | Disposition | Replacement | Reason |
| --- | ---: | --- | --- | --- | --- |
| `malformed` |  | `complete_no_paper` | `keep` |  | malformed decision is not writable |
| `missing` |  | `complete_no_paper` | `keep` |  | missing decision is not writable |
| `needs_review` |  | `complete_no_paper` | `migrate_after_freeze` | `unknown` | ambiguous decisions must not become paper work |
| `negative` |  | `complete_no_paper` | `keep` |  | not writable |
| `positive` |  | `write_paper` | `keep` |  | only state allowed to create actionable write_needed |
| `unknown` |  | `complete_no_paper` | `keep` |  | unknown decision is not writable |

### `projects.origin_idea_status`

| Raw value | Live rows | Operator lane | Disposition | Replacement | Reason |
| --- | ---: | --- | --- | --- | --- |
| `deprecated` |  | `historical` | `keep` |  | source/provenance status only |
| `discarded` |  | `historical` | `keep` |  | source/provenance status only |
| `exploring` |  | `ready_queue` | `keep` |  | included by default intake policy |
| `parked` |  | `historical` | `keep` |  | source/provenance status only |
| `testing` |  | `ready_queue` | `keep` |  | included by default intake policy |
| `unknown` |  | `historical` | `legacy_internal` |  | source/provenance status only |
| `validated` |  | `historical` | `keep` |  | source/provenance status only |

### `publication_automation_items.automation_status`

| Raw value | Live rows | Operator lane | Disposition | Replacement | Reason |
| --- | ---: | --- | --- | --- | --- |
| `approved_for_finalization` |  | `automate_publication` | `migrate_after_freeze` | `queued` | approval wording is internal compatibility only |
| `blocked` |  | `needs_operator` | `keep` |  | automation blocker |
| `changes_requested` |  | `needs_operator` | `migrate_after_freeze` | `blocked` | legacy paper-review correction state |
| `claimed` |  | `automate_publication` | `keep` |  | automation actor has claimed the item |
| `deferred` |  | `historical` | `keep` |  | intentionally skipped automation item |
| `finalized` |  | `ready_to_publish` | `keep` |  | finalization package and required evidence paths are ready |
| `in_review` |  | `automate_publication` | `migrate_after_freeze` | `claimed` | legacy paper-review running state |
| `queued` |  | `automate_publication` | `keep` |  | automation work is queued |
| `rejected` |  | `historical` | `keep` |  | terminal non-publication automation state |
| `triage_ready` |  | `automate_publication` | `migrate_after_freeze` | `queued` | legacy paper-review queue state |
| `unreviewed` |  | `automate_publication` | `migrate_after_freeze` | `queued` | legacy paper-review queue state |

### `queue_items.last_run_state`

| Raw value | Live rows | Operator lane | Disposition | Replacement | Reason |
| --- | ---: | --- | --- | --- | --- |
| `<blank>` |  | `historical` | `legacy_internal` |  | blank detail state |
| `awaiting_wake` |  | `running` | `keep` |  | worker callback is expected |
| `canceled` |  | `historical` | `keep` |  | terminal no-action state |
| `cancelled` |  | `historical` | `alias` | `canceled` | British spelling alias |
| `dispatch_accepted` |  | `running` | `legacy_internal` | `awaiting_wake or reconciled when superseded` | old dispatch bridge state |
| `dispatch_error` |  | `needs_operator` | `keep` |  | dispatch failed |
| `dispatching` |  | `running` | `keep` |  | dispatch request is in flight |
| `gate_error` |  | `needs_operator` | `keep` |  | wake gate failed |
| `gate_timeout` |  | `needs_operator` | `keep` |  | wake gate timed out |
| `malformed` |  | `complete_no_paper` | `keep` |  | malformed decision is not writable |
| `missing` |  | `complete_no_paper` | `keep` |  | missing decision is not writable |
| `needs_review` |  | `needs_operator` | `migrate_after_freeze` | `gate_error` | legacy run attention wording |
| `negative` |  | `complete_no_paper` | `keep` |  | not writable |
| `positive` |  | `write_paper` | `keep` |  | only state allowed to create actionable write_needed |
| `prepared` |  | `running` | `alias` | `dispatching` | pre-dispatch transient |
| `question_pending` |  | `needs_operator` | `keep` |  | worker needs an answer |
| `reconciled` |  | `historical` | `keep` |  | settled historical run |
| `running` |  | `running` | `keep` |  | worker is active |
| `session_finished_ready` |  | `historical` | `alias` | `wake_ready` | alternate delivery-complete callback |
| `unknown` |  | `historical` | `legacy_internal` |  | imported run rows without reliable lifecycle evidence |
| `waiting_external_evidence` |  | `needs_operator` | `keep` |  | external/worker evidence is missing |
| `wake_ready` |  | `historical` | `keep` |  | delivery signal only; not a paper-positive signal |

### `queue_items.status`

| Raw value | Live rows | Operator lane | Disposition | Replacement | Reason |
| --- | ---: | --- | --- | --- | --- |
| `awaiting_wake` |  | `running` | `keep` |  | worker callback is expected |
| `blocked` |  | `needs_operator` | `keep` |  | explicit blocker |
| `canceled` |  | `historical` | `keep` |  | terminal no-action state |
| `completed` |  | `complete_no_paper` | `keep` |  | paper action is derived from project decision and paper ledgers |
| `dispatch_error` |  | `needs_operator` | `keep` |  | dispatch failed and needs inspection |
| `dispatching` |  | `running` | `keep` |  | dispatch request is in flight |
| `needs_review` |  | `needs_operator` | `migrate_after_freeze` | `blocked` | legacy queue attention wording |
| `paused` |  | `paused` | `keep` |  | explicit maintenance/policy hold |
| `queued` |  | `ready_queue` | `keep` |  | primary dispatchable queue state |
| `reconciling` |  | `running` | `keep` |  | control plane is settling callback evidence |
| `running` |  | `running` | `keep` |  | worker is active |
| `wake_received` |  | `running` | `alias` | `reconciling` | callback has arrived but reconciliation is not done |

### `runs.gate_state`

| Raw value | Live rows | Operator lane | Disposition | Replacement | Reason |
| --- | ---: | --- | --- | --- | --- |
| `<blank>` |  | `historical` | `legacy_internal` |  | blank gate detail state |
| `awaiting_wake` |  | `running` | `keep` |  | worker callback is expected |
| `canceled` |  | `historical` | `keep` |  | terminal no-action state |
| `cancelled` |  | `historical` | `alias` | `canceled` | British spelling alias |
| `dispatch_accepted` |  | `running` | `legacy_internal` | `awaiting_wake or reconciled when superseded` | old dispatch bridge state |
| `dispatch_error` |  | `needs_operator` | `keep` |  | dispatch failed |
| `dispatching` |  | `running` | `keep` |  | dispatch request is in flight |
| `gate_error` |  | `needs_operator` | `keep` |  | wake gate failed |
| `gate_timeout` |  | `needs_operator` | `keep` |  | wake gate timed out |
| `needs_review` |  | `needs_operator` | `migrate_after_freeze` | `gate_error` | legacy run attention wording |
| `prepared` |  | `running` | `alias` | `dispatching` | pre-dispatch transient |
| `question_pending` |  | `needs_operator` | `keep` |  | worker needs an answer |
| `reconciled` |  | `historical` | `keep` |  | settled historical run |
| `running` |  | `running` | `keep` |  | worker is active |
| `session_finished_ready` |  | `historical` | `alias` | `wake_ready` | alternate delivery-complete callback |
| `unknown` |  | `historical` | `legacy_internal` |  | imported run rows without reliable lifecycle evidence |
| `waiting_external_evidence` |  | `needs_operator` | `keep` |  | external/worker evidence is missing |
| `wake_ready` |  | `historical` | `keep` |  | delivery signal only; not a paper-positive signal |

### `runs.state`

| Raw value | Live rows | Operator lane | Disposition | Replacement | Reason |
| --- | ---: | --- | --- | --- | --- |
| `awaiting_wake` |  | `running` | `keep` |  | worker callback is expected |
| `canceled` |  | `historical` | `keep` |  | terminal no-action state |
| `cancelled` |  | `historical` | `alias` | `canceled` | British spelling alias |
| `dispatch_accepted` |  | `running` | `legacy_internal` | `awaiting_wake or reconciled when superseded` | old dispatch bridge state |
| `dispatch_error` |  | `needs_operator` | `keep` |  | dispatch failed |
| `dispatching` |  | `running` | `keep` |  | dispatch request is in flight |
| `gate_error` |  | `needs_operator` | `keep` |  | wake gate failed |
| `gate_timeout` |  | `needs_operator` | `keep` |  | wake gate timed out |
| `needs_review` |  | `needs_operator` | `migrate_after_freeze` | `gate_error` | legacy run attention wording |
| `prepared` |  | `running` | `alias` | `dispatching` | pre-dispatch transient |
| `question_pending` |  | `needs_operator` | `keep` |  | worker needs an answer |
| `reconciled` |  | `historical` | `keep` |  | settled historical run |
| `running` |  | `running` | `keep` |  | worker is active |
| `session_finished_ready` |  | `historical` | `alias` | `wake_ready` | alternate delivery-complete callback |
| `unknown` |  | `historical` | `legacy_internal` |  | imported run rows without reliable lifecycle evidence |
| `waiting_external_evidence` |  | `needs_operator` | `keep` |  | external/worker evidence is missing |
| `wake_ready` |  | `historical` | `keep` |  | delivery signal only; not a paper-positive signal |
