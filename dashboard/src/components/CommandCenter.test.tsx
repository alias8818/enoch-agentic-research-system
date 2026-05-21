import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { CommandHero } from './CommandHero'
import { MovementDiagnosis } from './MovementDiagnosis'
import { PaperMiniStrip } from './PaperMiniStrip'
import { PrimaryAction } from './PrimaryAction'
import { SafetyBar } from './SafetyBar'
import { WorkerLanes } from './WorkerLanes'

const diagnosis = {
  status: 'actionable',
  primary_reason: 'GB10 lane can dispatch queued work.',
  blockers: [{ kind: 'dispatch_available', title: 'GB10 lane can dispatch', summary: 'GB10 lane can dispatch queued work.', action_hash: '#queue:queued' }],
}

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

it('renders the leave-running hero from backend diagnosis', () => {
  render(<CommandHero overview={{ ok: true, counts: { active: 1, queued: 2 }, paper_counts: { publication_draft: 1 } }} diagnosis={diagnosis} />)
  expect(screen.getByText('Can I leave this running?')).toBeInTheDocument()
  expect(screen.getByText('Yes, but there is work you can start')).toBeInTheDocument()
  expect(screen.getByText('GB10 lane can dispatch queued work.')).toBeInTheDocument()
})

it('runs dispatch primary actions as safe dry-runs instead of only linking away', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ action: 'dry_run_dispatch', reason: 'dry-run dispatch selected candidate' }), { status: 200 }))
  const onRefresh = vi.fn()

  render(<PrimaryAction action={{ kind: 'dispatch_next', title: 'Dispatch GB10 lane', summary: 'One queued candidate matches the idle lane.', action_label: 'Dispatch', action_hash: '#queue:queued' }} onRefresh={onRefresh} />)

  expect(screen.getByText('Primary action')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Check dispatch' }))

  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))
  expect(fetchMock).toHaveBeenCalledWith('/control/dispatch-next', expect.objectContaining({
    method: 'POST',
    body: expect.stringContaining('"dry_run":true'),
  }))
  expect(screen.getByText('Primary action dry-run')).toBeInTheDocument()
  expect(screen.getByText('dry-run dispatch selected candidate')).toBeInTheDocument()
  expect(onRefresh).toHaveBeenCalledTimes(1)
})

it('dispatches the top dispatch action only after dry-run and dialog confirmation', async () => {
  const confirmSpy = vi.spyOn(window, 'confirm')
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ action: 'dry_run_dispatch', reason: 'dry-run dispatch selected candidate' }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ action: 'dispatch_started', reason: 'live dispatch accepted selected candidate' }), { status: 200 }))
  const onRefresh = vi.fn()

  render(<PrimaryAction action={{ kind: 'dispatch_next', title: 'Dispatch GB10 lane', summary: 'One queued candidate matches the idle lane.', action_label: 'Dispatch', action_hash: '#queue:queued' }} onRefresh={onRefresh} />)
  expect(screen.getByRole('button', { name: 'Dispatch work' })).toBeDisabled()

  fireEvent.click(screen.getByRole('button', { name: 'Check dispatch' }))
  await screen.findByText('dry-run dispatch selected candidate')

  fireEvent.click(screen.getByRole('button', { name: 'Dispatch work' }))
  const dialog = await screen.findByRole('dialog', { name: 'Dispatch top action?' })
  expect(dialog).toHaveTextContent('starts live dispatch')
  expect(confirmSpy).not.toHaveBeenCalled()
  fireEvent.click(dialog.querySelectorAll('button')[1])

  await screen.findByText('live dispatch accepted selected candidate')
  expect(fetchMock).toHaveBeenNthCalledWith(1, '/control/dispatch-next', expect.objectContaining({
    method: 'POST',
    body: JSON.stringify({ dry_run: true, requested_by: 'dashboard-v2', force_preflight: true }),
  }))
  expect(fetchMock).toHaveBeenNthCalledWith(2, '/control/dispatch-next', expect.objectContaining({
    method: 'POST',
    body: JSON.stringify({ dry_run: false, requested_by: 'dashboard-v2', force_preflight: true }),
  }))
  expect(onRefresh).toHaveBeenCalledTimes(2)
})

