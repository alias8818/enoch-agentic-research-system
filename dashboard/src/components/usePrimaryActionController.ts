import { useCallback, useState } from 'react'
import type { TopAction } from '../types'
import { useOperatorDialog } from './OperatorDialog'
import type { CommandPresentationContext } from '../commandResultPresentation'
import {
  EMPTY_PRIMARY_ACTION_READINESS,
  LiveActionCancelled,
  computeLiveReady,
  dryRunIndicatesReady,
  executeConfirmedLiveAction,
  isDryRunActionKind,
  postDryRunRequest,
  readinessAfterDryRun,
  type PrimaryActionReadiness,
} from './primaryActionCommands'
import { actionSignature } from './primaryActionCommands'

type CommandResult = {
  payload: Record<string, unknown>
  context?: CommandPresentationContext
}

function commandFamilyForAction(action: TopAction): CommandPresentationContext['commandFamily'] {
  if (action.kind === 'dispatch_next') return 'dispatch'
  if (action.kind === 'investigate_followup') return 'followup'
  if (action.kind === 'write_paper') return 'paper'
  if (action.kind === 'finalize_paper') return 'finalize'
  if (action.kind === 'feed_lanes') return 'research'
  return 'command'
}

function errorPayload(error: unknown): Record<string, unknown> {
  return { ok: false, reason: error instanceof Error ? error.message : String(error) }
}

export function usePrimaryActionController(action: TopAction | undefined, onRefresh?: () => void) {
  const [result, setResult] = useState<CommandResult | null>(null)
  const [isPending, setIsPending] = useState(false)
  const [readiness, setReadiness] = useState<PrimaryActionReadiness>(EMPTY_PRIMARY_ACTION_READINESS)
  const { confirm, dialog } = useOperatorDialog()
  const currentActionSignature = action ? actionSignature(action) : ''
  const liveReady = action ? computeLiveReady(action, readiness, currentActionSignature) : false
  const staleReady = Boolean(readiness.signature) && readiness.signature !== currentActionSignature

  const clearReadiness = useCallback(() => {
    setReadiness(EMPTY_PRIMARY_ACTION_READINESS)
  }, [])

  const runDryRun = useCallback(async () => {
    if (!action || !isDryRunActionKind(action.kind)) return
    setIsPending(true)
    try {
      const payload = await postDryRunRequest(action)
      setResult({ payload, context: { commandFamily: commandFamilyForAction(action) } })
      const ready = dryRunIndicatesReady(action, payload)
      setReadiness(readinessAfterDryRun(action, ready, currentActionSignature))
      onRefresh?.()
    } catch (error) {
      setResult({ payload: errorPayload(error), context: { commandFamily: commandFamilyForAction(action) } })
      clearReadiness()
    } finally {
      setIsPending(false)
    }
  }, [action, clearReadiness, currentActionSignature, onRefresh])

  const runLive = useCallback(async () => {
    if (!action || !isDryRunActionKind(action.kind) || !liveReady) return
    setIsPending(true)
    try {
      const payload = await executeConfirmedLiveAction(action, confirm)
      setResult({
        payload,
        context: { commandFamily: commandFamilyForAction(action) },
      })
      clearReadiness()
      onRefresh?.()
    } catch (error) {
      if (error instanceof LiveActionCancelled) return
      setResult({ payload: errorPayload(error), context: { commandFamily: commandFamilyForAction(action) } })
    } finally {
      setIsPending(false)
    }
  }, [action, clearReadiness, confirm, liveReady, onRefresh])

  return {
    result,
    isPending,
    runDryRun,
    runLive,
    liveReady,
    staleReady,
    dialog,
  }
}
