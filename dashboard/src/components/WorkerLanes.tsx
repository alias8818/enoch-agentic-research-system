import { useState } from 'react'
import { apiPost } from '../api/client'
import type { WorkerLane } from '../types'
import { useOperatorDialog } from './OperatorDialog'

type CommandResult = {
  title: string
  payload: Record<string, unknown>
}

type WorkerLanesProps = {
  lanes: WorkerLane[]
  onRefresh: () => void
  isLoading?: boolean
  error?: unknown
}

const dryRunCyclePayload = {
  enabled: false,
  dry_run: true,
  requested_by: 'dashboard-v2',
  max_provider_requests_per_run: 1,
  max_promotions_per_run: 2,
  max_dispatches_per_run: 0,
  wait_for_completion: false,
  max_wait_seconds: 0,
  max_paper_drafts_per_run: 0,
  max_publication_rewrites_per_run: 0,
  generation_max_tokens: 8000,
  generation_attempts: 2,
  temperature: 0.6,
}

const liveCyclePayload = {
  ...dryRunCyclePayload,
  enabled: true,
  dry_run: false,
}

function laneLabel(lane: WorkerLane): string {
  const target = String(lane.machine_target || lane.lane_key || '').toLowerCase()
  const role = String(lane.worker_role || '').toLowerCase()
  if (target.includes('cpu') || role.includes('cpu')) return 'CPU lane'
  if (target.includes('gb10') || role.includes('gpu')) return 'GB10 lane'
  return lane.label || lane.machine_target || 'Worker lane'
}

function sentence(value?: string | null): string {
  return String(value || 'observe').replaceAll('_', ' ')
}

function laneDisabledReason(lane: WorkerLane, canFeed: boolean, canDispatch: boolean): string {
  if (canDispatch) return 'Ready to dispatch queued work.'
  if (lane.dispatch_blocker) return lane.dispatch_blocker
  if (lane.status === 'active') return 'Lane is active.'
  if ((lane.queued_count ?? 0) <= 0) return 'No queued candidate for lane.'
  if (!canFeed) return `Next feed action is ${sentence(lane.feed_pressure?.next_autopilot_action)}.`
  return 'Waiting for backend lane eligibility.'
}

function ResultCard({ result }: { result: CommandResult | null }) {
  if (!result) return null
  const reason = String(result.payload.reason || result.payload.detail || result.payload.action || 'Command completed.')
  return (
    <section className="result-card lane-command-result" aria-live="polite">
      <h3>{result.title}</h3>
      <p>{reason}</p>
      <pre>{JSON.stringify(result.payload, null, 2)}</pre>
    </section>
  )
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}

