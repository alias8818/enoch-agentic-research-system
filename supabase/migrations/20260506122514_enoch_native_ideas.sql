-- Supabase-native idea workbench.
--
-- This is the database boundary for removing Notion from the runtime path:
-- ideas become canonical rows in private schema `enoch`. Historical Notion IDs
-- and URLs remain as source provenance only and must not be treated as the
-- editable/operator ledger after cutover.

begin;
set local statement_timeout = '5min';
set local lock_timeout = '30s';

create table if not exists enoch.ideas (
  idea_id text primary key check (length(idea_id) > 0),
  title text not null check (length(title) > 0),
  idea_status text not null default 'exploring',
  category text not null default '',
  priority text not null default '',
  source_kind text not null default 'supabase_native',
  source_external_id text not null default '',
  source_external_url text not null default '',
  description text not null default '',
  implementation text not null default '',
  baseline_to_beat text not null default '',
  kill_condition text not null default '',
  accessibility_delta text not null default '',
  experiment_results text not null default '',
  expected_token_budget text not null default '',
  confidence text not null default '',
  feasibility text not null default '',
  leverage text not null default '',
  novelty_score text not null default '',
  signal_speed text not null default '',
  teacher_dependence text not null default '',
  machine_target text not null default '',
  model text not null default '',
  sandbox text not null default '',
  selection_rank integer not null default 50,
  dispatch_priority integer not null default 50,
  source_payload_json jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists enoch.idea_events (
  idea_event_id bigserial primary key,
  idea_id text not null references enoch.ideas(idea_id) on delete cascade,
  event_type text not null check (length(event_type) > 0),
  actor text not null default '',
  payload_json jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

drop trigger if exists trg_ideas_updated_at on enoch.ideas;
create trigger trg_ideas_updated_at
before update on enoch.ideas
for each row execute function enoch.set_updated_at();

create or replace view enoch.idea_workbench
with (security_invoker = true) as
select
  i.idea_id,
  i.title,
  i.idea_status,
  i.category,
  i.priority,
  i.source_kind,
  i.source_external_id,
  i.source_external_url,
  i.machine_target,
  i.model,
  i.sandbox,
  i.selection_rank,
  i.dispatch_priority,
  p.project_id,
  q.status as queue_status,
  q.current_run_id,
  q.last_run_state,
  q.next_action_hint,
  q.manual_review_required,
  q.updated_at as queue_updated_at,
  pa.paper_id,
  pa.paper_status,
  i.created_at,
  i.updated_at
from enoch.ideas i
left join enoch.projects p on p.project_id = i.idea_id
left join enoch.queue_items q on q.project_id = i.idea_id
left join lateral (
  select paper.paper_id, paper.paper_status
  from enoch.papers paper
  where paper.project_id = i.idea_id
  order by paper.updated_at desc
  limit 1
) pa on true;

alter table enoch.ideas enable row level security;
alter table enoch.idea_events enable row level security;

grant select, insert, update, delete on enoch.ideas to service_role;
grant select, insert, update, delete on enoch.idea_events to service_role;
grant usage, select on sequence enoch.idea_events_idea_event_id_seq to service_role;

drop policy if exists service_role_all on enoch.ideas;
create policy service_role_all on enoch.ideas
  for all to service_role using (true) with check (true);

drop policy if exists service_role_all on enoch.idea_events;
create policy service_role_all on enoch.idea_events
  for all to service_role using (true) with check (true);

comment on table enoch.ideas is
  'Supabase-native canonical idea workbench. Historical Notion IDs/URLs are source provenance only; runtime no longer depends on Notion as the editable ledger.';
comment on table enoch.idea_events is
  'Append-only events for Supabase-native idea lifecycle changes.';
comment on view enoch.idea_workbench is
  'Operator workbench view joining native ideas to project, queue, and latest paper state.';
commit;

set statement_timeout = '30min';
set lock_timeout = '30s';

create index concurrently if not exists idx_ideas_status_priority
  on enoch.ideas(idea_status, dispatch_priority asc, selection_rank asc, updated_at desc);

create index concurrently if not exists idx_ideas_source_external
  on enoch.ideas(source_kind, source_external_id)
  where source_external_id <> '';

create index concurrently if not exists idx_idea_events_idea
  on enoch.idea_events(idea_id, created_at desc);

reset lock_timeout;
reset statement_timeout;

begin;
set local statement_timeout = '5min';
set local lock_timeout = '30s';

-- Backfill native ideas from the latest imported Notion payloads retained in
-- control_events. This captures richer idea fields that projects/queue rows do
-- not own, while demoting Notion to immutable provenance.
with latest_rows as (
  select distinct on (row->>'id')
    coalesce(nullif(row->>'property_omx_project_id', ''), replace(row->>'id', '-', '')) as idea_id,
    row,
    ce.created_at as source_created_at
  from enoch.control_events ce
  cross join lateral jsonb_array_elements(ce.payload_json->'notion_rows') as row
  where ce.event_type = 'notion.intake'
    and jsonb_typeof(ce.payload_json->'notion_rows') = 'array'
    and coalesce(row->>'id', '') <> ''
  order by row->>'id', ce.created_at desc
)
insert into enoch.ideas(
  idea_id, title, idea_status, category, priority, source_kind, source_external_id, source_external_url,
  description, implementation, baseline_to_beat, kill_condition, accessibility_delta, experiment_results,
  expected_token_budget, confidence, feasibility, leverage, novelty_score, signal_speed, teacher_dependence,
  machine_target, model, sandbox, selection_rank, dispatch_priority, source_payload_json, created_at, updated_at
)
select
  lr.idea_id,
  coalesce(nullif(lr.row->>'property_idea', ''), nullif(lr.row->>'title', ''), lr.idea_id),
  coalesce(nullif(lr.row->>'property_status', ''), 'unknown'),
  coalesce(lr.row->>'property_category', ''),
  coalesce(lr.row->>'property_priority', ''),
  'notion_import',
  coalesce(lr.row->>'id', ''),
  coalesce(lr.row->>'url', ''),
  coalesce(lr.row->>'property_description', ''),
  coalesce(lr.row->>'property_implementation', ''),
  coalesce(lr.row->>'property_baseline_to_beat', ''),
  coalesce(lr.row->>'property_kill_condition', ''),
  coalesce(lr.row->>'property_accessibility_delta', ''),
  coalesce(lr.row->>'property_experiment_results', ''),
  coalesce(lr.row->>'property_expected_token_budget', ''),
  coalesce(lr.row->>'property_confidence', ''),
  coalesce(lr.row->>'property_feasibility', ''),
  coalesce(lr.row->>'property_leverage', ''),
  coalesce(lr.row->>'property_novelty_score', ''),
  coalesce(lr.row->>'property_signal_speed', ''),
  coalesce(lr.row->>'property_teacher_dependence', ''),
  coalesce(nullif(lr.row->>'property_omx_machine_target', ''), ''),
  coalesce(nullif(lr.row->>'property_omx_model', ''), ''),
  coalesce(nullif(lr.row->>'property_omx_sandbox', ''), ''),
  case
    when coalesce(lr.row->>'property_omx_selection_rank', '') ~ '^\d+$'
      then (lr.row->>'property_omx_selection_rank')::integer
    else 50
  end,
  case
    when coalesce(lr.row->>'property_omx_dispatch_priority', '') ~ '^\d+$'
      then (lr.row->>'property_omx_dispatch_priority')::integer
    else 50
  end,
  lr.row,
  lr.source_created_at,
  now()
from latest_rows lr
where lr.idea_id <> ''
on conflict (idea_id) do nothing;

-- Ensure every existing project has a native idea row even when no historical
-- rich idea payload is available.
insert into enoch.ideas(
  idea_id, title, idea_status, source_kind, source_external_id, source_external_url,
  machine_target, model, sandbox, selection_rank, dispatch_priority, created_at, updated_at
)
select
  p.project_id,
  p.project_name,
  coalesce(nullif(p.origin_idea_status, ''), 'unknown'),
  case
    when p.notion_page_id <> '' or p.notion_page_url <> '' then 'notion_project_snapshot'
    else 'project_snapshot'
  end,
  p.notion_page_id,
  p.notion_page_url,
  coalesce(q.machine_target, ''),
  coalesce(q.model, ''),
  coalesce(q.sandbox, ''),
  coalesce(q.selection_rank, 50),
  coalesce(q.dispatch_priority, 50),
  p.created_at,
  p.updated_at
from enoch.projects p
left join enoch.queue_items q using(project_id)
on conflict (idea_id) do nothing;

insert into enoch.idea_events(idea_id, event_type, actor, payload_json)
select
  i.idea_id,
  'idea.migrated_from_existing_control_plane',
  'migration:20260506122514',
  jsonb_build_object('source_kind', i.source_kind)
from enoch.ideas i
where not exists (
  select 1
  from enoch.idea_events e
  where e.idea_id = i.idea_id
    and e.event_type = 'idea.migrated_from_existing_control_plane'
);

commit;
