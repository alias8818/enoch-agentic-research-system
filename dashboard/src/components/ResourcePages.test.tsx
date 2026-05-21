import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { saveToken } from '../api/client'
import { CorpusPage, EventsPage, ObservabilityPage, PapersPage, ProjectsPage, QueuePage, RunsPage } from './ResourcePages'

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

  renderWithClient(<QueuePage route={{ page: 'queue', status: 'queued', hash: '#queue:queued' }} />)

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


it('checks selected queued rows with dispatch-one dry-run only', async () => {
  saveToken('test-token')
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ rows: [{ project_id: 'project-1', status: 'queued', machine_target: 'gb10', title: 'Queue item' }], page: { returned: 1, has_more: false } }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ project_id: 'project-1', project: { project_name: 'Queue item' } }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true, action: 'dry_run_dispatch_one', reason: 'dry-run selected explicit queued candidate; no state mutated', candidate: { project_id: 'project-1' } }), { status: 200 }))

  renderWithClient(<QueuePage route={{ page: 'queue', status: 'queued', hash: '#queue:queued' }} />)

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

it('loads project discovery rows from the V1 projects endpoint', async () => {
  saveToken('test-token')
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ rows: [{ project_id: 'project-1', project_name: 'Trace Oracle', origin_idea_status: 'testing', queue_status: 'queued', latest_run_state: 'running' }], page: { returned: 1, has_more: false } }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ project_id: 'project-1', project: { project_name: 'Trace Oracle' } }), { status: 200 }))

  renderWithClient(<ProjectsPage route={{ page: 'projects', status: 'testing', hash: '#projects?status=testing' }} />)

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

  renderWithClient(<RunsPage route={{ page: 'runs', state: 'running', hash: '#runs:running' }} />)

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

  renderWithClient(<PapersPage route={{ page: 'papers', status: 'publication_draft', hash: '#papers?status=publication_draft' }} />)
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

  renderWithClient(<QueuePage route={{ page: 'queue', status: '', hash: '#queue' }} />)
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

  renderWithClient(<PapersPage route={{ page: 'papers', status: '', hash: '#papers' }} />)
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

  renderWithClient(<QueuePage route={{ page: 'queue', status: 'queued', hash: '#queue:queued' }} />)
  fireEvent.click(await screen.findByText('Queue item'))
  await screen.findByRole('heading', { name: /Detailed project/ })

  renderWithClient(<PapersPage route={{ page: 'papers', status: '', hash: '#papers' }} />)
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
