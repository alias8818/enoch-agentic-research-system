type OverviewFreshnessProps = {
  generatedAt?: string
  laneGeneratedAt?: string
  isFetching?: boolean
  onRefresh: () => void
}

function formatStamp(value?: string): string {
  if (!value) return 'unknown'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

export function OverviewFreshness({ generatedAt, laneGeneratedAt, isFetching, onRefresh }: Readonly<OverviewFreshnessProps>) {
  return (
    <section className="freshness-bar" aria-label="Dashboard data freshness">
      <div>
        <strong>Data freshness</strong>
        <span>overview {formatStamp(generatedAt)} · lanes {formatStamp(laneGeneratedAt)}</span>
      </div>
      <button className="secondary-button" type="button" onClick={onRefresh} disabled={isFetching}>
        {isFetching ? 'Refreshing…' : 'Refresh now'}
      </button>
    </section>
  )
}
