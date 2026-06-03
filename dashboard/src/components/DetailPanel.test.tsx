import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { DetailPage, DetailPanel } from './DetailPanel'

function renderWithClient(ui: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

function assertJsonBlocksInRawDetails(container: HTMLElement) {
  container.querySelectorAll('.json-block').forEach((block) => {
    if (block.closest('.artifact-preview')) return
    expect(block.closest('details.raw-details')).not.toBeNull()
  })
}

const PREFIXED_ID_PATTERN = /^(project|run|paper|event):/i

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
  assertJsonBlocksInRawDetails(document.body)
})

it('renders run detail from the backed run endpoint', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(new Response(JSON.stringify({ run_id: 'run-1', run: { run_id: 'run-1', project_id: 'project-1', state: 'running', gate_state: 'awaiting_wake', current_activity: 'testing' } }), { status: 200 }))

  renderWithClient(<DetailPanel selection={{ kind: 'run', id: 'run-1' }} onClose={() => undefined} />)

  expect(await screen.findByRole('heading', { name: 'run-1' })).toBeInTheDocument()
  expect((await screen.findAllByText('gate')).length).toBeGreaterThan(0)
  expect(screen.getAllByText('awaiting_wake').length).toBeGreaterThan(0)
  assertJsonBlocksInRawDetails(document.body)
})

it('renders event detail from the selected row without fetching an event endpoint', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch')

  renderWithClient(<DetailPanel selection={{ kind: 'event', id: '9', row: { id: 9, event_type: 'Queue Alert', summary: 'Lane blocked', payload: { reason: 'lane active' } } }} onClose={() => undefined} />)

  expect(screen.getAllByText('Queue Alert').length).toBeGreaterThan(0)
  expect(screen.getByRole('heading', { name: 'Lane blocked' })).toBeInTheDocument()
  expect(screen.getByText('Raw payload')).toBeInTheDocument()
  expect(fetchMock).not.toHaveBeenCalled()
  assertJsonBlocksInRawDetails(document.body)
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
  expect(screen.getAllByRole('link', { name: /run-1/ }).some((link) => link.getAttribute('href') === '/control/dashboard-v2#run:run-1')).toBe(true)
  expect(screen.getByText('Related papers')).toBeInTheDocument()
  expect(screen.getAllByRole('link', { name: /Draft paper/ }).some((link) => link.getAttribute('href') === '/control/dashboard-v2#paper:paper-1')).toBe(true)
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
  assertJsonBlocksInRawDetails(document.body)
})

it.each([
  {
    kind: 'project' as const,
    id: 'project:llm-generated-trace-replay-with-a-very-long-project-slug',
    payload: { project_id: 'project:llm-generated-trace-replay-with-a-very-long-project-slug', status: 'queued', queue: { lane: 'gb10' } },
    expectedTitle: 'llm-generated-…oject-slug',
  },
  {
    kind: 'run' as const,
    id: 'run:llm-generated-trace-replay-with-a-very-long-run-slug:00001',
    payload: { run_id: 'run:llm-generated-trace-replay-with-a-very-long-run-slug:00001', run: { run_id: 'run:llm-generated-trace-replay-with-a-very-long-run-slug:00001', state: 'running' } },
    expectedTitle: 'llm-generated-…slug:00001',
  },
  {
    kind: 'paper' as const,
    id: 'paper:trace-oracle-slug:00001:arxiv_draft',
    payload: {
      paper_id: 'paper:trace-oracle-slug:00001:arxiv_draft',
      paper: { paper_id: 'paper:trace-oracle-slug:00001:arxiv_draft', status: 'publication_draft' },
    },
    expectedTitle: 'trace-oracle-s…rxiv_draft',
  },
  {
    kind: 'event' as const,
    id: '9',
    payload: { id: 9, event_type: 'Queue Alert', summary: 'Lane blocked on gb10' },
    expectedTitle: 'Lane blocked on gb10',
  },
])('detail page h1 never uses prefixed slug hero for $kind', async ({ kind, id, payload, expectedTitle }) => {
  if (kind === 'event') {
    renderWithClient(<DetailPage selection={{ kind, id, row: payload }} />)
  } else {
    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(new Response(JSON.stringify(payload), { status: 200 }))
    renderWithClient(<DetailPage selection={{ kind, id }} />)
  }

  const heading = await screen.findByRole('heading', { level: 1, name: expectedTitle })
  expect(heading.textContent).not.toMatch(PREFIXED_ID_PATTERN)
})

