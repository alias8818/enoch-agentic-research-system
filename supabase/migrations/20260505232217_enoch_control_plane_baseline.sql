-- Enoch/OMX control-plane baseline for hosted Supabase/Postgres.
-- Baseline draft: apply only to sandbox/preview cloud targets until cutover is approved.
-- Design notes:
--   * The authoritative control-plane schema lives in private schema `enoch`.
--   * `public` remains empty; browser/Data API mutation is not part of Phase 1.
--   * RLS is enabled on all domain tables as defense in depth, with no anon grants.
--   * Operator-facing counts are modeled as views so raw ledgers are not mixed.

begin;

create schema if not exists enoch;
create schema if not exists extensions;

create extension if not exists pgcrypto with schema extensions;

create or replace function enoch.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

create table if not exists enoch.control_flags (
  singleton boolean primary key default true check (singleton),
  queue_paused boolean not null default false,
  maintenance_mode boolean not null default false,
  pause_reason text not null default '',
  paused_at timestamptz,
  paused_by text not null default '',
  updated_at timestamptz not null default now()
);

insert into enoch.control_flags(singleton)
values (true)
on conflict (singleton) do nothing;

create table if not exists enoch.projects (
  project_id text primary key check (length(project_id) > 0),
  project_name text not null check (length(project_name) > 0),
  project_dir text not null default '',
  notion_page_url text not null default '',
  notion_page_id text not null default '',
  origin_idea_status text not null default 'unknown',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists enoch.queue_items (
  project_id text primary key references enoch.projects(project_id) on delete cascade,
  status text not null check (length(status) > 0),
  selection_rank integer not null default 0,
  dispatch_priority integer not null default 0,
  auto_continue boolean not null default false,
  continue_count integer not null default 0 check (continue_count >= 0),
  max_continues integer not null default 0 check (max_continues >= 0),
  retry_count integer not null default 0 check (retry_count >= 0),
  max_retries integer not null default 0 check (max_retries >= 0),
  current_run_id text not null default '',
  current_session_id text not null default '',
  last_run_state text not null default '',
  last_event_type text not null default '',
  next_action_hint text not null default '',
  manual_review_required boolean not null default false,
  blocked_reason text not null default '',
  last_error text not null default '',
  last_result_summary text not null default '',
  machine_target text not null default '',
  model text not null default '',
  sandbox text not null default '',
  last_dispatch_at timestamptz,
  last_callback_at timestamptz,
  stale_after timestamptz,
  updated_at timestamptz not null default now()
);

create table if not exists enoch.runs (
  run_id text primary key check (length(run_id) > 0),
  project_id text not null references enoch.projects(project_id) on delete cascade,
  session_id text not null default '',
  state text not null check (length(state) > 0),
  dispatch_mode text not null default '',
  started_at timestamptz,
  ended_at timestamptz,
  last_callback_at timestamptz,
  gate_state text not null default '',
  current_activity text not null default '',
  idempotency_key text not null,
  updated_at timestamptz not null default now(),
  unique (idempotency_key)
);

create table if not exists enoch.project_decisions (
  decision_id bigserial primary key,
  project_id text not null references enoch.projects(project_id) on delete cascade,
  run_id text references enoch.runs(run_id) on delete set null,
  decision_type text not null default 'project_outcome',
  decision_gate_state text not null check (
    decision_gate_state in ('positive', 'negative', 'needs_review', 'missing', 'malformed', 'unknown')
  ),
  decision_summary text not null default '',
  artifact_path text not null default '',
  payload_json jsonb not null default '{}'::jsonb,
  payload_hash text not null check (payload_hash ~ '^[a-f0-9]{64}$'),
  decided_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (project_id, run_id, decision_type)
);

create table if not exists enoch.papers (
  paper_id text primary key check (length(paper_id) > 0),
  project_id text not null references enoch.projects(project_id) on delete cascade,
  run_id text references enoch.runs(run_id) on delete set null,
  paper_type text not null default 'arxiv_draft',
  paper_status text not null check (length(paper_status) > 0),
  draft_markdown_path text not null default '',
  draft_latex_path text not null default '',
  evidence_bundle_path text not null default '',
  claim_ledger_path text not null default '',
  manifest_path text not null default '',
  artifact_root text not null default '',
  artifact_payload_hash text not null default '',
  generated_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists enoch.publication_automation_items (
  paper_id text primary key references enoch.papers(paper_id) on delete cascade,
  automation_status text not null check (
    automation_status in ('queued', 'claimed', 'blocked', 'finalized', 'deferred')
  ),
  automation_actor text not null default '',
  blocker text not null default '',
  claimed_at timestamptz,
  checklist_json jsonb not null default '{}'::jsonb,
  rank_score integer not null default 0,
  rank_reasons_json jsonb not null default '[]'::jsonb,
  missing_signals_json jsonb not null default '[]'::jsonb,
  rank_tiebreaker text not null default '',
  source_audit_path text not null default '',
  finalization_package_path text not null default '',
  finalized_at timestamptz,
  decision_summary text not null default '',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists enoch.corpus_imports (
  corpus_import_id bigserial primary key,
  paper_id text not null references enoch.papers(paper_id) on delete cascade,
  corpus_repo text not null default '',
  artifact_slug text not null default '',
  commit_sha text not null default '',
  manifest_path text not null default '',
  manifest_hash text not null default '',
  imported_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  unique (paper_id, corpus_repo)
);

create table if not exists enoch.control_events (
  event_id bigserial primary key,
  idempotency_key text not null unique,
  event_type text not null check (length(event_type) > 0),
  entity_type text not null check (length(entity_type) > 0),
  entity_id text not null default '',
  payload_json jsonb not null default '{}'::jsonb,
  payload_hash text not null check (payload_hash ~ '^[a-f0-9]{64}$'),
  created_at timestamptz not null default now()
);

create table if not exists enoch.operator_observations (
  observation_id bigserial primary key,
  source text not null check (length(source) > 0),
  scope text not null default '',
  observed_at timestamptz not null default now(),
  ttl_seconds integer not null default 0 check (ttl_seconds >= 0),
  status text not null default 'unknown',
  payload_json jsonb not null default '{}'::jsonb,
  payload_hash text not null check (payload_hash ~ '^[a-f0-9]{64}$'),
  created_at timestamptz not null default now()
);

create table if not exists enoch.observation_archive_manifests (
  archive_month date primary key,
  observation_count bigint not null check (observation_count >= 0),
  archive_uri text not null,
  archive_hash text not null check (archive_hash ~ '^[a-f0-9]{64}$'),
  created_at timestamptz not null default now()
);

create index if not exists idx_queue_items_status_priority
  on enoch.queue_items(status, dispatch_priority desc, selection_rank asc, updated_at desc);

create unique index if not exists idx_queue_one_active_lane_per_machine
  on enoch.queue_items(machine_target)
  where machine_target <> '' and status in ('dispatching', 'running');

create index if not exists idx_runs_project_state
  on enoch.runs(project_id, state, updated_at desc);

create index if not exists idx_project_decisions_gate
  on enoch.project_decisions(project_id, decision_gate_state, decided_at desc);

create index if not exists idx_papers_project_status
  on enoch.papers(project_id, paper_status, updated_at desc);

create index if not exists idx_publication_automation_status_rank
  on enoch.publication_automation_items(automation_status, rank_score desc, updated_at desc);

create index if not exists idx_control_events_entity
  on enoch.control_events(entity_type, entity_id, created_at desc);

create index if not exists idx_operator_observations_latest
  on enoch.operator_observations(source, scope, observed_at desc, observation_id desc);

create or replace view enoch.paper_eligibility as
select
  q.project_id,
  p.project_name,
  q.current_run_id as run_id,
  coalesce(d.decision_gate_state, 'missing') as decision_gate_state,
  coalesce(d.decision_summary, '') as decision_summary,
  exists (
    select 1
    from enoch.papers paper
    where paper.project_id = q.project_id
      and paper.paper_status in ('draft_review', 'publication_draft', 'finalized', 'approved_for_corpus')
  ) as has_live_paper_row,
  (
    q.status in ('run_complete_no_paper', 'run_complete_draft_needed', 'completed')
    and coalesce(d.decision_gate_state, 'missing') = 'positive'
    and not exists (
      select 1
      from enoch.papers paper
      where paper.project_id = q.project_id
        and paper.paper_status in ('draft_review', 'publication_draft', 'finalized', 'approved_for_corpus')
    )
  ) as write_needed,
  (
    q.status in ('run_complete_no_paper', 'run_complete_draft_needed', 'completed')
    and coalesce(d.decision_gate_state, 'missing') <> 'positive'
  ) as not_writable_by_decision_gate
from enoch.queue_items q
join enoch.projects p on p.project_id = q.project_id
left join lateral (
  select d.*
  from enoch.project_decisions d
  where d.project_id = q.project_id
    and (d.run_id = nullif(q.current_run_id, '') or d.run_id is null)
  order by d.decided_at desc, d.decision_id desc
  limit 1
) d on true;

create or replace view enoch.operator_dashboard_counts as
select
  count(*) filter (where pe.write_needed) as write_needed,
  count(*) filter (
    where q.status in ('run_complete_no_paper', 'run_complete_draft_needed', 'completed')
  ) as raw_completed_no_paper_candidates,
  count(*) filter (where pe.not_writable_by_decision_gate) as not_writable_by_decision_gate,
  count(*) filter (
    where q.manual_review_required or q.blocked_reason <> '' or q.last_error <> ''
  ) as needs_attention,
  count(*) filter (where q.status in ('queued', 'dispatching', 'running')) as active_or_queued,
  (
    select count(*)
    from enoch.publication_automation_items pai
    where pai.automation_status in ('queued', 'claimed')
  ) as publication_automation_pending,
  (
    select count(*)
    from enoch.papers paper
    where paper.paper_status in ('publication_draft', 'finalized', 'approved_for_corpus')
  ) as publication_ready,
  (select count(distinct ci.paper_id) from enoch.corpus_imports ci) as corpus_imported
from enoch.queue_items q
left join enoch.paper_eligibility pe on pe.project_id = q.project_id;

create trigger trg_projects_updated_at
before update on enoch.projects
for each row execute function enoch.set_updated_at();

create trigger trg_queue_items_updated_at
before update on enoch.queue_items
for each row execute function enoch.set_updated_at();

create trigger trg_runs_updated_at
before update on enoch.runs
for each row execute function enoch.set_updated_at();

create trigger trg_project_decisions_updated_at
before update on enoch.project_decisions
for each row execute function enoch.set_updated_at();

create trigger trg_papers_updated_at
before update on enoch.papers
for each row execute function enoch.set_updated_at();

create trigger trg_publication_automation_items_updated_at
before update on enoch.publication_automation_items
for each row execute function enoch.set_updated_at();

alter table enoch.control_flags enable row level security;
alter table enoch.projects enable row level security;
alter table enoch.queue_items enable row level security;
alter table enoch.runs enable row level security;
alter table enoch.project_decisions enable row level security;
alter table enoch.papers enable row level security;
alter table enoch.publication_automation_items enable row level security;
alter table enoch.corpus_imports enable row level security;
alter table enoch.control_events enable row level security;
alter table enoch.operator_observations enable row level security;
alter table enoch.observation_archive_manifests enable row level security;

revoke all on schema enoch from public, anon, authenticated;
revoke all on all tables in schema enoch from public, anon, authenticated;
revoke all on all functions in schema enoch from public, anon, authenticated;

comment on schema enoch is
  'Private Enoch/OMX control-plane schema. Access through trusted backend only during migration.';
comment on view enoch.paper_eligibility is
  'Decision-gated paper eligibility view: write_needed only means positive actionable work with no existing paper row.';
comment on view enoch.operator_dashboard_counts is
  'Operator-facing aggregate counts with raw candidates separated from actionable work.';

commit;
