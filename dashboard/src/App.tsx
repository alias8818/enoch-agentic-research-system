import { QueryClient, QueryClientProvider, useQuery, useQueryClient } from '@tanstack/react-query'
import { FormEvent, useEffect, useState } from 'react'
import { apiGet, getSavedToken, saveToken } from './api/client'
import { CommandHero } from './components/CommandHero'
import { MovementDiagnosis } from './components/MovementDiagnosis'
import { OverviewFreshness } from './components/OverviewFreshness'
import { PaperMiniStrip } from './components/PaperMiniStrip'
import { PrimaryAction, resolvePrimaryAction } from './components/PrimaryAction'
import { SafetyBar } from './components/SafetyBar'
import { AutomationPage } from './components/AutomationPage'
import { DetailPage } from './components/DetailPanel'
import { CorpusPage, EventsPage, IntakePage, ObservabilityPage, PapersPage, ProjectsPage, QueuePage, RunsPage } from './components/ResourcePages'
import { ResearchPage } from './components/ResearchPage'
import { WorkerLanes } from './components/WorkerLanes'
import { DASHBOARD_V2_PATH, canonicalDashboardHash, dashboardV2Href, dashboardRouteTitle, parseDashboardRoute } from './routes'
import type { DashboardRoute } from './routes'
import { detailParentPage, unsupportedRouteSuggestions } from './routePolicy'
import type { AutomationReadiness, OverviewResponse, StatusResponse } from './types'
import { applyTheme, getSavedTheme, saveTheme, toggleTheme, type DashboardTheme } from './theme'

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
      </section>
    </main>
  )
}

