import { expect, it } from 'vitest'
import { legacyDashboardHref } from './navigation'

it('maps backend hash actions to the legacy dashboard path', () => {
  expect(legacyDashboardHref('#queue:queued')).toBe('/control/dashboard#queue:queued')
  expect(legacyDashboardHref('papers')).toBe('/control/dashboard#papers')
  expect(legacyDashboardHref('/control/dashboard-v2#events')).toBe('/control/dashboard#events')
})
