import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { saveToken } from '../api/client'
import { CorpusPage, EventsPage, IntakePage, ObservabilityPage, PapersPage, ProjectsPage, QueuePage, RunsPage } from './ResourcePages'

function renderWithClient(ui: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

function requestUrl(call: unknown[]): URL {
  const [input] = call
  expect(typeof input).toBe('string')
  return new URL(input as string, 'https://enoch.local')
}

function expectParam(url: URL, name: string, value: string) {
  expect(url.searchParams.get(name)).toBe(value)
}

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  saveToken('')
})

it('loads queue rows from the V1 queue endpoint with the route status', async () => {
  saveToken('test-token')
  const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ rows: [{ project_id: 'p1', status: 'queued', title: 'Queue item' }], page: { returned: 1, has_more: false } }), { status: 200 }))

  renderWithClient(<QueuePage route={{ page: 'queue', status: 'queued', search: '', hash: '#queue:queued' }} />)

  await screen.findByText('Queue item')
  expect(screen.getByRole('link', { name: /p1/ })).toHaveAttribute('href', '/control/dashboard-v2#project:p1')
  expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/control/api/v1/queue?'), expect.objectContaining({ headers: { Authorization: 'Bearer test-token' } }))
  const url = requestUrl(fetchMock.mock.calls[0])
  expect(url.pathname).toBe('/control/api/v1/queue')
  expectParam(url, 'queue', 'all')
  expectParam(url, 'page_size', '50')
  expectParam(url, 'sort', 'priority')
  expectParam(url, 'status', 'queued')
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
  const first = requestUrl(fetchMock.mock.calls[0])
  const second = requestUrl(fetchMock.mock.calls[1])
  expectParam(first, 'status', 'queued')
  expectParam(second, 'status', 'active')
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
    body: JSON.stringify({ project_id: 'project-1', dry_run: true, requested_by: 'dashboard-v2', force_preflight: true }),
  }))
})

it('live-dispatches a selected queued row only after dry-run and dialog confirmation', async () => {
  saveToken('test-token')
  const confirmSpy = vi.spyOn(window, 'confirm')
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
    body: JSON.stringify({ project_id: 'project-live', dry_run: false, requested_by: 'dashboard-v2', force_preflight: true }),
  }))
  await screen.findByText('Fresh queue item')
  expect(fetchMock).toHaveBeenNthCalledWith(5, expect.stringContaining('/control/api/v1/queue?'), expect.any(Object))
})

it('loads project discovery rows from the V1 projects endpoint', async () => {
  saveToken('test-token')
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ rows: [{ project_id: 'project-1', project_name: 'Trace Oracle', origin_idea_status: 'testing', queue_status: 'queued', latest_run_state: 'running' }], page: { returned: 1, has_more: false } }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ project_id: 'project-1', project: { project_name: 'Trace Oracle' } }), { status: 200 }))

  renderWithClient(<ProjectsPage route={{ page: 'projects', status: 'testing', search: '', hash: '#projects?status=testing' }} />)

  await screen.findByText('Trace Oracle')
  expect(screen.getByRole('link', { name: /project-1/ })).toHaveAttribute('href', '/control/dashboard-v2#project:project-1')
  const url = requestUrl(fetchMock.mock.calls[0])
  expect(url.pathname).toBe('/control/api/v1/projects')
  expectParam(url, 'status', 'testing')
  expectParam(url, 'page_size', '50')
  expectParam(url, 'sort', 'recent')

  fireEvent.click(screen.getByText('Trace Oracle'))
  await screen.findByLabelText('Dashboard detail panel')
  expect(fetchMock).toHaveBeenNthCalledWith(2, '/control/api/v1/projects/project-1', expect.any(Object))
})

