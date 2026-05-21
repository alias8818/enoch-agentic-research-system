import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { saveToken } from '../api/client'
import { AutomationPage } from './AutomationPage'

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
  const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ counts: { triage_ready: 1 }, rows: [{ paper_id: 'paper-1', review_status: 'triage_ready', paper_status: 'publication_draft', project_name: 'Paper project' }] }), { status: 200 }))

  renderWithClient(<AutomationPage />)

  await screen.findByText('Paper project')
  expect(screen.getByRole('link', { name: /paper-1/ })).toHaveAttribute('href', '/control/dashboard-v2#automation:paper-1')
  expect(fetchMock).toHaveBeenCalledWith('/control/api/publication-automation?page_size=50&paper_status=publication_draft&sort=-rank_score', expect.objectContaining({ headers: { Authorization: 'Bearer test-token' } }))
})

it('opens automation detail from selected table rows', async () => {
  saveToken('test-token')
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ counts: {}, rows: [{ paper_id: 'paper-select', review_status: 'triage_ready', paper_status: 'publication_draft', project_name: 'Selectable paper' }] }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ item: { paper_id: 'paper-select', project_name: 'Selectable paper', review_status: 'triage_ready', paper_status: 'publication_draft', rank_score: 77, rank_reasons: ['row selected'] }, checklist: { items: [{ item_id: 'evidence', label: 'Evidence bundle present', status: 'pending' }] } }), { status: 200 }))

  renderWithClient(<AutomationPage />)

  fireEvent.click(await screen.findByText('Selectable paper'))

  await screen.findByLabelText('Automation detail')
  expect(screen.getByLabelText('Targeted paper')).toHaveTextContent('paper-select')
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
    .mockResolvedValueOnce(new Response(JSON.stringify({ dry_run: true, package_path: '/tmp/package.json', paper_id: 'paper-target' }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ counts: {}, rows: [{ paper_id: 'paper-target' }] }), { status: 200 }))

  renderWithClient(<AutomationPage paperId="paper-target" />)

  await screen.findByLabelText('Automation detail')
  await screen.findByText('Evidence bundle present')
  await screen.findByText('positive evidence')
  const targeted = screen.getByLabelText('Targeted paper')
  expect(targeted).toHaveTextContent('Targeted paper')
  expect(targeted).toHaveTextContent('paper-target')
  fireEvent.click(screen.getByRole('button', { name: 'Dry-run finalization package' }))

  await screen.findByText('Finalization dry-run result')
  expect(fetchMock).toHaveBeenNthCalledWith(2, '/control/api/publication-automation/paper-target', expect.any(Object))
  expect(fetchMock).toHaveBeenNthCalledWith(3, '/control/api/paper-reviews/paper-target/prepare-finalization-package', expect.objectContaining({ method: 'POST', body: expect.stringContaining('"dry_run":true') }))
})

it('updates automation checklist items through dialog-confirmed V2 mutation', async () => {
  const confirmSpy = vi.spyOn(window, 'confirm')
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ counts: {}, rows: [{ paper_id: 'paper-target', review_status: 'triage_ready', paper_status: 'publication_draft', project_name: 'Target paper' }] }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ item: { paper_id: 'paper-target', project_name: 'Target paper', review_status: 'triage_ready', paper_status: 'publication_draft', rank_score: 91 }, checklist: { items: [{ item_id: 'evidence', label: 'Evidence bundle present', status: 'pending', note: '' }] } }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true, paper_id: 'paper-target', item_id: 'evidence', status: 'pass' }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ item: { paper_id: 'paper-target', project_name: 'Target paper', review_status: 'triage_ready', paper_status: 'publication_draft', rank_score: 91 }, checklist: { items: [{ item_id: 'evidence', label: 'Evidence bundle present', status: 'pass', note: 'Marked passed from dashboard-v2' }] } }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ counts: {}, rows: [{ paper_id: 'paper-target' }] }), { status: 200 }))

  renderWithClient(<AutomationPage paperId="paper-target" />)

  await screen.findByText('Evidence bundle present')
  fireEvent.click(screen.getByRole('button', { name: 'Mark evidence pass' }))

  expect(screen.getByRole('dialog', { name: 'Mark checklist item passed?' })).toBeInTheDocument()
  expect(confirmSpy).not.toHaveBeenCalled()

  fireEvent.click(screen.getByRole('button', { name: 'Mark passed' }))

  await screen.findByText('Checklist update result')
  expect(fetchMock).toHaveBeenNthCalledWith(3, '/control/api/publication-automation/paper-target/checklist/evidence', expect.objectContaining({
    method: 'POST',
    body: expect.stringContaining('"status":"pass"'),
  }))
  expect(fetchMock).toHaveBeenNthCalledWith(3, '/control/api/publication-automation/paper-target/checklist/evidence', expect.objectContaining({
    body: expect.stringContaining('"note":"Marked passed from dashboard-v2"'),
  }))
})

it('dry-runs rewrite batch and finalization package without live rewrite', async () => {
  vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ counts: {}, rows: [{ paper_id: 'paper-1', review_status: 'triage_ready', paper_status: 'publication_draft', project_name: 'Paper project' }] }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ dry_run: true, matched: 1, rows: [{ paper_id: 'paper-1', action: 'would_rewrite' }] }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ dry_run: true, package_path: '/tmp/package.json' }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ counts: {}, rows: [{ paper_id: 'paper-1' }] }), { status: 200 }))

  renderWithClient(<AutomationPage />)

  await screen.findByText('Paper project')
  fireEvent.click(screen.getByRole('button', { name: 'Dry-run rewrite batch' }))
  await screen.findByText('Rewrite dry-run result')
  fireEvent.click(screen.getByRole('button', { name: 'Dry-run finalization package' }))
  await screen.findByText('Finalization dry-run result')

  expect(globalThis.fetch).toHaveBeenNthCalledWith(2, '/control/api/paper-reviews/rewrite-batch', expect.objectContaining({ method: 'POST', body: expect.stringContaining('"dry_run":true') }))
  expect(globalThis.fetch).toHaveBeenNthCalledWith(3, '/control/api/paper-reviews/paper-1/prepare-finalization-package', expect.objectContaining({ method: 'POST', body: expect.stringContaining('"dry_run":true') }))
})