it('runs follow-up primary actions as safe dry-runs instead of only linking away', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ action: 'dry_run_followup', reason: 'would queue bounded follow-up', followup: { idea_id: 'follow-1' } }), { status: 200 }))
  const onRefresh = vi.fn()

  render(<PrimaryAction action={{ kind: 'investigate_followup', title: 'Launch follow-up', summary: 'A bounded adjacent test is ready.', action_label: 'Launch follow-up', action_hash: '#research' }} onRefresh={onRefresh} />)

  fireEvent.click(screen.getByRole('button', { name: 'Check follow-up' }))

  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))
  expect(fetchMock).toHaveBeenCalledWith('/control/api/v1/followups/launch-next', expect.objectContaining({
    method: 'POST',
    body: expect.stringContaining('"dry_run":true'),
  }))
  expect(String(fetchMock.mock.calls[0][1]?.body)).toContain('"max_followup_depth":4')
  expect(screen.getByText('Primary action dry-run')).toBeInTheDocument()
  expect(screen.getByText('would queue bounded follow-up')).toBeInTheDocument()
  expect(onRefresh).toHaveBeenCalledTimes(1)
})

it('launches the top follow-up action only after dry-run and dialog confirmation', async () => {
  const confirmSpy = vi.spyOn(window, 'confirm')
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ action: 'dry_run_followup', reason: 'would queue bounded follow-up', followup: { idea_id: 'follow-1', title: 'Follow-up test' } }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ action: 'followup_queued', reason: 'follow-up queued without dispatch', followup: { idea_id: 'follow-1' } }), { status: 200 }))
  const onRefresh = vi.fn()

  render(<PrimaryAction action={{ kind: 'investigate_followup', title: 'Launch follow-up', summary: 'A bounded adjacent test is ready.', action_label: 'Launch follow-up', action_hash: '#research' }} onRefresh={onRefresh} />)
  expect(screen.getByRole('button', { name: 'Launch follow-up' })).toBeDisabled()

  fireEvent.click(screen.getByRole('button', { name: 'Check follow-up' }))
  await screen.findByText('would queue bounded follow-up')

  fireEvent.click(screen.getByRole('button', { name: 'Launch follow-up' }))
  const dialog = await screen.findByRole('dialog', { name: 'Launch follow-up investigation?' })
  expect(dialog).toHaveTextContent('queues investigation work')
  expect(confirmSpy).not.toHaveBeenCalled()
  fireEvent.click(dialog.querySelectorAll('button')[1])

  await screen.findByText('follow-up queued without dispatch')
  expect(fetchMock).toHaveBeenNthCalledWith(1, '/control/api/v1/followups/launch-next', expect.objectContaining({
    method: 'POST',
    body: JSON.stringify({ dry_run: true, requested_by: 'dashboard-v2', max_followup_depth: 4 }),
  }))
  expect(fetchMock).toHaveBeenNthCalledWith(2, '/control/api/v1/followups/launch-next', expect.objectContaining({
    method: 'POST',
    body: JSON.stringify({ dry_run: false, requested_by: 'dashboard-v2', max_followup_depth: 4 }),
  }))
  expect(onRefresh).toHaveBeenCalledTimes(2)
})

it('runs write-paper primary actions as safe dry-runs instead of only linking away', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ action: 'dry_run_draft', reason: 'eligible paper-ready candidate found', paper: { paper_id: 'paper-1' } }), { status: 200 }))
  const onRefresh = vi.fn()

  render(<PrimaryAction action={{ kind: 'write_paper', title: 'Draft next paper', summary: 'Paper-ready run exists.', action_label: 'Open draft lane', action_hash: '#papers?status=publication_draft' }} onRefresh={onRefresh} />)

  fireEvent.click(screen.getByRole('button', { name: 'Check draft' }))

  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))
  expect(fetchMock).toHaveBeenCalledWith('/control/papers/draft-next', expect.objectContaining({
    method: 'POST',
    body: expect.stringContaining('"dry_run":true'),
  }))
  expect(String(fetchMock.mock.calls[0][1]?.body)).toContain('"force":true')
  expect(screen.getByText('Primary action dry-run')).toBeInTheDocument()
  expect(screen.getByText('eligible paper-ready candidate found')).toBeInTheDocument()
  expect(onRefresh).toHaveBeenCalledTimes(1)
})

