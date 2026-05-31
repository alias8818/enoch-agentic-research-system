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
      malformed_provider_model_counts: { 'hf:model-a': 2 },
      recent_malformed_provider_responses: [{
        checked_at: '2026-05-30T03:00:30Z',
        recorded_at: '2026-05-30T03:04:45Z',
        trace_id: 'research-cycle-trace-a',
        run_cycle_id: 'run-cycle-a',
        provider_model: 'hf:model-a',
        malformed_provider_response_count: 2,
        generated_count: 0,
        promoted_count: 0,
        dispatched_count: 2,
        operator_action: 'inspect provider-generation output for this tick before trusting new idea volume',
      }],
      post_prompt_warning_details: [{
        code: 'malformed_provider_responses',
        severity: 'warning',
        message: '2 malformed provider responses across 1 recent tick',
        operator_action: 'inspect provider-generation output for the listed ticks before trusting new idea volume',
      }],
      provider_generation_health: {
        available: true,
        rows_checked: 4,
        malformed_provider_response_count: 2,
        malformed_provider_response_ticks: 1,
        clean_tick_count: 3,
        consecutive_clean_ticks: 2,
        last_checked_at: '2026-05-30T04:00:30Z',
        last_malformed_at: '2026-05-30T03:00:30Z',
        malformed_provider_model_counts: { 'hf:model-a': 2 },
        latest_tick: {
          checked_at: '2026-05-30T04:00:30Z',
          recorded_at: '2026-05-30T04:04:45Z',
          trace_id: 'research-cycle-trace-b',
          run_cycle_id: 'run-cycle-b',
          provider_model: 'hf:model-b',
          malformed_provider_response_count: 0,
          generated_count: 3,
          promoted_count: 1,
          dispatched_count: 0,
          status: 'clean',
          operator_action: 'provider generation is currently clean; keep monitoring before widening automation',
        },
        last_malformed_tick: {
          checked_at: '2026-05-30T03:00:30Z',
          recorded_at: '2026-05-30T03:04:45Z',
          trace_id: 'research-cycle-trace-a',
          run_cycle_id: 'run-cycle-a',
          provider_model: 'hf:model-a',
          malformed_provider_response_count: 2,
          generated_count: 0,
          promoted_count: 0,
          dispatched_count: 2,
          status: 'malformed',
          operator_action: 'inspect provider-generation output for this tick before trusting new idea volume',
        },
        operator_action: 'provider generation has 2 clean ticks since the last malformed response; review the last malformed model before widening automation',
      },
      useful_adjacent_followup_evidence: {
        current: [{
          case_id: 'useful_adjacent_followup:post-run',
          case_type: 'useful_adjacent_followup',
          severity: 'info',
          title: 'Current follow-up',
          project_id: 'post-project',
          project_name: 'Current Project',
          run_id: 'post-run',
          followup_title: 'Current follow-up',
          followup_depth: 1,
          expected_behavior: 'Prefer bounded follow-up.',
        }],
        previous: [],
        delta: -4,
      },
      candidate_status_counts: {
        admitted: 45,
        needs_review: 53,
        rejected: 2,
      },
      decision_outcome_counts: [{
        decision: 'finalize_negative',
        hypothesis_status: 'mixed',
        count: 50,
      }],
      top_candidate_categories: [{
        category: 'home-training',
        count: 22,
      }],
      candidate_status_samples: {
        admitted: [{
          candidate_id: 'candidate-admitted',
          title: 'Admitted candidate',
          status: 'admitted',
          deterministic_total_score: 76.4,
          contract_quality_score: 1,
          problems: [],
        }],
      },
      decision_outcome_samples: [{
        decision: 'finalize_negative',
        hypothesis_status: 'mixed',
        samples: [{
          project_id: 'project-mixed',
          project_name: 'Mixed project',
          run_id: 'run-mixed',
          evidence_strength: 'moderate',
          followup_title: 'Mixed follow-up',
          problems: [],
        }],
      }],
      window_comparison: {
        cutoff: '2026-05-11T09:58:00Z',
        limit: 20,
        delta: {
          admitted_rate_delta: 0.1,
          proxy_only_positive_delta: -4,
          useful_adjacent_followup_delta: -4,
          moonshot_avg_score_delta: 1.426,
        },
        current: {
          candidate_count: 20,
          decision_count: 20,
          admitted_rate: 0.6,
          avg_total_score: 73.093,
          status_counts: { admitted: 12, rejected: 4 },
          category_counts: { 'home-training': 3, 'long-context': 4 },
          generation_mode_counts: { fresh_grounded: 9, moonshot: 10 },
          eval_case_counts: { proxy_only_positive: 6, useful_adjacent_followup: 2 },
          high_similarity_pair_count: 0,
        },
        previous: {
          candidate_count: 20,
          decision_count: 20,
          admitted_rate: 0.5,
          avg_total_score: 71.82,
          status_counts: { admitted: 10, rejected: 2 },
          category_counts: { 'home-training': 4, 'spec-decoding': 4 },
          generation_mode_counts: { fresh_grounded: 7, moonshot: 7 },
          eval_case_counts: { proxy_only_positive: 8, useful_adjacent_followup: 6 },
          high_similarity_pair_count: 0,
        },
      },
      operator_recommendations: [
        'inspect provider-generation failures before trusting new idea volume',
      ],
    },
  }).research_signal_quality).toMatchObject({
    malformed_provider_response_count: 16,
    refresh_reason: 'missing database URL',
    signal_verdict: 'stale',
    signal_reasons: [{ code: 'quality_report_stale', severity: 'blocked' }],
    malformed_provider_model_counts: { 'hf:model-a': 2 },
    recent_malformed_provider_responses: [{
      trace_id: 'research-cycle-trace-a',
      run_cycle_id: 'run-cycle-a',
      provider_model: 'hf:model-a',
      malformed_provider_response_count: 2,
    }],
    post_prompt_warning_details: [{
      code: 'malformed_provider_responses',
      severity: 'warning',
    }],
    provider_generation_health: {
      rows_checked: 4,
      consecutive_clean_ticks: 2,
      latest_tick: {
        provider_model: 'hf:model-b',
        status: 'clean',
      },
      last_malformed_tick: {
        provider_model: 'hf:model-a',
        malformed_provider_response_count: 2,
      },
    },
    useful_adjacent_followup_evidence: {
      current: [{
        case_id: 'useful_adjacent_followup:post-run',
        project_id: 'post-project',
        followup_title: 'Current follow-up',
      }],
      previous: [],
      delta: -4,
    },
    candidate_status_counts: {
      admitted: 45,
      needs_review: 53,
      rejected: 2,
    },
    decision_outcome_counts: [{
      decision: 'finalize_negative',
      hypothesis_status: 'mixed',
      count: 50,
    }],
    top_candidate_categories: [{
      category: 'home-training',
      count: 22,
    }],
    candidate_status_samples: {
      admitted: [{
        candidate_id: 'candidate-admitted',
        title: 'Admitted candidate',
      }],
    },
    decision_outcome_samples: [{
      decision: 'finalize_negative',
      hypothesis_status: 'mixed',
      samples: [{
        project_id: 'project-mixed',
        run_id: 'run-mixed',
      }],
    }],
    window_comparison: {
      cutoff: '2026-05-11T09:58:00Z',
      current: {
        admitted_rate: 0.6,
        generation_mode_counts: { fresh_grounded: 9, moonshot: 10 },
      },
      previous: {
        admitted_rate: 0.5,
        category_counts: { 'spec-decoding': 4 },
      },
      delta: {
        admitted_rate_delta: 0.1,
      },
    },
    operator_recommendations: [
      'inspect provider-generation failures before trusting new idea volume',
    ],
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
