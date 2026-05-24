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
  corpus_import_id: z.string().optional(),
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
  }).passthrough().optional(),
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
