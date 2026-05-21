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

export function OverviewFreshness({ generatedAt, laneGeneratedAt, isFetching, onRefresh }: OverviewFreshnessProps) {
  return (
    <section className="flex flex-col gap-3 rounded-2xl border border-zinc-800 bg-zinc-950/70 p-4 md:flex-row md:items-center md:justify-between" aria-label="Dashboard data freshness">
      <div className="text-sm text-zinc-400">
        <strong className="text-white">Data freshness</strong>
        <span className="ml-2">overview={formatStamp(generatedAt)} · lanes={formatStamp(laneGeneratedAt)}</span>
      </div>
      <button className="rounded-lg border border-zinc-700 px-3 py-2 text-sm font-bold text-white hover:border-sky-500 disabled:opacity-40" type="button" onClick={onRefresh} disabled={isFetching}>
        {isFetching ? 'Refreshing…' : 'Refresh now'}
      </button>
    </section>
  )
}
