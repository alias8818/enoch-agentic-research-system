import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { fetchMockRequestBody } from '../test/fetchMockBody'
import { CommandHero } from './CommandHero'
import { MovementDiagnosis } from './MovementDiagnosis'
import { PaperMiniStrip } from './PaperMiniStrip'
import { PrimaryAction, resolvePrimaryAction } from './PrimaryAction'
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

function openBulkLaneCommands() {
  fireEvent.click(screen.getByText('Bulk lane commands'))
}

it('renders the leave-running hero from backend diagnosis', () => {
  render(<CommandHero overview={{ ok: true, counts: { active: 1, queued: 2 }, paper_counts: { publication_draft: 1 } }} diagnosis={diagnosis} />)
  expect(screen.getByText('Can I leave this running?')).toBeInTheDocument()
  expect(screen.getByText('Action available')).toBeInTheDocument()
  expect(screen.getByText('GB10 lane can dispatch queued work.')).toBeInTheDocument()
})

it('runs dispatch primary actions as safe dry-runs instead of only linking away', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ action: 'dry_run_dispatch', reason: 'dry-run dispatch selected candidate', candidate: { project_id: 'project-1', machine_target: 'gb10' } }), { status: 200 }))
  const onRefresh = vi.fn()

  render(<PrimaryAction action={{ kind: 'dispatch_next', title: 'Dispatch GB10 lane', summary: 'One queued candidate matches the idle lane.', action_label: 'Dispatch', action_hash: '#queue:queued' }} onRefresh={onRefresh} />)

  expect(screen.getByText('Primary action')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Check dispatch' }))

  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))
  expect(fetchMock).toHaveBeenCalledWith('/control/dispatch-next', expect.objectContaining({
    method: 'POST',
    body: expect.stringContaining('"dry_run":true'),
  }))
  expect(screen.getByText('Dispatch dry-run passed')).toBeInTheDocument()
  expect(screen.getByText('dry-run dispatch selected candidate')).toBeInTheDocument()
  expect(screen.getByText('Selected work')).toBeInTheDocument()
  expect(screen.getByText('project-1')).toBeInTheDocument()
  expect(screen.getByText('Lane / target')).toBeInTheDocument()
  expect(screen.getByText('gb10')).toBeInTheDocument()
  expect(screen.getByText('Operator decision')).toBeInTheDocument()
  expect(screen.getByText('Safe to dispatch')).toBeInTheDocument()
  expect(screen.getByText('Raw JSON')).toBeInTheDocument()
  expect(onRefresh).toHaveBeenCalledTimes(1)
})

it('explains why the primary live action is disabled before preflight', () => {
  render(<PrimaryAction action={{ kind: 'dispatch_next', title: 'Dispatch GB10 lane', summary: 'One queued candidate matches the idle lane.', action_label: 'Dispatch', action_hash: '#queue:queued' }} />)

  expect(screen.getByRole('button', { name: 'Dispatch work' })).toBeDisabled()
  expect(screen.getByText('Dispatch work disabled: run Check dispatch first.')).toBeInTheDocument()
})

it('dispatches the top dispatch action only after dry-run and dialog confirmation', async () => {
  const confirmSpy = vi.spyOn(globalThis, 'confirm')
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
  expect(fetchMock).toHaveBeenNthCalledWith(1, '/control/dispatch-next', expect.objectContaining({ method: 'POST' }))
  expect(fetchMock).toHaveBeenNthCalledWith(2, '/control/dispatch-next', expect.objectContaining({ method: 'POST' }))
  expect(JSON.parse(fetchMockRequestBody(fetchMock, 0))).toEqual({ dry_run: true, requested_by: 'dashboard-v2', force_preflight: true })
  expect(JSON.parse(fetchMockRequestBody(fetchMock, 1))).toEqual({ dry_run: false, requested_by: 'dashboard-v2', force_preflight: true })
  expect(onRefresh).toHaveBeenCalledTimes(2)
})

