set statement_timeout = '30min';
set lock_timeout = '30s';

with duplicate_lineage as (
  select
    lineage_id,
    row_number() over (
      partition by source_type, source_id, target_type, target_id, relation_type
      order by lineage_id asc
    ) as duplicate_rank
  from enoch.research_lineage
)
delete from enoch.research_lineage rl
using duplicate_lineage d
where rl.lineage_id = d.lineage_id
  and d.duplicate_rank > 1;

create unique index concurrently if not exists idx_research_lineage_identity_unique
  on enoch.research_lineage(source_type, source_id, target_type, target_id, relation_type);

with duplicate_migration_events as (
  select
    idea_event_id,
    row_number() over (
      partition by idea_id, event_type, actor
      order by idea_event_id asc
    ) as duplicate_rank
  from enoch.idea_events
  where event_type = 'idea.migrated_from_existing_control_plane'
    and actor = 'migration:20260506122514'
)
delete from enoch.idea_events e
using duplicate_migration_events d
where e.idea_event_id = d.idea_event_id
  and d.duplicate_rank > 1;

create unique index concurrently if not exists idx_idea_events_native_migration_once
  on enoch.idea_events(idea_id, event_type, actor)
  where event_type = 'idea.migrated_from_existing_control_plane'
    and actor = 'migration:20260506122514';

reset lock_timeout;
reset statement_timeout;
