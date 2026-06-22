-- Keep dashboard list pages on Postgres indexes after moving filtering,
-- sorting, and pagination out of Python and into SQL.
-- Build indexes concurrently because these tables are hot in production.
-- This migration intentionally does not use a transaction block: PostgreSQL
-- forbids CREATE INDEX CONCURRENTLY inside transactions.

set statement_timeout = '30min';
set lock_timeout = '30s';

create index concurrently if not exists idx_queue_items_updated_desc
  on enoch.queue_items(updated_at desc, project_id desc);

create index concurrently if not exists idx_queue_items_status_updated_desc
  on enoch.queue_items(status, updated_at desc, project_id desc);

create index concurrently if not exists idx_queue_items_priority_page
  on enoch.queue_items(dispatch_priority asc, selection_rank asc, updated_at desc, project_id desc);

create index concurrently if not exists idx_papers_updated_desc
  on enoch.papers(updated_at desc, paper_id desc);

create index concurrently if not exists idx_papers_status_updated_desc
  on enoch.papers(paper_status, updated_at desc, paper_id desc);

create index concurrently if not exists idx_runs_updated_desc
  on enoch.runs(updated_at desc, run_id desc);

create index concurrently if not exists idx_runs_state_updated_desc
  on enoch.runs(state, updated_at desc, run_id desc);

reset lock_timeout;
reset statement_timeout;
