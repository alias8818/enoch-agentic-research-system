import { describe, expect, it } from 'vitest'
import { canonicalDashboardHash, parseDashboardRoute } from './routes'
import {
  DASHBOARD_LIFECYCLE_CHAIN,
  ROUTE_CONSOLIDATION_MAP,
  ROUTE_AUDIT,
  classifyDashboardRoute,
  detailBreadcrumb,
  detailListHash,
  detailParentPage,
  unsupportedRouteSuggestions,
} from './routePolicy'

describe('routePolicy', () => {
  it('preserves the operator lifecycle chain for route consolidation work', () => {
    expect(DASHBOARD_LIFECYCLE_CHAIN.map((item) => item.label).join(' -> ')).toBe(
      'candidate -> queue row -> dispatch/run -> worker lane -> evidence/artifact -> paper/package/import -> event/alert',
    )
  })

  it('assigns each implemented top-level route to one operator job', () => {
    const mappedHashes = new Set(ROUTE_CONSOLIDATION_MAP.map((entry) => entry.hash))
    const implementedTopLevelHashes = ROUTE_AUDIT
      .filter((entry) => !entry.hash.includes(':'))
      .map((entry) => entry.hash)

    expect(new Set(implementedTopLevelHashes)).toEqual(mappedHashes)

    for (const entry of ROUTE_CONSOLIDATION_MAP) {
      expect(entry.owner, entry.hash).not.toBe('')
      expect(entry.operatorQuestion.length, entry.hash).toBeGreaterThan(20)
      expect(entry.lifecycleStages.length, entry.hash).toBeGreaterThan(0)
    }
  })

  it('defines consolidation ownership for overlapping workbench routes', () => {
    const byHash = new Map(ROUTE_CONSOLIDATION_MAP.map((entry) => [entry.hash, entry]))

    expect(byHash.get('#research')).toMatchObject({
      owner: 'Work Queue',
      parentHash: '#queue',
      decision: 'owned-subworkflow',
    })
    expect(byHash.get('#intake')).toMatchObject({
      owner: 'Work Queue',
      parentHash: '#queue',
      decision: 'owned-subworkflow',
    })
    expect(byHash.get('#corpus')).toMatchObject({
      owner: 'Papers',
      parentHash: '#papers',
      decision: 'compatibility-subworkflow',
    })
    expect(byHash.get('#automation')).toMatchObject({
      owner: 'Papers',
      parentHash: '#papers',
      decision: 'compatibility-subworkflow',
    })
  })

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

  it('labels overlapping secondary routes by operator job instead of implementation noun', () => {
    expect(classifyDashboardRoute(parseDashboardRoute('#corpus')).label).toBe('Paper corpus import')
    expect(classifyDashboardRoute(parseDashboardRoute('#research')).label).toBe('Candidate generation')
    expect(classifyDashboardRoute(parseDashboardRoute('#intake')).label).toBe('Idea intake')
    expect(classifyDashboardRoute(parseDashboardRoute('#automation')).label).toBe('Paper actions')

    expect(unsupportedRouteSuggestions('#paper:missing').map((item) => item.label)).toContain('Paper actions')
  })

  it('parents paper sub-workflow routes back to the Papers list', () => {
    expect(classifyDashboardRoute(parseDashboardRoute('#corpus')).parentListHash).toBe('#papers')
    expect(classifyDashboardRoute(parseDashboardRoute('#automation')).parentListHash).toBe('#papers')
    expect(classifyDashboardRoute(parseDashboardRoute('#papers')).parentListHash).toBeUndefined()
  })
})
