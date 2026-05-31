import { useState } from 'react'
import { apiPost } from '../api/client'
import { displayText } from '../displayText'
import { dryRunCyclePayload, liveCyclePayload } from '../researchCyclePayloads'
import type { WorkerLane } from '../types'
import { useOperatorDialog } from './OperatorDialog'
import type { CommandPresentationContext } from '../commandResultPresentation'
import { CommandResultSummary } from './CommandResultSummary'
import { feedDryRunAllowsLiveCycle } from '../feedDryRun'

type CommandResult = {
  payload: Record<string, unknown>
  context?: CommandPresentationContext
}

type WorkerLanesProps = {
  lanes: WorkerLane[]
  onRefresh: () => void
  isLoading?: boolean
  error?: unknown
}

function laneLabel(lane: WorkerLane): string {
  const target = displayText(lane.machine_target || lane.lane_key, '').toLowerCase()
  const role = displayText(lane.worker_role, '').toLowerCase()
  const knownLane = [
    { match: target.includes('cpu') || role.includes('cpu'), label: 'CPU lane' },
    { match: target.includes('gb10') || role.includes('gpu'), label: 'GB10 lane' },
  ].find((entry) => entry.match)
  return knownLane?.label ?? displayText(lane.label, displayText(lane.machine_target, 'Worker lane'))
}

function sentence(value?: string | null): string {
  return displayText(value, 'observe').replaceAll('_', ' ')
}

const DEFAULT_DESIRED_QUEUE_DEPTH = 25

function laneDesiredQueueDepth(lane: WorkerLane): number {
  const desired = lane.feed_pressure?.desired_queue_depth
  if (typeof desired === 'number' && desired >= 0) return desired
  return DEFAULT_DESIRED_QUEUE_DEPTH
}

function laneQueueDepthLabel(lane: WorkerLane): string {
  const queued = lane.queued_count ?? 0
  return `${queued} / ${laneDesiredQueueDepth(lane)}`
}

function laneBelowDesiredDepth(lane: WorkerLane): boolean {
  return (lane.queued_count ?? 0) < laneDesiredQueueDepth(lane)
}

function laneDepthFeedMessage(lane: WorkerLane): string {
  const feedAction = lane.feed_pressure?.next_autopilot_action || 'observe'
  const label = laneLabel(lane)
  const depthMessages: Record<string, string> = {
    promote_candidate: `${label} needs admitted candidates promoted to reach queue depth.`,
    generate_candidate: `${label} needs generated work to reach queue depth.`,
  }
  return depthMessages[feedAction] ?? `${label} is below desired queue depth.`
}

function laneActiveQueueReason(lane: WorkerLane): string | null {
  const queued = lane.queued_count ?? 0
  if (lane.status !== 'active' || queued <= 0) return null
  return `${queued} queued waiting while this lane is active.`
}

function laneFeedReason(lane: WorkerLane): string | null {
  const activeReason = laneActiveQueueReason(lane)
  if (activeReason) return activeReason
  if (!laneBelowDesiredDepth(lane)) return null
  return lane.feed_pressure?.operator_summary ?? laneDepthFeedMessage(lane)
}

function laneBlockedMessage(lane: WorkerLane, canFeed: boolean): string {
  const blocker = lane.dispatch_blocker
  if (blocker) return blocker
  if (lane.status === 'active') return 'Lane is active.'
  if ((lane.queued_count ?? 0) <= 0) return 'No queued candidate for lane.'
  if (canFeed) return 'Waiting for backend lane eligibility.'
  return `Next feed action is ${sentence(lane.feed_pressure?.next_autopilot_action)}.`
}

function laneDisabledReason(lane: WorkerLane, canFeed: boolean, canDispatch: boolean): string {
  if (canDispatch) return 'Ready to dispatch queued work.'
  return laneBlockedMessage(lane, canFeed)
}

function laneConfirmationMessage(lane: WorkerLane): string | null {
  if (lane.status !== 'active') return null
  const state = displayText(lane.active_confirmation?.state, 'unknown')
  const reason = displayText(lane.active_confirmation?.reason, '')
  if (state === 'unknown' && reason) return `Worker confirmation unavailable: ${reason}.`
  const messages: Record<string, string> = {
    active_confirmed: 'Worker confirmed active run.',
    active_unconfirmed: 'Active row is not confirmed by worker telemetry.',
    active_unconfirmed_grace: 'Worker restart grace: active row is not confirmed yet.',
    preflight_stale_after_dispatch: 'Worker telemetry is older than this dispatch; refresh lane preflight.',
    stale_active: 'Stale active: worker reports no matching live run.',
    unknown: 'Worker confirmation unavailable.',
  }
  return messages[state] ?? null
}

