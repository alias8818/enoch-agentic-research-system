"""Static control-plane HTTP route bindings.

This module replaces the previous exec-of-source-string route registration path.
The functions below are generated from the former binding blocks but are real
Python source so ruff, pyright, coverage, semgrep, traceback formatting, and
code search can see them. Runtime dependencies are injected from router.py via
the namespace mapping passed to each registration function.
"""

from __future__ import annotations

from typing import Any, MutableMapping
import inspect

# Runtime-injected names. They are populated by _sync_namespace() before each
# binding block runs; declarations keep static analyzers aware of the symbols
# formerly hidden inside exec strings.
asyncio: Any = None
Annotated: Any = None
Body: Any = None
CONTROL_PLANE_DB_WORKER_PREFLIGHT_SOURCE: Any = None
CROSS_SOURCE_ACTIVE_LANE_RECONCILIATION_AUTHORITY: Any = None
ControlStateResponse: Any = None
DASHBOARD_V2_DIST_PATH: Any = None
DEFAULT_ALLOWED_RESEARCH_MODELS: Any = None
DEFAULT_AUTOPILOT_HISTORY_PATH: Any = None
DEFAULT_MACHINE_TARGET: Any = None
DEFAULT_REPORT_PATHS: Any = None
DEFAULT_RESEARCH_PROVIDER_BASE_URL: Any = None
DEFAULT_SOURCE_LINEAGE_REPORT_PATH: Any = None
DEFAULT_WINDOW_REPORT_PATH: Any = None
DashboardConfigStatus: Any = None
DashboardEventsResponse: Any = None
DashboardFinding: Any = None
DashboardFreshness: Any = None
DashboardIntakeResponse: Any = None
DashboardObservationRecord: Any = None
DashboardPageMeta: Any = None
DashboardPaperDetailResponse: Any = None
DashboardPaperReviewDetailResponse: Any = None
DashboardPaperReviewsResponse: Any = None
DashboardPapersResponse: Any = None
DashboardProjectDetailResponse: Any = None
DashboardQueueResponse: Any = None
DashboardRunDetailResponse: Any = None
DashboardStatusResponse: Any = None
DispatchNextRequest: Any = None
DispatchNextResponse: Any = None
DispatchOneRequest: Any = None
DraftNextRequest: Any = None
DraftNextResponse: Any = None
ExportSnapshotResponse: Any = None
FollowupLaunchRequest: Any = None
FollowupLaunchResponse: Any = None
GateCallback: Any = None
GateConfig: Any = None
HTMLResponse: Any = None
HTTPException: Any = None
Header: Any = None
IdeaIntakeRequest: Any = None
IdeaIntakeResponse: Any = None
IdempotencyConflict: Any = None
ImportSnapshotRequest: Any = None
ImportSnapshotResponse: Any = None
LEGACY_NOTION_API_REPLACEMENT_PATH: Any = None
LegacyNotionApiDisabledError: Any = None
MarkQueueItemPausedRequest: Any = None
Namespace: Any = None
NotionIntakeRequest: Any = None
NotionIntakeResponse: Any = None
OperatorTrace: Any = None
PAPER_REVIEW_DRAFT_REWRITTEN: Any = None
PUBLICATION_AUTOMATION_ITEM_NOT_FOUND: Any = None
PaperArtifactRootError: Any = None
PaperArtifactRootNotInspectableError: Any = None
PaperArtifactSnapshotReadError: Any = None
PaperReviewApproveFinalizationRequest: Any = None
PaperReviewBackfillRequest: Any = None
PaperReviewBackfillResponse: Any = None
PaperReviewBulkRewriteRequest: Any = None
PaperReviewBulkRewriteResponse: Any = None
PaperReviewChecklistUpdateRequest: Any = None
PaperReviewClaimRequest: Any = None
PaperReviewFinalizationPackageResponse: Any = None
PaperReviewMutationResponse: Any = None
PaperReviewPrepareFinalizationRequest: Any = None
PaperReviewRewriteDraftRequest: Any = None
PaperReviewRewriteDraftResponse: Any = None
PaperReviewStatusUpdateRequest: Any = None
PaperRewriteBlockedReviewStatusError: Any = None
PaperRewriteEvidenceRequiredError: Any = None
PaperRewriteIdempotencyReuseError: Any = None
PaperStatus: Any = None
Path: Any = None
PauseRequest: Any = None
ProjectionResponse: Any = None
PublicationAutomationNotFoundError: Any = None
Query: Any = None
RESEARCH_FACILITY_LEDGER_REQUIRES_SUPABASE_STORE: Any = None
RedirectResponse: Any = None
Response: Any = None
ResumeRequest: Any = None
SUPABASE_NATIVE_IDEAS_WORKBENCH_AUTHORITY: Any = None
UnresolvableConfiguredProjectRootError: Any = None
WakeGateUrlNotAllowedError: Any = None
WorkerPreflightRequest: Any = None
WorkerPreflightResponse: Any = None
WorkerPreflightUrlNotConfiguredError: Any = None
_DEFAULT_RESEARCH_MODEL: Any = None
_HTTP_400_PREFLIGHT_WAKE_GATE: Any = None
_HTTP_400_RESEARCH_CANDIDATE_ID: Any = None
_HTTP_404_DASHBOARD_ASSET: Any = None
_HTTP_404_PAPER: Any = None
_HTTP_404_PAPER_DETAIL: Any = None
_HTTP_404_PROJECT: Any = None
_HTTP_404_PUBLICATION_AUTOMATION_NEXT: Any = None
_HTTP_404_RUN: Any = None
_HTTP_410_LEGACY_NOTION_API: Any = None
_HTTP_500_UNRESOLVABLE_ARTIFACT_ROOT: Any = None
_HTTP_501_SUPABASE_LEDGER: Any = None
_HTTP_501_WRITABLE_STORE: Any = None
_HTTP_503_DASHBOARD_V2: Any = None
_HTTP_503_WORKER_PREFLIGHT_URL: Any = None
_HTTP_DISPATCH_ONE_RESPONSES: Any = None
_HTTP_MARK_QUEUE_ITEM_PAUSED_RESPONSES: Any = None
_HTTP_NOTION_INTAKE_RESPONSES: Any = None
_HTTP_PAPER_REVIEW_MUTATION_RESPONSES: Any = None
_HTTP_PUBLICATION_AUTOMATION_DETAIL_RESPONSES: Any = None
_HTTP_WRITABLE_IDEMPOTENCY_RESPONSES: Any = None
_LiveResearchCycleParams: Any = None
_PAPER_REWRITE_DRAFT_RESPONSES: Any = None
_ROUTER_GATE_CONFIG: Any = None
_ResearchCycleInitialResponseParams: Any = None
_active_items_fast: Any = None
_annotate_dispatch_route: Any = None
_append_dashboard_active_lane_findings: Any = None
_append_dashboard_control_flag_findings: Any = None
_append_dashboard_dispatch_lane_blockers: Any = None
_append_dashboard_observation_freshness_findings: Any = None
_append_dashboard_preflight_runtime_findings: Any = None
_append_dashboard_worker_lane_confirmation_findings: Any = None
_append_research_cycle_queue_paused_guardrail: Any = None
_artifact_root_for_queue_row: Any = None
_auto_reconcile_stale_callback_ready: Any = None
_automation_readiness_payload: Any = None
_automation_timer_snapshot: Any = None
_bounded_float_from_mapping: Any = None
_bounded_int_env: Any = None
_bounded_int_from_mapping: Any = None
_budget_endpoint_diagnostics: Any = None
_build_research_cycle_initial_response: Any = None
_cached_observation_freshness: Any = None
_callback_acceptance_token_fingerprint: Any = None
_candidate_machine_target_conflict_set: Any = None
_candidate_project_dir: Any = None
_classify_queue: Any = None
_collect_research_cycle_stop_reasons: Any = None
_commit_paper_rewrite_draft: Any = None
_compact_worker_dashboard_check_payload: Any = None
_compact_worker_preflight_payload: Any = None
_compute_janitor_report: Any = None
_compute_promotable_rows: Any = None
_compute_research_lane_feed_pressure: Any = None
_config_status: Any = None
_configured_worker_lanes: Any = None
_configured_worker_preflight_url: Any = None
_cp_active_items_fast: Any = None
_cp_mount_annotate_dispatch_route: Any = None
_cp_mount_callback_acceptance_token_fingerprint: Any = None
_cp_mount_candidate_machine_target_conflict_set: Any = None
_cp_mount_configured_worker_lanes: Any = None
_cp_mount_has_conflicting_active_lane: Any = None
_cp_mount_open_worker_dispatch_candidate: Any = None
_cp_mount_preflight_observation_applies_to_candidate: Any = None
_cp_mount_preflight_observation_lane_key: Any = None
_cp_mount_worker_lane_capacity: Any = None
_cp_mount_worker_lane_key: Any = None
_cp_queued_dispatch_candidates: Any = None
_cp_queued_items_fast: Any = None
_cp_recently_completed_items_fast: Any = None
_dashboard_ideas_intake_response: Any = None
_dashboard_next_paper_review_response: Any = None
_dashboard_paper_reviews_response: Any = None
_dashboard_status_source_freshness: Any = None
_dashboard_worker_preflight_context: Any = None
_db_freshness: Any = None
_default_worker_url_key: Any = None
_detail_conflicts: Any = None
_dispatch_gates_allow_live: Any = None
_dispatch_route_metadata: Any = None
_enrich_queue_row: Any = None
_evaluate_research_cycle_backpressure: Any = None
_evidence_sync_skipped_by_gate: Any = None
_execute_live_dispatch: Any = None
_execute_live_research_cycle: Any = None
_expanduser_path_or_http: Any = None
_fetch_dashboard_status_observations: Any = None
_fetch_synthetic_research_budget: Any = None
_fresh_until: Any = None
_freshness_for_observation: Any = None
_has_conflicting_active_lane: Any = None
_has_symlink_component: Any = None
_ideas_intake_empty_projection_warnings: Any = None
_ideas_intake_prepare_latest: Any = None
_ideas_intake_resolve_parts: Any = None
_intake_freshness: Any = None
_is_stale: Any = None
_latest_dashboard_observation_metadata: Any = None
_live_dispatch: Any = None
_local_artifact_root_http: Any = None
_local_paper_evidence_present: Any = None
_normal_status: Any = None
_open_worker_dispatch_candidate: Any = None
_operator_trace_queue_findings: Any = None
_paginate: Any = None
_paper_counts: Any = None
_paper_record_from_candidate: Any = None
_paper_record_from_store_row: Any = None
_paper_review_detail_response: Any = None
_paper_rewrite_candidate_payload: Any = None
_paper_rewrite_idempotent_response: Any = None
_paper_rewrite_rows_or_404: Any = None
_parse_ts: Any = None
_pause_automation_for_control_pause: Any = None
_pre_evidence_paper_decision_gate: Any = None
_preflight_check: Any = None
_preflight_observation_applies_to_candidate: Any = None
_preflight_observation_lane_key: Any = None
_preflight_targets_default_worker: Any = None
_prepare_draft_evidence: Any = None
_project_events: Any = None
_provider_budget_for_readiness: Any = None
_queue_counts: Any = None
_queue_rows_for_lane_feed: Any = None
_queued_dispatch_candidates: Any = None
_queued_items_fast: Any = None
_recent_worker_settling_without_vm_match: Any = None
_recently_completed_items_fast: Any = None
_record_paper_evidence_blocked: Any = None
_record_preflight_observations: Any = None
_refresh_worker_observations_if_needed: Any = None
_require_legacy_notion_api_enabled: Any = None
_require_safe_paper_artifact_root: Any = None
_require_writable_store: Any = None
_require_writable_store_http: Any = None
_research_cycle_idle_queued_lane_available: Any = None
_research_cycle_pre_live_exit: Any = None
_research_lane_feed_pressure: Any = None
_research_quality_payload: Any = None
_research_row_lane_key: Any = None
_resolve_paper_artifact: Any = None
_resolve_paper_rewrite_artifact_root: Any = None
_resolve_research_cycle_params: Any = None
_resolve_research_provider_model: Any = None
_resolve_synthetic_budget_provider: Any = None
_review_counts: Any = None
_rewrite_paper_review_draft: Any = None
_row_age_seconds: Any = None
_search_rows: Any = None
_select_generation_target_lane: Any = None
_snapshot_paper_rewrite_artifacts: Any = None
_sort_rows: Any = None
_source_lineage_payload: Any = None
_sync_remote_project_evidence: Any = None
_synthetic_budget_auth_mode: Any = None
_synthetic_budget_base_url: Any = None
_synthetic_budget_request_api_key: Any = None
_systemctl_show: Any = None
_target_aware_preflight_payload: Any = None
_truthy_flag: Any = None
_validate_research_candidate_id: Any = None
_worker_dashboard_body_from_preflight: Any = None
_worker_detail_freshness: Any = None
_worker_detail_observations: Any = None
_worker_evidence_sync_kwargs_for_row: Any = None
_worker_lane_capacity: Any = None
_worker_lane_key: Any = None
_worker_observations_need_refresh: Any = None
_worker_settling_after_vm_completion: Any = None
action: Any = None
active: Any = None
active_for_lanes: Any = None
active_lane_keys: Any = None
active_limit: Any = None
active_on_default_worker: Any = None
alert: Any = None
all_configured_lanes_active: Any = None
all_counts: Any = None
all_rows: Any = None
allow_worker_refresh: Any = None
allowed: Any = None
allowed_models: Any = None
allowed_urls: Any = None
artifact_gate: Any = None
artifact_readable: Any = None
artifact_root: Any = None
artifact_snapshots: Any = None
asset_path: Any = None
asset_root: Any = None
authority: Any = None
authorization: Any = None
authorize: Any = None
auto_reconcile: Any = None
backend: Any = None
backfill_created: Any = None
backfill_errors: Any = None
backfill_inserted: Any = None
backfill_skipped: Any = None
backfill_updated: Any = None
backpressure_reasons: Any = None
base_url: Any = None
blocked_count: Any = None
blocked_rows: Any = None
blockers: Any = None
body: Any = None
bounded_float: Any = None
bounded_int: Any = None
bounded_useful_signal_row_gate: Any = None
budget: Any = None
budget_base_url: Any = None
budget_endpoint: Any = None
budget_timeout: Any = None
callback: Any = None
callback_run_id: Any = None
candidate: Any = None
candidate_for_write: Any = None
candidate_id: Any = None
candidate_root: Any = None
candidates: Any = None
cfg: Any = None
check: Any = None
classify_low_utilization_runs: Any = None
cmd: Any = None
config: Any = None
configured: Any = None
configured_lane_keys: Any = None
configured_worker: Any = None
conflicts: Any = None
control_reports_active: Any = None
counts: Any = None
created: Any = None
current_rss_mib: Any = None
cursor: Any = None
dashboard: Any = None
dashboard_check: Any = None
dashboard_events: Any = None
dashboard_ideas_intake: Any = None
dashboard_next_paper_review: Any = None
dashboard_next_publication_automation: Any = None
dashboard_notion_intake: Any = None
dashboard_paper: Any = None
dashboard_paper_artifact: Any = None
dashboard_paper_review: Any = None
dashboard_paper_review_approve_finalization: Any = None
dashboard_paper_review_checklist: Any = None
dashboard_paper_review_claim: Any = None
dashboard_paper_review_prepare_finalization_package: Any = None
dashboard_paper_review_rewrite_draft: Any = None
dashboard_paper_review_status: Any = None
dashboard_paper_reviews: Any = None
dashboard_paper_reviews_backfill: Any = None
dashboard_paper_reviews_rewrite_batch: Any = None
dashboard_papers: Any = None
dashboard_payload: Any = None
dashboard_preflight: Any = None
dashboard_project: Any = None
dashboard_publication_automation: Any = None
dashboard_publication_automation_item: Any = None
dashboard_queue: Any = None
dashboard_queue_alert_check: Any = None
dashboard_queue_health: Any = None
dashboard_research_facility: Any = None
dashboard_research_generate_batch: Any = None
dashboard_research_generate_provider_batch: Any = None
dashboard_research_promote_candidate: Any = None
dashboard_research_provider_budget: Any = None
dashboard_research_run_cycle: Any = None
dashboard_run: Any = None
dashboard_status: Any = None
dashboard_status_response: Any = None
dashboard_v1_automation_readiness: Any = None
dashboard_v1_events: Any = None
dashboard_v1_lanes: Any = None
dashboard_v1_observability_health: Any = None
dashboard_v1_observability_memory: Any = None
dashboard_v1_overview: Any = None
dashboard_v1_paper_detail: Any = None
dashboard_v1_papers: Any = None
dashboard_v1_project_detail: Any = None
dashboard_v1_projects: Any = None
dashboard_v1_queue: Any = None
dashboard_v1_research_quality: Any = None
dashboard_v1_run_detail: Any = None
dashboard_v1_runs: Any = None
dashboard_v1_source_lineage: Any = None
dashboard_v2: Any = None
dashboard_v2_asset: Any = None
data: Any = None
datetime: Any = None
db_path: Any = None
decision_gate: Any = None
decision_record: Any = None
decision_sync: Any = None
default_lane_key: Any = None
default_worker_lane: Any = None
dispatch_next: Any = None
dispatch_one: Any = None
dispatch_safe: Any = None
draft_candidate_payload: Any = None
draft_next: Any = None
dry_candidate: Any = None
dry_run: Any = None
early_response: Any = None
eligible_paper_draft_candidates: Any = None
enabled: Any = None
entity_id: Any = None
entity_type: Any = None
errors: Any = None
estimated_requests: Any = None
evaluate_and_notify_queue_alerts: Any = None
evaluate_longhaul_readiness: Any = None
event_cursor: Any = None
event_id: Any = None
event_limit: Any = None
event_more: Any = None
event_type: Any = None
events: Any = None
evidence: Any = None
evidence_sync: Any = None
exc: Any = None
export_snapshot: Any = None
failed: Any = None
field: Any = None
flags: Any = None
fresh_generation_backlog_threshold: Any = None
freshness: Any = None
generated: Any = None
generated_candidates: Any = None
generation_attempts: Any = None
generation_max_tokens: Any = None
generation_target_lane: Any = None
generation_timeout: Any = None
get_state: Any = None
global_observation: Any = None
group: Any = None
groups: Any = None
handle: Any = None
has_critical: Any = None
has_more: Any = None
health: Any = None
ideas_workbench_projection: Any = None
idle_queued_lane_available: Any = None
import_snapshot: Any = None
include_latest_payload: Any = None
include_payload: Any = None
include_rank_reasons: Any = None
index: Any = None
index_path: Any = None
initial_feed_lanes: Any = None
initial_open_lane_promotable: Any = None
initial_promotable: Any = None
inserted: Any = None
intake_ideas: Any = None
intake_notion_ideas: Any = None
is_sentry_enabled: Any = None
item: Any = None
item_id: Any = None
janitor_enabled: Any = None
janitor_limit: Any = None
janitor_report: Any = None
jsonable_encoder: Any = None
key: Any = None
key_name: Any = None
lane: Any = None
lane_feed_pressure: Any = None
lane_key: Any = None
lanes: Any = None
latest: Any = None
latest_route_observation: Any = None
launch_next_followup: Any = None
launcher: Any = None
legacy_finalize_positive: Any = None
legacy_notion_alias: Any = None
line: Any = None
live: Any = None
live_dispatch_open: Any = None
llm_model_health: Any = None
load_latest_quality_status: Any = None
load_latest_source_lineage_status: Any = None
local_evidence_present: Any = None
machine_target: Any = None
manifest: Any = None
manual_review: Any = None
mark_queue_item_paused: Any = None
matched: Any = None
max_bytes: Any = None
max_candidates: Any = None
max_dispatches: Any = None
max_paper_drafts: Any = None
max_promotions: Any = None
max_provider_requests: Any = None
max_publication_rewrites: Any = None
max_wait_seconds: Any = None
media_type: Any = None
mimetypes: Any = None
min_admission_score: Any = None
min_queue_depth: Any = None
min_queue_depth_per_lane: Any = None
min_remaining_credits: Any = None
min_rolling_remaining: Any = None
missing: Any = None
model_resolution: Any = None
name: Any = None
needle: Any = None
next_candidate: Any = None
next_cursor: Any = None
no_live: Any = None
notion_execution_updates_projection: Any = None
notion_papers_projection: Any = None
notion_queue_projection: Any = None
observation: Any = None
observations: Any = None
open_candidate: Any = None
open_lane_research_rows: Any = None
open_lane_research_rows_local: Any = None
open_worker_candidate: Any = None
operator_trace: Any = None
original_project_dir: Any = None
original_record: Any = None
os: Any = None
out: Any = None
out_rows: Any = None
overview: Any = None
overview_min_admission_score: Any = None
package_path: Any = None
page: Any = None
page_rows: Any = None
page_size: Any = None
paper: Any = None
paper_counts: Any = None
paper_cursor: Any = None
paper_draft_decision_gate: Any = None
paper_event_payload: Any = None
paper_id: Any = None
paper_more: Any = None
paper_status: Any = None
papers: Any = None
params: Any = None
parsed: Any = None
partial: Any = None
path: Any = None
paths: Any = None
pause: Any = None
pause_event_id: Any = None
payload: Any = None
peak: Any = None
peak_rss_mib: Any = None
pid: Any = None
plan: Any = None
plan_json: Any = None
plans: Any = None
poll_interval_seconds: Any = None
post_sync_decision_gate: Any = None
preflight: Any = None
preflight_applies: Any = None
preflight_applies_to_open_candidate: Any = None
preflight_lane: Any = None
preflight_payload: Any = None
preflight_targets_default_worker: Any = None
project: Any = None
project_dir: Any = None
project_dir_text: Any = None
project_id: Any = None
projection: Any = None
projection_counts: Any = None
projects: Any = None
promotable: Any = None
promotable_rows: Any = None
promotion_batch_limit: Any = None
prop: Any = None
properties: Any = None
provider_api_key: Any = None
provider_base_url: Any = None
provider_id: Any = None
provider_model: Any = None
provider_openai_base_url: Any = None
queue: Any = None
queue_counts: Any = None
queue_item: Any = None
queue_items: Any = None
queue_label: Any = None
queue_total: Any = None
queued: Any = None
queued_for_lanes: Any = None
quota_payload: Any = None
raw_candidate: Any = None
raw_path: Any = None
read_llm_settings: Any = None
read_models: Any = None
readiness: Any = None
reason: Any = None
recent: Any = None
recent_events: Any = None
record: Any = None
record_ideas_observation: Any = None
record_notion_observation: Any = None
record_paper_draft: Any = None
records: Any = None
refresh_worker: Any = None
refreshed: Any = None
replay: Any = None
request_payload: Any = None
requested_by: Any = None
requested_url: Any = None
require_bearer: Any = None
research_facility: Any = None
research_facility_scan: Any = None
research_provider_budget: Any = None
research_provider_generate: Any = None
research_row_lane_key: Any = None
reserve_requests: Any = None
resolved: Any = None
resource_findings: Any = None
resource_utilization_status: Any = None
response: Any = None
response_candidate: Any = None
result: Any = None
resume: Any = None
reverse: Any = None
review_status: Any = None
rewritten: Any = None
router: Any = None
row: Any = None
row_gate: Any = None
row_last_run_state: Any = None
row_run_id: Any = None
rows: Any = None
rss: Any = None
run: Any = None
run_cursor: Any = None
run_cycle_id: Any = None
run_id: Any = None
run_item: Any = None
run_more: Any = None
run_row: Any = None
run_worker_preflight: Any = None
runs: Any = None
safe_budget: Any = None
safe_budget_keys: Any = None
safe_keys: Any = None
safe_page: Any = None
safe_root: Any = None
safe_size: Any = None
scope: Any = None
scoped: Any = None
scoped_payload: Any = None
search: Any = None
seed: Any = None
selected: Any = None
services: Any = None
settings: Any = None
settling_blocker: Any = None
settling_message: Any = None
settling_without_match: Any = None
should_refresh_worker: Any = None
should_sync_decision: Any = None
size: Any = None
size_bytes: Any = None
skipped: Any = None
skipped_reasons: Any = None
skipped_rows: Any = None
snapshot: Any = None
sort: Any = None
source: Any = None
source_freshness: Any = None
source_project_dir: Any = None
source_specs: Any = None
spec: Any = None
stale: Any = None
start: Any = None
state: Any = None
state_response: Any = None
status: Any = None
status_min_admission_score: Any = None
stop_reasons: Any = None
store: Any = None
subprocess: Any = None
summarize_lane_snapshot: Any = None
summary_reader: Any = None
systemd: Any = None
target: Any = None
temperature: Any = None
timeout: Any = None
timers: Any = None
timezone: Any = None
topic: Any = None
trace_id: Any = None
truncated: Any = None
ts: Any = None
unit: Any = None
updated: Any = None
updated_candidate: Any = None
urlparse: Any = None
use_current_dir: Any = None
utc_now: Any = None
v: Any = None
value: Any = None
wait_for_completion: Any = None
warn_threshold: Any = None
warnings: Any = None
worker_callback: Any = None
worker_ctx: Any = None
worker_dashboard: Any = None
worker_host: Any = None
worker_lane_limit: Any = None
worker_lanes: Any = None
worker_live_matches_active: Any = None
worker_observations: Any = None
worker_preflight: Any = None
worker_reports_idle: Any = None
worker_settling: Any = None
worker_settling_after_vm_completion: Any = None
worker_url: Any = None
write_paper_artifacts: Any = None
writer: Any = None

_BINDING_ENTRYPOINTS = {
    "_prepare_control_plane_http_bindings_core",
    "_prepare_control_plane_http_bindings_dashboard",
    "_prepare_control_plane_http_bindings_dispatch",
    "_prepare_control_plane_http_bindings_publication",
    "_register_control_plane_dashboard_shell_routes",
    "_register_control_plane_dashboard_v1_routes",
    "_register_control_plane_api_read_routes",
    "_register_control_plane_publication_routes",
    "_register_control_plane_papers_events_routes",
    "_register_control_plane_research_routes",
    "_register_control_plane_operator_legacy_routes",
}


