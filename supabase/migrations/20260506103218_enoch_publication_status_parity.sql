-- Preserve current publication automation status values during staged SQLite -> Supabase backfill.
-- The table name moved away from operator-facing "review" language, but the migration
-- must still accept existing internal automation states until the write path is cut over.

begin;

do $$
declare
  constraint_record record;
begin
  for constraint_record in
    select c.conname
    from pg_constraint c
    join pg_attribute a
      on a.attrelid = c.conrelid
     and a.attnum = any(c.conkey)
    where c.conrelid = 'enoch.publication_automation_items'::regclass
      and c.contype = 'c'
      and a.attname = 'automation_status'
  loop
    execute format(
      'alter table enoch.publication_automation_items drop constraint %I',
      constraint_record.conname
    );
  end loop;
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
