import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { saveToken } from '../api/client'
import { SAVED_TABLE_FILTERS_STORAGE_KEY } from '../savedTableFilters'
import { fetchMockCallUrl, fetchMockRequestBody } from '../test/fetchMockBody'
import { CorpusPage, EventsPage, IntakePage, ObservabilityPage, PapersPage, ProjectsPage, QueuePage, RunsPage } from './ResourcePages'

function renderWithClient(ui: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

function fetchMockUrl(fetchMock: Parameters<typeof fetchMockCallUrl>[0], callIndex: number): URL {
  return new URL(fetchMockCallUrl(fetchMock, callIndex), 'https://enoch.local')
}

function expectParam(url: URL, name: string, value: string) {
  expect(url.searchParams.get(name)).toBe(value)
}

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  saveToken('')
  globalThis.localStorage.removeItem(SAVED_TABLE_FILTERS_STORAGE_KEY)
})

it('loads queue rows from the V1 queue endpoint with the route queue slice', async () => {
  saveToken('test-token')
  const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ rows: [{ project_id: 'p1', status: 'queued', title: 'Queue item' }], page: { returned: 1, has_more: false } }), { status: 200 }))

  renderWithClient(<QueuePage route={{ page: 'queue', status: 'queued', search: '', hash: '#queue:queued' }} />)

  await screen.findByText('Queue item')
  expect(screen.getByRole('link', { name: /p1/ })).toHaveAttribute('href', '/control/dashboard-v2#project:p1')
  expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/control/api/v1/queue?'), expect.objectContaining({ headers: { Authorization: 'Bearer test-token' } }))
  const url = fetchMockUrl(fetchMock, 0)
  expect(url.pathname).toBe('/control/api/v1/queue')
  expectParam(url, 'queue', 'queued')
  expectParam(url, 'page_size', '50')
  expectParam(url, 'sort', 'priority')
  expect(url.searchParams.get('status')).toBeNull()
})




it('refreshes queue rows explicitly from the V2 page', async () => {
  saveToken('test-token')
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ generated_at: '2026-05-21T05:00:00Z', rows: [{ project_id: 'queued-project', status: 'queued', title: 'Queued item' }], page: { returned: 1, has_more: false } }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ generated_at: '2026-05-21T05:01:00Z', rows: [{ project_id: 'fresh-project', status: 'queued', title: 'Fresh item' }], page: { returned: 1, has_more: false } }), { status: 200 }))

  renderWithClient(<QueuePage route={{ page: 'queue', status: 'queued', search: '', hash: '#queue:queued' }} />)
  await screen.findByText('Queued item')

  fireEvent.click(screen.getByRole('button', { name: 'Refresh rows' }))

  await screen.findByText('Fresh item')
  expect(screen.getByText('Last loaded 2026-05-21T05:01:00Z')).toBeInTheDocument()
  expect(fetchMock).toHaveBeenCalledTimes(2)
})

it('refreshes project rows explicitly from the V2 page', async () => {
  saveToken('test-token')
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ generated_at: '2026-05-21T06:00:00Z', rows: [{ project_id: 'project-old', project_name: 'Old project', origin_idea_status: 'testing' }], page: { returned: 1, has_more: false } }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ generated_at: '2026-05-21T06:03:00Z', rows: [{ project_id: 'project-fresh', project_name: 'Fresh project', origin_idea_status: 'testing' }], page: { returned: 1, has_more: false } }), { status: 200 }))

  renderWithClient(<ProjectsPage route={{ page: 'projects', status: 'testing', search: '', hash: '#projects?status=testing' }} />)
  await screen.findByText('Old project')

  fireEvent.click(screen.getByRole('button', { name: 'Refresh rows' }))

  await screen.findByText('Fresh project')
  expect(screen.getByText('Last loaded 2026-05-21T06:03:00Z')).toBeInTheDocument()
  expect(fetchMock).toHaveBeenCalledTimes(2)
})

it('refreshes event rows explicitly from the V2 page', async () => {
  saveToken('test-token')
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ generated_at: '2026-05-21T07:00:00Z', rows: [{ id: 7, event_type: 'Queue Alert', summary: 'Old alert' }], page: { returned: 1, has_more: false } }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ generated_at: '2026-05-21T07:02:00Z', rows: [{ id: 8, event_type: 'worker.callback', summary: 'Fresh callback' }], page: { returned: 1, has_more: false } }), { status: 200 }))

  renderWithClient(<EventsPage />)
  await screen.findByText('Old alert')

  fireEvent.click(screen.getByRole('button', { name: 'Refresh rows' }))

  await screen.findByText('Fresh callback')
  expect(screen.getByText('Last loaded 2026-05-21T07:02:00Z')).toBeInTheDocument()
  expect(fetchMock).toHaveBeenCalledTimes(2)
})

it('syncs route-derived status changes into resource page backend filters', async () => {
  saveToken('test-token')
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ rows: [{ project_id: 'queued-project', status: 'queued', title: 'Queued item' }], page: { returned: 1, has_more: false } }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ rows: [{ project_id: 'active-project', status: 'active', title: 'Active item' }], page: { returned: 1, has_more: false } }), { status: 200 }))

  const { rerender } = renderWithClient(<QueuePage route={{ page: 'queue', status: 'queued', search: '', hash: '#queue:queued' }} />)
  await screen.findByText('Queued item')

  rerender(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <QueuePage route={{ page: 'queue', status: 'active', search: '', hash: '#queue:active' }} />
    </QueryClientProvider>,
  )

  await screen.findByText('Active item')
  expect(screen.getByLabelText(/Status/i)).toHaveValue('active')
  const first = fetchMockUrl(fetchMock, 0)
  const second = fetchMockUrl(fetchMock, 1)
  expectParam(first, 'queue', 'queued')
  expect(new URL(first, 'https://enoch.local').searchParams.get('status')).toBeNull()
  expectParam(second, 'queue', 'active')
  expect(new URL(second, 'https://enoch.local').searchParams.get('status')).toBeNull()
})

