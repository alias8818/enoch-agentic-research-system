-- Advisor hardening for the Enoch/OMX control-plane baseline.
-- Keeps the schema private while making trusted backend access explicit.

begin;

create or replace function enoch.set_updated_at()
returns trigger
language plpgsql
set search_path = enoch, pg_temp
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

create index if not exists idx_papers_run_id
  on enoch.papers(run_id)
  where run_id is not null;

create index if not exists idx_project_decisions_run_id
  on enoch.project_decisions(run_id)
  where run_id is not null;

grant usage on schema enoch to service_role;
grant select, insert, update, delete on all tables in schema enoch to service_role;
grant usage, select on all sequences in schema enoch to service_role;
grant execute on all functions in schema enoch to service_role;

do $$
declare
  table_record record;
begin
  for table_record in
    select tablename
    from pg_tables
    where schemaname = 'enoch'
      and not exists (
        select 1
        from pg_policies policy
        where policy.schemaname = 'enoch'
          and policy.tablename = pg_tables.tablename
      )
    order by tablename
  loop
    execute format(
      'create policy service_role_all on enoch.%I for all to service_role using (true) with check (true)',
      table_record.tablename
    );
  end loop;
end;
$$;

commit;
