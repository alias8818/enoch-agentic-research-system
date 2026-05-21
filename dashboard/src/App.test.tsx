import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
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
  fireEvent.click(screen.getByText('Show secondary details'))
  expect(screen.getAllByRole('link', { name: 'Runs' }).some((link) => link.getAttribute('href') === '/control/dashboard-v2#runs')).toBe(true)
  expect(screen.getAllByRole('link', { name: 'Papers' }).some((link) => link.getAttribute('href') === '/control/dashboard-v2#papers')).toBe(true)
  expect(screen.getByRole('link', { name: 'Recent activity' })).toHaveAttribute('href', '/control/dashboard-v2#events')

  fireEvent.click(screen.getByRole('button', { name: 'Refresh now' }))
  await waitFor(() => expect(globalThis.fetch).toHaveBeenCalledTimes(4))
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
