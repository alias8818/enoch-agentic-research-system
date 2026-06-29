import type { ReactNode } from 'react'
export function RawDetails({ summary, children, className }: Readonly<{ summary: string; children: ReactNode; className?: string }>) {
  const classes = ['raw-details', className].filter(Boolean).join(' ')
  return <details className={classes}><summary>{summary}</summary>{children}</details>
}
export function RawJsonDetails({ summary, payload, className }: Readonly<{ summary: string; payload: unknown; className?: string }>) {
  const operatorSummary = summary.toLowerCase().startsWith('raw ') ? summary.replace(/^Raw\b/, 'Diagnostic') : summary
  return <RawDetails summary={operatorSummary} className={className}><pre className="json-block">{JSON.stringify(payload, null, 2)}</pre></RawDetails>
}
