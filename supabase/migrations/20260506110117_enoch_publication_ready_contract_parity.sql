-- Match the Python operator model's ready_to_publish contract in SQL.
-- A publication draft is ready to publish only after automated finalization has
-- produced a finalized review row with a finalization package.

begin;

create or replace view enoch.operator_dashboard_counts as
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
    from enoch.papers paper
    join enoch.publication_automation_items automation_item on automation_item.paper_id = paper.paper_id
    where paper.paper_status = 'publication_draft'
      and automation_item.automation_status = 'finalized'
      and automation_item.finalization_package_path <> ''
  ) as publication_ready,
  (select count(distinct ci.paper_id) from enoch.corpus_imports ci) as corpus_imported
from enoch.queue_items q
left join enoch.paper_eligibility pe on pe.project_id = q.project_id;

comment on view enoch.operator_dashboard_counts is
  'Operator-facing aggregate counts matching the Python dashboard candidate and publication-ready contracts.';

commit;
