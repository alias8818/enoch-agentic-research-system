import { QueryClient, QueryClientProvider, useQuery, useQueryClient } from '@tanstack/react-query'
import { type ReactNode, type RefObject, useEffect, useRef, useState } from 'react'
import { ActiveWorkList } from './activeWorkDisplay'
import { displayText } from './displayText'
import { apiGet, getSavedToken, saveToken } from './api/client'
import { parseAutomationReadiness, parseOverviewResponse, parseStatusResponse } from './api/readModelSchemas'
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
import { KeyboardShortcutHelp } from './components/KeyboardShortcutHelp'
import { applyTheme, getSavedTheme, saveTheme, toggleTheme, type DashboardTheme } from './theme'
import { useDashboardKeyboardShortcuts } from './useDashboardKeyboardShortcuts'

function TokenGate({ onSave }: Readonly<{ onSave: () => void }>) {
  const [token, setToken] = useState(getSavedToken())
  return (
    <main className="auth-frame">
      <section className="auth-card">
        <p className="eyebrow">Enoch Dashboard V2</p>
        <h1>Bearer token required</h1>
        <p>The React dashboard does not call authenticated APIs until a token is saved locally in this browser.</p>
        <form
          className="auth-form"
          onSubmit={(event) => {
            event.preventDefault()
            saveToken(token)
            onSave()
          }}
        >
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
  const overview = useQuery({ queryKey: ['overview'], queryFn: () => apiGet<unknown>('/control/api/v1/overview?active_limit=8&event_limit=6').then(parseOverviewResponse), refetchInterval: 30_000 })
  const status = useQuery({ queryKey: ['status'], queryFn: () => apiGet<unknown>('/control/api/status').then(parseStatusResponse), refetchInterval: 30_000 })
  const readiness = useQuery({
    queryKey: ['automation-readiness'],
    queryFn: () => apiGet<unknown>('/control/api/v1/automation-readiness').then(parseAutomationReadiness),
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
    return <div className="rounded-3xl border border-red-900 bg-red-950/40 p-8 text-red-100">Command state unavailable: {formatReadinessErrorMessage(overview.error)}</div>
  }

  return (
    <OverviewPageBody
      data={overview.data}
      statusData={status.data}
      statusLoading={status.isLoading}
      statusError={status.error}
      readinessData={readiness.data}
      readinessLoading={readiness.isLoading}
      readinessFetching={readiness.isFetching}
      readinessError={readiness.error}
      onReadinessRefetch={() => readiness.refetch()}
      readinessRequested={readinessRequested}
      isFetching={overview.isFetching || status.isFetching}
      onSecondaryOpenChange={setSecondaryOpen}
      onReadinessRequested={() => setReadinessRequested(true)}
      refresh={refresh}
    />
  )
}

function formatReadinessErrorMessage(error: unknown): string {
  if (error instanceof Error) return error.message
  return displayText(error, 'unknown error')
}

function readinessCheckCardDetail(blockers: string[], readiness?: AutomationReadiness): string {
  if (blockers.length > 0) return blockers[0]
  if (readiness?.ok) return 'Long-haul checks currently pass.'
  return 'Run the readiness check before leaving automation unattended.'
}

function readinessCheckButtonLabel(hasReadiness: boolean): string {
  if (hasReadiness) return 'Refresh readiness'
  return 'Check readiness'
}

function readinessCheckCardLabel(
  error: unknown,
  readiness: AutomationReadiness | undefined,
  isLoading: boolean,
  requested: boolean,
): string {
  if (error) return `Unavailable: ${formatReadinessErrorMessage(error)}`
  if (readiness?.label) return readiness.label
  if (isLoading) return 'Checking…'
  if (requested) return 'No readiness result returned'
  return 'Not checked'
}

function eventDetailHref(eventId: string): string {
  if (eventId) return dashboardV2Href(`#event:${encodeURIComponent(eventId)}`)
  return dashboardV2Href('#events')
}

function triggerReadinessCheck(
  readinessRequested: boolean,
  onReadinessRequested: () => void,
  onReadinessRefetch: () => void,
): void {
  onReadinessRequested()
  if (readinessRequested) onReadinessRefetch()
}

function OverviewPageBody({
  data,
  statusData,
  statusLoading,
  statusError,
  readinessData,
  readinessLoading,
  readinessFetching,
  readinessError,
  onReadinessRefetch,
  readinessRequested,
  isFetching,
  onSecondaryOpenChange,
  onReadinessRequested,
  refresh,
}: Readonly<{
  data: OverviewResponse
  statusData?: StatusResponse
  statusLoading: boolean
  statusError: unknown
  readinessData?: AutomationReadiness
  readinessLoading: boolean
  readinessFetching: boolean
  readinessError: unknown
  onReadinessRefetch: () => void
  readinessRequested: boolean
  isFetching: boolean
  onSecondaryOpenChange: (open: boolean) => void
  onReadinessRequested: () => void
  refresh: () => void
}>) {
  const diagnosis = data.movement_diagnosis || { status: 'unknown', primary_reason: 'No movement diagnosis returned.', blockers: [] }
  const primaryAction = resolvePrimaryAction(data, readinessData)
  const recentEvents = data.recent_events || []
  const activeItems = data.active_items || []
  const operatorCounts = data.operator_counts || {}
  const operatorDetailCounts = data.operator_detail_counts || {}
  return (
    <div className="command-stack">
      <div className="command-topline">
        <OverviewFreshness generatedAt={data.generated_at} laneGeneratedAt={statusData?.generated_at} isFetching={isFetching} onRefresh={refresh} />
        <SafetyBar flags={data.flags} onRefresh={refresh} />
      </div>
      <CommandHero overview={data} diagnosis={diagnosis} readiness={readinessData} readinessRequested={readinessRequested} readinessLoading={readinessLoading || readinessFetching} requiresReadinessCheck />
      <ReadinessCheckCard
        readiness={readinessData}
        isLoading={readinessLoading || readinessFetching}
        error={readinessError}
        requested={readinessRequested}
        onCheck={() => triggerReadinessCheck(readinessRequested, onReadinessRequested, onReadinessRefetch)}
      />
      <MovementDiagnosis diagnosis={diagnosis} />
      <div className="command-grid">
        <WorkerLanes lanes={statusData?.worker_lanes || []} isLoading={statusLoading} error={statusError} onRefresh={refresh} />
        <div className="side-rail">
          <PrimaryAction
            action={primaryAction}
            onRefresh={refresh}
            onCheckReadiness={() => triggerReadinessCheck(readinessRequested, onReadinessRequested, onReadinessRefetch)}
          />
          <PaperMiniStrip pipeline={data.paper_pipeline} onRefresh={refresh} />
        </div>
      </div>
      <OverviewSecondaryFold
        recentEvents={recentEvents}
        operatorCounts={operatorCounts}
        operatorDetailCounts={operatorDetailCounts}
        activeItems={activeItems}
        readinessData={readinessData}
        readinessLoading={readinessLoading}
        readinessError={readinessError}
        onSecondaryOpenChange={onSecondaryOpenChange}
      />
    </div>
  )
}

function recentActivityListKey(event: Record<string, unknown>, index: number): string {
  const id = displayText(event.event_id ?? event.id, '')
  const type = displayText(event.event_type, 'event')
  return id || `${type}-${index}`
}

function RecentActivityItem({ event }: Readonly<{ event: Record<string, unknown> }>) {
  const id = displayText(event.event_id ?? event.id, '')
  const type = displayText(event.event_type, 'event')
  const summary = displayText(event.summary ?? event.entity_id, 'No event summary returned.')
  return (
    <li>
      <a href={eventDetailHref(id)}>{type}</a>
      <span>{summary}</span>
    </li>
  )
}

function RecentActivityStream({ events }: Readonly<{ events: OverviewResponse['recent_events'] }>) {
  const recentEvents = events || []
  if (recentEvents.length === 0) {
    return <p>No recent activity returned in the bounded overview snapshot.</p>
  }
  return (
    <ol>
      {recentEvents.slice(0, 6).map((event, index) => (
        <RecentActivityItem key={recentActivityListKey(event, index)} event={event} />
      ))}
    </ol>
  )
}

function OverviewSecondaryFold({
  recentEvents,
  operatorCounts,
  operatorDetailCounts,
  activeItems,
  readinessData,
  readinessLoading,
  readinessError,
  onSecondaryOpenChange,
}: Readonly<{
  recentEvents: OverviewResponse['recent_events']
  operatorCounts: Record<string, unknown>
  operatorDetailCounts: Record<string, unknown>
  activeItems: Record<string, unknown>[]
  readinessData?: AutomationReadiness
  readinessLoading: boolean
  readinessError: unknown
  onSecondaryOpenChange: (open: boolean) => void
}>) {
  return (
    <details className="secondary-fold" onToggle={(event) => onSecondaryOpenChange(event.currentTarget.open)}>
      <summary>Show secondary details</summary>
      <div className="secondary-links">
        <a href={dashboardV2Href('#runs')}>Runs</a>
        <a href={dashboardV2Href('#papers')}>Papers</a>
        <a href={dashboardV2Href('#events')}>Recent activity</a>
      </div>
      <section className="activity-snapshot" aria-label="Recent activity stream">
        <h3>Recent activity stream</h3>
        <RecentActivityStream events={recentEvents} />
      </section>
      <OperatorQueueSnapshot operatorCounts={operatorCounts} operatorDetailCounts={operatorDetailCounts} />
      <ActiveWorkSummary activeItems={activeItems} />
      <AutomationReadinessSummary readiness={readinessData} isLoading={readinessLoading} error={readinessError} />
    </details>
  )
}

function ReadinessCheckCard({
  readiness,
  isLoading,
  error,
  requested,
  onCheck,
}: Readonly<{
  readiness?: AutomationReadiness
  isLoading: boolean
  error: unknown
  requested: boolean
  onCheck: () => void
}>) {
  const blockers = readiness?.blockers || []
  const label = readinessCheckCardLabel(error, readiness, isLoading, requested)
  return (
    <section className="readiness-check-card" aria-label="Readiness check">
      <div>
        <p className="eyebrow">Automation readiness</p>
        <h2>{label}</h2>
        <p>{readinessCheckCardDetail(blockers, readiness)}</p>
      </div>
      <button className="secondary-button" type="button" disabled={isLoading} onClick={onCheck}>
        {readinessCheckButtonLabel(Boolean(readiness))}
      </button>
    </section>
  )
}


function formatPositiveCount(value: number): string {
  if (Number.isFinite(value) && value > 0) return String(Math.floor(value))
  return '0'
}

function displayOperatorCount(value: unknown): string {
  if (typeof value === 'boolean' || value === null || value === undefined) return '0'
  if (typeof value === 'number') return formatPositiveCount(value)
  if (typeof value === 'string') return formatPositiveCount(Number(value.trim()))
  return '0'
}

function labelOperatorKey(key: string): string {
  return key.replaceAll('_', ' ')
}

function operatorQueueRows(
  operatorCounts: Record<string, unknown>,
  operatorDetailCounts: Record<string, unknown>,
): [string, unknown][] {
  const entries: [string, unknown][] = [
    ['needs_attention', operatorCounts.needs_attention],
    ['running', operatorCounts.running],
    ['write_paper', operatorCounts.write_paper],
    ['ready_to_publish', operatorCounts.ready_to_publish],
    ['finalization_needed', operatorDetailCounts.finalization_needed],
    ['followup_candidate', operatorDetailCounts.followup_candidate],
  ]
  return entries.filter(([, value]) => displayOperatorCount(value) !== '0')
}

function OperatorQueueRowList({ rows }: Readonly<{ rows: [string, unknown][] }>) {
  return (
    <dl>
      {rows.slice(0, 6).map(([key, value]) => (
        <div key={String(key)}>
          <dt>{labelOperatorKey(String(key))}</dt>
          <dd>{displayOperatorCount(value)}</dd>
        </div>
      ))}
    </dl>
  )
}

function OperatorQueueSnapshot({ operatorCounts, operatorDetailCounts }: Readonly<{ operatorCounts: Record<string, unknown>; operatorDetailCounts: Record<string, unknown> }>) {
  const rows = operatorQueueRows(operatorCounts, operatorDetailCounts)
  let body: ReactNode = <p>No operator queue counts reported in the bounded overview snapshot.</p>
  if (rows.length > 0) {
    body = <OperatorQueueRowList rows={rows} />
  }

  return (
    <section className="operator-snapshot" aria-label="Operator queue snapshot">
      <h3>Operator queue snapshot</h3>
      {body}
    </section>
  )
}

function ActiveWorkSummary({ activeItems }: Readonly<{ activeItems: Record<string, unknown>[] }>) {
  return (
    <section className="active-work-snapshot" aria-label="Active work snapshot">
      <h3>Active work snapshot</h3>
      <ActiveWorkList activeItems={activeItems} />
    </section>
  )
}

function readinessPillClass(ok: boolean | undefined): string {
  return ok ? 'readiness-pill readiness-pill--good' : 'readiness-pill readiness-pill--warn'
}

function automationReadinessSummaryLabel(readiness: AutomationReadiness | undefined, isLoading: boolean): string {
  if (readiness?.label) return readiness.label
  if (isLoading) return 'Checking automation readiness…'
  return 'Automation readiness unavailable'
}

function ReadinessFacts({ summary }: Readonly<{ summary: NonNullable<AutomationReadiness['summary']> }>) {
  return (
    <div className="readiness-facts">
      <span>queued {String(summary.queued ?? 0)}</span>
      <span>active {String(summary.active ?? 0)}</span>
      <span>queue {summary.queue_paused ? 'paused' : 'unpaused'}</span>
      <span>maintenance {summary.maintenance_mode ? 'on' : 'off'}</span>
    </div>
  )
}

function ReadinessBlockersBody({ blockers, showAllPassed }: Readonly<{ blockers: string[]; showAllPassed: boolean }>) {
  if (blockers.length > 0) {
    return (
      <ul>
        {blockers.slice(0, 6).map((blocker) => <li key={blocker}>{blocker}</li>)}
      </ul>
    )
  }
  if (showAllPassed) {
    return <p>All reported long-haul readiness checks passed.</p>
  }
  return null
}

function ReadinessChecksList({ checks }: Readonly<{ checks: NonNullable<AutomationReadiness['checks']> }>) {
  if (checks.length === 0) return null
  return (
    <div className="readiness-checks" aria-label="Automation readiness checks">
      {checks.slice(0, 8).map((check) => (
        <span key={String(check.name)} className={readinessPillClass(check.ok)}>
          {String(check.name || 'check')}: {check.ok ? 'ok' : 'blocked'}
        </span>
      ))}
    </div>
  )
}

function automationReadinessErrorMessage(error: unknown): ReactNode {
  if (!error) return null
  return <p>Automation readiness unavailable: {formatReadinessErrorMessage(error)}</p>
}

function AutomationReadinessSummary({ readiness, isLoading, error }: Readonly<{ readiness?: AutomationReadiness; isLoading: boolean; error: unknown }>) {
  const blockers = readiness?.blockers ?? []
  const checks = readiness?.checks ?? []
  const summary = readiness?.summary ?? {}
  const label = automationReadinessSummaryLabel(readiness, isLoading)
  const showAllPassed = Boolean(readiness && !error && !isLoading && blockers.length === 0)
  const errorMessage = automationReadinessErrorMessage(error)
  const blockersBody = error ? null : <ReadinessBlockersBody blockers={blockers} showAllPassed={showAllPassed} />

  return (
    <section className="readiness-snapshot" aria-label="Automation readiness">
      <div>
        <h3>Automation readiness</h3>
        <span className={readinessPillClass(readiness?.ok)}>{label}</span>
      </div>
      {errorMessage}
      {blockersBody}
      <ReadinessFacts summary={summary} />
      <ReadinessChecksList checks={checks} />
    </section>
  )
}

function currentRoute(): DashboardRoute {
  const rawHash = globalThis.location.hash || '#overview'
  const canonical = canonicalDashboardHash(rawHash)
  if (canonical !== rawHash) {
    globalThis.history.replaceState(globalThis.history.state, '', `${DASHBOARD_V2_PATH}${canonical}`)
  }
  return parseDashboardRoute(canonical)
}

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

function resolveRoutedPage(route: DashboardRoute): ReactNode {
  let content: ReactNode = <OverviewPage />
  switch (route.page) {
    case 'detail':
      content = <DetailPage selection={{ kind: route.kind, id: route.id }} />
      break
    case 'projects':
      content = <ProjectsPage route={route} />
      break
    case 'queue':
      content = <QueuePage route={route} />
      break
    case 'runs':
      content = <RunsPage route={route} />
      break
    case 'papers':
      content = <PapersPage route={route} />
      break
    case 'events':
      content = <EventsPage route={route} />
      break
    case 'observability':
      content = <ObservabilityPage />
      break
    case 'corpus':
      content = <CorpusPage route={route} />
      break
    case 'research':
      content = <ResearchPage route={route} />
      break
    case 'intake':
      content = <IntakePage route={route} />
      break
    case 'automation':
      content = <AutomationPage paperId={route.paperId} search={route.search} reviewStatus={route.reviewStatus} />
      break
    case 'unsupported':
      content = <UnsupportedRoutePage hash={route.hash} />
      break
    default:
      break
  }
  return content
}

function RoutedPage({ route }: Readonly<{ route: DashboardRoute }>) {
  return resolveRoutedPage(route)
}

function navClass(route: DashboardRoute, page: DashboardRoute['page']): string {
  const active = route.page === page || (route.page === 'detail' && detailParentPage(route.kind) === page)
  return active ? 'nav-link nav-link--active' : 'nav-link'
}

function moreNavClass(route: DashboardRoute): string {
  return ['events', 'observability', 'corpus', 'research', 'intake', 'automation', 'unsupported'].includes(route.page) ? 'nav-more nav-more--active' : 'nav-more'
}

function GlobalSearchForm({ inputRef }: Readonly<{ inputRef: RefObject<HTMLInputElement | null> }>) {
  const [query, setQuery] = useState('')
  return (
    <form
      className="app-global-search"
      onSubmit={(event) => {
        event.preventDefault()
        const trimmed = query.trim()
        globalThis.location.href = dashboardV2Href(trimmed ? `#projects?search=${encodeURIComponent(trimmed)}` : '#projects')
      }}
    >
      <label htmlFor="app-global-search-input">Global search</label>
      <input
        id="app-global-search-input"
        ref={inputRef}
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        placeholder="Search projects"
      />
      <button className="secondary-button" type="submit">Search projects</button>
    </form>
  )
}

function Shell() {
  const [hasToken, setHasToken] = useState(Boolean(getSavedToken()))
  const [route, setRoute] = useState<DashboardRoute>(() => currentRoute())
  const [theme, setTheme] = useState<DashboardTheme>(() => getSavedTheme())
  const [shortcutHelpOpen, setShortcutHelpOpen] = useState(false)
  const searchInputRef = useRef<HTMLInputElement | null>(null)

  useEffect(() => {
    applyTheme(theme)
  }, [theme])

  useEffect(() => {
    const onHashChange = () => setRoute(currentRoute())
    globalThis.addEventListener('hashchange', onHashChange)
    return () => globalThis.removeEventListener('hashchange', onHashChange)
  }, [])

  useDashboardKeyboardShortcuts({
    helpOpen: shortcutHelpOpen,
    onToggleHelp: () => setShortcutHelpOpen((current) => !current),
    onCloseHelp: () => setShortcutHelpOpen(false),
    searchInputRef,
  })

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
            <GlobalSearchForm inputRef={searchInputRef} />
            <button className="secondary-button" type="button" aria-label="Show keyboard shortcuts" onClick={() => setShortcutHelpOpen(true)}>
              Shortcuts
            </button>
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
        <KeyboardShortcutHelp open={shortcutHelpOpen} onClose={() => setShortcutHelpOpen(false)} />
      </div>
    </main>
  )
}

export function App() {
  const [queryClient] = useState(() => new QueryClient())
  return <QueryClientProvider client={queryClient}><Shell /></QueryClientProvider>
}
