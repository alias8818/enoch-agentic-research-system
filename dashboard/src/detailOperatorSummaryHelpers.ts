import { displayText } from './displayText'
import { shortId } from './format'

export type DetailKind = 'project' | 'run' | 'paper' | 'event'

export type EntityLink = {
  kind: DetailKind
  id: string
  label: string
}

export type OperatorAnswer = {
  label: string
  value: string
}

export type OperatorSection = {
  title: string
  answers: OperatorAnswer[]
}

export type DetailOperatorSummary = {
  state: string
  context: string
  next: string
  entityLinks: EntityLink[]
  sections: OperatorSection[]
  recentActivity: string | null
  actionNeeded: string | null
}

export type IntakeIdeaOperatorSummary = {
  state: string
  context: string
  next: string
  entityLinks: EntityLink[]
  sections: OperatorSection[]
  actionNeeded: string | null
}

export type ResearchCandidateOperatorSummary = IntakeIdeaOperatorSummary

export function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
}

export function recordArray(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value) ? value.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object' && !Array.isArray(item)) : []
}

export function firstValue(...values: unknown[]): unknown {
  return values.find((value) => value !== null && value !== undefined && value !== '')
}

export function text(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  if (typeof value === 'boolean') return value ? 'yes' : 'no'
  return displayText(value, '—')
}

export function entityLink(kind: DetailKind, id: unknown, label?: unknown): EntityLink | null {
  const normalized = text(id)
  if (normalized === '—') return null
  return { kind, id: normalized, label: text(label || shortId(normalized)) }
}

export function pushLink(links: EntityLink[], link: EntityLink | null) {
  if (!link) return
  if (links.some((existing) => existing.kind === link.kind && existing.id === link.id)) return
  links.push(link)
}

export function operatorNextStep(source: Record<string, unknown>, fallback: string): string {
  return text(firstValue(source.operator_next_step, fallback))
}

export function operatorStageLabel(source: Record<string, unknown>, fallback: string): string {
  return text(firstValue(source.operator_stage_label, source.operator_detail_stage_label, fallback))
}

export function queueRecord(payload: Record<string, unknown>): Record<string, unknown> {
  return record(payload.queue_item || payload.queue)
}

export function nullableText(value: unknown): string | null {
  const normalized = text(value)
  return normalized === '—' ? null : normalized
}

export function latestEventSummary(events: Record<string, unknown>[]): string | null {
  const latest = events[0]
  if (!latest) return null
  const summary = text(firstValue(latest.summary, latest.event_type))
  const when = text(firstValue(latest.created_at, latest.updated_at))
  if (summary === '—') return null
  return when === '—' ? summary : `${summary} (${when})`
}

export function recentActivityFrom(events: Record<string, unknown>[], ...fallbacks: unknown[]): string | null {
  return latestEventSummary(events) ?? nullableText(firstValue(...fallbacks))
}

export function artifactFlagPresent(flags: Record<string, unknown>, key: string): boolean {
  const aliases: Record<string, string[]> = {
    draft_markdown: ['draft_markdown', 'draft_markdown_path'],
    draft_latex: ['draft_latex', 'draft_latex_path'],
    evidence_bundle: ['evidence_bundle', 'evidence_bundle_path'],
    claim_ledger: ['claim_ledger', 'claim_ledger_path'],
    manifest: ['manifest', 'manifest_path'],
    finalization_package: ['finalization_package', 'finalization_package_path'],
  }
  return (aliases[key] || [key]).some((alias) => Boolean(flags[alias]))
}

export function artifactChecklist(flags: Record<string, unknown>): OperatorAnswer[] {
  const labels: Record<string, string> = {
    draft_markdown: 'draft markdown',
    draft_latex: 'draft latex',
    evidence_bundle: 'evidence bundle',
    claim_ledger: 'claim ledger',
    manifest: 'manifest',
    finalization_package: 'finalization package',
  }
  return Object.entries(labels).map(([key, label]) => ({
    label,
    value: artifactFlagPresent(flags, key) ? 'present' : 'missing',
  }))
}

export function missingPublicationArtifacts(flags: Record<string, unknown>): string[] {
  const labels: Record<string, string> = {
    draft_markdown: 'draft markdown',
    evidence_bundle: 'evidence bundle',
    claim_ledger: 'claim ledger',
    manifest: 'manifest',
    finalization_package: 'finalization package',
  }
  return Object.keys(labels).filter((key) => !artifactFlagPresent(flags, key)).map((key) => labels[key])
}

export function triStateFlag(value: unknown): string {
  if (value === true || value === 1 || value === '1' || value === 'true') return 'yes'
  if (value === false || value === 0 || value === '0' || value === 'false') return 'no'
  return 'unknown'
}
