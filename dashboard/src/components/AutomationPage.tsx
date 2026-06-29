import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { AutomationDetail } from '../api/readModels'
import { displayText } from '../displayText'
import { parseAutomationDetail, parseAutomationListResponse } from '../api/readModelSchemas'
import { apiGet, apiPost } from '../api/client'
import { dashboardV2Href } from '../routes'
import { DataTable } from './DataTable'
import { hashQuery, ListFilterBar, type ListFilterState } from './ListFilterBar'
import { useOperatorDialog } from './OperatorDialog'
import type { CommandPresentationContext } from '../commandResultPresentation'
import { OperatorResultCard } from './operator/OperatorResultCard'
import { SelectedEntityActions } from './operator/SelectedEntityActions'
import { automationTableColumns, simpleTableColumns } from '../tablePresentation'
import { PageHeader } from './PageHeader'
import { PaperWorkflowNav } from './PaperWorkflowNav'
import { WorkbenchCountsFold, WorkbenchOperatorSummary } from './WorkbenchSummary'

type MutationResult = Record<string, unknown>
type ChecklistUpdateInput = { paperId: string; itemId: string; status: 'pass' | 'fail' | 'accepted_risk' }

function idempotencyKey(prefix: string): string {
  return `${prefix}:dashboard-v2:${Date.now()}`
}

function automationHash(state: ListFilterState, paperId = ''): string {
  const base = paperId ? `#automation:${encodeURIComponent(paperId)}` : '#automation'
  return `${base}${hashQuery([['search', state.search], ['review_status', state.status]])}`
}

function automationListUrl(state: ListFilterState): string {
  const params = new URLSearchParams({
    page_size: state.pageSize,
    paper_status: 'publication_draft',
    sort: '-rank_score',
  })
  if (state.search) params.set('search', state.search)
  if (state.status) params.set('review_status', state.status)
  if (state.cursor) params.set('page', state.cursor)
  return `/control/api/publication-automation?${params.toString()}`
}

function replaceRouteHash(hash: string) {
  if (globalThis.window === undefined) return
  globalThis.history.replaceState(globalThis.history.state, '', hash)
}

function automationCellHref(row: Record<string, unknown>, column: string): string | undefined {
  if (column !== 'paper_id') return undefined
  const paperId = displayText(row.paper_id)
  return paperId ? dashboardV2Href(`#automation:${encodeURIComponent(paperId)}`) : undefined
}

function textList(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value.map((item) => displayText(item).trim()).filter(Boolean)
}

function checklistMarkActions(
  checklistItem: Record<string, unknown>,
): { key: string; label: string; status: ChecklistUpdateInput['status'] }[] {
  const itemId = displayText(checklistItem.item_id)
  const status = displayText(checklistItem.status).toLowerCase()
  if (!itemId || status === 'pass' || status === 'passed') return []
  return [
    { key: `${itemId}-pass`, label: `Mark ${itemId} pass`, status: 'pass' },
    { key: `${itemId}-fail`, label: `Mark ${itemId} fail`, status: 'fail' },
    { key: `${itemId}-risk`, label: `Mark ${itemId} accepted risk`, status: 'accepted_risk' },
  ]
}

function automationResultCards(mutations: {
  rewriteDryRun: { data?: MutationResult }
  rewriteDraft: { data?: MutationResult }
  finalizationDryRun: { data?: MutationResult }
  finalizationLive: { data?: MutationResult }
  rejectPaper: { data?: MutationResult }
  checklistUpdate: { data?: MutationResult }
}): { result?: MutationResult; context: CommandPresentationContext }[] {
  return [
    { result: mutations.rewriteDryRun.data, context: { commandFamily: 'finalize' } },
    { result: mutations.rewriteDraft.data, context: { commandFamily: 'finalize' } },
    { result: mutations.finalizationDryRun.data, context: { commandFamily: 'finalize' } },
    { result: mutations.finalizationLive.data, context: { commandFamily: 'finalize' } },
    { result: mutations.rejectPaper.data, context: { commandFamily: 'automation' } },
    { result: mutations.checklistUpdate.data, context: { commandFamily: 'automation' } },
  ]
}

