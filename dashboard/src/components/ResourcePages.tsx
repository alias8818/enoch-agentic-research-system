import { useEffect, useState } from 'react'
import { displayText } from '../displayText'
import { formatReadinessErrorMessage } from '../readinessErrors'
import { useQuery } from '@tanstack/react-query'
import { apiGet, apiPost } from '../api/client'
import {
  parseEventListResponse,
  parseIntakeIdeasResponse,
  parseOverviewResponse,
  parsePaperListResponse,
  parseProjectListResponse,
  parseQueueListResponse,
  parseRunListResponse,
} from '../api/readModelSchemas'
import { dashboardV2Href } from '../routes'
import type { DashboardRoute } from '../routes'
import { publicCorpusIndexUrl, publicCorpusPaperUrl, publicReleaseValidatorUrl } from '../corpusLinks'
import { shortId } from '../format'
import { DataTable } from './DataTable'
import { DetailPanel } from './DetailPanel'
import { useOperatorDialog } from './OperatorDialog'
import type { CommandPresentationContext } from '../commandResultPresentation'
import { CommandResultSummary } from './CommandResultSummary'
import { deriveIntakeIdeaOperatorSummary } from '../detailOperatorSummary'
import {
  deriveCorpusEmpty,
  deriveEventsEmpty,
  deriveIntakeEmpty,
  deriveProjectsEmpty,
  deriveQueueEmpty,
  deriveResourceErrorCopy,
  deriveRunsEmpty,
  derivePapersEmpty,
  deriveSimpleTableEmpty,
} from '../resourceStatePresentation'
import {
  corpusTableColumns,
  eventsTableColumns,
  papersTableColumns,
  projectsTableColumns,
  queueDispatchReadiness,
  queueTableColumns,
  runsTableColumns,
  simpleTableColumns,
} from '../tablePresentation'
import { hashQuery, ListFilterBar } from './ListFilterBar'
import { PageResourceErrorCard } from './ResourceStateCards'
import {
  ActionRow,
  EntityLinkChips,
  LoadingStateCard,
  OperatorDetailSummary,
  OperatorQuestionSections,
  PageShell,
  RawJsonDetails,
} from './ui'
import { PaperWorkflowNav } from './PaperWorkflowNav'
import { WorkbenchCountsFold, WorkbenchOperatorSummary } from './WorkbenchSummary'

type ObservabilityHealth = { generated_at?: string; route_observability_enabled?: boolean; route_observability_log_configured?: boolean; latest_route_observation?: string | null; sentry_enabled?: boolean; sentry_configured?: boolean; sentry_environment?: string; sentry_release?: string }
type ObservabilityMemory = { generated_at?: string; rss_mib?: number | null; peak_rss_mib?: number | null; warn_threshold_mib?: number | null; memory_warn?: boolean; route_observability_enabled?: boolean }
type ObservabilityLlmModel = {
  provider_id?: string
  provider_label?: string
  model_id?: string
  label?: string
  endpoint_health?: string
  format_health?: string
  visible_output_health?: string
  reasoning_budget_health?: string
  workflow_health?: string
  latest_failure_kind?: string
  latest_latency_ms?: number
  latest_status_code?: number
  latest_finish_reason?: string
  latest_visible_chars?: number
  success_rate?: number
  format_success_rate?: number
  operator_action?: string
  latest_preview?: string
}
type ObservabilityWorkflowModelRecommendation = {
  model_id?: string
  label?: string
  recommendation?: string
  operator_action?: string
}
type ObservabilityWorkflowRecommendation = {
  workflow_id?: string
  label?: string
  status?: string
  required_contracts?: string[]
  current_model_pool?: string[]
  recommended_model_pool?: string[]
  recommended_default_model?: string
  operator_action?: string
  models?: ObservabilityWorkflowModelRecommendation[]
}
type ObservabilityLlmHarnessEvent = {
  event_id?: number | string
  event_type?: string
  created_at?: string
  workflow_id?: string
  provider_id?: string
  model_id?: string
  selected_provider_id?: string
  selected_model_id?: string
  tool_name?: string
  status?: string
  failure_kind?: string
  selection_reason?: string
  budget_gate_status?: string
  health_gate_status?: string
  estimated_cost_usd?: number
  input_token_count?: number
  output_token_count?: number
  result_count?: number
}
type ObservabilityLlmHarness = {
  generated_at?: string
  status?: string
  event_count?: number
  failure_count?: number
  estimated_cost_usd?: number
  status_counts?: Record<string, number>
  event_type_counts?: Record<string, number>
  recent_events?: ObservabilityLlmHarnessEvent[]
}

function numericCount(value: unknown): number {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value === 'string' && value.trim()) {
    const parsed = Number(value)
    return Number.isFinite(parsed) ? parsed : 0
  }
  return 0
}
type ObservabilityLlmModels = { generated_at?: string; status?: string; model_count?: number; unhealthy_count?: number; structurally_unhealthy_count?: number; models?: ObservabilityLlmModel[]; workflow_recommendations?: ObservabilityWorkflowRecommendation[] }
type DetailSelection = { kind: 'project' | 'run' | 'paper' | 'event'; id: string; row?: Record<string, unknown> }
type FilterState = { search: string; status: string; pageSize: string; cursor: string }
type CommandResult = { payload: Record<string, unknown>; context?: CommandPresentationContext }

function refetchInBackground(refetch: () => Promise<unknown>): void {
  refetch().catch(() => undefined)
}

function refetchAllInBackground(...refetches: Array<() => Promise<unknown>>): void {
  for (const refetch of refetches) {
    refetchInBackground(refetch)
  }
}

function corpusImportValidationCopy(publishReady: number): Readonly<{ status: string; detail: string }> {
  if (publishReady > 0) {
    return { status: 'pending', detail: 'Import validation needs corpus autopilot.' }
  }
  return { status: 'clean', detail: 'Corpus import ledger has no missing finalized drafts.' }
}

function dryRunDispatchFollowUp(action: unknown, projectId: string, signature: string): Readonly<{ projectId: string; signature: string }> {
  if (action === 'dry_run_dispatch_one') {
    return { projectId, signature }
  }
  return { projectId: '', signature: '' }
}

function runsRouteHash(state: FilterState): string {
  const base = state.status ? `#runs:${encodeURIComponent(state.status)}` : '#runs'
  return statusHash(base, '', { ...state, status: '' })
}

function memoryHeadline(memoryWarn: boolean | undefined): string {
  if (memoryWarn) return 'Memory warning active'
  return 'Memory is inside configured threshold'
}

function routeObservabilityHeadline(enabled: boolean | undefined): string {
  if (enabled) return 'Route logging enabled'
  return 'Route logging disabled'
}

function sentryHeadline(enabled: boolean | undefined, configured: boolean | undefined): string {
  if (enabled) return 'Sentry exception capture enabled'
  if (configured) return 'Sentry configured but SDK is not active'
  return 'Sentry exception capture disabled'
}

function modelObservabilityHeadline(data: ObservabilityLlmModels): string {
  if ((data.structurally_unhealthy_count || 0) > 0) return 'Model usefulness degraded'
  if ((data.unhealthy_count || 0) > 0) return 'Model endpoint health needs attention'
  if ((data.model_count || 0) > 0) return 'Models are measured'
  return 'No enabled models configured'
}

