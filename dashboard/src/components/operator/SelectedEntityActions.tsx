import type { ReactNode } from 'react'
import { shortId } from '../../format'

export function SelectedEntityActions({
  title,
  entityId,
  description,
  children,
  ariaLabel = 'Selected entity actions',
}: {
  title: string
  entityId: string
  description?: string
  children: ReactNode
  ariaLabel?: string
}) {
  return (
    <section className="queue-command-card queue-command-card--compact" aria-label={ariaLabel}>
      <div>
        <p className="eyebrow">Selected paper actions</p>
        <h2>{title}</h2>
        <span className="detail-id-chip" title={entityId}>{shortId(entityId)}</span>
        {description ? <p>{description}</p> : null}
      </div>
      <div className="action-row">{children}</div>
    </section>
  )
}
