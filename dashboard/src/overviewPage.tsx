import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { ActiveWorkList } from './activeWorkDisplay'
import { AutomationReadinessSummary } from './automationReadinessPanel'
import { apiGet } from './api/client'
import { parseAutomationReadiness, parseOverviewResponse, parseStatusResponse } from './api/readModelSchemas'
import { CommandHero } from './components/CommandHero'
import { MovementDiagnosis } from './components/MovementDiagnosis'
import { OverviewFreshness } from './components/OverviewFreshness'
import { PaperMiniStrip } from './components/PaperMiniStrip'
import { actionSignature, PrimaryAction, resolvePrimaryAction } from './components/PrimaryAction'
import { SafetyBar } from './components/SafetyBar'
import { WorkerLanes } from './components/WorkerLanes'
import { EntityLinkChips } from './components/ui'
import type { EntityLink } from './detailOperatorSummary'
import { displayText } from './displayText'
import { OperatorQueueSnapshot } from './operatorQueueSnapshot'
import { formatReadinessErrorMessage } from './readinessErrors'
import { dashboardV2Href } from './routes'
import type { AutomationReadiness, OverviewResponse, StatusResponse, TopAction } from './types'

export function OverviewPage() {
  const queryClient = useQueryClient()
  const [secondaryOpen, setSecondaryOpen] = useState(false)
  const [readinessRequested, setReadinessRequested] = useState(false)
  const overview = useQuery({ queryKey: ['overview'], queryFn: () => apiGet<unknown>('/control/api/v1/overview?active_limit=8&event_limit=6').then(parseOverviewResponse), refetchInterval: 30_000 })
  const status = useQuery({ queryKey: ['status'], queryFn: () => apiGet<unknown>('/control/api/status?refresh_worker=true').then(parseStatusResponse), refetchInterval: 30_000 })
  const readiness = useQuery({
    queryKey: ['automation-readiness'],
    queryFn: () => apiGet<unknown>('/control/api/v1/automation-readiness').then(parseAutomationReadiness),
    refetchInterval: 60_000,
    enabled: secondaryOpen || readinessRequested,
  })
  const refresh = () => {
    overview.refetch().catch(() => undefined)
    status.refetch().catch(() => undefined)
    queryClient
      .invalidateQueries({
        predicate: (query) =>
          query.queryKey[0] !== 'overview' && query.queryKey[0] !== 'status',
      })
      .catch(() => undefined)
  }

  if (overview.isLoading) {
    return <div className="rounded-3xl border border-zinc-800 bg-zinc-950 p-8 text-zinc-300">Loading command center…</div>
  }
  if (overview.isError || !overview.data) {
    return <div className="rounded-3xl border border-red-900 bg-red-950/40 p-8 text-red-100">Command state unavailable: {formatReadinessErrorMessage(overview.error)}</div>
  }

  return (
    <OverviewPageBody
      data={overview.data}
      statusData={status.data}
      statusLoading={status.isLoading}
      statusError={status.error}
      readinessData={readiness.data}
      readinessLoading={readiness.isLoading}
      readinessFetching={readiness.isFetching}
      readinessError={readiness.error}
      onReadinessRefetch={() => readiness.refetch()}
      readinessRequested={readinessRequested}
      isFetching={overview.isFetching || status.isFetching}
      onSecondaryOpenChange={setSecondaryOpen}
      onReadinessRequested={() => setReadinessRequested(true)}
      refresh={refresh}
    />
  )
}

function readinessCheckCardDetail(blockers: string[], readiness?: AutomationReadiness): string {
  if (blockers.length > 0) return blockers[0]
  if (readiness?.ok) return 'Long-haul checks currently pass.'
  return 'Run the readiness check before leaving automation unattended.'
}

function readinessCheckButtonLabel(hasReadiness: boolean): string {
  if (hasReadiness) return 'Refresh readiness'
  return 'Check readiness'
}

function readinessCheckCardLabel(
  error: unknown,
  readiness: AutomationReadiness | undefined,
  isLoading: boolean,
  requested: boolean,
): string {
  if (error) return `Unavailable: ${formatReadinessErrorMessage(error)}`
  if (readiness?.label) return readiness.label
  if (isLoading) return 'Checking…'
  if (requested) return 'No readiness result returned'
  return 'Not checked'
}

function eventDetailHref(eventId: string): string {
  if (eventId) return dashboardV2Href(`#event:${encodeURIComponent(eventId)}`)
  return dashboardV2Href('#events')
}

function triggerReadinessCheck(
  readinessRequested: boolean,
  onReadinessRequested: () => void,
  onReadinessRefetch: () => void,
): void {
  onReadinessRequested()
  if (readinessRequested) onReadinessRefetch()
}

function OverviewPageBody({
  data,
  statusData,
  statusLoading,
  statusError,
  readinessData,
  readinessLoading,
  readinessFetching,
  readinessError,
  onReadinessRefetch,
  readinessRequested,
  isFetching,
  onSecondaryOpenChange,
  onReadinessRequested,
  refresh,
}: Readonly<{
  data: OverviewResponse
  statusData?: StatusResponse
  statusLoading: boolean
  statusError: unknown
  readinessData?: AutomationReadiness
  readinessLoading: boolean
  readinessFetching: boolean
  readinessError: unknown
  onReadinessRefetch: () => void
  readinessRequested: boolean
  isFetching: boolean
  onSecondaryOpenChange: (open: boolean) => void
  onReadinessRequested: () => void
  refresh: () => void
}>) {
  const diagnosis = data.movement_diagnosis || { status: 'unknown', primary_reason: 'No movement diagnosis returned.', blockers: [] }
  const primaryAction = resolvePrimaryAction(data, readinessData)
  const recentEvents = data.recent_events || []
  const activeItems = data.active_items || []
  const operatorCounts = data.operator_counts || {}
  const operatorDetailCounts = data.operator_detail_counts || {}
  return (
    <div className="command-stack">
      <div className="command-topline">
        <OverviewFreshness generatedAt={data.generated_at} laneGeneratedAt={statusData?.generated_at} isFetching={isFetching} onRefresh={refresh} />
        <SafetyBar flags={data.flags} onRefresh={refresh} />
      </div>
      <CommandHero overview={data} diagnosis={diagnosis} readiness={readinessData} readinessRequested={readinessRequested} readinessLoading={readinessLoading || readinessFetching} requiresReadinessCheck />
      <ReadinessCheckCard
        readiness={readinessData}
        isLoading={readinessLoading || readinessFetching}
        error={readinessError}
        requested={readinessRequested}
        onCheck={() => triggerReadinessCheck(readinessRequested, onReadinessRequested, onReadinessRefetch)}
      />
      <MovementDiagnosis diagnosis={diagnosis} />
      <div className="command-grid">
        <WorkerLanes lanes={statusData?.worker_lanes || []} isLoading={statusLoading} error={statusError} onRefresh={refresh} />
        <div className="side-rail">
          <PrimaryAction
            action={primaryAction}
            onRefresh={refresh}
            onCheckReadiness={() => triggerReadinessCheck(readinessRequested, onReadinessRequested, onReadinessRefetch)}
          />
          <TopActions actions={data.top_actions} primaryAction={primaryAction} />
          <ResearchSignalQualityCard quality={data.research_signal_quality} />
          <ResearchYieldCard researchYield={data.research_yield} />
          <PaperMiniStrip pipeline={data.paper_pipeline} onRefresh={refresh} />
        </div>
      </div>
      <OverviewSecondaryFold
        recentEvents={recentEvents}
        operatorCounts={operatorCounts}
        operatorDetailCounts={operatorDetailCounts}
        activeItems={activeItems}
        readinessData={readinessData}
        readinessLoading={readinessLoading}
        readinessError={readinessError}
        onSecondaryOpenChange={onSecondaryOpenChange}
      />
    </div>
  )
}

