import { apiGet } from '../api/client'
import { useQuery } from '@tanstack/react-query'

export type DetailKind = 'project' | 'paper' | 'event'

export type DetailSelection = {
  kind: DetailKind
  id: string
  row?: Record<string, unknown>
}

type Field = { label: string; value: unknown }

function endpoint(selection: DetailSelection): string | null {
  if (selection.kind === 'project') return `/control/api/v1/projects/${encodeURIComponent(selection.id)}`
  if (selection.kind === 'paper') return `/control/api/v1/papers/${encodeURIComponent(selection.id)}`
  return null
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
}

function firstValue(...values: unknown[]): unknown {
  return values.find((value) => value !== null && value !== undefined && value !== '')
}

function stringifyValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  if (typeof value === 'boolean') return value ? 'yes' : 'no'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

function detailTitle(kind: DetailKind, payload: Record<string, unknown>, fallbackId: string): string {
  const project = record(payload.project)
  const paper = record(payload.paper)
  return stringifyValue(firstValue(
    project.project_name,
    project.title,
    paper.paper_title,
    paper.title,
    payload.title,
    payload.summary,
    payload.event_type,
    fallbackId,
  ))
}

function detailFields(kind: DetailKind, payload: Record<string, unknown>, fallbackId: string): Field[] {
  const project = record(payload.project)
  const paper = record(payload.paper)
  const queue = record(payload.queue)
  if (kind === 'project') {
    return [
      { label: 'project id', value: firstValue(payload.project_id, project.project_id, fallbackId) },
      { label: 'status', value: firstValue(payload.status, queue.status, project.status) },
      { label: 'machine target', value: firstValue(payload.machine_target, queue.machine_target, project.machine_target) },
      { label: 'lane', value: firstValue(payload.lane, queue.lane, queue.machine_target) },
      { label: 'run id', value: firstValue(payload.run_id, queue.run_id, project.current_run_id) },
      { label: 'updated', value: firstValue(payload.updated_at, project.updated_at, queue.updated_at) },
    ]
  }
  if (kind === 'paper') {
    return [
      { label: 'paper id', value: firstValue(payload.paper_id, paper.paper_id, fallbackId) },
      { label: 'project id', value: firstValue(payload.project_id, paper.project_id) },
      { label: 'status', value: firstValue(payload.status, paper.status) },
      { label: 'artifact dir', value: firstValue(payload.artifact_dir, paper.artifact_dir) },
      { label: 'updated', value: firstValue(payload.updated_at, paper.updated_at) },
    ]
  }
  return [
    { label: 'event id', value: firstValue(payload.id, payload.event_id, fallbackId) },
    { label: 'event type', value: payload.event_type },
    { label: 'entity', value: firstValue(payload.entity_id, payload.project_id, payload.paper_id) },
    { label: 'created', value: payload.created_at },
    { label: 'summary', value: payload.summary },
  ]
}

function FieldGrid({ fields }: { fields: Field[] }) {
  const visible = fields.filter((field) => field.value !== null && field.value !== undefined && field.value !== '')
  if (!visible.length) return null
  return (
    <dl className="mt-5 grid gap-3 sm:grid-cols-2">
      {visible.map((field) => (
        <div key={field.label} className="rounded-2xl border border-zinc-800 bg-black/20 p-4">
          <dt className="text-xs font-bold uppercase tracking-[0.16em] text-zinc-500">{field.label}</dt>
          <dd className="mt-2 break-words text-sm font-semibold text-zinc-100">{stringifyValue(field.value)}</dd>
        </div>
      ))}
    </dl>
  )
}

function StructuredDetail({ kind, id, payload }: { kind: DetailKind; id: string; payload: Record<string, unknown> }) {
  const title = detailTitle(kind, payload, id)
  const summary = stringifyValue(firstValue(payload.summary, record(payload.project).abstract, record(payload.paper).summary, record(payload.paper).abstract))
  return (
    <div className="mt-4 overflow-auto pr-1">
      <section className="rounded-2xl border border-zinc-800 bg-zinc-900/60 p-5">
        <p className="text-xs font-bold uppercase tracking-[0.22em] text-sky-300">Structured summary</p>
        <h3 className="mt-2 text-2xl font-black text-white">{title}</h3>
        {summary !== '—' && summary !== title ? <p className="mt-3 text-sm leading-6 text-zinc-300">{summary}</p> : null}
        <FieldGrid fields={detailFields(kind, payload, id)} />
      </section>
      <details className="mt-4 rounded-2xl border border-dashed border-zinc-800 bg-black/20 p-4 text-zinc-300">
        <summary className="cursor-pointer text-sm font-bold text-zinc-200">Raw payload</summary>
        <pre className="mt-4 max-h-[42vh] overflow-auto rounded-xl bg-black/50 p-4 text-xs text-zinc-300">{JSON.stringify(payload, null, 2)}</pre>
      </details>
    </div>
  )
}

function DetailBody({ selection }: { selection: DetailSelection }) {
  const url = endpoint(selection)
  const query = useQuery({
    queryKey: ['detail', selection.kind, selection.id],
    queryFn: () => apiGet<Record<string, unknown>>(url || ''),
    enabled: Boolean(url),
    retry: false,
  })
  if (!url) return <StructuredDetail kind={selection.kind} id={selection.id} payload={selection.row || {}} />
  if (query.isLoading) return <div className="mt-4 rounded-2xl border border-zinc-800 bg-black/20 p-4 text-zinc-400">Loading detail…</div>
  if (query.isError) return <div className="mt-4 rounded-2xl border border-red-900 bg-red-950/40 p-4 text-red-100">Detail unavailable: {String(query.error.message)}</div>
  return <StructuredDetail kind={selection.kind} id={selection.id} payload={query.data || {}} />
}

export function DetailPanel({ selection, onClose }: { selection: DetailSelection | null; onClose: () => void }) {
  if (!selection) return null
  return (
    <aside className="fixed inset-y-0 right-0 z-40 flex w-full max-w-2xl flex-col border-l border-zinc-800 bg-zinc-950 p-5 shadow-2xl shadow-black/60" aria-label="Dashboard detail panel">
      <div className="flex items-start justify-between gap-4 border-b border-zinc-800 pb-4">
        <div>
          <p className="text-xs font-bold uppercase tracking-[0.24em] text-sky-300">{selection.kind} detail</p>
          <h2 className="mt-2 text-xl font-black text-white">{selection.id}</h2>
        </div>
        <button className="rounded-lg border border-zinc-700 px-3 py-2 text-sm font-bold text-white" type="button" onClick={onClose}>Close</button>
      </div>
      <DetailBody selection={selection} />
    </aside>
  )
}
