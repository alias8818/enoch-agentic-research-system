export type ResourceEndpoint =
  | 'queue'
  | 'projects'
  | 'runs'
  | 'papers'
  | 'corpus'
  | 'events'
  | 'intake'
  | 'observability-health'
  | 'observability-memory'

export type EmptyStateKind = 'idle' | 'filtered' | 'blocked'

export type ComposedEmptyStateCopy = {
  title: string
  body: string
  kind: EmptyStateKind
  hint?: string
}

export type ResourceErrorCopy = {
  eyebrow: string
  title: string
  summary: string
  dispatchImpact: string
  nextSteps: string[]
  logCommand: string
}

export type ListFilterContext = {
  search?: string
  status?: string
  defaultStatus?: string
}

import { displayText } from './displayText'

const CONTROL_PLANE_LOG = 'journalctl -u enoch-control-plane.service -n 160 --no-pager'

function errorMessage(error: unknown): string {
  if (error instanceof Error) return error.message
  return displayText(error, 'Unknown error')
}

function hasActiveFilters(context: ListFilterContext): boolean {
  return Boolean(context.search?.trim())
}

function filteredEmpty(title: string, body: string, hint?: string): ComposedEmptyStateCopy {
  return { kind: 'filtered', title, body, hint }
}

function idleEmpty(title: string, body: string, hint?: string): ComposedEmptyStateCopy {
  return { kind: 'idle', title, body, hint }
}

function blockedEmpty(title: string, body: string, hint?: string): ComposedEmptyStateCopy {
  return { kind: 'blocked', title, body, hint }
}

export function deriveResourceErrorCopy(endpoint: ResourceEndpoint, error: unknown): ResourceErrorCopy {
  const detail = errorMessage(error)
  const base = {
    nextSteps: [
      'Refresh once to rule out a transient read-model failure.',
      `If the error persists, inspect control-plane logs for the bounded endpoint response (${detail}).`,
    ],
    logCommand: CONTROL_PLANE_LOG,
  }

  if (endpoint === 'queue') {
    return {
      eyebrow: 'Queue read model',
      title: 'Queue could not load',
      summary: 'The bounded queue endpoint failed before any rows could render.',
      dispatchImpact: 'Selected-row dispatch checks and live dispatch from this page are unavailable until the queue loads.',
      ...base,
    }
  }

  if (endpoint === 'projects') {
    return {
      eyebrow: 'Projects read model',
      title: 'Projects could not load',
      summary: 'Project discovery failed before the table could render.',
      dispatchImpact: 'Project search is unavailable here; worker-lane dispatch may still work from the command center when lane status is healthy.',
      ...base,
    }
  }

  if (endpoint === 'runs') {
    return {
      eyebrow: 'Runs read model',
      title: 'Runs could not load',
      summary: 'The runs list failed before any run rows could render.',
      dispatchImpact: 'Run visibility only — dispatch and feed controls are not blocked by this read-model failure.',
      ...base,
    }
  }

  if (endpoint === 'papers' || endpoint === 'corpus') {
    return {
      eyebrow: endpoint === 'corpus' ? 'Paper corpus import read model' : 'Papers read model',
      title: endpoint === 'corpus' ? 'Paper corpus import rows could not load' : 'Papers could not load',
      summary: endpoint === 'corpus'
        ? 'Publication-ready draft rows failed before the corpus import table could render.'
        : 'The papers list failed before any paper rows could render.',
      dispatchImpact: 'Paper actions on this page are unavailable; research and dispatch lanes are unaffected.',
      ...base,
    }
  }

  if (endpoint === 'events') {
    return {
      eyebrow: 'Events read model',
      title: 'Events could not load',
      summary: 'The bounded events endpoint returned an error before any event rows could render.',
      dispatchImpact: 'Event history is unavailable here; dispatch and lane controls are unaffected.',
      ...base,
    }
  }

  if (endpoint === 'intake') {
    return {
      eyebrow: 'Idea intake read model',
      title: 'Intake workbench could not load',
      summary: 'The bounded intake projection failed before idea rows could render.',
      dispatchImpact: 'Intake review is unavailable; admitted ideas may still queue through backend automation.',
      ...base,
    }
  }

  if (endpoint === 'observability-health') {
    return {
      eyebrow: 'Observability health',
      title: 'Route observability sample could not load',
      summary: 'The health read model failed before route logging status could render.',
      dispatchImpact: 'Debug visibility only — dispatch, research, and paper lanes are unaffected.',
      ...base,
    }
  }

  return {
    eyebrow: 'Observability memory',
    title: 'Memory sample could not load',
    summary: 'The memory read model failed before RSS pressure could render.',
    dispatchImpact: 'Debug visibility only — dispatch, research, and paper lanes are unaffected.',
    ...base,
  }
}