it('invalidates primary action live dispatch when the top action changes', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ action: 'dry_run_dispatch', reason: 'dry-run dispatch selected candidate' }), { status: 200 }))
  const onRefresh = vi.fn()

  const { rerender } = render(<PrimaryAction action={{ kind: 'dispatch_next', title: 'Dispatch GB10 lane', summary: 'One queued candidate matches the idle lane.', action_label: 'Dispatch', action_hash: '#queue:queued' }} onRefresh={onRefresh} />)

  fireEvent.click(screen.getByRole('button', { name: 'Check dispatch' }))
  await screen.findByText('dry-run dispatch selected candidate')
  expect(fetchMock).toHaveBeenCalledTimes(1)
  expect(screen.getByRole('button', { name: 'Dispatch work' })).toBeEnabled()

  rerender(<PrimaryAction action={{ kind: 'dispatch_next', title: 'Dispatch CPU lane', summary: 'A different queued candidate now matches the idle lane.', action_label: 'Dispatch', action_hash: '#queue:queued&lane=cpu' }} onRefresh={onRefresh} />)

  expect(screen.getByRole('button', { name: 'Dispatch work' })).toBeDisabled()
  expect(screen.getByText('Dispatch work disabled: top action changed; run Check dispatch again.')).toBeInTheDocument()
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
  expect(fetchMockRequestBody(fetchMock, 0)).toContain('"max_followup_depth":4')
  expect(screen.getByText('Follow-up dry-run passed')).toBeInTheDocument()
  expect(onRefresh).toHaveBeenCalledTimes(1)
})

it('launches the top follow-up action only after dry-run and dialog confirmation', async () => {
  const confirmSpy = vi.spyOn(globalThis, 'confirm')
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
  expect(fetchMock).toHaveBeenNthCalledWith(1, '/control/api/v1/followups/launch-next', expect.objectContaining({ method: 'POST' }))
  expect(fetchMock).toHaveBeenNthCalledWith(2, '/control/api/v1/followups/launch-next', expect.objectContaining({ method: 'POST' }))
  expect(JSON.parse(fetchMockRequestBody(fetchMock, 0))).toEqual({ dry_run: true, requested_by: 'dashboard-v2', max_followup_depth: 4 })
  expect(JSON.parse(fetchMockRequestBody(fetchMock, 1))).toEqual({ dry_run: false, requested_by: 'dashboard-v2', max_followup_depth: 4 })
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
  expect(fetchMockRequestBody(fetchMock, 0)).toContain('"force":true')
  expect(screen.getByText('Paper draft dry-run passed')).toBeInTheDocument()
  expect(screen.getByText('eligible paper-ready candidate found')).toBeInTheDocument()
  expect(onRefresh).toHaveBeenCalledTimes(1)
})

it('drafts the top write-paper action only after dry-run and dialog confirmation', async () => {
  const confirmSpy = vi.spyOn(globalThis, 'confirm')
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
  expect(fetchMock).toHaveBeenNthCalledWith(1, '/control/papers/draft-next', expect.objectContaining({ method: 'POST' }))
  expect(fetchMock).toHaveBeenNthCalledWith(2, '/control/papers/draft-next', expect.objectContaining({ method: 'POST' }))
  expect(JSON.parse(fetchMockRequestBody(fetchMock, 0))).toEqual({ dry_run: true, requested_by: 'dashboard-v2', force: true })
  expect(JSON.parse(fetchMockRequestBody(fetchMock, 1))).toEqual({ dry_run: false, requested_by: 'dashboard-v2', force: true })
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
  expect(fetchMockRequestBody(fetchMock, 0)).toContain('"paper_status":"publication_draft"')
  expect(fetchMockRequestBody(fetchMock, 0)).toContain('"skip_rewritten":true')
  expect(screen.getByText('Paper finalize dry-run passed')).toBeInTheDocument()
  expect(screen.getByText('would finalize 2 publication drafts')).toBeInTheDocument()
  expect(onRefresh).toHaveBeenCalledTimes(1)
})

it('finalizes the top paper action only after dry-run and dialog confirmation', async () => {
  const confirmSpy = vi.spyOn(globalThis, 'confirm')
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
  expect(fetchMockRequestBody(fetchMock, 0)).toContain('"dry_run":true')
  expect(fetchMockRequestBody(fetchMock, 0)).toContain('"paper_status":"publication_draft"')
  expect(fetchMockRequestBody(fetchMock, 0)).toContain('"skip_rewritten":true')
  expect(fetchMock).toHaveBeenNthCalledWith(2, '/control/api/paper-reviews/rewrite-batch', expect.objectContaining({
    method: 'POST',
    body: expect.stringContaining('"idempotency_key":"primary-action-rewrite-batch-live:dashboard-v2:'),
  }))
  expect(fetchMockRequestBody(fetchMock, 1)).toContain('"dry_run":false')
  expect(fetchMockRequestBody(fetchMock, 1)).toContain('"force":true')
  expect(fetchMockRequestBody(fetchMock, 1)).toContain('"paper_status":"publication_draft"')
  expect(onRefresh).toHaveBeenCalledTimes(2)
})