class _RouterGlobalProxy:
    """Late-bound callable proxy for router.py globals that tests may patch."""

    __slots__ = ("_module_globals", "_name")

    def __init__(self, module_globals: dict[str, Any], name: str) -> None:
        self._module_globals = module_globals
        self._name = name

    def _target(self) -> Any:
        return self._module_globals[self._name]

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return self._target()(*args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._target(), name)


def _sync_namespace(ns: MutableMapping[str, Any]) -> None:
    module_globals = getattr(ns, "_module_globals", None)
    if isinstance(module_globals, dict):
        globals().update(
            {
                key: _RouterGlobalProxy(module_globals, key)
                if inspect.isfunction(value)
                else value
                for key, value in module_globals.items()
                if key not in _BINDING_ENTRYPOINTS
            }
        )
    globals().update(dict(ns))


def _export_namespace(ns: MutableMapping[str, Any], names: tuple[str, ...]) -> None:
    module_globals = globals()
    ns.update({name: module_globals[name] for name in names if name in module_globals})


def _prepare_control_plane_http_bindings_core(ns: MutableMapping[str, Any]) -> None:
    global \
        _active_items_fast, \
        _annotate_dispatch_route, \
        _callback_acceptance_token_fingerprint, \
        _candidate_machine_target_conflict_set, \
        _configured_worker_lanes, \
        _has_conflicting_active_lane, \
        _open_worker_dispatch_candidate, \
        _preflight_observation_applies_to_candidate
    global \
        _preflight_observation_lane_key, \
        _queue_rows_for_lane_feed, \
        _queued_dispatch_candidates, \
        _queued_items_fast, \
        _recently_completed_items_fast, \
        _require_writable_store, \
        _research_lane_feed_pressure, \
        _worker_lane_capacity
    global _worker_lane_key, authorize
    _sync_namespace(ns)

    def authorize(authorization: str | None) -> None:
        require_bearer(authorization)

    _require_writable_store = partial(
        _require_writable_store_http, backend=config.control_plane_store_backend
    )

    _worker_lane_key = partial(_cp_mount_worker_lane_key, config)
    _annotate_dispatch_route = partial(_cp_mount_annotate_dispatch_route, config=config)
    _preflight_observation_lane_key = partial(
        _cp_mount_preflight_observation_lane_key, config
    )
    _preflight_observation_applies_to_candidate = partial(
        _cp_mount_preflight_observation_applies_to_candidate, config
    )
    _callback_acceptance_token_fingerprint = partial(
        _cp_mount_callback_acceptance_token_fingerprint, config
    )
    _active_items_fast = partial(_cp_active_items_fast, store)
    _queued_items_fast = partial(_cp_queued_items_fast, store)
    _recently_completed_items_fast = partial(_cp_recently_completed_items_fast, store)
    _queued_dispatch_candidates = partial(_cp_queued_dispatch_candidates, store)
    _open_worker_dispatch_candidate = partial(
        _cp_mount_open_worker_dispatch_candidate, store, config
    )
    _configured_worker_lanes = partial(_cp_mount_configured_worker_lanes, config)
    _worker_lane_capacity = partial(_cp_mount_worker_lane_capacity, config, store)
    _candidate_machine_target_conflict_set = partial(
        _cp_mount_candidate_machine_target_conflict_set, config
    )
    _has_conflicting_active_lane = partial(
        _cp_mount_has_conflicting_active_lane, config, store
    )

    def _queue_rows_for_lane_feed() -> list[dict[str, Any]]:
        if hasattr(store, "queued_items_sql"):
            try:
                return store.queued_items_sql(limit=200)  # type: ignore[attr-defined]
            except TypeError:
                return store.queued_items_sql()  # type: ignore[attr-defined]
        if hasattr(store, "queue_rows"):
            return _queued_dispatch_candidates(store.queue_rows())
        return []

    def _research_lane_feed_pressure(
        *,
        active: list[dict[str, Any]],
        queued: list[dict[str, Any]] | None,
        lanes: list[dict[str, Any]] | None = None,
        promotable: list[dict[str, Any]] | None = None,
        min_queue_depth: int = 1,
        min_admission_score: float = 72.0,
    ) -> dict[str, dict[str, Any]]:
        # Thin local wrapper after top-level extraction.
        return _compute_research_lane_feed_pressure(
            active=active,
            queued=queued,
            lanes=lanes,
            promotable=promotable,
            min_queue_depth=min_queue_depth,
            min_admission_score=min_admission_score,
            _worker_lane_capacity=_worker_lane_capacity,
            _queue_rows_for_lane_feed=_queue_rows_for_lane_feed,
            _queued_dispatch_candidates=_queued_dispatch_candidates,
            _worker_lane_key=_worker_lane_key,
            store=store,
        )

    _export_namespace(
        ns,
        (
            "_active_items_fast",
            "_annotate_dispatch_route",
            "_callback_acceptance_token_fingerprint",
            "_candidate_machine_target_conflict_set",
            "_configured_worker_lanes",
            "_has_conflicting_active_lane",
            "_open_worker_dispatch_candidate",
            "_preflight_observation_applies_to_candidate",
            "_preflight_observation_lane_key",
            "_queue_rows_for_lane_feed",
            "_queued_dispatch_candidates",
            "_queued_items_fast",
            "_recently_completed_items_fast",
            "_require_writable_store",
            "_research_lane_feed_pressure",
            "_worker_lane_capacity",
            "_worker_lane_key",
            "authorize",
        ),
    )


