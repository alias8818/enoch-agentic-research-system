import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { apiGet, apiPost } from '../api/client'
import { dryRunCyclePayload, liveCyclePayload } from '../researchCyclePayloads'
import { dashboardV2Href } from '../routes'
import type { DashboardRoute } from '../routes'
import { shortId } from '../format'
import { DataTable } from './DataTable'
import { simpleTableColumns } from '../tablePresentation'
import { useOperatorDialog } from './OperatorDialog'
import type { CommandPresentationContext } from '../commandResultPresentation'
import { CommandResultSummary } from './CommandResultSummary'
import { PageHeader } from './PageHeader'
import { deriveResearchCandidateOperatorSummary } from '../detailOperatorSummary'
import { EntityLinkChips, InlineErrorStateCard, LoadingStateCard, OperatorDetailSummary, OperatorQuestionSections, RawJsonDetails } from './ui'

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
  dry_run?: boolean
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

type GenerateBatchResponse = {
  ok?: boolean
  action?: string
  reason?: string
  dry_run?: boolean
  candidate_count?: number
  admitted_count?: number
  queued_count?: number
}

function ResultCard({ result, context, stale }: { result?: Record<string, unknown>; context?: CommandPresentationContext; stale?: boolean }) {
  if (!result) return null
  return <CommandResultSummary result={{ payload: result, context: { ...context, stale } }} />
}

function facilitySignature(facility?: ResearchFacilityResponse): string {
  if (!facility) return ''
  const counts = facility.counts && typeof facility.counts === 'object'
    ? Object.entries(facility.counts).sort(([left], [right]) => left.localeCompare(right))
    : []
  return JSON.stringify({
    generated_at: facility.generated_at || '',
    counts,
    rows: (facility.rows || []).map((row) => [
      String(row.candidate_id || ''),
      String(row.status || ''),
      String(row.admission_decision || ''),
      String(row.machine_target || ''),
      String(row.updated_at || ''),
    ]),
  })
}

function cycleDryRunAllowsLive(payload?: CycleResponse): boolean {
  if (!payload) return false
  const action = String(payload.action || '').toLowerCase()
  const reason = String(payload.reason || '').toLowerCase()
  if (action.includes('blocked') || action.includes('skipped') || reason.includes('blocked')) return false
  return payload.dry_run === true || action.includes('dry_run') || reason.includes('would ')
}

function liveCycleDisabledReason(canLiveCycle: boolean, dryRunReady: boolean, staleDryRun: boolean, isPending: boolean): string {
  if (isPending) return 'Run one bounded cycle disabled: research command is running.'
  if (canLiveCycle) return ''
  if (staleDryRun) return 'Run one bounded cycle disabled: facility state changed; dry-run bounded cycle again.'
  if (!dryRunReady) return 'Run one bounded cycle disabled: dry-run bounded cycle first.'
  return ''
}

function generateBatchAllowsLive(payload?: GenerateBatchResponse): boolean {
  if (!payload?.ok) return false
  const action = String(payload.action || '').toLowerCase()
  if (action.includes('blocked')) return false
  return payload.dry_run === true && action.includes('dry_run_generate')
}

function providerBatchAllowsLive(payload?: GenerateBatchResponse): boolean {
  if (!payload?.ok) return false
  const action = String(payload.action || '').toLowerCase()
  if (action.includes('blocked')) return false
  return payload.dry_run === true && action.includes('dry_run_provider')
}

function liveGenerateDisabledReason(canLive: boolean, dryRunReady: boolean, isPending: boolean, label: string): string {
  if (isPending) return `${label} disabled: research command is running.`
  if (canLive) return ''
  if (!dryRunReady) return `${label} disabled: dry-run candidate generation first.`
  return ''
}

function CandidateDetail({ row, candidateId }: { row: Record<string, unknown> | null; candidateId: string }) {
  if (!row && candidateId) {
    return (
      <section className="detail-panel" aria-label="Research candidate detail">
        <div className="detail-panel-head">
          <div>
            <p className="eyebrow">Research candidate detail</p>
            <h2>Candidate detail</h2>
            <span className="detail-id-chip" title={candidateId}>{shortId(candidateId)}</span>
          </div>
        </div>
        <section className="detail-summary">
          <p>Candidate {candidateId} is not present in the bounded research facility rows returned by /control/api/research/facility.</p>
        </section>
      </section>
    )
  }
  if (!row) return null
  const operatorSummary = deriveResearchCandidateOperatorSummary(row)
  return (
    <section className="detail-panel" aria-label="Research candidate detail">
      <div className="detail-panel-head">
        <div>
          <p className="eyebrow">Research candidate detail</p>
          <h2>{String(row.title || row.candidate_id || 'Selected candidate')}</h2>
          <span className="detail-id-chip" title={String(row.candidate_id || '')}>{shortId(String(row.candidate_id || ''))}</span>
        </div>
      </div>
      <section className="detail-summary">
        <EntityLinkChips links={operatorSummary.entityLinks} />
        <OperatorDetailSummary
          state={operatorSummary.state}
          context={operatorSummary.context}
          next={operatorSummary.next}
          ariaLabel="Research candidate operator summary"
        />
        <OperatorQuestionSections sections={operatorSummary.sections} recentActivity={null} actionNeeded={operatorSummary.actionNeeded} />
        <RawJsonDetails summary="Raw candidate row" payload={row} />
      </section>
    </section>
  )
}

