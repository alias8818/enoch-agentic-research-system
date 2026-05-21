import { QueryClient, QueryClientProvider, useQuery, useQueryClient } from '@tanstack/react-query'
import { FormEvent, useEffect, useState } from 'react'
import { apiGet, getSavedToken, saveToken } from './api/client'
import { CommandHero } from './components/CommandHero'
import { MovementDiagnosis } from './components/MovementDiagnosis'
import { OverviewFreshness } from './components/OverviewFreshness'
import { PaperMiniStrip } from './components/PaperMiniStrip'
import { PrimaryAction } from './components/PrimaryAction'
import { SafetyBar } from './components/SafetyBar'
import { AutomationPage } from './components/AutomationPage'
import { DetailPage } from './components/DetailPanel'
import { CorpusPage, EventsPage, IntakePage, ObservabilityPage, PapersPage, ProjectsPage, QueuePage, RunsPage } from './components/ResourcePages'
import { ResearchPage } from './components/ResearchPage'
import { WorkerLanes } from './components/WorkerLanes'
import { dashboardV2Href, parseDashboardRoute } from './routes'
import type { DashboardRoute } from './routes'
import type { OverviewResponse, StatusResponse } from './types'

const queryClient = new QueryClient()

function TokenGate({ onSave }: { onSave: () => void }) {
  const [token, setToken] = useState(getSavedToken())
  function submit(event: FormEvent) {
    event.preventDefault()
    saveToken(token)
    onSave()
  }
  return (
    <main className="auth-frame">
      <section className="auth-card">
        <p className="eyebrow">Enoch Dashboard V2</p>
        <h1>Bearer token required</h1>
        <p>The React dashboard does not call authenticated APIs until a token is saved locally in this browser.</p>
        <form className="auth-form" onSubmit={submit}>
          <input type="password" value={token} onChange={(event) => setToken(event.target.value)} placeholder="Bearer token" aria-label="Bearer token" />
          <button className="primary-button" type="submit">Save token</button>
        </form>
        <a className="text-link" href="/control/dashboard">Open legacy dashboard</a>
      </section>
    </main>
  )
}

function OverviewPage() {
  const queryClient = useQueryClient()
  const overview = useQuery({ queryKey: ['overview'], queryFn: () => apiGet<OverviewResponse>('/control/api/v1/overview?active_limit=8&event_limit=6'), refetchInterval: 30_000 })
  const status = useQuery({ queryKey: ['status'], queryFn: () => apiGet<StatusResponse>('/control/api/status'), refetchInterval: 30_000 })
  const refresh = () => {
    void overview.refetch()
    void status.refetch()
    void queryClient.invalidateQueries({ predicate: (query) => query.queryKey[0] !== 'overview' && query.queryKey[0] !== 'status' })
  }

  if (overview.isLoading) {
    return <div className="rounded-3xl border border-zinc-800 bg-zinc-950 p-8 text-zinc-300">Loading command center…</div>
  }
  if (overview.isError || !overview.data) {
    return <div className="rounded-3xl border border-red-900 bg-red-950/40 p-8 text-red-100">Command state unavailable: {String(overview.error?.message || 'unknown error')}</div>
  }

  const data = overview.data
  const diagnosis = data.movement_diagnosis || { status: 'unknown', primary_reason: 'No movement diagnosis returned.', blockers: [] }
  return (
    <div className="command-stack">
      <div className="command-topline">
        <OverviewFreshness generatedAt={data.generated_at} laneGeneratedAt={status.data?.generated_at} isFetching={overview.isFetching || status.isFetching} onRefresh={refresh} />
        <SafetyBar flags={data.flags} onRefresh={refresh} />
      </div>
      <CommandHero overview={data} diagnosis={diagnosis} />
      <div className="command-grid">
        <WorkerLanes lanes={status.data?.worker_lanes || []} onRefresh={refresh} />
        <div className="side-rail">
          <PrimaryAction action={data.top_actions?.[0]} onRefresh={refresh} />
          <PaperMiniStrip pipeline={data.paper_pipeline} onRefresh={refresh} />
        </div>
      </div>
      <MovementDiagnosis diagnosis={diagnosis} />
      <details className="secondary-fold">
        <summary>Show secondary details</summary>
        <div>
          <a href={dashboardV2Href('#runs')}>Runs</a>
          <a href={dashboardV2Href('#papers')}>Papers</a>
          <a href={dashboardV2Href('#events')}>Recent activity</a>
        </div>
      </details>
    </div>
  )
}