function activeArtifactBusyField(isPending: boolean, field?: string): string {
  if (!isPending) return ''
  return field ?? ''
}

const artifactFields = ['draft_markdown_path', 'draft_latex_path', 'evidence_bundle_path', 'claim_ledger_path', 'manifest_path']

function artifactLabel(field: string): string {
  return field.replace('_path', '').replaceAll('_', ' ')
}

function artifactPreviewButtonLabel(artifactBusy: string, field: string): string {
  if (artifactBusy === field) return `Loading ${artifactLabel(field)}`
  return `Preview ${artifactLabel(field)}`
}

function automationDetailTitle(item: AutomationDetail['item']): string {
  const paperTitle = displayText(item?.paper_title)
  if (paperTitle) return paperTitle
  const projectName = displayText(item?.project_name)
  if (projectName) return projectName
  return displayText(item?.paper_id, 'Automation detail')
}

function AutomationDetailArtifacts({
  paperId,
  fields,
  artifactBusy,
  onPreviewArtifact,
}: Readonly<{
  paperId: string
  fields: string[]
  artifactBusy: string
  onPreviewArtifact: (paperId: string, field: string) => void
}>) {
  return (
    <>
      <h3>Artifacts</h3>
      <div className="action-row" aria-label="Artifact preview actions">
        {fields.map((field) => (
          <button
            key={field}
            className="secondary-button"
            type="button"
            disabled={artifactBusy === field}
            onClick={() => onPreviewArtifact(paperId, field)}
          >
            {artifactPreviewButtonLabel(artifactBusy, field)}
          </button>
        ))}
      </div>
    </>
  )
}

function AutomationDetailChecklist({
  checklistItems,
  paperId,
  checklistBusy,
  onMarkChecklist,
}: Readonly<{
  checklistItems: Record<string, unknown>[]
  paperId: string
  checklistBusy: boolean
  onMarkChecklist?: (input: ChecklistUpdateInput) => void
}>) {
  return (
    <>
      <h3>Checklist</h3>
      <DataTable rows={checklistItems} columns={simpleTableColumns(['item_id', 'label', 'status', 'note'], { label: { kind: 'primary' } })} empty="No checklist rows returned." />
      {onMarkChecklist ? (
        <div className="action-row" aria-label="Checklist actions">
          {checklistItems.flatMap((checklistItem) =>
            checklistMarkActions(checklistItem).map((action) => (
              <button
                key={action.key}
                className="secondary-button"
                type="button"
                disabled={checklistBusy}
                onClick={() => onMarkChecklist({ paperId, itemId: displayText(checklistItem.item_id), status: action.status })}
              >
                {action.label}
              </button>
            )),
          )}
        </div>
      ) : null}
    </>
  )
}

