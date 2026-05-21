import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { MovementDiagnosis } from './MovementDiagnosis'
import { resolveMovementPanelCopy } from './movementPanelCopy'
import type { MovementDiagnosis as MovementDiagnosisType } from '../types'

describe('resolveMovementPanelCopy', () => {
  it('uses an active-work title when movement status is ready', () => {
    const copy = resolveMovementPanelCopy({
      status: 'ready',
      primary_reason: 'Configured worker lanes are occupied by active runs.',
      blockers: [
        {
          kind: 'lane_active',
          title: 'CPU lane is running',
          summary: 'CPU lane is occupied by active work.',
        },
      ],
    })

    expect(copy.title).toBe('What is moving now?')
  })

  it('uses an actionable title when movement status is actionable', () => {
    const copy = resolveMovementPanelCopy({
      status: 'actionable',
      primary_reason: 'GB10 lane can dispatch queued work.',
      blockers: [
        {
          kind: 'dispatch_available',
          title: 'GB10 lane can dispatch',
          summary: 'GB10 lane can dispatch queued work.',
        },
      ],
    })

    expect(copy.title).toBe('What can I do next?')
  })

  it('uses a blocked title when movement status is blocked', () => {
    const copy = resolveMovementPanelCopy({
      status: 'blocked',
      primary_reason: 'Queue is paused.',
      blockers: [
        {
          kind: 'queue_paused',
          title: 'Queue is paused',
          summary: 'Queued work will not dispatch until the queue is resumed.',
        },
      ],
    })

    expect(copy.title).toBe('Why no work is moving?')
  })
})

describe('MovementDiagnosis', () => {
  function renderDiagnosis(diagnosis: MovementDiagnosisType) {
    render(<MovementDiagnosis diagnosis={diagnosis} />)
    return resolveMovementPanelCopy(diagnosis)
  }

  it('renders active-work copy for ready movement diagnosis', () => {
    const copy = renderDiagnosis({
      status: 'ready',
      primary_reason: 'CPU lane is occupied by active work.',
      blockers: [
        {
          kind: 'lane_active',
          title: 'CPU lane is running',
          summary: 'CPU lane is occupied by active work.',
        },
      ],
    })

    expect(screen.getByRole('heading', { level: 2, name: copy.title })).toBeInTheDocument()
    expect(screen.getByLabelText(copy.title)).toBeInTheDocument()
    expect(screen.getByText(copy.subtitle)).toBeInTheDocument()
    expect(screen.getByText('CPU lane is running')).toBeInTheDocument()
  })

  it('renders actionable copy for dispatch-available movement diagnosis', () => {
    const copy = renderDiagnosis({
      status: 'actionable',
      primary_reason: 'GB10 lane can dispatch queued work.',
      blockers: [
        {
          kind: 'dispatch_available',
          title: 'GB10 lane can dispatch',
          summary: 'GB10 lane can dispatch queued work.',
          action_hash: '#queue:queued',
        },
      ],
    })

    expect(screen.getByRole('heading', { level: 2, name: copy.title })).toBeInTheDocument()
    expect(screen.getByLabelText(copy.title)).toBeInTheDocument()
    expect(screen.getByText('GB10 lane can dispatch')).toBeInTheDocument()
  })

  it('renders blocked copy for hard-blocker movement diagnosis', () => {
    const copy = renderDiagnosis({
      status: 'blocked',
      primary_reason: 'Queue is paused.',
      blockers: [
        {
          kind: 'queue_paused',
          title: 'Queue is paused',
          summary: 'Queued work will not dispatch until the queue is resumed.',
        },
      ],
    })

    expect(screen.getByRole('heading', { level: 2, name: copy.title })).toBeInTheDocument()
    expect(screen.getByLabelText(copy.title)).toBeInTheDocument()
    expect(screen.getByText('Queue is paused')).toBeInTheDocument()
  })
})
