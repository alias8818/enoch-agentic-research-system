import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiGet, apiPost } from '../api/client'
import { DataTable } from './DataTable'
import { useOperatorDialog } from './OperatorDialog'

type ResearchFacilityResponse = {
  rows?: Record<string, unknown>[]
  counts?: Record<string, unknown>
  authority?: string
}

type BudgetResponse = {
  ok?: boolean
  failures?: string[]
  remaining_credits?: number
  rolling_remaining?: number
  auth_mode?: string
}

type CycleResponse = {
  ok?: boolean
  action?: string
  reason?: string
  generated_count?: number
  promoted_count?: number
  dispatched_count?: number
  queued_count?: number
}

const dryRunCyclePayload = {
  enabled: false,
  dry_run: true,
  requested_by: 'dashboard-v2',
  max_provider_requests_per_run: 1,
  max_promotions_per_run: 2,
  max_dispatches_per_run: 0,
  wait_for_completion: false,
  max_wait_seconds: 0,
  max_paper_drafts_per_run: 0,
  max_publication_rewrites_per_run: 0,
  generation_max_tokens: 8000,
  generation_attempts: 2,
  temperature: 0.6,
}

const liveCyclePayload = {
  ...dryRunCyclePayload,
  enabled: true,
  dry_run: false,
}

function ResultCard({ title, result }: { title: string; result?: Record<string, unknown> }) {
  if (!result) return null
  return (
    <section className="rounded-2xl border border-zinc-800 bg-black/20 p-5">
      <h3 className="font-bold text-white">{title}</h3>
      <pre className="mt-3 max-h-72 overflow-auto rounded-xl bg-black/40 p-4 text-xs text-zinc-300">{JSON.stringify(result, null, 2)}</pre>
    </section>
  )
}

export function ResearchPage() {
  const queryClient = useQueryClient()
  const { confirm, dialog } = useOperatorDialog()
  const facility = useQuery({ queryKey: ['research-facility'], queryFn: () => apiGet<ResearchFacilityResponse>('/control/api/research/facility?page_size=50') })
  const budget = useMutation({ mutationFn: () => apiGet<BudgetResponse>('/control/api/research/provider-budget?estimated_requests=1&reserve_requests=2') })
  const cycle = useMutation({
    mutationFn: (payload: typeof dryRunCyclePayload) => apiPost<CycleResponse>('/control/api/research/run-cycle', payload),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['research-facility'] }),
  })

  async function runDryCycle() {
    await cycle.mutateAsync(dryRunCyclePayload)
  }

  async function runLiveCycle() {
    const confirmed = await confirm({
      title: 'Run one bounded live cycle?',
      message: 'This can spend one provider request and promote candidates. V2 will not dispatch, wait for completion, write papers, or finalize publications from this action.',
      confirmLabel: 'Run bounded cycle',
      tone: 'warn',
    })
    if (!confirmed) return
    await cycle.mutateAsync(liveCyclePayload)
  }

  const rows = facility.data?.rows || []
  const counts = facility.data?.counts || {}

  return (
    <section className="space-y-5">
      <div className="rounded-3xl border border-zinc-800 bg-zinc-950 p-6">
        <p className="text-xs font-bold uppercase tracking-[0.28em] text-sky-300">Dashboard V2</p>
        <h1 className="mt-2 text-3xl font-black text-white">Research Facility</h1>
        <p className="mt-2 text-sm text-zinc-400">Bounded candidate workbench and autopilot controls. Backend APIs remain the source of truth.</p>
        <div className="mt-5 flex flex-wrap gap-2">
          <button className="rounded-xl border border-zinc-700 px-4 py-2 text-sm font-bold text-white disabled:opacity-40" type="button" onClick={() => budget.mutate()} disabled={budget.isPending}>Check provider budget</button>
          <button className="rounded-xl border border-zinc-700 px-4 py-2 text-sm font-bold text-white disabled:opacity-40" type="button" onClick={runDryCycle} disabled={cycle.isPending}>Dry-run bounded cycle</button>
          <button className="rounded-xl bg-sky-500 px-4 py-2 text-sm font-bold text-white disabled:opacity-40" type="button" onClick={runLiveCycle} disabled={cycle.isPending}>Run one bounded cycle</button>
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

      <ResultCard title="Provider budget result" result={budget.data as Record<string, unknown> | undefined} />
      <ResultCard title="Run-cycle result" result={cycle.data as Record<string, unknown> | undefined} />

      {dialog}

      {facility.isLoading ? <div className="rounded-2xl border border-zinc-800 bg-zinc-950 p-8 text-zinc-400">Loading research facility…</div> : null}
      {facility.isError ? <div className="rounded-2xl border border-red-900 bg-red-950/40 p-8 text-red-100">Research data unavailable: {String(facility.error.message)}</div> : null}
      {!facility.isLoading && !facility.isError ? (
        <DataTable rows={rows} columns={['candidate_id', 'status', 'admission_decision', 'machine_target', 'title', 'updated_at']} empty="No research candidates returned." />
      ) : null}
    </section>
  )
}
