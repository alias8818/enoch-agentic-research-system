import { describe, expect, it } from 'vitest'
import { deriveDetailOperatorSummary, deriveIntakeIdeaOperatorSummary, deriveResearchCandidateOperatorSummary } from './detailOperatorSummary'

describe('deriveDetailOperatorSummary', () => {
  it('answers project operator questions from queue_item and related rows', () => {
    const summary = deriveDetailOperatorSummary('project', {
      project_id: 'project-1',
      project: { project_name: 'Trace oracle', origin_idea_status: 'admitted' },
      queue_item: {
        status: 'queued',
        machine_target: 'gb10',
        current_run_id: 'run-1',
        last_run_state: 'queued',
        related_paper_id: 'paper-1',
        related_paper_status: 'publication_draft',
        operator_next_step: 'Run dispatch dry-run on gb10.',
      },
      events: [{ summary: 'Queue item created', created_at: '2026-05-21T10:00:00Z' }],
    })

    expect(summary.state).not.toBe('—')
    expect(summary.context).toContain('gb10')
    expect(summary.next).toContain('dry-run')
    expect(summary.entityLinks).toEqual(expect.arrayContaining([
      expect.objectContaining({ kind: 'run', id: 'run-1' }),
      expect.objectContaining({ kind: 'paper', id: 'paper-1' }),
    ]))
    expect(summary.sections.some((section) => section.title === 'What is this project?')).toBe(true)
    expect(summary.sections.some((section) => section.title === 'Paper and publication path')).toBe(true)
    expect(summary.recentActivity).toContain('Queue item created')
  })

  it('preserves unknown corpus import state instead of reporting no', () => {
    const summary = deriveDetailOperatorSummary('project', {
      project_id: 'project-1',
      project: { project_name: 'Trace oracle' },
      queue_item: { status: 'queued', related_paper_id: 'paper-1' },
    })
    const paperSection = summary.sections.find((section) => section.title === 'Paper and publication path')
    expect(paperSection?.answers.find((answer) => answer.label === 'corpus imported')?.value).toBe('unknown')
  })

  it('maps numeric corpus import flags from queue rows', () => {
    const summary = deriveDetailOperatorSummary('project', {
      project_id: 'project-1',
      project: { project_name: 'Trace oracle' },
      queue_item: { status: 'queued', related_paper_id: 'paper-1', related_corpus_imported: 1 },
    })
    const paperSection = summary.sections.find((section) => section.title === 'Paper and publication path')
    expect(paperSection?.answers.find((answer) => answer.label === 'corpus imported')?.value).toBe('yes')
  })

  it('prefers queue finalization status over stale paper row data', () => {
    const summary = deriveDetailOperatorSummary('project', {
      project_id: 'project-1',
      project: { project_name: 'Trace oracle' },
      queue_item: { status: 'queued', related_finalization_status: 'package_ready' },
      papers: [{ paper_id: 'paper-1', finalization_status: 'draft_only' }],
    })
    const paperSection = summary.sections.find((section) => section.title === 'Paper and publication path')
    expect(paperSection?.answers.find((answer) => answer.label === 'finalization status')?.value).toBe('package_ready')
  })

  it('does not duplicate operator stage in the paper publication section', () => {
    const summary = deriveDetailOperatorSummary('project', {
      project_id: 'project-1',
      project: { project_name: 'Trace oracle' },
      queue_item: {
        status: 'queued',
        operator_stage_label: 'Write papers',
        related_paper_id: 'paper-1',
        related_paper_status: 'publication_draft',
      },
    })
    const paperSection = summary.sections.find((section) => section.title === 'Paper and publication path')
    expect(paperSection?.answers.some((answer) => answer.label === 'operator stage')).toBe(false)
    expect(summary.state).toBe('Write papers')
  })

  it('answers run operator questions with lane, outcome, and publication path', () => {
    const summary = deriveDetailOperatorSummary('run', {
      run_id: 'run-1',
      run: {
        run_id: 'run-1',
        project_id: 'project-1',
        project_name: 'Trace oracle',
        state: 'running',
        gate_state: 'awaiting_wake',
        current_activity: 'testing',
        operator_lane: 'write_paper',
        started_at: '2026-05-21T09:00:00Z',
        updated_at: '2026-05-21T10:00:00Z',
        related_paper_id: 'paper-1',
        related_paper_status: 'publication_draft',
        related_review_status: 'ready',
        related_artifact_paths_present: { evidence_bundle: true, claim_ledger: false, finalization_package: true },
      },
      queue_item: { machine_target: 'gb10', operator_lane: 'write_paper' },
      events: [{ summary: 'Wake callback pending', created_at: '2026-05-21T10:01:00Z' }],
    })

    expect(summary.state).toBe('running')
    expect(summary.context).toContain('waiting for wake')
    expect(summary.next).toContain('wake callback')
    expect(summary.entityLinks[0]).toMatchObject({ kind: 'project', id: 'project-1' })
    expect(summary.sections.some((section) => section.title === 'Worker and lane')).toBe(true)
    expect(summary.sections.some((section) => section.title === 'Run outcome')).toBe(true)
    expect(summary.sections.some((section) => section.title === 'Paper and publication path')).toBe(true)
    const laneSection = summary.sections.find((section) => section.title === 'Worker and lane')
    expect(laneSection?.answers.find((answer) => answer.label === 'machine target')?.value).toBe('gb10')
    expect(laneSection?.answers.find((answer) => answer.label === 'operator lane')?.value).toBe('write_paper')
    const outcomeSection = summary.sections.find((section) => section.title === 'Run outcome')
    expect(outcomeSection?.answers.find((answer) => answer.label === 'outcome')?.value).toBe('waiting for wake')
    expect(summary.sections.flatMap((section) => section.answers)).toEqual(expect.arrayContaining([
      expect.objectContaining({ label: 'gate', value: 'awaiting_wake' }),
      expect.objectContaining({ label: 'evidence bundle', value: 'present' }),
      expect.objectContaining({ label: 'finalization package', value: 'present' }),
    ]))
    expect(summary.recentActivity).toContain('Wake callback pending')
  })

  it('does not treat operator_lane as machine target without queue_item', () => {
    const summary = deriveDetailOperatorSummary('run', {
      run_id: 'run-1',
      run: {
        run_id: 'run-1',
        state: 'running',
        operator_lane: 'write_paper',
      },
    })
    const laneSection = summary.sections.find((section) => section.title === 'Worker and lane')
    expect(laneSection?.answers.find((answer) => answer.label === 'machine target')?.value).toBe('—')
    expect(laneSection?.answers.find((answer) => answer.label === 'operator lane')?.value).toBe('write_paper')
  })

  it('labels finished runs from ended_at even when gate is still awaiting_wake', () => {
    const summary = deriveDetailOperatorSummary('run', {
      run_id: 'run-1',
      run: {
        run_id: 'run-1',
        state: 'completed',
        gate_state: 'awaiting_wake',
        ended_at: '2026-05-21T11:00:00Z',
      },
    })
    const outcomeSection = summary.sections.find((section) => section.title === 'Run outcome')
    expect(outcomeSection?.answers.find((answer) => answer.label === 'outcome')?.value).toBe('finished')
  })

  it('answers paper operator questions with publication blockers and lane context', () => {
    const summary = deriveDetailOperatorSummary('paper', {
      paper_id: 'paper-1',
      paper: {
        paper_id: 'paper-1',
        title: 'Artifact paper',
        project_id: 'project-1',
        run_id: 'run-1',
        paper_status: 'publication_draft',
        review_status: 'ready',
        artifact_paths_present: {
          draft_markdown: true,
          evidence_bundle: true,
          claim_ledger: true,
          manifest: false,
          finalization_package: false,
        },
      },
      queue_item: { machine_target: 'gb10' },
      run: { run_id: 'run-1', state: 'completed' },
    })

    expect(summary.state).toBe('publication_draft')
    expect(summary.context).toContain('manifest')
    expect(summary.next).toContain('finalize')
    expect(summary.entityLinks).toEqual(expect.arrayContaining([
      expect.objectContaining({ kind: 'project', id: 'project-1' }),
      expect.objectContaining({ kind: 'run', id: 'run-1' }),
    ]))
    expect(summary.sections.some((section) => section.title === 'What is this paper?')).toBe(true)
    expect(summary.sections.some((section) => section.title === 'What blocks publication?')).toBe(true)
    const blockers = summary.sections.find((section) => section.title === 'What blocks publication?')
    expect(blockers?.answers.find((answer) => answer.label === 'missing artifacts')?.value).toContain('manifest')
    const laneSection = summary.sections.find((section) => section.title === 'Related project and run')
    expect(laneSection?.answers.find((answer) => answer.label === 'machine target')?.value).toBe('gb10')
    expect(summary.actionNeeded).toContain('manifest')
  })

  it('accepts backend artifact path keys in publication checklist', () => {
    const summary = deriveDetailOperatorSummary('paper', {
      paper_id: 'paper-2',
      paper: {
        paper_id: 'paper-2',
        paper_status: 'publication_draft',
        artifact_paths_present: {
          draft_markdown_path: '/tmp/draft.md',
          draft_latex_path: '/tmp/draft.tex',
          evidence_bundle_path: '/tmp/evidence',
          claim_ledger_path: '/tmp/claims',
          manifest_path: '/tmp/manifest.json',
          finalization_package_path: '/tmp/package',
        },
      },
    })
    const checklist = summary.sections.find((section) => section.title === 'Publication checklist')
    expect(checklist?.answers.every((answer) => answer.value === 'present')).toBe(true)
    const blockers = summary.sections.find((section) => section.title === 'What blocks publication?')
    expect(blockers?.answers.find((answer) => answer.label === 'missing artifacts')?.value).toContain('corpus import')
  })

  it('answers event operator questions with entity links and payload proof', () => {
    const summary = deriveDetailOperatorSummary('event', {
      id: 9,
      event_type: 'Queue Alert',
      project_id: 'project-1',
      run_id: 'run-1',
      summary: 'Lane blocked on gb10',
      created_at: '2026-05-21T10:00:00Z',
      payload: { reason: 'lane active', gate_state: 'awaiting_wake' },
    })

    expect(summary.state).toBe('Lane blocked on gb10')
    expect(summary.context).toContain('project-1')
    expect(summary.context).toContain('2026-05-21T10:00:00Z')
    expect(summary.entityLinks).toEqual(expect.arrayContaining([
      expect.objectContaining({ kind: 'project', id: 'project-1' }),
      expect.objectContaining({ kind: 'run', id: 'run-1' }),
    ]))
    expect(summary.sections.some((section) => section.title === 'What happened?')).toBe(true)
    expect(summary.sections.some((section) => section.title === 'When?')).toBe(true)
    expect(summary.sections.some((section) => section.title === 'Which entity was affected?')).toBe(true)
    expect(summary.sections.some((section) => section.title === 'What does the payload prove?')).toBe(true)
    const proof = summary.sections.find((section) => section.title === 'What does the payload prove?')
    expect(proof?.answers).toEqual(expect.arrayContaining([
      expect.objectContaining({ label: 'reason', value: 'lane active' }),
      expect.objectContaining({ label: 'gate state', value: 'awaiting_wake' }),
    ]))
    expect(summary.actionNeeded).toBe('lane active')
    expect(summary.next).toContain('lane active')
  })

  it('derives entity links from nested payload and entity_type', () => {
    const summary = deriveDetailOperatorSummary('event', {
      event_id: 42,
      event_type: 'Run Error',
      entity_type: 'run',
      entity_id: 'run-9',
      created_at: '2026-05-21T11:00:00Z',
      payload: { error: 'dispatch failed', run_id: 'run-9' },
    })

    expect(summary.entityLinks[0]).toMatchObject({ kind: 'run', id: 'run-9' })
    expect(summary.actionNeeded).toBe('dispatch failed')
  })
})

