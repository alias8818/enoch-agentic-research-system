import { shortId } from './format'
import {
  entityLink,
  firstValue,
  operatorNextStep,
  operatorStageLabel,
  pushLink,
  text,
  type EntityLink,
  type IntakeIdeaOperatorSummary,
} from './detailOperatorSummaryHelpers'

function intakeWhyNotQueued(blocked: string, queueStatus: string, ideaStatus: string): string {
  if (blocked !== '—') return blocked
  if (queueStatus === 'queued') return 'currently queued'
  if (ideaStatus === 'rejected') return 'idea rejected at admission'
  if (ideaStatus === 'candidate') return 'not admitted yet — promote or admit before queuing'
  if (ideaStatus === 'stale') return 'idea marked stale — refresh or re-admit'
  if (queueStatus === '—' || queueStatus.length === 0) return 'no queue row yet'
  return `queue status is ${queueStatus}`
}

function intakeContext(
  promoted: boolean,
  projectId: string,
  sourceKind: string,
  ideaStatus: string,
  queueStatus: string,
  machineTarget: string,
  paperStatus: string,
): string {
  if (promoted) {
    return `Promoted to project ${shortId(projectId)}; source ${sourceKind}; queue ${queueStatus}; lane ${machineTarget}.`
  }
  return `Source ${sourceKind}; admission ${ideaStatus}; queue ${queueStatus}; paper ${paperStatus}.`
}

function intakeNextStepMessage(
  attention: boolean,
  blocked: string,
  queueStatus: string,
  ideaStatus: string,
  nextHint: string,
): string {
  if (attention && blocked !== '—') return `Resolve blocker first: ${blocked}.`
  if (queueStatus === 'queued') return 'Open the matching project and run a dispatch dry-run before starting work.'
  if (queueStatus === 'active' || queueStatus === 'running') {
    return 'Open the current project/run detail and verify the lane is still moving.'
  }
  if (ideaStatus === 'rejected') return 'Do not queue this idea; review admission rejection and source lineage.'
  if (ideaStatus === 'candidate') return 'Admit or promote this candidate before expecting queue work.'
  if (nextHint !== '—') return `Follow backend hint: ${nextHint}.`
  return 'Review source lineage and admission state before creating more queue work.'
}

function intakeNeedsAttention(row: Record<string, unknown>, queueStatus: string, ideaStatus: string): boolean {
  return row.manual_review_required === true
    || row.operator_attention === true
    || queueStatus.includes('blocked')
    || queueStatus.includes('review')
    || ideaStatus === 'rejected'
}

function intakeActionNeeded(attention: boolean, blocked: string, ideaStatus: string): string | null {
  if (!attention) return null
  if (blocked !== '—') return blocked
  if (ideaStatus === 'rejected') return 'Idea rejected at admission.'
  return 'Admission or queue state needs operator review.'
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
  const attention = intakeNeedsAttention(row, queueStatus, ideaStatus)
  const whyNotQueued = intakeWhyNotQueued(blocked, queueStatus, ideaStatus)
  const entityLinks: EntityLink[] = []
  pushLink(entityLinks, entityLink('project', projectId !== '—' ? projectId : null, row.title))
  pushLink(entityLinks, entityLink('run', runId !== '—' ? runId : null))
  pushLink(entityLinks, entityLink('paper', paperId !== '—' ? paperId : null))

  return {
    state: operatorStageLabel(row, ideaStatus),
    context: intakeContext(promoted, projectId, sourceKind, ideaStatus, queueStatus, machineTarget, paperStatus),
    next: operatorNextStep(row, intakeNextStepMessage(attention, blocked, queueStatus, ideaStatus, nextHint)),
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
    actionNeeded: intakeActionNeeded(attention, blocked, ideaStatus),
  }
}
