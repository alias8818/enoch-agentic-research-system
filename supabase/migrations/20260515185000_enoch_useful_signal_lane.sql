-- Useful-signal read model: distinguish bounded local positive signals from
-- paper-positive decisions and from scale-blocked promising results.

begin;

create or replace view enoch.paper_eligibility
with (security_invoker = true) as
with latest_decision as (
  select distinct on (q.project_id)
    q.project_id,
    d.decision_gate_state,
    d.decision_summary,
    d.payload_json,
    d.followup_recommended,
    d.followup_type,
    d.followup_title,
    d.followup_hypothesis,
    d.followup_required_evidence,
    d.followup_success_threshold,
    d.followup_stop_condition,
    d.followup_depth
  from enoch.queue_items q
  left join enoch.project_decisions d
    on d.project_id = q.project_id
   and (d.run_id = nullif(q.current_run_id, '') or d.run_id is null)
  order by q.project_id, d.decided_at desc nulls last, d.decision_id desc nulls last
), decision_fields as (
  select
    ld.*,
    coalesce(ld.payload_json #>> '{project_decision,research_outcome}', '') as research_outcome,
    coalesce(ld.payload_json #>> '{project_decision,hypothesis_status}', '') as hypothesis_status,
    coalesce(ld.payload_json #>> '{project_decision,evidence_strength}', '') as evidence_strength,
    coalesce(ld.payload_json #>> '{project_decision,claim_scope}', '') as claim_scope,
    coalesce(ld.payload_json #>> '{project_decision,scale_limits}', '') as scale_limits,
    coalesce(ld.payload_json #>> '{project_decision,useful_signal_summary}', '') as useful_signal_summary,
    coalesce(ld.payload_json #>> '{project_decision,recommended_next_action}', '') as recommended_next_action,
    coalesce(ld.payload_json #>> '{project_decision,stop_reason}', '') as stop_reason,
    lower(coalesce(ld.payload_json #>> '{project_decision,bounded_paper_ready}', 'false')) in ('true', '1', 'yes') as bounded_paper_ready,
    lower(coalesce(ld.payload_json #>> '{project_decision,compute_scale_blocked}', 'false')) in ('true', '1', 'yes') as compute_scale_blocked
  from latest_decision ld
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
  cf.raw_write_candidate,
  (
    cf.status = 'completed'
    and not cf.manual_review_required
    and not (cf.has_project_paper_row or cf.has_run_paper_row)
    and coalesce(d.decision_gate_state, 'missing') <> 'positive'
    and coalesce(d.followup_recommended, false)
  ) as followup_recommended,
  coalesce(d.followup_type, '') as followup_type,
  coalesce(d.followup_title, '') as followup_title,
  coalesce(d.followup_hypothesis, '') as followup_hypothesis,
  coalesce(d.followup_required_evidence, '[]'::jsonb) as followup_required_evidence,
  coalesce(d.followup_success_threshold, '') as followup_success_threshold,
  coalesce(d.followup_stop_condition, '') as followup_stop_condition,
  coalesce(d.followup_depth, 0) as followup_depth,
  coalesce(d.research_outcome, '') as research_outcome,
  coalesce(d.hypothesis_status, '') as hypothesis_status,
  coalesce(d.evidence_strength, '') as evidence_strength,
  coalesce(d.claim_scope, '') as claim_scope,
  coalesce(d.scale_limits, '') as scale_limits,
  coalesce(d.useful_signal_summary, '') as useful_signal_summary,
  coalesce(d.recommended_next_action, '') as recommended_next_action,
  coalesce(d.stop_reason, '') as stop_reason,
  coalesce(d.bounded_paper_ready, false) as bounded_paper_ready,
  coalesce(d.compute_scale_blocked, false) as compute_scale_blocked
from candidate_flags cf
left join decision_fields d on d.project_id = cf.project_id;

create or replace view enoch.operator_dashboard_counts
with (security_invoker = true) as
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
  ) as hf_dataset_synced,
  count(*) filter (where pe.followup_recommended and not pe.compute_scale_blocked) as followup_needed,
  count(*) filter (where pe.research_outcome in ('useful_signal', 'paper_positive') and not pe.compute_scale_blocked) as useful_signals,
  count(*) filter (where pe.compute_scale_blocked) as compute_scale_blocked
from enoch.queue_items q
left join enoch.paper_eligibility pe on pe.project_id = q.project_id;

comment on view enoch.paper_eligibility is
  'Decision-gated paper eligibility plus bounded useful-signal and follow-up read-model fields.';
comment on view enoch.operator_dashboard_counts is
  'Operator-facing aggregate counts with paper work, useful signals, scale-blocked signals, corpus import work, and follow-up investigation work kept separate.';

commit;
