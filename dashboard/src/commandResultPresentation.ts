import { displayText } from './displayText'

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
  return displayText(value)
}

function action(payload: Record<string, unknown>): string {
  return text(payload.action).toLowerCase()
}

function isBlocked(payload: Record<string, unknown>): boolean {
  const value = action(payload)
  return value.includes('blocked') || value.includes('failed') || value.includes('error')
}

function isDryRun(payload: Record<string, unknown>): boolean {
  if (payload.dry_run === true) return true
  return action(payload).includes('dry_run')
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

const FAMILY_BLOCKED_TITLES: Readonly<Record<string, string>> = {
  dispatch: 'Dispatch blocked',
  paper: 'Paper action blocked',
  finalize: 'Paper action blocked',
  research: 'Research action blocked',
  followup: 'Follow-up blocked',
  automation: 'Automation action blocked',
  command: 'Command blocked',
}

const FAMILY_DRY_RUN_TITLES: Readonly<Record<string, string>> = {
  dispatch: 'Dispatch dry-run passed',
  finalize: 'Paper finalize dry-run passed',
  paper: 'Paper draft dry-run passed',
  followup: 'Follow-up dry-run passed',
  research: 'Research dry-run passed',
  command: 'Dry-run passed',
}

const FAMILY_PASSED_TITLES: Readonly<Record<string, string>> = {
  dispatch: 'Dispatch completed',
  finalize: 'Paper finalize completed',
  paper: 'Paper action completed',
  followup: 'Follow-up completed',
  research: 'Research action completed',
  command: 'Command completed',
}

function familyTitle(family: string): string {
  if (family === 'dispatch') return 'Dispatch'
  if (family === 'finalize') return 'Paper finalize'
  if (family === 'paper') return 'Paper action'
  if (family === 'followup') return 'Follow-up'
  if (family === 'research') return 'Research action'
  return 'Command'
}

function titleForFamily(family: string, titles: Readonly<Record<string, string>>): string {
  return titles[family] ?? titles.command
}

function deriveTitle(payload: Record<string, unknown>, context: CommandPresentationContext | undefined, severity: CommandSeverity): string {
  const family = commandFamily(payload, context)
  if (context?.stale) return `${familyTitle(family)} stale — refresh required`

  if (severity === 'blocked' || severity === 'failed') return titleForFamily(family, FAMILY_BLOCKED_TITLES)
  if (severity === 'dry_run') return titleForFamily(family, FAMILY_DRY_RUN_TITLES)
  if (severity === 'passed') return titleForFamily(family, FAMILY_PASSED_TITLES)
  return 'Command result'
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
