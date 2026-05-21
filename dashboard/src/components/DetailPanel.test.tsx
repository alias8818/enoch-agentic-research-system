import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { DetailPanel } from './DetailPanel'

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

  expect(screen.getByText('Queue Alert')).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: 'Lane blocked' })).toBeInTheDocument()
  expect(screen.getByText('Raw payload')).toBeInTheDocument()
  expect(fetchMock).not.toHaveBeenCalled()
})