function laneConfirmationClass(lane: WorkerLane): string {
  const state = displayText(lane.active_confirmation?.state, 'unknown')
  if (state === 'active_confirmed') return 'lane-confirmation lane-confirmation--good'
  if (state === 'active_unconfirmed_grace') return 'lane-confirmation lane-confirmation--warn'
  if (state === 'stale_active') return 'lane-confirmation lane-confirmation--bad'
  return 'lane-confirmation'
}

function laneHasStaleActiveConfirmation(lane: WorkerLane): boolean {
  return displayText(lane.active_confirmation?.state, '') === 'stale_active'
}

function ResultCard({ result, stale }: Readonly<{ result: CommandResult | null; stale?: boolean }>) {
  if (!result) return null
  return <CommandResultSummary result={{ payload: result.payload, context: { ...result.context, stale: stale || result.context?.stale } }} />
}

function commandResultStale(
  result: CommandResult | null,
  liveFeedReady: boolean,
  liveFeedSignature: string,
  feedSignature: string,
  liveOpenLaneSignature: string,
  openLaneSignature: string,
): boolean {
  if (!result) return false
  if (result.context?.commandFamily === 'research') {
    return liveFeedReady && liveFeedSignature !== feedSignature
  }
  if (result.context?.commandFamily === 'dispatch') {
    return Boolean(liveOpenLaneSignature) && liveOpenLaneSignature !== openLaneSignature
  }
  return false
}

function errorMessage(error: unknown): string {
  if (error instanceof globalThis.Error) return error.message
  return String(error)
}

function dryRunLaneEntryAllowsLive(entry: unknown): boolean {
  if (!entry || typeof entry !== 'object') return false
  const payload = (entry as { result?: unknown }).result
  if (!payload || typeof payload !== 'object') return false
  return dispatchDryRunAllowsLive(payload as Record<string, unknown>)
}

function dispatchDryRunIsBlocked(result: Record<string, unknown>): boolean {
  const action = displayText(result.action, '').toLowerCase()
  const reason = displayText(result.reason || result.detail, '').toLowerCase()
  if (action.includes('blocked')) return true
  if (action.includes('skipped')) return true
  return reason.includes('blocked')
}

function dispatchMultiLaneDryRunAllowsLive(result: Record<string, unknown>): boolean {
  if (Number(result.candidate_count || 0) <= 0) return false
  const laneResults = Array.isArray(result.results) ? result.results : []
  return laneResults.every(dryRunLaneEntryAllowsLive)
}

function dispatchDryRunAllowsLive(result: Record<string, unknown>): boolean {
  if (dispatchDryRunIsBlocked(result)) return false
  if (result.action === 'dry_run_dispatch_lanes') return dispatchMultiLaneDryRunAllowsLive(result)
  return displayText(result.action, '').toLowerCase().includes('dry_run')
}

function globalFeedDisabledReason(canFeedAny: boolean, liveFeedReady: boolean, canLiveFeed: boolean, busyAction: string | null): string {
  if (busyAction) return 'Feed idle lanes disabled: another lane command is running.'
  if (liveFeedReady && !canLiveFeed) return 'Run feed cycle disabled: lane state changed; run Feed idle lanes again.'
  if (!canFeedAny) return 'Feed idle lanes disabled: no lane is asking to generate or promote work.'
  if (!canLiveFeed) return 'Run feed cycle disabled: run Feed idle lanes first.'
  return ''
}

function globalDispatchDisabledReason(canDispatchAny: boolean, canLiveDispatchOpenLanes: boolean, busyAction: string | null): string {
  if (busyAction) return 'Dispatch open lanes disabled: another lane command is running.'
  if (!canDispatchAny) return 'Dispatch open lanes disabled: no lane can dispatch queued work.'
  if (!canLiveDispatchOpenLanes) return 'Dispatch open lanes disabled: run Check open lanes first.'
  return ''
}

