export type DashboardTheme = 'dark' | 'light'

export const THEME_STORAGE_KEY = 'enochDashboardTheme'

export function getSavedTheme(): DashboardTheme {
  const storage = globalThis.window?.localStorage
  const saved = storage?.getItem(THEME_STORAGE_KEY)
  return saved === 'light' ? 'light' : 'dark'
}

export function saveTheme(theme: DashboardTheme): void {
  globalThis.window?.localStorage?.setItem(THEME_STORAGE_KEY, theme)
  applyTheme(theme)
}

export function applyTheme(theme: DashboardTheme): void {
  const root = globalThis.document?.documentElement
  if (!root) return
  root.dataset.theme = theme
  root.style.colorScheme = theme
}

export function toggleTheme(current: DashboardTheme): DashboardTheme {
  return current === 'dark' ? 'light' : 'dark'
}
