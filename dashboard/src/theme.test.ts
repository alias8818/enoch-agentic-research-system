import { expect, it } from 'vitest'
import { applyTheme, getSavedTheme, saveTheme, toggleTheme } from './theme'

it('persists dashboard theme preference in localStorage', () => {
  saveTheme('light')
  expect(getSavedTheme()).toBe('light')
  expect(document.documentElement.dataset.theme).toBe('light')

  saveTheme('dark')
  expect(getSavedTheme()).toBe('dark')
  expect(document.documentElement.dataset.theme).toBe('dark')
})

it('toggles between dark and light themes', () => {
  applyTheme('dark')
  expect(toggleTheme('dark')).toBe('light')
  expect(toggleTheme('light')).toBe('dark')
})
