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

function kindLabel(kind: DetailKind): string {
  return `${kind[0].toUpperCase()}${kind.slice(1)} detail`
}

function shortId(value: string): string {
  if (value.length <= 30) return value
  return `${value.slice(0, 14)}…${value.slice(-10)}`
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

function detailStatus(kind: DetailKind, payload: Record<string, unknown>): { state: string; context: string; next: string } {
  const project = record(payload.project)
  const run = record(payload.run)
  const paper = record(payload.paper)
  const queue = record(payload.queue)
  if (kind === 'project') {
    const state = stringifyValue(firstValue(payload.status, queue.status, project.status, payload.queue_status, payload.origin_idea_status))
    const lane = stringifyValue(firstValue(payload.lane, queue.lane, payload.machine_target, queue.machine_target, project.machine_target))
    const runState = stringifyValue(firstValue(payload.latest_run_state, payload.run_state, run.state, queue.last_run_state))
    return {
      state,
      context: `Lane ${lane}; run ${runState}.`,
      next: state === 'queued'
        ? 'Check the lane card or selected dispatch dry-run before starting work.'
        : state === 'active' || runState === 'running'
          ? 'Open the current run and verify activity, gate state, and errors.'
          : 'Review recent events and paper status before taking a write or dispatch action.',
    }
  }
  if (kind === 'run') {
    const state = stringifyValue(firstValue(payload.state, run.state))
    const gate = stringifyValue(firstValue(payload.gate_state, run.gate_state))
    const activity = stringifyValue(firstValue(payload.current_activity, run.current_activity))
    return {
      state,
      context: `Gate ${gate}; activity ${activity}.`,
      next: state === 'running' || state === 'dispatching'
        ? 'Watch current activity and recent events; investigate if the gate stops moving.'
        : state.includes('error') || gate.includes('error')
          ? 'Open recent events and logs before retrying dispatch.'
          : 'Review artifacts and paper eligibility before queuing another action.',
    }
  }
  if (kind === 'paper') {
    const state = stringifyValue(firstValue(payload.status, paper.status, paper.paper_status, payload.paper_status))
    const evidence = stringifyValue(firstValue(paper.evidence_bundle_path, payload.evidence_bundle_path, paper.claim_ledger_path, payload.claim_ledger_path))
    return {
      state,
      context: evidence === '—' ? 'No evidence artifact path is visible in this read model.' : `Evidence/artifact path present: ${shortId(evidence)}.`,
      next: state.includes('draft')
        ? 'Preview artifacts, then finalize only after evidence and checklist state look correct.'
        : 'Use the paper pipeline only after deterministic paper gates mark this writable.',
    }
  }
  const eventType = stringifyValue(payload.event_type)
  const entity = stringifyValue(firstValue(payload.entity_id, payload.project_id, payload.paper_id))
  return {
    state: eventType,
    context: `Entity ${entity}; created ${stringifyValue(payload.created_at)}.`,
    next: entity !== '—' ? 'Open the related project, run, or paper if this event requires action.' : 'Use the payload only as supporting detail; do not treat it as a command.',
  }
}

function OperatorDetailSummary({ kind, payload }: { kind: DetailKind; payload: Record<string, unknown> }) {
  const summary = detailStatus(kind, payload)
  return (
    <section className="detail-operator-summary" aria-label="Operator detail summary">
      <div>
        <p className="eyebrow">Current state</p>
        <strong>{summary.state}</strong>
        <span>{summary.context}</span>
      </div>
      <div>
        <p className="eyebrow">Next safe action</p>
        <span>{summary.next}</span>
      </div>
    </section>
  )
}

function StructuredDetail({ kind, id, payload }: { kind: DetailKind; id: string; payload: Record<string, unknown> }) {
  const title = detailTitle(kind, payload, id)
  const summary = stringifyValue(firstValue(payload.summary, record(payload.project).abstract, record(payload.paper).summary, record(payload.paper).abstract))
  return (
    <div className="detail-body">
      <section className="detail-summary">
        <p className="eyebrow">{kindLabel(kind)}</p>
        <h3>{title}</h3>
        {summary !== '—' && summary !== title ? <p>{summary}</p> : null}
        <FieldGrid fields={detailFields(kind, payload, id)} />
      </section>
      <OperatorDetailSummary kind={kind} payload={payload} />
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

function payloadFromDetailData(kind: DetailKind, data?: Record<string, unknown>): Record<string, unknown> {
  if (kind === 'event') {
    const rows = Array.isArray(data?.rows) ? data.rows : []
    return record(rows[0])
  }
  return data || {}
}

function statusSubtitle(kind: DetailKind, id: string, payload: Record<string, unknown>): string {
  const status = detailStatus(kind, payload).state
  return `${kindLabel(kind)} · ${shortId(id)} · ${status}`
}

export function DetailPanel({ selection, onClose }: { selection: DetailSelection | null; onClose: () => void }) {
  if (!selection) return null
  return (
    <aside className="detail-panel" aria-label="Dashboard detail panel">
      <div className="detail-panel-head">
        <div>
          <p className="eyebrow">{kindLabel(selection.kind)}</p>
          <h2>{kindLabel(selection.kind)}</h2>
          <span className="detail-id-chip" title={selection.id}>{shortId(selection.id)}</span>
        </div>
        <button className="secondary-button" type="button" onClick={onClose}>Close</button>
      </div>
      <DetailBody selection={selection} />
    </aside>
  )
}

export function DetailPage({ selection }: { selection: DetailSelection }) {
  const inlineRow = selection.row
  const hasInlineEvent = selection.kind === 'event' && inlineRow
  const url = endpoint(selection)
  const query = useQuery({
    queryKey: ['detail-page', selection.kind, selection.id],
    queryFn: () => apiGet<Record<string, unknown>>(url || ''),
    enabled: Boolean(url) && !hasInlineEvent,
    retry: false,
  })
  const payload = hasInlineEvent ? inlineRow : payloadFromDetailData(selection.kind, query.data)
  const hasResolvedPayload = hasInlineEvent || query.isSuccess
  const title = hasResolvedPayload ? detailTitle(selection.kind, payload, selection.id) : kindLabel(selection.kind)
  const subtitle = hasResolvedPayload
    ? statusSubtitle(selection.kind, selection.id, payload)
    : `${kindLabel(selection.kind)} · ${shortId(selection.id)} · loading`
  return (
    <section className="page-stack">
      <div className="page-hero">
        <p className="eyebrow">Dashboard V2 detail</p>
        <h1>{title}</h1>
        <p>{subtitle}</p>
        <span className="detail-id-chip" title={selection.id}>{shortId(selection.id)}</span>
      </div>
      <aside className="detail-panel detail-panel--page" aria-label="Dashboard detail page">
        {query.isLoading && !hasInlineEvent ? <div className="state-card">Loading detail…</div> : null}
        {query.isError && !hasInlineEvent ? <div className="state-card state-card--error">Detail unavailable: {String(query.error.message)}</div> : null}
        {(hasInlineEvent || query.isSuccess || !url) && !query.isError ? <StructuredDetail kind={selection.kind} id={selection.id} payload={payload} /> : null}
      </aside>
    </section>
  )
}
