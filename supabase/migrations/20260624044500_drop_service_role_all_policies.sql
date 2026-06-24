-- Remove redundant blanket service_role RLS policies.
--
-- Supabase/Postgres service_role bypasses RLS; explicit grants are sufficient.
-- Blanket true predicates add no protection for service_role and are dangerous
-- examples if copied to future non-bypass roles.

begin;

do $$
declare
  table_record record;
begin
  for table_record in
    select tablename
    from pg_tables
    where schemaname = 'enoch'
    order by tablename
  loop
    execute format(
      'drop policy if exists service_role_all on enoch.%I',
      table_record.tablename
    );
  end loop;
end;
$$;

commit;
