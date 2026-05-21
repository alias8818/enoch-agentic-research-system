import type { AutomationReadiness, MovementDiagnosis, OverviewResponse } from '../types'

type HeroReadinessState = {
  readiness?: AutomationReadiness
  readinessRequested?: boolean
  readinessLoading?: boolean
  requiresReadinessCheck?: boolean
}

export type CommandHeroState = {
  className: string
  answer: string
  reason?: string
}

function movementTone(status: string | undefined): string {
  if (status === 'ready') return 'command-hero command-hero--ready'
  if (status === 'actionable') return 'command-hero command-hero--actionable'
  return 'command-hero command-hero--blocked'
}

function hasHealthyActiveWork(diagnosis: MovementDiagnosis): boolean {
  const blockers = diagnosis.blockers ?? []
  return diagnosis.status === 'ready' && blockers.some((blocker) => blocker.kind === 'lane_active')
}

function movementAnswer(status: string | undefined, diagnosis: MovementDiagnosis): string {
  if (status === 'ready') {
    return hasHealthyActiveWork(diagnosis) ? 'Yes — active work is running' : 'Yes — leave it running'
  }
  if (status === 'actionable') return 'Action available'
  return 'Not yet'
}

export function resolveCommandHeroState(
  diagnosis: MovementDiagnosis,
  readinessState: HeroReadinessState,
): CommandHeroState {
  const status = diagnosis.status || 'unknown'
  if (!readinessState.requiresReadinessCheck) {
    return { className: movementTone(status), answer: movementAnswer(status, diagnosis) }
  }
  if (readinessState.readinessLoading) {
    return {
      className: 'command-hero command-hero--actionable',
      answer: 'Checking readiness',
      reason: 'Waiting for the long-haul readiness check before answering unattended operation.',
    }
  }
  if (!readinessState.readiness && !readinessState.readinessRequested) {
    return {
      className: 'command-hero command-hero--actionable',
      answer: 'Check readiness first',
      reason: 'Run the readiness check before leaving automation unattended.',
    }
  }
  if (readinessState.readiness && readinessState.readiness.ok === false) {
    return {
      className: 'command-hero command-hero--blocked',
      answer: 'Not yet',
      reason: readinessState.readiness.blockers?.[0] || readinessState.readiness.label || 'Automation readiness is blocked.',
    }
  }
  return { className: movementTone(status), answer: movementAnswer(status, diagnosis) }
}

export function CommandHero({
  overview,
  diagnosis,
  readiness,
  readinessRequested = false,
  readinessLoading = false,
  requiresReadinessCheck = false,
}: {
  overview: OverviewResponse
  diagnosis: MovementDiagnosis
} & HeroReadinessState) {
  const active = overview.counts?.active ?? 0
  const queued = overview.counts?.queued ?? 0
  const drafts = Number(overview.paper_counts?.publication_draft ?? 0) + Number(overview.paper_counts?.draft_review ?? 0)
  const chips = [
    ['active', active],
    ['queued', queued],
    ['drafts', drafts],
  ] as const
  const state = resolveCommandHeroState(diagnosis, { readiness, readinessRequested, readinessLoading, requiresReadinessCheck })
  const reason = state.reason || diagnosis.primary_reason || 'No deterministic movement diagnosis returned.'

  return (
    <section className={state.className} aria-label="Can I leave this running?">
      <div>
        <p className="eyebrow">Can I leave this running?</p>
        <h1>{state.answer}</h1>
        <p className="hero-reason">{reason}</p>
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
