import { expect, it } from 'vitest'
import { legacyDashboardHref } from './navigation'

it('maps backend hash actions to the V2-owned hashes to the React dashboard', () => {
  expect(legacyDashboardHref('#queue:queued')).toBe('/control/dashboard-v2#queue:queued')
  expect(legacyDashboardHref('papers')).toBe('/control/dashboard-v2#papers')
  expect(legacyDashboardHref('/control/dashboard-v2#events')).toBe('/control/dashboard-v2#events')
})
