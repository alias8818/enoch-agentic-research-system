import { FormEvent, useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { apiGet, apiPost } from '../api/client'
import { dashboardV2Href } from '../routes'
import type { DashboardRoute } from '../routes'
import { DataTable } from './DataTable'
import { DetailPanel } from './DetailPanel'
import { useOperatorDialog } from './OperatorDialog'
import type { CommandPresentationContext } from '../commandResultPresentation'
import { CommandResultSummary } from './CommandResultSummary'
import { deriveIntakeIdeaOperatorSummary } from '../detailOperatorSummary'

type PageMeta = { next_cursor?: string; has_more?: boolean; returned?: number; page_size?: number }
type PageResponse = { rows?: Record<string, unknown>[]; counts?: Record<string, unknown>; generated_at?: string; page?: PageMeta }
type OverviewPaperPipeline = {
  publish_ready?: number
  published_imported?: number
  publication_ready_total?: number
  missing_from_corpus?: number
}
type OverviewLite = { paper_pipeline?: OverviewPaperPipeline; generated_at?: string }
type ObservabilityHealth = { generated_at?: string; route_observability_enabled?: boolean; route_observability_log_configured?: boolean; latest_route_observation?: string | null }
type ObservabilityMemory = { generated_at?: string; rss_mib?: number | null; peak_rss_mib?: number | null; warn_threshold_mib?: number | null; memory_warn?: boolean; route_observability_enabled?: boolean }
type DetailSelection = { kind: 'project' | 'run' | 'paper' | 'event'; id: string; row?: Record<string, unknown> }
type FilterState = { search: string; status: string; pageSize: string; cursor: string }
type CommandResult = { payload: Record<string, unknown>; context?: CommandPresentationContext }

function PageShell({ title, subtitle, children, action }: { title: string; subtitle: string; children: React.ReactNode; action?: React.ReactNode }) {
  return (
    <section className="page-stack">
      <div className="page-hero page-hero--with-action">
        <div>
          <p className="eyebrow">Dashboard V2</p>
          <h1>{title}</h1>
          <p>{subtitle}</p>
        </div>
        {action ? <div className="page-hero-action">{action}</div> : null}
      </div>
      {children}
    </section>
  )
}

function LoadingCard({ label }: { label: string }) {
  return <div className="state-card">Loading {label}…</div>
}

function ErrorCard({ error }: { error: unknown }) {
  return <div className="state-card state-card--error">V2 data unavailable: {String(error instanceof Error ? error.message : error)}</div>
}

function EventsErrorCard({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  const message = String(error instanceof Error ? error.message : error)
  return (
    <section className="state-card state-card--error v2-error-card">
      <p className="eyebrow">Events read model</p>
      <h2>Events could not load</h2>
      <p>The backend events read model returned an error. Refresh once; if it persists, check the control-plane logs for the bounded events endpoint.</p>
      <p className="error-detail">{message}</p>
      <div className="action-row">
        <button className="secondary-button" type="button" onClick={onRetry}>Retry events</button>
        <a className="secondary-button" href="/control/dashboard#events">Open legacy events</a>
      </div>
    </section>
  )
}

function PageRefreshAction({ generatedAt, isFetching, onRefresh, label = 'Last loaded', refreshLabel = 'Refresh rows' }: { generatedAt?: string; isFetching: boolean; onRefresh: () => void; label?: string; refreshLabel?: string }) {
  return (
    <>
      <span>{label} {generatedAt || 'unknown'}</span>
      <button className="secondary-button" type="button" disabled={isFetching} onClick={onRefresh}>
        {isFetching ? 'Refreshing…' : refreshLabel}
      </button>
    </>
  )
}

function FilterBar({ state, statusOptions, onApply, onNext, onReset, page }: { state: FilterState; statusOptions: { label: string; value: string }[]; onApply: (next: FilterState) => void; onNext: () => void; onReset: () => void; page?: PageMeta }) {
  const [draft, setDraft] = useState(state)
  useEffect(() => {
    setDraft(state)
  }, [state])
  function submit(event: FormEvent) {
    event.preventDefault()
    onApply({ ...draft, cursor: '' })
  }
  return (
    <form className="filter-bar" onSubmit={submit}>
      <label>Search
        <input value={draft.search} onChange={(event) => setDraft({ ...draft, search: event.target.value })} placeholder="Search" />
      </label>
      <label>Status
        <select value={draft.status} onChange={(event) => setDraft({ ...draft, status: event.target.value })}>
          {statusOptions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
        </select>
      </label>
      <label>Size
        <select value={draft.pageSize} onChange={(event) => setDraft({ ...draft, pageSize: event.target.value })}>
          {['25', '50', '100', '200'].map((value) => <option key={value} value={value}>{value}</option>)}
        </select>
      </label>
      <button className="primary-button" type="submit">Apply filters</button>
      <button className="secondary-button" type="button" onClick={() => { setDraft({ search: '', status: '', pageSize: '50', cursor: '' }); onReset() }}>Reset</button>
      <button className="secondary-button" type="button" disabled={!page?.has_more} onClick={onNext}>Next page</button>
      <span>Showing {page?.returned ?? 0}</span>
    </form>
  )
}

function withCommonParams(state: FilterState, sort: string): URLSearchParams {
  const params = new URLSearchParams({ page_size: state.pageSize, sort })
  if (state.status) params.set('status', state.status)
  if (state.search) params.set('search', state.search)
  if (state.cursor) params.set('cursor', state.cursor)
  return params
}


function hashQuery(entries: [string, string][]): string {
  const params = new URLSearchParams()
  entries.forEach(([key, value]) => {
    if (value) params.set(key, value)
  })
  const text = params.toString()
  return text ? `?${text}` : ''
}

function replaceRouteHash(hash: string) {
  if (typeof window === 'undefined') return
  window.history.replaceState(window.history.state, '', hash)
}

function queueHash(state: FilterState): string {
  const base = state.status ? `#queue:${encodeURIComponent(state.status)}` : '#queue'
  return `${base}${hashQuery([['search', state.search]])}`
}

function statusHash(base: string, statusKey: string, state: FilterState): string {
  return `${base}${hashQuery([[statusKey, state.status], ['search', state.search]])}`
}

function withRunParams(state: FilterState): URLSearchParams {
  const params = new URLSearchParams({ page_size: state.pageSize, sort: 'recent' })
  if (state.status) params.set('state', state.status)
  if (state.search) params.set('search', state.search)
  if (state.cursor) params.set('cursor', state.cursor)
  return params
}

function firstValue(...values: unknown[]): unknown {
  return values.find((value) => value !== null && value !== undefined && value !== '')
}

function shortId(value: string): string {
  if (value.length <= 30) return value
  return `${value.slice(0, 14)}…${value.slice(-10)}`
}

function selectedDispatchReason(selection: DetailSelection | null): string {
  if (!selection) return 'Select a queued row to check whether that exact candidate can dispatch.'
  if (!selection.id) return 'Selected row has no project id.'
  const status = String(selection.row?.status || '').toLowerCase()
  if (status !== 'queued') return `Selected row is ${status || 'not queued'}.`
  return 'Dry-run checks /control/dispatch-one for the selected project only.'
}

function queueDispatchSignature(row?: Record<string, unknown>): string {
  if (!row) return ''
  return [
    String(row.project_id || ''),
    String(row.status || '').toLowerCase(),
    String(row.machine_target || ''),
    String(row.current_run_id || ''),
    String(row.dispatch_priority || ''),
    String(row.selection_rank || ''),
    String(row.updated_at || ''),
  ].join('|')
}

function selectedDispatchDisabledReason(canDryRunSelected: boolean, liveReady: boolean, staleReady: boolean, dispatchBusy: boolean): string {
  if (dispatchBusy) return 'Dispatch selected project disabled: dispatch command is running.'
  if (staleReady) return 'Dispatch selected project disabled: selected row changed; run Check selected dispatch again.'
  if (!canDryRunSelected) return 'Dispatch selected project disabled: select a queued row first.'
  if (!liveReady) return 'Dispatch selected project disabled: run Check selected dispatch first.'
  return ''
}

function CommandResultCard({ result, stale }: { result: CommandResult | null; stale?: boolean }) {
  if (!result) return null
  return <CommandResultSummary result={{ payload: result.payload, context: { ...result.context, stale: stale || result.context?.stale } }} />
}

function CountCard({ label, value, detail }: { label: string; value: unknown; detail: string }) {
  return (
    <div className="count-card">
      <div>{String(value ?? 0)}</div>
      <div>{label}</div>
      <p>{detail}</p>
    </div>
  )
}

function eventCellHref(row: Record<string, unknown>, column: string): string | undefined {
  if (column !== 'id' && column !== 'event_id') return undefined
  const id = firstValue(row.event_id, row.id)
  return id ? dashboardV2Href(`#event:${encodeURIComponent(String(id))}`) : undefined
}

function detailCellHref(row: Record<string, unknown>, column: string): string | undefined {
  if (column === 'project_id') {
    const id = firstValue(row.project_id)
    return id ? dashboardV2Href(`#project:${encodeURIComponent(String(id))}`) : undefined
  }
  if (column === 'run_id') {
    const id = firstValue(row.run_id)
    return id ? dashboardV2Href(`#run:${encodeURIComponent(String(id))}`) : undefined
  }
  if (column === 'paper_id') {
    const id = firstValue(row.paper_id)
    return id ? dashboardV2Href(`#paper:${encodeURIComponent(String(id))}`) : undefined
  }
  return eventCellHref(row, column)
}

export function QueuePage({ route }: { route: Extract<DashboardRoute, { page: 'queue' }> }) {
  const [selection, setSelection] = useState<DetailSelection | null>(null)
  const [dispatchResult, setDispatchResult] = useState<CommandResult | null>(null)
  const [dispatchBusy, setDispatchBusy] = useState(false)
  const [liveDispatchProjectId, setLiveDispatchProjectId] = useState('')
  const [liveDispatchSignature, setLiveDispatchSignature] = useState('')
  const [filters, setFilters] = useState<FilterState>({ search: route.search || '', status: route.status, pageSize: '50', cursor: '' })
  const { confirm, dialog } = useOperatorDialog()
  useEffect(() => {
    setFilters((current) => current.status === route.status && current.search === route.search ? current : { ...current, status: route.status, search: route.search || '', cursor: '' })
    setSelection(null)
    setDispatchResult(null)
    setLiveDispatchProjectId('')
    setLiveDispatchSignature('')
  }, [route.search, route.status])
  const params = withCommonParams(filters, 'priority')
  params.set('queue', 'all')
  const query = useQuery({ queryKey: ['queue', filters], queryFn: () => apiGet<PageResponse>(`/control/api/v1/queue?${params}`) })
  if (query.isLoading) return <LoadingCard label="queue" />
  if (query.isError) return <ErrorCard error={query.error} />
  const selectedProjectId = selection?.id || ''
  const selectedStatus = String(selection?.row?.status || '').toLowerCase()
  const canDryRunSelected = Boolean(selectedProjectId) && selectedStatus === 'queued'
  const selectedCurrentRow = (query.data?.rows || []).find((row) => String(row.project_id || '') === selectedProjectId)
  const selectedCurrentSignature = queueDispatchSignature(selectedCurrentRow || selection?.row)
  const canLiveDispatchSelected = canDryRunSelected
    && liveDispatchProjectId === selectedProjectId
    && Boolean(liveDispatchSignature)
    && liveDispatchSignature === selectedCurrentSignature
  const staleDispatchReady = Boolean(liveDispatchSignature) && liveDispatchSignature !== selectedCurrentSignature
  const dispatchDisabledReason = selectedDispatchDisabledReason(canDryRunSelected, canLiveDispatchSelected, staleDispatchReady, dispatchBusy)
  async function dryRunSelectedDispatch() {
    if (!canDryRunSelected) return
    setDispatchBusy(true)
    try {
      const payload = await apiPost<Record<string, unknown>>('/control/dispatch-one', {
        project_id: selectedProjectId,
        dry_run: true,
        requested_by: 'dashboard-v2',
        force_preflight: true,
      })
      setDispatchResult({ payload, context: { commandFamily: 'dispatch' } })
      setLiveDispatchProjectId(payload.action === 'dry_run_dispatch_one' ? selectedProjectId : '')
      setLiveDispatchSignature(payload.action === 'dry_run_dispatch_one' ? selectedCurrentSignature : '')
    } catch (error) {
      setDispatchResult({ payload: { ok: false, reason: error instanceof Error ? error.message : String(error) }, context: { commandFamily: 'dispatch' } })
      setLiveDispatchProjectId('')
      setLiveDispatchSignature('')
    } finally {
      setDispatchBusy(false)
    }
  }
  async function liveDispatchSelected() {
    if (!selectedProjectId || !canLiveDispatchSelected) return
    const confirmed = await confirm({
      title: 'Dispatch selected project?',
      message: `This starts live dispatch for exactly ${selectedProjectId}. Use Check selected dispatch again if the row changed or went stale.`,
      confirmLabel: 'Dispatch selected',
      tone: 'warn',
    })
    if (!confirmed) return
    setDispatchBusy(true)
    try {
      const payload = await apiPost<Record<string, unknown>>('/control/dispatch-one', {
        project_id: selectedProjectId,
        dry_run: false,
        requested_by: 'dashboard-v2',
        force_preflight: true,
      })
      setDispatchResult({ payload, context: { commandFamily: 'dispatch' } })
      setLiveDispatchProjectId('')
      setLiveDispatchSignature('')
      setSelection(null)
      void query.refetch()
    } catch (error) {
      setDispatchResult({ payload: { ok: false, reason: error instanceof Error ? error.message : String(error) }, context: { commandFamily: 'dispatch' } })
    } finally {
      setDispatchBusy(false)
    }
  }
  return (
    <>
      <PageShell title="Queue" subtitle="Bounded queue rows from /control/api/v1/queue. No frontend lifecycle inference." action={<PageRefreshAction generatedAt={query.data?.generated_at} isFetching={query.isFetching} onRefresh={() => { void query.refetch() }} />}>
        <FilterBar state={filters} statusOptions={[{ label: 'all statuses', value: '' }, { label: 'queued', value: 'queued' }, { label: 'active', value: 'active' }, { label: 'blocked', value: 'blocked' }, { label: 'completed', value: 'completed' }]} onApply={(next) => { setFilters(next); replaceRouteHash(queueHash(next)) }} onReset={() => { const next = { search: '', status: route.status, pageSize: '50', cursor: '' }; setFilters(next); replaceRouteHash(queueHash(next)) }} onNext={() => setFilters({ ...filters, cursor: query.data?.page?.next_cursor || '' })} page={query.data?.page} />
        <section className="queue-command-card">
          <div>
            <p className="eyebrow">Selected queue row</p>
            <h2>{selectedProjectId || 'No row selected'}</h2>
            <p>{selectedDispatchReason(selection)}</p>
          </div>
          <div className="action-row">
            <button className="secondary-button" type="button" disabled={!canDryRunSelected || dispatchBusy} onClick={dryRunSelectedDispatch}>
              {dispatchBusy ? 'Checking…' : 'Check selected dispatch'}
            </button>
            <button className="primary-button" type="button" disabled={!canLiveDispatchSelected || dispatchBusy} onClick={liveDispatchSelected}>
              Dispatch selected project
            </button>
          </div>
          {dispatchDisabledReason ? <p className="primary-action-disabled-reason">{dispatchDisabledReason}</p> : null}
        </section>
        <CommandResultCard result={dispatchResult} stale={staleDispatchReady} />
        <DataTable rows={query.data?.rows || []} columns={['project_id', 'status', 'lane', 'machine_target', 'title', 'updated_at']} empty="No queue rows match this filter." cellHref={detailCellHref} onSelectRow={(row) => { setDispatchResult(null); setLiveDispatchProjectId(''); setLiveDispatchSignature(''); setSelection({ kind: 'project', id: String(row.project_id || ''), row }) }} />
        <DetailPanel selection={selection} onClose={() => setSelection(null)} />
      </PageShell>
      {dialog}
    </>
  )
}

export function ProjectsPage({ route }: { route: Extract<DashboardRoute, { page: 'projects' }> }) {
  const [selection, setSelection] = useState<DetailSelection | null>(null)
  const [filters, setFilters] = useState<FilterState>({ search: route.search || '', status: route.status, pageSize: '50', cursor: '' })
  useEffect(() => {
    setFilters((current) => current.status === route.status && current.search === route.search ? current : { ...current, status: route.status, search: route.search || '', cursor: '' })
    setSelection(null)
  }, [route.search, route.status])
  const params = withCommonParams(filters, 'recent')
  const query = useQuery({ queryKey: ['projects', filters], queryFn: () => apiGet<PageResponse>(`/control/api/v1/projects?${params}`) })
  if (query.isLoading) return <LoadingCard label="projects" />
  if (query.isError) return <ErrorCard error={query.error} />
  return (
    <PageShell title="Projects" subtitle="Project discovery from /control/api/v1/projects. Bounded, searchable, and detail-backed." action={<PageRefreshAction generatedAt={query.data?.generated_at} isFetching={query.isFetching} onRefresh={() => { void query.refetch() }} />}>
      <FilterBar state={filters} statusOptions={[{ label: 'all project states', value: '' }, { label: 'testing', value: 'testing' }, { label: 'exploring', value: 'exploring' }, { label: 'queued', value: 'queued' }, { label: 'running', value: 'running' }, { label: 'completed', value: 'completed' }, { label: 'blocked', value: 'blocked' }]} onApply={(next) => { setFilters(next); replaceRouteHash(statusHash('#projects', 'status', next)) }} onReset={() => { const next = { search: '', status: route.status, pageSize: '50', cursor: '' }; setFilters(next); replaceRouteHash(statusHash('#projects', 'status', next)) }} onNext={() => setFilters({ ...filters, cursor: query.data?.page?.next_cursor || '' })} page={query.data?.page} />
      <DataTable rows={query.data?.rows || []} columns={['project_id', 'project_name', 'origin_idea_status', 'queue_status', 'latest_run_state', 'related_paper_status', 'updated_at']} empty="No projects match this filter." cellHref={detailCellHref} onSelectRow={(row) => setSelection({ kind: 'project', id: String(row.project_id || ''), row })} />
      <DetailPanel selection={selection} onClose={() => setSelection(null)} />
    </PageShell>
  )
}

export function RunsPage({ route }: { route: Extract<DashboardRoute, { page: 'runs' }> }) {
  const [selection, setSelection] = useState<DetailSelection | null>(null)
  const [filters, setFilters] = useState<FilterState>({ search: route.search || '', status: route.state, pageSize: '50', cursor: '' })
  useEffect(() => {
    setFilters((current) => current.status === route.state && current.search === route.search ? current : { ...current, status: route.state, search: route.search || '', cursor: '' })
    setSelection(null)
  }, [route.search, route.state])
  const params = withRunParams(filters)
  const query = useQuery({ queryKey: ['runs', filters], queryFn: () => apiGet<PageResponse>(`/control/api/v1/runs?${params}`) })
  if (query.isLoading) return <LoadingCard label="runs" />
  if (query.isError) return <ErrorCard error={query.error} />
  return (
    <PageShell title="Runs" subtitle="Active and historical run rows from /control/api/v1/runs. This is the V2 owner for active-work inspection." action={<PageRefreshAction generatedAt={query.data?.generated_at} isFetching={query.isFetching} onRefresh={() => { void query.refetch() }} />}>
      <FilterBar state={filters} statusOptions={[{ label: 'all run states', value: '' }, { label: 'running', value: 'running' }, { label: 'dispatching', value: 'dispatching' }, { label: 'awaiting wake', value: 'awaiting_wake' }, { label: 'dispatch error', value: 'dispatch_error' }, { label: 'completed', value: 'completed' }, { label: 'wake ready', value: 'wake_ready' }]} onApply={(next) => { setFilters(next); replaceRouteHash(statusHash(next.status ? `#runs:${encodeURIComponent(next.status)}` : '#runs', '', { ...next, status: '' })) }} onReset={() => { const next = { search: '', status: route.state, pageSize: '50', cursor: '' }; setFilters(next); replaceRouteHash(statusHash(next.status ? `#runs:${encodeURIComponent(next.status)}` : '#runs', '', { ...next, status: '' })) }} onNext={() => setFilters({ ...filters, cursor: query.data?.page?.next_cursor || '' })} page={query.data?.page} />
      <DataTable rows={query.data?.rows || []} columns={['run_id', 'project_id', 'state', 'gate_state', 'dispatch_mode', 'current_activity', 'updated_at']} empty="No run rows match this filter." cellHref={detailCellHref} onSelectRow={(row) => setSelection({ kind: 'run', id: String(row.run_id || ''), row })} />
      <DetailPanel selection={selection} onClose={() => setSelection(null)} />
    </PageShell>
  )
}

export function PapersPage({ route }: { route: Extract<DashboardRoute, { page: 'papers' }> }) {
  const [selection, setSelection] = useState<DetailSelection | null>(null)
  const [filters, setFilters] = useState<FilterState>({ search: route.search || '', status: route.status, pageSize: '50', cursor: '' })
  useEffect(() => {
    setFilters((current) => current.status === route.status && current.search === route.search ? current : { ...current, status: route.status, search: route.search || '', cursor: '' })
    setSelection(null)
  }, [route.search, route.status])
  const params = withCommonParams(filters, 'recent')
  const query = useQuery({ queryKey: ['papers', filters], queryFn: () => apiGet<PageResponse>(`/control/api/v1/papers?${params}`) })
  if (query.isLoading) return <LoadingCard label="papers" />
  if (query.isError) return <ErrorCard error={query.error} />
  return (
    <PageShell title="Papers" subtitle="Paper pipeline rows from /control/api/v1/papers." action={<PageRefreshAction generatedAt={query.data?.generated_at} isFetching={query.isFetching} onRefresh={() => { void query.refetch() }} />}>
      <FilterBar state={filters} statusOptions={[{ label: 'all paper statuses', value: '' }, { label: 'publication draft', value: 'publication_draft' }, { label: 'draft review', value: 'draft_review' }, { label: 'archived', value: 'archived' }]} onApply={(next) => { setFilters(next); replaceRouteHash(statusHash('#papers', 'status', next)) }} onReset={() => { const next = { search: '', status: route.status, pageSize: '50', cursor: '' }; setFilters(next); replaceRouteHash(statusHash('#papers', 'status', next)) }} onNext={() => setFilters({ ...filters, cursor: query.data?.page?.next_cursor || '' })} page={query.data?.page} />
      <DataTable rows={query.data?.rows || []} columns={['paper_id', 'project_id', 'status', 'title', 'artifact_dir', 'updated_at']} empty="No paper rows match this filter." cellHref={detailCellHref} onSelectRow={(row) => setSelection({ kind: 'paper', id: String(row.paper_id || ''), row })} />
      <DetailPanel selection={selection} onClose={() => setSelection(null)} />
    </PageShell>
  )
}

export function CorpusPage({ route }: { route?: Extract<DashboardRoute, { page: 'corpus' }> }) {
  const [selection, setSelection] = useState<DetailSelection | null>(null)
  const [filters, setFilters] = useState<FilterState>({ search: route?.search || '', status: route?.status || 'publication_draft', pageSize: '50', cursor: '' })
  useEffect(() => {
    const nextSearch = route?.search || ''
    const nextStatus = route?.status || 'publication_draft'
    setFilters((current) => current.search === nextSearch && current.status === nextStatus ? current : { ...current, search: nextSearch, status: nextStatus, cursor: '' })
    setSelection(null)
  }, [route?.search, route?.status])
  const params = withCommonParams(filters, 'recent')
  const overview = useQuery({ queryKey: ['corpus', 'overview'], queryFn: () => apiGet<OverviewLite>('/control/api/v1/overview?active_limit=1&event_limit=1') })
  const query = useQuery({ queryKey: ['corpus', filters], queryFn: () => apiGet<PageResponse>(`/control/api/v1/papers?${params}`) })
  if (query.isLoading) return <LoadingCard label="corpus import" />
  if (query.isError) return <ErrorCard error={query.error} />
  const pipeline = overview.data?.paper_pipeline || {}
  const publishReady = pipeline.publish_ready ?? pipeline.missing_from_corpus ?? 0
  const imported = pipeline.published_imported ?? 0
  const publicationReady = pipeline.publication_ready_total ?? 0
  const validationDetail = publishReady > 0
    ? 'Import validation needs corpus autopilot.'
    : 'Corpus import ledger has no missing finalized drafts.'
  return (
    <PageShell title="Corpus import" subtitle="Publication-ready paper rows and corpus-import ledger status. Publish/import work stays scoped to finalized drafts missing corpus import." action={<PageRefreshAction generatedAt={query.data?.generated_at} isFetching={query.isFetching || overview.isFetching} onRefresh={() => { void query.refetch(); void overview.refetch() }} />}>
      <section className="count-grid" aria-label="Corpus import summary">
        <CountCard label="Missing corpus import" value={publishReady} detail="Finalized publication drafts without corpus-import ledger rows." />
        <CountCard label="Already imported" value={imported} detail="Publication-ready drafts already recorded in corpus_imports." />
        <CountCard label="Publication-ready total" value={publicationReady} detail="Finalized drafts whether imported or still missing import." />
        <CountCard label="Import validation" value={publishReady > 0 ? 'pending' : 'clean'} detail={validationDetail} />
      </section>
      <FilterBar state={filters} statusOptions={[{ label: 'publication draft', value: 'publication_draft' }, { label: 'draft review', value: 'draft_review' }, { label: 'archived', value: 'archived' }, { label: 'all paper statuses', value: '' }]} onApply={(next) => { setFilters(next); replaceRouteHash(statusHash('#corpus', 'status', next)) }} onReset={() => { const next = { search: '', status: route?.status || 'publication_draft', pageSize: '50', cursor: '' }; setFilters(next); replaceRouteHash(statusHash('#corpus', 'status', next)) }} onNext={() => setFilters({ ...filters, cursor: query.data?.page?.next_cursor || '' })} page={query.data?.page} />
      <DataTable rows={query.data?.rows || []} columns={['paper_id', 'project_id', 'status', 'corpus_imported', 'corpus_import_id', 'title', 'updated_at']} empty="No corpus import rows match this filter." cellHref={detailCellHref} onSelectRow={(row) => setSelection({ kind: 'paper', id: String(row.paper_id || ''), row })} />
      <DetailPanel selection={selection} onClose={() => setSelection(null)} />
    </PageShell>
  )
}


type IntakeResponse = {
  generated_at?: string
  latest_sync?: Record<string, unknown> | null
  projection_counts?: Record<string, number>
  queued_projection?: Record<string, unknown>[]
  skipped_reasons?: Record<string, number>
  recent_events?: Record<string, unknown>[]
}

function IntakeIdeaDetail({ row, ideaId, onClose }: { row: Record<string, unknown> | null; ideaId?: string; onClose: () => void }) {
  if (!row && ideaId) {
    return (
      <section className="detail-panel" aria-label="Intake idea detail">
        <div className="detail-panel-head">
          <div>
            <p className="eyebrow">Intake idea detail</p>
            <h2>Idea detail</h2>
            <span className="detail-id-chip" title={ideaId}>{shortId(ideaId)}</span>
          </div>
          <button className="secondary-button" type="button" onClick={onClose}>Close</button>
        </div>
        <section className="detail-summary">
          <p>Idea {ideaId} is not present in the bounded intake projection returned by /control/api/intake/ideas.</p>
        </section>
      </section>
    )
  }
  if (!row) return null
  const operatorSummary = deriveIntakeIdeaOperatorSummary(row)
  return (
    <section className="detail-panel" aria-label="Intake idea detail">
      <div className="detail-panel-head">
        <div>
          <p className="eyebrow">Intake idea detail</p>
          <h2>{String(row.title || row.idea_id || 'Selected idea')}</h2>
          <span className="detail-id-chip" title={String(row.idea_id || '')}>{shortId(String(row.idea_id || ''))}</span>
        </div>
        <button className="secondary-button" type="button" onClick={onClose}>Close</button>
      </div>
      <section className="detail-summary">
        <div className="detail-entity-links" aria-label="Related entity links">
          {operatorSummary.entityLinks.map((link) => (
            <a key={`${link.kind}-${link.id}`} className="detail-id-chip detail-id-chip--link" href={dashboardV2Href(`#${link.kind}:${encodeURIComponent(link.id)}`)} title={link.id}>
              {link.kind}: {link.label}
            </a>
          ))}
        </div>
        <section className="detail-operator-summary" aria-label="Idea operator summary">
          <div>
            <p className="eyebrow">Current state</p>
            <strong>{operatorSummary.state}</strong>
            <span>{operatorSummary.context}</span>
          </div>
          <div>
            <p className="eyebrow">Next safe action</p>
            <span>{operatorSummary.next}</span>
          </div>
        </section>
        <section className="detail-operator-questions" aria-label="Operator questions">
          {operatorSummary.sections.map((section) => (
            <article key={section.title} className="detail-operator-question">
              <h4>{section.title}</h4>
              <dl className="detail-field-grid">
                {section.answers.map((answer) => (
                  <div key={`${section.title}-${answer.label}`} className="detail-field">
                    <dt>{answer.label}</dt>
                    <dd>{answer.value}</dd>
                  </div>
                ))}
              </dl>
            </article>
          ))}
          {operatorSummary.actionNeeded ? (
            <article className="detail-operator-question detail-operator-question--attention">
              <h4>Action needed now</h4>
              <p>{operatorSummary.actionNeeded}</p>
            </article>
          ) : null}
        </section>
        <details className="raw-details">
          <summary>Raw intake row</summary>
          <pre className="json-block">{JSON.stringify(row, null, 2)}</pre>
        </details>
      </section>
    </section>
  )
}

function intakeCellHref(row: Record<string, unknown>, column: string): string | undefined {
  if (column !== 'idea_id') return undefined
  const ideaId = String(row.idea_id || '')
  return ideaId ? dashboardV2Href(`#idea:${encodeURIComponent(ideaId)}`) : undefined
}

export function IntakePage({ route }: { route?: Extract<DashboardRoute, { page: 'intake' }> }) {
  const [selection, setSelection] = useState<Record<string, unknown> | null>(null)
  const query = useQuery({ queryKey: ['intake'], queryFn: () => apiGet<IntakeResponse>('/control/api/intake/ideas?page_size=100') })
  if (query.isLoading) return <LoadingCard label="ideas intake" />
  if (query.isError) return <ErrorCard error={query.error} />
  const data = query.data || {}
  const counts = data.projection_counts || {}
  const skipped = Object.entries(data.skipped_reasons || {}).map(([reason, count]) => ({ reason, count }))
  const latestSync = data.latest_sync ? [data.latest_sync] : []
  const routeIdeaId = route?.ideaId || ''
  const rows = data.queued_projection || []
  const selectedRow = selection || rows.find((row) => String(row.idea_id || '') === routeIdeaId) || null
  return (
    <PageShell title="Ideas intake" subtitle="Supabase-native idea workbench from /control/api/intake/ideas. Notion fields are provenance only." action={<PageRefreshAction generatedAt={data.generated_at} isFetching={query.isFetching} onRefresh={() => { setSelection(null); void query.refetch() }} refreshLabel="Refresh intake" />}>
      <section className="count-grid">
        {Object.entries(counts).slice(0, 8).map(([key, value]) => (
          <div key={key} className="count-card">
            <div>{String(value)}</div>
            <div>{key.replaceAll('_', ' ')}</div>
          </div>
        ))}
      </section>
      <section className="result-card">
        <h2>Latest intake sync</h2>
        <DataTable rows={latestSync} columns={['source', 'status', 'observed_at', 'authority']} empty="No intake sync observation returned." />
      </section>
      <section className="result-card">
        <h2>Skipped reasons</h2>
        <DataTable rows={skipped} columns={['reason', 'count']} empty="No skipped intake rows returned." />
      </section>
      <DataTable rows={rows} columns={['idea_id', 'title', 'idea_status', 'queue_status', 'next_action_hint', 'paper_status', 'source_kind', 'updated_at']} empty="No intake idea rows returned." cellHref={intakeCellHref} onSelectRow={setSelection} />
      <IntakeIdeaDetail row={selectedRow} ideaId={routeIdeaId} onClose={() => setSelection(null)} />
    </PageShell>
  )
}

export function EventsPage({ route }: { route?: Extract<DashboardRoute, { page: 'events' }> }) {
  const [selection, setSelection] = useState<DetailSelection | null>(null)
  const [filters, setFilters] = useState<FilterState>({ search: route?.search || '', status: route?.eventType || '', pageSize: '50', cursor: '' })
  useEffect(() => {
    const nextSearch = route?.search || ''
    const nextStatus = route?.eventType || ''
    setFilters((current) => current.search === nextSearch && current.status === nextStatus ? current : { ...current, search: nextSearch, status: nextStatus, cursor: '' })
    setSelection(null)
  }, [route?.eventType, route?.search])
  const params = new URLSearchParams({ page_size: filters.pageSize, sort: 'recent' })
  if (filters.status) params.set('event_type', filters.status)
  if (filters.search) params.set('search', filters.search)
  if (filters.cursor) params.set('cursor', filters.cursor)
  const query = useQuery({ queryKey: ['events', filters], queryFn: () => apiGet<PageResponse>(`/control/api/v1/events?${params}`) })
  if (query.isLoading) return <LoadingCard label="events" />
  if (query.isError) return <EventsErrorCard error={query.error} onRetry={() => { void query.refetch() }} />
  return (
    <PageShell title="Events" subtitle="Recent formatted control-plane events from /control/api/v1/events." action={<PageRefreshAction generatedAt={query.data?.generated_at} isFetching={query.isFetching} onRefresh={() => { void query.refetch() }} />}>
      <FilterBar state={filters} statusOptions={[{ label: 'all event types', value: '' }, { label: 'Queue Alert', value: 'Queue Alert' }, { label: 'worker.callback', value: 'worker.callback' }, { label: 'paper.drafted', value: 'paper.drafted' }, { label: 'research.run_cycle.live', value: 'research.run_cycle.live' }]} onApply={(next) => { setFilters(next); replaceRouteHash(statusHash('#events', 'event_type', next)) }} onReset={() => { const next = { search: '', status: '', pageSize: '50', cursor: '' }; setFilters(next); replaceRouteHash(statusHash('#events', 'event_type', next)) }} onNext={() => setFilters({ ...filters, cursor: query.data?.page?.next_cursor || '' })} page={query.data?.page} />
      <DataTable rows={query.data?.rows || []} columns={['id', 'entity_type', 'entity_id', 'event_type', 'created_at', 'summary']} empty="No recent events returned." cellHref={detailCellHref} onSelectRow={(row) => setSelection({ kind: 'event', id: String(row.id || row.event_id || ''), row })} />
      <DetailPanel selection={selection} onClose={() => setSelection(null)} />
    </PageShell>
  )
}

function boolText(value: unknown): string {
  if (value === true) return 'yes'
  if (value === false) return 'no'
  return '—'
}

function mibText(value: unknown): string {
  return typeof value === 'number' ? `${value.toFixed(1)} MiB` : '—'
}

function latestObservationText(value: string | null | undefined): string {
  if (!value) return 'No route observation sample available.'
  try {
    const parsed = JSON.parse(value) as unknown
    return JSON.stringify(parsed, null, 2)
  } catch {
    return value
  }
}

export function ObservabilityPage() {
  const health = useQuery({ queryKey: ['observability', 'health'], queryFn: () => apiGet<ObservabilityHealth>('/control/api/v1/observability/health') })
  const memory = useQuery({ queryKey: ['observability', 'memory'], queryFn: () => apiGet<ObservabilityMemory>('/control/api/v1/observability/memory') })
  if (health.isLoading || memory.isLoading) return <LoadingCard label="observability" />
  if (health.isError) return <ErrorCard error={health.error} />
  if (memory.isError) return <ErrorCard error={memory.error} />
  const healthData = health.data || {}
  const memoryData = memory.data || {}
  const generatedAt = `health ${healthData.generated_at || 'unknown'} · memory ${memoryData.generated_at || 'unknown'}`
  return (
    <PageShell title="Observability" subtitle="Controller process and route-observability state from bounded V1 read models." action={<PageRefreshAction generatedAt={generatedAt} isFetching={health.isFetching || memory.isFetching} onRefresh={() => { void health.refetch(); void memory.refetch() }} refreshLabel="Refresh observability" />}>
      <section className="detail-summary">
        <p className="eyebrow">Controller memory</p>
        <h2>{memoryData.memory_warn ? 'Memory warning active' : 'Memory is inside configured threshold'}</h2>
        <dl className="detail-field-grid">
          <div className="detail-field"><dt>rss</dt><dd>{mibText(memoryData.rss_mib)}</dd></div>
          <div className="detail-field"><dt>peak rss</dt><dd>{mibText(memoryData.peak_rss_mib)}</dd></div>
          <div className="detail-field"><dt>warn threshold</dt><dd>{mibText(memoryData.warn_threshold_mib)}</dd></div>
          <div className="detail-field"><dt>warning</dt><dd>{boolText(memoryData.memory_warn)}</dd></div>
        </dl>
      </section>
      <section className="detail-summary">
        <p className="eyebrow">Route observability</p>
        <h2>{healthData.route_observability_enabled ? 'Route logging enabled' : 'Route logging disabled'}</h2>
        <dl className="detail-field-grid">
          <div className="detail-field"><dt>enabled</dt><dd>{boolText(healthData.route_observability_enabled)}</dd></div>
          <div className="detail-field"><dt>custom log path</dt><dd>{boolText(healthData.route_observability_log_configured)}</dd></div>
          <div className="detail-field"><dt>health sampled</dt><dd>{healthData.generated_at || '—'}</dd></div>
          <div className="detail-field"><dt>memory sampled</dt><dd>{memoryData.generated_at || '—'}</dd></div>
        </dl>
        <details className="raw-details">
          <summary>Latest route observation</summary>
          <pre className="json-block">{latestObservationText(healthData.latest_route_observation)}</pre>
        </details>
      </section>
    </PageShell>
  )
}
