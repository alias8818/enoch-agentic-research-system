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

it('keeps non-command primary actions as V2 links', () => {
  render(<PrimaryAction action={{ kind: 'write_paper', title: 'Draft next paper', summary: 'Paper-ready run exists.', action_label: 'Open draft lane', action_hash: '#papers?status=publication_draft' }} />)
  expect(screen.getByRole('link', { name: 'Open draft lane' })).toHaveAttribute('href', '/control/dashboard-v2#papers?status=publication_draft')
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

it('renders the paper mini strip and movement diagnosis', () => {
  render(<><PaperMiniStrip pipeline={{ write_needed: 2, finalize_needed: 1, publish_ready: 0 }} /><MovementDiagnosis diagnosis={diagnosis} /></>)
  expect(screen.getByText('Paper pipeline')).toBeInTheDocument()
  expect(screen.getByText('Why no work is moving?')).toBeInTheDocument()
  expect(screen.getByText('GB10 lane can dispatch')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Open' })).toHaveAttribute('href', '/control/dashboard-v2#queue:queued')
  expect(screen.getByRole('link', { name: /Write/ })).toHaveAttribute('href', '/control/dashboard-v2#papers?status=publication_draft')
})
