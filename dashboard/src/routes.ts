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
  | { page: 'automation'; paperId: string; hash: string }
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

export function parseDashboardRoute(hashOrPath: string | undefined): DashboardRoute {
  const hash = normalizeHash(hashOrPath)
  if (hash.startsWith('#project:')) return { page: 'detail', kind: 'project', id: detailId(hash, '#project:'), hash }
  if (hash.startsWith('#run:')) return { page: 'detail', kind: 'run', id: detailId(hash, '#run:'), hash }
  if (hash.startsWith('#paper:')) return { page: 'detail', kind: 'paper', id: detailId(hash, '#paper:'), hash }
  if (hash.startsWith('#event:')) return { page: 'detail', kind: 'event', id: detailId(hash, '#event:'), hash }
  if (hash.startsWith('#projects')) {
    return { page: 'projects', status: queryParam(hash, 'status'), search: queryParam(hash, 'search'), hash }
  }
  if (hash.startsWith('#queue')) {
    const status = hash.includes(':') ? hash.split(':', 2)[1].split('?', 1)[0] : queryParam(hash, 'status')
    return { page: 'queue', status, search: queryParam(hash, 'search'), hash }
  }
  if (hash.startsWith('#runs')) {
    const state = hash.includes(':') ? hash.split(':', 2)[1].split('?', 1)[0] : queryParam(hash, 'state')
    return { page: 'runs', state, search: queryParam(hash, 'search'), hash }
  }
  if (hash.startsWith('#papers')) {
    return { page: 'papers', status: queryParam(hash, 'status'), search: queryParam(hash, 'search'), hash }
  }
  if (hash.startsWith('#events')) return { page: 'events', eventType: queryParam(hash, 'event_type'), search: queryParam(hash, 'search'), hash }
  if (hash.startsWith('#observability')) return { page: 'observability', hash }
  if (hash.startsWith('#corpus')) return { page: 'corpus', status: queryParam(hash, 'status'), search: queryParam(hash, 'search'), hash }
  if (hash.startsWith('#candidate:')) return { page: 'research', candidateId: detailId(hash, '#candidate:'), hash }
  if (hash.startsWith('#research:')) return { page: 'research', candidateId: detailId(hash, '#research:'), hash }
  if (hash.startsWith('#research')) return { page: 'research', candidateId: '', hash }
  if (hash.startsWith('#idea:')) return { page: 'intake', ideaId: detailId(hash, '#idea:'), hash }
  if (hash.startsWith('#intake:')) return { page: 'intake', ideaId: detailId(hash, '#intake:'), hash }
  if (hash.startsWith('#intake')) return { page: 'intake', ideaId: '', hash }
  if (hash.startsWith('#automation:')) return { page: 'automation', paperId: detailId(hash, '#automation:'), hash }
  if (hash.startsWith('#review:')) return { page: 'automation', paperId: detailId(hash, '#review:'), hash }
  if (hash.startsWith('#automation') || hash.startsWith('#reviews')) return { page: 'automation', paperId: '', hash }
  if (hash === '#overview' || hash === '#') return { page: 'overview', hash: '#overview' }
  return { page: 'unsupported', hash }
}

export function dashboardV2Href(hashOrPath: string | undefined, fallbackHash = '#overview'): string {
  const route = parseDashboardRoute(hashOrPath || fallbackHash)
  return `${DASHBOARD_V2_PATH}${route.hash}`
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
      return 'Corpus import'
    case 'research':
      return 'Research Facility'
    case 'intake':
      return 'Ideas intake'
    case 'automation':
      return 'Publication automation'
    case 'detail':
      return `${route.kind[0].toUpperCase()}${route.kind.slice(1)} detail`
    case 'unsupported':
      return 'Unsupported route'
    default:
      return 'Dashboard'
  }
}
