export type Tone = 'good' | 'info' | 'warn' | 'bad' | 'critical' | 'muted'

export interface TopAction {
  kind: string
  priority?: number
  tone?: Tone | string
  title: string
  summary?: string
  action_label?: string
  action_hash?: string
  lane?: string
  machine_target?: string
  project_id?: string
  feed_action?: string
  blocker_kind?: string
  target?: { project_id?: string; name?: string; [key: string]: unknown }
}

export interface WorkerLane {
  lane_key?: string
  machine_target?: string
  worker_role?: string
  label?: string
  status?: string
  queued_count?: number
  dispatch_available?: boolean
  dispatch_blocker?: string
  active_item?: { project_id?: string; project_name?: string; current_run_id?: string } | null
  next_candidate?: { project_id?: string; project_name?: string } | null
  feed_pressure?: {
    next_autopilot_action?: string
    operator_summary?: string
    desired_queue_depth?: number
    queue_deficit?: number
  } | null
}

export interface MovementBlocker {
  kind: string
  lane?: string
  tone?: Tone | string
  title: string
  summary?: string
  action_label?: string
  action_hash?: string
}

export interface MovementDiagnosis {
  status: string
  primary_reason: string
  blockers: MovementBlocker[]
}

export interface AutomationReadiness {
  ok?: boolean
  label?: string
  blockers?: string[]
  checks?: { name?: string; ok?: boolean }[]
  summary?: { queued?: number; active?: number; queue_paused?: boolean; maintenance_mode?: boolean; [key: string]: unknown }
}

export interface OverviewResponse {
  ok: boolean
  generated_at?: string
  counts?: { active?: number; queued?: number; [key: string]: unknown }
  paper_counts?: { publication_draft?: number; draft_review?: number; [key: string]: unknown }
  top_actions?: TopAction[]
  primary_operator_action?: TopAction | null
  active_items?: Record<string, unknown>[]
  recent_events?: Record<string, unknown>[]
  operator_counts?: Record<string, unknown>
  operator_detail_counts?: Record<string, unknown>
  paper_pipeline?: { write_needed?: number; finalize_needed?: number; publish_ready?: number }
  movement_diagnosis?: MovementDiagnosis
  flags?: { queue_paused?: boolean; maintenance_mode?: boolean; [key: string]: unknown }
}

export interface StatusResponse {
  worker_lanes?: WorkerLane[]
  generated_at?: string
}
