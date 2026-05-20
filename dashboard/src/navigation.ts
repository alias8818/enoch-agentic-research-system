const LEGACY_DASHBOARD_PATH = '/control/dashboard'

export function legacyDashboardHref(hashOrPath: string | undefined, fallbackHash = '#overview'): string {
  const value = (hashOrPath || fallbackHash).trim() || fallbackHash
  if (value.startsWith('/control/dashboard')) return value
  if (value.startsWith('#')) return `${LEGACY_DASHBOARD_PATH}${value}`
  if (value.startsWith('/')) return value
  return `${LEGACY_DASHBOARD_PATH}#${value}`
}
