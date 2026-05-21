import { useState } from 'react'
import { apiPost } from '../api/client'
import type { WorkerLane } from '../types'

type CommandResult = {
  title: string
  payload: Record<string, unknown>
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

export function WorkerLanes({ lanes, onRefresh }: { lanes: WorkerLane[]; onRefresh: () => void }) {
  const [commandResult, setCommandResult] = useState<CommandResult | null>(null)
  const [busyAction, setBusyAction] = useState<'feed' | 'dispatch' | null>(null)

  async function feedLane() {
    setBusyAction('feed')
    try {
      const result = await apiPost<Record<string, unknown>>('/control/api/research/run-cycle', dryRunCyclePayload)
      setCommandResult({ title: 'Feed dry-run result', payload: result })
      onRefresh()
    } catch (error) {
      setCommandResult({ title: 'Feed dry-run failed', payload: { ok: false, reason: error instanceof Error ? error.message : String(error) } })
    } finally {
      setBusyAction(null)
    }
  }

  async function dispatchLane() {
    setBusyAction('dispatch')
    try {
      const result = await apiPost<Record<string, unknown>>('/control/dispatch-next', { dry_run: true, requested_by: 'dashboard-v2', force_preflight: true })
      setCommandResult({ title: 'Dispatch dry-run result', payload: result })
      onRefresh()
    } catch (error) {
      setCommandResult({ title: 'Dispatch dry-run failed', payload: { ok: false, reason: error instanceof Error ? error.message : String(error) } })
    } finally {
      setBusyAction(null)
    }
  }

  const visible = lanes.filter((lane) => ['CPU lane', 'GB10 lane'].includes(laneLabel(lane)))
  const rendered = visible.length ? visible : lanes
  const canFeedAny = rendered.some((lane) => ['generate_candidate', 'promote_candidate'].includes(lane.feed_pressure?.next_autopilot_action || ''))
  const canDispatchAny = rendered.some((lane) => lane.dispatch_available)
  return (
    <section className="lane-console" aria-label="Worker lanes">
      <div className="lane-console-head">
        <div>
          <p className="eyebrow">Worker lanes</p>
          <h2>CPU / GB10 command surface</h2>
          <p>Lane state is the source of truth. Aggregate queue counts do not decide dispatch.</p>
        </div>
        <div className="lane-console-actions">
          <button className="secondary-button" disabled={!canFeedAny || busyAction !== null} onClick={feedLane}>Feed idle lanes</button>
          <button className="primary-button" disabled={!canDispatchAny || busyAction !== null} onClick={dispatchLane}>Check open lanes</button>
        </div>
      </div>
      <ResultCard result={commandResult} />
      <div className="lane-grid">
        {rendered.map((lane) => {
          const feedAction = lane.feed_pressure?.next_autopilot_action || 'observe'
          const canFeed = feedAction === 'generate_candidate' || feedAction === 'promote_candidate'
          const canDispatch = Boolean(lane.dispatch_available)
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
                <button className="primary-button" disabled={!canDispatch || busyAction !== null} onClick={dispatchLane}>Check dispatch</button>
              </div>
            </article>
          )
        })}
      </div>
    </section>
  )
}
