import { useState } from 'react'
import { apiPost } from '../api/client'
import { dashboardV2Href } from '../routes'
import type { OverviewResponse } from '../types'

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

export function PaperMiniStrip({ pipeline, onRefresh }: { pipeline: OverviewResponse['paper_pipeline']; onRefresh?: () => void }) {
  const [result, setResult] = useState<CommandResult | null>(null)
  const [isPending, setIsPending] = useState(false)
  const writeNeeded = pipeline?.write_needed ?? 0
  const finalizeNeeded = pipeline?.finalize_needed ?? 0
  const publishReady = pipeline?.publish_ready ?? 0

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
      onRefresh?.()
    } catch (error) {
      setResult({ title: 'Paper dry-run failed', payload: { ok: false, reason: error instanceof Error ? error.message : String(error) } })
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
      <ResultCard result={result} />
    </section>
  )
}
