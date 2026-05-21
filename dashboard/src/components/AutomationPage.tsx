import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiGet, apiPost } from '../api/client'
import { dashboardV2Href } from '../routes'
import { DataTable } from './DataTable'
import { useOperatorDialog } from './OperatorDialog'
import type { CommandPresentationContext } from '../commandResultPresentation'
import { CommandResultSummary } from './CommandResultSummary'
import { PageHeader } from './PageHeader'

type AutomationResponse = {
  rows?: Record<string, unknown>[]
  counts?: Record<string, unknown>
  generated_at?: string
}
type AutomationDetailResponse = {
  item?: Record<string, unknown>
  checklist?: { items?: Record<string, unknown>[] }
}
type ArtifactPreviewResponse = {
  project_name?: string
  field?: string
  content?: string
}

type MutationResult = Record<string, unknown>
type ChecklistUpdateInput = { paperId: string; itemId: string }

function idempotencyKey(prefix: string): string {
  return `${prefix}:dashboard-v2:${Date.now()}`
}

function firstPaperId(rows: Record<string, unknown>[], preferredPaperId = ''): string {
  if (preferredPaperId) return preferredPaperId
  return String(rows.find((row) => row.paper_id)?.paper_id || '')
}

function ResultCard({ result, context }: { result?: MutationResult; context?: CommandPresentationContext }) {
  if (!result) return null
  return <CommandResultSummary result={{ payload: result, context }} />
}

function automationCellHref(row: Record<string, unknown>, column: string): string | undefined {
  if (column !== 'paper_id') return undefined
  const paperId = String(row.paper_id || '')
  return paperId ? dashboardV2Href(`#automation:${encodeURIComponent(paperId)}`) : undefined
}

function textList(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value.map((item) => String(item || '').trim()).filter(Boolean)
}

const artifactFields = ['draft_markdown_path', 'draft_latex_path', 'evidence_bundle_path', 'claim_ledger_path', 'manifest_path']

function artifactLabel(field: string): string {
  return field.replace('_path', '').replaceAll('_', ' ')
}