def _prepare_control_plane_http_bindings_dashboard(
    ns: MutableMapping[str, Any],
) -> None:
    global \
        _append_dashboard_control_flag_findings, \
        _append_dashboard_dispatch_lane_blockers, \
        _automation_readiness_payload, \
        _automation_timer_snapshot, \
        _config_status, \
        _dashboard_status_source_freshness, \
        _dispatch_gates_allow_live, \
        _fetch_dashboard_status_observations
    global \
        _freshness_for_observation, \
        _live_dispatch, \
        _provider_budget_for_readiness, \
        _record_preflight_observations, \
        _refresh_worker_observations_if_needed, \
        _research_quality_payload, \
        _source_lineage_payload, \
        _systemctl_show
    global _worker_observations_need_refresh, state_response
    _sync_namespace(ns)

    def state_response() -> ControlStateResponse:
        # Legacy /control/state must stay bounded and operator-safe. Paper-writing
        # eligibility is exposed by /control/api/v1/overview.paper_pipeline, not
        # mixed into the dispatch candidate slot here. This keeps the state
        # endpoint focused on pause flags, queue counts, active work, and the
        # next dispatchable queue row.
        counts = (
            store.queue_counts_sql()
            if hasattr(store, "queue_counts_sql")
            else store.status_counts()
        )
        paper_counts = (
            store.paper_counts_sql() if hasattr(store, "paper_counts_sql") else {}
        )
        queue_total = counts.get("all", 0)
        active = _active_items_fast()
        queued = _queued_items_fast()
        return ControlStateResponse(
            flags=store.flags(),
            counts={
                **counts,
                "papers": int(paper_counts.get("all", 0)),
                "queue_total": int(queue_total),
            },
            active_items=active,
            worker_lanes=_worker_lane_capacity(active=active, rows=queued),
            next_candidate=_open_worker_dispatch_candidate(
                active=active, queued=queued
            ),
            recent_events=store.recent_events(10),
        )

    def _config_status() -> DashboardConfigStatus:
        return DashboardConfigStatus(
            live_dispatch_enabled=config.live_dispatch_enabled,
            worker_wake_gate_url=config.worker_wake_gate_url,
            worker_token_configured=bool(config.worker_wake_gate_bearer_token),
            dispatch_timeout_sec=config.dispatch_timeout_sec,
            project_root=str(config.expanded_project_root),
            state_dir=str(config.expanded_state_dir),
            pushover_alerts_enabled=config.pushover_alerts_enabled,
            pushover_configured=bool(
                config.pushover_app_token and config.pushover_user_key
            ),
            queue_alert_cooldown_sec=config.queue_alert_cooldown_sec,
            queue_alert_hang_after_sec=config.queue_alert_hang_after_sec,
        )

    def _systemctl_show(unit: str, properties: list[str]) -> dict[str, Any]:
        cmd = ["systemctl", "show", unit, "--no-pager"]
        for prop in properties:
            cmd.extend(["-p", prop])
        try:
            result = subprocess.run(
                cmd, check=False, capture_output=True, text=True, timeout=8
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {"Unit": unit, "ok": False, "error": str(exc)}
        parsed: dict[str, Any] = {"Unit": unit, "ok": result.returncode == 0}
        for line in result.stdout.splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                parsed[key] = value
        if result.returncode != 0:
            parsed["error"] = (result.stderr or result.stdout)[-500:]
        return parsed

    def _automation_timer_snapshot() -> tuple[
        dict[str, dict[str, Any]], dict[str, dict[str, Any]]
    ]:
        timers = {
            unit: _systemctl_show(
                unit, ["ActiveState", "LastTriggerUSec", "NextElapseUSecRealtime"]
            )
            for unit in (
                "enoch-research-autopilot.timer",
                "enoch-corpus-import-autopilot.timer",
            )
        }
        services = {
            unit: _systemctl_show(
                unit,
                [
                    "ActiveState",
                    "SubState",
                    "Result",
                    "ExecMainStatus",
                    "ActiveEnterTimestamp",
                    "InactiveEnterTimestamp",
                ],
            )
            for unit in (
                "enoch-research-autopilot.service",
                "enoch-corpus-import-autopilot.service",
            )
        }
        return timers, services

    def _provider_budget_for_readiness() -> dict[str, Any]:
        from scripts import research_provider_budget

        base_url, provider_api_key = _resolve_synthetic_budget_provider(
            _ROUTER_GATE_CONFIG
        )
        budget_base_url = _synthetic_budget_base_url(base_url)
        budget_endpoint = f"{budget_base_url}/v2/quotas"
        estimated_requests = int(
            os.environ.get("ENOCH_RESEARCH_AUTOPILOT_ESTIMATED_REQUESTS") or 1
        )
        reserve_requests = max(
            1, int(os.environ.get("ENOCH_RESEARCH_AUTOPILOT_RESERVE_REQUESTS") or 2)
        )
        min_remaining_credits = float(
            os.environ.get("ENOCH_RESEARCH_AUTOPILOT_MIN_CREDITS") or 5.0
        )
        min_rolling_remaining = int(
            os.environ.get("ENOCH_RESEARCH_AUTOPILOT_MIN_ROLLING") or 10
        )
        try:
            payload = research_provider_budget.fetch_json(
                budget_endpoint,
                api_key=_synthetic_budget_request_api_key(
                    budget_base_url, provider_api_key
                ),
                timeout=max(
                    1,
                    min(
                        int(
                            os.environ.get("ENOCH_RESEARCH_AUTOPILOT_BUDGET_TIMEOUT")
                            or 20
                        ),
                        60,
                    ),
                ),
            )
            result = research_provider_budget.synthetic_budget_status(
                payload,
                min_remaining_credits=min_remaining_credits,
                min_rolling_remaining=min_rolling_remaining,
                estimated_requests=estimated_requests,
                reserve_requests=reserve_requests,
            )
            result.update(_budget_endpoint_diagnostics(budget_endpoint))
        except Exception as exc:  # noqa: BLE001 - readiness must fail closed if the provider cannot be checked
            result = {
                "ok": False,
                "provider": "synthetic",
                "checked_at": utc_now(),
                "estimated_requests": estimated_requests,
                "reserve_requests": reserve_requests,
                "failures": [f"provider budget check failed: {exc}"],
                **_budget_endpoint_diagnostics(budget_endpoint),
            }
        safe_keys = {
            "ok",
            "provider",
            "checked_at",
            "estimated_requests",
            "reserve_requests",
            "remaining_credits",
            "min_remaining_credits",
            "rolling_remaining",
            "rolling_max",
            "rolling_limited",
            "rolling_next_tick_at",
            "weekly_next_regen_at",
            "weekly_next_regen_credits",
            "subscription_remaining",
            "subscription_renews_at",
            "budget_endpoint_host",
            "budget_endpoint_path",
            "failures",
        }
        return {key: result.get(key) for key in safe_keys if key in result}

    def _research_quality_payload() -> dict[str, Any]:
        configured = os.environ.get("ENOCH_RESEARCH_QUALITY_REPORT_PATH", "").strip()
        paths = (
            (configured, *DEFAULT_REPORT_PATHS) if configured else DEFAULT_REPORT_PATHS
        )
        status = load_latest_quality_status(
            paths,
            window_report_path=os.environ.get(
                "ENOCH_RESEARCH_QUALITY_WINDOW_REPORT_PATH", DEFAULT_WINDOW_REPORT_PATH
            ),
            autopilot_history_path=os.environ.get(
                "ENOCH_RESEARCH_AUTOPILOT_HISTORY_PATH", DEFAULT_AUTOPILOT_HISTORY_PATH
            ),
        )
        return {
            "source": "control_api_v1_research_quality",
            "authority": "latest read-only DSPy/research-quality report",
            **status,
        }

    def _source_lineage_payload() -> dict[str, Any]:
        configured = os.environ.get("ENOCH_SOURCE_LINEAGE_REPORT_PATH", "").strip()
        paths = (
            (configured, DEFAULT_SOURCE_LINEAGE_REPORT_PATH)
            if configured
            else (DEFAULT_SOURCE_LINEAGE_REPORT_PATH,)
        )
        status = load_latest_source_lineage_status(paths)
        return {
            "source": "control_api_v1_source_lineage",
            "authority": "latest read-only source-lineage validator report",
            **status,
        }

    def _automation_readiness_payload() -> dict[str, Any]:
        # Automation-readiness is a high-frequency dashboard read path. It must
        # not run live worker network preflight as a side effect; stale/missing
        # cached worker observations are reported as readiness checks instead.
        status = dashboard_status_response(
            refresh_worker=False, allow_worker_refresh=False
        )
        state = state_response().model_dump(mode="json")
        state["worker_lanes"] = status.model_dump(mode="json").get("worker_lanes", [])
        overview = read_models.overview(store, active_limit=5, event_limit=5)
        blocked_rows, _, _ = store.queue_page(
            queue="all",
            status="blocked",
            search="",
            cursor="",
            page_size=3,
            sort="priority",
        )
        overview["blocked_attention_samples"] = [
            read_models.summarize_queue_list_row(row) for row in blocked_rows
        ]
        timers, services = _automation_timer_snapshot()
        resource_findings = [
            item for item in status.warnings if item.source == "worker_resource_policy"
        ]
        try:
            settings = read_llm_settings(config)
            llm_model_health = read_models.llm_model_health_summary(store, settings)
        except Exception as exc:  # noqa: BLE001 - readiness must fail visible, not 500
            llm_model_health = {
                "ok": False,
                "status": "needs_attention",
                "unhealthy_count": 1,
                "models": [],
                "reason": f"LLM model health unavailable: {type(exc).__name__}: {exc}",
            }
        readiness = evaluate_longhaul_readiness(
            state=state,
            overview=overview,
            timers=timers,
            services=services,
            provider_budget=_provider_budget_for_readiness(),
            research_quality=_research_quality_payload(),
            source_lineage=_source_lineage_payload(),
            resource_utilization=resource_utilization_status(resource_findings),
            llm_model_health=llm_model_health,
        )
        operator_trace = OperatorTrace.from_config(config)
        trace_id = OperatorTrace.new_trace_id("automation-readiness")
        operator_trace.record(
            "automation_readiness.result",
            trace_id=trace_id,
            requested_by="dashboard.automation_readiness",
            ok=readiness.get("ok"),
            status=readiness.get("status"),
            label=readiness.get("label"),
            blockers=(readiness.get("blockers") or [])[:20],
            summary={
                key: (readiness.get("summary") or {}).get(key)
                for key in (
                    "active",
                    "queued",
                    "blocked",
                    "needs_attention",
                    "write_needed",
                    "publish_ready",
                    "queue_paused",
                    "maintenance_mode",
                    "research_last_result",
                    "corpus_last_result",
                    "research_quality_status",
                    "source_lineage_status",
                    "resource_utilization_status",
                    "llm_model_health_status",
                    "llm_model_unhealthy_count",
                )
                if key in (readiness.get("summary") or {})
            },
        )
        readiness["trace_id"] = trace_id
        return {
            "source": "control_api_v1_automation_readiness",
            "authority": "live control-plane state, systemd timers, provider budget, LLM model health, latest research-quality report, and bounded dashboard read model",
            "timers": timers,
            "llm_model_health": llm_model_health,
            "services": services,
            **readiness,
        }

    def _record_preflight_observations(response: WorkerPreflightResponse) -> None:
        if config.control_plane_store_backend == "supabase_readonly":
            return
        preflight_payload = _compact_worker_preflight_payload(
            response.model_dump(mode="json")
        )
        lane_key = _preflight_observation_lane_key(
            DashboardObservationRecord(
                source="worker_preflight", payload=preflight_payload
            )
        )
        default_lane_key = _worker_lane_key({"machine_target": ""})
        if not lane_key or lane_key == default_lane_key:
            store.upsert_dashboard_observation(
                source="worker_preflight",
                status="ok" if response.ok else "warn",
                ttl_seconds=300,
                payload=preflight_payload,
            )
        if lane_key:
            store.upsert_dashboard_observation(
                source="worker_preflight",
                scope=f"lane:{lane_key}",
                status="ok" if response.ok else "warn",
                ttl_seconds=300,
                payload=preflight_payload,
            )
        dashboard_check = next(
            (
                check
                for check in response.checks
                if check.name == "wake_gate_dashboard_api"
            ),
            None,
        )
        if dashboard_check is not None:
            dashboard_payload = _compact_worker_dashboard_check_payload(
                dashboard_check.model_dump(mode="json")
            )
            dashboard_status = "ok" if dashboard_check.ok else "unavailable"
            if not lane_key or lane_key == default_lane_key:
                store.upsert_dashboard_observation(
                    source="worker_dashboard_api",
                    status=dashboard_status,
                    ttl_seconds=300,
                    payload=dashboard_payload,
                )
            if lane_key:
                store.upsert_dashboard_observation(
                    source="worker_dashboard_api",
                    scope=f"lane:{lane_key}",
                    status=dashboard_status,
                    ttl_seconds=300,
                    payload=dashboard_payload,
                )
            body = (dashboard_payload.get("data") or {}).get("body") or {}
            for run_item in body.get("runs") or []:
                if not isinstance(run_item, dict):
                    continue
                run_id = str(run_item.get("run_id") or "").strip()
                project_id = str(run_item.get("project_id") or "").strip()
                scoped_payload = {
                    "source": "worker_dashboard_api",
                    "run": run_item,
                    "dashboard_timestamp": body.get("timestamp"),
                    "totals": body.get("totals") or {},
                }
                if run_id:
                    store.upsert_dashboard_observation(
                        source="worker_dashboard_api",
                        scope=f"run:{run_id}",
                        status="ok" if dashboard_check.ok else "unavailable",
                        ttl_seconds=120,
                        payload=scoped_payload,
                    )
                if project_id:
                    store.upsert_dashboard_observation(
                        source="worker_dashboard_api",
                        scope=f"project:{project_id}",
                        status="ok" if dashboard_check.ok else "unavailable",
                        ttl_seconds=120,
                        payload=scoped_payload,
                    )

    # Live dispatch is never allowed to bypass fresh worker evidence.  The
    # request field remains for API compatibility, but the control plane
    # always performs the non-mutating worker preflight before prepare/dispatch.
    _live_dispatch = partial(
        _execute_live_dispatch,
        config=config,
        store=store,
        require_writable_store=_require_writable_store,
        candidate_machine_target_conflict_set=_candidate_machine_target_conflict_set,
        callback_acceptance_token_fingerprint=_callback_acceptance_token_fingerprint,
        record_preflight_observations=_record_preflight_observations,
        dispatch_route_metadata=_dispatch_route_metadata,
    )

    def _freshness_for_observation(
        source: str, authority: str, observation: DashboardObservationRecord | None
    ) -> DashboardFreshness:
        if observation is None:
            return DashboardFreshness(
                source=source,
                authority=authority,
                stale=True,
                detail="no cached observation",
            )
        stale = _is_stale(observation.observed_at, observation.ttl_seconds)
        return DashboardFreshness(
            source=source,
            authority=authority,
            observed_at=observation.observed_at,
            ttl_seconds=observation.ttl_seconds,
            fresh_until=_fresh_until(observation.observed_at, observation.ttl_seconds),
            stale=stale,
            status=observation.status,
            detail="stale cached observation" if stale else "fresh cached observation",
        )

    def _worker_observations_need_refresh(
        observations: dict[str, DashboardObservationRecord | None], active: list[dict]
    ) -> bool:
        for source in ("worker_preflight", "worker_dashboard_api"):
            observation = observations.get(source)
            if observation is None or _is_stale(
                observation.observed_at, observation.ttl_seconds
            ):
                return True
        preflight = observations.get("worker_preflight")
        no_live = _preflight_check(preflight, "worker_no_live_runs")
        if no_live:
            default_worker_lane = _worker_lane_key({"machine_target": ""})
            preflight_lane = _preflight_observation_lane_key(preflight)
            if preflight_lane and preflight_lane != default_worker_lane:
                return False
            worker_reports_idle = bool(no_live.get("ok"))
            control_reports_active = any(
                _worker_lane_key(row) == default_worker_lane for row in active
            )
            if worker_reports_idle == control_reports_active:
                # The cached worker/control active-lane projections disagree.
                # Refresh before presenting a scary conflict; the transition
                # may simply have happened between dashboard polls.
                return True
        return False

    def _refresh_worker_observations_if_needed(
        observations: dict[str, DashboardObservationRecord | None], active: list[dict]
    ) -> dict[str, DashboardObservationRecord]:
        if not _worker_observations_need_refresh(observations, active):
            return {
                key: value for key, value in observations.items() if value is not None
            }
        if (
            not config.live_dispatch_enabled
            or not config.worker_wake_gate_url
            or not config.worker_wake_gate_bearer_token
        ):
            return {
                key: value for key, value in observations.items() if value is not None
            }
        preflight = run_worker_preflight(
            WorkerPreflightRequest(
                wake_gate_url=config.worker_wake_gate_url,
                bearer_token=config.worker_wake_gate_bearer_token,
                expected_callback_token_fingerprint=_callback_acceptance_token_fingerprint(),
                require_paused=False,
                strict=False,
            ),
            store.flags(),
        )
        _record_preflight_observations(preflight)
        return store.latest_dashboard_observations()

    def _dispatch_gates_allow_live(flags: Any, config: GateConfig) -> bool:
        return (
            config.live_dispatch_enabled
            and not flags.queue_paused
            and not flags.maintenance_mode
        )

    def _fetch_dashboard_status_observations(
        *,
        refresh_worker: bool,
        active: list[dict],
        allow_worker_refresh: bool = True,
    ) -> dict[str, DashboardObservationRecord | None]:
        observations: dict[str, DashboardObservationRecord | None] = {
            "worker_preflight": store.latest_dashboard_observation(
                source="worker_preflight"
            ),
            "worker_dashboard_api": _latest_dashboard_observation_metadata(
                "worker_dashboard_api"
            ),
            "idea_intake": _latest_dashboard_observation_metadata("idea_intake"),
            "snapshot_mirror": _latest_dashboard_observation_metadata(
                "snapshot_mirror"
            ),
        }
        should_refresh_worker = allow_worker_refresh and (
            refresh_worker or _worker_observations_need_refresh(observations, active)
        )
        if should_refresh_worker:
            refreshed = _refresh_worker_observations_if_needed(
                dict(observations), active
            )
            observations = {
                "worker_preflight": refreshed.get("worker_preflight"),
                "worker_dashboard_api": _latest_dashboard_observation_metadata(
                    "worker_dashboard_api"
                ),
                "idea_intake": _latest_dashboard_observation_metadata("idea_intake"),
                "snapshot_mirror": _latest_dashboard_observation_metadata(
                    "snapshot_mirror"
                ),
            }
        return observations

    def _dashboard_status_source_freshness(
        observations: dict[str, DashboardObservationRecord | None],
        *,
        preflight: DashboardObservationRecord | None,
        worker_dashboard: DashboardObservationRecord | None,
    ) -> dict[str, DashboardFreshness]:
        return {
            "control_plane_db": DashboardFreshness(
                source="control_plane_db",
                authority="canonical execution/control state",
                observed_at=utc_now(),
                stale=False,
                status="ok",
                detail="direct SQLite read",
            ),
            "control_plane_config": DashboardFreshness(
                source="control_plane_config",
                authority="static operational config",
                observed_at=utc_now(),
                stale=False,
                status="ok",
                detail="current process config",
            ),
            "worker_preflight": _freshness_for_observation(
                "worker_preflight",
                "cached explicit worker preflight evidence",
                preflight,
            ),
            "worker_dashboard_api": _freshness_for_observation(
                "worker_dashboard_api", "cached GB10 runtime evidence", worker_dashboard
            ),
            "idea_intake": _freshness_for_observation(
                "idea_intake",
                "Supabase-native ideas intake",
                observations.get("idea_intake"),
            ),
            "snapshot_mirror": _freshness_for_observation(
                "snapshot_mirror",
                "cached worker/intake mirror",
                observations.get("snapshot_mirror"),
            ),
        }

    def _append_dashboard_control_flag_findings(
        *,
        flags: Any,
        warnings: list[DashboardFinding],
        blockers: list[str],
    ) -> None:
        if flags.queue_paused:
            blockers.append("queue paused")
            warnings.append(
                DashboardFinding(
                    severity="warn",
                    source="control_plane_db",
                    authority="dynamic control flag",
                    message=flags.pause_reason or "queue is paused",
                    suggested_action="resume the queue when maintenance is complete",
                )
            )
        if flags.maintenance_mode:
            blockers.append("maintenance mode")
            warnings.append(
                DashboardFinding(
                    severity="warn",
                    source="control_plane_db",
                    authority="dynamic control flag",
                    message="maintenance mode is enabled",
                    suggested_action="disable maintenance mode before live dispatch",
                )
            )
        if not config.live_dispatch_enabled:
            blockers.append("live dispatch disabled")
            warnings.append(
                DashboardFinding(
                    severity="warn",
                    source="control_plane_config",
                    authority="static operational config",
                    message="live dispatch is disabled by config",
                    suggested_action="enable live_dispatch_enabled only when ready",
                )
            )

    def _append_dashboard_dispatch_lane_blockers(
        *,
        flags: Any,
        active: list[dict],
        rows: list[dict],
        open_worker_candidate: dict | None,
        blockers: list[str],
    ) -> None:
        configured_lane_keys = {
            str(lane.get("lane_key") or "") for lane in _configured_worker_lanes()
        }
        active_lane_keys = {_worker_lane_key(row) for row in active}
        all_configured_lanes_active = (
            bool(configured_lane_keys) and configured_lane_keys <= active_lane_keys
        )
        if (
            active
            and not open_worker_candidate
            and (_queued_dispatch_candidates(rows) or all_configured_lanes_active)
        ):
            blockers.append("all configured worker lanes active")
        elif _dispatch_gates_allow_live(flags, config) and not open_worker_candidate:
            blockers.append("no queued dispatch candidate")

    _export_namespace(
        ns,
        (
            "_append_dashboard_control_flag_findings",
            "_append_dashboard_dispatch_lane_blockers",
            "_automation_readiness_payload",
            "_automation_timer_snapshot",
            "_config_status",
            "_dashboard_status_source_freshness",
            "_dispatch_gates_allow_live",
            "_fetch_dashboard_status_observations",
            "_freshness_for_observation",
            "_live_dispatch",
            "_provider_budget_for_readiness",
            "_record_preflight_observations",
            "_refresh_worker_observations_if_needed",
            "_research_quality_payload",
            "_source_lineage_payload",
            "_systemctl_show",
            "_worker_observations_need_refresh",
            "state_response",
        ),
    )


def _prepare_control_plane_http_bindings_dispatch(ns: MutableMapping[str, Any]) -> None:
    global \
        _append_dashboard_active_lane_findings, \
        _append_dashboard_observation_freshness_findings, \
        _append_dashboard_preflight_runtime_findings, \
        _cached_observation_freshness, \
        _classify_queue, \
        _dashboard_worker_preflight_context, \
        _db_freshness, \
        _enrich_queue_row
    global \
        _latest_dashboard_observation_metadata, \
        _paginate, \
        _paper_counts, \
        _project_events, \
        _queue_counts, \
        _review_counts, \
        _row_age_seconds, \
        _search_rows
    global _sort_rows, dashboard_status_response
    _sync_namespace(ns)

    def _dashboard_worker_preflight_context(
        preflight: DashboardObservationRecord | None,
        *,
        active: list[dict],
        open_worker_candidate: dict | None,
    ) -> dict[str, Any]:
        no_live = _preflight_check(preflight, "worker_no_live_runs")
        default_worker_lane = _worker_lane_key({"machine_target": ""})
        preflight_lane = _preflight_observation_lane_key(preflight)
        preflight_targets_default_worker = (
            not preflight or not preflight_lane or preflight_lane == default_worker_lane
        )
        preflight_applies_to_open_candidate = (
            _preflight_observation_applies_to_candidate(
                preflight, open_worker_candidate
            )
        )
        active_on_default_worker = [
            row for row in active if _worker_lane_key(row) == default_worker_lane
        ]
        worker_live_matches_active = bool(
            preflight_targets_default_worker
            and active_on_default_worker
            and no_live
            and no_live.get("ok") is False
        )
        worker_settling_after_vm_completion = None
        if preflight_targets_default_worker and not active:
            worker_settling_after_vm_completion = _worker_settling_after_vm_completion(
                preflight=preflight,
                queue_rows=_recently_completed_items_fast(),
                run_rows=store.run_rows(),
            )
            if not worker_settling_after_vm_completion:
                worker_settling_after_vm_completion = (
                    _recent_worker_settling_without_vm_match(preflight=preflight)
                )
        return {
            "no_live": no_live,
            "preflight_targets_default_worker": preflight_targets_default_worker,
            "preflight_applies_to_open_candidate": preflight_applies_to_open_candidate,
            "active_on_default_worker": active_on_default_worker,
            "worker_live_matches_active": worker_live_matches_active,
            "worker_settling_after_vm_completion": worker_settling_after_vm_completion,
        }

    def _append_dashboard_observation_freshness_findings(
        source_freshness: dict[str, DashboardFreshness],
        *,
        flags: Any,
        worker_ctx: dict[str, Any],
        warnings: list[DashboardFinding],
        blockers: list[str],
    ) -> None:
        worker_live_matches_active = bool(worker_ctx["worker_live_matches_active"])
        worker_settling = worker_ctx["worker_settling_after_vm_completion"]
        preflight_applies = bool(worker_ctx["preflight_applies_to_open_candidate"])
        live_dispatch_open = _dispatch_gates_allow_live(flags, config)
        for name, freshness in source_freshness.items():
            if freshness.stale and name in {"worker_preflight", "worker_dashboard_api"}:
                warnings.append(
                    DashboardFinding(
                        severity="warn",
                        source=name,
                        authority=freshness.authority,
                        message=f"{name} is stale or missing",
                        observed_at=freshness.observed_at,
                        suggested_action="run /control/api/preflight or wait for the next refresh observation",
                    )
                )
                if live_dispatch_open:
                    blockers.append(f"{name} stale or missing")
                continue
            if name not in {"worker_preflight", "worker_dashboard_api"}:
                continue
            if freshness.status == "ok":
                continue
            if name == "worker_preflight" and (
                worker_live_matches_active
                or worker_settling
                or worker_ctx.get("active_on_default_worker")
            ):
                continue
            warnings.append(
                DashboardFinding(
                    severity="warn",
                    source=name,
                    authority=freshness.authority,
                    message=f"{name} status is {freshness.status}",
                    observed_at=freshness.observed_at,
                    suggested_action="run /control/api/preflight and verify GB10 health before dispatch",
                )
            )
            if live_dispatch_open and (name != "worker_preflight" or preflight_applies):
                blockers.append(f"{name} not ok")

    def _append_dashboard_preflight_runtime_findings(
        preflight: DashboardObservationRecord | None,
        *,
        flags: Any,
        worker_ctx: dict[str, Any],
        warnings: list[DashboardFinding],
        blockers: list[str],
    ) -> None:
        preflight_targets_default_worker = bool(
            worker_ctx["preflight_targets_default_worker"]
        )
        preflight_applies = bool(worker_ctx["preflight_applies_to_open_candidate"])
        live_dispatch_open = _dispatch_gates_allow_live(flags, config)
        health = _preflight_check(preflight, "wake_gate_healthz")
        dashboard = _preflight_check(preflight, "wake_gate_dashboard_api")
        resource_findings = (
            classify_low_utilization_runs(
                _worker_dashboard_body_from_preflight(preflight)
            )
            if preflight_targets_default_worker
            else []
        )
        if resource_findings:
            warnings.extend(resource_findings)
            blockers.append("GB10 low-utilization CPU-only active run")
        if health and not health.get("ok"):
            warnings.append(
                DashboardFinding(
                    severity="warn",
                    source="worker_preflight",
                    authority="worker reachability evidence",
                    message="cached worker wake gate health check failed",
                    observed_at=preflight.observed_at if preflight else None,
                    suggested_action="verify the affected worker service before dispatch",
                    data=health,
                )
            )
            if live_dispatch_open and preflight_applies:
                blockers.append("worker health check failed")
        if not (dashboard and dashboard.get("data", {}).get("skipped")):
            return
        warnings.append(
            DashboardFinding(
                severity="warn",
                source="worker_preflight",
                authority="worker runtime evidence",
                message="authenticated worker dashboard checks were skipped",
                observed_at=preflight.observed_at if preflight else None,
                suggested_action="configure worker bearer token before live dispatch",
                data=dashboard,
            )
        )
        if live_dispatch_open and preflight_applies:
            blockers.append("worker dashboard telemetry skipped")

    def _append_dashboard_active_lane_findings(
        preflight: DashboardObservationRecord | None,
        *,
        flags: Any,
        worker_ctx: dict[str, Any],
        warnings: list[DashboardFinding],
        blockers: list[str],
        conflicts: list[DashboardFinding],
    ) -> None:
        no_live = worker_ctx["no_live"]
        preflight_targets_default_worker = bool(
            worker_ctx["preflight_targets_default_worker"]
        )
        preflight_applies = bool(worker_ctx["preflight_applies_to_open_candidate"])
        active_on_default_worker = worker_ctx["active_on_default_worker"]
        worker_settling = worker_ctx["worker_settling_after_vm_completion"]
        live_dispatch_open = _dispatch_gates_allow_live(flags, config)
        if (
            preflight_targets_default_worker
            and active_on_default_worker
            and no_live
            and no_live.get("ok") is True
        ):
            conflicts.append(
                DashboardFinding(
                    severity="warn",
                    source=CONTROL_PLANE_DB_WORKER_PREFLIGHT_SOURCE,
                    authority=CROSS_SOURCE_ACTIVE_LANE_RECONCILIATION_AUTHORITY,
                    message="VM control plane has an active row on the default worker, but cached default-worker preflight says no live worker run",
                    observed_at=preflight.observed_at if preflight else None,
                    suggested_action="inspect run detail and reconcile if the worker truly exited",
                    data={
                        "active_count": len(active_on_default_worker),
                        "worker_check": no_live,
                    },
                )
            )
            return
        if not (
            preflight_targets_default_worker
            and not active_on_default_worker
            and no_live
            and no_live.get("ok") is False
        ):
            return
        if worker_settling:
            settling_without_match = (
                worker_settling.get("match_type")
                == "recent_worker_settling_without_vm_active_row"
            )
            if settling_without_match:
                settling_message = (
                    "GB10 worker is settling a recent worker run with no active process"
                )
                settling_blocker = "GB10 worker settling recent run"
            else:
                settling_message = (
                    "GB10 worker is settling a completed VM run with no active process"
                )
                settling_blocker = "GB10 worker settling completed run"
            warnings.append(
                DashboardFinding(
                    severity="warn",
                    source="worker_settling",
                    authority=CROSS_SOURCE_ACTIVE_LANE_RECONCILIATION_AUTHORITY,
                    message=settling_message,
                    observed_at=preflight.observed_at if preflight else None,
                    suggested_action="wait for the worker quiet-window to clear before dispatch",
                    data=worker_settling,
                )
            )
            if live_dispatch_open and preflight_applies:
                blockers.append(settling_blocker)
            return
        conflicts.append(
            DashboardFinding(
                severity="critical" if preflight_applies else "warn",
                source=CONTROL_PLANE_DB_WORKER_PREFLIGHT_SOURCE,
                authority="single active GB10 lane safety",
                message="GB10 reports live/active work but VM control plane has no active row",
                observed_at=preflight.observed_at if preflight else None,
                suggested_action="pause dispatch to the affected worker lane and reconcile before starting another job",
                data={"worker_check": no_live},
            )
        )
        if preflight_applies:
            blockers.append("GB10/VM active-lane conflict")

    def dashboard_status_response(
        *, refresh_worker: bool = False, allow_worker_refresh: bool = True
    ) -> DashboardStatusResponse:
        rows = _queued_items_fast()
        paper_counts = (
            store.paper_counts_sql() if hasattr(store, "paper_counts_sql") else {}
        )
        flags = store.flags()
        active = _active_items_fast()
        observations = _fetch_dashboard_status_observations(
            refresh_worker=refresh_worker,
            active=active,
            allow_worker_refresh=allow_worker_refresh,
        )
        preflight = observations.get("worker_preflight")
        worker_dashboard = observations.get("worker_dashboard_api")
        recent_events = store.recent_events(10)
        queue_counts = (
            store.queue_counts_sql()
            if hasattr(store, "queue_counts_sql")
            else store.status_counts()
        )
        counts = {
            **queue_counts,
            "papers": int(paper_counts.get("all", 0)),
            "queue_total": int(queue_counts.get("all", 0)),
        }
        cfg = _config_status()
        source_freshness = _dashboard_status_source_freshness(
            observations, preflight=preflight, worker_dashboard=worker_dashboard
        )
        warnings: list[DashboardFinding] = []
        conflicts: list[DashboardFinding] = []
        blockers: list[str] = []
        _append_dashboard_control_flag_findings(
            flags=flags, warnings=warnings, blockers=blockers
        )
        open_worker_candidate = _open_worker_dispatch_candidate(
            active=active, queued=rows
        )
        _append_dashboard_dispatch_lane_blockers(
            flags=flags,
            active=active,
            rows=rows,
            open_worker_candidate=open_worker_candidate,
            blockers=blockers,
        )
        worker_ctx = _dashboard_worker_preflight_context(
            preflight, active=active, open_worker_candidate=open_worker_candidate
        )
        _append_dashboard_observation_freshness_findings(
            source_freshness,
            flags=flags,
            worker_ctx=worker_ctx,
            warnings=warnings,
            blockers=blockers,
        )
        _append_dashboard_preflight_runtime_findings(
            preflight,
            flags=flags,
            worker_ctx=worker_ctx,
            warnings=warnings,
            blockers=blockers,
        )
        _append_dashboard_active_lane_findings(
            preflight,
            flags=flags,
            worker_ctx=worker_ctx,
            warnings=warnings,
            blockers=blockers,
            conflicts=conflicts,
        )
        worker_lanes = _worker_lane_capacity(
            active=active,
            rows=rows,
            global_blockers=blockers,
            worker_preflight=preflight,
        )
        _append_dashboard_worker_lane_confirmation_findings(
            worker_lanes,
            warnings=warnings,
            blockers=blockers,
            conflicts=conflicts,
        )
        has_critical = any(item.severity == "critical" for item in conflicts)
        dispatch_safe = not blockers and not has_critical
        try:
            status_min_admission_score = float(
                os.environ.get("ENOCH_RESEARCH_ADMIT_THRESHOLD") or 72.0
            )
        except ValueError:
            status_min_admission_score = 72.0
        lane_feed_pressure = _research_lane_feed_pressure(
            active=active,
            queued=rows,
            lanes=worker_lanes,
            min_queue_depth=_bounded_int_env(
                "ENOCH_RESEARCH_MIN_QUEUE_DEPTH_PER_LANE", 25, 0, 100
            ),
            min_admission_score=status_min_admission_score,
        )
        for lane in worker_lanes:
            key = str(lane.get("machine_target") or lane.get("lane_key") or "")
            if key in lane_feed_pressure:
                lane["feed_pressure"] = lane_feed_pressure[key]
        return DashboardStatusResponse(
            flags=flags,
            config=cfg,
            counts=counts,
            active_items=active,
            worker_lanes=worker_lanes,
            lane_feed_pressure=lane_feed_pressure,
            next_candidate=open_worker_candidate,
            dispatch_safe=dispatch_safe,
            dispatch_blockers=blockers,
            source_freshness=source_freshness,
            observations={
                source: observations.get(source)
                for source in (
                    "worker_preflight",
                    "worker_dashboard_api",
                    "idea_intake",
                    "snapshot_mirror",
                )
            },
            warnings=warnings,
            conflicts=conflicts,
            recent_events=recent_events,
        )

    def _db_freshness(
        authority: str = "canonical control-plane SQLite",
    ) -> dict[str, DashboardFreshness]:
        return {
            "control_plane_db": DashboardFreshness(
                source="control_plane_db",
                authority=authority,
                observed_at=utc_now(),
                stale=False,
                status="ok",
                detail="direct SQLite read",
            )
        }

    def _latest_dashboard_observation_metadata(
        source: str, scope: str = "global"
    ) -> DashboardObservationRecord | None:
        summary_reader = getattr(store, "latest_dashboard_observation_summary", None)
        if callable(summary_reader):
            return summary_reader(source=source, scope=scope)
        return store.latest_dashboard_observation(source=source, scope=scope)

    def _cached_observation_freshness(
        source: str, authority: str, scope: str = "global"
    ) -> dict[str, DashboardFreshness]:
        observation = _latest_dashboard_observation_metadata(source, scope)
        return {source: _freshness_for_observation(source, authority, observation)}

    def _classify_queue(row: dict[str, Any]) -> set[str]:
        status = _normal_status(row.get("status"))
        groups = {"all", status}
        if status in {
            "dispatching",
            "running",
            "awaiting_wake",
            "wake_received",
            "reconciling",
        }:
            groups.add("active")
        if status == "queued":
            groups.add("queued")
        if status in {"blocked", "needs_review", "dispatch_error"} or _truthy_flag(
            row.get("manual_review_required")
        ):
            groups.add("blocked")
        if status == "paused":
            groups.add("paused")
        if status in {"completed", "canceled"}:
            groups.add("completed")
        return groups

    def _row_age_seconds(row: dict[str, Any]) -> int | None:
        ts = _parse_ts(str(row.get("updated_at") or row.get("created_at") or ""))
        if ts is None:
            return None
        return max(0, int((datetime.now(timezone.utc) - ts).total_seconds()))

    def _enrich_queue_row(row: dict[str, Any]) -> dict[str, Any]:
        out = dict(row)
        out["queue_groups"] = sorted(_classify_queue(row))
        out["age_seconds"] = _row_age_seconds(row)
        out["links"] = {
            "project": f"/control/api/projects/{row.get('project_id') or ''}",
            "run": f"/control/api/runs/{row.get('current_run_id') or ''}"
            if row.get("current_run_id")
            else "",
            "dashboard_project": f"/control/dashboard-v2#project:{row.get('project_id') or ''}",
            "dashboard_run": f"/control/dashboard-v2#run:{row.get('current_run_id') or ''}"
            if row.get("current_run_id")
            else "",
        }
        if row.get("stale_after") and _is_stale(str(row.get("stale_after")), 0):
            out["stale"] = True
        return out

    def _search_rows(rows: list[dict[str, Any]], search: str) -> list[dict[str, Any]]:
        needle = search.strip().lower()
        if not needle:
            return rows
        return [
            row
            for row in rows
            if needle
            in " ".join(
                str(v).lower()
                for v in row.values()
                if isinstance(v, (str, int, float, bool))
            )
        ]

    def _sort_rows(rows: list[dict[str, Any]], sort: str) -> list[dict[str, Any]]:
        reverse = sort.startswith("-")
        key = sort[1:] if reverse else sort
        if key in {
            "updated_at",
            "project_name",
            "status",
            "last_callback_at",
            "last_dispatch_at",
            "paper_status",
            "review_status",
            "rank_bucket",
        }:
            return sorted(
                rows, key=lambda row: str(row.get(key) or ""), reverse=reverse
            )
        if key in {
            "dispatch_priority",
            "selection_rank",
            "retry_count",
            "age_seconds",
            "rank_score",
        }:
            return sorted(rows, key=lambda row: int(row.get(key) or 0), reverse=reverse)
        return rows

    def _paginate(
        rows: list[dict[str, Any]], *, page: int, page_size: int
    ) -> tuple[list[dict[str, Any]], int, int]:
        safe_page = max(1, page)
        safe_size = max(1, min(page_size, 500))
        start = (safe_page - 1) * safe_size
        return rows[start : start + safe_size], safe_page, safe_size

    def _queue_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
        counts: dict[str, int] = {"all": len(rows)}
        for row in rows:
            for group in _classify_queue(row):
                counts[group] = counts.get(group, 0) + 1
        return counts

    def _paper_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
        counts: dict[str, int] = {"all": len(rows)}
        for row in rows:
            key = _normal_status(row.get("paper_status")) or "unknown"
            counts[key] = counts.get(key, 0) + 1
        return counts

    def _review_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
        counts: dict[str, int] = {"all": len(rows)}
        for row in rows:
            for key_name in ("review_status", "paper_status", "rank_bucket"):
                key = (
                    _normal_status(row.get(key_name))
                    if key_name in {"review_status", "paper_status"}
                    else str(row.get(key_name) or "unknown")
                ) or "unknown"
                counts[key] = counts.get(key, 0) + 1
        return counts

    def _project_events(project_id: str) -> list[dict[str, Any]]:
        events = store.event_rows(limit=100, entity_id=project_id)
        queue = store.queue_row(project_id)
        run_id = str((queue or {}).get("current_run_id") or "")
        if run_id:
            events.extend(store.event_rows(limit=50, entity_id=run_id))
        events.sort(key=lambda item: int(item.get("event_id") or 0), reverse=True)
        return events[:100]

    _export_namespace(
        ns,
        (
            "_append_dashboard_active_lane_findings",
            "_append_dashboard_observation_freshness_findings",
            "_append_dashboard_preflight_runtime_findings",
            "_cached_observation_freshness",
            "_classify_queue",
            "_dashboard_worker_preflight_context",
            "_db_freshness",
            "_enrich_queue_row",
            "_latest_dashboard_observation_metadata",
            "_paginate",
            "_paper_counts",
            "_project_events",
            "_queue_counts",
            "_review_counts",
            "_row_age_seconds",
            "_search_rows",
            "_sort_rows",
            "dashboard_status_response",
        ),
    )


def _prepare_control_plane_http_bindings_publication(
    ns: MutableMapping[str, Any],
) -> None:
    global \
        _candidate_project_dir, \
        _configured_worker_preflight_url, \
        _dashboard_ideas_intake_response, \
        _dashboard_next_paper_review_response, \
        _dashboard_paper_reviews_response, \
        _default_worker_url_key, \
        _detail_conflicts, \
        _intake_freshness
    global \
        _paper_review_detail_response, \
        _pre_evidence_paper_decision_gate, \
        _preflight_targets_default_worker, \
        _prepare_draft_evidence, \
        _require_legacy_notion_api_enabled, \
        _require_safe_paper_artifact_root, \
        _resolve_paper_artifact, \
        _rewrite_paper_review_draft
    global \
        _target_aware_preflight_payload, \
        _worker_detail_freshness, \
        _worker_detail_observations
    _sync_namespace(ns)

    def _intake_freshness() -> dict[str, DashboardFreshness]:
        return {
            **_db_freshness(SUPABASE_NATIVE_IDEAS_WORKBENCH_AUTHORITY),
            **_cached_observation_freshness(
                "idea_intake", "latest Supabase-native ideas intake observation"
            ),
        }

    def _require_legacy_notion_api_enabled() -> None:
        if not config.legacy_notion_api_enabled:
            raise LegacyNotionApiDisabledError(
                "Legacy Notion control-plane APIs are disabled; use Supabase-native "
                "/control/intake/ideas and /control/api/intake/ideas."
            )

    def _worker_detail_observations(
        project_id: str = "", run_id: str = ""
    ) -> dict[str, DashboardObservationRecord | None]:
        observations: dict[str, DashboardObservationRecord | None] = {
            "worker_preflight": store.latest_dashboard_observation(
                source="worker_preflight"
            ),
            "worker_dashboard_api": store.latest_dashboard_observation(
                source="worker_dashboard_api"
            ),
        }
        if project_id:
            observations["worker_dashboard_api_project"] = (
                store.latest_dashboard_observation(
                    source="worker_dashboard_api", scope=f"project:{project_id}"
                )
            )
        if run_id:
            observations["worker_dashboard_api_run"] = (
                store.latest_dashboard_observation(
                    source="worker_dashboard_api", scope=f"run:{run_id}"
                )
            )
        return observations

    def _worker_detail_freshness(
        source: str, authority: str, scope: str
    ) -> dict[str, DashboardFreshness]:
        scoped = store.latest_dashboard_observation(source=source, scope=scope)
        if scoped is not None:
            return {source: _freshness_for_observation(source, authority, scoped)}
        global_observation = store.latest_dashboard_observation(source=source)
        if global_observation is not None:
            return {
                source: _freshness_for_observation(
                    source, f"{authority} (global fallback)", global_observation
                )
            }
        return {source: _freshness_for_observation(source, authority, None)}

    def _detail_conflicts(
        *,
        active: bool = False,
        worker_observations: dict[str, DashboardObservationRecord | None],
    ) -> list[DashboardFinding]:
        preflight = worker_observations.get("worker_preflight")
        no_live = _preflight_check(preflight, "worker_no_live_runs")
        conflicts: list[DashboardFinding] = []
        if active and no_live and no_live.get("ok") is True:
            conflicts.append(
                DashboardFinding(
                    severity="warn",
                    source=CONTROL_PLANE_DB_WORKER_PREFLIGHT_SOURCE,
                    authority=CROSS_SOURCE_ACTIVE_LANE_RECONCILIATION_AUTHORITY,
                    message="control-plane row is active but latest worker preflight reports no live run",
                    observed_at=preflight.observed_at if preflight else None,
                    suggested_action="inspect run detail and reconcile the active row if the worker exited",
                    data={"worker_check": no_live},
                )
            )
        if not active and no_live and no_live.get("ok") is False:
            conflicts.append(
                DashboardFinding(
                    severity="critical",
                    source=CONTROL_PLANE_DB_WORKER_PREFLIGHT_SOURCE,
                    authority="single active GB10 lane safety",
                    message="worker reports live work but this detail view has no active control-plane row",
                    observed_at=preflight.observed_at if preflight else None,
                    suggested_action="pause dispatch and reconcile before starting another job",
                    data={"worker_check": no_live},
                )
            )
        return conflicts

    def _dashboard_paper_reviews_response(
        *,
        authorization: Annotated[str | None, Header()] = None,
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=500)] = 50,
        review_status: str = "",
        paper_status: str = "",
        search: str = "",
        sort: str = "-rank_score",
        include_rank_reasons: bool = True,
        queue_label: str = "publication_automation",
    ) -> DashboardPaperReviewsResponse:
        authorize(authorization)
        rows = store.paper_review_rows(include_rank_reasons=include_rank_reasons)
        all_counts = _review_counts(rows)
        if review_status:
            rows = [
                row
                for row in rows
                if _normal_status(row.get("review_status"))
                == _normal_status(review_status)
            ]
        if paper_status:
            rows = [
                row
                for row in rows
                if _normal_status(row.get("paper_status"))
                == _normal_status(paper_status)
            ]
        rows = _sort_rows(_search_rows(rows, search), sort)
        page_rows, safe_page, safe_size = _paginate(
            rows, page=page, page_size=page_size
        )
        return DashboardPaperReviewsResponse(
            operator_summary=read_models.summarize_automation_workbench(
                counts=all_counts,
                page_total=len(rows),
                page_returned=len(page_rows),
                review_status=review_status,
                search=search,
            ),
            page=DashboardPageMeta(
                page=safe_page,
                page_size=safe_size,
                total=len(rows),
                returned=len(page_rows),
                queue=queue_label,
                filters={
                    "search": search,
                    "review_status": review_status,
                    "paper_status": paper_status,
                    "include_rank_reasons": include_rank_reasons,
                },
                sort=sort,
            ),
            counts=all_counts,
            rows=page_rows,
            source_freshness=_db_freshness(
                "canonical publication automation queue read model"
            ),
            conflicts=[],
        )

    def _paper_review_detail_response(
        paper_id: str,
    ) -> DashboardPaperReviewDetailResponse:
        item = store.paper_review_row(paper_id, include_rank_reasons=True)
        paper = store.paper_row(paper_id)
        if item is None or paper is None:
            raise PublicationAutomationNotFoundError(
                PUBLICATION_AUTOMATION_ITEM_NOT_FOUND
            )
        project_id = str(paper.get("project_id") or "")
        return DashboardPaperReviewDetailResponse(
            paper_id=paper_id,
            item=item,
            checklist=store.paper_review_checklist(paper_id),
            paper=paper,
            project=store.project_row(project_id) if project_id else None,
            events=store.event_rows(limit=100, entity_id=paper_id)
            + (store.event_rows(limit=50, entity_id=project_id) if project_id else []),
            source_freshness=_db_freshness(
                "publication automation/paper/project aggregate"
            ),
            warnings=[],
            conflicts=[],
        )

    def _dashboard_next_paper_review_response(
        *,
        authorization: Annotated[str | None, Header()] = None,
        review_status: str = "",
        paper_status: str = "publication_draft",
        search: str = "",
    ) -> DashboardPaperReviewDetailResponse:
        authorize(authorization)
        rows = store.paper_review_rows(include_rank_reasons=True)
        if review_status:
            rows = [
                row
                for row in rows
                if _normal_status(row.get("review_status"))
                == _normal_status(review_status)
            ]
        else:
            rows = [
                row
                for row in rows
                if _normal_status(row.get("review_status"))
                not in {
                    "blocked",
                    "changes_requested",
                    "finalized",
                    "in_review",
                    "rejected",
                    "unreviewed",
                }
            ]
        if paper_status:
            rows = [
                row
                for row in rows
                if _normal_status(row.get("paper_status"))
                == _normal_status(paper_status)
            ]
        rows = _sort_rows(_search_rows(rows, search), "-rank_score")
        if not rows:
            raise PublicationAutomationNotFoundError(
                "no matching publication automation item"
            )
        return _paper_review_detail_response(str(rows[0].get("paper_id") or ""))

    def _rewrite_paper_review_draft(
        paper_id: str, payload: PaperReviewRewriteDraftRequest
    ) -> PaperReviewRewriteDraftResponse:
        paper, item = _paper_rewrite_rows_or_404(store, paper_id)
        project_id = str(paper.get("project_id") or "")
        project = store.project_row(project_id) if project_id else None
        try:
            artifact_root, use_current_dir = _resolve_paper_rewrite_artifact_root(
                config, project_id=project_id, project=project
            )
        except PaperArtifactRootNotInspectableError as exc:
            raise PaperArtifactRootError(str(exc)) from exc
        replay = _paper_rewrite_idempotent_response(
            store,
            payload=payload,
            paper_id=paper_id,
            item=item,
            paper=paper,
            artifact_root=artifact_root,
        )
        if replay is not None:
            return replay
        artifact_root.mkdir(parents=True, exist_ok=True)
        source_project_dir = str((project or {}).get("project_dir") or "")
        evidence_sync = _sync_remote_project_evidence(
            config,
            project_id=project_id,
            artifact_root=artifact_root,
            source_project_dir=source_project_dir
            if source_project_dir and not use_current_dir
            else "",
            source_run_id=str(paper.get("run_id") or ""),
        )
        if config.paper_evidence_sync_enabled and not _local_paper_evidence_present(
            artifact_root
        ):
            _record_paper_evidence_blocked(
                config,
                store,
                entity_type="paper",
                entity_id=paper_id,
                project_id=project_id,
                run_id=str(paper.get("run_id") or ""),
                paper_id=paper_id,
                artifact_root=str(artifact_root),
                evidence_sync=evidence_sync,
            )
            raise PaperRewriteEvidenceRequiredError(evidence_sync) from None
        original_record = _paper_record_from_store_row(paper)
        original_project_dir = str(
            (project or {}).get("project_dir") or paper.get("project_dir") or ""
        )
        record = original_record.model_copy(
            update={
                "paper_status": PaperStatus.PUBLICATION_DRAFT,
                "updated_at": utc_now(),
            }
        )
        candidate = _paper_rewrite_candidate_payload(
            project_id=project_id,
            project=project,
            paper=paper,
            item=item,
            artifact_root=artifact_root,
            record=record,
            evidence_sync=evidence_sync,
        )
        artifact_snapshots = _snapshot_paper_rewrite_artifacts(artifact_root, record)
        return _commit_paper_rewrite_draft(
            store,
            config,
            payload=payload,
            candidate=candidate,
            record=record,
            artifact_root=artifact_root,
            use_current_dir=use_current_dir,
            project_id=project_id,
            evidence_sync=evidence_sync,
            artifact_snapshots=artifact_snapshots,
            original_record=original_record,
            original_project_dir=original_project_dir,
            item=item,
        )

    def _require_safe_paper_artifact_root(paper_id: str) -> None:
        paper = store.paper_row(paper_id)
        if paper is None:
            raise HTTPException(status_code=404, detail=_HTTP_404_PAPER_DETAIL)
        project_id = str(paper.get("project_id") or "").strip()
        project_dir_text = str(paper.get("project_dir") or project_id).strip()
        safe_root = _local_artifact_root_http(
            config, project_id=project_id, project_dir_text=project_dir_text
        )
        candidate = _expanduser_path_or_http(
            project_dir_text,
            detail="paper project_dir contains an unexpandable user home",
        )
        try:
            candidate_root = (
                candidate
                if candidate.is_absolute()
                else config.expanded_project_root / candidate
            ).resolve()
        except (OSError, RuntimeError, ValueError) as exc:
            raise HTTPException(
                status_code=400,
                detail="paper finalization artifact root could not be resolved",
            ) from exc
        if candidate_root != safe_root:
            raise HTTPException(
                status_code=400,
                detail="paper finalization artifacts must resolve inside the configured project root",
            )

    def _resolve_paper_artifact(paper: dict[str, Any], field: str) -> Path:
        allowed = {
            "draft_markdown_path",
            "draft_latex_path",
            "evidence_bundle_path",
            "claim_ledger_path",
            "manifest_path",
        }
        if field not in allowed:
            raise HTTPException(status_code=404, detail="unknown paper artifact field")
        raw_path = str(paper.get(field) or "").strip()
        if not raw_path:
            raise HTTPException(
                status_code=404, detail=f"paper artifact path is empty: {field}"
            )
        project_dir_text = str(
            paper.get("project_dir") or paper.get("project_id") or ""
        ).strip()
        project_dir = (
            _local_artifact_root_http(
                config,
                project_id=str(paper.get("project_id") or "").strip(),
                project_dir_text=project_dir_text,
            )
            if project_dir_text
            else None
        )
        path = _expanduser_path_or_http(
            raw_path, detail="paper artifact path contains an unexpandable user home"
        )
        if path.is_absolute():
            resolved = path
        elif project_dir is not None:
            resolved = project_dir / path
        else:
            resolved = path
        try:
            resolved = resolved.resolve()
        except (OSError, RuntimeError, ValueError) as exc:
            raise HTTPException(
                status_code=400, detail="paper artifact path could not be resolved"
            ) from exc
        if project_dir is not None:
            try:
                resolved.relative_to(project_dir.resolve())
            except (OSError, RuntimeError, ValueError) as exc:
                raise HTTPException(
                    status_code=400,
                    detail="paper artifact path escapes project directory",
                ) from exc
        try:
            artifact_readable = resolved.exists() and resolved.is_file()
        except (OSError, RuntimeError, ValueError):
            artifact_readable = False
        if not artifact_readable:
            raise HTTPException(
                status_code=404, detail=f"paper artifact is not readable: {field}"
            )
        return resolved

    def _dashboard_ideas_intake_response(
        *,
        legacy_notion_alias: bool = False,
        page_size: int = 50,
        include_latest_payload: bool = False,
    ) -> DashboardIntakeResponse:
        latest, projection, recent, projection_counts, freshness = (
            _ideas_intake_resolve_parts(
                store,
                page_size=page_size,
                include_latest_payload=include_latest_payload,
                latest_metadata=_latest_dashboard_observation_metadata,
                intake_freshness=_intake_freshness,
                db_freshness=_db_freshness,
                freshness_for_observation=_freshness_for_observation,
            )
        )
        latest, skipped_reasons = _ideas_intake_prepare_latest(
            latest, include_latest_payload=include_latest_payload
        )
        warnings = _ideas_intake_empty_projection_warnings(projection)
        projection = [
            read_models.summarize_idea_workbench_row(row)
            for row in projection[:page_size]
        ]
        return DashboardIntakeResponse(
            source="control_api_intake_notion"
            if legacy_notion_alias
            else "control_api_intake_ideas",
            authority="Legacy Notion projection alias; Supabase ideas are canonical"
            if legacy_notion_alias
            else "Supabase-native ideas workbench; Notion is provenance only",
            operator_summary=read_models.summarize_intake_workbench(
                projection_counts=projection_counts,
                queued_projection=projection,
                skipped_reasons=skipped_reasons,
                latest_sync=latest,
            ),
            latest_sync=latest,
            projection_counts=projection_counts,
            queued_projection=projection,
            skipped_reasons=skipped_reasons,
            recent_events=recent,
            source_freshness=freshness,
            warnings=warnings,
            conflicts=[],
        )

    def _configured_worker_preflight_url() -> str:
        worker_url = (config.worker_wake_gate_url or "").strip()
        worker_host = urlparse(worker_url).hostname or ""
        if not worker_url or worker_host == DEFAULT_MACHINE_TARGET:
            raise WorkerPreflightUrlNotConfiguredError(
                "worker preflight requires configured worker_wake_gate_url"
            )
        return worker_url

    def _default_worker_url_key() -> str:
        return _configured_worker_preflight_url().rstrip("/")

    def _preflight_targets_default_worker(payload: WorkerPreflightRequest) -> bool:
        return (payload.wake_gate_url or "").strip().rstrip(
            "/"
        ) == _default_worker_url_key()

    def _target_aware_preflight_payload(
        payload: WorkerPreflightRequest,
    ) -> WorkerPreflightRequest:
        machine_target = (payload.machine_target or "").strip()
        if machine_target:
            target = config.resolved_worker_target(machine_target)
            return payload.model_copy(
                update={
                    "wake_gate_url": target.wake_gate_url,
                    "bearer_token": target.bearer_token,
                    "expected_callback_token_fingerprint": payload.expected_callback_token_fingerprint
                    or _callback_acceptance_token_fingerprint(),
                    "min_memory_available_mib": target.min_memory_available_mib
                    or payload.min_memory_available_mib,
                }
            )
        requested_url = (payload.wake_gate_url or "").strip().rstrip("/")
        allowed_urls = {
            _configured_worker_preflight_url().rstrip("/"),
            *{
                (target.wake_gate_url or "").strip().rstrip("/")
                for target in config.worker_targets.values()
                if (target.wake_gate_url or "").strip()
            },
        }
        if requested_url and requested_url not in allowed_urls:
            raise WakeGateUrlNotAllowedError(
                "wake_gate_url must match configured worker_wake_gate_url or a "
                "configured worker target; use machine_target for named routes"
            )
        worker_host = urlparse((payload.wake_gate_url or "").strip()).hostname or ""
        if worker_host == DEFAULT_MACHINE_TARGET:
            return payload.model_copy(
                update={
                    "wake_gate_url": _configured_worker_preflight_url(),
                    "bearer_token": config.worker_wake_gate_bearer_token,
                    "expected_callback_token_fingerprint": payload.expected_callback_token_fingerprint
                    or _callback_acceptance_token_fingerprint(),
                }
            )
        return payload.model_copy(
            update={
                "expected_callback_token_fingerprint": payload.expected_callback_token_fingerprint
                or _callback_acceptance_token_fingerprint(),
            }
        )

    def _candidate_project_dir(candidate: dict[str, Any]) -> Path:
        project_id = str(candidate.get("project_id") or "").strip()
        project_dir_text = str(candidate.get("project_dir") or project_id).strip()
        # Completed worker rows can carry worker-absolute or stale relative paths
        # that are not valid on the VM. Use a VM-local artifact root and keep the
        # original source path only for evidence sync.
        return _local_artifact_root_http(
            config, project_id=project_id, project_dir_text=project_dir_text
        )

    def _prepare_draft_evidence(candidate: dict[str, Any]) -> dict[str, Any]:
        project_id = str(candidate.get("project_id") or "").strip()
        artifact_root = _candidate_project_dir(candidate)
        evidence_sync = _sync_remote_project_evidence(
            config,
            project_id=project_id,
            artifact_root=artifact_root,
            source_project_dir=str(candidate.get("project_dir") or ""),
            source_run_id=str(
                candidate.get("current_run_id") or candidate.get("run_id") or ""
            ),
        )
        return {
            "artifact_root": str(artifact_root),
            "evidence_sync": evidence_sync,
            "local_evidence_present": _local_paper_evidence_present(artifact_root),
        }

    def _pre_evidence_paper_decision_gate(
        candidate: dict[str, Any],
    ) -> tuple[dict[str, Any], str]:
        """Return paper eligibility before any remote evidence sync side effect.

        Evidence sync is operator-visible and can alert. It must only run after
        a deterministic local/control-plane gate says the candidate is actually
        writable. Raw wake-ready rows are not enough.
        """

        legacy_finalize_positive = (
            str(candidate.get("last_run_state") or "").strip() == "finalize_positive"
        )
        if legacy_finalize_positive:
            return {"eligible": True, "reason": "legacy finalize_positive state"}, str(
                _candidate_project_dir(candidate)
            )
        row_gate = bounded_useful_signal_row_gate(candidate)
        if row_gate.get("eligible"):
            return row_gate, str(_candidate_project_dir(candidate))
        artifact_root = str(_candidate_project_dir(candidate))
        artifact_gate = paper_draft_decision_gate(artifact_root)
        if artifact_gate.get("eligible"):
            return artifact_gate, artifact_root
        return row_gate, artifact_root

    _export_namespace(
        ns,
        (
            "_candidate_project_dir",
            "_configured_worker_preflight_url",
            "_dashboard_ideas_intake_response",
            "_dashboard_next_paper_review_response",
            "_dashboard_paper_reviews_response",
            "_default_worker_url_key",
            "_detail_conflicts",
            "_intake_freshness",
            "_paper_review_detail_response",
            "_pre_evidence_paper_decision_gate",
            "_preflight_targets_default_worker",
            "_prepare_draft_evidence",
            "_require_legacy_notion_api_enabled",
            "_require_safe_paper_artifact_root",
            "_resolve_paper_artifact",
            "_rewrite_paper_review_draft",
            "_target_aware_preflight_payload",
            "_worker_detail_freshness",
            "_worker_detail_observations",
        ),
    )