function workflowRecommendationHeadline(items: ObservabilityWorkflowRecommendation[]): string {
  if (items.some((item) => item.status === 'blocked')) return 'Workflow model pools blocked'
  if (items.some((item) => item.status === 'needs_attention')) return 'Workflow model pools need tuning'
  if (items.length > 0) return 'Workflow model pools measured'
  return 'No workflow model recommendations'
}

function harnessTelemetryHeadline(data: ObservabilityLlmHarness): string {
  if ((data.event_count ?? 0) <= 0) return 'No harness telemetry recorded'
  if ((data.failure_count ?? 0) > 0 || data.status === 'needs_attention') return 'Harness telemetry needs attention'
  return 'Harness telemetry healthy'
}

function healthLabel(value: string | undefined): string {
  if (!value) return 'unknown'
  return value.replaceAll('_', ' ')
}

function costText(value: number | undefined): string {
  return typeof value === 'number' && Number.isFinite(value) ? `$${value.toFixed(6)}` : '$0.000000'
}

function firstHarnessEvent(events: ObservabilityLlmHarnessEvent[], eventType: string): ObservabilityLlmHarnessEvent | undefined {
  return events.find((event) => event.event_type === eventType)
}

function harnessEventTitle(event: ObservabilityLlmHarnessEvent | undefined, fallback: string): string {
  if (!event) return fallback
  if (event.event_type === 'llm_harness.route_decision') {
    return `${event.selected_provider_id || event.provider_id || 'provider'} / ${event.selected_model_id || event.model_id || 'model'}`
  }
  if (event.event_type === 'llm_harness.tool_result' || event.event_type === 'llm_harness.tool_call') {
    return event.tool_name || fallback
  }
  return event.workflow_id || fallback
}

function harnessEventDetail(event: ObservabilityLlmHarnessEvent | undefined, fallback: string): string {
  if (!event) return fallback
  if (event.event_type === 'llm_harness.route_decision') {
    return event.selection_reason || 'Route decision recorded without an operator-facing reason.'
  }
  if (event.failure_kind) {
    return `Latest status ${healthLabel(event.status)} with ${event.failure_kind}.`
  }
  if (event.event_type === 'llm_harness.cost_observation') {
    return `${costText(event.estimated_cost_usd)} estimated cost; ${event.input_token_count ?? 0} input tokens and ${event.output_token_count ?? 0} output tokens.`
  }
  if (event.result_count !== undefined) {
    return `${event.result_count} bounded result(s) recorded.`
  }
  return `Latest status ${healthLabel(event.status)}.`
}

function percentText(value: number | undefined): string {
  return typeof value === 'number' ? `${Math.round(value * 100)}%` : '—'
}

function ResourceErrorCard({ endpoint, error, onRetry, retryLabel }: Readonly<{ endpoint: Parameters<typeof deriveResourceErrorCopy>[0]; error: unknown; onRetry: () => void; retryLabel?: string }>) {
  return <PageResourceErrorCard copy={deriveResourceErrorCopy(endpoint, error)} error={error} onRetry={onRetry} retryLabel={retryLabel} />
}

function PageRefreshAction({ generatedAt, isFetching, onRefresh, label = 'Last loaded', refreshLabel = 'Refresh rows' }: Readonly<{ generatedAt?: string; isFetching: boolean; onRefresh: () => void; label?: string; refreshLabel?: string }>) {
  return (
    <ActionRow ariaLabel={label}>
      <span>{label} {generatedAt || 'unknown'}</span>
      <button className="secondary-button" type="button" disabled={isFetching} onClick={onRefresh}>
        {isFetching ? 'Refreshing…' : refreshLabel}
      </button>
    </ActionRow>
  )
}

function withCommonParams(state: FilterState, sort: string): URLSearchParams {
  const params = new URLSearchParams({ page_size: state.pageSize, sort })
  if (state.status) params.set('status', state.status)
  if (state.search) params.set('search', state.search)
  if (state.cursor) params.set('cursor', state.cursor)
  return params
}


function replaceRouteHash(hash: string) {
  if (globalThis.window === undefined) return
  globalThis.history.replaceState(globalThis.history.state, '', hash)
}

function queueHash(state: FilterState): string {
  const base = state.status ? `#queue:${encodeURIComponent(state.status)}` : '#queue'
  return `${base}${hashQuery([['search', state.search]])}`
}

function queueListParams(state: FilterState): URLSearchParams {
  const params = new URLSearchParams({ page_size: state.pageSize, sort: 'priority' })
  const queueSlice = ['active', 'blocked', 'queued'].includes(state.status)
    ? state.status
    : 'all'
  params.set('queue', queueSlice)
  if (state.status && queueSlice === 'all') params.set('status', state.status)
  if (state.search) params.set('search', state.search)
  if (state.cursor) params.set('cursor', state.cursor)
  return params
}

function statusHash(base: string, statusKey: string, state: FilterState): string {
  return `${base}${hashQuery([[statusKey, state.status], ['search', state.search]])}`
}

function withRunParams(state: FilterState): URLSearchParams {
  const params = new URLSearchParams({ page_size: state.pageSize, sort: 'recent' })
  if (state.status) params.set('state', state.status)
  if (state.search) params.set('search', state.search)
  if (state.cursor) params.set('cursor', state.cursor)
  return params
}

function firstValue(...values: unknown[]): unknown {
  return values.find((value) => value !== null && value !== undefined && value !== '')
}

function selectedDispatchReason(selection: DetailSelection | null): string {
  if (!selection) return 'Select a queued row to check whether that exact candidate can dispatch.'
  if (!selection.id) return 'Selected row has no project id.'
  const status = displayText(selection.row?.status).toLowerCase()
  if (status !== 'queued') return `Selected row is ${status || 'not queued'}.`
  return 'Dry-run checks /control/dispatch-one for the selected project only.'
}

function queueDispatchSignature(row?: Record<string, unknown>): string {
  if (!row) return ''
  return [
    displayText(row.project_id),
    displayText(row.status).toLowerCase(),
    displayText(row.machine_target),
    displayText(row.current_run_id),
    displayText(row.dispatch_priority),
    displayText(row.selection_rank),
    displayText(row.updated_at),
  ].join('|')
}

function selectedDispatchDisabledReason(canDryRunSelected: boolean, liveReady: boolean, staleReady: boolean, dispatchBusy: boolean): string {
  if (dispatchBusy) return 'Dispatch selected project disabled: dispatch command is running.'
  if (staleReady) return 'Dispatch selected project disabled: selected row changed; run Check selected dispatch again.'
  if (!canDryRunSelected) return 'Dispatch selected project disabled: select a queued row first.'
  if (!liveReady) return 'Dispatch selected project disabled: run Check selected dispatch first.'
  return ''
}

function mergeQueueFiltersFromRoute(current: FilterState, route: { search?: string; status: string }): FilterState | null {
  if (current.status === route.status && current.search === route.search) return null
  return { ...current, status: route.status, search: route.search || '', cursor: '' }
}

type QueueDispatchState = {
  selectedProjectId: string
  selectedCurrentSignature: string
  canDryRunSelected: boolean
  canLiveDispatchSelected: boolean
  staleDispatchReady: boolean
  dispatchDisabledReason: string
}

