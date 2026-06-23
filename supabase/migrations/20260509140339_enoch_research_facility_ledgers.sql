-- Enoch Research Facility ledgers.
--
-- This creates a separate, auditable idea-generation lane.  These tables do
-- not dispatch work by themselves.  Promotion into enoch.ideas/projects/queue
-- must be recorded through research_admissions so operators can answer
-- "why did this get queued?" without reading provider logs.

begin;
set local statement_timeout = '5min';
set local lock_timeout = '30s';

create table if not exists enoch.research_sources (
  source_id text primary key check (length(source_id) > 0),
  source_kind text not null check (source_kind in (
    'arxiv',
    'github',
    'hacker_news',
    'x',
    'blog',
    'prior_negative_result',
    'prior_followup_evidence',
    'user_supplied',
    'chatgpt_supplied',
    'internal_generated',
    'manual_note',
    'other'
  )),
  title text not null default '',
  url text not null default '',
  external_id text not null default '',
  retrieved_at timestamptz,
  summary text not null default '',
  payload_json jsonb not null default '{}'::jsonb,
  content_hash text not null default '',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check (payload_json is not null)
);

create table if not exists enoch.research_candidates (
  candidate_id text primary key check (length(candidate_id) > 0),
  generation_mode text not null check (generation_mode in (
    'fresh_grounded',
    'followup_from_negative',
    'moonshot',
    'implementation_gap',
    'paper_replication_extension',
    'home_hardware_accessibility',
    'manual_import'
  )),
  status text not null default 'generated' check (status in ('generated', 'rejected', 'admitted', 'merged', 'needs_review')),
  title text not null check (length(title) > 0),
  category text not null default '',
  priority text not null default '',
  source_kind text not null default '',
  source_ids jsonb not null default '[]'::jsonb check (jsonb_typeof(source_ids) = 'array'),
  source_urls jsonb not null default '[]'::jsonb check (jsonb_typeof(source_urls) = 'array'),
  parent_project_id text not null default '',
  parent_run_id text not null default '',
  hypothesis text not null default '',
  mechanism text not null default '',
  description text not null default '',
  implementation text not null default '',
  baseline_to_beat text not null default '',
  success_threshold text not null default '',
  kill_condition text not null default '',
  accessibility_delta text not null default '',
  expected_artifacts jsonb not null default '[]'::jsonb check (jsonb_typeof(expected_artifacts) = 'array'),
  required_evidence jsonb not null default '[]'::jsonb check (jsonb_typeof(required_evidence) = 'array'),
  likely_failure_modes jsonb not null default '[]'::jsonb check (jsonb_typeof(likely_failure_modes) = 'array'),
  estimated_runtime_class text not null default '' check (estimated_runtime_class in ('', 'small', 'medium', 'large', 'overnight')),
  expected_token_budget text not null default '' check (expected_token_budget in ('', 'small', 'medium', 'large')),
  machine_target text not null default '',
  model text not null default '',
  sandbox text not null default '',
  novelty_score numeric(5,2) not null default 0 check (novelty_score >= 0 and novelty_score <= 10),
  feasibility_score numeric(5,2) not null default 0 check (feasibility_score >= 0 and feasibility_score <= 10),
  accessibility_score numeric(5,2) not null default 0 check (accessibility_score >= 0 and accessibility_score <= 10),
  falsifiability_score numeric(5,2) not null default 0 check (falsifiability_score >= 0 and falsifiability_score <= 10),
  total_score numeric(6,2) not null default 0 check (total_score >= 0 and total_score <= 100),
  score_breakdown jsonb not null default '{}'::jsonb,
  dedupe_key text not null check (length(dedupe_key) > 0),
  similar_prior_projects jsonb not null default '[]'::jsonb check (jsonb_typeof(similar_prior_projects) = 'array'),
  novelty_comparison text not null default '',
  risk_notes text not null default '',
  rejection_reason text not null default '',
  provider text not null default '',
  provider_model text not null default '',
  prompt_version text not null default '',
  generated_by text not null default '',
  raw_candidate_json jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  admitted_at timestamptz,
  check (raw_candidate_json is not null),
  check (
    generation_mode <> 'fresh_grounded'
    or jsonb_array_length(source_urls) > 0
    or jsonb_array_length(source_ids) > 0
  ),
  check (
    generation_mode <> 'followup_from_negative'
    or parent_project_id <> ''
    or parent_run_id <> ''
  )
);

create table if not exists enoch.research_admissions (
  admission_id bigserial primary key,
  candidate_id text not null references enoch.research_candidates(candidate_id) on delete cascade,
  admission_decision text not null check (admission_decision in ('admitted', 'rejected', 'needs_review', 'merged')),
  admission_reason text not null default '',
  score_breakdown jsonb not null default '{}'::jsonb,
  admitted_idea_id text references enoch.ideas(idea_id) on delete set null,
  operator text not null default '',
  idempotency_key text not null unique,
  created_at timestamptz not null default now()
);

