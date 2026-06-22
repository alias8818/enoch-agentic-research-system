begin;
set local statement_timeout = '5min';
set local lock_timeout = '30s';

-- Allow the Research Facility LLM janitor to close review loops without losing
-- operator meaning. These statuses keep rejected rows distinct from candidates
-- that need a rewrite or are safe to defer.

alter table enoch.research_candidates
  drop constraint if exists research_candidates_status_check;

alter table enoch.research_candidates
  add constraint research_candidates_status_check
  check (status in ('generated', 'rejected', 'admitted', 'merged', 'needs_review', 'rewrite_needed', 'deferred'));

alter table enoch.research_admissions
  drop constraint if exists research_admissions_admission_decision_check;

alter table enoch.research_admissions
  add constraint research_admissions_admission_decision_check
  check (admission_decision in ('admitted', 'rejected', 'needs_review', 'merged', 'rewrite_needed', 'deferred'));

commit;
