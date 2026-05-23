import { apiPost } from '../api/client'
import { feedDryRunAllowsLiveCycle } from '../feedDryRun'
import { dryRunCyclePayload, liveCyclePayload } from '../researchCyclePayloads'
import type { TopAction } from '../types'
import type { CommandPresentationContext } from '../commandResultPresentation'

const DRY_RUN_CHECK_LABELS: Record<DryRunActionKind, string> = {
  dispatch_next: 'Check dispatch',
  investigate_followup: 'Check follow-up',
  write_paper: 'Check draft',
  finalize_paper: 'Check finalization',
  feed_lanes: 'Feed idle lanes',
}

const LIVE_BUTTON_LABELS: Record<DryRunActionKind, string> = {
  dispatch_next: 'Dispatch work',
  investigate_followup: 'Launch follow-up',
  write_paper: 'Draft paper',
  finalize_paper: 'Finalize drafts',
  feed_lanes: 'Run feed cycle',
}

const STALE_LIVE_DISABLED_MESSAGES: Record<DryRunActionKind, string> = {
  dispatch_next: 'Dispatch work disabled: top action changed; run Check dispatch again.',
  investigate_followup: 'Launch follow-up disabled: top action changed; run Check follow-up again.',
  write_paper: 'Draft paper disabled: top action changed; run Check draft again.',
  finalize_paper: 'Finalize drafts disabled: top action changed; run Check finalization again.',
  feed_lanes: 'Run feed cycle disabled: top action changed; run Feed idle lanes again.',
}

const NOT_READY_LIVE_DISABLED_MESSAGES: Record<DryRunActionKind, string> = {
  dispatch_next: 'Dispatch work disabled: run Check dispatch first.',
  investigate_followup: 'Launch follow-up disabled: run Check follow-up first.',
  write_paper: 'Draft paper disabled: run Check draft first.',
  finalize_paper: 'Finalize drafts disabled: run Check finalization first.',
  feed_lanes: 'Run feed cycle disabled: run Feed idle lanes first.',
}

export function dryRunCheckLabel(action: TopAction): string {
  if (isDryRunActionKind(action.kind)) return DRY_RUN_CHECK_LABELS[action.kind]
  return 'Check dispatch'
}

export function livePrimaryButtonLabel(action: TopAction): string | null {
  if (!isDryRunActionKind(action.kind)) return null
  if (action.kind === 'dispatch_next') {
    return action.project_id ? 'Dispatch lane' : LIVE_BUTTON_LABELS.dispatch_next
  }
  return LIVE_BUTTON_LABELS[action.kind]
}

export function liveActionDisabledReason(
  action: TopAction,
  ready: boolean,
  staleReady: boolean,
  isPending: boolean,
): string {
  if (isPending) return `${action.action_label || 'Action'} disabled: command is running.`
  if (ready) return ''
  if (!isDryRunActionKind(action.kind)) return ''
  const messages = staleReady ? STALE_LIVE_DISABLED_MESSAGES : NOT_READY_LIVE_DISABLED_MESSAGES
  return messages[action.kind]
}

export function actionSignature(action: TopAction): string {
  return [
    action.kind,
    action.project_id || '',
    action.lane || '',
    action.title,
    action.summary || '',
    action.action_label || '',
    action.action_hash || '',
  ].join('|')
}

export type DryRunActionKind =
  | 'dispatch_next'
  | 'investigate_followup'
  | 'write_paper'
  | 'finalize_paper'
  | 'feed_lanes'

export type PrimaryActionReadiness = {
  dispatch: boolean
  followup: boolean
  draft: boolean
  finalize: boolean
  feed: boolean
  signature: string
}

export const EMPTY_PRIMARY_ACTION_READINESS: PrimaryActionReadiness = {
  dispatch: false,
  followup: false,
  draft: false,
  finalize: false,
  feed: false,
  signature: '',
}

type ConfirmOptions = {
  title: string
  message: string
  confirmLabel?: string
  tone?: 'info' | 'warn' | 'danger'
}

export class LiveActionCancelled extends Error {
  readonly cancelled = true
}

