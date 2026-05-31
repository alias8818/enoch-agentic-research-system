import { expect, it } from 'vitest'
import {
  eventListRowSchema,
  OPERATOR_LIST_FIELD_KEYS,
  listRowSchemaKeys,
  overviewResponseSchema,
  paperListRowSchema,
  parseAutomationDetail,
  parseAutomationListResponse,
  parseAutomationReadiness,
  parseEventListResponse,
  parseIntakeIdeasResponse,
  parseOverviewResponse,
  parsePaperListResponse,
  parseProjectListResponse,
  parseQueueListResponse,
  parseRunListResponse,
  parseStatusResponse,
  projectListRowSchema,
  queueListRowSchema,
  runListRowSchema,
  statusResponseSchema,
} from './readModelSchemas'
import {
  eventListFixture,
  intakeIdeasFixture,
  overviewFixture,
  paperListFixture,
  projectListFixture,
  queueListFixture,
  runListFixture,
  statusFixture,
} from './readModelFixtures'

it('parses bounded queue list responses and rejects malformed rows', () => {
  const parsed = parseQueueListResponse(queueListFixture)
  expect(parsed.rows?.[0]?.project_name).toBe('Oracle lane')
  expect(() => parseQueueListResponse({ rows: 'bad' })).toThrow()
})

it('parses project, run, paper, event, and automation list responses', () => {
  expect(parseProjectListResponse(projectListFixture).rows?.[0]?.project_id).toBe('project-1')
  expect(parseRunListResponse(runListFixture).rows?.[0]?.state).toBe('running')
  expect(parsePaperListResponse(paperListFixture).rows?.[0]?.paper_status).toBe('publication_draft')
  expect(parseEventListResponse(eventListFixture).rows?.[0]?.event_type).toBe('worker_callback.received')
  expect(parseAutomationListResponse({ rows: [{ paper_id: 'paper-1', rank_score: 91 }] }).rows?.[0]?.rank_score).toBe(91)
})

it('parses intake ideas workbench responses and rejects malformed projections', () => {
  const parsed = parseIntakeIdeasResponse(intakeIdeasFixture)
  expect(parsed.queued_projection?.[0]?.operator_stage).toBe('ready_queue')
  expect(parsed.queued_projection?.[0]?.operator_stage_label).toBe('Queued for lane')
  expect(() => parseIntakeIdeasResponse({ queued_projection: 'bad' })).toThrow()
})

it('parses command-center overview, status, and readiness payloads', () => {
  const overview = parseOverviewResponse(overviewFixture)
  expect(overview.movement_diagnosis?.status).toBe('actionable')
  expect(overview.primary_operator_action?.kind).toBe('dispatch_next')
  expect(parseOverviewResponse({
    research_signal_quality: {
      status: 'warnings',
      weak_evidence_count: 1,
      malformed_provider_response_count: 16,
      useful_adjacent_followup_delta: -4,
      refresh_reason: 'missing database URL',
      signal_verdict: 'stale',
      signal_reasons: [{ code: 'quality_report_stale', severity: 'blocked' }],
    },
  }).research_signal_quality).toMatchObject({
    malformed_provider_response_count: 16,
    refresh_reason: 'missing database URL',
    signal_verdict: 'stale',
    signal_reasons: [{ code: 'quality_report_stale', severity: 'blocked' }],
  })
  expect(parseStatusResponse(statusFixture).worker_lanes?.[0]?.machine_target).toBe('cpu-proxmox-1')
  expect(parseAutomationReadiness({ ok: true, label: 'Long-haul mode: READY' }).label).toBe('Long-haul mode: READY')
})


it('accepts explicit null lane on global primary operator blockers', () => {
  const parsed = parseOverviewResponse({
    ok: true,
    primary_operator_action: {
      kind: 'open_blocker',
      tone: 'warn',
      title: 'Maintenance mode is on',
      summary: 'Automation is intentionally held until maintenance mode is cleared.',
      action_label: 'Resume queue',
      action_hash: '#overview',
      blocker_kind: 'maintenance_mode',
      lane: null,
    },
    movement_diagnosis: {
      status: 'blocked',
      primary_reason: 'maintenance_mode',
      blockers: [{
        kind: 'maintenance_mode',
        lane: null,
        tone: 'warn',
        title: 'Maintenance mode is on',
        summary: 'Automation is intentionally held until maintenance mode is cleared.',
      }],
    },
  })

  expect(parsed.primary_operator_action?.lane).toBeNull()
  expect(parsed.movement_diagnosis?.blockers[0]?.lane).toBeNull()
})

it('parses automation detail payloads', () => {
  const parsed = parseAutomationDetail({
    item: { paper_id: 'paper-1', review_status: 'triage_ready' },
    checklist: { items: [{ item_id: 'evidence', status: 'pending' }] },
  })
  expect(parsed.item?.paper_id).toBe('paper-1')
  expect(parsed.checklist?.items?.[0]?.item_id).toBe('evidence')
})

it('keeps operator table fields in list row schemas', () => {
  const schemaByKind = {
    queue: queueListRowSchema,
    projects: projectListRowSchema,
    runs: runListRowSchema,
    papers: paperListRowSchema,
    events: eventListRowSchema,
  } as const
  for (const [kind, requiredKeys] of Object.entries(OPERATOR_LIST_FIELD_KEYS) as Array<[keyof typeof schemaByKind, readonly string[]]>) {
    const keys = listRowSchemaKeys(schemaByKind[kind])
    for (const key of requiredKeys) expect(keys, `${kind} schema must validate ${key}`).toContain(key)
  }
})

it('accepts representative fixtures through strict row schemas', () => {
  expect(overviewResponseSchema.parse(overviewFixture).ok).toBe(true)
  expect(statusResponseSchema.parse(statusFixture).worker_lanes?.length).toBe(1)
  expect(paperListRowSchema.parse(paperListFixture.rows[0]).title).toBe('Draft on oracle lane')
})


it('accepts numeric and null corpus import ids on paper rows', () => {
  const parsed = parsePaperListResponse({
    rows: [
      { paper_id: 'paper-imported', title: 'Imported paper', paper_status: 'published', corpus_import_id: 42 },
      { paper_id: 'paper-draft', title: 'Draft paper', review_status: null, corpus_import_id: null },
    ],
  })

  expect(parsed.rows?.[0]?.corpus_import_id).toBe(42)
  expect(parsed.rows?.[1]?.corpus_import_id).toBeNull()
})

it('accepts explicit nulls from SQL joins on project and paper list rows', () => {
  expect(parseProjectListResponse({
    rows: [{ project_id: 'project-new', project_name: 'Idle project', latest_run_state: null, related_paper_status: null }],
  }).rows?.[0]?.latest_run_state).toBeNull()
  expect(parsePaperListResponse({
    rows: [{ paper_id: 'paper-1', title: 'Untriaged draft', review_status: null }],
  }).rows?.[0]?.review_status).toBeNull()
})

it('accepts explicit null text fields on queue rows from legacy read models', () => {
  const parsed = parseQueueListResponse({
    rows: [{
      project_id: 'queued-1',
      project_name: null,
      status: 'queued',
      decision_summary: null,
      blocked_reason: null,
      next_action_hint: null,
    }],
  })

  expect(parsed.rows?.[0]?.project_id).toBe('queued-1')
  expect(parsed.rows?.[0]?.decision_summary).toBeNull()
})
