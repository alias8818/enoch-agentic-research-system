-- Allow deterministic follow-up source provenance rows.
--
-- Follow-up launches capture their parent run as a research_sources row and a
-- project-to-project lineage edge. Keep the database contract aligned with the
-- creation path so provenance capture cannot fail after application validation.

begin;

alter table enoch.research_sources
  drop constraint if exists research_sources_source_kind_check;

alter table enoch.research_sources
  add constraint research_sources_source_kind_check
  check (source_kind in (
    'arxiv',
    'github',
    'hacker_news',
    'x',
    'blog',
    'prior_negative_result',
    'prior_followup_evidence',
    'followup_parent_run',
    'user_supplied',
    'chatgpt_supplied',
    'internal_generated',
    'manual_note',
    'other'
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
    'merged_into'
  ));

commit;
