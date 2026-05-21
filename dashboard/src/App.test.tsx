import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { saveToken } from './api/client'
import { App } from './App'

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  saveToken('')
  window.location.hash = ''
})

it('keeps overview secondary links in V2 and exposes data freshness', async () => {
  vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true, generated_at: '2026-05-20T12:00:00Z', counts: { active: 0, queued: 0 }, paper_counts: {}, movement_diagnosis: { status: 'ready', primary_reason: 'No blockers.', blockers: [] }, flags: {} }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ generated_at: '2026-05-20T12:00:05Z', worker_lanes: [] }), { status: 200 }))
    .mockResolvedValue(new Response(JSON.stringify({ ok: true, generated_at: '2026-05-20T12:01:00Z', counts: { active: 0, queued: 0 }, paper_counts: {}, movement_diagnosis: { status: 'ready', primary_reason: 'No blockers.', blockers: [] }, flags: {} }), { status: 200 }))
  saveToken('test-token')

  render(<App />)

  expect(await screen.findByText('Can I leave this running?')).toBeInTheDocument()
  expect(screen.getByLabelText('Dashboard data freshness')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Overview' })).toBeInTheDocument()
  fireEvent.click(screen.getByText('More'))
  expect(screen.getByRole('link', { name: 'Events' })).toHaveAttribute('href', '/control/dashboard-v2#events')
  expect(screen.getByRole('link', { name: 'Legacy dashboard' })).toHaveAttribute('href', '/control/dashboard')
  fireEvent.click(screen.getByText('Show secondary details'))
  expect(screen.getAllByRole('link', { name: 'Runs' }).some((link) => link.getAttribute('href') === '/control/dashboard-v2#runs')).toBe(true)
  expect(screen.getAllByRole('link', { name: 'Papers' }).some((link) => link.getAttribute('href') === '/control/dashboard-v2#papers')).toBe(true)
  expect(screen.getByRole('link', { name: 'Recent activity' })).toHaveAttribute('href', '/control/dashboard-v2#events')

  fireEvent.click(screen.getByRole('button', { name: 'Refresh now' }))
  await waitFor(() => expect(globalThis.fetch).toHaveBeenCalledTimes(6))
})

it('shows recent activity inside the collapsed overview secondary fold', async () => {
  vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({
      ok: true,
      generated_at: '2026-05-20T12:00:00Z',
      counts: { active: 0, queued: 0 },
      paper_counts: {},
      movement_diagnosis: { status: 'ready', primary_reason: 'No blockers.', blockers: [] },
      flags: {},
      recent_events: [
        { id: 42, event_type: 'Queue Alert', summary: 'GB10 lane became idle', created_at: '2026-05-20T12:00:01Z' },
      ],
    }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ generated_at: '2026-05-20T12:00:05Z', worker_lanes: [] }), { status: 200 }))
  saveToken('test-token')

  render(<App />)

  expect(await screen.findByText('Can I leave this running?')).toBeInTheDocument()
  fireEvent.click(screen.getByText('Show secondary details'))
  expect(screen.getByText('Recent activity')).toBeInTheDocument()
  expect(screen.getByText('GB10 lane became idle')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: /Queue Alert/ })).toHaveAttribute('href', '/control/dashboard-v2#event:42')
})

it('shows automation readiness in the collapsed overview secondary fold', async () => {
  vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({
      ok: true,
      generated_at: '2026-05-20T12:00:00Z',
      counts: { active: 0, queued: 0 },
      paper_counts: {},
      movement_diagnosis: { status: 'ready', primary_reason: 'No blockers.', blockers: [] },
      flags: {},
      recent_events: [],
    }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ generated_at: '2026-05-20T12:00:05Z', worker_lanes: [] }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({
      ok: false,
      label: 'Long-haul mode: BLOCKED — queued/active state inconsistent',
      blockers: ['queue_counts_consistent: blocked'],
      checks: [{ name: 'queue_unpaused', ok: true }, { name: 'queue_counts_consistent', ok: false }],
      summary: { queued: 3, active: 2, queue_paused: false, maintenance_mode: false },
    }), { status: 200 }))
  saveToken('test-token')

  render(<App />)

  expect(await screen.findByText('Can I leave this running?')).toBeInTheDocument()
  fireEvent.click(screen.getByText('Show secondary details'))
  expect(screen.getByText('Automation readiness')).toBeInTheDocument()
  expect(screen.getByText('Long-haul mode: BLOCKED — queued/active state inconsistent')).toBeInTheDocument()
  expect(screen.getAllByText('queue_counts_consistent: blocked')).toHaveLength(2)
  expect(globalThis.fetch).toHaveBeenNthCalledWith(3, '/control/api/v1/automation-readiness', expect.any(Object))
})

it('shows active work inside the collapsed overview secondary fold', async () => {
  vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({
      ok: true,
      generated_at: '2026-05-20T12:00:00Z',
      counts: { active: 1, queued: 0 },
      paper_counts: {},
      movement_diagnosis: { status: 'ready', primary_reason: 'One CPU job is running.', blockers: [] },
      flags: {},
      active_items: [
        { project_id: 'project-cpu', current_run_id: 'run-cpu', project_name: 'Prompt-to-Test Oracle', machine_target: 'cpu-proxmox-1', updated_at: '2026-05-20T12:00:01Z' },
      ],
      recent_events: [],
    }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ generated_at: '2026-05-20T12:00:05Z', worker_lanes: [] }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true, label: 'Long-haul mode: READY', blockers: [], checks: [], summary: { queued: 0, active: 1 } }), { status: 200 }))
  saveToken('test-token')

  render(<App />)

  expect(await screen.findByText('Can I leave this running?')).toBeInTheDocument()
  fireEvent.click(screen.getByText('Show secondary details'))
  expect(screen.getByText('Active work snapshot')).toBeInTheDocument()
  expect(screen.getByText('Prompt-to-Test Oracle')).toBeInTheDocument()
  expect(screen.getByText('cpu-proxmox-1 · run-cpu')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: /Open run/ })).toHaveAttribute('href', '/control/dashboard-v2#run:run-cpu')
})