async function dispatchExplicitLaneCandidates(candidateLanes: WorkerLane[], dryRun: boolean): Promise<Record<string, unknown>> {
  const results = []
  for (const lane of candidateLanes) {
    const projectId = displayText(lane.next_candidate?.project_id, '')
    results.push({
      lane: laneLabel(lane),
      project_id: projectId,
      result: await apiPost<Record<string, unknown>>('/control/dispatch-one', {
        project_id: projectId,
        dry_run: dryRun,
        requested_by: 'dashboard-v2',
        force_preflight: true,
      }),
    })
  }
  let action = 'dispatch_lanes_started'
  let verb = 'dispatched'
  if (dryRun) {
    action = 'dry_run_dispatch_lanes'
    verb = 'checked'
  }
  return {
    action,
    reason: `${verb} ${results.length} lane candidates`,
    candidate_count: results.length,
    results,
  }
}

function buildFeedSignature(feedEligibleLanes: WorkerLane[]): string {
  if (feedEligibleLanes.length === 0) return ''
  return feedEligibleLanes
    .map((lane) => [
      displayText(lane.lane_key || lane.machine_target, laneLabel(lane)),
      displayText(lane.feed_pressure?.next_autopilot_action, ''),
      lane.queued_count ?? 0,
      displayText(lane.status, ''),
    ].join(':'))
    .join('|')
}

function buildOpenLaneSignature(explicitOpenLaneCandidates: WorkerLane[], canDispatchAny: boolean): string {
  if (explicitOpenLaneCandidates.length > 0) {
    return explicitOpenLaneCandidates.map((lane) => displayText(lane.next_candidate?.project_id, '')).join('|')
  }
  if (canDispatchAny) return 'aggregate-dispatch-next'
  return ''
}

function feedSignatureAfterDryRun(allowed: boolean, signature: string): string {
  if (!allowed) return ''
  return signature
}

function liveProjectIdAfterDispatchDryRun(projectId: string, result: Record<string, unknown>): string {
  if (!projectId) return ''
  if (result.action !== 'dry_run_dispatch_one') return ''
  return projectId
}

function openLaneSignatureAfterDispatchDryRun(
  projectId: string,
  result: Record<string, unknown>,
  signature: string,
): string {
  if (projectId) return ''
  if (!dispatchDryRunAllowsLive(result)) return ''
  return signature
}

async function runLiveOpenLaneDispatch(explicitOpenLaneCandidates: WorkerLane[]): Promise<Record<string, unknown>> {
  if (explicitOpenLaneCandidates.length > 0) {
    return dispatchExplicitLaneCandidates(explicitOpenLaneCandidates, false)
  }
  return apiPost<Record<string, unknown>>('/control/dispatch-next', {
    dry_run: false,
    requested_by: 'dashboard-v2',
    force_preflight: true,
  })
}

function selectRenderedLanes(lanes: WorkerLane[]): WorkerLane[] {
  const visible = lanes.filter((lane) => ['CPU lane', 'GB10 lane'].includes(laneLabel(lane)))
  if (visible.length > 0) return visible
  return lanes
}

async function resolveDispatchDryRunResult(
  lane: WorkerLane | undefined,
  projectId: string,
  explicitOpenLaneCandidates: WorkerLane[],
): Promise<Record<string, unknown>> {
  if (projectId) {
    return apiPost<Record<string, unknown>>('/control/dispatch-one', {
      project_id: projectId,
      dry_run: true,
      requested_by: 'dashboard-v2',
      force_preflight: true,
    })
  }
  if (explicitOpenLaneCandidates.length > 0) {
    return dispatchExplicitLaneCandidates(explicitOpenLaneCandidates, true)
  }
  return apiPost<Record<string, unknown>>('/control/dispatch-next', { dry_run: true, requested_by: 'dashboard-v2', force_preflight: true })
}

function laneProjectLabel(item: { project_name?: string; project_id?: string } | null | undefined): string {
  return displayText(item?.project_name || item?.project_id, '')
}

function researchCommandErrorPayload(error: unknown): CommandResult {
  return { payload: { ok: false, reason: errorMessage(error) }, context: { commandFamily: 'research' } }
}

function dispatchCommandErrorPayload(error: unknown): CommandResult {
  return { payload: { ok: false, reason: errorMessage(error) }, context: { commandFamily: 'dispatch' } }
}

