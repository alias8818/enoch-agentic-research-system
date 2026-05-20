import type { MovementDiagnosis, OverviewResponse } from '../types'

function tone(status: string | undefined): string {
  if (status === 'ready') return 'border-emerald-500/50 bg-emerald-950/30 text-emerald-100'
  if (status === 'actionable') return 'border-sky-500/50 bg-sky-950/30 text-sky-100'
  return 'border-amber-500/50 bg-amber-950/30 text-amber-100'
}

export function CommandHero({ overview, diagnosis }: { overview: OverviewResponse; diagnosis: MovementDiagnosis }) {
  const status = diagnosis.status || 'unknown'
  const answer = status === 'ready' ? 'Yes' : status === 'actionable' ? 'Yes, but there is work you can start' : 'No'
  const active = overview.counts?.active ?? 0
  const queued = overview.counts?.queued ?? 0
  const drafts = Number(overview.paper_counts?.publication_draft ?? 0) + Number(overview.paper_counts?.draft_review ?? 0)

  return (
    <section className={`rounded-3xl border p-6 shadow-2xl shadow-black/20 ${tone(status)}`} aria-label="Can I leave this running?">
      <div className="flex flex-col gap-6 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.28em] text-white/60">Can I leave this running?</p>
          <h1 className="mt-3 text-4xl font-black tracking-tight text-white md:text-5xl">{answer}</h1>
          <p className="mt-3 max-w-3xl text-sm text-white/75">{diagnosis.primary_reason || 'No deterministic movement diagnosis returned.'}</p>
        </div>
        <div className="grid grid-cols-3 gap-3 text-center">
          {[['Active', active], ['Queued', queued], ['Drafts', drafts]].map(([label, value]) => (
            <div key={label} className="rounded-2xl bg-black/20 px-5 py-4 ring-1 ring-white/10">
              <div className="text-2xl font-black tabular-nums text-white">{value}</div>
              <div className="mt-1 text-[0.7rem] uppercase tracking-[0.18em] text-white/50">{label}</div>
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}