describe('deriveIntakeIdeaOperatorSummary', () => {
  it('answers intake admission and queue questions from read-model fields', () => {
    const summary = deriveIntakeIdeaOperatorSummary({
      idea_id: 'idea-1',
      project_id: 'project-1',
      title: 'New oracle trace',
      idea_status: 'admitted',
      queue_status: 'queued',
      paper_status: 'none',
      source_kind: 'supabase_idea',
      source_external_id: 'ext-42',
      source_external_url: 'https://example.invalid/idea',
      machine_target: 'gb10',
      current_run_id: 'run-1',
      next_action_hint: 'Dispatch dry-run recommended',
      operator_stage_label: 'Ready queue',
      operator_next_step: 'Dispatch when the lane is available.',
    })

    expect(summary.state).toBe('Ready queue')
    expect(summary.next).toBe('Dispatch when the lane is available.')
    expect(summary.context).toContain('gb10')
    expect(summary.entityLinks).toEqual(expect.arrayContaining([
      expect.objectContaining({ kind: 'project', id: 'project-1' }),
      expect.objectContaining({ kind: 'run', id: 'run-1' }),
    ]))
    expect(summary.sections.some((section) => section.title === 'Admission and promote')).toBe(true)
    expect(summary.sections.some((section) => section.title === 'Queue and lane')).toBe(true)
    const lineage = summary.sections.find((section) => section.title === 'Source and lineage')
    expect(lineage?.answers.find((answer) => answer.label === 'source external id')?.value).toBe('ext-42')
    const queue = summary.sections.find((section) => section.title === 'Queue and lane')
    expect(queue?.answers.find((answer) => answer.label === 'why not queued')?.value).toBe('currently queued')
  })

  it('explains rejected and candidate ideas that are not queued', () => {
    const rejected = deriveIntakeIdeaOperatorSummary({
      idea_id: 'idea-reject',
      idea_status: 'rejected',
      queue_status: '',
      source_kind: 'research_facility',
    })
    expect(rejected.next).toContain('Do not queue')
    expect(rejected.actionNeeded).toContain('rejected')
    const queue = rejected.sections.find((section) => section.title === 'Queue and lane')
    expect(queue?.answers.find((answer) => answer.label === 'why not queued')?.value).toContain('rejected')

    const candidate = deriveIntakeIdeaOperatorSummary({
      idea_id: 'idea-candidate',
      idea_status: 'candidate',
      queue_status: '',
      source_kind: 'internal_generated',
    })
    expect(candidate.next).toContain('Admit or promote')
    expect(candidate.sections.find((section) => section.title === 'Admission and promote')?.answers.find((answer) => answer.label === 'promoted project')?.value).toBe('not promoted yet')
  })

  it('marks promoted ideas with related project context', () => {
    const summary = deriveIntakeIdeaOperatorSummary({
      idea_id: 'idea-src',
      project_id: 'project-promoted',
      title: 'Promoted trace',
      idea_status: 'admitted',
      queue_status: 'queued',
      source_kind: 'chatgpt_pro',
      machine_target: 'cpu',
    })
    expect(summary.context).toContain('Promoted to project')
    expect(summary.sections.find((section) => section.title === 'Admission and promote')?.answers.find((answer) => answer.label === 'promoted project')?.value).toBe('project-promoted')
  })
})

