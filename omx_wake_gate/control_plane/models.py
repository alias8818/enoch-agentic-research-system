from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field

from ..models import utc_now


def idempotency_key_field(prefix: str):
    return Field(default_factory=lambda: f"{prefix}:{utc_now()}")


class OkResponse(BaseModel):
    ok: bool = True


class EventMutationResponse(OkResponse):
    inserted_event: bool = False
    event_id: int | None = None


class DryRunCountResponse(OkResponse):
    dry_run: bool
    inserted_event: bool = False
    created: int = 0
    updated: int = 0
    skipped: int = 0


class QueueStatus(str, Enum):
    QUEUED = "queued"
    DISPATCHING = "dispatching"
    RUNNING = "running"
    AWAITING_WAKE = "awaiting_wake"
    WAKE_RECEIVED = "wake_received"
    RECONCILING = "reconciling"
    COMPLETED = "completed"
    PAUSED = "paused"
    CANCELED = "canceled"
    DISPATCH_ERROR = "dispatch_error"
    BLOCKED = "blocked"
    NEEDS_REVIEW = "needs_review"


class RunState(str, Enum):
    PREPARED = "prepared"
    DISPATCHING = "dispatching"
    RUNNING = "running"
    AWAITING_WAKE = "awaiting_wake"
    QUESTION_PENDING = "question_pending"
    WAKE_READY = "wake_ready"
    SESSION_FINISHED_READY = "session_finished_ready"
    GATE_TIMEOUT = "gate_timeout"
    GATE_ERROR = "gate_error"
    RECONCILED = "reconciled"
    DISPATCH_ERROR = "dispatch_error"


class PaperStatus(str, Enum):
    ELIGIBLE = "eligible"
    DRAFT_GENERATING = "draft_generating"
    DRAFT_REVIEW = "draft_review"
    PUBLICATION_GENERATING = "publication_generating"
    PUBLICATION_DRAFT = "publication_draft"
    HUMAN_REVIEW_REQUIRED = "human_review_required"
    ARCHIVED = "archived"


class ReviewStatus(str, Enum):
    UNREVIEWED = "unreviewed"
    TRIAGE_READY = "triage_ready"
    IN_REVIEW = "in_review"
    CHANGES_REQUESTED = "changes_requested"
    BLOCKED = "blocked"
    APPROVED_FOR_FINALIZATION = "approved_for_finalization"
    FINALIZED = "finalized"
    REJECTED = "rejected"


class ControlFlags(BaseModel):
    queue_paused: bool = True
    maintenance_mode: bool = True
    pause_reason: str = "hard cutover: LangGraph control plane not resumed"
    paused_at: str | None = Field(default_factory=utc_now)
    paused_by: str = "system"
    updated_at: str = Field(default_factory=utc_now)


class PauseRequest(BaseModel):
    reason: str = "operator maintenance"
    paused_by: str = "operator"
    maintenance_mode: bool = True


class ResumeRequest(BaseModel):
    resumed_by: str = "operator"
    maintenance_mode: bool = False


class MarkQueueItemPausedRequest(BaseModel):
    project_id: str
    reason: str = "maintenance/cutover reconciliation: no live worker process remains"
    updated_by: str = "operator"


class NotionIntakeRequest(BaseModel):
    idempotency_key: str = idempotency_key_field("notion-intake")
    source: str = "notion"
    notion_rows: list[dict[str, Any]] = Field(default_factory=list)
    dry_run: bool = True
    include_statuses: list[str] = Field(default_factory=lambda: ["exploring", "testing"])
    default_machine_target: str = "worker.example"
    default_model: str = "gpt-5.5"
    default_sandbox: str = "danger-full-access"


class NotionIntakeResponse(DryRunCountResponse):
    dry_run: bool
    candidates: list[dict[str, Any]] = Field(default_factory=list)
    skipped_rows: list[dict[str, Any]] = Field(default_factory=list)


class ProjectRecord(BaseModel):
    project_id: str
    project_name: str = ""
    project_dir: str = ""
    notion_page_url: str = ""
    origin_idea_status: str = ""
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)


