import type { ComposedEmptyStateCopy, ResourceErrorCopy } from '../resourceStatePresentation'

function errorMessage(error: unknown): string {
  return String(error instanceof Error ? error.message : error)
}

function emptyEyebrow(kind: ComposedEmptyStateCopy['kind']): string {
  if (kind === 'filtered') return 'No matches'
  if (kind === 'blocked') return 'Attention clear'
  return 'System idle'
}

export function PageResourceErrorCard({
  copy,
  error,
  onRetry,
  retryLabel = 'Retry',
}: {
  copy: ResourceErrorCopy
  error: unknown
  onRetry: () => void
  retryLabel?: string
}) {
  return (
    <section className="state-card state-card--error v2-error-card" aria-live="polite">
      <p className="eyebrow">{copy.eyebrow}</p>
      <h2>{copy.title}</h2>
      <p>{copy.summary}</p>
      <p className="v2-error-impact"><strong>Dispatch impact:</strong> {copy.dispatchImpact}</p>
      <ul className="v2-error-steps">
        {copy.nextSteps.map((step) => <li key={step}>{step}</li>)}
      </ul>
      <p className="error-detail">{errorMessage(error)}</p>
      <details className="raw-details v2-error-log">
        <summary>Operator log command</summary>
        <pre className="json-block">{copy.logCommand}</pre>
      </details>
      <div className="action-row">
        <button className="secondary-button" type="button" onClick={onRetry}>{retryLabel}</button>
      </div>
    </section>
  )
}

export function ComposedEmptyState({ state }: { state: ComposedEmptyStateCopy }) {
  return (
    <section className={`composed-empty-state composed-empty-state--${state.kind}`} role="status">
      <p className="eyebrow">{emptyEyebrow(state.kind)}</p>
      <strong>{state.title}</strong>
      <p>{state.body}</p>
      {state.hint ? <p className="composed-empty-state-hint">{state.hint}</p> : null}
    </section>
  )
}
