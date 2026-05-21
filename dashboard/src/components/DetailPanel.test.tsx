import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { DetailPage, DetailPanel } from './DetailPanel'

function renderWithClient(ui: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

it('renders project detail as structured fields with raw payload collapsed', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(new Response(JSON.stringify({ project_id: 'project-1', status: 'active', project: { project_name: 'Structured project', machine_target: 'gb10' }, queue: { lane: 'gb10' } }), { status: 200 }))

  renderWithClient(<DetailPanel selection={{ kind: 'project', id: 'project-1' }} onClose={() => undefined} />)

  expect(await screen.findByRole('heading', { name: 'Structured project' })).toBeInTheDocument()
  expect(screen.getByText('machine target')).toBeInTheDocument()
  expect(screen.getAllByText('gb10').length).toBeGreaterThan(0)
  expect(screen.getByText('Raw payload')).toBeInTheDocument()
})

it('renders run detail from the backed run endpoint', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(new Response(JSON.stringify({ run_id: 'run-1', run: { run_id: 'run-1', project_id: 'project-1', state: 'running', gate_state: 'awaiting_wake', current_activity: 'testing' } }), { status: 200 }))

  renderWithClient(<DetailPanel selection={{ kind: 'run', id: 'run-1' }} onClose={() => undefined} />)

  expect(await screen.findByRole('heading', { name: 'run-1' })).toBeInTheDocument()
  expect(await screen.findByText('gate')).toBeInTheDocument()
  expect(screen.getByText('awaiting_wake')).toBeInTheDocument()
})

it('renders event detail from the selected row without fetching an event endpoint', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch')

  renderWithClient(<DetailPanel selection={{ kind: 'event', id: '9', row: { id: 9, event_type: 'Queue Alert', summary: 'Lane blocked', payload: { reason: 'lane active' } } }} onClose={() => undefined} />)

  expect(screen.getAllByText('Queue Alert').length).toBeGreaterThan(0)
  expect(screen.getByRole('heading', { name: 'Lane blocked' })).toBeInTheDocument()
  expect(screen.getByText('Raw payload')).toBeInTheDocument()
  expect(fetchMock).not.toHaveBeenCalled()
})

it('keeps hook order stable when switching from inline event detail to fetched detail', async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(new Response(JSON.stringify({
    project_id: 'project-1',
    project: { project_name: 'Structured project', machine_target: 'gb10' },
  }), { status: 200 }))
  const panel = (selection: React.ComponentProps<typeof DetailPanel>['selection']) => (
    <QueryClientProvider client={client}>
      <DetailPanel selection={selection} onClose={() => undefined} />
    </QueryClientProvider>
  )

  const { rerender } = render(panel({ kind: 'event', id: '9', row: { id: 9, event_type: 'Queue Alert', summary: 'Lane blocked' } }))
  expect(screen.getByRole('heading', { name: 'Lane blocked' })).toBeInTheDocument()

  rerender(panel({ kind: 'project', id: 'project-1' }))

  expect(await screen.findByRole('heading', { name: 'Structured project' })).toBeInTheDocument()
})


it('renders related project runs and papers as V2 links instead of raw-only JSON', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(new Response(JSON.stringify({
    project_id: 'project-1',
    project: { project_name: 'Structured project' },
    runs: [{ run_id: 'run-1', state: 'running', current_activity: 'testing' }],
    papers: [{ paper_id: 'paper-1', title: 'Draft paper', status: 'publication_draft' }],
    events: [{ id: 9, event_type: 'Queue Alert', summary: 'Lane blocked' }],
  }), { status: 200 }))

  renderWithClient(<DetailPanel selection={{ kind: 'project', id: 'project-1' }} onClose={() => undefined} />)

  expect(await screen.findByRole('heading', { name: 'Structured project' })).toBeInTheDocument()
  expect(screen.getByText('Related runs')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: /run-1/ })).toHaveAttribute('href', '/control/dashboard-v2#run:run-1')
  expect(screen.getByText('Related papers')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: /Draft paper/ })).toHaveAttribute('href', '/control/dashboard-v2#paper:paper-1')
  expect(screen.getByText('Recent events')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: /Lane blocked/ })).toHaveAttribute('href', '/control/dashboard-v2#event:9')
})


it('loads paper artifacts directly from V2 paper detail', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({
      paper_id: 'paper-1',
      paper: {
        paper_id: 'paper-1',
        title: 'Artifact paper',
        draft_markdown_path: 'papers/run-1/final.md',
        evidence_bundle_path: 'papers/run-1/evidence.json',
        claim_ledger_path: 'papers/run-1/claims.json',
        manifest_path: 'papers/run-1/manifest.json',
      },
    }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ field: 'draft_markdown_path', content: '# Artifact paper\nBody', truncated: false, size_bytes: 21 }), { status: 200 }))

  renderWithClient(<DetailPanel selection={{ kind: 'paper', id: 'paper-1' }} onClose={() => undefined} />)

  expect(await screen.findByRole('heading', { name: 'Artifact paper' })).toBeInTheDocument()
  expect(screen.getByText('Paper artifacts')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Preview draft markdown' }))

  expect(await screen.findByText('Artifact preview')).toBeInTheDocument()
  expect(screen.getByText((content) => content.includes('# Artifact paper'))).toBeInTheDocument()
  expect(fetchMock).toHaveBeenNthCalledWith(2, '/control/api/papers/paper-1/artifact/draft_markdown_path', expect.any(Object))
})

it('uses compact useful headers instead of raw monster ids on direct detail pages', async () => {
  const longId = 'paper:llm-generated-ledger-trace-replay-with-a-very-long-project-slug:run-00001:arxiv_draft'
  vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(new Response(JSON.stringify({
    paper_id: longId,
    paper: {
      paper_id: longId,
      title: 'Trace replay paper',
      status: 'publication_draft',
      evidence_bundle_path: 'papers/evidence.json',
    },
  }), { status: 200 }))

  renderWithClient(<DetailPage selection={{ kind: 'paper', id: longId }} />)

  expect(screen.queryByRole('heading', { name: `paper: ${longId}` })).not.toBeInTheDocument()
  expect(await screen.findByRole('heading', { name: 'Trace replay paper', level: 1 })).toBeInTheDocument()
  expect(screen.getByText(/Paper detail · paper:llm-gene…rxiv_draft · publication_draft/)).toBeInTheDocument()
  expect(screen.getAllByText('publication_draft').length).toBeGreaterThan(0)
  expect(screen.getByText('Next safe action')).toBeInTheDocument()
})
