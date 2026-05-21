import { describe, expect, it } from 'vitest'
import { deriveDetailOperatorSummary, deriveIntakeIdeaOperatorSummary } from './detailOperatorSummary'

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

  it('answers run operator questions with project link and timestamps', () => {
    const summary = deriveDetailOperatorSummary('run', {
      run_id: 'run-1',
      run: {
        run_id: 'run-1',
        project_id: 'project-1',
        project_name: 'Trace oracle',
        state: 'running',
        gate_state: 'awaiting_wake',
        current_activity: 'testing',
        started_at: '2026-05-21T09:00:00Z',
        updated_at: '2026-05-21T10:00:00Z',
        related_artifact_paths_present: { evidence_bundle: true, claim_ledger: false },
      },
      events: [{ summary: 'Wake callback pending', created_at: '2026-05-21T10:01:00Z' }],
    })

    expect(summary.state).toBe('running')
    expect(summary.next).toContain('Watch activity')
    expect(summary.entityLinks[0]).toMatchObject({ kind: 'project', id: 'project-1' })
    expect(summary.sections.flatMap((section) => section.answers)).toEqual(expect.arrayContaining([
      expect.objectContaining({ label: 'gate', value: 'awaiting_wake' }),
      expect.objectContaining({ label: 'evidence bundle', value: 'present' }),
    ]))
    expect(summary.recentActivity).toContain('Wake callback pending')
  })

  it('answers paper operator questions with checklist and related links', () => {
    const summary = deriveDetailOperatorSummary('paper', {
      paper_id: 'paper-1',
      paper: {
        paper_id: 'paper-1',
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
    })

    expect(summary.state).toBe('publication_draft')
    expect(summary.next).toContain('Preview artifacts')
    expect(summary.entityLinks).toEqual(expect.arrayContaining([
      expect.objectContaining({ kind: 'project', id: 'project-1' }),
      expect.objectContaining({ kind: 'run', id: 'run-1' }),
    ]))
    expect(summary.sections.some((section) => section.title === 'Publication checklist')).toBe(true)
  })

  it('answers event operator questions with entity links', () => {
    const summary = deriveDetailOperatorSummary('event', {
      id: 9,
      event_type: 'Queue Alert',
      project_id: 'project-1',
      summary: 'Lane blocked on gb10',
      created_at: '2026-05-21T10:00:00Z',
    })

    expect(summary.state).toBe('Queue Alert')
    expect(summary.entityLinks[0]).toMatchObject({ kind: 'project', id: 'project-1' })
    expect(summary.sections[0].answers).toEqual(expect.arrayContaining([
      expect.objectContaining({ label: 'summary', value: 'Lane blocked on gb10' }),
    ]))
  })
})

describe('deriveIntakeIdeaOperatorSummary', () => {
  it('answers intake admission and queue questions', () => {
    const summary = deriveIntakeIdeaOperatorSummary({
      idea_id: 'idea-1',
      project_id: 'project-1',
      title: 'New oracle trace',
      idea_status: 'admitted',
      queue_status: 'queued',
      paper_status: 'none',
      source_kind: 'supabase_idea',
      next_action_hint: 'Dispatch dry-run recommended',
    })

    expect(summary.state).toBe('admitted')
    expect(summary.next).toContain('dry-run')
    expect(summary.entityLinks[0]).toMatchObject({ kind: 'project', id: 'project-1' })
    expect(summary.sections.some((section) => section.title === 'Admission and queue')).toBe(true)
  })
})
