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
    candidate_status_counts?: Record<string, number>
    decision_outcome_counts?: {
      decision?: string
      hypothesis_status?: string
      count?: number
    }[]
    top_candidate_categories?: {
      category?: string
      count?: number
    }[]
    candidate_status_samples?: Record<string, {
      candidate_id?: string
      title?: string
      status?: string
      deterministic_total_score?: number
      contract_quality_score?: number
      problems?: string[]
    }[]>
    decision_outcome_samples?: {
      decision?: string
      hypothesis_status?: string
      samples?: {
        project_id?: string
        project_name?: string
        run_id?: string
        decision?: string
        hypothesis_status?: string
        evidence_strength?: string
        research_outcome?: string
        followup_title?: string
        problems?: string[]
      }[]
    }[]
    window_comparison?: {
      cutoff?: string
      limit?: number
      delta?: Record<string, number>
      current?: {
        candidate_count?: number
        decision_count?: number
        admitted_rate?: number
        avg_total_score?: number
        status_counts?: Record<string, number>
        category_counts?: Record<string, number>
        generation_mode_counts?: Record<string, number>
        eval_case_counts?: Record<string, number>
        high_similarity_pair_count?: number
      }
      previous?: {
        candidate_count?: number
        decision_count?: number
        admitted_rate?: number
        avg_total_score?: number
        status_counts?: Record<string, number>
        category_counts?: Record<string, number>
        generation_mode_counts?: Record<string, number>
        eval_case_counts?: Record<string, number>
        high_similarity_pair_count?: number
      }
    }
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
    malformed_provider_model_counts?: Record<string, number>
    recent_malformed_provider_responses?: {
      checked_at?: string
      recorded_at?: string
      trace_id?: string
      run_cycle_id?: string
      provider_model?: string
      malformed_provider_response_count?: number
      generated_count?: number
      promoted_count?: number
      dispatched_count?: number
      operator_action?: string
    }[]
    post_prompt_warning_details?: {
      code?: string
      severity?: string
      message?: string
      operator_action?: string
    }[]
    provider_generation_health?: {
      available?: boolean
      rows_checked?: number
      malformed_provider_response_count?: number
      malformed_provider_response_ticks?: number
      clean_tick_count?: number
      consecutive_clean_ticks?: number
      last_checked_at?: string
      last_malformed_at?: string
      malformed_provider_model_counts?: Record<string, number>
      latest_tick?: {
        checked_at?: string
        recorded_at?: string
        trace_id?: string
        run_cycle_id?: string
        provider_model?: string
        malformed_provider_response_count?: number
        generated_count?: number
        promoted_count?: number
        dispatched_count?: number
        status?: string
        operator_action?: string
      }
      last_malformed_tick?: {
        checked_at?: string
        recorded_at?: string
        trace_id?: string
        run_cycle_id?: string
        provider_model?: string
        malformed_provider_response_count?: number
        generated_count?: number
        promoted_count?: number
        dispatched_count?: number
        status?: string
        operator_action?: string
      }
      operator_action?: string
    }
    useful_adjacent_followup_evidence?: {
      current?: {
        case_id?: string
        case_type?: string
        severity?: string
        title?: string
        project_id?: string
        project_name?: string
        run_id?: string
        followup_title?: string
        followup_depth?: number
        expected_behavior?: string
      }[]
      previous?: {
        case_id?: string
        case_type?: string
        severity?: string
        title?: string
        project_id?: string
        project_name?: string
        run_id?: string
        followup_title?: string
        followup_depth?: number
        expected_behavior?: string
      }[]
      delta?: number
    }
    report_age_hours?: number | null
    report_stale_after_hours?: number
    report_is_stale?: boolean
    freshness_summary?: string
    signal_verdict?: string
    signal_label?: string
    signal_operator_action?: string
    signal_reasons?: {
      code?: string
      severity?: string
      message?: string
      operator_action?: string
    }[]
    refresh_ok?: boolean
    refresh_action?: string
    refresh_reason?: string
    refresh_recorded_at?: string
    refresh_status_path?: string
    refresh_operator_action?: string
    last_malformed_at?: string
    last_checked_at?: string
    top_problem_details?: {
      section?: string
      severity?: string
      problem?: string
      project_id?: string
      candidate_id?: string
      run_id?: string
      title?: string
      decision?: string
      hypothesis_status?: string
      operator_action?: string
    }[]
    recommendations?: string[]
    operator_recommendations?: string[]
    operator_summary?: string
  }
  movement_diagnosis?: MovementDiagnosis
  flags?: { queue_paused?: boolean; maintenance_mode?: boolean; [key: string]: unknown }
}

export interface StatusResponse {
  worker_lanes?: WorkerLane[]
  generated_at?: string
}