it('keeps non-command primary actions as V2 links', () => {
  render(<PrimaryAction action={{ kind: 'publish_paper', title: 'Import finalized drafts', summary: 'Finalized drafts need corpus import.', action_label: 'Open corpus import', action_hash: '#corpus' }} />)
  expect(screen.getByRole('link', { name: 'Open corpus import' })).toHaveAttribute('href', '/control/dashboard-v2#corpus')
})

it('renders worker lane commands without deriving queue truth from aggregate counts', () => {
  render(<WorkerLanes lanes={[
    {
      lane_key: 'cpu',
      machine_target: 'cpu-proxmox-1',
      status: 'active',
      queued_count: 0,
      dispatch_available: false,
      active_item: { project_name: 'CPU job' },
      active_confirmation: { state: 'stale_active' },
    },
    { lane_key: 'gb10', machine_target: 'gb10', status: 'idle', queued_count: 1, dispatch_available: true, next_candidate: { project_name: 'GB10 job' } },
  ]} onRefresh={() => undefined} />)
  expect(screen.getByText('CPU lane')).toBeInTheDocument()
  expect(screen.getByText('GB10 lane')).toBeInTheDocument()
  expect(screen.getByText('CPU job')).toBeInTheDocument()
  expect(screen.getByText('GB10 job')).toBeInTheDocument()
  expect(screen.getByText('Stale active: worker reports no matching live run.')).toBeInTheDocument()
  expect(screen.getByText('Lane is active.')).toBeInTheDocument()
  expect(screen.getByText('Ready to dispatch queued work.')).toBeInTheDocument()
  expect(screen.getAllByText('Check dispatch')).toHaveLength(2)
  expect(screen.getByText('Bulk lane commands').closest('details')).not.toHaveAttribute('open')
})

it('uses dialog confirmations for queue pause instead of window.confirm', async () => {
  const confirmSpy = vi.spyOn(globalThis, 'confirm')
  const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ ok: true }), { status: 200 }))
  const onRefresh = vi.fn()

  render(<SafetyBar flags={{ queue_paused: false, maintenance_mode: false }} onRefresh={onRefresh} />)
  fireEvent.click(screen.getByRole('button', { name: 'Pause queue' }))

  expect(await screen.findByRole('dialog', { name: 'Pause the queue?' })).toBeInTheDocument()
  expect(confirmSpy).not.toHaveBeenCalled()
  const dialog = screen.getByRole('dialog', { name: 'Pause the queue?' })
  fireEvent.click(dialog.querySelectorAll('button')[1])

  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith('/control/pause', expect.objectContaining({ method: 'POST' })))
  const pauseCall = fetchMock.mock.calls.find(([path]) => path === '/control/pause')
  expect(JSON.parse(fetchMockRequestBody({ mock: { calls: pauseCall ? [pauseCall] : [] } }, 0))).toEqual({
    reason: 'dashboard operator pause',
    paused_by: 'dashboard-v2',
    maintenance_mode: true,
  })
  expect(onRefresh).toHaveBeenCalledTimes(1)
})

it('dry-runs dispatch from lane buttons without starting live dispatch', async () => {
  const confirmSpy = vi.spyOn(globalThis, 'confirm')
  const alertSpy = vi.spyOn(globalThis, 'alert')
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
  expect(screen.getByText('Dispatch dry-run passed')).toBeInTheDocument()
  expect(screen.getByText('dry-run dispatch selected candidate')).toBeInTheDocument()
  expect(confirmSpy).not.toHaveBeenCalled()
  expect(alertSpy).not.toHaveBeenCalled()
  expect(onRefresh).toHaveBeenCalledTimes(1)
})


it('explains why global lane commands are disabled', () => {
  render(<WorkerLanes lanes={[{ lane_key: 'gb10', machine_target: 'gb10', status: 'idle', queued_count: 1, dispatch_available: true, next_candidate: { project_id: 'gb10-project', project_name: 'GB10 job' } }]} onRefresh={() => undefined} />)

  openBulkLaneCommands()
  expect(screen.getByRole('button', { name: 'Dispatch open lanes' })).toBeDisabled()
  expect(screen.getByText('Dispatch open lanes disabled: run Check open lanes first.')).toBeInTheDocument()
})

