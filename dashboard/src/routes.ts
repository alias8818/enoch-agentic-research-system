export type DashboardRoute =
  | { page: 'overview'; hash: '#overview' }
  | { page: 'projects'; status: string; hash: string }
  | { page: 'queue'; status: string; hash: string }
  | { page: 'runs'; state: string; hash: string }
  | { page: 'papers'; status: string; hash: string }
  | { page: 'events'; hash: string }
  | { page: 'observability'; hash: string }
  | { page: 'corpus'; hash: string }
  | { page: 'research'; hash: string }
  | { page: 'automation'; hash: string }
  | { page: 'legacy'; hash: string }

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

export function parseDashboardRoute(hashOrPath: string | undefined): DashboardRoute {
  const hash = normalizeHash(hashOrPath)
  if (hash.startsWith('#projects')) {
    return { page: 'projects', status: queryParam(hash, 'status'), hash }
  }
  if (hash.startsWith('#queue')) {
    const status = hash.includes(':') ? hash.split(':', 2)[1].split('?', 1)[0] : queryParam(hash, 'status')
    return { page: 'queue', status, hash }
  }
  if (hash.startsWith('#runs')) {
    const state = hash.includes(':') ? hash.split(':', 2)[1].split('?', 1)[0] : queryParam(hash, 'state')
    return { page: 'runs', state, hash }
  }
  if (hash.startsWith('#papers')) {
    return { page: 'papers', status: queryParam(hash, 'status'), hash }
  }
  if (hash.startsWith('#events')) return { page: 'events', hash }
  if (hash.startsWith('#observability')) return { page: 'observability', hash }
  if (hash.startsWith('#corpus')) return { page: 'corpus', hash }
  if (hash.startsWith('#research')) return { page: 'research', hash }
  if (hash.startsWith('#automation')) return { page: 'automation', hash }
  if (hash === '#overview' || hash === '#') return { page: 'overview', hash: '#overview' }
  return { page: 'legacy', hash }
}

export function dashboardV2Href(hashOrPath: string | undefined, fallbackHash = '#overview'): string {
  const route = parseDashboardRoute(hashOrPath || fallbackHash)
  if (route.page === 'legacy') return `${LEGACY_DASHBOARD_PATH}${route.hash}`
  return `${DASHBOARD_V2_PATH}${route.hash}`
}
