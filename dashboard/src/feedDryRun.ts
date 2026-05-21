export function feedDryRunAllowsLiveCycle(result: Record<string, unknown>): boolean {
  if (result.dry_run !== true) return false
  const action = String(result.action || '').toLowerCase()
  const reason = String(result.reason || result.detail || '').toLowerCase()
  if (action.includes('blocked') || action.includes('skipped') || reason.includes('blocked')) return false
  return action.includes('dry_run') || action.includes('would') || reason.includes('would ')
}