it('requires an open-lanes dry-run before live dispatch is enabled', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ action: 'dry_run_dispatch_one', reason: 'gb10 can dispatch' }), { status: 200 }))
  const onRefresh = vi.fn()

  render(<WorkerLanes lanes={[{ lane_key: 'gb10', machine_target: 'gb10', status: 'idle', queued_count: 1, dispatch_available: true, next_candidate: { project_id: 'gb10-project', project_name: 'GB10 job' } }]} onRefresh={onRefresh} />)

  openBulkLaneCommands()
  expect(screen.getByRole('button', { name: 'Dispatch open lanes' })).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: 'Check open lanes' }))

  await screen.findByText('checked 1 lane candidates')
  expect(fetchMock).toHaveBeenCalledTimes(1)
  expect(screen.getByRole('button', { name: 'Dispatch open lanes' })).toBeEnabled()
})

it('uses a dialog before live dispatching open lanes', async () => {
  const confirmSpy = vi.spyOn(globalThis, 'confirm')
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ action: 'dry_run_dispatch', reason: 'dry-run dispatch accepted queued work' }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ action: 'dispatch_started', reason: 'live dispatch accepted queued work' }), { status: 200 }))
  const onRefresh = vi.fn()

  render(<WorkerLanes lanes={[{ lane_key: 'gb10', machine_target: 'gb10', status: 'idle', queued_count: 1, dispatch_available: true, next_candidate: { project_name: 'GB10 job' } }]} onRefresh={onRefresh} />)
  openBulkLaneCommands()
  expect(screen.getByRole('button', { name: 'Dispatch open lanes' })).toBeDisabled()

  fireEvent.click(screen.getByRole('button', { name: 'Check open lanes' }))
  await screen.findByText('dry-run dispatch accepted queued work')
  fireEvent.click(screen.getByRole('button', { name: 'Dispatch open lanes' }))

  expect(await screen.findByRole('dialog', { name: 'Dispatch open lanes?' })).toBeInTheDocument()
  expect(confirmSpy).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: 'Dispatch work' }))

  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2))
  expect(fetchMock).toHaveBeenNthCalledWith(1, '/control/dispatch-next', expect.objectContaining({
    method: 'POST',
    body: expect.stringContaining('"dry_run":true'),
  }))
  expect(fetchMock).toHaveBeenNthCalledWith(2, '/control/dispatch-next', expect.objectContaining({
    method: 'POST',
    body: expect.stringContaining('"dry_run":false'),
  }))
  expect(screen.getByText('Dispatch completed')).toBeInTheDocument()
  expect(screen.getByText('live dispatch accepted queued work')).toBeInTheDocument()
  expect(onRefresh).toHaveBeenCalledTimes(2)
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
  expect(fetchMockRequestBody(fetchMock, 0)).toContain('"enabled":false')
  expect(fetchMockRequestBody(fetchMock, 0)).toContain('"max_dispatches_per_run":0')
  expect(screen.getByText('Research action blocked')).toBeInTheDocument()
  expect(screen.getByText('provider budget passed; no provider request spent')).toBeInTheDocument()
  expect(onRefresh).toHaveBeenCalledTimes(1)
})

it('keeps live feed disabled after a blocked feed dry-run', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ action: 'research_cycle_blocked', dry_run: true, reason: 'provider budget blocked; no provider request should run' }), { status: 200 }))
  const onRefresh = vi.fn()

  render(<WorkerLanes lanes={[{ lane_key: 'gb10', machine_target: 'gb10', status: 'idle', queued_count: 0, dispatch_available: false, feed_pressure: { next_autopilot_action: 'generate_candidate' } }]} onRefresh={onRefresh} />)

  openBulkLaneCommands()
  expect(screen.getByRole('button', { name: 'Run feed cycle' })).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: 'Feed idle lanes' }))

  await screen.findByText('provider budget blocked; no provider request should run')
  expect(fetchMock).toHaveBeenCalledTimes(1)
  expect(screen.getByRole('button', { name: 'Run feed cycle' })).toBeDisabled()
})

it('runs a confirmed live feed cycle only after a feed dry-run', async () => {
  const confirmSpy = vi.spyOn(globalThis, 'confirm')
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ action: 'research_cycle_dry_run', dry_run: true, reason: 'would generate one candidate' }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ action: 'research_cycle_live', dry_run: false, reason: 'generated one candidate without dispatch' }), { status: 200 }))
  const onRefresh = vi.fn()

  render(<WorkerLanes lanes={[{ lane_key: 'gb10', machine_target: 'gb10', status: 'idle', queued_count: 0, dispatch_available: false, feed_pressure: { next_autopilot_action: 'generate_candidate' } }]} onRefresh={onRefresh} />)
  openBulkLaneCommands()
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
  expect(fetchMockRequestBody(fetchMock, 0)).toContain('"enabled":false')
  expect(fetchMock).toHaveBeenNthCalledWith(2, '/control/api/research/run-cycle', expect.objectContaining({
    method: 'POST',
    body: expect.stringContaining('"dry_run":false'),
  }))
  expect(fetchMockRequestBody(fetchMock, 1)).toContain('"enabled":true')
  expect(fetchMockRequestBody(fetchMock, 1)).toContain('"max_dispatches_per_run":0')
  expect(onRefresh).toHaveBeenCalledTimes(2)
})