type LaneEmptyStateProps = Readonly<{
  error?: unknown
  isLoading: boolean
  hasLanes: boolean
}>

function LaneEmptyState({ error, isLoading, hasLanes }: LaneEmptyStateProps) {
  if (error) {
    return (
      <output className="lane-empty-state lane-empty-state--error">
        <strong>Worker lane status unavailable.</strong>
        <p>{errorMessage(error)}</p>
      </output>
    )
  }
  if (isLoading) {
    return (
      <output className="lane-empty-state">
        <strong>Loading worker lane capacity…</strong>
        <p>Waiting for /control/api/status before enabling feed or dispatch controls.</p>
      </output>
    )
  }
  if (!hasLanes) {
    return (
      <output className="lane-empty-state">
        <strong>No worker lane capacity returned.</strong>
        <p>The status endpoint did not include CPU or GB10 lane data, so V2 cannot safely feed or dispatch work from this panel.</p>
      </output>
    )
  }
  return null
}

type LaneCardProps = Readonly<{
  lane: WorkerLane
  busyAction: 'feed' | 'feed-live' | 'dispatch' | 'dispatch-live' | 'reconcile' | null
  liveLaneProjectId: string
  onFeedLane: () => void
  onDispatchLane: (lane: WorkerLane) => void
  onLiveDispatchLane: (lane: WorkerLane) => void
  onReconcileLane: (lane: WorkerLane) => void
}>

function LaneCard({ lane, busyAction, liveLaneProjectId, onFeedLane, onDispatchLane, onLiveDispatchLane, onReconcileLane }: LaneCardProps) {
  const feedAction = lane.feed_pressure?.next_autopilot_action || 'observe'
  const canFeed = feedAction === 'generate_candidate' || feedAction === 'promote_candidate'
  const canDispatch = Boolean(lane.dispatch_available)
  const projectId = displayText(lane.next_candidate?.project_id, '')
  const canLiveDispatchLane = canDispatch && Boolean(projectId) && liveLaneProjectId === projectId
  const active = laneProjectLabel(lane.active_item)
  const next = laneProjectLabel(lane.next_candidate)
  const feedReason = laneFeedReason(lane)
  const disabledReason = laneDisabledReason(lane, canFeed, canDispatch)
  const confirmationMessage = laneConfirmationMessage(lane)
  const canReconcile = laneHasStaleActiveConfirmation(lane)
  const reasonClassName = canDispatch ? 'lane-reason lane-reason--ready' : 'lane-reason'
  const label = laneLabel(lane)

  return (
    <article className="lane-card">
      <div className="lane-card-top">
        <div>
          <p className="eyebrow">{label}</p>
          <h3>{displayText(lane.status, 'unknown')}</h3>
        </div>
        <div className="lane-queue-count" aria-label={`${label} queue depth ${laneQueueDepthLabel(lane)} queued`}>
          <strong>{laneQueueDepthLabel(lane)}</strong>
          <span>queued</span>
        </div>
      </div>
      <dl className="lane-facts">
        <div>
          <dt>Current</dt>
          <dd>{active || 'idle'}</dd>
        </div>
        <div>
          <dt>Next</dt>
          <dd>{next || 'none'}</dd>
        </div>
        <div>
          <dt>Feed action</dt>
          <dd>{sentence(feedAction)}</dd>
        </div>
      </dl>
      {feedReason ? <p className="lane-feed-reason">{feedReason}</p> : null}
      {confirmationMessage ? <p className={laneConfirmationClass(lane)}>{confirmationMessage}</p> : null}
      <p className={reasonClassName}>{disabledReason}</p>
      <div className="lane-actions">
        <button className="secondary-button" disabled={!canFeed || busyAction !== null} onClick={onFeedLane}>Feed idle lane</button>
        <button className="secondary-button" disabled={!canDispatch || busyAction !== null} onClick={() => onDispatchLane(lane)}>Check dispatch</button>
        {canReconcile ? <button className="secondary-button" disabled={busyAction !== null} onClick={() => onReconcileLane(lane)}>Run safe reconcile</button> : null}
        <button className="primary-button" disabled={!canLiveDispatchLane || busyAction !== null} onClick={() => onLiveDispatchLane(lane)}>Dispatch lane</button>
      </div>
    </article>
  )
}