it('loads active lane rows through the backend queue slice', async () => {
  saveToken('test-token')
  const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(new Response(JSON.stringify({
    counts: { active: 2, queued: 47 },
    rows: [{ project_id: 'active-lane-row', status: 'awaiting_wake', title: 'Active lane row' }],
    page: { returned: 1, has_more: false },
  }), { status: 200 }))

  renderWithClient(<QueuePage route={{ page: 'queue', status: 'active', search: '', hash: '#queue:active' }} />)

  expect(await screen.findByText('Active lane row')).toBeInTheDocument()
  const url = fetchMockUrl(fetchMock, 0)
  expectParam(url, 'queue', 'active')
  expect(url.searchParams.get('status')).toBeNull()
  expect(screen.queryByText('Queue is empty')).not.toBeInTheDocument()
})

it('checks selected queued rows with dispatch-one dry-run only', async () => {
  saveToken('test-token')
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ rows: [{ project_id: 'project-1', status: 'queued', machine_target: 'gb10', title: 'Queue item' }], page: { returned: 1, has_more: false } }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ project_id: 'project-1', project: { project_name: 'Queue item' } }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true, action: 'dry_run_dispatch_one', reason: 'dry-run selected explicit queued candidate; no state mutated', candidate: { project_id: 'project-1' } }), { status: 200 }))

  renderWithClient(<QueuePage route={{ page: 'queue', status: 'queued', search: '', hash: '#queue:queued' }} />)

  fireEvent.click(await screen.findByText('Queue item'))
  await screen.findByLabelText('Dashboard detail panel')
  fireEvent.click(screen.getByRole('button', { name: /Check selected dispatch/i }))

  await screen.findByText('dry-run selected explicit queued candidate; no state mutated')
  expect(fetchMock).toHaveBeenNthCalledWith(3, '/control/dispatch-one', expect.objectContaining({
    method: 'POST',
    headers: { Authorization: 'Bearer test-token', 'Content-Type': 'application/json' },
  }))
  expect(JSON.parse(fetchMockRequestBody(fetchMock, 2))).toEqual({
    project_id: 'project-1',
    dry_run: true,
    requested_by: 'dashboard-v2',
    force_preflight: true,
  })
  expect(screen.getByText('Selected work')).toBeInTheDocument()
  expect(screen.getByText('Lane / target')).toBeInTheDocument()
  expect(screen.getAllByText('Next safe action').length).toBeGreaterThan(0)
  expect(screen.getByText('Raw JSON')).toBeInTheDocument()
})

it('live-dispatches a selected queued row only after dry-run and dialog confirmation', async () => {
  saveToken('test-token')
  const confirmSpy = vi.spyOn(globalThis, 'confirm')
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ rows: [{ project_id: 'project-live', status: 'queued', machine_target: 'gb10', title: 'Live queue item' }], page: { returned: 1, has_more: false } }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ project_id: 'project-live', project: { project_name: 'Live queue item' } }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true, action: 'dry_run_dispatch_one', reason: 'dry-run selected explicit queued candidate', candidate: { project_id: 'project-live' } }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true, action: 'live_dispatch_one', reason: 'live dispatch started selected queued candidate', candidate: { project_id: 'project-live' } }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ generated_at: '2026-05-21T11:00:00Z', rows: [{ project_id: 'project-other', status: 'queued', machine_target: 'gb10', title: 'Fresh queue item' }], page: { returned: 1, has_more: false } }), { status: 200 }))

  renderWithClient(<QueuePage route={{ page: 'queue', status: 'queued', search: '', hash: '#queue:queued' }} />)

  fireEvent.click(await screen.findByText('Live queue item'))
  await screen.findByLabelText('Dashboard detail panel')
  expect(screen.getByRole('button', { name: 'Dispatch selected project' })).toBeDisabled()

  fireEvent.click(screen.getByRole('button', { name: /Check selected dispatch/i }))
  await screen.findByText('dry-run selected explicit queued candidate')
  fireEvent.click(screen.getByRole('button', { name: 'Dispatch selected project' }))

  expect(await screen.findByRole('dialog', { name: 'Dispatch selected project?' })).toBeInTheDocument()
  expect(confirmSpy).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: 'Dispatch selected' }))

  await screen.findByText('live dispatch started selected queued candidate')
  expect(fetchMock).toHaveBeenNthCalledWith(4, '/control/dispatch-one', expect.objectContaining({
    method: 'POST',
    headers: { Authorization: 'Bearer test-token', 'Content-Type': 'application/json' },
  }))
  expect(JSON.parse(fetchMockRequestBody(fetchMock, 3))).toEqual({
    project_id: 'project-live',
    dry_run: false,
    requested_by: 'dashboard-v2',
    force_preflight: true,
  })
  await screen.findByText('Fresh queue item')
  expect(fetchMock).toHaveBeenNthCalledWith(5, expect.stringContaining('/control/api/v1/queue?'), expect.any(Object))
})

