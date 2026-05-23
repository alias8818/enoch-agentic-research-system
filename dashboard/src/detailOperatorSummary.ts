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

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
}

function recordArray(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value) ? value.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object' && !Array.isArray(item)) : []
}

function firstValue(...values: unknown[]): unknown {
  return values.find((value) => value !== null && value !== undefined && value !== '')
}

function text(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  if (typeof value === 'boolean') return value ? 'yes' : 'no'
  return String(value)
}

function entityLink(kind: DetailKind, id: unknown, label?: unknown): EntityLink | null {
  const normalized = text(id)
  if (normalized === '—') return null
  return { kind, id: normalized, label: text(label || shortId(normalized)) }
}

function pushLink(links: EntityLink[], link: EntityLink | null) {
  if (!link) return
  if (links.some((existing) => existing.kind === link.kind && existing.id === link.id)) return
  links.push(link)
}

function operatorNextStep(source: Record<string, unknown>, fallback: string): string {
  return text(firstValue(source.operator_next_step, fallback))
}

function operatorStageLabel(source: Record<string, unknown>, fallback: string): string {
  return text(firstValue(source.operator_stage_label, source.operator_detail_stage_label, fallback))
}

function queueRecord(payload: Record<string, unknown>): Record<string, unknown> {
  return record(payload.queue_item || payload.queue)
}

function nullableText(value: unknown): string | null {
  const normalized = text(value)
  return normalized === '—' ? null : normalized
}

function latestEventSummary(events: Record<string, unknown>[]): string | null {
  const latest = events[0]
  if (!latest) return null
  const summary = text(firstValue(latest.summary, latest.event_type))
  const when = text(firstValue(latest.created_at, latest.updated_at))
  if (summary === '—') return null
  return when !== '—' ? `${summary} (${when})` : summary
}

function recentActivityFrom(events: Record<string, unknown>[], ...fallbacks: unknown[]): string | null {
  return latestEventSummary(events) ?? nullableText(firstValue(...fallbacks))
}

