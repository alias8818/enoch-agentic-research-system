import { useState } from 'react'
import { apiGet } from '../api/client'
import { deriveDetailOperatorSummary, type DetailKind, type DetailOperatorSummary, type EntityLink } from '../detailOperatorSummary'
import { shortId } from '../format'
import { detailBreadcrumb } from '../routePolicy'
import { dashboardV2Href } from '../routes'
import { useQuery } from '@tanstack/react-query'
import { PageHeader } from './PageHeader'

export type { DetailKind }

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

const artifactFlagKeys: Record<(typeof artifactFields)[number][0], string> = {
  draft_markdown_path: 'draft_markdown',
  draft_latex_path: 'draft_latex',
  evidence_bundle_path: 'evidence_bundle',
  claim_ledger_path: 'claim_ledger',
  manifest_path: 'manifest',
}

function PaperArtifacts({ id, payload }: { id: string; payload: Record<string, unknown> }) {
  const paper = record(payload.paper)
  const flags = record(paper.artifact_paths_present)
  const available = artifactFields.filter(([field]) => Boolean(flags[artifactFlagKeys[field]] || paper[field]))
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
  return sanitizeHeroTitle(stringifyValue(firstValue(
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
  )), kind)
}

function sanitizeHeroTitle(title: string, kind: DetailKind): string {
  const trimmed = title.trim()
  const match = trimmed.match(/^(project|run|paper|event):(.+)/i)
  if (!match) return trimmed
  const rest = match[2].trim()
  return rest ? shortId(rest) : kindLabel(kind)
}

function queueRecord(payload: Record<string, unknown>): Record<string, unknown> {
  return record(payload.queue_item || payload.queue)
}

