import type { ReactNode } from 'react'
export function Eyebrow({ children }: Readonly<{ children: ReactNode }>) {
  return <p className="eyebrow">{children}</p>
}
