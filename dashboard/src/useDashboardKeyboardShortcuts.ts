import { RefObject, useEffect } from 'react'
import { isEditableTarget } from './keyboardShortcuts'

export function useDashboardKeyboardShortcuts({
  helpOpen,
  onToggleHelp,
  onCloseHelp,
  searchInputRef,
}: {
  helpOpen: boolean
  onToggleHelp: () => void
  onCloseHelp: () => void
  searchInputRef: RefObject<HTMLInputElement | null>
}) {
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape' && helpOpen) {
        event.preventDefault()
        onCloseHelp()
        return
      }

      if (isEditableTarget(event.target)) return

      if (event.key === '?' && !event.ctrlKey && !event.metaKey && !event.altKey) {
        event.preventDefault()
        onToggleHelp()
        return
      }

      if (event.key === '/' && !event.ctrlKey && !event.metaKey && !event.altKey) {
        event.preventDefault()
        searchInputRef.current?.focus()
        searchInputRef.current?.select()
      }
    }

    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [helpOpen, onCloseHelp, onToggleHelp, searchInputRef])
}
