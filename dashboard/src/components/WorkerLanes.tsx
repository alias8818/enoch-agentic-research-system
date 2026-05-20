import { apiPost } from '../api/client'
import type { WorkerLane } from '../types'

function laneLabel(lane: WorkerLane): string {
  const target = String(lane.machine_target || lane.lane_key || '').toLowerCase()
  const role = String(lane.worker_role || '').toLowerCase()
  if (target.includes('cpu') || role.includes('cpu')) return 'CPU lane'
  if (target.includes('gb10') || role.includes('gpu')) return 'GB10 lane'
  return lane.label || lane.machine_target || 'Worker lane'
}

export function WorkerLanes({ lanes, onRefresh }: { lanes: WorkerLane[]; onRefresh: () => void }) {
  async function feedLane() {
    await apiPost('/control/api/research/run-cycle', {
      enabled: true,
      dry_run: false,
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
    })
    onRefresh()
  }
  async function dispatchLane() {
    if (!window.confirm('Dry-run and dispatch an open lane?')) return
    const dryRun = await apiPost<{ action?: string }>('/control/dispatch-next', { dry_run: true, requested_by: 'dashboard-v2', force_preflight: true })
    if (dryRun.action !== 'dry_run_dispatch') {
      window.alert('Dispatch dry-run did not find an open lane candidate.')
      onRefresh()
      return
    }
    if (!window.confirm('Dry-run passed. Start live dispatch now?')) {
      onRefresh()
      return
    }
    await apiPost('/control/dispatch-next', { dry_run: false, requested_by: 'dashboard-v2', force_preflight: true })
    onRefresh()
  }
  const visible = lanes.filter((lane) => ['CPU lane', 'GB10 lane'].includes(laneLabel(lane)))
  const rendered = visible.length ? visible : lanes
  return (
    <section className="rounded-2xl border border-zinc-800 bg-zinc-950 p-5">
      <h2 className="text-lg font-bold text-white">Worker lanes</h2>
      <p className="mt-1 text-sm text-zinc-400">CPU and GB10 lanes are the center of the operator view.</p>
      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        {rendered.map((lane) => {
          const feedAction = lane.feed_pressure?.next_autopilot_action || 'observe'
          const canFeed = feedAction === 'generate_candidate' || feedAction === 'promote_candidate'
          const canDispatch = Boolean(lane.dispatch_available)
          const active = lane.active_item?.project_name || lane.active_item?.project_id
          const next = lane.next_candidate?.project_name || lane.next_candidate?.project_id
          return (
            <article key={lane.lane_key || lane.machine_target || laneLabel(lane)} className="rounded-2xl border border-zinc-800 bg-black/20 p-5">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-[0.22em] text-zinc-500">{laneLabel(lane)}</p>
                  <h3 className="mt-2 text-2xl font-black text-white">{lane.status || 'unknown'}</h3>
                </div>
                <div className="text-right">
                  <div className="text-2xl font-black tabular-nums text-white">{lane.queued_count ?? 0}</div>
                  <div className="text-xs uppercase tracking-wide text-zinc-500">queued</div>
                </div>
              </div>
              <p className="mt-4 text-sm text-zinc-300">{active ? `Current: ${active}` : next ? `Next: ${next}` : lane.dispatch_blocker || 'No queued candidate for lane'}</p>
              <p className="mt-2 text-sm text-zinc-500">Autopilot next: {feedAction.replaceAll('_', ' ')}</p>
              <div className="mt-5 flex gap-2">
                <button className="rounded-lg border border-zinc-700 px-3 py-2 text-sm font-bold text-white disabled:opacity-40" disabled={!canFeed} onClick={feedLane}>Feed idle lane</button>
                <button className="rounded-lg bg-sky-500 px-3 py-2 text-sm font-bold text-white disabled:opacity-40" disabled={!canDispatch} onClick={dispatchLane}>Dispatch this lane</button>
              </div>
            </article>
          )
        })}
      </div>
    </section>
  )
}