it('drafts the top write-paper action only after dry-run and dialog confirmation', async () => {
  const confirmSpy = vi.spyOn(window, 'confirm')
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ action: 'dry_run_draft', reason: 'eligible paper-ready candidate found', paper: { paper_id: 'paper-1' } }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ action: 'draft_created', reason: 'draft written for paper-ready candidate', paper: { paper_id: 'paper-1' } }), { status: 200 }))
  const onRefresh = vi.fn()

  render(<PrimaryAction action={{ kind: 'write_paper', title: 'Draft next paper', summary: 'Paper-ready run exists.', action_label: 'Open draft lane', action_hash: '#papers?status=publication_draft' }} onRefresh={onRefresh} />)
  expect(screen.getByRole('button', { name: 'Draft paper' })).toBeDisabled()

  fireEvent.click(screen.getByRole('button', { name: 'Check draft' }))
  await screen.findByText('eligible paper-ready candidate found')

  fireEvent.click(screen.getByRole('button', { name: 'Draft paper' }))
  const dialog = await screen.findByRole('dialog', { name: 'Draft next paper?' })
  expect(dialog).toHaveTextContent('writes draft artifacts')
  expect(confirmSpy).not.toHaveBeenCalled()
  fireEvent.click(dialog.querySelectorAll('button')[1])

  await screen.findByText('draft written for paper-ready candidate')
  expect(fetchMock).toHaveBeenNthCalledWith(1, '/control/papers/draft-next', expect.objectContaining({
    method: 'POST',
    body: JSON.stringify({ dry_run: true, requested_by: 'dashboard-v2', force: true }),
  }))
  expect(fetchMock).toHaveBeenNthCalledWith(2, '/control/papers/draft-next', expect.objectContaining({
    method: 'POST',
    body: JSON.stringify({ dry_run: false, requested_by: 'dashboard-v2', force: true }),
  }))
  expect(onRefresh).toHaveBeenCalledTimes(2)
})

it('runs finalize-paper primary actions as safe dry-runs instead of only linking away', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ action: 'dry_run_rewrite_batch', reason: 'would finalize 2 publication drafts', candidates: [{ paper_id: 'paper-1' }] }), { status: 200 }))
  const onRefresh = vi.fn()

  render(<PrimaryAction action={{ kind: 'finalize_paper', title: 'Finalize publication drafts', summary: 'Publication drafts need packages.', action_label: 'Open automation queue', action_hash: '#automation' }} onRefresh={onRefresh} />)

  fireEvent.click(screen.getByRole('button', { name: 'Check finalization' }))

  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))
  expect(fetchMock).toHaveBeenCalledWith('/control/api/paper-reviews/rewrite-batch', expect.objectContaining({
    method: 'POST',
    body: expect.stringContaining('"dry_run":true'),
  }))
  expect(String(fetchMock.mock.calls[0][1]?.body)).toContain('"paper_status":"publication_draft"')
  expect(String(fetchMock.mock.calls[0][1]?.body)).toContain('"skip_rewritten":true')
  expect(screen.getByText('Primary action dry-run')).toBeInTheDocument()
  expect(screen.getByText('would finalize 2 publication drafts')).toBeInTheDocument()
  expect(onRefresh).toHaveBeenCalledTimes(1)
})

it('finalizes the top paper action only after dry-run and dialog confirmation', async () => {
  const confirmSpy = vi.spyOn(window, 'confirm')
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ dry_run: true, matched: 2, processed: 2, reason: 'would finalize 2 publication drafts' }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ dry_run: false, rewritten: 2, failed: 0, reason: 'finalized 2 publication drafts' }), { status: 200 }))
  const onRefresh = vi.fn()

  render(<PrimaryAction action={{ kind: 'finalize_paper', title: 'Finalize publication drafts', summary: 'Publication drafts need packages.', action_label: 'Open automation queue', action_hash: '#automation' }} onRefresh={onRefresh} />)
  expect(screen.getByRole('button', { name: 'Finalize drafts' })).toBeDisabled()

  fireEvent.click(screen.getByRole('button', { name: 'Check finalization' }))
  await screen.findByText('would finalize 2 publication drafts')

  fireEvent.click(screen.getByRole('button', { name: 'Finalize drafts' }))
  const dialog = await screen.findByRole('dialog', { name: 'Finalize publication drafts?' })
  expect(dialog).toHaveTextContent('rewrites publication draft packages')
  expect(confirmSpy).not.toHaveBeenCalled()
  fireEvent.click(dialog.querySelectorAll('button')[1])

  await screen.findByText('finalized 2 publication drafts')
  expect(fetchMock).toHaveBeenNthCalledWith(1, '/control/api/paper-reviews/rewrite-batch', expect.objectContaining({
    method: 'POST',
    body: expect.stringContaining('"idempotency_key":"primary-action-rewrite-batch:dashboard-v2:'),
  }))
  expect(String(fetchMock.mock.calls[0][1]?.body)).toContain('"dry_run":true')
  expect(String(fetchMock.mock.calls[0][1]?.body)).toContain('"paper_status":"publication_draft"')
  expect(String(fetchMock.mock.calls[0][1]?.body)).toContain('"skip_rewritten":true')
  expect(fetchMock).toHaveBeenNthCalledWith(2, '/control/api/paper-reviews/rewrite-batch', expect.objectContaining({
    method: 'POST',
    body: expect.stringContaining('"idempotency_key":"primary-action-rewrite-batch-live:dashboard-v2:'),
  }))
  expect(String(fetchMock.mock.calls[1][1]?.body)).toContain('"dry_run":false')
  expect(String(fetchMock.mock.calls[1][1]?.body)).toContain('"force":true')
  expect(String(fetchMock.mock.calls[1][1]?.body)).toContain('"paper_status":"publication_draft"')
  expect(onRefresh).toHaveBeenCalledTimes(2)
})

