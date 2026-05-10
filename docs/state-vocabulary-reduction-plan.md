# State vocabulary reduction plan

Status: migration-safe target vocabulary for control-plane runtime state. This plan was written during the Supabase-backed phase; current production storage is local Postgres on `enoch-core`. For current runtime topology, see [`current-runtime-snapshot.md`](current-runtime-snapshot.md).

This plan reduces operator and agent reasoning to small domain vocabularies while keeping raw compatibility values constrained and auditable. It is a planning and validation artifact: live data changes still go through `scripts/normalize_state_surfaces.py` dry-run/apply plus `scripts/state_doctor.py` evidence.

## Cleanup action contract

| Action | Meaning | Data migration rule |
| --- | --- | --- |
| `keep` | Canonical value may continue to be minted. | No cleanup migration. |
| `alias` | Compatibility spelling or callback synonym. | Normalize when present and state doctor is otherwise clean. |
| `migrate` | Old workflow value with a safe replacement after freeze. | Migrate only through reviewed normalization SQL. |
| `retire` | Historical/import/provenance value accepted for audit only. | Do not mint; do not bulk rewrite without a provenance-preserving migration plan. |

## Final small state sets

### Ideas

| Final state | Meaning |
| --- | --- |
| `ready` | Candidate intake item that can become project work. |
| `held` | Intentionally parked idea; no worker action. |
| `discarded` | Rejected/deprecated idea; no worker action. |
| `promoted` | Idea already became project/publication provenance. |
| `historical` | Imported or incomplete source provenance only. |

### Projects

| Final state | Meaning |
| --- | --- |
| `ready` | Queued project work that can dispatch when policy allows. |
| `running` | Project work is actively dispatching/running/reconciling. |
| `needs_attention` | Project is blocked, failed, or waiting on an operator/irreducible input. |
| `paused` | Project is held by maintenance or policy. |
| `done_no_paper` | Completed or non-positive project; no paper action. |
| `paper_positive` | Decision gate says the completed work is paper-actionable. |
| `canceled` | Terminal canceled project work. |
| `historical` | Source/provenance-only project field; not runtime state. |

### Runs

| Final state | Meaning |
| --- | --- |
| `running` | Worker dispatch/callback is in progress. |
| `needs_attention` | Run failed, timed out, asked a question, or needs external evidence. |
| `delivered` | Worker callback delivered; decision/paper lanes decide next action. |
| `settled` | Run evidence is reconciled and historical. |
| `canceled` | Terminal canceled run. |
| `decision_positive` | Detail-only positive decision hint; not a run lifecycle. |
| `decision_no_paper` | Detail-only non-positive/missing/malformed decision hint. |
| `historical` | Imported/blank/legacy detail evidence; not active work. |

### Papers

| Final state | Meaning |
| --- | --- |
| `needed` | Paper-positive work has no draft yet. |
| `drafting` | Draft generation is running. |
| `finalizing` | Automated rewrite/finalization/package work is pending or running. |
| `ready_to_publish` | Finalization package exists and corpus-import ledger is missing. |
| `published` | Corpus import ledger represents the publication. |
| `blocked` | Publication automation has a real blocker. |
| `archived` | Terminal no-publication/no-action paper artifact. |

## Migration-safe raw-state mapping

