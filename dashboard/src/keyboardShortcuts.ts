export type KeyboardShortcutScope = 'global' | 'table'

export type KeyboardShortcut = {
  keys: string
  description: string
  scope: KeyboardShortcutScope
}

export const DASHBOARD_KEYBOARD_SHORTCUTS: KeyboardShortcut[] = [
  { keys: '?', description: 'Show or hide keyboard shortcuts', scope: 'global' },
  { keys: '/', description: 'Focus global project search', scope: 'global' },
  { keys: 'Esc', description: 'Close keyboard shortcuts help', scope: 'global' },
  { keys: 'Enter or Space', description: 'Select the focused table row', scope: 'table' },
]

export function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  if (target.isContentEditable) return true
  const tag = target.tagName
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT'
}
