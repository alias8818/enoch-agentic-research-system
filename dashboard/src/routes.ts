export type DashboardRoute =
  | { page: 'overview'; hash: '#overview' }
  | { page: 'detail'; kind: 'project' | 'run' | 'paper' | 'event'; id: string; hash: string }
  | { page: 'projects'; status: string; search: string; hash: string }
  | { page: 'queue'; status: string; search: string; hash: string }
  | { page: 'runs'; state: string; search: string; hash: string }
  | { page: 'papers'; status: string; search: string; hash: string }
  | { page: 'events'; eventType: string; search: string; hash: string }
  | { page: 'observability'; hash: string }
  | { page: 'corpus'; status: string; search: string; hash: string }
  | { page: 'research'; candidateId: string; hash: string }
  | { page: 'intake'; ideaId: string; hash: string }
  | { page: 'automation'; paperId: string; search: string; reviewStatus: string; hash: string }
  | { page: 'settings'; hash: string }
  | { page: 'unsupported'; hash: string }

export const DASHBOARD_V2_PATH = '/control/dashboard-v2'
export const LEGACY_DASHBOARD_PATH = '/control/dashboard'

function normalizeHash(hashOrPath: string | undefined, fallback = '#overview'): string {
  const value = (hashOrPath || fallback).trim() || fallback
  if (value.startsWith('/control/dashboard-v2')) return value.slice(DASHBOARD_V2_PATH.length) || fallback
  if (value.startsWith('/control/dashboard')) return value.slice(LEGACY_DASHBOARD_PATH.length) || fallback
  if (value.startsWith('#')) return value
  if (value.startsWith('/')) return value
  return `#${value}`
}

function queryParam(hash: string, name: string): string {
  const [, query = ''] = hash.split('?', 2)
  return new URLSearchParams(query).get(name) || ''
}

function detailId(hash: string, prefix: string): string {
  const raw = hash.slice(prefix.length).split('?', 1)[0]
  try {
    return decodeURIComponent(raw)
  } catch {
    return raw
  }
}

function hashPathSegment(hash: string, queryParamName: string): string {
  if (hash.includes(':')) return hash.split(':', 2)[1].split('?', 1)[0]
  return queryParam(hash, queryParamName)
}

function parseDetailRoute(
  hash: string,
  prefix: string,
  kind: 'project' | 'run' | 'paper' | 'event',
): DashboardRoute {
  return { page: 'detail', kind, id: detailId(hash, prefix), hash }
}

function parseFilteredListRoute(
  hash: string,
  page: 'projects' | 'papers' | 'corpus',
): DashboardRoute {
  return { page, status: queryParam(hash, 'status'), search: queryParam(hash, 'search'), hash }
}

function parseAutomationRoute(hash: string, paperPrefix: string): DashboardRoute {
  return {
    page: 'automation',
    paperId: paperPrefix ? detailId(hash, paperPrefix) : '',
    search: queryParam(hash, 'search'),
    reviewStatus: queryParam(hash, 'review_status'),
    hash,
  }
}

type RouteParser = (hash: string) => DashboardRoute | null

