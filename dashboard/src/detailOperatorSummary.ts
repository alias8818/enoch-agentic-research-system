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
    value: flags[key] ? 'present' : 'missing',
  }))
}

function triStateFlag(value: unknown): string {
  if (value === true) return 'yes'
  if (value === false) return 'no'
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
  const paperFinalization = text(firstValue(papers[0]?.finalization_status, papers[0]?.package_status, queue.related_finalization_status))
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

function runSummary(payload: Record<string, unknown>): DetailOperatorSummary {
  const run = record(payload.run)
  const project = record(payload.project)
  const papers = recordArray(payload.papers)
  const events = recordArray(payload.events)
  const stageSource = { ...run, ...payload }
  const state = text(firstValue(run.state, payload.state))
  const gate = text(firstValue(run.gate_state, payload.gate_state))
  const activity = text(firstValue(run.current_activity, payload.current_activity))
  const projectId = text(firstValue(run.project_id, project.project_id, payload.project_id))
  const projectName = text(firstValue(project.project_name, run.project_name))
  const paperId = text(firstValue(run.related_paper_id, papers[0]?.paper_id))
  const entityLinks: EntityLink[] = []
  pushLink(entityLinks, entityLink('project', projectId !== '—' ? projectId : null, projectName))
  pushLink(entityLinks, entityLink('paper', paperId !== '—' ? paperId : null, papers[0]?.paper_title || papers[0]?.title))
  const errorState = state.includes('error') || gate.includes('error')
  const artifactFlags = record(run.related_artifact_paths_present)

  return {
    state: operatorStageLabel(stageSource, state),
    context: `Gate ${gate}; activity ${activity}.`,
    next: operatorNextStep(stageSource, errorState
      ? 'Inspect recent events and worker logs before retrying dispatch.'
      : state === 'running' || state === 'dispatching'
        ? 'Watch activity and recent events; intervene only if the gate stops moving.'
        : 'Review related paper artifacts before queuing another action.'),
    entityLinks,
    sections: [
      {
        title: 'Project and worker context',
        answers: [
          { label: 'project', value: projectName !== '—' ? projectName : projectId },
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
        title: 'Timestamps',
        answers: [
          { label: 'started', value: text(firstValue(run.started_at, payload.started_at)) },
          { label: 'updated', value: text(firstValue(run.updated_at, payload.updated_at)) },
          { label: 'ended', value: text(firstValue(run.ended_at, payload.ended_at)) },
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

function paperSummary(payload: Record<string, unknown>): DetailOperatorSummary {
  const paper = record(payload.paper)
  const project = record(payload.project)
  const run = record(payload.run)
  const events = recordArray(payload.events)
  const stageSource = { ...paper, ...payload }
  const status = text(firstValue(paper.paper_status, paper.status, payload.status, payload.paper_status))
  const review = text(firstValue(paper.review_status, payload.review_status))
  const imported = paper.corpus_imported === true
  const flags = record(paper.artifact_paths_present)
  const projectId = text(firstValue(paper.project_id, project.project_id, payload.project_id))
  const runId = text(firstValue(paper.run_id, run.run_id, payload.run_id))
  const entityLinks: EntityLink[] = []
  pushLink(entityLinks, entityLink('project', projectId !== '—' ? projectId : null, project.project_name))
  pushLink(entityLinks, entityLink('run', runId !== '—' ? runId : null))

  return {
    state: operatorStageLabel(stageSource, status),
    context: imported
      ? 'Corpus import ledger shows this paper as imported.'
      : review !== '—'
        ? `Review ${review}; evidence paths ${flags.evidence_bundle ? 'present' : 'missing'}.`
        : `Evidence paths ${flags.evidence_bundle ? 'present' : 'missing'}; claim ledger ${flags.claim_ledger ? 'present' : 'missing'}.`,
    next: operatorNextStep(stageSource, imported
      ? 'No corpus import action is needed for this paper.'
      : status.includes('draft')
        ? 'Preview artifacts, then finalize only after checklist items look correct.'
        : 'Use paper commands only after deterministic gates mark this writable.'),
    entityLinks,
    sections: [
      {
        title: 'Paper pipeline status',
        answers: [
          { label: 'paper status', value: status },
          { label: 'review status', value: review },
          { label: 'corpus imported', value: text(imported) },
          { label: 'corpus import id', value: text(paper.corpus_import_id) },
        ],
      },
      {
        title: 'Draft and finalization',
        answers: [
          { label: 'paper type', value: text(paper.paper_type) },
          { label: 'finalization package', value: flags.finalization_package ? 'present' : 'missing' },
          { label: 'HF dataset synced', value: text(paper.hf_dataset_synced) },
        ],
      },
      {
        title: 'Publication checklist',
        answers: artifactChecklist(flags),
      },
    ],
    recentActivity: latestEventSummary(events),
    actionNeeded: review === 'rejected' ? 'Review rejected this paper; do not publish without a new run.' : null,
  }
}

function eventSummary(payload: Record<string, unknown>): DetailOperatorSummary {
  const eventType = text(payload.event_type)
  const entityId = text(firstValue(payload.entity_id, payload.project_id, payload.paper_id, payload.run_id))
  const entityType = text(firstValue(payload.entity_type, payload.project_id ? 'project' : payload.run_id ? 'run' : payload.paper_id ? 'paper' : 'entity'))
  const summary = text(firstValue(payload.summary, payload.message))
  const entityLinks: EntityLink[] = []
  if (payload.project_id) pushLink(entityLinks, entityLink('project', payload.project_id))
  if (payload.run_id) pushLink(entityLinks, entityLink('run', payload.run_id))
  if (payload.paper_id) pushLink(entityLinks, entityLink('paper', payload.paper_id))
  if (!entityLinks.length && entityId !== '—') {
    const kind = entityType.includes('run') ? 'run' : entityType.includes('paper') ? 'paper' : 'project'
    pushLink(entityLinks, entityLink(kind, entityId))
  }

  return {
    state: eventType,
    context: `${entityType} ${entityId}; created ${text(payload.created_at)}.`,
    next: entityLinks.length
      ? 'Open the related project, run, or paper if this event requires action.'
      : 'Use the payload only as supporting detail; do not treat it as a command.',
    entityLinks,
    sections: [
      {
        title: 'Event summary',
        answers: [
          { label: 'event type', value: eventType },
          { label: 'entity type', value: entityType },
          { label: 'entity id', value: entityId },
          { label: 'summary', value: summary },
          { label: 'created', value: text(payload.created_at) },
        ],
      },
    ],
    recentActivity: summary !== '—' ? summary : null,
    actionNeeded: null,
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
  const projectId = text(firstValue(row.project_id, row.idea_id))
  const sourceKind = text(row.source_kind)
  const blocked = text(firstValue(row.blocked_reason, row.last_error))
  const attention = row.manual_review_required === true || queueStatus.includes('blocked') || queueStatus.includes('review')
  const entityLinks: EntityLink[] = []
  pushLink(entityLinks, entityLink('project', projectId !== '—' ? projectId : null, row.title))

  return {
    state: ideaStatus,
    context: `Source ${sourceKind}; queue ${queueStatus}; paper ${paperStatus}.`,
    next: attention && blocked !== '—'
      ? `Resolve blocker first: ${blocked}.`
      : queueStatus === 'queued'
        ? 'Open the matching project and run a dispatch dry-run before starting work.'
        : queueStatus === 'active' || queueStatus === 'running'
          ? 'Open the current project/run detail and verify the lane is still moving.'
          : nextHint !== '—'
            ? `Follow backend hint: ${nextHint}.`
            : 'Review source lineage and admission state before creating more queue work.',
    entityLinks,
    sections: [
      {
        title: 'Source and lineage',
        answers: [
          { label: 'source kind', value: sourceKind },
          { label: 'idea status', value: ideaStatus },
          { label: 'updated', value: text(row.updated_at) },
        ],
      },
      {
        title: 'Admission and queue',
        answers: [
          { label: 'queue status', value: queueStatus },
          { label: 'paper status', value: paperStatus },
          { label: 'next action hint', value: nextHint },
          { label: 'why not queued', value: blocked !== '—' ? blocked : queueStatus === 'queued' ? 'currently queued' : 'see queue status above' },
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
    actionNeeded: attention ? (blocked !== '—' ? blocked : 'Admission or queue state needs operator review.') : null,
  }
}
