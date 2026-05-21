import type { ReactNode } from 'react'
type StateCardVariant = 'default' | 'error'
function variantClass(variant: StateCardVariant, compact?: boolean): string {
  const classes = ['state-card']
  if (variant === 'error') classes.push('state-card--error')
  if (compact) classes.push('state-card--compact')
  return classes.join(' ')
}
export function StateCard({ children, variant = 'default', compact, ariaLive }: { children: ReactNode; variant?: StateCardVariant; compact?: boolean; ariaLive?: 'polite' | 'assertive' | 'off' }) {
  return <div className={variantClass(variant, compact)} aria-live={ariaLive}>{children}</div>
}
export function LoadingStateCard({ label }: { label: string }) { return <StateCard>Loading {label}…</StateCard> }
export function InlineErrorStateCard({ prefix, message }: { prefix: string; message: string }) {
  return <StateCard variant="error">{prefix}: {message}</StateCard>
}
