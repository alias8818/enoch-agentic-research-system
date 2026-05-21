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
  expect(screen.queryByRole('link', { name: 'Legacy dashboard' })).not.toBeInTheDocument()
  fireEvent.click(screen.getByText('Show secondary details'))
  expect(screen.getAllByRole('link', { name: 'Runs' }).some((link) => link.getAttribute('href') === '/control/dashboard-v2#runs')).toBe(true)
  expect(screen.getAllByRole('link', { name: 'Papers' }).some((link) => link.getAttribute('href') === '/control/dashboard-v2#papers')).toBe(true)
  expect(screen.getByRole('link', { name: 'Recent activity' })).toHaveAttribute('href', '/control/dashboard-v2#events')

  fireEvent.click(screen.getByRole('button', { name: 'Refresh now' }))
  await waitFor(() => expect(globalThis.fetch).toHaveBeenCalledTimes(5))
})

it('surfaces the movement diagnosis before lane and action controls', async () => {
  vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({
      ok: true,
      generated_at: '2026-05-20T12:00:00Z',
      counts: { active: 0, queued: 0 },
      paper_counts: {},
      flags: {},
      movement_diagnosis: {
        status: 'blocked',
        primary_reason: 'No admitted GB10 candidates.',
        blockers: [
          {
            kind: 'no_admitted_candidates',
            title: 'No admitted candidates',
            summary: 'Generate or promote work before dispatching an idle lane.',
            action_hash: '#research',
            action_label: 'Open research',
          },
        ],
      },
      top_actions: [
        {
          kind: 'investigate_followup',
          priority: 40,
          tone: 'warn',
          title: 'Investigate follow-up candidates',
          summary: 'Promote the strongest candidate before dispatching.',
          action_label: 'Open research',
          action_hash: '#research',
          target: {},
        },
      ],
      paper_pipeline: { write_needed: 0, finalize_needed: 0, publish_ready: 0 },
      recent_events: [],
    }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({
      generated_at: '2026-05-20T12:00:05Z',
      worker_lanes: [
        {
          lane_key: 'gb10',
          label: 'GB10 lane',
          machine_target: 'gb10',
          status: 'idle',
          queued_count: 0,
          dispatch_available: false,
          feed_pressure: { next_autopilot_action: 'generate_candidate' },
        },
      ],
    }), { status: 200 }))
  saveToken('test-token')

  render(<App />)

  const diagnosis = (await screen.findByText('Why no work is moving?')).closest('section') as HTMLElement
  const lanes = screen.getByLabelText('Worker lanes')
  const controls = screen.getByLabelText('Primary action')

  expect(Boolean(diagnosis.compareDocumentPosition(lanes) & Node.DOCUMENT_POSITION_FOLLOWING)).toBe(true)
  expect(Boolean(diagnosis.compareDocumentPosition(controls) & Node.DOCUMENT_POSITION_FOLLOWING)).toBe(true)
  expect(within(diagnosis).getByText('No admitted candidates')).toBeInTheDocument()
})

