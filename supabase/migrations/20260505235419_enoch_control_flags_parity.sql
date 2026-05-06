-- Preserve SQLite control-plane safety defaults in Supabase.

begin;

alter table enoch.control_flags
  alter column queue_paused set default true,
  alter column maintenance_mode set default true,
  alter column pause_reason set default 'hard cutover: LangGraph control plane not resumed',
  alter column paused_by set default 'system';

update enoch.control_flags
set queue_paused = true,
    maintenance_mode = true,
    pause_reason = case
      when pause_reason = '' then 'hard cutover: LangGraph control plane not resumed'
      else pause_reason
    end,
    paused_at = coalesce(paused_at, now()),
    paused_by = case when paused_by = '' then 'system' else paused_by end,
    updated_at = now()
where singleton = true;

commit;
