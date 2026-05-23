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
  return typeof desired === 'number' && desired >= 0 ? desired : DEFAULT_DESIRED_QUEUE_DEPTH
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

function laneFeedReason(lane: WorkerLane): string | null {
  const queued = lane.queued_count ?? 0
  if (lane.status === 'active' && queued > 0) {
    return `${queued} queued waiting while this lane is active.`
  }
  if (!laneBelowDesiredDepth(lane)) return null
  return lane.feed_pressure?.operator_summary ?? laneDepthFeedMessage(lane)
}

function laneDisabledReason(lane: WorkerLane, canFeed: boolean, canDispatch: boolean): string {
  if (canDispatch) return 'Ready to dispatch queued work.'
  const blocker = lane.dispatch_blocker
  if (blocker) return blocker
  if (lane.status === 'active') return 'Lane is active.'
  if ((lane.queued_count ?? 0) <= 0) return 'No queued candidate for lane.'
  return canFeed
    ? 'Waiting for backend lane eligibility.'
    : `Next feed action is ${sentence(lane.feed_pressure?.next_autopilot_action)}.`
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
  return error instanceof Error ? error.message : String(error)
}

function dispatchDryRunAllowsLive(result: Record<string, unknown>): boolean {
  const action = displayText(result.action, '').toLowerCase()
  const reason = displayText(result.reason || result.detail, '').toLowerCase()
  if (action.includes('blocked') || action.includes('skipped') || reason.includes('blocked')) return false
  if (result.action === 'dry_run_dispatch_lanes') {
    if (Number(result.candidate_count || 0) <= 0) return false
    const laneResults = Array.isArray(result.results) ? result.results : []
    return laneResults.every((entry) => {
      if (!entry || typeof entry !== 'object') return false
      const payload = (entry as { result?: unknown }).result
      if (!payload || typeof payload !== 'object') return false
      return dispatchDryRunAllowsLive(payload as Record<string, unknown>)
    })
  }
  return action.includes('dry_run')
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
  return {
    action: dryRun ? 'dry_run_dispatch_lanes' : 'dispatch_lanes_started',
    reason: `${dryRun ? 'checked' : 'dispatched'} ${results.length} lane candidates`,
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
  return canDispatchAny ? 'aggregate-dispatch-next' : ''
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
  busyAction: 'feed' | 'feed-live' | 'dispatch' | 'dispatch-live' | null
  liveLaneProjectId: string
  onFeedLane: () => void
  onDispatchLane: (lane: WorkerLane) => void
  onLiveDispatchLane: (lane: WorkerLane) => void
}>

function LaneCard({ lane, busyAction, liveLaneProjectId, onFeedLane, onDispatchLane, onLiveDispatchLane }: LaneCardProps) {
  const feedAction = lane.feed_pressure?.next_autopilot_action || 'observe'
  const canFeed = feedAction === 'generate_candidate' || feedAction === 'promote_candidate'
  const canDispatch = Boolean(lane.dispatch_available)
  const projectId = displayText(lane.next_candidate?.project_id, '')
  const canLiveDispatchLane = canDispatch && Boolean(projectId) && liveLaneProjectId === projectId
  const active = displayText(lane.active_item?.project_name || lane.active_item?.project_id, '')
  const next = displayText(lane.next_candidate?.project_name || lane.next_candidate?.project_id, '')
  const feedReason = laneFeedReason(lane)
  const disabledReason = laneDisabledReason(lane, canFeed, canDispatch)
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
      <p className={reasonClassName}>{disabledReason}</p>
      <div className="lane-actions">
        <button className="secondary-button" disabled={!canFeed || busyAction !== null} onClick={onFeedLane}>Feed idle lane</button>
        <button className="secondary-button" disabled={!canDispatch || busyAction !== null} onClick={() => onDispatchLane(lane)}>Check dispatch</button>
        <button className="primary-button" disabled={!canLiveDispatchLane || busyAction !== null} onClick={() => onLiveDispatchLane(lane)}>Dispatch lane</button>
      </div>
    </article>
  )
}