it('renders P2 operator question sections with entity links for project detail', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(new Response(JSON.stringify({
    project_id: 'project-1',
    project: { project_name: 'Structured project', origin_idea_status: 'admitted' },
    queue_item: {
      status: 'queued',
      machine_target: 'gb10',
      current_run_id: 'run-1',
      last_run_state: 'queued',
      related_paper_id: 'paper-1',
      related_paper_status: 'publication_draft',
      related_review_status: 'ready',
      operator_stage_label: 'Write papers',
    },
    events: [{ summary: 'Queue item created', created_at: '2026-05-21T10:00:00Z' }],
  }), { status: 200 }))

  renderWithClient(<DetailPage selection={{ kind: 'project', id: 'project-1' }} />)

  expect(await screen.findByText('Current state')).toBeInTheDocument()
  expect(screen.getByRole('navigation', { name: 'Breadcrumb' })).toHaveTextContent('Projects')
  expect(screen.getByRole('link', { name: 'Projects' })).toHaveAttribute('href', '/control/dashboard-v2#projects')
  expect(screen.getByText('Next safe action')).toBeInTheDocument()
  expect(screen.getByText('What is this project?')).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: 'Paper and publication path' })).toBeInTheDocument()
  expect(screen.getByText('What happened most recently?')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: /run: run-1/ })).toHaveAttribute('href', '/control/dashboard-v2#run:run-1')
  expect(screen.getByRole('link', { name: /paper: paper-1/ })).toHaveAttribute('href', '/control/dashboard-v2#paper:paper-1')
  expect(screen.queryByRole('heading', { name: /^project:/i })).not.toBeInTheDocument()
  expect(screen.getByText('Record fields')).toBeInTheDocument()
  const currentState = screen.getByText('Current state')
  const recordFields = screen.getByText('Record fields')
  expect(currentState.compareDocumentPosition(recordFields) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
})

it('renders P2 operator question sections for run detail with project link', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(new Response(JSON.stringify({
    run_id: 'run-1',
    run: {
      run_id: 'run-1',
      project_id: 'project-1',
      project_name: 'Structured project',
      state: 'running',
      gate_state: 'awaiting_wake',
      current_activity: 'testing',
      operator_lane: 'gb10',
      started_at: '2026-05-21T09:00:00Z',
      related_paper_id: 'paper-1',
      related_paper_status: 'publication_draft',
    },
    queue_item: { machine_target: 'gb10', operator_lane: 'gb10' },
    papers: [{ paper_id: 'paper-1', title: 'Draft paper', paper_status: 'publication_draft' }],
    events: [{ summary: 'Wake callback pending', created_at: '2026-05-21T10:01:00Z' }],
  }), { status: 200 }))

  renderWithClient(<DetailPage selection={{ kind: 'run', id: 'run-1' }} />)

  expect(await screen.findByText('Run progress')).toBeInTheDocument()
  expect(screen.getByRole('navigation', { name: 'Breadcrumb' })).toHaveTextContent('Runs')
  expect(screen.getByRole('link', { name: 'Runs' })).toHaveAttribute('href', '/control/dashboard-v2#runs')
  expect(screen.getByRole('heading', { name: 'Worker and lane' })).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: 'Run outcome' })).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: 'Paper and publication path' })).toBeInTheDocument()
  expect(screen.getByText('What happened most recently?')).toBeInTheDocument()
  expect(screen.getByText('Record fields')).toBeInTheDocument()
  const currentState = screen.getByText('Current state')
  const recordFields = screen.getByText('Record fields')
  expect(currentState.compareDocumentPosition(recordFields) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  expect(screen.getByRole('link', { name: /project: Structured project/ })).toHaveAttribute('href', '/control/dashboard-v2#project:project-1')
  expect(screen.getAllByRole('link', { name: /Draft paper/ }).some((link) => link.getAttribute('href') === '/control/dashboard-v2#paper:paper-1')).toBe(true)
})

