-- Keep Supabase operator paper counts aligned with the dashboard contract:
-- raw completed/no-paper candidates are only rows without an existing paper row.

begin;

create or replace view enoch.paper_eligibility as
with latest_decision as (
  select distinct on (q.project_id)
    q.project_id,
    d.decision_gate_state,
    d.decision_summary
  from enoch.queue_items q
  left join enoch.project_decisions d
    on d.project_id = q.project_id
   and (d.run_id = nullif(q.current_run_id, '') or d.run_id is null)
  order by q.project_id, d.decided_at desc nulls last, d.decision_id desc nulls last
), paper_presence as (
  select
    q.project_id,
    exists (
      select 1
      from enoch.papers paper
      where paper.project_id = q.project_id
        and paper.paper_status in ('draft_review', 'publication_draft', 'finalized', 'approved_for_corpus')
    ) as has_live_paper_row
  from enoch.queue_items q
)
select
  q.project_id,
  p.project_name,
  q.current_run_id as run_id,
  coalesce(d.decision_gate_state, 'missing') as decision_gate_state,
  coalesce(d.decision_summary, '') as decision_summary,
  pp.has_live_paper_row,
  (
    q.status in ('run_complete_no_paper', 'run_complete_draft_needed', 'completed')
    and coalesce(d.decision_gate_state, 'missing') = 'positive'
    and not pp.has_live_paper_row
  ) as write_needed,
  (
    q.status in ('run_complete_no_paper', 'run_complete_draft_needed', 'completed')
    and coalesce(d.decision_gate_state, 'missing') <> 'positive'
    and not pp.has_live_paper_row
  ) as not_writable_by_decision_gate
from enoch.queue_items q
join enoch.projects p on p.project_id = q.project_id
join paper_presence pp on pp.project_id = q.project_id
left join latest_decision d on d.project_id = q.project_id;

create or replace view enoch.operator_dashboard_counts as
select
  count(*) filter (where pe.write_needed) as write_needed,
  count(*) filter (
    where q.status in ('run_complete_no_paper', 'run_complete_draft_needed', 'completed')
      and not coalesce(pe.has_live_paper_row, false)
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

comment on view enoch.paper_eligibility is
  'Decision-gated paper eligibility view: write_needed only means positive actionable work with no existing paper row.';
comment on view enoch.operator_dashboard_counts is
  'Operator-facing aggregate counts with raw completed/no-paper candidates separated from completed rows that already have papers.';

commit;
