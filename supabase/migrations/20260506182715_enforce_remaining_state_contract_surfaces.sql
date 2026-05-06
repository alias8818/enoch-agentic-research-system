-- Complete the raw state contract constraints for detail/debug lifecycle
-- columns. These values are intentionally broader than the operator lanes:
-- `last_run_state` can contain wake-gate states and decision-gate summary
-- states, while `gate_state` is strictly wake/run-gate detail.

begin;

alter table enoch.queue_items
  drop constraint if exists queue_items_last_run_state_contract_check,
  add constraint queue_items_last_run_state_contract_check
  check (last_run_state in (
    '', 'prepared', 'dispatching', 'running', 'awaiting_wake',
    'question_pending', 'wake_ready', 'session_finished_ready',
    'gate_timeout', 'gate_error', 'reconciled', 'dispatch_error',
    'dispatch_accepted', 'needs_review', 'waiting_external_evidence',
    'unknown', 'cancelled', 'canceled',
    'positive', 'negative', 'missing', 'malformed'
  ));

alter table enoch.runs
  drop constraint if exists runs_gate_state_contract_check,
  add constraint runs_gate_state_contract_check
  check (gate_state in (
    '', 'prepared', 'dispatching', 'running', 'awaiting_wake',
    'question_pending', 'wake_ready', 'session_finished_ready',
    'gate_timeout', 'gate_error', 'reconciled', 'dispatch_error',
    'dispatch_accepted', 'needs_review', 'waiting_external_evidence',
    'unknown', 'cancelled', 'canceled'
  ));

comment on constraint queue_items_last_run_state_contract_check on enoch.queue_items is
  'Allowed raw queue detail states. This is drill-down evidence only; operator lanes are derived separately.';
comment on constraint runs_gate_state_contract_check on enoch.runs is
  'Allowed raw wake-gate detail states. This is debug evidence only; wake_ready is not paper polarity.';

commit;