def _register_control_plane_dashboard_shell_routes(
    ns: MutableMapping[str, Any],
) -> None:
    global \
        dashboard, \
        dashboard_queue_alert_check, \
        dashboard_queue_health, \
        dashboard_status, \
        dashboard_v1_automation_readiness, \
        dashboard_v1_overview, \
        dashboard_v1_research_quality, \
        dashboard_v1_source_lineage
    global dashboard_v2, dashboard_v2_asset, get_state, health, worker_callback
    _sync_namespace(ns)

    @router.get("/dashboard")
    def dashboard(
        authorization: Annotated[str | None, Header()] = None,
    ) -> RedirectResponse:
        """Legacy dashboard URL redirects to canonical Dashboard V2 (hash preserved client-side)."""
        authorize(authorization)
        return RedirectResponse(url="/control/dashboard-v2", status_code=307)

    @router.get(
        "/dashboard-v2", response_class=HTMLResponse, responses=_HTTP_503_DASHBOARD_V2
    )
    def dashboard_v2(
        authorization: Annotated[str | None, Header()] = None,
    ) -> HTMLResponse:
        authorize(authorization)
        index_path = DASHBOARD_V2_DIST_PATH / "index.html"
        if not index_path.is_file():
            raise HTTPException(
                status_code=503,
                detail="Dashboard V2 assets are missing; run npm --prefix dashboard run build.",
            )
        return HTMLResponse(
            index_path.read_text(encoding="utf-8"),
            headers={"Cache-Control": "no-store"},
        )

    @router.get(
        "/dashboard-v2/assets/{asset_path:path}", responses=_HTTP_404_DASHBOARD_ASSET
    )
    def dashboard_v2_asset(
        asset_path: str, authorization: Annotated[str | None, Header()] = None
    ) -> Response:
        authorize(authorization)
        asset_root = (DASHBOARD_V2_DIST_PATH / "assets").resolve()
        raw_candidate = asset_root / asset_path
        if _has_symlink_component(asset_root, raw_candidate):
            raise HTTPException(status_code=404, detail="asset not found")
        candidate = raw_candidate.resolve()
        try:
            candidate.relative_to(asset_root)
        except ValueError:
            raise HTTPException(status_code=404, detail="asset not found") from None
        if not candidate.is_file():
            raise HTTPException(status_code=404, detail="asset not found")
        media_type = (
            mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        )
        return Response(
            candidate.read_bytes(),
            media_type=media_type,
            headers={"Cache-Control": "no-store"},
        )

    @router.get("/health")
    def health(authorization: Annotated[str | None, Header()] = None) -> dict:
        authorize(authorization)
        backend = config.control_plane_store_backend
        db_path = str(getattr(store, "path", backend))
        return {
            "ok": True,
            "service": "enoch-langgraph-control-plane",
            "db_path": db_path,
            "store_backend": backend,
            "timestamp": utc_now(),
        }

    @router.get("/state")
    def get_state(
        authorization: Annotated[str | None, Header()] = None,
    ) -> ControlStateResponse:
        authorize(authorization)
        return state_response()

    @router.get("/api/status")
    def dashboard_status(
        refresh_worker: Annotated[bool, Query()] = False,
        authorization: Annotated[str | None, Header()] = None,
    ) -> DashboardStatusResponse:
        authorize(authorization)
        # Dashboard reads must be cheap and side-effect-free by default. Operators
        # can still request a live worker refresh explicitly with refresh_worker=true.
        return dashboard_status_response(
            refresh_worker=refresh_worker, allow_worker_refresh=refresh_worker
        )

    @router.post(
        "/api/alerts/queue-check",
        responses=_HTTP_500_UNRESOLVABLE_ARTIFACT_ROOT,
    )
    def dashboard_queue_alert_check(
        payload: dict[str, Any] | None = None,
        authorization: Annotated[str | None, Header()] = None,
    ) -> dict[str, Any]:
        authorize(authorization)
        request_payload = payload or {}
        dry_run = bool(request_payload.get("dry_run", True))
        requested_by = str(request_payload.get("requested_by") or "operator")
        if not dry_run:
            _require_writable_store("queue alert live check")
        refresh_worker = bool(request_payload.get("refresh_worker", True))
        status = dashboard_status_response(
            refresh_worker=refresh_worker, allow_worker_refresh=refresh_worker
        )
        auto_reconcile: list[dict[str, Any]] = []
        if not dry_run:
            auto_reconcile = _auto_reconcile_stale_callback_ready(
                config, store, status, requested_by=requested_by
            )
            if any(item.get("ok") for item in auto_reconcile):
                status = dashboard_status_response(
                    refresh_worker=False, allow_worker_refresh=False
                )
        if (
            auto_reconcile
            and any(item.get("ok") for item in auto_reconcile)
            and not status.active_items
        ):
            alert = {
                "ok": True,
                "source": "control_api_queue_alert_check",
                "generated_at": utc_now(),
                "dry_run": dry_run,
                "should_alert": False,
                "sent": False,
                "suppressed_by_cooldown": False,
                "fingerprint": "auto-reconciled",
                "event_id": None,
                "inserted_event": False,
                "event_append_error": "",
                "alerts_enabled": config.pushover_alerts_enabled,
                "pushover_configured": False,
                "notification": {
                    "attempted": False,
                    "ok": True,
                    "status_code": None,
                    "detail": "auto reconciled stale callback",
                },
                "hermes_alert_webhook_enabled": config.hermes_alert_webhook_enabled,
                "hermes_alert_webhook_configured": False,
                "hermes_webhook": {
                    "attempted": False,
                    "ok": True,
                    "status_code": None,
                    "detail": "auto reconciled stale callback",
                },
                "findings": [],
                "transient_suppressed_findings": [],
            }
        else:
            alert = evaluate_and_notify_queue_alerts(
                config=config,
                store=store,
                status=status,
                dry_run=dry_run,
                force_notify=bool(request_payload.get("force_notify", False)),
                requested_by=requested_by,
            )
        if auto_reconcile:
            alert["auto_reconcile"] = auto_reconcile
            if (
                any(item.get("ok") for item in auto_reconcile)
                and not status.active_items
            ):
                alert.update(
                    {
                        "should_alert": False,
                        "sent": False,
                        "suppressed_by_cooldown": False,
                        "fingerprint": "auto-reconciled",
                        "event_id": None,
                        "inserted_event": False,
                        "event_append_error": "",
                        "findings": [],
                        "notification": {
                            "attempted": False,
                            "ok": True,
                            "status_code": None,
                            "detail": "auto reconciled stale callback",
                        },
                    }
                )
        operator_trace = OperatorTrace.from_config(config)
        trace_id = OperatorTrace.new_trace_id("queue-check")
        operator_trace.record(
            "queue_check.result",
            trace_id=trace_id,
            requested_by=requested_by,
            dry_run=dry_run,
            should_alert=alert.get("should_alert"),
            sent=alert.get("sent"),
            findings=_operator_trace_queue_findings(alert.get("findings", [])),
            auto_reconcile=auto_reconcile[:10],
            before={
                "active_count": len(status.active_items),
                "blockers": status.dispatch_blockers,
            },
        )
        alert["trace_id"] = trace_id
        return alert

    @router.get("/api/queue-health")
    def dashboard_queue_health(
        refresh_worker: Annotated[bool, Query()] = False,
        authorization: Annotated[str | None, Header()] = None,
    ) -> dict[str, Any]:
        authorize(authorization)
        status = dashboard_status_response(refresh_worker=refresh_worker)
        active = status.active_items[0] if status.active_items else None
        run_id = str((active or {}).get("current_run_id") or "")
        project_id = str((active or {}).get("project_id") or "")
        alert = evaluate_and_notify_queue_alerts(
            config=config,
            store=store,
            status=status,
            dry_run=True,
            force_notify=False,
            requested_by="dashboard.queue_health",
        )
        return {
            "ok": True,
            "source": "control_api_queue_health",
            "authority": "aggregated queue health read model",
            "generated_at": utc_now(),
            "status": status.model_dump(mode="json"),
            "active_run_detail": {
                "queue_item": active,
                "run": store.run_row(run_id) if run_id else None,
                "project": store.project_row(project_id) if project_id else None,
                "events": _project_events(project_id) if project_id else [],
            },
            "latest_alert_check": alert,
            "recent_alert_events": store.event_rows(
                limit=20, entity_type="queue_alert"
            ),
            "recent_worker_callbacks": store.event_rows(
                limit=20, search="worker_callback."
            ),
        }

    @router.post(
        "/api/worker-callback",
        responses=_HTTP_500_UNRESOLVABLE_ARTIFACT_ROOT,
    )
    def worker_callback(
        callback: GateCallback, authorization: Annotated[str | None, Header()] = None
    ) -> dict[str, Any]:
        authorize(authorization)
        _require_writable_store("worker callback recording")
        try:
            event_id, inserted, row = store.record_worker_callback(callback)
        except IdempotencyConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        decision_sync: dict[str, Any] | None = None
        callback_run_id = str(callback.run_id or "").strip()
        row_run_id = str((row or {}).get("current_run_id") or "").strip()
        row_last_run_state = str((row or {}).get("last_run_state") or "").strip()
        should_sync_decision = (
            inserted
            and callback.event_type in {"wake_ready", "session_finished_ready"}
            and bool(row)
            and row_run_id == callback_run_id
            and row_last_run_state in {"wake_ready", "session_finished_ready"}
        )
        if should_sync_decision and row:
            project_id = str(row.get("project_id") or callback.project_id or "").strip()
            artifact_root, project_dir_text = _artifact_root_for_queue_row(config, row)
            decision_gate = paper_draft_decision_gate(artifact_root)
            evidence_sync = _evidence_sync_skipped_by_gate(config, decision_gate)
            if decision_gate.get("eligible") or not decision_gate.get("values"):
                evidence_sync = _sync_remote_project_evidence(
                    config,
                    project_id=project_id,
                    artifact_root=artifact_root,
                    source_project_dir=project_dir_text,
                    source_run_id=str(callback.run_id or ""),
                    **_worker_evidence_sync_kwargs_for_row(config, row),
                )
                decision_gate = paper_draft_decision_gate(artifact_root)
            decision_sync = {
                "artifact_root": str(artifact_root),
                "evidence_sync": evidence_sync,
                "decision_gate": decision_gate,
            }
            local_evidence_present = _local_paper_evidence_present(artifact_root)
            if (
                config.paper_evidence_sync_enabled
                and not local_evidence_present
                and decision_gate.get("eligible")
            ):
                decision_sync["evidence_alert"] = _record_paper_evidence_blocked(
                    config,
                    store,
                    entity_type="project",
                    entity_id=project_id,
                    project_id=project_id,
                    run_id=str(callback.run_id or ""),
                    artifact_root=str(artifact_root),
                    evidence_sync=evidence_sync,
                )
            if local_evidence_present and hasattr(
                store, "record_project_decision_gate"
            ):
                try:
                    decision_record = store.record_project_decision_gate(
                        project_id=project_id,
                        run_id=str(callback.run_id or ""),
                        artifact_root=artifact_root,
                    )
                except Exception as exc:
                    decision_record = {
                        "ok": False,
                        "persisted": False,
                        "reason": "decision persistence failed",
                        "error_type": type(exc).__name__,
                    }
                decision_sync["decision_record"] = decision_record
                if decision_record.get("persisted") and project_id:
                    store.update_project_dir(project_id, str(artifact_root))
                    row = store.queue_row(project_id) or row
        return {
            "ok": True,
            "accepted": True,
            "run_id": callback.run_id,
            "session_id": callback.session_id,
            "event_type": callback.event_type,
            "state": callback.event_type,
            "idempotency_key": callback.idempotency_key,
            "event_id": event_id,
            "inserted_event": inserted,
            "queue_item": row,
            "decision_sync": decision_sync,
            "controller_action": "record_worker_callback",
            "next_action_hint": row.get("next_action_hint")
            if row
            else "callback_recorded_no_queue_row",
        }

    @router.get("/api/v1/research-quality")
    def dashboard_v1_research_quality(
        authorization: Annotated[str | None, Header()] = None,
    ) -> dict[str, Any]:
        authorize(authorization)
        return _research_quality_payload()

    @router.get("/api/v1/source-lineage")
    def dashboard_v1_source_lineage(
        authorization: Annotated[str | None, Header()] = None,
    ) -> dict[str, Any]:
        authorize(authorization)
        return _source_lineage_payload()

    @router.get("/api/v1/automation-readiness")
    def dashboard_v1_automation_readiness(
        authorization: Annotated[str | None, Header()] = None,
    ) -> dict[str, Any]:
        authorize(authorization)
        return _automation_readiness_payload()

    @router.get("/api/v1/overview")
    def dashboard_v1_overview(
        authorization: Annotated[str | None, Header()] = None,
        active_limit: Annotated[int, Query(ge=1, le=25)] = 5,
        event_limit: Annotated[int, Query(ge=0, le=50)] = 10,
    ) -> dict[str, Any]:
        authorize(authorization)
        # Compute worker-lane capacity once and feed it into the overview read
        # model so `top_actions.dispatch_next` is lane-aware. Aggregate
        # `counts.active` / `counts.queued` are NOT used to imply lane dispatch
        # truth — the CPU lane being busy must not suppress dispatch on an
        # idle GB10 lane and vice versa. Use the bounded `_active_items_fast`
        # / `_queued_items_fast` helpers so the v1 dashboard contract (no
        # `queue_rows()` / `paper_rows()` legacy reads) is preserved.
        active_for_lanes = _active_items_fast()
        queued_for_lanes = _queued_items_fast()
        worker_lanes = _worker_lane_capacity(
            active=active_for_lanes, rows=queued_for_lanes
        )
        try:
            overview_min_admission_score = float(
                os.environ.get("ENOCH_RESEARCH_ADMIT_THRESHOLD") or 72.0
            )
        except ValueError:
            overview_min_admission_score = 72.0
        lane_feed_pressure = _research_lane_feed_pressure(
            active=active_for_lanes,
            queued=queued_for_lanes,
            lanes=worker_lanes,
            min_queue_depth=_bounded_int_env(
                "ENOCH_RESEARCH_MIN_QUEUE_DEPTH_PER_LANE", 25, 0, 100
            ),
            min_admission_score=overview_min_admission_score,
        )
        for lane in worker_lanes:
            key = str(lane.get("machine_target") or lane.get("lane_key") or "")
            if key in lane_feed_pressure:
                lane["feed_pressure"] = lane_feed_pressure[key]
        data = read_models.overview(
            store,
            active_limit=active_limit,
            event_limit=event_limit,
            worker_lanes=worker_lanes,
            flags=store.flags(),
        )
        open_candidate = _open_worker_dispatch_candidate(
            active=active_for_lanes, queued=queued_for_lanes
        )
        data["next_candidate"] = (
            read_models.summarize_queue_row(open_candidate) if open_candidate else None
        )
        return {
            "ok": True,
            "source": "control_api_v1_overview",
            "authority": "bounded dashboard read model",
            "generated_at": utc_now(),
            **data,
            "links": {
                "queue": "/control/api/v1/queue",
                "runs": "/control/api/v1/runs",
                "papers": "/control/api/v1/papers",
                "events": "/control/api/v1/events",
            },
        }

    _export_namespace(
        ns,
        (
            "dashboard",
            "dashboard_queue_alert_check",
            "dashboard_queue_health",
            "dashboard_status",
            "dashboard_v1_automation_readiness",
            "dashboard_v1_overview",
            "dashboard_v1_research_quality",
            "dashboard_v1_source_lineage",
            "dashboard_v2",
            "dashboard_v2_asset",
            "get_state",
            "health",
            "worker_callback",
        ),
    )


