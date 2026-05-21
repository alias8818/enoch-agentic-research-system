import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiGet, apiPost } from '../api/client'
import { DataTable } from './DataTable'

type AutomationResponse = {
  rows?: Record<string, unknown>[]
  counts?: Record<string, unknown>
}

type MutationResult = Record<string, unknown>

function idempotencyKey(prefix: string): string {
  return `${prefix}:dashboard-v2:${Date.now()}`
}

function firstPaperId(rows: Record<string, unknown>[]): string {
  return String(rows.find((row) => row.paper_id)?.paper_id || '')
}

function ResultCard({ result }: { result?: MutationResult }) {
  if (!result) return null
  return <pre className="json-block">{JSON.stringify(result, null, 2)}</pre>
}

export function AutomationPage() {
  const queryClient = useQueryClient()
  const automation = useQuery({
    queryKey: ['publication-automation'],
    queryFn: () => apiGet<AutomationResponse>('/control/api/publication-automation?page_size=50&paper_status=publication_draft&sort=-rank_score'),
  })
  const rewriteDryRun = useMutation({ mutationFn: () => apiPost<MutationResult>('/control/api/paper-reviews/rewrite-batch', { idempotency_key: idempotencyKey('paper-review-bulk-rewrite'), requested_by: 'dashboard-v2', paper_status: 'publication_draft', dry_run: true, limit: 10, skip_rewritten: true }) })
  const finalizationDryRun = useMutation({
    mutationFn: (paperId: string) => apiPost<MutationResult>(`/control/api/paper-reviews/${encodeURIComponent(paperId)}/prepare-finalization-package`, { idempotency_key: idempotencyKey(`paper-review-package:${paperId}`), requested_by: 'dashboard-v2', target_label: 'dashboard-v2-dry-run', dry_run: true }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['publication-automation'] }),
  })
  const rows = automation.data?.rows || []
  const counts = automation.data?.counts || {}
  const selectedPaperId = firstPaperId(rows)

  return (
    <section className="page-stack">
      <div className="page-hero">
        <p className="eyebrow">Dashboard V2</p>
        <h1>Publication automation</h1>
        <p>Paper workflow controls for draft rewrite planning and finalization package dry-runs. Live publish remains out of V2 for now.</p>
        <div className="action-row">
          <button className="secondary-button" type="button" onClick={() => rewriteDryRun.mutate()} disabled={rewriteDryRun.isPending}>Dry-run rewrite batch</button>
          <button className="secondary-button" type="button" onClick={() => selectedPaperId && finalizationDryRun.mutate(selectedPaperId)} disabled={!selectedPaperId || finalizationDryRun.isPending}>Dry-run finalization package</button>
        </div>
      </div>

      <section className="count-grid">
        {Object.entries(counts).slice(0, 8).map(([key, value]) => (
          <div key={key} className="count-card">
            <div>{String(value)}</div>
            <div>{key.replaceAll('_', ' ')}</div>
          </div>
        ))}
      </section>

      {rewriteDryRun.data ? <section className="result-card"><h2>Rewrite dry-run result</h2><ResultCard result={rewriteDryRun.data} /></section> : null}
      {finalizationDryRun.data ? <section className="result-card"><h2>Finalization dry-run result</h2><ResultCard result={finalizationDryRun.data} /></section> : null}

      {automation.isLoading ? <div className="state-card">Loading publication automation…</div> : null}
      {automation.isError ? <div className="state-card state-card--error">Publication automation unavailable: {String(automation.error.message)}</div> : null}
      {!automation.isLoading && !automation.isError ? (
        <DataTable rows={rows} columns={['paper_id', 'review_status', 'paper_status', 'project_name', 'rank_score', 'updated_at']} empty="No publication automation rows returned." />
      ) : null}
    </section>
  )
}
