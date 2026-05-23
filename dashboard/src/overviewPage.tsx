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
import { PrimaryAction, resolvePrimaryAction } from './components/PrimaryAction'
import { SafetyBar } from './components/SafetyBar'
import { WorkerLanes } from './components/WorkerLanes'
import { displayText } from './displayText'
import { OperatorQueueSnapshot } from './operatorQueueSnapshot'
import { formatReadinessErrorMessage } from './readinessErrors'
import { dashboardV2Href } from './routes'
import type { AutomationReadiness, OverviewResponse, StatusResponse } from './types'

export function OverviewPage() {
  const queryClient = useQueryClient()
  const [secondaryOpen, setSecondaryOpen] = useState(false)
  const [readinessRequested, setReadinessRequested] = useState(false)
  const overview = useQuery({ queryKey: ['overview'], queryFn: () => apiGet<unknown>('/control/api/v1/overview?active_limit=8&event_limit=6').then(parseOverviewResponse), refetchInterval: 30_000 })
  const status = useQuery({ queryKey: ['status'], queryFn: () => apiGet<unknown>('/control/api/status').then(parseStatusResponse), refetchInterval: 30_000 })
  const readiness = useQuery({
    queryKey: ['automation-readiness'],
    queryFn: () => apiGet<unknown>('/control/api/v1/automation-readiness').then(parseAutomationReadiness),
    refetchInterval: 60_000,
    enabled: secondaryOpen || readinessRequested,
  })
  const refresh = () => {
    void overview.refetch()
    void status.refetch()
    void queryClient.invalidateQueries({ predicate: (query) => query.queryKey[0] !== 'overview' && query.queryKey[0] !== 'status' })
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