export function deriveQueueEmpty(context: ListFilterContext): ComposedEmptyStateCopy {
  if (hasActiveFilters(context)) {
    return filteredEmpty(
      'No queue rows match these filters',
      'Try clearing search or widening the status filter to see queued, active, or blocked work.',
      'Dispatch is unaffected — this page simply has no rows for the current filter.',
    )
  }
  if (context.status === 'blocked') {
    return idleEmpty(
      'No blocked queue rows',
      'Nothing is currently blocked in the queue slice. That usually means dispatch gates are clear.',
    )
  }
  if (context.status === 'queued') {
    return idleEmpty(
      'No queued work right now',
      'The queue slice is empty by design. Worker lanes may still be idle or waiting for new candidates.',
      'Use the command center feed controls if lanes are open but no candidates are queued.',
    )
  }
  return idleEmpty(
    'Queue is empty',
    'No projects match the current queue view. The system may be idle or work may already be active elsewhere.',
  )
}

export function deriveProjectsEmpty(context: ListFilterContext): ComposedEmptyStateCopy {
  if (hasActiveFilters(context)) {
    return filteredEmpty(
      'No projects match these filters',
      'Clear search or choose a broader project state to rediscover work.',
    )
  }
  return idleEmpty(
    'No projects in this slice',
    'The project index is empty for the current view. That can mean intake has not promoted new work yet.',
    'Check Idea intake or the command center if you expected active projects.',
  )
}

export function deriveRunsEmpty(context: ListFilterContext): ComposedEmptyStateCopy {
  if (hasActiveFilters(context)) {
    return filteredEmpty(
      'No runs match these filters',
      'Clear search or choose a broader run state to inspect activity.',
    )
  }
  if (context.status === 'dispatch_error') {
    return blockedEmpty(
      'No runs in dispatch error',
      'Nothing is currently stuck in dispatch_error. That is usually healthy unless you expected a failed dispatch.',
    )
  }
  if (context.status === 'running' || context.status === 'dispatching') {
    return idleEmpty(
      'No active runs',
      'No runs are executing in this slice. Worker lanes may be idle or waiting for dispatch.',
    )
  }
  return idleEmpty(
    'No runs in this slice',
    'The runs list is empty for the current view. Work may not have started yet or may have already completed.',
  )
}

export function derivePapersEmpty(context: ListFilterContext): ComposedEmptyStateCopy {
  if (hasActiveFilters(context)) {
    return filteredEmpty(
      'No papers match these filters',
      'Clear search or choose a broader paper status to find draft or review work.',
    )
  }
  return idleEmpty(
    'No paper actions pending',
    'Nothing in the papers slice needs operator attention right now.',
    'Paper actions and paper corpus import may still have work on other routes.',
  )
}

export function deriveCorpusEmpty(context: ListFilterContext): ComposedEmptyStateCopy {
  if (hasActiveFilters(context)) {
    return filteredEmpty(
      'No corpus import candidates match these filters',
      'Clear search or widen the paper status filter to find missing import rows.',
    )
  }
  return idleEmpty(
    'No missing corpus imports in this slice',
    'Publication-ready drafts in this view already have import coverage or nothing is waiting here.',
    'Check the overview counts above — a zero missing count usually means the ledger is caught up.',
  )
}

export function deriveEventsEmpty(context: ListFilterContext): ComposedEmptyStateCopy {
  if (hasActiveFilters(context)) {
    return filteredEmpty(
      'No events match these filters',
      'Clear search or choose a broader event type to inspect recent control-plane activity.',
    )
  }
  return idleEmpty(
    'No recent events returned',
    'The bounded events feed is quiet. That can mean the control plane is idle or event retention is empty.',
  )
}

export function deriveIntakeEmpty(): ComposedEmptyStateCopy {
  return idleEmpty(
    'No admitted ideas in the intake projection',
    'The bounded intake workbench returned no queued ideas. Intake may be caught up or waiting on the next sync.',
    'Review Latest intake sync above — a stale or failed sync can explain an empty projection.',
  )
}

export function deriveSimpleTableEmpty(label: string): ComposedEmptyStateCopy {
  return idleEmpty(`No ${label} returned`, `The backend returned an empty ${label} slice for this panel.`)
}