function qualityDeltaLabel(value: unknown): string {
  const number = Number(value ?? 0)
  if (!Number.isFinite(number)) return '0'
  if (number > 0) return `+${number}`
  return String(number)
}

function qualityAgeLabel(value: unknown): string {
  const number = Number(value)
  if (!Number.isFinite(number)) return 'unknown'
  return `${number.toFixed(1)}h`
}

type ResearchSignalQuality = NonNullable<OverviewResponse['research_signal_quality']>
type MalformedProviderEvidence = NonNullable<ResearchSignalQuality['recent_malformed_provider_responses']>[number]
type UsefulFollowupEvidence = NonNullable<NonNullable<ResearchSignalQuality['useful_adjacent_followup_evidence']>['current']>[number]
type DecisionOutcomeCount = NonNullable<ResearchSignalQuality['decision_outcome_counts']>[number]
type CandidateCategoryCount = NonNullable<ResearchSignalQuality['top_candidate_categories']>[number]
type CandidateStatusSample = NonNullable<ResearchSignalQuality['candidate_status_samples']>[string][number]
type DecisionOutcomeSampleGroup = NonNullable<ResearchSignalQuality['decision_outcome_samples']>[number]
type DecisionOutcomeSample = NonNullable<DecisionOutcomeSampleGroup['samples']>[number]
type QualityFloor = NonNullable<ResearchSignalQuality['quality_floor']>
type QualityFloorCandidateSample = NonNullable<QualityFloor['candidate_samples']>[number]
type QualityFloorDecisionSample = NonNullable<QualityFloor['decision_samples']>[number]
type QualityWindowComparison = NonNullable<ResearchSignalQuality['window_comparison']>
type ProviderGenerationHealth = NonNullable<ResearchSignalQuality['provider_generation_health']>
type DecisionPosture = NonNullable<ResearchSignalQuality['decision_posture']>
type DecisionPostureSample = NonNullable<DecisionPosture['representative_useful_signals']>[number]
type PaperReadinessBlockers = NonNullable<DecisionPosture['paper_readiness_blockers']>
type PaperReadinessBlockerSample = NonNullable<PaperReadinessBlockers['samples']>[number]
type FollowupReadiness = NonNullable<ResearchSignalQuality['followup_readiness']>
type FollowupReadinessSample = NonNullable<FollowupReadiness['ready_followups']>[number]
type PrioritizedFollowup = NonNullable<FollowupReadiness['prioritized_followups']>[number]
type FollowupScopeAlignment = NonNullable<ResearchSignalQuality['followup_scope_alignment']>
type FollowupScopeCandidate = NonNullable<FollowupScopeAlignment['global_candidate']>
type ResearchYield = NonNullable<OverviewResponse['research_yield']>
type ResearchYieldTarget = NonNullable<NonNullable<ResearchYield['paper_recovery']>['target']>

type ResearchQualityLinkedSample = {
  project_id?: string
  project_name?: string
  run_id?: string
  paper_id?: string
  links?: Record<string, string>
}

function malformedProviderEvidenceLabel(row: MalformedProviderEvidence): string {
  const count = Number(row.malformed_provider_response_count ?? 0)
  const checkedAt = displayText(row.checked_at, 'unknown time')
  const runId = displayText(row.run_cycle_id || row.trace_id, '')
  return runId ? `${count} malformed responses at ${checkedAt} (${runId})` : `${count} malformed responses at ${checkedAt}`
}

function followupEvidenceTitle(prefix: string, row: UsefulFollowupEvidence): string {
  return `${prefix}: ${displayText(row.followup_title || row.title, 'Unnamed follow-up')}`
}

function followupEvidenceId(row: UsefulFollowupEvidence): string {
  return [
    displayText(row.project_id, ''),
    displayText(row.run_id, ''),
  ].filter(Boolean).join(' / ') || displayText(row.case_id, 'unknown case')
}

function portfolioLabel(value: string | undefined): string {
  return displayText(value, 'unknown').replaceAll('_', ' ')
}

function decisionOutcomeLabel(row: DecisionOutcomeCount): string {
  const decision = portfolioLabel(row.decision)
  const hypothesis = portfolioLabel(row.hypothesis_status)
  return `${decision} / ${hypothesis} ${String(row.count ?? 0)}`
}

function categoryCountLabel(row: CandidateCategoryCount): string {
  return `${portfolioLabel(row.category)} ${String(row.count ?? 0)}`
}

function windowCountEntries(value: Record<string, number> | undefined, limit = 2): [string, number][] {
  return Object.entries(value ?? {}).slice(0, limit)
}

function windowCountLabel([label, count]: [string, number]): string {
  return `${portfolioLabel(label)} ${String(count)}`
}

function researchYieldDroughtLabel(researchYield: ResearchYield): string {
  return researchYield.paper_drought?.warning ? 'paper drought active' : 'paper drought clear'
}

function researchYieldAgeLabel(researchYield: ResearchYield): string {
  const age = researchYield.latest_paper_age_days
  const ageLabel = typeof age === 'number' ? `${age}d ago` : 'unknown age'
  const threshold = Number(researchYield.paper_drought?.threshold_days ?? 0)
  return `latest paper ${ageLabel} / threshold ${threshold}d`
}