it('invalidates selected queue dispatch when refreshed row state changes', async () => {
  saveToken('test-token')
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ generated_at: '2026-05-21T11:00:00Z', rows: [{ project_id: 'project-stale', status: 'queued', machine_target: 'gb10', title: 'Stale queue item', updated_at: '2026-05-21T11:00:00Z' }], page: { returned: 1, has_more: false } }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ project_id: 'project-stale', project: { project_name: 'Stale queue item' } }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true, action: 'dry_run_dispatch_one', reason: 'dry-run selected explicit queued candidate', candidate: { project_id: 'project-stale' } }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ generated_at: '2026-05-21T11:01:00Z', rows: [{ project_id: 'project-stale', status: 'active', machine_target: 'gb10', title: 'Stale queue item', updated_at: '2026-05-21T11:01:00Z' }], page: { returned: 1, has_more: false } }), { status: 200 }))

  renderWithClient(<QueuePage route={{ page: 'queue', status: 'queued', search: '', hash: '#queue:queued' }} />)

  fireEvent.click(await screen.findByText('Stale queue item'))
  await screen.findByLabelText('Dashboard detail panel')
  fireEvent.click(screen.getByRole('button', { name: /Check selected dispatch/i }))

  await screen.findByText('dry-run selected explicit queued candidate')
  expect(screen.getByRole('button', { name: 'Dispatch selected project' })).toBeEnabled()

  fireEvent.click(screen.getByRole('button', { name: 'Refresh rows' }))
  await screen.findByText('Last loaded 2026-05-21T11:01:00Z')

  expect(fetchMock).toHaveBeenCalledTimes(4)
  expect(screen.getByRole('button', { name: 'Dispatch selected project' })).toBeDisabled()
  expect(screen.getByText('Dispatch selected project disabled: selected row changed; run Check selected dispatch again.')).toBeInTheDocument()
})

it('loads project discovery rows from the V1 projects endpoint', async () => {
  saveToken('test-token')
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ rows: [{ project_id: 'project-1', project_name: 'Trace Oracle', origin_idea_status: 'testing', queue_status: 'queued', latest_run_state: 'running' }], page: { returned: 1, has_more: false } }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ project_id: 'project-1', project: { project_name: 'Trace Oracle' } }), { status: 200 }))

  renderWithClient(<ProjectsPage route={{ page: 'projects', status: 'testing', search: '', hash: '#projects?status=testing' }} />)

  await screen.findByText('Trace Oracle')
  expect(screen.getByRole('link', { name: /project-1/ })).toHaveAttribute('href', '/control/dashboard-v2#project:project-1')
  const url = fetchMockUrl(fetchMock, 0)
  expect(url.pathname).toBe('/control/api/v1/projects')
  expectParam(url, 'status', 'testing')
  expectParam(url, 'page_size', '50')
  expectParam(url, 'sort', 'recent')

  fireEvent.click(screen.getByText('Trace Oracle'))
  await screen.findByLabelText('Dashboard detail panel')
  expect(fetchMock).toHaveBeenNthCalledWith(2, '/control/api/v1/projects/project-1', expect.any(Object))
})

it('explains event read-model failures without dumping a generic 500 card', async () => {
  saveToken('test-token')
  vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(new Response(JSON.stringify({ detail: 'server error' }), { status: 500 }))

  renderWithClient(<EventsPage route={{ page: 'events', eventType: '', search: '', hash: '#events' }} />)

  expect(await screen.findByText('Events could not load')).toBeInTheDocument()
  expect(screen.getByText(/Dispatch impact:/)).toBeInTheDocument()
  expect(screen.getByText('Retry events')).toBeInTheDocument()
  expect(screen.queryByText('Open legacy events')).not.toBeInTheDocument()
  expect(screen.queryByText(/V2 data unavailable/)).not.toBeInTheDocument()
})

it('explains idle queue slices when no rows are returned', async () => {
  saveToken('test-token')
  vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(new Response(JSON.stringify({ rows: [], page: { returned: 0, has_more: false } }), { status: 200 }))

  renderWithClient(<QueuePage route={{ page: 'queue', status: 'queued', search: '', hash: '#queue:queued' }} />)

  expect(await screen.findByText('No queued work right now')).toBeInTheDocument()
  expect(screen.getByText(/empty by design/i)).toBeInTheDocument()
})

it('explains queue endpoint failures with retry guidance', async () => {
  saveToken('test-token')
  vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(new Response(JSON.stringify({ detail: 'server error' }), { status: 500 }))

  renderWithClient(<QueuePage route={{ page: 'queue', status: 'queued', search: '', hash: '#queue:queued' }} />)

  expect(await screen.findByText('Queue could not load')).toBeInTheDocument()
  expect(screen.getByText(/Dispatch impact:/)).toBeInTheDocument()
  expect(screen.getByText('Retry queue')).toBeInTheDocument()
  expect(screen.queryByText(/V2 data unavailable/)).not.toBeInTheDocument()
})

it('loads runs from the V1 runs endpoint with state filters and detail fetches', async () => {
  saveToken('test-token')
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ rows: [{ run_id: 'run-1', project_id: 'project-1', state: 'running', gate_state: 'awaiting_wake', current_activity: 'testing' }], page: { returned: 1, has_more: false } }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ run_id: 'run-1', run: { run_id: 'run-1', project_id: 'project-1', state: 'running', current_activity: 'testing' } }), { status: 200 }))

  renderWithClient(<RunsPage route={{ page: 'runs', state: 'running', search: '', hash: '#runs:running' }} />)

  await screen.findByText('run-1')
  expect(screen.getByRole('link', { name: /run-1/ })).toHaveAttribute('href', '/control/dashboard-v2#run:run-1')
  const url = fetchMockUrl(fetchMock, 0)
  expect(url.pathname).toBe('/control/api/v1/runs')
  expectParam(url, 'state', 'running')
  expectParam(url, 'page_size', '50')
  expectParam(url, 'sort', 'recent')
  expect(url.searchParams.get('status')).toBeNull()

  fireEvent.click(screen.getByText('testing'))
  await screen.findByText('testing')
  expect(fetchMock).toHaveBeenNthCalledWith(2, '/control/api/v1/runs/run-1', expect.any(Object))
})

