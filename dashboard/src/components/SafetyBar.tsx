import { apiPost } from '../api/client'
import type { OverviewResponse } from '../types'

export function SafetyBar({ flags, onRefresh }: { flags: OverviewResponse['flags']; onRefresh: () => void }) {
  const paused = Boolean(flags?.queue_paused)
  const maintenance = Boolean(flags?.maintenance_mode)
  async function pause() {
    if (!window.confirm('Pause the queue?')) return
    await apiPost('/control/pause', { paused_by: 'dashboard-v2' })
    onRefresh()
  }
  async function resume() {
    if (!window.confirm('Resume the queue?')) return
    await apiPost('/control/resume', { resumed_by: 'dashboard-v2', maintenance_mode: false })
    onRefresh()
  }
  return (
    <section className="flex flex-col gap-3 rounded-2xl border border-zinc-800 bg-zinc-950/70 p-4 md:flex-row md:items-center md:justify-between">
      <div>
        <strong className="text-sm text-white">Queue safety</strong>
        <span className="ml-2 text-sm text-zinc-400">paused={String(paused)} · maintenance={maintenance ? 'on' : 'off'}</span>
      </div>
      <div className="flex gap-2">
        <button className="rounded-lg bg-red-600 px-3 py-2 text-sm font-bold text-white disabled:opacity-40" disabled={paused} onClick={pause}>Pause queue</button>
        <button className="rounded-lg border border-zinc-700 px-3 py-2 text-sm font-bold text-white disabled:opacity-40" disabled={!paused && !maintenance} onClick={resume}>Resume queue</button>
      </div>
    </section>
  )
}
