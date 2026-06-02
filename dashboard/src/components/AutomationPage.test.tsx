import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { join } from 'node:path'
import { tmpdir } from 'node:os'
import { afterEach, expect, it, vi } from 'vitest'
import { saveToken } from '../api/client'
import { fetchMockCallUrl, fetchMockRequestBody } from '../test/fetchMockBody'
import { AutomationPage } from './AutomationPage'

const mockPackagePath = join(tmpdir(), 'enoch-test-package.json')

function renderWithClient(ui: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  saveToken('')
})

it('loads publication automation rows from the bounded API', async () => {
  saveToken('test-token')
  const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ counts: { triage_ready: 1 }, operator_summary: '1 paper(s) ready for automation triage; select a row and dry-run rewrite or finalization.', rows: [{ paper_id: 'paper-1', review_status: 'triage_ready', paper_status: 'publication_draft', project_name: 'Paper project' }] }), { status: 200 }))

  renderWithClient(<AutomationPage />)

  await screen.findByText('Paper project')
  const workflowNav = screen.getByRole('navigation', { name: 'Papers workflow' })
  expect(within(workflowNav).getByRole('link', { name: /Paper actions/ })).toHaveAttribute('aria-current', 'page')
  expect(within(workflowNav).getByRole('link', { name: /Papers/ })).toHaveAttribute('href', '/control/dashboard-v2#papers')
  expect(within(workflowNav).getByRole('link', { name: /Paper corpus import/ })).toHaveAttribute('href', '/control/dashboard-v2#corpus')
  expect(screen.getByText(/ready for automation triage/i)).toBeInTheDocument()
  expect(screen.getByRole('link', { name: /paper-1/ })).toHaveAttribute('href', '/control/dashboard-v2#automation:paper-1')
  expect(fetchMock).toHaveBeenCalledWith(
    expect.stringContaining('/control/api/publication-automation?'),
    expect.objectContaining({ headers: { Authorization: 'Bearer test-token' } }),
  )
  expect(fetchMockCallUrl(fetchMock, 0)).toContain('page_size=50')
  expect(fetchMockCallUrl(fetchMock, 0)).toContain('paper_status=publication_draft')
  expect(fetchMockCallUrl(fetchMock, 0)).toContain('sort=-rank_score')
})

it('opens automation detail from selected table rows', async () => {
  saveToken('test-token')
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ counts: {}, rows: [{ paper_id: 'paper-select', review_status: 'triage_ready', paper_status: 'publication_draft', project_name: 'Selectable paper' }] }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ item: { paper_id: 'paper-select', project_name: 'Selectable paper', review_status: 'triage_ready', paper_status: 'publication_draft', rank_score: 77, rank_reasons: ['row selected'] }, checklist: { items: [{ item_id: 'evidence', label: 'Evidence bundle present', status: 'pending' }] } }), { status: 200 }))

  renderWithClient(<AutomationPage />)

  fireEvent.click(await screen.findByText('Selectable paper'))

  await screen.findByLabelText('Automation detail')
  expect(screen.getByLabelText('Selected paper actions')).toHaveTextContent('paper-select')
  expect(screen.getByText('row selected')).toBeInTheDocument()
  expect(fetchMock).toHaveBeenNthCalledWith(2, '/control/api/publication-automation/paper-select', expect.any(Object))
})

it('refreshes publication automation rows explicitly from V2', async () => {
  saveToken('test-token')
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ generated_at: '2026-05-21T08:00:00Z', counts: {}, rows: [{ paper_id: 'paper-old', review_status: 'triage_ready', paper_status: 'publication_draft', project_name: 'Old paper' }] }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ generated_at: '2026-05-21T08:04:00Z', counts: {}, rows: [{ paper_id: 'paper-fresh', review_status: 'triage_ready', paper_status: 'publication_draft', project_name: 'Fresh paper' }] }), { status: 200 }))

  renderWithClient(<AutomationPage />)
  await screen.findByText('Old paper')

  fireEvent.click(screen.getByRole('button', { name: 'Refresh automation' }))

  await screen.findByText('Fresh paper')
  expect(screen.getByText('Last loaded 2026-05-21T08:04:00Z')).toBeInTheDocument()
  expect(fetchMock).toHaveBeenCalledTimes(2)
})


