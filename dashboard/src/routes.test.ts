import { expect, it } from 'vitest'
import { dashboardV2Href, parseDashboardRoute } from './routes'

it('parses V2-owned command-center routes', () => {
  expect(parseDashboardRoute('#queue:queued')).toEqual({ page: 'queue', status: 'queued', hash: '#queue:queued' })
  expect(parseDashboardRoute('#runs:running')).toEqual({ page: 'runs', state: 'running', hash: '#runs:running' })
  expect(parseDashboardRoute('#runs?state=awaiting_wake')).toEqual({ page: 'runs', state: 'awaiting_wake', hash: '#runs?state=awaiting_wake' })
  expect(parseDashboardRoute('#papers?status=publication_draft')).toEqual({ page: 'papers', status: 'publication_draft', hash: '#papers?status=publication_draft' })
  expect(parseDashboardRoute('#events')).toEqual({ page: 'events', hash: '#events' })
  expect(parseDashboardRoute('#observability')).toEqual({ page: 'observability', hash: '#observability' })
  expect(parseDashboardRoute('#corpus')).toEqual({ page: 'corpus', hash: '#corpus' })
  expect(parseDashboardRoute('#research')).toEqual({ page: 'research', hash: '#research' })
  expect(parseDashboardRoute('#automation')).toEqual({ page: 'automation', hash: '#automation' })
})

it('keeps unimplemented hashes on the legacy dashboard', () => {
  expect(dashboardV2Href('#queue:queued')).toBe('/control/dashboard-v2#queue:queued')
  expect(dashboardV2Href('#runs')).toBe('/control/dashboard-v2#runs')
  expect(dashboardV2Href('#papers?status=publication_draft')).toBe('/control/dashboard-v2#papers?status=publication_draft')
  expect(dashboardV2Href('#research')).toBe('/control/dashboard-v2#research')
  expect(dashboardV2Href('#automation')).toBe('/control/dashboard-v2#automation')
  expect(dashboardV2Href('#observability')).toBe('/control/dashboard-v2#observability')
  expect(dashboardV2Href('#corpus')).toBe('/control/dashboard-v2#corpus')
})
