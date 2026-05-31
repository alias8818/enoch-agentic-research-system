/**
 * Zod validators for dashboard read-model DTOs.
 * Parse API payloads at query boundaries so table/detail rendering cannot silently drift from backend shapes.
 */
import { z } from 'zod'
import type {
  AutomationDetail,
  AutomationListRow,
  EventListRow,
  IntakeIdeasResponse,
  PagedRows,
  PaperListRow,
  ProjectListRow,
  QueueListRow,
  RunListRow,
} from './readModels'
import type { AutomationReadiness, OverviewResponse, StatusResponse } from '../types'

const pageMetaSchema = z.object({
  returned: z.number().optional(),
  has_more: z.boolean().optional(),
  next_cursor: z.string().optional(),
  page_size: z.number().optional(),
}).passthrough()

/** SQL LEFT JOINs and idle projects may send explicit null instead of omitting keys. */
const apiString = z.string().nullish()
const apiId = z.union([z.string(), z.number()]).nullish()

function pagedRowsSchema<T extends z.ZodTypeAny>(rowSchema: T) {
  return z.object({
    rows: z.array(rowSchema).optional(),
    page: pageMetaSchema.optional(),
    generated_at: z.string().optional(),
    counts: z.record(z.unknown()).optional(),
    operator_summary: z.string().optional(),
  }).passthrough()
}

export const queueListRowSchema = z.object({
  project_id: apiString,
  project_name: apiString,
  title: apiString,
  status: apiString,
  dispatch_priority: z.number().optional(),
  selection_rank: z.number().optional(),
  current_run_id: apiString,
  next_action_hint: apiString,
  manual_review_required: z.boolean().optional(),
  blocked_reason: apiString,
  decision_summary: apiString,
  machine_target: apiString,
  operator_lane: apiString,
  operator_stage_label: apiString,
  updated_at: apiString,
  age_seconds: z.number().optional(),
}).passthrough()

export const projectListRowSchema = z.object({
  project_id: apiString,
  project_name: apiString,
  queue_status: apiString,
  latest_run_state: apiString,
  related_paper_status: apiString,
  machine_target: apiString,
  lane: apiString,
  updated_at: z.string().optional(),
  age_seconds: z.number().optional(),
}).passthrough()

export const runListRowSchema = z.object({
  run_id: z.string().optional(),
  project_id: z.string().optional(),
  project_name: z.string().optional(),
  state: z.string().optional(),
  gate_state: z.string().optional(),
  dispatch_mode: z.string().optional(),
  machine_target: z.string().optional(),
  current_activity: z.string().optional(),
  updated_at: z.string().optional(),
  age_seconds: z.number().optional(),
}).passthrough()

export const paperListRowSchema = z.object({
  paper_id: z.string().optional(),
  project_id: z.string().optional(),
  project_name: z.string().optional(),
  title: z.string().optional(),
  paper_title: z.string().optional(),
  paper_status: apiString,
  review_status: apiString,
  corpus_imported: z.boolean().optional(),
  corpus_import_id: apiId,
  artifact_paths_present: z.record(z.unknown()).optional(),
  updated_at: z.string().optional(),
  age_seconds: z.number().optional(),
}).passthrough()

export const eventListRowSchema = z.object({
  event_id: z.union([z.string(), z.number()]).optional(),
  id: z.union([z.string(), z.number()]).optional(),
  event_type: z.string().optional(),
  summary: z.string().optional(),
  entity_type: z.string().optional(),
  entity_id: z.string().optional(),
  project_id: z.string().optional(),
  run_id: z.string().optional(),
  paper_id: z.string().optional(),
  created_at: z.string().optional(),
  updated_at: z.string().optional(),
  age_seconds: z.number().optional(),
}).passthrough()

export const automationListRowSchema = z.object({
  paper_id: z.string().optional(),
  project_name: z.string().optional(),
  paper_status: apiString,
  review_status: apiString,
  rank_score: z.number().optional(),
}).passthrough()