it('keeps overview command result raw JSON inside collapsed details', async () => {
  vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({
      ok: true,
      generated_at: '2026-05-20T12:00:00Z',
      counts: { active: 0, queued: 1 },
      paper_counts: {},
      movement_diagnosis: { status: 'actionable', primary_reason: 'Dispatch ready.', blockers: [] },
      flags: {},
      top_actions: [{
        kind: 'dispatch_next',
        title: 'Dispatch GB10 lane',
        summary: 'One queued candidate matches the idle lane.',
        action_label: 'Dispatch',
        action_hash: '#queue:queued',
      }],
      primary_operator_action: {
        kind: 'dispatch_next',
        title: 'Dispatch GB10 lane',
        summary: 'One queued candidate matches the idle lane.',
        action_label: 'Check dispatch',
        action_hash: '#queue:queued',
      },
      recent_events: [],
    }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ generated_at: '2026-05-20T12:00:05Z', worker_lanes: [] }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({
      ok: true,
      label: 'Long-haul mode: READY',
      blockers: [],
      checks: [{ name: 'queue_unpaused', ok: true }],
      summary: { queued: 1, active: 0, queue_paused: false, maintenance_mode: false },
    }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({
      action: 'dry_run_dispatch',
      reason: 'dry-run dispatch selected candidate',
      candidate: { project_id: 'project-1', machine_target: 'gb10' },
    }), { status: 200 }))
    .mockResolvedValue(new Response(JSON.stringify({
      ok: true,
      generated_at: '2026-05-20T12:00:10Z',
      counts: { active: 0, queued: 1 },
      paper_counts: {},
      movement_diagnosis: { status: 'actionable', primary_reason: 'Dispatch ready.', blockers: [] },
      flags: {},
      top_actions: [{
        kind: 'dispatch_next',
        title: 'Dispatch GB10 lane',
        summary: 'One queued candidate matches the idle lane.',
        action_label: 'Dispatch',
        action_hash: '#queue:queued',
      }],
      primary_operator_action: {
        kind: 'dispatch_next',
        title: 'Dispatch GB10 lane',
        summary: 'One queued candidate matches the idle lane.',
        action_label: 'Check dispatch',
        action_hash: '#queue:queued',
      },
      recent_events: [],
    }), { status: 200 }))
  saveToken('test-token')

  render(<App />)

  await screen.findByText('Can I leave this running?')
  fireEvent.click(within(screen.getByLabelText('Primary action')).getByRole('button', { name: 'Check readiness' }))
  await within(screen.getByLabelText('Readiness check')).findByText('Long-haul mode: READY')
  fireEvent.click(screen.getByRole('button', { name: 'Check dispatch' }))
  await screen.findByText('dry-run dispatch selected candidate')

  const resultCard = screen.getByText('Selected work').closest('.command-result-summary') as HTMLElement
  resultCard.querySelectorAll('.json-block').forEach((block) => {
    expect(block.closest('details.raw-details')).not.toBeNull()
  })
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

it('does not claim secondary readiness passed before readiness data loads', async () => {
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
  saveToken('test-token')

  render(<App />)

  expect(await screen.findByText('Can I leave this running?')).toBeInTheDocument()
  const secondaryReadiness = screen.getByLabelText('Automation readiness')
  expect(within(secondaryReadiness).getByText('Automation readiness unavailable')).toBeInTheDocument()
  expect(within(secondaryReadiness).queryByText('All reported long-haul readiness checks passed.')).not.toBeInTheDocument()
})

it('does not answer leave-running as ready before readiness is checked', async () => {
  vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({
      ok: true,
      generated_at: '2026-05-20T12:00:00Z',
      counts: { active: 0, queued: 0 },
      paper_counts: {},
      movement_diagnosis: { status: 'ready', primary_reason: 'No movement blockers.', blockers: [] },
      flags: {},
      recent_events: [],
    }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ generated_at: '2026-05-20T12:00:05Z', worker_lanes: [] }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({
      ok: false,
      label: 'Long-haul mode: BLOCKED — queued/active state inconsistent',
      blockers: ['queue_counts_consistent: blocked'],
      checks: [{ name: 'queue_counts_consistent', ok: false }],
      summary: { queued: 3, active: 2, queue_paused: false, maintenance_mode: false },
    }), { status: 200 }))
  saveToken('test-token')

  render(<App />)

  const leaveRunningHero = (await screen.findByText('Can I leave this running?')).closest('section') as HTMLElement
  expect(within(leaveRunningHero).getByRole('heading', { level: 1, name: 'Check readiness first' })).toBeInTheDocument()
  expect(within(leaveRunningHero).getByText('Run the readiness check before leaving automation unattended.')).toBeInTheDocument()

  fireEvent.click(within(screen.getByLabelText('Readiness check')).getByRole('button', { name: 'Check readiness' }))

  expect(await within(leaveRunningHero).findByText('Not yet')).toBeInTheDocument()
  expect(screen.getAllByText('queue_counts_consistent: blocked').length).toBeGreaterThan(0)
})

it('checks automation readiness above the fold on demand', async () => {
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
      ok: true,
      label: 'Long-haul mode: READY',
      blockers: [],
      checks: [{ name: 'queue_unpaused', ok: true }],
      summary: { queued: 0, active: 0, queue_paused: false, maintenance_mode: false },
    }), { status: 200 }))
  saveToken('test-token')

  render(<App />)

  expect(await screen.findByText('Can I leave this running?')).toBeInTheDocument()
  await waitFor(() => expect(globalThis.fetch).toHaveBeenCalledTimes(2))
  const readinessCard = screen.getByLabelText('Readiness check')
  expect(readinessCard).toHaveTextContent('Not checked')
  expect(globalThis.fetch).not.toHaveBeenCalledWith('/control/api/v1/automation-readiness', expect.any(Object))

  fireEvent.click(within(readinessCard).getByRole('button', { name: 'Check readiness' }))

  expect(await within(readinessCard).findByText('Long-haul mode: READY')).toBeInTheDocument()
  expect(globalThis.fetch).toHaveBeenNthCalledWith(3, '/control/api/v1/automation-readiness', expect.any(Object))
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
  await waitFor(() => expect(globalThis.fetch).toHaveBeenCalledTimes(2))
  expect(globalThis.fetch).not.toHaveBeenCalledWith('/control/api/v1/automation-readiness', expect.any(Object))

  fireEvent.click(screen.getByText('Show secondary details'))

  const secondaryReadiness = screen.getByLabelText('Automation readiness')
  expect(await within(secondaryReadiness).findByText('Automation readiness')).toBeInTheDocument()
  expect(await within(secondaryReadiness).findByText('Long-haul mode: BLOCKED — queued/active state inconsistent')).toBeInTheDocument()
  expect(within(secondaryReadiness).getAllByText('queue_counts_consistent: blocked')).toHaveLength(2)
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