it('loads papers and events as first-class V2 subviews', async () => {
  vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ rows: [{ paper_id: 'paper-1', status: 'publication_draft', title: 'Draft paper' }], page: { returned: 1, has_more: false } }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ rows: [{ id: 7, event_type: 'Queue Alert', summary: 'Alert summary' }], page: { returned: 1, has_more: false } }), { status: 200 }))

  renderWithClient(<PapersPage route={{ page: 'papers', status: 'publication_draft', search: '', hash: '#papers?status=publication_draft' }} />)
  await screen.findByText('Draft paper')
  expect(screen.getByRole('link', { name: /paper-1/ })).toHaveAttribute('href', '/control/dashboard-v2#paper:paper-1')

  renderWithClient(<EventsPage />)
  await screen.findByText('Alert summary')

  await waitFor(() => expect(globalThis.fetch).toHaveBeenCalledTimes(2))
})

it('applies queue filters and follows the backend cursor without inventing paging', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ rows: [{ project_id: 'p1', status: 'queued', title: 'First item' }], page: { returned: 1, has_more: true, next_cursor: 'cursor-2' } }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ rows: [{ project_id: 'p2', status: 'active', title: 'Filtered item' }], page: { returned: 1, has_more: true, next_cursor: 'cursor-3' } }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ rows: [{ project_id: 'p3', status: 'active', title: 'Next page item' }], page: { returned: 1, has_more: false } }), { status: 200 }))

  renderWithClient(<QueuePage route={{ page: 'queue', status: '', search: '', hash: '#queue' }} />)
  await screen.findByText('First item')

  fireEvent.change(screen.getByLabelText(/Search/i), { target: { value: 'oracle' } })
  fireEvent.change(screen.getByLabelText(/Status/i), { target: { value: 'active' } })
  fireEvent.change(screen.getByLabelText(/Size/i), { target: { value: '25' } })
  fireEvent.click(screen.getByRole('button', { name: /Apply filters/i }))
  await screen.findByText('Filtered item')

  let url = fetchMockUrl(fetchMock, 1)
  expectParam(url, 'search', 'oracle')
  expectParam(url, 'queue', 'active')
  expect(url.searchParams.get('status')).toBeNull()
  expectParam(url, 'page_size', '25')
  expect(url.searchParams.get('cursor')).toBeNull()

  fireEvent.click(screen.getByRole('button', { name: /Next page/i }))
  await screen.findByText('Next page item')

  url = fetchMockUrl(fetchMock, 2)
  expectParam(url, 'cursor', 'cursor-3')
  expectParam(url, 'search', 'oracle')
  expectParam(url, 'queue', 'active')
  expect(url.searchParams.get('status')).toBeNull()
})

it('loads saved queue filter presets from localStorage and applies them to the queue read model', async () => {
  globalThis.localStorage.setItem(SAVED_TABLE_FILTERS_STORAGE_KEY, JSON.stringify({
    queue: [{ id: 'preset-1', name: 'Queued watch', search: 'oracle', status: 'queued', pageSize: '25' }],
  }))
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ rows: [{ project_id: 'p1', status: 'queued', title: 'First item' }], page: { returned: 1, has_more: false } }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ rows: [{ project_id: 'p2', status: 'queued', title: 'Saved filter item' }], page: { returned: 1, has_more: false } }), { status: 200 }))

  renderWithClient(<QueuePage route={{ page: 'queue', status: '', search: '', hash: '#queue' }} />)
  await screen.findByText('First item')

  fireEvent.change(screen.getByLabelText(/Saved filters/i), { target: { value: 'preset-1' } })
  await screen.findByText('Saved filter item')

  const url = fetchMockUrl(fetchMock, 1)
  expectParam(url, 'search', 'oracle')
  expectParam(url, 'queue', 'queued')
  expect(url.searchParams.get('status')).toBeNull()
  expectParam(url, 'page_size', '25')
})

it('saves the current queue filter draft as a local preset', async () => {
  vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ rows: [{ project_id: 'p1', status: 'queued', title: 'First item' }], page: { returned: 1, has_more: false } }), { status: 200 }))

  renderWithClient(<QueuePage route={{ page: 'queue', status: '', search: '', hash: '#queue' }} />)
  await screen.findByText('First item')

  fireEvent.change(screen.getByLabelText(/Search/i), { target: { value: 'oracle' } })
  fireEvent.change(screen.getByLabelText(/Status/i), { target: { value: 'queued' } })
  fireEvent.click(screen.getByRole('button', { name: /Save current/i }))
  fireEvent.change(screen.getByLabelText(/Preset name/i), { target: { value: 'Queued watch' } })
  fireEvent.click(screen.getByRole('button', { name: /Save preset/i }))

  const stored = JSON.parse(globalThis.localStorage.getItem(SAVED_TABLE_FILTERS_STORAGE_KEY) || '{}')
  expect(stored.queue).toEqual([expect.objectContaining({
    name: 'Queued watch',
    search: 'oracle',
    status: 'queued',
    pageSize: '50',
  })])
})