function researchYieldRecoveryLabel(researchYield: ResearchYield): string {
  const recovery = researchYield.paper_recovery
  const action = portfolioLabel(recovery?.next_action)
  const status = portfolioLabel(recovery?.status)
  const count = Number(recovery?.count ?? 0)
  return `recovery ${action} / ${status} / ${count}`
}

function researchYieldMaturityEntries(researchYield: ResearchYield): [string, number][] {
  return Object.entries(researchYield.maturity_counts ?? {})
    .filter(([, count]) => Number(count) > 0)
    .slice(0, 4)
}

function researchYieldTargetLabel(target: ResearchYieldTarget | null | undefined): string {
  if (!target) return ''
  return `target ${displayText(target.project_name || target.followup_title || target.title || target.project_id, 'Unnamed recovery target')}`
}

function researchYieldTargetLinks(target: ResearchYieldTarget | null | undefined): EntityLink[] {
  if (!target) return []
  const links: EntityLink[] = []
  if (target.project_id) {
    links.push({ kind: 'project', id: target.project_id, label: displayText(target.project_name, target.project_id) })
  }
  if (target.run_id) {
    links.push({ kind: 'run', id: target.run_id, label: target.run_id })
  }
  return links
}

function topActionTargetLabel(action: TopAction): string {
  const target = action.target
  if (!target) return ''
  const label = displayText(target.name || target.project_name || target.title || target.project_id, '')
  return label ? `target ${label}` : ''
}

function topActionTargetLinks(action: TopAction): EntityLink[] {
  const target = action.target
  if (!target) return []
  const links: EntityLink[] = []
  const projectId = displayText(target.project_id, '')
  const runId = displayText(target.current_run_id || target.run_id, '')
  if (projectId) {
    links.push({ kind: 'project', id: projectId, label: displayText(target.name || target.project_name, projectId) })
  }
  if (runId) {
    links.push({ kind: 'run', id: runId, label: runId })
  }
  return links
}

function topActionMetaLabel(action: TopAction): string {
  const parts: string[] = []
  if (typeof action.priority === 'number') parts.push(`priority ${action.priority}`)
  if (typeof action.count === 'number') parts.push(`count ${action.count}`)
  return parts.join(' / ')
}

function windowAdmittedRateLabel(windowComparison: QualityWindowComparison): string {
  const current = String(windowComparison.current?.admitted_rate ?? 0)
  const previous = String(windowComparison.previous?.admitted_rate ?? 0)
  return `admitted rate ${current} now / ${previous} previous`
}

function qualityFloorPostureLabel(floor: QualityFloor): string {
  const posture = portfolioLabel(floor.posture)
  const threshold = Number(floor.threshold ?? 0)
  return `floor ${posture} at ${threshold.toFixed(2)}`
}

function qualityFloorCountLabel(floor: QualityFloor): string {
  const below = Number(floor.below_floor_count ?? 0)
  const checked = Number(floor.candidates_checked ?? 0) + Number(floor.decisions_checked ?? 0)
  return `below floor ${below} / ${checked} checked`
}

function qualityFloorCandidateTitle(row: QualityFloorCandidateSample): string {
  const score = Number(row.score ?? 0).toFixed(2)
  return `candidate ${displayText(row.title || row.candidate_id, 'unnamed candidate')} ${score}`
}

function qualityFloorDecisionTitle(row: QualityFloorDecisionSample): string {
  const score = Number(row.score ?? 0).toFixed(2)
  return `decision ${displayText(row.project_name || row.project_id || row.run_id, 'unnamed decision')} ${score}`
}

function providerCleanStreakLabel(health: ProviderGenerationHealth): string {
  const count = Number(health.consecutive_clean_ticks ?? 0)
  const tickLabel = count === 1 ? 'tick' : 'ticks'
  return `${count} clean ${tickLabel} since last malformed`
}

function providerWarningPostureLabel(health: ProviderGenerationHealth): string {
  return `provider warning ${portfolioLabel(health.malformed_history_status || 'unknown')}`
}

function providerLatestTickLabel(health: ProviderGenerationHealth): string {
  const latest = health.latest_tick
  const model = displayText(latest?.provider_model, 'unknown model')
  const status = displayText(latest?.status, 'unknown')
  const checkedAt = displayText(latest?.checked_at, 'unknown time')
  return `latest ${model} ${status} at ${checkedAt}`
}

function providerYieldLabel(health: ProviderGenerationHealth): string {
  const latest = health.latest_tick
  const status = portfolioLabel(health.latest_yield_status || 'unknown')
  const generated = Number(latest?.generated_count ?? 0)
  const promoted = Number(latest?.promoted_count ?? 0)
  const initialPromotable = Number(latest?.initial_promotable_count ?? 0)
  return `${status}: ${generated} generated / ${promoted} promoted / ${initialPromotable} initially promotable`
}

function providerYieldStreakLabel(health: ProviderGenerationHealth): string {
  const zeroGenerated = Number(health.consecutive_zero_generated_ticks ?? 0)
  const zeroPromoted = Number(health.consecutive_zero_promoted_ticks ?? 0)
  return `${zeroGenerated} zero-generation ticks / ${zeroPromoted} zero-promotion ticks`
}

function providerLastMalformedLabel(health: ProviderGenerationHealth): string {
  const last = health.last_malformed_tick
  const model = displayText(last?.provider_model, 'unknown model')
  const count = Number(last?.malformed_provider_response_count ?? 0)
  const checkedAt = displayText(last?.checked_at, 'unknown time')
  return `last malformed ${model} ${count} at ${checkedAt}`
}

function decisionPostureUsefulLabel(posture: DecisionPosture): string {
  const useful = Number(posture.useful_signal_count ?? 0)
  const total = Number(posture.decisions_checked ?? 0)
  return `useful signals ${useful} / ${total} decisions`
}

function decisionPostureReadyLabel(posture: DecisionPosture): string {
  return `publication-ready ${Number(posture.bounded_paper_ready_count ?? 0)}`
}

function decisionPostureFollowupLabel(posture: DecisionPosture): string {
  return `follow-up recommended ${Number(posture.followup_recommended_count ?? 0)}`
}

function decisionPostureLabel(posture: DecisionPosture): string {
  return `posture ${portfolioLabel(posture.publication_posture)}`
}

function decisionPostureSampleTitle(row: DecisionPostureSample): string {
  return displayText(row.project_name || row.followup_title || row.project_id, 'Unnamed useful signal')
}