def _register_control_plane_dashboard_v1_routes(ns: MutableMapping[str, Any]) -> None:
    global \
        dashboard_v1_events, \
        dashboard_v1_lanes, \
        dashboard_v1_observability_health, \
        dashboard_v1_observability_memory, \
        dashboard_v1_paper_detail, \
        dashboard_v1_papers, \
        dashboard_v1_project_detail, \
        dashboard_v1_projects
    global \
        dashboard_v1_queue, \
        dashboard_v1_run_detail, \
        dashboard_v1_runs, \
        launch_next_followup
    _sync_namespace(ns)

    @router.post("/api/v1/followups/launch-next")
    def launch_next_followup(
        payload: FollowupLaunchRequest,
        authorization: Annotated[str | None, Header()] = None,
    ) -> FollowupLaunchResponse:
        authorize(authorization)
        if not payload.dry_run:
            _require_writable_store("follow-up launch")
            flags = store.flags()
            if (
                flags.maintenance_mode
                and payload.override_hold_action != "followup-launch-while-held"
            ):
                raise HTTPException(
                    status_code=409,
                    detail="maintenance mode blocks follow-up launch; set override_hold_action=followup-launch-while-held for an explicit operator override",
                )
            if (
                flags.queue_paused
                and payload.override_hold_action != "followup-launch-while-held"
            ):
                raise HTTPException(
                    status_code=409,
                    detail="queue pause blocks follow-up launch; set override_hold_action=followup-launch-while-held for an explicit operator override",
                )
        launcher = getattr(store, "launch_followup_candidate", None)
        if not callable(launcher):
            return FollowupLaunchResponse(
                ok=True,
                action="noop",
                reason="store does not support follow-up branching",
            )
        result = launcher(
            project_id=payload.project_id,
            dry_run=payload.dry_run,
            requested_by=payload.requested_by,
            max_followup_depth=payload.max_followup_depth,
        )
        return FollowupLaunchResponse(
            ok=bool(result.get("ok", True)),
            action=result.get("action") or "noop",
            reason=result.get("reason") or "",
            candidate=result.get("candidate"),
            followup=result.get("followup"),
            event_id=result.get("event_id"),
        )

    @router.get("/api/v1/lanes")
    def dashboard_v1_lanes(
        authorization: Annotated[str | None, Header()] = None,
    ) -> dict[str, Any]:
        authorize(authorization)
        active_for_lanes = _active_items_fast(limit=10)
        queued_for_lanes = _queued_items_fast()
        active = [read_models.summarize_queue_row(row) for row in active_for_lanes]
        next_candidate = _open_worker_dispatch_candidate(
            active=active_for_lanes, queued=queued_for_lanes
        )
        return {
            "ok": True,
            "source": "control_api_v1_lanes",
            "authority": "bounded active-lane read model",
            "generated_at": utc_now(),
            "active_items": active,
            "next_candidate": read_models.summarize_queue_row(next_candidate)
            if next_candidate
            else None,
            "counts": store.queue_counts_sql(),
        }

    @router.get("/api/v1/queue")
    def dashboard_v1_queue(
        authorization: Annotated[str | None, Header()] = None,
        queue: Annotated[str, Query()] = "all",
        status: str = "",
        search: str = "",
        cursor: str = "",
        page_size: Annotated[int, Query(ge=1, le=200)] = 50,
        sort: str = "priority",
    ) -> dict[str, Any]:
        authorize(authorization)
        safe_size = read_models.page_size(page_size)
        rows, next_cursor, has_more = store.queue_page(
            queue=queue,
            status=status,
            search=search,
            cursor=cursor,
            page_size=safe_size,
            sort=sort,
        )
        out = [read_models.summarize_queue_list_row(row) for row in rows]
        return {
            "ok": True,
            "source": "control_api_v1_queue",
            "authority": "bounded SQL queue read model",
            "generated_at": utc_now(),
            "counts": store.queue_counts_sql(),
            "page": read_models.page_response(
                rows=out,
                next_cursor=next_cursor,
                has_more=has_more,
                page_size_value=safe_size,
                cursor=cursor,
                filters={
                    "queue": queue,
                    "status": status,
                    "search": search,
                    "sort": sort,
                },
            ),
            "rows": out,
        }

    @router.get("/api/v1/runs")
    def dashboard_v1_runs(
        authorization: Annotated[str | None, Header()] = None,
        state: str = "",
        project_id: str = "",
        search: str = "",
        cursor: str = "",
        page_size: Annotated[int, Query(ge=1, le=200)] = 50,
        sort: str = "recent",
    ) -> dict[str, Any]:
        authorize(authorization)
        safe_size = read_models.page_size(page_size)
        rows, next_cursor, has_more = store.run_page(
            state=state,
            project_id=project_id,
            search=search,
            cursor=cursor,
            page_size=safe_size,
            sort=sort,
        )
        out = [read_models.summarize_run_list_row(row) for row in rows]
        return {
            "ok": True,
            "source": "control_api_v1_runs",
            "authority": "bounded SQL run read model",
            "generated_at": utc_now(),
            "page": read_models.page_response(
                rows=out,
                next_cursor=next_cursor,
                has_more=has_more,
                page_size_value=safe_size,
                cursor=cursor,
                filters={
                    "state": state,
                    "project_id": project_id,
                    "search": search,
                    "sort": sort,
                },
            ),
            "rows": out,
        }

    @router.get("/api/v1/runs/{run_id}", responses=_HTTP_404_RUN)
    def dashboard_v1_run_detail(
        run_id: str,
        authorization: Annotated[str | None, Header()] = None,
        event_limit: Annotated[int, Query(ge=0, le=100)] = 50,
    ) -> dict[str, Any]:
        authorize(authorization)
        run = store.run_row(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        project_id = str(run.get("project_id") or "")
        events, next_cursor, has_more = store.event_page(
            entity_id=run_id, page_size=event_limit, include_payload=False
        )
        papers, paper_cursor, paper_more = store.paper_page(run_id=run_id, page_size=25)
        queue_item = store.queue_row(project_id) if project_id else None
        if queue_item and str(queue_item.get("current_run_id") or "").strip() != run_id:
            queue_item = None
        return {
            "ok": True,
            "source": "control_api_v1_run",
            "authority": "bounded SQL run detail read model",
            "generated_at": utc_now(),
            "run_id": run_id,
            "run": read_models.summarize_run_row(run),
            "project": store.project_row(project_id) if project_id else None,
            "queue_item": read_models.summarize_queue_row(queue_item)
            if queue_item
            else None,
            "papers": [read_models.summarize_paper_row(row) for row in papers],
            "papers_page": read_models.page_response(
                rows=papers,
                next_cursor=paper_cursor,
                has_more=paper_more,
                page_size_value=25,
                cursor="",
                filters={"run_id": run_id},
            ),
            "events": events,
            "events_page": read_models.page_response(
                rows=events,
                next_cursor=next_cursor,
                has_more=has_more,
                page_size_value=read_models.page_size(event_limit, cap=100),
                cursor="",
                filters={"entity_id": run_id},
            ),
        }

    @router.get("/api/v1/projects")
    def dashboard_v1_projects(
        authorization: Annotated[str | None, Header()] = None,
        status: str = "",
        search: str = "",
        cursor: str = "",
        page_size: Annotated[int, Query(ge=1, le=200)] = 50,
        sort: str = "recent",
    ) -> dict[str, Any]:
        authorize(authorization)
        safe_size = read_models.page_size(page_size)
        rows, next_cursor, has_more = store.project_page(
            status=status, search=search, cursor=cursor, page_size=safe_size, sort=sort
        )
        out = [read_models.summarize_project_list_row(row) for row in rows]
        return {
            "ok": True,
            "source": "control_api_v1_projects",
            "authority": "bounded SQL project read model",
            "generated_at": utc_now(),
            "page": read_models.page_response(
                rows=out,
                next_cursor=next_cursor,
                has_more=has_more,
                page_size_value=safe_size,
                cursor=cursor,
                filters={"status": status, "search": search, "sort": sort},
            ),
            "rows": out,
        }

    @router.get("/api/v1/projects/{project_id}", responses=_HTTP_404_PROJECT)
    def dashboard_v1_project_detail(
        project_id: str,
        authorization: Annotated[str | None, Header()] = None,
        event_limit: Annotated[int, Query(ge=0, le=100)] = 50,
    ) -> dict[str, Any]:
        authorize(authorization)
        project = store.project_row(project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="project not found")
        runs, run_cursor, run_more = store.run_page(project_id=project_id, page_size=25)
        papers, paper_cursor, paper_more = store.paper_page(
            project_id=project_id, page_size=25
        )
        events, event_cursor, event_more = store.event_page(
            entity_id=project_id, page_size=event_limit, include_payload=False
        )
        queue_item = store.queue_row(project_id)
        return {
            "ok": True,
            "source": "control_api_v1_project",
            "authority": "bounded SQL project detail read model",
            "generated_at": utc_now(),
            "project_id": project_id,
            "project": project,
            "queue_item": read_models.summarize_queue_row(queue_item)
            if queue_item
            else None,
            "runs": [read_models.summarize_run_row(row) for row in runs],
            "runs_page": read_models.page_response(
                rows=runs,
                next_cursor=run_cursor,
                has_more=run_more,
                page_size_value=25,
                cursor="",
                filters={"project_id": project_id},
            ),
            "papers": [read_models.summarize_paper_row(row) for row in papers],
            "papers_page": read_models.page_response(
                rows=papers,
                next_cursor=paper_cursor,
                has_more=paper_more,
                page_size_value=25,
                cursor="",
                filters={"project_id": project_id},
            ),
            "events": events,
            "events_page": read_models.page_response(
                rows=events,
                next_cursor=event_cursor,
                has_more=event_more,
                page_size_value=read_models.page_size(event_limit, cap=100),
                cursor="",
                filters={"entity_id": project_id},
            ),
        }

    @router.get("/api/v1/papers")
    def dashboard_v1_papers(
        authorization: Annotated[str | None, Header()] = None,
        status: str = "",
        search: str = "",
        cursor: str = "",
        page_size: Annotated[int, Query(ge=1, le=200)] = 50,
        sort: str = "recent",
    ) -> dict[str, Any]:
        authorize(authorization)
        safe_size = read_models.page_size(page_size)
        rows, next_cursor, has_more = store.paper_page(
            status=status, search=search, cursor=cursor, page_size=safe_size, sort=sort
        )
        out = [read_models.summarize_paper_list_row(row) for row in rows]
        return {
            "ok": True,
            "source": "control_api_v1_papers",
            "authority": "bounded SQL paper read model",
            "generated_at": utc_now(),
            "counts": store.paper_counts_sql(),
            "page": read_models.page_response(
                rows=out,
                next_cursor=next_cursor,
                has_more=has_more,
                page_size_value=safe_size,
                cursor=cursor,
                filters={"status": status, "search": search, "sort": sort},
            ),
            "rows": out,
        }

    @router.get("/api/v1/papers/{paper_id}", responses=_HTTP_404_PAPER)
    def dashboard_v1_paper_detail(
        paper_id: str,
        authorization: Annotated[str | None, Header()] = None,
        event_limit: Annotated[int, Query(ge=0, le=100)] = 50,
    ) -> dict[str, Any]:
        authorize(authorization)
        paper = store.paper_row(paper_id)
        if paper is None:
            raise HTTPException(status_code=404, detail=_HTTP_404_PAPER_DETAIL)
        project_id = str(paper.get("project_id") or "")
        run_id = str(paper.get("run_id") or "")
        events, next_cursor, has_more = store.event_page(
            entity_id=paper_id, page_size=event_limit, include_payload=False
        )
        run_row = store.run_row(run_id) if run_id else None
        queue_item = store.queue_row(project_id) if project_id else None
        return {
            "ok": True,
            "source": "control_api_v1_paper",
            "authority": "bounded SQL paper detail read model",
            "generated_at": utc_now(),
            "paper_id": paper_id,
            "paper": read_models.summarize_paper_row(paper),
            "project": store.project_row(project_id) if project_id else None,
            "run": read_models.summarize_run_row(run_row) if run_row else None,
            "queue_item": read_models.summarize_queue_row(queue_item)
            if queue_item
            else None,
            "events": events,
            "events_page": read_models.page_response(
                rows=events,
                next_cursor=next_cursor,
                has_more=has_more,
                page_size_value=read_models.page_size(event_limit, cap=100),
                cursor="",
                filters={"entity_id": paper_id},
            ),
        }

    @router.get("/api/v1/events")
    def dashboard_v1_events(
        authorization: Annotated[str | None, Header()] = None,
        event_id: str = "",
        entity_type: str = "",
        entity_id: str = "",
        event_type: str = "",
        search: str = "",
        cursor: str = "",
        page_size: Annotated[int, Query(ge=1, le=200)] = 50,
        include_payload: bool = False,
        sort: str = "recent",
    ) -> dict[str, Any]:
        authorize(authorization)
        safe_size = read_models.page_size(page_size)
        rows, next_cursor, has_more = store.event_page(
            event_id=event_id,
            entity_type=entity_type,
            entity_id=entity_id,
            event_type=event_type,
            search=search,
            cursor=cursor,
            page_size=safe_size,
            include_payload=include_payload,
            sort=sort,
        )
        return {
            "ok": True,
            "source": "control_api_v1_events",
            "authority": "bounded SQL event read model",
            "generated_at": utc_now(),
            "page": read_models.page_response(
                rows=rows,
                next_cursor=next_cursor,
                has_more=has_more,
                page_size_value=safe_size,
                cursor=cursor,
                filters={
                    "event_id": event_id,
                    "entity_type": entity_type,
                    "entity_id": entity_id,
                    "event_type": event_type,
                    "search": search,
                    "include_payload": include_payload,
                    "sort": sort,
                },
            ),
            "rows": rows,
        }

    @router.get("/api/v1/observability/health")
    def dashboard_v1_observability_health(
        authorization: Annotated[str | None, Header()] = None,
    ) -> dict[str, Any]:
        authorize(authorization)
        latest_route_observation = None
        if config.route_observability_enabled:
            path = (
                Path(config.route_observability_log_path).expanduser()
                if config.route_observability_log_path
                else config.expanded_state_dir / "route_observations.jsonl"
            )
            try:
                with path.open("rb") as handle:
                    handle.seek(0, 2)
                    size = handle.tell()
                    handle.seek(max(0, size - 4096))
                    latest = handle.readlines()[-1:] or []
                    latest_route_observation = (
                        latest[0].decode("utf-8", errors="replace").strip()
                        if latest
                        else None
                    )
            except OSError:
                latest_route_observation = None
        return {
            "ok": True,
            "source": "control_api_v1_observability_health",
            "authority": "bounded route observability read model",
            "generated_at": utc_now(),
            "route_observability_enabled": config.route_observability_enabled,
            "route_observability_log_configured": bool(
                config.route_observability_log_path
            ),
            "sentry_configured": bool(os.environ.get("SENTRY_DSN", "").strip()),
            "sentry_enabled": is_sentry_enabled(),
            "sentry_environment": os.environ.get("ENOCH_SENTRY_ENV")
            or os.environ.get("ENOCH_ENV")
            or "production",
            "sentry_release": os.environ.get("ENOCH_SENTRY_RELEASE")
            or os.environ.get("ENOCH_RELEASE")
            or "unknown",
            "latest_route_observation": latest_route_observation,
        }

    @router.get("/api/v1/observability/memory")
    def dashboard_v1_observability_memory(
        authorization: Annotated[str | None, Header()] = None,
    ) -> dict[str, Any]:
        authorize(authorization)
        rss = current_rss_mib()
        peak = peak_rss_mib()
        warn_threshold = config.route_observability_memory_warn_rss_mib
        return {
            "ok": True,
            "source": "control_api_v1_observability_memory",
            "authority": "current controller process memory sample",
            "generated_at": utc_now(),
            "rss_mib": rss,
            "peak_rss_mib": peak,
            "warn_threshold_mib": warn_threshold,
            "memory_warn": bool(
                warn_threshold and rss is not None and rss >= warn_threshold
            ),
            "route_observability_enabled": config.route_observability_enabled,
        }

    _export_namespace(
        ns,
        (
            "dashboard_v1_events",
            "dashboard_v1_lanes",
            "dashboard_v1_observability_health",
            "dashboard_v1_observability_memory",
            "dashboard_v1_paper_detail",
            "dashboard_v1_papers",
            "dashboard_v1_project_detail",
            "dashboard_v1_projects",
            "dashboard_v1_queue",
            "dashboard_v1_run_detail",
            "dashboard_v1_runs",
            "launch_next_followup",
        ),
    )


def _register_control_plane_api_read_routes(ns: MutableMapping[str, Any]) -> None:
    global dashboard_project, dashboard_queue, dashboard_run
    _sync_namespace(ns)

    @router.get("/api/queues/{queue}")
    def dashboard_queue(
        queue: str,
        authorization: Annotated[str | None, Header()] = None,
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=500)] = 50,
        search: str = "",
        status: str = "",
        sort: str = "dispatch_priority",
    ) -> DashboardQueueResponse:
        authorize(authorization)
        all_rows = [_enrich_queue_row(row) for row in store.queue_rows()]
        selected = (
            [row for row in all_rows if queue in _classify_queue(row)]
            if queue != "all"
            else all_rows
        )
        if status:
            selected = [
                row
                for row in selected
                if _normal_status(row.get("status")) == _normal_status(status)
            ]
        selected = _sort_rows(_search_rows(selected, search), sort)
        page_rows, safe_page, safe_size = _paginate(
            selected, page=page, page_size=page_size
        )
        return DashboardQueueResponse(
            queue=queue,
            counts=_queue_counts(all_rows),
            rows=page_rows,
            page=DashboardPageMeta(
                page=safe_page,
                page_size=safe_size,
                total=len(selected),
                returned=len(page_rows),
                queue=queue,
                filters={"search": search, "status": status},
                sort=sort,
            ),
            source_freshness=_db_freshness("canonical queue/project read model"),
            conflicts=[],
        )

    @router.get("/api/projects/{project_id}", responses=_HTTP_404_PROJECT)
    def dashboard_project(
        project_id: str, authorization: Annotated[str | None, Header()] = None
    ) -> DashboardProjectDetailResponse:
        authorize(authorization)
        project = store.project_row(project_id)
        queue_item = store.queue_row(project_id)
        if project is None and queue_item is None:
            raise HTTPException(status_code=404, detail="project not found")
        runs = [row for row in store.run_rows() if row.get("project_id") == project_id]
        papers = [
            row for row in store.paper_rows() if row.get("project_id") == project_id
        ]
        observations = _worker_detail_observations(
            project_id=project_id,
            run_id=str((queue_item or {}).get("current_run_id") or ""),
        )
        warnings = []
        active = bool(queue_item and "active" in _classify_queue(queue_item))
        if (
            queue_item
            and "active" in _classify_queue(queue_item)
            and not runs
            and not (
                observations.get("worker_dashboard_api_project")
                or observations.get("worker_dashboard_api")
            )
        ):
            warnings.append(
                DashboardFinding(
                    severity="warn",
                    source="control_plane_db",
                    authority="project detail aggregate",
                    message="active queue item has no local run row or worker observation",
                    suggested_action="inspect worker and reconcile if process exited",
                )
            )
        return DashboardProjectDetailResponse(
            project_id=project_id,
            project=project,
            queue_item=_enrich_queue_row(queue_item) if queue_item else None,
            runs=runs,
            papers=papers,
            events=_project_events(project_id),
            worker_observations=observations,
            source_freshness={
                **_db_freshness("project/queue/run/paper aggregate"),
                **_worker_detail_freshness(
                    "worker_dashboard_api",
                    "project-scoped cached worker detail",
                    f"project:{project_id}",
                ),
            },
            warnings=warnings,
            conflicts=_detail_conflicts(
                active=active, worker_observations=observations
            ),
        )

    @router.get("/api/runs/{run_id}", responses=_HTTP_404_RUN)
    def dashboard_run(
        run_id: str, authorization: Annotated[str | None, Header()] = None
    ) -> DashboardRunDetailResponse:
        authorize(authorization)
        run = store.run_row(run_id)
        queue_item = next(
            (row for row in store.queue_rows() if row.get("current_run_id") == run_id),
            None,
        )
        project_id = str((run or queue_item or {}).get("project_id") or "")
        if run is None and queue_item is None:
            raise HTTPException(status_code=404, detail="run not found")
        observations = _worker_detail_observations(project_id=project_id, run_id=run_id)
        active = bool(queue_item and "active" in _classify_queue(queue_item))
        return DashboardRunDetailResponse(
            run_id=run_id,
            run=run,
            queue_item=_enrich_queue_row(queue_item) if queue_item else None,
            project=store.project_row(project_id) if project_id else None,
            papers=[row for row in store.paper_rows() if row.get("run_id") == run_id],
            events=store.event_rows(limit=100, entity_id=run_id)
            + (store.event_rows(limit=50, entity_id=project_id) if project_id else []),
            worker_observations=observations,
            source_freshness={
                **_db_freshness("run/project/paper aggregate"),
                **_worker_detail_freshness(
                    "worker_dashboard_api",
                    "run-scoped cached worker detail",
                    f"run:{run_id}",
                ),
            },
            warnings=[]
            if (
                observations.get("worker_dashboard_api_run")
                or observations.get("worker_dashboard_api")
            )
            else [
                DashboardFinding(
                    severity="info",
                    source="worker_dashboard_api",
                    authority="run detail worker evidence",
                    message="no worker observation cached yet",
                    suggested_action="run /control/api/preflight or refresh run detail when available",
                )
            ],
            conflicts=_detail_conflicts(
                active=active, worker_observations=observations
            ),
        )

    _export_namespace(ns, ("dashboard_project", "dashboard_queue", "dashboard_run"))


