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
import type { AutomationReadiness, OverviewResponse, StatusResponse } from './types'

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
  const readiness = useQuery({ queryKey: ['automation-readiness'], queryFn: () => apiGet<AutomationReadiness>('/control/api/v1/automation-readiness'), refetchInterval: 60_000 })
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
  const recentEvents = data.recent_events || []
  const activeItems = data.active_items || []
  const operatorCounts = data.operator_counts || {}
  const operatorDetailCounts = data.operator_detail_counts || {}
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
        <div className="secondary-links">
          <a href={dashboardV2Href('#runs')}>Runs</a>
          <a href={dashboardV2Href('#papers')}>Papers</a>
          <a href={dashboardV2Href('#events')}>Recent activity</a>
        </div>
        <section className="activity-snapshot" aria-label="Recent activity stream">
          <h3>Recent activity stream</h3>
          {recentEvents.length > 0 ? (
            <ol>
              {recentEvents.slice(0, 6).map((event, index) => {
                const id = String(event.event_id || event.id || '')
                const type = String(event.event_type || 'event')
                const summary = String(event.summary || event.entity_id || 'No event summary returned.')
                return (
                  <li key={id || `${type}-${index}`}>
                    <a href={id ? dashboardV2Href(`#event:${encodeURIComponent(id)}`) : dashboardV2Href('#events')}>{type}</a>
                    <span>{summary}</span>
                  </li>
                )
              })}
            </ol>
          ) : (
            <p>No recent activity returned in the bounded overview snapshot.</p>
          )}
        </section>
        <OperatorQueueSnapshot operatorCounts={operatorCounts} operatorDetailCounts={operatorDetailCounts} />
        <ActiveWorkSummary activeItems={activeItems} />
        <AutomationReadinessSummary readiness={readiness.data} isLoading={readiness.isLoading} error={readiness.error} />
      </details>
    </div>
  )
}


function displayOperatorCount(value: unknown): string {
  if (typeof value === 'boolean' || value === null || value === undefined) return '0'
  if (typeof value === 'number') return Number.isFinite(value) && value > 0 ? String(Math.floor(value)) : '0'
  if (typeof value === 'string') {
    const parsed = Number(value.trim())
    return Number.isFinite(parsed) && parsed > 0 ? String(Math.floor(parsed)) : '0'
  }
  return '0'
}

function labelOperatorKey(key: string): string {
  return key.replaceAll('_', ' ')
}

function OperatorQueueSnapshot({ operatorCounts, operatorDetailCounts }: { operatorCounts: Record<string, unknown>; operatorDetailCounts: Record<string, unknown> }) {
  const rows = [
    ['needs_attention', operatorCounts.needs_attention],
    ['running', operatorCounts.running],
    ['write_paper', operatorCounts.write_paper],
    ['ready_to_publish', operatorCounts.ready_to_publish],
    ['finalization_needed', operatorDetailCounts.finalization_needed],
    ['followup_candidate', operatorDetailCounts.followup_candidate],
  ].filter(([, value]) => displayOperatorCount(value) !== '0')

  return (
    <section className="operator-snapshot" aria-label="Operator queue snapshot">
      <h3>Operator queue snapshot</h3>
      {rows.length > 0 ? (
        <dl>
          {rows.slice(0, 6).map(([key, value]) => (
            <div key={String(key)}>
              <dt>{labelOperatorKey(String(key))}</dt>
              <dd>{displayOperatorCount(value)}</dd>
            </div>
          ))}
        </dl>
      ) : (
        <p>No operator queue counts reported in the bounded overview snapshot.</p>
      )}
    </section>
  )
}

function ActiveWorkSummary({ activeItems }: { activeItems: Record<string, unknown>[] }) {
  return (
    <section className="active-work-snapshot" aria-label="Active work snapshot">
      <h3>Active work snapshot</h3>
      {activeItems.length > 0 ? (
        <ol>
          {activeItems.slice(0, 6).map((item, index) => {
            const projectId = String(item.project_id || '')
            const runId = String(item.current_run_id || item.run_id || '')
            const label = String(item.project_name || projectId || runId || 'Active work')
            const machine = String(item.machine_target || item.lane || 'unknown lane')
            const href = runId
              ? dashboardV2Href(`#run:${encodeURIComponent(runId)}`)
              : projectId
                ? dashboardV2Href(`#project:${encodeURIComponent(projectId)}`)
                : dashboardV2Href('#runs')
            return (
              <li key={runId || projectId || index}>
                <div>
                  <strong>{label}</strong>
                  <span>{machine} · {runId || projectId || 'no run id'}</span>
                </div>
                <a href={href}>{runId ? 'Open run' : 'Open project'}</a>
              </li>
            )
          })}
        </ol>
      ) : (
        <p>No active work returned in the bounded overview snapshot.</p>
      )}
    </section>
  )
}

function AutomationReadinessSummary({ readiness, isLoading, error }: { readiness?: AutomationReadiness; isLoading: boolean; error: unknown }) {
  const blockers = readiness?.blockers || []
  const checks = readiness?.checks || []
  const summary = readiness?.summary || {}
  const label = readiness?.label || (isLoading ? 'Checking automation readiness…' : 'Automation readiness unavailable')
  return (
    <section className="readiness-snapshot" aria-label="Automation readiness">
      <div>
        <h3>Automation readiness</h3>
        <span className={readiness?.ok ? 'readiness-pill readiness-pill--good' : 'readiness-pill readiness-pill--warn'}>{label}</span>
      </div>
      {error ? <p>Automation readiness unavailable: {String(error instanceof Error ? error.message : error)}</p> : null}
      {!error && blockers.length > 0 ? (
        <ul>
          {blockers.slice(0, 6).map((blocker) => <li key={blocker}>{blocker}</li>)}
        </ul>
      ) : null}
      {!error && !isLoading && blockers.length === 0 ? <p>All reported long-haul readiness checks passed.</p> : null}
      <div className="readiness-facts">
        <span>queued {String(summary.queued ?? 0)}</span>
        <span>active {String(summary.active ?? 0)}</span>
        <span>queue {summary.queue_paused ? 'paused' : 'unpaused'}</span>
        <span>maintenance {summary.maintenance_mode ? 'on' : 'off'}</span>
      </div>
      {checks.length > 0 ? (
        <div className="readiness-checks" aria-label="Automation readiness checks">
          {checks.slice(0, 8).map((check) => (
            <span key={String(check.name)} className={check.ok ? 'readiness-pill readiness-pill--good' : 'readiness-pill readiness-pill--warn'}>
              {String(check.name || 'check')}: {check.ok ? 'ok' : 'blocked'}
            </span>
          ))}
        </div>
      ) : null}
    </section>
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
  const [queryClient] = useState(() => new QueryClient())
  return <QueryClientProvider client={queryClient}><Shell /></QueryClientProvider>
}
