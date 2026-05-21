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

it('renders only the first primary action', () => {
  render(<PrimaryAction action={{ kind: 'dispatch_next', title: 'Dispatch GB10 lane', summary: 'One queued candidate matches the idle lane.', action_label: 'Dispatch', action_hash: '#queue:queued' }} />)
  expect(screen.getByText('Primary action')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Dispatch' })).toHaveAttribute('href', '/control/dashboard-v2#queue:queued')
})

it('renders worker lane commands without deriving queue truth from aggregate counts', () => {
  render(<WorkerLanes lanes={[{ lane_key: 'cpu', machine_target: 'cpu-proxmox-1', status: 'active', queued_count: 0, dispatch_available: false, active_item: { project_name: 'CPU job' } }, { lane_key: 'gb10', machine_target: 'gb10', status: 'idle', queued_count: 1, dispatch_available: true, next_candidate: { project_name: 'GB10 job' } }]} onRefresh={() => undefined} />)
  expect(screen.getByText('CPU lane')).toBeInTheDocument()
  expect(screen.getByText('GB10 lane')).toBeInTheDocument()
  expect(screen.getByText('CPU job')).toBeInTheDocument()
  expect(screen.getByText('GB10 job')).toBeInTheDocument()
  expect(screen.getByText('Lane is active.')).toBeInTheDocument()
  expect(screen.getByText('Ready to dispatch queued work.')).toBeInTheDocument()
  expect(screen.getAllByText('Dispatch this lane')).toHaveLength(2)
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

it('uses staged dialog confirmations for live dispatch and no alert fallback', async () => {
  const confirmSpy = vi.spyOn(window, 'confirm')
  const alertSpy = vi.spyOn(window, 'alert')
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ action: 'dry_run_dispatch' }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ action: 'dispatched' }), { status: 200 }))
  const onRefresh = vi.fn()

  render(<WorkerLanes lanes={[{ lane_key: 'gb10', machine_target: 'gb10', status: 'idle', queued_count: 1, dispatch_available: true, next_candidate: { project_name: 'GB10 job' } }]} onRefresh={onRefresh} />)
  fireEvent.click(screen.getByRole('button', { name: 'Dispatch this lane' }))

  expect(await screen.findByRole('dialog', { name: 'Dry-run dispatch?' })).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Run dispatch dry-run' }))
  expect(await screen.findByRole('dialog', { name: 'Start live dispatch?' })).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Start live dispatch' }))

  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2))
  expect(confirmSpy).not.toHaveBeenCalled()
  expect(alertSpy).not.toHaveBeenCalled()
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