export const automationDetailSchema = z.object({
  item: z.record(z.unknown()).optional(),
  checklist: z.object({
    items: z.array(z.record(z.unknown())).optional(),
  }).optional(),
}).passthrough()

const topActionSchema = z.object({
  kind: z.string(),
  priority: z.number().optional(),
  tone: apiString,
  title: z.string(),
  summary: apiString,
  action_label: apiString,
  action_hash: apiString,
  lane: apiString,
  machine_target: apiString,
  project_id: apiString,
  feed_action: apiString,
  blocker_kind: apiString,
  target: z.record(z.unknown()).nullable().optional(),
}).passthrough()

const movementBlockerSchema = z.object({
  kind: z.string(),
  lane: apiString,
  tone: apiString,
  title: z.string(),
  summary: apiString,
  action_label: apiString,
  action_hash: apiString,
}).passthrough()

const movementDiagnosisSchema = z.object({
  status: z.string(),
  primary_reason: z.string(),
  blockers: z.array(movementBlockerSchema),
}).passthrough()

const researchYieldTargetSchema = z.object({
  project_id: z.string().optional(),
  project_name: z.string().optional(),
  run_id: z.string().optional(),
  followup_title: z.string().optional(),
  title: z.string().optional(),
}).passthrough()

const researchYieldSchema = z.object({
  latest_paper_age_days: z.number().nullable().optional(),
  paper_drought: z.object({
    warning: z.boolean().optional(),
    threshold_days: z.number().optional(),
    explanation: z.string().optional(),
  }).passthrough().optional(),
  paper_recovery: z.object({
    status: z.string().optional(),
    next_action: z.string().optional(),
    count: z.number().optional(),
    reason: z.string().optional(),
    target: researchYieldTargetSchema.nullable().optional(),
  }).passthrough().optional(),
  maturity_counts: z.record(z.string(), z.number()).optional(),
  top_deepen_required_candidate: z.record(z.unknown()).nullable().optional(),
  dominant_missing_evidence_reason: z.string().optional(),
}).passthrough()

const usefulFollowupEvidenceRowSchema = z.object({
  case_id: z.string().optional(),
  case_type: z.string().optional(),
  severity: z.string().optional(),
  title: z.string().optional(),
  project_id: z.string().optional(),
  project_name: z.string().optional(),
  run_id: z.string().optional(),
  followup_title: z.string().optional(),
  followup_depth: z.number().optional(),
  expected_behavior: z.string().optional(),
}).passthrough()

const decisionOutcomeCountSchema = z.object({
  decision: z.string().optional(),
  hypothesis_status: z.string().optional(),
  count: z.number().optional(),
}).passthrough()

const candidateCategoryCountSchema = z.object({
  category: z.string().optional(),
  count: z.number().optional(),
}).passthrough()

const researchQualitySampleLinksSchema = z.record(z.string(), z.string()).optional()

const candidateStatusSampleSchema = z.object({
  candidate_id: z.string().optional(),
  title: z.string().optional(),
  status: z.string().optional(),
  deterministic_total_score: z.number().optional(),
  contract_quality_score: z.number().optional(),
  problems: z.array(z.string()).optional(),
}).passthrough()

const decisionOutcomeSampleRowSchema = z.object({
  project_id: z.string().optional(),
  project_name: z.string().optional(),
  run_id: z.string().optional(),
  links: researchQualitySampleLinksSchema,
  decision: z.string().optional(),
  hypothesis_status: z.string().optional(),
  evidence_strength: z.string().optional(),
  research_outcome: z.string().optional(),
  followup_title: z.string().optional(),
  problems: z.array(z.string()).optional(),
}).passthrough()

const decisionOutcomeSampleGroupSchema = z.object({
  decision: z.string().optional(),
  hypothesis_status: z.string().optional(),
  samples: z.array(decisionOutcomeSampleRowSchema).optional(),
}).passthrough()

