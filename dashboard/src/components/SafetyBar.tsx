import { apiPost } from '../api/client'
import type { OverviewResponse } from '../types'
import { useOperatorDialog } from './OperatorDialog'

export function SafetyBar({ flags, onRefresh }: { flags: OverviewResponse['flags']; onRefresh: () => void }) {
  const paused = Boolean(flags?.queue_paused)
  const maintenance = Boolean(flags?.maintenance_mode)
  const { confirm, dialog } = useOperatorDialog()
  async function pause() {
    const confirmed = await confirm({
      title: 'Pause the queue?',
      message: 'This stops automatic dispatch while you perform maintenance. Active runs are not killed by this action.',
      confirmLabel: 'Pause queue',
      tone: 'danger',
    })
    if (!confirmed) return
    await apiPost('/control/pause', { paused_by: 'dashboard-v2' })
    onRefresh()
  }
  async function resume() {
    const confirmed = await confirm({
      title: 'Resume the queue?',
      message: 'This clears queue pause and maintenance mode so eligible lanes can move again.',
      confirmLabel: 'Resume queue',
      tone: 'warn',
    })
    if (!confirmed) return
    await apiPost('/control/resume', { resumed_by: 'dashboard-v2', maintenance_mode: false })
    onRefresh()
  }
  return (
    <>
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
      {dialog}
    </>
  )
}
