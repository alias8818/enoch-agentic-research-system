import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it } from 'vitest'
import { CommandResultSummary } from './CommandResultSummary'

afterEach(() => {
  cleanup()
})

function assertJsonBlocksInRawDetails(container: HTMLElement) {
  container.querySelectorAll('.json-block').forEach((block) => {
    expect(block.closest('details.raw-details')).not.toBeNull()
  })
}

it('renders dispatch dry-run summary with decisive title and operator decision', () => {
  const payload = {
    ok: true,
    dry_run: true,
    action: 'dry_run_dispatch',
    reason: 'eligible queued project on gb10 lane',
    project_id: 'gb10-project',
    lane: 'gb10',
    machine_target: 'gb10',
    candidate: { project_id: 'gb10-project', project_name: 'Trace oracle', lane: 'gb10' },
  }

  const { container } = render(
    <CommandResultSummary result={{ payload, context: { commandFamily: 'dispatch' } }} />,
  )

  expect(screen.getByText('Dispatch dry-run passed')).toBeInTheDocument()
  expect(screen.getByText('Dry-run only')).toBeInTheDocument()
  expect(screen.getByText('Selected work')).toBeInTheDocument()
  expect(screen.getByText('gb10-project')).toBeInTheDocument()
  expect(screen.getByText('Operator decision')).toBeInTheDocument()
  expect(screen.getByText('Safe to dispatch')).toBeInTheDocument()
  expect(screen.queryByText('Backend action')).not.toBeInTheDocument()
  expect(screen.queryByText(/"dry_run": true/)).not.toBeVisible()

  assertJsonBlocksInRawDetails(container)

  fireEvent.click(screen.getByText('Raw JSON'))
  expect(screen.getByText(/"dry_run": true/)).toBeVisible()
})

it('keeps blocked command raw JSON inside details.raw-details', () => {
  const { container } = render(
    <CommandResultSummary
      result={{
        payload: { ok: false, reason: 'dispatch blocked by preflight', action: 'dispatch_blocked' },
        context: { commandFamily: 'dispatch' },
      }}
    />,
  )

  assertJsonBlocksInRawDetails(container)
  expect(screen.getByText('Dispatch blocked')).toBeInTheDocument()
  expect(screen.getByText('Do not dispatch')).toBeInTheDocument()
})
