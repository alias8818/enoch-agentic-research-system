import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { apiGet, apiPost } from '../api/client'
import { displayText } from '../displayText'
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
import { WorkbenchCountsFold, WorkbenchOperatorSummary } from './WorkbenchSummary'

type ResearchFacilityResponse = {
  rows?: Record<string, unknown>[]
  counts?: Record<string, unknown>
  operator_summary?: string
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

function ResultCard({ result, context, stale }: Readonly<{ result?: Record<string, unknown>; context?: CommandPresentationContext; stale?: boolean }>) {
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
      displayText(row.candidate_id),
      displayText(row.status),
      displayText(row.admission_decision),
      displayText(row.machine_target),
      displayText(row.updated_at),
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

function CandidateDetailMissing({ candidateId }: Readonly<{ candidateId: string }>) {
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

function CandidateDetailPanel({ row }: Readonly<{ row: Record<string, unknown> }>) {
  const operatorSummary = deriveResearchCandidateOperatorSummary(row)
  const rowCandidateId = displayText(row.candidate_id)
  return (
    <section className="detail-panel" aria-label="Research candidate detail">
      <div className="detail-panel-head">
        <div>
          <p className="eyebrow">Research candidate detail</p>
          <h2>{displayText(row.title || row.candidate_id, 'Selected candidate')}</h2>
          <span className="detail-id-chip" title={rowCandidateId}>{shortId(rowCandidateId)}</span>
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

function researchCandidateDetailHref(candidateId: string): string {
  return dashboardV2Href(`#research:${encodeURIComponent(candidateId)}`)
}

type ResearchGenerationSectionProps = Readonly<{
  generateBatchPending: boolean
  generateProviderBatchPending: boolean
  canLiveGenerateBatch: boolean
  canLiveProviderBatch: boolean
  generateBatchDisabledReason: string
  providerBatchDisabledReason: string
  onDryRunGenerateBatch: () => void
  onLiveGenerateBatch: () => void
  onDryRunProviderBatch: () => void
  onLiveProviderBatch: () => void
}>

function ResearchGenerationSection({
  generateBatchPending,
  generateProviderBatchPending,
  canLiveGenerateBatch,
  canLiveProviderBatch,
  generateBatchDisabledReason,
  providerBatchDisabledReason,
  onDryRunGenerateBatch,
  onLiveGenerateBatch,
  onDryRunProviderBatch,
  onLiveProviderBatch,
}: ResearchGenerationSectionProps) {
  return (
    <>
      <section className="queue-command-card queue-command-card--compact" aria-label="Research candidate generation">
        <div>
          <p className="eyebrow">Candidate generation</p>
          <h2>Generate research candidates</h2>
          <p>Dry-run internal or provider-backed batches first. Live generation writes facility ledger rows only; it does not dispatch queue work.</p>
        </div>
        <div className="action-row">
          <button className="secondary-button" type="button" disabled={generateBatchPending} onClick={onDryRunGenerateBatch}>Dry-run generate batch</button>
          <button className="primary-button" type="button" disabled={generateBatchPending || !canLiveGenerateBatch} onClick={onLiveGenerateBatch}>Generate candidate batch</button>
          <button className="secondary-button" type="button" disabled={generateProviderBatchPending} onClick={onDryRunProviderBatch}>Dry-run provider batch</button>
          <button className="danger-button" type="button" disabled={generateProviderBatchPending || !canLiveProviderBatch} onClick={onLiveProviderBatch}>Generate provider batch</button>
        </div>
      </section>
      {generateBatchDisabledReason ? <p className="primary-action-disabled-reason">{generateBatchDisabledReason}</p> : null}
      {providerBatchDisabledReason ? <p className="primary-action-disabled-reason">{providerBatchDisabledReason}</p> : null}
    </>
  )
}

type ResearchSelectedCandidateSectionProps = Readonly<{
  selectedCandidateTitle: string
  selectedCandidateId: string
  promotionPending: boolean
  candidateDryRunPassed: boolean
  onDryRunPromotion: () => void
  onPromoteCandidate: () => void
  promotionResult?: PromotionResponse
}>

function ResearchSelectedCandidateSection({
  selectedCandidateTitle,
  selectedCandidateId,
  promotionPending,
  candidateDryRunPassed,
  onDryRunPromotion,
  onPromoteCandidate,
  promotionResult,
}: ResearchSelectedCandidateSectionProps) {
  return (
    <>
      <section className="queue-command-card">
        <div>
          <p className="eyebrow">Selected candidate</p>
          <h2>{selectedCandidateTitle}</h2>
          <p>{selectedCandidateId ? 'Dry-run promotion first. Live promotion queues the idea/project row only; it does not dispatch.' : 'Select an admitted candidate row before promotion.'}</p>
        </div>
        <div className="action-row">
          <button className="secondary-button" type="button" disabled={!selectedCandidateId || promotionPending} onClick={onDryRunPromotion}>
            {promotionPending ? 'Checking…' : 'Dry-run promote selected'}
          </button>
          <button className="primary-button" type="button" disabled={!selectedCandidateId || !candidateDryRunPassed || promotionPending} onClick={onPromoteCandidate}>
            Promote selected candidate
          </button>
        </div>
      </section>
      {promotionResult?.action === 'dry_run_promote_candidate' ? <ResultCard result={promotionResult} context={{ commandFamily: 'research' }} /> : null}
      {promotionResult?.action === 'promote_candidate' ? <ResultCard result={promotionResult} context={{ commandFamily: 'research' }} /> : null}
    </>
  )
}

type ResearchFacilityBodyProps = Readonly<{
  rows: Record<string, unknown>[]
  counts: Record<string, unknown>
  activeCandidate: Record<string, unknown> | null
  routeCandidateId: string
  onSelectRow: (row: Record<string, unknown>) => void
}>

function ResearchFacilityBody({ rows, counts, activeCandidate, routeCandidateId, onSelectRow }: ResearchFacilityBodyProps) {
  return (
    <>
      <DataTable
        rows={rows}
        columns={simpleTableColumns(['candidate_id', 'status', 'admission_decision', 'machine_target', 'title', 'updated_at'], { title: { kind: 'primary' }, candidate_id: { kind: 'id' } })}
        empty="No research candidates returned."
        cellHref={(row, column) => {
          if (column !== 'candidate_id') return undefined
          const candidateId = displayText(row.candidate_id)
          return candidateId ? researchCandidateDetailHref(candidateId) : undefined
        }}
        onSelectRow={onSelectRow}
      />
      <WorkbenchCountsFold counts={counts} label="Research facility counts" />
      {!activeCandidate && routeCandidateId ? <CandidateDetailMissing candidateId={routeCandidateId} /> : null}
      {activeCandidate ? <CandidateDetailPanel row={activeCandidate} /> : null}
    </>
  )
}


type ResearchConfirm = ReturnType<typeof useOperatorDialog>['confirm']

type ResearchConfirmOptions = Parameters<ResearchConfirm>[0]

async function runConfirmedOperatorAction(
  canLive: boolean,
  confirm: ResearchConfirm,
  dialog: ResearchConfirmOptions,
  mutate: () => Promise<unknown>,
) {
  if (!canLive) return
  const confirmed = await confirm(dialog)
  if (!confirmed) return
  await mutate()
}

type ResearchPageRoute = Extract<DashboardRoute, { page: 'research' }>

function onGenerateBatchMutationSuccess(
  payload: GenerateBatchResponse,
  variables: { dry_run: boolean },
  setDryRunReady: (ready: boolean) => void,
  allowsLive: (payload?: GenerateBatchResponse) => boolean,
  invalidateFacility: () => void,
) {
  if (variables.dry_run) {
    setDryRunReady(allowsLive(payload))
    return
  }
  setDryRunReady(false)
  invalidateFacility()
}

function researchCycleLiveReady(dryRunReady: boolean, dryRunSignature: string, currentFacilitySignature: string): boolean {
  if (!dryRunReady) return false
  if (!currentFacilitySignature) return false
  return dryRunSignature === currentFacilitySignature
}

function researchCycleDryRunStale(dryRunReady: boolean, dryRunSignature: string, currentFacilitySignature: string): boolean {
  return dryRunReady && dryRunSignature !== currentFacilitySignature
}

function deriveResearchCycleDerivedState(input: Readonly<{
  facilityData?: ResearchFacilityResponse
  cycleDryRunReady: boolean
  cycleDryRunSignature: string
  cyclePending: boolean
}>) {
  const currentFacilitySignature = facilitySignature(input.facilityData)
  const canLiveCycle = researchCycleLiveReady(input.cycleDryRunReady, input.cycleDryRunSignature, currentFacilitySignature)
  const staleCycleDryRun = researchCycleDryRunStale(input.cycleDryRunReady, input.cycleDryRunSignature, currentFacilitySignature)
  const cycleDisabledReason = liveCycleDisabledReason(canLiveCycle, input.cycleDryRunReady, staleCycleDryRun, input.cyclePending)
  return { currentFacilitySignature, canLiveCycle, staleCycleDryRun, cycleDisabledReason }
}

function deriveResearchBatchDerivedState(input: Readonly<{
  batchDryRunReady: boolean
  providerBatchDryRunReady: boolean
  generateBatchPending: boolean
  providerBatchPending: boolean
  generateBatchData?: GenerateBatchResponse
  providerBatchData?: GenerateBatchResponse
}>) {
  const canLiveGenerateBatch = input.batchDryRunReady && generateBatchAllowsLive(input.generateBatchData)
  const canLiveProviderBatch = input.providerBatchDryRunReady && providerBatchAllowsLive(input.providerBatchData)
  const generateBatchDisabledReason = liveGenerateDisabledReason(canLiveGenerateBatch, input.batchDryRunReady, input.generateBatchPending, 'Generate candidate batch')
  const providerBatchDisabledReason = liveGenerateDisabledReason(canLiveProviderBatch, input.providerBatchDryRunReady, input.providerBatchPending, 'Generate provider batch')
  return { canLiveGenerateBatch, canLiveProviderBatch, generateBatchDisabledReason, providerBatchDisabledReason }
}

function deriveResearchSelectionDerivedState(input: Readonly<{
  routeCandidateId: string
  rows: Record<string, unknown>[]
  selectedCandidate: Record<string, unknown> | null
  promotionData?: PromotionResponse
}>) {
  const activeCandidate = input.selectedCandidate || input.rows.find((row) => displayText(row.candidate_id) === input.routeCandidateId) || null
  const selectedCandidateId = displayText(activeCandidate?.candidate_id, input.routeCandidateId)
  const selectedCandidateTitle = displayText(activeCandidate?.title, selectedCandidateId || 'No candidate selected')
  const candidateDryRunPassed = input.promotionData?.action === 'dry_run_promote_candidate' && input.promotionData?.candidate_id === selectedCandidateId
  return { activeCandidate, selectedCandidateId, selectedCandidateTitle, candidateDryRunPassed }
}

function deriveResearchPageDerivedState(input: Readonly<{
  routeCandidateId: string
  facilityData?: ResearchFacilityResponse
  selectedCandidate: Record<string, unknown> | null
  cycleDryRunReady: boolean
  cycleDryRunSignature: string
  batchDryRunReady: boolean
  providerBatchDryRunReady: boolean
  cyclePending: boolean
  generateBatchPending: boolean
  providerBatchPending: boolean
  generateBatchData?: GenerateBatchResponse
  providerBatchData?: GenerateBatchResponse
  promotionData?: PromotionResponse
}>) {
  const rows = input.facilityData?.rows || []
  const counts = input.facilityData?.counts || {}
  return {
    rows,
    counts,
    ...deriveResearchCycleDerivedState(input),
    ...deriveResearchBatchDerivedState(input),
    ...deriveResearchSelectionDerivedState({
      routeCandidateId: input.routeCandidateId,
      rows,
      selectedCandidate: input.selectedCandidate,
      promotionData: input.promotionData,
    }),
  }
}

function useResearchPageController(route?: ResearchPageRoute) {
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
      if (payload.action !== 'promote_candidate') return
      setSelectedCandidate(null)
      queryClient.invalidateQueries({ queryKey: ['research-facility'] }).catch(() => undefined)
    },
  })
  const invalidateFacility = () => {
    queryClient.invalidateQueries({ queryKey: ['research-facility'] }).catch(() => undefined)
  }
  const generateBatch = useMutation({
    mutationFn: (payload: { dry_run: boolean; max_candidates: number; requested_by: string }) => apiPost<GenerateBatchResponse>('/control/api/research/generate-batch', payload),
    onSuccess: (payload, variables) => {
      onGenerateBatchMutationSuccess(payload, variables, setBatchDryRunReady, generateBatchAllowsLive, invalidateFacility)
    },
  })
  const generateProviderBatch = useMutation({
    mutationFn: (payload: { dry_run: boolean; max_candidates: number; requested_by: string }) => apiPost<GenerateBatchResponse>('/control/api/research/generate-provider-batch', payload),
    onSuccess: (payload, variables) => {
      onGenerateBatchMutationSuccess(payload, variables, setProviderBatchDryRunReady, providerBatchAllowsLive, invalidateFacility)
    },
  })

  const routeCandidateId = route?.candidateId || ''
  const derived = deriveResearchPageDerivedState({
    routeCandidateId,
    facilityData: facility.data,
    selectedCandidate,
    cycleDryRunReady,
    cycleDryRunSignature,
    batchDryRunReady,
    providerBatchDryRunReady,
    cyclePending: cycle.isPending,
    generateBatchPending: generateBatch.isPending,
    providerBatchPending: generateProviderBatch.isPending,
    generateBatchData: generateBatch.data,
    providerBatchData: generateProviderBatch.data,
    promotionData: promotion.data,
  })

  async function runDryCycle() {
    const payload = await cycle.mutateAsync(dryRunCyclePayload)
    const ready = cycleDryRunAllowsLive(payload)
    setCycleDryRunReady(ready)
    setCycleDryRunSignature(ready ? derived.currentFacilitySignature : '')
  }

  async function runLiveCycle() {
    await runConfirmedOperatorAction(derived.canLiveCycle, confirm, {
      title: 'Run one bounded live cycle?',
      message: 'This can spend one provider request and promote candidates. V2 will not dispatch, wait for completion, write papers, or finalize publications from this action.',
      confirmLabel: 'Run bounded cycle',
      tone: 'warn',
    }, async () => {
      await cycle.mutateAsync(liveCyclePayload)
      setCycleDryRunReady(false)
      setCycleDryRunSignature('')
    })
  }

  async function runLiveGenerateBatch() {
    await runConfirmedOperatorAction(derived.canLiveGenerateBatch, confirm, {
      title: 'Generate research candidates now?',
      message: 'This writes new internal research candidates to the facility ledger. Inspect dry-run counts before proceeding.',
      confirmLabel: 'Generate candidates',
      tone: 'warn',
    }, () => generateBatch.mutateAsync({ dry_run: false, max_candidates: 3, requested_by: 'dashboard-v2' }))
  }

  async function runLiveProviderBatch() {
    await runConfirmedOperatorAction(derived.canLiveProviderBatch, confirm, {
      title: 'Generate provider-backed candidates now?',
      message: 'This spends provider inference budget and writes candidates to the facility ledger. Inspect dry-run budget checks first.',
      confirmLabel: 'Generate provider batch',
      tone: 'danger',
    }, () => generateProviderBatch.mutateAsync({ dry_run: false, max_candidates: 2, requested_by: 'dashboard-v2' }))
  }

  async function dryRunPromotion() {
    if (!derived.selectedCandidateId) return
    await promotion.mutateAsync({ candidate_id: derived.selectedCandidateId, dry_run: true, requested_by: 'dashboard-v2' })
  }

  async function promoteCandidate() {
    if (!derived.selectedCandidateId) return
    await runConfirmedOperatorAction(true, confirm, {
      title: 'Promote admitted candidate?',
      message: `Promote ${derived.selectedCandidateId} into queued idea/project rows? This writes queue ledgers only and will not dispatch work.`,
      confirmLabel: 'Promote candidate',
      tone: 'warn',
    }, () => promotion.mutateAsync({ candidate_id: derived.selectedCandidateId, dry_run: false, requested_by: 'dashboard-v2' }))
  }

  function refreshCandidates() {
    setSelectedCandidate(null)
    promotion.reset()
    setBatchDryRunReady(false)
    setProviderBatchDryRunReady(false)
    facility.refetch().catch(() => undefined)
  }

  return {
    dialog,
    facility,
    budget,
    cycle,
    promotion,
    generateBatch,
    generateProviderBatch,
    ...derived,
    routeCandidateId,
    setSelectedCandidate,
    runDryCycle,
    runLiveCycle,
    runLiveGenerateBatch,
    runLiveProviderBatch,
    dryRunPromotion,
    promoteCandidate,
    refreshCandidates,
  }
}

export function ResearchPage({ route }: Readonly<{ route?: ResearchPageRoute }>) {
  const page = useResearchPageController(route)

  return (
    <section className="page-stack">
      <PageHeader
        title="Candidate generation"
        subtitle="Promote admitted candidates and run bounded research cycles safely."
        dataSource="/control/api/v1/research-facility and autopilot endpoints"
        action={(
          <>
            <span>Last loaded {page.facility.data?.generated_at || 'unknown'}</span>
            <button className="secondary-button" type="button" disabled={page.facility.isFetching} onClick={page.refreshCandidates}>
              {page.facility.isFetching ? 'Refreshing…' : 'Refresh candidates'}
            </button>
          </>
        )}
        toolbar={(
          <div className="action-row">
            <button className="secondary-button" type="button" onClick={() => page.budget.mutate()} disabled={page.budget.isPending}>Check provider budget</button>
            <button className="secondary-button" type="button" onClick={() => { page.runDryCycle().catch(() => undefined) }} disabled={page.cycle.isPending}>Dry-run bounded cycle</button>
            <button className="primary-button" type="button" onClick={() => { page.runLiveCycle().catch(() => undefined) }} disabled={page.cycle.isPending || !page.canLiveCycle}>Run one bounded cycle</button>
          </div>
        )}
      />
      {page.cycleDisabledReason ? <p className="primary-action-disabled-reason">{page.cycleDisabledReason}</p> : null}

      <ResearchGenerationSection
        generateBatchPending={page.generateBatch.isPending}
        generateProviderBatchPending={page.generateProviderBatch.isPending}
        canLiveGenerateBatch={page.canLiveGenerateBatch}
        canLiveProviderBatch={page.canLiveProviderBatch}
        generateBatchDisabledReason={page.generateBatchDisabledReason}
        providerBatchDisabledReason={page.providerBatchDisabledReason}
        onDryRunGenerateBatch={() => { page.generateBatch.mutateAsync({ dry_run: true, max_candidates: 3, requested_by: 'dashboard-v2' }).catch(() => undefined) }}
        onLiveGenerateBatch={() => { page.runLiveGenerateBatch().catch(() => undefined) }}
        onDryRunProviderBatch={() => { page.generateProviderBatch.mutateAsync({ dry_run: true, max_candidates: 2, requested_by: 'dashboard-v2' }).catch(() => undefined) }}
        onLiveProviderBatch={() => { page.runLiveProviderBatch().catch(() => undefined) }}
      />

      <WorkbenchOperatorSummary summary={page.facility.data?.operator_summary} />

      <ResultCard result={page.budget.data} context={{ commandFamily: 'research' }} />
      <ResultCard result={page.cycle.data} context={{ commandFamily: 'research' }} stale={page.staleCycleDryRun} />
      <ResultCard result={page.generateBatch.data} context={{ commandFamily: 'research' }} />
      <ResultCard result={page.generateProviderBatch.data} context={{ commandFamily: 'research' }} />

      <ResearchSelectedCandidateSection
        selectedCandidateTitle={page.selectedCandidateTitle}
        selectedCandidateId={page.selectedCandidateId}
        promotionPending={page.promotion.isPending}
        candidateDryRunPassed={page.candidateDryRunPassed}
        onDryRunPromotion={() => { page.dryRunPromotion().catch(() => undefined) }}
        onPromoteCandidate={() => { page.promoteCandidate().catch(() => undefined) }}
        promotionResult={page.promotion.data}
      />

      {page.dialog}

      {page.facility.isLoading ? <LoadingStateCard label="research facility" /> : null}
      {page.facility.isError ? <InlineErrorStateCard prefix="Research data unavailable" message={String(page.facility.error.message)} /> : null}
      {!page.facility.isLoading && !page.facility.isError ? (
        <ResearchFacilityBody rows={page.rows} counts={page.counts} activeCandidate={page.activeCandidate} routeCandidateId={page.routeCandidateId} onSelectRow={page.setSelectedCandidate} />
      ) : null}
    </section>
  )
}