function artifactFlagPresent(flags: Record<string, unknown>, key: string): boolean {
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

function artifactChecklist(flags: Record<string, unknown>): OperatorAnswer[] {
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

function missingPublicationArtifacts(flags: Record<string, unknown>): string[] {
  const labels: Record<string, string> = {
    draft_markdown: 'draft markdown',
    evidence_bundle: 'evidence bundle',
    claim_ledger: 'claim ledger',
    manifest: 'manifest',
    finalization_package: 'finalization package',
  }
  return Object.keys(labels).filter((key) => !artifactFlagPresent(flags, key)).map((key) => labels[key])
}

function triStateFlag(value: unknown): string {
  if (value === true || value === 1 || value === '1' || value === 'true') return 'yes'
  if (value === false || value === 0 || value === '0' || value === 'false') return 'no'
  return 'unknown'
}

function projectSummary(payload: Record<string, unknown>): DetailOperatorSummary {
  const project = record(payload.project)
  const queue = queueRecord(payload)
  const runs = recordArray(payload.runs)
  const papers = recordArray(payload.papers)
  const events = recordArray(payload.events)
  const stageSource = { ...project, ...queue, ...payload }
  const state = text(firstValue(queue.status, queue.queue_status, payload.status, project.origin_idea_status, payload.queue_status))
  const lane = text(firstValue(queue.machine_target, queue.operator_lane, payload.machine_target, project.machine_target))
  const runId = text(firstValue(queue.current_run_id, project.current_run_id, payload.run_id, runs[0]?.run_id))
  const runState = text(firstValue(queue.last_run_state, payload.latest_run_state, runs[0]?.state))
  const paperStatus = text(firstValue(queue.related_paper_status, papers[0]?.paper_status, papers[0]?.status, payload.related_paper_status))
  const paperId = text(firstValue(queue.related_paper_id, papers[0]?.paper_id))
  const paperReview = text(firstValue(queue.related_review_status, papers[0]?.review_status))
  const paperFinalization = text(firstValue(queue.related_finalization_status, papers[0]?.finalization_status, papers[0]?.package_status))
  const corpusImported = triStateFlag(firstValue(queue.related_corpus_imported, papers[0]?.corpus_imported))
  const blocked = text(firstValue(queue.blocked_reason, queue.last_error, queue.decision_summary))
  const attention = queue.operator_attention === true || state.includes('blocked') || state.includes('review')
  const entityLinks: EntityLink[] = []
  pushLink(entityLinks, entityLink('run', runId !== '—' ? runId : null))
  pushLink(entityLinks, entityLink('paper', paperId !== '—' ? paperId : null, papers[0]?.paper_title || papers[0]?.title))

  return {
    state: operatorStageLabel(stageSource, state),
    context: `Queue ${state}; lane ${lane}; latest run ${runState}.`,
    next: operatorNextStep(stageSource, attention
      ? 'Resolve the blocker or manual-review flag before dispatching again.'
      : state === 'queued'
        ? 'Run a dispatch dry-run on the lane card before starting work.'
        : runState === 'running' || state === 'running'
          ? 'Open the current run and watch gate state plus recent events.'
          : 'Review paper status and recent events before taking a write action.'),
    entityLinks,
    sections: [
      {
        title: 'What is this project?',
        answers: [
          { label: 'name', value: text(firstValue(project.project_name, payload.project_name)) },
          { label: 'origin idea status', value: text(firstValue(project.origin_idea_status, payload.origin_idea_status)) },
          { label: 'updated', value: text(firstValue(project.updated_at, queue.updated_at, payload.updated_at)) },
        ],
      },
      {
        title: 'Queue and lane ownership',
        answers: [
          { label: 'queue status', value: state },
          { label: 'lane / machine target', value: lane },
          { label: 'selection rank', value: text(queue.selection_rank) },
          { label: 'next action hint', value: text(queue.next_action_hint) },
        ],
      },
      {
        title: 'Latest run',
        answers: [
          { label: 'current run', value: runId },
          { label: 'run state', value: runState },
        ],
      },
      {
        title: 'Paper and publication path',
        answers: [
          { label: 'related paper', value: paperId },
          { label: 'paper status', value: paperStatus },
          { label: 'review status', value: paperReview },
          { label: 'finalization status', value: paperFinalization },
          { label: 'corpus imported', value: corpusImported },
        ],
      },
    ],
    recentActivity: recentActivityFrom(events, queue.last_result_summary, queue.decision_summary),
    actionNeeded: attention && blocked !== '—' ? blocked : attention ? 'Operator attention required.' : null,
  }
}

function runOutcomeLabel(state: string, gate: string, endedAt: string): string {
  const normalizedState = state.toLowerCase()
  const normalizedGate = gate.toLowerCase()
  if (normalizedState.includes('error') || normalizedGate.includes('error')) return 'failed'
  if (endedAt !== '—') return 'finished'
  if (normalizedGate === 'awaiting_wake' || normalizedState === 'awaiting_wake' || normalizedState === 'wake_received') {
    return 'waiting for wake'
  }
  if (normalizedState === 'running' || normalizedState === 'dispatching' || normalizedState === 'reconciling') {
    return 'still running'
  }
  return state !== '—' ? state : 'unknown'
}

function runSummary(payload: Record<string, unknown>): DetailOperatorSummary {
  const run = record(payload.run)
  const project = record(payload.project)
  const queue = queueRecord(payload)
  const papers = recordArray(payload.papers)
  const events = recordArray(payload.events)
  const stageSource = { ...run, ...payload }
  const state = text(firstValue(run.state, payload.state))
  const gate = text(firstValue(run.gate_state, payload.gate_state))
  const activity = text(firstValue(run.current_activity, payload.current_activity))
  const projectId = text(firstValue(run.project_id, project.project_id, payload.project_id))
  const projectName = text(firstValue(project.project_name, run.project_name))
  const machineTarget = text(firstValue(queue.machine_target, payload.machine_target))
  const operatorLane = text(firstValue(run.operator_lane, queue.operator_lane))
  const endedAt = text(firstValue(run.ended_at, payload.ended_at))
  const lastCallbackAt = text(firstValue(run.last_callback_at, payload.last_callback_at))
  const paperId = text(firstValue(run.related_paper_id, papers[0]?.paper_id))
  const paperStatus = text(firstValue(run.related_paper_status, papers[0]?.paper_status, papers[0]?.status))
  const paperReview = text(firstValue(run.related_review_status, papers[0]?.review_status))
  const entityLinks: EntityLink[] = []
  pushLink(entityLinks, entityLink('project', projectId !== '—' ? projectId : null, projectName))
  pushLink(entityLinks, entityLink('paper', paperId !== '—' ? paperId : null, papers[0]?.paper_title || papers[0]?.title))
  const errorState = state.includes('error') || gate.includes('error')
  const artifactFlags = record(run.related_artifact_paths_present)
  const outcome = runOutcomeLabel(state, gate, endedAt)

  return {
    state: operatorStageLabel(stageSource, state),
    context: `Gate ${gate}; activity ${activity}; outcome ${outcome}.`,
    next: operatorNextStep(stageSource, errorState
      ? 'Inspect recent events and worker logs before retrying dispatch.'
      : outcome === 'waiting for wake'
        ? 'Wait for the worker wake callback unless the gate has been stale for too long.'
        : state === 'running' || state === 'dispatching'
          ? 'Watch activity and recent events; intervene only if the gate stops moving.'
          : 'Review related paper artifacts before queuing another action.'),
    entityLinks,
    sections: [
      {
        title: 'Which project ran?',
        answers: [
          { label: 'project', value: projectName !== '—' ? projectName : projectId },
          { label: 'project id', value: projectId },
        ],
      },
      {
        title: 'Worker and lane',
        answers: [
          { label: 'machine target', value: machineTarget },
          { label: 'operator lane', value: operatorLane },
          { label: 'dispatch mode', value: text(firstValue(run.dispatch_mode, payload.dispatch_mode)) },
          { label: 'session', value: text(firstValue(run.session_id, payload.session_id)) },
        ],
      },
      {
        title: 'Run progress',
        answers: [
          { label: 'state', value: state },
          { label: 'gate', value: gate },
          { label: 'activity', value: activity },
        ],
      },
      {
        title: 'Run outcome',
        answers: [
          { label: 'outcome', value: outcome },
          { label: 'last callback', value: lastCallbackAt },
          { label: 'ended', value: endedAt },
        ],
      },
      {
        title: 'Timestamps',
        answers: [
          { label: 'started', value: text(firstValue(run.started_at, payload.started_at)) },
          { label: 'updated', value: text(firstValue(run.updated_at, payload.updated_at)) },
          { label: 'ended', value: endedAt },
        ],
      },
      {
        title: 'Paper and publication path',
        answers: [
          { label: 'related paper', value: paperId },
          { label: 'paper status', value: paperStatus },
          { label: 'review status', value: paperReview },
        ],
      },
      {
        title: 'Artifacts available',
        answers: artifactChecklist(artifactFlags),
      },
    ],
    recentActivity: latestEventSummary(events),
    actionNeeded: errorState ? `Run stopped in ${state} with gate ${gate}.` : null,
  }
}

function paperPublicationBlocker(
  review: string,
  operatorExplanation: string,
  missingArtifacts: string[],
  imported: boolean,
): string {
  if (review === 'rejected') return 'Review rejected this paper.'
  if (operatorExplanation !== '—') return operatorExplanation
  if (missingArtifacts.length) return `Missing: ${missingArtifacts.join(', ')}.`
  if (imported) return 'Corpus import complete; no publication blockers.'
  return 'Publication artifacts ready for corpus import.'
}

function paperSummaryContext(
  imported: boolean,
  missingArtifacts: string[],
  review: string,
  flags: Record<string, unknown>,
): string {
  if (imported) return 'Corpus import ledger shows this paper as imported.'
  if (missingArtifacts.length) {
    return `Publication blocked: missing ${missingArtifacts.join(', ')}.`
  }
  if (review !== '—') return `Review ${review}; all publication artifacts present.`
  const evidence = artifactFlagPresent(flags, 'evidence_bundle') ? 'present' : 'missing'
  const claimLedger = artifactFlagPresent(flags, 'claim_ledger') ? 'present' : 'missing'
  return `Evidence paths ${evidence}; claim ledger ${claimLedger}.`
}

function paperSummaryNextStep(
  stageSource: Record<string, unknown>,
  imported: boolean,
  reviewRejected: boolean,
  needsFinalization: boolean,
  missingArtifacts: string[],
): string {
  if (imported) {
    return operatorNextStep(stageSource, 'No corpus import action is needed for this paper.')
  }
  if (reviewRejected) {
    return operatorNextStep(stageSource, 'Do not publish; start a new run or resolve review rejection first.')
  }
  if (needsFinalization || missingArtifacts.length) {
    return operatorNextStep(stageSource, 'Preview artifacts, then finalize only after checklist items look correct.')
  }
  return operatorNextStep(stageSource, 'Run corpus import when the publication checklist is complete.')
}

function paperSummaryActionNeeded(
  reviewRejected: boolean,
  missingArtifacts: string[],
): string | null {
  if (reviewRejected) return 'Review rejected this paper; do not publish without a new run.'
  if (missingArtifacts.length) {
    return `Complete missing artifacts before publication: ${missingArtifacts.join(', ')}.`
  }
  return null
}

function paperSummary(payload: Record<string, unknown>): DetailOperatorSummary {
  const paper = record(payload.paper)
  const project = record(payload.project)
  const run = record(payload.run)
  const queue = queueRecord(payload)
  const events = recordArray(payload.events)
  const stageSource = { ...paper, ...payload }
  const title = text(firstValue(paper.paper_title, paper.title, payload.title))
  const status = text(firstValue(paper.paper_status, paper.status, payload.status, payload.paper_status))
  const review = text(firstValue(paper.review_status, payload.review_status))
  const imported = paper.corpus_imported === true
  const flags = record(paper.artifact_paths_present)
  const projectId = text(firstValue(paper.project_id, project.project_id, payload.project_id))
  const projectName = text(firstValue(project.project_name, paper.project_name))
  const runId = text(firstValue(paper.run_id, run.run_id, payload.run_id))
  const runState = text(firstValue(run.state, payload.run_state))
  const machineTarget = text(firstValue(queue.machine_target, payload.machine_target))
  const operatorExplanation = text(firstValue(paper.operator_explanation, payload.operator_explanation))
  const missingArtifacts = missingPublicationArtifacts(flags)
  const publicationBlocker = paperPublicationBlocker(review, operatorExplanation, missingArtifacts, imported)
  const entityLinks: EntityLink[] = []
  pushLink(entityLinks, entityLink('project', projectId !== '—' ? projectId : null, projectName))
  pushLink(entityLinks, entityLink('run', runId !== '—' ? runId : null))
  const reviewRejected = review === 'rejected'
  const needsFinalization = missingArtifacts.includes('finalization package')
  const context = paperSummaryContext(imported, missingArtifacts, review, flags)

  return {
    state: operatorStageLabel(stageSource, status),
    context,
    next: paperSummaryNextStep(stageSource, imported, reviewRejected, needsFinalization, missingArtifacts),
    entityLinks,
    sections: [
      {
        title: 'What is this paper?',
        answers: [
          { label: 'title', value: title },
          { label: 'paper status', value: status },
          { label: 'paper type', value: text(paper.paper_type) },
          { label: 'review status', value: review },
        ],
      },
      {
        title: 'Related project and run',
        answers: [
          { label: 'project', value: projectName !== '—' ? projectName : projectId },
          { label: 'run state', value: runState },
          { label: 'machine target', value: machineTarget },
        ],
      },
      {
        title: 'Publication checklist',
        answers: artifactChecklist(flags),
      },
      {
        title: 'Draft and import status',
        answers: [
          { label: 'corpus imported', value: text(imported) },
          { label: 'corpus import id', value: text(paper.corpus_import_id) },
          { label: 'HF dataset synced', value: text(paper.hf_dataset_synced) },
        ],
      },
      {
        title: 'What blocks publication?',
        answers: [
          { label: 'missing artifacts', value: publicationBlocker },
          { label: 'operator explanation', value: operatorExplanation },
        ],
      },
    ],
    recentActivity: latestEventSummary(events),
    actionNeeded: paperSummaryActionNeeded(reviewRejected, missingArtifacts),
  }
}

const EVENT_PAYLOAD_PROOF_KEYS: ReadonlyArray<[string, string]> = [
  ['reason', 'reason'], ['detail', 'detail'], ['summary', 'payload summary'],
  ['gate_state', 'gate state'], ['state', 'state'], ['status', 'status'],
  ['blocked_reason', 'blocked reason'], ['operator_summary', 'operator summary'],
  ['project_id', 'project id'], ['run_id', 'run id'], ['paper_id', 'paper id'],
]

function eventPayloadRecord(payload: Record<string, unknown>): Record<string, unknown> {
  return record(payload.payload)
}

function eventHumanSummary(payload: Record<string, unknown>): string {
  const nested = eventPayloadRecord(payload)
  return text(firstValue(payload.summary, payload.message, nested.summary, nested.reason, nested.detail, nested.operator_summary, payload.event_type))
}

function eventEntityLinks(payload: Record<string, unknown>): EntityLink[] {
  const entityLinks: EntityLink[] = []
  const nested = eventPayloadRecord(payload)
  const entityType = text(firstValue(payload.entity_type, '')).toLowerCase()
  const entityId = text(firstValue(payload.entity_id, ''))
  for (const source of [payload, nested]) {
    pushLink(entityLinks, entityLink('project', source.project_id))
    pushLink(entityLinks, entityLink('run', source.run_id))
    pushLink(entityLinks, entityLink('paper', source.paper_id))
  }
  if (!entityLinks.length && entityId !== '—') {
    if (entityType === 'queue_alert') return entityLinks
    const kind: DetailKind = entityType.includes('run') ? 'run' : entityType.includes('paper') || entityType.includes('paper_review') ? 'paper' : 'project'
    pushLink(entityLinks, entityLink(kind, entityId))
  }
  return entityLinks
}

function eventEntityLabel(entityType: string, entityId: string): string {
  if (entityId === '—') return ''
  const normalized = entityType.toLowerCase()
  if (normalized === 'queue_alert') return `Alert fingerprint ${shortId(entityId)}`
  return `${entityType} ${shortId(entityId)}`
}

function payloadProofAnswers(payload: Record<string, unknown>): OperatorAnswer[] {
  const nested = eventPayloadRecord(payload)
  const answers: OperatorAnswer[] = []
  const seen = new Set<string>()
  for (const [key, label] of EVENT_PAYLOAD_PROOF_KEYS) {
    const normalized = text(firstValue(nested[key], payload[key]))
    if (normalized === '—' || seen.has(label)) continue
    seen.add(label)
    answers.push({ label, value: normalized })
  }
  const findings = recordArray(nested.findings)
  if (findings.length) {
    answers.push({ label: 'findings', value: `${findings.length} recorded` })
    const topFinding = findings[0]
    const topFindingMessage = text(firstValue(topFinding.message, topFinding.source))
    if (topFindingMessage !== '—') {
      answers.push({ label: 'top finding', value: topFindingMessage })
    }
  }
  if (Array.isArray(nested.dispatch_blockers)) {
    const blockers = nested.dispatch_blockers.map((item) => text(item)).filter((item) => item !== '—')
    answers.push({ label: 'dispatch blockers', value: blockers.length ? blockers.join('; ') : 'none' })
  }
  if (Array.isArray(nested.transient_suppressed_findings)) {
    answers.push({ label: 'suppressed transient findings', value: String(nested.transient_suppressed_findings.length) })
  }
  if (nested.dispatch_safe !== null && nested.dispatch_safe !== undefined) {
    answers.push({ label: 'dispatch safe at event time', value: text(nested.dispatch_safe) })
  }
  if (!answers.length) {
    answers.push({ label: 'payload', value: nested && Object.keys(nested).length ? 'present — expand Raw payload for full evidence' : 'empty' })
  }
  return answers
}

function eventActionNeeded(payload: Record<string, unknown>): string | null {
  const nested = eventPayloadRecord(payload)
  const reason = text(firstValue(nested.reason, nested.blocked_reason, nested.error, payload.blocked_reason))
  if (reason === '—') {
    const findings = recordArray(nested.findings)
    const topFinding = findings[0]
    const findingReason = text(firstValue(topFinding?.message, topFinding?.source))
    return findingReason === '—' ? null : findingReason
  }
  const eventType = text(payload.event_type).toLowerCase()
  if (eventType.includes('blocked') || eventType.includes('alert') || eventType.includes('error') || eventType.includes('conflict') || reason.toLowerCase().includes('block') || reason.toLowerCase().includes('fail')) return reason
  return null
}

function eventSummary(payload: Record<string, unknown>): DetailOperatorSummary {
  const eventType = text(payload.event_type)
  const headline = eventHumanSummary(payload)
  const entityId = text(firstValue(payload.entity_id, payload.project_id, payload.paper_id, payload.run_id))
  const entityType = text(firstValue(payload.entity_type, payload.project_id ? 'project' : payload.run_id ? 'run' : payload.paper_id ? 'paper' : 'entity'))
  const createdAt = text(firstValue(payload.created_at, payload.updated_at))
  const eventId = text(firstValue(payload.event_id, payload.id))
  const entityLinks = eventEntityLinks(payload)
  const actionNeeded = eventActionNeeded(payload)
  const stageSource = { ...payload, ...eventPayloadRecord(payload) }

  return {
    state: operatorStageLabel(stageSource, headline !== eventType ? headline : eventType),
    context: entityId !== '—' ? `${eventEntityLabel(entityType, entityId)} · logged ${createdAt}.` : `Logged ${createdAt}.`,
    next: operatorNextStep(stageSource, actionNeeded ? `Resolve the recorded blocker: ${actionNeeded}` : entityLinks.length ? 'Open the related project, run, or paper if this event requires action.' : 'Use the payload only as supporting detail; do not treat it as a command.'),
    entityLinks,
    sections: [
      { title: 'What happened?', answers: [{ label: 'event type', value: eventType }, { label: 'summary', value: headline }, { label: 'event id', value: eventId }] },
      { title: 'When?', answers: [{ label: 'created', value: createdAt }, { label: 'updated', value: text(payload.updated_at) }] },
      { title: 'Which entity was affected?', answers: [{ label: 'entity type', value: entityType }, { label: 'entity id', value: entityId }, { label: 'related links', value: entityLinks.length ? `${entityLinks.length} linked` : 'none resolved' }] },
      { title: 'What does the payload prove?', answers: payloadProofAnswers(payload) },
    ],
    recentActivity: headline !== eventType ? headline : null,
    actionNeeded,
  }
}

export function deriveDetailOperatorSummary(kind: DetailKind, payload: Record<string, unknown>): DetailOperatorSummary {
  if (kind === 'project') return projectSummary(payload)
  if (kind === 'run') return runSummary(payload)
  if (kind === 'paper') return paperSummary(payload)
  return eventSummary(payload)
}

export function deriveIntakeIdeaOperatorSummary(row: Record<string, unknown>): IntakeIdeaOperatorSummary {
  const ideaStatus = text(row.idea_status)
  const queueStatus = text(row.queue_status)
  const paperStatus = text(row.paper_status)
  const nextHint = text(row.next_action_hint)
  const ideaId = text(row.idea_id)
  const projectId = text(firstValue(row.project_id, row.idea_id))
  const sourceKind = text(row.source_kind)
  const sourceExternalId = text(row.source_external_id)
  const sourceExternalUrl = text(row.source_external_url)
  const machineTarget = text(row.machine_target)
  const runId = text(row.current_run_id)
  const runState = text(row.last_run_state)
  const paperId = text(row.paper_id)
  const blocked = text(firstValue(row.blocked_reason, row.last_error))
  const promoted = projectId !== '—' && projectId !== ideaId
  const attention = row.manual_review_required === true || row.operator_attention === true || queueStatus.includes('blocked') || queueStatus.includes('review') || ideaStatus === 'rejected'
  const whyNotQueued = blocked !== '—'
    ? blocked
    : queueStatus === 'queued'
      ? 'currently queued'
      : ideaStatus === 'rejected'
        ? 'idea rejected at admission'
        : ideaStatus === 'candidate'
          ? 'not admitted yet — promote or admit before queuing'
          : ideaStatus === 'stale'
            ? 'idea marked stale — refresh or re-admit'
            : !queueStatus || queueStatus === '—'
              ? 'no queue row yet'
              : `queue status is ${queueStatus}`
  const entityLinks: EntityLink[] = []
  pushLink(entityLinks, entityLink('project', projectId !== '—' ? projectId : null, row.title))
  pushLink(entityLinks, entityLink('run', runId !== '—' ? runId : null))
  pushLink(entityLinks, entityLink('paper', paperId !== '—' ? paperId : null))

  return {
    state: operatorStageLabel(row, ideaStatus),
    context: promoted
      ? `Promoted to project ${shortId(projectId)}; source ${sourceKind}; queue ${queueStatus}; lane ${machineTarget}.`
      : `Source ${sourceKind}; admission ${ideaStatus}; queue ${queueStatus}; paper ${paperStatus}.`,
    next: operatorNextStep(row, attention && blocked !== '—'
      ? `Resolve blocker first: ${blocked}.`
      : queueStatus === 'queued'
        ? 'Open the matching project and run a dispatch dry-run before starting work.'
        : queueStatus === 'active' || queueStatus === 'running'
          ? 'Open the current project/run detail and verify the lane is still moving.'
          : ideaStatus === 'rejected'
            ? 'Do not queue this idea; review admission rejection and source lineage.'
            : ideaStatus === 'candidate'
              ? 'Admit or promote this candidate before expecting queue work.'
              : nextHint !== '—'
                ? `Follow backend hint: ${nextHint}.`
                : 'Review source lineage and admission state before creating more queue work.'),
    entityLinks,
    sections: [
      {
        title: 'Source and lineage',
        answers: [
          { label: 'source kind', value: sourceKind },
          { label: 'source external id', value: sourceExternalId },
          { label: 'source url', value: sourceExternalUrl },
          { label: 'idea status', value: ideaStatus },
          { label: 'updated', value: text(firstValue(row.queue_updated_at, row.updated_at)) },
        ],
      },
      {
        title: 'Admission and promote',
        answers: [
          { label: 'admission state', value: ideaStatus },
          { label: 'promoted project', value: promoted ? projectId : 'not promoted yet' },
          { label: 'manual review', value: text(row.manual_review_required) },
          { label: 'selection rank', value: text(row.selection_rank) },
        ],
      },
      {
        title: 'Queue and lane',
        answers: [
          { label: 'queue status', value: queueStatus },
          { label: 'lane / machine target', value: machineTarget },
          { label: 'current run', value: runId },
          { label: 'last run state', value: runState },
          { label: 'paper status', value: paperStatus },
          { label: 'next action hint', value: nextHint },
          { label: 'why not queued', value: whyNotQueued },
        ],
      },
      {
        title: 'Related project',
        answers: [
          { label: 'project id', value: projectId },
          { label: 'title', value: text(row.title) },
        ],
      },
    ],
    actionNeeded: attention ? (blocked !== '—' ? blocked : ideaStatus === 'rejected' ? 'Idea rejected at admission.' : 'Admission or queue state needs operator review.') : null,
  }
}

export function deriveResearchCandidateOperatorSummary(row: Record<string, unknown>): ResearchCandidateOperatorSummary {
  const status = text(row.status)
  const admission = text(row.admission_decision)
  const target = text(row.machine_target)
  const candidateId = text(row.candidate_id)
  const ideaId = text(firstValue(row.admitted_idea_id, row.idea_id))
  const projectId = text(row.project_id)
  const promoted = ideaId !== '—' || projectId !== '—'
  const rejected = status === 'rejected' || admission.toLowerCase().includes('reject')
  const admitted = status === 'admitted' || admission.toLowerCase().includes('admit')
  const attention = rejected || row.manual_review_required === true || row.operator_attention === true
  const whyNotPromoted = rejected
    ? 'admission rejected — keep as negative evidence'
    : !admitted
      ? 'not admitted — review facility scoring before promote'
      : promoted
        ? ideaId !== '—'
          ? `promoted to idea ${shortId(ideaId)}`
          : `linked project ${shortId(projectId)}`
        : 'admitted but not yet promoted to intake/queue'
  const entityLinks: EntityLink[] = []
  pushLink(entityLinks, entityLink('project', projectId !== '—' ? projectId : null, row.title))

  return {
    state: operatorStageLabel(row, status),
    context: `Admission ${admission}; target ${target}; facility status ${status}.`,
    next: operatorNextStep(row, rejected
      ? 'No launch action is needed; keep this as negative evidence unless a new follow-up is warranted.'
      : admitted
        ? 'Promote only after dry-run confirms this exact candidate still maps to a queue item.'
        : 'Review admission, source lineage, and machine target before promoting or queuing work.'),
    entityLinks,
    sections: [
      {
        title: 'Source and lineage',
        answers: [
          { label: 'candidate id', value: candidateId },
          { label: 'source kind', value: text(row.source_kind) },
          { label: 'source external id', value: text(row.source_external_id) },
          { label: 'facility status', value: status },
          { label: 'updated', value: text(row.updated_at) },
        ],
      },
      {
        title: 'Admission and promote',
        answers: [
          { label: 'admission decision', value: admission },
          { label: 'admitted idea', value: ideaId },
          { label: 'linked project', value: projectId },
          { label: 'promote path', value: whyNotPromoted },
          { label: 'selection rank', value: text(row.selection_rank) },
        ],
      },
      {
        title: 'Lane and dispatch',
        answers: [
          { label: 'machine target', value: target },
          { label: 'total score', value: text(row.total_score) },
          { label: 'title', value: text(row.title) },
        ],
      },
    ],
    actionNeeded: attention ? (rejected ? 'Candidate rejected at admission.' : 'Admission needs operator review before promote.') : null,
  }
}