function OverviewPage() {
  const queryClient = useQueryClient()
  const [secondaryOpen, setSecondaryOpen] = useState(false)
  const [readinessRequested, setReadinessRequested] = useState(false)
  const overview = useQuery({ queryKey: ['overview'], queryFn: () => apiGet<OverviewResponse>('/control/api/v1/overview?active_limit=8&event_limit=6'), refetchInterval: 30_000 })
  const status = useQuery({ queryKey: ['status'], queryFn: () => apiGet<StatusResponse>('/control/api/status'), refetchInterval: 30_000 })
  const readiness = useQuery({
    queryKey: ['automation-readiness'],
    queryFn: () => apiGet<AutomationReadiness>('/control/api/v1/automation-readiness'),
    refetchInterval: 60_000,
    enabled: secondaryOpen || readinessRequested,
  })
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
  const primaryAction = resolvePrimaryAction(data, readinessRequested)
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
      <CommandHero overview={data} diagnosis={diagnosis} readiness={readiness.data} readinessRequested={readinessRequested} readinessLoading={readiness.isLoading || readiness.isFetching} requiresReadinessCheck />
      <ReadinessCheckCard
        readiness={readiness.data}
        isLoading={readiness.isLoading || readiness.isFetching}
        error={readiness.error}
        requested={readinessRequested}
        onCheck={() => {
          setReadinessRequested(true)
          if (readinessRequested) void readiness.refetch()
        }}
      />
      <MovementDiagnosis diagnosis={diagnosis} />
      <div className="command-grid">
        <WorkerLanes lanes={status.data?.worker_lanes || []} isLoading={status.isLoading} error={status.error} onRefresh={refresh} />
        <div className="side-rail">
          <PrimaryAction
            action={primaryAction}
            onRefresh={refresh}
            onCheckReadiness={() => {
              setReadinessRequested(true)
              if (readinessRequested) void readiness.refetch()
            }}
          />
          <PaperMiniStrip pipeline={data.paper_pipeline} onRefresh={refresh} />
        </div>
      </div>
      <details className="secondary-fold" onToggle={(event) => setSecondaryOpen(event.currentTarget.open)}>
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

function ReadinessCheckCard({
  readiness,
  isLoading,
  error,
  requested,
  onCheck,
}: {
  readiness?: AutomationReadiness;
  isLoading: boolean;
  error: unknown;
  requested: boolean;
  onCheck: () => void;
}) {
  const blockers = readiness?.blockers || []
  const label = error
    ? `Unavailable: ${String(error instanceof Error ? error.message : error)}`
    : readiness?.label || (isLoading ? 'Checking…' : requested ? 'No readiness result returned' : 'Not checked')
  return (
    <section className="readiness-check-card" aria-label="Readiness check">
      <div>
        <p className="eyebrow">Automation readiness</p>
        <h2>{label}</h2>
        <p>{blockers.length > 0 ? blockers[0] : readiness?.ok ? 'Long-haul checks currently pass.' : 'Run the readiness check before leaving automation unattended.'}</p>
      </div>
      <button className="secondary-button" type="button" disabled={isLoading} onClick={onCheck}>
        {readiness ? 'Refresh readiness' : 'Check readiness'}
      </button>
    </section>
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
      {readiness && !error && !isLoading && blockers.length === 0 ? <p>All reported long-haul readiness checks passed.</p> : null}
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
  const rawHash = window.location.hash || '#overview'
  const canonical = canonicalDashboardHash(rawHash)
  if (canonical !== rawHash) {
    window.history.replaceState(window.history.state, '', `${DASHBOARD_V2_PATH}${canonical}`)
  }
  return parseDashboardRoute(canonical)
}

function RoutedPage({ route }: { route: DashboardRoute }) {
  if (route.page === 'detail') return <DetailPage selection={{ kind: route.kind, id: route.id }} />
  if (route.page === 'projects') return <ProjectsPage route={route} />
  if (route.page === 'queue') return <QueuePage route={route} />
  if (route.page === 'runs') return <RunsPage route={route} />
  if (route.page === 'papers') return <PapersPage route={route} />
  if (route.page === 'events') return <EventsPage route={route} />
  if (route.page === 'observability') return <ObservabilityPage />
  if (route.page === 'corpus') return <CorpusPage route={route} />
  if (route.page === 'research') return <ResearchPage route={route} />
  if (route.page === 'intake') return <IntakePage route={route} />
  if (route.page === 'automation') return <AutomationPage paperId={route.paperId} search={route.search} reviewStatus={route.reviewStatus} />
  if (route.page === 'unsupported') {
    const suggestions = unsupportedRouteSuggestions(route.hash)
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
  return <OverviewPage />
}

function navClass(route: DashboardRoute, page: DashboardRoute['page']): string {
  const active = route.page === page || (route.page === 'detail' && detailParentPage(route.kind) === page)
  return active ? 'nav-link nav-link--active' : 'nav-link'
}

function moreNavClass(route: DashboardRoute): string {
  return ['events', 'observability', 'corpus', 'research', 'intake', 'automation', 'unsupported'].includes(route.page) ? 'nav-more nav-more--active' : 'nav-more'
}

function GlobalSearchForm() {
  const [query, setQuery] = useState('')
  function submit(event: FormEvent) {
    event.preventDefault()
    const trimmed = query.trim()
    window.location.href = dashboardV2Href(trimmed ? `#projects?search=${encodeURIComponent(trimmed)}` : '#projects')
  }
  return (
    <form className="app-global-search" onSubmit={submit}>
      <label>
        Global search
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search projects"
        />
      </label>
      <button className="secondary-button" type="submit">Search projects</button>
    </form>
  )
}

function Shell() {
  const [hasToken, setHasToken] = useState(Boolean(getSavedToken()))
  const [route, setRoute] = useState<DashboardRoute>(() => currentRoute())
  const [theme, setTheme] = useState<DashboardTheme>(() => getSavedTheme())

  useEffect(() => {
    applyTheme(theme)
  }, [theme])

  useEffect(() => {
    const onHashChange = () => setRoute(currentRoute())
    window.addEventListener('hashchange', onHashChange)
    return () => window.removeEventListener('hashchange', onHashChange)
  }, [])

  if (!hasToken) return <TokenGate onSave={() => setHasToken(Boolean(getSavedToken()))} />
  return (
    <main className="app-frame">
      <div className="app-shell">
        <header className="app-header app-header--compact">
          <div className="app-brand">
            <a className="app-brand-link" href={dashboardV2Href('#overview')}>
              <span className="eyebrow">Enoch Dashboard V2</span>
            </a>
            <p className="app-header-context">{dashboardRouteTitle(route)}</p>
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
                <button className="nav-link" type="button" onClick={() => { saveToken(''); setHasToken(false) }}>Clear token</button>
              </div>
            </details>
          </nav>
          <div className="app-header-tools">
            <GlobalSearchForm />
            <button
              className="secondary-button"
              type="button"
              aria-label={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
              onClick={() => {
                const next = toggleTheme(theme)
                setTheme(next)
                saveTheme(next)
              }}
            >
              {theme === 'dark' ? 'Light theme' : 'Dark theme'}
            </button>
          </div>
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