it('invalidates live feed authorization when feed-eligible lanes change', async () => {
  vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ action: 'research_cycle_dry_run', dry_run: true, reason: 'would generate one candidate' }), { status: 200 }))
  const onRefresh = vi.fn()

  const { rerender } = render(<WorkerLanes lanes={[{ lane_key: 'gb10', machine_target: 'gb10', status: 'idle', queued_count: 0, dispatch_available: false, feed_pressure: { next_autopilot_action: 'generate_candidate' } }]} onRefresh={onRefresh} />)

  openBulkLaneCommands()
  fireEvent.click(screen.getByRole('button', { name: 'Feed idle lanes' }))
  await screen.findByText('would generate one candidate')
  expect(screen.getByRole('button', { name: 'Run feed cycle' })).toBeEnabled()

  rerender(<WorkerLanes lanes={[{ lane_key: 'gb10', machine_target: 'gb10', status: 'idle', queued_count: 1, dispatch_available: true, feed_pressure: { next_autopilot_action: 'observe' }, next_candidate: { project_id: 'gb10-project', project_name: 'GB10 job' } }]} onRefresh={onRefresh} />)

  openBulkLaneCommands()
  expect(screen.getByRole('button', { name: 'Run feed cycle' })).toBeDisabled()
  expect(screen.getByText('Run feed cycle disabled: lane state changed; run Feed idle lanes again.')).toBeInTheDocument()
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
  expect(fetchMockRequestBody(fetchMock, 0)).toContain('"dry_run":true')
  expect(screen.getByText('Dispatch dry-run passed')).toBeInTheDocument()
})

it('live-dispatches a lane candidate only after exact lane dry-run and dialog confirmation', async () => {
  const confirmSpy = vi.spyOn(globalThis, 'confirm')
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
  expect(fetchMock).toHaveBeenNthCalledWith(1, '/control/dispatch-one', expect.objectContaining({ method: 'POST' }))
  expect(fetchMock).toHaveBeenNthCalledWith(2, '/control/dispatch-one', expect.objectContaining({ method: 'POST' }))
  expect(JSON.parse(fetchMockRequestBody(fetchMock, 0))).toEqual({ project_id: 'gb10-project', dry_run: true, requested_by: 'dashboard-v2', force_preflight: true })
  expect(JSON.parse(fetchMockRequestBody(fetchMock, 1))).toEqual({ project_id: 'gb10-project', dry_run: false, requested_by: 'dashboard-v2', force_preflight: true })
  expect(onRefresh).toHaveBeenCalledTimes(2)
})