type WorkerLaneCommandDeps = Readonly<{
  feedSignature: string
  openLaneSignature: string
  explicitOpenLaneCandidates: WorkerLane[]
  canLiveFeed: boolean
  canLiveDispatchOpenLanes: boolean
  onRefresh: () => void
  confirm: (options: { title: string; message: string; confirmLabel: string; tone: 'warn' | 'danger' }) => Promise<boolean>
  setBusyAction: (action: 'feed' | 'feed-live' | 'dispatch' | 'dispatch-live' | 'reconcile' | null) => void
  setCommandResult: (result: CommandResult | null) => void
  setLiveFeedReady: (ready: boolean) => void
  setLiveFeedSignature: (signature: string) => void
  setLiveLaneProjectId: (projectId: string) => void
  setLiveOpenLaneSignature: (signature: string) => void
}>

async function runFeedLaneDryRun(deps: WorkerLaneCommandDeps): Promise<void> {
  deps.setBusyAction('feed')
  deps.setLiveLaneProjectId('')
  deps.setLiveOpenLaneSignature('')
  try {
    const result = await apiPost<Record<string, unknown>>('/control/api/research/run-cycle', dryRunCyclePayload)
    const allowed = feedDryRunAllowsLiveCycle(result)
    deps.setCommandResult({ payload: result, context: { commandFamily: 'research' } })
    deps.setLiveFeedReady(allowed)
    deps.setLiveFeedSignature(feedSignatureAfterDryRun(allowed, deps.feedSignature))
    deps.onRefresh()
  } catch (feedError) {
    deps.setCommandResult(researchCommandErrorPayload(feedError))
    deps.setLiveFeedReady(false)
    deps.setLiveFeedSignature('')
  } finally {
    deps.setBusyAction(null)
  }
}

async function runLiveFeedCycle(deps: WorkerLaneCommandDeps): Promise<void> {
  if (!deps.canLiveFeed) return
  const confirmed = await deps.confirm({
    title: 'Run one bounded feed cycle?',
    message: 'This can spend one provider request and promote candidates. It will not dispatch, wait for completion, write papers, or finalize publications.',
    confirmLabel: 'Run feed cycle',
    tone: 'warn',
  })
  if (!confirmed) return
  deps.setBusyAction('feed-live')
  deps.setLiveLaneProjectId('')
  try {
    const result = await apiPost<Record<string, unknown>>('/control/api/research/run-cycle', liveCyclePayload)
    deps.setCommandResult({ payload: result, context: { commandFamily: 'research' } })
    deps.setLiveFeedReady(false)
    deps.setLiveFeedSignature('')
    deps.onRefresh()
  } catch (feedError) {
    deps.setCommandResult(researchCommandErrorPayload(feedError))
  } finally {
    deps.setBusyAction(null)
  }
}

async function runDispatchLaneDryRun(deps: WorkerLaneCommandDeps, lane?: WorkerLane): Promise<void> {
  deps.setBusyAction('dispatch')
  deps.setLiveFeedReady(false)
  deps.setLiveFeedSignature('')
  try {
    const projectId = displayText(lane?.next_candidate?.project_id, '')
    const result = await resolveDispatchDryRunResult(lane, projectId, deps.explicitOpenLaneCandidates)
    deps.setCommandResult({ payload: result, context: { commandFamily: 'dispatch' } })
    deps.setLiveLaneProjectId(liveProjectIdAfterDispatchDryRun(projectId, result))
    deps.setLiveOpenLaneSignature(openLaneSignatureAfterDispatchDryRun(projectId, result, deps.openLaneSignature))
    deps.onRefresh()
  } catch (dispatchError) {
    deps.setCommandResult(dispatchCommandErrorPayload(dispatchError))
    deps.setLiveLaneProjectId('')
    deps.setLiveOpenLaneSignature('')
  } finally {
    deps.setBusyAction(null)
  }
}

