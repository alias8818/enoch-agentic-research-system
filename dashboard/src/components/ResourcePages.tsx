import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { apiGet } from '../api/client'
import type { DashboardRoute } from '../routes'
import { DataTable } from './DataTable'
import { DetailPanel } from './DetailPanel'

type PageResponse = { rows?: Record<string, unknown>[]; counts?: Record<string, unknown>; generated_at?: string }
type DetailSelection = { kind: 'project' | 'paper' | 'event'; id: string; row?: Record<string, unknown> }

function PageShell({ title, subtitle, children }: { title: string; subtitle: string; children: React.ReactNode }) {
  return (
    <section className="space-y-5">
      <div className="rounded-3xl border border-zinc-800 bg-zinc-950 p-6">
        <p className="text-xs font-bold uppercase tracking-[0.28em] text-sky-300">Dashboard V2</p>
        <h1 className="mt-2 text-3xl font-black text-white">{title}</h1>
        <p className="mt-2 text-sm text-zinc-400">{subtitle}</p>
      </div>
      {children}
    </section>
  )
}

function LoadingCard({ label }: { label: string }) {
  return <div className="rounded-2xl border border-zinc-800 bg-zinc-950 p-8 text-zinc-400">Loading {label}…</div>
}

function ErrorCard({ error }: { error: unknown }) {
  return <div className="rounded-2xl border border-red-900 bg-red-950/40 p-8 text-red-100">V2 data unavailable: {String(error instanceof Error ? error.message : error)}</div>
}

export function QueuePage({ route }: { route: Extract<DashboardRoute, { page: 'queue' }> }) {
  const [selection, setSelection] = useState<DetailSelection | null>(null)
  const params = new URLSearchParams({ queue: 'all', page_size: '50', sort: 'priority' })
  if (route.status) params.set('status', route.status)
  const query = useQuery({ queryKey: ['queue', route.status], queryFn: () => apiGet<PageResponse>(`/control/api/v1/queue?${params}`) })
  if (query.isLoading) return <LoadingCard label="queue" />
  if (query.isError) return <ErrorCard error={query.error} />
  return (
    <PageShell title="Queue" subtitle="Bounded queue rows from /control/api/v1/queue. No frontend lifecycle inference.">
      <DataTable rows={query.data?.rows || []} columns={['project_id', 'status', 'lane', 'machine_target', 'title', 'updated_at']} empty="No queue rows match this filter." onSelectRow={(row) => setSelection({ kind: 'project', id: String(row.project_id || ''), row })} />
      <DetailPanel selection={selection} onClose={() => setSelection(null)} />
    </PageShell>
  )
}

export function PapersPage({ route }: { route: Extract<DashboardRoute, { page: 'papers' }> }) {
  const [selection, setSelection] = useState<DetailSelection | null>(null)
  const params = new URLSearchParams({ page_size: '50', sort: 'recent' })
  if (route.status) params.set('status', route.status)
  const query = useQuery({ queryKey: ['papers', route.status], queryFn: () => apiGet<PageResponse>(`/control/api/v1/papers?${params}`) })
  if (query.isLoading) return <LoadingCard label="papers" />
  if (query.isError) return <ErrorCard error={query.error} />
  return (
    <PageShell title="Papers" subtitle="Paper pipeline rows from /control/api/v1/papers.">
      <DataTable rows={query.data?.rows || []} columns={['paper_id', 'project_id', 'status', 'title', 'artifact_dir', 'updated_at']} empty="No paper rows match this filter." onSelectRow={(row) => setSelection({ kind: 'paper', id: String(row.paper_id || ''), row })} />
      <DetailPanel selection={selection} onClose={() => setSelection(null)} />
    </PageShell>
  )
}

export function EventsPage() {
  const [selection, setSelection] = useState<DetailSelection | null>(null)
  const query = useQuery({ queryKey: ['events'], queryFn: () => apiGet<PageResponse>('/control/api/v1/events?page_size=50&sort=recent') })
  if (query.isLoading) return <LoadingCard label="events" />
  if (query.isError) return <ErrorCard error={query.error} />
  return (
    <PageShell title="Events" subtitle="Recent formatted control-plane events from /control/api/v1/events.">
      <DataTable rows={query.data?.rows || []} columns={['id', 'entity_type', 'entity_id', 'event_type', 'created_at', 'summary']} empty="No recent events returned." onSelectRow={(row) => setSelection({ kind: 'event', id: String(row.id || row.event_id || ''), row })} />
      <DetailPanel selection={selection} onClose={() => setSelection(null)} />
    </PageShell>
  )
}