class QueueItemRecord(BaseModel):
    project_id: str
    status: QueueStatus = QueueStatus.QUEUED
    selection_rank: int = 50
    dispatch_priority: int = 50
    auto_continue: bool = True
    continue_count: int = 0
    max_continues: int = 0
    retry_count: int = 0
    max_retries: int = 2
    current_run_id: str = ""
    current_session_id: str = ""
    last_run_state: str = ""
    last_event_type: str = ""
    next_action_hint: str = "controller_review"
    manual_review_required: bool = False
    blocked_reason: str = ""
    last_error: str = ""
    last_result_summary: str = ""
    machine_target: str = "worker.example"
    model: str = "gpt-5.5"
    sandbox: str = "danger-full-access"
    last_dispatch_at: str | None = None
    last_callback_at: str | None = None
    stale_after: str | None = None
    updated_at: str = Field(default_factory=utc_now)


class RunRecord(BaseModel):
    run_id: str
    project_id: str
    session_id: str = ""
    state: RunState = RunState.PREPARED
    dispatch_mode: Literal["exec", "resume"] = "exec"
    started_at: str | None = None
    ended_at: str | None = None
    last_callback_at: str | None = None
    gate_state: str = ""
    current_activity: str = ""
    idempotency_key: str = ""
    updated_at: str = Field(default_factory=utc_now)


class PaperRecord(BaseModel):
    paper_id: str
    project_id: str
    run_id: str = ""
    paper_type: str = "arxiv_draft"
    paper_status: PaperStatus = PaperStatus.DRAFT_REVIEW
    draft_markdown_path: str = ""
    draft_latex_path: str = ""
    evidence_bundle_path: str = ""
    claim_ledger_path: str = ""
    manifest_path: str = ""
    generated_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)


class PaperReviewRecord(BaseModel):
    paper_id: str
    review_status: ReviewStatus = ReviewStatus.UNREVIEWED
    reviewer: str = ""
    blocker: str = ""
    claimed_at: str = ""
    checklist_json: dict[str, Any] = Field(default_factory=dict)
    rank_score: int = 0
    rank_reasons: list[str] = Field(default_factory=list)
    missing_signals: list[str] = Field(default_factory=list)
    rank_tiebreaker: str = ""
    source_audit_path: str = ""
    finalization_package_path: str = ""
    finalized_at: str = ""
    decision_summary: str = ""
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)


class ReviewRankingInput(BaseModel):
    paper: dict[str, Any]
    project: dict[str, Any] = Field(default_factory=dict)
    queue_item: dict[str, Any] = Field(default_factory=dict)
    audit: dict[str, Any] = Field(default_factory=dict)
    review: dict[str, Any] = Field(default_factory=dict)
    missing_signals: list[str] = Field(default_factory=list)


class ReviewQueueItem(BaseModel):
    paper_id: str
    project_id: str = ""
    project_name: str = ""
    paper_status: str = ""
    paper_type: str = ""
    review_status: str = ReviewStatus.UNREVIEWED.value
    checklist_progress: dict[str, int] = Field(default_factory=dict)
    blocker: str = ""
    reviewer: str = ""
    claimed_at: str = ""
    updated_at: str = ""
    rank_score: int = 0
    rank_bucket: str = "review"
    rank_reasons: list[str] = Field(default_factory=list)
    missing_signals: list[str] = Field(default_factory=list)
    rank_tiebreaker: str = ""
    draft_markdown_path: str = ""
    draft_latex_path: str = ""
    evidence_bundle_path: str = ""
    claim_ledger_path: str = ""
    manifest_path: str = ""
    finalization_package_path: str = ""
    finalized_at: str = ""
    decision_summary: str = ""
    links: dict[str, str] = Field(default_factory=dict)


class PaperReviewBackfillRequest(BaseModel):
    idempotency_key: str = idempotency_key_field("paper-review-backfill")
    requested_by: str = "operator"
    source_audit_path: str = ""
    dry_run: bool = True


class PaperReviewBackfillResponse(DryRunCountResponse):
    dry_run: bool
    errors: list[dict[str, Any]] = Field(default_factory=list)


class PaperReviewMutationResponse(EventMutationResponse):
    item: ReviewQueueItem


