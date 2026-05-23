import type { ReactNode } from 'react'
export function ActionRow({ children, ariaLabel }: Readonly<{ children: ReactNode; ariaLabel?: string }>) {
  return <div className="action-row" aria-label={ariaLabel}>{children}</div>
}
