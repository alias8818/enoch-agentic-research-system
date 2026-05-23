import { displayText } from './displayText'
import { dashboardV2Href } from './routes'

export type TableColumnKind = 'primary' | 'id' | 'text' | 'age' | 'status' | 'link'

export type TableColumnSpec = {
  key: string
  label: string
  kind?: TableColumnKind
  value?: (row: Record<string, unknown>) => unknown
}

function text(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  if (typeof value === 'boolean') return value ? 'yes' : 'no'
  return displayText(value, '—')
}

function firstValue(...values: unknown[]): unknown {
  return values.find((value) => value !== null && value !== undefined && value !== '')
}

export function shortTableId(value: unknown): string {
  const normalized = text(value)
  if (normalized === '—') return normalized
  if (normalized.length <= 24) return normalized
  return `${normalized.slice(0, 12)}…${normalized.slice(-8)}`
}

export function formatAgeLabel(row: Record<string, unknown>): string {
  const seconds = row.age_seconds
  if (typeof seconds === 'number' && Number.isFinite(seconds)) {
    if (seconds < 60) return `${Math.round(seconds)}s ago`
    if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`
    if (seconds < 86400) return `${Math.round(seconds / 3600)}h ago`
    return `${Math.round(seconds / 86400)}d ago`
  }
  const stamp = text(firstValue(row.updated_at, row.created_at))
  return stamp === '—' ? stamp : stamp.replace('T', ' ').replace(/\.\d+Z$/, 'Z')
}

export function queueDispatchReadiness(row: Record<string, unknown>): { label: string; tone: 'ready' | 'blocked' | 'neutral' } {
  const status = displayText(firstValue(row.status, row.queue_status)).toLowerCase()
  const blocked = text(firstValue(row.blocked_reason, row.decision_summary))
  if (row.manual_review_required === true) return { label: 'Needs operator review', tone: 'blocked' }
  if (blocked !== '—') return { label: blocked, tone: 'blocked' }
  if (status === 'queued') return { label: 'Queued — dry-run required before dispatch', tone: 'ready' }
  if (status) return { label: `Not dispatchable (${status})`, tone: 'neutral' }
  return { label: 'Unknown queue state', tone: 'neutral' }
}

export function paperEvidenceAvailability(row: Record<string, unknown>): string {
  const flags = row.artifact_paths_present
  if (flags && typeof flags === 'object' && !Array.isArray(flags)) {
    const record = flags as Record<string, unknown>
    const evidence = record.evidence_bundle === true
    const ledger = record.claim_ledger === true
    const manifest = record.manifest === true
    if (evidence && ledger && manifest) return 'complete'
    if (evidence || ledger) return 'partial'
    return 'missing'
  }
  return '—'
}

export function paperPipelineStatus(row: Record<string, unknown>): string {
  if (row.corpus_imported === true) return 'imported'
  const flags = row.artifact_paths_present
  if (flags && typeof flags === 'object' && !Array.isArray(flags) && (flags as Record<string, unknown>).finalization_package === true) {
    return 'finalization ready'
  }
  const review = text(row.review_status)
  if (review !== '—') return review
  return text(firstValue(row.paper_status, row.status))
}

export function eventEntityLink(row: Record<string, unknown>): { label: string; href?: string } {
  const entityType = displayText(row.entity_type).toLowerCase()
  const projectId = text(firstValue(row.project_id, entityType.includes('project') ? row.entity_id : null))
  const runId = text(firstValue(row.run_id, entityType.includes('run') ? row.entity_id : null))
  const paperId = text(firstValue(row.paper_id, entityType.includes('paper') ? row.entity_id : null))
  if (projectId !== '—') return { label: `project: ${shortTableId(projectId)}`, href: dashboardV2Href(`#project:${encodeURIComponent(projectId)}`) }
  if (runId !== '—') return { label: `run: ${shortTableId(runId)}`, href: dashboardV2Href(`#run:${encodeURIComponent(runId)}`) }
  if (paperId !== '—') return { label: `paper: ${shortTableId(paperId)}`, href: dashboardV2Href(`#paper:${encodeURIComponent(paperId)}`) }
  const entityId = text(row.entity_id)
  if (entityId !== '—') return { label: shortTableId(entityId) }
  return { label: '—' }
}

export function resolveColumnValue(row: Record<string, unknown>, column: TableColumnSpec): unknown {
  if (column.value) return column.value(row)
  if (column.key === 'age') return formatAgeLabel(row)
  if (column.key === 'dispatch_readiness') return queueDispatchReadiness(row).label
  if (column.key === 'evidence') return paperEvidenceAvailability(row)
  if (column.key === 'pipeline_status') return paperPipelineStatus(row)
  if (column.key === 'entity_link') return eventEntityLink(row).label
  if (column.key === 'lane') return firstValue(row.lane, row.machine_target, row.operator_lane)
  if (column.key === 'title') return firstValue(row.title, row.project_name, row.paper_title)
  return row[column.key]
}

export function resolveColumnTone(row: Record<string, unknown>, column: TableColumnSpec): string | undefined {
  if (column.key === 'dispatch_readiness') return queueDispatchReadiness(row).tone
  return undefined
}

export const projectsTableColumns: TableColumnSpec[] = [
  { key: 'project_name', label: 'project', kind: 'primary', value: (row) => firstValue(row.project_name, row.title, row.project_id) },
  { key: 'project_id', label: 'id', kind: 'id' },
  { key: 'machine_target', label: 'lane', value: (row) => firstValue(row.machine_target, row.lane) },
  { key: 'queue_status', label: 'status', kind: 'status', value: (row) => firstValue(row.queue_status, row.status) },
  { key: 'latest_run_state', label: 'latest run', kind: 'status' },
  { key: 'related_paper_status', label: 'paper', kind: 'status', value: (row) => firstValue(row.related_paper_status, row.paper_status) },
  { key: 'age', label: 'updated', kind: 'age' },
]

export const queueTableColumns: TableColumnSpec[] = [
  { key: 'title', label: 'project', kind: 'primary' },
  { key: 'project_id', label: 'id', kind: 'id' },
  { key: 'dispatch_readiness', label: 'dispatch', kind: 'status' },
  { key: 'machine_target', label: 'lane', value: (row) => firstValue(row.machine_target, row.lane) },
  { key: 'status', label: 'queue status', kind: 'status' },
  { key: 'next_action_hint', label: 'hint', value: (row) => firstValue(row.next_action_hint, row.blocked_reason) },
  { key: 'age', label: 'updated', kind: 'age' },
]

export const runsTableColumns: TableColumnSpec[] = [
  { key: 'project_name', label: 'project', kind: 'primary', value: (row) => firstValue(row.project_name, row.project_id) },
  { key: 'run_id', label: 'run id', kind: 'id' },
  { key: 'state', label: 'state', kind: 'status' },
  { key: 'gate_state', label: 'gate', kind: 'status' },
  { key: 'dispatch_mode', label: 'lane/mode', value: (row) => firstValue(row.machine_target, row.dispatch_mode) },
  { key: 'current_activity', label: 'activity' },
  { key: 'age', label: 'updated', kind: 'age' },
]

export const papersTableColumns: TableColumnSpec[] = [
  { key: 'title', label: 'paper', kind: 'primary', value: (row) => firstValue(row.title, row.paper_title, row.paper_id) },
  { key: 'paper_id', label: 'id', kind: 'id' },
  { key: 'paper_status', label: 'status', kind: 'status', value: (row) => firstValue(row.paper_status, row.status) },
  { key: 'evidence', label: 'evidence', kind: 'status' },
  { key: 'pipeline_status', label: 'finalization/import', kind: 'status' },
  { key: 'age', label: 'updated', kind: 'age' },
]

export const corpusTableColumns: TableColumnSpec[] = [
  { key: 'title', label: 'paper', kind: 'primary', value: (row) => firstValue(row.title, row.paper_title, row.paper_id) },
  { key: 'paper_id', label: 'id', kind: 'id' },
  { key: 'paper_status', label: 'status', kind: 'status', value: (row) => firstValue(row.paper_status, row.status) },
  { key: 'pipeline_status', label: 'import state', kind: 'status' },
  { key: 'corpus_import_id', label: 'import id', kind: 'id' },
  { key: 'age', label: 'updated', kind: 'age' },
]

export const eventsTableColumns: TableColumnSpec[] = [
  { key: 'event_type', label: 'type', kind: 'status' },
  { key: 'summary', label: 'summary', kind: 'primary' },
  { key: 'entity_link', label: 'entity', kind: 'link' },
  { key: 'created_at', label: 'created', value: (row) => formatAgeLabel({ ...row, age_seconds: undefined }) },
]

export const automationTableColumns: TableColumnSpec[] = [
  { key: 'project_name', label: 'project', kind: 'primary', value: (row) => firstValue(row.project_name, row.paper_id) },
  { key: 'paper_id', label: 'paper id', kind: 'id' },
  { key: 'paper_status', label: 'paper status', kind: 'status' },
  { key: 'review_status', label: 'review', kind: 'status' },
  { key: 'pipeline_status', label: 'finalization/import', kind: 'status' },
  { key: 'age', label: 'updated', kind: 'age' },
]

export function simpleTableColumns(keys: string[], overrides: Partial<Record<string, Partial<TableColumnSpec>>> = {}): TableColumnSpec[] {
  return keys.map((key) => ({
    key,
    label: overrides[key]?.label || key.replaceAll('_', ' '),
    kind: overrides[key]?.kind,
    value: overrides[key]?.value,
  }))
}

type DashboardEntity = 'project' | 'run' | 'paper'

function entityDashboardHref(entity: DashboardEntity, id: unknown): string | undefined {
  if (!id) return undefined
  return dashboardV2Href(`#${entity}:${encodeURIComponent(displayText(id))}`)
}

const columnKeyEntityField: Partial<
  Record<string, { field: 'project_id' | 'run_id' | 'paper_id'; entity: DashboardEntity }>
> = {
  project_id: { field: 'project_id', entity: 'project' },
  run_id: { field: 'run_id', entity: 'run' },
  paper_id: { field: 'paper_id', entity: 'paper' },
}

function idColumnLinkHref(row: Record<string, unknown>, columnKey: string): string | undefined {
  const mapping = columnKeyEntityField[columnKey]
  if (!mapping) return undefined
  return entityDashboardHref(mapping.entity, firstValue(row[mapping.field]))
}

function primaryColumnLinkHref(row: Record<string, unknown>): string | undefined {
  return (
    entityDashboardHref('project', firstValue(row.project_id))
    ?? entityDashboardHref('run', firstValue(row.run_id))
    ?? entityDashboardHref('paper', firstValue(row.paper_id))
  )
}

export function columnLinkHref(row: Record<string, unknown>, column: TableColumnSpec): string | undefined {
  if (column.key === 'entity_link') return eventEntityLink(row).href
  const idHref = idColumnLinkHref(row, column.key)
  if (idHref) return idHref
  if (column.key === 'primary' || column.kind === 'primary') return primaryColumnLinkHref(row)
  return undefined
}
