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
  return <pre className="max-h-80 overflow-auto rounded-2xl border border-zinc-800 bg-black/40 p-4 text-xs text-zinc-300">{JSON.stringify(result, null, 2)}</pre>
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
    <section className="space-y-5">
      <div className="rounded-3xl border border-zinc-800 bg-zinc-950 p-6">
        <p className="text-xs font-bold uppercase tracking-[0.28em] text-sky-300">Dashboard V2</p>
        <h1 className="mt-2 text-3xl font-black text-white">Publication automation</h1>
        <p className="mt-2 text-sm text-zinc-400">Paper workflow controls for draft rewrite planning and finalization package dry-runs. Live publish remains out of V2 for now.</p>
        <div className="mt-5 flex flex-wrap gap-2">
          <button className="rounded-xl border border-zinc-700 px-4 py-2 text-sm font-bold text-white disabled:opacity-40" type="button" onClick={() => rewriteDryRun.mutate()} disabled={rewriteDryRun.isPending}>Dry-run rewrite batch</button>
          <button className="rounded-xl border border-zinc-700 px-4 py-2 text-sm font-bold text-white disabled:opacity-40" type="button" onClick={() => selectedPaperId && finalizationDryRun.mutate(selectedPaperId)} disabled={!selectedPaperId || finalizationDryRun.isPending}>Dry-run finalization package</button>
        </div>
      </div>

      <section className="grid gap-3 md:grid-cols-4">
        {Object.entries(counts).slice(0, 8).map(([key, value]) => (
          <div key={key} className="rounded-2xl border border-zinc-800 bg-zinc-950 p-4">
            <div className="text-2xl font-black tabular-nums text-white">{String(value)}</div>
            <div className="mt-1 text-xs uppercase tracking-[0.16em] text-zinc-500">{key.replaceAll('_', ' ')}</div>
          </div>
        ))}
      </section>

      {rewriteDryRun.data ? <section><h2 className="mb-3 text-lg font-bold text-white">Rewrite dry-run result</h2><ResultCard result={rewriteDryRun.data} /></section> : null}
      {finalizationDryRun.data ? <section><h2 className="mb-3 text-lg font-bold text-white">Finalization dry-run result</h2><ResultCard result={finalizationDryRun.data} /></section> : null}

      {automation.isLoading ? <div className="rounded-2xl border border-zinc-800 bg-zinc-950 p-8 text-zinc-400">Loading publication automation…</div> : null}
      {automation.isError ? <div className="rounded-2xl border border-red-900 bg-red-950/40 p-8 text-red-100">Publication automation unavailable: {String(automation.error.message)}</div> : null}
      {!automation.isLoading && !automation.isError ? (
        <DataTable rows={rows} columns={['paper_id', 'review_status', 'paper_status', 'project_name', 'rank_score', 'updated_at']} empty="No publication automation rows returned." />
      ) : null}
    </section>
  )
}