function currentRoute(): DashboardRoute {
  return parseDashboardRoute(window.location.hash || '#overview')
}

function RoutedPage({ route }: { route: DashboardRoute }) {
  if (route.page === 'detail') return <DetailPage selection={{ kind: route.kind, id: route.id }} />
  if (route.page === 'projects') return <ProjectsPage route={route} />
  if (route.page === 'queue') return <QueuePage route={route} />
  if (route.page === 'runs') return <RunsPage route={route} />
  if (route.page === 'papers') return <PapersPage route={route} />
  if (route.page === 'events') return <EventsPage />
  if (route.page === 'observability') return <ObservabilityPage />
  if (route.page === 'corpus') return <CorpusPage />
  if (route.page === 'research') return <ResearchPage />
  if (route.page === 'intake') return <IntakePage />
  if (route.page === 'automation') return <AutomationPage paperId={route.paperId} />
  if (route.page === 'legacy') {
    return (
      <section className="legacy-card">
        <p className="eyebrow">Legacy fallback</p>
        <h1>This V2 page is not implemented yet</h1>
        <p>Use the legacy dashboard for this workflow until the React subview owns it.</p>
        <a className="primary-button primary-button--link" href={`/control/dashboard${route.hash}`}>Open legacy view</a>
      </section>
    )
  }
  return <OverviewPage />
}

function navClass(route: DashboardRoute, page: DashboardRoute['page']): string {
  return route.page === page ? 'nav-link nav-link--active' : 'nav-link'
}

function moreNavClass(route: DashboardRoute): string {
  return ['events', 'observability', 'corpus', 'research', 'intake', 'automation', 'legacy'].includes(route.page) ? 'nav-more nav-more--active' : 'nav-more'
}

function Shell() {
  const [hasToken, setHasToken] = useState(Boolean(getSavedToken()))
  const [route, setRoute] = useState<DashboardRoute>(() => currentRoute())

  useEffect(() => {
    const onHashChange = () => setRoute(currentRoute())
    window.addEventListener('hashchange', onHashChange)
    return () => window.removeEventListener('hashchange', onHashChange)
  }, [])

  if (!hasToken) return <TokenGate onSave={() => setHasToken(Boolean(getSavedToken()))} />
  return (
    <main className="app-frame">
      <div className="app-shell">
        <header className="app-header">
          <div>
            <p className="eyebrow">Enoch Dashboard V2</p>
            <h1>Operator command center</h1>
          </div>
          <nav className="app-nav" aria-label="Dashboard V2 navigation">
            <a className={navClass(route, 'overview')} href={dashboardV2Href('#overview')}>Overview</a>
            <a className={navClass(route, 'projects')} href={dashboardV2Href('#projects')}>Projects</a>
            <a className={navClass(route, 'queue')} href={dashboardV2Href('#queue:queued')}>Queue</a>
            <a className={navClass(route, 'runs')} href={dashboardV2Href('#runs')}>Runs</a>
            <a className={navClass(route, 'papers')} href={dashboardV2Href('#papers')}>Papers</a>
            <details className={moreNavClass(route)}>
              <summary>More</summary>
              <div className="nav-menu">
                <a className={navClass(route, 'events')} href={dashboardV2Href('#events')}>Events</a>
                <a className={navClass(route, 'observability')} href={dashboardV2Href('#observability')}>Observability</a>
                <a className={navClass(route, 'corpus')} href={dashboardV2Href('#corpus')}>Corpus</a>
                <a className={navClass(route, 'research')} href={dashboardV2Href('#research')}>Research</a>
                <a className={navClass(route, 'intake')} href={dashboardV2Href('#intake')}>Intake</a>
                <a className={navClass(route, 'automation')} href={dashboardV2Href('#automation')}>Automation</a>
                <a className="nav-link" href="/control/dashboard">Legacy dashboard</a>
                <button className="nav-link" type="button" onClick={() => { saveToken(''); setHasToken(false) }}>Clear token</button>
              </div>
            </details>
          </nav>
        </header>
        <RoutedPage route={route} />
      </div>
    </main>
  )
}

export function App() {
  return <QueryClientProvider client={queryClient}><Shell /></QueryClientProvider>
}