it('shows operator queue counts inside the collapsed overview secondary fold', async () => {
  vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({
      ok: true,
      generated_at: '2026-05-20T12:00:00Z',
      counts: { active: 1, queued: 4 },
      paper_counts: {},
      operator_counts: { needs_attention: 2, running: 1, write_paper: 3, ready_to_publish: 1 },
      operator_detail_counts: { finalization_needed: 2, followup_candidate: 5 },
      movement_diagnosis: { status: 'actionable', primary_reason: 'Operator work exists.', blockers: [] },
      flags: {},
      active_items: [],
      recent_events: [],
    }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ generated_at: '2026-05-20T12:00:05Z', worker_lanes: [] }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true, label: 'Long-haul mode: READY', blockers: [], checks: [], summary: { queued: 4, active: 1 } }), { status: 200 }))
  saveToken('test-token')

  render(<App />)

  expect(await screen.findByText('Can I leave this running?')).toBeInTheDocument()
  fireEvent.click(screen.getByText('Show secondary details'))
  const snapshot = screen.getByLabelText('Operator queue snapshot')
  expect(within(snapshot).getByRole('heading', { name: 'Operator queue snapshot' })).toBeInTheDocument()
  expect(within(snapshot).getByText('needs attention')).toBeInTheDocument()
  expect(within(snapshot).getAllByText('2')).toHaveLength(2)
  expect(within(snapshot).getByText('write paper')).toBeInTheDocument()
  expect(within(snapshot).getByText('3')).toBeInTheDocument()
  expect(within(snapshot).getByText('followup candidate')).toBeInTheDocument()
  expect(within(snapshot).getByText('5')).toBeInTheDocument()
})

it('uses V2-authored token and fallback surfaces', () => {
  render(<App />)
  expect(screen.getByRole('heading', { name: 'Bearer token required' })).toBeInTheDocument()
  expect(screen.getByLabelText('Bearer token')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Save token' })).toBeInTheDocument()
})


it('opens direct V2 detail hashes without legacy fallback', async () => {
  window.location.hash = '#run:run-1'
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ run_id: 'run-1', run: { run_id: 'run-1', project_id: 'project-1', state: 'running' } }), { status: 200 }))
  saveToken('test-token')

  render(<App />)

  expect(await screen.findByLabelText('Dashboard detail page')).toBeInTheDocument()
  expect(screen.queryByText('This V2 page is not implemented yet')).not.toBeInTheDocument()
  expect(fetchMock).toHaveBeenCalledWith('/control/api/v1/runs/run-1', expect.any(Object))
})


it('opens direct V2 event detail hashes from the events read model', async () => {
  window.location.hash = '#event:7'
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ rows: [{ event_id: 7, event_type: 'Queue Alert', summary: 'Target event summary', entity_id: 'project-1', created_at: '2026-05-21T00:00:00Z' }], page: { returned: 1, has_more: false } }), { status: 200 }))
  saveToken('test-token')

  render(<App />)

  expect(await screen.findByLabelText('Dashboard detail page')).toBeInTheDocument()
  await screen.findByRole('heading', { name: 'Target event summary' })
  expect(screen.queryByText('This V2 page is not implemented yet')).not.toBeInTheDocument()
  expect(fetchMock).toHaveBeenCalledWith('/control/api/v1/events?event_id=7&include_payload=true&page_size=1&sort=recent', expect.any(Object))
})


it('opens legacy review hashes in the V2 automation page instead of legacy fallback', async () => {
  window.location.hash = '#review:paper-legacy'
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ counts: {}, rows: [] }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ item: { paper_id: 'paper-legacy', project_name: 'Legacy review paper', review_status: 'triage_ready', paper_status: 'publication_draft' }, checklist: { items: [] } }), { status: 200 }))
  saveToken('test-token')

  render(<App />)

  expect(await screen.findByRole('heading', { name: 'Publication automation' })).toBeInTheDocument()
  expect(await screen.findByText('Legacy review paper')).toBeInTheDocument()
  expect(screen.queryByText('This V2 page is not implemented yet')).not.toBeInTheDocument()
  expect(fetchMock).toHaveBeenNthCalledWith(2, '/control/api/publication-automation/paper-legacy', expect.any(Object))
})


it('opens intake hashes in the V2 ideas intake page instead of legacy fallback', async () => {
  window.location.hash = '#intake'
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({
      latest_sync: { source: 'idea_intake', status: 'ok', observed_at: '2026-05-21T00:00:00Z', payload: { payload_omitted: true, skipped_row_count: 1 } },
      projection_counts: { queued: 1 },
      skipped_reasons: { duplicate: 1 },
      queued_projection: [{ idea_id: 'idea-1', title: 'Better queue policy', idea_status: 'admitted', queue_status: 'queued', next_action_hint: 'dispatch', source_kind: 'synthetic' }],
    }), { status: 200 }))
  saveToken('test-token')

  render(<App />)

  expect(await screen.findByRole('heading', { name: 'Ideas intake' })).toBeInTheDocument()
  expect(await screen.findByText('Better queue policy')).toBeInTheDocument()
  expect(screen.getByText('duplicate')).toBeInTheDocument()
  expect(screen.queryByText('This V2 page is not implemented yet')).not.toBeInTheDocument()
  expect(fetchMock).toHaveBeenCalledWith('/control/api/intake/ideas?page_size=100', expect.any(Object))
})
