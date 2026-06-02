import { describe, expect, it } from 'vitest'
import {
  deriveEventsEmpty,
  deriveQueueEmpty,
  deriveResourceErrorCopy,
  deriveRunsEmpty,
} from './resourceStatePresentation'

describe('resourceStatePresentation', () => {
  it('maps queue endpoint failures to dispatch-aware guidance', () => {
    const copy = deriveResourceErrorCopy('queue', new Error('GET /control/api/v1/queue -> 500'))

    expect(copy.title).toBe('Queue could not load')
    expect(copy.dispatchImpact).toContain('dispatch')
    expect(copy.logCommand).toContain('enoch-control-plane.service')
    expect(copy.nextSteps.length).toBeGreaterThan(0)
  })

  it('distinguishes idle queue from filtered empty states', () => {
    expect(deriveQueueEmpty({ status: 'queued' }).kind).toBe('idle')
    expect(deriveQueueEmpty({ status: 'queued' }).title).toBe('No queued work right now')
    expect(deriveQueueEmpty({ search: 'oracle', status: 'queued' }).kind).toBe('filtered')
  })

  it('does not call the active queue slice idle when active work exists elsewhere', () => {
    const copy = deriveQueueEmpty({ status: 'active', activeCount: 2 })

    expect(copy.kind).toBe('blocked')
    expect(copy.title).toBe('Active lane work is not shown in this queue slice')
    expect(copy.body).toContain('2 active')
    expect(copy.hint).toContain('Runs')
  })

  it('marks active run slices as idle when empty', () => {
    expect(deriveRunsEmpty({ status: 'running' }).title).toBe('No active runs')
    expect(deriveRunsEmpty({ status: 'running' }).kind).toBe('idle')
  })

  it('marks filtered events as no-match rather than system idle', () => {
    expect(deriveEventsEmpty({ search: 'stalled' }).kind).toBe('filtered')
    expect(deriveEventsEmpty({}).kind).toBe('idle')
  })

  it('maps events endpoint errors without legacy fallback links', () => {
    const copy = deriveResourceErrorCopy('events', new Error('server error'))
    expect(copy.title).toBe('Events could not load')
    expect(copy.nextSteps.length).toBeGreaterThan(0)
  })
})
