type CommandResultLike = {
  title: string
  payload: Record<string, unknown>
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
}

function firstValue(...values: unknown[]): unknown {
  return values.find((value) => value !== null && value !== undefined && value !== '')
}

function text(value: unknown, fallback = '—'): string {
  if (value === null || value === undefined || value === '') return fallback
  if (typeof value === 'boolean') return value ? 'yes' : 'no'
  return String(value)
}

function commandReason(payload: Record<string, unknown>): string {
  return text(firstValue(payload.reason, payload.detail, payload.message, payload.action), 'Command completed.')
}

function selectedWork(payload: Record<string, unknown>): string {
  const candidate = record(firstValue(payload.candidate, payload.project, payload.paper, payload.item, payload.selected))
  return text(firstValue(
    payload.project_id,
    payload.paper_id,
    payload.run_id,
    payload.candidate_id,
    payload.idea_id,
    candidate.project_id,
    candidate.paper_id,
    candidate.run_id,
    candidate.candidate_id,
    candidate.idea_id,
    candidate.title,
    candidate.project_name,
    payload.action,
  ))
}

function laneTarget(payload: Record<string, unknown>): string {
  const candidate = record(firstValue(payload.candidate, payload.project, payload.selected))
  const laneResult = Array.isArray(payload.results) ? record(record(payload.results[0]).result) : {}
  return text(firstValue(
    payload.lane,
    payload.machine_target,
    payload.target,
    payload.worker_role,
    candidate.lane,
    candidate.machine_target,
    laneResult.lane,
    laneResult.machine_target,
  ))
}

function commandOutcome(payload: Record<string, unknown>): string {
  const action = text(payload.action, '')
  if (payload.ok === false) return 'Blocked or failed'
  if (action.toLowerCase().includes('blocked')) return 'Blocked'
  if (action.toLowerCase().includes('dry_run') || payload.dry_run === true) return 'Dry-run only'
  if (action) return action.replaceAll('_', ' ')
  return 'Completed'
}

function nextSafeAction(payload: Record<string, unknown>): string {
  const action = text(payload.action, '').toLowerCase()
  const reason = commandReason(payload).toLowerCase()
  if (payload.ok === false || action.includes('blocked') || reason.includes('blocked') || reason.includes('failed')) {
    return 'Do not run the live action yet. Fix the blocker or refresh current state first.'
  }
  if (action.includes('dry_run') || payload.dry_run === true) {
    return 'Review this summary, then run the live action only if the selected work and lane still match.'
  }
  return 'Refresh the dashboard and verify the queue, run, or paper state moved as expected.'
}

function SummaryField({ label, value }: { label: string; value: string }) {
  return (
    <div className="command-result-field">
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  )
}

export function CommandResultSummary({ result, className = '' }: { result: CommandResultLike | null | undefined; className?: string }) {
  if (!result) return null
  const payload = result.payload || {}
  const reason = commandReason(payload)
  return (
    <section className={`result-card command-result-summary ${className}`.trim()} aria-live="polite">
      <div className="command-result-head">
        <div>
          <p className="eyebrow">Command result</p>
          <h3>{result.title}</h3>
        </div>
        <span className="status-chip">{commandOutcome(payload)}</span>
      </div>
      <p className="command-result-reason">{reason}</p>
      <dl className="command-result-grid">
        <SummaryField label="Selected work" value={selectedWork(payload)} />
        <SummaryField label="Lane / target" value={laneTarget(payload)} />
        <SummaryField label="Backend action" value={text(payload.action, '—')} />
        <SummaryField label="Next safe action" value={nextSafeAction(payload)} />
      </dl>
      <details className="raw-details command-result-raw">
        <summary>Raw JSON</summary>
        <pre className="json-block">{JSON.stringify(payload, null, 2)}</pre>
      </details>
    </section>
  )
}
