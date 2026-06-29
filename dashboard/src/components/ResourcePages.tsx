import { useEffect, useState } from 'react'
import { displayText } from '../displayText'
import { formatReadinessErrorMessage } from '../readinessErrors'
import { useQuery } from '@tanstack/react-query'
import { apiGet, apiPost, saveToken } from '../api/client'
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
  BriefingCard,
  BriefingGrid,
  EntityLinkChips,
  LoadingStateCard,
  MetricStrip,
  OperatorDetailSummary,
  OperatorQuestionSections,
  PageShell,
  RawJsonDetails,
} from './ui'
import { PaperWorkflowNav } from './PaperWorkflowNav'
import { WorkbenchCountsFold, WorkbenchOperatorSummary } from './WorkbenchSummary'

type ObservabilityHealth = { generated_at?: string; route_observability_enabled?: boolean; route_observability_log_configured?: boolean; latest_route_observation?: string | null; sentry_enabled?: boolean; sentry_configured?: boolean; sentry_environment?: string; sentry_release?: string }
type ObservabilityMemory = { generated_at?: string; rss_mib?: number | null; peak_rss_mib?: number | null; warn_threshold_mib?: number | null; memory_warn?: boolean; route_observability_enabled?: boolean }
type BriefingTone = 'neutral' | 'good' | 'warn' | 'risk'
type ResourceRowCardTone = BriefingTone | 'info'
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
type QueueStatusContext = {
  counts?: Record<string, unknown>
  dispatch_safe?: boolean
  dispatch_blockers?: unknown[]
  queue_paused?: boolean
  maintenance_mode?: boolean
}

function refetchInBackground(refetch: () => Promise<unknown>): void {
  refetch().catch((error: unknown) => {
    handleBackgroundRefetchError(error)
  })
}

function refetchAllInBackground(...refetches: Array<() => Promise<unknown>>): void {
  for (const refetch of refetches) {
    refetchInBackground(refetch)
  }
}

/**
 * Inspect an error thrown by a background refetch and decide whether to
 * surface it. The previous implementation discarded every error with
 * `.catch(() => undefined)`, which meant a 401 (token expired/revoked) was
 * indistinguishable from a transient network blip. The user kept seeing
 * stale rows with no signal that auth had lapsed — and the TokenGate was
 * never invoked, so the only path to recovery was a manual page refresh.
 *
 * Detection rules:
 *   - `apiGet`/`apiPost` errors include the HTTP status in the message as
 *     `path -> <status>: detail`. Match `-> 401` case-insensitively.
 *   - Some callers wrap fetch errors in `Response`-style objects. Inspect
 *     for `.status === 401` defensively.
 *
 * When an auth lapse is detected:
 *   - Clear the saved token via `saveToken('')` (so a subsequent save can
 *     recover and the next mount of <Shell> does not auto-resume).
 *   - Dispatch `enoch:auth-lapsed`. App.tsx listens for this and forces a
 *     re-render of <Shell>, which then evaluates `hasToken` and shows
 *     <TokenGate>.
 *
 * All other errors are logged at warn level (not swallowed) so transient
 * network failures and 5xx remain visible in the browser console.
 */
export function handleBackgroundRefetchError(error: unknown): void {
  if (isAuthLapsedError(error)) {
    saveToken('')
    if (typeof globalThis.dispatchEvent === 'function' && typeof globalThis.CustomEvent === 'function') {
      globalThis.dispatchEvent(new globalThis.CustomEvent('enoch:auth-lapsed'))
    }
    return
  }
  if (typeof globalThis.console !== 'undefined' && typeof globalThis.console.warn === 'function') {
    const message = error instanceof Error ? error.message : String(error)
    globalThis.console.warn('[enoch-dashboard] background refetch failed:', message)
  }
}