class PaperReviewClaimRequest(BaseModel):
    idempotency_key: str = idempotency_key_field("paper-review-claim")
    requested_by: str = "operator"
    reviewer: str
    note: str = ""
    clear_blocker: bool = False


class PaperReviewChecklistUpdateRequest(BaseModel):
    idempotency_key: str = idempotency_key_field("paper-review-checklist")
    requested_by: str = "operator"
    status: Literal["pending", "pass", "fail", "accepted_risk", "not_applicable"]
    note: str = ""


class PaperReviewStatusUpdateRequest(BaseModel):
    idempotency_key: str = idempotency_key_field("paper-review-status")
    requested_by: str = "operator"
    review_status: ReviewStatus
    note: str = ""
    blocker: str = ""


class PaperReviewApproveFinalizationRequest(BaseModel):
    idempotency_key: str = idempotency_key_field("paper-review-approval")
    requested_by: str = "operator"
    note: str = ""


class PaperReviewPrepareFinalizationRequest(BaseModel):
    idempotency_key: str = idempotency_key_field("paper-review-package")
    requested_by: str = "operator"
    target_label: str = ""
    dry_run: bool = True


class PaperReviewRewriteDraftRequest(BaseModel):
    idempotency_key: str = idempotency_key_field("paper-review-rewrite")
    requested_by: str = "operator"
    force: bool = True


class PaperReviewRewriteDraftResponse(EventMutationResponse):
    item: ReviewQueueItem | None = None
    paper: dict[str, Any] | None = None
    writer: dict[str, Any] = Field(default_factory=dict)
    artifact_root: str = ""


class PaperReviewBulkRewriteRequest(BaseModel):
    idempotency_key: str = idempotency_key_field("paper-review-bulk-rewrite")
    requested_by: str = "ai-publication-pipeline"
    paper_status: str = "publication_draft"
    review_status: str = ""
    search: str = ""
    limit: int = Field(default=10, ge=1, le=200)
    force: bool = True
    dry_run: bool = False
    skip_rewritten: bool = True


class PaperReviewBulkRewriteResponse(OkResponse):
    dry_run: bool = False
    matched: int = 0
    processed: int = 0
    rewritten: int = 0
    failed: int = 0
    rows: list[dict[str, Any]] = Field(default_factory=list)


class PaperReviewFinalizationPackageResponse(EventMutationResponse):
    dry_run: bool = True
    item: ReviewQueueItem | None = None
    package_path: str = ""
    manifest: dict[str, Any] = Field(default_factory=dict)


class EventRecord(BaseModel):
    event_id: int
    idempotency_key: str
    event_type: str
    entity_type: str
    entity_id: str
    payload: dict[str, Any]
    created_at: str


class ImportSnapshotRequest(BaseModel):
    idempotency_key: str = idempotency_key_field("manual-import")
    source: str = "legacy_n8n"
    queue_rows: list[dict[str, Any]] = Field(default_factory=list)
    paper_rows: list[dict[str, Any]] = Field(default_factory=list)
    # Accept raw wake-gate dashboard snapshot files directly so the migration path
    # does not depend on n8n DataTable export being available during cutover.
    queue_snapshot: dict[str, Any] | list[dict[str, Any]] | None = None
    paper_snapshot: dict[str, Any] | list[dict[str, Any]] | None = None


class ImportSnapshotResponse(OkResponse):
    inserted_event: bool
    imported_projects: int
    imported_queue_items: int
    imported_papers: int


class DispatchNextRequest(BaseModel):
    dry_run: bool = True
    requested_by: str = "operator"
    force_preflight: bool = True


class LiveDispatchResult(BaseModel):
    run_id: str
    project_id: str
    project_dir: str
    prompt_file: str
    prepare: dict[str, Any] = Field(default_factory=dict)
    dispatch: dict[str, Any] = Field(default_factory=dict)
    preflight: WorkerPreflightResponse | None = None


class DispatchNextResponse(BaseModel):
    ok: bool
    action: Literal["paused", "noop", "dry_run_dispatch", "live_dispatch", "dispatch_blocked"]
    reason: str
    candidate: dict[str, Any] | None = None
    active_count: int = 0
    event_id: int | None = None
    live: LiveDispatchResult | None = None