create table if not exists enoch.research_lineage (
  lineage_id bigserial primary key,
  source_type text not null check (source_type in ('source', 'candidate', 'idea', 'project', 'run', 'decision', 'paper', 'corpus_import')),
  source_id text not null check (length(source_id) > 0),
  target_type text not null check (target_type in ('source', 'candidate', 'idea', 'project', 'run', 'decision', 'paper', 'corpus_import')),
  target_id text not null check (length(target_id) > 0),
  relation_type text not null check (relation_type in (
    'generated_from',
    'deduped_against',
    'admitted_as',
    'queued_as',
    'ran_as',
    'decided_by',
    'paper_from',
    'imported_as',
    'branched_from',
    'merged_into'
  )),
  evidence_json jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

drop trigger if exists trg_research_sources_updated_at on enoch.research_sources;
create trigger trg_research_sources_updated_at
before update on enoch.research_sources
for each row execute function enoch.set_updated_at();

drop trigger if exists trg_research_candidates_updated_at on enoch.research_candidates;
create trigger trg_research_candidates_updated_at
before update on enoch.research_candidates
for each row execute function enoch.set_updated_at();

create or replace view enoch.research_facility_workbench
with (security_invoker = true) as
select
  c.candidate_id,
  c.generation_mode,
  c.status,
  c.title,
  c.category,
  c.priority,
  c.total_score,
  c.novelty_score,
  c.feasibility_score,
  c.accessibility_score,
  c.falsifiability_score,
  c.dedupe_key,
  c.parent_project_id,
  c.parent_run_id,
  c.similar_prior_projects,
  c.source_urls,
  c.provider,
  c.provider_model,
  c.created_at,
  c.updated_at,
  a.admission_decision,
  a.admission_reason,
  a.admitted_idea_id,
  a.operator as admitted_by,
  a.created_at as admitted_decided_at,
  q.status as admitted_queue_status,
  q.current_run_id as admitted_current_run_id,
  p.project_name as admitted_project_name
from enoch.research_candidates c
left join lateral (
  select *
  from enoch.research_admissions ra
  where ra.candidate_id = c.candidate_id
  order by ra.created_at desc, ra.admission_id desc
  limit 1
) a on true
left join enoch.projects p on p.project_id = a.admitted_idea_id
left join enoch.queue_items q on q.project_id = a.admitted_idea_id;

alter table enoch.research_sources enable row level security;
alter table enoch.research_candidates enable row level security;
alter table enoch.research_admissions enable row level security;
alter table enoch.research_lineage enable row level security;

grant select, insert, update, delete on enoch.research_sources to service_role;
grant select, insert, update, delete on enoch.research_candidates to service_role;
grant select, insert, update, delete on enoch.research_admissions to service_role;
grant select, insert, update, delete on enoch.research_lineage to service_role;
grant usage, select on sequence enoch.research_admissions_admission_id_seq to service_role;
grant usage, select on sequence enoch.research_lineage_lineage_id_seq to service_role;

drop policy if exists service_role_all on enoch.research_sources;
create policy service_role_all on enoch.research_sources
  for all to service_role using (true) with check (true);

drop policy if exists service_role_all on enoch.research_candidates;
create policy service_role_all on enoch.research_candidates
  for all to service_role using (true) with check (true);

drop policy if exists service_role_all on enoch.research_admissions;
create policy service_role_all on enoch.research_admissions
  for all to service_role using (true) with check (true);

drop policy if exists service_role_all on enoch.research_lineage;
create policy service_role_all on enoch.research_lineage
  for all to service_role using (true) with check (true);

comment on table enoch.research_sources is
  'Research Facility source ledger. Captures where generated candidates came from, including external URLs and prior Enoch evidence.';
comment on table enoch.research_candidates is
  'Research Facility candidate ledger. Raw generated ideas before admission; not dispatchable by itself.';
comment on table enoch.research_admissions is
  'Research Facility admission ledger. Records why a candidate was admitted, rejected, merged, or held for review.';
comment on table enoch.research_lineage is
  'Research Facility lineage ledger connecting sources, candidates, admitted ideas, projects, runs, decisions, papers, and corpus imports.';
comment on view enoch.research_facility_workbench is
  'Operator-facing Research Facility workbench view for generated candidates and latest admission/queue state.';

commit;

set statement_timeout = '30min';
set lock_timeout = '30s';

create unique index concurrently if not exists idx_research_sources_kind_external
  on enoch.research_sources(source_kind, external_id)
  where external_id <> '';

create unique index concurrently if not exists idx_research_candidates_dedupe_key
  on enoch.research_candidates(dedupe_key);

create index concurrently if not exists idx_research_candidates_status_score
  on enoch.research_candidates(status, total_score desc, updated_at desc);

create index concurrently if not exists idx_research_candidates_mode_score
  on enoch.research_candidates(generation_mode, total_score desc, updated_at desc);

create index concurrently if not exists idx_research_candidates_parent
  on enoch.research_candidates(parent_project_id, parent_run_id)
  where parent_project_id <> '' or parent_run_id <> '';

create index concurrently if not exists idx_research_admissions_candidate
  on enoch.research_admissions(candidate_id, created_at desc);

create index concurrently if not exists idx_research_lineage_source
  on enoch.research_lineage(source_type, source_id, created_at desc);

create index concurrently if not exists idx_research_lineage_target
  on enoch.research_lineage(target_type, target_id, created_at desc);

create unique index concurrently if not exists idx_research_lineage_identity_unique
  on enoch.research_lineage(source_type, source_id, target_type, target_id, relation_type);

reset lock_timeout;
reset statement_timeout;