const qualityWindowSideSchema = z.object({
  candidate_count: z.number().optional(),
  decision_count: z.number().optional(),
  admitted_rate: z.number().optional(),
  avg_total_score: z.number().optional(),
  status_counts: z.record(z.string(), z.number()).optional(),
  category_counts: z.record(z.string(), z.number()).optional(),
  generation_mode_counts: z.record(z.string(), z.number()).optional(),
  eval_case_counts: z.record(z.string(), z.number()).optional(),
  high_similarity_pair_count: z.number().optional(),
}).passthrough()

const qualityWindowComparisonSchema = z.object({
  cutoff: z.string().optional(),
  limit: z.number().optional(),
  delta: z.record(z.string(), z.number()).optional(),
  current: qualityWindowSideSchema.optional(),
  previous: qualityWindowSideSchema.optional(),
}).passthrough()

const providerGenerationTickSchema = z.object({
  checked_at: z.string().optional(),
  recorded_at: z.string().optional(),
  trace_id: z.string().optional(),
  run_cycle_id: z.string().optional(),
  provider_model: z.string().optional(),
  malformed_provider_response_count: z.number().optional(),
  initial_promotable_count: z.number().optional(),
  generated_count: z.number().optional(),
  promoted_count: z.number().optional(),
  dispatched_count: z.number().optional(),
  reason: z.string().optional(),
  status: z.string().optional(),
  operator_action: z.string().optional(),
}).passthrough()

const providerGenerationHealthSchema = z.object({
  available: z.boolean().optional(),
  rows_checked: z.number().optional(),
  malformed_provider_response_count: z.number().optional(),
  malformed_provider_response_ticks: z.number().optional(),
  clean_tick_count: z.number().optional(),
  consecutive_clean_ticks: z.number().optional(),
  malformed_history_status: z.string().optional(),
  active_malformed_warning: z.boolean().optional(),
  last_checked_at: z.string().optional(),
  last_malformed_at: z.string().optional(),
  malformed_provider_model_counts: z.record(z.string(), z.number()).optional(),
  latest_tick: providerGenerationTickSchema.optional(),
  last_malformed_tick: providerGenerationTickSchema.optional(),
  consecutive_zero_generated_ticks: z.number().optional(),
  consecutive_zero_promoted_ticks: z.number().optional(),
  latest_yield_status: z.string().optional(),
  yield_operator_action: z.string().optional(),
  operator_action: z.string().optional(),
}).passthrough()

const decisionPostureSampleSchema = z.object({
  project_id: z.string().optional(),
  project_name: z.string().optional(),
  run_id: z.string().optional(),
  links: researchQualitySampleLinksSchema,
  decision: z.string().optional(),
  hypothesis_status: z.string().optional(),
  evidence_strength: z.string().optional(),
  research_outcome: z.string().optional(),
  bounded_paper_ready: z.boolean().optional(),
  followup_recommended: z.boolean().optional(),
  followup_title: z.string().optional(),
  recommended_next_action: z.string().optional(),
}).passthrough()

const paperReadinessBlockerSampleSchema = z.object({
  project_id: z.string().optional(),
  project_name: z.string().optional(),
  run_id: z.string().optional(),
  links: researchQualitySampleLinksSchema,
  hypothesis_status: z.string().optional(),
  evidence_strength: z.string().optional(),
  research_outcome: z.string().optional(),
  bounded_paper_ready: z.boolean().optional(),
  followup_recommended: z.boolean().optional(),
  followup_title: z.string().optional(),
  recommended_next_action: z.string().optional(),
  blocker_reasons: z.array(z.string()).optional(),
}).passthrough()

const paperReadinessBlockersSchema = z.object({
  available: z.boolean().optional(),
  decisions_checked: z.number().optional(),
  paper_ready_count: z.number().optional(),
  blocker_counts: z.record(z.string(), z.number()).optional(),
  samples: z.array(paperReadinessBlockerSampleSchema).optional(),
  operator_action: z.string().optional(),
}).passthrough()