function deriveQueueDispatchState(
  rows: Record<string, unknown>[] | undefined,
  selection: DetailSelection | null,
  liveDispatchProjectId: string,
  liveDispatchSignature: string,
  dispatchBusy: boolean,
): QueueDispatchState {
  const selectedProjectId = selection?.id || ''
  const selectedStatus = displayText(selection?.row?.status).toLowerCase()
  const canDryRunSelected = Boolean(selectedProjectId) && selectedStatus === 'queued'
  const selectedCurrentRow = (rows || []).find((row) => displayText(row.project_id) === selectedProjectId)
  const selectedCurrentSignature = queueDispatchSignature(selectedCurrentRow || selection?.row)
  const canLiveDispatchSelected = canDryRunSelected
    && liveDispatchProjectId === selectedProjectId
    && Boolean(liveDispatchSignature)
    && liveDispatchSignature === selectedCurrentSignature
  const staleDispatchReady = Boolean(liveDispatchSignature) && liveDispatchSignature !== selectedCurrentSignature
  const dispatchDisabledReason = selectedDispatchDisabledReason(canDryRunSelected, canLiveDispatchSelected, staleDispatchReady, dispatchBusy)
  return { selectedProjectId, selectedCurrentSignature, canDryRunSelected, canLiveDispatchSelected, staleDispatchReady, dispatchDisabledReason }
}

type QueueDispatchMutators = {
  setDispatchBusy: (busy: boolean) => void
  setDispatchResult: (result: CommandResult | null) => void
  setLiveDispatchProjectId: (projectId: string) => void
  setLiveDispatchSignature: (signature: string) => void
  setSelection: (selection: DetailSelection | null) => void
  refetchQueue: () => Promise<unknown>
}

async function runQueueDryRunDispatch(
  canDryRunSelected: boolean,
  selectedProjectId: string,
  selectedCurrentSignature: string,
  mutators: QueueDispatchMutators,
): Promise<void> {
  if (!canDryRunSelected) return
  mutators.setDispatchBusy(true)
  try {
    const payload = await apiPost<Record<string, unknown>>('/control/dispatch-one', {
      project_id: selectedProjectId,
      dry_run: true,
      requested_by: 'dashboard-v2',
      force_preflight: true,
    })
    mutators.setDispatchResult({ payload, context: { commandFamily: 'dispatch' } })
    const followUp = dryRunDispatchFollowUp(payload.action, selectedProjectId, selectedCurrentSignature)
    mutators.setLiveDispatchProjectId(followUp.projectId)
    mutators.setLiveDispatchSignature(followUp.signature)
  } catch (error) {
    mutators.setDispatchResult({ payload: { ok: false, reason: formatReadinessErrorMessage(error) }, context: { commandFamily: 'dispatch' } })
    mutators.setLiveDispatchProjectId('')
    mutators.setLiveDispatchSignature('')
  } finally {
    mutators.setDispatchBusy(false)
  }
}

async function runQueueLiveDispatch(
  selectedProjectId: string,
  canLiveDispatchSelected: boolean,
  confirm: (options: { title: string; message: string; confirmLabel: string; tone: 'warn' }) => Promise<boolean>,
  mutators: QueueDispatchMutators,
): Promise<void> {
  if (!selectedProjectId || !canLiveDispatchSelected) return
  const confirmed = await confirm({
    title: 'Dispatch selected project?',
    message: `This starts live dispatch for exactly ${selectedProjectId}. Use Check selected dispatch again if the row changed or went stale.`,
    confirmLabel: 'Dispatch selected',
    tone: 'warn',
  })
  if (!confirmed) return
  mutators.setDispatchBusy(true)
  try {
    const payload = await apiPost<Record<string, unknown>>('/control/dispatch-one', {
      project_id: selectedProjectId,
      dry_run: false,
      requested_by: 'dashboard-v2',
      force_preflight: true,
    })
    mutators.setDispatchResult({ payload, context: { commandFamily: 'dispatch' } })
    mutators.setLiveDispatchProjectId('')
    mutators.setLiveDispatchSignature('')
    mutators.setSelection(null)
    refetchInBackground(mutators.refetchQueue)
  } catch (error) {
    mutators.setDispatchResult({ payload: { ok: false, reason: formatReadinessErrorMessage(error) }, context: { commandFamily: 'dispatch' } })
  } finally {
    mutators.setDispatchBusy(false)
  }
}

function QueueDispatchCommandCard({
  selection,
  dispatch,
  dispatchBusy,
  dispatchDisabledReason,
  onDryRun,
  onLive,
}: Readonly<{
  selection: DetailSelection | null
  dispatch: QueueDispatchState
  dispatchBusy: boolean
  dispatchDisabledReason: string
  onDryRun: () => void
  onLive: () => void
}>) {
  const { selectedProjectId, canDryRunSelected, canLiveDispatchSelected } = dispatch
  return (
    <section className="queue-command-card queue-command-card--compact">
      <div>
        <p className="eyebrow">Selected queue row</p>
        <h2>{displayText(firstValue(selection?.row?.project_name, selection?.row?.title), displayText(selectedProjectId, 'No row selected'))}</h2>
        {selectedProjectId ? <span className="detail-id-chip" title={selectedProjectId}>{shortId(selectedProjectId)}</span> : null}
        <p>{selection?.row ? queueDispatchReadiness(selection.row).label : selectedDispatchReason(selection)}</p>
      </div>
      <div className="action-row">
        <button className="secondary-button" type="button" disabled={!canDryRunSelected || dispatchBusy} onClick={onDryRun}>
          {dispatchBusy ? 'Checking…' : 'Check selected dispatch'}
        </button>
        <button className="primary-button" type="button" disabled={!canLiveDispatchSelected || dispatchBusy} onClick={onLive}>
          Dispatch selected project
        </button>
      </div>
      {dispatchDisabledReason ? <p className="primary-action-disabled-reason">{dispatchDisabledReason}</p> : null}
    </section>
  )
}

function CommandResultCard({ result, stale }: Readonly<{ result: CommandResult | null; stale?: boolean }>) {
  if (!result) return null
  return <CommandResultSummary result={{ payload: result.payload, context: { ...result.context, stale: stale || result.context?.stale } }} />
}

function CountCard({ label, value, detail }: Readonly<{ label: string; value: unknown; detail: string }>) {
  return (
    <div className="count-card">
      <div>{displayText(value, '0')}</div>
      <div>{label}</div>
      <p>{detail}</p>
    </div>
  )
}

function eventCellHref(row: Record<string, unknown>, column: string): string | undefined {
  if (column !== 'id' && column !== 'event_id') return undefined
  const id = firstValue(row.event_id, row.id)
  const idText = displayText(id)
  return idText ? dashboardV2Href(`#event:${encodeURIComponent(idText)}`) : undefined
}

function detailCellHref(row: Record<string, unknown>, column: string): string | undefined {
  if (column === 'project_id') {
    const idText = displayText(firstValue(row.project_id))
    return idText ? dashboardV2Href(`#project:${encodeURIComponent(idText)}`) : undefined
  }
  if (column === 'run_id') {
    const idText = displayText(firstValue(row.run_id))
    return idText ? dashboardV2Href(`#run:${encodeURIComponent(idText)}`) : undefined
  }
  if (column === 'paper_id') {
    const idText = displayText(firstValue(row.paper_id))
    return idText ? dashboardV2Href(`#paper:${encodeURIComponent(idText)}`) : undefined
  }
  return eventCellHref(row, column)
}