it('renders the paper mini strip and movement diagnosis', () => {
  render(<><PaperMiniStrip pipeline={{ write_needed: 2, finalize_needed: 1, publish_ready: 0 }} /><MovementDiagnosis diagnosis={diagnosis} /></>)
  expect(screen.getByText('Paper pipeline')).toBeInTheDocument()
  expect(screen.getByText('What can I do next?')).toBeInTheDocument()
  expect(screen.getByText('GB10 lane can dispatch')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Open' })).toHaveAttribute('href', '/control/dashboard-v2#queue:queued')
  expect(screen.getByRole('link', { name: /Write/ })).toHaveAttribute('href', '/control/dashboard-v2#papers?status=publication_draft')
})

it('explains why paper strip live finalization is disabled before dry-run', () => {
  render(<PaperMiniStrip pipeline={{ write_needed: 0, finalize_needed: 1, publish_ready: 0 }} />)

  expect(screen.getByRole('button', { name: 'Finalize drafts' })).toBeDisabled()
  expect(screen.getByText('Finalize drafts disabled: run Dry-run finalize first.')).toBeInTheDocument()
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
  expect(fetchMockRequestBody(fetchMock, 0)).toContain('"limit":10')
  expect(screen.getByText('Paper finalize dry-run passed')).toBeInTheDocument()
  expect(screen.getByText('would rewrite one publication draft')).toBeInTheDocument()
  expect(onRefresh).toHaveBeenCalledTimes(1)
})

it('finalizes paper strip drafts only after dry-run and dialog confirmation', async () => {
  const confirmSpy = vi.spyOn(globalThis, 'confirm')
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
  expect(fetchMockRequestBody(fetchMock, 0)).toContain('"dry_run":true')
  expect(fetchMock).toHaveBeenNthCalledWith(2, '/control/api/paper-reviews/rewrite-batch', expect.objectContaining({
    method: 'POST',
    body: expect.stringContaining('"idempotency_key":"paper-strip-rewrite-batch-live:dashboard-v2:'),
  }))
  expect(fetchMockRequestBody(fetchMock, 1)).toContain('"dry_run":false')
  expect(fetchMockRequestBody(fetchMock, 1)).toContain('"force":true')
  expect(onRefresh).toHaveBeenCalledTimes(2)
})

it('invalidates paper strip live finalization when pipeline state changes', async () => {
  vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ dry_run: true, matched: 1, processed: 1, reason: 'would rewrite one publication draft' }), { status: 200 }))
  const onRefresh = vi.fn()

  const { rerender } = render(<PaperMiniStrip pipeline={{ write_needed: 0, finalize_needed: 1, publish_ready: 0 }} onRefresh={onRefresh} />)

  fireEvent.click(screen.getByRole('button', { name: 'Dry-run finalize' }))
  await screen.findByText('would rewrite one publication draft')
  expect(screen.getByRole('button', { name: 'Finalize drafts' })).toBeEnabled()

  rerender(<PaperMiniStrip pipeline={{ write_needed: 0, finalize_needed: 0, publish_ready: 1 }} onRefresh={onRefresh} />)

  expect(screen.getByRole('button', { name: 'Finalize drafts' })).toBeDisabled()
  expect(screen.getByText('Finalize drafts disabled: paper pipeline changed; run Dry-run finalize again.')).toBeInTheDocument()
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

  openBulkLaneCommands()
  fireEvent.click(screen.getByRole('button', { name: 'Check open lanes' }))

  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2))
  expect(fetchMock).toHaveBeenNthCalledWith(1, '/control/dispatch-one', expect.objectContaining({ method: 'POST' }))
  expect(fetchMock).toHaveBeenNthCalledWith(2, '/control/dispatch-one', expect.objectContaining({ method: 'POST' }))
  expect(JSON.parse(fetchMockRequestBody(fetchMock, 0))).toEqual({ project_id: 'cpu-project', dry_run: true, requested_by: 'dashboard-v2', force_preflight: true })
  expect(JSON.parse(fetchMockRequestBody(fetchMock, 1))).toEqual({ project_id: 'gb10-project', dry_run: true, requested_by: 'dashboard-v2', force_preflight: true })
  expect(screen.getByText('Dispatch dry-run passed')).toBeInTheDocument()
  expect(screen.getByText('checked 2 lane candidates')).toBeInTheDocument()
  expect(onRefresh).toHaveBeenCalledTimes(1)
})

it('keeps open-lanes live dispatch disabled when any lane dry-run is blocked', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ action: 'dry_run_dispatch_one', reason: 'cpu candidate can dispatch' }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ action: 'dispatch_blocked', reason: 'gb10 lane active blocked' }), { status: 200 }))
  const onRefresh = vi.fn()

  render(<WorkerLanes lanes={[
    { lane_key: 'cpu', machine_target: 'cpu-proxmox-1', status: 'idle', queued_count: 1, dispatch_available: true, next_candidate: { project_id: 'cpu-project', project_name: 'CPU job' } },
    { lane_key: 'gb10', machine_target: 'gb10', status: 'idle', queued_count: 1, dispatch_available: true, next_candidate: { project_id: 'gb10-project', project_name: 'GB10 job' } },
  ]} onRefresh={onRefresh} />)

  fireEvent.click(screen.getByRole('button', { name: 'Check open lanes' }))

  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2))
  expect(screen.getByText('checked 2 lane candidates')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Dispatch open lanes' })).toBeDisabled()
})

