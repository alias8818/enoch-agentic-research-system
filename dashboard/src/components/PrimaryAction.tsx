import { dashboardV2Href } from '../routes'
import type { TopAction } from '../types'

export function PrimaryAction({ action }: { action?: TopAction }) {
  if (!action) {
    return (
      <section className="primary-action primary-action--idle" aria-label="Primary action">
        <div>
          <p className="eyebrow">Primary action</p>
          <h2>Nothing to click right now</h2>
          <p>The backend action model did not rank an operator action.</p>
        </div>
      </section>
    )
  }
  return (
    <section className="primary-action" aria-label="Primary action">
      <div>
        <p className="eyebrow">Primary action</p>
        <h2>{action.title}</h2>
        <p>{action.summary}</p>
      </div>
      <a className="primary-button primary-action-cta" href={dashboardV2Href(action.action_hash || '#overview')}>
        {action.action_label || 'Open'}
      </a>
    </section>
  )
}