function paperBlockerReasonLabel(reason: string): string {
  return reason.replaceAll('_', ' ')
}

function paperBlockerCountLabel(entry: [string, number]): string {
  return `${paperBlockerReasonLabel(entry[0])} ${entry[1]}`
}

function paperBlockerSampleTitle(row: PaperReadinessBlockerSample): string {
  return `sample ${displayText(row.project_name || row.followup_title || row.project_id, 'Unnamed paper blocker')}`
}

function paperBlockerSampleReasons(row: PaperReadinessBlockerSample): string {
  return (row.blocker_reasons ?? [])
    .slice(0, 3)
    .map(paperBlockerReasonLabel)
    .join(' / ')
}

function followupReadinessReadyLabel(readiness: FollowupReadiness): string {
  const ready = Number(readiness.bounded_ready_count ?? 0)
  const recommended = Number(readiness.recommended_count ?? 0)
  return `ready follow-ups ${ready} / ${recommended} recommended`
}

function followupReadinessMissingStopLabel(readiness: FollowupReadiness): string {
  return `missing stop ${Number(readiness.missing_stop_condition_count ?? 0)}`
}

function followupReadinessTypeEntries(readiness: FollowupReadiness): [string, number][] {
  return Object.entries(readiness.followup_type_counts ?? {}).slice(0, 3)
}

function followupReadinessSampleTitle(row: FollowupReadinessSample): string {
  return displayText(row.followup_title || row.project_name || row.project_id, 'Unnamed follow-up')
}

function followupScopePostureLabel(alignment: FollowupScopeAlignment): string {
  return alignment.same_project ? 'same follow-up scope' : 'different follow-up scopes'
}

function followupScopeCandidateLabel(scope: string, row: FollowupScopeCandidate | undefined): string {
  if (!row) return `${scope}: none`
  return `${scope}: ${displayText(row.project_name || row.followup_title || row.project_id, 'unnamed follow-up')}`
}

function prioritizedFollowupReasons(row: PrioritizedFollowup): string {
  return (row.priority_reasons ?? [])
    .slice(0, 3)
    .map((reason) => displayText(reason, '').replaceAll('_', ' '))
    .filter(Boolean)
    .join(' / ') || [
      displayText(row.hypothesis_status, ''),
      displayText(row.evidence_strength, ''),
      displayText(row.followup_type, ''),
    ].filter(Boolean).join(' / ') || 'no priority reasons returned'
}

function candidateStatusSampleTitle(status: string, row: CandidateStatusSample): string {
  return `${portfolioLabel(status)}: ${displayText(row.title, 'Unnamed candidate')}`
}

function candidateStatusSampleId(row: CandidateStatusSample): string {
  return displayText(row.candidate_id, 'unknown candidate')
}

function decisionOutcomeSampleTitle(group: DecisionOutcomeSampleGroup, row: DecisionOutcomeSample): string {
  return `${portfolioLabel(group.decision)} / ${portfolioLabel(group.hypothesis_status)}: ${displayText(row.project_name || row.followup_title, 'Unnamed project')}`
}

function decisionOutcomeSampleId(row: DecisionOutcomeSample): string {
  return [
    displayText(row.project_id, ''),
    displayText(row.run_id, ''),
  ].filter(Boolean).join(' / ') || displayText(row.followup_title, 'unknown run')
}

function qualityStatusClass(status: string | undefined, ok: boolean | undefined): string {
  if (status === 'blocked' || ok === false) return 'quality-pill quality-pill--bad'
  if (status === 'warnings') return 'quality-pill quality-pill--warn'
  return 'quality-pill quality-pill--good'
}

function researchQualitySampleLinks(row: ResearchQualityLinkedSample | undefined): EntityLink[] {
  if (!row?.links) return []
  const links: EntityLink[] = []
  if (row.links.project && row.project_id) {
    links.push({ kind: 'project', id: row.project_id, label: displayText(row.project_name, row.project_id) })
  }
  if (row.links.run && row.run_id) {
    links.push({ kind: 'run', id: row.run_id, label: row.run_id })
  }
  if (row.links.paper && row.paper_id) {
    links.push({ kind: 'paper', id: row.paper_id, label: row.paper_id })
  }
  return links
}

function activeSignalReason(quality: ResearchSignalQuality): NonNullable<ResearchSignalQuality['signal_reasons']>[number] | undefined {
  return quality.signal_reasons?.find((reason) => reason.active || reason.status === 'active') ?? quality.signal_reasons?.[0]
}

function ResearchQualitySignalVerdict({ quality }: Readonly<{ quality: ResearchSignalQuality }>) {
  const signalReason = activeSignalReason(quality)
  if (!quality.signal_label && !signalReason) return null
  return (
    <div className="quality-snapshot-detail">
      <h4>Signal verdict</h4>
      <p>{displayText(quality.signal_label || quality.signal_verdict, 'No signal verdict returned.')}</p>
      {signalReason ? <p>{displayText(signalReason.message || signalReason.code, 'No signal reason returned.')}</p> : null}
      <p>{displayText(quality.signal_operator_action || signalReason?.operator_action, 'Inspect Research Quality before resuming unattended automation.')}</p>
    </div>
  )
}

type ResearchOutputReadinessContract = NonNullable<ResearchSignalQuality['research_output_readiness']>
type ResearchOutputReadinessInvariant = NonNullable<ResearchOutputReadinessContract['failed_invariants']>[number]
type ResearchOutputReadinessArtifact = NonNullable<ResearchOutputReadinessContract['affected_artifacts']>[number]

function readinessInvariantLabel(invariant: ResearchOutputReadinessInvariant): string {
  const label = displayText(invariant.label || invariant.code, 'Unknown readiness invariant')
  const current = displayText(invariant.current, 'unknown')
  const required = displayText(invariant.required, 'unknown')
  const previous = invariant.previous === undefined ? '' : ` / previous ${displayText(invariant.previous, 'unknown')}`
  const delta = invariant.delta === undefined ? '' : ` / delta ${displayText(invariant.delta, 'unknown')}`
  return `${label}: ${current} / required ${required}${previous}${delta}`
}

function readinessArtifactLabel(artifact: ResearchOutputReadinessArtifact): string {
  return `Affected: ${displayText(artifact.title || artifact.project_name || artifact.run_id || artifact.project_id || artifact.case_id, 'unknown artifact')}`
}