async function runLiveDispatchOpenLanes(deps: WorkerLaneCommandDeps): Promise<void> {
  if (!deps.canLiveDispatchOpenLanes) return
  const confirmed = await deps.confirm({
    title: 'Dispatch open lanes?',
    message: 'This starts live dispatch for eligible queued work on open lanes. Use Check open lanes first if you want a dry-run preflight only.',
    confirmLabel: 'Dispatch work',
    tone: 'warn',
  })
  if (!confirmed) return
  deps.setBusyAction('dispatch-live')
  deps.setLiveLaneProjectId('')
  deps.setLiveOpenLaneSignature('')
  deps.setLiveFeedReady(false)
  deps.setLiveFeedSignature('')
  try {
    const result = await runLiveOpenLaneDispatch(deps.explicitOpenLaneCandidates)
    deps.setCommandResult({ payload: result, context: { commandFamily: 'dispatch' } })
    deps.onRefresh()
  } catch (dispatchError) {
    deps.setCommandResult(dispatchCommandErrorPayload(dispatchError))
  } finally {
    deps.setBusyAction(null)
  }
}

async function runLiveDispatchLane(deps: WorkerLaneCommandDeps, lane: WorkerLane, liveLaneProjectId: string): Promise<void> {
  const projectId = displayText(lane.next_candidate?.project_id, '')
  if (!projectId || liveLaneProjectId !== projectId) return
  const label = laneLabel(lane)
  const confirmed = await deps.confirm({
    title: `Dispatch ${label}?`,
    message: `This starts live dispatch for exactly ${projectId}. Use Check dispatch again if the lane candidate changed.`,
    confirmLabel: 'Dispatch lane',
    tone: 'warn',
  })
  if (!confirmed) return
  deps.setBusyAction('dispatch-live')
  deps.setLiveFeedReady(false)
  deps.setLiveFeedSignature('')
  try {
    const result = await apiPost<Record<string, unknown>>('/control/dispatch-one', {
      project_id: projectId,
      dry_run: false,
      requested_by: 'dashboard-v2',
      force_preflight: true,
    })
    deps.setCommandResult({ payload: result, context: { commandFamily: 'dispatch' } })
    deps.setLiveLaneProjectId('')
    deps.onRefresh()
  } catch (dispatchError) {
    deps.setCommandResult(dispatchCommandErrorPayload(dispatchError))
  } finally {
    deps.setBusyAction(null)
  }
}

async function runSafeStaleActiveReconcile(deps: WorkerLaneCommandDeps, lane: WorkerLane): Promise<void> {
  if (!laneHasStaleActiveConfirmation(lane)) return
  const confirmed = await deps.confirm({
    title: 'Run safe stale-active reconcile?',
    message: 'This runs the queue alert reconcile path. The backend only mutates state when deterministic stale-active conditions and local decision/evidence gates pass.',
    confirmLabel: 'Run reconcile',
    tone: 'warn',
  })
  if (!confirmed) return
  deps.setBusyAction('reconcile')
  try {
    const activeProjectId = displayText(lane.active_item?.project_id, '')
    const activeRunId = displayText(lane.active_item?.current_run_id, '')
    const result = await apiPost<Record<string, unknown>>('/control/api/alerts/queue-check', {
      dry_run: false,
      requested_by: 'dashboard-v2',
      refresh_worker: false,
      lane_key: displayText(lane.lane_key, ''),
      machine_target: displayText(lane.machine_target, ''),
      project_id: activeProjectId,
      run_id: activeRunId,
    })
    deps.setCommandResult({ payload: result, context: { commandFamily: 'dispatch' } })
    deps.onRefresh()
  } catch (reconcileError) {
    deps.setCommandResult(dispatchCommandErrorPayload(reconcileError))
  } finally {
    deps.setBusyAction(null)
  }
}


