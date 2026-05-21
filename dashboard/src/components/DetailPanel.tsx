import { useState } from 'react'
import { apiGet } from '../api/client'
import { dashboardV2Href } from '../routes'
import { useQuery } from '@tanstack/react-query'

export type DetailKind = 'project' | 'run' | 'paper' | 'event'

export type DetailSelection = {
  kind: DetailKind
  id: string
  row?: Record<string, unknown>
}

type Field = { label: string; value: unknown }

function endpoint(selection: DetailSelection): string | null {
  if (selection.kind === 'project') return `/control/api/v1/projects/${encodeURIComponent(selection.id)}`
  if (selection.kind === 'run') return `/control/api/v1/runs/${encodeURIComponent(selection.id)}`
  if (selection.kind === 'paper') return `/control/api/v1/papers/${encodeURIComponent(selection.id)}`
  if (selection.kind === 'event') return `/control/api/v1/events?event_id=${encodeURIComponent(selection.id)}&include_payload=true&page_size=1&sort=recent`
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

function recordArray(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value) ? value.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object' && !Array.isArray(item)) : []
}

function rowTitle(row: Record<string, unknown>, fallback: string): string {
  return stringifyValue(firstValue(row.title, row.project_name, row.paper_title, row.summary, row.current_activity, row.event_type, fallback))
}

function RelatedSection({ title, rows, kind }: { title: string; rows: Record<string, unknown>[]; kind: 'run' | 'paper' | 'event' }) {
  if (!rows.length) return null
  return (
    <section className="detail-related">
      <h4>{title}</h4>
      <div className="detail-related-list">
        {rows.slice(0, 6).map((row, index) => {
          const id = stringifyValue(firstValue(row.run_id, row.paper_id, row.id, row.event_id, `row-${index + 1}`))
          const titleText = kind === 'run' ? id : rowTitle(row, id)
          const meta = stringifyValue(firstValue(row.state, row.status, row.event_type, row.updated_at, row.created_at))
          return (
            <a key={`${kind}-${id}-${index}`} className="detail-related-row detail-related-row--link" href={dashboardV2Href(`#${kind}:${encodeURIComponent(id)}`)}>
              <strong>{titleText}</strong>
              {meta !== '—' && meta !== titleText ? <span>{meta}</span> : null}
            </a>
          )
        })}
      </div>
    </section>
  )
}

function RelatedDetails({ payload }: { payload: Record<string, unknown> }) {
  const runs = recordArray(payload.runs)
  const papers = recordArray(payload.papers)
  const events = recordArray(payload.events)
  if (!runs.length && !papers.length && !events.length) return null
  return (
    <section className="detail-related-group" aria-label="Related detail records">
      <RelatedSection title="Related runs" rows={runs} kind="run" />
      <RelatedSection title="Related papers" rows={papers} kind="paper" />
      <RelatedSection title="Recent events" rows={events} kind="event" />
    </section>
  )
}

type ArtifactPreview = {
  field: string
  content?: string
  size_bytes?: number
  truncated?: boolean
  reason?: string
}

const artifactFields = [
  ['draft_markdown_path', 'draft markdown'],
  ['draft_latex_path', 'draft latex'],
  ['evidence_bundle_path', 'evidence bundle'],
  ['claim_ledger_path', 'claim ledger'],
  ['manifest_path', 'manifest'],
] as const