def _register_control_plane_publication_routes(ns: MutableMapping[str, Any]) -> None:
    global \
        dashboard_events, \
        dashboard_ideas_intake, \
        dashboard_next_paper_review, \
        dashboard_next_publication_automation, \
        dashboard_paper, \
        dashboard_paper_artifact, \
        dashboard_paper_review, \
        dashboard_paper_review_approve_finalization
    global \
        dashboard_paper_review_checklist, \
        dashboard_paper_review_claim, \
        dashboard_paper_review_prepare_finalization_package, \
        dashboard_paper_review_rewrite_draft, \
        dashboard_paper_review_status, \
        dashboard_paper_reviews, \
        dashboard_paper_reviews_backfill, \
        dashboard_paper_reviews_rewrite_batch
    global \
        dashboard_papers, \
        dashboard_publication_automation, \
        dashboard_publication_automation_item, \
        dashboard_research_facility, \
        dashboard_research_generate_batch, \
        dashboard_research_generate_provider_batch
    _sync_namespace(ns)

    @router.post(
        "/api/publication-automation/backfill",
        responses=_HTTP_WRITABLE_IDEMPOTENCY_RESPONSES,
    )
    @router.post(
        "/api/paper-reviews/backfill", responses=_HTTP_WRITABLE_IDEMPOTENCY_RESPONSES
    )
    def dashboard_paper_reviews_backfill(
        payload: PaperReviewBackfillRequest,
        authorization: Annotated[str | None, Header()] = None,
    ) -> PaperReviewBackfillResponse:
        authorize(authorization)
        _require_writable_store("publication automation backfill")
        try:
            inserted, created, updated, skipped, errors = store.backfill_paper_reviews(
                payload
            )
        except IdempotencyConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return PaperReviewBackfillResponse(
            dry_run=payload.dry_run,
            inserted_event=inserted,
            created=created,
            updated=updated,
            skipped=skipped,
            errors=errors,
        )

    @router.get("/api/publication-automation")
    def dashboard_publication_automation(
        authorization: Annotated[str | None, Header()] = None,
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=500)] = 50,
        review_status: str = "",
        paper_status: str = "",
        search: str = "",
        sort: str = "-rank_score",
        include_rank_reasons: bool = True,
    ) -> DashboardPaperReviewsResponse:
        return _dashboard_paper_reviews_response(
            authorization=authorization,
            page=page,
            page_size=page_size,
            review_status=review_status,
            paper_status=paper_status,
            search=search,
            sort=sort,
            include_rank_reasons=include_rank_reasons,
            queue_label="publication_automation",
        )

    @router.get("/api/paper-reviews")
    def dashboard_paper_reviews(
        authorization: Annotated[str | None, Header()] = None,
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=500)] = 50,
        review_status: str = "",
        paper_status: str = "",
        search: str = "",
        sort: str = "-rank_score",
        include_rank_reasons: bool = True,
    ) -> DashboardPaperReviewsResponse:
        return _dashboard_paper_reviews_response(
            authorization=authorization,
            page=page,
            page_size=page_size,
            review_status=review_status,
            paper_status=paper_status,
            search=search,
            sort=sort,
            include_rank_reasons=include_rank_reasons,
            queue_label="paper_reviews",
        )

    @router.get(
        "/api/publication-automation/next",
        responses=_HTTP_404_PUBLICATION_AUTOMATION_NEXT,
    )
    def dashboard_next_publication_automation(
        authorization: Annotated[str | None, Header()] = None,
        review_status: str = "",
        paper_status: str = "publication_draft",
        search: str = "",
    ) -> DashboardPaperReviewDetailResponse:
        try:
            return _dashboard_next_paper_review_response(
                authorization=authorization,
                review_status=review_status,
                paper_status=paper_status,
                search=search,
            )
        except PublicationAutomationNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get(
        "/api/paper-reviews/next", responses=_HTTP_404_PUBLICATION_AUTOMATION_NEXT
    )
    def dashboard_next_paper_review(
        authorization: Annotated[str | None, Header()] = None,
        review_status: str = "",
        paper_status: str = "publication_draft",
        search: str = "",
    ) -> DashboardPaperReviewDetailResponse:
        try:
            return _dashboard_next_paper_review_response(
                authorization=authorization,
                review_status=review_status,
                paper_status=paper_status,
                search=search,
            )
        except PublicationAutomationNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get(
        "/api/publication-automation/{paper_id}",
        responses=_HTTP_PUBLICATION_AUTOMATION_DETAIL_RESPONSES,
    )
    def dashboard_publication_automation_item(
        paper_id: str, authorization: Annotated[str | None, Header()] = None
    ) -> DashboardPaperReviewDetailResponse:
        authorize(authorization)
        try:
            return _paper_review_detail_response(paper_id)
        except PublicationAutomationNotFoundError as exc:
            raise HTTPException(
                status_code=404, detail=PUBLICATION_AUTOMATION_ITEM_NOT_FOUND
            ) from exc

    @router.get(
        "/api/paper-reviews/{paper_id}",
        responses=_HTTP_PUBLICATION_AUTOMATION_DETAIL_RESPONSES,
    )
    def dashboard_paper_review(
        paper_id: str, authorization: Annotated[str | None, Header()] = None
    ) -> DashboardPaperReviewDetailResponse:
        authorize(authorization)
        try:
            return _paper_review_detail_response(paper_id)
        except PublicationAutomationNotFoundError as exc:
            raise HTTPException(
                status_code=404, detail=PUBLICATION_AUTOMATION_ITEM_NOT_FOUND
            ) from exc

    @router.post(
        "/api/publication-automation/{paper_id}/claim",
        responses=_HTTP_PAPER_REVIEW_MUTATION_RESPONSES,
    )
    @router.post(
        "/api/paper-reviews/{paper_id}/claim",
        responses=_HTTP_PAPER_REVIEW_MUTATION_RESPONSES,
    )
    def dashboard_paper_review_claim(
        paper_id: str,
        payload: PaperReviewClaimRequest,
        authorization: Annotated[str | None, Header()] = None,
    ) -> PaperReviewMutationResponse:
        authorize(authorization)
        _require_writable_store("publication automation claim")
        try:
            event_id, inserted, item = store.claim_paper_review(paper_id, payload)
        except IdempotencyConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return PaperReviewMutationResponse(
            inserted_event=inserted, event_id=event_id, item=item
        )

    @router.post(
        "/api/publication-automation/{paper_id}/checklist/{item_id}",
        responses=_HTTP_PAPER_REVIEW_MUTATION_RESPONSES,
    )
    @router.post(
        "/api/paper-reviews/{paper_id}/checklist/{item_id}",
        responses=_HTTP_PAPER_REVIEW_MUTATION_RESPONSES,
    )
    def dashboard_paper_review_checklist(
        paper_id: str,
        item_id: str,
        payload: PaperReviewChecklistUpdateRequest,
        authorization: Annotated[str | None, Header()] = None,
    ) -> PaperReviewMutationResponse:
        authorize(authorization)
        _require_writable_store("publication automation checklist update")
        try:
            event_id, inserted, item = store.update_paper_review_checklist(
                paper_id, item_id, payload
            )
        except IdempotencyConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return PaperReviewMutationResponse(
            inserted_event=inserted, event_id=event_id, item=item
        )

    @router.post(
        "/api/publication-automation/{paper_id}/status",
        responses=_HTTP_PAPER_REVIEW_MUTATION_RESPONSES,
    )
    @router.post(
        "/api/paper-reviews/{paper_id}/status",
        responses=_HTTP_PAPER_REVIEW_MUTATION_RESPONSES,
    )
    def dashboard_paper_review_status(
        paper_id: str,
        payload: PaperReviewStatusUpdateRequest,
        authorization: Annotated[str | None, Header()] = None,
    ) -> PaperReviewMutationResponse:
        authorize(authorization)
        _require_writable_store("publication automation status update")
        try:
            event_id, inserted, item = store.update_paper_review_status(
                paper_id, payload
            )
        except IdempotencyConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return PaperReviewMutationResponse(
            inserted_event=inserted, event_id=event_id, item=item
        )

    @router.post(
        "/api/publication-automation/{paper_id}/approve-finalization",
        responses=_HTTP_PAPER_REVIEW_MUTATION_RESPONSES,
    )
    @router.post(
        "/api/paper-reviews/{paper_id}/approve-finalization",
        responses=_HTTP_PAPER_REVIEW_MUTATION_RESPONSES,
    )
    def dashboard_paper_review_approve_finalization(
        paper_id: str,
        payload: PaperReviewApproveFinalizationRequest,
        authorization: Annotated[str | None, Header()] = None,
    ) -> PaperReviewMutationResponse:
        authorize(authorization)
        _require_writable_store("publication automation finalization approval")
        try:
            event_id, inserted, item = store.approve_paper_review_finalization(
                paper_id, payload
            )
        except IdempotencyConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return PaperReviewMutationResponse(
            inserted_event=inserted, event_id=event_id, item=item
        )

    @router.post(
        "/api/publication-automation/rewrite-batch",
        responses=_PAPER_REWRITE_DRAFT_RESPONSES,
    )
    @router.post(
        "/api/paper-reviews/rewrite-batch",
        responses=_PAPER_REWRITE_DRAFT_RESPONSES,
    )
    def dashboard_paper_reviews_rewrite_batch(
        payload: PaperReviewBulkRewriteRequest,
        authorization: Annotated[str | None, Header()] = None,
    ) -> PaperReviewBulkRewriteResponse:
        authorize(authorization)
        if not payload.dry_run:
            _require_writable_store("publication automation rewrite batch")
        rows = store.paper_review_rows(include_rank_reasons=True)
        if payload.review_status:
            rows = [
                row
                for row in rows
                if _normal_status(row.get("review_status"))
                == _normal_status(payload.review_status)
            ]
        else:
            rows = [
                row
                for row in rows
                if _normal_status(row.get("review_status"))
                not in {
                    "blocked",
                    "changes_requested",
                    "finalized",
                    "in_review",
                    "rejected",
                    "unreviewed",
                }
            ]
        if payload.paper_status:
            rows = [
                row
                for row in rows
                if _normal_status(row.get("paper_status"))
                == _normal_status(payload.paper_status)
            ]
        if payload.skip_rewritten:
            rows = [
                row
                for row in rows
                if not store.event_rows(
                    limit=1,
                    entity_id=str(row.get("paper_id") or ""),
                    event_type=PAPER_REVIEW_DRAFT_REWRITTEN,
                )
            ]
        rows = _sort_rows(_search_rows(rows, payload.search), "-rank_score")
        matched = len(rows)
        selected = rows[: payload.limit]
        out_rows: list[dict[str, Any]] = []
        if payload.dry_run:
            for row in selected:
                out_rows.append(
                    {
                        "paper_id": row.get("paper_id"),
                        "project_name": row.get("project_name"),
                        "action": "would_rewrite",
                    }
                )
            return PaperReviewBulkRewriteResponse(
                dry_run=True,
                matched=matched,
                processed=len(selected),
                rewritten=0,
                failed=0,
                rows=out_rows,
            )
        rewritten = 0
        failed = 0
        for index, row in enumerate(selected, start=1):
            pid = str(row.get("paper_id") or "")
            try:
                result = _rewrite_paper_review_draft(
                    pid,
                    PaperReviewRewriteDraftRequest(
                        idempotency_key=f"{payload.idempotency_key}:{index}:{pid}",
                        requested_by=payload.requested_by,
                        force=payload.force,
                    ),
                )
                rewritten += 1
                out_rows.append(
                    {
                        "paper_id": pid,
                        "project_name": row.get("project_name"),
                        "ok": True,
                        "provider": result.writer.get("provider"),
                        "model": result.writer.get("model"),
                        "evidence_sync": result.writer.get("evidence_sync"),
                        "artifact_root": result.artifact_root,
                    }
                )
            except HTTPException as exc:
                failed += 1
                out_rows.append(
                    {
                        "paper_id": pid,
                        "project_name": row.get("project_name"),
                        "ok": False,
                        "error": exc.detail,
                    }
                )
            except (
                PublicationAutomationNotFoundError,
                PaperRewriteEvidenceRequiredError,
                PaperArtifactRootNotInspectableError,
                ValueError,
            ) as exc:
                failed += 1
                out_rows.append(
                    {
                        "paper_id": pid,
                        "project_name": row.get("project_name"),
                        "ok": False,
                        "error": str(exc),
                    }
                )
            except (
                Exception
            ) as exc:  # pragma: no cover - defensive for live batch operations
                failed += 1
                out_rows.append(
                    {
                        "paper_id": pid,
                        "project_name": row.get("project_name"),
                        "ok": False,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
        return PaperReviewBulkRewriteResponse(
            dry_run=False,
            matched=matched,
            processed=len(selected),
            rewritten=rewritten,
            failed=failed,
            rows=out_rows,
        )

    @router.post(
        "/api/publication-automation/{paper_id}/rewrite-draft",
        responses=_PAPER_REWRITE_DRAFT_RESPONSES,
    )
    @router.post(
        "/api/paper-reviews/{paper_id}/rewrite-draft",
        responses=_PAPER_REWRITE_DRAFT_RESPONSES,
    )
    def dashboard_paper_review_rewrite_draft(
        paper_id: str,
        payload: PaperReviewRewriteDraftRequest,
        authorization: Annotated[str | None, Header()] = None,
    ) -> PaperReviewRewriteDraftResponse:
        authorize(authorization)
        _require_writable_store("publication automation draft rewrite")
        try:
            return _rewrite_paper_review_draft(paper_id, payload)
        except PublicationAutomationNotFoundError as exc:
            raise HTTPException(
                status_code=404, detail=PUBLICATION_AUTOMATION_ITEM_NOT_FOUND
            ) from exc
        except PaperRewriteBlockedReviewStatusError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except (
            UnresolvableConfiguredProjectRootError,
            PaperArtifactRootError,
            PaperArtifactRootNotInspectableError,
            PaperArtifactSnapshotReadError,
        ) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except PaperRewriteIdempotencyReuseError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except PaperRewriteEvidenceRequiredError as exc:
            raise HTTPException(
                status_code=424,
                detail={
                    "message": "paper rewrite requires synced project evidence",
                    "evidence_sync": exc.evidence_sync,
                },
            ) from exc
        except IdempotencyConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post(
        "/api/publication-automation/{paper_id}/prepare-finalization-package",
        responses=_HTTP_500_UNRESOLVABLE_ARTIFACT_ROOT,
    )
    @router.post(
        "/api/paper-reviews/{paper_id}/prepare-finalization-package",
        responses=_HTTP_500_UNRESOLVABLE_ARTIFACT_ROOT,
    )
    def dashboard_paper_review_prepare_finalization_package(
        paper_id: str,
        payload: PaperReviewPrepareFinalizationRequest,
        authorization: Annotated[str | None, Header()] = None,
    ) -> PaperReviewFinalizationPackageResponse:
        authorize(authorization)
        _require_writable_store("publication automation finalization package")
        _require_safe_paper_artifact_root(paper_id)
        try:
            event_id, inserted, item, package_path, manifest = (
                store.prepare_paper_review_finalization_package(
                    paper_id, payload, require_approval=False
                )
            )
        except IdempotencyConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return PaperReviewFinalizationPackageResponse(
            dry_run=payload.dry_run,
            inserted_event=inserted,
            event_id=event_id,
            item=item,
            package_path=package_path,
            manifest=manifest,
        )

    @router.get("/api/papers")
    def dashboard_papers(
        authorization: Annotated[str | None, Header()] = None,
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=500)] = 50,
        search: str = "",
        status: str = "",
        sort: str = "-updated_at",
    ) -> DashboardPapersResponse:
        authorize(authorization)
        rows = store.paper_rows()
        all_counts = _paper_counts(rows)
        if status:
            rows = [
                row
                for row in rows
                if _normal_status(row.get("paper_status")) == _normal_status(status)
            ]
        rows = _sort_rows(_search_rows(rows, search), sort)
        page_rows, safe_page, safe_size = _paginate(
            rows, page=page, page_size=page_size
        )
        for row in page_rows:
            row["links"] = {
                "paper": f"/control/api/papers/{row.get('paper_id') or ''}",
                "project": f"/control/api/projects/{row.get('project_id') or ''}",
                "run": f"/control/api/runs/{row.get('run_id') or ''}"
                if row.get("run_id")
                else "",
            }
        return DashboardPapersResponse(
            page=DashboardPageMeta(
                page=safe_page,
                page_size=safe_size,
                total=len(rows),
                returned=len(page_rows),
                queue="papers",
                filters={"search": search, "status": status},
                sort=sort,
            ),
            counts=all_counts,
            rows=page_rows,
            source_freshness=_db_freshness("canonical paper queue read model"),
            conflicts=[],
        )

    @router.get(
        "/api/papers/{paper_id}/artifact/{field}",
        responses=_HTTP_500_UNRESOLVABLE_ARTIFACT_ROOT,
    )
    def dashboard_paper_artifact(
        paper_id: str, field: str, authorization: Annotated[str | None, Header()] = None
    ) -> dict[str, Any]:
        authorize(authorization)
        paper = store.paper_row(paper_id)
        if paper is None:
            raise HTTPException(status_code=404, detail=_HTTP_404_PAPER_DETAIL)
        path = _resolve_paper_artifact(paper, field)
        max_bytes = 1_000_000
        try:
            data = path.read_bytes()
            size_bytes = path.stat().st_size
        except (OSError, RuntimeError, ValueError) as exc:
            raise HTTPException(
                status_code=404, detail=f"paper artifact is not readable: {field}"
            ) from exc
        truncated = len(data) > max_bytes
        if truncated:
            data = data[:max_bytes]
        return {
            "ok": True,
            "paper_id": paper_id,
            "project_id": str(paper.get("project_id") or ""),
            "project_name": str(paper.get("project_name") or ""),
            "field": field,
            "path": str(paper.get(field) or ""),
            "absolute_path": str(path),
            "size_bytes": size_bytes,
            "truncated": truncated,
            "content": data.decode("utf-8", errors="replace"),
        }

    @router.get("/api/papers/{paper_id}", responses=_HTTP_404_PAPER)
    def dashboard_paper(
        paper_id: str, authorization: Annotated[str | None, Header()] = None
    ) -> DashboardPaperDetailResponse:
        authorize(authorization)
        paper = store.paper_row(paper_id)
        if paper is None:
            raise HTTPException(status_code=404, detail=_HTTP_404_PAPER_DETAIL)
        project_id = str(paper.get("project_id") or "")
        run_id = str(paper.get("run_id") or "")
        missing = [
            name
            for name in (
                "draft_markdown_path",
                "draft_latex_path",
                "evidence_bundle_path",
                "claim_ledger_path",
                "manifest_path",
            )
            if not paper.get(name)
        ]
        warnings = (
            [
                DashboardFinding(
                    severity="warn",
                    source="control_plane_db",
                    authority="paper artifact record",
                    message=f"paper is missing artifact path(s): {', '.join(missing)}",
                    suggested_action="generate or reconcile paper artifacts",
                )
            ]
            if missing
            else []
        )
        return DashboardPaperDetailResponse(
            paper_id=paper_id,
            paper=paper,
            project=store.project_row(project_id) if project_id else None,
            run=store.run_row(run_id) if run_id else None,
            events=store.event_rows(limit=100, entity_id=paper_id)
            + (store.event_rows(limit=50, entity_id=project_id) if project_id else []),
            source_freshness=_db_freshness("paper/project/run aggregate"),
            warnings=warnings,
            conflicts=[],
        )

    @router.get("/api/events")
    def dashboard_events(
        authorization: Annotated[str | None, Header()] = None,
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=500)] = 100,
        entity_type: str = "",
        entity_id: str = "",
        event_type: str = "",
        search: str = "",
    ) -> DashboardEventsResponse:
        authorize(authorization)
        rows = store.event_rows(
            limit=1000,
            entity_type=entity_type,
            entity_id=entity_id,
            event_type=event_type,
            search=search,
        )
        page_rows, safe_page, safe_size = _paginate(
            rows, page=page, page_size=page_size
        )
        return DashboardEventsResponse(
            page=DashboardPageMeta(
                page=safe_page,
                page_size=safe_size,
                total=len(rows),
                returned=len(page_rows),
                queue="events",
                filters={
                    "entity_type": entity_type,
                    "entity_id": entity_id,
                    "event_type": event_type,
                    "search": search,
                },
                sort="-event_id",
            ),
            rows=page_rows,
            source_freshness=_db_freshness("append-only control event log"),
            conflicts=[],
        )

    @router.get("/api/intake/ideas")
    def dashboard_ideas_intake(
        authorization: Annotated[str | None, Header()] = None,
        page_size: Annotated[int, Query(ge=1, le=200)] = 50,
        include_latest_payload: Annotated[bool, Query()] = False,
    ) -> DashboardIntakeResponse:
        authorize(authorization)
        return _dashboard_ideas_intake_response(
            page_size=page_size, include_latest_payload=include_latest_payload
        )

    @router.get("/api/research/facility")
    def dashboard_research_facility(
        authorization: Annotated[str | None, Header()] = None,
        page_size: Annotated[int, Query(ge=1, le=200)] = 50,
    ) -> dict[str, Any]:
        authorize(authorization)
        rows = (
            store.research_facility_workbench_projection(limit=page_size)
            if hasattr(store, "research_facility_workbench_projection")
            else []
        )
        counts = (
            store.research_facility_workbench_counts()
            if hasattr(store, "research_facility_workbench_counts")
            else {}
        )
        if not counts:
            for row in rows:
                status = str(row.get("status") or "unknown")
                counts[status] = counts.get(status, 0) + 1
        return {
            "ok": True,
            "authority": "Research Facility ledgers: sources, candidates, admissions, lineage",
            "operator_summary": read_models.summarize_research_facility_workbench(
                counts=counts, returned_rows=len(rows)
            ),
            "rows": rows,
            "counts": counts,
            "page": {
                "page_size": page_size,
                "returned": len(rows),
                "counts_scope": "all_rows"
                if hasattr(store, "research_facility_workbench_counts")
                else "returned_rows",
            },
        }

    @router.post("/api/research/generate-batch", responses=_HTTP_501_SUPABASE_LEDGER)
    def dashboard_research_generate_batch(
        payload: Annotated[dict[str, Any] | None, Body()] = None,
        authorization: Annotated[str | None, Header()] = None,
    ) -> dict[str, Any]:
        authorize(authorization)
        from argparse import Namespace
        from scripts import research_facility, research_facility_scan

        body = payload or {}
        dry_run = bool(body.get("dry_run", True))
        max_candidates = _bounded_int_from_mapping(body, "max_candidates", 3, 1, 10)
        requested_by = str(body.get("requested_by") or "dashboard")[:80]
        if not dry_run:
            _require_writable_store("Research Facility candidate generation")
        source_specs = [
            {
                "title": "Provider-budget-aware idea generation scheduler",
                "summary": "Test whether local idea generation should check provider quota, rolling budget, and queue state before spending inference requests on new research candidates.",
                "url": "enoch://research-facility/smoke/provider-budget-scheduler",
            },
            {
                "title": "Counterexample-first candidate admission gate",
                "summary": "Test whether candidate ideas should carry explicit falsification probes before admission, reducing shallow incremental work and preventing positive-only framing.",
                "url": "enoch://research-facility/smoke/counterexample-admission-gate",
            },
            {
                "title": "Queue-safe candidate promotion ledger",
                "summary": "Test whether generated candidates can be promoted to queued projects only through an auditable ledger that preserves dry-run evidence and prevents accidental dispatch.",
                "url": "enoch://research-facility/smoke/queue-safe-promotion-ledger",
            },
        ][:max_candidates]
        records = [
            research_facility_scan.SourceRecord.from_parts(
                source_kind="internal_generated",
                title=spec["title"],
                url=spec["url"],
                summary=spec["summary"],
                payload_json={"smoke_test": True, "requested_by": requested_by},
            )
            for spec in source_specs
        ]
        candidates = [
            research_facility_scan.candidate_from_source(
                record,
                default_machine=os.environ.get(
                    "ENOCH_RESEARCH_DEFAULT_MACHINE", "research-facility-node"
                ),  # NOSONAR
                default_model=os.environ.get(
                    "ENOCH_RESEARCH_DEFAULT_MODEL", _DEFAULT_RESEARCH_MODEL
                ),
                default_sandbox=os.environ.get(
                    "ENOCH_RESEARCH_DEFAULT_SANDBOX", "danger-full-access"
                ),
            )
            for record in records
        ]
        plans = research_facility.plan_candidates(
            candidates,
            Namespace(
                default_machine=os.environ.get(
                    "ENOCH_RESEARCH_DEFAULT_MACHINE", "research-facility-node"
                ),  # NOSONAR
                default_model=os.environ.get(
                    "ENOCH_RESEARCH_DEFAULT_MODEL", _DEFAULT_RESEARCH_MODEL
                ),
                default_sandbox=os.environ.get(
                    "ENOCH_RESEARCH_DEFAULT_SANDBOX", "danger-full-access"
                ),
                admit_threshold=_bounded_float_from_mapping(
                    body, "admit_threshold", 72.0, 0.0, 100.0
                ),
                review_threshold=_bounded_float_from_mapping(
                    body, "review_threshold", 58.0, 0.0, 100.0
                ),
                history=[],
            ),
        )
        plan_json = [plan.to_json() for plan in plans]
        response = {
            "ok": True,
            "action": "dry_run_generate_candidates"
            if dry_run
            else "generate_candidates",
            "dry_run": dry_run,
            "queue_admitted": False,
            "candidate_count": len(plans),
            "admitted_count": sum(
                1 for plan in plans if plan.admission_decision == "admitted"
            ),
            "needs_review_count": sum(
                1 for plan in plans if plan.admission_decision == "needs_review"
            ),
            "rejected_count": sum(
                1 for plan in plans if plan.admission_decision == "rejected"
            ),
            "queued_count": 0,
            "plans": plan_json,
        }
        if dry_run:
            return response
        if not hasattr(store, "record_research_facility_plans"):
            raise HTTPException(
                status_code=501,
                detail=RESEARCH_FACILITY_LEDGER_REQUIRES_SUPABASE_STORE,
            )
        response["ledger_result"] = store.record_research_facility_plans(
            plans, requested_by=requested_by, queue_admitted=False
        )
        return response

    @router.post(
        "/api/research/generate-provider-batch", responses=_HTTP_501_SUPABASE_LEDGER
    )
    def dashboard_research_generate_provider_batch(
        payload: Annotated[dict[str, Any] | None, Body()] = None,
        authorization: Annotated[str | None, Header()] = None,
    ) -> dict[str, Any]:
        authorize(authorization)
        from argparse import Namespace
        from scripts import (
            research_facility,
            research_provider_budget,
            research_provider_generate,
        )

        body = payload or {}
        dry_run = bool(body.get("dry_run", True))
        max_candidates = _bounded_int_from_mapping(body, "max_candidates", 2, 1, 5)
        requested_by = str(body.get("requested_by") or "dashboard")[:80]
        if not dry_run:
            _require_writable_store("Research Facility provider generation")
        provider_base_url = os.environ.get(
            "ENOCH_RESEARCH_PROVIDER_BASE_URL", DEFAULT_RESEARCH_PROVIDER_BASE_URL
        ).rstrip("/")
        provider_openai_base_url = os.environ.get(
            "ENOCH_RESEARCH_PROVIDER_OPENAI_BASE_URL", f"{provider_base_url}/openai/v1"
        ).rstrip("/")
        provider_model = str(
            body.get("model")
            or os.environ.get("ENOCH_RESEARCH_PROVIDER_MODEL")
            or DEFAULT_ALLOWED_RESEARCH_MODELS[-1]
        ).strip()
        topic = str(body.get("topic") or "").strip()
        temperature = _bounded_float_from_mapping(body, "temperature", 0.8, 0.0, 1.5)
        seed = str(body.get("seed") or utc_now()).strip()
        reserve_requests = _bounded_int_from_mapping(
            body, "reserve_requests", 2, 1, 100
        )
        budget_timeout = _bounded_int_from_mapping(body, "budget_timeout", 20, 1, 60)
        generation_timeout = _bounded_int_from_mapping(
            body, "generation_timeout", 180, 10, 300
        )
        generation_max_tokens = _bounded_int_from_mapping(
            body,
            "generation_max_tokens",
            _bounded_int_env("ENOCH_RESEARCH_PROVIDER_MAX_TOKENS", 8000, 1000, 16000),
            1000,
            16000,
        )
        generation_attempts = _bounded_int_from_mapping(
            body,
            "generation_attempts",
            _bounded_int_env("ENOCH_RESEARCH_PROVIDER_ATTEMPTS", 2, 1, 3),
            1,
            3,
        )
        estimated_requests = generation_attempts
        try:
            quota_payload = research_provider_budget.fetch_json(
                f"{provider_base_url}/v2/quotas", api_key="", timeout=budget_timeout
            )
            budget = research_provider_budget.synthetic_budget_status(
                quota_payload,
                min_remaining_credits=_bounded_float_from_mapping(
                    body, "min_remaining_credits", 5.0, 0.0, 1_000_000.0
                ),
                min_rolling_remaining=_bounded_int_from_mapping(
                    body, "min_rolling_remaining", 10, 0, 100_000
                ),
                estimated_requests=estimated_requests,
                reserve_requests=reserve_requests,
            )
        except Exception as exc:  # noqa: BLE001 - generation must fail closed if budget cannot be checked
            budget = {
                "ok": False,
                "provider": "synthetic",
                "checked_at": utc_now(),
                "estimated_requests": estimated_requests,
                "reserve_requests": reserve_requests,
                "failures": [f"provider budget check failed: {exc}"],
            }
        safe_budget_keys = {
            "ok",
            "provider",
            "checked_at",
            "estimated_requests",
            "reserve_requests",
            "remaining_credits",
            "min_remaining_credits",
            "rolling_remaining",
            "rolling_max",
            "rolling_limited",
            "rolling_next_tick_at",
            "weekly_next_regen_at",
            "weekly_next_regen_credits",
            "subscription_remaining",
            "subscription_renews_at",
            "budget_endpoint_host",
            "budget_endpoint_path",
            "failures",
        }
        safe_budget = {
            key: budget.get(key) for key in safe_budget_keys if key in budget
        }
        response: dict[str, Any] = {
            "ok": bool(budget.get("ok")),
            "action": "dry_run_provider_generate_candidates"
            if dry_run
            else "provider_generate_candidates",
            "dry_run": dry_run,
            "queue_admitted": False,
            "dispatch_started": False,
            "provider": "synthetic.new",
            "provider_model": provider_model,
            "max_candidates": max_candidates,
            "topic": topic,
            "temperature": temperature,
            "generation_max_tokens": generation_max_tokens,
            "generation_attempts": generation_attempts,
            "seed": seed,
            "budget": safe_budget,
            "queued_count": 0,
        }
        if not budget.get("ok"):
            response["action"] = "provider_generation_blocked"
            response["reason"] = "; ".join(
                str(item)
                for item in budget.get("failures") or ["provider budget unavailable"]
            )
            return response
        if dry_run:
            response["reason"] = (
                "provider budget passed; no provider request spent and no ledger rows written"
            )
            return response
        if not hasattr(store, "record_research_facility_plans"):
            raise HTTPException(
                status_code=501,
                detail=RESEARCH_FACILITY_LEDGER_REQUIRES_SUPABASE_STORE,
            )
        try:
            generated = research_provider_generate.generate_provider_candidates(
                base_url=provider_openai_base_url,
                model=provider_model,
                api_key="",
                max_candidates=max_candidates,
                topic=topic,
                temperature=temperature,
                seed=seed,
                timeout=generation_timeout,
                max_tokens=generation_max_tokens,
                attempts=generation_attempts,
                default_machine=os.environ.get(
                    "ENOCH_RESEARCH_DEFAULT_MACHINE", "research-facility-node"
                ),  # NOSONAR
                default_model=os.environ.get(
                    "ENOCH_RESEARCH_DEFAULT_MODEL", _DEFAULT_RESEARCH_MODEL
                ),
                default_sandbox=os.environ.get(
                    "ENOCH_RESEARCH_DEFAULT_SANDBOX", "danger-full-access"
                ),
            )
        except Exception as exc:  # noqa: BLE001 - provider generation must fail closed without ledger writes
            response.update(
                {
                    "ok": False,
                    "action": "provider_generation_failed",
                    "reason": f"provider generation failed before ledger write: {exc}",
                    "candidate_count": 0,
                    "admitted_count": 0,
                    "needs_review_count": 0,
                    "rejected_count": 0,
                }
            )
            return response
        generated_candidates = (generated.get("candidates") or [])[:max_candidates]
        if not generated_candidates:
            response.update(
                {
                    "ok": False,
                    "action": "provider_generation_failed",
                    "reason": "provider generation returned 0 usable candidates; no ledger rows written",
                    "candidate_count": 0,
                    "admitted_count": 0,
                    "needs_review_count": 0,
                    "rejected_count": 0,
                    "provider_response_id": generated.get("provider_response_id", ""),
                }
            )
            return response
        plans = research_facility.plan_candidates(
            generated_candidates,
            Namespace(
                default_machine=os.environ.get(
                    "ENOCH_RESEARCH_DEFAULT_MACHINE", "research-facility-node"
                ),  # NOSONAR
                default_model=os.environ.get(
                    "ENOCH_RESEARCH_DEFAULT_MODEL", _DEFAULT_RESEARCH_MODEL
                ),
                default_sandbox=os.environ.get(
                    "ENOCH_RESEARCH_DEFAULT_SANDBOX", "danger-full-access"
                ),
                admit_threshold=_bounded_float_from_mapping(
                    body, "admit_threshold", 72.0, 0.0, 100.0
                ),
                review_threshold=_bounded_float_from_mapping(
                    body, "review_threshold", 58.0, 0.0, 100.0
                ),
                history=[],
            ),
        )
        response["candidate_count"] = len(plans)
        response["admitted_count"] = sum(
            1 for plan in plans if plan.admission_decision == "admitted"
        )
        response["needs_review_count"] = sum(
            1 for plan in plans if plan.admission_decision == "needs_review"
        )
        response["rejected_count"] = sum(
            1 for plan in plans if plan.admission_decision == "rejected"
        )
        response["provider_response_id"] = generated.get("provider_response_id", "")
        response["attempts_used"] = generated.get("attempts_used", 1)
        response["plans"] = [plan.to_json() for plan in plans]
        response["ledger_result"] = store.record_research_facility_plans(
            plans, requested_by=requested_by, queue_admitted=False
        )
        return response

    _export_namespace(
        ns,
        (
            "dashboard_events",
            "dashboard_ideas_intake",
            "dashboard_next_paper_review",
            "dashboard_next_publication_automation",
            "dashboard_paper",
            "dashboard_paper_artifact",
            "dashboard_paper_review",
            "dashboard_paper_review_approve_finalization",
            "dashboard_paper_review_checklist",
            "dashboard_paper_review_claim",
            "dashboard_paper_review_prepare_finalization_package",
            "dashboard_paper_review_rewrite_draft",
            "dashboard_paper_review_status",
            "dashboard_paper_reviews",
            "dashboard_paper_reviews_backfill",
            "dashboard_paper_reviews_rewrite_batch",
            "dashboard_papers",
            "dashboard_publication_automation",
            "dashboard_publication_automation_item",
            "dashboard_research_facility",
            "dashboard_research_generate_batch",
            "dashboard_research_generate_provider_batch",
        ),
    )


