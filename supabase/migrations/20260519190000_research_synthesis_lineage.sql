-- Support Research Facility cluster synthesis/oracle gating.

alter table enoch.research_candidates
  drop constraint if exists research_candidates_status_check;

alter table enoch.research_candidates
  add constraint research_candidates_status_check
  check (status in (
    'generated',
    'rejected',
    'admitted',
    'merged',
    'needs_review',
    'rewrite_needed',
    'deferred',
    'deferred_pending_oracle',
    'superseded'
  ));

alter table enoch.research_lineage
  drop constraint if exists research_lineage_relation_type_check;

alter table enoch.research_lineage
  add constraint research_lineage_relation_type_check
  check (relation_type in (
    'generated_from',
    'deduped_against',
    'admitted_as',
    'queued_as',
    'ran_as',
    'decided_by',
    'paper_from',
    'imported_as',
    'branched_from',
    'followup_parent',
    'merged_into',
    'synthesized_from',
    'superseded_by',
    'inspired_by_success'
  ));