export function QueuePage({ route }: Readonly<{ route: Extract<DashboardRoute, { page: 'queue' }> }>) {
  const [selection, setSelection] = useState<DetailSelection | null>(null)
  const [dispatchResult, setDispatchResult] = useState<CommandResult | null>(null)
  const [dispatchBusy, setDispatchBusy] = useState(false)
  const [liveDispatchProjectId, setLiveDispatchProjectId] = useState('')
  const [liveDispatchSignature, setLiveDispatchSignature] = useState('')
  const [filters, setFilters] = useState<FilterState>({ search: route.search || '', status: route.status, pageSize: '50', cursor: '' })
  const { confirm, dialog } = useOperatorDialog()
  useEffect(() => {
    setFilters((current) => mergeQueueFiltersFromRoute(current, route) ?? current)
    setSelection(null)
    setDispatchResult(null)
    setLiveDispatchProjectId('')
    setLiveDispatchSignature('')
  }, [route.search, route.status])
  const params = queueListParams(filters)
  const query = useQuery({ queryKey: ['queue', filters], queryFn: () => apiGet<unknown>(`/control/api/v1/queue?${params}`).then(parseQueueListResponse) })
  if (query.isLoading) return <LoadingStateCard label="queue" />
  if (query.isError) return <ResourceErrorCard endpoint="queue" error={query.error} onRetry={() => { refetchInBackground(() => query.refetch()) }} retryLabel="Retry queue" />
  const dispatch = deriveQueueDispatchState(query.data?.rows, selection, liveDispatchProjectId, liveDispatchSignature, dispatchBusy)
  const dispatchMutators: QueueDispatchMutators = {
    setDispatchBusy,
    setDispatchResult,
    setLiveDispatchProjectId,
    setLiveDispatchSignature,
    setSelection,
    refetchQueue: () => query.refetch(),
  }
  return (
    <>
      <PageShell title="Queue" subtitle="Review queue rows, dry-run dispatch, and start selected work safely." dataSource="/control/api/v1/queue" action={<PageRefreshAction generatedAt={query.data?.generated_at} isFetching={query.isFetching} onRefresh={() => { refetchInBackground(() => query.refetch()) }} />}>
        <ListFilterBar savedFiltersTableId="queue" state={filters} statusOptions={[{ label: 'all statuses', value: '' }, { label: 'queued', value: 'queued' }, { label: 'active', value: 'active' }, { label: 'blocked', value: 'blocked' }, { label: 'completed', value: 'completed' }]} onApply={(next) => { setFilters(next); replaceRouteHash(queueHash(next)) }} onReset={() => { const next = { search: '', status: route.status, pageSize: '50', cursor: '' }; setFilters(next); replaceRouteHash(queueHash(next)) }} onNext={() => setFilters({ ...filters, cursor: query.data?.page?.next_cursor || '' })} page={query.data?.page} />
        <QueueDispatchCommandCard
          selection={selection}
          dispatch={dispatch}
          dispatchBusy={dispatchBusy}
          dispatchDisabledReason={dispatch.dispatchDisabledReason}
          onDryRun={() => { void runQueueDryRunDispatch(dispatch.canDryRunSelected, dispatch.selectedProjectId, dispatch.selectedCurrentSignature, dispatchMutators) }}
          onLive={() => { void runQueueLiveDispatch(dispatch.selectedProjectId, dispatch.canLiveDispatchSelected, confirm, dispatchMutators) }}
        />
        <CommandResultCard result={dispatchResult} stale={dispatch.staleDispatchReady} />
        <DataTable rows={query.data?.rows || []} columns={queueTableColumns} empty={deriveQueueEmpty({ search: filters.search, status: filters.status, activeCount: numericCount(query.data?.counts?.active) })} cellHref={detailCellHref} onSelectRow={(row) => { setDispatchResult(null); setLiveDispatchProjectId(''); setLiveDispatchSignature(''); setSelection({ kind: 'project', id: displayText(row.project_id), row }) }} />
        <DetailPanel selection={selection} onClose={() => setSelection(null)} />
      </PageShell>
      {dialog}
    </>
  )
}

export function ProjectsPage({ route }: Readonly<{ route: Extract<DashboardRoute, { page: 'projects' }> }>) {
  const [selection, setSelection] = useState<DetailSelection | null>(null)
  const [filters, setFilters] = useState<FilterState>({ search: route.search || '', status: route.status, pageSize: '50', cursor: '' })
  useEffect(() => {
    setFilters((current) => current.status === route.status && current.search === route.search ? current : { ...current, status: route.status, search: route.search || '', cursor: '' })
    setSelection(null)
  }, [route.search, route.status])
  const params = withCommonParams(filters, 'recent')
  const query = useQuery({ queryKey: ['projects', filters], queryFn: () => apiGet<unknown>(`/control/api/v1/projects?${params}`).then(parseProjectListResponse) })
  if (query.isLoading) return <LoadingStateCard label="projects" />
  if (query.isError) return <ResourceErrorCard endpoint="projects" error={query.error} onRetry={() => { refetchInBackground(() => query.refetch()) }} retryLabel="Retry projects" />
  return (
    <PageShell title="Projects" subtitle="Search projects and open structured detail before dispatch or paper actions." dataSource="/control/api/v1/projects" action={<PageRefreshAction generatedAt={query.data?.generated_at} isFetching={query.isFetching} onRefresh={() => { refetchInBackground(() => query.refetch()) }} />}>
      <ListFilterBar state={filters} statusOptions={[{ label: 'all project states', value: '' }, { label: 'testing', value: 'testing' }, { label: 'exploring', value: 'exploring' }, { label: 'queued', value: 'queued' }, { label: 'running', value: 'running' }, { label: 'completed', value: 'completed' }, { label: 'blocked', value: 'blocked' }]} onApply={(next) => { setFilters(next); replaceRouteHash(statusHash('#projects', 'status', next)) }} onReset={() => { const next = { search: '', status: route.status, pageSize: '50', cursor: '' }; setFilters(next); replaceRouteHash(statusHash('#projects', 'status', next)) }} onNext={() => setFilters({ ...filters, cursor: query.data?.page?.next_cursor || '' })} page={query.data?.page} />
      <DataTable rows={query.data?.rows || []} columns={projectsTableColumns} empty={deriveProjectsEmpty({ search: filters.search, status: filters.status })} cellHref={detailCellHref} onSelectRow={(row) => setSelection({ kind: 'project', id: displayText(row.project_id), row })} />
      <DetailPanel selection={selection} onClose={() => setSelection(null)} />
    </PageShell>
  )
}