function ResearchOutputReadiness({ readiness }: Readonly<{ readiness: ResearchSignalQuality['research_output_readiness'] }>) {
  if (!readiness) return null
  const failed = readiness.failed_invariants ?? []
  const affected = readiness.affected_artifacts?.[0]
  const nextAction = readiness.next_bounded_action
  const blocker = readiness.blocked_by || readiness.hold_state
    ? `blocked by ${portfolioLabel(displayText(readiness.blocked_by, 'none'))} / ${portfolioLabel(displayText(readiness.hold_state, 'none'))}`
    : ''
  return (
    <div className="quality-snapshot-detail">
      <h4>Output readiness</h4>
      <p>{displayText(readiness.label || readiness.state, 'No output-readiness contract returned.')}</p>
      {blocker ? <p>{blocker}</p> : null}
      {failed.map((invariant) => (
        <p key={invariant.code ?? invariant.label}>{readinessInvariantLabel(invariant)}</p>
      ))}
      {nextAction?.title ? <p>{`Next bounded action: ${nextAction.title}`}</p> : null}
      {affected ? <p>{readinessArtifactLabel(affected)}</p> : null}
      <p>{displayText(readiness.operator_action, 'Inspect Research Quality output readiness before resuming automation.')}</p>
    </div>
  )
}

function ResearchQualityProviderEvidence({ quality }: Readonly<{ quality: ResearchSignalQuality }>) {
  const providerEvidence = quality.recent_malformed_provider_responses?.[0]
  const postPromptWarning = quality.post_prompt_warning_details?.[0]
  if (!providerEvidence && !postPromptWarning) return null
  return (
    <div className="quality-snapshot-detail">
      <h4>Provider warning evidence</h4>
      {providerEvidence ? (
        <>
          <p>{displayText(providerEvidence.provider_model, 'Unknown provider model')}</p>
          <p>{malformedProviderEvidenceLabel(providerEvidence)}</p>
          <p>{displayText(providerEvidence.operator_action, 'Inspect provider-generation output before trusting new idea volume.')}</p>
        </>
      ) : <p>{displayText(postPromptWarning?.message || postPromptWarning?.code, 'No provider warning detail returned.')}</p>}
    </div>
  )
}

function ResearchQualityProviderRecovery({ providerHealth }: Readonly<{ providerHealth: ResearchSignalQuality['provider_generation_health'] }>) {
  if (!providerHealth) return null
  return (
    <div className="quality-snapshot-detail">
      <h4>Provider recovery</h4>
      <p>{providerWarningPostureLabel(providerHealth)}</p>
      <p>{providerCleanStreakLabel(providerHealth)}</p>
      <p>{providerLatestTickLabel(providerHealth)}</p>
      <h4>Provider yield</h4>
      <p>{providerYieldLabel(providerHealth)}</p>
      <p>{providerYieldStreakLabel(providerHealth)}</p>
      <p>{displayText(providerHealth.yield_operator_action, 'Inspect provider-generation yield before trusting idea volume.')}</p>
      <p>{providerLastMalformedLabel(providerHealth)}</p>
      <p>{displayText(providerHealth.operator_action, 'Inspect provider-generation history before trusting new idea volume.')}</p>
    </div>
  )
}

function ResearchQualityFollowupTrend({ quality }: Readonly<{ quality: ResearchSignalQuality }>) {
  const currentFollowupEvidence = quality.useful_adjacent_followup_evidence?.current?.[0]
  const previousFollowupEvidence = quality.useful_adjacent_followup_evidence?.previous?.[0]
  if (!currentFollowupEvidence && !previousFollowupEvidence) return null
  return (
    <div className="quality-snapshot-detail">
      <h4>Follow-up trend evidence</h4>
      {currentFollowupEvidence ? (
        <>
          <p>{followupEvidenceTitle('Current', currentFollowupEvidence)}</p>
          <p>{followupEvidenceId(currentFollowupEvidence)}</p>
        </>
      ) : null}
      {previousFollowupEvidence ? (
        <>
          <p>{followupEvidenceTitle('Previous', previousFollowupEvidence)}</p>
          <p>{followupEvidenceId(previousFollowupEvidence)}</p>
        </>
      ) : null}
    </div>
  )
}

function ResearchQualityPortfolioComposition({ quality }: Readonly<{ quality: ResearchSignalQuality }>) {
  const candidateStatusCounts = Object.entries(quality.candidate_status_counts ?? {}).slice(0, 3)
  const decisionOutcomeCounts = quality.decision_outcome_counts?.slice(0, 2) ?? []
  const topCandidateCategories = quality.top_candidate_categories?.slice(0, 2) ?? []
  if (candidateStatusCounts.length === 0 && decisionOutcomeCounts.length === 0 && topCandidateCategories.length === 0) return null
  return (
    <div className="quality-snapshot-detail">
      <h4>Portfolio composition</h4>
      {candidateStatusCounts.map(([status, count]) => (
        <p key={status}>{portfolioLabel(status)} {String(count)}</p>
      ))}
      {decisionOutcomeCounts.map((row) => (
        <p key={`${row.decision ?? 'unknown'}-${row.hypothesis_status ?? 'unknown'}`}>{decisionOutcomeLabel(row)}</p>
      ))}
      {topCandidateCategories.map((row) => (
        <p key={row.category ?? 'unknown'}>{categoryCountLabel(row)}</p>
      ))}
    </div>
  )
}

function ResearchQualityPortfolioEvidence({ quality }: Readonly<{ quality: ResearchSignalQuality }>) {
  const candidateStatusSamples = Object.entries(quality.candidate_status_samples ?? {})
    .flatMap(([status, rows]) => rows.slice(0, 1).map((row) => ({ status, row })))
    .slice(0, 3)
  const decisionOutcomeSamples = (quality.decision_outcome_samples ?? [])
    .flatMap((group) => (group.samples ?? []).slice(0, 1).map((row) => ({ group, row })))
    .slice(0, 2)
  if (candidateStatusSamples.length === 0 && decisionOutcomeSamples.length === 0) return null
  return (
    <div className="quality-snapshot-detail">
      <h4>Portfolio evidence</h4>
      {candidateStatusSamples.map(({ status, row }) => (
        <div key={`${status}-${row.candidate_id ?? row.title ?? 'candidate'}`}>
          <p>{candidateStatusSampleTitle(status, row)}</p>
          <p>{candidateStatusSampleId(row)}</p>
        </div>
      ))}
      {decisionOutcomeSamples.map(({ group, row }) => (
        <div key={`${group.decision ?? 'unknown'}-${group.hypothesis_status ?? 'unknown'}-${row.run_id ?? row.project_id ?? row.project_name ?? 'run'}`}>
          <p>{decisionOutcomeSampleTitle(group, row)}</p>
          <p>{decisionOutcomeSampleId(row)}</p>
          <EntityLinkChips links={researchQualitySampleLinks(row)} />
        </div>
      ))}
    </div>
  )
}