export function isAuthLapsedError(error: unknown): boolean {
  if (error === null || error === undefined) return false
  // Response-shaped wrapper: { status: 401 } or { status: '401' }.
  if (typeof error === 'object') {
    const status = (error as { status?: unknown }).status
    if (status === 401 || status === '401') return true
  }
  // apiGet/apiPost format: "path -> 401: detail".
  const message = error instanceof Error ? error.message : typeof error === 'string' ? error : ''
  if (message && /->\s*401\b/i.test(message)) return true
  return false
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
  if ((data.unhealthy_count || 0) > 0) return 'Model endpoint health needs action'
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
  if ((data.failure_count ?? 0) > 0 || data.status === 'needs_attention') return 'Harness telemetry needs action'
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

function isGeneratedAtStale(generatedAt?: string): boolean {
  if (!generatedAt) return false
  const parsed = Date.parse(generatedAt)
  if (!Number.isFinite(parsed)) return false
  const ageMs = Date.now() - parsed
  return ageMs > 15 * 60 * 1000
}

function PageRefreshAction({ generatedAt, isFetching, onRefresh, label = 'Last loaded', refreshLabel = 'Refresh rows' }: Readonly<{ generatedAt?: string; isFetching: boolean; onRefresh: () => void; label?: string; refreshLabel?: string }>) {
  const stale = isGeneratedAtStale(generatedAt)
  return (
    <ActionRow ariaLabel={label}>
      <span>{label} {generatedAt || 'unknown'}</span>
      {stale ? <span className="refresh-stale-note">Data may be stale; refresh before operator action.</span> : null}
      <button className="secondary-button" type="button" disabled={isFetching} onClick={onRefresh}>
        {isFetching ? 'Refreshing…' : refreshLabel}
      </button>
    </ActionRow>
  )
}

function rowsWithStatus(rows: ReadonlyArray<Record<string, unknown>>, status: string): number {
  return rows.filter((row) => displayText(firstValue(row.status, row.queue_status)).toLowerCase() === status).length
}

function actionableQueueRows(rows: ReadonlyArray<Record<string, unknown>>): number {
  return rows.filter((row) => queueDispatchReadiness(row).tone === 'ready').length
}

function rowFieldText(row: Record<string, unknown>, keys: string[]): string {
  for (const key of keys) {
    const value = displayText(row[key], '')
    if (value) return value
  }
  return ''
}

function rowsWithAnyValue(rows: ReadonlyArray<Record<string, unknown>>, keys: string[], value: string): number {
  return rows.filter((row) => rowFieldText(row, keys).toLowerCase() === value).length
}

function activeOrWaitingRuns(rows: ReadonlyArray<Record<string, unknown>>): number {
  return rows.filter((row) => ['running', 'dispatching', 'awaiting_wake', 'wake_ready'].includes(displayText(row.state).toLowerCase())).length
}

function publicationReadyRows(rows: ReadonlyArray<Record<string, unknown>>): number {
  return rows.filter((row) => ['ready', 'publish_ready', 'publication_ready'].includes(rowFieldText(row, ['paper_status', 'status']).toLowerCase())).length
}

function evidenceMissingRows(rows: ReadonlyArray<Record<string, unknown>>): number {
  return rows.filter((row) => {
    const evidence = rowFieldText(row, ['evidence', 'evidence_status']).toLowerCase()
    return evidence === '' || evidence === 'missing'
  }).length
}

function firstHumanTitle(rows: ReadonlyArray<Record<string, unknown>>, keys: string[], fallback: string): string {
  for (const row of rows) {
    for (const key of keys) {
      const value = displayText(row[key], '')
      if (value) return value
    }
  }
  return fallback
}

function EmptyBriefingArticle({
  className,
  eyebrow = 'Empty slice',
  title,
  impact,
  nextAction,
  diagnostics,
}: Readonly<{
  className: string
  eyebrow?: string
  title: string
  impact: string
  nextAction: string
  diagnostics: string
}>) {
  return (
    <article className={className}>
      <p className="eyebrow">{eyebrow}</p>
      <h3>{title}</h3>
      <dl className="operator-state-facts">
        <div><dt>Impact</dt><dd>{impact}</dd></div>
        <div><dt>Next action</dt><dd>{nextAction}</dd></div>
        <div><dt>Diagnostics</dt><dd>{diagnostics}</dd></div>
      </dl>
    </article>
  )
}

function projectNeedsAttention(row: Record<string, unknown>): boolean {
  if (row.operator_attention === true) return true
  const tone = rowFieldText(row, ['operator_tone']).toLowerCase()
  const stage = rowFieldText(row, ['operator_stage', 'operator_detail_stage', 'queue_status', 'status', 'latest_run_state']).toLowerCase()
  return ['risk', 'warn', 'error'].includes(tone)
    || stage.includes('block')
    || stage.includes('fail')
    || stage.includes('error')
}

function projectIsRunning(row: Record<string, unknown>): boolean {
  const stage = rowFieldText(row, ['operator_stage', 'operator_detail_stage', 'queue_status', 'status', 'latest_run_state']).toLowerCase()
  return ['running', 'awaiting_wake', 'dispatching', 'wake_ready'].some((value) => stage.includes(value))
}

function projectIsReady(row: Record<string, unknown>): boolean {
  const stage = rowFieldText(row, ['operator_stage', 'operator_detail_stage', 'queue_status', 'status']).toLowerCase()
  return ['ready', 'queued', 'testing', 'exploring'].some((value) => stage.includes(value))
}

function projectCardTone(row: Record<string, unknown>): string {
  const tone = rowFieldText(row, ['operator_tone']).toLowerCase()
  if (projectNeedsAttention(row)) return tone === 'warn' ? 'warn' : 'risk'
  if (projectIsRunning(row)) return 'info'
  if (projectIsReady(row)) return 'good'
  return 'neutral'
}

function projectHealthLabel(row: Record<string, unknown>): string {
  return rowFieldText(row, ['operator_stage_label', 'operator_detail_stage_label', 'operator_stage', 'queue_status', 'status']) || 'Unknown'
}

function projectChangedLabel(row: Record<string, unknown>): string {
  const updated = rowFieldText(row, ['updated_at', 'created_at'])
  if (updated) return updated
  const ageSeconds = numericCount(row.age_seconds)
  if (ageSeconds > 0) return `${Math.round(ageSeconds / 60)} min ago`
  return 'No update timestamp'
}

function projectNextStep(row: Record<string, unknown>): string {
  return rowFieldText(row, ['operator_next_step', 'next_action_hint', 'operator_explanation']) || 'Open the row to inspect current project evidence.'
}

function projectArtifactSummary(row: Record<string, unknown>): string {
  const paths = row.related_artifact_paths_present
  if (!paths || typeof paths !== 'object' || Array.isArray(paths)) return 'artifact signals unavailable'
  const present = Object.values(paths as Record<string, unknown>).filter(Boolean).length
  if (present === 0) return 'no paper artifacts yet'
  return `${present} artifact signal(s) present`
}

function prioritizedProjectRows(rows: ReadonlyArray<Record<string, unknown>>): Record<string, unknown>[] {
  return [...rows]
    .sort((left, right) => {
      const attentionDelta = Number(projectNeedsAttention(right)) - Number(projectNeedsAttention(left))
      if (attentionDelta !== 0) return attentionDelta
      const runningDelta = Number(projectIsRunning(right)) - Number(projectIsRunning(left))
      if (runningDelta !== 0) return runningDelta
      const readyDelta = Number(projectIsReady(right)) - Number(projectIsReady(left))
      if (readyDelta !== 0) return readyDelta
      return 0
    })
    .slice(0, 3)
}

function projectBriefingHeadline(attention: number, running: number, ready: number, rowCount: number): string {
  if (attention > 0) return `${attention} workstream(s) blocked or need action`
  if (running > 0) return `${running} workstream(s) actively moving`
  if (ready > 0) return `${ready} ready workstream(s) available`
  if (rowCount > 0) return 'Workstreams are quiet or recently completed'
  return 'No project rows returned'
}

function projectBriefingTone(attention: number, running: number, ready: number): BriefingTone {
  if (attention > 0) return 'risk'
  if (running > 0) return 'neutral'
  if (ready > 0) return 'good'
  return 'neutral'
}

function ProjectsBriefing({ rows }: Readonly<{ rows: ReadonlyArray<Record<string, unknown>> }>) {
  const attention = rows.filter(projectNeedsAttention).length
  const running = rows.filter(projectIsRunning).length
  const ready = rows.filter(projectIsReady).length
  const completed = rowsWithStatus(rows, 'completed')
  const highlightedRows = prioritizedProjectRows(rows)
  const headline = projectBriefingHeadline(attention, running, ready, rows.length)
  const tone = projectBriefingTone(attention, running, ready)
  return (
    <>
      <BriefingGrid>
        <BriefingCard eyebrow="Workstream health" title={headline} detail="Projects now open with operator-stage health and action buckets before the diagnostic project table." tone={tone}>
          <MetricStrip ariaLabel="Project workstream health summary" items={[{ label: 'needs action', value: attention }, { label: 'running', value: running }, { label: 'ready', value: ready }]} />
        </BriefingCard>
        <BriefingCard eyebrow="Priority workstreams" title={highlightedRows.length > 0 ? 'Top visible workstreams are grouped by operator relevance' : 'No visible workstream to prioritize'} detail="Each card below answers what changed, whether the workstream is healthy, and the next action before IDs or copy controls." />
        <BriefingCard eyebrow="Drilldown evidence" title="IDs and diagnostic fields stay in row drilldowns" detail="Open a row for exact project ID, run links, dispatch history, paper artifacts, and diagnostic JSON evidence; the table remains the bounded evidence ledger." >
          <MetricStrip ariaLabel="Project evidence summary" items={[{ label: 'visible rows', value: rows.length }, { label: 'completed', value: completed }, { label: 'highlighted', value: highlightedRows.length }]} />
        </BriefingCard>
      </BriefingGrid>
      <section className="project-workstream-cards" aria-label="Prioritized project workstreams">
        {highlightedRows.length > 0 ? highlightedRows.map((row) => {
          const title = firstHumanTitle([row], ['project_name', 'title', 'project_id'], 'Untitled project')
          const explanation = rowFieldText(row, ['operator_explanation']) || 'No operator explanation recorded for this project row.'
          const tone = projectCardTone(row)
          return (
            <article className={`project-workstream-card project-workstream-card--${tone}`} key={displayText(row.project_id, title)}>
              <p className="eyebrow">{projectHealthLabel(row)}</p>
              <h3>{title}</h3>
              <p>{explanation}</p>
              <dl className="project-workstream-card__facts">
                <div><dt>Health</dt><dd>{projectHealthLabel(row)}</dd></div>
                <div><dt>Changed</dt><dd>{projectChangedLabel(row)}</dd></div>
                <div><dt>Next action</dt><dd>{projectNextStep(row)}</dd></div>
                <div><dt>Evidence</dt><dd>{projectArtifactSummary(row)}</dd></div>
              </dl>
            </article>
          )
        }) : (
          <EmptyBriefingArticle
            className="project-workstream-card"
            title="No project rows match this filter"
            impact="No workstream card can be prioritized from the current slice; dispatch safety is not changed by this empty view."
            nextAction="Clear filters or refresh before relying on Projects for workstream decisions."
            diagnostics="Use the table empty state and Data source disclosure for raw query context."
          />
        )}
      </section>
    </>
  )
}

function queueDispatchBlockers(statusContext?: QueueStatusContext): string[] {
  if (!Array.isArray(statusContext?.dispatch_blockers)) return []
  return statusContext.dispatch_blockers.map((item) => displayText(item)).filter(Boolean)
}

function queueSafetyTitle(statusUnavailable: boolean | undefined, dispatchSafe: boolean, blockers: string[], holdActive: boolean, canInspectDispatch: boolean): string {
  if (statusUnavailable) return 'Queue loaded; dispatch safety unavailable'
  if (dispatchSafe) return 'Safe to dispatch after selected dry-run'
  if (blockers.length > 0) return `Dispatch waits: ${blockers[0]}`
  if (holdActive) return 'Dispatch is intentionally held'
  if (canInspectDispatch) return 'Ready candidates are waiting for lane capacity'
  return 'No dispatchable candidate visible'
}

function queueSafetyDetail(statusUnavailable: boolean | undefined, dispatchSafe: boolean, blockers: string[]): string {
  if (statusUnavailable) return 'The queue rows loaded, but the global dispatch-safety endpoint did not return; retry refresh before live dispatch.'
  if (dispatchSafe) return 'Select one queued candidate, run the dry-run preflight, then dispatch only if the selected row stays unchanged.'
  if (blockers.length > 0) return 'The table still shows candidate readiness, but live dispatch should wait until the global safety blocker clears.'
  return 'Use selected-row dry-run before any live dispatch; raw lane hints remain in row drilldowns.'
}

function queueSafetyTone(statusUnavailable: boolean | undefined, dispatchSafe: boolean, blockers: string[], holdActive: boolean): BriefingTone {
  if (statusUnavailable) return 'warn'
  if (dispatchSafe) return 'good'
  if (blockers.length > 0 || holdActive) return 'warn'
  return 'neutral'
}

function queueCandidateTitle(canInspectDispatch: boolean): string {
  if (canInspectDispatch) return 'Ready candidates stay grouped above raw rows'
  return 'No ready candidate in this slice'
}

function queueCandidateTone(blocked: number): BriefingTone {
  if (blocked > 0) return 'risk'
  return 'neutral'
}

function QueueBriefing({
  rows,
  queueCounts,
  statusContext,
  statusUnavailable,
}: Readonly<{
  rows: ReadonlyArray<Record<string, unknown>>
  queueCounts?: Record<string, unknown>
  statusContext?: QueueStatusContext
  statusUnavailable?: boolean
}>) {
  const queued = numericCount(statusContext?.counts?.queued ?? queueCounts?.queued) || rowsWithStatus(rows, 'queued')
  const activeCount = numericCount(statusContext?.counts?.active ?? queueCounts?.active)
  const blocked = rowsWithStatus(rows, 'blocked')
  const completed = rowsWithStatus(rows, 'completed')
  const readyHere = actionableQueueRows(rows)
  const blockers = queueDispatchBlockers(statusContext)
  const dispatchSafe = statusContext?.dispatch_safe === true
  const holdActive = statusContext?.queue_paused === true || statusContext?.maintenance_mode === true
  const canInspectDispatch = queued > 0 || readyHere > 0
  const safetyTitle = queueSafetyTitle(statusUnavailable, dispatchSafe, blockers, holdActive, canInspectDispatch)
  const safetyDetail = queueSafetyDetail(statusUnavailable, dispatchSafe, blockers)
  const safetyTone = queueSafetyTone(statusUnavailable, dispatchSafe, blockers, holdActive)
  const candidateTitle = queueCandidateTitle(canInspectDispatch)
  const candidateTone = queueCandidateTone(blocked)
  return (
    <BriefingGrid>
      <BriefingCard eyebrow="Dispatch safety" title={safetyTitle} detail={safetyDetail} tone={safetyTone}>
        <MetricStrip ariaLabel="Queue dispatch safety summary" items={[{ label: 'queued', value: queued }, { label: 'active lanes', value: activeCount }, { label: 'blockers', value: blockers.length }]} />
      </BriefingCard>
      <BriefingCard eyebrow="Candidate groups" title={candidateTitle} detail="Rows below remain the evidence table; this briefing translates queue status into operator action buckets first." tone={candidateTone}>
        <MetricStrip ariaLabel="Queue candidate grouping summary" items={[{ label: 'ready here', value: readyHere }, { label: 'blocked here', value: blocked }, { label: 'completed here', value: completed }]} />
      </BriefingCard>
      <BriefingCard eyebrow="Action sequence" title="Select candidate → dry-run → dispatch" detail="Live dispatch stays disabled until the selected queued row passes a dry-run and remains unchanged after refresh." />
    </BriefingGrid>
  )
}

function runStateText(row: Record<string, unknown>): string {
  return rowFieldText(row, ['operator_stage', 'operator_detail_stage', 'state', 'gate_state']).toLowerCase()
}

function runNeedsAttention(row: Record<string, unknown>): boolean {
  if (row.operator_attention === true) return true
  const tone = rowFieldText(row, ['operator_tone']).toLowerCase()
  const state = runStateText(row)
  return ['risk', 'warn', 'error'].includes(tone)
    || state.includes('fail')
    || state.includes('error')
    || state.includes('blocked')
}

function runIsActive(row: Record<string, unknown>): boolean {
  const state = runStateText(row)
  return ['running', 'dispatching', 'awaiting_wake'].some((value) => state.includes(value))
}

function runIsComplete(row: Record<string, unknown>): boolean {
  const state = runStateText(row)
  return state.includes('complete') || state.includes('wake_ready') || state === 'completed'
}

function runSubject(row: Record<string, unknown>): string {
  const projectName = rowFieldText(row, ['project_name'])
  if (projectName) return projectName
  const projectId = rowFieldText(row, ['project_id'])
  if (projectId) return projectId.replaceAll('-', ' ')
  return 'Untitled run'
}

function runHealthLabel(row: Record<string, unknown>): string {
  return rowFieldText(row, ['operator_stage_label', 'operator_detail_stage_label', 'state', 'gate_state']) || 'Unknown'
}

function runOutcomeLabel(row: Record<string, unknown>): string {
  if (runNeedsAttention(row)) return 'Needs investigation'
  if (runIsActive(row)) return 'In progress'
  if (runIsComplete(row)) return runHealthLabel(row)
  return 'Unknown outcome'
}

function runEvidenceSummary(row: Record<string, unknown>): string {
  const paths = row.related_artifact_paths_present
  if (!paths || typeof paths !== 'object' || Array.isArray(paths)) return 'artifact signals unavailable'
  const present = Object.values(paths as Record<string, unknown>).filter(Boolean).length
  if (present > 0) return `${present} artifact signal(s) present`
  if (rowFieldText(row, ['last_callback_at', 'ended_at'])) return 'callback observed; no paper artifacts yet'
  return 'waiting for callback or artifact evidence'
}

function runTimelineItems(row: Record<string, unknown>): ReadonlyArray<Readonly<{ label: string; value: string }>> {
  return [
    { label: 'Started', value: rowFieldText(row, ['started_at']) || 'start time unknown' },
    { label: 'Gate / worker', value: rowFieldText(row, ['gate_state', 'current_activity', 'dispatch_mode']) || 'worker state unknown' },
    { label: 'Callback / outcome', value: rowFieldText(row, ['last_callback_at', 'ended_at']) || runOutcomeLabel(row) },
    { label: 'Evidence', value: runEvidenceSummary(row) },
  ]
}

function prioritizedRunRows(rows: ReadonlyArray<Record<string, unknown>>): Record<string, unknown>[] {
  return [...rows]
    .sort((left, right) => {
      const attentionDelta = Number(runNeedsAttention(right)) - Number(runNeedsAttention(left))
      if (attentionDelta !== 0) return attentionDelta
      const activeDelta = Number(runIsActive(right)) - Number(runIsActive(left))
      if (activeDelta !== 0) return activeDelta
      const completeDelta = Number(runIsComplete(right)) - Number(runIsComplete(left))
      if (completeDelta !== 0) return completeDelta
      return 0
    })
    .slice(0, 3)
}

function runBriefingHeadline(attention: number, active: number, completed: number, rowCount: number): string {
  if (attention > 0) return `${attention} recent run(s) need investigation`
  if (active > 0) return `${active} run(s) are in progress`
  if (completed > 0) return `${completed} recent run(s) reached an outcome`
  if (rowCount > 0) return 'Recent runs need timeline review'
  return 'No run rows returned'
}

function runBriefingTone(attention: number, active: number, completed: number): BriefingTone {
  if (attention > 0) return 'risk'
  if (active > 0) return 'neutral'
  if (completed > 0) return 'good'
  return 'neutral'
}

function runCardTone(row: Record<string, unknown>): ResourceRowCardTone {
  if (runNeedsAttention(row)) return 'risk'
  if (runIsActive(row)) return 'info'
  if (runIsComplete(row)) return 'good'
  return 'neutral'
}

function RunsBriefing({ rows }: Readonly<{ rows: ReadonlyArray<Record<string, unknown>> }>) {
  const attention = rows.filter(runNeedsAttention).length
  const active = rows.filter(runIsActive).length
  const completed = rows.filter(runIsComplete).length
  const storyRows = prioritizedRunRows(rows)
  const headline = runBriefingHeadline(attention, active, completed, rows.length)
  const tone = runBriefingTone(attention, active, completed)
  return (
    <>
      <BriefingGrid>
        <BriefingCard eyebrow="Run story" title={headline} detail="Runs now lead with outcome, callback, and evidence state before diagnostic IDs, gates, and worker internals." tone={tone}>
          <MetricStrip ariaLabel="Run story summary" items={[{ label: 'needs action', value: attention }, { label: 'in progress', value: active }, { label: 'outcome', value: completed }]} />
        </BriefingCard>
        <BriefingCard eyebrow="Timeline hierarchy" title={storyRows.length > 0 ? 'Top visible runs are summarized as timelines' : 'No visible run timeline'} detail="Each story card shows start, gate/worker step, callback/outcome, and evidence before the diagnostic run ledger." />
        <BriefingCard eyebrow="Drilldown evidence" title="Run IDs, callback internals, and logs stay in drilldowns" detail="Use the table and row detail panel for exact run identifiers, copied links, callback evidence, gates, and diagnostic JSON evidence." />
      </BriefingGrid>
      <section className="run-story-cards" aria-label="Prioritized run stories">
        {storyRows.length > 0 ? storyRows.map((row) => {
          const title = runSubject(row)
          const tone = runCardTone(row)
          return (
            <article className={`run-story-card run-story-card--${tone}`} key={displayText(row.run_id, title)}>
              <p className="eyebrow">{runHealthLabel(row)}</p>
              <h3>{title}</h3>
              <p>{rowFieldText(row, ['operator_explanation']) || 'No operator explanation recorded for this run row.'}</p>
              <ol className="run-story-timeline">
                {runTimelineItems(row).map((item) => (
                  <li key={item.label}>
                    <span>{item.label}</span>
                    <strong>{item.value}</strong>
                  </li>
                ))}
              </ol>
              <p className="run-story-next"><strong>Next action:</strong> {rowFieldText(row, ['operator_next_step', 'current_activity']) || 'Open the row for forensic run details.'}</p>
            </article>
          )
        }) : (
          <EmptyBriefingArticle
            className="run-story-card"
            title="No run rows match this filter"
            impact="No run timeline can be summarized from the current slice; this is visibility-only and does not block dispatch by itself."
            nextAction="Clear filters or refresh before relying on Runs for callback, gate, or evidence timing."
            diagnostics="Use the table empty state and Data source disclosure for raw query context."
          />
        )}
      </section>
    </>
  )
}

function paperStatusText(row: Record<string, unknown>): string {
  return rowFieldText(row, ['operator_stage', 'operator_detail_stage', 'review_status', 'paper_status', 'status']).toLowerCase()
}

function paperNeedsAttention(row: Record<string, unknown>): boolean {
  if (row.operator_attention === true) return true
  const tone = rowFieldText(row, ['operator_tone']).toLowerCase()
  const status = paperStatusText(row)
  return ['risk', 'warn', 'error'].includes(tone)
    || status.includes('missing')
    || status.includes('blocked')
    || status.includes('failed')
}

function paperArtifactCount(row: Record<string, unknown>): number {
  const flags = row.artifact_paths_present
  if (!flags || typeof flags !== 'object' || Array.isArray(flags)) return 0
  return Object.values(flags as Record<string, unknown>).filter(Boolean).length
}

function paperHasCompleteEvidence(row: Record<string, unknown>): boolean {
  const flags = row.artifact_paths_present
  if (!flags || typeof flags !== 'object' || Array.isArray(flags)) return false
  const record = flags as Record<string, unknown>
  return (record.evidence_bundle_path === true || record.evidence_bundle === true)
    && (record.claim_ledger_path === true || record.claim_ledger === true)
    && (record.manifest_path === true || record.manifest === true)
}

function paperIsReady(row: Record<string, unknown>): boolean {
  const status = paperStatusText(row)
  return row.corpus_imported === true
    || status.includes('finalized')
    || status.includes('ready')
    || paperHasCompleteEvidence(row)
}

function paperNeedsEvidence(row: Record<string, unknown>): boolean {
  if (paperNeedsAttention(row)) return true
  if (paperIsReady(row) && paperArtifactCount(row) > 0) return false
  const status = paperStatusText(row)
  return paperArtifactCount(row) === 0 || status.includes('draft') || status.includes('review')
}

function paperSubject(row: Record<string, unknown>): string {
  const explicit = rowFieldText(row, ['title', 'paper_title'])
  if (explicit) return explicit
  const projectName = rowFieldText(row, ['project_name'])
  if (projectName) return projectName
  const projectId = rowFieldText(row, ['project_id'])
  if (projectId) return projectId.replaceAll('-', ' ')
  const slug = rowFieldText(row, ['artifact_slug'])
  if (slug) return slug.replaceAll('-', ' ')
  return 'Untitled publication artifact'
}

function paperReadinessLabel(row: Record<string, unknown>): string {
  const label = rowFieldText(row, ['operator_stage_label', 'operator_detail_stage_label', 'review_status', 'paper_status', 'status'])
  if (!label) return 'Unknown readiness'
  return label.replaceAll('review', 'gate').replaceAll('Review', 'Gate')
}

function paperAutomationCopy(value: string): string {
  return value
    .replaceAll('paper/review', 'paper gate')
    .replaceAll('Paper/review', 'Paper gate')
    .replaceAll('review', 'gate')
    .replaceAll('Review', 'Gate')
}

function paperEvidenceLabel(row: Record<string, unknown>): string {
  const count = paperArtifactCount(row)
  if (paperHasCompleteEvidence(row)) return `complete evidence package (${count} artifact signal(s))`
  if (count > 0) return `partial evidence package (${count} artifact signal(s))`
  return 'no artifact evidence visible'
}

function paperCorpusLabel(row: Record<string, unknown>): string {
  if (row.corpus_imported === true) return 'imported to corpus'
  if (row.hf_dataset_synced === true) return 'dataset sync recorded'
  if (rowFieldText(row, ['corpus_import_id', 'corpus_imported_at'])) return 'corpus import activity recorded'
  return 'not imported to corpus yet'
}

function paperNextStep(row: Record<string, unknown>): string {
  return paperAutomationCopy(rowFieldText(row, ['operator_next_step', 'operator_explanation']) || 'Open the row for artifact paths, draft IDs, and publication evidence.')
}

function prioritizedPaperRows(rows: ReadonlyArray<Record<string, unknown>>): Record<string, unknown>[] {
  return [...rows]
    .sort((left, right) => {
      const attentionDelta = Number(paperNeedsAttention(right)) - Number(paperNeedsAttention(left))
      if (attentionDelta !== 0) return attentionDelta
      const evidenceDelta = Number(paperNeedsEvidence(right)) - Number(paperNeedsEvidence(left))
      if (evidenceDelta !== 0) return evidenceDelta
      const readyDelta = Number(paperIsReady(right)) - Number(paperIsReady(left))
      if (readyDelta !== 0) return readyDelta
      return paperArtifactCount(right) - paperArtifactCount(left)
    })
    .slice(0, 3)
}

function paperBriefingTitle(attention: number, evidenceReview: number, ready: number, rowCount: number): string {
  if (attention > 0) return `Current page: ${attention} of ${rowCount} visible paper row(s) are blocked by deterministic publication gates`
  if (evidenceReview > 0) return `Current page: ${evidenceReview} of ${rowCount} visible paper row(s) need evidence-gate completion`
  if (ready > 0) return `Current page: ${ready} of ${rowCount} visible paper row(s) passed publication evidence gates`
  if (rowCount > 0) return 'Current page publication rows are awaiting gate classification'
  return 'No paper rows returned'
}

function paperBriefingTone(attention: number, evidenceReview: number, ready: number): BriefingTone {
  if (attention > 0) return 'risk'
  if (evidenceReview > 0) return 'warn'
  if (ready > 0) return 'good'
  return 'neutral'
}

function paperCardTone(row: Record<string, unknown>): BriefingTone {
  if (paperNeedsAttention(row)) return 'risk'
  if (paperNeedsEvidence(row)) return 'warn'
  if (paperIsReady(row)) return 'good'
  return 'neutral'
}

function PapersBriefing({ rows, counts, page }: Readonly<{ rows: ReadonlyArray<Record<string, unknown>>, counts?: Record<string, unknown>, page?: Record<string, unknown> }>) {
  const attention = rows.filter(paperNeedsAttention).length
  const evidenceReview = rows.filter(paperNeedsEvidence).length
  const ready = rows.filter(paperIsReady).length
  const imported = rows.filter((row) => row.corpus_imported === true).length
  const artifactRows = prioritizedPaperRows(rows)
  const title = paperBriefingTitle(attention, evidenceReview, ready, rows.length)
  const tone = paperBriefingTone(attention, evidenceReview, ready)
  const totalRows = counts?.all ?? 'unknown'
  const publicationRows = counts?.publication_draft ?? 'unknown'
  const returnedRows = page?.returned ?? rows.length
  return (
    <>
      <BriefingGrid>
        <BriefingCard eyebrow="Publication automation gates" title={title} detail={`This is an automation gate summary for the currently loaded table page/filter (${returnedRows} visible row(s)); it is not the public corpus total or Paper Material Graph count, and it is not a manual approval queue. Total SQL paper rows: ${totalRows}; publication-draft rows: ${publicationRows}.`} tone={tone}>
          <MetricStrip ariaLabel="Paper automation gate summary" items={[{ label: 'visible rows', value: rows.length }, { label: 'visible gate-blocked', value: evidenceReview }, { label: 'visible imported', value: imported }]} />
        </BriefingCard>
        <BriefingCard eyebrow="Artifact outcomes" title={artifactRows.length > 0 ? 'Top visible papers are summarized as publication artifacts' : 'No visible paper artifact'} detail="Each card below names the artifact, deterministic gate state, evidence package, corpus state, and next automation step while keeping exact draft IDs in the table/detail views." />
        <BriefingCard eyebrow="Drilldown evidence" title="Draft IDs and artifact paths stay in drilldowns" detail="Use the table and row detail panel for composite paper IDs, import IDs, finalization package paths, corpus manifests, and diagnostic JSON evidence." />
      </BriefingGrid>
      <section className="paper-artifact-cards" aria-label="Prioritized publication artifacts">
        {artifactRows.length > 0 ? artifactRows.map((row) => {
          const subject = paperSubject(row)
          const tone = paperCardTone(row)
          return (
            <article className={`paper-artifact-card paper-artifact-card--${tone}`} key={displayText(row.paper_id, subject)}>
              <p className="eyebrow">{paperReadinessLabel(row)}</p>
              <h3>{subject}</h3>
              <p>{paperAutomationCopy(rowFieldText(row, ['operator_explanation']) || 'No operator explanation recorded for this paper artifact.')}</p>
              <dl className="paper-artifact-card__facts">
                <div>
                  <dt>Evidence</dt>
                  <dd>{paperEvidenceLabel(row)}</dd>
                </div>
                <div>
                  <dt>Corpus</dt>
                  <dd>{paperCorpusLabel(row)}</dd>
                </div>
                <div>
                  <dt>Next automation step</dt>
                  <dd>{paperNextStep(row)}</dd>
                </div>
              </dl>
            </article>
          )
        }) : (
          <EmptyBriefingArticle
            className="paper-artifact-card"
            title="No paper rows match this filter"
            impact="No publication artifact card can be prioritized from the current slice; research and dispatch lanes are unaffected."
            nextAction="Clear filters or refresh before relying on Papers for publication gate state."
            diagnostics="Use the table empty state and Data source disclosure for raw query context."
          />
        )}
      </section>
    </>
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
        <p className="eyebrow">Selected dispatch action</p>
        <h2>{displayText(firstValue(selection?.row?.project_name, selection?.row?.title), displayText(selectedProjectId, 'No row selected'))}</h2>
        {selectedProjectId ? <span className="detail-id-chip" title={selectedProjectId}>{shortId(selectedProjectId)}</span> : null}
        <p>{selection?.row ? queueDispatchReadiness(selection.row).label : selectedDispatchReason(selection)}</p>
      </div>
      <ol className="queue-action-steps" aria-label="Selected dispatch action sequence">
        <li className={canDryRunSelected ? 'queue-action-steps__item queue-action-steps__item--ready' : 'queue-action-steps__item'}>Select queued row</li>
        <li className={canLiveDispatchSelected ? 'queue-action-steps__item queue-action-steps__item--ready' : 'queue-action-steps__item'}>Dry-run preflight</li>
        <li className={canLiveDispatchSelected ? 'queue-action-steps__item queue-action-steps__item--ready' : 'queue-action-steps__item'}>Live dispatch</li>
      </ol>
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
  const queueHasLiveStatusContext = Boolean((query.data as Record<string, unknown> | undefined)?.source)
  const statusQuery = useQuery({
    queryKey: ['queue-dispatch-status'],
    queryFn: () => apiGet<QueueStatusContext>('/control/api/status?refresh_worker=true'),
    enabled: queueHasLiveStatusContext,
    retry: 1,
  })
  if (query.isLoading) return <LoadingStateCard label="queue" />
  if (query.isError) return <ResourceErrorCard endpoint="queue" error={query.error} onRetry={() => { refetchInBackground(() => query.refetch()) }} retryLabel="Retry queue" />
  const dispatch = deriveQueueDispatchState(query.data?.rows, selection, liveDispatchProjectId, liveDispatchSignature, dispatchBusy)
  const rows = query.data?.rows || []
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
      <PageShell title="Queue" subtitle="Inspect queue rows, dry-run dispatch, and start selected work safely." dataSource="/control/api/v1/queue" action={<PageRefreshAction generatedAt={query.data?.generated_at} isFetching={query.isFetching || statusQuery.isFetching} onRefresh={() => { queueHasLiveStatusContext ? refetchAllInBackground(() => query.refetch(), () => statusQuery.refetch()) : refetchInBackground(() => query.refetch()) }} />}>
        <QueueBriefing rows={rows} queueCounts={query.data?.counts} statusContext={statusQuery.data} statusUnavailable={statusQuery.isError} />
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
        <DataTable rows={rows} columns={queueTableColumns} empty={deriveQueueEmpty({ search: filters.search, status: filters.status, activeCount: numericCount(query.data?.counts?.active) })} cellHref={detailCellHref} onSelectRow={(row) => { setDispatchResult(null); setLiveDispatchProjectId(''); setLiveDispatchSignature(''); setSelection({ kind: 'project', id: displayText(row.project_id), row }) }} />
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
  const rows = query.data?.rows || []
  return (
    <PageShell title="Projects" subtitle="Search projects and open structured detail before dispatch or paper actions." dataSource="/control/api/v1/projects" action={<PageRefreshAction generatedAt={query.data?.generated_at} isFetching={query.isFetching} onRefresh={() => { refetchInBackground(() => query.refetch()) }} />}>
      <ProjectsBriefing rows={rows} />
      <ListFilterBar state={filters} statusOptions={[{ label: 'all project states', value: '' }, { label: 'testing', value: 'testing' }, { label: 'exploring', value: 'exploring' }, { label: 'queued', value: 'queued' }, { label: 'running', value: 'running' }, { label: 'completed', value: 'completed' }, { label: 'blocked', value: 'blocked' }]} onApply={(next) => { setFilters(next); replaceRouteHash(statusHash('#projects', 'status', next)) }} onReset={() => { const next = { search: '', status: route.status, pageSize: '50', cursor: '' }; setFilters(next); replaceRouteHash(statusHash('#projects', 'status', next)) }} onNext={() => setFilters({ ...filters, cursor: query.data?.page?.next_cursor || '' })} page={query.data?.page} />
      <DataTable rows={rows} columns={projectsTableColumns} empty={deriveProjectsEmpty({ search: filters.search, status: filters.status })} cellHref={detailCellHref} onSelectRow={(row) => setSelection({ kind: 'project', id: displayText(row.project_id), row })} />
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
  const rows = query.data?.rows || []
  return (
    <PageShell title="Runs" subtitle="Inspect run state, gates, activity, and related artifacts." dataSource="/control/api/v1/runs" action={<PageRefreshAction generatedAt={query.data?.generated_at} isFetching={query.isFetching} onRefresh={() => { refetchInBackground(() => query.refetch()) }} />}>
      <RunsBriefing rows={rows} />
      <ListFilterBar state={filters} statusOptions={[{ label: 'all run states', value: '' }, { label: 'running', value: 'running' }, { label: 'dispatching', value: 'dispatching' }, { label: 'awaiting wake', value: 'awaiting_wake' }, { label: 'dispatch error', value: 'dispatch_error' }, { label: 'completed', value: 'completed' }, { label: 'wake ready', value: 'wake_ready' }]} onApply={(next) => { setFilters(next); replaceRouteHash(runsRouteHash(next)) }} onReset={() => { const next = { search: '', status: route.state, pageSize: '50', cursor: '' }; setFilters(next); replaceRouteHash(runsRouteHash(next)) }} onNext={() => setFilters({ ...filters, cursor: query.data?.page?.next_cursor || '' })} page={query.data?.page} />
      <DataTable rows={rows} columns={runsTableColumns} empty={deriveRunsEmpty({ search: filters.search, status: filters.status })} cellHref={detailCellHref} onSelectRow={(row) => setSelection({ kind: 'run', id: displayText(row.run_id), row })} />
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
  const rows = query.data?.rows || []
  return (
    <PageShell title="Papers" subtitle="Track draft, finalization, and publication gate state." dataSource="/control/api/v1/papers" action={<PageRefreshAction generatedAt={query.data?.generated_at} isFetching={query.isFetching} onRefresh={() => { refetchInBackground(() => query.refetch()) }} />}>
      <PaperWorkflowNav active="papers" />
      <PapersBriefing rows={rows} counts={query.data?.counts} page={query.data?.page as Record<string, unknown> | undefined} />
      <ListFilterBar state={filters} statusOptions={[{ label: 'all paper statuses', value: '' }, { label: 'publication draft', value: 'publication_draft' }, { label: 'draft gate', value: 'draft_review' }, { label: 'archived', value: 'archived' }]} onApply={(next) => { setFilters(next); replaceRouteHash(statusHash('#papers', 'status', next)) }} onReset={() => { const next = { search: '', status: route.status, pageSize: '50', cursor: '' }; setFilters(next); replaceRouteHash(statusHash('#papers', 'status', next)) }} onNext={() => setFilters({ ...filters, cursor: query.data?.page?.next_cursor || '' })} page={query.data?.page} />
      <DataTable rows={rows} columns={papersTableColumns} empty={derivePapersEmpty({ search: filters.search, status: filters.status })} cellHref={detailCellHref} onSelectRow={(row) => setSelection({ kind: 'paper', id: displayText(row.paper_id), row })} />
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
    <PageShell title="Idea intake" subtitle="Inspect admitted ideas, queue state, and next operator actions." dataSource="/control/api/intake/ideas" action={<PageRefreshAction generatedAt={data.generated_at} isFetching={query.isFetching} onRefresh={() => { setSelection(null); refetchInBackground(() => query.refetch()) }} refreshLabel="Refresh intake" />}>
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
