import { expect, it } from 'vitest'
import { DASHBOARD_KEYBOARD_SHORTCUTS, isEditableTarget } from './keyboardShortcuts'

it('lists the operator keyboard shortcuts in a stable catalog', () => {
  expect(DASHBOARD_KEYBOARD_SHORTCUTS.map((shortcut) => shortcut.keys)).toEqual([
    '?',
    '/',
    'Esc',
    'Enter or Space',
  ])
})

it('treats form controls as editable shortcut targets', () => {
  const input = document.createElement('input')
  expect(isEditableTarget(input)).toBe(true)

  const button = document.createElement('button')
  expect(isEditableTarget(button)).toBe(false)
})