function idempotencyKey(prefix: string): string {
  return `${prefix}:dashboard-v2:${Date.now()}`
}

export function isDryRunActionKind(kind: string): kind is DryRunActionKind {
  return kind === 'dispatch_next'
    || kind === 'investigate_followup'
    || kind === 'write_paper'
    || kind === 'finalize_paper'
    || kind === 'feed_lanes'
}

export async function postDryRunRequest(action: TopAction): Promise<Record<string, unknown>> {
  switch (action.kind) {
    case 'investigate_followup':
      return apiPost<Record<string, unknown>>('/control/api/v1/followups/launch-next', {
        dry_run: true,
        requested_by: 'dashboard-v2',
        max_followup_depth: 4,
      })
    case 'write_paper':
      return apiPost<Record<string, unknown>>('/control/papers/draft-next', {
        dry_run: true,
        requested_by: 'dashboard-v2',
        force: true,
      })
    case 'finalize_paper':
      return apiPost<Record<string, unknown>>('/control/api/paper-reviews/rewrite-batch', {
        idempotency_key: idempotencyKey('primary-action-rewrite-batch'),
        requested_by: 'dashboard-v2',
        paper_status: 'publication_draft',
        dry_run: true,
        limit: 10,
        skip_rewritten: true,
      })
    case 'feed_lanes':
      return apiPost<Record<string, unknown>>('/control/api/research/run-cycle', dryRunCyclePayload)
    case 'dispatch_next':
      if (action.project_id) {
        return apiPost<Record<string, unknown>>('/control/dispatch-one', {
          project_id: action.project_id,
          dry_run: true,
          requested_by: 'dashboard-v2',
          force_preflight: true,
        })
      }
      return apiPost<Record<string, unknown>>('/control/dispatch-next', {
        dry_run: true,
        requested_by: 'dashboard-v2',
        force_preflight: true,
      })
    default:
      throw new Error(`Unsupported dry-run action: ${action.kind}`)
  }
}

export function dryRunIndicatesReady(action: TopAction, payload: Record<string, unknown>): boolean {
  switch (action.kind) {
    case 'dispatch_next':
      return String(payload.action || '').includes('dry_run')
    case 'investigate_followup':
      return payload.action === 'dry_run_followup'
    case 'write_paper':
      return payload.action === 'dry_run_draft'
    case 'finalize_paper':
      return payload.dry_run === true && Number(payload.processed || 0) > 0
    case 'feed_lanes':
      return feedDryRunAllowsLiveCycle(payload)
    default:
      return false
  }
}

export function readinessAfterDryRun(
  action: TopAction,
  ready: boolean,
  signature: string,
): PrimaryActionReadiness {
  const next = { ...EMPTY_PRIMARY_ACTION_READINESS, signature: ready ? signature : '' }
  switch (action.kind) {
    case 'dispatch_next':
      return { ...next, dispatch: ready }
    case 'investigate_followup':
      return { ...next, followup: ready }
    case 'write_paper':
      return { ...next, draft: ready }
    case 'finalize_paper':
      return { ...next, finalize: ready }
    case 'feed_lanes':
      return { ...next, feed: ready }
    default:
      return next
  }
}

function readinessFlagForKind(readiness: PrimaryActionReadiness, kind: string): boolean {
  switch (kind) {
    case 'dispatch_next':
      return readiness.dispatch
    case 'investigate_followup':
      return readiness.followup
    case 'write_paper':
      return readiness.draft
    case 'finalize_paper':
      return readiness.finalize
    case 'feed_lanes':
      return readiness.feed
    default:
      return true
  }
}

export function computeLiveReady(
  action: TopAction,
  readiness: PrimaryActionReadiness,
  currentSignature: string,
): boolean {
  if (!isDryRunActionKind(action.kind)) return true
  return readinessFlagForKind(readiness, action.kind) && readiness.signature === currentSignature
}

