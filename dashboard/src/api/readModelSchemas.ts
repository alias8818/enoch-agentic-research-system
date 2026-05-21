import { z } from 'zod'
import type { AutomationDetail, AutomationListRow, PagedRows, ProjectListRow, QueueListRow } from './readModels'

const pageMetaSchema = z.object({
  returned: z.number().optional(),
  has_more: z.boolean().optional(),
  next_cursor: z.string().optional(),
  page_size: z.number().optional(),
}).passthrough()

function pagedRowsSchema<T extends z.ZodTypeAny>(rowSchema: T) {
  return z.object({
    rows: z.array(rowSchema).optional(),
    page: pageMetaSchema.optional(),
    generated_at: z.string().optional(),
    counts: z.record(z.unknown()).optional(),
  }).passthrough()
}

export const queueListRowSchema = z.object({
  project_id: z.string().optional(),
  project_name: z.string().optional(),
  status: z.string().optional(),
  dispatch_priority: z.number().optional(),
  next_action_hint: z.string().optional(),
  manual_review_required: z.boolean().optional(),
  blocked_reason: z.string().optional(),
  decision_summary: z.string().optional(),
  machine_target: z.string().optional(),
  operator_lane: z.string().optional(),
  operator_stage_label: z.string().optional(),
  updated_at: z.string().optional(),
  age_seconds: z.number().optional(),
}).passthrough()

export const projectListRowSchema = z.object({
  project_id: z.string().optional(),
  project_name: z.string().optional(),
  queue_status: z.string().optional(),
  latest_run_state: z.string().optional(),
  related_paper_status: z.string().optional(),
  updated_at: z.string().optional(),
  age_seconds: z.number().optional(),
}).passthrough()

export const automationListRowSchema = z.object({
  paper_id: z.string().optional(),
  project_name: z.string().optional(),
  paper_status: z.string().optional(),
  review_status: z.string().optional(),
  rank_score: z.number().optional(),
}).passthrough()

export const automationDetailSchema = z.object({
  item: z.record(z.unknown()).optional(),
  checklist: z.object({
    items: z.array(z.record(z.unknown())).optional(),
  }).optional(),
}).passthrough()

export const queueListResponseSchema = pagedRowsSchema(queueListRowSchema)
export const projectListResponseSchema = pagedRowsSchema(projectListRowSchema)
export const automationListResponseSchema = pagedRowsSchema(automationListRowSchema)

export function parseQueueListResponse(payload: unknown): PagedRows<QueueListRow> {
  return queueListResponseSchema.parse(payload) as PagedRows<QueueListRow>
}

export function parseProjectListResponse(payload: unknown): PagedRows<ProjectListRow> {
  return projectListResponseSchema.parse(payload) as PagedRows<ProjectListRow>
}

export function parseAutomationListResponse(payload: unknown): PagedRows<AutomationListRow> {
  return automationListResponseSchema.parse(payload) as PagedRows<AutomationListRow>
}

export function parseAutomationDetail(payload: unknown): AutomationDetail {
  return automationDetailSchema.parse(payload) as AutomationDetail
}