const decisionPostureSchema = z.object({
  available: z.boolean().optional(),
  decisions_checked: z.number().optional(),
  useful_signal_count: z.number().optional(),
  negative_count: z.number().optional(),
  bounded_paper_ready_count: z.number().optional(),
  followup_recommended_count: z.number().optional(),
  compute_scale_blocked_count: z.number().optional(),
  publication_posture: z.string().optional(),
  research_outcome_counts: z.record(z.string(), z.number()).optional(),
  hypothesis_status_counts: z.record(z.string(), z.number()).optional(),
  evidence_strength_counts: z.record(z.string(), z.number()).optional(),
  decision_counts: z.record(z.string(), z.number()).optional(),
  paper_readiness_blockers: paperReadinessBlockersSchema.optional(),
  representative_useful_signals: z.array(decisionPostureSampleSchema).optional(),
  operator_action: z.string().optional(),
}).passthrough()

const followupReadinessSampleSchema = z.object({
  project_id: z.string().optional(),
  project_name: z.string().optional(),
  run_id: z.string().optional(),
  links: researchQualitySampleLinksSchema,
  followup_type: z.string().optional(),
  followup_title: z.string().optional(),
  followup_required_evidence_count: z.number().optional(),
  followup_success_threshold: z.string().optional(),
  followup_stop_condition: z.string().optional(),
  recommended_next_action: z.string().optional(),
  hypothesis_status: z.string().optional(),
  evidence_strength: z.string().optional(),
  priority_score: z.number().optional(),
  priority_reasons: z.array(z.string()).optional(),
  missing_fields: z.array(z.string()).optional(),
}).passthrough()

const followupReadinessSchema = z.object({
  available: z.boolean().optional(),
  recommended_count: z.number().optional(),
  bounded_ready_count: z.number().optional(),
  underspecified_count: z.number().optional(),
  missing_title_count: z.number().optional(),
  missing_success_threshold_count: z.number().optional(),
  missing_stop_condition_count: z.number().optional(),
  thin_required_evidence_count: z.number().optional(),
  followup_type_counts: z.record(z.string(), z.number()).optional(),
  ready_followups: z.array(followupReadinessSampleSchema).optional(),
  prioritized_followups: z.array(followupReadinessSampleSchema).optional(),
  underspecified_followups: z.array(followupReadinessSampleSchema).optional(),
  operator_action: z.string().optional(),
}).passthrough()

const followupScopeCandidateSchema = z.object({
  project_id: z.string().optional(),
  project_name: z.string().optional(),
  run_id: z.string().optional(),
  followup_title: z.string().optional(),
  recommended_next_action: z.string().optional(),
}).passthrough()

const followupScopeAlignmentSchema = z.object({
  available: z.boolean().optional(),
  global_ready_count: z.number().optional(),
  same_project: z.boolean().optional(),
  same_run: z.boolean().optional(),
  global_candidate: followupScopeCandidateSchema.optional(),
  quality_window_candidate: followupScopeCandidateSchema.optional(),
  operator_action: z.string().optional(),
}).passthrough()

