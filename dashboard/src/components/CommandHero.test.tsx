import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import type { AutomationReadiness, MovementDiagnosis, OverviewResponse } from '../types'
import { CommandHero } from './CommandHero'
import { PaperMiniStrip } from './PaperMiniStrip'

const overview: OverviewResponse = {
  ok: true,
  counts: { active: 1, queued: 2 },
  paper_counts: { publication_draft: 1 },
}

const readyReadiness: AutomationReadiness = {
  ok: true,
  label: 'Long-haul mode: READY',
  blockers: [],
}

const failedReadiness: AutomationReadiness = {
  ok: false,
  label: 'Long-haul mode: BLOCKED — queued/active state inconsistent',
  blockers: ['queue_counts_consistent: blocked'],
}

function renderHero(
  diagnosis: MovementDiagnosis,
  readinessState: {
    readiness?: AutomationReadiness
    readinessRequested?: boolean
    readinessLoading?: boolean
    requiresReadinessCheck?: boolean
  } = {},
) {
  render(
    <CommandHero
      overview={overview}
      diagnosis={diagnosis}
      requiresReadinessCheck
      {...readinessState}
    />,
  )
  return screen.getByLabelText('Can I leave this running?')
}

afterEach(() => {
  cleanup()
})

describe('CommandHero state strip', () => {
  it('shows only active and queued counts; paper counts belong in PaperMiniStrip', () => {
    render(
      <>
        <CommandHero
          overview={{
            ok: true,
            counts: { active: 3, queued: 14 },
            paper_counts: { publication_draft: 9, draft_review: 2 },
          }}
          diagnosis={{ status: 'ready', primary_reason: 'No movement blockers.', blockers: [] }}
        />
        <PaperMiniStrip pipeline={{ write_needed: 9, finalize_needed: 4, publish_ready: 1 }} />
      </>,
    )

    const strip = screen.getByLabelText('Current command state')
    expect(strip).toHaveTextContent('active')
    expect(strip).toHaveTextContent('3')
    expect(strip).toHaveTextContent('queued')
    expect(strip).toHaveTextContent('14')
    expect(strip).not.toHaveTextContent('drafts')
    expect(screen.getByRole('heading', { level: 2, name: 'Write → Finalize → Publish' })).toBeInTheDocument()
    expect(screen.getByText('Write').closest('a')).toHaveTextContent('9')
    expect(screen.getByText('Finalize').closest('button')).toHaveTextContent('4')
    expect(screen.getByText('Publish').closest('a')).toHaveTextContent('1')
  })
})

describe('CommandHero readiness × movement matrix', () => {
  it('shows Check readiness first when readiness is unchecked and movement is ready', () => {
    const hero = renderHero({
      status: 'ready',
      primary_reason: 'No movement blockers.',
      blockers: [],
    })

    expect(hero).toHaveClass('command-hero--actionable')
    expect(hero).not.toHaveClass('command-hero--blocked')
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Check readiness first')
    expect(screen.queryByText('Not yet')).not.toBeInTheDocument()
  })

  it('shows healthy active-work copy when readiness passed and lanes are active', () => {
    const hero = renderHero(
      {
        status: 'ready',
        primary_reason: 'Configured worker lanes are occupied by active runs; this is normal while queued backlog waits.',
        blockers: [
          { kind: 'lane_active', title: 'CPU lane is running', summary: 'CPU lane is occupied by Active CPU.' },
          { kind: 'lane_active', title: 'GB10 lane is running', summary: 'GB10 lane is occupied by Active GB10.' },
          { kind: 'followup_ready', title: 'Bounded follow-up is ready', summary: 'A preserved signal has enough bounded evidence to queue the next investigation.' },
        ],
      },
      { readiness: readyReadiness, readinessRequested: true },
    )

    expect(hero).toHaveClass('command-hero--ready')
    expect(hero).not.toHaveClass('command-hero--blocked')
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Yes — active work is running')
    expect(screen.queryByText('Not yet')).not.toBeInTheDocument()
  })

  it('shows Action available when readiness passed and dispatch is available', () => {
    const hero = renderHero(
      {
        status: 'actionable',
        primary_reason: 'GB10 lane can dispatch queued work.',
        blockers: [
          { kind: 'lane_active', title: 'CPU lane is running', summary: 'CPU lane is occupied by Active CPU.' },
          { kind: 'dispatch_available', title: 'GB10 lane can dispatch', summary: 'GB10 lane can dispatch queued work.' },
        ],
      },
      { readiness: readyReadiness, readinessRequested: true },
    )

    expect(hero).toHaveClass('command-hero--actionable')
    expect(hero).not.toHaveClass('command-hero--blocked')
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Action available')
  })

  it('shows Not yet when readiness failed', () => {
    const hero = renderHero(
      {
        status: 'ready',
        primary_reason: 'No movement blockers.',
        blockers: [],
      },
      { readiness: failedReadiness, readinessRequested: true },
    )

    expect(hero).toHaveClass('command-hero--blocked')
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Not yet')
    expect(screen.getByText('queue_counts_consistent: blocked')).toBeInTheDocument()
  })
})
