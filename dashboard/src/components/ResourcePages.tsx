import { FormEvent, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { apiGet, apiPost } from '../api/client'
import type { DashboardRoute } from '../routes'
import { DataTable } from './DataTable'
import { DetailPanel } from './DetailPanel'

type PageMeta = { next_cursor?: string; has_more?: boolean; returned?: number; page_size?: number }
type PageResponse = { rows?: Record<string, unknown>[]; counts?: Record<string, unknown>; generated_at?: string; page?: PageMeta }
type ObservabilityHealth = { generated_at?: string; route_observability_enabled?: boolean; route_observability_log_configured?: boolean; latest_route_observation?: string | null }
type ObservabilityMemory = { generated_at?: string; rss_mib?: number | null; peak_rss_mib?: number | null; warn_threshold_mib?: number | null; memory_warn?: boolean; route_observability_enabled?: boolean }
type DetailSelection = { kind: 'project' | 'run' | 'paper' | 'event'; id: string; row?: Record<string, unknown> }
type FilterState = { search: string; status: string; pageSize: string; cursor: string }
type CommandResult = { title: string; payload: Record<string, unknown> }

function PageShell({ title, subtitle, children }: { title: string; subtitle: string; children: React.ReactNode }) {
  return (
    <section className="page-stack">
      <div className="page-hero">
        <p className="eyebrow">Dashboard V2</p>
        <h1>{title}</h1>
        <p>{subtitle}</p>
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

function FilterBar({ state, statusOptions, onApply, onNext, onReset, page }: { state: FilterState; statusOptions: { label: string; value: string }[]; onApply: (next: FilterState) => void; onNext: () => void; onReset: () => void; page?: PageMeta }) {
  const [draft, setDraft] = useState(state)
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

function withRunParams(state: FilterState): URLSearchParams {
  const params = new URLSearchParams({ page_size: state.pageSize, sort: 'recent' })
  if (state.status) params.set('state', state.status)
  if (state.search) params.set('search', state.search)
  if (state.cursor) params.set('cursor', state.cursor)
  return params
}

function selectedDispatchReason(selection: DetailSelection | null): string {
  if (!selection) return 'Select a queued row to check whether that exact candidate can dispatch.'
  if (!selection.id) return 'Selected row has no project id.'
  const status = String(selection.row?.status || '').toLowerCase()
  if (status !== 'queued') return `Selected row is ${status || 'not queued'}.`
  return 'Dry-run checks /control/dispatch-one for the selected project only.'
}

function CommandResultCard({ result }: { result: CommandResult | null }) {
  if (!result) return null
  const reason = String(result.payload.reason || result.payload.detail || result.payload.action || 'Command completed.')
  return (
    <section className="result-card" aria-live="polite">
      <h3>{result.title}</h3>
      <p>{reason}</p>
      <pre>{JSON.stringify(result.payload, null, 2)}</pre>
    </section>
  )
}

export function QueuePage({ route }: { route: Extract<DashboardRoute, { page: 'queue' }> }) {
  const [selection, setSelection] = useState<DetailSelection | null>(null)
  const [dispatchResult, setDispatchResult] = useState<CommandResult | null>(null)
  const [dispatchBusy, setDispatchBusy] = useState(false)
  const [filters, setFilters] = useState<FilterState>({ search: '', status: route.status, pageSize: '50', cursor: '' })
  const params = withCommonParams(filters, 'priority')
  params.set('queue', 'all')
  const query = useQuery({ queryKey: ['queue', filters], queryFn: () => apiGet<PageResponse>(`/control/api/v1/queue?${params}`) })
  if (query.isLoading) return <LoadingCard label="queue" />
  if (query.isError) return <ErrorCard error={query.error} />
  const selectedProjectId = selection?.id || ''
  const selectedStatus = String(selection?.row?.status || '').toLowerCase()
  const canDryRunSelected = Boolean(selectedProjectId) && selectedStatus === 'queued'
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
      setDispatchResult({ title: 'Selected dispatch dry-run', payload })
    } catch (error) {
      setDispatchResult({ title: 'Selected dispatch dry-run failed', payload: { ok: false, reason: error instanceof Error ? error.message : String(error) } })
    } finally {
      setDispatchBusy(false)
    }
  }
  return (
    <PageShell title="Queue" subtitle="Bounded queue rows from /control/api/v1/queue. No frontend lifecycle inference.">
      <FilterBar state={filters} statusOptions={[{ label: 'all statuses', value: '' }, { label: 'queued', value: 'queued' }, { label: 'active', value: 'active' }, { label: 'blocked', value: 'blocked' }, { label: 'completed', value: 'completed' }]} onApply={setFilters} onReset={() => setFilters({ search: '', status: route.status, pageSize: '50', cursor: '' })} onNext={() => setFilters({ ...filters, cursor: query.data?.page?.next_cursor || '' })} page={query.data?.page} />
      <section className="queue-command-card">
        <div>
          <p className="eyebrow">Selected queue row</p>
          <h2>{selectedProjectId || 'No row selected'}</h2>
          <p>{selectedDispatchReason(selection)}</p>
        </div>
        <button className="primary-button" type="button" disabled={!canDryRunSelected || dispatchBusy} onClick={dryRunSelectedDispatch}>
          {dispatchBusy ? 'Checking…' : 'Check selected dispatch'}
        </button>
      </section>
      <CommandResultCard result={dispatchResult} />
      <DataTable rows={query.data?.rows || []} columns={['project_id', 'status', 'lane', 'machine_target', 'title', 'updated_at']} empty="No queue rows match this filter." onSelectRow={(row) => { setDispatchResult(null); setSelection({ kind: 'project', id: String(row.project_id || ''), row }) }} />
      <DetailPanel selection={selection} onClose={() => setSelection(null)} />
    </PageShell>
  )
}

export function ProjectsPage({ route }: { route: Extract<DashboardRoute, { page: 'projects' }> }) {
  const [selection, setSelection] = useState<DetailSelection | null>(null)
  const [filters, setFilters] = useState<FilterState>({ search: '', status: route.status, pageSize: '50', cursor: '' })
  const params = withCommonParams(filters, 'recent')
  const query = useQuery({ queryKey: ['projects', filters], queryFn: () => apiGet<PageResponse>(`/control/api/v1/projects?${params}`) })
  if (query.isLoading) return <LoadingCard label="projects" />
  if (query.isError) return <ErrorCard error={query.error} />
  return (
    <PageShell title="Projects" subtitle="Project discovery from /control/api/v1/projects. Bounded, searchable, and detail-backed.">
      <FilterBar state={filters} statusOptions={[{ label: 'all project states', value: '' }, { label: 'testing', value: 'testing' }, { label: 'exploring', value: 'exploring' }, { label: 'queued', value: 'queued' }, { label: 'running', value: 'running' }, { label: 'completed', value: 'completed' }, { label: 'blocked', value: 'blocked' }]} onApply={setFilters} onReset={() => setFilters({ search: '', status: route.status, pageSize: '50', cursor: '' })} onNext={() => setFilters({ ...filters, cursor: query.data?.page?.next_cursor || '' })} page={query.data?.page} />
      <DataTable rows={query.data?.rows || []} columns={['project_id', 'project_name', 'origin_idea_status', 'queue_status', 'latest_run_state', 'related_paper_status', 'updated_at']} empty="No projects match this filter." onSelectRow={(row) => setSelection({ kind: 'project', id: String(row.project_id || ''), row })} />
      <DetailPanel selection={selection} onClose={() => setSelection(null)} />
    </PageShell>
  )
}

export function RunsPage({ route }: { route: Extract<DashboardRoute, { page: 'runs' }> }) {
  const [selection, setSelection] = useState<DetailSelection | null>(null)
  const [filters, setFilters] = useState<FilterState>({ search: '', status: route.state, pageSize: '50', cursor: '' })
  const params = withRunParams(filters)
  const query = useQuery({ queryKey: ['runs', filters], queryFn: () => apiGet<PageResponse>(`/control/api/v1/runs?${params}`) })
  if (query.isLoading) return <LoadingCard label="runs" />
  if (query.isError) return <ErrorCard error={query.error} />
  return (
    <PageShell title="Runs" subtitle="Active and historical run rows from /control/api/v1/runs. This is the V2 owner for active-work inspection.">
      <FilterBar state={filters} statusOptions={[{ label: 'all run states', value: '' }, { label: 'running', value: 'running' }, { label: 'dispatching', value: 'dispatching' }, { label: 'awaiting wake', value: 'awaiting_wake' }, { label: 'dispatch error', value: 'dispatch_error' }, { label: 'completed', value: 'completed' }, { label: 'wake ready', value: 'wake_ready' }]} onApply={setFilters} onReset={() => setFilters({ search: '', status: route.state, pageSize: '50', cursor: '' })} onNext={() => setFilters({ ...filters, cursor: query.data?.page?.next_cursor || '' })} page={query.data?.page} />
      <DataTable rows={query.data?.rows || []} columns={['run_id', 'project_id', 'state', 'gate_state', 'dispatch_mode', 'current_activity', 'updated_at']} empty="No run rows match this filter." onSelectRow={(row) => setSelection({ kind: 'run', id: String(row.run_id || ''), row })} />
      <DetailPanel selection={selection} onClose={() => setSelection(null)} />
    </PageShell>
  )
}

export function PapersPage({ route }: { route: Extract<DashboardRoute, { page: 'papers' }> }) {
  const [selection, setSelection] = useState<DetailSelection | null>(null)
  const [filters, setFilters] = useState<FilterState>({ search: '', status: route.status, pageSize: '50', cursor: '' })
  const params = withCommonParams(filters, 'recent')
  const query = useQuery({ queryKey: ['papers', filters], queryFn: () => apiGet<PageResponse>(`/control/api/v1/papers?${params}`) })
  if (query.isLoading) return <LoadingCard label="papers" />
  if (query.isError) return <ErrorCard error={query.error} />
  return (
    <PageShell title="Papers" subtitle="Paper pipeline rows from /control/api/v1/papers.">
      <FilterBar state={filters} statusOptions={[{ label: 'all paper statuses', value: '' }, { label: 'publication draft', value: 'publication_draft' }, { label: 'draft review', value: 'draft_review' }, { label: 'archived', value: 'archived' }]} onApply={setFilters} onReset={() => setFilters({ search: '', status: route.status, pageSize: '50', cursor: '' })} onNext={() => setFilters({ ...filters, cursor: query.data?.page?.next_cursor || '' })} page={query.data?.page} />
      <DataTable rows={query.data?.rows || []} columns={['paper_id', 'project_id', 'status', 'title', 'artifact_dir', 'updated_at']} empty="No paper rows match this filter." onSelectRow={(row) => setSelection({ kind: 'paper', id: String(row.paper_id || ''), row })} />
      <DetailPanel selection={selection} onClose={() => setSelection(null)} />
    </PageShell>
  )
}

export function CorpusPage() {
  const [selection, setSelection] = useState<DetailSelection | null>(null)
  const [filters, setFilters] = useState<FilterState>({ search: '', status: 'publication_draft', pageSize: '50', cursor: '' })
  const params = withCommonParams(filters, 'recent')
  const query = useQuery({ queryKey: ['corpus', filters], queryFn: () => apiGet<PageResponse>(`/control/api/v1/papers?${params}`) })
  if (query.isLoading) return <LoadingCard label="corpus import" />
  if (query.isError) return <ErrorCard error={query.error} />
  return (
    <PageShell title="Corpus import" subtitle="Publication-ready paper rows and corpus-import ledger status. Publish/import work stays scoped to finalized drafts missing corpus import.">
      <FilterBar state={filters} statusOptions={[{ label: 'publication draft', value: 'publication_draft' }, { label: 'draft review', value: 'draft_review' }, { label: 'archived', value: 'archived' }, { label: 'all paper statuses', value: '' }]} onApply={setFilters} onReset={() => setFilters({ search: '', status: 'publication_draft', pageSize: '50', cursor: '' })} onNext={() => setFilters({ ...filters, cursor: query.data?.page?.next_cursor || '' })} page={query.data?.page} />
      <DataTable rows={query.data?.rows || []} columns={['paper_id', 'project_id', 'status', 'corpus_imported', 'corpus_import_id', 'title', 'updated_at']} empty="No corpus import rows match this filter." onSelectRow={(row) => setSelection({ kind: 'paper', id: String(row.paper_id || ''), row })} />
      <DetailPanel selection={selection} onClose={() => setSelection(null)} />
    </PageShell>
  )
}

export function EventsPage() {
  const [selection, setSelection] = useState<DetailSelection | null>(null)
  const [filters, setFilters] = useState<FilterState>({ search: '', status: '', pageSize: '50', cursor: '' })
  const params = new URLSearchParams({ page_size: filters.pageSize, sort: 'recent' })
  if (filters.status) params.set('event_type', filters.status)
  if (filters.search) params.set('search', filters.search)
  if (filters.cursor) params.set('cursor', filters.cursor)
  const query = useQuery({ queryKey: ['events', filters], queryFn: () => apiGet<PageResponse>(`/control/api/v1/events?${params}`) })
  if (query.isLoading) return <LoadingCard label="events" />
  if (query.isError) return <ErrorCard error={query.error} />
  return (
    <PageShell title="Events" subtitle="Recent formatted control-plane events from /control/api/v1/events.">
      <FilterBar state={filters} statusOptions={[{ label: 'all event types', value: '' }, { label: 'Queue Alert', value: 'Queue Alert' }, { label: 'worker.callback', value: 'worker.callback' }, { label: 'paper.drafted', value: 'paper.drafted' }, { label: 'research.run_cycle.live', value: 'research.run_cycle.live' }]} onApply={setFilters} onReset={() => setFilters({ search: '', status: '', pageSize: '50', cursor: '' })} onNext={() => setFilters({ ...filters, cursor: query.data?.page?.next_cursor || '' })} page={query.data?.page} />
      <DataTable rows={query.data?.rows || []} columns={['id', 'entity_type', 'entity_id', 'event_type', 'created_at', 'summary']} empty="No recent events returned." onSelectRow={(row) => setSelection({ kind: 'event', id: String(row.id || row.event_id || ''), row })} />
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
  return (
    <PageShell title="Observability" subtitle="Controller process and route-observability state from bounded V1 read models.">
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
