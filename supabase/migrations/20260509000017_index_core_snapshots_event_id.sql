-- Fix Supabase advisor lint 0001_unindexed_foreign_keys for
-- enoch.core_snapshots(event_id) -> enoch.core_events(id).
--
-- Keep the recent "unused index" INFO findings unchanged for now: these tables
-- are new runtime ledgers and query stats can be sparse/reset. Dropping those
-- indexes before the workload stabilizes risks removing intended read paths.

create index if not exists idx_core_snapshots_event_id
  on enoch.core_snapshots(event_id);