it('renders P2 operator question sections for paper detail with entity links', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(new Response(JSON.stringify({
    paper_id: 'paper-1',
    paper: {
      paper_id: 'paper-1',
      title: 'Artifact paper',
      project_id: 'project-1',
      run_id: 'run-1',
      paper_status: 'publication_draft',
      review_status: 'ready',
      artifact_paths_present: {
        draft_markdown: true,
        evidence_bundle: true,
        claim_ledger: true,
        manifest: false,
        finalization_package: false,
      },
    },
    project: { project_id: 'project-1', project_name: 'Structured project' },
    run: { run_id: 'run-1', state: 'completed' },
    queue_item: { machine_target: 'gb10', project_id: 'project-1' },
    events: [{ summary: 'Paper draft updated', created_at: '2026-05-21T10:01:00Z' }],
  }), { status: 200 }))

  renderWithClient(<DetailPage selection={{ kind: 'paper', id: 'paper-1' }} />)

  expect(await screen.findByText('Current state')).toBeInTheDocument()
  expect(screen.getByRole('navigation', { name: 'Breadcrumb' })).toHaveTextContent('Papers')
  expect(screen.getByRole('link', { name: 'Papers' })).toHaveAttribute('href', '/control/dashboard-v2#papers')
  expect(screen.getByText('What is this paper?')).toBeInTheDocument()
  expect(screen.getByText('What blocks publication?')).toBeInTheDocument()
  expect(screen.getByText('Related project and run')).toBeInTheDocument()
  expect(screen.getByText('Publication checklist')).toBeInTheDocument()
  expect(screen.getByText('What happened most recently?')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Preview draft markdown' })).toBeInTheDocument()
  expect(screen.getByText('Record fields')).toBeInTheDocument()
  const currentState = screen.getByText('Current state')
  const recordFields = screen.getByText('Record fields')
  expect(currentState.compareDocumentPosition(recordFields) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  expect(screen.getByRole('link', { name: /project: Structured project/ })).toHaveAttribute('href', '/control/dashboard-v2#project:project-1')
  expect(screen.getByRole('link', { name: /run: run-1/ })).toHaveAttribute('href', '/control/dashboard-v2#run:run-1')
})

it('renders P2 operator question sections for event detail with entity links', async () => {
  renderWithClient(<DetailPage selection={{
    kind: 'event',
    id: '9',
    row: {
      id: 9,
      event_type: 'Queue Alert',
      project_id: 'project-1',
      run_id: 'run-1',
      summary: 'Lane blocked on gb10',
      created_at: '2026-05-21T10:00:00Z',
      payload: { reason: 'lane active', gate_state: 'awaiting_wake' },
    },
  }} />)

  expect(await screen.findByText('Current state')).toBeInTheDocument()
  expect(screen.getByRole('navigation', { name: 'Breadcrumb' })).toHaveTextContent('Events')
  expect(screen.getByRole('link', { name: 'Events' })).toHaveAttribute('href', '/control/dashboard-v2#events')
  expect(screen.getByText('What happened?')).toBeInTheDocument()
  expect(screen.getByText('When?')).toBeInTheDocument()
  expect(screen.getByText('Which entity was affected?')).toBeInTheDocument()
  expect(screen.getByText('What does the payload prove?')).toBeInTheDocument()
  expect(screen.getByText('Record fields')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: /project: project-1/ })).toHaveAttribute('href', '/control/dashboard-v2#project:project-1')
  expect(screen.getByRole('link', { name: /run: run-1/ })).toHaveAttribute('href', '/control/dashboard-v2#run:run-1')
  const rawDetails = screen.getByText('Raw payload').closest('details')
  expect(rawDetails).not.toHaveAttribute('open')
})