it('keeps visible resource filters aligned with hash navigation', async () => {
  window.location.hash = '#queue:queued'
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ rows: [{ project_id: 'queued-project', status: 'queued', title: 'Queued item' }], page: { returned: 1, has_more: false } }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ rows: [{ project_id: 'active-project', status: 'active', title: 'Active item' }], page: { returned: 1, has_more: false } }), { status: 200 }))
  saveToken('test-token')

  render(<App />)
  await screen.findByText('Queued item')

  window.location.hash = '#queue:active'
  window.dispatchEvent(new HashChangeEvent('hashchange'))

  await screen.findByText('Active item')
  expect(screen.getByLabelText(/Status/i)).toHaveValue('active')
  expect(new URL(String(fetchMock.mock.calls[0][0]), 'https://enoch.local').searchParams.get('status')).toBe('queued')
  expect(new URL(String(fetchMock.mock.calls[1][0]), 'https://enoch.local').searchParams.get('status')).toBe('active')
})

it('keeps unsupported hashes inside the V2 shell with route suggestions only', () => {
  window.location.hash = '#unknown-workflow'
  saveToken('test-token')

  render(<App />)

  expect(screen.getByRole('heading', { name: 'Unsupported V2 route' })).toBeInTheDocument()
  expect(screen.queryByText('This V2 page is not implemented yet')).not.toBeInTheDocument()
  expect(screen.getAllByRole('link', { name: /command center/i })).toHaveLength(1)
  expect(screen.queryByRole('link', { name: 'Open this hash in legacy dashboard' })).not.toBeInTheDocument()
})

it('canonicalizes alias hashes to supported routes on load', () => {
  window.location.hash = '#reviews'
  saveToken('test-token')

  render(<App />)

  expect(window.location.hash).toBe('#automation')
  expect(screen.getByRole('heading', { name: 'Publication automation' })).toBeInTheDocument()
})

it('redirects legacy status hashes to the command center', () => {
  window.location.hash = '#status'
  saveToken('test-token')
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({
    generated_at: '2026-05-21T12:00:00Z',
    queue: { queued: 0, active: 0 },
    paper_pipeline: { publish_ready: 0, published_imported: 0, publication_ready_total: 0 },
    events: [],
  }), { status: 200 }))

  render(<App />)

  expect(window.location.hash).toBe('#overview')
})


it('uses V2-authored token and fallback surfaces', () => {
  render(<App />)
  expect(screen.getByRole('heading', { name: 'Bearer token required' })).toBeInTheDocument()
  expect(screen.getByLabelText('Bearer token')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Save token' })).toBeInTheDocument()
  expect(screen.queryByRole('link', { name: 'Open legacy dashboard' })).not.toBeInTheDocument()
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
  await screen.findByRole('heading', { name: 'Target event summary', level: 1 })
  expect(screen.getByText('Event detail · 7 · Target event summary')).toBeInTheDocument()
  expect(screen.queryByText('This V2 page is not implemented yet')).not.toBeInTheDocument()
  expect(fetchMock).toHaveBeenCalledWith('/control/api/v1/events?event_id=7&include_payload=true&page_size=1&sort=recent', expect.any(Object))
})





it('keeps corpus hash filters in the V2 corpus read model', async () => {
  window.location.hash = '#corpus?status=draft_review&search=manifest'
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ paper_pipeline: { publish_ready: 0, published_imported: 0, publication_ready_total: 0 } }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ rows: [{ paper_id: 'paper-manifest', status: 'draft_review', title: 'Manifest review paper' }], page: { returned: 1 } }), { status: 200 }))
  saveToken('test-token')

  render(<App />)

  expect(await screen.findByRole('heading', { name: 'Corpus import' })).toBeInTheDocument()
  expect(await screen.findByText('Manifest review paper')).toBeInTheDocument()
  expect(fetchMock).toHaveBeenNthCalledWith(2, '/control/api/v1/papers?page_size=50&sort=recent&status=draft_review&search=manifest', expect.any(Object))
})