function ResearchQualityFloor({ qualityFloor }: Readonly<{ qualityFloor: ResearchSignalQuality['quality_floor'] }>) {
  if (!qualityFloor) return null
  const qualityFloorCandidate = qualityFloor.candidate_samples?.[0]
  const qualityFloorDecision = qualityFloor.decision_samples?.[0]
  return (
    <div className="quality-snapshot-detail">
      <h4>Quality floor</h4>
      <p>{qualityFloorPostureLabel(qualityFloor)}</p>
      <p>{qualityFloorCountLabel(qualityFloor)}</p>
      {qualityFloorCandidate ? <p>{qualityFloorCandidateTitle(qualityFloorCandidate)}</p> : null}
      {qualityFloorDecision ? <p>{qualityFloorDecisionTitle(qualityFloorDecision)}</p> : null}
      <p>{displayText(qualityFloor.operator_action, 'Inspect quality-floor posture before widening automation.')}</p>
    </div>
  )
}

function ResearchQualityDecisionPosture({ decisionPosture }: Readonly<{ decisionPosture: ResearchSignalQuality['decision_posture'] }>) {
  if (!decisionPosture) return null
  const decisionPostureSample = decisionPosture.representative_useful_signals?.[0]
  return (
    <div className="quality-snapshot-detail">
      <h4>Decision posture</h4>
      <p>{decisionPostureUsefulLabel(decisionPosture)}</p>
      <p>{decisionPostureReadyLabel(decisionPosture)}</p>
      <p>{decisionPostureFollowupLabel(decisionPosture)}</p>
      <p>{decisionPostureLabel(decisionPosture)}</p>
      {decisionPostureSample ? (
        <>
          <p>{decisionPostureSampleTitle(decisionPostureSample)}</p>
          <p>{displayText(decisionPostureSample.recommended_next_action, 'No next action returned for representative useful signal.')}</p>
          <EntityLinkChips links={researchQualitySampleLinks(decisionPostureSample)} />
        </>
      ) : null}
      <p>{displayText(decisionPosture.operator_action, 'Inspect decision posture before treating throughput as publication output.')}</p>
    </div>
  )
}

function ResearchQualityPaperBlockers({ paperReadinessBlockers }: Readonly<{ paperReadinessBlockers: PaperReadinessBlockers | undefined }>) {
  if (!paperReadinessBlockers) return null
  const paperBlockerSample = paperReadinessBlockers.samples?.[0]
  const paperBlockerCounts = Object.entries(paperReadinessBlockers.blocker_counts ?? {}).slice(0, 4)
  return (
    <div className="quality-snapshot-detail">
      <h4>Paper blockers</h4>
      <p>paper-ready {Number(paperReadinessBlockers.paper_ready_count ?? 0)} / {Number(paperReadinessBlockers.decisions_checked ?? 0)} decisions</p>
      {paperBlockerCounts.map((entry) => (
        <p key={`paper-blocker-${entry[0]}`}>{paperBlockerCountLabel(entry)}</p>
      ))}
      {paperBlockerSample ? (
        <>
          <p>{paperBlockerSampleTitle(paperBlockerSample)}</p>
          <p>{paperBlockerSampleReasons(paperBlockerSample)}</p>
          <EntityLinkChips links={researchQualitySampleLinks(paperBlockerSample)} />
        </>
      ) : null}
      <p>{displayText(paperReadinessBlockers.operator_action, 'Inspect paper-readiness blockers before treating useful signals as publication output.')}</p>
    </div>
  )
}

function ResearchQualityFollowupReadiness({ followupReadiness }: Readonly<{ followupReadiness: ResearchSignalQuality['followup_readiness'] }>) {
  if (!followupReadiness) return null
  const readyFollowup = followupReadiness.ready_followups?.[0]
  const prioritizedFollowup = followupReadiness.prioritized_followups?.[0]
  const underspecifiedFollowup = followupReadiness.underspecified_followups?.[0]
  const followupTypeCounts = followupReadinessTypeEntries(followupReadiness)
  return (
    <div className="quality-snapshot-detail">
      <h4>Follow-up readiness</h4>
      <p>{followupReadinessReadyLabel(followupReadiness)}</p>
      <p>underspecified {Number(followupReadiness.underspecified_count ?? 0)}</p>
      <p>{followupReadinessMissingStopLabel(followupReadiness)}</p>
      {followupTypeCounts.map((entry) => (
        <p key={`followup-type-${entry[0]}`}>{windowCountLabel(entry)}</p>
      ))}
      {readyFollowup ? (
        <>
          <p>{followupReadinessSampleTitle(readyFollowup)}</p>
          <p>{displayText(readyFollowup.followup_success_threshold, 'No success threshold returned for ready follow-up.')}</p>
          <EntityLinkChips links={researchQualitySampleLinks(readyFollowup)} />
        </>
      ) : null}
      {prioritizedFollowup ? (
        <>
          <p>Prioritized follow-up</p>
          <p>{followupReadinessSampleTitle(prioritizedFollowup)}</p>
          <p>priority {Number(prioritizedFollowup.priority_score ?? 0)}</p>
          <p>{prioritizedFollowupReasons(prioritizedFollowup)}</p>
          <p>{displayText(prioritizedFollowup.recommended_next_action, 'No next action returned for prioritized follow-up.')}</p>
          <EntityLinkChips links={researchQualitySampleLinks(prioritizedFollowup)} />
        </>
      ) : null}
      {underspecifiedFollowup ? (
        <>
          <p>{followupReadinessSampleTitle(underspecifiedFollowup)}</p>
          <EntityLinkChips links={researchQualitySampleLinks(underspecifiedFollowup)} />
        </>
      ) : null}
      <p>{displayText(followupReadiness.operator_action, 'Inspect follow-up readiness before queueing more work.')}</p>
    </div>
  )
}

function ResearchQualityFollowupScope({ followupScopeAlignment }: Readonly<{ followupScopeAlignment: ResearchSignalQuality['followup_scope_alignment'] }>) {
  if (!followupScopeAlignment) return null
  return (
    <div className="quality-snapshot-detail">
      <h4>Follow-up scope</h4>
      <p>global ready {Number(followupScopeAlignment.global_ready_count ?? 0)}</p>
      <p>{followupScopeCandidateLabel('global', followupScopeAlignment.global_candidate)}</p>
      <p>{followupScopeCandidateLabel('quality window', followupScopeAlignment.quality_window_candidate)}</p>
      <p>{followupScopePostureLabel(followupScopeAlignment)}</p>
      <p>{displayText(followupScopeAlignment.operator_action, 'Compare global ranked follow-up selection against Research Quality window samples.')}</p>
    </div>
  )
}

