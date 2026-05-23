function formatCountLabel(key: string): string {
  return key.replaceAll('_', ' ')
}

export function WorkbenchOperatorSummary({ summary }: Readonly<{ summary?: string | null }>) {
  const text = String(summary || '').trim()
  if (!text) return null
  return (
    <p className="workbench-operator-summary" aria-live="polite">
      {text}
    </p>
  )
}

export function WorkbenchCountsFold({
  counts,
  label = 'Ledger counts',
}: {
  counts?: Record<string, unknown> | null
  label?: string
}) {
  const entries = Object.entries(counts || {})
    .filter(([, value]) => Number(value || 0) > 0)
    .sort(([left], [right]) => left.localeCompare(right))
  if (!entries.length) return null
  return (
    <details className="workbench-counts-fold raw-details">
      <summary>{label}</summary>
      <dl className="workbench-counts-list">
        {entries.map(([key, value]) => (
          <div key={key} className="workbench-counts-item">
            <dt>{formatCountLabel(key)}</dt>
            <dd>{String(value)}</dd>
          </div>
        ))}
      </dl>
    </details>
  )
}
