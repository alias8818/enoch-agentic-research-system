import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { KeyboardShortcutHelp } from './KeyboardShortcutHelp'

afterEach(() => {
  cleanup()
})

it('renders the keyboard shortcut catalog when open', () => {
  render(<KeyboardShortcutHelp open onClose={() => undefined} />)

  expect(screen.getByRole('heading', { name: 'Keyboard shortcuts' })).toBeInTheDocument()
  expect(screen.getByText('Focus global project search')).toBeInTheDocument()
  expect(screen.getByText('Select the focused table row')).toBeInTheDocument()
})

it('calls onClose when the close button is clicked', () => {
  const onClose = vi.fn()
  render(<KeyboardShortcutHelp open onClose={onClose} />)

  fireEvent.click(screen.getByRole('button', { name: 'Close' }))
  expect(onClose).toHaveBeenCalledTimes(1)
})

it('renders nothing when closed', () => {
  render(<KeyboardShortcutHelp open={false} onClose={() => undefined} />)
  expect(screen.queryByRole('heading', { name: 'Keyboard shortcuts' })).not.toBeInTheDocument()
})