export function RunsPage({ route }: Readonly<{ route: Extract<DashboardRoute, { page: 'runs' }> }>) {
  const [selection, setSelection] = useState<DetailSelection | null>(null)
  const [filters, setFilters] = useState<FilterState>({ search: route.search || '', status: route.state, pageSize: '50', cursor: '' })
  useEffect(() => {
    setFilters((current) => current.status === route.state && current.search === route.search ? current : { ...current, status: route.state, search: route.search || '', cursor: '' })
    setSelection(null)
  }, [route.search, route.state])
  const params = withRunParams(filters)
  const query = useQuery({ queryKey: ['runs', filters], queryFn: () => apiGet<unknown>(`/control/api/v1/runs?${params}`).then(parseRunListResponse) })
  if (query.isLoading) return <LoadingStateCard label="runs" />
  if (query.isError) return <ResourceErrorCard endpoint="runs" error={query.error} onRetry={() => { refetchInBackground(() => query.refetch()) }} retryLabel="Retry runs" />
  return (
    <PageShell title="Runs" subtitle="Inspect run state, gates, activity, and related artifacts." dataSource="/control/api/v1/runs" action={<PageRefreshAction generatedAt={query.data?.generated_at} isFetching={query.isFetching} onRefresh={() => { refetchInBackground(() => query.refetch()) }} />}>
      <ListFilterBar state={filters} statusOptions={[{ label: 'all run states', value: '' }, { label: 'running', value: 'running' }, { label: 'dispatching', value: 'dispatching' }, { label: 'awaiting wake', value: 'awaiting_wake' }, { label: 'dispatch error', value: 'dispatch_error' }, { label: 'completed', value: 'completed' }, { label: 'wake ready', value: 'wake_ready' }]} onApply={(next) => { setFilters(next); replaceRouteHash(runsRouteHash(next)) }} onReset={() => { const next = { search: '', status: route.state, pageSize: '50', cursor: '' }; setFilters(next); replaceRouteHash(runsRouteHash(next)) }} onNext={() => setFilters({ ...filters, cursor: query.data?.page?.next_cursor || '' })} page={query.data?.page} />
      <DataTable rows={query.data?.rows || []} columns={runsTableColumns} empty={deriveRunsEmpty({ search: filters.search, status: filters.status })} cellHref={detailCellHref} onSelectRow={(row) => setSelection({ kind: 'run', id: displayText(row.run_id), row })} />
      <DetailPanel selection={selection} onClose={() => setSelection(null)} />
    </PageShell>
  )
}

export function PapersPage({ route }: Readonly<{ route: Extract<DashboardRoute, { page: 'papers' }> }>) {
  const [selection, setSelection] = useState<DetailSelection | null>(null)
  const [filters, setFilters] = useState<FilterState>({ search: route.search || '', status: route.status, pageSize: '50', cursor: '' })
  useEffect(() => {
    setFilters((current) => current.status === route.status && current.search === route.search ? current : { ...current, status: route.status, search: route.search || '', cursor: '' })
    setSelection(null)
  }, [route.search, route.status])
  const params = withCommonParams(filters, 'recent')
  const query = useQuery({ queryKey: ['papers', filters], queryFn: () => apiGet<unknown>(`/control/api/v1/papers?${params}`).then(parsePaperListResponse) })
  if (query.isLoading) return <LoadingStateCard label="papers" />
  if (query.isError) return <ResourceErrorCard endpoint="papers" error={query.error} onRetry={() => { refetchInBackground(() => query.refetch()) }} retryLabel="Retry papers" />
  return (
    <PageShell title="Papers" subtitle="Track draft, finalization, and publication readiness." dataSource="/control/api/v1/papers" action={<PageRefreshAction generatedAt={query.data?.generated_at} isFetching={query.isFetching} onRefresh={() => { refetchInBackground(() => query.refetch()) }} />}>
      <PaperWorkflowNav active="papers" />
      <ListFilterBar state={filters} statusOptions={[{ label: 'all paper statuses', value: '' }, { label: 'publication draft', value: 'publication_draft' }, { label: 'draft review', value: 'draft_review' }, { label: 'archived', value: 'archived' }]} onApply={(next) => { setFilters(next); replaceRouteHash(statusHash('#papers', 'status', next)) }} onReset={() => { const next = { search: '', status: route.status, pageSize: '50', cursor: '' }; setFilters(next); replaceRouteHash(statusHash('#papers', 'status', next)) }} onNext={() => setFilters({ ...filters, cursor: query.data?.page?.next_cursor || '' })} page={query.data?.page} />
      <DataTable rows={query.data?.rows || []} columns={papersTableColumns} empty={derivePapersEmpty({ search: filters.search, status: filters.status })} cellHref={detailCellHref} onSelectRow={(row) => setSelection({ kind: 'paper', id: displayText(row.paper_id), row })} />
      <DetailPanel selection={selection} onClose={() => setSelection(null)} />
    </PageShell>
  )
}

function CorpusSelectedPaperLink({ row }: Readonly<{ row: Record<string, unknown> }>) {
  const paperUrl = publicCorpusPaperUrl(row)
  if (!paperUrl) {
    return (
      <p className="composed-empty-state-hint">Select an imported row with an artifact slug to open its public corpus path.</p>
    )
  }
  return (
    <div className="action-row">
      <a className="primary-button primary-button--link" href={paperUrl} target="_blank" rel="noreferrer">Open public paper.md</a>
    </div>
  )
}

export function CorpusPage({ route }: Readonly<{ route?: Extract<DashboardRoute, { page: 'corpus' }> }>) {
  const [selection, setSelection] = useState<DetailSelection | null>(null)
  const [filters, setFilters] = useState<FilterState>({ search: route?.search || '', status: route?.status || 'publication_draft', pageSize: '50', cursor: '' })
  useEffect(() => {
    const nextSearch = route?.search || ''
    const nextStatus = route?.status || 'publication_draft'
    setFilters((current) => current.search === nextSearch && current.status === nextStatus ? current : { ...current, search: nextSearch, status: nextStatus, cursor: '' })
    setSelection(null)
  }, [route?.search, route?.status])
  const params = withCommonParams(filters, 'recent')
  const overview = useQuery({ queryKey: ['corpus', 'overview'], queryFn: () => apiGet<unknown>('/control/api/v1/overview?active_limit=1&event_limit=1').then(parseOverviewResponse) })
  const query = useQuery({ queryKey: ['corpus', filters], queryFn: () => apiGet<unknown>(`/control/api/v1/papers?${params}`).then(parsePaperListResponse) })
  if (query.isLoading) return <LoadingStateCard label="corpus import" />
  if (query.isError) return <ResourceErrorCard endpoint="corpus" error={query.error} onRetry={() => { refetchInBackground(() => query.refetch()) }} retryLabel="Retry corpus rows" />
  const pipeline = overview.data?.paper_pipeline || {}
  const publishReady = pipeline.publish_ready ?? pipeline.missing_from_corpus ?? 0
  const imported = pipeline.published_imported ?? 0
  const publicationReady = pipeline.publication_ready_total ?? 0
  const { status: importValidationStatus, detail: validationDetail } = corpusImportValidationCopy(publishReady)
  return (
    <PageShell title="Paper corpus import" subtitle="Find publication-ready drafts that still need corpus import." dataSource="/control/api/v1/papers and corpus import ledger" action={<PageRefreshAction generatedAt={query.data?.generated_at} isFetching={query.isFetching || overview.isFetching} onRefresh={() => { refetchAllInBackground(() => query.refetch(), () => overview.refetch()) }} />}>
      <PaperWorkflowNav active="corpus" />
      <section className="count-grid" aria-label="Corpus import summary">
        <CountCard label="Missing corpus import" value={publishReady} detail="Finalized publication drafts without corpus-import ledger rows." />
        <CountCard label="Already imported" value={imported} detail="Publication-ready drafts already recorded in corpus_imports." />
        <CountCard label="Publication-ready total" value={publicationReady} detail="Finalized drafts whether imported or still missing import." />
        <CountCard label="Import validation" value={importValidationStatus} detail={validationDetail} />
      </section>
      <section className="corpus-links-card" aria-label="Public corpus and release validation">
        <p className="eyebrow">External evidence</p>
        <p className="corpus-links-copy">Open the public corpus index, release-validator script, or a row&apos;s published paper.md after import.</p>
        <div className="action-row">
          <a className="secondary-button secondary-button--link" href={publicCorpusIndexUrl()} target="_blank" rel="noreferrer">Corpus index (GitHub)</a>
          <a className="secondary-button secondary-button--link" href={publicReleaseValidatorUrl()} target="_blank" rel="noreferrer">Release validator script</a>
        </div>
        {selection?.kind === 'paper' && selection.row ? <CorpusSelectedPaperLink row={selection.row} /> : null}
      </section>
      <ListFilterBar state={filters} statusOptions={[{ label: 'publication draft', value: 'publication_draft' }, { label: 'draft review', value: 'draft_review' }, { label: 'archived', value: 'archived' }, { label: 'all paper statuses', value: '' }]} onApply={(next) => { setFilters(next); replaceRouteHash(statusHash('#corpus', 'status', next)) }} onReset={() => { const next = { search: '', status: route?.status || 'publication_draft', pageSize: '50', cursor: '' }; setFilters(next); replaceRouteHash(statusHash('#corpus', 'status', next)) }} onNext={() => setFilters({ ...filters, cursor: query.data?.page?.next_cursor || '' })} page={query.data?.page} />
      <DataTable rows={query.data?.rows || []} columns={corpusTableColumns} empty={deriveCorpusEmpty({ search: filters.search, status: filters.status, defaultStatus: 'publication_draft' })} cellHref={detailCellHref} onSelectRow={(row) => setSelection({ kind: 'paper', id: displayText(row.paper_id), row })} />
      <DetailPanel selection={selection} onClose={() => setSelection(null)} />
    </PageShell>
  )
}


