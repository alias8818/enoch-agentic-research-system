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

  it('marks active run slices as idle when empty', () => {
    expect(deriveRunsEmpty({ status: 'running' }).title).toBe('No active runs')
    expect(deriveRunsEmpty({ status: 'running' }).kind).toBe('idle')
  })

  it('marks filtered events as no-match rather than system idle', () => {
    expect(deriveEventsEmpty({ search: 'stalled' }).kind).toBe('filtered')
    expect(deriveEventsEmpty({}).kind).toBe('idle')
  })

  it('keeps legacy events fallback on events endpoint errors', () => {
    const copy = deriveResourceErrorCopy('events', new Error('server error'))
    expect(copy.legacyLink?.href).toBe('/control/dashboard#events')
  })
})