it('keeps visible filter controls synced after reset defaults are applied', async () => {
  vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ paper_pipeline: { publish_ready: 0, published_imported: 0, publication_ready_total: 0 } }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ rows: [{ paper_id: 'paper-draft', status: 'publication_draft', title: 'Draft paper' }], page: { returned: 1, has_more: false } }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ rows: [{ paper_id: 'paper-review', status: 'draft_review', title: 'Review paper' }], page: { returned: 1, has_more: false } }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ rows: [{ paper_id: 'paper-reset', status: 'publication_draft', title: 'Reset paper' }], page: { returned: 1, has_more: false } }), { status: 200 }))

  renderWithClient(<CorpusPage />)
  await screen.findByText('Draft paper')

  fireEvent.change(screen.getByLabelText(/Status/i), { target: { value: 'draft_review' } })
  fireEvent.click(screen.getByRole('button', { name: /Apply filters/i }))
  await screen.findByText('Review paper')

  fireEvent.click(screen.getByRole('button', { name: /Reset/i }))
  await screen.findByText('Reset paper')

  expect(screen.getByLabelText(/Status/i)).toHaveValue('publication_draft')
})

it('writes applied event filters back to the V2 hash', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ rows: [{ id: 7, event_type: 'Queue Alert', summary: 'Alert summary' }], page: { returned: 1, has_more: false } }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ rows: [{ id: 8, event_type: 'worker.callback', summary: 'Callback summary' }], page: { returned: 1, has_more: false } }), { status: 200 }))

  renderWithClient(<EventsPage />)
  await screen.findByText('Alert summary')
  fireEvent.change(screen.getByLabelText(/Search/i), { target: { value: 'stalled' } })
  fireEvent.change(screen.getByLabelText(/Event type/i), { target: { value: 'worker.callback' } })
  fireEvent.click(screen.getByRole('button', { name: /Apply filters/i }))

  await screen.findByText('Callback summary')
  expect(globalThis.location.hash).toBe('#events?event_type=worker.callback&search=stalled')
  expect(fetchMock).toHaveBeenCalledTimes(2)
})

it('applies paper and event filters to the backed endpoints', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ rows: [{ paper_id: 'paper-1', status: 'publication_draft', title: 'Draft paper' }], page: { returned: 1, has_more: false } }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ rows: [{ paper_id: 'paper-2', status: 'draft_review', title: 'Review paper' }], page: { returned: 1, has_more: false } }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ rows: [{ id: 7, event_type: 'Queue Alert', summary: 'Alert summary' }], page: { returned: 1, has_more: false } }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ rows: [{ id: 8, event_type: 'worker.callback', summary: 'Callback summary' }], page: { returned: 1, has_more: false } }), { status: 200 }))

  renderWithClient(<PapersPage route={{ page: 'papers', status: '', search: '', hash: '#papers' }} />)
  await screen.findByText('Draft paper')
  const workflowNav = screen.getByRole('navigation', { name: 'Papers workflow' })
  expect(within(workflowNav).getByRole('link', { name: /Papers/ })).toHaveAttribute('aria-current', 'page')
  expect(within(workflowNav).getByRole('link', { name: /Paper corpus import/ })).toHaveAttribute('href', '/control/dashboard-v2#corpus')
  expect(within(workflowNav).getByRole('link', { name: /Paper actions/ })).toHaveAttribute('href', '/control/dashboard-v2#automation')

  fireEvent.change(screen.getByLabelText(/Search/i), { target: { value: 'trace' } })
  fireEvent.change(screen.getByLabelText(/Status/i), { target: { value: 'draft_review' } })
  fireEvent.click(screen.getByRole('button', { name: /Apply filters/i }))
  await screen.findByText('Review paper')

  let url = fetchMockUrl(fetchMock, 1)
  expect(url.pathname).toBe('/control/api/v1/papers')
  expectParam(url, 'search', 'trace')
  expectParam(url, 'status', 'draft_review')

  cleanup()
  renderWithClient(<EventsPage />)
  await screen.findByText('Alert summary')
  fireEvent.change(screen.getByLabelText(/Search/i), { target: { value: 'stalled' } })
  fireEvent.change(screen.getByLabelText(/Event type/i), { target: { value: 'worker.callback' } })
  fireEvent.click(screen.getByRole('button', { name: /Apply filters/i }))
  await screen.findByText('Callback summary')

  url = fetchMockUrl(fetchMock, 3)
  expect(url.pathname).toBe('/control/api/v1/events')
  expectParam(url, 'search', 'stalled')
  expectParam(url, 'event_type', 'worker.callback')
  expect(url.searchParams.get('status')).toBeNull()
})

it('opens queue and paper detail panels from selected rows', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ rows: [{ project_id: 'project-1', status: 'queued', title: 'Queue item' }], page: { returned: 1, has_more: false } }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ project_id: 'project-1', project: { project_name: 'Detailed project' } }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ rows: [{ paper_id: 'paper-1', status: 'publication_draft', title: 'Draft paper' }], page: { returned: 1, has_more: false } }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ paper_id: 'paper-1', paper: { paper_title: 'Detailed paper' } }), { status: 200 }))

  renderWithClient(<QueuePage route={{ page: 'queue', status: 'queued', search: '', hash: '#queue:queued' }} />)
  fireEvent.click(await screen.findByText('Queue item'))
  await screen.findByRole('heading', { name: /Detailed project/ })

  renderWithClient(<PapersPage route={{ page: 'papers', status: '', search: '', hash: '#papers' }} />)
  fireEvent.click(await screen.findByText('Draft paper'))
  await screen.findByRole('heading', { name: /Detailed paper/ })

  expect(fetchMock).toHaveBeenNthCalledWith(2, '/control/api/v1/projects/project-1', expect.any(Object))
  expect(fetchMock).toHaveBeenNthCalledWith(4, '/control/api/v1/papers/paper-1', expect.any(Object))
})

