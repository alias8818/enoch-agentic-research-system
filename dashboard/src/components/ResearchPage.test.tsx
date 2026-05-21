import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { saveToken } from '../api/client'
import { ResearchPage } from './ResearchPage'

function renderWithClient(ui: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  saveToken('')
})

it('loads research facility rows and checks provider budget through bounded APIs', async () => {
  saveToken('test-token')
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ counts: { admitted: 1 }, rows: [{ candidate_id: 'cand-1', status: 'admitted', title: 'Candidate one' }] }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true, remaining_credits: 10, rolling_remaining: 99 }), { status: 200 }))

  renderWithClient(<ResearchPage />)

  await screen.findByText('Candidate one')
  fireEvent.click(screen.getByRole('button', { name: 'Check provider budget' }))
  await screen.findByText('Provider budget result')

  expect(fetchMock).toHaveBeenNthCalledWith(1, '/control/api/research/facility?page_size=50', expect.objectContaining({ headers: { Authorization: 'Bearer test-token' } }))
  expect(fetchMock).toHaveBeenNthCalledWith(2, '/control/api/research/provider-budget?estimated_requests=1&reserve_requests=2', expect.objectContaining({ headers: { Authorization: 'Bearer test-token' } }))
})

it('refreshes research facility rows explicitly from V2', async () => {
  saveToken('test-token')
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ generated_at: '2026-05-21T08:10:00Z', counts: { admitted: 1 }, rows: [{ candidate_id: 'cand-old', status: 'admitted', title: 'Old candidate' }] }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ generated_at: '2026-05-21T08:12:00Z', counts: { admitted: 1 }, rows: [{ candidate_id: 'cand-fresh', status: 'admitted', title: 'Fresh candidate' }] }), { status: 200 }))

  renderWithClient(<ResearchPage />)
  await screen.findByText('Old candidate')

  fireEvent.click(screen.getByRole('button', { name: 'Refresh candidates' }))

  await screen.findByText('Fresh candidate')
  expect(screen.getByText('Last loaded 2026-05-21T08:12:00Z')).toBeInTheDocument()
  expect(fetchMock).toHaveBeenCalledTimes(2)
})

it('dry-runs the bounded research cycle without live enablement', async () => {
  vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ counts: {}, rows: [] }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true, action: 'research_cycle_dry_run' }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ counts: {}, rows: [] }), { status: 200 }))

  renderWithClient(<ResearchPage />)

  await screen.findByText('No research candidates returned.')
  fireEvent.click(screen.getByRole('button', { name: 'Dry-run bounded cycle' }))
  await screen.findByText('Run-cycle result')

  expect(globalThis.fetch).toHaveBeenNthCalledWith(2, '/control/api/research/run-cycle', expect.objectContaining({
    method: 'POST',
    body: expect.stringContaining('"dry_run":true'),
  }))
})


it('uses a dialog before running a bounded live research cycle', async () => {
  const confirmSpy = vi.spyOn(window, 'confirm')
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ counts: {}, rows: [] }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true, action: 'research_cycle_live' }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ counts: {}, rows: [] }), { status: 200 }))

  renderWithClient(<ResearchPage />)

  await screen.findByText('No research candidates returned.')
  fireEvent.click(screen.getByRole('button', { name: 'Run one bounded cycle' }))

  const dialog = await screen.findByRole('dialog', { name: 'Run one bounded live cycle?' })
  expect(dialog).toHaveTextContent('will not dispatch')
  expect(confirmSpy).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: 'Run bounded cycle' }))

  await screen.findByText('Run-cycle result')
  await waitFor(() => expect(fetchMock).toHaveBeenNthCalledWith(2, '/control/api/research/run-cycle', expect.objectContaining({
    method: 'POST',
    body: expect.stringContaining('"dry_run":false'),
  })))
})

it('dry-runs and confirms admitted candidate promotion without dispatching', async () => {
  const confirmSpy = vi.spyOn(window, 'confirm')
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ counts: { admitted: 1 }, rows: [{ candidate_id: 'cand-1', status: 'admitted', admission_decision: 'admitted', admitted_idea_id: '', title: 'Candidate one' }] }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true, action: 'dry_run_promote_candidate', candidate_id: 'cand-1', title: 'Candidate one', reason: 'candidate can be promoted' }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true, action: 'promote_candidate', candidate_id: 'cand-1', idea_id: 'cand-1', queued_count: 1, dispatch_started: false, reason: 'promoted without dispatch' }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ counts: {}, rows: [] }), { status: 200 }))

  renderWithClient(<ResearchPage />)

  fireEvent.click(await screen.findByText('Candidate one'))
  expect(screen.getByText('cand-1')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Dry-run promote selected' }))

  await screen.findByText('Candidate promotion dry-run')
  expect(fetchMock).toHaveBeenNthCalledWith(2, '/control/api/research/promote-candidate', expect.objectContaining({
    method: 'POST',
    body: JSON.stringify({ candidate_id: 'cand-1', dry_run: true, requested_by: 'dashboard-v2' }),
  }))

  fireEvent.click(screen.getByRole('button', { name: 'Promote selected candidate' }))
  const dialog = await screen.findByRole('dialog', { name: 'Promote admitted candidate?' })
  expect(dialog).toHaveTextContent('will not dispatch')
  expect(confirmSpy).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: 'Promote candidate' }))

  await screen.findByText('Candidate promotion result')
  await waitFor(() => expect(fetchMock).toHaveBeenNthCalledWith(3, '/control/api/research/promote-candidate', expect.objectContaining({
    method: 'POST',
    body: JSON.stringify({ candidate_id: 'cand-1', dry_run: false, requested_by: 'dashboard-v2' }),
  })))
})