const researchSignalQualitySchema = z.object({
  status: z.string().optional(),
  ok: z.boolean().optional(),
  decisions_checked: z.number().optional(),
  candidate_status_counts: z.record(z.string(), z.number()).optional(),
  decision_outcome_counts: z.array(decisionOutcomeCountSchema).optional(),
  top_candidate_categories: z.array(candidateCategoryCountSchema).optional(),
  candidate_status_samples: z.record(
    z.string(),
    z.array(candidateStatusSampleSchema),
  ).optional(),
  decision_outcome_samples: z.array(decisionOutcomeSampleGroupSchema).optional(),
  window_comparison: qualityWindowComparisonSchema.optional(),
  weak_evidence_count: z.number().optional(),
  warning_problem_count: z.number().optional(),
  blocked_problem_count: z.number().optional(),
  decision_coverage: z.number().optional(),
  proxy_only_positive: z.number().optional(),
  proxy_only_positive_delta: z.number().optional(),
  useful_adjacent_followup: z.number().optional(),
  useful_adjacent_followup_delta: z.number().optional(),
  moonshot_avg_score_delta: z.number().optional(),
  malformed_provider_response_count: z.number().optional(),
  malformed_provider_response_ticks: z.number().optional(),
  malformed_provider_model_counts: z.record(z.string(), z.number()).optional(),
  recent_malformed_provider_responses: z.array(z.object({
    checked_at: z.string().optional(),
    recorded_at: z.string().optional(),
    trace_id: z.string().optional(),
    run_cycle_id: z.string().optional(),
    provider_model: z.string().optional(),
    malformed_provider_response_count: z.number().optional(),
    generated_count: z.number().optional(),
    promoted_count: z.number().optional(),
    dispatched_count: z.number().optional(),
    operator_action: z.string().optional(),
  }).passthrough()).optional(),
  post_prompt_warning_details: z.array(z.object({
    code: z.string().optional(),
    severity: z.string().optional(),
    message: z.string().optional(),
    operator_action: z.string().optional(),
  }).passthrough()).optional(),
  provider_generation_health: providerGenerationHealthSchema.optional(),
  decision_posture: decisionPostureSchema.optional(),
  followup_readiness: followupReadinessSchema.optional(),
  followup_scope_alignment: followupScopeAlignmentSchema.optional(),
  useful_adjacent_followup_evidence: z.object({
    current: z.array(usefulFollowupEvidenceRowSchema).optional(),
    previous: z.array(usefulFollowupEvidenceRowSchema).optional(),
    delta: z.number().optional(),
  }).passthrough().optional(),
  report_age_hours: z.number().nullable().optional(),
  report_stale_after_hours: z.number().optional(),
  report_is_stale: z.boolean().optional(),
  freshness_summary: z.string().optional(),
  signal_verdict: z.string().optional(),
  signal_label: z.string().optional(),
  signal_operator_action: z.string().optional(),
  signal_reasons: z.array(z.object({
    code: z.string().optional(),
    severity: z.string().optional(),
    message: z.string().optional(),
    operator_action: z.string().optional(),
  }).passthrough()).optional(),
  research_output_readiness: z.object({
    state: z.string().optional(),
    label: z.string().optional(),
    blocked_by: z.string().optional(),
    hold_state: z.string().optional(),
    failed_invariants: z.array(z.object({
      code: z.string().optional(),
      label: z.string().optional(),
      current: z.union([z.number(), z.string()]).optional(),
      required: z.union([z.number(), z.string()]).optional(),
      previous: z.union([z.number(), z.string()]).optional(),
      delta: z.union([z.number(), z.string()]).optional(),
      useful_signal_count: z.number().optional(),
      publication_posture: z.string().optional(),
    }).passthrough()).optional(),
    affected_artifacts: z.array(z.object({
      source: z.string().optional(),
      project_id: z.string().optional(),
      project_name: z.string().optional(),
      run_id: z.string().optional(),
      title: z.string().optional(),
      case_id: z.string().optional(),
    }).passthrough()).optional(),
    next_bounded_action: z.object({
      kind: z.string().optional(),
      title: z.string().optional(),
      summary: z.string().optional(),
      action_label: z.string().optional(),
      action_hash: z.string().optional(),
      target: z.object({
        project_id: z.string().optional(),
        run_id: z.string().optional(),
        name: z.string().optional(),
      }).passthrough().optional(),
    }).passthrough().optional(),
    operator_action: z.string().optional(),
    signal_verdict: z.string().optional(),
  }).passthrough().optional(),
  refresh_ok: z.boolean().optional(),
  refresh_action: z.string().optional(),
  refresh_reason: z.string().optional(),
  refresh_recorded_at: z.string().optional(),
  refresh_status_path: z.string().optional(),
  refresh_operator_action: z.string().optional(),
  last_malformed_at: z.string().optional(),
  last_checked_at: z.string().optional(),
  top_problem_details: z.array(z.object({
    section: z.string().optional(),
    severity: z.string().optional(),
    problem: z.string().optional(),
    project_id: z.string().optional(),
    candidate_id: z.string().optional(),
    run_id: z.string().optional(),
    title: z.string().optional(),
    decision: z.string().optional(),
    hypothesis_status: z.string().optional(),
    operator_action: z.string().optional(),
  }).passthrough()).optional(),
  recommendations: z.array(z.string()).optional(),
  operator_recommendations: z.array(z.string()).optional(),
  operator_summary: z.string().optional(),
}).passthrough()

