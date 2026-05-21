import { useState } from 'react'
import { apiPost } from '../api/client'
import { dashboardV2Href } from '../routes'
import { dryRunCyclePayload, liveCyclePayload } from '../researchCyclePayloads'
import type { OverviewResponse, TopAction } from '../types'
import { useOperatorDialog } from './OperatorDialog'
import type { CommandPresentationContext } from '../commandResultPresentation'
import { CommandResultSummary } from './CommandResultSummary'

type CommandResult = {
  payload: Record<string, unknown>
  context?: CommandPresentationContext
}

function commandFamilyForAction(action: TopAction): CommandPresentationContext['commandFamily'] {
  if (action.kind === 'dispatch_next') return 'dispatch'
  if (action.kind === 'investigate_followup') return 'followup'
  if (action.kind === 'write_paper') return 'paper'
  if (action.kind === 'finalize_paper') return 'finalize'
  if (action.kind === 'feed_lanes') return 'research'
  return 'command'
}

function ResultCard({ result, stale }: { result: CommandResult | null; stale?: boolean }) {
  if (!result) return null
  return <CommandResultSummary result={{ payload: result.payload, context: { ...result.context, stale: stale || result.context?.stale } }} />
}

function isDryRunCommand(action: TopAction): boolean {
  return action.kind === 'dispatch_next' || action.kind === 'investigate_followup' || action.kind === 'write_paper' || action.kind === 'finalize_paper' || action.kind === 'feed_lanes'
}

