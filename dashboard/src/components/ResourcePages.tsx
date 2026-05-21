import { FormEvent, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { apiGet } from '../api/client'
import type { DashboardRoute } from '../routes'
import { DataTable } from './DataTable'
import { DetailPanel } from './DetailPanel'

type PageMeta = { next_cursor?: string; has_more?: boolean; returned?: number; page_size?: number }
type PageResponse = { rows?: Record<string, unknown>[]; counts?: Record<string, unknown>; generated_at?: string; page?: PageMeta }
type DetailSelection = { kind: 'project' | 'run' | 'paper' | 'event'; id: string; row?: Record<string, unknown> }
type FilterState = { search: string; status: string; pageSize: string; cursor: string }

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

export function QueuePage({ route }: { route: Extract<DashboardRoute, { page: 'queue' }> }) {
  const [selection, setSelection] = useState<DetailSelection | null>(null)
  const [filters, setFilters] = useState<FilterState>({ search: '', status: route.status, pageSize: '50', cursor: '' })
  const params = withCommonParams(filters, 'priority')
  params.set('queue', 'all')
  const query = useQuery({ queryKey: ['queue', filters], queryFn: () => apiGet<PageResponse>(`/control/api/v1/queue?${params}`) })
  if (query.isLoading) return <LoadingCard label="queue" />
  if (query.isError) return <ErrorCard error={query.error} />
  return (
    <PageShell title="Queue" subtitle="Bounded queue rows from /control/api/v1/queue. No frontend lifecycle inference.">
      <FilterBar state={filters} statusOptions={[{ label: 'all statuses', value: '' }, { label: 'queued', value: 'queued' }, { label: 'active', value: 'active' }, { label: 'blocked', value: 'blocked' }, { label: 'completed', value: 'completed' }]} onApply={setFilters} onReset={() => setFilters({ search: '', status: route.status, pageSize: '50', cursor: '' })} onNext={() => setFilters({ ...filters, cursor: query.data?.page?.next_cursor || '' })} page={query.data?.page} />
      <DataTable rows={query.data?.rows || []} columns={['project_id', 'status', 'lane', 'machine_target', 'title', 'updated_at']} empty="No queue rows match this filter." onSelectRow={(row) => setSelection({ kind: 'project', id: String(row.project_id || ''), row })} />
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
