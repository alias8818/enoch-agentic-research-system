import type { ReactNode } from 'react'
import { dashboardV2Href } from '../routes'
import type { AutomationReadiness, OverviewResponse, TopAction } from '../types'
import { CommandResultSummary } from './CommandResultSummary'
import {
  dryRunCheckLabel,
  isDryRunActionKind,
  liveActionDisabledReason,
  livePrimaryButtonLabel,
} from './primaryActionCommands'
import { usePrimaryActionController } from './usePrimaryActionController'

export { actionSignature } from './primaryActionCommands'

type CommandResult = {
  payload: Record<string, unknown>
  context?: { stale?: boolean; commandFamily?: string }
}

type PrimaryActionCtaProps = {
  action: TopAction
  isPending: boolean
  liveReady: boolean
  liveDisabledReason: string
  controlHoldReason?: string
  onCheckReadiness?: () => void
  onDryRun: () => void | Promise<void>
  onLive: () => void | Promise<void>
}

type PrimaryActionViewProps = PrimaryActionCtaProps & {
  result: CommandResult | null
  staleReady: boolean
  dialog: ReactNode
}

function ResultCard({ result, stale }: Readonly<{ result: CommandResult | null; stale?: boolean }>) {
  if (!result) return null
  return (
    <CommandResultSummary
      className="primary-action-result"
      result={{ payload: result.payload, context: { ...result.context, stale: stale || result.context?.stale } }}
    />
  )
}

function PrimaryActionIdle() {
  return (
    <section className="primary-action primary-action--idle" aria-label="Primary action">
      <div className="primary-action-copy">
        <p className="eyebrow">Primary action</p>
        <h2>Nothing to click right now</h2>
        <p>No decisive operator action is available right now.</p>
      </div>
    </section>
  )
}

function CheckReadinessButton({
  action,
  isPending,
  onCheckReadiness,
}: Readonly<{
  action: TopAction
  isPending: boolean
  onCheckReadiness?: () => void
}>) {
  return (
    <button className="primary-button primary-action-cta" type="button" disabled={isPending} onClick={() => onCheckReadiness?.()}>
      {action.action_label || 'Check readiness'}
    </button>
  )
}

function PrimaryActionDryRunControls({
  action,
  isPending,
  liveReady,
  liveDisabledReason,
  controlHoldReason,
  onDryRun,
  onLive,
}: Readonly<Pick<PrimaryActionCtaProps, 'action' | 'isPending' | 'liveReady' | 'liveDisabledReason' | 'controlHoldReason' | 'onDryRun' | 'onLive'>>) {
  const liveLabel = livePrimaryButtonLabel(action)
  const held = Boolean(controlHoldReason)
  const disabledReason = controlHoldReason || liveDisabledReason
  return (
    <div className="primary-action-buttons">
      <button className="secondary-button primary-action-cta" type="button" disabled={isPending || held} onClick={onDryRun}>
        {dryRunCheckLabel(action)}
      </button>
      {liveLabel && (
        <button className="primary-button primary-action-cta" type="button" disabled={isPending || held || !liveReady} onClick={onLive}>
          {liveLabel}
        </button>
      )}
      {disabledReason && <p className="primary-action-disabled-reason">{disabledReason}</p>}
    </div>
  )
}

function PrimaryActionOpenLink({ action }: Readonly<{ action: TopAction }>) {
  return (
    <a className="primary-button primary-action-cta" href={dashboardV2Href(action.action_hash || '#overview')}>
      {action.action_label || 'Open'}
    </a>
  )
}

function PrimaryActionCta(props: Readonly<PrimaryActionCtaProps>) {
  const { action, isPending, liveReady, liveDisabledReason, onCheckReadiness, onDryRun, onLive } = props
  if (action.kind === 'check_readiness') {
    return <CheckReadinessButton action={action} isPending={isPending} onCheckReadiness={onCheckReadiness} />
  }
  if (isDryRunActionKind(action.kind)) {
    return (
      <PrimaryActionDryRunControls
        action={action}
        isPending={isPending}
        liveReady={liveReady}
        liveDisabledReason={liveDisabledReason}
        controlHoldReason={props.controlHoldReason}
        onDryRun={onDryRun}
        onLive={onLive}
      />
    )
  }
  return <PrimaryActionOpenLink action={action} />
}

function PrimaryActionView(props: Readonly<PrimaryActionViewProps>) {
  const { action, result, staleReady, dialog } = props
  return (
    <section className="primary-action" aria-label="Primary action">
      <div className="primary-action-copy">
        <p className="eyebrow">Primary action</p>
        <h2>{action.title}</h2>
        <p>{action.summary}</p>
      </div>
      <PrimaryActionCta {...props} />
      <ResultCard result={result} stale={staleReady} />
      {dialog}
    </section>
  )
}

export function resolvePrimaryAction(
  overview: OverviewResponse,
  readiness?: AutomationReadiness,
): TopAction | undefined {
  if (!readiness) {
    return {
      kind: 'check_readiness',
      tone: 'warn',
      title: 'Check readiness first',
      summary: 'Run the long-haul readiness check before leaving automation unattended.',
      action_label: 'Check readiness',
    }
  }
  return overview.primary_operator_action || undefined
}

export function PrimaryAction({
  action,
  onRefresh,
  onCheckReadiness,
  controlHoldReason,
}: Readonly<{
  action?: TopAction
  onRefresh?: () => void
  onCheckReadiness?: () => void
  controlHoldReason?: string
}>) {
  const controller = usePrimaryActionController(action, onRefresh)
  if (!action) return <PrimaryActionIdle />

  const liveDisabledReason = isDryRunActionKind(action.kind)
    ? liveActionDisabledReason(action, controller.liveReady, controller.staleReady, controller.isPending)
    : ''

  return (
    <PrimaryActionView
      action={action}
      isPending={controller.isPending}
      liveReady={controller.liveReady}
      liveDisabledReason={liveDisabledReason}
      controlHoldReason={controlHoldReason}
      result={controller.result}
      staleReady={controller.staleReady}
      dialog={controller.dialog}
      onCheckReadiness={onCheckReadiness}
      onDryRun={controller.runDryRun}
      onLive={controller.runLive}
    />
  )
}