function AutomationDetailCard({
  detail,
  onMarkChecklistPass,
  onPreviewArtifact,
  checklistBusy = false,
  artifactBusy = '',
}: {
  detail?: AutomationDetailResponse;
  onMarkChecklistPass?: (input: ChecklistUpdateInput) => void;
  onPreviewArtifact?: (paperId: string, field: string) => void;
  checklistBusy?: boolean;
  artifactBusy?: string;
}) {
  if (!detail?.item) return null
  const item = detail.item
  const checklistItems = detail.checklist?.items || []
  const paperId = String(item.paper_id || '')
  const reasons = textList(item.rank_reasons)
  const availableArtifactFields = artifactFields.filter((field) => Boolean(item[field]))
  return (
    <section className="result-card" aria-label="Automation detail">
      <h2>{String(item.project_name || item.paper_title || item.paper_id || 'Automation detail')}</h2>
      <dl className="detail-field-grid">
        <div className="detail-field"><dt>paper id</dt><dd>{String(item.paper_id || '—')}</dd></div>
        <div className="detail-field"><dt>automation</dt><dd>{String(item.review_status || '—')}</dd></div>
        <div className="detail-field"><dt>paper status</dt><dd>{String(item.paper_status || '—')}</dd></div>
        <div className="detail-field"><dt>rank score</dt><dd>{String(item.rank_score ?? '—')}</dd></div>
      </dl>
      {reasons.length ? (
        <>
          <h3>Rank reasons</h3>
          <ul>{reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>
        </>
      ) : null}
      {availableArtifactFields.length > 0 && onPreviewArtifact && paperId ? (
        <>
          <h3>Artifacts</h3>
          <div className="action-row" aria-label="Artifact preview actions">
            {availableArtifactFields.map((field) => (
              <button
                key={field}
                className="secondary-button"
                type="button"
                disabled={artifactBusy === field}
                onClick={() => onPreviewArtifact(paperId, field)}
              >
                {artifactBusy === field ? `Loading ${artifactLabel(field)}` : `Preview ${artifactLabel(field)}`}
              </button>
            ))}
          </div>
        </>
      ) : null}
      {checklistItems.length ? (
        <>
          <h3>Checklist</h3>
          <DataTable rows={checklistItems} columns={['item_id', 'label', 'status', 'note']} empty="No checklist rows returned." />
          {onMarkChecklistPass && paperId ? (
            <div className="action-row" aria-label="Checklist actions">
              {checklistItems.map((checklistItem) => {
                const itemId = String(checklistItem.item_id || '')
                const status = String(checklistItem.status || '').toLowerCase()
                if (!itemId || status === 'pass' || status === 'passed') return null
                return (
                  <button
                    key={itemId}
                    className="secondary-button"
                    type="button"
                    disabled={checklistBusy}
                    onClick={() => onMarkChecklistPass({ paperId, itemId })}
                  >
                    Mark {itemId} pass
                  </button>
                )
              })}
            </div>
          ) : null}
        </>
      ) : null}
    </section>
  )
}

export function AutomationPage({ paperId = '' }: { paperId?: string }) {
  const queryClient = useQueryClient()
  const { confirm, dialog } = useOperatorDialog()
  const [selectedPaperId, setSelectedPaperId] = useState(paperId)
  const [artifactPreview, setArtifactPreview] = useState<ArtifactPreviewResponse | null>(null)
  const automation = useQuery({
    queryKey: ['publication-automation'],
    queryFn: () => apiGet<AutomationResponse>('/control/api/publication-automation?page_size=50&paper_status=publication_draft&sort=-rank_score'),
  })
  useEffect(() => {
    setSelectedPaperId(paperId)
  }, [paperId])
  const rows = automation.data?.rows || []
  const activePaperId = selectedPaperId
  const detail = useQuery({
    queryKey: ['publication-automation-detail', activePaperId],
    queryFn: () => apiGet<AutomationDetailResponse>(`/control/api/publication-automation/${encodeURIComponent(activePaperId)}`),
    enabled: Boolean(activePaperId),
  })
  const rewriteDryRun = useMutation({ mutationFn: () => apiPost<MutationResult>('/control/api/paper-reviews/rewrite-batch', { idempotency_key: idempotencyKey('paper-review-bulk-rewrite'), requested_by: 'dashboard-v2', paper_status: 'publication_draft', dry_run: true, limit: 10, skip_rewritten: true }) })
  const finalizationDryRun = useMutation({
    mutationFn: (paperId: string) => apiPost<MutationResult>(`/control/api/paper-reviews/${encodeURIComponent(paperId)}/prepare-finalization-package`, { idempotency_key: idempotencyKey(`paper-review-package:${paperId}`), requested_by: 'dashboard-v2', target_label: 'dashboard-v2-dry-run', dry_run: true }),
    onSuccess: (_result, paperId) => {
      void queryClient.invalidateQueries({ queryKey: ['publication-automation'] })
      void queryClient.invalidateQueries({ queryKey: ['publication-automation-detail', paperId] })
    },
  })
  const checklistUpdate = useMutation({
    mutationFn: ({ paperId, itemId }: ChecklistUpdateInput) => apiPost<MutationResult>(`/control/api/publication-automation/${encodeURIComponent(paperId)}/checklist/${encodeURIComponent(itemId)}`, {
      idempotency_key: idempotencyKey(`paper-review-checklist:${paperId}:${itemId}:pass`),
      requested_by: 'dashboard-v2',
      status: 'pass',
      note: 'Marked passed from dashboard-v2',
    }),
    onSuccess: (_result, input) => {
      void queryClient.invalidateQueries({ queryKey: ['publication-automation'] })
      void queryClient.invalidateQueries({ queryKey: ['publication-automation-detail', input.paperId] })
    },
  })
  const artifactPreviewQuery = useMutation({
    mutationFn: ({ paperId, field }: { paperId: string; field: string }) => apiGet<ArtifactPreviewResponse>(`/control/api/papers/${encodeURIComponent(paperId)}/artifact/${encodeURIComponent(field)}`),
    onSuccess: (result) => setArtifactPreview(result),
  })
  async function markChecklistPass(input: ChecklistUpdateInput) {
    const ok = await confirm({
      title: 'Mark checklist item passed?',
      message: `Mark checklist item ${input.itemId} as passed for paper ${input.paperId}. This updates publication automation state.`,
      confirmLabel: 'Mark passed',
      cancelLabel: 'Cancel',
      tone: 'warn',
    })
    if (ok) checklistUpdate.mutate(input)
  }
  const counts = automation.data?.counts || {}
  const actionPaperId = activePaperId || firstPaperId(rows)
  function refreshAutomation() {
    void automation.refetch()
    if (selectedPaperId) void detail.refetch()
  }
  function previewArtifact(paperId: string, field: string) {
    setArtifactPreview(null)
    artifactPreviewQuery.mutate({ paperId, field })
  }

  return (
    <section className="page-stack">
      <PageHeader
        title="Publication automation"
        subtitle="Dry-run rewrite batches and finalization packages before any live publish work."
        dataSource="/control/api/v1/automation and paper detail endpoints"
        action={(
          <>
            <span>Last loaded {automation.data?.generated_at || 'unknown'}</span>
            <button className="secondary-button" type="button" disabled={automation.isFetching || detail.isFetching} onClick={refreshAutomation}>
              {automation.isFetching || detail.isFetching ? 'Refreshing…' : 'Refresh automation'}
            </button>
          </>
        )}
        toolbar={(
          <div className="action-row">
            <button className="secondary-button" type="button" onClick={() => rewriteDryRun.mutate()} disabled={rewriteDryRun.isPending}>Dry-run rewrite batch</button>
            <button className="secondary-button" type="button" onClick={() => actionPaperId && finalizationDryRun.mutate(actionPaperId)} disabled={!actionPaperId || finalizationDryRun.isPending}>Dry-run finalization package</button>
          </div>
        )}
      />

      <section className="count-grid">
        {Object.entries(counts).slice(0, 8).map(([key, value]) => (
          <div key={key} className="count-card">
            <div>{String(value)}</div>
            <div>{key.replaceAll('_', ' ')}</div>
          </div>
        ))}
      </section>

      {activePaperId ? (
        <section className="result-card" aria-label="Targeted paper">
          <h2>Targeted paper</h2>
          <p>{activePaperId}</p>
          <p>Finalization dry-run uses this selected paper id, not an implicit unrelated table row.</p>
        </section>
      ) : null}

      <AutomationDetailCard
        detail={detail.data}
        onMarkChecklistPass={(input) => { void markChecklistPass(input) }}
        onPreviewArtifact={previewArtifact}
        checklistBusy={checklistUpdate.isPending}
        artifactBusy={artifactPreviewQuery.isPending ? artifactPreviewQuery.variables?.field || '' : ''}
      />
      {detail.isError ? <div className="state-card state-card--error">Automation detail unavailable: {String(detail.error.message)}</div> : null}

      {rewriteDryRun.data ? <ResultCard result={rewriteDryRun.data} context={{ commandFamily: 'finalize' }} /> : null}
      {finalizationDryRun.data ? <ResultCard result={finalizationDryRun.data} context={{ commandFamily: 'finalize' }} /> : null}
      {checklistUpdate.data ? <ResultCard result={checklistUpdate.data} context={{ commandFamily: 'automation' }} /> : null}
      {artifactPreviewQuery.isError ? <div className="state-card state-card--error">Artifact preview unavailable: {String(artifactPreviewQuery.error.message)}</div> : null}
      {artifactPreview ? (
        <section className="result-card artifact-preview" aria-label="Artifact preview">
          <h2>Artifact preview</h2>
          <p>{artifactPreview.project_name || activePaperId || 'Paper artifact'} · {artifactPreview.field || 'artifact'}</p>
          <pre className="artifact-content">{String(artifactPreview.content || '')}</pre>
        </section>
      ) : null}

      {automation.isLoading ? <div className="state-card">Loading publication automation…</div> : null}
      {automation.isError ? <div className="state-card state-card--error">Publication automation unavailable: {String(automation.error.message)}</div> : null}
      {dialog}

      {!automation.isLoading && !automation.isError ? (
        <DataTable
          rows={rows}
          columns={['paper_id', 'review_status', 'paper_status', 'project_name', 'rank_score', 'updated_at']}
          empty="No publication automation rows returned."
          cellHref={automationCellHref}
          onSelectRow={(row) => setSelectedPaperId(String(row.paper_id || ''))}
        />
      ) : null}
    </section>
  )
}
