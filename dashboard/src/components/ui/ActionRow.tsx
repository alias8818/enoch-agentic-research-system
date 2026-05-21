import type { ReactNode } from 'react'
export function ActionRow({ children, ariaLabel }: { children: ReactNode; ariaLabel?: string }) {
  return <div className="action-row" aria-label={ariaLabel}>{children}</div>
}