it('keeps non-command primary actions as V2 links', () => {
  render(<PrimaryAction action={{ kind: 'publish_paper', title: 'Import finalized drafts', summary: 'Finalized drafts need corpus import.', action_label: 'Open corpus import', action_hash: '#corpus' }} />)
  expect(screen.getByRole('link', { name: 'Open corpus import' })).toHaveAttribute('href', '/control/dashboard-v2#corpus')
})

it('renders worker lane commands without deriving queue truth from aggregate counts', () => {
  render(<WorkerLanes lanes={[{ lane_key: 'cpu', machine_target: 'cpu-proxmox-1', status: 'active', queued_count: 0, dispatch_available: false, active_item: { project_name: 'CPU job' } }, { lane_key: 'gb10', machine_target: 'gb10', status: 'idle', queued_count: 1, dispatch_available: true, next_candidate: { project_name: 'GB10 job' } }]} onRefresh={() => undefined} />)
  expect(screen.getByText('CPU lane')).toBeInTheDocument()
  expect(screen.getByText('GB10 lane')).toBeInTheDocument()
  expect(screen.getByText('CPU job')).toBeInTheDocument()
  expect(screen.getByText('GB10 job')).toBeInTheDocument()
  expect(screen.getByText('Lane is active.')).toBeInTheDocument()
  expect(screen.getByText('Ready to dispatch queued work.')).toBeInTheDocument()
  expect(screen.getAllByText('Check dispatch')).toHaveLength(2)
})

it('uses dialog confirmations for queue pause instead of window.confirm', async () => {
  const confirmSpy = vi.spyOn(window, 'confirm')
  const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ ok: true }), { status: 200 }))
  const onRefresh = vi.fn()

  render(<SafetyBar flags={{ queue_paused: false, maintenance_mode: false }} onRefresh={onRefresh} />)
  fireEvent.click(screen.getByRole('button', { name: 'Pause queue' }))

  expect(await screen.findByRole('dialog', { name: 'Pause the queue?' })).toBeInTheDocument()
  expect(confirmSpy).not.toHaveBeenCalled()
  const dialog = screen.getByRole('dialog', { name: 'Pause the queue?' })
  fireEvent.click(dialog.querySelectorAll('button')[1])

  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith('/control/pause', expect.objectContaining({ method: 'POST' })))
  expect(onRefresh).toHaveBeenCalledTimes(1)
})

it('dry-runs dispatch from lane buttons without starting live dispatch', async () => {
  const confirmSpy = vi.spyOn(window, 'confirm')
  const alertSpy = vi.spyOn(window, 'alert')
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ action: 'dry_run_dispatch', reason: 'dry-run dispatch selected candidate', candidate: { project_name: 'GB10 job' } }), { status: 200 }))
  const onRefresh = vi.fn()

  render(<WorkerLanes lanes={[{ lane_key: 'gb10', machine_target: 'gb10', status: 'idle', queued_count: 1, dispatch_available: true, next_candidate: { project_name: 'GB10 job' } }]} onRefresh={onRefresh} />)
  fireEvent.click(screen.getByRole('button', { name: 'Check dispatch' }))

  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))
  expect(fetchMock).toHaveBeenCalledWith('/control/dispatch-next', expect.objectContaining({
    method: 'POST',
    body: expect.stringContaining('"dry_run":true'),
  }))
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  expect(screen.getByText('Dispatch dry-run result')).toBeInTheDocument()
  expect(screen.getByText('dry-run dispatch selected candidate')).toBeInTheDocument()
  expect(confirmSpy).not.toHaveBeenCalled()
  expect(alertSpy).not.toHaveBeenCalled()
  expect(onRefresh).toHaveBeenCalledTimes(1)
})

