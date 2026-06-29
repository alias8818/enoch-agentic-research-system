import {
  artifactChecklist,
  artifactFlagPresent,
  entityLink,
  firstValue,
  latestEventSummary,
  missingPublicationArtifacts,
  operatorNextStep,
  operatorStageLabel,
  pushLink,
  queueRecord,
  record,
  recordArray,
  text,
  type DetailOperatorSummary,
  type EntityLink,
  type OperatorSection,
} from './detailOperatorSummaryHelpers'

type PaperSummaryInput = {
  stageSource: Record<string, unknown>
  title: string
  status: string
  review: string
  imported: boolean
  flags: Record<string, unknown>
  projectId: string
  projectName: string
  runId: string
  runState: string
  machineTarget: string
  operatorExplanation: string
  paper: Record<string, unknown>
  events: Record<string, unknown>[]
}

function artifactPresenceLabel(flags: Record<string, unknown>, key: string): string {
  return artifactFlagPresent(flags, key) ? 'present' : 'missing'
}

function paperPublicationBlocker(
  review: string,
  operatorExplanation: string,
  missingArtifacts: string[],
  imported: boolean,
): string {
  const blockers: ReadonlyArray<readonly [boolean, string]> = [
    [review === 'rejected', 'Publication gate rejected this paper.'],
    [operatorExplanation !== '—', operatorExplanation],
    [missingArtifacts.length > 0, `Missing: ${missingArtifacts.join(', ')}.`],
    [imported, 'Corpus import complete; no publication blockers.'],
  ]
  return blockers.find(([matches]) => matches)?.[1] ?? 'Publication artifacts ready for corpus import.'
}

function paperSummaryContext(
  imported: boolean,
  missingArtifacts: string[],
  review: string,
  flags: Record<string, unknown>,
): string {
  if (imported) return 'Corpus import ledger shows this paper as imported.'
  if (missingArtifacts.length > 0) {
    return `Publication blocked: missing ${missingArtifacts.join(', ')}.`
  }
  if (review !== '—') return `Publication gate ${review}; all publication artifacts present.`
  const evidence = artifactPresenceLabel(flags, 'evidence_bundle')
  const claimLedger = artifactPresenceLabel(flags, 'claim_ledger')
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
    return operatorNextStep(stageSource, 'Do not publish; start a new run or resolve the failed publication gate first.')
  }
  if (needsFinalization || missingArtifacts.length > 0) {
    return operatorNextStep(stageSource, 'Preview generated artifacts, then finalize only after checklist gates pass.')
  }
  return operatorNextStep(stageSource, 'Run corpus import when the publication checklist is complete.')
}

function paperSummaryActionNeeded(
  reviewRejected: boolean,
  missingArtifacts: string[],
): string | null {
  if (reviewRejected) return 'Publication gate rejected this paper; do not publish without a new run.'
  if (missingArtifacts.length > 0) {
    return `Complete missing artifacts before publication: ${missingArtifacts.join(', ')}.`
  }
  return null
}

function readPaperSummaryInput(payload: Record<string, unknown>): PaperSummaryInput {
  const paper = record(payload.paper)
  const project = record(payload.project)
  const run = record(payload.run)
  const queue = queueRecord(payload)
  const events = recordArray(payload.events)
  const stageSource = { ...paper, ...payload }
  return {
    stageSource,
    title: text(firstValue(paper.paper_title, paper.title, payload.title)),
    status: text(firstValue(paper.paper_status, paper.status, payload.status, payload.paper_status)),
    review: text(firstValue(paper.review_status, payload.review_status)),
    imported: paper.corpus_imported === true,
    flags: record(paper.artifact_paths_present),
    projectId: text(firstValue(paper.project_id, project.project_id, payload.project_id)),
    projectName: text(firstValue(project.project_name, paper.project_name)),
    runId: text(firstValue(paper.run_id, run.run_id, payload.run_id)),
    runState: text(firstValue(run.state, payload.run_state)),
    machineTarget: text(firstValue(queue.machine_target, payload.machine_target)),
    operatorExplanation: text(firstValue(paper.operator_explanation, payload.operator_explanation)),
    paper,
    events,
  }
}

function paperSummaryEntityLinks(projectId: string, projectName: string, runId: string): EntityLink[] {
  const entityLinks: EntityLink[] = []
  pushLink(entityLinks, entityLink('project', projectId === '—' ? null : projectId, projectName))
  pushLink(entityLinks, entityLink('run', runId === '—' ? null : runId))
  return entityLinks
}

function paperSummarySections(
  input: PaperSummaryInput,
  publicationBlocker: string,
): OperatorSection[] {
  const projectLabel = input.projectName === '—' ? input.projectId : input.projectName
  return [
    {
      title: 'What is this paper?',
      answers: [
        { label: 'title', value: input.title },
        { label: 'paper status', value: input.status },
        { label: 'paper type', value: text(input.paper.paper_type) },
        { label: 'publication gate status', value: input.review },
      ],
    },
    {
      title: 'Related project and run',
      answers: [
        { label: 'project', value: projectLabel },
        { label: 'run state', value: input.runState },
        { label: 'machine target', value: input.machineTarget },
      ],
    },
    {
      title: 'Publication checklist',
      answers: artifactChecklist(input.flags),
    },
    {
      title: 'Draft and import status',
      answers: [
        { label: 'corpus imported', value: text(input.imported) },
        { label: 'corpus import id', value: text(input.paper.corpus_import_id) },
        { label: 'HF dataset synced', value: text(input.paper.hf_dataset_synced) },
      ],
    },
    {
      title: 'What blocks publication?',
      answers: [
        { label: 'missing artifacts', value: publicationBlocker },
        { label: 'operator explanation', value: input.operatorExplanation },
      ],
    },
  ]
}

export function paperSummary(payload: Record<string, unknown>): DetailOperatorSummary {
  const input = readPaperSummaryInput(payload)
  const missingArtifacts = missingPublicationArtifacts(input.flags)
  const publicationBlocker = paperPublicationBlocker(
    input.review,
    input.operatorExplanation,
    missingArtifacts,
    input.imported,
  )
  const reviewRejected = input.review === 'rejected'
  const needsFinalization = missingArtifacts.includes('finalization package')

  return {
    state: operatorStageLabel(input.stageSource, input.status),
    context: paperSummaryContext(input.imported, missingArtifacts, input.review, input.flags),
    next: paperSummaryNextStep(
      input.stageSource,
      input.imported,
      reviewRejected,
      needsFinalization,
      missingArtifacts,
    ),
    entityLinks: paperSummaryEntityLinks(input.projectId, input.projectName, input.runId),
    sections: paperSummarySections(input, publicationBlocker),
    recentActivity: latestEventSummary(input.events),
    actionNeeded: paperSummaryActionNeeded(reviewRejected, missingArtifacts),
  }
}
