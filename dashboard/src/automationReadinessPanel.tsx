import type { ReactNode } from 'react'
import { formatReadinessErrorMessage } from './readinessErrors'
import type { AutomationReadiness } from './types'

function readinessPillClass(ok: boolean | undefined): string {
  if (ok) return 'readiness-pill readiness-pill--good'
  return 'readiness-pill readiness-pill--warn'
}

function automationReadinessSummaryLabel(readiness: AutomationReadiness | undefined, isLoading: boolean): string {
  if (readiness?.label) return readiness.label
  if (isLoading) return 'Checking automation readiness…'
  return 'Automation readiness unavailable'
}

function queuePauseLabel(paused: boolean | undefined): string {
  if (paused) return 'paused'
  return 'unpaused'
}

function maintenanceModeLabel(enabled: boolean | undefined): string {
  if (enabled) return 'on'
  return 'off'
}

function readinessCheckStatusLabel(ok: boolean | undefined): string {
  if (ok) return 'ok'
  return 'blocked'
}

function visibleReadinessChecks(checks: NonNullable<AutomationReadiness['checks']>) {
  return [...checks].sort((left, right) => {
    if (left.ok === right.ok) return 0
    return left.ok ? 1 : -1
  }).slice(0, 8)
}

function ReadinessFacts({ summary }: Readonly<{ summary: NonNullable<AutomationReadiness['summary']> }>) {
  return (
    <div className="readiness-facts">
      <span>queued {String(summary.queued ?? 0)}</span>
      <span>active {String(summary.active ?? 0)}</span>
      <span>queue {queuePauseLabel(summary.queue_paused)}</span>
      <span>maintenance {maintenanceModeLabel(summary.maintenance_mode)}</span>
    </div>
  )
}

function ReadinessBlockersBody({ blockers, showAllPassed }: Readonly<{ blockers: string[]; showAllPassed: boolean }>) {
  if (blockers.length > 0) {
    return (
      <ul>
        {blockers.slice(0, 6).map((blocker) => <li key={blocker}>{blocker}</li>)}
      </ul>
    )
  }
  if (showAllPassed) {
    return <p>All reported long-haul readiness checks passed.</p>
  }
  return null
}

function ReadinessChecksList({ checks }: Readonly<{ checks: NonNullable<AutomationReadiness['checks']> }>) {
  if (checks.length === 0) return null
  return (
    <div className="readiness-checks" aria-label="Automation readiness checks">
      {visibleReadinessChecks(checks).map((check) => (
        <span key={String(check.name)} className={readinessPillClass(check.ok)}>
          {String(check.name || 'check')}: {readinessCheckStatusLabel(check.ok)}
        </span>
      ))}
    </div>
  )
}

function automationReadinessErrorMessage(error: unknown): ReactNode {
  if (!error) return null
  return <p>Automation readiness unavailable: {formatReadinessErrorMessage(error)}</p>
}

export function AutomationReadinessSummary({ readiness, isLoading, error }: Readonly<{ readiness?: AutomationReadiness; isLoading: boolean; error: unknown }>) {
  const blockers = readiness?.blockers ?? []
  const checks = readiness?.checks ?? []
  const summary = readiness?.summary ?? {}
  const label = automationReadinessSummaryLabel(readiness, isLoading)
  const showAllPassed = Boolean(readiness && !error && !isLoading && blockers.length === 0)
  const errorMessage = automationReadinessErrorMessage(error)
  let blockersBody: ReactNode = <ReadinessBlockersBody blockers={blockers} showAllPassed={showAllPassed} />
  if (error) blockersBody = null

  return (
    <section className="readiness-snapshot" aria-label="Automation readiness">
      <div>
        <h3>Automation readiness</h3>
        <span className={readinessPillClass(readiness?.ok)}>{label}</span>
      </div>
      {errorMessage}
      {blockersBody}
      <ReadinessFacts summary={summary} />
      <ReadinessChecksList checks={checks} />
    </section>
  )
}
