import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiGet, apiPost } from '../api/client'
import { dashboardV2Href } from '../routes'
import { DataTable } from './DataTable'
import { useOperatorDialog } from './OperatorDialog'

type AutomationResponse = {
  rows?: Record<string, unknown>[]
  counts?: Record<string, unknown>
  generated_at?: string
}
type AutomationDetailResponse = {
  item?: Record<string, unknown>
  checklist?: { items?: Record<string, unknown>[] }
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

function ResultCard({ result }: { result?: MutationResult }) {
  if (!result) return null
  return <pre className="json-block">{JSON.stringify(result, null, 2)}</pre>
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

function AutomationDetailCard({ detail, onMarkChecklistPass, checklistBusy = false }: { detail?: AutomationDetailResponse; onMarkChecklistPass?: (input: ChecklistUpdateInput) => void; checklistBusy?: boolean }) {
  if (!detail?.item) return null
  const item = detail.item
  const checklistItems = detail.checklist?.items || []
  const paperId = String(item.paper_id || '')
  const reasons = textList(item.rank_reasons)
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
  const automation = useQuery({
    queryKey: ['publication-automation'],
    queryFn: () => apiGet<AutomationResponse>('/control/api/publication-automation?page_size=50&paper_status=publication_draft&sort=-rank_score'),
  })
  const detail = useQuery({
    queryKey: ['publication-automation-detail', paperId],
    queryFn: () => apiGet<AutomationDetailResponse>(`/control/api/publication-automation/${encodeURIComponent(paperId)}`),
    enabled: Boolean(paperId),
  })
  const rewriteDryRun = useMutation({ mutationFn: () => apiPost<MutationResult>('/control/api/paper-reviews/rewrite-batch', { idempotency_key: idempotencyKey('paper-review-bulk-rewrite'), requested_by: 'dashboard-v2', paper_status: 'publication_draft', dry_run: true, limit: 10, skip_rewritten: true }) })
  const finalizationDryRun = useMutation({
    mutationFn: (paperId: string) => apiPost<MutationResult>(`/control/api/paper-reviews/${encodeURIComponent(paperId)}/prepare-finalization-package`, { idempotency_key: idempotencyKey(`paper-review-package:${paperId}`), requested_by: 'dashboard-v2', target_label: 'dashboard-v2-dry-run', dry_run: true }),
    onSuccess: () => {
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
  const rows = automation.data?.rows || []
  const counts = automation.data?.counts || {}
  const selectedPaperId = firstPaperId(rows, paperId)
  function refreshAutomation() {
    void automation.refetch()
    if (paperId) void detail.refetch()
  }

  return (
    <section className="page-stack">
      <div className="page-hero page-hero--with-action">
        <div>
          <p className="eyebrow">Dashboard V2</p>
          <h1>Publication automation</h1>
          <p>Paper workflow controls for draft rewrite planning and finalization package dry-runs. Live publish remains out of V2 for now.</p>
          <div className="action-row">
            <button className="secondary-button" type="button" onClick={() => rewriteDryRun.mutate()} disabled={rewriteDryRun.isPending}>Dry-run rewrite batch</button>
            <button className="secondary-button" type="button" onClick={() => selectedPaperId && finalizationDryRun.mutate(selectedPaperId)} disabled={!selectedPaperId || finalizationDryRun.isPending}>Dry-run finalization package</button>
          </div>
        </div>
        <div className="page-hero-action">
          <span>Last loaded {automation.data?.generated_at || 'unknown'}</span>
          <button className="secondary-button" type="button" disabled={automation.isFetching || detail.isFetching} onClick={refreshAutomation}>
            {automation.isFetching || detail.isFetching ? 'Refreshing…' : 'Refresh automation'}
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

      {paperId ? (
        <section className="result-card" aria-label="Targeted paper">
          <h2>Targeted paper</h2>
          <p>{paperId}</p>
          <p>Finalization dry-run uses this paper id from the route, not the first visible table row.</p>
        </section>
      ) : null}

      <AutomationDetailCard detail={detail.data} onMarkChecklistPass={(input) => { void markChecklistPass(input) }} checklistBusy={checklistUpdate.isPending} />
      {detail.isError ? <div className="state-card state-card--error">Automation detail unavailable: {String(detail.error.message)}</div> : null}

      {rewriteDryRun.data ? <section className="result-card"><h2>Rewrite dry-run result</h2><ResultCard result={rewriteDryRun.data} /></section> : null}
      {finalizationDryRun.data ? <section className="result-card"><h2>Finalization dry-run result</h2><ResultCard result={finalizationDryRun.data} /></section> : null}
      {checklistUpdate.data ? <section className="result-card"><h2>Checklist update result</h2><ResultCard result={checklistUpdate.data} /></section> : null}

      {automation.isLoading ? <div className="state-card">Loading publication automation…</div> : null}
      {automation.isError ? <div className="state-card state-card--error">Publication automation unavailable: {String(automation.error.message)}</div> : null}
      {dialog}

      {!automation.isLoading && !automation.isError ? (
        <DataTable rows={rows} columns={['paper_id', 'review_status', 'paper_status', 'project_name', 'rank_score', 'updated_at']} empty="No publication automation rows returned." cellHref={automationCellHref} />
      ) : null}
    </section>
  )
}