function ResearchQualityWindowComparison({ windowComparison }: Readonly<{ windowComparison: ResearchSignalQuality['window_comparison'] }>) {
  const windowGenerationModes = windowCountEntries(windowComparison?.current?.generation_mode_counts)
  const windowCategories = windowCountEntries(windowComparison?.current?.category_counts)
  const hasWindowComparison = Boolean(
    windowComparison && (
      windowGenerationModes.length > 0
      || windowCategories.length > 0
      || typeof windowComparison.current?.admitted_rate === 'number'
      || typeof windowComparison.previous?.admitted_rate === 'number'
    ),
  )
  if (!hasWindowComparison || !windowComparison) return null
  return (
    <div className="quality-snapshot-detail">
      <h4>Window comparison</h4>
      <p>{windowAdmittedRateLabel(windowComparison)}</p>
      {windowGenerationModes.map((entry) => (
        <p key={`generation-${entry[0]}`}>{windowCountLabel(entry)}</p>
      ))}
      {windowCategories.map((entry) => (
        <p key={`category-${entry[0]}`}>{windowCountLabel(entry)}</p>
      ))}
      <p>high similarity pairs {String(windowComparison.current?.high_similarity_pair_count ?? 0)}</p>
    </div>
  )
}

function ResearchQualityReportFreshness({ freshnessSummary }: Readonly<{ freshnessSummary?: string | null }>) {
  if (!freshnessSummary) return null
  return (
    <div className="quality-snapshot-detail">
      <h4>Report freshness</h4>
      <p>{freshnessSummary}</p>
    </div>
  )
}

function ResearchQualityRefreshSource({ quality }: Readonly<{ quality: ResearchSignalQuality }>) {
  if (!quality.refresh_reason && !quality.refresh_operator_action) return null
  return (
    <div className="quality-snapshot-detail">
      <h4>Refresh source</h4>
      <p>{displayText(quality.refresh_reason || quality.refresh_action, 'No refresh status returned.')}</p>
      <p>{displayText(quality.refresh_operator_action, 'Inspect the Research Quality refresh sidecar before resuming unattended automation.')}</p>
    </div>
  )
}

function ResearchQualityAffectedArtifact({ affected }: Readonly<{ affected: NonNullable<ResearchSignalQuality['top_problem_details']>[number] | undefined }>) {
  if (!affected) return null
  return (
    <div className="quality-snapshot-detail">
      <h4>Affected artifact</h4>
      <p>{displayText(affected.title || affected.project_id || affected.candidate_id, 'Unnamed artifact')}</p>
      <p>{displayText(affected.problem, 'No quality problem returned.')}</p>
      <p>{displayText(affected.operator_action, 'Inspect the affected artifact before resuming unattended automation.')}</p>
    </div>
  )
}

function ResearchQualityRecommendedAction({ recommendation }: Readonly<{ recommendation?: string }>) {
  if (!recommendation) return null
  return (
    <div className="quality-snapshot-detail">
      <h4>Recommended action</h4>
      <p>{recommendation}</p>
    </div>
  )
}

function TopActions({
  actions,
  primaryAction,
}: Readonly<{
  actions: TopAction[] | undefined
  primaryAction: TopAction | undefined
}>) {
  const primarySignature = primaryAction ? actionSignature(primaryAction) : ''
  const visibleActions = (actions || [])
    .filter((action) => actionSignature(action) !== primarySignature)
    .slice(0, 3)
  if (visibleActions.length === 0) return null
  return (
    <section className="quality-snapshot" aria-label="Top actions">
      <div>
        <h3>Top actions</h3>
        <span className="quality-pill quality-pill--info">{visibleActions.length}</span>
      </div>
      {visibleActions.map((action, index) => {
        const targetLabel = topActionTargetLabel(action)
        return (
          <div className="quality-snapshot-detail" key={`${actionSignature(action)}:${index}`}>
            <h4>{action.title}</h4>
            {topActionMetaLabel(action) ? <p>{topActionMetaLabel(action)}</p> : null}
            <p>{displayText(action.summary, 'No action summary returned.')}</p>
            {targetLabel ? <p>{targetLabel}</p> : null}
            <EntityLinkChips links={topActionTargetLinks(action)} />
            {action.action_hash ? <a href={dashboardV2Href(action.action_hash)}>{action.action_label || 'Open'}</a> : null}
          </div>
        )
      })}
    </section>
  )
}

function ResearchYieldCard({ researchYield }: Readonly<{ researchYield: OverviewResponse['research_yield'] }>) {
  if (!researchYield) return null
  const maturityEntries = researchYieldMaturityEntries(researchYield)
  const target = researchYield.paper_recovery?.target
  const targetLabel = researchYieldTargetLabel(target)
  return (
    <section className="quality-snapshot" aria-label="Research yield">
      <div>
        <h3>Research yield</h3>
        <span className={researchYield.paper_drought?.warning ? 'quality-pill quality-pill--warn' : 'quality-pill quality-pill--good'}>
          {researchYieldDroughtLabel(researchYield)}
        </span>
      </div>
      <p>{researchYieldAgeLabel(researchYield)}</p>
      <div className="quality-snapshot-detail">
        <h4>Paper recovery</h4>
        <p>{researchYieldRecoveryLabel(researchYield)}</p>
        <p>{displayText(researchYield.paper_recovery?.reason, 'No deterministic paper-recovery action returned.')}</p>
        {targetLabel ? <p>{targetLabel}</p> : null}
        <EntityLinkChips links={researchYieldTargetLinks(target)} />
      </div>
      {maturityEntries.length > 0 ? (
        <div className="quality-snapshot-detail">
          <h4>Maturity states</h4>
          {maturityEntries.map((entry) => (
            <p key={`research-yield-maturity-${entry[0]}`}>{windowCountLabel(entry)}</p>
          ))}
        </div>
      ) : null}
      {researchYield.dominant_missing_evidence_reason ? (
        <p>dominant gap {researchYield.dominant_missing_evidence_reason}</p>
      ) : null}
    </section>
  )
}

