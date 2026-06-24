begin;

create table if not exists enoch.core_events (
  id bigserial primary key,
  idempotency_key text not null unique,
  event_type text not null check (length(event_type) > 0),
  source text not null default '',
  payload_json jsonb not null default '{}'::jsonb,
  payload_hash text not null check (length(payload_hash) > 0),
  created_at timestamptz not null default now()
);

create table if not exists enoch.core_snapshots (
  id bigserial primary key,
  idempotency_key text not null unique,
  snapshot_type text not null check (length(snapshot_type) > 0),
  event_id bigint not null references enoch.core_events(id),
  source text not null default '',
  payload_json jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists enoch.core_decisions (
  id bigserial primary key,
  decision_key text not null unique,
  project_id text,
  run_id text,
  decision_type text not null check (length(decision_type) > 0),
  payload_json jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists enoch.core_projection_cache (
  projection_key text primary key,
  projection_version text not null,
  payload_json jsonb not null default '{}'::jsonb,
  rebuilt_at timestamptz not null default now()
);

create index if not exists idx_core_events_type_created
  on enoch.core_events(event_type, created_at desc);
create index if not exists idx_core_snapshots_type_id
  on enoch.core_snapshots(snapshot_type, id desc);
create index if not exists idx_core_decisions_project_run
  on enoch.core_decisions(project_id, run_id, created_at desc);

alter table enoch.core_events enable row level security;
alter table enoch.core_snapshots enable row level security;
alter table enoch.core_decisions enable row level security;
alter table enoch.core_projection_cache enable row level security;

revoke all on enoch.core_events, enoch.core_snapshots, enoch.core_decisions, enoch.core_projection_cache from public, anon, authenticated;
grant select, insert, update, delete on enoch.core_events, enoch.core_snapshots, enoch.core_decisions, enoch.core_projection_cache to service_role;
grant usage, select on sequence enoch.core_events_id_seq, enoch.core_snapshots_id_seq, enoch.core_decisions_id_seq to service_role;

drop policy if exists service_role_all on enoch.core_events;
drop policy if exists service_role_all on enoch.core_snapshots;
drop policy if exists service_role_all on enoch.core_decisions;
drop policy if exists service_role_all on enoch.core_projection_cache;
-- service_role bypasses RLS; explicit grants above are sufficient.
-- Avoid blanket USING (true) policies that can be copied to non-bypass roles.

comment on table enoch.core_events is
  'Append-only Enoch core shadow/proposal events. Supabase-backed replacement for enoch_core.sqlite3 events.';
comment on table enoch.core_snapshots is
  'Enoch core shadow/proposal snapshots. Latest snapshot deterministically rebuilds proposal projections.';
comment on table enoch.core_projection_cache is
  'Optional cached projections for Enoch core; runtime projections can be rebuilt from snapshots.';

commit;