export const overviewResponseSchema = z.object({
  ok: z.boolean().optional(),
  generated_at: z.string().optional(),
  counts: z.record(z.unknown()).optional(),
  paper_counts: z.record(z.unknown()).optional(),
  top_actions: z.array(topActionSchema).optional(),
  primary_operator_action: topActionSchema.nullable().optional(),
  active_items: z.array(z.record(z.unknown())).optional(),
  recent_events: z.array(z.record(z.unknown())).optional(),
  operator_counts: z.record(z.unknown()).optional(),
  operator_detail_counts: z.record(z.unknown()).optional(),
  paper_pipeline: z.object({
    write_needed: z.number().optional(),
    finalize_needed: z.number().optional(),
    publish_ready: z.number().optional(),
    published_imported: z.number().optional(),
    publication_ready_total: z.number().optional(),
    missing_from_corpus: z.number().optional(),
    paper_gate_archive_count: z.number().optional(),
    paper_write_blocked: z.number().optional(),
    paper_gate_archive_summary: z.string().optional(),
  }).passthrough().optional(),
  research_yield: researchYieldSchema.optional(),
  research_signal_quality: researchSignalQualitySchema.optional(),
  movement_diagnosis: movementDiagnosisSchema.optional(),
  flags: z.record(z.unknown()).optional(),
}).passthrough()

const workerLaneSchema = z.object({
  lane_key: z.string().optional(),
  machine_target: z.string().optional(),
  worker_role: z.string().optional(),
  label: z.string().optional(),
  status: z.string().optional(),
  queued_count: z.number().optional(),
  dispatch_available: z.boolean().optional(),
  dispatch_blocker: z.string().optional(),
  active_item: z.object({
    project_id: z.string().optional(),
    project_name: z.string().optional(),
    current_run_id: z.string().optional(),
  }).nullable().optional(),
  active_confirmation: z.object({
    state: z.string().optional(),
    matched: z.boolean().optional(),
    reason: z.string().optional(),
    matched_run_id: z.string().optional(),
    matched_project_id: z.string().optional(),
    active_process_count: z.number().nullable().optional(),
  }).nullable().optional(),
  next_candidate: z.object({
    project_id: z.string().optional(),
    project_name: z.string().optional(),
  }).nullable().optional(),
  feed_pressure: z.object({
    next_autopilot_action: z.string().optional(),
    operator_summary: z.string().optional(),
    desired_queue_depth: z.number().optional(),
    queue_deficit: z.number().optional(),
  }).nullable().optional(),
}).passthrough()

export const statusResponseSchema = z.object({
  worker_lanes: z.array(workerLaneSchema).optional(),
  generated_at: z.string().optional(),
}).passthrough()

export const automationReadinessSchema = z.object({
  ok: z.boolean().optional(),
  label: z.string().optional(),
  blockers: z.array(z.string()).optional(),
  checks: z.array(z.object({
    name: z.string().optional(),
    ok: z.boolean().optional(),
  })).optional(),
  summary: z.record(z.unknown()).optional(),
}).passthrough()

