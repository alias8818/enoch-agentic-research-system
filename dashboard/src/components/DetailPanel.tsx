import { useState } from 'react'
import { apiGet } from '../api/client'
import { deriveDetailOperatorSummary, type DetailKind, type DetailOperatorSummary } from '../detailOperatorSummary'
import { shortId } from '../format'
import { detailBreadcrumb } from '../routePolicy'
import { dashboardV2Href } from '../routes'
import { useQuery } from '@tanstack/react-query'
import { PageHeader } from './PageHeader'
import {
  EntityLinkChips,
  Eyebrow,
  InlineErrorStateCard,
  LoadingStateCard,
  OperatorDetailSummary,
  OperatorQuestionSections,
  RawJsonDetails,
  StateCard,
} from './ui'

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
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'bigint') return String(value)
  return '—'
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

function RelatedSection({ title, rows, kind }: Readonly<{ title: string; rows: Record<string, unknown>[]; kind: 'run' | 'paper' | 'event' }>) {
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

function RelatedDetails({ payload }: Readonly<{ payload: Record<string, unknown> }>) {
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

function artifactPreviewMeta(preview: ArtifactPreview): string {
  const parts = [preview.field]
  if (preview.size_bytes) parts.push(`${preview.size_bytes} bytes`)
  if (preview.truncated) parts.push('truncated')
  return parts.join(' · ')
}

function PaperArtifacts({ id, payload }: Readonly<{ id: string; payload: Record<string, unknown> }>) {
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
          <p>{artifactPreviewMeta(preview)}</p>
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
  const raw = stringifyValue(firstValue(
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
  const sanitized = sanitizeHeroTitle(raw, kind)
  return isSlugLikeTitle(sanitized) ? shortId(sanitized) : sanitized
}

function isSlugLikeTitle(title: string): boolean {
  const trimmed = title.trim()
  if (!trimmed || /\s/.test(trimmed)) return false
  return trimmed.length > 30 && /^[a-z0-9_:-]+$/i.test(trimmed)
}

const kindPrefixPattern = /^(project|run|paper|event):(.+)/i

function sanitizeHeroTitle(title: string, kind: DetailKind): string {
  const trimmed = title.trim()
  const match = kindPrefixPattern.exec(trimmed)
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

function FieldGrid({ fields }: Readonly<{ fields: Field[] }>) {
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

function RecordFields({ kind, id, payload, presentation }: Readonly<{ kind: DetailKind; id: string; payload: Record<string, unknown>; presentation: 'panel' | 'page' }>) {
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

function isQueueAlertEvent(payload: Record<string, unknown>): boolean {
  return stringifyValue(payload.event_type).toLowerCase() === 'queue_alert.detected'
}

function listValues(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value.map((item) => stringifyValue(item)).filter((item) => item !== '—')
}

function queueAlertCurrentState(isLoading: boolean, isError: boolean, resolvedNow: boolean): string {
  if (isLoading) return 'Checking current status…'
  if (isError) return 'Current status unavailable'
  if (resolvedNow) return 'Resolved now'
  return 'Still blocking now'
}

function currentBlockersLabel(isSuccess: boolean, currentBlockers: string[]): string {
  if (!isSuccess) return '—'
  return currentBlockers.length ? currentBlockers.join('; ') : 'none'
}

function findingKey(finding: Record<string, unknown>, index: number): string {
  return `${stringifyValue(firstValue(finding.message, finding.source))}-${index}`
}

function QueueAlertDetails({ payload }: Readonly<{ payload: Record<string, unknown> }>) {
  const isQueueAlert = isQueueAlertEvent(payload)
  const nested = record(payload.payload)
  const findings = recordArray(nested.findings)
  const blockers = listValues(nested.dispatch_blockers)
  const suppressed = recordArray(nested.transient_suppressed_findings)
  const status = useQuery({
    queryKey: ['queue-alert-current-status', stringifyValue(firstValue(payload.event_id, payload.id, nested.fingerprint))],
    queryFn: () => apiGet<Record<string, unknown>>('/control/api/status'),
    enabled: isQueueAlert,
    retry: false,
  })
  if (!isQueueAlert) return null
  const currentBlockers = listValues(status.data?.dispatch_blockers)
  const resolvedNow = status.isSuccess && Boolean(status.data?.dispatch_safe) && currentBlockers.length === 0
  const currentState = queueAlertCurrentState(status.isLoading, status.isError, resolvedNow)
  return (
    <section className="detail-related queue-alert-detail" aria-label="Queue alert detail">
      <h4>Queue alert detail</h4>
      <dl className="detail-field-grid">
        <div className="detail-field">
          <dt>current alert state</dt>
          <dd>{currentState}</dd>
        </div>
        <div className="detail-field">
          <dt>event-time dispatch safe</dt>
          <dd>{stringifyValue(nested.dispatch_safe)}</dd>
        </div>
        <div className="detail-field">
          <dt>event-time blockers</dt>
          <dd>{blockers.length ? blockers.join('; ') : 'none'}</dd>
        </div>
        <div className="detail-field">
          <dt>current blockers</dt>
          <dd>{currentBlockersLabel(status.isSuccess, currentBlockers)}</dd>
        </div>
        <div className="detail-field">
          <dt>suppressed transient findings</dt>
          <dd>{suppressed.length}</dd>
        </div>
      </dl>
      {findings.length ? (
        <div className="detail-related-list">
          <strong>Alert findings</strong>
          {findings.slice(0, 5).map((finding, index) => {
            const suggestedAction = stringifyValue(finding.suggested_action)
            return (
            <div key={findingKey(finding, index)} className="detail-related-row">
              <strong>{stringifyValue(firstValue(finding.message, finding.source, `finding ${index + 1}`))}</strong>
              <span>{stringifyValue(firstValue(finding.severity, 'unknown'))} · {stringifyValue(firstValue(finding.source, 'unknown source'))}</span>
              {suggestedAction !== '—' ? <span>{suggestedAction}</span> : null}
            </div>
            )
          })}
        </div>
      ) : null}
    </section>
  )
}

function structuredDetailLead(presentation: 'panel' | 'page', summary: string, title: string, kind: DetailKind) {
  if (presentation === 'panel') {
    return (
      <>
        <Eyebrow>{kindLabel(kind)}</Eyebrow>
        <h3>{title}</h3>
        {summary !== '—' && summary !== title ? <p>{summary}</p> : null}
      </>
    )
  }
  if (summary !== '—' && summary !== title) {
    return <p className="detail-page-lead">{summary}</p>
  }
  return null
}

function StructuredDetail({ kind, id, payload, presentation = 'panel', operatorSummary: operatorSummaryProp }: Readonly<{ kind: DetailKind; id: string; payload: Record<string, unknown>; presentation?: 'panel' | 'page'; operatorSummary?: DetailOperatorSummary }>) {
  const title = detailTitle(kind, payload, id)
  const summary = stringifyValue(firstValue(payload.summary, record(payload.project).abstract, record(payload.paper).summary, record(payload.paper).abstract))
  const operatorSummary = operatorSummaryProp ?? deriveDetailOperatorSummary(kind, payload)
  return (
    <div className={`detail-body${presentation === 'page' ? ' detail-body--page' : ''}`}>
      <section className={`detail-summary${presentation === 'page' ? ' detail-summary--flat' : ''}`}>
        {structuredDetailLead(presentation, summary, title, kind)}
        <EntityLinkChips links={operatorSummary.entityLinks} />
        {presentation === 'panel' ? <FieldGrid fields={detailFields(kind, payload, id)} /> : null}
      </section>
      <OperatorDetailSummary state={operatorSummary.state} context={operatorSummary.context} next={operatorSummary.next} />
      <OperatorQuestionSections sections={operatorSummary.sections} recentActivity={operatorSummary.recentActivity} actionNeeded={operatorSummary.actionNeeded} />
      {kind === 'event' ? <QueueAlertDetails payload={payload} /> : null}
      {kind === 'paper' ? <PaperArtifacts id={id} payload={payload} /> : null}
      <RelatedDetails payload={payload} />
      {presentation === 'page' ? <RecordFields kind={kind} id={id} payload={payload} presentation={presentation} /> : null}
      <RawJsonDetails summary="Raw payload" payload={payload} />
    </div>
  )
}

function resolveDetailPayload(selection: DetailSelection, queryData?: Record<string, unknown>): Record<string, unknown> {
  if (selection.kind === 'event' && selection.row) return selection.row
  if (!endpoint(selection)) return selection.row || {}
  if (selection.kind === 'event') {
    const rows = Array.isArray(queryData?.rows) ? queryData.rows : []
    return record(rows[0])
  }
  return queryData || {}
}

function DetailBody({ selection }: Readonly<{ selection: DetailSelection }>) {
  const hasInlineEvent = selection.kind === 'event' && selection.row
  const url = endpoint(selection)
  const query = useQuery({
    queryKey: ['detail', selection.kind, selection.id],
    queryFn: () => apiGet<Record<string, unknown>>(url || ''),
    enabled: Boolean(url) && !hasInlineEvent,
    retry: false,
  })
  if (query.isLoading && !hasInlineEvent && url) return <LoadingStateCard label="detail" />
  if (query.isError && !hasInlineEvent && url) return <InlineErrorStateCard prefix="Detail unavailable" message={String(query.error.message)} />
  const payload = hasInlineEvent ? selection.row! : resolveDetailPayload(selection, query.data)
  return <StructuredDetail kind={selection.kind} id={selection.id} payload={payload} />
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

export function DetailPanel({ selection, onClose }: Readonly<{ selection: DetailSelection | null; onClose: () => void }>) {
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

export function DetailPage({ selection }: Readonly<{ selection: DetailSelection }>) {
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
        {query.isLoading && !hasInlineEvent ? <StateCard compact>Loading detail…</StateCard> : null}
        {query.isError && !hasInlineEvent ? <StateCard variant="error" compact>Detail unavailable: {String(query.error.message)}</StateCard> : null}
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
