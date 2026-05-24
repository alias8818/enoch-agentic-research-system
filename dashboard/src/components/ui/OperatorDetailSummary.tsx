import { Eyebrow } from './Eyebrow'
export function OperatorDetailSummary({ state, context, next, ariaLabel = 'Operator detail summary' }: Readonly<{ state: string; context: string; next: string; ariaLabel?: string }>) {
  return (
    <section className="detail-operator-summary" aria-label={ariaLabel}>
      <div><Eyebrow>Current state</Eyebrow><strong>{state}</strong><span>{context}</span></div>
      <div><Eyebrow>Next safe action</Eyebrow><span>{next}</span></div>
    </section>
  )
}