it('loads corpus import rows as a first-class V2 subview', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ paper_pipeline: { publish_ready: 0, published_imported: 0, publication_ready_total: 0 } }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ rows: [{ paper_id: 'paper-corpus', project_id: 'project-1', status: 'publication_draft', corpus_imported: false, title: 'Corpus candidate' }], page: { returned: 1, has_more: false } }), { status: 200 }))

  renderWithClient(<CorpusPage />)

  expect(await screen.findByText('Corpus candidate')).toBeInTheDocument()
  const workflowNav = screen.getByRole('navigation', { name: 'Papers workflow' })
  expect(within(workflowNav).getByRole('link', { name: /Paper corpus import/ })).toHaveAttribute('aria-current', 'page')
  expect(within(workflowNav).getByRole('link', { name: /Papers/ })).toHaveAttribute('href', '/control/dashboard-v2#papers')
  expect(within(workflowNav).getByRole('link', { name: /Paper actions/ })).toHaveAttribute('href', '/control/dashboard-v2#automation')
  expect(screen.getByRole('link', { name: /paper-corpus/ })).toHaveAttribute('href', '/control/dashboard-v2#paper:paper-corpus')
  const url = fetchMockUrl(fetchMock, 1)
  expect(url.pathname).toBe('/control/api/v1/papers')
  expectParam(url, 'status', 'publication_draft')
  expectParam(url, 'sort', 'recent')
})

it('shows corpus import movement summary from the overview read model', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ paper_pipeline: { publish_ready: 2, published_imported: 7, publication_ready_total: 9, missing_from_corpus: 2 }, generated_at: '2026-05-21T01:00:00Z' }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ rows: [{ paper_id: 'paper-corpus', project_id: 'project-1', status: 'publication_draft', corpus_imported: false, title: 'Corpus candidate' }], page: { returned: 1, has_more: false } }), { status: 200 }))

  renderWithClient(<CorpusPage />)

  expect(await screen.findByText('Missing corpus import')).toBeInTheDocument()
  expect(screen.getByText('2')).toBeInTheDocument()
  expect(screen.getByText('Already imported')).toBeInTheDocument()
  expect(screen.getByText('7')).toBeInTheDocument()
  expect(screen.getByText('Publication-ready total')).toBeInTheDocument()
  expect(screen.getByText('9')).toBeInTheDocument()
  expect(screen.getByText('Import validation needs corpus autopilot.')).toBeInTheDocument()
  expect(await screen.findByText('Corpus candidate')).toBeInTheDocument()
  expect(fetchMock).toHaveBeenNthCalledWith(1, '/control/api/v1/overview?active_limit=1&event_limit=1', expect.any(Object))
})

it('shows corpus public artifact and validator links', async () => {
  vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ paper_pipeline: { publish_ready: 0, published_imported: 1, publication_ready_total: 1 }, generated_at: '2026-05-21T01:00:00Z' }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({
      rows: [{
        paper_id: 'paper-corpus',
        project_id: 'project-1',
        status: 'publication_draft',
        corpus_imported: true,
        artifact_slug: 'controlled-drill',
        title: 'Corpus candidate',
      }],
      page: { returned: 1, has_more: false },
    }), { status: 200 }))

  renderWithClient(<CorpusPage />)

  expect(await screen.findByRole('link', { name: 'Corpus index (GitHub)' })).toHaveAttribute(
    'href',
    'https://github.com/alias8818/enoch-ai-research-corpus/blob/main/papers/index.json',
  )
  expect(screen.getByRole('link', { name: 'Release validator script' })).toHaveAttribute(
    'href',
    'https://github.com/alias8818/enoch-agentic-research-system/blob/main/scripts/validate_public_release.py',
  )
})

it('shows raw event detail without inventing a missing event endpoint', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(new Response(JSON.stringify({ rows: [{ id: 9, event_type: 'Queue Alert', summary: 'Alert summary', payload: { reason: 'blocked' } }], page: { returned: 1, has_more: false } }), { status: 200 }))

  renderWithClient(<EventsPage />)
  fireEvent.click(await screen.findByText('Alert summary'))

  expect(await screen.findByLabelText('Dashboard detail panel')).toHaveTextContent('Queue Alert')
  expect(globalThis.fetch).toHaveBeenCalledTimes(1)
})

