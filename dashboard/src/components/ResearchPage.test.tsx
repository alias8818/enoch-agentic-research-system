import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
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
