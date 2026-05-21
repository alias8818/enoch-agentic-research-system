import { expect, it } from 'vitest'
import { dashboardHref } from './navigation'

it('maps backend hash actions to the V2-owned hashes to the React dashboard', () => {
  expect(dashboardHref('#queue:queued')).toBe('/control/dashboard-v2#queue:queued')
  expect(dashboardHref('papers')).toBe('/control/dashboard-v2#papers')
  expect(dashboardHref('/control/dashboard-v2#events')).toBe('/control/dashboard-v2#events')
})
