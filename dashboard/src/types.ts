export type Tone = 'good' | 'info' | 'warn' | 'bad' | 'critical' | 'muted'

export interface TopAction {
  kind: string
  priority?: number
  tone?: string | null
  title: string
  summary?: string | null
  action_label?: string | null
  action_hash?: string | null
  lane?: string | null
  machine_target?: string | null
  project_id?: string | null
  feed_action?: string | null
  blocker_kind?: string | null
  target?: { project_id?: string; name?: string; [key: string]: unknown } | null
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
  active_confirmation?: {
    state?: string
    matched?: boolean
    reason?: string
    matched_run_id?: string
    matched_project_id?: string
    active_process_count?: number | null
  } | null
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
  lane?: string | null
  tone?: Tone | null
  title: string
  summary?: string | null
  action_label?: string | null
  action_hash?: string | null
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
  paper_pipeline?: {
    write_needed?: number
    finalize_needed?: number
    publish_ready?: number
    published_imported?: number
    publication_ready_total?: number
    missing_from_corpus?: number
    paper_gate_archive_count?: number
    paper_write_blocked?: number
    paper_gate_archive_summary?: string
  }
  research_signal_quality?: {
    status?: string
    ok?: boolean
    decisions_checked?: number
    weak_evidence_count?: number
    warning_problem_count?: number
    blocked_problem_count?: number
    decision_coverage?: number
    proxy_only_positive?: number
    proxy_only_positive_delta?: number
    useful_adjacent_followup?: number
    useful_adjacent_followup_delta?: number
    moonshot_avg_score_delta?: number
    malformed_provider_response_count?: number
    malformed_provider_response_ticks?: number
    last_malformed_at?: string
    last_checked_at?: string
    operator_summary?: string
  }
  movement_diagnosis?: MovementDiagnosis
  flags?: { queue_paused?: boolean; maintenance_mode?: boolean; [key: string]: unknown }
}

export interface StatusResponse {
  worker_lanes?: WorkerLane[]
  generated_at?: string
}