| Domain | Surface | Raw value | Final state | Cleanup action | Migration target | Safe auto-migrate? | Operator lane | Reason |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Projects | `queue_items.status` | `awaiting_wake` | `running` | `keep` | — | n/a | `running` | worker callback is expected |
| Projects | `queue_items.status` | `blocked` | `needs_attention` | `keep` | — | n/a | `needs_operator` | explicit blocker |
| Projects | `queue_items.status` | `canceled` | `canceled` | `keep` | — | n/a | `historical` | terminal no-action state |
| Projects | `queue_items.status` | `completed` | `done_no_paper` | `keep` | — | n/a | `complete_no_paper` | paper action is derived from project decision and paper ledgers |
| Projects | `queue_items.status` | `dispatch_error` | `needs_attention` | `keep` | — | n/a | `needs_operator` | dispatch failed and needs inspection |
| Projects | `queue_items.status` | `dispatching` | `running` | `keep` | — | n/a | `running` | dispatch request is in flight |
| Projects | `queue_items.status` | `needs_review` | `needs_attention` | `migrate` | blocked | yes | `needs_operator` | legacy queue attention wording |
| Projects | `queue_items.status` | `paused` | `paused` | `keep` | — | n/a | `paused` | explicit maintenance/policy hold |
| Projects | `queue_items.status` | `queued` | `ready` | `keep` | — | n/a | `ready_queue` | primary dispatchable queue state |
| Projects | `queue_items.status` | `reconciling` | `running` | `keep` | — | n/a | `running` | control plane is settling callback evidence |
| Projects | `queue_items.status` | `running` | `running` | `keep` | — | n/a | `running` | worker is active |
| Projects | `queue_items.status` | `wake_received` | `running` | `alias` | reconciling | yes | `running` | callback has arrived but reconciliation is not done |
| Runs | `runs.state` | `awaiting_wake` | `running` | `keep` | — | n/a | `running` | worker callback is expected |
| Runs | `runs.state` | `canceled` | `canceled` | `keep` | — | n/a | `historical` | terminal no-action state |
| Runs | `runs.state` | `cancelled` | `canceled` | `alias` | canceled | yes | `historical` | British spelling alias |
| Runs | `runs.state` | `dispatch_accepted` | `running` | `retire` | awaiting_wake or reconciled when superseded | no | `running` | old dispatch bridge state |
| Runs | `runs.state` | `dispatch_error` | `needs_attention` | `keep` | — | n/a | `needs_operator` | dispatch failed |
| Runs | `runs.state` | `dispatching` | `running` | `keep` | — | n/a | `running` | dispatch request is in flight |
| Runs | `runs.state` | `gate_error` | `needs_attention` | `keep` | — | n/a | `needs_operator` | worker gate failed |
| Runs | `runs.state` | `gate_timeout` | `needs_attention` | `keep` | — | n/a | `needs_operator` | worker gate timed out |
| Runs | `runs.state` | `needs_review` | `needs_attention` | `migrate` | gate_error | yes | `needs_operator` | legacy run attention wording |
| Runs | `runs.state` | `prepared` | `running` | `alias` | dispatching | yes | `running` | pre-dispatch transient |
| Runs | `runs.state` | `question_pending` | `needs_attention` | `keep` | — | n/a | `needs_operator` | worker needs an answer |
| Runs | `runs.state` | `reconciled` | `settled` | `keep` | — | n/a | `historical` | settled historical run |
| Runs | `runs.state` | `running` | `running` | `keep` | — | n/a | `running` | worker is active |
| Runs | `runs.state` | `session_finished_ready` | `delivered` | `alias` | wake_ready | yes | `historical` | alternate delivery-complete callback |
| Runs | `runs.state` | `unknown` | `historical` | `retire` | — | no | `historical` | imported run rows without reliable lifecycle evidence |
| Runs | `runs.state` | `waiting_external_evidence` | `needs_attention` | `keep` | — | n/a | `needs_operator` | external/worker evidence is missing |
| Runs | `runs.state` | `wake_ready` | `delivered` | `keep` | — | n/a | `historical` | delivery signal only; not a paper-positive signal |
| Runs | `queue_items.last_run_state` | `<blank>` | `historical` | `retire` | — | no | `historical` | blank detail state |
| Runs | `queue_items.last_run_state` | `awaiting_wake` | `running` | `keep` | — | n/a | `running` | worker callback is expected |
| Runs | `queue_items.last_run_state` | `canceled` | `canceled` | `keep` | — | n/a | `historical` | terminal no-action state |
| Runs | `queue_items.last_run_state` | `cancelled` | `canceled` | `alias` | canceled | yes | `historical` | British spelling alias |
| Runs | `queue_items.last_run_state` | `dispatch_accepted` | `running` | `retire` | awaiting_wake or reconciled when superseded | no | `running` | old dispatch bridge state |
| Runs | `queue_items.last_run_state` | `dispatch_error` | `needs_attention` | `keep` | — | n/a | `needs_operator` | dispatch failed |
| Runs | `queue_items.last_run_state` | `dispatching` | `running` | `keep` | — | n/a | `running` | dispatch request is in flight |
| Runs | `queue_items.last_run_state` | `gate_error` | `needs_attention` | `keep` | — | n/a | `needs_operator` | worker gate failed |
| Runs | `queue_items.last_run_state` | `gate_timeout` | `needs_attention` | `keep` | — | n/a | `needs_operator` | worker gate timed out |
| Runs | `queue_items.last_run_state` | `malformed` | `decision_no_paper` | `keep` | — | n/a | `complete_no_paper` | malformed decision is not writable |
| Runs | `queue_items.last_run_state` | `missing` | `decision_no_paper` | `keep` | — | n/a | `complete_no_paper` | missing decision is not writable |
| Runs | `queue_items.last_run_state` | `needs_review` | `needs_attention` | `migrate` | gate_error | yes | `needs_operator` | legacy run attention wording |
| Runs | `queue_items.last_run_state` | `negative` | `decision_no_paper` | `keep` | — | n/a | `complete_no_paper` | not writable |
| Runs | `queue_items.last_run_state` | `positive` | `decision_positive` | `keep` | — | n/a | `write_paper` | only state allowed to create actionable write_needed |
| Runs | `queue_items.last_run_state` | `prepared` | `running` | `alias` | dispatching | yes | `running` | pre-dispatch transient |
| Runs | `queue_items.last_run_state` | `question_pending` | `needs_attention` | `keep` | — | n/a | `needs_operator` | worker needs an answer |
| Runs | `queue_items.last_run_state` | `reconciled` | `settled` | `keep` | — | n/a | `historical` | settled historical run |
| Runs | `queue_items.last_run_state` | `running` | `running` | `keep` | — | n/a | `running` | worker is active |
| Runs | `queue_items.last_run_state` | `session_finished_ready` | `delivered` | `alias` | wake_ready | yes | `historical` | alternate delivery-complete callback |
| Runs | `queue_items.last_run_state` | `unknown` | `historical` | `retire` | — | no | `historical` | imported run rows without reliable lifecycle evidence |
| Runs | `queue_items.last_run_state` | `waiting_external_evidence` | `needs_attention` | `keep` | — | n/a | `needs_operator` | external/worker evidence is missing |
| Runs | `queue_items.last_run_state` | `wake_ready` | `delivered` | `keep` | — | n/a | `historical` | delivery signal only; not a paper-positive signal |
| Runs | `runs.gate_state` | `<blank>` | `historical` | `retire` | — | no | `historical` | blank gate detail state |
| Runs | `runs.gate_state` | `awaiting_wake` | `running` | `keep` | — | n/a | `running` | worker callback is expected |
| Runs | `runs.gate_state` | `canceled` | `canceled` | `keep` | — | n/a | `historical` | terminal no-action state |
| Runs | `runs.gate_state` | `cancelled` | `canceled` | `alias` | canceled | yes | `historical` | British spelling alias |
| Runs | `runs.gate_state` | `dispatch_accepted` | `running` | `retire` | awaiting_wake or reconciled when superseded | no | `running` | old dispatch bridge state |
| Runs | `runs.gate_state` | `dispatch_error` | `needs_attention` | `keep` | — | n/a | `needs_operator` | dispatch failed |
| Runs | `runs.gate_state` | `dispatching` | `running` | `keep` | — | n/a | `running` | dispatch request is in flight |
| Runs | `runs.gate_state` | `gate_error` | `needs_attention` | `keep` | — | n/a | `needs_operator` | worker gate failed |
| Runs | `runs.gate_state` | `gate_timeout` | `needs_attention` | `keep` | — | n/a | `needs_operator` | worker gate timed out |
| Runs | `runs.gate_state` | `needs_review` | `needs_attention` | `migrate` | gate_error | yes | `needs_operator` | legacy run attention wording |
| Runs | `runs.gate_state` | `prepared` | `running` | `alias` | dispatching | yes | `running` | pre-dispatch transient |
| Runs | `runs.gate_state` | `question_pending` | `needs_attention` | `keep` | — | n/a | `needs_operator` | worker needs an answer |
| Runs | `runs.gate_state` | `reconciled` | `settled` | `keep` | — | n/a | `historical` | settled historical run |
| Runs | `runs.gate_state` | `running` | `running` | `keep` | — | n/a | `running` | worker is active |
| Runs | `runs.gate_state` | `session_finished_ready` | `delivered` | `alias` | wake_ready | yes | `historical` | alternate delivery-complete callback |
| Runs | `runs.gate_state` | `unknown` | `historical` | `retire` | — | no | `historical` | imported run rows without reliable lifecycle evidence |
| Runs | `runs.gate_state` | `waiting_external_evidence` | `needs_attention` | `keep` | — | n/a | `needs_operator` | external/worker evidence is missing |
| Runs | `runs.gate_state` | `wake_ready` | `delivered` | `keep` | — | n/a | `historical` | delivery signal only; not a paper-positive signal |
| Papers | `papers.paper_status` | `approved_for_corpus` | `published` | `retire` | corpus import ledger | no | `published` | old flattened public-import state |
| Papers | `papers.paper_status` | `archived` | `archived` | `keep` | — | n/a | `historical` | terminal no-action paper state |
| Papers | `papers.paper_status` | `draft_generating` | `drafting` | `keep` | — | n/a | `running` | draft writer is active |
| Papers | `papers.paper_status` | `draft_review` | `finalizing` | `migrate` | publication_draft or archived when automation rejected | yes | `automate_publication` | legacy first-draft label; operator should see first draft or automation |
| Papers | `papers.paper_status` | `eligible` | `needed` | `retire` | draft_generating | no | `write_paper` | paper eligibility now lives in paper_eligibility/write_needed |
| Papers | `papers.paper_status` | `finalized` | `ready_to_publish` | `retire` | publication_draft + publication_automation.finalized | no | `ready_to_publish` | old flattened paper readiness state |
| Papers | `papers.paper_status` | `human_review_required` | `blocked` | `migrate` | blocked | yes | `needs_operator` | manual paper review is not a normal workflow |
| Papers | `papers.paper_status` | `publication_draft` | `finalizing` | `keep` | — | n/a | `automate_publication` | publication readiness also requires finalized automation package |
| Papers | `papers.paper_status` | `publication_generating` | `finalizing` | `keep` | — | n/a | `running` | publication rewrite/finalization is active |
| Papers | `publication_automation_items.automation_status` | `approved_for_finalization` | `finalizing` | `migrate` | queued | yes | `automate_publication` | approval wording is internal compatibility only |
| Papers | `publication_automation_items.automation_status` | `blocked` | `blocked` | `keep` | — | n/a | `needs_operator` | automation blocker |
| Papers | `publication_automation_items.automation_status` | `changes_requested` | `blocked` | `migrate` | blocked | yes | `needs_operator` | legacy paper-review correction state |
| Papers | `publication_automation_items.automation_status` | `claimed` | `finalizing` | `keep` | — | n/a | `automate_publication` | automation actor has claimed the item |
| Papers | `publication_automation_items.automation_status` | `deferred` | `archived` | `keep` | — | n/a | `historical` | intentionally skipped automation item |
| Papers | `publication_automation_items.automation_status` | `finalized` | `ready_to_publish` | `keep` | — | n/a | `ready_to_publish` | finalization package is ready |
| Papers | `publication_automation_items.automation_status` | `in_review` | `finalizing` | `migrate` | claimed | yes | `automate_publication` | legacy paper-review running state |
| Papers | `publication_automation_items.automation_status` | `queued` | `finalizing` | `keep` | — | n/a | `automate_publication` | automation work is queued |
| Papers | `publication_automation_items.automation_status` | `rejected` | `archived` | `keep` | — | n/a | `historical` | terminal non-publication automation state |
| Papers | `publication_automation_items.automation_status` | `triage_ready` | `finalizing` | `migrate` | queued | yes | `automate_publication` | legacy paper-review queue state |
| Papers | `publication_automation_items.automation_status` | `unreviewed` | `finalizing` | `migrate` | queued | yes | `automate_publication` | legacy paper-review queue state |
| Projects | `project_decisions.decision_gate_state` | `malformed` | `done_no_paper` | `keep` | — | n/a | `complete_no_paper` | malformed decision is not writable |
| Projects | `project_decisions.decision_gate_state` | `missing` | `done_no_paper` | `keep` | — | n/a | `complete_no_paper` | missing decision is not writable |
| Projects | `project_decisions.decision_gate_state` | `needs_review` | `done_no_paper` | `migrate` | unknown | yes | `complete_no_paper` | ambiguous decisions must not become paper work |
| Projects | `project_decisions.decision_gate_state` | `negative` | `done_no_paper` | `keep` | — | n/a | `complete_no_paper` | not writable |
| Projects | `project_decisions.decision_gate_state` | `positive` | `paper_positive` | `keep` | — | n/a | `write_paper` | only state allowed to create actionable write_needed |
| Projects | `project_decisions.decision_gate_state` | `unknown` | `done_no_paper` | `keep` | — | n/a | `complete_no_paper` | unknown decision is not writable |
| Ideas | `ideas.idea_status` | `deprecated` | `discarded` | `keep` | — | n/a | `historical` | source/provenance status only |
| Ideas | `ideas.idea_status` | `discarded` | `discarded` | `keep` | — | n/a | `historical` | source/provenance status only |
| Ideas | `ideas.idea_status` | `exploring` | `ready` | `keep` | — | n/a | `ready_queue` | included by default intake policy |
| Ideas | `ideas.idea_status` | `parked` | `held` | `keep` | — | n/a | `historical` | source/provenance status only |
| Ideas | `ideas.idea_status` | `testing` | `ready` | `keep` | — | n/a | `ready_queue` | included by default intake policy |
| Ideas | `ideas.idea_status` | `unknown` | `historical` | `retire` | — | no | `historical` | source/provenance status only |
| Ideas | `ideas.idea_status` | `validated` | `promoted` | `keep` | — | n/a | `historical` | source/provenance status only |
| Projects | `projects.origin_idea_status` | `deprecated` | `historical` | `keep` | — | n/a | `historical` | source/provenance status only |
| Projects | `projects.origin_idea_status` | `discarded` | `historical` | `keep` | — | n/a | `historical` | source/provenance status only |
| Projects | `projects.origin_idea_status` | `exploring` | `historical` | `keep` | — | n/a | `ready_queue` | included by default intake policy |
| Projects | `projects.origin_idea_status` | `parked` | `historical` | `keep` | — | n/a | `historical` | source/provenance status only |
| Projects | `projects.origin_idea_status` | `testing` | `historical` | `keep` | — | n/a | `ready_queue` | included by default intake policy |
| Projects | `projects.origin_idea_status` | `unknown` | `historical` | `retire` | — | no | `historical` | source/provenance status only |
| Projects | `projects.origin_idea_status` | `validated` | `historical` | `keep` | — | n/a | `historical` | source/provenance status only |

## Database cleanup boundary

- Database check constraints remain the guardrail against arbitrary raw state strings.
- `scripts/normalize_state_surfaces.py` owns reviewed cleanup SQL and is dry-run by default.
- `scripts/state_doctor.py` must pass after any cleanup and before unfreezing runtime automation.
- `retire` rows are not noise if classified as inactive historical/attention residue; they remain visible as provenance.
