import { expect, it } from 'vitest'
import { deriveCommandPresentation } from './commandResultPresentation'

it('maps dispatch dry-run success to decisive title and safe dispatch decision', () => {
  const presentation = deriveCommandPresentation({
    action: 'dry_run_dispatch',
    reason: 'dry-run dispatch selected candidate',
    candidate: { project_id: 'project-1', machine_target: 'gb10' },
  }, { commandFamily: 'dispatch' })

  expect(presentation.title).toBe('Dispatch dry-run passed')
  expect(presentation.severity).toBe('dry_run')
  expect(presentation.decision).toBe('Safe to dispatch')
})

it('maps ok false to failed severity before blocked action names are considered', () => {
  const presentation = deriveCommandPresentation({
    ok: false,
    action: 'dispatch_blocked',
    reason: 'lane busy',
  }, { commandFamily: 'dispatch' })

  expect(presentation.title).toBe('Dispatch blocked')
  expect(presentation.severity).toBe('failed')
  expect(presentation.decision).toBe('Do not dispatch')
})

it('maps blocked action names to blocked severity when ok is not false', () => {
  const presentation = deriveCommandPresentation({
    action: 'dry_run_draft_blocked',
    reason: 'no eligible paper-ready candidate',
  }, { commandFamily: 'paper' })

  expect(presentation.severity).toBe('blocked')
})

it('maps paper finalize dry-run success', () => {
  const presentation = deriveCommandPresentation({
    dry_run: true,
    processed: 2,
    reason: 'would finalize 2 publication drafts',
  }, { commandFamily: 'finalize' })

  expect(presentation.title).toBe('Paper finalize dry-run passed')
  expect(presentation.severity).toBe('dry_run')
})

it('maps paper action blocked', () => {
  const presentation = deriveCommandPresentation({
    action: 'dry_run_draft_blocked',
    reason: 'no eligible paper-ready candidate',
  }, { commandFamily: 'paper' })

  expect(presentation.title).toBe('Paper action blocked')
  expect(presentation.severity).toBe('blocked')
  expect(presentation.decision).toBe('Fix blocker first')
})

it('maps stale context to refresh decision', () => {
  const presentation = deriveCommandPresentation({
    action: 'dry_run_dispatch',
    reason: 'still valid but stale UI',
  }, { commandFamily: 'dispatch', stale: true })

  expect(presentation.title).toContain('stale')
  expect(presentation.severity).toBe('stale')
  expect(presentation.decision).toBe('Refresh and check again')
})

it('maps live dispatch success', () => {
  const presentation = deriveCommandPresentation({
    action: 'dispatch_started',
    reason: 'live dispatch accepted selected candidate',
  }, { commandFamily: 'dispatch' })

  expect(presentation.title).toBe('Dispatch completed')
  expect(presentation.severity).toBe('passed')
})

it('maps blocked research cycle to family-specific title', () => {
  const presentation = deriveCommandPresentation({
    ok: false,
    action: 'research_cycle_blocked',
    reason: 'no eligible candidate',
  }, { commandFamily: 'research' })

  expect(presentation.title).toBe('Research action blocked')
  expect(presentation.severity).toBe('failed')
})
