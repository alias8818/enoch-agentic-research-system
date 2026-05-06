-- Match the Python dashboard's eligible_paper_draft_candidates contract in SQL.
-- Raw completed/no-paper candidates are not every completed row; they are the
-- completed worker-delivery rows that are draft-ready, not manually blocked,
-- not excluded by human-data keywords, and have no existing paper for the same
-- project or run.

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
), candidate_base as (
  select
    q.*,
    p.project_name,
    p.project_dir,
    p.notion_page_url,
    lower(concat_ws(E'\n', p.project_name, q.last_result_summary, q.blocked_reason)) as draft_exclusion_haystack,
    exists (
      select 1
      from enoch.papers paper
      where paper.project_id = q.project_id
        and paper.paper_status in ('draft_review', 'publication_draft', 'finalized', 'approved_for_corpus')
    ) as has_project_paper_row,
    exists (
      select 1
      from enoch.papers paper
      where paper.run_id = q.current_run_id
        and q.current_run_id <> ''
        and paper.paper_status in ('draft_review', 'publication_draft', 'finalized', 'approved_for_corpus')
    ) as has_run_paper_row
  from enoch.queue_items q
  join enoch.projects p on p.project_id = q.project_id
), candidate_flags as (
  select
    cb.*,
    (
      cb.status = 'completed'
      and (
        cb.last_run_state = 'finalize_positive'
        or (
          cb.last_run_state in ('wake_ready', 'session_finished_ready')
          and cb.next_action_hint = 'draft_paper_or_select_next_project'
          and cb.current_run_id <> ''
          and (cb.project_dir <> '' or cb.notion_page_url <> '' or cb.last_result_summary <> '')
        )
      )
      and not cb.manual_review_required
      and not cb.has_project_paper_row
      and not cb.has_run_paper_row
      and not (
        cb.draft_exclusion_haystack like '%human-validated%'
        or cb.draft_exclusion_haystack like '%human label%'
        or cb.draft_exclusion_haystack like '%human annotation%'
        or cb.draft_exclusion_haystack like '%human rater%'
        or cb.draft_exclusion_haystack like '%reviewer noise%'
        or (cb.draft_exclusion_haystack like '%benchmark%' and cb.draft_exclusion_haystack like '%human%')
      )
    ) as raw_write_candidate
  from candidate_base cb
)
select
  cf.project_id,
  cf.project_name,
  cf.current_run_id as run_id,
  coalesce(d.decision_gate_state, 'missing') as decision_gate_state,
  coalesce(d.decision_summary, '') as decision_summary,
  (cf.has_project_paper_row or cf.has_run_paper_row) as has_live_paper_row,
  (
    cf.raw_write_candidate
    and coalesce(d.decision_gate_state, 'missing') = 'positive'
  ) as write_needed,
  (
    cf.raw_write_candidate
    and coalesce(d.decision_gate_state, 'missing') <> 'positive'
  ) as not_writable_by_decision_gate,
  cf.raw_write_candidate
from candidate_flags cf
left join latest_decision d on d.project_id = cf.project_id;

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
    where paper.paper_status in ('publication_draft', 'finalized', 'approved_for_corpus')
  ) as publication_ready,
  (select count(distinct ci.paper_id) from enoch.corpus_imports ci) as corpus_imported
from enoch.queue_items q
left join enoch.paper_eligibility pe on pe.project_id = q.project_id;

comment on view enoch.paper_eligibility is
  'Decision-gated paper eligibility view matching the dashboard eligible_paper_draft_candidates contract.';
comment on view enoch.operator_dashboard_counts is
  'Operator-facing aggregate counts whose paper pipeline fields match the Python dashboard candidate contract.';

commit;