it('loads observability health and memory from backed V1 endpoints', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ generated_at: '2026-05-20T12:00:00Z', route_observability_enabled: true, route_observability_log_configured: false, sentry_enabled: true, sentry_configured: true, sentry_environment: 'production', sentry_release: 'abc1234', latest_route_observation: '{"route":"/control/api/status","status":200}' }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ generated_at: '2026-05-20T12:00:01Z', rss_mib: 128.25, peak_rss_mib: 256.5, warn_threshold_mib: 1024, memory_warn: false, route_observability_enabled: true }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({
      generated_at: '2026-05-20T12:00:02Z',
      status: 'needs_attention',
      model_count: 2,
      unhealthy_count: 0,
      structurally_unhealthy_count: 1,
      models: [{ provider_id: 'synthetic', provider_label: 'Synthetic', model_id: 'owl', label: 'Owl', endpoint_health: 'healthy', format_health: 'healthy', visible_output_health: 'empty', reasoning_budget_health: 'length_limited', latest_finish_reason: 'length', latest_visible_chars: 0, success_rate: 1, format_success_rate: 1, operator_action: 'increase output budget before structured automation', latest_preview: '' }],
      workflow_recommendations: [{
        workflow_id: 'research_generation',
        label: 'Research agents',
        status: 'needs_attention',
        required_contracts: ['candidate_json'],
        recommended_model_pool: ['owl'],
        recommended_default_model: 'owl',
        operator_action: 'prefer owl for Research agents; remove or tune degraded pool entries',
        models: [
          { model_id: 'glm', label: 'GLM', recommendation: 'increase_max_tokens_or_remove', operator_action: 'increase max_tokens or remove GLM for candidate_json until visible structured output passes' },
          { model_id: 'owl', label: 'Owl', recommendation: 'usable', operator_action: 'Owl passed required contract evidence for this workflow' },
        ],
      }],
    }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({
      generated_at: '2026-05-20T12:00:03Z',
      status: 'needs_attention',
      event_count: 4,
      failure_count: 1,
      estimated_cost_usd: 0.0025,
      recent_events: [
        { event_id: 4, event_type: 'llm_harness.output_contract', created_at: '2026-05-20T12:00:03Z', workflow_id: 'idea_generation_enrichment', status: 'rejected', failure_kind: 'schema_mismatch' },
        { event_id: 3, event_type: 'llm_harness.tool_result', created_at: '2026-05-20T12:00:02Z', workflow_id: 'idea_generation_enrichment', tool_name: 'exa_search', status: 'ok', result_count: 3 },
        { event_id: 2, event_type: 'llm_harness.route_decision', created_at: '2026-05-20T12:00:01Z', workflow_id: 'idea_generation_enrichment', selected_provider_id: 'openrouter', selected_model_id: 'kimi-k2', selection_reason: 'cheap model passed required structured-output probe', budget_gate_status: 'ok', health_gate_status: 'ok' },
        { event_id: 1, event_type: 'llm_harness.cost_observation', created_at: '2026-05-20T12:00:00Z', workflow_id: 'idea_generation_enrichment', status: 'ok', estimated_cost_usd: 0.0025, input_token_count: 1200, output_token_count: 180 },
      ],
    }), { status: 200 }))

  renderWithClient(<ObservabilityPage />)

  expect(await screen.findByRole('heading', { name: 'Model usefulness degraded' })).toBeInTheDocument()
  expect(screen.getByText('increase output budget before structured automation')).toBeInTheDocument()
  expect(screen.getByText('length limited')).toBeInTheDocument()
  expect(screen.getByText('empty')).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: 'Workflow model pools need tuning' })).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: 'Research agents' })).toBeInTheDocument()
  expect(screen.getByText('Recommendations use measured prompt-contract probes, not endpoint health alone.')).toBeInTheDocument()
  expect(screen.getByText('prefer owl for Research agents; remove or tune degraded pool entries')).toBeInTheDocument()
  expect(screen.getByText('increase max_tokens or remove GLM for candidate_json until visible structured output passes')).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: 'Harness telemetry needs attention' })).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: 'Latest route decision' })).toBeInTheDocument()
  expect(screen.getByText('openrouter / kimi-k2')).toBeInTheDocument()
  expect(screen.getByText('cheap model passed required structured-output probe')).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: 'Latest tool result' })).toBeInTheDocument()
  expect(screen.getByText('exa_search')).toBeInTheDocument()
  expect(screen.getByText('3 bounded result(s) recorded.')).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: 'Latest output contract' })).toBeInTheDocument()
  expect(screen.getByText('Latest status rejected with schema_mismatch.')).toBeInTheDocument()
  const harnessRawSummary = screen.getByText('Recent bounded harness events')
  expect(harnessRawSummary.closest('details.raw-details')).not.toBeNull()
  expect(screen.getByText((content) => content.includes('llm_harness.route_decision')).closest('details.raw-details')).not.toBeNull()
  expect(await screen.findByRole('heading', { name: 'Memory is inside configured threshold' })).toBeInTheDocument()
  expect(screen.getByText('128.3 MiB')).toBeInTheDocument()
  expect(screen.getByText('Route logging enabled')).toBeInTheDocument()
  expect(screen.getByText('Sentry exception capture enabled')).toBeInTheDocument()
  expect(screen.getByText('production')).toBeInTheDocument()
  expect(screen.getByText('abc1234')).toBeInTheDocument()
  expect(screen.getByText((content) => content.includes('/control/api/status'))).toBeInTheDocument()
  expect(fetchMock).toHaveBeenNthCalledWith(1, '/control/api/v1/observability/health', expect.any(Object))
  expect(fetchMock).toHaveBeenNthCalledWith(2, '/control/api/v1/observability/memory', expect.any(Object))
  expect(fetchMock).toHaveBeenNthCalledWith(3, '/control/api/v1/observability/llm-models', expect.any(Object))
  expect(fetchMock).toHaveBeenNthCalledWith(4, '/control/api/v1/observability/llm-harness', expect.any(Object))
})

