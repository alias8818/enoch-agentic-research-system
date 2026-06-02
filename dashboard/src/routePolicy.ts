import type { DashboardRoute } from './routes'
import { dashboardV2Href } from './routes'

export type RouteSurface = 'command-center' | 'list' | 'detail' | 'debug' | 'unsupported'

export type RouteClassification = {
  surface: RouteSurface
  label: string
  parentListHash?: string
}

export type BreadcrumbItem = {
  label: string
  href?: string
}

export type DetailKind = 'project' | 'run' | 'paper' | 'event'

export const ROUTE_AUDIT: ReadonlyArray<{ hash: string; surface: RouteSurface; note: string }> = [
  { hash: '#overview', surface: 'command-center', note: 'Primary operator command center' },
  { hash: '#projects', surface: 'list', note: 'Project discovery index' },
  { hash: '#queue', surface: 'list', note: 'Queue slices with selected-row dispatch' },
  { hash: '#runs', surface: 'list', note: 'Run activity index' },
  { hash: '#papers', surface: 'list', note: 'Paper pipeline index' },
  { hash: '#events', surface: 'list', note: 'Bounded event log' },
  { hash: '#corpus', surface: 'list', note: 'Papers-owned corpus import gap list' },
  { hash: '#research', surface: 'list', note: 'Candidate generation and promotion workbench' },
  { hash: '#intake', surface: 'list', note: 'Idea intake workbench' },
  { hash: '#automation', surface: 'list', note: 'Paper action automation rows' },
  { hash: '#observability', surface: 'debug', note: 'Route/memory debug health' },
  { hash: '#project:…', surface: 'detail', note: 'Structured project detail page' },
  { hash: '#run:…', surface: 'detail', note: 'Structured run detail page' },
  { hash: '#paper:…', surface: 'detail', note: 'Structured paper detail page' },
  { hash: '#event:…', surface: 'detail', note: 'Structured event detail page' },
  { hash: '#research:…', surface: 'list', note: 'Research list with selected candidate panel' },
  { hash: '#intake:…', surface: 'list', note: 'Intake list with selected idea panel' },
  { hash: '#automation:…', surface: 'list', note: 'Automation list with selected paper panel' },
]

const DETAIL_ROUTE_META: Readonly<Record<DetailKind, { listHash: string; listLabel: string; parentPage: DashboardRoute['page'] }>> = {
  project: { listHash: '#projects', listLabel: 'Projects', parentPage: 'projects' },
  run: { listHash: '#runs', listLabel: 'Runs', parentPage: 'runs' },
  paper: { listHash: '#papers', listLabel: 'Papers', parentPage: 'papers' },
  event: { listHash: '#events', listLabel: 'Events', parentPage: 'events' },
}

export function detailListHash(kind: DetailKind): string {
  return DETAIL_ROUTE_META[kind].listHash
}

export function detailListLabel(kind: DetailKind): string {
  return DETAIL_ROUTE_META[kind].listLabel
}

export function detailParentPage(kind: DetailKind): DashboardRoute['page'] {
  return DETAIL_ROUTE_META[kind].parentPage
}

export function detailBreadcrumb(kind: DetailKind, currentLabel: string): BreadcrumbItem[] {
  return [
    { label: detailListLabel(kind), href: dashboardV2Href(detailListHash(kind)) },
    { label: currentLabel },
  ]
}

export function classifyDashboardRoute(route: DashboardRoute): RouteClassification {
  switch (route.page) {
    case 'overview':
      return { surface: 'command-center', label: 'Command center' }
    case 'projects':
      return { surface: 'list', label: 'Projects' }
    case 'queue':
      return { surface: 'list', label: 'Queue' }
    case 'runs':
      return { surface: 'list', label: 'Runs' }
    case 'papers':
      return { surface: 'list', label: 'Papers' }
    case 'events':
      return { surface: 'list', label: 'Events' }
    case 'corpus':
      return { surface: 'list', label: 'Paper corpus import' }
    case 'research':
      return { surface: 'list', label: 'Candidate generation' }
    case 'intake':
      return { surface: 'list', label: 'Idea intake' }
    case 'automation':
      return { surface: 'list', label: 'Paper actions' }
    case 'observability':
      return { surface: 'debug', label: 'Observability' }
    case 'detail':
      return {
        surface: 'detail',
        label: `${route.kind} detail`,
        parentListHash: detailListHash(route.kind),
      }
    case 'unsupported':
      return { surface: 'unsupported', label: 'Unsupported route' }
    default:
      return { surface: 'unsupported', label: 'Unsupported route' }
  }
}

export function unsupportedRouteSuggestions(hash: string): { label: string; href: string }[] {
  const suggestions = [
    { label: 'Projects', href: dashboardV2Href('#projects') },
    { label: 'Queue', href: dashboardV2Href('#queue:queued') },
  ]
  if (hash.includes('paper') || hash.includes('review')) {
    return [{ label: 'Papers', href: dashboardV2Href('#papers') }, { label: 'Paper actions', href: dashboardV2Href('#automation') }, ...suggestions]
  }
  if (hash.includes('run')) {
    return [{ label: 'Runs', href: dashboardV2Href('#runs') }, ...suggestions]
  }
  if (hash.includes('event')) {
    return [{ label: 'Events', href: dashboardV2Href('#events') }, ...suggestions]
  }
  return suggestions
}