const ROUTE_PARSERS: RouteParser[] = [
  (hash) => (hash.startsWith('#project:') ? parseDetailRoute(hash, '#project:', 'project') : null),
  (hash) => (hash.startsWith('#run:') ? parseDetailRoute(hash, '#run:', 'run') : null),
  (hash) => (hash.startsWith('#paper:') ? parseDetailRoute(hash, '#paper:', 'paper') : null),
  (hash) => (hash.startsWith('#event:') ? parseDetailRoute(hash, '#event:', 'event') : null),
  (hash) => (hash.startsWith('#projects') ? parseFilteredListRoute(hash, 'projects') : null),
  (hash) => (hash.startsWith('#queue')
    ? { page: 'queue', status: hashPathSegment(hash, 'status'), search: queryParam(hash, 'search'), hash }
    : null),
  (hash) => (hash.startsWith('#runs')
    ? { page: 'runs', state: hashPathSegment(hash, 'state'), search: queryParam(hash, 'search'), hash }
    : null),
  (hash) => (hash.startsWith('#papers') ? parseFilteredListRoute(hash, 'papers') : null),
  (hash) => (hash.startsWith('#events')
    ? { page: 'events', eventType: queryParam(hash, 'event_type'), search: queryParam(hash, 'search'), hash }
    : null),
  (hash) => (hash.startsWith('#observability') ? { page: 'observability', hash } : null),
  (hash) => (hash.startsWith('#corpus') ? parseFilteredListRoute(hash, 'corpus') : null),
  (hash) => (hash.startsWith('#candidate:')
    ? { page: 'research', candidateId: detailId(hash, '#candidate:'), hash }
    : null),
  (hash) => (hash.startsWith('#research:')
    ? { page: 'research', candidateId: detailId(hash, '#research:'), hash }
    : null),
  (hash) => (hash.startsWith('#research') ? { page: 'research', candidateId: '', hash } : null),
  (hash) => (hash.startsWith('#idea:') ? { page: 'intake', ideaId: detailId(hash, '#idea:'), hash } : null),
  (hash) => (hash.startsWith('#intake:') ? { page: 'intake', ideaId: detailId(hash, '#intake:'), hash } : null),
  (hash) => (hash.startsWith('#intake') ? { page: 'intake', ideaId: '', hash } : null),
  (hash) => (hash.startsWith('#automation:') ? parseAutomationRoute(hash, '#automation:') : null),
  (hash) => (hash.startsWith('#review:') ? parseAutomationRoute(hash, '#review:') : null),
  (hash) => (hash.startsWith('#automation') || hash.startsWith('#reviews') ? parseAutomationRoute(hash, '') : null),
  (hash) => (hash.startsWith('#settings') ? { page: 'settings', hash } : null),
]

export function canonicalDashboardHash(hashOrPath: string | undefined, fallback = '#overview'): string {
  let hash = normalizeHash(hashOrPath, fallback)

  if (hash.startsWith('#review:')) hash = `#automation:${hash.slice('#review:'.length)}`
  else if (hash === '#reviews' || hash.startsWith('#reviews?')) hash = `#automation${hash.slice('#reviews'.length)}`
  else if (hash.startsWith('#candidate:')) hash = `#research:${hash.slice('#candidate:'.length)}`
  else if (hash.startsWith('#idea:')) hash = `#intake:${hash.slice('#idea:'.length)}`
  else if (hash === '#status' || hash.startsWith('#status?')) hash = '#overview'
  else if (hash.startsWith('#dispatch')) hash = '#queue:queued'
  else if (hash.startsWith('#workers')) hash = '#overview'

  return hash
}

export function parseDashboardRoute(hashOrPath: string | undefined): DashboardRoute {
  const hash = normalizeHash(hashOrPath)
  for (const parse of ROUTE_PARSERS) {
    const route = parse(hash)
    if (route) return route
  }
  if (hash === '#overview' || hash === '#') return { page: 'overview', hash: '#overview' }
  return { page: 'unsupported', hash }
}

export function dashboardV2Href(hashOrPath: string | undefined, fallbackHash = '#overview'): string {
  const hash = canonicalDashboardHash(hashOrPath || fallbackHash, fallbackHash)
  return `${DASHBOARD_V2_PATH}${hash}`
}

export function dashboardRouteTitle(route: DashboardRoute): string {
  switch (route.page) {
    case 'overview':
      return 'Command center'
    case 'projects':
      return 'Projects'
    case 'queue':
      return 'Queue'
    case 'runs':
      return 'Runs'
    case 'papers':
      return 'Papers'
    case 'events':
      return 'Events'
    case 'observability':
      return 'Observability'
    case 'corpus':
      return 'Paper corpus import'
    case 'research':
      return 'Candidate generation'
    case 'intake':
      return 'Idea intake'
    case 'automation':
      return 'Paper actions'
    case 'settings':
      return 'Settings'
    case 'detail':
      return `${route.kind[0].toUpperCase()}${route.kind.slice(1)} detail`
    case 'unsupported':
      return 'Unsupported route'
    default:
      return 'Dashboard'
  }
}