export const queueListResponseSchema = pagedRowsSchema(queueListRowSchema)
export const projectListResponseSchema = pagedRowsSchema(projectListRowSchema)
export const runListResponseSchema = pagedRowsSchema(runListRowSchema)
export const paperListResponseSchema = pagedRowsSchema(paperListRowSchema)
export const eventListResponseSchema = pagedRowsSchema(eventListRowSchema)
export const automationListResponseSchema = pagedRowsSchema(automationListRowSchema)

export const intakeIdeaProjectionRowSchema = z.object({
  idea_id: apiString,
  title: apiString,
  idea_status: apiString,
  queue_status: apiString,
  next_action_hint: apiString,
  paper_status: apiString,
  source_kind: apiString,
  machine_target: apiString,
  project_id: apiString,
  updated_at: apiString,
  operator_stage: apiString,
  operator_detail_stage: apiString,
  operator_next_step: apiString,
  operator_stage_label: apiString,
}).passthrough()

export const intakeIdeasResponseSchema = z.object({
  ok: z.boolean().optional(),
  generated_at: z.string().optional(),
  operator_summary: z.string().optional(),
  latest_sync: z.record(z.unknown()).nullable().optional(),
  projection_counts: z.record(z.number()).optional(),
  queued_projection: z.array(intakeIdeaProjectionRowSchema).optional(),
  skipped_reasons: z.record(z.number()).optional(),
  recent_events: z.array(z.record(z.unknown())).optional(),
}).passthrough()

export const OPERATOR_LIST_FIELD_KEYS = {
  queue: ['project_id', 'project_name', 'status'] as const,
  projects: ['project_id', 'project_name', 'queue_status'] as const,
  runs: ['run_id', 'project_name', 'state'] as const,
  papers: ['paper_id', 'paper_status'] as const,
  events: ['event_type', 'summary'] as const,
} as const

export function listRowSchemaKeys(schema: z.ZodObject<z.ZodRawShape>): string[] {
  return Object.keys(schema.shape)
}

export function parseQueueListResponse(payload: unknown): PagedRows<QueueListRow> {
  return queueListResponseSchema.parse(payload) as PagedRows<QueueListRow>
}

export function parseProjectListResponse(payload: unknown): PagedRows<ProjectListRow> {
  return projectListResponseSchema.parse(payload) as PagedRows<ProjectListRow>
}

export function parseRunListResponse(payload: unknown): PagedRows<RunListRow> {
  return runListResponseSchema.parse(payload) as PagedRows<RunListRow>
}

export function parsePaperListResponse(payload: unknown): PagedRows<PaperListRow> {
  return paperListResponseSchema.parse(payload) as PagedRows<PaperListRow>
}

export function parseEventListResponse(payload: unknown): PagedRows<EventListRow> {
  return eventListResponseSchema.parse(payload) as PagedRows<EventListRow>
}

export function parseAutomationListResponse(payload: unknown): PagedRows<AutomationListRow> {
  return automationListResponseSchema.parse(payload) as PagedRows<AutomationListRow>
}

export function parseAutomationDetail(payload: unknown): AutomationDetail {
  return automationDetailSchema.parse(payload) as AutomationDetail
}

export function parseOverviewResponse(payload: unknown): OverviewResponse {
  const parsed = overviewResponseSchema.parse(payload) as OverviewResponse
  return { ...parsed, ok: parsed.ok ?? true }
}

export function parseStatusResponse(payload: unknown): StatusResponse {
  return statusResponseSchema.parse(payload) as StatusResponse
}

export function parseAutomationReadiness(payload: unknown): AutomationReadiness {
  return automationReadinessSchema.parse(payload) as AutomationReadiness
}

export function parseIntakeIdeasResponse(payload: unknown): IntakeIdeasResponse {
  return intakeIdeasResponseSchema.parse(payload) as IntakeIdeasResponse
}