function detailFields(kind: DetailKind, payload: Record<string, unknown>, fallbackId: string): Field[] {
  const project = record(payload.project)
  const run = record(payload.run)
  const paper = record(payload.paper)
  const queue = queueRecord(payload)
  if (kind === 'project') {
    return [
      { label: 'project id', value: firstValue(payload.project_id, project.project_id, fallbackId) },
      { label: 'status', value: firstValue(queue.status, queue.queue_status, payload.status, project.origin_idea_status) },
      { label: 'machine target', value: firstValue(queue.machine_target, payload.machine_target, project.machine_target) },
      { label: 'lane', value: firstValue(queue.machine_target, queue.operator_lane, payload.lane, payload.machine_target) },
      { label: 'run id', value: firstValue(queue.current_run_id, payload.run_id, project.current_run_id) },
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
      { label: 'started', value: firstValue(payload.started_at, run.started_at) },
      { label: 'updated', value: firstValue(payload.updated_at, run.updated_at) },
      { label: 'ended', value: firstValue(payload.ended_at, run.ended_at) },
    ]
  }
  if (kind === 'paper') {
    return [
      { label: 'paper id', value: firstValue(payload.paper_id, paper.paper_id, fallbackId) },
      { label: 'project id', value: firstValue(payload.project_id, paper.project_id) },
      { label: 'status', value: firstValue(paper.paper_status, paper.status, payload.status, payload.paper_status) },
      { label: 'review status', value: firstValue(paper.review_status, payload.review_status) },
      { label: 'updated', value: firstValue(payload.updated_at, paper.updated_at) },
    ]
  }
  return [
    { label: 'event id', value: firstValue(payload.id, payload.event_id, fallbackId) },
    { label: 'event type', value: payload.event_type },
    { label: 'entity', value: firstValue(payload.entity_id, payload.project_id, payload.paper_id, payload.run_id) },
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

function EntityLinkChips({ links }: { links: EntityLink[] }) {
  if (!links.length) return null
  return (
    <div className="detail-entity-links" aria-label="Related entity links">
      {links.map((link) => (
        <a key={`${link.kind}-${link.id}`} className="detail-id-chip detail-id-chip--link" href={dashboardV2Href(`#${link.kind}:${encodeURIComponent(link.id)}`)} title={link.id}>
          {link.kind}: {link.label}
        </a>
      ))}
    </div>
  )
}

function OperatorQuestionSections({ sections, recentActivity, actionNeeded }: { sections: ReturnType<typeof deriveDetailOperatorSummary>['sections']; recentActivity: string | null; actionNeeded: string | null }) {
  if (!sections.length && !recentActivity && !actionNeeded) return null
  return (
    <section className="detail-operator-questions" aria-label="Operator questions">
      {sections.map((section) => (
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
      {recentActivity ? (
        <article className="detail-operator-question">
          <h4>What happened most recently?</h4>
          <p>{recentActivity}</p>
        </article>
      ) : null}
      {actionNeeded ? (
        <article className="detail-operator-question detail-operator-question--attention">
          <h4>Action needed now</h4>
          <p>{actionNeeded}</p>
        </article>
      ) : null}
    </section>
  )
}

function OperatorDetailSummary({ state, context, next }: { state: string; context: string; next: string }) {
  return (
    <section className="detail-operator-summary" aria-label="Operator detail summary">
      <div>
        <p className="eyebrow">Current state</p>
        <strong>{state}</strong>
        <span>{context}</span>
      </div>
      <div>
        <p className="eyebrow">Next safe action</p>
        <span>{next}</span>
      </div>
    </section>
  )
}

function RecordFields({ kind, id, payload, presentation }: { kind: DetailKind; id: string; payload: Record<string, unknown>; presentation: 'panel' | 'page' }) {
  const fields = detailFields(kind, payload, id)
  if (presentation === 'page') {
    return (
      <details className="detail-record-fields">
        <summary>Record fields</summary>
        <FieldGrid fields={fields} />
      </details>
    )
  }
  return <FieldGrid fields={fields} />
}

function StructuredDetail({ kind, id, payload, presentation = 'panel', operatorSummary: operatorSummaryProp }: { kind: DetailKind; id: string; payload: Record<string, unknown>; presentation?: 'panel' | 'page'; operatorSummary?: DetailOperatorSummary }) {
  const title = detailTitle(kind, payload, id)
  const summary = stringifyValue(firstValue(payload.summary, record(payload.project).abstract, record(payload.paper).summary, record(payload.paper).abstract))
  const operatorSummary = operatorSummaryProp ?? deriveDetailOperatorSummary(kind, payload)
  const fields = detailFields(kind, payload, id)
  return (
    <div className={`detail-body${presentation === 'page' ? ' detail-body--page' : ''}`}>
      <section className={`detail-summary${presentation === 'page' ? ' detail-summary--flat' : ''}`}>
        {presentation === 'panel' ? (
          <>
            <p className="eyebrow">{kindLabel(kind)}</p>
            <h3>{title}</h3>
            {summary !== '—' && summary !== title ? <p>{summary}</p> : null}
          </>
        ) : summary !== '—' && summary !== title ? <p className="detail-page-lead">{summary}</p> : null}
        <EntityLinkChips links={operatorSummary.entityLinks} />
        {presentation === 'panel' ? <FieldGrid fields={fields} /> : null}
      </section>
      <OperatorDetailSummary state={operatorSummary.state} context={operatorSummary.context} next={operatorSummary.next} />
      <OperatorQuestionSections sections={operatorSummary.sections} recentActivity={operatorSummary.recentActivity} actionNeeded={operatorSummary.actionNeeded} />
      {kind === 'paper' ? <PaperArtifacts id={id} payload={payload} /> : null}
      <RelatedDetails payload={payload} />
      {presentation === 'page' ? <RecordFields kind={kind} id={id} payload={payload} presentation={presentation} /> : null}
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

function statusSubtitle(kind: DetailKind, id: string, state: string): string {
  return `${kindLabel(kind)} · ${shortId(id)} · ${state}`
}

export function DetailPanel({ selection, onClose }: { selection: DetailSelection | null; onClose: () => void }) {
  if (!selection) return null
  return (
    <aside className="detail-panel" aria-label="Dashboard detail panel">
      <div className="detail-panel-head">
        <div>
          <p className="eyebrow">{kindLabel(selection.kind)}</p>
          <span className="detail-id-chip" title={selection.id}>{shortId(selection.id)}</span>
        </div>
        <button className="secondary-button" type="button" onClick={onClose}>Close</button>
      </div>
      <DetailBody selection={selection} />
    </aside>
  )
}

function detailDataSource(kind: DetailKind, id: string): string {
  if (kind === 'project') return `/control/api/v1/projects/${encodeURIComponent(id)}`
  if (kind === 'run') return `/control/api/v1/runs/${encodeURIComponent(id)}`
  if (kind === 'paper') return `/control/api/v1/papers/${encodeURIComponent(id)}`
  return `/control/api/v1/events?event_id=${encodeURIComponent(id)}&include_payload=true&page_size=1&sort=recent`
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
  const operatorSummary = hasResolvedPayload ? deriveDetailOperatorSummary(selection.kind, payload) : null
  const title = hasResolvedPayload ? detailTitle(selection.kind, payload, selection.id) : kindLabel(selection.kind)
  const subtitle = hasResolvedPayload && operatorSummary
    ? statusSubtitle(selection.kind, selection.id, operatorSummary.state)
    : `${kindLabel(selection.kind)} · ${shortId(selection.id)} · loading`
  return (
    <section className="page-stack">
      <PageHeader
        title={title}
        subtitle={subtitle}
        breadcrumb={detailBreadcrumb(selection.kind, title)}
        dataSource={detailDataSource(selection.kind, selection.id)}
        action={<span className="detail-id-chip" title={selection.id}>{shortId(selection.id)}</span>}
      />
      <div className="detail-page-body" aria-label="Dashboard detail page">
        {query.isLoading && !hasInlineEvent ? <div className="state-card state-card--compact">Loading detail…</div> : null}
        {query.isError && !hasInlineEvent ? <div className="state-card state-card--error state-card--compact">Detail unavailable: {String(query.error.message)}</div> : null}
        {(hasInlineEvent || query.isSuccess || !url) && !query.isError ? (
          <StructuredDetail
            kind={selection.kind}
            id={selection.id}
            payload={payload}
            presentation="page"
            operatorSummary={operatorSummary ?? undefined}
          />
        ) : null}
      </div>
    </section>
  )
}