it('keeps project and run hash search filters in V2 read models', async () => {
  window.location.hash = '#projects?status=testing&search=oracle'
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ rows: [{ project_id: 'project-filtered', project_name: 'Oracle project', origin_idea_status: 'testing' }], page: { returned: 1 } }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ rows: [{ run_id: 'run-filtered', state: 'running', current_activity: 'oracle replay' }], page: { returned: 1 } }), { status: 200 }))
  saveToken('test-token')

  render(<App />)

  expect(await screen.findByRole('heading', { name: 'Projects' })).toBeInTheDocument()
  expect(await screen.findByText('Oracle project')).toBeInTheDocument()
  expect(fetchMock).toHaveBeenNthCalledWith(1, '/control/api/v1/projects?page_size=50&sort=recent&status=testing&search=oracle', expect.any(Object))

  window.location.hash = '#runs:running?search=replay'
  window.dispatchEvent(new HashChangeEvent('hashchange'))

  expect(await screen.findByRole('heading', { name: 'Runs' })).toBeInTheDocument()
  expect(await screen.findByText('oracle replay')).toBeInTheDocument()
  expect(fetchMock).toHaveBeenNthCalledWith(2, '/control/api/v1/runs?page_size=50&sort=recent&state=running&search=replay', expect.any(Object))
})

it('keeps queue hash search filters in the V2 queue read model', async () => {
  window.location.hash = '#queue:queued?search=gb10'
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ rows: [{ project_id: 'queued-gb10', status: 'queued', title: 'GB10 queued work' }], page: { returned: 1 } }), { status: 200 }))
  saveToken('test-token')

  render(<App />)

  expect(await screen.findByRole('heading', { name: 'Queue' })).toBeInTheDocument()
  expect(await screen.findByText('GB10 queued work')).toBeInTheDocument()
  expect(fetchMock).toHaveBeenCalledWith('/control/api/v1/queue?page_size=50&sort=priority&status=queued&search=gb10&queue=all', expect.any(Object))
})

it('keeps paper hash filters in the V2 papers read model', async () => {
  window.location.hash = '#papers?status=publication_draft&search=trace-oracle'
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ rows: [{ paper_id: 'paper-filtered', status: 'publication_draft', title: 'Trace oracle paper' }], page: { returned: 1 } }), { status: 200 }))
  saveToken('test-token')

  render(<App />)

  expect(await screen.findByRole('heading', { name: 'Papers' })).toBeInTheDocument()
  expect(await screen.findByText('Trace oracle paper')).toBeInTheDocument()
  expect(fetchMock).toHaveBeenCalledWith('/control/api/v1/papers?page_size=50&sort=recent&status=publication_draft&search=trace-oracle', expect.any(Object))
})

it('keeps event hash filters in the V2 events read model', async () => {
  window.location.hash = '#events?event_type=Queue%20Alert&search=active-lane'
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ rows: [{ id: 'event-filtered', event_type: 'Queue Alert', summary: 'active-lane blocked' }], page: { returned: 1 } }), { status: 200 }))
  saveToken('test-token')

  render(<App />)

  expect(await screen.findByRole('heading', { name: 'Events' })).toBeInTheDocument()
  expect(await screen.findByText('active-lane blocked')).toBeInTheDocument()
  expect(fetchMock).toHaveBeenCalledWith('/control/api/v1/events?page_size=50&sort=recent&event_type=Queue+Alert&search=active-lane', expect.any(Object))
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

it('opens intake idea hashes as first-class V2 details', async () => {
  window.location.hash = '#idea:idea-1'
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({
      latest_sync: { source: 'idea_intake', status: 'ok', observed_at: '2026-05-21T00:00:00Z' },
      projection_counts: { queued: 1 },
      queued_projection: [
        { idea_id: 'idea-1', title: 'Direct idea detail', idea_status: 'admitted', queue_status: 'queued', next_action_hint: 'dispatch', source_kind: 'synthetic' },
        { idea_id: 'idea-2', title: 'Other idea', idea_status: 'candidate', queue_status: '' },
      ],
    }), { status: 200 }))
  saveToken('test-token')

  render(<App />)

  expect(await screen.findByRole('heading', { name: 'Ideas intake' })).toBeInTheDocument()
  const detail = await screen.findByLabelText('Intake idea detail')
  expect(detail).toHaveTextContent('Direct idea detail')
  expect(detail).toHaveTextContent('idea-1')
  expect(detail).toHaveTextContent('dispatch')
  expect(screen.queryByText('This V2 page is not implemented yet')).not.toBeInTheDocument()
  expect(fetchMock).toHaveBeenCalledWith('/control/api/intake/ideas?page_size=100', expect.any(Object))
})

