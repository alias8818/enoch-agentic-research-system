import { describe, expect, it } from 'vitest'
import { canonicalDashboardHash, parseDashboardRoute } from './routes'
import {
  ROUTE_AUDIT,
  classifyDashboardRoute,
  detailBreadcrumb,
  detailListHash,
  detailParentPage,
  unsupportedRouteSuggestions,
} from './routePolicy'

describe('routePolicy', () => {
  it('canonicalizes alias and legacy dead hashes to supported routes', () => {
    expect(canonicalDashboardHash('#reviews')).toBe('#automation')
    expect(canonicalDashboardHash('#reviews?search=oracle&review_status=queued')).toBe('#automation?search=oracle&review_status=queued')
    expect(canonicalDashboardHash('#review:paper-1')).toBe('#automation:paper-1')
    expect(canonicalDashboardHash('#candidate:cand-1')).toBe('#research:cand-1')
    expect(canonicalDashboardHash('#idea:idea-1')).toBe('#intake:idea-1')
    expect(canonicalDashboardHash('#status')).toBe('#overview')
    expect(canonicalDashboardHash('#dispatch-one')).toBe('#queue:queued')
  })

  it('classifies implemented routes for the audit catalog', () => {
    for (const entry of ROUTE_AUDIT) {
      if (entry.hash.endsWith('…')) continue
      const route = parseDashboardRoute(entry.hash)
      expect(classifyDashboardRoute(route).surface, entry.hash).toBe(entry.surface)
    }
  })

  it('maps detail routes back to their parent list pages', () => {
    expect(detailListHash('project')).toBe('#projects')
    expect(detailParentPage('run')).toBe('runs')
    expect(detailBreadcrumb('paper', 'Draft title')).toEqual([
      { label: 'Papers', href: '/control/dashboard-v2#papers' },
      { label: 'Draft title' },
    ])
  })

  it('does not duplicate the command center link in unsupported route suggestions', () => {
    const overviewHref = '/control/dashboard-v2#overview'
    for (const hash of ['#unknown-workflow', '#paper:missing', '#run:missing', '#event:missing']) {
      const hrefs = unsupportedRouteSuggestions(hash).map((item) => item.href)
      expect(hrefs, hash).not.toContain(overviewHref)
    }
  })
})
