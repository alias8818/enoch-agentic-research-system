import { expect, it } from 'vitest'
import { dashboardV2Href, parseDashboardRoute } from './routes'

it('parses V2-owned command-center routes', () => {
  expect(parseDashboardRoute('#project:project-1')).toEqual({ page: 'detail', kind: 'project', id: 'project-1', hash: '#project:project-1' })
  expect(parseDashboardRoute('#run:run%2F1')).toEqual({ page: 'detail', kind: 'run', id: 'run/1', hash: '#run:run%2F1' })
  expect(parseDashboardRoute('#paper:paper-1')).toEqual({ page: 'detail', kind: 'paper', id: 'paper-1', hash: '#paper:paper-1' })
  expect(parseDashboardRoute('#projects?status=testing')).toEqual({ page: 'projects', status: 'testing', hash: '#projects?status=testing' })
  expect(parseDashboardRoute('#queue:queued')).toEqual({ page: 'queue', status: 'queued', hash: '#queue:queued' })
  expect(parseDashboardRoute('#runs:running')).toEqual({ page: 'runs', state: 'running', hash: '#runs:running' })
  expect(parseDashboardRoute('#runs?state=awaiting_wake')).toEqual({ page: 'runs', state: 'awaiting_wake', hash: '#runs?state=awaiting_wake' })
  expect(parseDashboardRoute('#papers?status=publication_draft')).toEqual({ page: 'papers', status: 'publication_draft', hash: '#papers?status=publication_draft' })
  expect(parseDashboardRoute('#events')).toEqual({ page: 'events', hash: '#events' })
  expect(parseDashboardRoute('#observability')).toEqual({ page: 'observability', hash: '#observability' })
  expect(parseDashboardRoute('#corpus')).toEqual({ page: 'corpus', hash: '#corpus' })
  expect(parseDashboardRoute('#research')).toEqual({ page: 'research', hash: '#research' })
  expect(parseDashboardRoute('#automation')).toEqual({ page: 'automation', paperId: '', hash: '#automation' })
  expect(parseDashboardRoute('#automation:paper%2F1')).toEqual({ page: 'automation', paperId: 'paper/1', hash: '#automation:paper%2F1' })
})

it('keeps unimplemented hashes on the legacy dashboard', () => {
  expect(dashboardV2Href('#project:project-1')).toBe('/control/dashboard-v2#project:project-1')
  expect(dashboardV2Href('#run:run-1')).toBe('/control/dashboard-v2#run:run-1')
  expect(dashboardV2Href('#paper:paper-1')).toBe('/control/dashboard-v2#paper:paper-1')
  expect(dashboardV2Href('#projects')).toBe('/control/dashboard-v2#projects')
  expect(dashboardV2Href('#queue:queued')).toBe('/control/dashboard-v2#queue:queued')
  expect(dashboardV2Href('#runs')).toBe('/control/dashboard-v2#runs')
  expect(dashboardV2Href('#papers?status=publication_draft')).toBe('/control/dashboard-v2#papers?status=publication_draft')
  expect(dashboardV2Href('#research')).toBe('/control/dashboard-v2#research')
  expect(dashboardV2Href('#automation')).toBe('/control/dashboard-v2#automation')
  expect(dashboardV2Href('#automation:paper-1')).toBe('/control/dashboard-v2#automation:paper-1')
  expect(dashboardV2Href('#observability')).toBe('/control/dashboard-v2#observability')
  expect(dashboardV2Href('#corpus')).toBe('/control/dashboard-v2#corpus')
})