it('uses a dialog before live dispatching open lanes', async () => {
  const confirmSpy = vi.spyOn(window, 'confirm')
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ action: 'dispatch_started', reason: 'live dispatch accepted queued work' }), { status: 200 }))
  const onRefresh = vi.fn()

  render(<WorkerLanes lanes={[{ lane_key: 'gb10', machine_target: 'gb10', status: 'idle', queued_count: 1, dispatch_available: true, next_candidate: { project_name: 'GB10 job' } }]} onRefresh={onRefresh} />)
  fireEvent.click(screen.getByRole('button', { name: 'Dispatch open lanes' }))

  expect(await screen.findByRole('dialog', { name: 'Dispatch open lanes?' })).toBeInTheDocument()
  expect(confirmSpy).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: 'Dispatch work' }))

  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))
  expect(fetchMock).toHaveBeenCalledWith('/control/dispatch-next', expect.objectContaining({
    method: 'POST',
    body: expect.stringContaining('"dry_run":false'),
  }))
  expect(screen.getByText('Live dispatch result')).toBeInTheDocument()
  expect(screen.getByText('live dispatch accepted queued work')).toBeInTheDocument()
  expect(onRefresh).toHaveBeenCalledTimes(1)
})

it('dry-runs feed actions without spending provider requests or promoting work', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ action: 'research_cycle_blocked', dry_run: true, reason: 'provider budget passed; no provider request spent' }), { status: 200 }))
  const onRefresh = vi.fn()

  render(<WorkerLanes lanes={[{ lane_key: 'gb10', machine_target: 'gb10', status: 'idle', queued_count: 0, dispatch_available: false, feed_pressure: { next_autopilot_action: 'generate_candidate' } }]} onRefresh={onRefresh} />)
  fireEvent.click(screen.getByRole('button', { name: 'Feed idle lane' }))

  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))
  expect(fetchMock).toHaveBeenCalledWith('/control/api/research/run-cycle', expect.objectContaining({
    method: 'POST',
    body: expect.stringContaining('"dry_run":true'),
  }))
  expect(String(fetchMock.mock.calls[0][1]?.body)).toContain('"enabled":false')
  expect(String(fetchMock.mock.calls[0][1]?.body)).toContain('"max_dispatches_per_run":0')
  expect(screen.getByText('Feed dry-run result')).toBeInTheDocument()
  expect(screen.getByText('provider budget passed; no provider request spent')).toBeInTheDocument()
  expect(onRefresh).toHaveBeenCalledTimes(1)
})

it('keeps live feed disabled after a blocked feed dry-run', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ action: 'research_cycle_blocked', dry_run: true, reason: 'provider budget blocked; no provider request should run' }), { status: 200 }))
  const onRefresh = vi.fn()

  render(<WorkerLanes lanes={[{ lane_key: 'gb10', machine_target: 'gb10', status: 'idle', queued_count: 0, dispatch_available: false, feed_pressure: { next_autopilot_action: 'generate_candidate' } }]} onRefresh={onRefresh} />)

  expect(screen.getByRole('button', { name: 'Run feed cycle' })).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: 'Feed idle lanes' }))

  await screen.findByText('provider budget blocked; no provider request should run')
  expect(fetchMock).toHaveBeenCalledTimes(1)
  expect(screen.getByRole('button', { name: 'Run feed cycle' })).toBeDisabled()
})

