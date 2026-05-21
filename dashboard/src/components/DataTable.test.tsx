import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { DataTable } from './DataTable'

afterEach(() => {
  vi.restoreAllMocks()
})

it('renders copy buttons for truncated identifier cells without selecting the row', async () => {
  const writeText = vi.fn().mockResolvedValue(undefined)
  Object.assign(navigator, { clipboard: { writeText } })
  const onSelectRow = vi.fn()

  render(<DataTable rows={[{ project_id: '80324bc197896999', status: 'queued', title: 'Candidate' }]} columns={['project_id', 'status', 'title']} empty="empty" onSelectRow={onSelectRow} />)

  fireEvent.click(screen.getByRole('button', { name: 'Copy project id 80324bc197896999' }))

  await waitFor(() => expect(writeText).toHaveBeenCalledWith('80324bc197896999'))
  expect(onSelectRow).not.toHaveBeenCalled()
  expect(await screen.findByText('Copied')).toBeInTheDocument()
})
