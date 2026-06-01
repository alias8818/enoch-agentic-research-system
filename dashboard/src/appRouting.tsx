import type { ReactNode } from 'react'
import { AutomationPage } from './components/AutomationPage'
import { DetailPage } from './components/DetailPanel'
import { CorpusPage, EventsPage, IntakePage, ObservabilityPage, PapersPage, ProjectsPage, QueuePage, RunsPage } from './components/ResourcePages'
import { ResearchPage } from './components/ResearchPage'
import { SettingsPage } from './components/SettingsPage'
import { OverviewPage } from './overviewPage'
import { dashboardV2Href } from './routes'
import type { DashboardRoute } from './routes'
import { unsupportedRouteSuggestions } from './routePolicy'

function UnsupportedRoutePage({ hash }: Readonly<{ hash: string }>) {
  const suggestions = unsupportedRouteSuggestions(hash)
  return (
    <section className="legacy-card unsupported-route-card">
      <p className="eyebrow">V2 route guard</p>
      <h1>Unsupported V2 route</h1>
      <p>This hash is not owned by a React subview yet. Use a supported list or detail route below, or return to the command center.</p>
      <div className="unsupported-route-actions">
        {suggestions.map((item) => (
          <a key={item.href} className="secondary-button secondary-button--link" href={item.href}>{item.label}</a>
        ))}
        <a className="primary-button primary-button--link" href={dashboardV2Href('#overview')}>Back to command center</a>
      </div>
    </section>
  )
}

type RoutedPageRenderer = (route: DashboardRoute) => ReactNode

const ROUTED_PAGE_RENDERERS: Record<DashboardRoute['page'], RoutedPageRenderer> = {
  overview: () => <OverviewPage />,
  detail: (route) => {
    const detailRoute = route as Extract<DashboardRoute, { page: 'detail' }>
    return <DetailPage selection={{ kind: detailRoute.kind, id: detailRoute.id }} />
  },
  projects: (route) => <ProjectsPage route={route as Extract<DashboardRoute, { page: 'projects' }>} />,
  queue: (route) => <QueuePage route={route as Extract<DashboardRoute, { page: 'queue' }>} />,
  runs: (route) => <RunsPage route={route as Extract<DashboardRoute, { page: 'runs' }>} />,
  papers: (route) => <PapersPage route={route as Extract<DashboardRoute, { page: 'papers' }>} />,
  events: (route) => <EventsPage route={route as Extract<DashboardRoute, { page: 'events' }>} />,
  observability: () => <ObservabilityPage />,
  corpus: (route) => <CorpusPage route={route as Extract<DashboardRoute, { page: 'corpus' }>} />,
  research: (route) => <ResearchPage route={route as Extract<DashboardRoute, { page: 'research' }>} />,
  intake: (route) => <IntakePage route={route as Extract<DashboardRoute, { page: 'intake' }>} />,
  automation: (route) => {
    const automationRoute = route as Extract<DashboardRoute, { page: 'automation' }>
    return <AutomationPage paperId={automationRoute.paperId} search={automationRoute.search} reviewStatus={automationRoute.reviewStatus} />
  },
  settings: () => <SettingsPage />,
  unsupported: (route) => {
    const unsupportedRoute = route as Extract<DashboardRoute, { page: 'unsupported' }>
    return <UnsupportedRoutePage hash={unsupportedRoute.hash} />
  },
}

function resolveRoutedPage(route: DashboardRoute): ReactNode {
  return ROUTED_PAGE_RENDERERS[route.page](route)
}

export function RoutedPage({ route }: Readonly<{ route: DashboardRoute }>) {
  return resolveRoutedPage(route)
}