function ResearchSignalQualityCard({ quality }: Readonly<{ quality: OverviewResponse['research_signal_quality'] }>) {
  if (!quality) {
    return (
      <section className="quality-snapshot" aria-label="Research signal quality">
        <div>
          <h3>Research signal quality</h3>
          <span className="quality-pill quality-pill--warn">unavailable</span>
        </div>
        <p>No quality snapshot returned in the bounded overview.</p>
      </section>
    )
  }
  const affected = quality.top_problem_details?.[0]
  const recommendation = quality.operator_recommendations?.[0] || quality.recommendations?.[0]
  const decisionPosture = quality.decision_posture
  return (
    <section className="quality-snapshot" aria-label="Research signal quality">
      <div>
        <h3>Research signal quality</h3>
        <span className={qualityStatusClass(quality.status, quality.ok)}>{displayText(quality.status, 'unknown')}</span>
      </div>
      <dl>
        <div>
          <dt>Weak evidence</dt>
          <dd>{String(quality.weak_evidence_count ?? 0)}</dd>
        </div>
        <div>
          <dt>Malformed provider</dt>
          <dd>{String(quality.malformed_provider_response_count ?? 0)}</dd>
        </div>
        <div>
          <dt>Useful trend</dt>
          <dd>{qualityDeltaLabel(quality.useful_adjacent_followup_delta)}</dd>
        </div>
        <div>
          <dt>Report age</dt>
          <dd>{qualityAgeLabel(quality.report_age_hours)}</dd>
        </div>
      </dl>
      <p>{displayText(quality.operator_summary, 'No research-quality summary returned.')}</p>
      <ResearchOutputReadiness readiness={quality.research_output_readiness} />
      <ResearchQualitySignalVerdict quality={quality} />
      <ResearchQualityProviderEvidence quality={quality} />
      <ResearchQualityProviderRecovery providerHealth={quality.provider_generation_health} />
      <ResearchQualityFollowupTrend quality={quality} />
      <ResearchQualityPortfolioComposition quality={quality} />
      <ResearchQualityPortfolioEvidence quality={quality} />
      <ResearchQualityFloor qualityFloor={quality.quality_floor} />
      <ResearchQualityDecisionPosture decisionPosture={decisionPosture} />
      <ResearchQualityPaperBlockers paperReadinessBlockers={decisionPosture?.paper_readiness_blockers} />
      <ResearchQualityFollowupReadiness followupReadiness={quality.followup_readiness} />
      <ResearchQualityFollowupScope followupScopeAlignment={quality.followup_scope_alignment} />
      <ResearchQualityWindowComparison windowComparison={quality.window_comparison} />
      <ResearchQualityReportFreshness freshnessSummary={quality.freshness_summary} />
      <ResearchQualityRefreshSource quality={quality} />
      <ResearchQualityAffectedArtifact affected={affected} />
      <ResearchQualityRecommendedAction recommendation={recommendation} />
    </section>
  )
}

function recentActivityListKey(event: Record<string, unknown>, index: number): string {
  const id = displayText(event.event_id ?? event.id, '')
  const type = displayText(event.event_type, 'event')
  return id || `${type}-${index}`
}

function RecentActivityItem({ event }: Readonly<{ event: Record<string, unknown> }>) {
  const id = displayText(event.event_id ?? event.id, '')
  const type = displayText(event.event_type, 'event')
  const summary = displayText(event.summary ?? event.entity_id, 'No event summary returned.')
  return (
    <li>
      <a href={eventDetailHref(id)}>{type}</a>
      <span>{summary}</span>
    </li>
  )
}

function RecentActivityStream({ events }: Readonly<{ events: OverviewResponse['recent_events'] }>) {
  const recentEvents = events || []
  if (recentEvents.length === 0) {
    return <p>No recent activity returned in the bounded overview snapshot.</p>
  }
  return (
    <ol>
      {recentEvents.slice(0, 6).map((event, index) => (
        <RecentActivityItem key={recentActivityListKey(event, index)} event={event} />
      ))}
    </ol>
  )
}

function OverviewSecondaryFold({
  recentEvents,
  operatorCounts,
  operatorDetailCounts,
  activeItems,
  readinessData,
  readinessLoading,
  readinessError,
  onSecondaryOpenChange,
}: Readonly<{
  recentEvents: OverviewResponse['recent_events']
  operatorCounts: Record<string, unknown>
  operatorDetailCounts: Record<string, unknown>
  activeItems: Record<string, unknown>[]
  readinessData?: AutomationReadiness
  readinessLoading: boolean
  readinessError: unknown
  onSecondaryOpenChange: (open: boolean) => void
}>) {
  return (
    <details className="secondary-fold" onToggle={(event) => onSecondaryOpenChange(event.currentTarget.open)}>
      <summary>Show secondary details</summary>
      <div className="secondary-links">
        <a href={dashboardV2Href('#runs')}>Runs</a>
        <a href={dashboardV2Href('#papers')}>Papers</a>
        <a href={dashboardV2Href('#events')}>Recent activity</a>
      </div>
      <section className="activity-snapshot" aria-label="Recent activity stream">
        <h3>Recent activity stream</h3>
        <RecentActivityStream events={recentEvents} />
      </section>
      <OperatorQueueSnapshot operatorCounts={operatorCounts} operatorDetailCounts={operatorDetailCounts} />
      <ActiveWorkSummary activeItems={activeItems} />
      <AutomationReadinessSummary readiness={readinessData} isLoading={readinessLoading} error={readinessError} />
    </details>
  )
}

function ReadinessCheckCard({
  readiness,
  isLoading,
  error,
  requested,
  onCheck,
}: Readonly<{
  readiness?: AutomationReadiness
  isLoading: boolean
  error: unknown
  requested: boolean
  onCheck: () => void
}>) {
  const blockers = readiness?.blockers || []
  const label = readinessCheckCardLabel(error, readiness, isLoading, requested)
  return (
    <section className="readiness-check-card" aria-label="Readiness check">
      <div>
        <p className="eyebrow">Automation readiness</p>
        <h2>{label}</h2>
        <p>{readinessCheckCardDetail(blockers, readiness)}</p>
      </div>
      <button className="secondary-button" type="button" disabled={isLoading} onClick={onCheck}>
        {readinessCheckButtonLabel(Boolean(readiness))}
      </button>
    </section>
  )
}

function ActiveWorkSummary({ activeItems }: Readonly<{ activeItems: Record<string, unknown>[] }>) {
  return (
    <section className="active-work-snapshot" aria-label="Active work snapshot">
      <h3>Active work snapshot</h3>
      <ActiveWorkList activeItems={activeItems} />
    </section>
  )
}