function AutomationDetailCard({
  detail,
  onMarkChecklist,
  onPreviewArtifact,
  checklistBusy = false,
  artifactBusy = '',
}: Readonly<{
  detail?: AutomationDetail
  onMarkChecklist?: (input: ChecklistUpdateInput) => void
  onPreviewArtifact?: (paperId: string, field: string) => void
  checklistBusy?: boolean
  artifactBusy?: string
}>) {
  if (!detail?.item) return null
  const item = detail.item
  const checklistItems = detail.checklist?.items || []
  const paperId = displayText(item.paper_id)
  const reasons = textList(item.rank_reasons)
  const availableArtifactFields = artifactFields.filter((field) => Boolean(item[field]))
  const detailTitle = automationDetailTitle(item)
  const showArtifacts = availableArtifactFields.length > 0 && Boolean(onPreviewArtifact) && Boolean(paperId)
  const showChecklist = checklistItems.length > 0
  return (
    <section className="result-card" aria-label="Automation detail">
      <h2>{detailTitle}</h2>
      <dl className="detail-field-grid">
        <div className="detail-field"><dt>paper id</dt><dd>{displayText(item.paper_id, '—')}</dd></div>
        <div className="detail-field"><dt>automation</dt><dd>{displayText(item.review_status, '—')}</dd></div>
        <div className="detail-field"><dt>paper status</dt><dd>{displayText(item.paper_status, '—')}</dd></div>
        <div className="detail-field"><dt>rank score</dt><dd>{displayText(item.rank_score, '—')}</dd></div>
      </dl>
      {reasons.length ? (
        <>
          <h3>Rank reasons</h3>
          <ul>{reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>
        </>
      ) : null}
      {showArtifacts && onPreviewArtifact ? (
        <AutomationDetailArtifacts
          paperId={paperId}
          fields={availableArtifactFields}
          artifactBusy={artifactBusy}
          onPreviewArtifact={onPreviewArtifact}
        />
      ) : null}
      {showChecklist ? (
        <AutomationDetailChecklist
          checklistItems={checklistItems}
          paperId={paperId}
          checklistBusy={checklistBusy}
          onMarkChecklist={onMarkChecklist}
        />
      ) : null}
    </section>
  )
}

function AutomationPageFeedback({
  activePaperId,
  artifactPreview,
  automationError,
  automationLoading,
  detailError,
  artifactPreviewError,
  resultCards,
}: Readonly<{
  activePaperId: string
  artifactPreview: { project_name?: string; field?: string; content?: string } | null
  automationError?: Error
  automationLoading: boolean
  detailError?: Error
  artifactPreviewError?: Error
  resultCards: { result?: MutationResult; context: CommandPresentationContext }[]
}>) {
  return (
    <>
      {detailError ? <div className="state-card state-card--error">Automation detail unavailable: {String(detailError.message)}</div> : null}
      {resultCards.map((card, index) => (
        <OperatorResultCard key={`${card.context.commandFamily}-${index}`} result={card.result} context={card.context} />
      ))}
      {artifactPreviewError ? <div className="state-card state-card--error">Artifact preview unavailable: {String(artifactPreviewError.message)}</div> : null}
      {artifactPreview ? (
        <section className="result-card artifact-preview" aria-label="Artifact preview">
          <h2>Artifact preview</h2>
          <p>{artifactPreview.project_name || activePaperId || 'Paper artifact'} · {artifactPreview.field || 'artifact'}</p>
          <pre className="artifact-content">{displayText(artifactPreview.content)}</pre>
        </section>
      ) : null}
      {automationLoading ? <div className="state-card">Loading publication automation…</div> : null}
      {automationError ? <div className="state-card state-card--error">Paper actions unavailable: {String(automationError.message)}</div> : null}
    </>
  )
}

export function AutomationPage({
  paperId = '',
  search = '',
  reviewStatus = '',
}: Readonly<{
  paperId?: string
  search?: string
  reviewStatus?: string
}>) {
  const queryClient = useQueryClient()
  const { confirm, dialog } = useOperatorDialog()
  const [selectedPaperId, setSelectedPaperId] = useState(paperId)
  const [artifactPreview, setArtifactPreview] = useState<{ project_name?: string; field?: string; content?: string } | null>(null)
  const [finalizationReadyPaperId, setFinalizationReadyPaperId] = useState<string | null>(null)
  const [filters, setFilters] = useState<ListFilterState>({
    search,
    status: reviewStatus,
    pageSize: '50',
    cursor: '',
  })

  useEffect(() => {
    setSelectedPaperId(paperId)
  }, [paperId])

  useEffect(() => {
    setFilters((current) => ({
      ...current,
      search,
      status: reviewStatus,
      cursor: '',
    }))
  }, [search, reviewStatus])


  const automation = useQuery({
    queryKey: ['publication-automation', filters],
    queryFn: () => apiGet<unknown>(automationListUrl(filters)).then(parseAutomationListResponse),
  })
  const rows = automation.data?.rows || []
  const activePaperId = selectedPaperId
  const detail = useQuery({
    queryKey: ['publication-automation-detail', activePaperId],
    queryFn: () => apiGet<unknown>(`/control/api/publication-automation/${encodeURIComponent(activePaperId)}`).then(parseAutomationDetail),
    enabled: Boolean(activePaperId),
  })

  function invalidateAutomation(paperId?: string) {
    queryClient.invalidateQueries({ queryKey: ['publication-automation'] }).catch(() => undefined)
    if (paperId) {
      queryClient.invalidateQueries({ queryKey: ['publication-automation-detail', paperId] }).catch(() => undefined)
    }
  }

  const rewriteDryRun = useMutation({
    mutationFn: () => apiPost<MutationResult>('/control/api/paper-reviews/rewrite-batch', {
      idempotency_key: idempotencyKey('paper-review-bulk-rewrite'),
      requested_by: 'dashboard-v2',
      paper_status: 'publication_draft',
      dry_run: true,
      limit: 10,
      skip_rewritten: true,
    }),
  })

  const rewriteDraft = useMutation({
    mutationFn: (targetPaperId: string) => apiPost<MutationResult>(`/control/api/publication-automation/${encodeURIComponent(targetPaperId)}/rewrite-draft`, {
      idempotency_key: idempotencyKey(`paper-review-rewrite:${targetPaperId}`),
      requested_by: 'dashboard-v2',
      force: true,
    }),
    onSuccess: (_result, targetPaperId) => invalidateAutomation(targetPaperId),
  })

  const finalizationDryRun = useMutation({
    mutationFn: (targetPaperId: string) => apiPost<MutationResult>(`/control/api/paper-reviews/${encodeURIComponent(targetPaperId)}/prepare-finalization-package`, {
      idempotency_key: idempotencyKey(`paper-review-package:${targetPaperId}`),
      requested_by: 'dashboard-v2',
      target_label: 'dashboard-v2-dry-run',
      dry_run: true,
    }),
    onSuccess: (_result, targetPaperId) => {
      setFinalizationReadyPaperId(targetPaperId)
      invalidateAutomation(targetPaperId)
    },
  })

  const finalizationLive = useMutation({
    mutationFn: (targetPaperId: string) => apiPost<MutationResult>(`/control/api/publication-automation/${encodeURIComponent(targetPaperId)}/prepare-finalization-package`, {
      idempotency_key: idempotencyKey(`paper-review-package-live:${targetPaperId}`),
      requested_by: 'dashboard-v2',
      target_label: 'dashboard-v2-live',
      dry_run: false,
    }),
    onSuccess: (_result, targetPaperId) => {
      setFinalizationReadyPaperId(null)
      invalidateAutomation(targetPaperId)
    },
  })

  const rejectPaper = useMutation({
    mutationFn: (targetPaperId: string) => apiPost<MutationResult>(`/control/api/publication-automation/${encodeURIComponent(targetPaperId)}/status`, {
      idempotency_key: idempotencyKey(`paper-review-reject:${targetPaperId}`),
      requested_by: 'dashboard-v2',
      review_status: 'rejected',
      note: 'Rejected from dashboard-v2 automation detail',
    }),
    onSuccess: (_result, targetPaperId) => invalidateAutomation(targetPaperId),
  })

  const checklistUpdate = useMutation({
    mutationFn: ({ paperId: targetPaperId, itemId, status }: ChecklistUpdateInput) => apiPost<MutationResult>(`/control/api/publication-automation/${encodeURIComponent(targetPaperId)}/checklist/${encodeURIComponent(itemId)}`, {
      idempotency_key: idempotencyKey(`paper-review-checklist:${targetPaperId}:${itemId}:${status}`),
      requested_by: 'dashboard-v2',
      status,
      note: `Marked ${status} from dashboard-v2`,
    }),
    onSuccess: (_result, input) => invalidateAutomation(input.paperId),
  })

  const artifactPreviewQuery = useMutation({
    mutationFn: ({ paperId: targetPaperId, field }: { paperId: string; field: string }) => apiGet<{ project_name?: string; field?: string; content?: string }>(`/control/api/papers/${encodeURIComponent(targetPaperId)}/artifact/${encodeURIComponent(field)}`),
    onSuccess: (result) => setArtifactPreview(result),
  })

  async function markChecklist(input: ChecklistUpdateInput) {
    const tone = input.status === 'pass' ? 'warn' : 'danger'
    const ok = await confirm({
      title: `Mark checklist item ${input.status}?`,
      message: `Mark checklist item ${input.itemId} as ${input.status} for paper ${input.paperId}.`,
      confirmLabel: `Mark ${input.status}`,
      cancelLabel: 'Cancel',
      tone,
    })
    if (ok) checklistUpdate.mutate(input)
  }

  async function runRewriteDraft(targetPaperId: string) {
    const ok = await confirm({
      title: 'Rewrite publication draft now?',
      message: 'This runs a live rewrite/finalize for the selected paper. Inspect automation detail before proceeding.',
      confirmLabel: 'Rewrite draft',
      tone: 'danger',
    })
    if (ok) rewriteDraft.mutate(targetPaperId)
  }

  async function runLiveFinalization(targetPaperId: string) {
    const ok = await confirm({
      title: 'Prepare live finalization package?',
      message: 'This writes the live finalization package for the selected paper after your dry-run check.',
      confirmLabel: 'Prepare live package',
      tone: 'danger',
    })
    if (ok) finalizationLive.mutate(targetPaperId)
  }

  async function runReject(targetPaperId: string) {
    const ok = await confirm({
      title: 'Reject this automation item?',
      message: 'This marks the publication automation gate as rejected.',
      confirmLabel: 'Reject paper',
      tone: 'danger',
    })
    if (ok) rejectPaper.mutate(targetPaperId)
  }

  async function openNextReady() {
    const params = new URLSearchParams({ paper_status: 'publication_draft' })
    if (filters.search) params.set('search', filters.search)
    if (filters.status) params.set('review_status', filters.status)
    const next = await apiGet<{ paper_id?: string; item?: { paper_id?: string } }>(`/control/api/publication-automation/next?${params.toString()}`)
    const nextPaperId = displayText(next.item?.paper_id, displayText(next.paper_id))
    if (!nextPaperId) return
    setSelectedPaperId(nextPaperId)
    replaceRouteHash(automationHash(filters, nextPaperId))
  }

  const counts = automation.data?.counts || {}
  const selectedRow = rows.find((row) => displayText(row.paper_id) === activePaperId)
  const resultCards = automationResultCards({
    rewriteDryRun,
    rewriteDraft,
    finalizationDryRun,
    finalizationLive,
    rejectPaper,
    checklistUpdate,
  })
  const selectedTitle = displayText(selectedRow?.project_name, activePaperId)

  function refreshAutomation() {
    automation.refetch().catch(() => undefined)
    if (selectedPaperId) detail.refetch().catch(() => undefined)
  }

  return (
    <section className="page-stack">
      <PageHeader
        title="Paper actions"
        subtitle="Dry-run first, then run per-paper rewrite, finalization, reject, and checklist actions on selected rows."
        dataSource="/control/api/publication-automation"
        action={(
          <>
            <span>Last loaded {automation.data?.generated_at || 'unknown'}</span>
            <button className="secondary-button" type="button" disabled={automation.isFetching || detail.isFetching} onClick={refreshAutomation}>
              {automation.isFetching || detail.isFetching ? 'Refreshing…' : 'Refresh automation'}
            </button>
            <button className="secondary-button" type="button" onClick={() => { void openNextReady() }}>Open next ready</button>
          </>
        )}
      />

      <PaperWorkflowNav active="automation" />

      <ListFilterBar
        state={filters}
        statusLabel="Publication gate status"
        statusOptions={[
          { label: 'all publication gate statuses', value: '' },
          { label: 'triage ready', value: 'triage_ready' },
          { label: 'queued', value: 'queued' },
          { label: 'claimed', value: 'claimed' },
          { label: 'blocked', value: 'blocked' },
          { label: 'finalized', value: 'finalized' },
          { label: 'rejected', value: 'rejected' },
        ]}
        onApply={(next) => {
          setFilters(next)
          replaceRouteHash(automationHash(next, activePaperId))
        }}
        onReset={() => {
          const next = { search: '', status: '', pageSize: '50', cursor: '' }
          setFilters(next)
          replaceRouteHash(automationHash(next, activePaperId))
        }}
        onNext={() => {
          const nextPage = String(Number(filters.cursor || '1') + 1)
          const next = { ...filters, cursor: nextPage }
          setFilters(next)
          replaceRouteHash(automationHash(next, activePaperId))
        }}
        page={{
          returned: automation.data?.page?.returned,
          has_more: automation.data?.page?.has_more,
        }}
      />

      <WorkbenchOperatorSummary summary={automation.data?.operator_summary} />

      {!automation.isLoading && !automation.isError ? (
        <DataTable
          rows={rows}
          columns={automationTableColumns}
          empty="No publication automation rows returned."
          cellHref={automationCellHref}
          onSelectRow={(row) => {
            const nextPaperId = displayText(row.paper_id)
            setSelectedPaperId(nextPaperId)
            replaceRouteHash(automationHash(filters, nextPaperId))
          }}
        />
      ) : null}

      {!automation.isLoading && !automation.isError ? (
        <WorkbenchCountsFold counts={counts} label="Paper action counts" />
      ) : null}

      {activePaperId ? (
        <SelectedEntityActions
          title={selectedTitle}
          entityId={activePaperId}
          description="Dry-run first where available, then confirm live rewrite, finalization, or reject."
          ariaLabel="Selected paper actions"
        >
          <button className="secondary-button" type="button" onClick={() => rewriteDryRun.mutate()} disabled={rewriteDryRun.isPending}>Dry-run rewrite batch</button>
          <button className="secondary-button" type="button" onClick={() => finalizationDryRun.mutate(activePaperId)} disabled={finalizationDryRun.isPending}>Dry-run finalization package</button>
          <button className="secondary-button" type="button" disabled={finalizationReadyPaperId !== activePaperId || finalizationLive.isPending} onClick={() => { void runLiveFinalization(activePaperId) }}>Prepare live finalization package</button>
          <button className="danger-button" type="button" disabled={rewriteDraft.isPending} onClick={() => { void runRewriteDraft(activePaperId) }}>Rewrite draft now</button>
          <button className="danger-button" type="button" disabled={rejectPaper.isPending} onClick={() => { void runReject(activePaperId) }}>Reject paper</button>
        </SelectedEntityActions>
      ) : null}

      <AutomationDetailCard
        detail={detail.data}
        onMarkChecklist={(input) => { void markChecklist(input) }}
        onPreviewArtifact={(targetPaperId, field) => {
          setArtifactPreview(null)
          artifactPreviewQuery.mutate({ paperId: targetPaperId, field })
        }}
        checklistBusy={checklistUpdate.isPending}
        artifactBusy={activeArtifactBusyField(artifactPreviewQuery.isPending, artifactPreviewQuery.variables?.field)}
      />
      <AutomationPageFeedback
        activePaperId={activePaperId}
        artifactPreview={artifactPreview}
        automationError={automation.isError ? automation.error : undefined}
        automationLoading={automation.isLoading}
        detailError={detail.isError ? detail.error : undefined}
        artifactPreviewError={artifactPreviewQuery.isError ? artifactPreviewQuery.error : undefined}
        resultCards={resultCards}
      />
      {dialog}
    </section>
  )
}