it('runs a confirmed live feed cycle only after a feed dry-run', async () => {
  const confirmSpy = vi.spyOn(window, 'confirm')
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ action: 'research_cycle_dry_run', dry_run: true, reason: 'would generate one candidate' }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ action: 'research_cycle_live', dry_run: false, reason: 'generated one candidate without dispatch' }), { status: 200 }))
  const onRefresh = vi.fn()

  render(<WorkerLanes lanes={[{ lane_key: 'gb10', machine_target: 'gb10', status: 'idle', queued_count: 0, dispatch_available: false, feed_pressure: { next_autopilot_action: 'generate_candidate' } }]} onRefresh={onRefresh} />)
  expect(screen.getByRole('button', { name: 'Run feed cycle' })).toBeDisabled()

  fireEvent.click(screen.getByRole('button', { name: 'Feed idle lanes' }))
  await screen.findByText('would generate one candidate')

  fireEvent.click(screen.getByRole('button', { name: 'Run feed cycle' }))
  const dialog = await screen.findByRole('dialog', { name: 'Run one bounded feed cycle?' })
  expect(dialog).toHaveTextContent('will not dispatch')
  expect(confirmSpy).not.toHaveBeenCalled()
  fireEvent.click(dialog.querySelectorAll('button')[1])

  await screen.findByText('generated one candidate without dispatch')
  expect(fetchMock).toHaveBeenNthCalledWith(1, '/control/api/research/run-cycle', expect.objectContaining({
    method: 'POST',
    body: expect.stringContaining('"dry_run":true'),
  }))
  expect(String(fetchMock.mock.calls[0][1]?.body)).toContain('"enabled":false')
  expect(fetchMock).toHaveBeenNthCalledWith(2, '/control/api/research/run-cycle', expect.objectContaining({
    method: 'POST',
    body: expect.stringContaining('"dry_run":false'),
  }))
  expect(String(fetchMock.mock.calls[1][1]?.body)).toContain('"enabled":true')
  expect(String(fetchMock.mock.calls[1][1]?.body)).toContain('"max_dispatches_per_run":0')
  expect(onRefresh).toHaveBeenCalledTimes(2)
})

it('uses dispatch-one for lane-card dispatch checks so the selected lane candidate is tested', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ action: 'dry_run_dispatch_one', reason: 'dry-run selected explicit queued candidate', candidate: { project_id: 'gb10-project' } }), { status: 200 }))
  const onRefresh = vi.fn()

  render(<WorkerLanes lanes={[{ lane_key: 'gb10', machine_target: 'gb10', status: 'idle', queued_count: 1, dispatch_available: true, next_candidate: { project_id: 'gb10-project', project_name: 'GB10 job' } }]} onRefresh={onRefresh} />)
  fireEvent.click(screen.getByRole('button', { name: 'Check dispatch' }))

  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))
  expect(fetchMock).toHaveBeenCalledWith('/control/dispatch-one', expect.objectContaining({
    method: 'POST',
    body: expect.stringContaining('"project_id":"gb10-project"'),
  }))
  expect(String(fetchMock.mock.calls[0][1]?.body)).toContain('"dry_run":true')
  expect(screen.getByText('Dispatch dry-run result')).toBeInTheDocument()
})

it('live-dispatches a lane candidate only after exact lane dry-run and dialog confirmation', async () => {
  const confirmSpy = vi.spyOn(window, 'confirm')
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ action: 'dry_run_dispatch_one', reason: 'dry-run selected explicit queued candidate', candidate: { project_id: 'gb10-project' } }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ action: 'live_dispatch_one', reason: 'live dispatch started exact GB10 candidate', candidate: { project_id: 'gb10-project' } }), { status: 200 }))
  const onRefresh = vi.fn()

  render(<WorkerLanes lanes={[{ lane_key: 'gb10', machine_target: 'gb10', status: 'idle', queued_count: 1, dispatch_available: true, next_candidate: { project_id: 'gb10-project', project_name: 'GB10 job' } }]} onRefresh={onRefresh} />)
  expect(screen.getByRole('button', { name: 'Dispatch lane' })).toBeDisabled()

  fireEvent.click(screen.getByRole('button', { name: 'Check dispatch' }))
  await screen.findByText('dry-run selected explicit queued candidate')

  fireEvent.click(screen.getByRole('button', { name: 'Dispatch lane' }))
  const dialog = await screen.findByRole('dialog', { name: 'Dispatch GB10 lane?' })
  expect(dialog).toBeInTheDocument()
  expect(confirmSpy).not.toHaveBeenCalled()
  fireEvent.click(dialog.querySelectorAll('button')[1])

  await screen.findByText('live dispatch started exact GB10 candidate')
  expect(fetchMock).toHaveBeenNthCalledWith(1, '/control/dispatch-one', expect.objectContaining({
    method: 'POST',
    body: JSON.stringify({ project_id: 'gb10-project', dry_run: true, requested_by: 'dashboard-v2', force_preflight: true }),
  }))
  expect(fetchMock).toHaveBeenNthCalledWith(2, '/control/dispatch-one', expect.objectContaining({
    method: 'POST',
    body: JSON.stringify({ project_id: 'gb10-project', dry_run: false, requested_by: 'dashboard-v2', force_preflight: true }),
  }))
  expect(onRefresh).toHaveBeenCalledTimes(2)
})

