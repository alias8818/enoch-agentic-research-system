-- Preserve current publication automation status values during staged SQLite -> Supabase backfill.
-- The table name moved away from operator-facing "review" language, but the migration
-- must still accept existing internal automation states until the write path is cut over.

begin;

do $$
declare
  constraint_name text;
begin
  select conname into constraint_name
  from pg_constraint
  where conrelid = 'enoch.publication_automation_items'::regclass
    and contype = 'c'
    and pg_get_constraintdef(oid) like '%automation_status%';

  if constraint_name is not null then
    execute format('alter table enoch.publication_automation_items drop constraint %I', constraint_name);
  end if;
end $$;

alter table enoch.publication_automation_items
  add constraint publication_automation_items_automation_status_check
  check (
    automation_status in (
      'queued',
      'claimed',
      'blocked',
      'finalized',
      'deferred',
      'triage_ready',
      'unreviewed',
      'in_review',
      'changes_requested',
      'approved_for_finalization',
      'rejected'
    )
  );

comment on column enoch.publication_automation_items.automation_status is
  'Internal publication automation state. Existing SQLite values are preserved for parity; operator UI maps these to automation labels.';

commit;
