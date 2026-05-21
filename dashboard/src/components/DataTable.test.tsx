import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { DataTable } from './DataTable'
import { projectsTableColumns } from '../tablePresentation'

afterEach(() => {
  vi.restoreAllMocks()
})

it('renders subtle copy buttons for id columns without selecting the row', async () => {
  const writeText = vi.fn().mockResolvedValue(undefined)
  Object.assign(navigator, { clipboard: { writeText } })
  const onSelectRow = vi.fn()

  render(<DataTable rows={[{ project_id: '80324bc197896999', status: 'queued', project_name: 'Candidate' }]} columns={projectsTableColumns} empty="empty" onSelectRow={onSelectRow} />)

  expect(screen.getByText('Candidate')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Copy id 80324bc197896999' }))

  await waitFor(() => expect(writeText).toHaveBeenCalledWith('80324bc197896999'))
  expect(onSelectRow).not.toHaveBeenCalled()
})

it('renders linked id cells without selecting the row', () => {
  const onSelectRow = vi.fn()

  render(<DataTable rows={[{ project_id: 'project-1', project_name: 'Trace oracle', queue_status: 'queued' }]} columns={projectsTableColumns} empty="empty" onSelectRow={onSelectRow} cellHref={(row, column) => column === 'project_id' ? '/control/dashboard-v2#project:project-1' : undefined} />)

  fireEvent.click(screen.getByRole('link', { name: 'project-1' }))

  expect(screen.getByRole('link', { name: 'project-1' })).toHaveAttribute('href', '/control/dashboard-v2#project:project-1')
  expect(onSelectRow).not.toHaveBeenCalled()
})
