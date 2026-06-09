import type { ReactNode } from 'react'
type StateCardVariant = 'default' | 'error'
function variantClass(variant: StateCardVariant, compact?: boolean): string {
  const classes = ['state-card']
  if (variant === 'error') classes.push('state-card--error')
  if (compact) classes.push('state-card--compact')
  return classes.join(' ')
}
export function StateCard({ children, variant = 'default', compact, ariaLive }: Readonly<{ children: ReactNode; variant?: StateCardVariant; compact?: boolean; ariaLive?: 'polite' | 'assertive' | 'off' }>) {
  return <div className={variantClass(variant, compact)} aria-live={ariaLive}>{children}</div>
}
export function LoadingStateCard({ label }: Readonly<{ label: string }>) {
  return (
    <StateCard ariaLive="polite">
      <p className="eyebrow">Loading read model</p>
      <h2>Loading {label}…</h2>
      <p>Waiting for the bounded dashboard read model before making an operator decision from this page.</p>
      <p className="state-card__hint">If this does not resolve, refresh once and then inspect the page data-source diagnostics.</p>
    </StateCard>
  )
}
export function InlineErrorStateCard({ prefix, message }: Readonly<{ prefix: string; message: string }>) {
  return <StateCard variant="error">{prefix}: {message}</StateCard>
}
