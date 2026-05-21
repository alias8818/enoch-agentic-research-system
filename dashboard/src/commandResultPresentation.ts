export type CommandSeverity = 'passed' | 'dry_run' | 'blocked' | 'failed' | 'stale'

export type OperatorDecision =
  | 'Safe to dispatch'
  | 'Do not dispatch'
  | 'Refresh and check again'
  | 'Fix blocker first'

export type CommandPresentationContext = {
  stale?: boolean
  commandFamily?: string
}

export type CommandPresentation = {
  title: string
  severity: CommandSeverity
  decision: OperatorDecision
  severityLabel: string
}

function text(value: unknown): string {
  if (value === null || value === undefined || value === '') return ''
  return String(value)
}

function action(payload: Record<string, unknown>): string {
  return text(payload.action).toLowerCase()
}

function isBlocked(payload: Record<string, unknown>): boolean {
  if (payload.ok === false) return true
  const value = action(payload)
  return value.includes('blocked') || value.includes('failed') || value.includes('error')
}

function isDryRun(payload: Record<string, unknown>): boolean {
  if (payload.dry_run === true) return true
  const value = action(payload)
  return value.includes('dry_run') || value.startsWith('dry_run_')
}

function commandFamily(payload: Record<string, unknown>, context?: CommandPresentationContext): string {
  if (context?.commandFamily) return context.commandFamily
  const value = action(payload)
  if (value.includes('dispatch') || value.includes('feed')) return 'dispatch'
  if (value.includes('draft') || value.includes('paper')) return 'paper'
  if (value.includes('rewrite') || value.includes('finaliz') || value.includes('package')) return 'finalize'
  if (value.includes('followup')) return 'followup'
  if (value.includes('research_cycle') || value.includes('promote')) return 'research'
  if (value.includes('checklist')) return 'automation'
  return 'command'
}

function severityLabel(severity: CommandSeverity): string {
  if (severity === 'passed') return 'Passed'
  if (severity === 'dry_run') return 'Dry-run only'
  if (severity === 'blocked') return 'Blocked'
  if (severity === 'failed') return 'Failed'
  return 'Stale state'
}

function deriveTitle(payload: Record<string, unknown>, context: CommandPresentationContext | undefined, severity: CommandSeverity): string {
  const family = commandFamily(payload, context)
  if (context?.stale) return `${familyTitle(family)} stale — refresh required`

  if (severity === 'blocked' || severity === 'failed') {
    if (family === 'dispatch') return 'Dispatch blocked'
    if (family === 'paper') return 'Paper action blocked'
    if (family === 'finalize') return 'Paper action blocked'
    return 'Command blocked'
  }

  if (severity === 'dry_run') {
    if (family === 'dispatch') return 'Dispatch dry-run passed'
    if (family === 'finalize') return 'Paper finalize dry-run passed'
    if (family === 'paper') return 'Paper draft dry-run passed'
    if (family === 'followup') return 'Follow-up dry-run passed'
    if (family === 'research') return 'Research dry-run passed'
    return 'Dry-run passed'
  }

  if (severity === 'passed') {
    if (family === 'dispatch') return 'Dispatch completed'
    if (family === 'finalize') return 'Paper finalize completed'
    if (family === 'paper') return 'Paper action completed'
    if (family === 'followup') return 'Follow-up completed'
    if (family === 'research') return 'Research action completed'
    return 'Command completed'
  }

  return 'Command result'
}

function familyTitle(family: string): string {
  if (family === 'dispatch') return 'Dispatch'
  if (family === 'finalize') return 'Paper finalize'
  if (family === 'paper') return 'Paper action'
  if (family === 'followup') return 'Follow-up'
  if (family === 'research') return 'Research action'
  return 'Command'
}

function deriveDecision(payload: Record<string, unknown>, context: CommandPresentationContext | undefined, severity: CommandSeverity): OperatorDecision {
  if (context?.stale || severity === 'stale') return 'Refresh and check again'
  if (severity === 'blocked' || severity === 'failed') {
    const family = commandFamily(payload, context)
    if (family === 'dispatch') return 'Do not dispatch'
    return 'Fix blocker first'
  }
  if (severity === 'dry_run') {
    const family = commandFamily(payload, context)
    if (family === 'dispatch') return 'Safe to dispatch'
    return 'Refresh and check again'
  }
  return 'Refresh and check again'
}

function deriveSeverity(payload: Record<string, unknown>, context?: CommandPresentationContext): CommandSeverity {
  if (context?.stale) return 'stale'
  if (payload.ok === false) return 'failed'
  if (isBlocked(payload)) return 'blocked'
  if (isDryRun(payload)) return 'dry_run'
  return 'passed'
}

export function deriveCommandPresentation(
  payload: Record<string, unknown> | null | undefined,
  context?: CommandPresentationContext,
): CommandPresentation {
  const body = payload || {}
  const severity = deriveSeverity(body, context)
  const title = deriveTitle(body, context, severity)
  const decision = deriveDecision(body, context, severity)
  return { title, severity, decision, severityLabel: severityLabel(severity) }
}
