-- Tighten the state contract now that the runtime is Supabase-backed.
-- These constraints intentionally preserve known historical/internal states while
-- preventing new arbitrary status strings from entering the operator ledgers.

begin;

alter table enoch.queue_items
  drop constraint if exists queue_items_status_contract_check,
  add constraint queue_items_status_contract_check
  check (status in (
    'queued', 'dispatching', 'running', 'awaiting_wake', 'wake_received',
    'reconciling', 'completed', 'paused', 'canceled', 'dispatch_error',
    'blocked', 'needs_review'
  ));

alter table enoch.runs
  drop constraint if exists runs_state_contract_check,
  add constraint runs_state_contract_check
  check (state in (
    'prepared', 'dispatching', 'running', 'awaiting_wake', 'question_pending',
    'wake_ready', 'session_finished_ready', 'gate_timeout', 'gate_error',
    'reconciled', 'dispatch_error', 'dispatch_accepted', 'needs_review',
    'waiting_external_evidence', 'unknown', 'cancelled', 'canceled'
  ));

alter table enoch.papers
  drop constraint if exists papers_status_contract_check,
  add constraint papers_status_contract_check
  check (paper_status in (
    'eligible', 'draft_generating', 'draft_review', 'publication_generating',
    'publication_draft', 'human_review_required', 'archived', 'finalized',
    'approved_for_corpus'
  ));

alter table enoch.projects
  drop constraint if exists projects_origin_idea_status_contract_check,
  add constraint projects_origin_idea_status_contract_check
  check (origin_idea_status in (
    'unknown', 'exploring', 'testing', 'validated', 'discarded', 'parked',
    'deprecated'
  ));

alter table enoch.ideas
  drop constraint if exists ideas_status_contract_check,
  add constraint ideas_status_contract_check
  check (idea_status in (
    'unknown', 'exploring', 'testing', 'validated', 'discarded', 'parked',
    'deprecated'
  ));

comment on constraint queue_items_status_contract_check on enoch.queue_items is
  'Allowed raw queue states. Operator UI must map these into the simpler operator lanes.';
comment on constraint runs_state_contract_check on enoch.runs is
  'Allowed raw worker/callback states, including historical import values. Not operator-facing vocabulary.';
comment on constraint papers_status_contract_check on enoch.papers is
  'Allowed raw paper artifact states. Public readiness is determined by publication_draft plus finalized automation package.';
comment on constraint projects_origin_idea_status_contract_check on enoch.projects is
  'Allowed source idea states preserved as provenance; execution state lives in queue_items.';
comment on constraint ideas_status_contract_check on enoch.ideas is
  'Allowed Supabase-native idea workbench states.';

commit;