class DraftNextRequest(BaseModel):
    force: bool = False
    requested_by: str = "operator"


class DraftNextResponse(BaseModel):
    ok: bool
    action: Literal["noop", "drafted"]
    reason: str
    paper: PaperRecord | None = None
    candidate: dict[str, Any] | None = None


class WorkerPreflightRequest(BaseModel):
    wake_gate_url: str = "http://worker.example:8787"
    bearer_token: str = ""
    require_paused: bool = True
    strict: bool = False
    max_gpu_pct: float = 5.0
    min_memory_available_mib: int = 16_384


class WorkerPreflightCheck(BaseModel):
    name: str
    ok: bool
    detail: str
    data: dict[str, Any] = Field(default_factory=dict)


class WorkerPreflightResponse(BaseModel):
    ok: bool
    target: str
    summary: str
    checks: list[WorkerPreflightCheck] = Field(default_factory=list)


class DashboardObservationRecord(BaseModel):
    observation_id: int | None = None
    source: Literal["worker_dashboard_api", "worker_preflight", "notion_sync", "snapshot_mirror"]
    scope: str = "global"
    observed_at: str = Field(default_factory=utc_now)
    ttl_seconds: int = 300
    status: Literal["ok", "warn", "error", "unavailable"] = "ok"
    payload: dict[str, Any] = Field(default_factory=dict)
    payload_hash: str = ""
    created_at: str = Field(default_factory=utc_now)


class DashboardFreshness(BaseModel):
    source: str
    authority: str
    observed_at: str | None = None
    ttl_seconds: int | None = None
    fresh_until: str | None = None
    stale: bool = False
    status: str = "missing"
    detail: str = ""


class DashboardFinding(BaseModel):
    severity: Literal["info", "warn", "critical"]
    source: str
    authority: str
    message: str
    observed_at: str | None = None
    suggested_action: str = ""
    data: dict[str, Any] = Field(default_factory=dict)


class DashboardApiResponse(OkResponse):
    generated_at: str = Field(default_factory=utc_now)
    source_freshness: dict[str, DashboardFreshness] = Field(default_factory=dict)
    warnings: list[DashboardFinding] = Field(default_factory=list)
    conflicts: list[DashboardFinding] = Field(default_factory=list)


class DashboardConfigStatus(BaseModel):
    source: Literal["control_plane_config"] = "control_plane_config"
    authority: str = "static operational config"
    live_dispatch_enabled: bool
    worker_wake_gate_url: str
    worker_token_configured: bool
    dispatch_timeout_sec: int
    project_root: str
    state_dir: str
    pushover_alerts_enabled: bool = False
    pushover_configured: bool = False
    queue_alert_cooldown_sec: int = 1800
    queue_alert_hang_after_sec: int = 3600


class DashboardStatusResponse(DashboardApiResponse):
    source: Literal["control_api_status"] = "control_api_status"
    authority: str = "aggregated read model"
    flags: ControlFlags
    config: DashboardConfigStatus
    counts: dict[str, int]
    active_items: list[dict[str, Any]]
    next_candidate: dict[str, Any] | None = None
    dispatch_safe: bool = False
    dispatch_blockers: list[str] = Field(default_factory=list)
    observations: dict[str, DashboardObservationRecord | None] = Field(default_factory=dict)
    recent_events: list[EventRecord] = Field(default_factory=list)


class DashboardPageMeta(BaseModel):
    page: int = 1
    page_size: int = 50
    total: int = 0
    returned: int = 0
    queue: str = ""
    filters: dict[str, Any] = Field(default_factory=dict)
    sort: str = ""


class DashboardQueueResponse(DashboardApiResponse):
    source: Literal["control_api_queue"] = "control_api_queue"
    authority: str = "control_plane_db queue read model"
    queue: str
    page: DashboardPageMeta
    counts: dict[str, int] = Field(default_factory=dict)
    rows: list[dict[str, Any]] = Field(default_factory=list)


