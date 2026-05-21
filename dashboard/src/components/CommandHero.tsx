import type { MovementDiagnosis, OverviewResponse } from '../types'

function tone(status: string | undefined): string {
  if (status === 'ready') return 'command-hero command-hero--ready'
  if (status === 'actionable') return 'command-hero command-hero--actionable'
  return 'command-hero command-hero--blocked'
}

function answerFor(status: string | undefined): string {
  if (status === 'ready') return 'Yes — leave it running'
  if (status === 'actionable') return 'Yes, but there is work you can start'
  return 'Not yet'
}

export function CommandHero({ overview, diagnosis }: { overview: OverviewResponse; diagnosis: MovementDiagnosis }) {
  const status = diagnosis.status || 'unknown'
  const active = overview.counts?.active ?? 0
  const queued = overview.counts?.queued ?? 0
  const drafts = Number(overview.paper_counts?.publication_draft ?? 0) + Number(overview.paper_counts?.draft_review ?? 0)
  const chips = [
    ['active', active],
    ['queued', queued],
    ['drafts', drafts],
  ] as const

  return (
    <section className={tone(status)} aria-label="Can I leave this running?">
      <div>
        <p className="eyebrow">Can I leave this running?</p>
        <h1>{answerFor(status)}</h1>
        <p className="hero-reason">{diagnosis.primary_reason || 'No deterministic movement diagnosis returned.'}</p>
      </div>
      <dl className="hero-state-strip" aria-label="Current command state">
        {chips.map(([label, value]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
    </section>
  )
}