function candidateCellHref(row: Record<string, unknown>, column: string): string | undefined {
  if (column !== 'candidate_id') return undefined
  const candidateId = String(row.candidate_id || '')
  return candidateId ? dashboardV2Href(`#research:${encodeURIComponent(candidateId)}`) : undefined
}

export function ResearchPage({ route }: { route?: Extract<DashboardRoute, { page: 'research' }> }) {
  const queryClient = useQueryClient()
  const { confirm, dialog } = useOperatorDialog()
  const [selectedCandidate, setSelectedCandidate] = useState<Record<string, unknown> | null>(null)
  const [cycleDryRunSignature, setCycleDryRunSignature] = useState('')
  const [cycleDryRunReady, setCycleDryRunReady] = useState(false)
  const [batchDryRunReady, setBatchDryRunReady] = useState(false)
  const [providerBatchDryRunReady, setProviderBatchDryRunReady] = useState(false)
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
  const generateBatch = useMutation({
    mutationFn: (payload: { dry_run: boolean; max_candidates: number; requested_by: string }) => apiPost<GenerateBatchResponse>('/control/api/research/generate-batch', payload),
    onSuccess: (payload, variables) => {
      if (variables.dry_run) {
        setBatchDryRunReady(generateBatchAllowsLive(payload))
      } else {
        setBatchDryRunReady(false)
        void queryClient.invalidateQueries({ queryKey: ['research-facility'] })
      }
    },
  })
  const generateProviderBatch = useMutation({
    mutationFn: (payload: { dry_run: boolean; max_candidates: number; requested_by: string }) => apiPost<GenerateBatchResponse>('/control/api/research/generate-provider-batch', payload),
    onSuccess: (payload, variables) => {
      if (variables.dry_run) {
        setProviderBatchDryRunReady(providerBatchAllowsLive(payload))
      } else {
        setProviderBatchDryRunReady(false)
        void queryClient.invalidateQueries({ queryKey: ['research-facility'] })
      }
    },
  })

  async function runDryCycle() {
    const payload = await cycle.mutateAsync(dryRunCyclePayload)
    const ready = cycleDryRunAllowsLive(payload)
    setCycleDryRunReady(ready)
    setCycleDryRunSignature(ready ? currentFacilitySignature : '')
  }

  async function runLiveCycle() {
    if (!canLiveCycle) return
    const confirmed = await confirm({
      title: 'Run one bounded live cycle?',
      message: 'This can spend one provider request and promote candidates. V2 will not dispatch, wait for completion, write papers, or finalize publications from this action.',
      confirmLabel: 'Run bounded cycle',
      tone: 'warn',
    })
    if (!confirmed) return
    await cycle.mutateAsync(liveCyclePayload)
    setCycleDryRunReady(false)
    setCycleDryRunSignature('')
  }

  async function runLiveGenerateBatch() {
    if (!canLiveGenerateBatch) return
    const confirmed = await confirm({
      title: 'Generate research candidates now?',
      message: 'This writes new internal research candidates to the facility ledger. Review dry-run counts before proceeding.',
      confirmLabel: 'Generate candidates',
      tone: 'warn',
    })
    if (!confirmed) return
    await generateBatch.mutateAsync({ dry_run: false, max_candidates: 3, requested_by: 'dashboard-v2' })
  }

  async function runLiveProviderBatch() {
    if (!canLiveProviderBatch) return
    const confirmed = await confirm({
      title: 'Generate provider-backed candidates now?',
      message: 'This spends provider inference budget and writes candidates to the facility ledger. Review dry-run budget checks first.',
      confirmLabel: 'Generate provider batch',
      tone: 'danger',
    })
    if (!confirmed) return
    await generateProviderBatch.mutateAsync({ dry_run: false, max_candidates: 2, requested_by: 'dashboard-v2' })
  }

  const rows = facility.data?.rows || []
  const currentFacilitySignature = facilitySignature(facility.data)
  const canLiveCycle = cycleDryRunReady && Boolean(currentFacilitySignature) && cycleDryRunSignature === currentFacilitySignature
  const staleCycleDryRun = cycleDryRunReady && cycleDryRunSignature !== currentFacilitySignature
  const cycleDisabledReason = liveCycleDisabledReason(canLiveCycle, cycleDryRunReady, staleCycleDryRun, cycle.isPending)
  const canLiveGenerateBatch = batchDryRunReady && generateBatchAllowsLive(generateBatch.data)
  const canLiveProviderBatch = providerBatchDryRunReady && providerBatchAllowsLive(generateProviderBatch.data)
  const generateBatchDisabledReason = liveGenerateDisabledReason(canLiveGenerateBatch, batchDryRunReady, generateBatch.isPending, 'Generate candidate batch')
  const providerBatchDisabledReason = liveGenerateDisabledReason(canLiveProviderBatch, providerBatchDryRunReady, generateProviderBatch.isPending, 'Generate provider batch')
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
    setBatchDryRunReady(false)
    setProviderBatchDryRunReady(false)
    void facility.refetch()
  }

  return (
    <section className="page-stack">
      <PageHeader
        title="Research Facility"
        subtitle="Promote admitted candidates and run bounded research cycles safely."
        dataSource="/control/api/v1/research-facility and autopilot endpoints"
        action={(
          <>
            <span>Last loaded {facility.data?.generated_at || 'unknown'}</span>
            <button className="secondary-button" type="button" disabled={facility.isFetching} onClick={refreshCandidates}>
              {facility.isFetching ? 'Refreshing…' : 'Refresh candidates'}
            </button>
          </>
        )}
        toolbar={(
          <div className="action-row">
            <button className="secondary-button" type="button" onClick={() => budget.mutate()} disabled={budget.isPending}>Check provider budget</button>
            <button className="secondary-button" type="button" onClick={runDryCycle} disabled={cycle.isPending}>Dry-run bounded cycle</button>
            <button className="primary-button" type="button" onClick={runLiveCycle} disabled={cycle.isPending || !canLiveCycle}>Run one bounded cycle</button>
          </div>
        )}
      />
      {cycleDisabledReason ? <p className="primary-action-disabled-reason">{cycleDisabledReason}</p> : null}

      <section className="queue-command-card queue-command-card--compact" aria-label="Research candidate generation">
        <div>
          <p className="eyebrow">Candidate generation</p>
          <h2>Generate research candidates</h2>
          <p>Dry-run internal or provider-backed batches first. Live generation writes facility ledger rows only; it does not dispatch queue work.</p>
        </div>
        <div className="action-row">
          <button className="secondary-button" type="button" disabled={generateBatch.isPending} onClick={() => { void generateBatch.mutateAsync({ dry_run: true, max_candidates: 3, requested_by: 'dashboard-v2' }) }}>Dry-run generate batch</button>
          <button className="primary-button" type="button" disabled={generateBatch.isPending || !canLiveGenerateBatch} onClick={() => { void runLiveGenerateBatch() }}>Generate candidate batch</button>
          <button className="secondary-button" type="button" disabled={generateProviderBatch.isPending} onClick={() => { void generateProviderBatch.mutateAsync({ dry_run: true, max_candidates: 2, requested_by: 'dashboard-v2' }) }}>Dry-run provider batch</button>
          <button className="danger-button" type="button" disabled={generateProviderBatch.isPending || !canLiveProviderBatch} onClick={() => { void runLiveProviderBatch() }}>Generate provider batch</button>
        </div>
      </section>
      {generateBatchDisabledReason ? <p className="primary-action-disabled-reason">{generateBatchDisabledReason}</p> : null}
      {providerBatchDisabledReason ? <p className="primary-action-disabled-reason">{providerBatchDisabledReason}</p> : null}

      <section className="count-grid">
        {Object.entries(counts).slice(0, 8).map(([key, value]) => (
          <div key={key} className="count-card">
            <div>{String(value)}</div>
            <div>{key.replaceAll('_', ' ')}</div>
          </div>
        ))}
      </section>

      <ResultCard result={budget.data as Record<string, unknown> | undefined} context={{ commandFamily: 'research' }} />
      <ResultCard result={cycle.data as Record<string, unknown> | undefined} context={{ commandFamily: 'research' }} stale={staleCycleDryRun} />
      <ResultCard result={generateBatch.data as Record<string, unknown> | undefined} context={{ commandFamily: 'research' }} />
      <ResultCard result={generateProviderBatch.data as Record<string, unknown> | undefined} context={{ commandFamily: 'research' }} />

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

      {promotion.data?.action === 'dry_run_promote_candidate' ? <ResultCard result={promotion.data as Record<string, unknown>} context={{ commandFamily: 'research' }} /> : null}
      {promotion.data?.action === 'promote_candidate' ? <ResultCard result={promotion.data as Record<string, unknown>} context={{ commandFamily: 'research' }} /> : null}

      {dialog}

      {facility.isLoading ? <LoadingStateCard label="research facility" /> : null}
      {facility.isError ? <InlineErrorStateCard prefix="Research data unavailable" message={String(facility.error.message)} /> : null}
      {!facility.isLoading && !facility.isError ? (
        <>
          <DataTable rows={rows} columns={simpleTableColumns(['candidate_id', 'status', 'admission_decision', 'machine_target', 'title', 'updated_at'], { title: { kind: 'primary' }, candidate_id: { kind: 'id' } })} empty="No research candidates returned." cellHref={candidateCellHref} onSelectRow={setSelectedCandidate} />
          <CandidateDetail row={activeCandidate} candidateId={routeCandidateId} />
        </>
      ) : null}
    </section>
  )
}