it('renders the paper mini strip and movement diagnosis', () => {
  render(<><PaperMiniStrip pipeline={{ write_needed: 2, finalize_needed: 1, publish_ready: 0 }} /><MovementDiagnosis diagnosis={diagnosis} /></>)
  expect(screen.getByText('Paper pipeline')).toBeInTheDocument()
  expect(screen.getByText('Why no work is moving?')).toBeInTheDocument()
  expect(screen.getByText('GB10 lane can dispatch')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Open' })).toHaveAttribute('href', '/control/dashboard-v2#queue:queued')
  expect(screen.getByRole('link', { name: /Write/ })).toHaveAttribute('href', '/control/dashboard-v2#papers?status=publication_draft')
})

it('runs paper finalize strip actions as dry-runs without rewriting drafts live', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ dry_run: true, matched: 1, processed: 1, reason: 'would rewrite one publication draft' }), { status: 200 }))
  const onRefresh = vi.fn()

  render(<PaperMiniStrip pipeline={{ write_needed: 0, finalize_needed: 1, publish_ready: 0 }} onRefresh={onRefresh} />)
  fireEvent.click(screen.getByRole('button', { name: 'Dry-run finalize' }))

  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))
  expect(fetchMock).toHaveBeenCalledWith('/control/api/paper-reviews/rewrite-batch', expect.objectContaining({
    method: 'POST',
    body: expect.stringContaining('"dry_run":true'),
  }))
  expect(String(fetchMock.mock.calls[0][1]?.body)).toContain('"limit":10')
  expect(screen.getByText('Paper dry-run result')).toBeInTheDocument()
  expect(screen.getByText('would rewrite one publication draft')).toBeInTheDocument()
  expect(onRefresh).toHaveBeenCalledTimes(1)
})

it('finalizes paper strip drafts only after dry-run and dialog confirmation', async () => {
  const confirmSpy = vi.spyOn(window, 'confirm')
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ dry_run: true, matched: 1, processed: 1, reason: 'would rewrite one publication draft' }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ dry_run: false, rewritten: 1, failed: 0, reason: 'rewrote one publication draft' }), { status: 200 }))
  const onRefresh = vi.fn()

  render(<PaperMiniStrip pipeline={{ write_needed: 0, finalize_needed: 1, publish_ready: 0 }} onRefresh={onRefresh} />)
  expect(screen.getByRole('button', { name: 'Finalize drafts' })).toBeDisabled()

  fireEvent.click(screen.getByRole('button', { name: 'Dry-run finalize' }))
  await screen.findByText('would rewrite one publication draft')

  fireEvent.click(screen.getByRole('button', { name: 'Finalize drafts' }))
  const dialog = await screen.findByRole('dialog', { name: 'Finalize paper strip drafts?' })
  expect(dialog).toHaveTextContent('rewrites the publication-draft batch')
  expect(confirmSpy).not.toHaveBeenCalled()
  fireEvent.click(dialog.querySelectorAll('button')[1])

  await screen.findByText('rewrote one publication draft')
  expect(fetchMock).toHaveBeenNthCalledWith(1, '/control/api/paper-reviews/rewrite-batch', expect.objectContaining({
    method: 'POST',
    body: expect.stringContaining('"idempotency_key":"paper-strip-rewrite-batch:dashboard-v2:'),
  }))
  expect(String(fetchMock.mock.calls[0][1]?.body)).toContain('"dry_run":true')
  expect(fetchMock).toHaveBeenNthCalledWith(2, '/control/api/paper-reviews/rewrite-batch', expect.objectContaining({
    method: 'POST',
    body: expect.stringContaining('"idempotency_key":"paper-strip-rewrite-batch-live:dashboard-v2:'),
  }))
  expect(String(fetchMock.mock.calls[1][1]?.body)).toContain('"dry_run":false')
  expect(String(fetchMock.mock.calls[1][1]?.body)).toContain('"force":true')
  expect(onRefresh).toHaveBeenCalledTimes(2)
})

