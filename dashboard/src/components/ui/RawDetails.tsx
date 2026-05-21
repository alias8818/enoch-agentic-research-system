import type { ReactNode } from 'react'
export function RawDetails({ summary, children, className }: { summary: string; children: ReactNode; className?: string }) {
  const classes = ['raw-details', className].filter(Boolean).join(' ')
  return <details className={classes}><summary>{summary}</summary>{children}</details>
}
export function RawJsonDetails({ summary, payload, className }: { summary: string; payload: unknown; className?: string }) {
  return <RawDetails summary={summary} className={className}><pre className="json-block">{JSON.stringify(payload, null, 2)}</pre></RawDetails>
}