function IntakeIdeaDetail({ row, ideaId, onClose }: Readonly<{ row: Record<string, unknown> | null; ideaId?: string; onClose: () => void }>) {
  if (!row && ideaId) {
    return (
      <section className="detail-panel" aria-label="Intake idea detail">
        <div className="detail-panel-head">
          <div>
            <p className="eyebrow">Intake idea detail</p>
            <h2>Idea detail</h2>
            <span className="detail-id-chip" title={ideaId}>{shortId(ideaId)}</span>
          </div>
          <button className="secondary-button" type="button" onClick={onClose}>Close</button>
        </div>
        <section className="detail-summary">
          <p>Idea {ideaId} is not present in the bounded intake projection returned by /control/api/intake/ideas.</p>
        </section>
      </section>
    )
  }
  if (!row) return null
  const operatorSummary = deriveIntakeIdeaOperatorSummary(row)
  return (
    <section className="detail-panel" aria-label="Intake idea detail">
      <div className="detail-panel-head">
        <div>
          <p className="eyebrow">Intake idea detail</p>
          <h2>{displayText(row.title, displayText(row.idea_id, 'Selected idea'))}</h2>
          <span className="detail-id-chip" title={displayText(row.idea_id)}>{shortId(displayText(row.idea_id))}</span>
        </div>
        <button className="secondary-button" type="button" onClick={onClose}>Close</button>
      </div>
      <section className="detail-summary">
        <EntityLinkChips links={operatorSummary.entityLinks} />
        <OperatorDetailSummary state={operatorSummary.state} context={operatorSummary.context} next={operatorSummary.next} ariaLabel="Idea operator summary" />
        <OperatorQuestionSections sections={operatorSummary.sections} recentActivity={null} actionNeeded={operatorSummary.actionNeeded} />
        <RawJsonDetails summary="Raw intake row" payload={row} />
      </section>
    </section>
  )
}

function intakeCellHref(row: Record<string, unknown>, column: string): string | undefined {
  if (column !== 'idea_id') return undefined
  const ideaId = displayText(row.idea_id)
  return ideaId ? dashboardV2Href(`#intake:${encodeURIComponent(ideaId)}`) : undefined
}

export function IntakePage({ route }: Readonly<{ route?: Extract<DashboardRoute, { page: 'intake' }> }>) {
  const [selection, setSelection] = useState<Record<string, unknown> | null>(null)
  const query = useQuery({
    queryKey: ['intake'],
    queryFn: () => apiGet<unknown>('/control/api/intake/ideas?page_size=100').then(parseIntakeIdeasResponse),
  })
  if (query.isLoading) return <LoadingStateCard label="ideas intake" />
  if (query.isError) return <ResourceErrorCard endpoint="intake" error={query.error} onRetry={() => { refetchInBackground(() => query.refetch()) }} retryLabel="Retry intake" />
  const data = query.data || {}
  const counts = data.projection_counts || {}
  const skipped = Object.entries(data.skipped_reasons || {}).map(([reason, count]) => ({ reason, count }))
  const latestSync = data.latest_sync ? [data.latest_sync] : []
  const routeIdeaId = route?.ideaId || ''
  const rows = data.queued_projection || []
  const selectedRow = selection || rows.find((row) => displayText(row.idea_id) === routeIdeaId) || null
  return (
    <PageShell title="Idea intake" subtitle="Review admitted ideas, queue state, and next operator actions." dataSource="/control/api/intake/ideas" action={<PageRefreshAction generatedAt={data.generated_at} isFetching={query.isFetching} onRefresh={() => { setSelection(null); refetchInBackground(() => query.refetch()) }} refreshLabel="Refresh intake" />}>
      <WorkbenchOperatorSummary summary={data.operator_summary} />
      <section className="result-card">
        <h2>Latest intake sync</h2>
        <DataTable rows={latestSync} columns={simpleTableColumns(['source', 'status', 'observed_at', 'authority'])} empty={deriveSimpleTableEmpty('intake sync observation')} />
      </section>
      <section className="result-card">
        <h2>Skipped reasons</h2>
        <DataTable rows={skipped} columns={simpleTableColumns(['reason', 'count'])} empty={deriveSimpleTableEmpty('skipped intake row')} />
      </section>
      <DataTable rows={rows} columns={simpleTableColumns(['idea_id', 'title', 'idea_status', 'queue_status', 'next_action_hint', 'paper_status', 'source_kind', 'updated_at'], { title: { kind: 'primary' }, idea_id: { kind: 'id' } })} empty={deriveIntakeEmpty()} cellHref={intakeCellHref} onSelectRow={setSelection} />
      <WorkbenchCountsFold counts={counts} label="Intake projection counts" />
      <IntakeIdeaDetail row={selectedRow} ideaId={routeIdeaId} onClose={() => setSelection(null)} />
    </PageShell>
  )
}