function dryRunLabel(action: TopAction): string {
  if (action.kind === 'investigate_followup') return 'Check follow-up'
  if (action.kind === 'write_paper') return 'Check draft'
  if (action.kind === 'finalize_paper') return 'Check finalization'
  if (action.kind === 'feed_lanes') return 'Feed idle lanes'
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

function feedDryRunAllowsLiveCycle(result: Record<string, unknown>): boolean {
  if (result.dry_run !== true) return false
  const action = String(result.action || '').toLowerCase()
  const reason = String(result.reason || result.detail || '').toLowerCase()
  if (action.includes('blocked') || action.includes('skipped') || reason.includes('blocked')) return false
  return action.includes('dry_run') || action.includes('would') || reason.includes('would ')
}

function liveActionDisabledReason(action: TopAction, ready: boolean, staleReady: boolean, isPending: boolean): string {
  if (isPending) return `${action.action_label || 'Action'} disabled: command is running.`
  if (ready) return ''
  if (staleReady) {
    if (action.kind === 'dispatch_next') return 'Dispatch work disabled: top action changed; run Check dispatch again.'
    if (action.kind === 'investigate_followup') return 'Launch follow-up disabled: top action changed; run Check follow-up again.'
    if (action.kind === 'write_paper') return 'Draft paper disabled: top action changed; run Check draft again.'
    if (action.kind === 'finalize_paper') return 'Finalize drafts disabled: top action changed; run Check finalization again.'
    if (action.kind === 'feed_lanes') return 'Run feed cycle disabled: top action changed; run Feed idle lanes again.'
  }
  if (action.kind === 'dispatch_next') return 'Dispatch work disabled: run Check dispatch first.'
  if (action.kind === 'investigate_followup') return 'Launch follow-up disabled: run Check follow-up first.'
  if (action.kind === 'write_paper') return 'Draft paper disabled: run Check draft first.'
  if (action.kind === 'finalize_paper') return 'Finalize drafts disabled: run Check finalization first.'
  if (action.kind === 'feed_lanes') return 'Run feed cycle disabled: run Feed idle lanes first.'
  return ''
}

export function resolvePrimaryAction(
  overview: OverviewResponse,
  readinessRequested: boolean,
): TopAction | undefined {
  if (!readinessRequested) {
    return {
      kind: 'check_readiness',
      tone: 'warn',
      title: 'Check readiness first',
      summary: 'Run the long-haul readiness check before leaving automation unattended.',
      action_label: 'Check readiness',
    }
  }
  return overview.primary_operator_action || undefined
}

export function PrimaryAction({
  action,
  onRefresh,
  onCheckReadiness,
}: {
  action?: TopAction
  onRefresh?: () => void
  onCheckReadiness?: () => void
}) {
  const [result, setResult] = useState<CommandResult | null>(null)
  const [isPending, setIsPending] = useState(false)
  const [dispatchReady, setDispatchReady] = useState(false)
  const [followupReady, setFollowupReady] = useState(false)
  const [draftReady, setDraftReady] = useState(false)
  const [finalizeReady, setFinalizeReady] = useState(false)
  const [feedReady, setFeedReady] = useState(false)
  const [readySignature, setReadySignature] = useState('')
  const { confirm, dialog } = useOperatorDialog()
  const currentActionSignature = action ? actionSignature(action) : ''

  function clearReadiness() {
    setDispatchReady(false)
    setFollowupReady(false)
    setDraftReady(false)
    setFinalizeReady(false)
    setFeedReady(false)
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
            : action.kind === 'feed_lanes'
              ? await apiPost<Record<string, unknown>>('/control/api/research/run-cycle', dryRunCyclePayload)
              : action.project_id
                ? await apiPost<Record<string, unknown>>('/control/dispatch-one', {
                    project_id: action.project_id,
                    dry_run: true,
                    requested_by: 'dashboard-v2',
                    force_preflight: true,
                  })
                : await apiPost<Record<string, unknown>>('/control/dispatch-next', { dry_run: true, requested_by: 'dashboard-v2', force_preflight: true })
      setResult({ payload, context: { commandFamily: commandFamilyForAction(action) } })
      const ready = action.kind === 'dispatch_next'
        ? String(payload.action || '').includes('dry_run')
        : action.kind === 'investigate_followup'
          ? payload.action === 'dry_run_followup'
          : action.kind === 'write_paper'
            ? payload.action === 'dry_run_draft'
            : action.kind === 'finalize_paper'
              ? payload.dry_run === true && Number(payload.processed || 0) > 0
              : action.kind === 'feed_lanes'
                ? feedDryRunAllowsLiveCycle(payload)
                : false
      setDispatchReady(action.kind === 'dispatch_next' && ready)
      setFollowupReady(action.kind === 'investigate_followup' && ready)
      setDraftReady(action.kind === 'write_paper' && ready)
      setFinalizeReady(action.kind === 'finalize_paper' && ready)
      setFeedReady(action.kind === 'feed_lanes' && ready)
      setReadySignature(ready ? currentActionSignature : '')
      onRefresh?.()
    } catch (error) {
      setResult({ payload: { ok: false, reason: error instanceof Error ? error.message : String(error) }, context: { commandFamily: commandFamilyForAction(action) } })
      clearReadiness()
    } finally {
      setIsPending(false)
    }
  }

  async function runLiveDispatch() {
    if (!action || action.kind !== 'dispatch_next' || !dispatchReady || readySignature !== currentActionSignature) return
    const confirmed = await confirm({
      title: action.project_id ? `Dispatch ${action.lane || 'lane'}?` : 'Dispatch top action?',
      message: action.project_id
        ? `This starts live dispatch for exactly ${action.project_id}. Use Check dispatch again if the lane candidate changed.`
        : 'This starts live dispatch for the current backend-selected queued work. Use Check dispatch again if lane or queue state may have changed.',
      confirmLabel: action.project_id ? 'Dispatch lane' : 'Dispatch work',
      tone: 'warn',
    })
    if (!confirmed) return
    setIsPending(true)
    try {
      const payload = action.project_id
        ? await apiPost<Record<string, unknown>>('/control/dispatch-one', {
            project_id: action.project_id,
            dry_run: false,
            requested_by: 'dashboard-v2',
            force_preflight: true,
          })
        : await apiPost<Record<string, unknown>>('/control/dispatch-next', { dry_run: false, requested_by: 'dashboard-v2', force_preflight: true })
      setResult({ payload, context: { commandFamily: commandFamilyForAction(action) } })
      clearReadiness()
      onRefresh?.()
    } catch (error) {
      setResult({ payload: { ok: false, reason: error instanceof Error ? error.message : String(error) }, context: { commandFamily: commandFamilyForAction(action) } })
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
      setResult({ payload, context: { commandFamily: commandFamilyForAction(action) } })
      clearReadiness()
      onRefresh?.()
    } catch (error) {
      setResult({ payload: { ok: false, reason: error instanceof Error ? error.message : String(error) }, context: { commandFamily: commandFamilyForAction(action) } })
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
      setResult({ payload, context: { commandFamily: commandFamilyForAction(action) } })
      clearReadiness()
      onRefresh?.()
    } catch (error) {
      setResult({ payload: { ok: false, reason: error instanceof Error ? error.message : String(error) }, context: { commandFamily: commandFamilyForAction(action) } })
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
      setResult({ payload, context: { commandFamily: commandFamilyForAction(action) } })
      clearReadiness()
      onRefresh?.()
    } catch (error) {
      setResult({ payload: { ok: false, reason: error instanceof Error ? error.message : String(error) }, context: { commandFamily: commandFamilyForAction(action) } })
    } finally {
      setIsPending(false)
    }
  }

  async function runLiveFeed() {
    if (!action || action.kind !== 'feed_lanes' || !feedReady || readySignature !== currentActionSignature) return
    const confirmed = await confirm({
      title: 'Run one bounded feed cycle?',
      message: 'This can spend one provider request and promote candidates. It will not dispatch, wait for completion, write papers, or finalize publications.',
      confirmLabel: 'Run feed cycle',
      tone: 'warn',
    })
    if (!confirmed) return
    setIsPending(true)
    try {
      const payload = await apiPost<Record<string, unknown>>('/control/api/research/run-cycle', liveCyclePayload)
      setResult({ payload, context: { commandFamily: 'research' } })
      clearReadiness()
      onRefresh?.()
    } catch (error) {
      setResult({ payload: { ok: false, reason: error instanceof Error ? error.message : String(error) }, context: { commandFamily: 'research' } })
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
          <p>No decisive operator action is available right now.</p>
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
          : action.kind === 'feed_lanes'
            ? feedReady && readySignature === currentActionSignature
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
      {action.kind === 'check_readiness' ? (
        <button className="primary-button primary-action-cta" type="button" disabled={isPending} onClick={() => onCheckReadiness?.()}>
          {action.action_label || 'Check readiness'}
        </button>
      ) : isDryRunCommand(action) ? (
        <div className="primary-action-buttons">
          <button className="secondary-button primary-action-cta" type="button" disabled={isPending} onClick={runDryRun}>{dryRunLabel(action)}</button>
          {action.kind === 'dispatch_next' ? (
            <button className="primary-button primary-action-cta" type="button" disabled={isPending || !liveReady} onClick={runLiveDispatch}>{action.project_id ? 'Dispatch lane' : 'Dispatch work'}</button>
          ) : null}
          {action.kind === 'feed_lanes' ? (
            <button className="primary-button primary-action-cta" type="button" disabled={isPending || !liveReady} onClick={runLiveFeed}>Run feed cycle</button>
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
      <ResultCard result={result} stale={staleReady} />
      {dialog}
    </section>
  )
}