export function WorkerLanes({ lanes, onRefresh, isLoading = false, error }: WorkerLanesProps) {
  const [commandResult, setCommandResult] = useState<CommandResult | null>(null)
  const [busyAction, setBusyAction] = useState<'feed' | 'feed-live' | 'dispatch' | 'dispatch-live' | null>(null)
  const [liveFeedReady, setLiveFeedReady] = useState(false)
  const [liveLaneProjectId, setLiveLaneProjectId] = useState('')
  const { confirm, dialog } = useOperatorDialog()
  const visible = lanes.filter((lane) => ['CPU lane', 'GB10 lane'].includes(laneLabel(lane)))
  const rendered = visible.length ? visible : lanes
  const explicitOpenLaneCandidates = rendered.filter((lane) => lane.dispatch_available && lane.next_candidate?.project_id)
  const canFeedAny = rendered.some((lane) => ['generate_candidate', 'promote_candidate'].includes(lane.feed_pressure?.next_autopilot_action || ''))
  const canDispatchAny = rendered.some((lane) => lane.dispatch_available)

  async function dispatchExplicitLaneCandidates(candidateLanes: WorkerLane[], dryRun: boolean): Promise<Record<string, unknown>> {
    const results = []
    for (const lane of candidateLanes) {
      const projectId = lane.next_candidate?.project_id || ''
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

  async function feedLane() {
    setBusyAction('feed')
    setLiveLaneProjectId('')
    try {
      const result = await apiPost<Record<string, unknown>>('/control/api/research/run-cycle', dryRunCyclePayload)
      setCommandResult({ title: 'Feed dry-run result', payload: result })
      setLiveFeedReady(result.dry_run === true || String(result.action || '').includes('dry_run'))
      onRefresh()
    } catch (error) {
      setCommandResult({ title: 'Feed dry-run failed', payload: { ok: false, reason: error instanceof Error ? error.message : String(error) } })
      setLiveFeedReady(false)
    } finally {
      setBusyAction(null)
    }
  }

  async function liveFeedCycle() {
    if (!liveFeedReady) return
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
      setCommandResult({ title: 'Live feed result', payload: result })
      setLiveFeedReady(false)
      onRefresh()
    } catch (error) {
      setCommandResult({ title: 'Live feed failed', payload: { ok: false, reason: error instanceof Error ? error.message : String(error) } })
    } finally {
      setBusyAction(null)
    }
  }

  async function dispatchLane(lane?: WorkerLane) {
    setBusyAction('dispatch')
    setLiveFeedReady(false)
    try {
      const projectId = lane?.next_candidate?.project_id || ''
      const result = projectId
        ? await apiPost<Record<string, unknown>>('/control/dispatch-one', { project_id: projectId, dry_run: true, requested_by: 'dashboard-v2', force_preflight: true })
        : explicitOpenLaneCandidates.length > 0
          ? await dispatchExplicitLaneCandidates(explicitOpenLaneCandidates, true)
          : await apiPost<Record<string, unknown>>('/control/dispatch-next', { dry_run: true, requested_by: 'dashboard-v2', force_preflight: true })
      setCommandResult({ title: 'Dispatch dry-run result', payload: result })
      setLiveLaneProjectId(projectId && result.action === 'dry_run_dispatch_one' ? projectId : '')
      onRefresh()
    } catch (error) {
      setCommandResult({ title: 'Dispatch dry-run failed', payload: { ok: false, reason: error instanceof Error ? error.message : String(error) } })
      setLiveLaneProjectId('')
    } finally {
      setBusyAction(null)
    }
  }

  async function liveDispatchOpenLanes() {
    const confirmed = await confirm({
      title: 'Dispatch open lanes?',
      message: 'This starts live dispatch for eligible queued work on open lanes. Use Check open lanes first if you want a dry-run preflight only.',
      confirmLabel: 'Dispatch work',
      tone: 'warn',
    })
    if (!confirmed) return
    setBusyAction('dispatch-live')
    setLiveLaneProjectId('')
    setLiveFeedReady(false)
    try {
      const result = explicitOpenLaneCandidates.length > 0
        ? await dispatchExplicitLaneCandidates(explicitOpenLaneCandidates, false)
        : await apiPost<Record<string, unknown>>('/control/dispatch-next', { dry_run: false, requested_by: 'dashboard-v2', force_preflight: true })
      setCommandResult({ title: 'Live dispatch result', payload: result })
      onRefresh()
    } catch (error) {
      setCommandResult({ title: 'Live dispatch failed', payload: { ok: false, reason: error instanceof Error ? error.message : String(error) } })
    } finally {
      setBusyAction(null)
    }
  }

  async function liveDispatchLane(lane: WorkerLane) {
    const projectId = lane.next_candidate?.project_id || ''
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
    try {
      const result = await apiPost<Record<string, unknown>>('/control/dispatch-one', { project_id: projectId, dry_run: false, requested_by: 'dashboard-v2', force_preflight: true })
      setCommandResult({ title: 'Lane live dispatch result', payload: result })
      setLiveLaneProjectId('')
      onRefresh()
    } catch (error) {
      setCommandResult({ title: 'Lane live dispatch failed', payload: { ok: false, reason: error instanceof Error ? error.message : String(error) } })
    } finally {
      setBusyAction(null)
    }
  }

  return (
    <>
      <section className="lane-console" aria-label="Worker lanes">
        <div className="lane-console-head">
          <div>
            <p className="eyebrow">Worker lanes</p>
            <h2>CPU / GB10 command surface</h2>
            <p>Lane state is the source of truth. Aggregate queue counts do not decide dispatch.</p>
          </div>
          <div className="lane-console-actions">
            <button className="secondary-button" disabled={!canFeedAny || busyAction !== null} onClick={feedLane}>Feed idle lanes</button>
            <button className="primary-button" disabled={!liveFeedReady || busyAction !== null} onClick={() => { void liveFeedCycle() }}>Run feed cycle</button>
            <button className="secondary-button" disabled={!canDispatchAny || busyAction !== null} onClick={() => { void dispatchLane() }}>Check open lanes</button>
            <button className="primary-button" disabled={!canDispatchAny || busyAction !== null} onClick={() => { void liveDispatchOpenLanes() }}>Dispatch open lanes</button>
          </div>
        </div>
        <ResultCard result={commandResult} />
        {error ? (
          <div className="lane-empty-state lane-empty-state--error" role="status">
            <strong>Worker lane status unavailable.</strong>
            <p>{errorMessage(error)}</p>
          </div>
        ) : isLoading ? (
          <div className="lane-empty-state" role="status">
            <strong>Loading worker lane capacity…</strong>
            <p>Waiting for /control/api/status before enabling feed or dispatch controls.</p>
          </div>
        ) : rendered.length === 0 ? (
          <div className="lane-empty-state" role="status">
            <strong>No worker lane capacity returned.</strong>
            <p>The status endpoint did not include CPU or GB10 lane data, so V2 cannot safely feed or dispatch work from this panel.</p>
          </div>
        ) : (
          <div className="lane-grid">
            {rendered.map((lane) => {
            const feedAction = lane.feed_pressure?.next_autopilot_action || 'observe'
            const canFeed = feedAction === 'generate_candidate' || feedAction === 'promote_candidate'
            const canDispatch = Boolean(lane.dispatch_available)
            const projectId = lane.next_candidate?.project_id || ''
            const canLiveDispatchLane = canDispatch && Boolean(projectId) && liveLaneProjectId === projectId
            const active = lane.active_item?.project_name || lane.active_item?.project_id
            const next = lane.next_candidate?.project_name || lane.next_candidate?.project_id
            return (
              <article key={lane.lane_key || lane.machine_target || laneLabel(lane)} className="lane-card">
                <div className="lane-card-top">
                  <div>
                    <p className="eyebrow">{laneLabel(lane)}</p>
                    <h3>{lane.status || 'unknown'}</h3>
                  </div>
                  <div className="lane-queue-count" aria-label={`${laneLabel(lane)} queued count`}>
                    <strong>{lane.queued_count ?? 0}</strong>
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
                <p className={canDispatch ? 'lane-reason lane-reason--ready' : 'lane-reason'}>{laneDisabledReason(lane, canFeed, canDispatch)}</p>
                <div className="lane-actions">
                  <button className="secondary-button" disabled={!canFeed || busyAction !== null} onClick={feedLane}>Feed idle lane</button>
                  <button className="secondary-button" disabled={!canDispatch || busyAction !== null} onClick={() => { void dispatchLane(lane) }}>Check dispatch</button>
                  <button className="primary-button" disabled={!canLiveDispatchLane || busyAction !== null} onClick={() => { void liveDispatchLane(lane) }}>Dispatch lane</button>
                </div>
              </article>
            )
            })}
          </div>
        )}
      </section>
      {dialog}
    </>
  )
}