export function WorkerLanes({ lanes, onRefresh, isLoading = false, error }: Readonly<WorkerLanesProps>) {
  const [commandResult, setCommandResult] = useState<CommandResult | null>(null)
  const [busyAction, setBusyAction] = useState<'feed' | 'feed-live' | 'dispatch' | 'dispatch-live' | 'reconcile' | null>(null)
  const [liveFeedReady, setLiveFeedReady] = useState(false)
  const [liveFeedSignature, setLiveFeedSignature] = useState('')
  const [liveLaneProjectId, setLiveLaneProjectId] = useState('')
  const [liveOpenLaneSignature, setLiveOpenLaneSignature] = useState('')
  const { confirm, dialog } = useOperatorDialog()
  const rendered = selectRenderedLanes(lanes)
  const explicitOpenLaneCandidates = rendered.filter((lane) => lane.dispatch_available && lane.next_candidate?.project_id)
  const feedEligibleLanes = rendered.filter((lane) =>
    ['generate_candidate', 'promote_candidate'].includes(lane.feed_pressure?.next_autopilot_action || ''),
  )
  const canFeedAny = feedEligibleLanes.length > 0
  const canDispatchAny = rendered.some((lane) => lane.dispatch_available)
  const feedSignature = buildFeedSignature(feedEligibleLanes)
  const openLaneSignature = buildOpenLaneSignature(explicitOpenLaneCandidates, canDispatchAny)
  const canLiveFeed = canFeedAny && liveFeedReady && liveFeedSignature === feedSignature
  const canLiveDispatchOpenLanes = canDispatchAny && liveOpenLaneSignature === openLaneSignature
  const feedDisabledReason = globalFeedDisabledReason(canFeedAny, liveFeedReady, canLiveFeed, busyAction)
  const dispatchDisabledReason = globalDispatchDisabledReason(canDispatchAny, canLiveDispatchOpenLanes, busyAction)

  const commandDeps: WorkerLaneCommandDeps = {
    feedSignature,
    openLaneSignature,
    explicitOpenLaneCandidates,
    canLiveFeed,
    canLiveDispatchOpenLanes,
    onRefresh,
    confirm,
    setBusyAction,
    setCommandResult,
    setLiveFeedReady,
    setLiveFeedSignature,
    setLiveLaneProjectId,
    setLiveOpenLaneSignature,
  }

  const showLaneGrid = !error && !isLoading && rendered.length > 0

  return (
    <>
      <section className="lane-console" aria-label="Worker lanes">
        <div className="lane-console-head">
          <div>
            <p className="eyebrow">Worker lanes</p>
            <h2>CPU / GB10 command surface</h2>
            <p>Dispatch and feed from each lane card. Bulk lane commands are secondary.</p>
          </div>
          <details className="lane-bulk-actions">
            <summary>Bulk lane commands</summary>
            <div className="lane-console-actions">
              <button className="secondary-button" disabled={!canFeedAny || busyAction !== null} onClick={() => { void runFeedLaneDryRun(commandDeps) }}>Feed idle lanes</button>
              <button className="primary-button" disabled={!canLiveFeed || busyAction !== null} onClick={() => { void runLiveFeedCycle(commandDeps) }}>Run feed cycle</button>
              <button className="secondary-button" disabled={!canDispatchAny || busyAction !== null} onClick={() => { void runDispatchLaneDryRun(commandDeps) }}>Check open lanes</button>
              <button className="primary-button" disabled={!canLiveDispatchOpenLanes || busyAction !== null} onClick={() => { void runLiveDispatchOpenLanes(commandDeps) }}>Dispatch open lanes</button>
              {feedDisabledReason || dispatchDisabledReason ? (
                <div className="lane-command-reasons" aria-label="Worker lane command disabled reasons">
                  {feedDisabledReason ? <p>{feedDisabledReason}</p> : null}
                  {dispatchDisabledReason ? <p>{dispatchDisabledReason}</p> : null}
                </div>
              ) : null}
            </div>
          </details>
        </div>
        <ResultCard result={commandResult} stale={commandResultStale(commandResult, liveFeedReady, liveFeedSignature, feedSignature, liveOpenLaneSignature, openLaneSignature)} />
        <LaneEmptyState error={error} isLoading={isLoading} hasLanes={rendered.length > 0} />
        {showLaneGrid ? (
          <div className="lane-grid">
            {rendered.map((lane) => (
              <LaneCard
                key={displayText(lane.lane_key || lane.machine_target, laneLabel(lane))}
                lane={lane}
                busyAction={busyAction}
                liveLaneProjectId={liveLaneProjectId}
                onFeedLane={() => { void runFeedLaneDryRun(commandDeps) }}
                onDispatchLane={(targetLane) => { void runDispatchLaneDryRun(commandDeps, targetLane) }}
                onLiveDispatchLane={(targetLane) => { void runLiveDispatchLane(commandDeps, targetLane, liveLaneProjectId) }}
                onReconcileLane={(targetLane) => { void runSafeStaleActiveReconcile(commandDeps, targetLane) }}
              />
            ))}
          </div>
        ) : null}
      </section>
      {dialog}
    </>
  )
}