it('uses compact secondary page headers instead of repeating the command-center hero', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({
    ok: true,
    generated_at: '2026-05-21T10:00:00Z',
    page: { returned: 0, has_more: false },
    rows: [],
  }), { status: 200 }))
  saveToken('test-token')
  window.location.hash = '#projects'

  const { container } = render(<App />)

  expect(await screen.findByRole('heading', { level: 1, name: 'Projects' })).toBeInTheDocument()
  expect(document.querySelector('.app-header-context')).toHaveTextContent('Projects')
  expect(screen.queryByRole('heading', { name: 'Operator command center' })).not.toBeInTheDocument()
  expect(container.querySelector('.page-hero')).toBeNull()
  expect(screen.getByText('Data source')).toBeInTheDocument()
})

it('routes global search to the projects list with a search query', async () => {
  vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({
      ok: true,
      generated_at: '2026-05-21T10:00:00Z',
      counts: { active: 0, queued: 0 },
      paper_counts: {},
      movement_diagnosis: { status: 'ready', primary_reason: 'No blockers.', blockers: [] },
      flags: {},
    }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ generated_at: '2026-05-21T10:00:05Z', worker_lanes: [] }), { status: 200 }))
    .mockResolvedValue(new Response(JSON.stringify({
      ok: true,
      generated_at: '2026-05-21T10:00:00Z',
      page: { returned: 0, has_more: false },
      rows: [],
    }), { status: 200 }))
  saveToken('test-token')
  window.location.hash = '#overview'

  render(<App />)
  await screen.findByText('Can I leave this running?')

  fireEvent.change(screen.getByLabelText('Global search'), { target: { value: 'oracle lane' } })
  fireEvent.click(screen.getByRole('button', { name: 'Search projects' }))

  expect(window.location.hash).toBe('#projects?search=oracle%20lane')
})

it('toggles the dashboard theme from the shell header', async () => {
  vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({
      ok: true,
      generated_at: '2026-05-21T10:00:00Z',
      counts: { active: 0, queued: 0 },
      paper_counts: {},
      movement_diagnosis: { status: 'ready', primary_reason: 'No blockers.', blockers: [] },
      flags: {},
    }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ generated_at: '2026-05-21T10:00:05Z', worker_lanes: [] }), { status: 200 }))
  saveToken('test-token')

  render(<App />)
  await screen.findByText('Can I leave this running?')

  expect(document.documentElement.dataset.theme).toBe('dark')
  fireEvent.click(screen.getByRole('button', { name: 'Switch to light theme' }))
  expect(document.documentElement.dataset.theme).toBe('light')
  expect(screen.getByRole('button', { name: 'Switch to dark theme' })).toBeInTheDocument()
})

it('opens keyboard shortcut help from the header button and question-mark shortcut', async () => {
  vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true, generated_at: '2026-05-20T12:00:00Z', counts: { active: 0, queued: 0 }, paper_counts: {}, movement_diagnosis: { status: 'ready', primary_reason: 'No blockers.', blockers: [] }, flags: {} }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ generated_at: '2026-05-20T12:00:05Z', worker_lanes: [] }), { status: 200 }))
  saveToken('test-token')

  render(<App />)
  await screen.findByText('Can I leave this running?')

  fireEvent.click(screen.getByRole('button', { name: 'Show keyboard shortcuts' }))
  expect(screen.getByRole('heading', { name: 'Keyboard shortcuts' })).toBeInTheDocument()
  expect(screen.getByText('Focus global project search')).toBeInTheDocument()

  fireEvent.click(screen.getByRole('button', { name: 'Close' }))
  expect(screen.queryByRole('heading', { name: 'Keyboard shortcuts' })).not.toBeInTheDocument()

  fireEvent.keyDown(window, { key: '?' })
  expect(screen.getByRole('heading', { name: 'Keyboard shortcuts' })).toBeInTheDocument()

  fireEvent.keyDown(window, { key: '/' })
  expect(screen.getByRole('textbox', { name: /global search/i })).toHaveFocus()
})
