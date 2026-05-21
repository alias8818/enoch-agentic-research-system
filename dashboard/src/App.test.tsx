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
  expect(screen.getByRole('link', { name: 'Overview' })).toBeInTheDocument()
  fireEvent.click(screen.getByText('More'))
  expect(screen.getByRole('link', { name: 'Events' })).toHaveAttribute('href', '/control/dashboard-v2#events')
  expect(screen.getByRole('link', { name: 'Legacy dashboard' })).toHaveAttribute('href', '/control/dashboard')
  fireEvent.click(screen.getByText('Show secondary details'))
  expect(screen.getAllByRole('link', { name: 'Runs' }).some((link) => link.getAttribute('href') === '/control/dashboard-v2#runs')).toBe(true)
  expect(screen.getAllByRole('link', { name: 'Papers' }).some((link) => link.getAttribute('href') === '/control/dashboard-v2#papers')).toBe(true)
  expect(screen.getByRole('link', { name: 'Recent activity' })).toHaveAttribute('href', '/control/dashboard-v2#events')

  fireEvent.click(screen.getByRole('button', { name: 'Refresh now' }))
  await waitFor(() => expect(globalThis.fetch).toHaveBeenCalledTimes(4))
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
