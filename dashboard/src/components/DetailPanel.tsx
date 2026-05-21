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
    <dl className="detail-field-grid">
      {visible.map((field) => (
        <div key={field.label} className="detail-field">
          <dt>{field.label}</dt>
          <dd>{stringifyValue(field.value)}</dd>
        </div>
      ))}
    </dl>
  )
}

function StructuredDetail({ kind, id, payload }: { kind: DetailKind; id: string; payload: Record<string, unknown> }) {
  const title = detailTitle(kind, payload, id)
  const summary = stringifyValue(firstValue(payload.summary, record(payload.project).abstract, record(payload.paper).summary, record(payload.paper).abstract))
  return (
    <div className="detail-body">
      <section className="detail-summary">
        <p className="eyebrow">Structured summary</p>
        <h3>{title}</h3>
        {summary !== '—' && summary !== title ? <p>{summary}</p> : null}
        <FieldGrid fields={detailFields(kind, payload, id)} />
      </section>
      <details className="raw-details">
        <summary>Raw payload</summary>
        <pre className="json-block">{JSON.stringify(payload, null, 2)}</pre>
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
  if (query.isLoading) return <div className="state-card">Loading detail…</div>
  if (query.isError) return <div className="state-card state-card--error">Detail unavailable: {String(query.error.message)}</div>
  return <StructuredDetail kind={selection.kind} id={selection.id} payload={query.data || {}} />
}

export function DetailPanel({ selection, onClose }: { selection: DetailSelection | null; onClose: () => void }) {
  if (!selection) return null
  return (
    <aside className="detail-panel" aria-label="Dashboard detail panel">
      <div className="detail-panel-head">
        <div>
          <p className="eyebrow">{selection.kind} detail</p>
          <h2>{selection.id}</h2>
        </div>
        <button className="secondary-button" type="button" onClick={onClose}>Close</button>
      </div>
      <DetailBody selection={selection} />
    </aside>
  )
}