describe('deriveResearchCandidateOperatorSummary', () => {
  it('answers admission, promote path, and lane questions for admitted candidates', () => {
    const summary = deriveResearchCandidateOperatorSummary({
      candidate_id: 'cand-1',
      title: 'Routed candidate',
      status: 'admitted',
      admission_decision: 'admitted',
      machine_target: 'gb10',
      admitted_idea_id: 'idea-9',
      operator_stage_label: 'Ready to promote',
      operator_next_step: 'Dry-run promote before queueing.',
      updated_at: '2026-05-21T08:20:00Z',
    })

    expect(summary.state).toBe('Ready to promote')
    expect(summary.next).toBe('Dry-run promote before queueing.')
    expect(summary.sections.some((section) => section.title === 'Source and lineage')).toBe(true)
    expect(summary.sections.some((section) => section.title === 'Admission and promote')).toBe(true)
    expect(summary.sections.some((section) => section.title === 'Lane and dispatch')).toBe(true)
    const promote = summary.sections.find((section) => section.title === 'Admission and promote')
    expect(promote?.answers.find((answer) => answer.label === 'promote path')?.value).toContain('idea-9')
  })

  it('explains rejected candidates without promote action', () => {
    const summary = deriveResearchCandidateOperatorSummary({
      candidate_id: 'cand-reject',
      status: 'rejected',
      admission_decision: 'reject',
      machine_target: 'cpu',
    })

    expect(summary.next).toContain('negative evidence')
    expect(summary.actionNeeded).toContain('rejected')
    expect(summary.sections.find((section) => section.title === 'Admission and promote')?.answers.find((answer) => answer.label === 'promote path')?.value).toContain('rejected')
  })
})
