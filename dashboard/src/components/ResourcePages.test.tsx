import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { saveToken } from '../api/client'
import { EventsPage, PapersPage, QueuePage } from './ResourcePages'

function renderWithClient(ui: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

afterEach(() => {
  vi.restoreAllMocks()
  saveToken('')
})

it('loads queue rows from the V1 queue endpoint with the route status', async () => {
  saveToken('test-token')
  const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ rows: [{ project_id: 'p1', status: 'queued', title: 'Queue item' }] }), { status: 200 }))

  renderWithClient(<QueuePage route={{ page: 'queue', status: 'queued', hash: '#queue:queued' }} />)

  await screen.findByText('Queue item')
  expect(fetchMock).toHaveBeenCalledWith('/control/api/v1/queue?queue=all&page_size=50&sort=priority&status=queued', expect.objectContaining({ headers: { Authorization: 'Bearer test-token' } }))
})

it('loads papers and events as first-class V2 subviews', async () => {
  vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ rows: [{ paper_id: 'paper-1', status: 'publication_draft', title: 'Draft paper' }] }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ rows: [{ id: 7, event_type: 'Queue Alert', summary: 'Alert summary' }] }), { status: 200 }))

  renderWithClient(<PapersPage route={{ page: 'papers', status: 'publication_draft', hash: '#papers?status=publication_draft' }} />)
  await screen.findByText('Draft paper')

  renderWithClient(<EventsPage />)
  await screen.findByText('Alert summary')

  await waitFor(() => expect(globalThis.fetch).toHaveBeenCalledTimes(2))
})
