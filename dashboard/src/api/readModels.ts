/** Shared dashboard read-model DTO shapes aligned with /control/api/v1/* list endpoints. */

export type PagedRows<T> = {
  rows?: T[]
  page?: {
    returned?: number
    has_more?: boolean
    next_cursor?: string
    page_size?: number
  }
  generated_at?: string
  counts?: Record<string, unknown>
}

export type QueueListRow = {
  project_id?: string
  project_name?: string
  status?: string
  dispatch_priority?: number
  next_action_hint?: string
  manual_review_required?: boolean
  blocked_reason?: string
  decision_summary?: string
  machine_target?: string
  operator_lane?: string
  operator_stage_label?: string
  updated_at?: string
  age_seconds?: number
}

export type ProjectListRow = {
  project_id?: string
  project_name?: string
  queue_status?: string
  latest_run_state?: string
  related_paper_status?: string
  updated_at?: string
  age_seconds?: number
}

export type AutomationListRow = {
  paper_id?: string
  project_name?: string
  paper_status?: string
  review_status?: string
  rank_score?: number
}

export type AutomationDetail = {
  item?: Record<string, unknown>
  checklist?: { items?: Record<string, unknown>[] }
}