export function liveConfirmOptions(action: TopAction): ConfirmOptions | null {
  switch (action.kind) {
    case 'dispatch_next':
      return {
        title: action.project_id ? `Dispatch ${action.lane || 'lane'}?` : 'Dispatch top action?',
        message: action.project_id
          ? `This starts live dispatch for exactly ${action.project_id}. Use Check dispatch again if the lane candidate changed.`
          : 'This starts live dispatch for the current backend-selected queued work. Use Check dispatch again if lane or queue state may have changed.',
        confirmLabel: action.project_id ? 'Dispatch lane' : 'Dispatch work',
        tone: 'warn',
      }
    case 'investigate_followup':
      return {
        title: 'Launch follow-up investigation?',
        message: 'This queues investigation work for the backend-selected follow-up. It does not dispatch work, write papers, or finalize publications. Use Check follow-up again if candidate state may have changed.',
        confirmLabel: 'Launch follow-up',
        tone: 'warn',
      }
    case 'write_paper':
      return {
        title: 'Draft next paper?',
        message: 'This writes draft artifacts for the backend-selected paper-ready candidate. Use Check draft again if the candidate may have changed.',
        confirmLabel: 'Draft paper',
        tone: 'warn',
      }
    case 'finalize_paper':
      return {
        title: 'Finalize publication drafts?',
        message: 'This rewrites publication draft packages for the backend-selected batch. Use Check finalization again if the queue may have changed.',
        confirmLabel: 'Finalize drafts',
        tone: 'warn',
      }
    case 'feed_lanes':
      return {
        title: 'Run one bounded feed cycle?',
        message: 'This can spend one provider request and promote candidates. It will not dispatch, wait for completion, write papers, or finalize publications.',
        confirmLabel: 'Run feed cycle',
        tone: 'warn',
      }
    default:
      return null
  }
}

export async function postLiveRequest(action: TopAction): Promise<Record<string, unknown>> {
  switch (action.kind) {
    case 'investigate_followup':
      return apiPost<Record<string, unknown>>('/control/api/v1/followups/launch-next', {
        dry_run: false,
        requested_by: 'dashboard-v2',
        max_followup_depth: 4,
      })
    case 'write_paper':
      return apiPost<Record<string, unknown>>('/control/papers/draft-next', {
        dry_run: false,
        requested_by: 'dashboard-v2',
        force: true,
      })
    case 'finalize_paper':
      return apiPost<Record<string, unknown>>('/control/api/paper-reviews/rewrite-batch', {
        idempotency_key: idempotencyKey('primary-action-rewrite-batch-live'),
        requested_by: 'dashboard-v2',
        paper_status: 'publication_draft',
        dry_run: false,
        force: true,
        limit: 10,
        skip_rewritten: true,
      })
    case 'feed_lanes':
      return apiPost<Record<string, unknown>>('/control/api/research/run-cycle', liveCyclePayload)
    case 'dispatch_next':
      if (action.project_id) {
        return apiPost<Record<string, unknown>>('/control/dispatch-one', {
          project_id: action.project_id,
          dry_run: false,
          requested_by: 'dashboard-v2',
          force_preflight: true,
        })
      }
      return apiPost<Record<string, unknown>>('/control/dispatch-next', {
        dry_run: false,
        requested_by: 'dashboard-v2',
        force_preflight: true,
      })
    default:
      throw new Error(`Unsupported live action: ${action.kind}`)
  }
}

export function commandFamilyForLive(action: TopAction): CommandPresentationContext['commandFamily'] {
  if (action.kind === 'feed_lanes') return 'research'
  if (action.kind === 'dispatch_next') return 'dispatch'
  if (action.kind === 'investigate_followup') return 'followup'
  if (action.kind === 'write_paper') return 'paper'
  if (action.kind === 'finalize_paper') return 'finalize'
  return 'command'
}

export async function executeConfirmedLiveAction(
  action: TopAction,
  confirm: (options: ConfirmOptions) => Promise<boolean>,
): Promise<Record<string, unknown>> {
  const options = liveConfirmOptions(action)
  if (!options) throw new Error(`Unsupported live action: ${action.kind}`)
  const confirmed = await confirm(options)
  if (!confirmed) throw new LiveActionCancelled()
  return postLiveRequest(action)
}
