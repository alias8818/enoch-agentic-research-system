-- Make corpus publication accounting ledger-owned.
-- `publication_ready` is actionable import work only: finalized publication
-- drafts that do not yet have a corpus_imports row.

begin;
set local statement_timeout = '60s';
set local lock_timeout = '5s';

alter table enoch.corpus_imports
  add column if not exists source_record_fingerprint text default '',
  add column if not exists public_artifact_id text default '',
  add column if not exists public_index_path text default '',
  add column if not exists hf_dataset_synced boolean default false,
  add column if not exists hf_dataset_url text default '';

do $$
declare
  rows_updated integer;
begin
  loop
    update enoch.corpus_imports
    set source_record_fingerprint = left(
      encode(
        extensions.digest(paper_id, 'sha256'),
        'hex'
      ),
      16
    )
    where corpus_import_id in (
      select corpus_import_id
      from enoch.corpus_imports
      where source_record_fingerprint = ''
      order by corpus_import_id
      limit 1000
    );

    get diagnostics rows_updated = row_count;
    exit when rows_updated = 0;
    perform pg_sleep(0.01);
  end loop;
end $$;

do $$
begin
  if exists (
    select 1
    from enoch.corpus_imports
    where source_record_fingerprint <> ''
    group by source_record_fingerprint
    having count(*) > 1
  ) then
    raise exception 'corpus_imports source_record_fingerprint backfill produced duplicates';
  end if;
end $$;

alter table enoch.corpus_imports
  alter column source_record_fingerprint set default '',
  alter column public_artifact_id set default '',
  alter column public_index_path set default '',
  alter column hf_dataset_synced set default false,
  alter column hf_dataset_url set default '';

commit;

set statement_timeout = '60s';
set lock_timeout = '5s';

create unique index concurrently if not exists idx_corpus_imports_source_fingerprint
  on enoch.corpus_imports(source_record_fingerprint)
  where source_record_fingerprint <> '';

create index concurrently if not exists idx_corpus_imports_hf_dataset_synced
  on enoch.corpus_imports(hf_dataset_synced, imported_at desc);

reset lock_timeout;
reset statement_timeout;

begin;
set local statement_timeout = '60s';
set local lock_timeout = '5s';

create or replace view enoch.operator_dashboard_counts as
with finalized_publication as (
  select paper.paper_id
  from enoch.papers paper
  join enoch.publication_automation_items automation_item on automation_item.paper_id = paper.paper_id
  where paper.paper_status = 'publication_draft'
    and automation_item.automation_status = 'finalized'
    and automation_item.finalization_package_path <> ''
)
select
  count(*) filter (where pe.write_needed) as write_needed,
  count(*) filter (where pe.raw_write_candidate) as raw_completed_no_paper_candidates,
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
    from finalized_publication fp
    where not exists (
      select 1
      from enoch.corpus_imports ci
      where ci.paper_id = fp.paper_id
    )
  ) as publication_ready,
  (select count(distinct ci.paper_id) from enoch.corpus_imports ci) as corpus_imported,
  (select count(*) from finalized_publication) as publication_ready_total,
  (
    select count(*)
    from enoch.corpus_imports ci
    where ci.hf_dataset_synced
  ) as hf_dataset_synced
from enoch.queue_items q
left join enoch.paper_eligibility pe on pe.project_id = q.project_id;

comment on view enoch.operator_dashboard_counts is
  'Operator-facing aggregate counts: publication_ready is finalized-but-not-imported work; corpus_imported is ledger-backed public/imported evidence.';
comment on column enoch.corpus_imports.source_record_fingerprint is
  'Stable fingerprint used by the public corpus index to reconcile a control-plane paper row without exposing raw IDs as the primary public key.';
comment on column enoch.corpus_imports.hf_dataset_synced is
  'True when the imported artifact has been included in the Hugging Face dataset sync.';

commit;