it('uses the paper id from automation detail hashes for finalization dry-runs', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ counts: {}, rows: [{ paper_id: 'paper-first', review_status: 'triage_ready', paper_status: 'publication_draft', project_name: 'First paper' }, { paper_id: 'paper-target', review_status: 'triage_ready', paper_status: 'publication_draft', project_name: 'Target paper' }] }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ item: { paper_id: 'paper-target', project_name: 'Target paper', review_status: 'triage_ready', paper_status: 'publication_draft', rank_score: 91, rank_reasons: ['positive evidence'] }, checklist: { items: [{ item_id: 'evidence', label: 'Evidence bundle present', status: 'passed' }] } }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ dry_run: true, package_path: mockPackagePath, paper_id: 'paper-target' }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ counts: {}, rows: [{ paper_id: 'paper-target' }] }), { status: 200 }))

  renderWithClient(<AutomationPage paperId="paper-target" />)

  await screen.findByLabelText('Automation detail')
  await screen.findByText('Evidence bundle present')
  await screen.findByText('positive evidence')
  const targeted = screen.getByLabelText('Selected paper actions')
  expect(targeted).toHaveTextContent('Target paper')
  expect(targeted).toHaveTextContent('paper-target')
  fireEvent.click(screen.getByRole('button', { name: 'Dry-run finalization package' }))

  await screen.findByText('Paper finalize dry-run passed')
  expect(fetchMock).toHaveBeenNthCalledWith(2, '/control/api/publication-automation/paper-target', expect.any(Object))
  expect(fetchMock).toHaveBeenNthCalledWith(3, '/control/api/paper-reviews/paper-target/prepare-finalization-package', expect.objectContaining({ method: 'POST' }))
  expect(fetchMockRequestBody(fetchMock, 2)).toContain('"dry_run":true')
})

it('previews selected paper artifacts inside V2 automation detail', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ counts: {}, rows: [{ paper_id: 'paper-target', review_status: 'triage_ready', paper_status: 'publication_draft', project_name: 'Target paper' }] }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({
      item: {
        paper_id: 'paper-target',
        project_name: 'Target paper',
        review_status: 'triage_ready',
        paper_status: 'publication_draft',
        rank_score: 91,
        draft_markdown_path: 'papers/paper-target/draft.md',
      },
      checklist: { items: [] },
    }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ project_name: 'Target paper', field: 'draft_markdown_path', content: '# Draft\nEvidence-backed result.' }), { status: 200 }))

  renderWithClient(<AutomationPage paperId="paper-target" />)

  await screen.findByLabelText('Automation detail')
  fireEvent.click(screen.getByRole('button', { name: 'Preview draft markdown' }))

  await screen.findByText('Artifact preview')
  expect(screen.getByText(/draft_markdown_path/)).toBeInTheDocument()
  expect(screen.getByText(/Evidence-backed result/)).toBeInTheDocument()
  expect(fetchMock).toHaveBeenNthCalledWith(3, '/control/api/papers/paper-target/artifact/draft_markdown_path', expect.objectContaining({ cache: 'no-store' }))
})

it('updates automation checklist items through dialog-confirmed V2 mutation', async () => {
  const confirmSpy = vi.spyOn(globalThis, 'confirm')
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ counts: {}, rows: [{ paper_id: 'paper-target', review_status: 'triage_ready', paper_status: 'publication_draft', project_name: 'Target paper' }] }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ item: { paper_id: 'paper-target', project_name: 'Target paper', review_status: 'triage_ready', paper_status: 'publication_draft', rank_score: 91 }, checklist: { items: [{ item_id: 'evidence', label: 'Evidence bundle present', status: 'pending', note: '' }] } }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true, paper_id: 'paper-target', item_id: 'evidence', status: 'pass' }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ item: { paper_id: 'paper-target', project_name: 'Target paper', review_status: 'triage_ready', paper_status: 'publication_draft', rank_score: 91 }, checklist: { items: [{ item_id: 'evidence', label: 'Evidence bundle present', status: 'pass', note: 'Marked passed from dashboard-v2' }] } }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ counts: {}, rows: [{ paper_id: 'paper-target' }] }), { status: 200 }))

  renderWithClient(<AutomationPage paperId="paper-target" />)

  await screen.findByText('Evidence bundle present')
  fireEvent.click(screen.getByRole('button', { name: 'Mark evidence pass' }))

  expect(screen.getByRole('dialog', { name: 'Mark checklist item pass?' })).toBeInTheDocument()
  expect(confirmSpy).not.toHaveBeenCalled()

  fireEvent.click(screen.getByRole('button', { name: 'Mark pass' }))

  await screen.findByText('Command completed')
  expect(fetchMock).toHaveBeenNthCalledWith(3, '/control/api/publication-automation/paper-target/checklist/evidence', expect.objectContaining({ method: 'POST' }))
  expect(fetchMockRequestBody(fetchMock, 2)).toContain('"status":"pass"')
  expect(fetchMockRequestBody(fetchMock, 2)).toContain('"note":"Marked pass from dashboard-v2"')
})

