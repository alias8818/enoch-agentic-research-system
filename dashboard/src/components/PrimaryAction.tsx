import { useState } from 'react'
import { apiPost } from '../api/client'
import { dashboardV2Href } from '../routes'
import type { TopAction } from '../types'
import { useOperatorDialog } from './OperatorDialog'
import { CommandResultSummary } from './CommandResultSummary'

type CommandResult = {
  title: string
  payload: Record<string, unknown>
}

function ResultCard({ result }: { result: CommandResult | null }) {
  return <CommandResultSummary result={result} />
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

function actionSignature(action: TopAction): string {
  return [
    action.kind,
    action.title,
    action.summary || '',
    action.action_label || '',
    action.action_hash || '',
  ].join('|')
}

function liveActionDisabledReason(action: TopAction, ready: boolean, staleReady: boolean, isPending: boolean): string {
  if (isPending) return `${action.action_label || 'Action'} disabled: command is running.`
  if (ready) return ''
  if (staleReady) {
    if (action.kind === 'dispatch_next') return 'Dispatch work disabled: top action changed; run Check dispatch again.'
    if (action.kind === 'investigate_followup') return 'Launch follow-up disabled: top action changed; run Check follow-up again.'
    if (action.kind === 'write_paper') return 'Draft paper disabled: top action changed; run Check draft again.'
    if (action.kind === 'finalize_paper') return 'Finalize drafts disabled: top action changed; run Check finalization again.'
  }
  if (action.kind === 'dispatch_next') return 'Dispatch work disabled: run Check dispatch first.'
  if (action.kind === 'investigate_followup') return 'Launch follow-up disabled: run Check follow-up first.'
  if (action.kind === 'write_paper') return 'Draft paper disabled: run Check draft first.'
  if (action.kind === 'finalize_paper') return 'Finalize drafts disabled: run Check finalization first.'
  return ''
}

export function PrimaryAction({ action, onRefresh }: { action?: TopAction; onRefresh?: () => void }) {
  const [result, setResult] = useState<CommandResult | null>(null)
  const [isPending, setIsPending] = useState(false)
  const [dispatchReady, setDispatchReady] = useState(false)
  const [followupReady, setFollowupReady] = useState(false)
  const [draftReady, setDraftReady] = useState(false)
  const [finalizeReady, setFinalizeReady] = useState(false)
  const [readySignature, setReadySignature] = useState('')
  const { confirm, dialog } = useOperatorDialog()
  const currentActionSignature = action ? actionSignature(action) : ''

  function clearReadiness() {
    setDispatchReady(false)
    setFollowupReady(false)
    setDraftReady(false)
    setFinalizeReady(false)
    setReadySignature('')
  }

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
      const ready = action.kind === 'dispatch_next'
        ? String(payload.action || '').includes('dry_run')
        : action.kind === 'investigate_followup'
          ? payload.action === 'dry_run_followup'
          : action.kind === 'write_paper'
            ? payload.action === 'dry_run_draft'
            : action.kind === 'finalize_paper'
              ? payload.dry_run === true && Number(payload.processed || 0) > 0
              : false
      setDispatchReady(action.kind === 'dispatch_next' && ready)
      setFollowupReady(action.kind === 'investigate_followup' && ready)
      setDraftReady(action.kind === 'write_paper' && ready)
      setFinalizeReady(action.kind === 'finalize_paper' && ready)
      setReadySignature(ready ? currentActionSignature : '')
      onRefresh?.()
    } catch (error) {
      setResult({ title: 'Primary action dry-run failed', payload: { ok: false, reason: error instanceof Error ? error.message : String(error) } })
      clearReadiness()
    } finally {
      setIsPending(false)
    }
  }

  async function runLiveDispatch() {
    if (!action || action.kind !== 'dispatch_next' || !dispatchReady || readySignature !== currentActionSignature) return
    const confirmed = await confirm({
      title: 'Dispatch top action?',
      message: 'This starts live dispatch for the current backend-selected queued work. Use Check dispatch again if lane or queue state may have changed.',
      confirmLabel: 'Dispatch work',
      tone: 'warn',
    })
    if (!confirmed) return
    setIsPending(true)
    try {
      const payload = await apiPost<Record<string, unknown>>('/control/dispatch-next', { dry_run: false, requested_by: 'dashboard-v2', force_preflight: true })
      setResult({ title: 'Primary action live dispatch', payload })
      clearReadiness()
      onRefresh?.()
    } catch (error) {
      setResult({ title: 'Primary action live dispatch failed', payload: { ok: false, reason: error instanceof Error ? error.message : String(error) } })
    } finally {
      setIsPending(false)
    }
  }

  async function runLiveFollowup() {
    if (!action || action.kind !== 'investigate_followup' || !followupReady || readySignature !== currentActionSignature) return
    const confirmed = await confirm({
      title: 'Launch follow-up investigation?',
      message: 'This queues investigation work for the backend-selected follow-up. It does not dispatch work, write papers, or finalize publications. Use Check follow-up again if candidate state may have changed.',
      confirmLabel: 'Launch follow-up',
      tone: 'warn',
    })
    if (!confirmed) return
    setIsPending(true)
    try {
      const payload = await apiPost<Record<string, unknown>>('/control/api/v1/followups/launch-next', { dry_run: false, requested_by: 'dashboard-v2', max_followup_depth: 4 })
      setResult({ title: 'Primary action live follow-up', payload })
      clearReadiness()
      onRefresh?.()
    } catch (error) {
      setResult({ title: 'Primary action live follow-up failed', payload: { ok: false, reason: error instanceof Error ? error.message : String(error) } })
    } finally {
      setIsPending(false)
    }
  }

  async function runLiveDraft() {
    if (!action || action.kind !== 'write_paper' || !draftReady || readySignature !== currentActionSignature) return
    const confirmed = await confirm({
      title: 'Draft next paper?',
      message: 'This writes draft artifacts for the backend-selected paper-ready candidate. Use Check draft again if the candidate may have changed.',
      confirmLabel: 'Draft paper',
      tone: 'warn',
    })
    if (!confirmed) return
    setIsPending(true)
    try {
      const payload = await apiPost<Record<string, unknown>>('/control/papers/draft-next', { dry_run: false, requested_by: 'dashboard-v2', force: true })
      setResult({ title: 'Primary action live draft', payload })
      clearReadiness()
      onRefresh?.()
    } catch (error) {
      setResult({ title: 'Primary action live draft failed', payload: { ok: false, reason: error instanceof Error ? error.message : String(error) } })
    } finally {
      setIsPending(false)
    }
  }

  async function runLiveFinalization() {
    if (!action || action.kind !== 'finalize_paper' || !finalizeReady || readySignature !== currentActionSignature) return
    const confirmed = await confirm({
      title: 'Finalize publication drafts?',
      message: 'This rewrites publication draft packages for the backend-selected batch. Use Check finalization again if the queue may have changed.',
      confirmLabel: 'Finalize drafts',
      tone: 'warn',
    })
    if (!confirmed) return
    setIsPending(true)
    try {
      const payload = await apiPost<Record<string, unknown>>('/control/api/paper-reviews/rewrite-batch', {
        idempotency_key: idempotencyKey('primary-action-rewrite-batch-live'),
        requested_by: 'dashboard-v2',
        paper_status: 'publication_draft',
        dry_run: false,
        force: true,
        limit: 10,
        skip_rewritten: true,
      })
      setResult({ title: 'Primary action live finalization', payload })
      clearReadiness()
      onRefresh?.()
    } catch (error) {
      setResult({ title: 'Primary action live finalization failed', payload: { ok: false, reason: error instanceof Error ? error.message : String(error) } })
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
  const liveReady = action.kind === 'dispatch_next'
    ? dispatchReady && readySignature === currentActionSignature
    : action.kind === 'investigate_followup'
      ? followupReady && readySignature === currentActionSignature
      : action.kind === 'write_paper'
        ? draftReady && readySignature === currentActionSignature
        : action.kind === 'finalize_paper'
          ? finalizeReady && readySignature === currentActionSignature
          : true
  const staleReady = Boolean(readySignature) && readySignature !== currentActionSignature
  const liveDisabledReason = isDryRunCommand(action) ? liveActionDisabledReason(action, liveReady, staleReady, isPending) : ''
  return (
    <section className="primary-action" aria-label="Primary action">
      <div>
        <p className="eyebrow">Primary action</p>
        <h2>{action.title}</h2>
        <p>{action.summary}</p>
      </div>
      {isDryRunCommand(action) ? (
        <div className="primary-action-buttons">
          <button className="secondary-button primary-action-cta" type="button" disabled={isPending} onClick={runDryRun}>{dryRunLabel(action)}</button>
          {action.kind === 'dispatch_next' ? (
            <button className="primary-button primary-action-cta" type="button" disabled={isPending || !liveReady} onClick={runLiveDispatch}>Dispatch work</button>
          ) : null}
          {action.kind === 'investigate_followup' ? (
            <button className="primary-button primary-action-cta" type="button" disabled={isPending || !liveReady} onClick={runLiveFollowup}>Launch follow-up</button>
          ) : null}
          {action.kind === 'write_paper' ? (
            <button className="primary-button primary-action-cta" type="button" disabled={isPending || !liveReady} onClick={runLiveDraft}>Draft paper</button>
          ) : null}
          {action.kind === 'finalize_paper' ? (
            <button className="primary-button primary-action-cta" type="button" disabled={isPending || !liveReady} onClick={runLiveFinalization}>Finalize drafts</button>
          ) : null}
          {liveDisabledReason ? <p className="primary-action-disabled-reason">{liveDisabledReason}</p> : null}
        </div>
      ) : (
        <a className="primary-button primary-action-cta" href={dashboardV2Href(action.action_hash || '#overview')}>
          {action.action_label || 'Open'}
        </a>
      )}
      <ResultCard result={result} />
      {dialog}
    </section>
  )
}
