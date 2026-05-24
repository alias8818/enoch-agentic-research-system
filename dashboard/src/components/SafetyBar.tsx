import { apiPost } from '../api/client'
import type { OverviewResponse } from '../types'
import { useOperatorDialog } from './OperatorDialog'

export function SafetyBar({ flags, onRefresh }: Readonly<{ flags: OverviewResponse['flags']; onRefresh: () => void }>) {
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
    await apiPost('/control/pause', {
      reason: 'dashboard operator pause',
      paused_by: 'dashboard-v2',
      maintenance_mode: true,
    })
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
      <section className="safety-bar" aria-label="Queue safety">
        <div>
          <strong>Queue safety</strong>
          <span>{paused ? 'paused' : 'unpaused'} · maintenance {maintenance ? 'on' : 'off'}</span>
        </div>
        <div>
          <button className="danger-button" type="button" disabled={paused} onClick={pause}>Pause queue</button>
          <button className="secondary-button" type="button" disabled={!paused && !maintenance} onClick={resume}>Resume queue</button>
        </div>
      </section>
      {dialog}
    </>
  )
}