export function EventsPage({ route }: Readonly<{ route?: Extract<DashboardRoute, { page: 'events' }> }>) {
  const [selection, setSelection] = useState<DetailSelection | null>(null)
  const [filters, setFilters] = useState<FilterState>({ search: route?.search || '', status: route?.eventType || '', pageSize: '50', cursor: '' })
  useEffect(() => {
    const nextSearch = route?.search || ''
    const nextStatus = route?.eventType || ''
    setFilters((current) => current.search === nextSearch && current.status === nextStatus ? current : { ...current, search: nextSearch, status: nextStatus, cursor: '' })
    setSelection(null)
  }, [route?.eventType, route?.search])
  const params = new URLSearchParams({ page_size: filters.pageSize, sort: 'recent' })
  if (filters.status) params.set('event_type', filters.status)
  if (filters.search) params.set('search', filters.search)
  if (filters.cursor) params.set('cursor', filters.cursor)
  const query = useQuery({ queryKey: ['events', filters], queryFn: () => apiGet<unknown>(`/control/api/v1/events?${params}`).then(parseEventListResponse) })
  if (query.isLoading) return <LoadingStateCard label="events" />
  if (query.isError) return <ResourceErrorCard endpoint="events" error={query.error} onRetry={() => { refetchInBackground(() => query.refetch()) }} retryLabel="Retry events" />
  return (
    <PageShell title="Events" subtitle="Scan recent control-plane events and open related entities." dataSource="/control/api/v1/events" action={<PageRefreshAction generatedAt={query.data?.generated_at} isFetching={query.isFetching} onRefresh={() => { refetchInBackground(() => query.refetch()) }} />}>
      <ListFilterBar state={filters} statusLabel="Event type" statusOptions={[{ label: 'all event types', value: '' }, { label: 'Queue Alert', value: 'Queue Alert' }, { label: 'worker.callback', value: 'worker.callback' }, { label: 'paper.drafted', value: 'paper.drafted' }, { label: 'research.run_cycle.live', value: 'research.run_cycle.live' }]} onApply={(next) => { setFilters(next); replaceRouteHash(statusHash('#events', 'event_type', next)) }} onReset={() => { const next = { search: '', status: '', pageSize: '50', cursor: '' }; setFilters(next); replaceRouteHash(statusHash('#events', 'event_type', next)) }} onNext={() => setFilters({ ...filters, cursor: query.data?.page?.next_cursor || '' })} page={query.data?.page} />
      <DataTable rows={query.data?.rows || []} columns={eventsTableColumns} empty={deriveEventsEmpty({ search: filters.search, status: filters.status })} onSelectRow={(row) => setSelection({ kind: 'event', id: displayText(row.id, displayText(row.event_id)), row })} />
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
export function ObservabilityPage() {
  const health = useQuery({ queryKey: ['observability', 'health'], queryFn: () => apiGet<ObservabilityHealth>('/control/api/v1/observability/health') })
  const memory = useQuery({ queryKey: ['observability', 'memory'], queryFn: () => apiGet<ObservabilityMemory>('/control/api/v1/observability/memory') })
  const llmModels = useQuery({ queryKey: ['observability', 'llm-models'], queryFn: () => apiGet<ObservabilityLlmModels>('/control/api/v1/observability/llm-models') })
  const llmHarness = useQuery({ queryKey: ['observability', 'llm-harness'], queryFn: () => apiGet<ObservabilityLlmHarness>('/control/api/v1/observability/llm-harness') })
  if (health.isLoading || memory.isLoading || llmModels.isLoading || llmHarness.isLoading) return <LoadingStateCard label="observability" />
  if (health.isError) return <ResourceErrorCard endpoint="observability-health" error={health.error} onRetry={() => { refetchInBackground(() => health.refetch()) }} retryLabel="Retry health sample" />
  if (memory.isError) return <ResourceErrorCard endpoint="observability-memory" error={memory.error} onRetry={() => { refetchInBackground(() => memory.refetch()) }} retryLabel="Retry memory sample" />
  if (llmModels.isError) return <ResourceErrorCard endpoint="observability-llm" error={llmModels.error} onRetry={() => { refetchInBackground(() => llmModels.refetch()) }} retryLabel="Retry model observability" />
  if (llmHarness.isError) return <ResourceErrorCard endpoint="observability-llm-harness" error={llmHarness.error} onRetry={() => { refetchInBackground(() => llmHarness.refetch()) }} retryLabel="Retry harness telemetry" />
  const healthData = health.data || {}
  const memoryData = memory.data || {}
  const llmData = llmModels.data || {}
  const harnessData = llmHarness.data || {}
  const harnessEvents = harnessData.recent_events || []
  const routeDecision = firstHarnessEvent(harnessEvents, 'llm_harness.route_decision')
  const toolResult = firstHarnessEvent(harnessEvents, 'llm_harness.tool_result') || firstHarnessEvent(harnessEvents, 'llm_harness.tool_call')
  const outputContract = firstHarnessEvent(harnessEvents, 'llm_harness.output_contract')
  const costObservation = firstHarnessEvent(harnessEvents, 'llm_harness.cost_observation')
  const generatedAt = `health ${healthData.generated_at || 'unknown'} · memory ${memoryData.generated_at || 'unknown'} · models ${llmData.generated_at || 'unknown'} · harness ${harnessData.generated_at || 'unknown'}`
  const attentionModels = (llmData.models || []).filter((model) => (
    model.endpoint_health !== 'healthy'
    || model.format_health === 'degraded'
    || model.visible_output_health === 'empty'
    || model.reasoning_budget_health === 'length_limited'
  ))
  const visibleModels = (attentionModels.length > 0 ? attentionModels : (llmData.models || [])).slice(0, 6)
  const workflowRecommendations = (llmData.workflow_recommendations || []).slice(0, 4)
  return (
    <PageShell title="Observability" subtitle="Check controller health, memory pressure, model usefulness, and route observability status." dataSource="/control/api/v1/observability bounded read models" action={<PageRefreshAction generatedAt={generatedAt} isFetching={health.isFetching || memory.isFetching || llmModels.isFetching || llmHarness.isFetching} onRefresh={() => { refetchAllInBackground(() => health.refetch(), () => memory.refetch(), () => llmModels.refetch(), () => llmHarness.refetch()) }} refreshLabel="Refresh observability" />}>
      <section className="detail-summary">
        <p className="eyebrow">Model observability</p>
        <h2>{modelObservabilityHeadline(llmData)}</h2>
        <dl className="detail-field-grid">
          <div className="detail-field"><dt>enabled models</dt><dd>{llmData.model_count ?? 0}</dd></div>
          <div className="detail-field"><dt>endpoint issues</dt><dd>{llmData.unhealthy_count ?? 0}</dd></div>
          <div className="detail-field"><dt>usefulness issues</dt><dd>{llmData.structurally_unhealthy_count ?? 0}</dd></div>
          <div className="detail-field"><dt>sampled</dt><dd>{llmData.generated_at || '—'}</dd></div>
        </dl>
        <section className="detail-operator-questions" aria-label="Model operator questions">
          {visibleModels.length > 0 ? visibleModels.map((model) => {
            const title = model.label || model.model_id || 'unknown model'
            return (
              <article key={`${model.provider_id || 'provider'}:${model.model_id || title}`} className="detail-operator-question">
                <h4>{title}</h4>
                <p>{model.operator_action || 'No action recorded for this model.'}</p>
                <dl className="detail-field-grid">
                  <div className="detail-field"><dt>provider</dt><dd>{model.provider_label || model.provider_id || '—'}</dd></div>
                  <div className="detail-field"><dt>endpoint</dt><dd>{healthLabel(model.endpoint_health)}</dd></div>
                  <div className="detail-field"><dt>format</dt><dd>{healthLabel(model.format_health)}</dd></div>
                  <div className="detail-field"><dt>visible output</dt><dd>{healthLabel(model.visible_output_health)}</dd></div>
                  <div className="detail-field"><dt>budget</dt><dd>{healthLabel(model.reasoning_budget_health)}</dd></div>
                  <div className="detail-field"><dt>finish</dt><dd>{healthLabel(model.latest_finish_reason)}</dd></div>
                  <div className="detail-field"><dt>visible chars</dt><dd>{model.latest_visible_chars ?? '—'}</dd></div>
                  <div className="detail-field"><dt>endpoint success</dt><dd>{percentText(model.success_rate)}</dd></div>
                  <div className="detail-field"><dt>format success</dt><dd>{percentText(model.format_success_rate)}</dd></div>
                </dl>
                <RawJsonDetails summary="Latest redacted model preview" payload={model.latest_preview || ''} />
              </article>
            )
          }) : <article className="detail-operator-question"><h4>No enabled model rows</h4><p>Configure at least one model before relying on automated model health.</p></article>}
        </section>
        <section className="detail-operator-questions" aria-label="Workflow model pool recommendations">
          <article className="detail-operator-question">
            <h4>{workflowRecommendationHeadline(workflowRecommendations)}</h4>
            <p>Recommendations use measured prompt-contract probes, not endpoint health alone.</p>
          </article>
          {workflowRecommendations.map((workflow) => {
            const label = workflow.label || workflow.workflow_id || 'unknown workflow'
            const recommended = workflow.recommended_model_pool?.length
              ? workflow.recommended_model_pool.join(', ')
              : 'none measured'
            const contracts = workflow.required_contracts?.length
              ? workflow.required_contracts.join(', ')
              : 'strict_json'
            const visibleActions = (workflow.models || [])
              .filter((item) => item.recommendation && item.recommendation !== 'usable')
              .slice(0, 3)
            return (
              <article key={workflow.workflow_id || label} className="detail-operator-question">
                <h4>{label}</h4>
                <p>{workflow.operator_action || 'No workflow recommendation recorded.'}</p>
                <dl className="detail-field-grid">
                  <div className="detail-field"><dt>status</dt><dd>{healthLabel(workflow.status)}</dd></div>
                  <div className="detail-field"><dt>requires</dt><dd>{contracts}</dd></div>
                  <div className="detail-field"><dt>recommended pool</dt><dd>{recommended}</dd></div>
                  <div className="detail-field"><dt>recommended default</dt><dd>{workflow.recommended_default_model || 'none measured'}</dd></div>
                </dl>
                {visibleActions.length > 0 ? (
                  <ul className="detail-list">
                    {visibleActions.map((item) => (
                      <li key={`${workflow.workflow_id || label}:${item.model_id || item.label}`}>
                        <strong>{item.label || item.model_id || 'unknown model'}:</strong> {item.operator_action || healthLabel(item.recommendation)}
                      </li>
                    ))}
                  </ul>
                ) : null}
              </article>
            )
          })}
        </section>
      </section>
      <section className="detail-summary">
        <p className="eyebrow">LLM harness telemetry</p>
        <h2>{harnessTelemetryHeadline(harnessData)}</h2>
        <dl className="detail-field-grid">
          <div className="detail-field"><dt>events</dt><dd>{harnessData.event_count ?? 0}</dd></div>
          <div className="detail-field"><dt>failures</dt><dd>{harnessData.failure_count ?? 0}</dd></div>
          <div className="detail-field"><dt>cost observed</dt><dd>{costText(harnessData.estimated_cost_usd)}</dd></div>
          <div className="detail-field"><dt>sampled</dt><dd>{harnessData.generated_at || '—'}</dd></div>
        </dl>
        <section className="detail-operator-questions" aria-label="Harness operator questions">
          <article className="detail-operator-question">
            <h4>Latest route decision</h4>
            <p><strong>{harnessEventTitle(routeDecision, 'No route decision recorded')}</strong></p>
            <p>{harnessEventDetail(routeDecision, 'No provider/model route decision has been recorded yet.')}</p>
            <dl className="detail-field-grid">
              <div className="detail-field"><dt>budget gate</dt><dd>{healthLabel(routeDecision?.budget_gate_status)}</dd></div>
              <div className="detail-field"><dt>health gate</dt><dd>{healthLabel(routeDecision?.health_gate_status)}</dd></div>
              <div className="detail-field"><dt>workflow</dt><dd>{routeDecision?.workflow_id || '—'}</dd></div>
            </dl>
          </article>
          <article className="detail-operator-question">
            <h4>Latest tool result</h4>
            <p><strong>{harnessEventTitle(toolResult, 'No tool call recorded')}</strong></p>
            <p>{harnessEventDetail(toolResult, 'No bounded tool result has been recorded yet.')}</p>
            <dl className="detail-field-grid">
              <div className="detail-field"><dt>status</dt><dd>{healthLabel(toolResult?.status)}</dd></div>
              <div className="detail-field"><dt>failure</dt><dd>{toolResult?.failure_kind || 'none'}</dd></div>
              <div className="detail-field"><dt>workflow</dt><dd>{toolResult?.workflow_id || '—'}</dd></div>
            </dl>
          </article>
          <article className="detail-operator-question">
            <h4>Latest output contract</h4>
            <p><strong>{harnessEventTitle(outputContract, 'No output contract recorded')}</strong></p>
            <p>{harnessEventDetail(outputContract, 'No structured-output contract result has been recorded yet.')}</p>
            <dl className="detail-field-grid">
              <div className="detail-field"><dt>status</dt><dd>{healthLabel(outputContract?.status)}</dd></div>
              <div className="detail-field"><dt>failure</dt><dd>{outputContract?.failure_kind || 'none'}</dd></div>
              <div className="detail-field"><dt>latest cost</dt><dd>{costText(costObservation?.estimated_cost_usd)}</dd></div>
            </dl>
          </article>
        </section>
        <RawJsonDetails summary="Recent bounded harness events" payload={harnessEvents} />
      </section>
      <section className="detail-summary">
        <p className="eyebrow">Controller memory</p>
        <h2>{memoryHeadline(memoryData.memory_warn)}</h2>
        <dl className="detail-field-grid">
          <div className="detail-field"><dt>rss</dt><dd>{mibText(memoryData.rss_mib)}</dd></div>
          <div className="detail-field"><dt>peak rss</dt><dd>{mibText(memoryData.peak_rss_mib)}</dd></div>
          <div className="detail-field"><dt>warn threshold</dt><dd>{mibText(memoryData.warn_threshold_mib)}</dd></div>
          <div className="detail-field"><dt>warning</dt><dd>{boolText(memoryData.memory_warn)}</dd></div>
        </dl>
      </section>
      <section className="detail-summary">
        <p className="eyebrow">Route observability</p>
        <h2>{routeObservabilityHeadline(healthData.route_observability_enabled)}</h2>
        <dl className="detail-field-grid">
          <div className="detail-field"><dt>enabled</dt><dd>{boolText(healthData.route_observability_enabled)}</dd></div>
          <div className="detail-field"><dt>custom log path</dt><dd>{boolText(healthData.route_observability_log_configured)}</dd></div>
          <div className="detail-field"><dt>health sampled</dt><dd>{healthData.generated_at || '—'}</dd></div>
          <div className="detail-field"><dt>memory sampled</dt><dd>{memoryData.generated_at || '—'}</dd></div>
        </dl>
        <RawJsonDetails summary="Latest route observation" payload={healthData.latest_route_observation} />
      </section>
      <section className="detail-summary">
        <p className="eyebrow">Sentry</p>
        <h2>{sentryHeadline(healthData.sentry_enabled, healthData.sentry_configured)}</h2>
        <dl className="detail-field-grid">
          <div className="detail-field"><dt>configured</dt><dd>{boolText(healthData.sentry_configured)}</dd></div>
          <div className="detail-field"><dt>enabled</dt><dd>{boolText(healthData.sentry_enabled)}</dd></div>
          <div className="detail-field"><dt>environment</dt><dd>{healthData.sentry_environment || '—'}</dd></div>
          <div className="detail-field"><dt>release</dt><dd>{healthData.sentry_release || '—'}</dd></div>
        </dl>
      </section>
    </PageShell>
  )
}
