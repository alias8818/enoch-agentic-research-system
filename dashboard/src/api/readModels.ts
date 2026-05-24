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
  operator_summary?: string
}

export type QueueListRow = {
  project_id?: string
  project_name?: string
  title?: string
  status?: string
  dispatch_priority?: number
  selection_rank?: number
  current_run_id?: string
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
  machine_target?: string
  lane?: string
  updated_at?: string
  age_seconds?: number
}

export type RunListRow = {
  run_id?: string
  project_id?: string
  project_name?: string
  state?: string
  gate_state?: string
  dispatch_mode?: string
  machine_target?: string
  current_activity?: string
  updated_at?: string
  age_seconds?: number
}

export type PaperListRow = {
  paper_id?: string
  project_id?: string
  project_name?: string
  title?: string
  paper_title?: string
  paper_status?: string
  review_status?: string
  corpus_imported?: boolean
  corpus_import_id?: string | number | null
  artifact_paths_present?: Record<string, unknown>
  updated_at?: string
  age_seconds?: number
}

export type EventListRow = {
  event_id?: string | number
  id?: string | number
  event_type?: string
  summary?: string
  entity_type?: string
  entity_id?: string
  project_id?: string
  run_id?: string
  paper_id?: string
  created_at?: string
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

export type IntakeIdeaProjectionRow = {
  idea_id?: string
  title?: string
  idea_status?: string
  queue_status?: string
  next_action_hint?: string
  paper_status?: string
  source_kind?: string
  machine_target?: string
  project_id?: string
  updated_at?: string
  operator_stage?: string
  operator_detail_stage?: string
  operator_next_step?: string
  operator_stage_label?: string
}

export type IntakeIdeasResponse = {
  ok?: boolean
  generated_at?: string
  operator_summary?: string
  latest_sync?: Record<string, unknown> | null
  projection_counts?: Record<string, number>
  queued_projection?: IntakeIdeaProjectionRow[]
  skipped_reasons?: Record<string, number>
  recent_events?: Record<string, unknown>[]
}
