import { shortId } from './format'
import {
  artifactChecklist,
  entityLink,
  firstValue,
  latestEventSummary,
  operatorNextStep,
  operatorStageLabel,
  pushLink,
  queueRecord,
  recentActivityFrom,
  record,
  recordArray,
  text,
  triStateFlag,
  type DetailKind,
  type DetailOperatorSummary,
  type EntityLink,
  type IntakeIdeaOperatorSummary,
  type OperatorAnswer,
} from './detailOperatorSummaryHelpers'
import { paperSummary } from './detailOperatorSummaryPaper'

export { deriveIntakeIdeaOperatorSummary } from './detailOperatorSummaryIntake'

function projectNextStepMessage(attention: boolean, state: string, runState: string): string {
  if (attention) {
    return 'Resolve the blocker or manual-review flag before dispatching again.'
  }
  if (state === 'queued') {
    return 'Run a dispatch dry-run on the lane card before starting work.'
  }
  if (runState === 'running' || state === 'running') {
    return 'Open the current run and watch gate state plus recent events.'
  }
  return 'Review paper status and recent events before taking a write action.'
}

export type {
  DetailKind,
  DetailOperatorSummary,
  EntityLink,
  IntakeIdeaOperatorSummary,
  OperatorAnswer,
  OperatorSection,
} from './detailOperatorSummaryHelpers'

