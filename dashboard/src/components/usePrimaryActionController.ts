import { useCallback, useEffect, useRef, useState } from 'react'
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
  const operationSerialRef = useRef(0)
  const liveReady = action ? computeLiveReady(action, readiness, currentActionSignature) : false
  const staleReady = Boolean(readiness.signature) && readiness.signature !== currentActionSignature

  useEffect(() => {
    operationSerialRef.current += 1
    setIsPending(false)
  }, [currentActionSignature])

  const clearReadiness = useCallback(() => {
    setReadiness(EMPTY_PRIMARY_ACTION_READINESS)
  }, [])

  const runDryRun = useCallback(async () => {
    if (!action || !isDryRunActionKind(action.kind)) return
    const requestedAction = action
    const requestedSignature = currentActionSignature
    const operationSerial = operationSerialRef.current + 1
    operationSerialRef.current = operationSerial
    const operationIsCurrent = () => operationSerialRef.current === operationSerial
    setIsPending(true)
    try {
      const payload = await postDryRunRequest(requestedAction)
      if (!operationIsCurrent()) return
      setResult({ payload, context: { commandFamily: commandFamilyForAction(requestedAction) } })
      const ready = dryRunIndicatesReady(requestedAction, payload)
      setReadiness(readinessAfterDryRun(requestedAction, ready, requestedSignature))
      onRefresh?.()
    } catch (error) {
      if (!operationIsCurrent()) return
      setResult({ payload: errorPayload(error), context: { commandFamily: commandFamilyForAction(requestedAction) } })
      clearReadiness()
    } finally {
      if (operationIsCurrent()) setIsPending(false)
    }
  }, [action, clearReadiness, currentActionSignature, onRefresh])

  const runLive = useCallback(async () => {
    if (!action || !isDryRunActionKind(action.kind) || !liveReady) return
    const requestedAction = action
    const operationSerial = operationSerialRef.current + 1
    operationSerialRef.current = operationSerial
    const operationIsCurrent = () => operationSerialRef.current === operationSerial
    setIsPending(true)
    try {
      const payload = await executeConfirmedLiveAction(requestedAction, confirm)
      if (!operationIsCurrent()) return
      setResult({
        payload,
        context: { commandFamily: commandFamilyForAction(requestedAction) },
      })
      clearReadiness()
      onRefresh?.()
    } catch (error) {
      if (error instanceof LiveActionCancelled) return
      if (!operationIsCurrent()) return
      setResult({ payload: errorPayload(error), context: { commandFamily: commandFamilyForAction(requestedAction) } })
    } finally {
      if (operationIsCurrent()) setIsPending(false)
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
