import { useState } from 'react'
import { apiPost } from '../api/client'
import { dashboardV2Href } from '../routes'
import type { OverviewResponse } from '../types'
import { useOperatorDialog } from './OperatorDialog'
import type { CommandPresentationContext } from '../commandResultPresentation'
import { CommandResultSummary } from './CommandResultSummary'

type CommandResult = {
  payload: Record<string, unknown>
  context?: CommandPresentationContext
}

function idempotencyKey(prefix: string): string {
  return `${prefix}:dashboard-v2:${Date.now()}`
}

function ResultCard({ result, stale }: Readonly<{ result: CommandResult | null; stale?: boolean }>) {
  if (!result) return null
  return <CommandResultSummary result={{ payload: result.payload, context: { ...result.context, stale: stale || result.context?.stale } }} />
}

function finalizationDisabledReason(finalizeNeeded: number, finalizeReady: boolean, canLiveFinalize: boolean, isPending: boolean): string {
  if (isPending) return 'Finalize drafts disabled: paper command is running.'
  if (finalizeReady && !canLiveFinalize) return 'Finalize drafts disabled: paper pipeline changed; run Dry-run finalize again.'
  if (finalizeNeeded <= 0) return 'Finalize drafts disabled: no publication drafts need finalization.'
  if (!canLiveFinalize) return 'Finalize drafts disabled: run Dry-run finalize first.'
  return ''
}

export function PaperMiniStrip({ pipeline, onRefresh }: Readonly<{ pipeline: OverviewResponse['paper_pipeline']; onRefresh?: () => void }>) {
  const [result, setResult] = useState<CommandResult | null>(null)
  const [isPending, setIsPending] = useState(false)
  const [finalizeReady, setFinalizeReady] = useState(false)
  const [finalizeSignature, setFinalizeSignature] = useState('')
  const { confirm, dialog } = useOperatorDialog()
  const writeNeeded = pipeline?.write_needed ?? 0
  const finalizeNeeded = pipeline?.finalize_needed ?? 0
  const publishReady = pipeline?.publish_ready ?? 0
  const archiveCount = pipeline?.paper_gate_archive_count ?? 0
  const writeBlocked = pipeline?.paper_write_blocked ?? 0
  const archiveSummary = pipeline?.paper_gate_archive_summary || `${archiveCount} completed runs are intentionally not paper-writable.`
  const pipelineSignature = [writeNeeded, finalizeNeeded, publishReady].join(':')
  const canLiveFinalize = finalizeReady && finalizeSignature === pipelineSignature
  const finalizeDisabledReason = finalizationDisabledReason(finalizeNeeded, finalizeReady, canLiveFinalize, isPending)

  async function dryRunFinalize() {
    setIsPending(true)
    try {
      const payload = await apiPost<Record<string, unknown>>('/control/api/paper-reviews/rewrite-batch', {
        idempotency_key: idempotencyKey('paper-strip-rewrite-batch'),
        requested_by: 'dashboard-v2',
        paper_status: 'publication_draft',
        dry_run: true,
        limit: 10,
        skip_rewritten: true,
      })
      const ready = payload.dry_run === true && Number(payload.processed || 0) > 0
      setResult({ payload, context: { commandFamily: 'finalize' } })
      setFinalizeReady(ready)
      setFinalizeSignature(ready ? pipelineSignature : '')
      onRefresh?.()
    } catch (error) {
      setResult({ payload: { ok: false, reason: error instanceof Error ? error.message : String(error) }, context: { commandFamily: 'finalize' } })
      setFinalizeReady(false)
      setFinalizeSignature('')
    } finally {
      setIsPending(false)
    }
  }

  async function liveFinalize() {
    if (!canLiveFinalize) return
    const confirmed = await confirm({
      title: 'Finalize paper strip drafts?',
      message: 'This rewrites the publication-draft batch surfaced by the paper strip. Use Dry-run finalize again if paper state may have changed.',
      confirmLabel: 'Finalize drafts',
      tone: 'warn',
    })
    if (!confirmed) return
    setIsPending(true)
    try {
      const payload = await apiPost<Record<string, unknown>>('/control/api/paper-reviews/rewrite-batch', {
        idempotency_key: idempotencyKey('paper-strip-rewrite-batch-live'),
        requested_by: 'dashboard-v2',
        paper_status: 'publication_draft',
        dry_run: false,
        force: true,
        limit: 10,
        skip_rewritten: true,
      })
      setResult({ payload, context: { commandFamily: 'finalize' } })
      setFinalizeReady(false)
      setFinalizeSignature('')
      onRefresh?.()
    } catch (error) {
      setResult({ payload: { ok: false, reason: error instanceof Error ? error.message : String(error) }, context: { commandFamily: 'finalize' } })
    } finally {
      setIsPending(false)
    }
  }

  return (
    <section className="paper-strip">
      <div>
        <p className="eyebrow">Paper pipeline</p>
        <h2>Write → Finalize → Publish</h2>
      </div>
      <div className="paper-steps">
        <a href={dashboardV2Href('#papers?status=publication_draft')}>
          <span>Write</span>
          <strong>{writeNeeded}</strong>
        </a>
        <button type="button" aria-label="Dry-run finalize" disabled={finalizeNeeded <= 0 || isPending} onClick={dryRunFinalize}>
          <span>Finalize</span>
          <strong>{finalizeNeeded}</strong>
          <em>Dry-run finalize</em>
        </button>
        <a href={dashboardV2Href('#corpus')}>
          <span>Publish</span>
          <strong>{publishReady}</strong>
        </a>
      </div>
      <div className="paper-strip-actions">
        <button className="primary-button" type="button" disabled={isPending || !canLiveFinalize} onClick={liveFinalize}>Finalize drafts</button>
        {finalizeDisabledReason ? <p className="paper-strip-disabled-reason">{finalizeDisabledReason}</p> : null}
      </div>
      {archiveCount > 0 || writeBlocked > 0 ? (
        <div className={writeBlocked > 0 ? 'paper-gate-note paper-gate-note--warn' : 'paper-gate-note'}>
          <strong>{writeBlocked > 0 ? 'Paper gate needs attention' : 'Paper gate archive'}</strong>
          <p>{archiveSummary} {writeBlocked} paper-writing candidate{writeBlocked === 1 ? ' is' : 's are'} currently blocked.</p>
        </div>
      ) : null}
      <ResultCard result={result} stale={finalizeReady && finalizeSignature !== pipelineSignature} />
      {dialog}
    </section>
  )
}