function projectActionNeeded(attention: boolean, blocked: string): string | null {
  if (!attention) return null
  if (blocked !== '—') return blocked
  return 'Operator attention required.'
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
    next: operatorNextStep(stageSource, projectNextStepMessage(attention, state, runState)),
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
    actionNeeded: projectActionNeeded(attention, blocked),
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

function runNextStepMessage(errorState: boolean, outcome: string, state: string): string {
  if (errorState) {
    return 'Inspect recent events and worker logs before retrying dispatch.'
  }
  if (outcome === 'waiting for wake') {
    return 'Wait for the worker wake callback unless the gate has been stale for too long.'
  }
  if (state === 'running' || state === 'dispatching') {
    return 'Watch activity and recent events; intervene only if the gate stops moving.'
  }
  return 'Review related paper artifacts before queuing another action.'
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
    next: operatorNextStep(stageSource, runNextStepMessage(errorState, outcome, state)),
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
    let kind: DetailKind = 'project'
    if (entityType.includes('run')) {
      kind = 'run'
    } else if (entityType.includes('paper') || entityType.includes('paper_review')) {
      kind = 'paper'
    }
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

function appendEventPayloadProofKeys(
  answers: OperatorAnswer[],
  seen: Set<string>,
  nested: Record<string, unknown>,
  payload: Record<string, unknown>,
): void {
  for (const [key, label] of EVENT_PAYLOAD_PROOF_KEYS) {
    const normalized = text(firstValue(nested[key], payload[key]))
    if (normalized === '—' || seen.has(label)) continue
    seen.add(label)
    answers.push({ label, value: normalized })
  }
}

function appendFindingsProofAnswers(answers: OperatorAnswer[], nested: Record<string, unknown>): void {
  const findings = recordArray(nested.findings)
  if (!findings.length) return
  answers.push({ label: 'findings', value: `${findings.length} recorded` })
  const topFindingMessage = text(firstValue(findings[0].message, findings[0].source))
  if (topFindingMessage !== '—') {
    answers.push({ label: 'top finding', value: topFindingMessage })
  }
}

function appendDispatchProofAnswers(answers: OperatorAnswer[], nested: Record<string, unknown>): void {
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
}

function emptyPayloadProofFallback(nested: Record<string, unknown>): OperatorAnswer {
  const hasNestedKeys = nested && Object.keys(nested).length > 0
  return {
    label: 'payload',
    value: hasNestedKeys ? 'present — expand Raw payload for full evidence' : 'empty',
  }
}

function payloadProofAnswers(payload: Record<string, unknown>): OperatorAnswer[] {
  const nested = eventPayloadRecord(payload)
  const answers: OperatorAnswer[] = []
  const seen = new Set<string>()
  appendEventPayloadProofKeys(answers, seen, nested, payload)
  appendFindingsProofAnswers(answers, nested)
  appendDispatchProofAnswers(answers, nested)
  if (!answers.length) {
    answers.push(emptyPayloadProofFallback(nested))
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

function eventDefaultEntityType(payload: Record<string, unknown>): string {
  if (payload.project_id) return 'project'
  if (payload.run_id) return 'run'
  if (payload.paper_id) return 'paper'
  return 'entity'
}

function eventNextStepMessage(actionNeeded: string | null, entityLinks: EntityLink[]): string {
  if (actionNeeded) {
    return `Resolve the recorded blocker: ${actionNeeded}`
  }
  if (entityLinks.length) {
    return 'Open the related project, run, or paper if this event requires action.'
  }
  return 'Use the payload only as supporting detail; do not treat it as a command.'
}

function eventSummary(payload: Record<string, unknown>): DetailOperatorSummary {
  const eventType = text(payload.event_type)
  const headline = eventHumanSummary(payload)
  const entityId = text(firstValue(payload.entity_id, payload.project_id, payload.paper_id, payload.run_id))
  const entityType = text(firstValue(payload.entity_type, eventDefaultEntityType(payload)))
  const createdAt = text(firstValue(payload.created_at, payload.updated_at))
  const eventId = text(firstValue(payload.event_id, payload.id))
  const entityLinks = eventEntityLinks(payload)
  const actionNeeded = eventActionNeeded(payload)
  const stageSource = { ...payload, ...eventPayloadRecord(payload) }

  return {
    state: operatorStageLabel(stageSource, headline !== eventType ? headline : eventType),
    context: entityId !== '—' ? `${eventEntityLabel(entityType, entityId)} · logged ${createdAt}.` : `Logged ${createdAt}.`,
    next: operatorNextStep(stageSource, eventNextStepMessage(actionNeeded, entityLinks)),
    entityLinks,
    sections: [
      { title: 'What happened?', answers: [{ label: 'event type', value: eventType }, { label: 'summary', value: headline }, { label: 'event id', value: eventId }] },
      { title: 'When?', answers: [{ label: 'created', value: createdAt }, { label: 'updated', value: text(payload.updated_at) }] },
      { title: 'Which entity was affected?', answers: [{ label: 'entity type', value: entityType }, { label: 'entity id', value: entityId }, { label: 'related links', value: entityLinks.length ? `${entityLinks.length} linked` : 'none resolved' }] },
      { title: 'What does the payload prove?', answers: payloadProofAnswers(payload) },
    ],
    recentActivity: headline === eventType ? null : headline,
    actionNeeded,
  }
}

export function deriveDetailOperatorSummary(kind: DetailKind, payload: Record<string, unknown>): DetailOperatorSummary {
  if (kind === 'project') return projectSummary(payload)
  if (kind === 'run') return runSummary(payload)
  if (kind === 'paper') return paperSummary(payload)
  return eventSummary(payload)
}

function researchCandidateRejected(status: string, admission: string): boolean {
  return status === 'rejected' || admission.toLowerCase().includes('reject')
}

function researchCandidateAdmitted(status: string, admission: string): boolean {
  return status === 'admitted' || admission.toLowerCase().includes('admit')
}

function researchCandidateNeedsAttention(row: Record<string, unknown>, rejected: boolean): boolean {
  return rejected || row.manual_review_required === true || row.operator_attention === true
}

function researchCandidatePromotePath(
  rejected: boolean,
  admitted: boolean,
  promoted: boolean,
  ideaId: string,
  projectId: string,
): string {
  if (rejected) return 'admission rejected — keep as negative evidence'
  if (!admitted) return 'not admitted — review facility scoring before promote'
  if (!promoted) return 'admitted but not yet promoted to intake/queue'
  if (ideaId !== '—') return `promoted to idea ${shortId(ideaId)}`
  return `linked project ${shortId(projectId)}`
}

function researchCandidateNextStepMessage(rejected: boolean, admitted: boolean): string {
  if (rejected) {
    return 'No launch action is needed; keep this as negative evidence unless a new follow-up is warranted.'
  }
  if (admitted) {
    return 'Promote only after dry-run confirms this exact candidate still maps to a queue item.'
  }
  return 'Review admission, source lineage, and machine target before promoting or queuing work.'
}

function researchCandidateActionNeeded(attention: boolean, rejected: boolean): string | null {
  if (!attention) return null
  if (rejected) return 'Candidate rejected at admission.'
  return 'Admission needs operator review before promote.'
}

export function deriveResearchCandidateOperatorSummary(row: Record<string, unknown>): IntakeIdeaOperatorSummary {
  const status = text(row.status)
  const admission = text(row.admission_decision)
  const target = text(row.machine_target)
  const candidateId = text(row.candidate_id)
  const ideaId = text(firstValue(row.admitted_idea_id, row.idea_id))
  const projectId = text(row.project_id)
  const promoted = ideaId !== '—' || projectId !== '—'
  const rejected = researchCandidateRejected(status, admission)
  const admitted = researchCandidateAdmitted(status, admission)
  const attention = researchCandidateNeedsAttention(row, rejected)
  const promotePath = researchCandidatePromotePath(rejected, admitted, promoted, ideaId, projectId)
  const entityLinks: EntityLink[] = []
  pushLink(entityLinks, entityLink('project', projectId !== '—' ? projectId : null, row.title))

  return {
    state: operatorStageLabel(row, status),
    context: `Admission ${admission}; target ${target}; facility status ${status}.`,
    next: operatorNextStep(row, researchCandidateNextStepMessage(rejected, admitted)),
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
          { label: 'promote path', value: promotePath },
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
    actionNeeded: researchCandidateActionNeeded(attention, rejected),
  }
}
