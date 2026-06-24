-- Allow Research Facility synthesis reports to create auditable source rows.
--
-- Synthesis candidates are generated from existing candidate clusters plus
-- reflection seeds. The source row marks that provenance explicitly instead of
-- pretending the synthesized oracle came directly from the original note/arxiv
-- source kind.

begin;

do $$
begin
  if exists (
    select 1
    from enoch.research_sources
    where source_kind not in (
      'arxiv',
      'github',
      'hacker_news',
      'x',
      'blog',
      'prior_negative_result',
      'prior_followup_evidence',
      'followup_parent_run',
      'research_synthesis',
      'user_supplied',
      'chatgpt_supplied',
      'internal_generated',
      'manual_note',
      'other'
    )
  ) then
    raise exception 'research_sources contains source_kind outside synthesis allow-list';
  end if;
end $$;

alter table enoch.research_sources
  drop constraint if exists research_sources_source_kind_check,
  drop constraint if exists research_sources_source_kind_check_v2,
  add constraint research_sources_source_kind_check_v3
  check (source_kind in (
    'arxiv',
    'github',
    'hacker_news',
    'x',
    'blog',
    'prior_negative_result',
    'prior_followup_evidence',
    'followup_parent_run',
    'research_synthesis',
    'user_supplied',
    'chatgpt_supplied',
    'internal_generated',
    'manual_note',
    'other'
  ));

commit;