it('loads runs from the V1 runs endpoint with state filters and detail fetches', async () => {
  saveToken('test-token')
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ rows: [{ run_id: 'run-1', project_id: 'project-1', state: 'running', gate_state: 'awaiting_wake', current_activity: 'testing' }], page: { returned: 1, has_more: false } }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ run_id: 'run-1', run: { run_id: 'run-1', project_id: 'project-1', state: 'running', current_activity: 'testing' } }), { status: 200 }))

  renderWithClient(<RunsPage route={{ page: 'runs', state: 'running', search: '', hash: '#runs:running' }} />)

  await screen.findByText('run-1')
  expect(screen.getByRole('link', { name: /run-1/ })).toHaveAttribute('href', '/control/dashboard-v2#run:run-1')
  expect(screen.getByRole('link', { name: /project-1/ })).toHaveAttribute('href', '/control/dashboard-v2#project:project-1')
  const url = requestUrl(fetchMock.mock.calls[0])
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

  let url = requestUrl(fetchMock.mock.calls[1])
  expectParam(url, 'search', 'oracle')
  expectParam(url, 'status', 'active')
  expectParam(url, 'page_size', '25')
  expect(url.searchParams.get('cursor')).toBeNull()

  fireEvent.click(screen.getByRole('button', { name: /Next page/i }))
  await screen.findByText('Next page item')

  url = requestUrl(fetchMock.mock.calls[2])
  expectParam(url, 'cursor', 'cursor-3')
  expectParam(url, 'search', 'oracle')
  expectParam(url, 'status', 'active')
})

it('applies paper and event filters to the backed endpoints', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ rows: [{ paper_id: 'paper-1', status: 'publication_draft', title: 'Draft paper' }], page: { returned: 1, has_more: false } }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ rows: [{ paper_id: 'paper-2', status: 'draft_review', title: 'Review paper' }], page: { returned: 1, has_more: false } }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ rows: [{ id: 7, event_type: 'Queue Alert', summary: 'Alert summary' }], page: { returned: 1, has_more: false } }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ rows: [{ id: 8, event_type: 'worker.callback', summary: 'Callback summary' }], page: { returned: 1, has_more: false } }), { status: 200 }))

  renderWithClient(<PapersPage route={{ page: 'papers', status: '', search: '', hash: '#papers' }} />)
  await screen.findByText('Draft paper')
  fireEvent.change(screen.getByLabelText(/Search/i), { target: { value: 'trace' } })
  fireEvent.change(screen.getByLabelText(/Status/i), { target: { value: 'draft_review' } })
  fireEvent.click(screen.getByRole('button', { name: /Apply filters/i }))
  await screen.findByText('Review paper')

  let url = requestUrl(fetchMock.mock.calls[1])
  expect(url.pathname).toBe('/control/api/v1/papers')
  expectParam(url, 'search', 'trace')
  expectParam(url, 'status', 'draft_review')

  cleanup()
  renderWithClient(<EventsPage />)
  await screen.findByText('Alert summary')
  fireEvent.change(screen.getByLabelText(/Search/i), { target: { value: 'stalled' } })
  fireEvent.change(screen.getByLabelText(/Status/i), { target: { value: 'worker.callback' } })
  fireEvent.click(screen.getByRole('button', { name: /Apply filters/i }))
  await screen.findByText('Callback summary')

  url = requestUrl(fetchMock.mock.calls[3])
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

  await screen.findByText('Corpus candidate')
  expect(screen.getByRole('link', { name: /paper-corpus/ })).toHaveAttribute('href', '/control/dashboard-v2#paper:paper-corpus')
  expect(screen.getByRole('link', { name: /project-1/ })).toHaveAttribute('href', '/control/dashboard-v2#project:project-1')
  const url = requestUrl(fetchMock.mock.calls[1])
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

it('shows raw event detail without inventing a missing event endpoint', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(new Response(JSON.stringify({ rows: [{ id: 9, event_type: 'Queue Alert', summary: 'Alert summary', payload: { reason: 'blocked' } }], page: { returned: 1, has_more: false } }), { status: 200 }))

  renderWithClient(<EventsPage />)
  fireEvent.click(await screen.findByText('Alert summary'))

  expect(screen.getByRole('link', { name: /9/ })).toHaveAttribute('href', '/control/dashboard-v2#event:9')
  expect(await screen.findByLabelText('Dashboard detail panel')).toHaveTextContent('Queue Alert')
  expect(globalThis.fetch).toHaveBeenCalledTimes(1)
})