function PaperArtifacts({ id, payload }: { id: string; payload: Record<string, unknown> }) {
  const paper = record(payload.paper)
  const available = artifactFields.filter(([field]) => paper[field])
  const [preview, setPreview] = useState<ArtifactPreview | null>(null)
  const [pendingField, setPendingField] = useState<string>('')
  if (!available.length) return null

  async function loadArtifact(field: string) {
    setPendingField(field)
    try {
      const artifact = await apiGet<ArtifactPreview>(`/control/api/papers/${encodeURIComponent(id)}/artifact/${encodeURIComponent(field)}`)
      setPreview(artifact)
    } catch (error) {
      setPreview({ field, reason: error instanceof Error ? error.message : String(error) })
    } finally {
      setPendingField('')
    }
  }

  return (
    <section className="detail-artifacts" aria-label="Paper artifacts">
      <div>
        <p className="eyebrow">Paper artifacts</p>
        <h4>Preview generated files</h4>
      </div>
      <div className="artifact-button-row">
        {available.map(([field, label]) => (
          <button key={field} className="secondary-button" type="button" disabled={pendingField === field} onClick={() => { void loadArtifact(field) }}>
            Preview {label}
          </button>
        ))}
      </div>
      {preview ? (
        <section className="artifact-preview">
          <h5>Artifact preview</h5>
          <p>{preview.field}{preview.size_bytes ? ` · ${preview.size_bytes} bytes` : ''}{preview.truncated ? ' · truncated' : ''}</p>
          <pre className="json-block">{preview.reason || preview.content || ''}</pre>
        </section>
      ) : null}
    </section>
  )
}

function detailTitle(kind: DetailKind, payload: Record<string, unknown>, fallbackId: string): string {
  const project = record(payload.project)
  const run = record(payload.run)
  const paper = record(payload.paper)
  return stringifyValue(firstValue(
    project.project_name,
    project.title,
    run.project_name,
    run.run_id,
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
  const run = record(payload.run)
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
  if (kind === 'run') {
    return [
      { label: 'run id', value: firstValue(payload.run_id, run.run_id, fallbackId) },
      { label: 'project id', value: firstValue(payload.project_id, run.project_id, project.project_id) },
      { label: 'state', value: firstValue(payload.state, run.state) },
      { label: 'gate', value: firstValue(payload.gate_state, run.gate_state) },
      { label: 'dispatch', value: firstValue(payload.dispatch_mode, run.dispatch_mode) },
      { label: 'activity', value: firstValue(payload.current_activity, run.current_activity) },
      { label: 'updated', value: firstValue(payload.updated_at, run.updated_at) },
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
      {kind === 'paper' ? <PaperArtifacts id={id} payload={payload} /> : null}
      <RelatedDetails payload={payload} />
      <details className="raw-details">
        <summary>Raw payload</summary>
        <pre className="json-block">{JSON.stringify(payload, null, 2)}</pre>
      </details>
    </div>
  )
}

function DetailBody({ selection }: { selection: DetailSelection }) {
  const inlineRow = selection.row
  const hasInlineEvent = selection.kind === 'event' && inlineRow
  const url = endpoint(selection)
  const query = useQuery({
    queryKey: ['detail', selection.kind, selection.id],
    queryFn: () => apiGet<Record<string, unknown>>(url || ''),
    enabled: Boolean(url) && !hasInlineEvent,
    retry: false,
  })
  if (hasInlineEvent) {
    return <StructuredDetail kind={selection.kind} id={selection.id} payload={inlineRow} />
  }
  if (!url) return <StructuredDetail kind={selection.kind} id={selection.id} payload={selection.row || {}} />
  if (query.isLoading) return <div className="state-card">Loading detail…</div>
  if (query.isError) return <div className="state-card state-card--error">Detail unavailable: {String(query.error.message)}</div>
  if (selection.kind === 'event') {
    const rows = Array.isArray(query.data?.rows) ? query.data.rows : []
    return <StructuredDetail kind={selection.kind} id={selection.id} payload={record(rows[0])} />
  }
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

export function DetailPage({ selection }: { selection: DetailSelection }) {
  return (
    <section className="page-stack">
      <div className="page-hero">
        <p className="eyebrow">Dashboard V2 detail</p>
        <h1>{selection.kind}: {selection.id}</h1>
        <p>Direct detail route backed by the V1 read-model endpoint. No legacy dashboard fallback.</p>
      </div>
      <aside className="detail-panel detail-panel--page" aria-label="Dashboard detail page">
        <DetailBody selection={selection} />
      </aside>
    </section>
  )
}