export function WorkerLanes({ lanes, onRefresh, isLoading = false, error }: Readonly<WorkerLanesProps>) {
  const [commandResult, setCommandResult] = useState<CommandResult | null>(null)
  const [busyAction, setBusyAction] = useState<'feed' | 'feed-live' | 'dispatch' | 'dispatch-live' | null>(null)
  const [liveFeedReady, setLiveFeedReady] = useState(false)
  const [liveFeedSignature, setLiveFeedSignature] = useState('')
  const [liveLaneProjectId, setLiveLaneProjectId] = useState('')
  const [liveOpenLaneSignature, setLiveOpenLaneSignature] = useState('')
  const { confirm, dialog } = useOperatorDialog()
  const visible = lanes.filter((lane) => ['CPU lane', 'GB10 lane'].includes(laneLabel(lane)))
  const rendered = visible.length ? visible : lanes
  const explicitOpenLaneCandidates = rendered.filter((lane) => lane.dispatch_available && lane.next_candidate?.project_id)
  const feedEligibleLanes = rendered.filter((lane) => ['generate_candidate', 'promote_candidate'].includes(lane.feed_pressure?.next_autopilot_action || ''))
  const canFeedAny = rendered.some((lane) => ['generate_candidate', 'promote_candidate'].includes(lane.feed_pressure?.next_autopilot_action || ''))
  const canDispatchAny = rendered.some((lane) => lane.dispatch_available)
  const feedSignature = buildFeedSignature(feedEligibleLanes)
  const openLaneSignature = buildOpenLaneSignature(explicitOpenLaneCandidates, canDispatchAny)
  const canLiveFeed = canFeedAny && liveFeedReady && liveFeedSignature === feedSignature
  const canLiveDispatchOpenLanes = canDispatchAny && liveOpenLaneSignature === openLaneSignature
  const feedDisabledReason = globalFeedDisabledReason(canFeedAny, liveFeedReady, canLiveFeed, busyAction)
  const dispatchDisabledReason = globalDispatchDisabledReason(canDispatchAny, canLiveDispatchOpenLanes, busyAction)

  async function feedLane() {
    setBusyAction('feed')
    setLiveLaneProjectId('')
    setLiveOpenLaneSignature('')
    try {
      const result = await apiPost<Record<string, unknown>>('/control/api/research/run-cycle', dryRunCyclePayload)
      const allowed = feedDryRunAllowsLiveCycle(result)
      setCommandResult({ payload: result, context: { commandFamily: 'research' } })
      setLiveFeedReady(allowed)
      setLiveFeedSignature(allowed ? feedSignature : '')
      onRefresh()
    } catch (feedError) {
      setCommandResult({ payload: { ok: false, reason: errorMessage(feedError) }, context: { commandFamily: 'research' } })
      setLiveFeedReady(false)
      setLiveFeedSignature('')
    } finally {
      setBusyAction(null)
    }
  }

  async function liveFeedCycle() {
    if (!canLiveFeed) return
    const confirmed = await confirm({
      title: 'Run one bounded feed cycle?',
      message: 'This can spend one provider request and promote candidates. It will not dispatch, wait for completion, write papers, or finalize publications.',
      confirmLabel: 'Run feed cycle',
      tone: 'warn',
    })
    if (!confirmed) return
    setBusyAction('feed-live')
    setLiveLaneProjectId('')
    try {
      const result = await apiPost<Record<string, unknown>>('/control/api/research/run-cycle', liveCyclePayload)
      setCommandResult({ payload: result, context: { commandFamily: 'research' } })
      setLiveFeedReady(false)
      setLiveFeedSignature('')
      onRefresh()
    } catch (feedError) {
      setCommandResult({ payload: { ok: false, reason: errorMessage(feedError) }, context: { commandFamily: 'research' } })
    } finally {
      setBusyAction(null)
    }
  }

  async function dispatchLane(lane?: WorkerLane) {
    setBusyAction('dispatch')
    setLiveFeedReady(false)
    setLiveFeedSignature('')
    try {
      const projectId = displayText(lane?.next_candidate?.project_id, '')
      const result = await resolveDispatchDryRunResult(lane, projectId, explicitOpenLaneCandidates)
      setCommandResult({ payload: result, context: { commandFamily: 'dispatch' } })
      setLiveLaneProjectId(projectId && result.action === 'dry_run_dispatch_one' ? projectId : '')
      setLiveOpenLaneSignature(!projectId && dispatchDryRunAllowsLive(result) ? openLaneSignature : '')
      onRefresh()
    } catch (dispatchError) {
      setCommandResult({ payload: { ok: false, reason: errorMessage(dispatchError) }, context: { commandFamily: 'dispatch' } })
      setLiveLaneProjectId('')
      setLiveOpenLaneSignature('')
    } finally {
      setBusyAction(null)
    }
  }

  async function liveDispatchOpenLanes() {
    if (!canLiveDispatchOpenLanes) return
    const confirmed = await confirm({
      title: 'Dispatch open lanes?',
      message: 'This starts live dispatch for eligible queued work on open lanes. Use Check open lanes first if you want a dry-run preflight only.',
      confirmLabel: 'Dispatch work',
      tone: 'warn',
    })
    if (!confirmed) return
    setBusyAction('dispatch-live')
    setLiveLaneProjectId('')
    setLiveOpenLaneSignature('')
    setLiveFeedReady(false)
    setLiveFeedSignature('')
    try {
      const result = explicitOpenLaneCandidates.length > 0
        ? await dispatchExplicitLaneCandidates(explicitOpenLaneCandidates, false)
        : await apiPost<Record<string, unknown>>('/control/dispatch-next', { dry_run: false, requested_by: 'dashboard-v2', force_preflight: true })
      setCommandResult({ payload: result, context: { commandFamily: 'dispatch' } })
      onRefresh()
    } catch (dispatchError) {
      setCommandResult({ payload: { ok: false, reason: errorMessage(dispatchError) }, context: { commandFamily: 'dispatch' } })
    } finally {
      setBusyAction(null)
    }
  }

  async function liveDispatchLane(lane: WorkerLane) {
    const projectId = displayText(lane.next_candidate?.project_id, '')
    if (!projectId || liveLaneProjectId !== projectId) return
    const label = laneLabel(lane)
    const confirmed = await confirm({
      title: `Dispatch ${label}?`,
      message: `This starts live dispatch for exactly ${projectId}. Use Check dispatch again if the lane candidate changed.`,
      confirmLabel: 'Dispatch lane',
      tone: 'warn',
    })
    if (!confirmed) return
    setBusyAction('dispatch-live')
    setLiveFeedReady(false)
    setLiveFeedSignature('')
    try {
      const result = await apiPost<Record<string, unknown>>('/control/dispatch-one', { project_id: projectId, dry_run: false, requested_by: 'dashboard-v2', force_preflight: true })
      setCommandResult({ payload: result, context: { commandFamily: 'dispatch' } })
      setLiveLaneProjectId('')
      onRefresh()
    } catch (dispatchError) {
      setCommandResult({ payload: { ok: false, reason: errorMessage(dispatchError) }, context: { commandFamily: 'dispatch' } })
    } finally {
      setBusyAction(null)
    }
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
              <button className="secondary-button" disabled={!canFeedAny || busyAction !== null} onClick={feedLane}>Feed idle lanes</button>
              <button className="primary-button" disabled={!canLiveFeed || busyAction !== null} onClick={() => { void liveFeedCycle() }}>Run feed cycle</button>
              <button className="secondary-button" disabled={!canDispatchAny || busyAction !== null} onClick={() => { void dispatchLane() }}>Check open lanes</button>
              <button className="primary-button" disabled={!canLiveDispatchOpenLanes || busyAction !== null} onClick={() => { void liveDispatchOpenLanes() }}>Dispatch open lanes</button>
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
                onFeedLane={feedLane}
                onDispatchLane={(lane) => { dispatchLane(lane).catch(() => undefined) }}
                onLiveDispatchLane={(lane) => { liveDispatchLane(lane).catch(() => undefined) }}
              />
            ))}
          </div>
        ) : null}
      </section>
      {dialog}
    </>
  )
}