def _register_control_plane_papers_events_routes(ns: MutableMapping[str, Any]) -> None:
    global \
        dashboard_notion_intake, \
        dashboard_research_promote_candidate, \
        dashboard_research_provider_budget, \
        dashboard_research_run_cycle
    _sync_namespace(ns)

    @router.post(
        "/api/research/run-cycle",
        responses=_HTTP_400_RESEARCH_CANDIDATE_ID,
    )
    async def dashboard_research_run_cycle(
        payload: Annotated[dict[str, Any] | None, Body()] = None,
        authorization: Annotated[str | None, Header()] = None,
    ) -> dict[str, Any]:
        """Run one bounded Research Facility cycle.

        This is intentionally a small automation step:
        provider quota check -> optional generation/admission ledgers -> explicit
        promotion of admitted candidates -> optional single dispatch -> optional
        positive-gated paper draft/finalization. It never unpauses the broad
        queue and every mutating stage is bounded by per-run limits.
        """

        authorize(authorization)
        from argparse import Namespace
        from scripts import (
            research_facility,
            research_provider_budget,
            research_provider_generate,
        )

        body = payload or {}
        dry_run = bool(body.get("dry_run", True))
        enabled = bool(body.get("enabled", False))
        requested_by = str(body.get("requested_by") or "dashboard")[:80]
        operator_trace = OperatorTrace.from_config(config)
        trace_id = OperatorTrace.new_trace_id("research-cycle")
        run_cycle_id = OperatorTrace.new_trace_id("run-cycle")
        if not dry_run:
            _require_writable_store("Research Facility run-cycle")
        if (
            not hasattr(store, "research_facility_workbench_projection")
            or not hasattr(store, "record_research_facility_plans")
            or not hasattr(store, "promote_research_candidate")
        ):
            raise HTTPException(
                status_code=501,
                detail="Research Facility run-cycle requires the Supabase control-plane store",
            )

        model_resolution = _resolve_research_provider_model(body)
        if isinstance(model_resolution, dict):
            return model_resolution
        provider_model, allowed_models = model_resolution

        bounded_int = partial(_bounded_int_from_mapping, body)
        bounded_float = partial(_bounded_float_from_mapping, body)

        # The 3 inputs below feed (or parallel) the extracted resolver...
        worker_lane_limit = max(1, min(4, len(_configured_worker_lanes()) or 1))
        promotion_batch_limit = _bounded_int_env(
            "ENOCH_RESEARCH_MAX_PROMOTIONS_PER_RUN_CAP", 25, 1, 100
        )

        params = _resolve_research_cycle_params(
            body,
            worker_lane_limit=worker_lane_limit,
            promotion_batch_limit=promotion_batch_limit,
        )

        max_provider_requests = params.max_provider_requests
        max_promotions = params.max_promotions
        max_dispatches = params.max_dispatches
        min_queue_depth_per_lane = params.min_queue_depth_per_lane
        max_paper_drafts = params.max_paper_drafts
        max_publication_rewrites = params.max_publication_rewrites
        wait_for_completion = params.wait_for_completion
        max_wait_seconds = params.max_wait_seconds
        poll_interval_seconds = params.poll_interval_seconds
        min_admission_score = params.min_admission_score
        max_candidates = params.max_candidates
        fresh_generation_backlog_threshold = params.fresh_generation_backlog_threshold
        topic = params.topic
        temperature = params.temperature
        seed = params.seed
        provider_base_url = params.provider_base_url
        provider_openai_base_url = params.provider_openai_base_url
        provider_api_key = params.provider_api_key
        provider_id = params.provider_id
        generation_timeout = params.generation_timeout
        generation_max_tokens = params.generation_max_tokens
        generation_attempts = params.generation_attempts

        active = store.active_items()
        counts = store.status_counts()
        blocked_count = int(counts.get("blocked") or 0)
        backpressure_reasons: list[str] = []
        estimated_requests = max_provider_requests * generation_attempts
        budget = _fetch_synthetic_research_budget(
            provider_id=provider_id,
            provider_base_url=provider_base_url,
            provider_api_key=provider_api_key,
            estimated_requests=estimated_requests,
            bounded_int=bounded_int,
            bounded_float=bounded_float,
            research_provider_budget=research_provider_budget,
        )
        stop_reasons = _collect_research_cycle_stop_reasons(
            body=body,
            dry_run=dry_run,
            enabled=enabled,
            blocked_count=blocked_count,
            budget=budget,
            max_provider_requests=max_provider_requests,
            backpressure_reasons=backpressure_reasons,
        )

        research_row_lane_key = partial(_research_row_lane_key, _worker_lane_key)
        promotable_rows = partial(
            _compute_promotable_rows,
            store=store,
            min_admission_score=min_admission_score,
            active=active,
            research_row_lane_key=research_row_lane_key,
            research_facility=research_facility,
        )

        janitor_enabled = bool(body.get("janitor_enabled", True))
        janitor_limit = bounded_int("janitor_limit", 250, 0, 500)
        janitor_report = _compute_janitor_report(
            store=store,
            janitor_enabled=janitor_enabled,
            janitor_limit=janitor_limit,
            max_promotions=max_promotions,
            dry_run=dry_run,
            stop_reasons=stop_reasons,
            backpressure_reasons=backpressure_reasons,
            requested_by=requested_by,
        )

        initial_promotable = promotable_rows()
        active_lane_keys = {_worker_lane_key(row) for row in active}
        initial_open_lane_promotable = open_lane_research_rows(
            initial_promotable,
            active_lane_keys,
            lane_key_func=research_row_lane_key,
        )
        initial_feed_lanes = _worker_lane_capacity(
            active=active, rows=_queue_rows_for_lane_feed()
        )
        lane_feed_pressure = _research_lane_feed_pressure(
            active=active,
            queued=_queue_rows_for_lane_feed(),
            lanes=initial_feed_lanes,
            promotable=initial_promotable,
            min_queue_depth=min_queue_depth_per_lane,
            min_admission_score=min_admission_score,
        )
        generation_target_lane = _select_generation_target_lane(lane_feed_pressure)
        operator_trace.record(
            "research.run_cycle.start",
            trace_id=trace_id,
            run_cycle_id=run_cycle_id,
            requested_by=requested_by,
            dry_run=dry_run,
            enabled=enabled,
            active_count=len(active),
            queued_count=int(counts.get("queued") or 0),
            blocked_count=blocked_count,
            max_provider_requests=max_provider_requests,
            max_promotions=max_promotions,
            max_dispatches=max_dispatches,
        )
        operator_trace.record(
            "research.lanes.before",
            trace_id=trace_id,
            run_cycle_id=run_cycle_id,
            requested_by=requested_by,
            lanes=summarize_lane_snapshot(initial_feed_lanes),
        )
        operator_trace.record(
            "research.generation_target.selected",
            trace_id=trace_id,
            run_cycle_id=run_cycle_id,
            requested_by=requested_by,
            machine_target=(generation_target_lane or {}).get("machine_target")
            if generation_target_lane
            else "",
            lane_key=(generation_target_lane or {}).get("lane_key")
            if generation_target_lane
            else "",
            target=generation_target_lane,
        )
        idle_queued_lane_available = _research_cycle_idle_queued_lane_available(
            lanes=initial_feed_lanes, max_dispatches=max_dispatches
        )
        backpressure_reasons.extend(
            _evaluate_research_cycle_backpressure(
                active=active,
                initial_open_lane_promotable=initial_open_lane_promotable,
                generation_target_lane=generation_target_lane,
                max_provider_requests=max_provider_requests,
                idle_queued_lane_available=idle_queued_lane_available,
            )
        )
        response = _build_research_cycle_initial_response(
            params=_ResearchCycleInitialResponseParams(
                dry_run=dry_run,
                enabled=enabled,
                provider_model=provider_model,
                allowed_models=allowed_models,
                body=body,
                max_provider_requests=max_provider_requests,
                max_promotions=max_promotions,
                max_dispatches=max_dispatches,
                min_queue_depth_per_lane=min_queue_depth_per_lane,
                max_paper_drafts=max_paper_drafts,
                max_publication_rewrites=max_publication_rewrites,
                min_admission_score=min_admission_score,
                wait_for_completion=wait_for_completion,
                max_wait_seconds=max_wait_seconds,
                fresh_generation_backlog_threshold=fresh_generation_backlog_threshold,
                janitor_enabled=janitor_enabled,
                janitor_limit=janitor_limit,
                janitor_report=janitor_report,
                budget=budget,
                initial_promotable=initial_promotable,
                initial_open_lane_promotable=initial_open_lane_promotable,
                lane_feed_pressure=lane_feed_pressure,
                generation_target_lane=generation_target_lane,
                stop_reasons=stop_reasons,
            ),
        )
        _append_research_cycle_queue_paused_guardrail(
            store=store,
            response=response,
            dry_run=dry_run,
            requested_by=requested_by,
        )
        early_response = _research_cycle_pre_live_exit(
            store=store,
            response=response,
            dry_run=dry_run,
            requested_by=requested_by,
            stop_reasons=stop_reasons,
            backpressure_reasons=backpressure_reasons,
            active=active,
            wait_for_completion=wait_for_completion,
            max_wait_seconds=max_wait_seconds,
            cycle_limits={
                "max_provider_requests": max_provider_requests,
                "max_promotions": max_promotions,
                "max_dispatches": max_dispatches,
                "max_paper_drafts": max_paper_drafts,
                "max_publication_rewrites": max_publication_rewrites,
            },
        )
        if early_response is not None:
            early_response["trace_id"] = trace_id
            early_response["run_cycle_id"] = run_cycle_id
            operator_trace.record(
                "research.run_cycle.end",
                trace_id=trace_id,
                run_cycle_id=run_cycle_id,
                requested_by=requested_by,
                reason=early_response.get("reason"),
                action=early_response.get("action"),
                backpressure=early_response.get("backpressure"),
            )
            return early_response

        open_lane_research_rows_local = partial(
            open_lane_research_rows, lane_key_func=research_row_lane_key
        )

        cycle_params = _LiveResearchCycleParams(
            store=store,
            requested_by=requested_by,
            generation_target_lane=generation_target_lane,
            initial_feed_lanes=initial_feed_lanes,
            max_dispatches=max_dispatches,
            max_provider_requests=max_provider_requests,
            fresh_generation_backlog_threshold=fresh_generation_backlog_threshold,
            initial_promotable=initial_promotable,
            promotable_rows=promotable_rows,
            open_lane_research_rows=open_lane_research_rows_local,
            max_promotions=max_promotions,
            provider_openai_base_url=provider_openai_base_url,
            provider_api_key=provider_api_key,
            provider_id=provider_id,
            provider_model=provider_model,
            max_candidates=max_candidates,
            topic=topic,
            temperature=temperature,
            seed=seed,
            generation_timeout=generation_timeout,
            generation_max_tokens=generation_max_tokens,
            generation_attempts=generation_attempts,
            min_admission_score=min_admission_score,
            bounded_float=bounded_float,
            namespace_cls=Namespace,
            research_provider_generate=research_provider_generate,
            research_facility=research_facility,
            wait_for_completion=wait_for_completion,
            max_wait_seconds=max_wait_seconds,
            poll_interval_seconds=poll_interval_seconds,
            max_paper_drafts=max_paper_drafts,
            max_publication_rewrites=max_publication_rewrites,
            draft_next=draft_next,
            rewrite_paper_review_draft=_rewrite_paper_review_draft,
            control_api_bearer_token=config.control_api_bearer_token,
            worker_lane_key=_worker_lane_key,
            worker_lane_capacity=_worker_lane_capacity,
            queue_rows_for_lane_feed=_queue_rows_for_lane_feed,
            live_dispatch=_live_dispatch,
            jsonable_encoder=jsonable_encoder,
            research_row_lane_key=research_row_lane_key,
            operator_trace=operator_trace,
            trace_id=trace_id,
            run_cycle_id=run_cycle_id,
        )
        cycle_response = {**response, "trace_id": trace_id, "run_cycle_id": run_cycle_id}
        return await asyncio.to_thread(
            lambda: asyncio.run(
                _execute_live_research_cycle(
                    params=cycle_params,
                    response=cycle_response,
                )
            )
        )

    @router.post(
        "/api/research/promote-candidate",
        responses=_HTTP_400_RESEARCH_CANDIDATE_ID,
    )
    def dashboard_research_promote_candidate(
        payload: Annotated[dict[str, Any] | None, Body()] = None,
        authorization: Annotated[str | None, Header()] = None,
    ) -> dict[str, Any]:
        authorize(authorization)
        body = payload or {}
        candidate_id = _validate_research_candidate_id(
            str(body.get("candidate_id") or "")
        )
        dry_run = bool(body.get("dry_run", True))
        requested_by = str(body.get("requested_by") or "dashboard")[:80]
        if not dry_run:
            _require_writable_store("Research Facility candidate promotion")
        if not hasattr(store, "promote_research_candidate"):
            raise HTTPException(
                status_code=501,
                detail="Research Facility promotion requires the Supabase control-plane store",
            )
        return store.promote_research_candidate(
            candidate_id, requested_by=requested_by, dry_run=dry_run
        )

    @router.get("/api/research/provider-budget")
    def dashboard_research_provider_budget(
        authorization: Annotated[str | None, Header()] = None,
        estimated_requests: Annotated[int, Query(ge=0, le=100)] = 2,
        reserve_requests: Annotated[int, Query(ge=0, le=100)] = 2,
        min_remaining_credits: Annotated[float, Query(ge=0.0)] = 5.0,
        min_rolling_remaining: Annotated[int, Query(ge=0)] = 10,
        timeout: Annotated[int, Query(ge=1, le=60)] = 20,
    ) -> dict[str, Any]:
        authorize(authorization)
        from scripts import research_provider_budget

        base_url, provider_api_key = _resolve_synthetic_budget_provider(
            _ROUTER_GATE_CONFIG
        )
        budget_endpoint = ""
        try:
            budget_base_url = _synthetic_budget_base_url(base_url)
            budget_endpoint = f"{budget_base_url}/v2/quotas"
            payload = research_provider_budget.fetch_json(
                budget_endpoint,
                api_key=_synthetic_budget_request_api_key(
                    budget_base_url, provider_api_key
                ),
                timeout=timeout,
            )
            result = research_provider_budget.synthetic_budget_status(
                payload,
                min_remaining_credits=min_remaining_credits,
                min_rolling_remaining=min_rolling_remaining,
                estimated_requests=estimated_requests,
                reserve_requests=reserve_requests,
            )
            result.update(_budget_endpoint_diagnostics(budget_endpoint))
        except Exception as exc:  # noqa: BLE001 - provider checks must fail closed but stay operator-readable
            result = {
                "ok": False,
                "provider": "synthetic",
                "checked_at": utc_now(),
                "estimated_requests": estimated_requests,
                "reserve_requests": reserve_requests,
                "failures": [f"provider budget check failed: {exc}"],
                **_budget_endpoint_diagnostics(budget_endpoint),
            }
        safe_keys = {
            "ok",
            "provider",
            "checked_at",
            "estimated_requests",
            "reserve_requests",
            "remaining_credits",
            "min_remaining_credits",
            "rolling_remaining",
            "rolling_max",
            "rolling_limited",
            "rolling_next_tick_at",
            "weekly_next_regen_at",
            "weekly_next_regen_credits",
            "subscription_remaining",
            "subscription_renews_at",
            "budget_endpoint_host",
            "budget_endpoint_path",
            "failures",
        }
        response = {key: result.get(key) for key in safe_keys if key in result}
        response.update(
            {
                "provider_endpoint": "configured",
                "auth_mode": _synthetic_budget_auth_mode(
                    _synthetic_budget_base_url(base_url), provider_api_key
                ),
                "payload_json": None,
            }
        )
        return response

    @router.get("/api/intake/notion", responses=_HTTP_410_LEGACY_NOTION_API)
    def dashboard_notion_intake(
        authorization: Annotated[str | None, Header()] = None,
        page_size: Annotated[int, Query(ge=1, le=200)] = 50,
        include_latest_payload: Annotated[bool, Query()] = False,
    ) -> DashboardIntakeResponse:
        authorize(authorization)
        try:
            _require_legacy_notion_api_enabled()
        except LegacyNotionApiDisabledError as exc:
            raise HTTPException(
                status_code=410,
                detail={
                    "message": str(exc),
                    "replacement": LEGACY_NOTION_API_REPLACEMENT_PATH,
                },
            ) from exc
        return _dashboard_ideas_intake_response(
            legacy_notion_alias=True,
            page_size=page_size,
            include_latest_payload=include_latest_payload,
        )

    _export_namespace(
        ns,
        (
            "dashboard_notion_intake",
            "dashboard_research_promote_candidate",
            "dashboard_research_provider_budget",
            "dashboard_research_run_cycle",
        ),
    )


