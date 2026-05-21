import { describe, expect, it } from 'vitest'
import {
  eventsTableColumns,
  formatAgeLabel,
  paperEvidenceAvailability,
  projectsTableColumns,
  queueDispatchReadiness,
  resolveColumnValue,
} from './tablePresentation'

describe('tablePresentation', () => {
  it('prioritizes project name before id in projects table', () => {
    const row = { project_id: 'project-1', project_name: 'Trace oracle', queue_status: 'queued', age_seconds: 125 }
    expect(resolveColumnValue(row, projectsTableColumns[0])).toBe('Trace oracle')
    expect(projectsTableColumns[0].kind).toBe('primary')
    expect(projectsTableColumns[1].kind).toBe('id')
  })

  it('formats age_seconds into operator-friendly labels', () => {
    expect(formatAgeLabel({ age_seconds: 45 })).toBe('45s ago')
    expect(formatAgeLabel({ age_seconds: 7200 })).toBe('2h ago')
  })

  it('derives queue dispatch readiness from blocked and queued state', () => {
    expect(queueDispatchReadiness({ status: 'queued' }).tone).toBe('ready')
    expect(queueDispatchReadiness({ status: 'queued', blocked_reason: 'lane busy' }).tone).toBe('blocked')
  })

  it('derives paper evidence availability from artifact flags', () => {
    expect(paperEvidenceAvailability({
      artifact_paths_present: { evidence_bundle: true, claim_ledger: true, manifest: true },
    })).toBe('complete')
    expect(paperEvidenceAvailability({ artifact_paths_present: { evidence_bundle: true } })).toBe('partial')
  })

  it('orders event columns with summary before entity link', () => {
    expect(eventsTableColumns.map((column) => column.key)).toEqual(['event_type', 'summary', 'entity_link', 'created_at'])
    expect(eventsTableColumns[1].kind).toBe('primary')
  })
})
