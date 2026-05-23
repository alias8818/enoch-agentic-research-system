import type { ReactNode } from 'react'
import { displayCount } from './displayText'

function labelOperatorKey(key: string): string {
  return key.replaceAll('_', ' ')
}

function operatorQueueRows(
  operatorCounts: Record<string, unknown>,
  operatorDetailCounts: Record<string, unknown>,
): [string, unknown][] {
  const entries: [string, unknown][] = [
    ['needs_attention', operatorCounts.needs_attention],
    ['running', operatorCounts.running],
    ['write_paper', operatorCounts.write_paper],
    ['ready_to_publish', operatorCounts.ready_to_publish],
    ['finalization_needed', operatorDetailCounts.finalization_needed],
    ['followup_candidate', operatorDetailCounts.followup_candidate],
  ]
  return entries.filter(([, value]) => displayCount(value) !== '0')
}

function OperatorQueueRowList({ rows }: Readonly<{ rows: [string, unknown][] }>) {
  return (
    <dl>
      {rows.slice(0, 6).map(([key, value]) => (
        <div key={String(key)}>
          <dt>{labelOperatorKey(String(key))}</dt>
          <dd>{displayCount(value)}</dd>
        </div>
      ))}
    </dl>
  )
}

export function OperatorQueueSnapshot({ operatorCounts, operatorDetailCounts }: Readonly<{ operatorCounts: Record<string, unknown>; operatorDetailCounts: Record<string, unknown> }>) {
  const rows = operatorQueueRows(operatorCounts, operatorDetailCounts)
  let body: ReactNode = <p>No operator queue counts reported in the bounded overview snapshot.</p>
  if (rows.length > 0) {
    body = <OperatorQueueRowList rows={rows} />
  }

  return (
    <section className="operator-snapshot" aria-label="Operator queue snapshot">
      <h3>Operator queue snapshot</h3>
      {body}
    </section>
  )
}