it('checks every open lane candidate with dispatch-one instead of aggregate dispatch-next', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ action: 'dry_run_dispatch_one', reason: 'cpu candidate can dispatch' }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ action: 'dry_run_dispatch_one', reason: 'gb10 candidate can dispatch' }), { status: 200 }))
  const onRefresh = vi.fn()

  render(<WorkerLanes lanes={[
    { lane_key: 'cpu', machine_target: 'cpu-proxmox-1', status: 'idle', queued_count: 1, dispatch_available: true, next_candidate: { project_id: 'cpu-project', project_name: 'CPU job' } },
    { lane_key: 'gb10', machine_target: 'gb10', status: 'idle', queued_count: 1, dispatch_available: true, next_candidate: { project_id: 'gb10-project', project_name: 'GB10 job' } },
  ]} onRefresh={onRefresh} />)

  fireEvent.click(screen.getByRole('button', { name: 'Check open lanes' }))

  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2))
  expect(fetchMock).toHaveBeenNthCalledWith(1, '/control/dispatch-one', expect.objectContaining({
    method: 'POST',
    body: JSON.stringify({ project_id: 'cpu-project', dry_run: true, requested_by: 'dashboard-v2', force_preflight: true }),
  }))
  expect(fetchMock).toHaveBeenNthCalledWith(2, '/control/dispatch-one', expect.objectContaining({
    method: 'POST',
    body: JSON.stringify({ project_id: 'gb10-project', dry_run: true, requested_by: 'dashboard-v2', force_preflight: true }),
  }))
  expect(screen.getByText('Dispatch dry-run result')).toBeInTheDocument()
  expect(screen.getByText('checked 2 lane candidates')).toBeInTheDocument()
  expect(onRefresh).toHaveBeenCalledTimes(1)
})

it('live-dispatches every open lane candidate with dispatch-one after confirmation', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ action: 'dispatch_started', reason: 'cpu dispatch started' }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ action: 'dispatch_started', reason: 'gb10 dispatch started' }), { status: 200 }))
  const onRefresh = vi.fn()

  render(<WorkerLanes lanes={[
    { lane_key: 'cpu', machine_target: 'cpu-proxmox-1', status: 'idle', queued_count: 1, dispatch_available: true, next_candidate: { project_id: 'cpu-project', project_name: 'CPU job' } },
    { lane_key: 'gb10', machine_target: 'gb10', status: 'idle', queued_count: 1, dispatch_available: true, next_candidate: { project_id: 'gb10-project', project_name: 'GB10 job' } },
  ]} onRefresh={onRefresh} />)

  fireEvent.click(screen.getByRole('button', { name: 'Dispatch open lanes' }))
  const dialog = await screen.findByRole('dialog', { name: 'Dispatch open lanes?' })
  fireEvent.click(dialog.querySelectorAll('button')[1])

  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2))
  expect(fetchMock).toHaveBeenNthCalledWith(1, '/control/dispatch-one', expect.objectContaining({
    method: 'POST',
    body: JSON.stringify({ project_id: 'cpu-project', dry_run: false, requested_by: 'dashboard-v2', force_preflight: true }),
  }))
  expect(fetchMock).toHaveBeenNthCalledWith(2, '/control/dispatch-one', expect.objectContaining({
    method: 'POST',
    body: JSON.stringify({ project_id: 'gb10-project', dry_run: false, requested_by: 'dashboard-v2', force_preflight: true }),
  }))
  expect(screen.getByText('Live dispatch result')).toBeInTheDocument()
  expect(screen.getByText('dispatched 2 lane candidates')).toBeInTheDocument()
  expect(onRefresh).toHaveBeenCalledTimes(1)
})

it('explains when no worker lane capacity is returned', () => {
  render(<WorkerLanes lanes={[]} onRefresh={() => undefined} />)

  expect(screen.getByText('No worker lane capacity returned.')).toBeInTheDocument()
  expect(screen.getByText('The status endpoint did not include CPU or GB10 lane data, so V2 cannot safely feed or dispatch work from this panel.')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Feed idle lanes' })).toBeDisabled()
  expect(screen.getByRole('button', { name: 'Check open lanes' })).toBeDisabled()
})

it('distinguishes lane status loading from an empty lane-capacity response', () => {
  render(<WorkerLanes lanes={[]} isLoading onRefresh={() => undefined} />)

  expect(screen.getByText('Loading worker lane capacity…')).toBeInTheDocument()
  expect(screen.queryByText('No worker lane capacity returned.')).not.toBeInTheDocument()
})

it('surfaces worker lane status errors instead of showing an empty lane list', () => {
  render(<WorkerLanes lanes={[]} error={new Error('/control/api/status -> 503')} onRefresh={() => undefined} />)

  expect(screen.getByText('Worker lane status unavailable.')).toBeInTheDocument()
  expect(screen.getByText('/control/api/status -> 503')).toBeInTheDocument()
  expect(screen.queryByText('No worker lane capacity returned.')).not.toBeInTheDocument()
})
