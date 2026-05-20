import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { saveToken } from '../api/client'
import { EventsPage, PapersPage, QueuePage } from './ResourcePages'

function renderWithClient(ui: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

afterEach(() => {
  cleanup()
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


it('opens queue and paper detail panels from selected rows', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ rows: [{ project_id: 'project-1', status: 'queued', title: 'Queue item' }] }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ project_id: 'project-1', project: { project_name: 'Detailed project' } }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ rows: [{ paper_id: 'paper-1', status: 'publication_draft', title: 'Draft paper' }] }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ paper_id: 'paper-1', paper: { paper_title: 'Detailed paper' } }), { status: 200 }))

  renderWithClient(<QueuePage route={{ page: 'queue', status: 'queued', hash: '#queue:queued' }} />)
  fireEvent.click(await screen.findByText('Queue item'))
  await screen.findByText(/Detailed project/)

  renderWithClient(<PapersPage route={{ page: 'papers', status: '', hash: '#papers' }} />)
  fireEvent.click(await screen.findByText('Draft paper'))
  await screen.findByText(/Detailed paper/)

  expect(fetchMock).toHaveBeenNthCalledWith(2, '/control/api/v1/projects/project-1', expect.any(Object))
  expect(fetchMock).toHaveBeenNthCalledWith(4, '/control/api/v1/papers/paper-1', expect.any(Object))
})

it('shows raw event detail without inventing a missing event endpoint', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(new Response(JSON.stringify({ rows: [{ id: 9, event_type: 'Queue Alert', summary: 'Alert summary', payload: { reason: 'blocked' } }] }), { status: 200 }))

  renderWithClient(<EventsPage />)
  fireEvent.click(await screen.findByText('Alert summary'))

  expect(await screen.findByLabelText('Dashboard detail panel')).toHaveTextContent('Queue Alert')
  expect(globalThis.fetch).toHaveBeenCalledTimes(1)
})
