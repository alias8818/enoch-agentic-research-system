import { useState } from 'react'
import { apiPost } from '../api/client'
import { dashboardV2Href } from '../routes'
import type { OverviewResponse } from '../types'
import { useOperatorDialog } from './OperatorDialog'

type CommandResult = {
  title: string
  payload: Record<string, unknown>
}

function idempotencyKey(prefix: string): string {
  return `${prefix}:dashboard-v2:${Date.now()}`
}

function ResultCard({ result }: { result: CommandResult | null }) {
  if (!result) return null
  const reason = String(result.payload.reason || result.payload.detail || result.payload.action || 'Dry-run completed.')
  return (
    <section className="result-card paper-strip-result" aria-live="polite">
      <h3>{result.title}</h3>
      <p>{reason}</p>
      <pre>{JSON.stringify(result.payload, null, 2)}</pre>
    </section>
  )
}

function finalizationDisabledReason(finalizeNeeded: number, finalizeReady: boolean, isPending: boolean): string {
  if (isPending) return 'Finalize drafts disabled: paper command is running.'
  if (finalizeNeeded <= 0) return 'Finalize drafts disabled: no publication drafts need finalization.'
  if (!finalizeReady) return 'Finalize drafts disabled: run Dry-run finalize first.'
  return ''
}

export function PaperMiniStrip({ pipeline, onRefresh }: { pipeline: OverviewResponse['paper_pipeline']; onRefresh?: () => void }) {
  const [result, setResult] = useState<CommandResult | null>(null)
  const [isPending, setIsPending] = useState(false)
  const [finalizeReady, setFinalizeReady] = useState(false)
  const { confirm, dialog } = useOperatorDialog()
  const writeNeeded = pipeline?.write_needed ?? 0
  const finalizeNeeded = pipeline?.finalize_needed ?? 0
  const publishReady = pipeline?.publish_ready ?? 0
  const finalizeDisabledReason = finalizationDisabledReason(finalizeNeeded, finalizeReady, isPending)

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
      setResult({ title: 'Paper dry-run result', payload })
      setFinalizeReady(payload.dry_run === true && Number(payload.processed || 0) > 0)
      onRefresh?.()
    } catch (error) {
      setResult({ title: 'Paper dry-run failed', payload: { ok: false, reason: error instanceof Error ? error.message : String(error) } })
      setFinalizeReady(false)
    } finally {
      setIsPending(false)
    }
  }

  async function liveFinalize() {
    if (!finalizeReady) return
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
      setResult({ title: 'Paper live finalization result', payload })
      setFinalizeReady(false)
      onRefresh?.()
    } catch (error) {
      setResult({ title: 'Paper live finalization failed', payload: { ok: false, reason: error instanceof Error ? error.message : String(error) } })
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
        <button className="primary-button" type="button" disabled={isPending || !finalizeReady} onClick={liveFinalize}>Finalize drafts</button>
        {finalizeDisabledReason ? <p className="paper-strip-disabled-reason">{finalizeDisabledReason}</p> : null}
      </div>
      <ResultCard result={result} />
      {dialog}
    </section>
  )
}
