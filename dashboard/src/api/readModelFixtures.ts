/** Representative API payloads for Zod schema regression tests. */

export const overviewFixture = {
  ok: true,
  generated_at: '2026-05-21T12:00:00Z',
  counts: { active: 1, queued: 2 },
  paper_counts: { publication_draft: 1 },
  paper_pipeline: { write_needed: 0, finalize_needed: 0, publish_ready: 0 },
  movement_diagnosis: {
    status: 'actionable',
    primary_reason: 'GB10 lane can dispatch queued work.',
    blockers: [{ kind: 'dispatch_available', title: 'GB10 lane can dispatch', summary: 'One candidate is ready.' }],
  },
  primary_operator_action: {
    kind: 'dispatch_next',
    title: 'Dispatch GB10 lane',
    summary: 'One queued candidate matches the idle lane.',
    action_label: 'Check dispatch',
    action_hash: '#queue:queued',
  },
  recent_events: [],
  active_items: [],
  operator_counts: {},
  operator_detail_counts: {},
  flags: { queue_paused: false, maintenance_mode: false },
}

export const statusFixture = {
  generated_at: '2026-05-21T12:00:00Z',
  worker_lanes: [{
    lane_key: 'cpu',
    machine_target: 'cpu-proxmox-1',
    label: 'CPU lane',
    status: 'active',
    queued_count: 3,
    dispatch_available: false,
    dispatch_blocker: 'lane active',
    active_item: { project_id: 'project-1', project_name: 'Alpha study' },
    feed_pressure: { desired_queue_depth: 25, queue_deficit: 0 },
  }],
}

export const queueListFixture = {
  generated_at: '2026-05-21T12:00:00Z',
  rows: [{
    project_id: 'project-1',
    project_name: 'Oracle lane',
    status: 'queued',
    machine_target: 'gb10',
    next_action_hint: 'Dry-run dispatch before live dispatch.',
    age_seconds: 120,
  }],
  page: { returned: 1, has_more: false },
}

export const projectListFixture = {
  rows: [{
    project_id: 'project-1',
    project_name: 'Oracle lane',
    queue_status: 'queued',
    latest_run_state: 'completed',
    related_paper_status: 'publication_draft',
    machine_target: 'gb10',
    age_seconds: 300,
  }],
  page: { returned: 1, has_more: false },
}

export const runListFixture = {
  rows: [{
    run_id: 'run-1',
    project_id: 'project-1',
    project_name: 'Oracle lane',
    state: 'running',
    gate_state: 'wake_ready',
    dispatch_mode: 'gb10',
    current_activity: 'Waiting for worker callback',
    age_seconds: 45,
  }],
  page: { returned: 1, has_more: false },
}

export const paperListFixture = {
  rows: [{
    paper_id: 'paper-1',
    project_id: 'project-1',
    title: 'Draft on oracle lane',
    paper_status: 'publication_draft',
    review_status: 'triage_ready',
    artifact_paths_present: { evidence_bundle: true, claim_ledger: true, manifest: true },
    age_seconds: 600,
  }],
  page: { returned: 1, has_more: false },
}

export const intakeIdeasFixture = {
  ok: true,
  generated_at: '2026-05-21T12:00:00Z',
  operator_summary: 'One admitted idea is queued for dispatch review.',
  latest_sync: { source: 'supabase', status: 'ok', observed_at: '2026-05-21T11:55:00Z', authority: 'ideas' },
  projection_counts: { queued: 1, admitted: 1 },
  queued_projection: [{
    idea_id: 'idea-operator',
    title: 'Operator Idea',
    idea_status: 'admitted',
    queue_status: 'queued',
    source_kind: 'supabase_idea',
    machine_target: 'gb10',
    project_id: 'project-operator',
    operator_stage: 'ready_queue',
    operator_detail_stage: 'idea_queued',
    operator_next_step: 'Inspect queue placement before dispatch.',
    operator_stage_label: 'Queued for lane',
  }],
  skipped_reasons: { below_threshold: 2 },
  recent_events: [],
}

export const eventListFixture = {
  rows: [{
    event_id: 'evt-1',
    event_type: 'worker_callback.received',
    summary: 'Worker callback received for run-1',
    entity_type: 'run',
    entity_id: 'run-1',
    project_id: 'project-1',
    created_at: '2026-05-21T11:00:00Z',
  }],
  page: { returned: 1, has_more: false },
}