it('live-dispatches every open lane candidate with dispatch-one after confirmation', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ action: 'dry_run_dispatch_one', reason: 'cpu candidate can dispatch' }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ action: 'dry_run_dispatch_one', reason: 'gb10 candidate can dispatch' }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ action: 'dispatch_started', reason: 'cpu dispatch started' }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ action: 'dispatch_started', reason: 'gb10 dispatch started' }), { status: 200 }))
  const onRefresh = vi.fn()

  render(<WorkerLanes lanes={[
    { lane_key: 'cpu', machine_target: 'cpu-proxmox-1', status: 'idle', queued_count: 1, dispatch_available: true, next_candidate: { project_id: 'cpu-project', project_name: 'CPU job' } },
    { lane_key: 'gb10', machine_target: 'gb10', status: 'idle', queued_count: 1, dispatch_available: true, next_candidate: { project_id: 'gb10-project', project_name: 'GB10 job' } },
  ]} onRefresh={onRefresh} />)

  openBulkLaneCommands()
  expect(screen.getByRole('button', { name: 'Dispatch open lanes' })).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: 'Check open lanes' }))
  await screen.findByText('checked 2 lane candidates')

  fireEvent.click(screen.getByRole('button', { name: 'Dispatch open lanes' }))
  const dialog = await screen.findByRole('dialog', { name: 'Dispatch open lanes?' })
  fireEvent.click(dialog.querySelectorAll('button')[1])

  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(4))
  expect(fetchMock).toHaveBeenNthCalledWith(1, '/control/dispatch-one', expect.objectContaining({ method: 'POST' }))
  expect(fetchMock).toHaveBeenNthCalledWith(2, '/control/dispatch-one', expect.objectContaining({ method: 'POST' }))
  expect(fetchMock).toHaveBeenNthCalledWith(3, '/control/dispatch-one', expect.objectContaining({ method: 'POST' }))
  expect(fetchMock).toHaveBeenNthCalledWith(4, '/control/dispatch-one', expect.objectContaining({ method: 'POST' }))
  expect(JSON.parse(fetchMockRequestBody(fetchMock, 0))).toEqual({ project_id: 'cpu-project', dry_run: true, requested_by: 'dashboard-v2', force_preflight: true })
  expect(JSON.parse(fetchMockRequestBody(fetchMock, 1))).toEqual({ project_id: 'gb10-project', dry_run: true, requested_by: 'dashboard-v2', force_preflight: true })
  expect(JSON.parse(fetchMockRequestBody(fetchMock, 2))).toEqual({ project_id: 'cpu-project', dry_run: false, requested_by: 'dashboard-v2', force_preflight: true })
  expect(JSON.parse(fetchMockRequestBody(fetchMock, 3))).toEqual({ project_id: 'gb10-project', dry_run: false, requested_by: 'dashboard-v2', force_preflight: true })
  expect(screen.getByText('Dispatch completed')).toBeInTheDocument()
  expect(screen.getByText('dispatched 2 lane candidates')).toBeInTheDocument()
  expect(onRefresh).toHaveBeenCalledTimes(2)
})

it('shows queued versus desired depth on CPU and GB10 lane cards', () => {
  render(<WorkerLanes lanes={[
    {
      lane_key: 'cpu',
      machine_target: 'cpu-proxmox-1',
      status: 'active',
      queued_count: 14,
      dispatch_available: false,
      active_item: { project_name: 'CPU job' },
      feed_pressure: { desired_queue_depth: 25, queue_deficit: 11, next_autopilot_action: 'generate_candidate' },
    },
    {
      lane_key: 'gb10',
      machine_target: 'gb10',
      status: 'idle',
      queued_count: 3,
      dispatch_available: false,
      feed_pressure: { desired_queue_depth: 25, queue_deficit: 22, next_autopilot_action: 'generate_candidate', operator_summary: 'GB10 lane idle with no queued candidate; autopilot should generate GB10-targeted work.' },
    },
  ]} onRefresh={() => undefined} />)

  expect(screen.getByLabelText('CPU lane queue depth 14 / 25 queued')).toBeInTheDocument()
  expect(screen.getByLabelText('GB10 lane queue depth 3 / 25 queued')).toBeInTheDocument()
  expect(screen.getAllByText('14 / 25')).toHaveLength(1)
  expect(screen.getAllByText('3 / 25')).toHaveLength(1)
})

it('shows one feed reason per lane when below desired queue depth', () => {
  render(<WorkerLanes lanes={[{ lane_key: 'gb10', machine_target: 'gb10', status: 'idle', queued_count: 3, dispatch_available: false, feed_pressure: { desired_queue_depth: 25, queue_deficit: 22, next_autopilot_action: 'generate_candidate', operator_summary: 'GB10 lane idle with no queued candidate; autopilot should generate GB10-targeted work.' } }]} onRefresh={() => undefined} />)

  expect(screen.getByText('GB10 lane idle with no queued candidate; autopilot should generate GB10-targeted work.')).toBeInTheDocument()
  expect(screen.getAllByText(/GB10 lane idle with no queued candidate/)).toHaveLength(1)
})