it('renders event detail entity link from nested payload when top-level ids are absent', async () => {
  renderWithClient(<DetailPage selection={{
    kind: 'event',
    id: '42',
    row: {
      event_id: 42,
      event_type: 'Run Error',
      entity_type: 'run',
      entity_id: 'run-9',
      created_at: '2026-05-21T11:00:00Z',
      payload: { error: 'dispatch failed', run_id: 'run-9' },
    },
  }} />)

  expect(await screen.findByText('Current state')).toBeInTheDocument()
  expect(screen.getByText('What happened?')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: /run: run-9/ })).toHaveAttribute('href', '/control/dashboard-v2#run:run-9')
  expect(screen.queryByRole('link', { name: /project:/ })).not.toBeInTheDocument()
})

it('renders queue alert findings, blockers, and current resolution from event detail', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({
      rows: [{
        event_id: 7714,
        event_type: 'queue_alert.detected',
        entity_type: 'queue_alert',
        entity_id: '21bb7dff4bfc277c',
        created_at: '2026-05-21T20:46:02Z',
        payload: {
          fingerprint: '21bb7dff4bfc277c',
          dispatch_safe: false,
          dispatch_blockers: ['worker_preflight not ok', 'GB10/VM active-lane conflict'],
          transient_suppressed_findings: [],
          findings: [
            {
              severity: 'critical',
              source: 'control_plane_db+worker_preflight',
              message: 'GB10 reports live/active work but VM control plane has no active row',
              suggested_action: 'pause dispatch to the affected worker lane and reconcile before starting another job',
            },
          ],
        },
      }],
    }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({
      dispatch_safe: true,
      dispatch_blockers: [],
    }), { status: 200 }))

  renderWithClient(<DetailPage selection={{ kind: 'event', id: '7714' }} />)

  expect(await screen.findByText('Queue alert detail')).toBeInTheDocument()
  expect(await screen.findByText('Resolved now')).toBeInTheDocument()
  expect(screen.getByText('Alert findings')).toBeInTheDocument()
  expect(screen.getAllByText('GB10 reports live/active work but VM control plane has no active row').length).toBeGreaterThan(0)
  expect(screen.getAllByText(/worker_preflight not ok; GB10\/VM active-lane conflict/).length).toBeGreaterThan(0)
  expect(screen.getByText('dispatch safe at event time')).toBeInTheDocument()
  expect(fetchMock).toHaveBeenNthCalledWith(1, '/control/api/v1/events?event_id=7714&include_payload=true&page_size=1&sort=recent', expect.any(Object))
  expect(fetchMock).toHaveBeenNthCalledWith(2, '/control/api/status', expect.any(Object))
})

it('fetches full event detail when selected event row only has payload summary', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({
      rows: [{
        event_id: 21173,
        event_type: 'queue_alert.detected',
        entity_type: 'queue_alert',
        entity_id: 'a04f20c95c67da1b',
        created_at: '2026-06-03T14:31:00Z',
        payload: {
          fingerprint: 'a04f20c95c67da1b',
          dispatch_safe: true,
          dispatch_blockers: [],
          transient_suppressed_findings: [],
          findings: [
            {
              severity: 'warn',
              source: 'research_quality',
              message: 'research signal requires review: no bounded paper-ready outputs are available',
              suggested_action: 'inspect warning findings before widening automation',
            },
          ],
        },
      }],
    }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({
      dispatch_safe: true,
      dispatch_blockers: [],
    }), { status: 200 }))

  renderWithClient(<DetailPage selection={{
    kind: 'event',
    id: '21173',
    row: {
      event_id: 21173,
      event_type: 'queue_alert.detected',
      entity_type: 'queue_alert',
      entity_id: 'a04f20c95c67da1b',
      created_at: '2026-06-03T14:31:00Z',
      payload_summary: { keys: [], bytes: 16752 },
    },
  }} />)

  expect(await screen.findByText('Queue alert detail')).toBeInTheDocument()
  expect(screen.getByText('Alert findings')).toBeInTheDocument()
  expect(screen.getAllByText('research signal requires review: no bounded paper-ready outputs are available').length).toBeGreaterThan(0)
  expect(screen.queryByText('payload empty')).not.toBeInTheDocument()
  expect(fetchMock).toHaveBeenNthCalledWith(1, '/control/api/v1/events?event_id=21173&include_payload=true&page_size=1&sort=recent', expect.any(Object))
})