def _register_control_plane_research_routes(ns: MutableMapping[str, Any]) -> None:
    global \
        import_snapshot, \
        intake_ideas, \
        intake_notion_ideas, \
        mark_queue_item_paused, \
        pause, \
        record_ideas_observation, \
        record_notion_observation, \
        resume
    _sync_namespace(ns)

    @router.post("/pause", responses=_HTTP_501_WRITABLE_STORE)
    def pause(
        payload: PauseRequest, authorization: Annotated[str | None, Header()] = None
    ) -> dict[str, Any]:
        authorize(authorization)
        _require_writable_store("operator pause")
        flags, pause_event_id = store.pause(
            reason=payload.reason,
            paused_by=payload.paused_by,
            maintenance_mode=payload.maintenance_mode,
        )
        systemd = _pause_automation_for_control_pause()
        store.append_event(
            idempotency_key=f"control-pause-systemd:{pause_event_id}",
            event_type="control.pause.systemd_pause",
            entity_type="control",
            entity_id="queue",
            payload={
                "requested_by": payload.paused_by,
                "systemd": systemd,
            },
        )
        response = state_response().model_dump(mode="json")
        response["systemd"] = systemd
        return response

    @router.post("/resume", responses=_HTTP_501_WRITABLE_STORE)
    def resume(
        payload: ResumeRequest, authorization: Annotated[str | None, Header()] = None
    ) -> ControlStateResponse:
        authorize(authorization)
        _require_writable_store("operator resume")
        store.resume(
            resumed_by=payload.resumed_by, maintenance_mode=payload.maintenance_mode
        )
        return state_response()

    @router.post(
        "/queue/mark-paused",
        responses=_HTTP_MARK_QUEUE_ITEM_PAUSED_RESPONSES,
    )
    def mark_queue_item_paused(
        payload: MarkQueueItemPausedRequest,
        authorization: Annotated[str | None, Header()] = None,
    ) -> ControlStateResponse:
        authorize(authorization)
        _require_writable_store("queue item pause")
        if not store.mark_queue_item_paused(
            project_id=payload.project_id,
            reason=payload.reason,
            updated_by=payload.updated_by,
        ):
            raise HTTPException(status_code=404, detail="queue item not found")
        return state_response()

    @router.post(
        "/import/legacy-snapshot", responses=_HTTP_WRITABLE_IDEMPOTENCY_RESPONSES
    )
    def import_snapshot(
        payload: ImportSnapshotRequest,
        authorization: Annotated[str | None, Header()] = None,
    ) -> ImportSnapshotResponse:
        authorize(authorization)
        _require_writable_store("legacy snapshot import")
        try:
            inserted, projects, queue_items, papers = store.import_snapshot(payload)
        except IdempotencyConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        response = ImportSnapshotResponse(
            inserted_event=inserted,
            imported_projects=projects,
            imported_queue_items=queue_items,
            imported_papers=papers,
        )
        store.upsert_dashboard_observation(
            source="snapshot_mirror",
            status="ok",
            ttl_seconds=900,
            payload={
                "source": payload.source,
                "imported_projects": projects,
                "imported_queue_items": queue_items,
                "imported_papers": papers,
                "inserted_event": inserted,
            },
        )
        return response

    @router.post("/intake/notion-ideas", responses=_HTTP_NOTION_INTAKE_RESPONSES)
    def intake_notion_ideas(
        payload: NotionIntakeRequest,
        authorization: Annotated[str | None, Header()] = None,
    ) -> NotionIntakeResponse:
        authorize(authorization)
        try:
            _require_legacy_notion_api_enabled()
        except LegacyNotionApiDisabledError as exc:
            raise HTTPException(
                status_code=410,
                detail={
                    "message": str(exc),
                    "replacement": LEGACY_NOTION_API_REPLACEMENT_PATH,
                },
            ) from exc
        if not payload.dry_run:
            _require_writable_store("Notion ideas intake")
        if payload.default_machine_target == DEFAULT_MACHINE_TARGET:
            configured_worker = urlparse(config.worker_wake_gate_url).hostname or ""
            if configured_worker:
                payload = payload.model_copy(
                    update={"default_machine_target": configured_worker}
                )
        if config.workload_machine_targets and not payload.workload_machine_targets:
            payload = payload.model_copy(
                update={"workload_machine_targets": config.workload_machine_targets}
            )
        try:
            inserted, created, updated, skipped, candidates, skipped_rows = (
                store.ingest_notion_ideas(payload)
            )
        except IdempotencyConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        response = NotionIntakeResponse(
            dry_run=payload.dry_run,
            inserted_event=inserted,
            created=created,
            updated=updated,
            skipped=skipped,
            candidates=candidates,
            skipped_rows=skipped_rows,
        )
        if not payload.dry_run:
            store.upsert_dashboard_observation(
                source="notion_sync",
                status="ok" if skipped == 0 else "warn",
                ttl_seconds=3600,
                payload=response.model_dump(mode="json"),
            )
        return response

    @router.post("/intake/ideas", responses=_HTTP_WRITABLE_IDEMPOTENCY_RESPONSES)
    def intake_ideas(
        payload: IdeaIntakeRequest,
        authorization: Annotated[str | None, Header()] = None,
    ) -> IdeaIntakeResponse:
        authorize(authorization)
        if not payload.dry_run:
            _require_writable_store("ideas intake")
        if payload.default_machine_target == DEFAULT_MACHINE_TARGET:
            configured_worker = urlparse(config.worker_wake_gate_url).hostname or ""
            if configured_worker:
                payload = payload.model_copy(
                    update={"default_machine_target": configured_worker}
                )
        if config.workload_machine_targets and not payload.workload_machine_targets:
            payload = payload.model_copy(
                update={"workload_machine_targets": config.workload_machine_targets}
            )
        try:
            inserted, created, updated, skipped, candidates, skipped_rows = (
                store.ingest_ideas(payload)
            )
        except IdempotencyConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        response = IdeaIntakeResponse(
            dry_run=payload.dry_run,
            inserted_event=inserted,
            created=created,
            updated=updated,
            skipped=skipped,
            candidates=candidates,
            skipped_rows=skipped_rows,
        )
        if not payload.dry_run:
            store.upsert_dashboard_observation(
                source="idea_intake",
                status="ok" if skipped == 0 else "warn",
                ttl_seconds=3600,
                payload=response.model_dump(mode="json"),
            )
        return response

    @router.post(
        "/api/intake/notion-observation", responses=_HTTP_410_LEGACY_NOTION_API
    )
    def record_notion_observation(
        payload: dict[str, Any], authorization: Annotated[str | None, Header()] = None
    ) -> dict[str, Any]:
        authorize(authorization)
        try:
            _require_legacy_notion_api_enabled()
        except LegacyNotionApiDisabledError as exc:
            raise HTTPException(
                status_code=410,
                detail={
                    "message": str(exc),
                    "replacement": LEGACY_NOTION_API_REPLACEMENT_PATH,
                },
            ) from exc
        _require_writable_store("intake observation")
        status = str(payload.get("status") or "ok")
        if status not in {"ok", "warn", "error", "unavailable"}:
            status = "warn"
        observation = store.upsert_dashboard_observation(
            source="notion_sync",
            status=status,
            ttl_seconds=int(payload.get("ttl_seconds") or 3600),
            payload=payload.get("payload")
            if isinstance(payload.get("payload"), dict)
            else payload,
        )
        return {"ok": True, "observation": observation.model_dump(mode="json")}

    @router.post("/api/intake/ideas-observation")
    def record_ideas_observation(
        payload: dict[str, Any], authorization: Annotated[str | None, Header()] = None
    ) -> dict[str, Any]:
        authorize(authorization)
        _require_writable_store("intake observation")
        status = str(payload.get("status") or "ok")
        if status not in {"ok", "warn", "error", "unavailable"}:
            status = "warn"
        observation = store.upsert_dashboard_observation(
            source="idea_intake",
            status=status,
            ttl_seconds=int(payload.get("ttl_seconds") or 3600),
            payload=payload.get("payload")
            if isinstance(payload.get("payload"), dict)
            else payload,
        )
        return {"ok": True, "observation": observation.model_dump(mode="json")}

    _export_namespace(
        ns,
        (
            "import_snapshot",
            "intake_ideas",
            "intake_notion_ideas",
            "mark_queue_item_paused",
            "pause",
            "record_ideas_observation",
            "record_notion_observation",
            "resume",
        ),
    )


def _register_control_plane_operator_legacy_routes(
    ns: MutableMapping[str, Any],
) -> None:
    global \
        dashboard_preflight, \
        dispatch_next, \
        dispatch_one, \
        draft_next, \
        export_snapshot, \
        ideas_workbench_projection, \
        notion_execution_updates_projection, \
        notion_papers_projection
    global notion_queue_projection, papers, queue, worker_preflight
    _sync_namespace(ns)

    @router.post("/worker/preflight", responses=_HTTP_503_WORKER_PREFLIGHT_URL)
    def worker_preflight(
        payload: WorkerPreflightRequest,
        authorization: Annotated[str | None, Header()] = None,
    ) -> WorkerPreflightResponse:
        authorize(authorization)
        try:
            worker_url = _configured_worker_preflight_url()
        except WorkerPreflightUrlNotConfiguredError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        payload = payload.model_copy(
            update={
                "wake_gate_url": worker_url,
                "bearer_token": config.worker_wake_gate_bearer_token,
                "expected_callback_token_fingerprint": payload.expected_callback_token_fingerprint
                or _callback_acceptance_token_fingerprint(),
            }
        )
        response = run_worker_preflight(payload, store.flags())
        _record_preflight_observations(response)
        return response

    @router.post(
        "/api/preflight",
        responses={**_HTTP_400_PREFLIGHT_WAKE_GATE, **_HTTP_503_WORKER_PREFLIGHT_URL},
    )
    def dashboard_preflight(
        payload: WorkerPreflightRequest,
        authorization: Annotated[str | None, Header()] = None,
    ) -> WorkerPreflightResponse:
        authorize(authorization)
        try:
            payload = _target_aware_preflight_payload(payload)
        except WakeGateUrlNotAllowedError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except WorkerPreflightUrlNotConfiguredError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        response = run_worker_preflight(payload, store.flags())
        _record_preflight_observations(response)
        return response

    @router.post("/dispatch-next")
    def dispatch_next(
        payload: DispatchNextRequest,
        authorization: Annotated[str | None, Header()] = None,
    ) -> DispatchNextResponse:
        authorize(authorization)
        if not payload.dry_run:
            _require_writable_store("live dispatch")
            active = store.active_items()
            candidate = _open_worker_dispatch_candidate()
            if not candidate:
                reason = (
                    "no queued candidate on an open worker lane"
                    if active
                    else "no queued candidate"
                )
                return DispatchNextResponse(
                    ok=True, action="noop", reason=reason, active_count=len(active)
                )
            live, event_id, updated_candidate = _live_dispatch(
                candidate, payload.requested_by, payload.force_preflight
            )
            return DispatchNextResponse(
                ok=True,
                action="live_dispatch",
                reason="live dispatch accepted by worker",
                candidate=updated_candidate,
                active_count=len(store.active_items()),
                event_id=event_id,
                live=live,
            )
        flags = store.flags()
        if flags.queue_paused:
            return DispatchNextResponse(
                ok=True,
                action="paused",
                reason=flags.pause_reason or "queue paused",
                candidate=None,
                active_count=len(store.active_items()),
                event_id=None,
            )
        candidate = _open_worker_dispatch_candidate()
        action = "dry_run_dispatch" if candidate else "noop"
        reason = (
            "dry-run dispatch selected candidate"
            if candidate
            else "no queued candidate on an open worker lane"
        )
        return DispatchNextResponse(
            ok=action in {"paused", "noop", "dry_run_dispatch"},
            action=action,
            reason=reason,
            candidate=_annotate_dispatch_route(candidate),
            active_count=len(store.active_items()),
            event_id=None,
        )

    @router.post("/dispatch-one", responses=_HTTP_DISPATCH_ONE_RESPONSES)
    def dispatch_one(
        payload: DispatchOneRequest,
        authorization: Annotated[str | None, Header()] = None,
    ) -> DispatchNextResponse:
        authorize(authorization)
        project_id = str(payload.project_id or "").strip()
        if not project_id:
            raise HTTPException(status_code=400, detail="project_id is required")
        candidate = store.queue_row(project_id)
        if not candidate:
            raise HTTPException(
                status_code=404, detail="project_id was not found in the queue"
            )
        if _normal_status(candidate.get("status")) != "queued":
            raise HTTPException(status_code=409, detail="project_id is not queued")
        manual_review = _truthy_flag(candidate.get("manual_review_required"))
        if manual_review:
            raise HTTPException(
                status_code=409,
                detail="project_id is blocked by manual_review_required",
            )
        if _has_conflicting_active_lane(candidate):
            raise HTTPException(
                status_code=409,
                detail="active worker lane already exists for selected candidate target",
            )
        if payload.dry_run:
            return DispatchNextResponse(
                ok=True,
                action="dry_run_dispatch_one",
                reason="dry-run selected explicit queued candidate; no state mutated",
                candidate=_annotate_dispatch_route(candidate),
                active_count=0,
            )
        live, event_id, updated_candidate = _live_dispatch(
            candidate,
            payload.requested_by,
            payload.force_preflight,
            allow_paused=True,
            held_override_action=payload.override_hold_action,
        )
        return DispatchNextResponse(
            ok=True,
            action="live_dispatch_one",
            reason="explicit live dispatch accepted by worker; global queue pause preserved",
            candidate=updated_candidate,
            active_count=1,
            event_id=event_id,
            live=live,
        )

    @router.get("/queue")
    def queue(authorization: Annotated[str | None, Header()] = None) -> dict:
        authorize(authorization)
        return {
            "ok": True,
            "rows": store.queue_rows(),
            "counts": store.status_counts(),
            "active": store.active_items(),
        }

    @router.get("/papers")
    def papers(authorization: Annotated[str | None, Header()] = None) -> dict:
        authorize(authorization)
        return {"ok": True, "rows": store.paper_rows()}

    @router.get("/export/snapshot")
    def export_snapshot(
        authorization: Annotated[str | None, Header()] = None,
    ) -> ExportSnapshotResponse:
        authorize(authorization)
        snapshot = store.export_snapshot()
        return ExportSnapshotResponse(
            flags=store.flags(),
            queue_rows=snapshot["queue_rows"],
            paper_rows=snapshot["paper_rows"],
            events=snapshot["events"],
        )

    @router.get("/projections/notion/queue", responses=_HTTP_410_LEGACY_NOTION_API)
    def notion_queue_projection(
        authorization: Annotated[str | None, Header()] = None,
    ) -> ProjectionResponse:
        authorize(authorization)
        try:
            _require_legacy_notion_api_enabled()
        except LegacyNotionApiDisabledError as exc:
            raise HTTPException(
                status_code=410,
                detail={
                    "message": str(exc),
                    "replacement": LEGACY_NOTION_API_REPLACEMENT_PATH,
                },
            ) from exc
        rows = store.queue_notion_projection()
        return ProjectionResponse(rows=rows, counts=store.status_counts())

    @router.get("/projections/ideas/workbench")
    def ideas_workbench_projection(
        authorization: Annotated[str | None, Header()] = None,
    ) -> ProjectionResponse:
        authorize(authorization)
        rows = (
            store.idea_workbench_projection()
            if hasattr(store, "idea_workbench_projection")
            else store.queue_notion_projection()
        )
        counts: dict[str, int] = {}
        for row in rows:
            key = str(row.get("idea_status") or row.get("queue_status") or "unknown")
            counts[key] = counts.get(key, 0) + 1
        return ProjectionResponse(rows=rows, counts=counts)

    @router.get("/projections/notion/papers", responses=_HTTP_410_LEGACY_NOTION_API)
    def notion_papers_projection(
        authorization: Annotated[str | None, Header()] = None,
    ) -> ProjectionResponse:
        authorize(authorization)
        try:
            _require_legacy_notion_api_enabled()
        except LegacyNotionApiDisabledError as exc:
            raise HTTPException(
                status_code=410,
                detail={
                    "message": str(exc),
                    "replacement": LEGACY_NOTION_API_REPLACEMENT_PATH,
                },
            ) from exc
        rows = store.paper_notion_projection()
        counts: dict[str, int] = {}
        for row in rows:
            key = str(row.get("paper_status") or "unknown")
            counts[key] = counts.get(key, 0) + 1
        return ProjectionResponse(rows=rows, counts=counts)

    @router.get(
        "/projections/notion/execution-updates", responses=_HTTP_410_LEGACY_NOTION_API
    )
    def notion_execution_updates_projection(
        authorization: Annotated[str | None, Header()] = None,
    ) -> ProjectionResponse:
        authorize(authorization)
        try:
            _require_legacy_notion_api_enabled()
        except LegacyNotionApiDisabledError as exc:
            raise HTTPException(
                status_code=410,
                detail={
                    "message": str(exc),
                    "replacement": LEGACY_NOTION_API_REPLACEMENT_PATH,
                },
            ) from exc
        rows = store.notion_execution_update_projection()
        return ProjectionResponse(rows=rows, counts={"updates": len(rows)})

    @router.post(
        "/papers/draft-next",
        responses=_HTTP_500_UNRESOLVABLE_ARTIFACT_ROOT,
    )
    def draft_next(
        payload: DraftNextRequest, authorization: Annotated[str | None, Header()] = None
    ) -> DraftNextResponse:
        authorize(authorization)
        candidates = eligible_paper_draft_candidates(
            store.queue_rows(), store.paper_rows()
        )
        skipped: list[dict[str, Any]] = []
        if not candidates:
            return DraftNextResponse(
                ok=True,
                action="noop",
                reason="no eligible completed paper-draft candidate without paper remains",
            )
        for candidate in candidates:
            decision_gate, artifact_root = _pre_evidence_paper_decision_gate(candidate)
            if not decision_gate.get("eligible"):
                skipped.append(
                    {
                        "project_id": candidate.get("project_id"),
                        "run_id": candidate.get("current_run_id"),
                        "reason": "project decision is not paper-ready",
                        "decision_gate": decision_gate,
                        "artifact_root": artifact_root,
                    }
                )
                continue
            if payload.dry_run:
                paper = _paper_record_from_candidate(candidate)
                dry_candidate = draft_candidate_payload(candidate)
                dry_candidate["evidence_sync"] = {
                    "enabled": config.paper_evidence_sync_enabled,
                    "skipped": True,
                    "reason": "dry_run",
                }
                dry_candidate["decision_gate"] = decision_gate
                return DraftNextResponse(
                    ok=True,
                    action="dry_run_draft",
                    reason="eligible paper-ready candidate found; dry_run prevented evidence sync and artifact writes",
                    paper=paper,
                    candidate=dry_candidate,
                )
            _require_writable_store("paper draft-next")
            flags = store.flags()
            if (
                flags.maintenance_mode
                and payload.override_hold_action != "draft-next-while-held"
            ):
                raise HTTPException(
                    status_code=409,
                    detail="maintenance mode blocks paper draft-next; set override_hold_action=draft-next-while-held for an explicit operator override",
                )
            if (
                flags.queue_paused
                and payload.override_hold_action != "draft-next-while-held"
            ):
                raise HTTPException(
                    status_code=409,
                    detail="queue pause blocks paper draft-next; set override_hold_action=draft-next-while-held for an explicit operator override",
                )
            evidence = _prepare_draft_evidence(candidate)
            if not evidence["local_evidence_present"]:
                _record_paper_evidence_blocked(
                    config,
                    store,
                    entity_type="project",
                    entity_id=str(candidate.get("project_id") or ""),
                    project_id=str(candidate.get("project_id") or ""),
                    run_id=str(
                        candidate.get("current_run_id") or candidate.get("run_id") or ""
                    ),
                    artifact_root=str(evidence.get("artifact_root") or ""),
                    evidence_sync=evidence.get("evidence_sync")
                    if isinstance(evidence.get("evidence_sync"), dict)
                    else {},
                )
                skipped.append(
                    {
                        "project_id": candidate.get("project_id"),
                        "run_id": candidate.get("current_run_id"),
                        "reason": "missing paper evidence",
                        "evidence_sync": evidence.get("evidence_sync"),
                    }
                )
                continue
            post_sync_decision_gate = paper_draft_decision_gate(
                str(evidence.get("artifact_root") or "")
            )
            if not post_sync_decision_gate.get("eligible"):
                skipped.append(
                    {
                        "project_id": candidate.get("project_id"),
                        "run_id": candidate.get("current_run_id"),
                        "reason": "project decision is not paper-ready after evidence sync",
                        "decision_gate": post_sync_decision_gate,
                        "artifact_root": evidence.get("artifact_root"),
                        "evidence_sync": evidence.get("evidence_sync"),
                    }
                )
                continue
            paper = _paper_record_from_candidate(candidate)
            candidate_for_write = {
                **candidate,
                "project_dir": evidence.get("artifact_root")
                or candidate.get("project_dir"),
                "evidence_sync": evidence.get("evidence_sync"),
            }
            writer = write_paper_artifacts(
                config, candidate_for_write, paper, force=payload.force
            )
            writer = {
                **writer,
                "evidence_sync": evidence.get("evidence_sync"),
                "artifact_root": evidence.get("artifact_root"),
                "decision_gate": post_sync_decision_gate,
            }
            paper_event_payload = {
                "requested_by": payload.requested_by,
                "paper": paper.model_dump(mode="json"),
                "writer": writer,
            }
            record_paper_draft = getattr(store, "record_paper_draft", None)
            if callable(record_paper_draft):
                record_paper_draft(
                    paper=paper,
                    project_dir=str(candidate_for_write["project_dir"]),
                    idempotency_key=f"paper-draft:{paper.paper_id}:{paper.updated_at}",
                    event_payload=paper_event_payload,
                )
            else:
                store.update_project_dir(
                    str(candidate.get("project_id") or ""),
                    str(candidate_for_write["project_dir"]),
                )
                store.upsert_paper(paper)
                store.append_event(
                    idempotency_key=f"paper-draft:{paper.paper_id}:{paper.updated_at}",
                    event_type="paper.drafted",
                    entity_type="paper",
                    entity_id=paper.paper_id,
                    payload=paper_event_payload,
                )
            try:
                (
                    backfill_inserted,
                    backfill_created,
                    backfill_updated,
                    backfill_skipped,
                    backfill_errors,
                ) = store.backfill_paper_reviews(
                    PaperReviewBackfillRequest(
                        idempotency_key=f"paper-review-backfill:{paper.paper_id}:{paper.updated_at}",
                        requested_by=payload.requested_by,
                        paper_ids=[paper.paper_id],
                        dry_run=False,
                    )
                )
                writer["review_backfill"] = {
                    "inserted_event": backfill_inserted,
                    "created": backfill_created,
                    "updated": backfill_updated,
                    "skipped": backfill_skipped,
                    "errors": backfill_errors,
                }
            except IdempotencyConflict as exc:
                writer["review_backfill"] = {
                    "inserted_event": False,
                    "created": 0,
                    "updated": 0,
                    "skipped": 0,
                    "errors": [{"reason": str(exc)}],
                }
            except Exception as exc:
                writer["review_backfill"] = {
                    "inserted_event": False,
                    "created": 0,
                    "updated": 0,
                    "skipped": 0,
                    "errors": [{"reason": f"{type(exc).__name__}: {exc}"}],
                }
            reason = f"paper draft created with {writer.get('provider')} / {writer.get('model')}"
            if writer.get("fallback_used"):
                reason += " (fallback used)"
            response_candidate = draft_candidate_payload(candidate)
            response_candidate["writer"] = writer
            return DraftNextResponse(
                ok=True,
                action="drafted",
                reason=reason,
                paper=paper,
                candidate=response_candidate,
            )
        return DraftNextResponse(
            ok=True,
            action="noop",
            reason="eligible paper-draft candidates were not paper-ready or lacked sufficient positive local or synced evidence",
            candidate={"skipped": skipped[:10]},
        )

    _export_namespace(
        ns,
        (
            "dashboard_preflight",
            "dispatch_next",
            "dispatch_one",
            "draft_next",
            "export_snapshot",
            "ideas_workbench_projection",
            "notion_execution_updates_projection",
            "notion_papers_projection",
            "notion_queue_projection",
            "papers",
            "queue",
            "worker_preflight",
        ),
    )
