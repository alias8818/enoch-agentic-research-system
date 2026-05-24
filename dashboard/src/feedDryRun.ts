import { displayText } from './displayText'

export function feedDryRunAllowsLiveCycle(result: Record<string, unknown>): boolean {
  if (result.dry_run !== true) return false
  const action = displayText(result.action).toLowerCase()
  const reason = displayText(result.reason || result.detail).toLowerCase()
  if (action.includes('blocked') || action.includes('skipped') || reason.includes('blocked')) return false
  return action.includes('dry_run') || action.includes('would') || reason.includes('would ')
}
