import type { CommandPresentationContext } from '../../commandResultPresentation'
import { CommandResultSummary } from '../CommandResultSummary'

export function OperatorResultCard({
  result,
  context,
  stale,
}: Readonly<{
  result?: Record<string, unknown>
  context?: CommandPresentationContext
  stale?: boolean
}>) {
  if (!result) return null
  return <CommandResultSummary result={{ payload: result, context: { ...context, stale } }} />
}