it('shows backlog waiting on active lanes that still have queued work', () => {
  render(<WorkerLanes lanes={[{ lane_key: 'cpu', machine_target: 'cpu-proxmox-1', status: 'active', queued_count: 14, dispatch_available: false, active_item: { project_name: 'CPU job' }, feed_pressure: { desired_queue_depth: 25, queue_deficit: 11, next_autopilot_action: 'generate_candidate' } }]} onRefresh={() => undefined} />)

  expect(screen.getByText('14 queued waiting while this lane is active.')).toBeInTheDocument()
  expect(screen.getByText('Lane is active.')).toBeInTheDocument()
})

it('explains when no worker lane capacity is returned', () => {
  render(<WorkerLanes lanes={[]} onRefresh={() => undefined} />)

  expect(screen.getByText('No worker lane capacity returned.')).toBeInTheDocument()
  expect(screen.getByText('The status endpoint did not include CPU or GB10 lane data, so V2 cannot safely feed or dispatch work from this panel.')).toBeInTheDocument()
  openBulkLaneCommands()
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

it('prefers readiness check before backend primary action', () => {
  const action = resolvePrimaryAction({ ok: true, primary_operator_action: { kind: 'dispatch_next', title: 'Dispatch GB10 lane', summary: 'Ready.' } })
  expect(action?.kind).toBe('check_readiness')
})

it('uses backend primary action after readiness is checked', () => {
  const action = resolvePrimaryAction(
    { ok: true, primary_operator_action: { kind: 'feed_lanes', title: 'Feed GB10 lane', summary: 'Needs backlog.' } },
    { ok: true, label: 'Long-haul mode: READY', blockers: [] },
  )
  expect(action?.kind).toBe('feed_lanes')
})

it('renders blocked primary action as a single navigation CTA', () => {
  render(<PrimaryAction action={{ kind: 'open_blocker', title: 'Queue is paused', summary: 'Paused.', action_label: 'Resume queue', action_hash: '#overview' }} />)
  expect(screen.getByRole('link', { name: 'Resume queue' })).toHaveAttribute('href', '/control/dashboard-v2#overview')
})

it('runs feed primary actions as safe dry-runs before live feed cycle', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(new Response(JSON.stringify({ dry_run: true, action: 'dry_run_research_cycle', reason: 'would generate one candidate' }), { status: 200 }))
  render(<PrimaryAction action={{ kind: 'feed_lanes', title: 'Feed GB10 lane', summary: 'Needs backlog.', action_label: 'Feed idle lanes', action_hash: '#research' }} onRefresh={vi.fn()} />)
  fireEvent.click(screen.getByRole('button', { name: 'Feed idle lanes' }))
  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))
  expect(screen.getByRole('button', { name: 'Run feed cycle' })).toBeEnabled()
})

it('invokes readiness check callback from primary action CTA', () => {
  const onCheckReadiness = vi.fn()
  render(<PrimaryAction action={{ kind: 'check_readiness', title: 'Check readiness first', summary: 'Run check.', action_label: 'Check readiness' }} onCheckReadiness={onCheckReadiness} />)
  fireEvent.click(screen.getByRole('button', { name: 'Check readiness' }))
  expect(onCheckReadiness).toHaveBeenCalledTimes(1)
})

it('requires a fresh dry run when primary dispatch project_id changes', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ action: 'dry_run_dispatch_one', reason: 'dry-run selected explicit queued candidate', candidate: { project_id: 'project-a' } }), { status: 200 }))
  const { rerender } = render(<PrimaryAction action={{ kind: 'dispatch_next', title: 'Dispatch GB10 lane', summary: 'Ready.', action_label: 'Check dispatch', project_id: 'project-a', lane: 'gb10' }} onRefresh={vi.fn()} />)
  fireEvent.click(screen.getByRole('button', { name: 'Check dispatch' }))
  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))
  expect(screen.getByRole('button', { name: 'Dispatch lane' })).toBeEnabled()
  rerender(<PrimaryAction action={{ kind: 'dispatch_next', title: 'Dispatch GB10 lane', summary: 'Ready.', action_label: 'Check dispatch', project_id: 'project-b', lane: 'gb10' }} onRefresh={vi.fn()} />)
  expect(screen.getByRole('button', { name: 'Dispatch lane' })).toBeDisabled()
  expect(screen.getByText('Dispatch work disabled: top action changed; run Check dispatch again.')).toBeInTheDocument()
})