it('refreshes observability samples explicitly from the V2 page', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ generated_at: '2026-05-21T09:00:00Z', route_observability_enabled: true, route_observability_log_configured: false, latest_route_observation: '{"route":"/old","status":200}' }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ generated_at: '2026-05-21T09:00:01Z', rss_mib: 100, peak_rss_mib: 140, warn_threshold_mib: 512, memory_warn: false }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ generated_at: '2026-05-21T09:00:02Z', status: 'healthy', model_count: 1, unhealthy_count: 0, structurally_unhealthy_count: 0, models: [{ provider_id: 'synthetic', model_id: 'owl', label: 'Owl', endpoint_health: 'healthy', format_health: 'healthy', visible_output_health: 'healthy', reasoning_budget_health: 'ok', latest_finish_reason: 'stop', latest_visible_chars: 12, success_rate: 1, format_success_rate: 1, operator_action: 'model is currently usable for measured structured automation', latest_preview: 'ok' }] }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ generated_at: '2026-05-21T09:00:03Z', status: 'healthy', event_count: 0, failure_count: 0, estimated_cost_usd: 0, recent_events: [] }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ generated_at: '2026-05-21T09:04:00Z', route_observability_enabled: false, route_observability_log_configured: true, latest_route_observation: '{"route":"/fresh","status":503}' }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ generated_at: '2026-05-21T09:04:01Z', rss_mib: 333.3, peak_rss_mib: 444.4, warn_threshold_mib: 512, memory_warn: true }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ generated_at: '2026-05-21T09:04:02Z', status: 'needs_attention', model_count: 1, unhealthy_count: 1, structurally_unhealthy_count: 0, models: [{ provider_id: 'synthetic', model_id: 'owl', label: 'Owl', endpoint_health: 'unhealthy', format_health: 'unmeasured', visible_output_health: 'unknown', reasoning_budget_health: 'unknown', latest_failure_kind: 'rate_limited', latest_status_code: 429, success_rate: 0, format_success_rate: 0, operator_action: 'fix provider endpoint health (rate_limited) before using this model', latest_preview: '' }] }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ generated_at: '2026-05-21T09:04:03Z', status: 'healthy', event_count: 1, failure_count: 0, estimated_cost_usd: 0.001, recent_events: [{ event_id: 1, event_type: 'llm_harness.route_decision', workflow_id: 'idea_generation_enrichment', selected_provider_id: 'openrouter', selected_model_id: 'glm', selection_reason: 'fresh route', status: 'ok' }] }), { status: 200 }))

  renderWithClient(<ObservabilityPage />)
  await screen.findByRole('heading', { name: 'Memory is inside configured threshold' })

  fireEvent.click(screen.getByRole('button', { name: 'Refresh observability' }))

  expect(await screen.findByRole('heading', { name: 'Memory warning active' })).toBeInTheDocument()
  expect(screen.getByText('333.3 MiB')).toBeInTheDocument()
  expect(screen.getByText('Last loaded health 2026-05-21T09:04:00Z · memory 2026-05-21T09:04:01Z · models 2026-05-21T09:04:02Z · harness 2026-05-21T09:04:03Z')).toBeInTheDocument()
  expect(screen.getByText((content) => content.includes('/fresh'))).toBeInTheDocument()
  expect(screen.getByText('fix provider endpoint health (rate_limited) before using this model')).toBeInTheDocument()
  expect(screen.getByText('fresh route')).toBeInTheDocument()
  expect(fetchMock).toHaveBeenCalledTimes(8)
})

it('refreshes intake workbench rows explicitly from the V2 page', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({
      generated_at: '2026-05-21T10:00:00Z',
      operator_summary: '1 idea(s) queued for operator review; promote or dispatch from the table below.',
      latest_sync: { source: 'supabase', status: 'ok', observed_at: '2026-05-21T09:59:00Z', authority: 'ideas' },
      projection_counts: { queued_projection: 1 },
      queued_projection: [{ idea_id: 'idea-old', title: 'Old intake idea', idea_status: 'admitted', queue_status: 'queued' }],
    }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({
      generated_at: '2026-05-21T10:05:00Z',
      operator_summary: '1 idea(s) queued for operator review; promote or dispatch from the table below.',
      latest_sync: { source: 'supabase', status: 'ok', observed_at: '2026-05-21T10:04:00Z', authority: 'ideas' },
      projection_counts: { queued_projection: 1 },
      queued_projection: [{ idea_id: 'idea-fresh', title: 'Fresh intake idea', idea_status: 'admitted', queue_status: 'queued' }],
    }), { status: 200 }))

  renderWithClient(<IntakePage />)
  await screen.findByText('Old intake idea')

  fireEvent.click(screen.getByRole('button', { name: 'Refresh intake' }))

  await screen.findByText('Fresh intake idea')
  expect(screen.getByText(/queued for operator review/i)).toBeInTheDocument()
  expect(screen.getByText('Last loaded 2026-05-21T10:05:00Z')).toBeInTheDocument()
  expect(fetchMock).toHaveBeenCalledTimes(2)
})

it('opens intake idea details from selected rows without a legacy fallback', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(new Response(JSON.stringify({
    generated_at: '2026-05-21T10:00:00Z',
    latest_sync: { source: 'supabase', status: 'ok', observed_at: '2026-05-21T09:59:00Z', authority: 'ideas' },
    projection_counts: { queued_projection: 1 },
    queued_projection: [{
      idea_id: 'idea-detail',
      title: 'Detailed intake idea',
      idea_status: 'admitted',
      queue_status: 'queued',
      next_action_hint: 'dispatch',
      source_kind: 'chatgpt_pro',
      source_external_url: 'https://example.invalid/source',
      machine_target: 'gb10',
      operator_stage_label: 'Ready queue',
      operator_next_step: 'Dispatch when the lane is available.',
    }],
  }), { status: 200 }))

  renderWithClient(<IntakePage />)

  fireEvent.click(await screen.findByText('Detailed intake idea'))

  const detail = await screen.findByLabelText('Intake idea detail')
  expect(detail).toHaveTextContent('idea-detail')
  expect(detail).toHaveTextContent('admitted')
  expect(detail).toHaveTextContent('queued')
  expect(detail).toHaveTextContent('gb10')
  expect(detail).toHaveTextContent('Ready queue')
  expect(detail).toHaveTextContent('Current state')
  expect(detail).toHaveTextContent('Next safe action')
  expect(detail).toHaveTextContent('Dispatch when the lane is available.')
  expect(detail).toHaveTextContent('Source and lineage')
  expect(detail).toHaveTextContent('Admission and promote')
  expect(screen.queryByRole('link', { name: /legacy/i })).not.toBeInTheDocument()
})
