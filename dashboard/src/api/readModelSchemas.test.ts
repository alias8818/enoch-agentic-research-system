import { expect, it } from 'vitest'
import {
  parseAutomationDetail,
  parseAutomationListResponse,
  parseProjectListResponse,
  parseQueueListResponse,
} from './readModelSchemas'

it('parses bounded queue list responses and rejects malformed rows', () => {
  const parsed = parseQueueListResponse({
    rows: [{ project_id: 'p-1', project_name: 'Oracle lane', status: 'queued' }],
    page: { returned: 1, has_more: false },
  })

  expect(parsed.rows?.[0]?.project_name).toBe('Oracle lane')
  expect(() => parseQueueListResponse({ rows: 'bad' })).toThrow()
})

it('parses project and automation list responses', () => {
  expect(parseProjectListResponse({ rows: [{ project_id: 'p-1' }] }).rows?.[0]?.project_id).toBe('p-1')
  expect(parseAutomationListResponse({ rows: [{ paper_id: 'paper-1', rank_score: 91 }] }).rows?.[0]?.rank_score).toBe(91)
})

it('parses automation detail payloads', () => {
  const parsed = parseAutomationDetail({
    item: { paper_id: 'paper-1', review_status: 'triage_ready' },
    checklist: { items: [{ item_id: 'evidence', status: 'pending' }] },
  })

  expect(parsed.item?.paper_id).toBe('paper-1')
  expect(parsed.checklist?.items?.[0]?.item_id).toBe('evidence')
})
