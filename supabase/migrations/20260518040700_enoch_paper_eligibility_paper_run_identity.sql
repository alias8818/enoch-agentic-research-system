-- Keep paper_eligibility tied to concrete project/run paper identity.
-- Older papers for the same project must not hide new-run write candidates.

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
  order by q.project_id, case when d.run_id = nullif(q.current_run_id, '') then 0 else 1 end, d.decided_at desc nulls last, d.decision_id desc nulls last
), decision_fields as (
  select
    ld.*,
    coalesce(ld.payload_json #>> '{project_decision,research_outcome}', ld.payload_json->>'research_outcome', '') as research_outcome,
    coalesce(ld.payload_json #>> '{project_decision,hypothesis_status}', ld.payload_json->>'hypothesis_status', '') as hypothesis_status,
    coalesce(ld.payload_json #>> '{project_decision,evidence_strength}', ld.payload_json->>'evidence_strength', '') as evidence_strength,
    coalesce(ld.payload_json #>> '{project_decision,claim_scope}', ld.payload_json->>'claim_scope', '') as claim_scope,
    coalesce(ld.payload_json #>> '{project_decision,scale_limits}', ld.payload_json->>'scale_limits', '') as scale_limits,
    coalesce(ld.payload_json #>> '{project_decision,useful_signal_summary}', ld.payload_json->>'useful_signal_summary', '') as useful_signal_summary,
    coalesce(ld.payload_json #>> '{project_decision,recommended_next_action}', ld.payload_json->>'recommended_next_action', '') as recommended_next_action,
    coalesce(ld.payload_json #>> '{project_decision,stop_reason}', ld.payload_json->>'stop_reason', '') as stop_reason,
    lower(coalesce(ld.payload_json #>> '{project_decision,bounded_paper_ready}', ld.payload_json->>'bounded_paper_ready', 'false')) in ('true', '1', 'yes') as bounded_paper_ready,
    lower(coalesce(ld.payload_json #>> '{project_decision,compute_scale_blocked}', ld.payload_json->>'compute_scale_blocked', 'false')) in ('true', '1', 'yes') as compute_scale_blocked
  from latest_decision ld
), candidate_base as (
  select
    q.*,
    p.project_name,
    p.project_dir,
    p.notion_page_url,
    lower(concat_ws(E'\n', p.project_name, q.last_result_summary, q.blocked_reason)) as draft_exclusion_haystack,
    exists (
      select 1 from enoch.papers paper
      where paper.project_id = q.project_id
        and paper.run_id = q.current_run_id
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
      and not cb.has_run_paper_row
      and cb.project_id not like 'canonical-positive-smoke-%'
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
), eligible as (
  select
    cf.*,
    coalesce(d.decision_gate_state, 'missing') = 'positive'
      or (
        coalesce(d.decision_gate_state, 'missing') = 'negative'
        and coalesce(d.research_outcome, '') = 'useful_signal'
        and coalesce(d.bounded_paper_ready, false)
        and coalesce(d.hypothesis_status, '') in ('supported', 'mixed')
        and coalesce(d.evidence_strength, '') in ('moderate', 'strong')
        and coalesce(d.claim_scope, '') <> ''
        and coalesce(d.scale_limits, '') <> ''
      ) as paper_gate_eligible,
    d.decision_gate_state as pe_decision_gate_state,
    d.decision_summary as pe_decision_summary,
    d.followup_recommended as pe_followup_recommended,
    d.followup_type as pe_followup_type,
    d.followup_title as pe_followup_title,
    d.followup_hypothesis as pe_followup_hypothesis,
    d.followup_required_evidence as pe_followup_required_evidence,
    d.followup_success_threshold as pe_followup_success_threshold,
    d.followup_stop_condition as pe_followup_stop_condition,
    d.followup_depth as pe_followup_depth,
    d.research_outcome as pe_research_outcome,
    d.hypothesis_status as pe_hypothesis_status,
    d.evidence_strength as pe_evidence_strength,
    d.claim_scope as pe_claim_scope,
    d.scale_limits as pe_scale_limits,
    d.useful_signal_summary as pe_useful_signal_summary,
    d.recommended_next_action as pe_recommended_next_action,
    d.stop_reason as pe_stop_reason,
    d.bounded_paper_ready as pe_bounded_paper_ready,
    d.compute_scale_blocked as pe_compute_scale_blocked
  from candidate_flags cf
  left join decision_fields d on d.project_id = cf.project_id
)
select
  e.project_id,
  e.project_name,
  e.current_run_id as run_id,
  coalesce(e.pe_decision_gate_state, 'missing') as decision_gate_state,
  coalesce(e.pe_decision_summary, '') as decision_summary,
  e.has_run_paper_row as has_live_paper_row,
  (e.raw_write_candidate and e.paper_gate_eligible) as write_needed,
  (e.raw_write_candidate and not e.paper_gate_eligible) as not_writable_by_decision_gate,
  e.raw_write_candidate,
  (
    e.status = 'completed'
    and not e.manual_review_required
    and not e.has_run_paper_row
    and not e.paper_gate_eligible
    and coalesce(e.pe_followup_recommended, false)
  ) as followup_recommended,
  coalesce(e.pe_followup_type, '') as followup_type,
  coalesce(e.pe_followup_title, '') as followup_title,
  coalesce(e.pe_followup_hypothesis, '') as followup_hypothesis,
  coalesce(e.pe_followup_required_evidence, '[]'::jsonb) as followup_required_evidence,
  coalesce(e.pe_followup_success_threshold, '') as followup_success_threshold,
  coalesce(e.pe_followup_stop_condition, '') as followup_stop_condition,
  coalesce(e.pe_followup_depth, 0) as followup_depth,
  coalesce(e.pe_research_outcome, '') as research_outcome,
  coalesce(e.pe_hypothesis_status, '') as hypothesis_status,
  coalesce(e.pe_evidence_strength, '') as evidence_strength,
  coalesce(e.pe_claim_scope, '') as claim_scope,
  coalesce(e.pe_scale_limits, '') as scale_limits,
  coalesce(e.pe_useful_signal_summary, '') as useful_signal_summary,
  coalesce(e.pe_recommended_next_action, '') as recommended_next_action,
  coalesce(e.pe_stop_reason, '') as stop_reason,
  coalesce(e.pe_bounded_paper_ready, false) as bounded_paper_ready,
  coalesce(e.pe_compute_scale_blocked, false) as compute_scale_blocked
from eligible e;

comment on view enoch.paper_eligibility is
  'Decision-gated paper eligibility plus paper-scout bounded useful-signal readiness.';

commit;
