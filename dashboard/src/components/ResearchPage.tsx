import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { apiGet, apiPost } from '../api/client'
import { dashboardV2Href } from '../routes'
import type { DashboardRoute } from '../routes'
import { DataTable } from './DataTable'
import { useOperatorDialog } from './OperatorDialog'

type ResearchFacilityResponse = {
  rows?: Record<string, unknown>[]
  counts?: Record<string, unknown>
  authority?: string
  generated_at?: string
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

type PromotionResponse = {
  ok?: boolean
  action?: string
  reason?: string
  candidate_id?: string
  title?: string
  idea_id?: string
  queued_count?: number
  dispatch_started?: boolean
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

function CandidateDetail({ row, candidateId }: { row: Record<string, unknown> | null; candidateId: string }) {
  if (!row && candidateId) {
    return (
      <section className="detail-panel" aria-label="Research candidate detail">
        <div className="detail-panel-head">
          <div>
            <p className="eyebrow">Research candidate detail</p>
            <h2>{candidateId}</h2>
          </div>
        </div>
        <section className="detail-summary">
          <p>Candidate {candidateId} is not present in the bounded research facility rows returned by /control/api/research/facility.</p>
        </section>
      </section>
    )
  }
  if (!row) return null
  return (
    <section className="detail-panel" aria-label="Research candidate detail">
      <div className="detail-panel-head">
        <div>
          <p className="eyebrow">Research candidate detail</p>
          <h2>{String(row.title || row.candidate_id || 'Selected candidate')}</h2>
        </div>
      </div>
      <section className="detail-summary">
        <p className="eyebrow">Deterministic facility row</p>
        <dl className="detail-field-grid">
          <div className="detail-field"><dt>candidate id</dt><dd>{String(row.candidate_id || '—')}</dd></div>
          <div className="detail-field"><dt>status</dt><dd>{String(row.status || '—')}</dd></div>
          <div className="detail-field"><dt>admission</dt><dd>{String(row.admission_decision || '—')}</dd></div>
          <div className="detail-field"><dt>machine target</dt><dd>{String(row.machine_target || '—')}</dd></div>
          <div className="detail-field"><dt>updated</dt><dd>{String(row.updated_at || '—')}</dd></div>
        </dl>
        <details className="raw-details">
          <summary>Raw candidate row</summary>
          <pre className="json-block">{JSON.stringify(row, null, 2)}</pre>
        </details>
      </section>
    </section>
  )
}

function candidateCellHref(row: Record<string, unknown>, column: string): string | undefined {
  if (column !== 'candidate_id') return undefined
  const candidateId = String(row.candidate_id || '')
  return candidateId ? dashboardV2Href(`#candidate:${encodeURIComponent(candidateId)}`) : undefined
}

export function ResearchPage({ route }: { route?: Extract<DashboardRoute, { page: 'research' }> }) {
  const queryClient = useQueryClient()
  const { confirm, dialog } = useOperatorDialog()
  const [selectedCandidate, setSelectedCandidate] = useState<Record<string, unknown> | null>(null)
  const facility = useQuery({ queryKey: ['research-facility'], queryFn: () => apiGet<ResearchFacilityResponse>('/control/api/research/facility?page_size=50') })
  const budget = useMutation({ mutationFn: () => apiGet<BudgetResponse>('/control/api/research/provider-budget?estimated_requests=1&reserve_requests=2') })
  const cycle = useMutation({
    mutationFn: (payload: typeof dryRunCyclePayload) => apiPost<CycleResponse>('/control/api/research/run-cycle', payload),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['research-facility'] }),
  })
  const promotion = useMutation({
    mutationFn: (payload: { candidate_id: string; dry_run: boolean; requested_by: string }) => apiPost<PromotionResponse>('/control/api/research/promote-candidate', payload),
    onSuccess: (payload) => {
      if (payload.action === 'promote_candidate') {
        setSelectedCandidate(null)
        void queryClient.invalidateQueries({ queryKey: ['research-facility'] })
      }
    },
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
  const routeCandidateId = route?.candidateId || ''
  const activeCandidate = selectedCandidate || rows.find((row) => String(row.candidate_id || '') === routeCandidateId) || null
  const selectedCandidateId = String(activeCandidate?.candidate_id || routeCandidateId || '')
  const selectedCandidateTitle = String(activeCandidate?.title || selectedCandidateId || 'No candidate selected')
  const candidateDryRunPassed = promotion.data?.action === 'dry_run_promote_candidate' && promotion.data?.candidate_id === selectedCandidateId

  async function dryRunPromotion() {
    if (!selectedCandidateId) return
    await promotion.mutateAsync({ candidate_id: selectedCandidateId, dry_run: true, requested_by: 'dashboard-v2' })
  }

  async function promoteCandidate() {
    if (!selectedCandidateId) return
    const confirmed = await confirm({
      title: 'Promote admitted candidate?',
      message: `Promote ${selectedCandidateId} into queued idea/project rows? This writes queue ledgers only and will not dispatch work.`,
      confirmLabel: 'Promote candidate',
      tone: 'warn',
    })
    if (!confirmed) return
    await promotion.mutateAsync({ candidate_id: selectedCandidateId, dry_run: false, requested_by: 'dashboard-v2' })
  }

  const counts = facility.data?.counts || {}
  function refreshCandidates() {
    setSelectedCandidate(null)
    promotion.reset()
    void facility.refetch()
  }

  return (
    <section className="page-stack">
      <div className="page-hero page-hero--with-action">
        <div>
          <p className="eyebrow">Dashboard V2</p>
          <h1>Research Facility</h1>
          <p>Bounded candidate workbench and autopilot controls. Backend APIs remain the source of truth.</p>
          <div className="action-row">
            <button className="secondary-button" type="button" onClick={() => budget.mutate()} disabled={budget.isPending}>Check provider budget</button>
            <button className="secondary-button" type="button" onClick={runDryCycle} disabled={cycle.isPending}>Dry-run bounded cycle</button>
            <button className="primary-button" type="button" onClick={runLiveCycle} disabled={cycle.isPending}>Run one bounded cycle</button>
          </div>
        </div>
        <div className="page-hero-action">
          <span>Last loaded {facility.data?.generated_at || 'unknown'}</span>
          <button className="secondary-button" type="button" disabled={facility.isFetching} onClick={refreshCandidates}>
            {facility.isFetching ? 'Refreshing…' : 'Refresh candidates'}
          </button>
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

      <section className="queue-command-card">
        <div>
          <p className="eyebrow">Selected candidate</p>
          <h2>{selectedCandidateTitle}</h2>
          <p>{selectedCandidateId ? 'Dry-run promotion first. Live promotion queues the idea/project row only; it does not dispatch.' : 'Select an admitted candidate row before promotion.'}</p>
        </div>
        <div className="action-row">
          <button className="secondary-button" type="button" disabled={!selectedCandidateId || promotion.isPending} onClick={dryRunPromotion}>
            {promotion.isPending ? 'Checking…' : 'Dry-run promote selected'}
          </button>
          <button className="primary-button" type="button" disabled={!selectedCandidateId || !candidateDryRunPassed || promotion.isPending} onClick={promoteCandidate}>
            Promote selected candidate
          </button>
        </div>
      </section>

      {promotion.data?.action === 'dry_run_promote_candidate' ? <ResultCard title="Candidate promotion dry-run" result={promotion.data as Record<string, unknown>} /> : null}
      {promotion.data?.action === 'promote_candidate' ? <ResultCard title="Candidate promotion result" result={promotion.data as Record<string, unknown>} /> : null}

      {dialog}

      {facility.isLoading ? <div className="state-card">Loading research facility…</div> : null}
      {facility.isError ? <div className="state-card state-card--error">Research data unavailable: {String(facility.error.message)}</div> : null}
      {!facility.isLoading && !facility.isError ? (
        <>
          <DataTable rows={rows} columns={['candidate_id', 'status', 'admission_decision', 'machine_target', 'title', 'updated_at']} empty="No research candidates returned." cellHref={candidateCellHref} onSelectRow={setSelectedCandidate} />
          <CandidateDetail row={activeCandidate} candidateId={routeCandidateId} />
        </>
      ) : null}
    </section>
  )
}