it('dry-runs rewrite batch and finalization package without live rewrite', async () => {
  saveToken('test-token')
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ counts: {}, rows: [{ paper_id: 'paper-1', review_status: 'triage_ready', paper_status: 'publication_draft', project_name: 'Paper project' }] }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ item: { paper_id: 'paper-1', project_name: 'Paper project', review_status: 'triage_ready', paper_status: 'publication_draft' }, checklist: { items: [] } }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ dry_run: true, matched: 1, rows: [{ paper_id: 'paper-1', action: 'would_rewrite' }] }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ dry_run: true, package_path: mockPackagePath }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ counts: {}, rows: [{ paper_id: 'paper-1' }] }), { status: 200 }))

  renderWithClient(<AutomationPage />)

  fireEvent.click(await screen.findByText('Paper project'))
  await screen.findByLabelText('Selected paper actions')
  fireEvent.click(screen.getByRole('button', { name: 'Dry-run rewrite batch' }))
  await screen.findByText('Paper finalize dry-run passed')
  fireEvent.click(screen.getByRole('button', { name: 'Dry-run finalization package' }))
  await screen.findByText('Paper finalize dry-run passed')

  expect(fetchMock).toHaveBeenNthCalledWith(3, '/control/api/paper-reviews/rewrite-batch', expect.objectContaining({ method: 'POST' }))
  expect(fetchMockRequestBody(fetchMock, 2)).toContain('"dry_run":true')
  expect(fetchMock).toHaveBeenNthCalledWith(4, '/control/api/paper-reviews/paper-1/prepare-finalization-package', expect.objectContaining({ method: 'POST' }))
  expect(fetchMockRequestBody(fetchMock, 3)).toContain('"dry_run":true')
})

it('only enables live finalization for the paper that completed dry-run', async () => {
  let resolveDryRun!: (value: Response) => void
  const dryRunPromise = new Promise<Response>((resolve) => {
    resolveDryRun = resolve
  })
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ counts: {}, rows: [
      { paper_id: 'paper-a', review_status: 'triage_ready', paper_status: 'publication_draft', project_name: 'Paper A' },
      { paper_id: 'paper-b', review_status: 'triage_ready', paper_status: 'publication_draft', project_name: 'Paper B' },
    ] }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ item: { paper_id: 'paper-a', project_name: 'Paper A', review_status: 'triage_ready', paper_status: 'publication_draft' }, checklist: { items: [] } }), { status: 200 }))
    .mockImplementationOnce(() => dryRunPromise)
    .mockResolvedValueOnce(new Response(JSON.stringify({ item: { paper_id: 'paper-b', project_name: 'Paper B', review_status: 'triage_ready', paper_status: 'publication_draft' }, checklist: { items: [] } }), { status: 200 }))
    .mockResolvedValue(new Response(JSON.stringify({ counts: {}, rows: [{ paper_id: 'paper-a' }, { paper_id: 'paper-b' }] }), { status: 200 }))

  renderWithClient(<AutomationPage paperId="paper-a" />)

  await screen.findByLabelText('Automation detail')
  fireEvent.click(screen.getByRole('button', { name: 'Dry-run finalization package' }))
  fireEvent.click(screen.getByText('Paper B'))
  await waitFor(() => {
    expect(fetchMock).toHaveBeenCalledWith('/control/api/publication-automation/paper-b', expect.any(Object))
  })

  resolveDryRun(new Response(JSON.stringify({ dry_run: true, paper_id: 'paper-a' }), { status: 200 }))

  const liveButton = screen.getByRole('button', { name: 'Prepare live finalization package' })
  await waitFor(() => expect(liveButton).toBeDisabled())
  expect(fetchMock).not.toHaveBeenCalledWith(
    '/control/api/publication-automation/paper-b/prepare-finalization-package',
    expect.objectContaining({ method: 'POST' }),
  )
})