it('loads observability health and memory from backed V1 endpoints', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ generated_at: '2026-05-20T12:00:00Z', route_observability_enabled: true, route_observability_log_configured: false, latest_route_observation: '{"route":"/control/api/status","status":200}' }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ generated_at: '2026-05-20T12:00:01Z', rss_mib: 128.25, peak_rss_mib: 256.5, warn_threshold_mib: 1024, memory_warn: false, route_observability_enabled: true }), { status: 200 }))

  renderWithClient(<ObservabilityPage />)

  expect(await screen.findByRole('heading', { name: 'Memory is inside configured threshold' })).toBeInTheDocument()
  expect(screen.getByText('128.3 MiB')).toBeInTheDocument()
  expect(screen.getByText('Route logging enabled')).toBeInTheDocument()
  expect(screen.getByText((content) => content.includes('/control/api/status'))).toBeInTheDocument()
  expect(fetchMock).toHaveBeenNthCalledWith(1, '/control/api/v1/observability/health', expect.any(Object))
  expect(fetchMock).toHaveBeenNthCalledWith(2, '/control/api/v1/observability/memory', expect.any(Object))
})

it('refreshes observability samples explicitly from the V2 page', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ generated_at: '2026-05-21T09:00:00Z', route_observability_enabled: true, route_observability_log_configured: false, latest_route_observation: '{"route":"/old","status":200}' }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ generated_at: '2026-05-21T09:00:01Z', rss_mib: 100, peak_rss_mib: 140, warn_threshold_mib: 512, memory_warn: false }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ generated_at: '2026-05-21T09:04:00Z', route_observability_enabled: false, route_observability_log_configured: true, latest_route_observation: '{"route":"/fresh","status":503}' }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ generated_at: '2026-05-21T09:04:01Z', rss_mib: 333.3, peak_rss_mib: 444.4, warn_threshold_mib: 512, memory_warn: true }), { status: 200 }))

  renderWithClient(<ObservabilityPage />)
  await screen.findByRole('heading', { name: 'Memory is inside configured threshold' })

  fireEvent.click(screen.getByRole('button', { name: 'Refresh observability' }))

  expect(await screen.findByRole('heading', { name: 'Memory warning active' })).toBeInTheDocument()
  expect(screen.getByText('333.3 MiB')).toBeInTheDocument()
  expect(screen.getByText('Last loaded health 2026-05-21T09:04:00Z · memory 2026-05-21T09:04:01Z')).toBeInTheDocument()
  expect(screen.getByText((content) => content.includes('/fresh'))).toBeInTheDocument()
  expect(fetchMock).toHaveBeenCalledTimes(4)
})

it('refreshes intake workbench rows explicitly from the V2 page', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({
      generated_at: '2026-05-21T10:00:00Z',
      latest_sync: { source: 'supabase', status: 'ok', observed_at: '2026-05-21T09:59:00Z', authority: 'ideas' },
      projection_counts: { queued_projection: 1 },
      queued_projection: [{ idea_id: 'idea-old', title: 'Old intake idea', idea_status: 'admitted', queue_status: 'queued' }],
    }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({
      generated_at: '2026-05-21T10:05:00Z',
      latest_sync: { source: 'supabase', status: 'ok', observed_at: '2026-05-21T10:04:00Z', authority: 'ideas' },
      projection_counts: { queued_projection: 1 },
      queued_projection: [{ idea_id: 'idea-fresh', title: 'Fresh intake idea', idea_status: 'admitted', queue_status: 'queued' }],
    }), { status: 200 }))

  renderWithClient(<IntakePage />)
  await screen.findByText('Old intake idea')

  fireEvent.click(screen.getByRole('button', { name: 'Refresh intake' }))

  await screen.findByText('Fresh intake idea')
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
    }],
  }), { status: 200 }))

  renderWithClient(<IntakePage />)

  fireEvent.click(await screen.findByText('Detailed intake idea'))

  const detail = await screen.findByLabelText('Intake idea detail')
  expect(detail).toHaveTextContent('idea-detail')
  expect(detail).toHaveTextContent('admitted')
  expect(detail).toHaveTextContent('queued')
  expect(detail).toHaveTextContent('dispatch')
  expect(screen.queryByRole('link', { name: /legacy/i })).not.toBeInTheDocument()
})