class DashboardProjectDetailResponse(DashboardApiResponse):
    source: Literal["control_api_project"] = "control_api_project"
    authority: str = "control_plane_db project aggregate"
    project_id: str
    project: dict[str, Any] | None = None
    queue_item: dict[str, Any] | None = None
    runs: list[dict[str, Any]] = Field(default_factory=list)
    papers: list[dict[str, Any]] = Field(default_factory=list)
    events: list[dict[str, Any]] = Field(default_factory=list)
    worker_observations: dict[str, DashboardObservationRecord | None] = Field(default_factory=dict)


class DashboardRunDetailResponse(DashboardApiResponse):
    source: Literal["control_api_run"] = "control_api_run"
    authority: str = "control_plane_db run aggregate plus cached worker evidence"
    run_id: str
    run: dict[str, Any] | None = None
    queue_item: dict[str, Any] | None = None
    project: dict[str, Any] | None = None
    papers: list[dict[str, Any]] = Field(default_factory=list)
    events: list[dict[str, Any]] = Field(default_factory=list)
    worker_observations: dict[str, DashboardObservationRecord | None] = Field(default_factory=dict)


class DashboardPapersResponse(DashboardApiResponse):
    source: Literal["control_api_papers"] = "control_api_papers"
    authority: str = "control_plane_db paper read model"
    page: DashboardPageMeta
    counts: dict[str, int] = Field(default_factory=dict)
    rows: list[dict[str, Any]] = Field(default_factory=list)


class DashboardPaperReviewsResponse(DashboardApiResponse):
    source: Literal["control_api_paper_reviews"] = "control_api_paper_reviews"
    authority: str = "control_plane_db paper review read model"
    page: DashboardPageMeta
    counts: dict[str, int] = Field(default_factory=dict)
    rows: list[ReviewQueueItem] = Field(default_factory=list)


class DashboardPaperReviewDetailResponse(DashboardApiResponse):
    source: Literal["control_api_paper_review"] = "control_api_paper_review"
    authority: str = "control_plane_db paper review aggregate"
    paper_id: str
    item: ReviewQueueItem
    checklist: dict[str, Any] = Field(default_factory=dict)
    paper: dict[str, Any] | None = None
    project: dict[str, Any] | None = None
    events: list[dict[str, Any]] = Field(default_factory=list)


class DashboardPaperDetailResponse(DashboardApiResponse):
    source: Literal["control_api_paper"] = "control_api_paper"
    authority: str = "control_plane_db paper aggregate"
    paper_id: str
    paper: dict[str, Any] | None = None
    project: dict[str, Any] | None = None
    run: dict[str, Any] | None = None
    events: list[dict[str, Any]] = Field(default_factory=list)


class DashboardEventsResponse(DashboardApiResponse):
    source: Literal["control_api_events"] = "control_api_events"
    authority: str = "control_plane_db event log"
    page: DashboardPageMeta
    rows: list[dict[str, Any]] = Field(default_factory=list)


class DashboardIntakeResponse(DashboardApiResponse):
    source: Literal["control_api_intake_notion"] = "control_api_intake_notion"
    authority: str = "Notion intake/review projection plus latest sync observation"
    latest_sync: DashboardObservationRecord | None = None
    projection_counts: dict[str, int] = Field(default_factory=dict)
    queued_projection: list[dict[str, Any]] = Field(default_factory=list)
    skipped_reasons: dict[str, int] = Field(default_factory=dict)
    recent_events: list[dict[str, Any]] = Field(default_factory=list)


class ControlStateResponse(OkResponse):
    flags: ControlFlags
    counts: dict[str, int]
    active_items: list[dict[str, Any]]
    next_candidate: dict[str, Any] | None = None
    recent_events: list[EventRecord] = Field(default_factory=list)


class ProjectionResponse(OkResponse):
    generated_at: str = Field(default_factory=utc_now)
    rows: list[dict[str, Any]]
    counts: dict[str, int] = Field(default_factory=dict)


class ExportSnapshotResponse(OkResponse):
    generated_at: str = Field(default_factory=utc_now)
    source: str = "langgraph_control_plane"
    flags: ControlFlags
    queue_rows: list[dict[str, Any]]
    paper_rows: list[dict[str, Any]]
    events: list[EventRecord] = Field(default_factory=list)
