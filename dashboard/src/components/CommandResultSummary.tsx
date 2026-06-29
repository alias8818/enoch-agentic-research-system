import { deriveCommandPresentation, type CommandPresentationContext } from '../commandResultPresentation'
import { displayText } from '../displayText'

type CommandResultLike = {
  title?: string
  payload: Record<string, unknown>
  context?: CommandPresentationContext
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
  return displayText(value, fallback)
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
    candidate.paper_title,
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

function SummaryField({ label, value }: Readonly<{ label: string; value: string }>) {
  return (
    <div className="command-result-field">
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  )
}

export function CommandResultSummary({ result, className = '' }: Readonly<{ result: CommandResultLike | null | undefined; className?: string }>) {
  if (!result) return null
  const payload = result.payload || {}
  const presentation = deriveCommandPresentation(payload, result.context)
  const title = result.title || presentation.title
  const reason = commandReason(payload)
  return (
    <section className={`result-card command-result-summary ${className}`.trim()} aria-live="polite">
      <div className="command-result-head">
        <div>
          <p className="eyebrow">Command result</p>
          <h3>{title}</h3>
        </div>
        <span className={`status-chip status-chip--${presentation.severity}`}>{presentation.severityLabel}</span>
      </div>
      <p className="command-result-reason">{reason}</p>
      <dl className="command-result-grid">
        <SummaryField label="Selected work" value={selectedWork(payload)} />
        <SummaryField label="Lane / target" value={laneTarget(payload)} />
        <SummaryField label="Operator decision" value={presentation.decision} />
      </dl>
      <details className="raw-details command-result-raw">
        <summary>Diagnostic JSON</summary>
        <pre className="json-block">{JSON.stringify(payload, null, 2)}</pre>
      </details>
    </section>
  )
}
