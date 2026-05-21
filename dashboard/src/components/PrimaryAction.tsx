import { useState } from 'react'
import { apiPost } from '../api/client'
import { dashboardV2Href } from '../routes'
import type { TopAction } from '../types'

type CommandResult = {
  title: string
  payload: Record<string, unknown>
}

function ResultCard({ result }: { result: CommandResult | null }) {
  if (!result) return null
  const reason = String(result.payload.reason || result.payload.detail || result.payload.action || 'Command completed.')
  return (
    <section className="result-card primary-action-result" aria-live="polite">
      <h3>{result.title}</h3>
      <p>{reason}</p>
      <pre>{JSON.stringify(result.payload, null, 2)}</pre>
    </section>
  )
}

function isDryRunCommand(action: TopAction): boolean {
  return action.kind === 'dispatch_next' || action.kind === 'investigate_followup' || action.kind === 'write_paper' || action.kind === 'finalize_paper'
}

function dryRunLabel(action: TopAction): string {
  if (action.kind === 'investigate_followup') return 'Check follow-up'
  if (action.kind === 'write_paper') return 'Check draft'
  if (action.kind === 'finalize_paper') return 'Check finalization'
  return 'Check dispatch'
}

function idempotencyKey(prefix: string): string {
  return `${prefix}:dashboard-v2:${Date.now()}`
}

export function PrimaryAction({ action, onRefresh }: { action?: TopAction; onRefresh?: () => void }) {
  const [result, setResult] = useState<CommandResult | null>(null)
  const [isPending, setIsPending] = useState(false)

  async function runDryRun() {
    if (!action || !isDryRunCommand(action)) return
    setIsPending(true)
    try {
      const payload = action.kind === 'investigate_followup'
        ? await apiPost<Record<string, unknown>>('/control/api/v1/followups/launch-next', { dry_run: true, requested_by: 'dashboard-v2', max_followup_depth: 4 })
        : action.kind === 'write_paper'
          ? await apiPost<Record<string, unknown>>('/control/papers/draft-next', { dry_run: true, requested_by: 'dashboard-v2', force: true })
          : action.kind === 'finalize_paper'
            ? await apiPost<Record<string, unknown>>('/control/api/paper-reviews/rewrite-batch', {
                idempotency_key: idempotencyKey('primary-action-rewrite-batch'),
                requested_by: 'dashboard-v2',
                paper_status: 'publication_draft',
                dry_run: true,
                limit: 10,
                skip_rewritten: true,
              })
            : await apiPost<Record<string, unknown>>('/control/dispatch-next', { dry_run: true, requested_by: 'dashboard-v2', force_preflight: true })
      setResult({ title: 'Primary action dry-run', payload })
      onRefresh?.()
    } catch (error) {
      setResult({ title: 'Primary action dry-run failed', payload: { ok: false, reason: error instanceof Error ? error.message : String(error) } })
    } finally {
      setIsPending(false)
    }
  }

  if (!action) {
    return (
      <section className="primary-action primary-action--idle" aria-label="Primary action">
        <div>
          <p className="eyebrow">Primary action</p>
          <h2>Nothing to click right now</h2>
          <p>The backend action model did not rank an operator action.</p>
        </div>
      </section>
    )
  }
  return (
    <section className="primary-action" aria-label="Primary action">
      <div>
        <p className="eyebrow">Primary action</p>
        <h2>{action.title}</h2>
        <p>{action.summary}</p>
      </div>
      {isDryRunCommand(action) ? (
        <button className="primary-button primary-action-cta" type="button" disabled={isPending} onClick={runDryRun}>{dryRunLabel(action)}</button>
      ) : (
        <a className="primary-button primary-action-cta" href={dashboardV2Href(action.action_hash || '#overview')}>
          {action.action_label || 'Open'}
        </a>
      )}
      <ResultCard result={result} />
    </section>
  )
}
