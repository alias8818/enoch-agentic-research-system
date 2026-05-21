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
    <section className="result-card">
      <h3>{title}</h3>
      <pre>{JSON.stringify(result, null, 2)}</pre>
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
    <section className="page-stack">
      <div className="page-hero">
        <p className="eyebrow">Dashboard V2</p>
        <h1>Research Facility</h1>
        <p>Bounded candidate workbench and autopilot controls. Backend APIs remain the source of truth.</p>
        <div className="action-row">
          <button className="secondary-button" type="button" onClick={() => budget.mutate()} disabled={budget.isPending}>Check provider budget</button>
          <button className="secondary-button" type="button" onClick={runDryCycle} disabled={cycle.isPending}>Dry-run bounded cycle</button>
          <button className="primary-button" type="button" onClick={runLiveCycle} disabled={cycle.isPending}>Run one bounded cycle</button>
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

      <ResultCard title="Provider budget result" result={budget.data as Record<string, unknown> | undefined} />
      <ResultCard title="Run-cycle result" result={cycle.data as Record<string, unknown> | undefined} />

      {dialog}

      {facility.isLoading ? <div className="state-card">Loading research facility…</div> : null}
      {facility.isError ? <div className="state-card state-card--error">Research data unavailable: {String(facility.error.message)}</div> : null}
      {!facility.isLoading && !facility.isError ? (
        <DataTable rows={rows} columns={['candidate_id', 'status', 'admission_decision', 'machine_target', 'title', 'updated_at']} empty="No research candidates returned." />
      ) : null}
    </section>
  )
}
