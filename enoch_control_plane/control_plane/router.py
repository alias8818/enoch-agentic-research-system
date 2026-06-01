from __future__ import annotations

from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from functools import partial
import json
import io
import hashlib
import mimetypes
from pathlib import Path, PurePosixPath
import os
import re
import select
import shlex
import subprocess
import tempfile
import time
from typing import Annotated, Any, Callable, Mapping
import urllib.error
import urllib.request
from urllib.parse import urlparse

from fastapi import APIRouter, Body, Header, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from ..config import GateConfig
from ..enoch_core.logic import (
    bounded_useful_signal_row_gate,
    draft_candidate_payload,
    eligible_paper_draft_candidates,
    paper_draft_decision_gate,
)
from ..enoch_core.store import IdempotencyConflict
from ..models import GateCallback, utc_now
from ..llm_settings import (
    LLMSettings,
    llm_settings_path,
    llm_provider_api_key,
    read_llm_settings,
    resolve_workflow_model,
    settings_response,
    settings_update_payload,
    write_llm_provider_secrets,
    write_llm_settings,
)
from ..observability import (
    capture_exception,
    current_rss_mib,
    is_sentry_enabled,
    peak_rss_mib,
)
from ..operational_trace import OperatorTrace, count_by_key, summarize_lane_snapshot
from ..research_provider_defaults import (
    DEFAULT_ALLOWED_RESEARCH_MODELS,
    DEFAULT_RESEARCH_PROVIDER_BASE_URL,
    default_research_provider_openai_base_url,
)
from ..timeutils import parse_utc_datetime
from .paper_writer import write_paper_artifacts
from .router_http_prepare_bindings_src import _HTTP_PREPARE_BINDINGS_SRC
from .models import (
    DEFAULT_MACHINE_TARGET,
    ControlStateResponse,
    DashboardConfigStatus,
    DashboardFinding,
    DashboardFreshness,
    DashboardObservationRecord,
    DashboardStatusResponse,
    DashboardRunDetailResponse,
    DashboardQueueResponse,
    DashboardProjectDetailResponse,
    DashboardPapersResponse,
    DashboardPaperDetailResponse,
    DashboardPaperReviewsResponse,
    DashboardPaperReviewDetailResponse,
    DashboardPageMeta,
    DashboardIntakeResponse,
    DashboardEventsResponse,
    DispatchNextRequest,
    DispatchNextResponse,
    DispatchOneRequest,
    DraftNextRequest,
    DraftNextResponse,
    ImportSnapshotRequest,
    ImportSnapshotResponse,
    IdeaIntakeRequest,
    IdeaIntakeResponse,
    MarkQueueItemPausedRequest,
    NotionIntakeRequest,
    NotionIntakeResponse,
    ExportSnapshotResponse,
    FollowupLaunchRequest,
    FollowupLaunchResponse,
    PaperRecord,
    PaperStatus,
    PaperReviewApproveFinalizationRequest,
    PaperReviewBackfillRequest,
    PaperReviewBackfillResponse,
    PaperReviewChecklistUpdateRequest,
    PaperReviewClaimRequest,
    PaperReviewFinalizationPackageResponse,
    PaperReviewMutationResponse,
    PaperReviewPrepareFinalizationRequest,
    PaperReviewBulkRewriteRequest,
    PaperReviewBulkRewriteResponse,
    PaperReviewRewriteDraftRequest,
    PaperReviewRewriteDraftResponse,
    PaperReviewStatusUpdateRequest,
    ProjectionResponse,
    WorkerPreflightRequest,
    WorkerPreflightResponse,
    PauseRequest,
    ResumeRequest,
)
from .alerts import evaluate_and_notify_queue_alerts, send_pushover
from .longhaul_readiness import evaluate_longhaul_readiness
from .resource_utilization import (
    classify_low_utilization_runs,
    resource_utilization_status,
)
from ..research_quality.status import (
    DEFAULT_AUTOPILOT_HISTORY_PATH,
    DEFAULT_REPORT_PATHS,
    DEFAULT_WINDOW_REPORT_PATH,
    load_latest_quality_status,
)
from ..source_lineage.status import (
    DEFAULT_REPORT_PATH as DEFAULT_SOURCE_LINEAGE_REPORT_PATH,
    load_latest_source_lineage_status,
)
from . import read_models
from .store import (
    ACTIVE_STATUSES,
    TERMINAL_SUCCESS_CALLBACK_STATES,
    ControlPlaneStore,
    _atomic_write_text,
    _restore_or_remove_path,
)
from .supabase_store import (
    SupabaseControlPlaneStore,
    SupabaseReadOnlyControlPlaneStore,
    resolve_supabase_database_url,
)
from .worker_adapter import HttpResult, post_worker_json, run_worker_preflight
from .worker_evidence_sync import _sync_worker_http_evidence

_HTTP_500_UNRESOLVABLE_ARTIFACT_ROOT: dict[int, dict[str, str]] = {
    500: {"description": "Configured artifact roots are not resolvable"},
}

_HTTP_400_RESEARCH_CANDIDATE_ID: dict[int, dict[str, str]] = {
    400: {
        "description": (
            "candidate_id is required or must be a bounded slug-like identifier"
        ),
    },
}

_HTTP_501_WRITABLE_STORE: dict[int, dict[str, str]] = {
    501: {
        "description": (
            "Mutating action requires a writable control-plane store; "
            "supabase_readonly is read-only"
        ),
    },
}

# Centralized description for S1192 duplication (501 ledger write paths).
RESEARCH_FACILITY_LEDGER_REQUIRES_SUPABASE_STORE = (
    "Research Facility ledger writes require the Supabase control-plane store"
)

_HTTP_501_SUPABASE_LEDGER: dict[int, dict[str, str]] = {
    501: {
        "description": RESEARCH_FACILITY_LEDGER_REQUIRES_SUPABASE_STORE,
    },
}

_HTTP_410_LEGACY_NOTION_API: dict[int, dict[str, str]] = {
    410: {
        "description": (
            "Legacy Notion control-plane APIs are disabled; use Supabase-native "
            "/control/intake/ideas and /control/api/intake/ideas"
        ),
    },
}

_HTTP_503_DASHBOARD_V2: dict[int, dict[str, str]] = {
    503: {"description": "Dashboard V2 static assets are missing or not built"},
}

_HTTP_503_WORKER_PREFLIGHT_URL: dict[int, dict[str, str]] = {
    503: {
        "description": "Worker preflight requires configured worker_wake_gate_url",
    },
}

_HTTP_404_RUN: dict[int, dict[str, str]] = {404: {"description": "Run not found"}}

_HTTP_404_PROJECT: dict[int, dict[str, str]] = {
    404: {"description": "Project not found"},
}

_HTTP_404_PAPER: dict[int, dict[str, str]] = {404: {"description": "Paper not found"}}

_HTTP_404_PAPER_DETAIL = "paper not found"

_HTTP_404_QUEUE_ITEM: dict[int, dict[str, str]] = {
    404: {"description": "Queue item not found"},
}

_HTTP_404_DASHBOARD_ASSET: dict[int, dict[str, str]] = {
    404: {"description": "Dashboard V2 asset not found"},
}

_HTTP_404_PUBLICATION_AUTOMATION: dict[int, dict[str, str]] = {
    404: {"description": "Publication automation item not found"},
}

_HTTP_404_PUBLICATION_AUTOMATION_NEXT: dict[int, dict[str, str]] = {
    404: {"description": "No matching publication automation item"},
}

_HTTP_409_IDEMPOTENCY: dict[int, dict[str, str]] = {
    409: {"description": "Idempotency key conflict or incompatible replay"},
}

_HTTP_409_DISPATCH: dict[int, dict[str, str]] = {
    409: {
        "description": (
            "Dispatch rejected: project not queued, manual review required, "
            "or active worker lane conflict"
        ),
    },
}

_HTTP_400_DISPATCH_PROJECT: dict[int, dict[str, str]] = {
    400: {"description": "project_id is required"},
}

_HTTP_400_PREFLIGHT_WAKE_GATE: dict[int, dict[str, str]] = {
    400: {
        "description": (
            "wake_gate_url must match configured worker_wake_gate_url or a "
            "configured worker target; use machine_target for named routes"
        ),
    },
}

_HTTP_PAPER_REVIEW_MUTATION_RESPONSES: dict[int, dict[str, str]] = {
    **_HTTP_501_WRITABLE_STORE,
    400: {"description": "Invalid publication automation mutation request"},
    409: _HTTP_409_IDEMPOTENCY[409],
}

_HTTP_PUBLICATION_AUTOMATION_DETAIL_RESPONSES: dict[int, dict[str, str]] = {
    404: _HTTP_404_PUBLICATION_AUTOMATION[404],
}

_HTTP_DISPATCH_ONE_RESPONSES: dict[int, dict[str, str]] = {
    **_HTTP_501_WRITABLE_STORE,
    **_HTTP_400_DISPATCH_PROJECT,
    404: {"description": "project_id was not found in the queue"},
    **_HTTP_409_DISPATCH,
}

_HTTP_NOTION_INTAKE_RESPONSES: dict[int, dict[str, str]] = {
    **_HTTP_501_WRITABLE_STORE,
    **_HTTP_409_IDEMPOTENCY,
    **_HTTP_410_LEGACY_NOTION_API,
}

_HTTP_WRITABLE_IDEMPOTENCY_RESPONSES: dict[int, dict[str, str]] = {
    **_HTTP_501_WRITABLE_STORE,
    **_HTTP_409_IDEMPOTENCY,
}

_HTTP_MARK_QUEUE_ITEM_PAUSED_RESPONSES: dict[int, dict[str, str]] = {
    **_HTTP_501_WRITABLE_STORE,
    **_HTTP_404_QUEUE_ITEM,
}


class UnresolvableArtifactRootsError(RuntimeError):
    """Configured project and state artifact roots could not be resolved."""


class UnresolvableConfiguredProjectRootError(ValueError):
    """Configured project root path could not be resolved."""


class PaperArtifactRootNotInspectableError(RuntimeError):
    """Paper rewrite project_dir exists but could not be inspected."""


class PaperArtifactRootError(ValueError):
    """Paper rewrite artifact root could not be resolved or inspected."""


class PaperArtifactSnapshotReadError(ValueError):
    """A paper rewrite artifact snapshot could not be read."""


class WritableControlPlaneStoreRequiredError(RuntimeError):
    """A mutating control-plane action requires a writable store backend."""


class LegacyNotionApiDisabledError(RuntimeError):
    """Legacy Notion control-plane APIs are disabled."""


class PublicationAutomationNotFoundError(LookupError):
    """Publication automation paper or review row is missing."""


class PaperRewriteBlockedReviewStatusError(ValueError):
    """Publication automation item cannot be rewritten in this review status."""


class PaperRewriteIdempotencyReuseError(ValueError):
    """Idempotency key was reused with a different rewrite payload."""


class PaperRewriteEvidenceRequiredError(RuntimeError):
    """Paper rewrite requires synced project evidence."""

    def __init__(self, evidence_sync: dict[str, Any]) -> None:
        self.evidence_sync = evidence_sync
        super().__init__("paper rewrite requires synced project evidence")


class WorkerPreflightUrlNotConfiguredError(RuntimeError):
    """Worker preflight URL is not configured."""


class WakeGateUrlNotAllowedError(ValueError):
    """wake_gate_url does not match configured worker targets."""


def _assert_writable_control_plane_store(action: str, *, backend: str) -> None:
    if backend == "supabase_readonly":
        raise WritableControlPlaneStoreRequiredError(
            f"{action} requires a writable control-plane store; "
            "supabase_readonly is read-only"
        )


def _require_writable_store_http(action: str, *, backend: str) -> None:
    try:
        _assert_writable_control_plane_store(action, backend=backend)
    except WritableControlPlaneStoreRequiredError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc


def _require_writable_store(action: str) -> None:
    if _ROUTER_GATE_CONFIG is None:
        raise HTTPException(status_code=501, detail="control-plane config is not bound")
    _require_writable_store_http(
        action, backend=_ROUTER_GATE_CONFIG.control_plane_store_backend
    )


RequireBearer = Callable[[str | None], None]

_RUN_NOTES_MD = "run_notes.md"
_EVIDENCE_SYNC_METHOD_WORKER_HTTP_SSH = "worker_http+ssh"
_DEFAULT_RESEARCH_MODEL = "gpt-5.5"
_ROUTER_GATE_CONFIG: GateConfig | None = None


@dataclass(frozen=True)
class _ResearchProviderSelection:
    provider_model: str
    allowed_models: list[str]
    provider_base_url: str
    provider_openai_base_url: str
    provider_api_key: str = ""
    provider_id: str = ""


def _normal_status(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def _truthy_flag(value: Any) -> bool:
    return value is True or value in {
        1,
        "1",
        "true",
        "True",
        "TRUE",
        "yes",
        "YES",
        "on",
        "ON",
    }


def _expanduser_path_or_http(
    value: str, *, detail: str = "path contains an unexpandable user home"
) -> Path:
    try:
        return Path(value).expanduser()
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=detail) from exc


def _bounded_int_from_mapping(
    values: dict[str, Any], name: str, default: int, lower: int, upper: int
) -> int:
    value = values.get(name)
    if value is None:
        value = default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(lower, min(parsed, upper))


def _bounded_float_from_mapping(
    values: dict[str, Any], name: str, default: float, lower: float, upper: float
) -> float:
    value = values.get(name)
    if value is None:
        value = default
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return max(lower, min(parsed, upper))


def _resolve_research_provider_model(
    body: dict[str, Any],
) -> tuple[str, list[str]] | dict[str, Any]:
    """Resolve and validate the research provider model against the allow-list.

    Extracted from dashboard_research_run_cycle to reduce cyclomatic complexity.
    Returns (provider_model, allowed_models) on success or an error response dict.
    """
    if _ROUTER_GATE_CONFIG is not None and not os.environ.get(
        "ENOCH_RESEARCH_ALLOWED_MODELS"
    ):
        requested_model = str(
            body.get("model") or os.environ.get("ENOCH_RESEARCH_PROVIDER_MODEL") or ""
        ).strip()
        try:
            settings = read_llm_settings(_ROUTER_GATE_CONFIG)
            workflow, model, _provider = resolve_workflow_model(
                settings,
                "research_generation",
                requested_model=requested_model,
                require_openai_compatible=True,
            )
            return model.model_id, workflow.model_pool
        except Exception as exc:
            reason = f"research provider settings invalid: {exc}"
            if requested_model:
                reason = (
                    f"provider model {requested_model!r} is not in the allowed model list; "
                    f"research provider settings invalid: {exc}"
                )
            return {
                "ok": False,
                "action": "research_cycle_blocked",
                "dry_run": bool(body.get("dry_run", True)),
                "reason": reason,
                "allowed_models": [],
                "queue_admitted": False,
                "dispatch_started": False,
            }

    allowed_models = [
        item.strip()
        for item in os.environ.get(
            "ENOCH_RESEARCH_ALLOWED_MODELS",
            ",".join(DEFAULT_ALLOWED_RESEARCH_MODELS),
        ).split(",")
        if item.strip()
    ]
    if not allowed_models:
        allowed_models = list(DEFAULT_ALLOWED_RESEARCH_MODELS)

    provider_model = str(
        body.get("model")
        or os.environ.get("ENOCH_RESEARCH_PROVIDER_MODEL")
        or DEFAULT_ALLOWED_RESEARCH_MODELS[-1]
    ).strip()

    if provider_model not in allowed_models:
        return {
            "ok": False,
            "action": "research_cycle_blocked",
            "dry_run": bool(body.get("dry_run", True)),
            "reason": f"provider model {provider_model!r} is not in the allowed model list",
            "allowed_models": allowed_models,
            "queue_admitted": False,
            "dispatch_started": False,
        }

    return provider_model, allowed_models


def _synthetic_budget_base_url(openai_base_url: str) -> str:
    value = str(openai_base_url or "").rstrip("/")
    if value.endswith("/openai/v1"):
        return value[: -len("/openai/v1")]
    return value


def _resolve_research_provider_selection(
    config: GateConfig,
    body: dict[str, Any],
) -> _ResearchProviderSelection | dict[str, Any]:
    """Resolve provider/model routing from settings unless env allow-list overrides it."""

    if os.environ.get("ENOCH_RESEARCH_ALLOWED_MODELS"):
        model_resolution = _resolve_research_provider_model(body)
        if isinstance(model_resolution, dict):
            return model_resolution
        provider_model, allowed_models = model_resolution
        openai_base_url = os.environ.get(
            "ENOCH_RESEARCH_PROVIDER_OPENAI_BASE_URL",
            default_research_provider_openai_base_url(
                os.environ.get(
                    "ENOCH_RESEARCH_PROVIDER_BASE_URL",
                    DEFAULT_RESEARCH_PROVIDER_BASE_URL,
                )
            ),
        ).rstrip("/")
        provider_base_url = os.environ.get(
            "ENOCH_RESEARCH_PROVIDER_BASE_URL",
            _synthetic_budget_base_url(openai_base_url),
        ).rstrip("/")
        return _ResearchProviderSelection(
            provider_model=provider_model,
            allowed_models=allowed_models,
            provider_base_url=provider_base_url,
            provider_openai_base_url=openai_base_url,
            provider_api_key=os.environ.get("ENOCH_RESEARCH_PROVIDER_API_KEY", ""),
            provider_id="env",
        )

    requested_model = str(
        body.get("model") or os.environ.get("ENOCH_RESEARCH_PROVIDER_MODEL") or ""
    ).strip()
    try:
        settings = read_llm_settings(config)
        workflow, model, provider = resolve_workflow_model(
            settings,
            "research_generation",
            requested_model=requested_model,
            require_openai_compatible=True,
        )
    except Exception as exc:
        reason = f"research provider settings invalid: {exc}"
        if requested_model:
            reason = (
                f"provider model {requested_model!r} is not in the allowed model list; "
                f"research provider settings invalid: {exc}"
            )
        return {
            "ok": False,
            "action": "research_cycle_blocked",
            "dry_run": bool(body.get("dry_run", True)),
            "reason": reason,
            "allowed_models": [],
            "queue_admitted": False,
            "dispatch_started": False,
        }
    openai_base_url = str(
        body.get("provider_openai_base_url")
        or os.environ.get("ENOCH_RESEARCH_PROVIDER_OPENAI_BASE_URL")
        or provider.base_url
    ).rstrip("/")
    provider_base_url = str(
        body.get("provider_base_url")
        or os.environ.get("ENOCH_RESEARCH_PROVIDER_BASE_URL")
        or (
            _synthetic_budget_base_url(openai_base_url)
            if provider.provider_id == "synthetic"
            else openai_base_url
        )
    ).rstrip("/")
    return _ResearchProviderSelection(
        provider_model=model.model_id,
        allowed_models=workflow.model_pool,
        provider_base_url=provider_base_url,
        provider_openai_base_url=openai_base_url,
        provider_api_key=llm_provider_api_key(config, provider),
        provider_id=provider.provider_id,
    )


def _resolve_research_cycle_params(
    body: dict[str, Any],
    *,
    worker_lane_limit: int = 4,
    promotion_batch_limit: int | None = None,
) -> Any:
    """Resolve all bounded limits and thresholds for one research cycle run.

    Extracted from dashboard_research_run_cycle to reduce cyclomatic complexity.
    The lane-dependent caps are passed from the (closure) call site that can
    see _configured_worker_lanes(); resolver stays top-level for testability.
    """
    from argparse import Namespace

    def bounded_int(name: str, default: int, lower: int, upper: int) -> int:
        return _bounded_int_from_mapping(body, name, default, lower, upper)

    def bounded_float(name: str, default: float, lower: float, upper: float) -> float:
        return _bounded_float_from_mapping(body, name, default, lower, upper)

    if promotion_batch_limit is None:
        promotion_batch_limit = _bounded_int_env(
            "ENOCH_RESEARCH_MAX_PROMOTIONS_PER_RUN_CAP", 25, 1, 100
        )

    provider_openai_base_url = os.environ.get(
        "ENOCH_RESEARCH_PROVIDER_OPENAI_BASE_URL",
        default_research_provider_openai_base_url(
            os.environ.get(
                "ENOCH_RESEARCH_PROVIDER_BASE_URL",
                DEFAULT_RESEARCH_PROVIDER_BASE_URL,
            )
        ),
    ).rstrip("/")
    provider_base_url = os.environ.get(
        "ENOCH_RESEARCH_PROVIDER_BASE_URL",
        _synthetic_budget_base_url(provider_openai_base_url),
    ).rstrip("/")
    if (
        _ROUTER_GATE_CONFIG is not None
        and not os.environ.get("ENOCH_RESEARCH_PROVIDER_OPENAI_BASE_URL")
        and not os.environ.get("ENOCH_RESEARCH_PROVIDER_BASE_URL")
    ):
        selection = _resolve_research_provider_selection(_ROUTER_GATE_CONFIG, body)
        if isinstance(selection, _ResearchProviderSelection):
            provider_base_url = selection.provider_base_url
            provider_openai_base_url = selection.provider_openai_base_url
            provider_api_key = selection.provider_api_key
        else:
            provider_api_key = os.environ.get("ENOCH_RESEARCH_PROVIDER_API_KEY", "")
    else:
        provider_api_key = os.environ.get("ENOCH_RESEARCH_PROVIDER_API_KEY", "")

    return Namespace(
        max_provider_requests=bounded_int("max_provider_requests_per_run", 1, 0, 3),
        max_promotions=bounded_int(
            "max_promotions_per_run",
            min(2, worker_lane_limit),
            0,
            promotion_batch_limit,
        ),
        max_dispatches=bounded_int("max_dispatches_per_run", 0, 0, worker_lane_limit),
        min_queue_depth_per_lane=bounded_int(
            "min_queue_depth_per_lane",
            _bounded_int_env("ENOCH_RESEARCH_MIN_QUEUE_DEPTH_PER_LANE", 25, 0, 100),
            0,
            100,
        ),
        max_paper_drafts=bounded_int("max_paper_drafts_per_run", 0, 0, 1),
        max_publication_rewrites=bounded_int(
            "max_publication_rewrites_per_run", 0, 0, 1
        ),
        wait_for_completion=bool(body.get("wait_for_completion", False)),
        max_wait_seconds=bounded_int("max_wait_seconds", 0, 0, 1800),
        poll_interval_seconds=bounded_int("poll_interval_seconds", 10, 2, 60),
        min_admission_score=bounded_float(
            "min_admission_score",
            bounded_float("admit_threshold", 72.0, 0.0, 100.0),
            0.0,
            100.0,
        ),
        max_candidates=bounded_int("max_candidates", 2, 1, 10),
        fresh_generation_backlog_threshold=bounded_int(
            "fresh_generation_backlog_threshold",
            _bounded_int_env(
                "ENOCH_RESEARCH_FRESH_GENERATION_BACKLOG_THRESHOLD", 25, 0, 500
            ),
            0,
            500,
        ),
        topic=str(body.get("topic") or "").strip(),
        temperature=bounded_float("temperature", 0.6, 0.0, 1.5),
        seed=str(body.get("seed") or utc_now()).strip(),
        provider_base_url=provider_base_url,
        provider_openai_base_url=provider_openai_base_url,
        provider_api_key=provider_api_key,
        generation_timeout=bounded_int("generation_timeout", 240, 10, 300),
        generation_max_tokens=bounded_int(
            "generation_max_tokens",
            _bounded_int_env("ENOCH_RESEARCH_PROVIDER_MAX_TOKENS", 8000, 1000, 16000),
            1000,
            16000,
        ),
        generation_attempts=bounded_int(
            "generation_attempts",
            _bounded_int_env("ENOCH_RESEARCH_PROVIDER_ATTEMPTS", 2, 1, 3),
            1,
            3,
        ),
    )


def _bounded_int_env(name: str, default: int, lower: int, upper: int) -> int:
    try:
        parsed = int(os.environ.get(name) or default)
    except ValueError:
        parsed = default
    return max(lower, min(parsed, upper))


def _event_cooldown_bucket(*, bucket_seconds: int = 3600) -> int:
    return int(datetime.now(timezone.utc).timestamp() // max(1, bucket_seconds))


def _active_lane_signature(active_items: list[dict[str, Any]]) -> str:
    parts = [
        f"{item.get('project_id') or ''}:{item.get('current_run_id') or ''}:{item.get('status') or ''}"
        for item in active_items
    ]
    payload = "|".join(sorted(parts))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


DASHBOARD_V2_DIST_PATH = Path(__file__).with_name("dashboard_v2")

# Centralized reason constant for the top remaining S1192 duplication
# (worker preflight error paths and messages in router.py).
WORKER_PREFLIGHT_FAILED_REASON = "worker preflight failed"

# Dashboard finding source for cross-source control-plane DB + worker preflight.
CONTROL_PLANE_DB_WORKER_PREFLIGHT_SOURCE = "control_plane_db+worker_preflight"

# Centralized authority for cross-source active-lane reconciliation findings.
CROSS_SOURCE_ACTIVE_LANE_RECONCILIATION_AUTHORITY = (
    "cross-source active-lane reconciliation"
)

# Centralized event type / status constant for the top remaining S1192 duplication
# (paper_review draft rewrite events and comparisons in router.py).
PAPER_REVIEW_DRAFT_REWRITTEN = "paper_review.draft_rewritten"

# Centralized 404 message for publication automation lookup paths (Sonar S1192 at :845).
PUBLICATION_AUTOMATION_ITEM_NOT_FOUND = "publication automation item not found"

# Centralized authority label for Supabase-native ideas workbench freshness paths.
SUPABASE_NATIVE_IDEAS_WORKBENCH_AUTHORITY = "Supabase-native ideas workbench"

# Centralized replacement path for legacy Notion API 410 responses (S1192).
LEGACY_NOTION_API_REPLACEMENT_PATH = "/control/intake/ideas"


def _atomic_write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("wb", dir=path.parent, delete=False) as handle:
            handle.write(content)
            tmp = Path(handle.name)
        tmp.replace(path)
    finally:
        if tmp is not None:
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError:
                pass


from .safe_tar_extract import extract_safe_tar_bytes as _extract_safe_tar_bytes


def _safe_local_evidence_file(project_dir: Path, path: Path) -> bool:
    try:
        rel = path.relative_to(project_dir)
        path.resolve().relative_to(project_dir.resolve())
    except (OSError, ValueError):
        return False
    current = project_dir
    for part in rel.parts:
        current = current / part
        if current.is_symlink():
            return False
    if not path.is_file():
        return False
    try:
        return path.stat().st_size > 0
    except OSError:
        return False


def _local_high_signal_evidence_present(project_dir: Path) -> bool:
    return _safe_local_evidence_file(project_dir, project_dir / _RUN_NOTES_MD) and any(
        _safe_local_evidence_file(project_dir, project_dir / rel)
        for rel in (".enoch/project_decision.json", ".omx/project_decision.json")
    )


def _existing_non_symlink_dir(path: Path) -> bool:
    try:
        return path.exists() and not path.is_symlink() and path.is_dir()
    except (OSError, RuntimeError, ValueError):
        return False


def _safe_rglob(path: Path, pattern: str) -> list[Path]:
    try:
        return list(path.rglob(pattern))
    except (OSError, RuntimeError, ValueError):
        return []


def _paper_dir_has_grounding_evidence(project_dir: Path, paper_dir: Path) -> bool:
    return _safe_local_evidence_file(
        project_dir, paper_dir / "evidence_bundle.json"
    ) and _safe_local_evidence_file(project_dir, paper_dir / "claim_ledger.json")


def _papers_tree_has_grounding_evidence(project_dir: Path, papers_dir: Path) -> bool:
    if not _existing_non_symlink_dir(papers_dir):
        return False
    safe_paper_dirs: list[Path] = []
    for path in _safe_rglob(papers_dir, "*"):
        try:
            if path.is_dir():
                safe_paper_dirs.append(path)
        except (OSError, RuntimeError, ValueError):
            continue
    return any(
        _paper_dir_has_grounding_evidence(project_dir, paper_dir)
        for paper_dir in sorted(safe_paper_dirs)
    )


def _local_paper_evidence_present(project_dir: Path) -> bool:
    if _local_high_signal_evidence_present(project_dir):
        return True
    if _papers_tree_has_grounding_evidence(project_dir, project_dir / "papers"):
        return True
    run_notes_present = _safe_local_evidence_file(
        project_dir, project_dir / _RUN_NOTES_MD
    )
    results_dir = project_dir / "results"
    return (
        run_notes_present
        and _existing_non_symlink_dir(results_dir)
        and any(
            _safe_local_evidence_file(project_dir, path)
            for path in _safe_rglob(results_dir, "*.json")
        )
    )


def _remote_evidence_dir_fallback(remote_root: str, project_id: str) -> str:
    return f"{remote_root}/{_safe_project_artifact_name(project_id)}"


def _remote_evidence_dir_for_source(
    config: GateConfig,
    *,
    remote_root: str,
    project_id: str,
    source: str,
) -> str | None:
    remote_source = PurePosixPath(source.replace("\\", "/"))
    if ".." in remote_source.parts:
        return _remote_evidence_dir_fallback(remote_root, project_id)
    try:
        source_path = Path(source).expanduser()
    except RuntimeError:
        return _remote_evidence_dir_fallback(remote_root, project_id)
    try:
        local_root = config.expanded_project_root.resolve()
    except (OSError, RuntimeError, ValueError):
        return _remote_evidence_dir_fallback(remote_root, project_id)
    if source_path.is_absolute():
        try:
            source_path.resolve().relative_to(local_root)
        except (OSError, RuntimeError, ValueError):
            return source
        return None
    if not remote_source.is_absolute():
        return f"{remote_root}/{remote_source.as_posix()}"
    return None


def _remote_evidence_dir(
    config: GateConfig, *, project_id: str, source_project_dir: str = ""
) -> str:
    remote_root = config.paper_evidence_sync_remote_root.rstrip("/")
    source = source_project_dir.strip()
    if not source:
        return f"{remote_root}/{project_id}"
    resolved = _remote_evidence_dir_for_source(
        config, remote_root=remote_root, project_id=project_id, source=source
    )
    if resolved is not None:
        return resolved
    return f"{remote_root}/{project_id}"


def _safe_project_artifact_name(project_id: str) -> str:
    raw = Path(str(project_id or "").strip())
    if (
        str(project_id or "").strip()
        and not raw.is_absolute()
        and not any(part in {"", ".", ".."} for part in raw.parts)
    ):
        return raw.as_posix()
    return _safe_slug(str(project_id or ""), "project")


def _has_symlink_component(root: Path, candidate: Path) -> bool:
    try:
        rel = candidate.relative_to(root)
    except ValueError:
        return True
    current = root
    for part in rel.parts:
        current = current / part
        if current.is_symlink():
            return True
    return False


def _safe_artifact_candidate(root: Path, candidate: Path) -> Path | None:
    try:
        resolved = candidate.resolve()
        resolved.relative_to(root)
    except (OSError, RuntimeError, ValueError):
        return None
    if _has_symlink_component(root, candidate):
        return None
    return resolved


def _safe_fallback_artifact_root(root: Path, project_id: str) -> Path:
    slug = _safe_slug(str(project_id or ""), "project")
    digest = hashlib.sha256(slug.encode("utf-8")).hexdigest()[:12]
    for candidate in (
        root / _safe_project_artifact_name(project_id),
        root / "_evidence_artifacts" / slug,
        root / f"_evidence_artifacts_{digest}" / slug,
    ):
        safe = _safe_artifact_candidate(root, candidate)
        if safe is not None:
            return safe
    return root


def _local_artifact_root(
    config: GateConfig, *, project_id: str, project_dir_text: str = ""
) -> Path:
    try:
        root = config.expanded_project_root.resolve()
    except (OSError, RuntimeError, ValueError):
        try:
            root = (config.expanded_state_dir / "evidence-artifacts").resolve()
        except (OSError, RuntimeError, ValueError) as exc:
            raise UnresolvableArtifactRootsError(
                "configured artifact roots are not resolvable"
            ) from exc
    fallback = _safe_fallback_artifact_root(root, project_id)
    source = str(project_dir_text or "").strip()
    if not source:
        return fallback
    try:
        candidate = Path(source).expanduser()
    except RuntimeError:
        return fallback
    safe_candidate = _safe_artifact_candidate(
        root, candidate if candidate.is_absolute() else root / candidate
    )
    return safe_candidate or fallback


def _local_artifact_root_http(
    config: GateConfig, *, project_id: str, project_dir_text: str = ""
) -> Path:
    try:
        return _local_artifact_root(
            config, project_id=project_id, project_dir_text=project_dir_text
        )
    except UnresolvableArtifactRootsError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


_PAPER_REWRITE_BLOCKED_REVIEW_STATUSES = frozenset(
    {
        "blocked",
        "changes_requested",
        "in_review",
        "unreviewed",
        "rejected",
    }
)

_PAPER_REWRITE_PUBLICATION_POLICY = {
    "ai_generated": True,
    "operator_credit_claim": "none",
    "disclaimer": (
        "AI-generated and AI-written from automated research artifacts; "
        "released with no personal authorship credit claimed by the operator."
    ),
}

_PAPER_REWRITE_DRAFT_RESPONSES: dict[int, dict[str, str]] = {
    400: {
        "description": (
            "Invalid rewrite request: blocked review status, configured "
            "project root or artifact root could not be resolved or "
            "inspected, unreadable artifacts, or validation error"
        ),
    },
    404: {"description": "Publication automation item not found"},
    409: {
        "description": (
            "Idempotency key conflict: key reused with a different payload, "
            "or event-store idempotency conflict during draft rewrite"
        ),
    },
}


def _paper_record_from_store_row(row: dict[str, Any]) -> PaperRecord:
    data = dict(row)
    for key in ("generated_at", "updated_at"):
        value = data.get(key)
        if isinstance(value, datetime):
            data[key] = value.isoformat()
    return PaperRecord.model_validate(data)


def _paper_rewrite_rows_or_404(
    store: ControlPlaneStore, paper_id: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    paper = store.paper_row(paper_id)
    item = store.paper_review_row(paper_id, include_rank_reasons=True)
    if paper is None or item is None:
        raise PublicationAutomationNotFoundError(PUBLICATION_AUTOMATION_ITEM_NOT_FOUND)
    review_status = _normal_status(item.get("review_status"))
    if review_status in _PAPER_REWRITE_BLOCKED_REVIEW_STATUSES:
        raise PaperRewriteBlockedReviewStatusError(
            f"publication automation items with review_status={review_status} "
            "cannot be rewritten or auto-published"
        )
    return paper, item


def _expanded_configured_project_root(config: GateConfig) -> Path:
    try:
        return config.expanded_project_root.resolve()
    except (OSError, RuntimeError, ValueError) as exc:
        raise UnresolvableConfiguredProjectRootError(
            "configured project root could not be resolved"
        ) from exc


def _paper_rewrite_current_project_dir(project: dict[str, Any] | None) -> Path:
    try:
        return (
            Path(str((project or {}).get("project_dir") or "")).expanduser()
            if project
            else Path()
        )
    except RuntimeError:
        return Path()


def _paper_rewrite_current_dir_resolution(
    configured_root: Path,
    current_project_dir: Path,
) -> tuple[bool, Path | None]:
    if not str(current_project_dir):
        return False, None
    try:
        resolved = current_project_dir.resolve()
        resolved.relative_to(configured_root)
    except ValueError:
        return False, None
    except (OSError, RuntimeError) as exc:
        raise PaperArtifactRootError(
            "paper artifact root could not be resolved"
        ) from exc
    try:
        return resolved.exists(), resolved
    except (OSError, RuntimeError) as exc:
        raise PaperArtifactRootNotInspectableError(
            "paper artifact root could not be inspected"
        ) from exc


def _resolve_paper_rewrite_artifact_root(
    config: GateConfig,
    *,
    project_id: str,
    project: dict[str, Any] | None,
) -> tuple[Path, bool]:
    try:
        configured_root = _expanded_configured_project_root(config)
    except UnresolvableConfiguredProjectRootError as exc:
        raise PaperArtifactRootError(str(exc)) from exc
    current_project_dir = _paper_rewrite_current_project_dir(project)
    use_current_dir, resolved_current_project_dir = (
        _paper_rewrite_current_dir_resolution(configured_root, current_project_dir)
    )
    try:
        artifact_root = (
            resolved_current_project_dir
            if use_current_dir and resolved_current_project_dir is not None
            else (configured_root / project_id).resolve()
        )
    except (OSError, RuntimeError, ValueError) as exc:
        raise PaperArtifactRootError(
            "paper artifact root could not be resolved"
        ) from exc
    return artifact_root, use_current_dir


def _paper_rewrite_idempotent_response(
    store: ControlPlaneStore,
    *,
    payload: PaperReviewRewriteDraftRequest,
    paper_id: str,
    item: dict[str, Any],
    paper: dict[str, Any],
    artifact_root: Path,
) -> PaperReviewRewriteDraftResponse | None:
    existing_event_reader = getattr(store, "event_by_idempotency_key", None)
    if not callable(existing_event_reader):
        return None
    existing_event = existing_event_reader(payload.idempotency_key)
    if not existing_event:
        return None
    if (
        str(existing_event.get("event_type") or "") != PAPER_REVIEW_DRAFT_REWRITTEN
        or str(existing_event.get("entity_id") or "") != paper_id
    ):
        raise PaperRewriteIdempotencyReuseError(
            f"idempotency key {payload.idempotency_key!r} was reused with "
            "different payload"
        )
    return PaperReviewRewriteDraftResponse(
        inserted_event=False,
        event_id=int(existing_event.get("event_id") or 0),
        item=item,
        paper=paper,
        writer={"idempotent_replay": True},
        artifact_root=str(artifact_root),
    )


def _paper_rewrite_candidate_payload(
    *,
    project_id: str,
    project: dict[str, Any] | None,
    paper: dict[str, Any],
    item: dict[str, Any],
    artifact_root: Path,
    record: PaperRecord,
    evidence_sync: dict[str, Any],
) -> dict[str, Any]:
    return {
        "project_id": project_id,
        "project_name": str(
            (project or paper or item).get("project_name") or project_id
        ),
        "project_dir": str(artifact_root),
        "run_id": record.run_id,
        "current_run_id": record.run_id,
        "notion_page_url": str((project or paper).get("notion_page_url") or ""),
        "paper_review_item": item,
        "paper": paper,
        "evidence_sync": evidence_sync,
        "publication_policy": _PAPER_REWRITE_PUBLICATION_POLICY,
    }


def _snapshot_paper_rewrite_artifacts(
    artifact_root: Path, record: PaperRecord
) -> dict[Path, tuple[bool, bytes]]:
    artifact_snapshots: dict[Path, tuple[bool, bytes]] = {}
    for rel_path in {
        record.draft_markdown_path,
        record.draft_latex_path,
        record.evidence_bundle_path,
        record.claim_ledger_path,
        record.manifest_path,
    }:
        try:
            target = (artifact_root / rel_path).resolve()
            target.relative_to(artifact_root)
        except (OSError, RuntimeError, ValueError):
            continue
        try:
            existed = target.exists()
            content = target.read_bytes() if existed and target.is_file() else b""
        except (OSError, RuntimeError, ValueError) as exc:
            raise PaperArtifactSnapshotReadError(
                f"paper artifact snapshot could not be read: {rel_path}"
            ) from exc
        artifact_snapshots[target] = (existed, content)
    return artifact_snapshots


def _restore_paper_rewrite_side_effects(
    store: ControlPlaneStore,
    *,
    artifact_snapshots: Mapping[Path, tuple[bool, bytes]],
    original_record: PaperRecord,
    original_project_dir: str,
    project_id: str,
) -> None:
    for path, (existed, content) in artifact_snapshots.items():
        _restore_or_remove_path(path, existed=existed, content=content)
    try:
        store.upsert_paper(original_record.model_copy(update={"updated_at": utc_now()}))
        if original_project_dir:
            store.update_project_dir(project_id, original_project_dir)
    except Exception as exc:
        raise RuntimeError("failed to restore paper rewrite side effects") from exc


def _paper_rewrite_draft_event_payload(
    *,
    payload: PaperReviewRewriteDraftRequest,
    candidate: dict[str, Any],
    record: PaperRecord,
    artifact_root: Path,
    writer: dict[str, Any],
    evidence_sync: dict[str, Any],
) -> dict[str, Any]:
    return {
        "action": "rewrite_draft",
        "requested_by": payload.requested_by,
        "force": payload.force,
        "artifact_root": str(artifact_root),
        "writer": writer,
        "evidence_sync": evidence_sync,
        "publication_policy": candidate["publication_policy"],
        "paper_paths": {
            "draft_markdown_path": record.draft_markdown_path,
            "draft_latex_path": record.draft_latex_path,
            "evidence_bundle_path": record.evidence_bundle_path,
            "claim_ledger_path": record.claim_ledger_path,
            "manifest_path": record.manifest_path,
        },
    }


def _write_paper_rewrite_draft_and_finalize(
    store: ControlPlaneStore,
    config: GateConfig,
    *,
    payload: PaperReviewRewriteDraftRequest,
    candidate: dict[str, Any],
    record: PaperRecord,
    artifact_root: Path,
    use_current_dir: bool,
    project_id: str,
    evidence_sync: dict[str, Any],
    draft_event_committed: dict[str, bool],
) -> dict[str, Any]:
    writer = write_paper_artifacts(config, candidate, record, force=payload.force)
    if not use_current_dir:
        store.update_project_dir(project_id, str(artifact_root))
    store.upsert_paper(record)
    event_id, inserted = store.append_event(
        idempotency_key=payload.idempotency_key,
        event_type=PAPER_REVIEW_DRAFT_REWRITTEN,
        entity_type="paper_review",
        entity_id=record.paper_id,
        payload=_paper_rewrite_draft_event_payload(
            payload=payload,
            candidate=candidate,
            record=record,
            artifact_root=artifact_root,
            writer=writer,
            evidence_sync=evidence_sync,
        ),
    )
    draft_event_committed["committed"] = True
    (
        finalization_event_id,
        finalization_inserted,
        finalized_item,
        package_path,
        _manifest,
    ) = store.prepare_paper_review_finalization_package(
        record.paper_id,
        PaperReviewPrepareFinalizationRequest(
            idempotency_key=f"{payload.idempotency_key}:automated-finalization",
            requested_by=payload.requested_by,
            target_label="automated-publication",
            dry_run=False,
        ),
        require_approval=False,
    )
    return {
        "writer": writer,
        "event_id": event_id,
        "inserted": inserted,
        "finalization_event_id": finalization_event_id,
        "finalization_inserted": finalization_inserted,
        "finalized_item": finalized_item,
        "package_path": package_path,
    }


def _handle_paper_rewrite_draft_commit_error(
    exc: BaseException,
    *,
    draft_event_committed: bool,
    store: ControlPlaneStore,
    artifact_snapshots: Mapping[Path, tuple[bool, bytes]],
    original_record: PaperRecord,
    original_project_dir: str,
    project_id: str,
) -> None:
    if not draft_event_committed:
        _restore_paper_rewrite_side_effects(
            store,
            artifact_snapshots=artifact_snapshots,
            original_record=original_record,
            original_project_dir=original_project_dir,
            project_id=project_id,
        )
    raise exc


def _paper_rewrite_draft_response_from_commit(
    store: ControlPlaneStore,
    *,
    record: PaperRecord,
    artifact_root: Path,
    evidence_sync: dict[str, Any],
    item: dict[str, Any],
    commit: Mapping[str, Any],
) -> PaperReviewRewriteDraftResponse:
    refreshed = (
        store.paper_review_row(record.paper_id, include_rank_reasons=True)
        or commit["finalized_item"]
        or item
    )
    writer_with_sync = {
        **commit["writer"],
        "evidence_sync": evidence_sync,
        "automated_finalization": {
            "inserted_event": commit["finalization_inserted"],
            "event_id": commit["finalization_event_id"],
            "package_path": commit["package_path"],
            "review_status": str((refreshed or {}).get("review_status") or ""),
        },
    }
    return PaperReviewRewriteDraftResponse(
        inserted_event=commit["inserted"],
        event_id=commit["event_id"],
        item=refreshed,
        paper=store.paper_row(record.paper_id),
        writer=writer_with_sync,
        artifact_root=str(artifact_root),
    )


def _commit_paper_rewrite_draft(
    store: ControlPlaneStore,
    config: GateConfig,
    *,
    payload: PaperReviewRewriteDraftRequest,
    candidate: dict[str, Any],
    record: PaperRecord,
    artifact_root: Path,
    use_current_dir: bool,
    project_id: str,
    evidence_sync: dict[str, Any],
    artifact_snapshots: dict[Path, tuple[bool, bytes]],
    original_record: PaperRecord,
    original_project_dir: str,
    item: dict[str, Any],
) -> PaperReviewRewriteDraftResponse:
    draft_event_committed = {"committed": False}
    try:
        commit = _write_paper_rewrite_draft_and_finalize(
            store,
            config,
            payload=payload,
            candidate=candidate,
            record=record,
            artifact_root=artifact_root,
            use_current_dir=use_current_dir,
            project_id=project_id,
            evidence_sync=evidence_sync,
            draft_event_committed=draft_event_committed,
        )
    except Exception as exc:
        _handle_paper_rewrite_draft_commit_error(
            exc,
            draft_event_committed=draft_event_committed["committed"],
            store=store,
            artifact_snapshots=artifact_snapshots,
            original_record=original_record,
            original_project_dir=original_project_dir,
            project_id=project_id,
        )
    return _paper_rewrite_draft_response_from_commit(
        store,
        record=record,
        artifact_root=artifact_root,
        evidence_sync=evidence_sync,
        item=item,
        commit=commit,
    )


def _stop_process(proc: subprocess.Popen | None) -> None:
    if proc is None:
        return
    if proc.poll() is None:
        proc.kill()
    try:
        proc.wait(timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        pass


def _restore_fd_blocking(fd: int, previous_blocking: bool | None) -> None:
    if previous_blocking is None:
        return
    try:
        os.set_blocking(fd, previous_blocking)
    except OSError:
        pass


def _read_bounded_fd_chunk(fd: int, *, max_bytes: int, total: int) -> bytes | None:
    try:
        return os.read(fd, min(1024 * 1024, max_bytes - total + 1))
    except BlockingIOError:
        return None


def _read_stdout_chunk_after_select(
    fd: int,
    proc: subprocess.Popen,
    *,
    ready: bool,
    max_bytes: int,
    total: int,
) -> tuple[bytes | None, bool]:
    if not ready:
        if proc.poll() is None:
            return None, True
        chunk = _read_bounded_fd_chunk(fd, max_bytes=max_bytes, total=total)
        return (b"", False) if chunk is None else (chunk, False)
    chunk = _read_bounded_fd_chunk(fd, max_bytes=max_bytes, total=total)
    if chunk is None:
        return None, True
    return chunk, False


def _read_process_stdout_bounded(
    proc: subprocess.Popen,
    *,
    command: list[str],
    timeout_sec: int,
    max_bytes: int,
) -> tuple[bytes, bool]:
    stdout = getattr(proc, "stdout", None)
    if stdout is None:
        return b"", False
    fd = stdout.fileno()
    chunks: list[bytes] = []
    total = 0
    deadline = time.monotonic() + max(1, int(timeout_sec))
    previous_blocking: bool | None = None
    try:
        previous_blocking = os.get_blocking(fd)
        os.set_blocking(fd, False)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(command, timeout_sec)
            ready, _, _ = select.select([fd], [], [], min(remaining, 0.25))
            chunk, should_continue = _read_stdout_chunk_after_select(
                fd,
                proc,
                ready=bool(ready),
                max_bytes=max_bytes,
                total=total,
            )
            if should_continue:
                continue
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                return b"".join(chunks), True
            chunks.append(chunk)
    finally:
        _restore_fd_blocking(fd, previous_blocking)
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise subprocess.TimeoutExpired(command, timeout_sec)
    proc.wait(timeout=min(5, remaining))
    return b"".join(chunks), False


def _remote_evidence_tar_include_paths() -> list[str]:
    return [
        _RUN_NOTES_MD,
        ".enoch/project_decision.json",
        ".enoch/metrics.json",
        ".omx/project_decision.json",
        ".omx/metrics.json",
        "results",
        "papers",
    ]


def _build_remote_evidence_ssh_cmd(config: GateConfig, remote_dir: str) -> list[str]:
    remote_cmd = (
        "cd "
        + shlex.quote(remote_dir)
        + " && tar -czf - --ignore-failed-read --exclude=__pycache__ --exclude='*.pyc' "
        + " ".join(shlex.quote(path) for path in _remote_evidence_tar_include_paths())
    )
    known_hosts = (config.expanded_state_dir / "ssh_known_hosts").expanduser()
    return [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=8",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        f"UserKnownHostsFile={known_hosts}",
        config.paper_evidence_sync_ssh_host,
        remote_cmd,
    ]


def _remote_evidence_tar_too_large_result(
    artifact_root: Path,
    http_sync: dict[str, Any],
    *,
    remote_dir: str,
    max_tar_bytes: int,
) -> dict[str, Any]:
    local_present = _local_paper_evidence_present(artifact_root)
    return {
        "enabled": True,
        "synced": local_present,
        "local_evidence_present": local_present,
        "reason": "remote_tar_too_large",
        "remote_dir": remote_dir,
        "error": f"remote evidence tar exceeded {max_tar_bytes} bytes",
        "http_sync": http_sync,
        "method": _EVIDENCE_SYNC_METHOD_WORKER_HTTP_SSH,
    }


def _read_remote_evidence_ssh_tar(
    config: GateConfig,
    ssh_cmd: list[str],
    *,
    artifact_root: Path,
    remote_dir: str,
    http_sync: dict[str, Any],
) -> tuple[bytes, bytes, int] | dict[str, Any]:
    max_tar_bytes = int(
        getattr(config, "paper_evidence_sync_max_tar_bytes", 96_000_000) or 96_000_000
    )
    ssh_proc: subprocess.Popen | None = None
    ssh_stderr_file: Any | None = None
    try:
        ssh_stderr_file = tempfile.TemporaryFile()
        ssh_proc = subprocess.Popen(
            ssh_cmd, stdout=subprocess.PIPE, stderr=ssh_stderr_file
        )
        ssh_stdout = getattr(ssh_proc, "stdout", None)
        if ssh_stdout is None or isinstance(ssh_stdout, io.BytesIO):
            ssh_out, ssh_err = ssh_proc.communicate(
                timeout=config.paper_evidence_sync_timeout_sec
            )
            if len(ssh_out or b"") > max_tar_bytes:
                _stop_process(ssh_proc)
                return _remote_evidence_tar_too_large_result(
                    artifact_root,
                    http_sync,
                    remote_dir=remote_dir,
                    max_tar_bytes=max_tar_bytes,
                )
            return ssh_out or b"", ssh_err or b"", int(ssh_proc.returncode or 0)
        ssh_out, too_large = _read_process_stdout_bounded(
            ssh_proc,
            command=ssh_cmd,
            timeout_sec=int(config.paper_evidence_sync_timeout_sec),
            max_bytes=max_tar_bytes,
        )
        if too_large:
            _stop_process(ssh_proc)
            return _remote_evidence_tar_too_large_result(
                artifact_root,
                http_sync,
                remote_dir=remote_dir,
                max_tar_bytes=max_tar_bytes,
            )
        ssh_stderr_file.seek(0)
        return (
            ssh_out,
            ssh_stderr_file.read(),
            int(ssh_proc.returncode or 0),
        )
    except subprocess.TimeoutExpired as exc:
        _stop_process(ssh_proc)
        return {
            "enabled": True,
            "synced": _local_paper_evidence_present(artifact_root),
            "reason": "timeout",
            "remote_dir": remote_dir,
            "error": str(exc),
            "http_sync": http_sync,
            "method": _EVIDENCE_SYNC_METHOD_WORKER_HTTP_SSH,
        }
    except OSError as exc:
        _stop_process(ssh_proc)
        return {
            "enabled": True,
            "synced": _local_paper_evidence_present(artifact_root),
            "reason": "spawn_failed",
            "remote_dir": remote_dir,
            "error": str(exc),
            "http_sync": http_sync,
            "method": _EVIDENCE_SYNC_METHOD_WORKER_HTTP_SSH,
        }
    finally:
        if ssh_stderr_file is not None:
            ssh_stderr_file.close()


def _finalize_remote_evidence_ssh_sync(
    artifact_root: Path,
    http_sync: dict[str, Any],
    *,
    remote_dir: str,
    ssh_out: bytes,
    ssh_err: bytes,
    ssh_code: int,
) -> dict[str, Any]:
    if ssh_code != 0:
        return {
            "enabled": True,
            "synced": _local_paper_evidence_present(artifact_root),
            "reason": "command_failed",
            "remote_dir": remote_dir,
            "ssh_returncode": ssh_code,
            "stderr": (ssh_err or b"").decode("utf-8", errors="replace")[-2000:],
            "stdout": (ssh_out or b"").decode("utf-8", errors="replace")[-1000:],
            "http_sync": http_sync,
            "method": _EVIDENCE_SYNC_METHOD_WORKER_HTTP_SSH,
        }
    extract_result = _extract_safe_tar_bytes(ssh_out or b"", artifact_root)
    if not extract_result.get("ok"):
        local_present = _local_paper_evidence_present(artifact_root)
        return {
            "enabled": True,
            "synced": local_present,
            "local_evidence_present": local_present,
            "reason": str(extract_result.get("reason") or "extract_failed"),
            "remote_dir": remote_dir,
            "extract": extract_result,
            "http_sync": http_sync,
            "method": _EVIDENCE_SYNC_METHOD_WORKER_HTTP_SSH,
        }
    local_evidence_present = _local_paper_evidence_present(artifact_root)
    return {
        "enabled": True,
        "synced": local_evidence_present,
        "reason": "synced"
        if local_evidence_present
        else "synced_without_required_evidence",
        "method": _EVIDENCE_SYNC_METHOD_WORKER_HTTP_SSH,
        "remote_dir": remote_dir,
        "local_evidence_present": local_evidence_present,
        "http_sync": http_sync,
    }


def _sync_remote_project_evidence_ssh_fallback(
    config: GateConfig,
    *,
    project_id: str,
    artifact_root: Path,
    source_project_dir: str,
    http_sync: dict[str, Any],
) -> dict[str, Any]:
    remote_dir = _remote_evidence_dir(
        config, project_id=project_id, source_project_dir=source_project_dir
    )
    # The VM talks to the GB10 over SSH and streams a bounded evidence tarball.
    # This intentionally excludes external source trees and large trace/log files,
    # while preserving the artifacts the paper writer needs for claim grounding.
    ssh_cmd = _build_remote_evidence_ssh_cmd(config, remote_dir)
    try:
        artifact_root.mkdir(parents=True, exist_ok=True)
        if not artifact_root.is_dir():
            raise NotADirectoryError(str(artifact_root))
    except (OSError, RuntimeError, ValueError) as exc:
        local_present = _local_paper_evidence_present(artifact_root)
        return {
            "enabled": True,
            "synced": local_present,
            "local_evidence_present": local_present,
            "reason": "artifact_root_unusable",
            "remote_dir": remote_dir,
            "error": f"{type(exc).__name__}: {exc}",
            "http_sync": http_sync,
            "method": _EVIDENCE_SYNC_METHOD_WORKER_HTTP_SSH,
        }
    known_hosts = (config.expanded_state_dir / "ssh_known_hosts").expanduser()
    known_hosts.parent.mkdir(parents=True, exist_ok=True)
    ssh_payload = _read_remote_evidence_ssh_tar(
        config,
        ssh_cmd,
        artifact_root=artifact_root,
        remote_dir=remote_dir,
        http_sync=http_sync,
    )
    if isinstance(ssh_payload, dict):
        return ssh_payload
    ssh_out, ssh_err, ssh_code = ssh_payload
    return _finalize_remote_evidence_ssh_sync(
        artifact_root,
        http_sync,
        remote_dir=remote_dir,
        ssh_out=ssh_out,
        ssh_err=ssh_err,
        ssh_code=ssh_code,
    )


def _sync_remote_project_evidence(
    config: GateConfig,
    *,
    project_id: str,
    artifact_root: Path,
    source_project_dir: str = "",
    source_run_id: str = "",
    worker_wake_gate_url: str | None = None,
    worker_bearer_token: str | None = None,
    allow_ssh_fallback: bool = True,
) -> dict[str, Any]:
    if not config.paper_evidence_sync_enabled:
        return {"enabled": False, "synced": False, "reason": "disabled"}
    http_sync = _sync_worker_http_evidence(
        config,
        project_id=project_id,
        artifact_root=artifact_root,
        source_run_id=source_run_id,
        worker_wake_gate_url=worker_wake_gate_url,
        worker_bearer_token=worker_bearer_token,
    )
    if http_sync.get("ok") and _local_paper_evidence_present(artifact_root):
        return {
            "enabled": True,
            "synced": True,
            "reason": str(http_sync.get("reason") or "worker_http_synced"),
            "method": "worker_http",
            "local_evidence_present": True,
            "http_sync": http_sync,
        }
    if not allow_ssh_fallback:
        local_present = _local_paper_evidence_present(artifact_root)
        return {
            "enabled": True,
            "synced": local_present,
            "local_evidence_present": local_present,
            "reason": "worker_http_no_required_evidence",
            "method": "worker_http",
            "http_sync": http_sync,
        }
    return _sync_remote_project_evidence_ssh_fallback(
        config,
        project_id=project_id,
        artifact_root=artifact_root,
        source_project_dir=source_project_dir,
        http_sync=http_sync,
    )


def _safe_slug(value: str, fallback: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip()).strip("-._").lower()
    return (slug or fallback)[:96]


def _validate_research_candidate_id(candidate_id: str) -> str:
    value = str(candidate_id or "").strip()
    if not value:
        raise HTTPException(status_code=400, detail="candidate_id is required")
    if len(value) > 160 or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]*", value):
        raise HTTPException(
            status_code=400,
            detail="candidate_id must be a bounded slug-like identifier",
        )
    return value


def _live_run_id(project_id: str) -> str:
    stamp = (
        utc_now()
        .replace("-", "")
        .replace(":", "")
        .replace(".", "")
        .replace("+00:00", "Z")
    )
    return f"{project_id}-{stamp}"


def _assert_live_dispatch_preconditions(
    *,
    config: GateConfig,
    store: ControlPlaneStore,
    require_writable_store: Callable[[str], None],
    allow_paused: bool,
) -> None:
    if not config.live_dispatch_enabled:
        raise HTTPException(
            status_code=501,
            detail="live dispatch is disabled by config.live_dispatch_enabled",
        )
    require_writable_store("live dispatch")
    flags = store.flags()
    if flags.maintenance_mode:
        raise HTTPException(
            status_code=409,
            detail="control plane must be out of maintenance mode before live dispatch",
        )
    if flags.queue_paused and not allow_paused:
        raise HTTPException(
            status_code=409,
            detail="control plane must be resumed before live dispatch",
        )


def _live_dispatch_project_context(candidate: dict) -> tuple[str, str, str]:
    project_id = str(candidate.get("project_id") or "").strip()
    if not project_id:
        raise HTTPException(status_code=400, detail="candidate lacks project_id")
    project_dir = _safe_slug(
        str(candidate.get("project_dir") or project_id), project_id
    )
    return project_id, project_dir, _live_run_id(project_id)


def _resolved_worker_target_with_bearer(
    config: GateConfig,
    candidate: dict,
    *,
    release_claim: Callable[[], None] | None = None,
) -> Any:
    worker_target = config.resolved_worker_target(
        str(candidate.get("machine_target") or "")
    )
    if worker_target.bearer_token:
        return worker_target
    if release_claim is not None:
        release_claim()
    raise HTTPException(
        status_code=500,
        detail=(
            "worker bearer token is not configured for "
            f"machine_target={candidate.get('machine_target') or 'default'}"
        ),
    )


def _claim_live_dispatch_candidate(
    store: ControlPlaneStore,
    *,
    project_id: str,
    run_id: str,
    requested_by: str,
    conflicting_machine_targets: set[str],
) -> dict:
    claim_kwargs = {
        "project_id": project_id,
        "run_id": run_id,
        "requested_by": requested_by,
        "conflicting_machine_targets": conflicting_machine_targets,
    }
    try:
        claim = store.claim_dispatch_candidate(**claim_kwargs)
    except TypeError as exc:
        if "conflicting_machine_targets" not in str(exc):
            raise
        claim_kwargs.pop("conflicting_machine_targets")
        claim = store.claim_dispatch_candidate(**claim_kwargs)
    if not claim:
        raise HTTPException(
            status_code=409,
            detail="dispatch candidate was already claimed or is no longer queued",
        )
    return claim


def _live_dispatch_preflight_min_memory_mib(worker_target: Any) -> int:
    if worker_target.min_memory_available_mib is not None:
        return int(worker_target.min_memory_available_mib)
    return int(WorkerPreflightRequest.model_fields["min_memory_available_mib"].default)


def _run_live_dispatch_preflight(
    *,
    worker_target: Any,
    store: ControlPlaneStore,
    project_id: str,
    run_id: str,
    force_preflight: bool,
    callback_acceptance_token_fingerprint: Callable[[], str],
    record_preflight_observations: Callable[[WorkerPreflightResponse], None],
) -> WorkerPreflightResponse:
    try:
        preflight = run_worker_preflight(
            WorkerPreflightRequest(
                wake_gate_url=worker_target.wake_gate_url,
                bearer_token=worker_target.bearer_token,
                expected_callback_token_fingerprint=callback_acceptance_token_fingerprint(),
                require_paused=False,
                strict=False,
                min_memory_available_mib=_live_dispatch_preflight_min_memory_mib(
                    worker_target
                ),
            ),
            store.flags(),
        )
    except Exception as exc:
        reason = f"{WORKER_PREFLIGHT_FAILED_REASON}: {type(exc).__name__}: {exc}"
        store.release_dispatch_claim(
            project_id=project_id, run_id=run_id, reason=reason
        )
        raise HTTPException(
            status_code=409,
            detail={
                "message": WORKER_PREFLIGHT_FAILED_REASON,
                "preflight_error": reason,
                "force_preflight_ignored": not force_preflight,
            },
        ) from exc
    record_preflight_observations(preflight)
    if preflight.ok:
        return preflight
    store.release_dispatch_claim(
        project_id=project_id,
        run_id=run_id,
        reason=WORKER_PREFLIGHT_FAILED_REASON,
    )
    raise HTTPException(
        status_code=409,
        detail={
            "message": WORKER_PREFLIGHT_FAILED_REASON,
            "preflight": preflight.model_dump(mode="json"),
            "force_preflight_ignored": not force_preflight,
        },
    )


def _live_dispatch_prepare_payload(
    *,
    run_id: str,
    project_id: str,
    project_dir: str,
    candidate: dict,
    requested_by: str,
    config: GateConfig,
    worker_target: Any,
    dispatch_route_metadata: Callable[[str, Any], dict[str, Any]],
) -> dict[str, Any]:
    prompt_file = f"{project_dir}/prompts/initial.md"
    resume_prompt_file = f"{project_dir}/prompts/resume.md"
    workload_class = config.workload_class_for_machine_target(
        str(candidate.get("machine_target") or ""),
        str(candidate.get("workload_class") or ""),
    )
    machine_target = str(candidate.get("machine_target") or "")
    return {
        "run_id": run_id,
        "project_id": project_id,
        "project_name": str(candidate.get("project_name") or project_id),
        "notion_page_url": str(candidate.get("notion_page_url") or ""),
        "project_dir": project_dir,
        "prompt_file": prompt_file,
        "prompt_text": _project_prompt(candidate),
        "resume_prompt_file": resume_prompt_file,
        "resume_prompt_text": _project_prompt(candidate)
        + "\n\nResume from the existing project artifacts and continue to a verified decision.\n",
        "metadata": {
            "workload_class": workload_class,
            "machine_target": machine_target,
            "dispatch_route": dispatch_route_metadata(machine_target, worker_target),
            "source": "langgraph_control_plane",
            "requested_by": requested_by,
        },
        "overwrite": True,
    }


def _post_live_dispatch_prepare(
    *,
    worker_target: Any,
    store: ControlPlaneStore,
    project_id: str,
    run_id: str,
    prepare_payload: dict[str, Any],
) -> dict[str, Any]:
    prepare = post_worker_json(
        worker_target.wake_gate_url,
        "/prepare-project",
        worker_target.bearer_token,
        prepare_payload,
    )
    if prepare.ok:
        return prepare.body if isinstance(prepare.body, dict) else {}
    store.release_dispatch_claim(
        project_id=project_id,
        run_id=run_id,
        reason="worker prepare-project failed",
    )
    raise HTTPException(
        status_code=502,
        detail={
            "message": "worker prepare-project failed",
            "status": prepare.status,
            "error": prepare.error,
            "body": prepare.body,
        },
    )


def _dispatch_session_id_from_body(body: dict[str, Any]) -> str:
    dispatch_body = body.get("dispatch")
    if not isinstance(dispatch_body, dict):
        dispatch_body = {}
    return str(dispatch_body.get("session_id") or "")


def _post_live_dispatch_run(
    *,
    worker_target: Any,
    store: ControlPlaneStore,
    project_id: str,
    run_id: str,
    project_dir: str,
    candidate: dict,
) -> tuple[dict[str, Any], str]:
    prompt_file = f"{project_dir}/prompts/initial.md"
    dispatch_payload = {
        "run_id": run_id,
        "project_id": project_id,
        "project_dir": project_dir,
        "prompt_file": prompt_file,
        "mode": "exec",
        "model": str(candidate.get("model") or _DEFAULT_RESEARCH_MODEL),
        "reasoning_effort": "medium",
        "sandbox": str(candidate.get("sandbox") or "danger-full-access"),
    }
    dispatch = post_worker_json(
        worker_target.wake_gate_url,
        "/dispatch",
        worker_target.bearer_token,
        dispatch_payload,
    )
    if not dispatch.ok:
        store.release_dispatch_claim(
            project_id=project_id, run_id=run_id, reason="worker dispatch failed"
        )
        raise HTTPException(
            status_code=502,
            detail={
                "message": "worker dispatch failed",
                "status": dispatch.status,
                "error": dispatch.error,
                "body": dispatch.body,
            },
        )
    body = dispatch.body if isinstance(dispatch.body, dict) else {}
    return body, _dispatch_session_id_from_body(body)


def _execute_live_dispatch(
    candidate: dict,
    requested_by: str,
    force_preflight: bool,
    *,
    allow_paused: bool = False,
    config: GateConfig,
    store: ControlPlaneStore,
    require_writable_store: Callable[[str], None],
    candidate_machine_target_conflict_set: Callable[[dict[str, Any]], set[str]],
    callback_acceptance_token_fingerprint: Callable[[], str],
    record_preflight_observations: Callable[[WorkerPreflightResponse], None],
    dispatch_route_metadata: Callable[[str, Any], dict[str, Any]],
) -> tuple[dict, int | None, dict]:
    operator_trace = OperatorTrace.from_config(config)
    trace_id = OperatorTrace.new_trace_id("dispatch")
    _assert_live_dispatch_preconditions(
        config=config,
        store=store,
        require_writable_store=require_writable_store,
        allow_paused=allow_paused,
    )
    project_id, project_dir, run_id = _live_dispatch_project_context(candidate)
    operator_trace.record(
        "dispatch.live.attempt",
        trace_id=trace_id,
        requested_by=requested_by,
        project_id=project_id,
        run_id=run_id,
        machine_target=str(candidate.get("machine_target") or ""),
        force_preflight=force_preflight,
        allow_paused=allow_paused,
    )
    _resolved_worker_target_with_bearer(config, candidate)
    candidate = _claim_live_dispatch_candidate(
        store,
        project_id=project_id,
        run_id=run_id,
        requested_by=requested_by,
        conflicting_machine_targets=candidate_machine_target_conflict_set(candidate),
    )

    def _release_for_missing_token() -> None:
        store.release_dispatch_claim(
            project_id=project_id,
            run_id=run_id,
            reason="worker bearer token missing for routed target",
        )

    worker_target = _resolved_worker_target_with_bearer(
        config, candidate, release_claim=_release_for_missing_token
    )
    try:
        preflight = _run_live_dispatch_preflight(
            worker_target=worker_target,
            store=store,
            project_id=project_id,
            run_id=run_id,
            force_preflight=force_preflight,
            callback_acceptance_token_fingerprint=callback_acceptance_token_fingerprint,
            record_preflight_observations=record_preflight_observations,
        )
    except HTTPException as exc:
        operator_trace.record(
            "dispatch.preflight.result",
            trace_id=trace_id,
            requested_by=requested_by,
            project_id=project_id,
            run_id=run_id,
            machine_target=str(candidate.get("machine_target") or ""),
            lane_key=getattr(worker_target, "wake_gate_url", ""),
            ok=False,
            status_code=exc.status_code,
            detail=exc.detail,
        )
        raise
    operator_trace.record(
        "dispatch.preflight.result",
        trace_id=trace_id,
        requested_by=requested_by,
        project_id=project_id,
        run_id=run_id,
        machine_target=str(candidate.get("machine_target") or ""),
        lane_key=getattr(worker_target, "wake_gate_url", ""),
        ok=preflight.ok,
        summary=preflight.summary,
        failed_checks=[check.name for check in preflight.checks if not check.ok],
    )
    prepare_payload = _live_dispatch_prepare_payload(
        run_id=run_id,
        project_id=project_id,
        project_dir=project_dir,
        candidate=candidate,
        requested_by=requested_by,
        config=config,
        worker_target=worker_target,
        dispatch_route_metadata=dispatch_route_metadata,
    )
    prepare_body = _post_live_dispatch_prepare(
        worker_target=worker_target,
        store=store,
        project_id=project_id,
        run_id=run_id,
        prepare_payload=prepare_payload,
    )
    dispatch_body, session_id = _post_live_dispatch_run(
        worker_target=worker_target,
        store=store,
        project_id=project_id,
        run_id=run_id,
        project_dir=project_dir,
        candidate=candidate,
    )
    store.update_project_dir(project_id, project_dir)
    event_id, updated_candidate = store.mark_dispatch_started(
        project_id=project_id,
        run_id=run_id,
        session_id=session_id,
        dispatch_payload=dispatch_body,
        requested_by=requested_by,
    )
    operator_trace.record(
        "dispatch.live.result",
        trace_id=trace_id,
        requested_by=requested_by,
        project_id=project_id,
        run_id=run_id,
        machine_target=str(
            updated_candidate.get("machine_target")
            or candidate.get("machine_target")
            or ""
        ),
        lane_key=getattr(worker_target, "wake_gate_url", ""),
        event_id=event_id,
        session_id=session_id,
    )
    machine_target = str(candidate.get("machine_target") or "")
    prompt_file = f"{project_dir}/prompts/initial.md"
    return (
        {
            "run_id": run_id,
            "project_id": project_id,
            "project_dir": project_dir,
            "prompt_file": prompt_file,
            "prepare": prepare_body,
            "dispatch": dispatch_body,
            "preflight": preflight.model_dump(mode="json"),
            "dispatch_route": dispatch_route_metadata(machine_target, worker_target),
        },
        event_id,
        updated_candidate,
    )


def _parse_ts(value: str | None) -> datetime | None:
    return parse_utc_datetime(value)


def _fresh_until(observed_at: str | None, ttl_seconds: int | None) -> str | None:
    observed = _parse_ts(observed_at)
    if observed is None or ttl_seconds is None:
        return None
    return (observed + timedelta(seconds=ttl_seconds)).isoformat()


def _is_stale(observed_at: str | None, ttl_seconds: int | None) -> bool:
    observed = _parse_ts(observed_at)
    if observed is None or ttl_seconds is None:
        return True
    return datetime.now(timezone.utc) > observed + timedelta(seconds=ttl_seconds)


def _fresh_observation(
    observation: DashboardObservationRecord | None,
) -> DashboardObservationRecord | None:
    if observation is None:
        return None
    if _is_stale(observation.observed_at, observation.ttl_seconds):
        return None
    return observation


def _preflight_check(
    preflight: DashboardObservationRecord | None, name: str
) -> dict | None:
    checks = (preflight.payload if preflight else {}).get("checks") or []
    for check in checks:
        if isinstance(check, dict) and check.get("name") == name:
            return check
    return None


def _worker_dashboard_body_from_preflight(
    preflight: DashboardObservationRecord | None,
) -> dict[str, Any]:
    dashboard = _preflight_check(preflight, "wake_gate_dashboard_api") or {}
    data = dashboard.get("data") if isinstance(dashboard, dict) else {}
    body = data.get("body") if isinstance(data, dict) else {}
    return body if isinstance(body, dict) else {}


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


WORKER_SETTLING_RECENT_GRACE_SEC = 180
ACTIVE_LANE_CONFIRMATION_GRACE_SEC = 180


def _worker_run_is_settling_without_process(run: dict[str, Any]) -> bool:
    active_process_count = _int_or_none(run.get("active_process_count"))
    if active_process_count != 0:
        return False
    gate_state = _normal_status(run.get("gate_state"))
    lifecycle_state = _normal_status(run.get("lifecycle_state"))
    return gate_state == "waiting_for_quiet_window" or lifecycle_state == "settling"


def _worker_run_updated_recently(
    run: dict[str, Any], *, grace_seconds: int = WORKER_SETTLING_RECENT_GRACE_SEC
) -> bool:
    observed = _parse_ts(
        str(
            run.get("updated_at")
            or run.get("last_seen_at")
            or run.get("created_at")
            or ""
        )
        or None
    )
    if observed is None:
        return False
    now = datetime.now(timezone.utc)
    grace = timedelta(seconds=max(1, grace_seconds))
    if observed > now + grace:
        return False
    return now <= observed + grace


def _worker_no_live_failed_check(
    preflight: DashboardObservationRecord | None,
) -> dict[str, Any] | None:
    no_live = _preflight_check(preflight, "worker_no_live_runs")
    if not no_live or no_live.get("ok") is not False:
        return None
    return no_live


def _preflight_observed_recently(
    preflight: DashboardObservationRecord | None,
    *,
    grace_seconds: int = ACTIVE_LANE_CONFIRMATION_GRACE_SEC,
) -> bool:
    observed = _parse_ts(preflight.observed_at if preflight else None)
    if observed is None:
        return False
    now = datetime.now(timezone.utc)
    grace = timedelta(seconds=max(1, grace_seconds))
    if observed > now + grace:
        return False
    return now <= observed + grace


def _queue_row_recent_callback(
    row: dict[str, Any],
    *,
    grace_seconds: int = ACTIVE_LANE_CONFIRMATION_GRACE_SEC,
) -> bool:
    observed = _parse_ts(str(row.get("last_callback_at") or "") or None)
    if observed is None:
        return False
    now = datetime.now(timezone.utc)
    grace = timedelta(seconds=max(1, grace_seconds))
    if observed > now + grace:
        return False
    return now <= observed + grace


def _preflight_predates_active_dispatch(
    preflight: DashboardObservationRecord | None, row: dict[str, Any]
) -> bool:
    preflight_observed = _parse_ts(preflight.observed_at if preflight else None)
    dispatch_observed = _parse_ts(str(row.get("last_dispatch_at") or "") or None)
    if preflight_observed is None or dispatch_observed is None:
        return False
    return preflight_observed < dispatch_observed


def _worker_dashboard_runs_from_preflight(
    preflight: DashboardObservationRecord | None,
) -> list[dict[str, Any]]:
    runs = _worker_dashboard_body_from_preflight(preflight).get("runs")
    if not isinstance(runs, list):
        return []
    return [run for run in runs if isinstance(run, dict)]


def _worker_run_matches_queue_row(run: dict[str, Any], row: dict[str, Any]) -> bool:
    row_run_id = str(row.get("current_run_id") or "").strip()
    row_project_id = str(row.get("project_id") or "").strip()
    run_run_id = str(run.get("run_id") or "").strip()
    run_project_id = str(run.get("project_id") or "").strip()
    if row_run_id and run_run_id and row_run_id == run_run_id:
        return True
    return bool(row_project_id and run_project_id and row_project_id == run_project_id)


def _worker_run_is_live_marker(run: dict[str, Any]) -> bool:
    active_process_count = _int_or_none(run.get("active_process_count"))
    if active_process_count is not None and active_process_count > 0:
        return True
    if run.get("is_live") is True:
        return True
    gate_state = _normal_status(run.get("gate_state"))
    lifecycle_state = _normal_status(run.get("lifecycle_state"))
    return gate_state in ACTIVE_STATUSES or lifecycle_state in ACTIVE_STATUSES


def _active_confirmation_for_no_live_check(
    *,
    preflight: DashboardObservationRecord,
    active_row: dict[str, Any],
    no_live: dict[str, Any],
) -> dict[str, Any]:
    if _preflight_observed_recently(preflight) or _queue_row_recent_callback(
        active_row
    ):
        return {
            "state": "active_unconfirmed_grace",
            "matched": False,
            "reason": "worker reports no live run, but observation/callback is within reconcile grace",
            "worker_check": no_live,
        }
    return {
        "state": "stale_active",
        "matched": False,
        "reason": "worker reports no live run for active control-plane row",
        "worker_check": no_live,
    }


def _matched_worker_run_confirmation(run: dict[str, Any]) -> dict[str, Any]:
    return {
        "state": "active_confirmed"
        if _worker_run_is_live_marker(run)
        else "active_unconfirmed",
        "matched": True,
        "matched_run_id": str(run.get("run_id") or ""),
        "matched_project_id": str(run.get("project_id") or ""),
        "active_process_count": _int_or_none(run.get("active_process_count")),
        "reason": "matched worker run/session marker",
    }


def _unmatched_worker_run_confirmation(
    *,
    preflight: DashboardObservationRecord,
    active_row: dict[str, Any],
    no_live: dict[str, Any] | None,
) -> dict[str, Any]:
    if no_live and no_live.get("ok") is True:
        if _preflight_predates_active_dispatch(preflight, active_row):
            return {
                "state": "preflight_stale_after_dispatch",
                "matched": False,
                "reason": "worker preflight observation predates active control-plane dispatch",
                "observed_at": preflight.observed_at,
                "last_dispatch_at": str(active_row.get("last_dispatch_at") or ""),
                "suggested_action": (
                    "refresh lane preflight before treating this active row as stale"
                ),
                "worker_check": no_live,
            }
        return _active_confirmation_for_no_live_check(
            preflight=preflight, active_row=active_row, no_live=no_live
        )
    return {
        "state": "active_unconfirmed",
        "matched": False,
        "reason": "worker preflight did not include a matching live run marker",
        "worker_check": no_live,
    }


def _active_lane_worker_confirmation(
    *,
    preflight: DashboardObservationRecord | None,
    preflight_lane_key: str,
    lane_key: str,
    active_row: dict[str, Any] | None,
) -> dict[str, Any]:
    if not active_row:
        return {"state": "idle", "matched": False}
    if preflight is None:
        return {
            "state": "unknown",
            "matched": False,
            "reason": "no worker preflight observation",
        }
    if preflight_lane_key and preflight_lane_key != lane_key:
        return {
            "state": "unknown",
            "matched": False,
            "reason": "preflight observation is for a different worker lane",
            "observed_lane_key": preflight_lane_key,
        }
    for run in _worker_dashboard_runs_from_preflight(preflight):
        if _worker_run_matches_queue_row(run, active_row):
            return _matched_worker_run_confirmation(run)
    no_live = _preflight_check(preflight, "worker_no_live_runs")
    return _unmatched_worker_run_confirmation(
        preflight=preflight, active_row=active_row, no_live=no_live
    )


def _terminal_run_states_for_worker_settling() -> set[str]:
    return set(TERMINAL_SUCCESS_CALLBACK_STATES) | {
        "completed",
        "complete",
        "finished",
    }


def _queue_row_completed_run_id(
    row: dict[str, Any],
    *,
    terminal_run_states: set[str],
) -> str | None:
    status = _normal_status(row.get("status"))
    if status in ACTIVE_STATUSES:
        return None
    last_run_state = _normal_status(row.get("last_run_state"))
    if status != "completed" and last_run_state not in terminal_run_states:
        return None
    run_id = str(row.get("current_run_id") or "").strip()
    return run_id or None


def _run_row_completed_run_id(
    row: dict[str, Any],
    *,
    terminal_run_states: set[str],
) -> str | None:
    state = _normal_status(row.get("state"))
    gate_state = _normal_status(row.get("gate_state"))
    if state not in terminal_run_states and gate_state not in terminal_run_states:
        return None
    run_id = str(row.get("run_id") or "").strip()
    return run_id or None


def _collect_completed_run_ids(
    *,
    queue_rows: list[dict[str, Any]],
    run_rows: list[dict[str, Any]],
    terminal_run_states: set[str],
) -> set[str]:
    completed_run_ids: set[str] = set()
    for row in queue_rows:
        run_id = _queue_row_completed_run_id(
            row, terminal_run_states=terminal_run_states
        )
        if run_id:
            completed_run_ids.add(run_id)

    for row in run_rows:
        run_id = _run_row_completed_run_id(row, terminal_run_states=terminal_run_states)
        if run_id:
            completed_run_ids.add(run_id)
    return completed_run_ids


def _worker_settling_match_for_completed_runs(
    *,
    preflight: DashboardObservationRecord | None,
    no_live: dict[str, Any],
    completed_run_ids: set[str],
) -> dict[str, Any] | None:
    body = _worker_dashboard_body_from_preflight(preflight)
    runs = body.get("runs")
    if not isinstance(runs, list):
        return None
    for run in runs:
        if not isinstance(run, dict):
            continue
        run_id = str(run.get("run_id") or "").strip()
        if run_id not in completed_run_ids:
            continue
        if not _worker_run_is_settling_without_process(run):
            continue
        return {
            "worker_run": run,
            "worker_check": no_live,
            "matched_run_id": run_id,
        }
    return None


def _recent_worker_settling_without_vm_match(
    *, preflight: DashboardObservationRecord | None
) -> dict[str, Any] | None:
    no_live = _worker_no_live_failed_check(preflight)
    if no_live is None:
        return None

    body = _worker_dashboard_body_from_preflight(preflight)
    runs = body.get("runs")
    if not isinstance(runs, list):
        return None
    for run in runs:
        if not isinstance(run, dict):
            continue
        if not _worker_run_is_settling_without_process(run):
            continue
        if not _worker_run_updated_recently(run):
            continue
        return {
            "worker_run": run,
            "worker_check": no_live,
            "matched_run_id": str(run.get("run_id") or "").strip(),
            "match_type": "recent_worker_settling_without_vm_active_row",
        }
    return None


def _worker_settling_after_vm_completion(
    *,
    preflight: DashboardObservationRecord | None,
    queue_rows: list[dict[str, Any]],
    run_rows: list[dict[str, Any]],
) -> dict[str, Any] | None:
    no_live = _worker_no_live_failed_check(preflight)
    if no_live is None:
        return None

    completed_run_ids = _collect_completed_run_ids(
        queue_rows=queue_rows,
        run_rows=run_rows,
        terminal_run_states=_terminal_run_states_for_worker_settling(),
    )
    if not completed_run_ids:
        return None

    return _worker_settling_match_for_completed_runs(
        preflight=preflight,
        no_live=no_live,
        completed_run_ids=completed_run_ids,
    )


def _truncate_text(value: Any, limit: int = 500) -> Any:
    if not isinstance(value, str) or len(value) <= limit:
        return value
    return f"{value[:limit]}…"


def _compact_list(values: Any, *, limit: int = 5) -> dict[str, Any]:
    if not isinstance(values, list):
        return {"count": 0, "items": []}
    return {
        "count": len(values),
        "items": values[:limit],
        "truncated": len(values) > limit,
    }


def _compact_project_decision(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    keys = (
        "project_decision",
        "hypothesis_status",
        "evidence_strength",
        "recommended_next_action",
        "stop_reason",
        "followup_recommended",
        "followup_count",
        "parent_project_id",
    )
    compact = {key: _truncate_text(value.get(key), 300) for key in keys if key in value}
    for key in ("key_findings", "next_steps", "followup_ideas"):
        if isinstance(value.get(key), list):
            compact[key] = _compact_list(
                [_truncate_text(item, 240) for item in value[key]], limit=3
            )
    return compact


def _compact_worker_run_item(run_item: Any) -> dict[str, Any]:
    """Keep worker runtime evidence useful without caching multi-100KB detail blobs.

    The GB10 dashboard can include long tails such as quiet_samples,
    run_notes_tail, project_decision narratives, and file listings.  Status and
    detail views need the identity/lifecycle/safety facts, not the full worker
    transcript.  Full worker evidence remains available from the worker host.
    """

    if not isinstance(run_item, dict):
        return {}
    scalar_keys = (
        "run_id",
        "project_id",
        "session_id",
        "gate_state",
        "is_live",
        "is_historical",
        "lifecycle_state",
        "needs_attention",
        "operator_status",
        "operator_status_detail",
        "current_activity",
        "created_at",
        "updated_at",
        "last_event_at",
        "callback_delivered",
        "active_process_count",
        "project_dir",
    )
    compact = {
        key: _truncate_text(run_item.get(key), 300)
        for key in scalar_keys
        if key in run_item
    }
    if "project_decision" in run_item:
        compact["project_decision"] = _compact_project_decision(
            run_item.get("project_decision")
        )
    if "decision_error" in run_item:
        compact["decision_error"] = _truncate_text(run_item.get("decision_error"), 500)
    for key in ("result_files", "recent_files", "active_processes"):
        if key in run_item:
            compact[key] = _compact_list(run_item.get(key), limit=5)
    for key in ("quiet_samples", "run_notes_tail", "stdout_tail", "stderr_tail"):
        if key in run_item:
            value = run_item.get(key)
            compact[f"{key}_omitted"] = True
            if isinstance(value, list):
                omitted_count = len(value)
            elif value:
                omitted_count = 1
            else:
                omitted_count = 0
            compact[f"{key}_count"] = omitted_count
    return compact


def _compact_worker_dashboard_body(body: Any) -> dict[str, Any]:
    if not isinstance(body, dict):
        return {}
    compact: dict[str, Any] = {}
    for key in ("ok", "timestamp", "totals", "telemetry"):
        if key in body:
            compact[key] = body.get(key)
    queue = body.get("queue")
    if isinstance(queue, dict):
        compact["queue"] = {
            key: queue.get(key)
            for key in (
                "total",
                "source",
                "updated_at",
                "active_count",
                "queued_count",
                "blocked_count",
                "branch_count",
                "negative_count",
                "positive_count",
                "completed_count",
                "draft_candidate_count",
                "polish_candidate_count",
                "status_counts",
                "run_state_counts",
            )
            if key in queue
        }
        if isinstance(queue.get("rows"), list):
            compact["queue"]["rows_omitted"] = True
            compact["queue"]["rows_count"] = len(queue["rows"])
    runs = body.get("runs")
    if isinstance(runs, list):
        compact["runs"] = [_compact_worker_run_item(run_item) for run_item in runs[:10]]
        compact["runs_count"] = len(runs)
        compact["runs_truncated"] = len(runs) > 10
    return compact


def _compact_worker_dashboard_check_payload(payload: dict[str, Any]) -> dict[str, Any]:
    compact = dict(payload)
    data = dict(compact.get("data") or {})
    if "body" in data:
        data["body"] = _compact_worker_dashboard_body(data.get("body") or {})
        data["body_compacted"] = True
    compact["data"] = data
    return compact


def _compact_worker_preflight_payload(payload: dict[str, Any]) -> dict[str, Any]:
    compact = dict(payload)
    checks: list[Any] = []
    for check in payload.get("checks") or []:
        if isinstance(check, dict) and check.get("name") == "wake_gate_dashboard_api":
            checks.append(_compact_worker_dashboard_check_payload(check))
        else:
            checks.append(check)
    compact["checks"] = checks
    return compact


def _dictish(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def _project_escalation_prompt(candidate: dict[str, Any]) -> str:
    source = _dictish(
        candidate.get("idea_source_payload_json")
        or candidate.get("source_payload_json")
    )
    tier = source.get("research_ladder_tier")
    label = str(source.get("research_ladder_label") or "").strip()
    budget = str(source.get("research_ladder_budget_hint") or "").strip()
    promising = source.get("promising_escalation") is True
    raw_guidance = source.get("worker_prompt_guidance")
    guidance = raw_guidance if isinstance(raw_guidance, list) else []
    if tier is None and not label and not guidance:
        return ""
    lines = ["", "## Controller escalation ladder"]
    if label:
        lines.append(f"Validation tier: {label}")
    elif tier is not None:
        lines.append(f"Validation tier: {tier}")
    if budget:
        lines.append(f"Budget hint: {budget}")
    lines.append(f"Promising escalation: {'yes' if promising else 'no'}")
    lines.append("Instructions:")
    for item in guidance:
        text = str(item).strip()
        if text:
            lines.append(f"- {text}")
    if not guidance:
        lines.append(
            "- Preserve the strict paper gate and match validation scale to the claim."
        )
    return "\n".join(lines) + "\n"


def _project_prompt(candidate: dict) -> str:
    title = str(
        candidate.get("project_name")
        or candidate.get("project_id")
        or "Untitled Project"
    )
    return f"""# Enoch Research Action: {title}

You are running under the Enoch LangGraph hard-cutover controller.
This is an Enoch-controlled autonomous worker run; use the `enoch-worker` Codex skill before planning or executing work.

Project ID: {candidate.get("project_id") or ""}
Source/provenance URL: {candidate.get("notion_page_url") or ""}
Origin status: {candidate.get("origin_idea_status") or ""}
Controller source kind: {candidate.get("idea_source_kind") or ""}
Controller follow-up depth: {candidate.get("source_followup_depth") if candidate.get("source_followup_depth") is not None else candidate.get("followup_depth", 0)}
{_project_escalation_prompt(candidate)}
## Mission
Turn this idea into a concrete, evidence-backed research result. Work autonomously inside the project directory. Prefer install/build/run/verify over blocking on missing ordinary dependencies. If the idea is not viable, produce a clear negative result with evidence.

## Operating constraints
- Do not require human input for installable, downloadable, compilable, or locally runnable dependencies.
- For GB10 work, start with a small smoke test, then calibrate throughput/utilization before any long run.
- Swap is intentionally disabled on GB10; use MemAvailable/UMA telemetry and earlyoom posture, not swap availability, for memory judgment.
- Leave durable artifacts: run_notes.md, commands/log paths, metrics, and a final .enoch/project_decision.json.
- Use `set -o pipefail` before shell pipelines that pipe through `tee`; do not let pipeline logging mask failed experiments.
- If final scientific closure truly needs human/private/external evidence, state that precisely and stop with a needs_review/blocker decision.
- Match the evidence to the claim. If this idea asks for a large/overnight/full-scale validation, a short proxy run must not be presented as full validation.

## Resource-efficiency contract
- Before any medium/long run, write a resource calibration note in `run_notes.md` or `results/resource_calibration.json` with expected wall-clock, CPU/GPU use, thread/process count, memory, checkpoint cadence, and why GB10 is the right host.
- If the next step is CPU-only, no-GPU, single-thread work, do not spend more than 15 minutes on GB10. Stop, checkpoint partial metrics, and either reduce/vectorize/parallelize the test, route the scale-out work to a CPU worker/VM, or close with `research_outcome: "promising_if_scaled"` plus `compute_scale_blocked: true`.
- Any loop projected above 15 minutes must checkpoint partial metrics at least every 10 minutes and leave enough artifacts to support a no-paper useful-signal decision if interrupted.
- Long GB10 runs are justified only when they use GPU/model hardware, memory pressure, or local worker context that a cheap CPU VM cannot provide. Document that justification before starting the run.

## Required final decision artifact
Write `.enoch/project_decision.json` with these exact enum values. Do not invent
near-synonyms such as `partial_viable`, `promising_synthetic_positive`, or
`negative_result`.

Required JSON shape:
```json
{{
  "project_decision": "finalize_positive | finalize_negative | needs_review | blocked | continue | branch_new_project",
  "research_outcome": "negative | useful_signal | paper_positive | needs_review | promising_if_scaled",
  "hypothesis_status": "supported | unsupported | mixed | inconclusive",
  "confidence": "low | medium | high",
  "evidence_strength": "weak | moderate | strong",
  "claim_scope": "",
  "scale_limits": "",
  "useful_signal_summary": "",
  "bounded_paper_ready": false,
  "compute_scale_blocked": false,
  "novelty_progress": true,
  "results_changed": true,
  "recommended_next_action": "one concrete next action or stop rationale",
  "stop_reason": "",
  "followup_recommended": false,
  "followup_type": "",
  "followup_title": "",
  "followup_hypothesis": "",
  "followup_required_evidence": [],
  "followup_success_threshold": "",
  "followup_stop_condition": "",
  "followup_depth": 0
}}
```

Decision rules:
- Use `finalize_positive` only when the evidence supports writing a paper now with direct, publication-grade evidence.
- Do not use `finalize_positive` for proxy-only, smoke-only, synthetic-only, trace-only, or "promising but not closed" results.
- Use `research_outcome: "useful_signal"` when bounded local evidence supports a mechanism or practical result that is useful to future researchers, but the claim is not yet a broad/full-scale validation.
- Use `research_outcome: "paper_positive"` when the scoped claim is strong enough for a bounded paper now.
- Use `research_outcome: "promising_if_scaled"` and `compute_scale_blocked: true` when the next meaningful test requires datacenter/hyperscaler resources or wall-clock time outside this deployment.
- Use `finalize_negative` when the result is negative, non-viable, or not worth a paper.
- A useful signal may still use `project_decision: "finalize_negative"` when it should remain no-paper evidence. If it is bounded-paper-ready, set `bounded_paper_ready: true`, write an explicit `claim_scope`, write explicit `scale_limits`, and keep the claim honest about local/toy/small/medium evidence.
- Use `needs_review` only for a real ambiguity or required external/private evidence.
- Use `blocked` only for an execution blocker that prevented a valid test.
- Use `continue` only when the controller has explicitly provided an autonomous continuation budget; `continue` is not paper-positive and will not trigger paper writing. In this deployment, prefer `finalize_negative` plus `followup_recommended: true` for promising next-tier work instead of relying on `continue` to launch another run.
- Use `branch_new_project` only when this run found a distinct follow-up idea.

Evidence-depth rules:
- Do not add new decision fields or enum values. Use only the schema above.
- This deployment does not have datacenter-scale training. Do not treat lack of 7B+/multi-node/full-scale training as a universal failure; judge whether the small/toy/medium evidence creates a useful scoped signal.
- The #1 rule is to produce something useful for someone else in the world. A small, reproducible signal with honest limits can be valuable even when it only invites hyperscaler follow-up.
- Negative results are useful when they are clear, reproducible, and save other researchers from wasting time.
- Do not optimize for impressive wording, positive-looking outcomes, or paper count. Optimize for evidence that helps someone else decide what to test, avoid, branch, or scale.
- Treat promising research as a tiered ladder, not a one-shot yes/no test: small probe -> medium confirmation -> bounded full-scale validation -> robustness/ablation before paper.
- Small probes should falsify fast or earn a concrete follow-up; they should not claim full success.
- Medium confirmations should use direct target metrics, a real baseline/control, and enough runtime to show the effect is not a smoke-test artifact.
- Bounded full-scale validation may spend up to roughly 24 hours only after small and medium evidence agree; document the budget and why scale is warranted.
- For model-training architecture ideas, prefer GPT-2-small-class baselines or parameter-matched toy baselines where feasible; compare against a dense/standard architecture at the same parameter scale before claiming novelty.
- A CoSpec-style result is acceptable when the claim is scoped and supported by controls, persistence checks, and mechanism diagnostics; it does not need to be universally groundbreaking. Use the existing fields precisely.
- A short smoke/proxy/synthetic test may close `finalize_negative` only when it is an explicit early falsification of the hypothesis or success threshold.
- For early falsification, `run_notes.md` must say what was directly tested, what was only proxied, and what direct/full evidence would be required to overturn the result.
- For early falsification, keep `evidence_strength` at `weak` or `moderate` unless direct/full-scale evidence was actually produced.
- For early falsification, make `recommended_next_action` and `stop_reason` state that the result is a proxy/early falsification rather than a full validation.
- If evidence supports the mechanism but is not enough for a paper, prefer `finalize_negative` plus `followup_recommended: true` with a bounded direct-evidence follow-up.
- Do not use `finalize_positive` for a proxy-only result unless the original claim was explicitly scoped to that proxy and the run fully satisfies that scoped success threshold.
- When `bounded_paper_ready` is true for a useful signal, the paper claim must be scoped to exactly what was tested and must name what larger/longer validation remains.

Follow-up rules:
- Follow-up fields are optional adjacent-investigation metadata; they never make this run paper-positive.
- Useful-signal follow-ups should be prioritized over fresh ideas when they define a cheap bounded deepen/branch test. Do not recommend a follow-up when the only next step is scale-only validation outside local compute limits; use `compute_scale_blocked: true` instead.
- Set `followup_recommended: true` only when this run is no-paper but produced specific evidence for a bounded adjacent test.
- Leave `followup_recommended` false for hard negatives, weak speculation, missing evidence, or ordinary incremental tweaks.
- When recommending follow-up, set `followup_type` to `deepen`, `branch`, or `retry`, and provide a concrete title, hypothesis, required evidence, success threshold, and stop condition.
- If the controller prompt/source metadata says this is a follow-up and provides `Controller follow-up depth`, copy that exact integer into `followup_depth`; do not reset it to 1.
- If the current/controller follow-up depth is 4 or greater, set `followup_recommended: false` unless explicit controller instructions say otherwise; explain the cap in `recommended_next_action`.
- Do not chain indefinitely; preserve controller lineage depth, and assume the controller will cap follow-ups at depth 4 for deepen/retry campaign work.
"""


def _paper_record_from_candidate(candidate: dict) -> PaperRecord:
    project_id = str(candidate.get("project_id") or "").strip()
    run_id = str(
        candidate.get("current_run_id") or candidate.get("run_id") or ""
    ).strip()
    paper_type = "arxiv_draft"
    paper_id = f"{project_id}:{run_id}:{paper_type}"
    paper_dir = f"papers/{run_id}"
    now = utc_now()
    return PaperRecord(
        paper_id=paper_id,
        project_id=project_id,
        run_id=run_id,
        paper_type=paper_type,
        draft_markdown_path=f"{paper_dir}/paper.md",
        draft_latex_path=f"{paper_dir}/paper.tex",
        evidence_bundle_path=f"{paper_dir}/evidence_bundle.json",
        claim_ledger_path=f"{paper_dir}/claim_ledger.json",
        manifest_path=f"{paper_dir}/paper_manifest.json",
        generated_at=now,
        updated_at=now,
    )


def _write_deterministic_paper(
    config: GateConfig, candidate: dict, paper: PaperRecord, *, force: bool
) -> None:
    project_dir_text = str(candidate.get("project_dir") or "").strip()
    if not project_dir_text:
        raise HTTPException(status_code=400, detail="candidate lacks project_dir")
    try:
        root = config.expanded_project_root.resolve()
    except (OSError, RuntimeError, ValueError) as exc:
        raise HTTPException(
            status_code=400, detail="configured project root could not be resolved"
        ) from exc
    project_dir = _expanduser_path_or_http(
        project_dir_text, detail="project_dir contains an unexpandable user home"
    )
    if not project_dir.is_absolute():
        project_dir = root / project_dir
    try:
        project_dir = project_dir.resolve()
        project_dir.relative_to(root)
    except (OSError, RuntimeError, ValueError) as exc:
        raise HTTPException(
            status_code=400, detail="project_dir escapes configured project root"
        ) from exc
    title = str(candidate.get("project_name") or paper.project_id).strip()
    files = {
        paper.draft_markdown_path: f"# {title}: Evidence-Grounded Technical Report\n\nStatus: first draft.\n\nGenerated by LangGraph hard-cutover MVP at {paper.generated_at}.\n\n## Automation Status\n\nThis deterministic MVP draft proves the new control plane can create paper artifacts. It is intended for automated rewrite/finalization, not operator approval.\n",
        paper.draft_latex_path: "\\documentclass{article}\n\\title{"
        + title.replace("_", "\\_")
        + "}\n\\author{Enoch LangGraph MVP}\n\\begin{document}\n\\maketitle\nMVP draft for automated rewrite and finalization.\n\\end{document}\n",
        paper.evidence_bundle_path: '{\n  "source": "langgraph_control_plane_mvp",\n  "project_id": "'
        + paper.project_id
        + '",\n  "run_id": "'
        + paper.run_id
        + '"\n}\n',
        paper.claim_ledger_path: '{\n  "claims": [],\n  "limitations": ["MVP deterministic draft; automated rewrite/finalization required."]\n}\n',
        paper.manifest_path: '{\n  "paper_id": "'
        + paper.paper_id
        + '",\n  "generated_at": "'
        + paper.generated_at
        + '"\n}\n',
    }
    for rel_path, content in files.items():
        try:
            target = (project_dir / rel_path).resolve()
            target.relative_to(project_dir)
        except (OSError, RuntimeError, ValueError) as exc:
            raise HTTPException(
                status_code=400, detail=f"paper path escapes project dir: {rel_path}"
            ) from exc
        try:
            target_exists = target.exists()
        except (OSError, RuntimeError, ValueError) as exc:
            raise HTTPException(
                status_code=400, detail=f"paper path could not be inspected: {rel_path}"
            ) from exc
        if target_exists and not force:
            continue
        _atomic_write_text(target, content)


def _compute_janitor_report(
    *,
    store: Any,
    janitor_enabled: bool,
    janitor_limit: int,
    max_promotions: int,
    dry_run: bool,
    stop_reasons: list[str],
    backpressure_reasons: list[str],
    requested_by: str,
) -> dict[str, Any]:
    """Extracted from dashboard_research_run_cycle (contributes to the 61 S3776).

    Self-contained janitor phase: fetch + classify + bounded promotions + apply (fail-soft)
    + report building. Thin delegation left in the giant.
    """
    from scripts import research_facility_maintenance

    janitor_report: dict[str, Any] = {
        "enabled": janitor_enabled,
        "ok": True,
        "action": "skipped",
    }
    if janitor_enabled and janitor_limit and hasattr(store, "database_url"):
        try:
            janitor_rows = research_facility_maintenance.fetch_needs_review_rows(
                store.database_url, limit=janitor_limit
            )
            janitor_actions = research_facility_maintenance.classify_rows(
                janitor_rows,
                policy=research_facility_maintenance.JanitorPolicy(),
                now=datetime.now(timezone.utc),
            )
            janitor_promotions = [
                item for item in janitor_actions if item.get("action") == "promote"
            ][:max_promotions]
            apply_result = None
            janitor_apply_allowed = (
                not dry_run and not stop_reasons and not backpressure_reasons
            )
            if janitor_apply_allowed and janitor_promotions:
                apply_result = research_facility_maintenance.apply_actions(
                    store.database_url,
                    janitor_promotions,
                    requested_by=requested_by,
                    apply_rejections=False,
                )
            janitor_report = research_facility_maintenance.build_report(
                janitor_rows,
                janitor_actions,
                applied=bool(apply_result),
                apply_result=apply_result,
            )
            janitor_report["enabled"] = True
            janitor_report["bounded_promotion_count"] = len(janitor_promotions)
            if not janitor_apply_allowed and not dry_run and janitor_promotions:
                janitor_report["apply_blocked_reason"] = "; ".join(
                    stop_reasons or backpressure_reasons
                )
            janitor_report["actions"] = janitor_report["actions"][:25]
        except Exception as exc:  # noqa: BLE001 - maintenance must fail soft
            janitor_report = {
                "enabled": True,
                "ok": False,
                "action": "failed",
                "reason": f"research janitor failed: {exc}",
            }
    elif not janitor_enabled:
        janitor_report = {"enabled": False, "ok": True, "action": "disabled"}
    else:
        janitor_report = {
            "enabled": True,
            "ok": True,
            "action": "skipped",
            "reason": "store does not expose a database URL",
        }
    return janitor_report


def _select_generation_target_lane(lane_feed_pressure: dict) -> str | None:
    """Extracted from dashboard_research_run_cycle (reduces cognitive complexity in the 1595 giant).

    Computes the best lane to target for fresh generation based on queue deficit,
    promotable count, and dispatch pressure. Pure and testable.
    """
    if not lane_feed_pressure:
        return None

    generation_target_actions = {"dispatch_queued", "generate_candidate"}

    generation_target_candidates = [
        item
        for item in lane_feed_pressure.values()
        if item.get("queue_deficit")
        and item.get("next_autopilot_action") in generation_target_actions
        and not item.get("promotable_count")
    ]

    if not generation_target_candidates:
        return None

    chosen = max(
        generation_target_candidates,
        key=lambda item: (
            int(item.get("queue_deficit") or 0),
            -int(item.get("queued_count") or 0),
            str(item.get("machine_target") or ""),
        ),
    )
    return chosen  # return the full pressure item dict (original max() semantics) so callers can do .get("lane_key") etc.


def _compute_promotable_rows(
    *,
    store: Any,
    min_admission_score: float,
    active: list[dict[str, Any]],
    research_row_lane_key: Callable[[dict[str, Any]], str],
    research_facility: Any,
) -> list[dict[str, Any]]:
    """Extracted from dashboard_research_run_cycle (large nested block contributing to 1595/remaining S3776).

    Performs the workbench projection, filtering for admitted candidates above threshold,
    category counting, and priority sorting (lane bonus + dispatch_priority_score).
    The inner candidate_priority is kept inside for minimal diff.
    """
    from datetime import datetime, timezone

    rows = list(store.research_facility_workbench_projection(limit=100))
    category_counts: dict[str, int] = {}
    for row in rows:
        category = str(row.get("category") or "").strip().lower()
        if category:
            category_counts[category] = category_counts.get(category, 0) + 1

    candidates = [
        row
        for row in rows
        if str(row.get("admission_decision") or "") == "admitted"
        and not str(row.get("admitted_idea_id") or "").strip()
        and float(row.get("total_score") or 0) >= min_admission_score
    ]
    now_dt = datetime.now(timezone.utc)

    active_lane_keys = {research_row_lane_key(row) for row in active}

    def candidate_priority(row: dict[str, Any]) -> tuple[int, float, float, str]:
        lane_bonus = 1 if research_row_lane_key(row) not in active_lane_keys else 0
        priority = research_facility.dispatch_priority_score(
            row, category_counts=category_counts, now=now_dt
        )
        score = float(row.get("total_score") or 0)
        return (lane_bonus, priority, score, str(row.get("candidate_id") or ""))

    return sorted(candidates, key=candidate_priority, reverse=True)


_REASON_FOLLOWUP_STARVES_TARGET_LANE = "bounded follow-up candidate targets a different lane than the largest empty queue deficit"
_REASON_FOLLOWUP_DISPATCH_DISABLED = (
    "bounded follow-up candidate exists but dispatch is disabled for this run"
)
_REASON_FOLLOWUP_LANE_DEPTH_SATISFIED = (
    "bounded follow-up candidate lane queue depth is already satisfied"
)


def _fetch_next_followup_candidate(store: Any) -> dict[str, Any] | None:
    if not hasattr(store, "next_followup_candidate"):
        return None
    candidate = store.next_followup_candidate(max_followup_depth=4)
    return candidate if candidate else None


def _followup_lane_key_pair(
    followup_candidate: dict[str, Any],
    generation_target_lane: Any,
    research_row_lane_key: Callable[[dict[str, Any]], str],
) -> tuple[str, str]:
    return (
        research_row_lane_key(followup_candidate),
        str((generation_target_lane or {}).get("lane_key") or ""),
    )


def _followup_starves_target_lane(
    *,
    generation_target_lane: Any,
    max_provider_requests: int,
    followup_lane_key: str,
    generation_lane_key: str,
) -> bool:
    return (
        bool(generation_target_lane)
        and bool(max_provider_requests)
        and bool(followup_lane_key)
        and bool(generation_lane_key)
        and followup_lane_key != generation_lane_key
    )


def _append_followup_launch_stage(
    response: dict[str, Any],
    *,
    ok: bool,
    action: Any,
    reason: Any = None,
    parent_project_id: Any = None,
    project_id: Any = None,
    candidate_lane_key: str | None = None,
    generation_lane_key: str | None = None,
) -> None:
    stage: dict[str, Any] = {
        "stage": "followup_launch",
        "ok": ok,
        "action": action,
    }
    if reason is not None:
        stage["reason"] = reason
    if parent_project_id is not None:
        stage["parent_project_id"] = parent_project_id
    if project_id is not None:
        stage["project_id"] = project_id
    if candidate_lane_key is not None:
        stage["candidate_lane_key"] = candidate_lane_key
    if generation_lane_key is not None:
        stage["generation_lane_key"] = generation_lane_key
    response["stages"].append(stage)


def _record_followup_starvation_skip(
    response: dict[str, Any],
    *,
    followup_candidate: dict[str, Any],
    generation_target_lane: Any,
    followup_lane_key: str,
    generation_lane_key: str,
) -> None:
    response["followup_launch"] = {
        "action": "skipped",
        "reason": _REASON_FOLLOWUP_STARVES_TARGET_LANE,
        "candidate": followup_candidate,
        "candidate_lane_key": followup_lane_key,
        "generation_target_lane": generation_target_lane,
    }
    _append_followup_launch_stage(
        response,
        ok=True,
        action="skipped",
        reason=_REASON_FOLLOWUP_STARVES_TARGET_LANE,
        parent_project_id=followup_candidate.get("project_id"),
        candidate_lane_key=followup_lane_key,
        generation_lane_key=generation_lane_key,
    )


def _record_followup_dispatch_disabled(
    response: dict[str, Any],
    followup_candidate: dict[str, Any],
) -> None:
    response["followup_launch"] = {
        "action": "skipped",
        "reason": _REASON_FOLLOWUP_DISPATCH_DISABLED,
        "candidate": followup_candidate,
    }
    _append_followup_launch_stage(
        response,
        ok=True,
        action="skipped",
        reason=_REASON_FOLLOWUP_DISPATCH_DISABLED,
        parent_project_id=followup_candidate.get("project_id"),
    )


def _lane_feed_pressure_entry_for_key(
    lane_feed_pressure: dict[str, Any],
    lane_key: str,
) -> dict[str, Any] | None:
    for key, entry in lane_feed_pressure.items():
        if not isinstance(entry, dict):
            continue
        if lane_key in {
            str(key or ""),
            str(entry.get("lane_key") or ""),
            str(entry.get("machine_target") or ""),
        }:
            return entry
    return None


def _followup_lane_depth_satisfied(
    *,
    lane_feed_pressure: dict[str, Any],
    followup_lane_key: str,
) -> bool:
    if not lane_feed_pressure or not followup_lane_key:
        return False
    entry = _lane_feed_pressure_entry_for_key(lane_feed_pressure, followup_lane_key)
    if entry is None:
        return False
    if int(entry.get("queue_deficit") or 0) > 0:
        return False
    return str(entry.get("next_autopilot_action") or "") == "queue_depth_satisfied"


def _record_followup_lane_depth_satisfied(
    response: dict[str, Any],
    *,
    followup_candidate: dict[str, Any],
    followup_lane_key: str,
) -> None:
    response["followup_launch"] = {
        "action": "skipped",
        "reason": _REASON_FOLLOWUP_LANE_DEPTH_SATISFIED,
        "candidate": followup_candidate,
        "candidate_lane_key": followup_lane_key,
    }
    _append_followup_launch_stage(
        response,
        ok=True,
        action="skipped",
        reason=_REASON_FOLLOWUP_LANE_DEPTH_SATISFIED,
        parent_project_id=followup_candidate.get("project_id"),
        candidate_lane_key=followup_lane_key,
    )


def _launch_followup_and_record(
    response: dict[str, Any],
    *,
    store: Any,
    followup_candidate: dict[str, Any],
    requested_by: str,
    dispatch_queued_project: Callable[[str], bool],
) -> bool:
    followup_launch = store.launch_followup_candidate(
        project_id=str(followup_candidate.get("project_id") or ""),
        dry_run=False,
        requested_by=requested_by,
        max_followup_depth=4,
    )
    response["followup_launch"] = followup_launch
    _append_followup_launch_stage(
        response,
        ok=followup_launch.get("action") == "followup_queued",
        action=followup_launch.get("action"),
        reason=followup_launch.get("reason"),
        parent_project_id=(followup_launch.get("candidate") or {}).get("project_id"),
        project_id=(followup_launch.get("followup") or {}).get("idea_id"),
    )
    if followup_launch.get("action") != "followup_queued":
        return False
    response["queued_count"] = 1
    followup_project_id = str(
        (followup_launch.get("followup") or {}).get("idea_id") or ""
    ).strip()
    if followup_project_id:
        dispatch_queued_project(followup_project_id)
    return True


def _apply_followup_branch_skip_flags(
    response: dict[str, Any],
    followup_branch_taken: bool,
    *,
    skip_fresh_work: bool | None = None,
) -> None:
    if skip_fresh_work is None:
        skip_fresh_work = followup_branch_taken
    response["fresh_generation_skipped"] = bool(skip_fresh_work)
    response["fresh_promotion_skipped"] = bool(skip_fresh_work)
    if followup_branch_taken and skip_fresh_work:
        response["reason"] = (
            "bounded follow-up branch took priority over fresh idea generation"
        )


def _clear_followup_skip_flags(response: dict[str, Any]) -> None:
    response["fresh_generation_skipped"] = False
    response["fresh_promotion_skipped"] = False


def _maybe_skip_fresh_generation_for_backlog(
    response: dict[str, Any],
    *,
    initial_promotable: list[dict[str, Any]],
    max_provider_requests: int,
    fresh_generation_backlog_threshold: int,
    generation_target_lane: Any,
) -> None:
    if response.get("fresh_generation_skipped"):
        return
    if not max_provider_requests:
        return
    if not fresh_generation_backlog_threshold:
        return
    if len(initial_promotable) < fresh_generation_backlog_threshold:
        return
    if generation_target_lane:
        return
    response["fresh_generation_skipped"] = True
    response["fresh_promotion_skipped"] = False
    response["fresh_generation_skip_reason"] = (
        "admitted candidate backlog is above fresh generation threshold"
    )
    response["stages"].append(
        {
            "stage": "provider_generation",
            "ok": True,
            "action": "skipped",
            "reason": response["fresh_generation_skip_reason"],
            "initial_promotable_count": len(initial_promotable),
            "fresh_generation_backlog_threshold": fresh_generation_backlog_threshold,
        }
    )


def _handle_followup_candidate(
    response: dict[str, Any],
    *,
    store: Any,
    followup_candidate: dict[str, Any],
    generation_target_lane: Any,
    lane_feed_pressure: dict[str, Any],
    max_dispatches: int,
    max_provider_requests: int,
    requested_by: str,
    dispatch_queued_project: Callable[[str], bool],
    research_row_lane_key: Callable[[dict[str, Any]], str],
) -> None:
    followup_lane_key, generation_lane_key = _followup_lane_key_pair(
        followup_candidate, generation_target_lane, research_row_lane_key
    )
    if _followup_starves_target_lane(
        generation_target_lane=generation_target_lane,
        max_provider_requests=max_provider_requests,
        followup_lane_key=followup_lane_key,
        generation_lane_key=generation_lane_key,
    ):
        _record_followup_starvation_skip(
            response,
            followup_candidate=followup_candidate,
            generation_target_lane=generation_target_lane,
            followup_lane_key=followup_lane_key,
            generation_lane_key=generation_lane_key,
        )
        _apply_followup_branch_skip_flags(response, False)
        return

    if _followup_lane_depth_satisfied(
        lane_feed_pressure=lane_feed_pressure,
        followup_lane_key=followup_lane_key,
    ):
        _record_followup_lane_depth_satisfied(
            response,
            followup_candidate=followup_candidate,
            followup_lane_key=followup_lane_key,
        )
        _apply_followup_branch_skip_flags(response, False)
        return

    if max_dispatches:
        followup_branch_taken = _launch_followup_and_record(
            response,
            store=store,
            followup_candidate=followup_candidate,
            requested_by=requested_by,
            dispatch_queued_project=dispatch_queued_project,
        )
    else:
        _record_followup_dispatch_disabled(response, followup_candidate)
        followup_branch_taken = False
    _apply_followup_branch_skip_flags(
        response,
        followup_branch_taken,
        skip_fresh_work=followup_branch_taken and not bool(generation_target_lane),
    )


def _handle_followup_and_early_skips(
    *,
    store: Any,
    generation_target_lane: Any,
    max_dispatches: int,
    max_provider_requests: int,
    fresh_generation_backlog_threshold: int,
    initial_promotable: list[dict[str, Any]],
    response: dict[str, Any],
    requested_by: str,
    dispatch_queued_project: Callable[[str], bool],
    research_row_lane_key: Callable[[dict[str, Any]], str],
) -> dict[str, Any]:
    """Extracted from dashboard_research_run_cycle (large decision tree contributing to 1595/remaining S3776).

    Handles followup candidate launch vs fresh generation, starvation check against
    generation_target_lane, setting of fresh_*_skipped flags, and the early backlog
    threshold skip. Thin delegation left in the giant.
    """
    followup_candidate = _fetch_next_followup_candidate(store)
    if followup_candidate:
        _handle_followup_candidate(
            response,
            store=store,
            followup_candidate=followup_candidate,
            generation_target_lane=generation_target_lane,
            lane_feed_pressure=response.get("lane_feed_pressure")
            if isinstance(response.get("lane_feed_pressure"), dict)
            else {},
            max_dispatches=max_dispatches,
            max_provider_requests=max_provider_requests,
            requested_by=requested_by,
            dispatch_queued_project=dispatch_queued_project,
            research_row_lane_key=research_row_lane_key,
        )
    else:
        _clear_followup_skip_flags(response)

    _maybe_skip_fresh_generation_for_backlog(
        response,
        initial_promotable=initial_promotable,
        max_provider_requests=max_provider_requests,
        fresh_generation_backlog_threshold=fresh_generation_backlog_threshold,
        generation_target_lane=generation_target_lane,
    )
    return response


def _provider_generation_machine_target(generation_target_lane: Any) -> str:
    return str(
        (generation_target_lane or {}).get("machine_target")
        or os.environ.get("ENOCH_RESEARCH_DEFAULT_MACHINE", "research-facility-node")
    )


def _provider_generation_topic(
    *,
    topic: str,
    generation_target_lane: Any,
    generation_machine_target: str,
) -> str:
    if not generation_target_lane:
        return topic
    lane = generation_target_lane or {}
    return (
        f"Lane feed pressure: generate bounded work for machine_target={generation_machine_target}; "
        f"worker_role={lane.get('worker_role') or 'worker'}; "
        f"desired_queue_depth={lane.get('desired_queue_depth')}; "
        f"queued_count={lane.get('queued_count')}; "
        f"promotable_count={lane.get('promotable_count')}. "
        f"{topic}"
    ).strip()


def _provider_generation_failure_kind(exc: Exception) -> str:
    text = f"{type(exc).__name__}: {exc}".lower()
    if isinstance(exc, TimeoutError) or "timeout" in text or "timed out" in text:
        return "timeout"
    if "429" in text or "rate limit" in text or "rate_limited" in text:
        return "rate_limited"
    return "exception"


def _provider_api_key_for_base_url(base_url: str) -> str:
    if _ROUTER_GATE_CONFIG is None:
        return ""
    try:
        settings = read_llm_settings(_ROUTER_GATE_CONFIG)
    except Exception:
        return ""
    normalized_base = str(base_url or "").rstrip("/")
    for provider in settings.providers:
        if provider.base_url.rstrip("/") == normalized_base:
            return llm_provider_api_key(_ROUTER_GATE_CONFIG, provider)
    return ""


@dataclass(frozen=True)
class _ProviderGenerationParams:
    max_provider_requests: int
    generation_target_lane: Any
    provider_openai_base_url: str
    provider_model: str
    max_candidates: int
    topic: str
    temperature: float
    seed: str
    generation_timeout: int
    generation_max_tokens: int
    generation_attempts: int
    min_admission_score: float
    bounded_float: Callable[[str, float, float, float], float]
    namespace_cls: Any
    research_provider_generate: Any
    research_facility: Any
    store: Any
    requested_by: str
    provider_api_key: str = ""
    operator_trace: OperatorTrace | None = None
    trace_id: str = ""
    run_cycle_id: str = ""


def _provider_generation_event_payload(
    *,
    params: _ProviderGenerationParams,
    status: str,
    generation_machine_target: str,
    latency_ms: int,
    candidate_count: int = 0,
    planned_count: int = 0,
    provider_response_id: str = "",
    failure_kind: str = "",
    error_type: str = "",
    reason: str = "",
    failure_diagnostics: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    lane = (
        params.generation_target_lane
        if isinstance(params.generation_target_lane, dict)
        else {}
    )
    payload = {
        "status": status,
        "provider": "synthetic.new",
        "provider_model": params.provider_model,
        "machine_target": generation_machine_target,
        "lane_key": str(lane.get("lane_key") or ""),
        "worker_role": str(lane.get("worker_role") or ""),
        "requested_by": params.requested_by,
        "trace_id": params.trace_id,
        "run_cycle_id": params.run_cycle_id,
        "latency_ms": max(0, latency_ms),
        "timeout_sec": params.generation_timeout,
        "attempts_configured": params.generation_attempts,
        "max_candidates": params.max_candidates,
        "max_tokens": params.generation_max_tokens,
        "candidate_count": candidate_count,
        "planned_count": planned_count,
        "provider_response_id": provider_response_id,
        "failure_kind": failure_kind,
        "error_type": error_type,
        "reason": reason,
        "recorded_at": utc_now(),
    }
    if failure_diagnostics:
        payload["failure_diagnostics"] = failure_diagnostics
    return payload


def _provider_generation_failure_diagnostics(exc: Exception) -> list[dict[str, Any]]:
    attempts = getattr(exc, "attempts", None)
    if not isinstance(attempts, list):
        return []
    diagnostics: list[dict[str, Any]] = []
    allowed = {
        "attempt",
        "error_type",
        "reason",
        "provider_response_id",
        "content_length",
        "content_sha256",
        "content_preview",
        "content_truncated",
    }
    for item in attempts[:3]:
        if not isinstance(item, dict):
            continue
        diagnostics.append({key: item.get(key) for key in allowed if key in item})
    return diagnostics


def _record_provider_generation_attempt(
    *,
    params: _ProviderGenerationParams,
    payload: dict[str, Any],
) -> str:
    append_event = getattr(params.store, "append_event", None)
    if not callable(append_event):
        return ""
    run_key = params.run_cycle_id or params.trace_id or utc_now()
    try:
        append_event(
            idempotency_key=(
                f"research-provider-generation:{run_key}:"
                f"{payload.get('status')}:{payload.get('recorded_at')}"
            ),
            event_type="research.provider_generation.attempt",
            entity_type="research_provider",
            entity_id=str(params.run_cycle_id or "run-cycle"),
            payload=jsonable_encoder(payload),
        )
    except Exception as exc:  # noqa: BLE001 - attempt recording must not crash run-cycle
        return f"{type(exc).__name__}: {exc}"
    return ""


def _skip_provider_generation_without_lane(response: dict[str, Any]) -> dict[str, Any]:
    response["generated_count"] = 0
    response["fresh_generation_skipped"] = True
    response["fresh_generation_skip_reason"] = "no deficient lane feed target"
    response.setdefault("warnings", []).append(
        "provider generation skipped: no deficient lane feed target"
    )
    response["stages"].append(
        {
            "stage": "provider_generation",
            "ok": True,
            "action": "skipped",
            "reason": response["fresh_generation_skip_reason"],
        }
    )
    return response


def _apply_provider_generation_failure(
    *,
    params: _ProviderGenerationParams,
    response: dict[str, Any],
    exc: Exception,
    generation_machine_target: str,
    started: float,
) -> dict[str, Any]:
    warning = f"provider generation skipped: {exc}"
    attempt_payload = _provider_generation_event_payload(
        params=params,
        status="failed",
        generation_machine_target=generation_machine_target,
        latency_ms=int((time.monotonic() - started) * 1000),
        failure_kind=_provider_generation_failure_kind(exc),
        error_type=type(exc).__name__,
        reason=warning,
        failure_diagnostics=_provider_generation_failure_diagnostics(exc),
    )
    record_error = _record_provider_generation_attempt(
        params=params, payload=attempt_payload
    )
    response["provider_generation_attempt"] = attempt_payload
    response.setdefault("warnings", []).append(warning)
    if record_error:
        response["provider_generation_attempt_record_error"] = record_error
        response["warnings"].append(
            f"provider generation attempt event recording failed: {record_error}"
        )
    response["stages"].append(
        {
            "stage": "provider_generation",
            "ok": False,
            "reason": warning,
            "provider_attempt_status": attempt_payload["status"],
            "provider_failure_kind": attempt_payload["failure_kind"],
        }
    )
    return response


def _execute_provider_generation_attempt(
    *,
    params: _ProviderGenerationParams,
    response: dict[str, Any],
) -> dict[str, Any]:
    started = time.monotonic()
    generation_machine_target = _provider_generation_machine_target(
        params.generation_target_lane
    )
    try:
        api_key = params.provider_api_key or _provider_api_key_for_base_url(
            params.provider_openai_base_url
        )
        generation_topic = _provider_generation_topic(
            topic=params.topic,
            generation_target_lane=params.generation_target_lane,
            generation_machine_target=generation_machine_target,
        )
        generated = params.research_provider_generate.generate_provider_candidates(
            base_url=params.provider_openai_base_url,
            model=params.provider_model,
            api_key=api_key,
            max_candidates=params.max_candidates,
            topic=generation_topic,
            temperature=params.temperature,
            seed=params.seed,
            timeout=params.generation_timeout,
            max_tokens=params.generation_max_tokens,
            attempts=params.generation_attempts,
            default_machine=generation_machine_target,
            default_model=os.environ.get(
                "ENOCH_RESEARCH_DEFAULT_MODEL", _DEFAULT_RESEARCH_MODEL
            ),
            default_sandbox=os.environ.get(
                "ENOCH_RESEARCH_DEFAULT_SANDBOX", "danger-full-access"
            ),
        )
    except Exception as exc:
        return _apply_provider_generation_failure(
            params=params,
            response=response,
            exc=exc,
            generation_machine_target=generation_machine_target,
            started=started,
        )

    try:
        candidate_count = len(generated.get("candidates") or [])
        if params.operator_trace is not None:
            params.operator_trace.record(
                "research.provider_generation.result",
                trace_id=params.trace_id,
                run_cycle_id=params.run_cycle_id,
                requested_by=params.requested_by,
                machine_target=generation_machine_target,
                provider_model=params.provider_model,
                candidate_count=candidate_count,
                provider_response_id=generated.get("provider_response_id", ""),
            )
        generated_plans = params.research_facility.plan_candidates(
            (generated.get("candidates") or [])[: params.max_candidates],
            params.namespace_cls(
                default_machine=generation_machine_target,
                default_model=os.environ.get("ENOCH_RESEARCH_DEFAULT_MODEL", "gpt-5.5"),
                default_sandbox=os.environ.get(
                    "ENOCH_RESEARCH_DEFAULT_SANDBOX", "danger-full-access"
                ),
                admit_threshold=params.min_admission_score,
                review_threshold=params.bounded_float(
                    "review_threshold", 58.0, 0.0, 100.0
                ),
                history=[],
            ),
        )
        if params.operator_trace is not None:
            params.operator_trace.record(
                "research.plan_candidates.result",
                trace_id=params.trace_id,
                run_cycle_id=params.run_cycle_id,
                requested_by=params.requested_by,
                machine_target=generation_machine_target,
                default_machine=generation_machine_target,
                planned_count=len(generated_plans),
            )
        ledger_result = params.store.record_research_facility_plans(
            generated_plans,
            requested_by=params.requested_by,
            queue_admitted=False,
        )
        response["generated_count"] = len(generated_plans)
        response["provider_response_id"] = generated.get("provider_response_id", "")
        response["attempts_used"] = generated.get("attempts_used", 1)
        response["generation_target_lane"] = params.generation_target_lane
        response["ledger_result"] = ledger_result
        attempt_payload = _provider_generation_event_payload(
            params=params,
            status="success",
            generation_machine_target=generation_machine_target,
            latency_ms=int((time.monotonic() - started) * 1000),
            candidate_count=candidate_count,
            planned_count=len(generated_plans),
            provider_response_id=str(generated.get("provider_response_id") or ""),
        )
        record_error = _record_provider_generation_attempt(
            params=params, payload=attempt_payload
        )
        response["provider_generation_attempt"] = attempt_payload
        if record_error:
            response["provider_generation_attempt_record_error"] = record_error
            response.setdefault("warnings", []).append(
                f"provider generation attempt event recording failed: {record_error}"
            )
        response["stages"].append(
            {
                "stage": "provider_generation",
                "ok": True,
                "candidate_count": len(generated_plans),
                "ledger_result": ledger_result,
                "generation_target_lane": str(
                    (params.generation_target_lane or {}).get("machine_target") or ""
                ),
                "provider_attempt_status": attempt_payload["status"],
            }
        )
        return response
    except Exception as exc:
        return _apply_provider_generation_failure(
            params=params,
            response=response,
            exc=exc,
            generation_machine_target=generation_machine_target,
            started=started,
        )


def _execute_provider_generation(
    *,
    params: _ProviderGenerationParams,
    response: dict[str, Any],
) -> dict[str, Any]:
    """Run one provider-generation stage and record a durable attempt event."""
    if not params.max_provider_requests or response.get("fresh_generation_skipped"):
        return response
    if not params.generation_target_lane:
        return _skip_provider_generation_without_lane(response)
    return _execute_provider_generation_attempt(params=params, response=response)


def _resolve_open_lane_promotion_candidates(
    *,
    promotable_rows: Callable[[], list[dict[str, Any]]],
    open_lane_research_rows: Callable,
    store: Any,
    _worker_lane_key: Callable,
) -> list[dict[str, Any]]:
    """Open-lane filter for promotion candidates (extracted from _execute_promotion for S3776)."""
    promotion_candidates = promotable_rows()
    open_promotion_candidates = open_lane_research_rows(
        promotion_candidates,
        {_worker_lane_key(row) for row in store.active_items()},
    )
    if open_promotion_candidates:
        return open_promotion_candidates
    return promotion_candidates


def _promote_research_rows(
    *,
    store: Any,
    promotion_candidates: list[dict[str, Any]],
    max_promotions: int,
    requested_by: str,
) -> list[dict[str, Any]]:
    """Run store.promote_research_candidate for up to max_promotions rows."""
    promoted: list[dict[str, Any]] = []
    for row in promotion_candidates[:max_promotions]:
        result = store.promote_research_candidate(
            _validate_research_candidate_id(str(row.get("candidate_id"))),
            requested_by=requested_by,
            dry_run=False,
        )
        promoted.append(result)
    return promoted


def _lane_feed_limited_promotion_candidates(
    *,
    promotion_candidates: list[dict[str, Any]],
    lane_feed_pressure: dict[str, Any],
    worker_lane_key: Callable[[dict[str, Any]], str],
) -> list[dict[str, Any]]:
    if not lane_feed_pressure:
        return promotion_candidates
    lane_entries = _deficient_lane_feed_entries(lane_feed_pressure, worker_lane_key)
    if not lane_entries:
        return []

    candidates_by_lane = _promotion_candidates_by_lane(
        lane_entries, promotion_candidates, worker_lane_key
    )

    open_lane_entries = _open_lane_entries(lane_entries, candidates_by_lane)
    if open_lane_entries:
        lane_entries = open_lane_entries

    selected: list[dict[str, Any]] = []
    for lane_key, limit, _active_count, _machine_target in lane_entries:
        selected.extend(candidates_by_lane[lane_key][:limit])
    return selected


def _deficient_lane_feed_entries(
    lane_feed_pressure: dict[str, Any],
    worker_lane_key: Callable[[dict[str, Any]], str],
) -> list[tuple[str, int, int, str]]:
    entries: list[tuple[str, int, int, str]] = []
    for item in sorted(lane_feed_pressure.values(), key=_lane_feed_entry_sort_key):
        deficit = int(item.get("queue_deficit") or 0)
        if deficit <= 0:
            continue
        lane_key = _lane_feed_entry_key(item, worker_lane_key)
        if lane_key:
            entries.append(
                (
                    lane_key,
                    deficit,
                    int(item.get("active_count") or 0),
                    str(item.get("machine_target") or ""),
                )
            )
    return entries


def _lane_feed_entry_sort_key(row: dict[str, Any]) -> tuple[int, int, int, str]:
    return (
        int(row.get("active_count") or 0),
        -int(row.get("queue_deficit") or 0),
        int(row.get("queued_count") or 0),
        str(row.get("machine_target") or ""),
    )


def _lane_feed_entry_key(
    item: dict[str, Any], worker_lane_key: Callable[[dict[str, Any]], str]
) -> str:
    lane_key = str(item.get("lane_key") or "")
    if lane_key:
        return lane_key
    return worker_lane_key({"machine_target": str(item.get("machine_target") or "")})


def _promotion_candidates_by_lane(
    lane_entries: list[tuple[str, int, int, str]],
    promotion_candidates: list[dict[str, Any]],
    worker_lane_key: Callable[[dict[str, Any]], str],
) -> dict[str, list[dict[str, Any]]]:
    candidates_by_lane: dict[str, list[dict[str, Any]]] = {
        lane_key: [] for lane_key, *_rest in lane_entries
    }
    for row in promotion_candidates:
        lane_key = worker_lane_key(
            {"machine_target": str(row.get("machine_target") or "")}
        )
        if lane_key in candidates_by_lane:
            candidates_by_lane[lane_key].append(row)
    return candidates_by_lane


def _open_lane_entries(
    lane_entries: list[tuple[str, int, int, str]],
    candidates_by_lane: dict[str, list[dict[str, Any]]],
) -> list[tuple[str, int, int, str]]:
    return [
        entry
        for entry in lane_entries
        if entry[2] <= 0 and candidates_by_lane[entry[0]]
    ]


def _promotion_success_count(promoted: list[dict[str, Any]]) -> int:
    return sum(
        1 for item in promoted if item.get("ok") and not item.get("already_promoted")
    )


def _record_promotion_stage(
    response: dict[str, Any], *, promoted: list[dict[str, Any]]
) -> None:
    response["promotions"] = promoted
    response["promoted_count"] = _promotion_success_count(promoted)
    response["queued_count"] = sum(
        int(item.get("queued_count") or 0) for item in promoted
    )
    response["stages"].append(
        {
            "stage": "promotion",
            "ok": True,
            "promoted_count": response["promoted_count"],
            "queued_count": response["queued_count"],
        }
    )


def _dispatch_promoted_until_cap(
    *,
    promoted: list[dict[str, Any]],
    max_dispatches: int,
    response: dict[str, Any],
    dispatch_queued_project: Callable[[str], bool],
) -> None:
    if not max_dispatches or not promoted:
        return
    for item in promoted:
        if int(response.get("dispatched_count") or 0) >= max_dispatches:
            break
        project_id = str(item.get("idea_id") or item.get("candidate_id") or "").strip()
        if project_id:
            dispatch_queued_project(project_id)


def _execute_promotion(
    *,
    promotable_rows: Callable[[], list[dict[str, Any]]],
    open_lane_research_rows: Callable,
    max_promotions: int,
    max_dispatches: int,
    store: Any,
    requested_by: str,
    response: dict[str, Any],
    _worker_lane_key: Callable,
    dispatch_queued_project: Callable[[str], bool],
    operator_trace: OperatorTrace | None = None,
    trace_id: str = "",
    run_cycle_id: str = "",
) -> dict[str, Any]:
    """Extracted from dashboard_research_run_cycle (self-contained promotion loop contributing to 1595/remaining S3776).

    Filters open_lane promotable candidates, calls store.promote_research_candidate for up to max_promotions,
    captures the promoted list, updates response counts/stages, and dispatches promoted items if dispatch capacity remains.
    Thin delegation left in the giant.
    """
    promoted: list[dict[str, Any]] = []
    if not response.get("fresh_promotion_skipped"):
        raw_promotion_candidates = promotable_rows()
        lane_feed_pressure = response.get("lane_feed_pressure") or {}
        promotion_candidates = _lane_feed_limited_promotion_candidates(
            promotion_candidates=raw_promotion_candidates,
            lane_feed_pressure=lane_feed_pressure
            if isinstance(lane_feed_pressure, dict)
            else {},
            worker_lane_key=_worker_lane_key,
        )
        if not lane_feed_pressure:
            promotion_candidates = _resolve_open_lane_promotion_candidates(
                promotable_rows=lambda: raw_promotion_candidates,
                open_lane_research_rows=open_lane_research_rows,
                store=store,
                _worker_lane_key=_worker_lane_key,
            )
        promoted = _promote_research_rows(
            store=store,
            promotion_candidates=promotion_candidates,
            max_promotions=max_promotions,
            requested_by=requested_by,
        )
        _record_promotion_stage(response, promoted=promoted)
        if operator_trace is not None:
            promoted_rows = [
                item.get("candidate")
                if isinstance(item.get("candidate"), dict)
                else item
                for item in promoted
                if isinstance(item, dict)
            ]
            operator_trace.record(
                "research.promotion.result",
                trace_id=trace_id,
                run_cycle_id=run_cycle_id,
                requested_by=requested_by,
                promoted_count=response.get("promoted_count"),
                queued_count=response.get("queued_count"),
                promoted_by_machine_target=count_by_key(
                    promoted_rows, "machine_target"
                ),
            )
    else:
        response["promotions"] = promoted
        response["promoted_count"] = 0

    _dispatch_promoted_until_cap(
        promoted=promoted,
        max_dispatches=max_dispatches,
        response=response,
        dispatch_queued_project=dispatch_queued_project,
    )
    return response


def _dispatch_queued_project(
    project_id: str,
    *,
    store: Any,
    response: dict[str, Any],
    requested_by: str,
    _live_dispatch: Callable,
    jsonable_encoder: Callable,
    operator_trace: OperatorTrace | None = None,
    trace_id: str = "",
    run_cycle_id: str = "",
) -> bool:
    """Extracted from dashboard_research_run_cycle (self-contained dispatch helper contributing to 1595/remaining S3776).

    Handles claim, live_dispatch with 409 backpressure handling, heavy response mutation
    (dispatch_started, dispatched_count, dispatch record, stages, dispatches list), and returns success.
    Thin delegation wrapper left in the giant so all call sites remain unchanged.
    """
    candidate = store.queue_row(project_id)
    if not candidate or str(candidate.get("status") or "") != "queued":
        _record_dispatch_not_dispatchable(response, project_id)
        return False

    machine_target = str(candidate.get("machine_target") or "")
    _record_dispatch_attempt(
        operator_trace=operator_trace,
        trace_id=trace_id,
        run_cycle_id=run_cycle_id,
        requested_by=requested_by,
        project_id=project_id,
        candidate=candidate,
        machine_target=machine_target,
    )
    try:
        live, event_id, updated_candidate = _live_dispatch(
            candidate, requested_by, force_preflight=True, allow_paused=True
        )
    except HTTPException as exc:
        if int(exc.status_code) != 409:
            raise
        _record_dispatch_backpressure(
            response=response,
            operator_trace=operator_trace,
            trace_id=trace_id,
            run_cycle_id=run_cycle_id,
            requested_by=requested_by,
            project_id=project_id,
            candidate=candidate,
            machine_target=machine_target,
            exc=exc,
            jsonable_encoder=jsonable_encoder,
        )
        return False

    _record_dispatch_success(
        response=response,
        operator_trace=operator_trace,
        trace_id=trace_id,
        run_cycle_id=run_cycle_id,
        requested_by=requested_by,
        project_id=project_id,
        machine_target=machine_target,
        live=live,
        event_id=event_id,
        updated_candidate=updated_candidate,
    )
    return True


def _record_dispatch_not_dispatchable(
    response: dict[str, Any], project_id: str
) -> None:
    response["stages"].append(
        {
            "stage": "dispatch",
            "ok": False,
            "reason": "queued project was not dispatchable",
            "project_id": project_id,
        }
    )


def _record_dispatch_attempt(
    *,
    operator_trace: OperatorTrace | None,
    trace_id: str,
    run_cycle_id: str,
    requested_by: str,
    project_id: str,
    candidate: dict[str, Any],
    machine_target: str,
) -> None:
    if operator_trace is None:
        return
    operator_trace.record(
        "research.dispatch_attempt",
        trace_id=trace_id,
        run_cycle_id=run_cycle_id,
        requested_by=requested_by,
        project_id=project_id,
        run_id=str(candidate.get("current_run_id") or ""),
        machine_target=machine_target,
        status=candidate.get("status"),
    )


def _record_dispatch_backpressure(
    *,
    response: dict[str, Any],
    operator_trace: OperatorTrace | None,
    trace_id: str,
    run_cycle_id: str,
    requested_by: str,
    project_id: str,
    candidate: dict[str, Any],
    machine_target: str,
    exc: HTTPException,
    jsonable_encoder: Callable[[Any], Any],
) -> None:
    detail = jsonable_encoder(exc.detail)
    if operator_trace is not None:
        operator_trace.record(
            "research.dispatch_result",
            trace_id=trace_id,
            run_cycle_id=run_cycle_id,
            requested_by=requested_by,
            project_id=project_id,
            machine_target=machine_target,
            backpressure=True,
            status_code=exc.status_code,
            detail=detail,
        )
    response["dispatch"] = {
        "event_id": None,
        "candidate": candidate,
        "live": None,
        "backpressure": True,
        "detail": detail,
    }
    response["stages"].append(
        {
            "stage": "dispatch",
            "ok": True,
            "action": "dispatch_backpressure",
            "project_id": project_id,
            "reason": "dispatch conflict/backpressure; queued work remains safe for the queue pump or next tick",
            "detail": detail,
        }
    )


def _record_dispatch_success(
    *,
    response: dict[str, Any],
    operator_trace: OperatorTrace | None,
    trace_id: str,
    run_cycle_id: str,
    requested_by: str,
    project_id: str,
    machine_target: str,
    live: Any,
    event_id: str,
    updated_candidate: dict[str, Any],
) -> None:
    response["dispatch_started"] = True
    response["dispatched_count"] = int(response.get("dispatched_count") or 0) + 1
    dispatch_record = {
        "event_id": event_id,
        "candidate": updated_candidate,
        "live": live,
    }
    response["dispatch"] = dispatch_record
    response.setdefault("dispatches", []).append(dispatch_record)
    if operator_trace is not None:
        operator_trace.record(
            "research.dispatch_result",
            trace_id=trace_id,
            run_cycle_id=run_cycle_id,
            requested_by=requested_by,
            project_id=project_id,
            run_id=str(updated_candidate.get("current_run_id") or ""),
            machine_target=str(
                updated_candidate.get("machine_target") or machine_target
            ),
            event_id=event_id,
            backpressure=False,
        )
    response["stages"].append(
        {
            "stage": "dispatch",
            "ok": True,
            "project_id": project_id,
            "event_id": event_id,
        }
    )


_RESEARCH_CYCLE_BUDGET_RESPONSE_KEYS = frozenset(
    {
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
        "failures",
    }
)


def _fetch_synthetic_research_budget(
    *,
    provider_base_url: str,
    estimated_requests: int,
    bounded_int: Callable[[str, int, int, int], int],
    bounded_float: Callable[[str, float, float, float], float],
    research_provider_budget: Any,
) -> dict[str, Any]:
    """Extracted from dashboard_research_run_cycle (budget try/except path contributing to S3776)."""
    try:
        reserve_requests = bounded_int("reserve_requests", 2, 1, 100)
        quota_payload = research_provider_budget.fetch_json(
            f"{provider_base_url}/v2/quotas",
            api_key="",
            timeout=bounded_int("budget_timeout", 20, 1, 60),
        )
        return research_provider_budget.synthetic_budget_status(
            quota_payload,
            min_remaining_credits=bounded_float(
                "min_remaining_credits", 5.0, 0.0, 1_000_000.0
            ),
            min_rolling_remaining=bounded_int("min_rolling_remaining", 10, 0, 100_000),
            estimated_requests=estimated_requests,
            reserve_requests=reserve_requests,
        )
    except Exception as exc:  # noqa: BLE001 - fail closed if budget cannot be checked
        return {
            "ok": False,
            "provider": "synthetic",
            "checked_at": utc_now(),
            "estimated_requests": estimated_requests,
            "reserve_requests": bounded_int("reserve_requests", 2, 1, 100),
            "failures": [f"provider budget check failed: {exc}"],
        }


def _collect_research_cycle_stop_reasons(
    *,
    body: dict[str, Any],
    dry_run: bool,
    enabled: bool,
    blocked_count: int,
    budget: dict[str, Any],
    max_provider_requests: int,
    backpressure_reasons: list[str],
) -> list[str]:
    """Extracted from dashboard_research_run_cycle (stop_reason assembly contributing to S3776)."""
    stop_reasons: list[str] = []
    if blocked_count and bool(body.get("stop_if_dashboard_attention", True)):
        stop_reasons.append(f"{blocked_count} blocked item(s) need attention")
    if not dry_run and not enabled:
        stop_reasons.append("live run-cycle requires enabled=true")
    if not budget.get("ok") and max_provider_requests and not backpressure_reasons:
        stop_reasons.append(
            "; ".join(
                str(item)
                for item in budget.get("failures") or ["provider budget unavailable"]
            )
        )
    return stop_reasons


def _evaluate_research_cycle_backpressure(
    *,
    active: list[dict[str, Any]],
    initial_open_lane_promotable: list[dict[str, Any]],
    generation_target_lane: Any,
    max_provider_requests: int,
    idle_queued_lane_available: bool = False,
) -> list[str]:
    """Extracted from dashboard_research_run_cycle (lane backpressure gate contributing to S3776)."""
    if (
        active
        and not initial_open_lane_promotable
        and not (generation_target_lane and max_provider_requests)
        and not idle_queued_lane_available
    ):
        return [
            "active worker lane already exists and no promotable candidate targets an idle lane"
        ]
    return []


def _research_cycle_idle_queued_lane_available(
    *, lanes: list[dict[str, Any]], max_dispatches: int
) -> bool:
    """Return whether live/dry research cycle capacity can dispatch an idle queued lane."""
    if max_dispatches <= 0:
        return False
    return any(
        bool(lane.get("dispatch_available"))
        and bool((lane.get("next_candidate") or {}).get("project_id"))
        for lane in lanes
        if isinstance(lane, dict)
    )


@dataclass(frozen=True)
class _ResearchCycleInitialResponseParams:
    dry_run: bool
    enabled: bool
    provider_model: str
    allowed_models: list[str]
    body: dict[str, Any]
    max_provider_requests: int
    max_promotions: int
    max_dispatches: int
    min_queue_depth_per_lane: int
    max_paper_drafts: int
    max_publication_rewrites: int
    min_admission_score: float
    wait_for_completion: bool
    max_wait_seconds: int
    fresh_generation_backlog_threshold: int
    janitor_enabled: bool
    janitor_limit: int
    janitor_report: dict[str, Any]
    budget: dict[str, Any]
    initial_promotable: list[dict[str, Any]]
    initial_open_lane_promotable: list[dict[str, Any]]
    lane_feed_pressure: dict[str, Any]
    generation_target_lane: Any
    stop_reasons: list[str]


def _build_research_cycle_initial_response(
    *,
    params: _ResearchCycleInitialResponseParams,
) -> dict[str, Any]:
    """Extracted from dashboard_research_run_cycle (large response skeleton contributing to S3776)."""
    return {
        "ok": not params.stop_reasons,
        "action": "dry_run_research_cycle" if params.dry_run else "research_cycle",
        "dry_run": params.dry_run,
        "enabled": params.enabled,
        "queue_admitted": False,
        "dispatch_started": False,
        "provider": "synthetic.new",
        "provider_model": params.provider_model,
        "allowed_models": params.allowed_models,
        "policy": {
            "max_provider_requests_per_run": params.max_provider_requests,
            "max_promotions_per_run": params.max_promotions,
            "max_dispatches_per_run": params.max_dispatches,
            "min_queue_depth_per_lane": params.min_queue_depth_per_lane,
            "max_paper_drafts_per_run": params.max_paper_drafts,
            "max_publication_rewrites_per_run": params.max_publication_rewrites,
            "min_admission_score": params.min_admission_score,
            "require_budget_ok": True,
            "stop_if_queue_active": True,
            "stop_if_dashboard_attention": bool(
                params.body.get("stop_if_dashboard_attention", True)
            ),
            "wait_for_completion": params.wait_for_completion,
            "max_wait_seconds": params.max_wait_seconds,
            "fresh_generation_backlog_threshold": params.fresh_generation_backlog_threshold,
            "janitor_enabled": params.janitor_enabled,
            "janitor_limit": params.janitor_limit,
        },
        "janitor": params.janitor_report,
        "budget": {
            key: params.budget.get(key)
            for key in _RESEARCH_CYCLE_BUDGET_RESPONSE_KEYS
            if key in params.budget
        },
        "initial_promotable_count": len(params.initial_promotable),
        "planned_promotions": [
            row.get("candidate_id")
            for row in (
                params.initial_open_lane_promotable or params.initial_promotable
            )[: params.max_promotions]
        ],
        "open_lane_promotable_count": len(params.initial_open_lane_promotable),
        "lane_feed_pressure": params.lane_feed_pressure,
        "generation_target_lane": params.generation_target_lane,
        "generated_count": 0,
        "promoted_count": 0,
        "dispatched_count": 0,
        "queued_count": 0,
        "stages": [],
    }


def _append_research_cycle_queue_paused_guardrail(
    *,
    store: Any,
    response: dict[str, Any],
    dry_run: bool,
    requested_by: str,
) -> None:
    """Extracted from dashboard_research_run_cycle (queue-paused guardrail contributing to S3776)."""
    flags = store.flags() if hasattr(store, "flags") else None
    queue_paused = bool(getattr(flags, "queue_paused", False))
    if dry_run or not queue_paused:
        return
    guardrail = "research autopilot is active but broad queue is paused"
    response.setdefault("guardrails", []).append(guardrail)
    if hasattr(store, "append_event"):
        store.append_event(
            idempotency_key=f"research-guardrail:queue-paused:{requested_by}:{utc_now()}",
            event_type="research.guardrail.queue_paused",
            entity_type="research",
            entity_id="run-cycle",
            payload={
                "message": guardrail,
                "queue_paused": True,
                "dry_run": dry_run,
                "requested_by": requested_by,
            },
        )


def _append_research_run_cycle_event_if_supported(
    store: Any,
    *,
    idempotency_key: str,
    event_type: str,
    payload: Mapping[str, Any],
) -> None:
    if not hasattr(store, "append_event"):
        return
    store.append_event(
        idempotency_key=idempotency_key,
        event_type=event_type,
        entity_type="research",
        entity_id="run-cycle",
        payload=jsonable_encoder(payload),
    )


def _research_cycle_live_mode_label(*, dry_run: bool) -> str:
    return "dry" if dry_run else "live"


def _operator_trace_queue_findings(
    findings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    summarized: list[dict[str, Any]] = []
    for finding in findings[:10]:
        if not isinstance(finding, dict):
            continue
        data = finding.get("data") if isinstance(finding.get("data"), dict) else {}
        active_item = (
            data.get("active_item") if isinstance(data.get("active_item"), dict) else {}
        )
        summarized.append(
            {
                "severity": finding.get("severity"),
                "source": finding.get("source"),
                "message": finding.get("message"),
                "suggested_action": finding.get("suggested_action"),
                "machine_target": data.get("machine_target")
                or active_item.get("machine_target"),
                "lane_key": data.get("lane_key"),
                "project_id": active_item.get("project_id"),
                "run_id": active_item.get("current_run_id"),
            }
        )
    return summarized


def _research_cycle_blocked_early_response(
    *,
    store: Any,
    response: dict[str, Any],
    dry_run: bool,
    requested_by: str,
    stop_reasons: list[str],
) -> dict[str, Any]:
    response["reason"] = "; ".join(stop_reasons)
    mode = _research_cycle_live_mode_label(dry_run=dry_run)
    _append_research_run_cycle_event_if_supported(
        store,
        idempotency_key=f"research-cycle:{mode}:{requested_by}:{utc_now()}",
        event_type="research.run_cycle.blocked",
        payload=response,
    )
    return response


def _research_cycle_backpressure_early_response(
    *,
    store: Any,
    response: dict[str, Any],
    dry_run: bool,
    requested_by: str,
    backpressure_reasons: list[str],
    active: list[dict[str, Any]],
) -> dict[str, Any]:
    response["ok"] = True
    response["action"] = (
        "dry_run_research_cycle_backpressure"
        if dry_run
        else "research_cycle_backpressure"
    )
    response["reason"] = "; ".join(backpressure_reasons)
    response["backpressure"] = True
    response["active_count"] = len(active)
    response["stages"].append(
        {
            "stage": "backpressure",
            "ok": True,
            "reason": response["reason"],
            "active_count": len(active),
        }
    )
    if not hasattr(store, "append_event"):
        return response
    mode = _research_cycle_live_mode_label(dry_run=dry_run)
    try:
        store.append_event(
            idempotency_key=(
                f"research-cycle:backpressure:{mode}:{requested_by}:"
                f"{_active_lane_signature(active)}:{_event_cooldown_bucket()}"
            ),
            event_type="research.run_cycle.backpressure",
            entity_type="research",
            entity_id="run-cycle",
            payload=jsonable_encoder(response),
        )
    except IdempotencyConflict as exc:
        response["event_write_suppressed"] = "idempotency_conflict"
        response["event_write_suppressed_reason"] = str(exc)
    return response


def _research_cycle_dry_run_early_response(
    *,
    store: Any,
    response: dict[str, Any],
    requested_by: str,
    wait_for_completion: bool,
    max_wait_seconds: int,
    cycle_limits: Mapping[str, int],
) -> dict[str, Any]:
    response["reason"] = (
        "dry-run only; provider was not called and no ledgers, queue rows, "
        "dispatches, or papers were written"
    )
    response["would_generate"] = cycle_limits["max_provider_requests"] > 0
    response["would_promote_up_to"] = cycle_limits["max_promotions"]
    response["would_dispatch_up_to"] = cycle_limits["max_dispatches"]
    response["would_wait_for_completion"] = wait_for_completion and max_wait_seconds > 0
    response["would_draft_papers_up_to"] = cycle_limits["max_paper_drafts"]
    response["would_finalize_papers_up_to"] = cycle_limits["max_publication_rewrites"]
    _append_research_run_cycle_event_if_supported(
        store,
        idempotency_key=f"research-cycle:dry:{requested_by}:{utc_now()}",
        event_type="research.run_cycle.dry_run",
        payload=response,
    )
    return response


def _research_cycle_pre_live_exit(
    *,
    store: Any,
    response: dict[str, Any],
    dry_run: bool,
    requested_by: str,
    stop_reasons: list[str],
    backpressure_reasons: list[str],
    active: list[dict[str, Any]],
    wait_for_completion: bool,
    max_wait_seconds: int,
    cycle_limits: Mapping[str, int],
) -> dict[str, Any] | None:
    """Extracted from dashboard_research_run_cycle (stop/backpressure/dry-run exits contributing to S3776).

    Returns a response dict when the handler should return early; None to continue to live execution.
    """
    if stop_reasons:
        return _research_cycle_blocked_early_response(
            store=store,
            response=response,
            dry_run=dry_run,
            requested_by=requested_by,
            stop_reasons=stop_reasons,
        )
    if backpressure_reasons:
        return _research_cycle_backpressure_early_response(
            store=store,
            response=response,
            dry_run=dry_run,
            requested_by=requested_by,
            backpressure_reasons=backpressure_reasons,
            active=active,
        )
    if dry_run:
        return _research_cycle_dry_run_early_response(
            store=store,
            response=response,
            requested_by=requested_by,
            wait_for_completion=wait_for_completion,
            max_wait_seconds=max_wait_seconds,
            cycle_limits=cycle_limits,
        )
    return None


def _dispatch_wait_in_progress_statuses() -> frozenset[str]:
    return frozenset(
        {
            "dispatching",
            "running",
            "awaiting_wake",
            "wake_received",
            "reconciling",
        }
    )


def _dispatch_wait_still_active(
    *, active_now: list[dict[str, Any]], last_status: str
) -> bool:
    if active_now:
        return True
    return last_status in _dispatch_wait_in_progress_statuses()


def _poll_dispatch_completion(
    *,
    store: Any,
    dispatched_project_id: str,
    deadline: float,
    poll_interval_seconds: int,
    refill_idle_lanes: Callable[[], int] | None = None,
) -> dict[str, Any]:
    """Poll queue status until dispatch completes or the deadline is reached."""
    polls = 0
    last_status = ""
    refill_dispatches = 0
    while True:
        polls += 1
        row = store.queue_row(dispatched_project_id) if dispatched_project_id else None
        active_now = store.active_items()
        last_status = str((row or {}).get("status") or "")
        if not _dispatch_wait_still_active(
            active_now=active_now, last_status=last_status
        ):
            return {
                "action": "completed",
                "project_id": dispatched_project_id,
                "status": last_status,
                "polls": polls,
                "refill_dispatches": refill_dispatches,
            }
        if time.monotonic() >= deadline:
            return {
                "action": "timeout",
                "project_id": dispatched_project_id,
                "status": last_status,
                "active_count": len(active_now),
                "polls": polls,
                "refill_dispatches": refill_dispatches,
            }
        if refill_idle_lanes is not None:
            refill_dispatches += max(0, int(refill_idle_lanes() or 0))
        time.sleep(poll_interval_seconds)


def _wait_for_completion(
    *,
    store: Any,
    response: dict[str, Any],
    wait_for_completion: bool,
    max_wait_seconds: int,
    poll_interval_seconds: int,
    refill_idle_lanes: Callable[[], int] | None = None,
) -> dict[str, Any]:
    """Extracted from dashboard_research_run_cycle (polling loop contributing to S3776).

    Polls queue status until the dispatched project leaves active states or times out.
    Mutates response with wait stage when polling runs.
    """
    wait_result: dict[str, Any] = {
        "action": "skipped",
        "reason": "wait_for_completion disabled",
    }
    if not (response.get("dispatch_started") and wait_for_completion):
        return wait_result
    if max_wait_seconds <= 0:
        wait_result = {"action": "skipped", "reason": "max_wait_seconds is 0"}
    else:
        dispatched_project_id = str(
            (response.get("dispatch", {}).get("candidate") or {}).get("project_id")
            or ""
        )
        deadline = time.monotonic() + max_wait_seconds
        wait_result = _poll_dispatch_completion(
            store=store,
            dispatched_project_id=dispatched_project_id,
            deadline=deadline,
            poll_interval_seconds=poll_interval_seconds,
            refill_idle_lanes=refill_idle_lanes,
        )
    response["wait"] = wait_result
    response["stages"].append({"stage": "wait_for_completion", **wait_result})
    return wait_result


def _refill_idle_lanes_during_wait(
    *,
    params: _LiveResearchCycleParams,
    response: dict[str, Any],
    dispatch_queued_project: Callable[[str], bool],
) -> int:
    remaining_refills = max(
        0,
        params.max_dispatches - int(response.get("dispatched_count") or 0),
    )
    if remaining_refills <= 0:
        return 0
    lanes = params.worker_lane_capacity(
        active=params.store.active_items(), rows=params.queue_rows_for_lane_feed()
    )
    dispatched = _dispatch_lane_project_ids(
        lanes=lanes,
        remaining=remaining_refills,
        dispatch_queued_project=dispatch_queued_project,
    )
    if not dispatched:
        return 0
    response["wait_refill_dispatch_count"] = (
        int(response.get("wait_refill_dispatch_count") or 0) + dispatched
    )
    response["stages"].append(
        {
            "stage": "wait_refill_idle_lanes",
            "ok": True,
            "dispatched_count": dispatched,
        }
    )
    return dispatched


def _paper_rewrite_error_stage(paper_id: str, exc: Exception) -> dict[str, Any]:
    if isinstance(exc, PaperRewriteEvidenceRequiredError):
        return {
            "stage": "publication_finalization",
            "ok": False,
            "paper_id": paper_id,
            "status_code": 424,
            "reason": "paper rewrite requires synced project evidence",
            "error_type": type(exc).__name__,
            "evidence_sync": exc.evidence_sync,
        }
    status_code = 400
    if isinstance(exc, PublicationAutomationNotFoundError):
        status_code = 404
    elif isinstance(exc, (PaperRewriteIdempotencyReuseError, IdempotencyConflict)):
        status_code = 409
    return {
        "stage": "publication_finalization",
        "ok": False,
        "paper_id": paper_id,
        "status_code": status_code,
        "reason": str(exc),
        "error_type": type(exc).__name__,
    }


def _execute_research_paper_stages(
    *,
    store: Any,
    response: dict[str, Any],
    max_paper_drafts: int,
    max_publication_rewrites: int,
    wait_for_completion: bool,
    wait_result: dict[str, Any],
    requested_by: str,
    draft_next: Callable[..., Any],
    rewrite_paper_review_draft: Callable[..., Any],
    control_api_bearer_token: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Extracted from dashboard_research_run_cycle (paper draft/finalize loop contributing to S3776)."""
    drafted_papers: list[dict[str, Any]] = []
    finalized_papers: list[dict[str, Any]] = []
    if not max_paper_drafts:
        return drafted_papers, finalized_papers
    if (
        response.get("dispatch_started")
        and wait_for_completion
        and wait_result.get("action") != "completed"
    ):
        response["stages"].append(
            {
                "stage": "paper_draft",
                "ok": False,
                "reason": "dispatched work did not complete inside this bounded run; paper stage skipped",
                "wait": wait_result,
            }
        )
        return drafted_papers, finalized_papers
    if store.active_items():
        response["stages"].append(
            {
                "stage": "paper_draft",
                "ok": False,
                "reason": "active worker lane exists; paper stage skipped",
            }
        )
        return drafted_papers, finalized_papers
    for draft_index in range(max_paper_drafts):
        draft_response = draft_next(
            DraftNextRequest(force=False, requested_by=requested_by, dry_run=False),
            authorization=f"Bearer {control_api_bearer_token}",
        )
        draft_payload = draft_response.model_dump(mode="json")
        drafted_papers.append(draft_payload)
        response["stages"].append(
            {
                "stage": "paper_draft",
                "ok": draft_response.ok,
                "action": draft_response.action,
                "reason": draft_response.reason,
            }
        )
        if draft_response.action != "drafted" or draft_response.paper is None:
            break
        if len(finalized_papers) < max_publication_rewrites:
            paper_id = draft_response.paper.paper_id
            try:
                rewrite_response = rewrite_paper_review_draft(
                    paper_id,
                    PaperReviewRewriteDraftRequest(
                        idempotency_key=f"research-cycle:{requested_by}:{draft_index}:{paper_id}:{utc_now()}",
                        requested_by=requested_by,
                        force=True,
                    ),
                )
            except (
                PublicationAutomationNotFoundError,
                PaperArtifactRootNotInspectableError,
                PaperRewriteEvidenceRequiredError,
                ValueError,
            ) as exc:
                response["stages"].append(_paper_rewrite_error_stage(paper_id, exc))
                break
            rewrite_payload = rewrite_response.model_dump(mode="json")
            finalized_papers.append(rewrite_payload)
            response["stages"].append(
                {
                    "stage": "publication_finalization",
                    "ok": rewrite_response.ok,
                    "paper_id": paper_id,
                    "event_id": rewrite_response.event_id,
                    "review_status": str(
                        (rewrite_payload.get("item") or {}).get("review_status") or ""
                    ),
                }
            )
    return drafted_papers, finalized_papers


@dataclass(frozen=True)
class _LiveResearchCycleParams:
    store: Any
    requested_by: str
    generation_target_lane: Any
    initial_feed_lanes: list[dict[str, Any]]
    max_dispatches: int
    max_provider_requests: int
    fresh_generation_backlog_threshold: int
    initial_promotable: list[dict[str, Any]]
    promotable_rows: Callable[[], list[dict[str, Any]]]
    open_lane_research_rows: Callable[..., list[dict[str, Any]]]
    max_promotions: int
    provider_openai_base_url: str
    provider_model: str
    max_candidates: int
    topic: str
    temperature: float
    seed: str
    generation_timeout: int
    generation_max_tokens: int
    generation_attempts: int
    min_admission_score: float
    bounded_float: Callable[[str, float, float, float], float]
    namespace_cls: Any
    research_provider_generate: Any
    research_facility: Any
    wait_for_completion: bool
    max_wait_seconds: int
    poll_interval_seconds: int
    max_paper_drafts: int
    max_publication_rewrites: int
    draft_next: Callable[..., Any]
    rewrite_paper_review_draft: Callable[..., Any]
    control_api_bearer_token: str
    worker_lane_key: Callable[[dict[str, Any]], str]
    worker_lane_capacity: Callable[..., list[dict[str, Any]]]
    queue_rows_for_lane_feed: Callable[[], list[dict[str, Any]]]
    live_dispatch: Callable[..., Any]
    jsonable_encoder: Callable[..., Any]
    research_row_lane_key: Callable[[dict[str, Any]], str]
    provider_api_key: str = ""
    operator_trace: OperatorTrace | None = None
    trace_id: str = ""
    run_cycle_id: str = ""


def _lane_dispatch_project_id(lane: dict[str, Any]) -> str:
    if not lane.get("dispatch_available"):
        return ""
    candidate = lane.get("next_candidate")
    if not isinstance(candidate, dict):
        return ""
    return str(candidate.get("project_id") or "")


def _dispatch_lane_project_ids(
    *,
    lanes: list[dict[str, Any]],
    remaining: int,
    dispatch_queued_project: Callable[[str], bool],
) -> int:
    dispatched = 0
    seen: set[str] = set()
    for lane in lanes:
        if dispatched >= remaining or not isinstance(lane, dict):
            break
        project_id = _lane_dispatch_project_id(lane)
        if not project_id or project_id in seen:
            continue
        seen.add(project_id)
        if dispatch_queued_project(project_id):
            dispatched += 1
    return dispatched


def _dispatch_idle_lane_queued_candidates(
    *,
    lanes: list[dict[str, Any]],
    max_dispatches: int,
    response: dict[str, Any],
    dispatch_queued_project: Callable[[str], bool],
) -> int:
    """Dispatch already-queued candidates on idle lanes before feed/generation work.

    The research autopilot should treat lanes independently: an active GB10 lane
    must not suppress a queued CPU lane.  This helper consumes the bounded lane
    read model produced before the live cycle and dispatches at most the
    remaining per-cycle dispatch capacity.
    """
    remaining = max(0, max_dispatches - int(response.get("dispatched_count") or 0))
    if remaining <= 0:
        return 0
    return _dispatch_lane_project_ids(
        lanes=lanes,
        remaining=remaining,
        dispatch_queued_project=dispatch_queued_project,
    )


def _execute_live_research_cycle(
    *,
    params: _LiveResearchCycleParams,
    response: dict[str, Any],
) -> dict[str, Any]:
    """Extracted from dashboard_research_run_cycle (live path orchestration contributing to S3776)."""

    def dispatch_queued_project(project_id: str) -> bool:
        return _dispatch_queued_project(
            project_id,
            store=params.store,
            response=response,
            requested_by=params.requested_by,
            _live_dispatch=params.live_dispatch,
            jsonable_encoder=params.jsonable_encoder,
            operator_trace=params.operator_trace,
            trace_id=params.trace_id,
            run_cycle_id=params.run_cycle_id,
        )

    _dispatch_idle_lane_queued_candidates(
        lanes=params.initial_feed_lanes,
        max_dispatches=params.max_dispatches,
        response=response,
        dispatch_queued_project=dispatch_queued_project,
    )
    remaining_dispatches = max(
        0, params.max_dispatches - int(response.get("dispatched_count") or 0)
    )

    response = _handle_followup_and_early_skips(
        store=params.store,
        generation_target_lane=params.generation_target_lane,
        max_dispatches=remaining_dispatches,
        max_provider_requests=params.max_provider_requests,
        fresh_generation_backlog_threshold=params.fresh_generation_backlog_threshold,
        initial_promotable=params.initial_promotable,
        response=response,
        requested_by=params.requested_by,
        dispatch_queued_project=dispatch_queued_project,
        research_row_lane_key=params.research_row_lane_key,
    )
    response = _execute_provider_generation(
        params=_ProviderGenerationParams(
            max_provider_requests=params.max_provider_requests,
            generation_target_lane=params.generation_target_lane,
            provider_openai_base_url=params.provider_openai_base_url,
            provider_api_key=params.provider_api_key,
            provider_model=params.provider_model,
            max_candidates=params.max_candidates,
            topic=params.topic,
            temperature=params.temperature,
            seed=params.seed,
            generation_timeout=params.generation_timeout,
            generation_max_tokens=params.generation_max_tokens,
            generation_attempts=params.generation_attempts,
            min_admission_score=params.min_admission_score,
            bounded_float=params.bounded_float,
            namespace_cls=params.namespace_cls,
            research_provider_generate=params.research_provider_generate,
            research_facility=params.research_facility,
            store=params.store,
            requested_by=params.requested_by,
            operator_trace=params.operator_trace,
            trace_id=params.trace_id,
            run_cycle_id=params.run_cycle_id,
        ),
        response=response,
    )

    response = _execute_promotion(
        promotable_rows=params.promotable_rows,
        open_lane_research_rows=params.open_lane_research_rows,
        max_promotions=params.max_promotions,
        max_dispatches=params.max_dispatches,
        store=params.store,
        requested_by=params.requested_by,
        response=response,
        _worker_lane_key=params.worker_lane_key,
        dispatch_queued_project=dispatch_queued_project,
        operator_trace=params.operator_trace,
        trace_id=params.trace_id,
        run_cycle_id=params.run_cycle_id,
    )
    wait_result = _wait_for_completion(
        store=params.store,
        response=response,
        wait_for_completion=params.wait_for_completion,
        max_wait_seconds=params.max_wait_seconds,
        poll_interval_seconds=params.poll_interval_seconds,
        refill_idle_lanes=partial(
            _refill_idle_lanes_during_wait,
            params=params,
            response=response,
            dispatch_queued_project=dispatch_queued_project,
        ),
    )
    drafted_papers, finalized_papers = _execute_research_paper_stages(
        store=params.store,
        response=response,
        max_paper_drafts=params.max_paper_drafts,
        max_publication_rewrites=params.max_publication_rewrites,
        wait_for_completion=params.wait_for_completion,
        wait_result=wait_result,
        requested_by=params.requested_by,
        draft_next=params.draft_next,
        rewrite_paper_review_draft=params.rewrite_paper_review_draft,
        control_api_bearer_token=params.control_api_bearer_token,
    )
    response["paper_drafts"] = drafted_papers
    response["paper_drafted_count"] = sum(
        1 for item in drafted_papers if item.get("action") == "drafted"
    )
    response["publication_finalizations"] = finalized_papers
    response["publication_finalized_count"] = len(finalized_papers)
    if params.operator_trace is not None:
        after_lanes = params.worker_lane_capacity(
            active=params.store.active_items(), rows=params.queue_rows_for_lane_feed()
        )
        params.operator_trace.record(
            "research.lanes.after",
            trace_id=params.trace_id,
            run_cycle_id=params.run_cycle_id,
            requested_by=params.requested_by,
            lanes=summarize_lane_snapshot(after_lanes),
        )
        params.operator_trace.record(
            "research.run_cycle.end",
            trace_id=params.trace_id,
            run_cycle_id=params.run_cycle_id,
            requested_by=params.requested_by,
            generated_count=response.get("generated_count"),
            promoted_count=response.get("promoted_count"),
            dispatched_count=response.get("dispatched_count"),
            paper_drafted_count=response.get("paper_drafted_count"),
            publication_finalized_count=response.get("publication_finalized_count"),
            reason=response.get("reason"),
        )
    if not response.get("reason"):
        response["reason"] = (
            "bounded research cycle completed; broad queue pause preserved and paper stages were positive-gated"
        )
    if hasattr(params.store, "append_event"):
        params.store.append_event(
            idempotency_key=f"research-cycle:live:{params.requested_by}:{utc_now()}",
            event_type="research.run_cycle.live",
            entity_type="research",
            entity_id="run-cycle",
            payload=params.jsonable_encoder(response),
        )
    return response


def _research_row_lane_key(
    worker_lane_key: Callable[[dict[str, Any]], str], row: dict[str, Any]
) -> str:
    """Map a research workbench row to a worker lane key (extracted from dashboard_research_run_cycle)."""
    return worker_lane_key({"machine_target": str(row.get("machine_target") or "")})


def research_row_lane_key(row: dict[str, Any]) -> str:
    """Default top-level lane key for direct callers that lack config context."""
    return str(row.get("machine_target") or "").strip()


def open_lane_research_rows(
    rows: list[dict[str, Any]],
    active_lane_keys: set[str],
    *,
    lane_key_func: Callable[[dict[str, Any]], str] | None = None,
) -> list[dict[str, Any]]:
    """Top-level version of the open-lane filter (extracted from the giant for reduced cognitive complexity).

    Accepts lane_key_func for exact semantics and testability (matches the original history extraction).
    """
    if not active_lane_keys:
        return rows
    if lane_key_func is None:
        lane_key_func = research_row_lane_key
    return [row for row in rows if lane_key_func(row) not in active_lane_keys]


def _research_lane_feed_pressure_label(machine_target: str, worker_role: Any) -> str:
    machine_lower = machine_target.lower()
    role_lower = str(worker_role or "").lower()
    if "gb10" in machine_lower or "gpu" in role_lower:
        return "GB10 lane"
    if "cpu" in machine_lower or "cpu" in role_lower:
        return "CPU lane"
    return f"{machine_target or 'default'} lane"


def _research_lane_generation_target_label(machine_target: str) -> str:
    machine_lower = machine_target.lower()
    if "gb10" in machine_lower:
        return "GB10"
    if "cpu" in machine_lower:
        return "CPU"
    return machine_target or "default"


def _promotable_rows_for_lane_feed_from_store(
    store: Any,
    *,
    min_admission_score: float,
) -> list[dict[str, Any]]:
    if not hasattr(store, "research_facility_workbench_projection"):
        return []
    try:
        workbench_rows = list(store.research_facility_workbench_projection(limit=100))  # type: ignore[attr-defined]
    except Exception:
        return []
    return [
        row
        for row in workbench_rows
        if str(row.get("admission_decision") or "") == "admitted"
        and not str(row.get("admitted_idea_id") or "").strip()
        and float(row.get("total_score") or 0) >= min_admission_score
    ]


def _rows_by_worker_lane_key(
    rows: list[dict[str, Any]],
    *,
    worker_lane_key: Callable[[dict[str, Any]], str],
    include_row: Callable[[dict[str, Any]], bool] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if include_row is not None and not include_row(row):
            continue
        grouped.setdefault(worker_lane_key(row), []).append(row)
    return grouped


def _research_lane_feed_autopilot_plan(
    *,
    label: str,
    queue_deficit: int,
    queued_count: int,
    active_count: int,
    promotable_count: int,
    min_queue_depth: int,
    machine_target: str,
) -> tuple[str, str]:
    if not queue_deficit:
        if queued_count > min_queue_depth:
            return (
                "queue_depth_satisfied",
                f"{label} is above desired queued depth {queued_count}/{min_queue_depth}; dispatch queued work before feeding more.",
            )
        return (
            "queue_depth_satisfied",
            f"{label} has queued depth {queued_count}/{min_queue_depth}; no feed action needed.",
        )
    if queued_count and not active_count:
        return (
            "dispatch_queued",
            f"{label} idle with queued work; autopilot should dispatch the queued candidate.",
        )
    if promotable_count:
        return (
            "promote_candidate",
            f"{label} needs queued depth {queued_count}/{min_queue_depth}; "
            f"autopilot should promote {promotable_count} admitted candidate(s).",
        )
    target_label = _research_lane_generation_target_label(machine_target)
    if queued_count:
        summary = (
            f"{label} active with queued depth {queued_count}/{min_queue_depth}; "
            f"autopilot should generate {target_label}-targeted work to fill the remaining deficit."
        )
    else:
        active_prefix = "idle " if not active_count else ""
        summary = (
            f"{label} {active_prefix}with no queued candidate; "
            f"autopilot should generate {target_label}-targeted work."
        )
    return ("generate_candidate", summary)


def _single_lane_feed_pressure_entry(
    lane: dict[str, Any],
    *,
    queued_by_lane: dict[str, list[dict[str, Any]]],
    promotable_by_lane: dict[str, list[dict[str, Any]]],
    min_queue_depth: int,
) -> tuple[str, dict[str, Any]]:
    lane_key = str(lane.get("lane_key") or "")
    machine_target = str(lane.get("machine_target") or "")
    label = _research_lane_feed_pressure_label(machine_target, lane.get("worker_role"))
    queued_count = len(queued_by_lane.get(lane_key, []))
    promotable_count = len(promotable_by_lane.get(lane_key, []))
    active_count = int(lane.get("active_count") or 0)
    queue_deficit = max(0, min_queue_depth - queued_count)
    if queued_count > min_queue_depth:
        queue_depth_status = "above_desired"
    elif queue_deficit:
        queue_depth_status = "below_desired"
    else:
        queue_depth_status = "at_desired"
    next_action, summary = _research_lane_feed_autopilot_plan(
        label=label,
        queue_deficit=queue_deficit,
        queued_count=queued_count,
        active_count=active_count,
        promotable_count=promotable_count,
        min_queue_depth=min_queue_depth,
        machine_target=machine_target,
    )
    pressure_key = machine_target or lane_key
    entry = {
        "lane_key": lane_key,
        "machine_target": machine_target,
        "worker_role": lane.get("worker_role"),
        "desired_queue_depth": min_queue_depth,
        "active_count": active_count,
        "queued_count": queued_count,
        "promotable_count": promotable_count,
        "queue_deficit": queue_deficit,
        "queue_depth_status": queue_depth_status,
        "above_desired_depth": queue_depth_status == "above_desired",
        "next_autopilot_action": next_action,
        "operator_summary": summary,
    }
    return pressure_key, entry


def _compute_research_lane_feed_pressure(
    *,
    active: list[dict[str, Any]],
    queued: list[dict[str, Any]] | None,
    lanes: list[dict[str, Any]] | None = None,
    promotable: list[dict[str, Any]] | None = None,
    min_queue_depth: int = 1,
    min_admission_score: float = 72.0,
    _worker_lane_capacity: Callable,
    _queue_rows_for_lane_feed: Callable,
    _queued_dispatch_candidates: Callable,
    _worker_lane_key: Callable,
    store: Any,
) -> dict[str, dict[str, Any]]:
    lane_rows = lanes or _worker_lane_capacity(active=active, rows=queued or [])
    queued_rows = list(queued if queued is not None else _queue_rows_for_lane_feed())
    if promotable is None:
        promotable_rows_for_feed = _promotable_rows_for_lane_feed_from_store(
            store, min_admission_score=min_admission_score
        )
    else:
        promotable_rows_for_feed = list(promotable)

    queued_by_lane = _rows_by_worker_lane_key(
        _queued_dispatch_candidates(queued_rows),
        worker_lane_key=_worker_lane_key,
    )
    promotable_by_lane = _rows_by_worker_lane_key(
        promotable_rows_for_feed,
        worker_lane_key=_worker_lane_key,
    )

    pressure: dict[str, dict[str, Any]] = {}
    min_queue_depth = max(0, min(int(min_queue_depth), 100))
    for lane in lane_rows:
        pressure_key, entry = _single_lane_feed_pressure_entry(
            lane,
            queued_by_lane=queued_by_lane,
            promotable_by_lane=promotable_by_lane,
            min_queue_depth=min_queue_depth,
        )
        pressure[pressure_key] = entry
    return pressure


def _ideas_intake_dict_rows(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(row) for row in value if isinstance(row, dict)]


def _ideas_intake_projection_counts(raw_counts: Any) -> dict[str, int]:
    if not isinstance(raw_counts, dict):
        return {}
    return {str(key): int(value or 0) for key, value in raw_counts.items()}


def _ideas_intake_load_raw_projection(
    store: Any, page_size: int
) -> list[dict[str, Any]]:
    idea_projection_reader = getattr(store, "idea_workbench_projection", None)
    legacy_projection_reader = getattr(store, "queue_notion_projection", None)
    if callable(idea_projection_reader):
        try:
            raw_projection = idea_projection_reader(limit=page_size)
        except TypeError:
            raw_projection = idea_projection_reader()
    elif callable(legacy_projection_reader):
        raw_projection = legacy_projection_reader()
    else:
        raw_projection = []
    return _ideas_intake_dict_rows(raw_projection)[:page_size]


def _ideas_intake_recent_events(store: Any) -> list[dict[str, Any]]:
    recent = _ideas_intake_dict_rows(
        store.event_rows(limit=20, event_type="ideas.intake")
    )
    if recent:
        return recent
    return _ideas_intake_dict_rows(
        store.event_rows(limit=20, event_type="notion.intake")
    )


def _ideas_intake_latest_from_parts(
    raw_latest: Any,
) -> DashboardObservationRecord | None:
    if raw_latest is None or isinstance(raw_latest, DashboardObservationRecord):
        return raw_latest
    return None


def _ideas_intake_skipped_reasons_from_payload(
    payload: dict[str, Any],
) -> dict[str, int]:
    if payload.get("skipped_reasons"):
        return {
            str(reason): int(count or 0)
            for reason, count in (payload.get("skipped_reasons") or {}).items()
        }
    skipped: dict[str, int] = {}
    for item in payload.get("skipped_rows") or []:
        reason = (
            str(item.get("reason") or "unknown")
            if isinstance(item, dict)
            else "unknown"
        )
        skipped[reason] = skipped.get(reason, 0) + 1
    return skipped


def _ideas_intake_prepare_latest(
    latest: DashboardObservationRecord | None,
    *,
    include_latest_payload: bool,
) -> tuple[DashboardObservationRecord | None, dict[str, int]]:
    if not latest:
        return None, {}
    payload = latest.payload or {}
    skipped_reasons = _ideas_intake_skipped_reasons_from_payload(payload)
    if include_latest_payload:
        return latest, skipped_reasons
    return (
        latest.model_copy(
            update={
                "payload": {
                    "payload_omitted": True,
                    "skipped_row_count": payload.get(
                        "skipped_row_count",
                        len(payload.get("skipped_rows") or []),
                    ),
                }
            }
        ),
        skipped_reasons,
    )


def _ideas_intake_empty_projection_warnings(
    projection: list[dict[str, Any]],
) -> list[DashboardFinding]:
    if projection:
        return []
    return [
        DashboardFinding(
            severity="warn",
            source="idea_intake",
            authority=SUPABASE_NATIVE_IDEAS_WORKBENCH_AUTHORITY,
            message="No Supabase-native ideas are visible",
            observed_at=utc_now(),
            suggested_action="load ideas into Supabase before resuming the queue",
        )
    ]


def _ideas_intake_fallback_parts(
    store: Any,
    *,
    page_size: int,
    include_latest_payload: bool,
    latest_metadata: Callable[[str], DashboardObservationRecord | None],
    intake_freshness: Callable[[], dict[str, DashboardFreshness]],
) -> tuple[
    DashboardObservationRecord | None,
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[str, int],
    dict[str, DashboardFreshness],
]:
    latest = (
        store.latest_dashboard_observation(source="idea_intake")
        if include_latest_payload
        else latest_metadata("idea_intake")
    )
    return (
        latest,
        _ideas_intake_load_raw_projection(store, page_size),
        _ideas_intake_recent_events(store),
        _ideas_intake_projection_counts(store.status_counts()),
        intake_freshness(),
    )


def _ideas_intake_parts_from_mapping(
    intake_parts: Mapping[str, Any],
    *,
    db_freshness: Callable[[str], dict[str, DashboardFreshness]],
    freshness_for_observation: Callable[
        [str, str, DashboardObservationRecord | None], DashboardFreshness
    ],
) -> tuple[
    DashboardObservationRecord | None,
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[str, int],
    dict[str, DashboardFreshness],
]:
    latest = _ideas_intake_latest_from_parts(intake_parts.get("latest_sync"))
    freshness = {
        **db_freshness(SUPABASE_NATIVE_IDEAS_WORKBENCH_AUTHORITY),
        "idea_intake": freshness_for_observation(
            "idea_intake",
            "latest Supabase-native ideas intake observation",
            latest,
        ),
    }
    return (
        latest,
        _ideas_intake_dict_rows(intake_parts.get("queued_projection")),
        _ideas_intake_dict_rows(intake_parts.get("recent_events")),
        _ideas_intake_projection_counts(intake_parts.get("projection_counts")),
        freshness,
    )


def _ideas_intake_resolve_parts(
    store: Any,
    *,
    page_size: int,
    include_latest_payload: bool,
    latest_metadata: Callable[[str], DashboardObservationRecord | None],
    intake_freshness: Callable[[], dict[str, DashboardFreshness]],
    db_freshness: Callable[[str], dict[str, DashboardFreshness]],
    freshness_for_observation: Callable[
        [str, str, DashboardObservationRecord | None], DashboardFreshness
    ],
) -> tuple[
    DashboardObservationRecord | None,
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[str, int],
    dict[str, DashboardFreshness],
]:
    intake_reader = getattr(store, "dashboard_ideas_intake_parts", None)
    fallback = partial(
        _ideas_intake_fallback_parts,
        store,
        page_size=page_size,
        include_latest_payload=include_latest_payload,
        latest_metadata=latest_metadata,
        intake_freshness=intake_freshness,
    )
    if not callable(intake_reader):
        return fallback()
    intake_parts = intake_reader(
        page_size=page_size, include_latest_payload=include_latest_payload
    )
    if isinstance(intake_parts, Mapping):
        return _ideas_intake_parts_from_mapping(
            intake_parts,
            db_freshness=db_freshness,
            freshness_for_observation=freshness_for_observation,
        )
    return fallback()


def _control_plane_store_for_config(config: GateConfig) -> Any:
    if config.control_plane_store_backend == "supabase_readonly":
        return SupabaseReadOnlyControlPlaneStore(
            resolve_supabase_database_url(config.supabase_database_url)
        )
    if config.control_plane_store_backend == "supabase":
        return SupabaseControlPlaneStore(
            resolve_supabase_database_url(config.supabase_database_url)
        )
    return ControlPlaneStore(config.expanded_state_dir / "control_plane.sqlite3")


def _alert_paper_evidence_blocked(
    config: GateConfig,
    *,
    project_id: str,
    run_id: str = "",
    paper_id: str = "",
    reason: str = "",
) -> dict[str, Any]:
    if not config.pushover_alerts_enabled:
        return {
            "attempted": False,
            "ok": False,
            "detail": "pushover alerts disabled",
        }
    result = send_pushover(
        config,
        title="Enoch paper evidence blocked",
        message=f"Paper generation blocked because source evidence could not be gathered. project={project_id} run={run_id or 'unknown'} paper={paper_id or 'unknown'} reason={reason or 'missing evidence'}",
        priority=1,
    )
    return {
        "attempted": result.attempted,
        "ok": result.ok,
        "status_code": result.status_code,
        "detail": result.detail,
    }


def _paper_evidence_blocked_event_key(
    *,
    entity_type: str,
    entity_id: str,
    run_id: str,
    paper_id: str,
) -> str:
    # Bucket by UTC day, not hour. A missing-evidence paper candidate is
    # durable until evidence arrives or the row is no longer paper-ready;
    # hourly timer retries should not produce hourly Pushover noise.
    bucket = utc_now()[:10]
    return ":".join(
        [
            "paper-evidence-sync-blocked",
            entity_type,
            _safe_slug(entity_id, "unknown"),
            _safe_slug(run_id or paper_id or "unknown", "unknown"),
            bucket,
        ]
    )


def _paper_evidence_blocked_payload(
    *,
    project_id: str,
    run_id: str,
    paper_id: str,
    artifact_root: str,
    reason: str,
    evidence_sync: dict[str, Any],
) -> dict[str, Any]:
    return {
        "project_id": project_id,
        "run_id": run_id,
        "paper_id": paper_id,
        "artifact_root": artifact_root,
        "reason": reason,
        "evidence_sync_summary": {
            "enabled": evidence_sync.get("enabled"),
            "synced": evidence_sync.get("synced"),
            "method": evidence_sync.get("method"),
            "local_evidence_present": evidence_sync.get("local_evidence_present"),
            "reason": reason,
        },
    }


def _paper_evidence_duplicate_alert_result(
    *, event_id: int | None = None, error: str = ""
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "attempted": False,
        "ok": True,
        "detail": "duplicate paper evidence alert suppressed",
        "event_id": event_id,
    }
    if error:
        result["event_store_conflict"] = True
        result["event_store_error"] = error[:300]
    return result


def _paper_evidence_event_store_failure_result(
    config: GateConfig,
    *,
    project_id: str,
    run_id: str,
    paper_id: str,
    reason: str,
    exc: Exception,
) -> dict[str, Any]:
    notification = _alert_paper_evidence_blocked(
        config,
        project_id=project_id,
        run_id=run_id,
        paper_id=paper_id,
        reason=reason,
    )
    return {
        **notification,
        "event_id": None,
        "event_store_failed": True,
        "event_store_error": f"{type(exc).__name__}: {exc}"[:300],
    }


def _record_paper_evidence_blocked(
    config: GateConfig,
    store: Any,
    *,
    entity_type: str,
    entity_id: str,
    project_id: str,
    run_id: str = "",
    paper_id: str = "",
    artifact_root: str = "",
    evidence_sync: dict[str, Any] | None = None,
) -> dict[str, Any]:
    evidence_sync = evidence_sync or {}
    reason = str(evidence_sync.get("reason") or "missing evidence")
    key = _paper_evidence_blocked_event_key(
        entity_type=entity_type,
        entity_id=entity_id,
        run_id=run_id,
        paper_id=paper_id,
    )
    payload = _paper_evidence_blocked_payload(
        project_id=project_id,
        run_id=run_id,
        paper_id=paper_id,
        artifact_root=artifact_root,
        reason=reason,
        evidence_sync=evidence_sync,
    )
    try:
        event_id, inserted = store.append_event(
            idempotency_key=key,
            event_type="paper.evidence_sync_blocked",
            entity_type=entity_type,
            entity_id=entity_id,
            payload=payload,
        )
    except IdempotencyConflict as exc:
        return _paper_evidence_duplicate_alert_result(error=str(exc))
    except Exception as exc:  # noqa: BLE001 - alerting must survive event-store failures
        return _paper_evidence_event_store_failure_result(
            config,
            project_id=project_id,
            run_id=run_id,
            paper_id=paper_id,
            reason=reason,
            exc=exc,
        )
    if not inserted:
        return _paper_evidence_duplicate_alert_result(event_id=event_id)
    notification = _alert_paper_evidence_blocked(
        config,
        project_id=project_id,
        run_id=run_id,
        paper_id=paper_id,
        reason=reason,
    )
    return {**notification, "event_id": event_id}


def _artifact_root_for_queue_row(
    config: GateConfig, row: dict[str, Any]
) -> tuple[Path, str]:
    project_id = str(row.get("project_id") or "").strip()
    project_dir_text = str(row.get("project_dir") or project_id).strip()
    return _local_artifact_root_http(
        config, project_id=project_id, project_dir_text=project_dir_text
    ), project_dir_text


def _evidence_sync_skipped_by_gate(
    config: GateConfig, gate: dict[str, Any]
) -> dict[str, Any]:
    return {
        "enabled": config.paper_evidence_sync_enabled,
        "synced": False,
        "skipped": True,
        "reason": "decision_gate_not_writable",
        "decision_gate_reason": str(gate.get("reason") or ""),
    }


def _worker_evidence_sync_kwargs_for_row(
    config: GateConfig, row: dict[str, Any]
) -> dict[str, Any]:
    machine_target = str(row.get("machine_target") or "")
    worker_target = config.resolved_worker_target(machine_target)
    default_target = config.resolved_worker_target("")
    target_url = (worker_target.wake_gate_url or "").strip().rstrip("/")
    default_url = (default_target.wake_gate_url or "").strip().rstrip("/")
    return {
        "worker_wake_gate_url": worker_target.wake_gate_url,
        "worker_bearer_token": worker_target.bearer_token,
        # The SSH evidence fallback is configured for the default/GB10 worker
        # root.  For routed CPU workers, falling back to that SSH host would
        # inspect the wrong machine and can mark a valid CPU run as missing
        # evidence.  Routed non-default workers must succeed through their
        # own HTTP read endpoint or fail closed.
        "allow_ssh_fallback": not target_url or target_url == default_url,
    }


def _stale_active_lane_identity(lane: dict[str, Any]) -> tuple[str, str, str] | None:
    confirmation = lane.get("active_confirmation")
    if not isinstance(confirmation, dict):
        return None
    if confirmation.get("state") != "stale_active":
        return None
    active_item = lane.get("active_item")
    if not isinstance(active_item, dict):
        return None
    return (
        str(active_item.get("project_id") or "").strip(),
        str(active_item.get("current_run_id") or "").strip(),
        str(active_item.get("current_session_id") or "").strip(),
    )


def _active_row_matches_identity(
    row: dict[str, Any], identity: tuple[str, str, str]
) -> bool:
    lane_project_id, lane_run_id, lane_session_id = identity
    project_id = str(row.get("project_id") or "").strip()
    run_id = str(row.get("current_run_id") or "").strip()
    session_id = str(row.get("current_session_id") or "").strip()
    return not (
        (lane_project_id and project_id != lane_project_id)
        or (lane_run_id and run_id != lane_run_id)
        or (lane_session_id and session_id != lane_session_id)
    )


def _active_row_identity_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("project_id") or "").strip(),
        str(row.get("current_run_id") or "").strip(),
        str(row.get("current_session_id") or "").strip(),
    )


def _status_stale_active_rows(status: DashboardStatusResponse) -> list[dict[str, Any]]:
    stale_rows: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str, str]] = set()
    for lane in status.worker_lanes:
        identity = _stale_active_lane_identity(lane)
        if identity is None:
            continue
        for row in status.active_items:
            if not _active_row_matches_identity(row, identity):
                continue
            key = _active_row_identity_key(row)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            stale_rows.append(row)
    return stale_rows


def _status_has_no_live_worker_conflict(status: DashboardStatusResponse) -> bool:
    if _status_stale_active_rows(status):
        return True
    return any(
        item.source == CONTROL_PLANE_DB_WORKER_PREFLIGHT_SOURCE
        and "no live worker run" in item.message
        for item in [*status.conflicts, *status.warnings]
    )


def _worker_lane_label(lane: dict[str, Any]) -> str:
    return str(
        lane.get("worker_role")
        or lane.get("machine_target")
        or lane.get("lane_key")
        or "worker lane"
    )


def _orphan_worker_lane_finding(
    lane: dict[str, Any], *, lane_label: str, no_live: dict[str, Any]
) -> DashboardFinding:
    return DashboardFinding(
        severity="critical",
        source=CONTROL_PLANE_DB_WORKER_PREFLIGHT_SOURCE,
        authority=CROSS_SOURCE_ACTIVE_LANE_RECONCILIATION_AUTHORITY,
        message=(
            f"{lane_label} worker reports live work but the control plane "
            "has no active row for that lane"
        ),
        suggested_action=(
            "pause dispatch and reconcile the orphan worker run before "
            "starting another job on this lane"
        ),
        data={
            "lane_key": lane.get("lane_key"),
            "machine_target": lane.get("machine_target"),
            "worker_check": no_live,
        },
    )


def _stale_worker_lane_finding(
    lane: dict[str, Any],
    *,
    lane_label: str,
    confirmation: dict[str, Any],
    state: str,
) -> DashboardFinding:
    active_item = (
        lane.get("active_item") if isinstance(lane.get("active_item"), dict) else {}
    )
    return DashboardFinding(
        severity="warn",
        source=CONTROL_PLANE_DB_WORKER_PREFLIGHT_SOURCE,
        authority=CROSS_SOURCE_ACTIVE_LANE_RECONCILIATION_AUTHORITY,
        message=(
            f"{lane_label} has an active control-plane row without a matching worker run"
            if state == "stale_active"
            else f"{lane_label} active row is unconfirmed during worker reconcile grace"
        ),
        suggested_action=(
            "run a live queue alert check to safely reconcile the stale active row"
            if state == "stale_active"
            else "wait for the worker observation grace window before reconciling"
        ),
        data={
            "lane_key": lane.get("lane_key"),
            "machine_target": lane.get("machine_target"),
            "active_item": active_item,
            "active_confirmation": confirmation,
        },
    )


def _worker_lane_confirmation_state(lane: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    confirmation = lane.get("active_confirmation")
    if not isinstance(confirmation, dict):
        return "", {}
    return str(confirmation.get("state") or ""), confirmation


def _append_dashboard_worker_lane_confirmation_findings(
    worker_lanes: list[dict[str, Any]],
    *,
    warnings: list[DashboardFinding],
    blockers: list[str],
    conflicts: list[DashboardFinding],
) -> None:
    for lane in worker_lanes:
        lane_label = _worker_lane_label(lane)
        worker_observations = lane.get("worker_observations")
        lane_preflight = (
            worker_observations.get("worker_preflight")
            if isinstance(worker_observations, dict)
            else None
        )
        no_live = _worker_no_live_failed_check(lane_preflight)
        if not int(lane.get("active_count") or 0) and no_live:
            finding = _orphan_worker_lane_finding(
                lane, lane_label=lane_label, no_live=no_live
            )
            warnings.append(finding)
            conflicts.append(finding)
            blockers.append(
                f"worker live run without active control-plane row: {lane_label}"
            )
            continue
        state, confirmation = _worker_lane_confirmation_state(lane)
        if state not in {"stale_active", "active_unconfirmed_grace"}:
            continue
        finding = _stale_worker_lane_finding(
            lane, lane_label=lane_label, confirmation=confirmation, state=state
        )
        warnings.append(finding)
        if state == "stale_active":
            conflicts.append(finding)
            blockers.append(f"stale active worker lane: {lane_label}")


def _auto_reconcile_evidence_gate_for_row(
    config: GateConfig, row: dict[str, Any]
) -> tuple[Path, dict[str, Any], dict[str, Any], str, str]:
    project_id = str(row.get("project_id") or "").strip()
    run_id = str(row.get("current_run_id") or "").strip()
    artifact_root, project_dir_text = _artifact_root_for_queue_row(config, row)
    gate = paper_draft_decision_gate(artifact_root)
    evidence_sync = _evidence_sync_skipped_by_gate(config, gate)
    if gate.get("eligible") or not gate.get("values"):
        evidence_sync = _sync_remote_project_evidence(
            config,
            project_id=project_id,
            artifact_root=artifact_root,
            source_project_dir=project_dir_text,
            source_run_id=run_id,
            **_worker_evidence_sync_kwargs_for_row(config, row),
        )
        gate = paper_draft_decision_gate(artifact_root)
    return artifact_root, gate, evidence_sync, project_id, run_id


def _auto_reconcile_missing_evidence_failure(
    config: GateConfig,
    store: Any,
    *,
    project_id: str,
    run_id: str,
    artifact_root: Path,
    gate: dict[str, Any],
    evidence_sync: dict[str, Any],
) -> dict[str, Any] | None:
    if not (
        config.paper_evidence_sync_enabled
        and not _local_paper_evidence_present(artifact_root)
        and gate.get("eligible")
    ):
        return None
    evidence_alert = _record_paper_evidence_blocked(
        config,
        store,
        entity_type="project",
        entity_id=project_id,
        project_id=project_id,
        run_id=run_id,
        artifact_root=str(artifact_root),
        evidence_sync=evidence_sync,
    )
    return {
        "ok": False,
        "project_id": project_id,
        "run_id": run_id,
        "reason": "missing paper evidence",
        "artifact_root": str(artifact_root),
        "evidence_sync": evidence_sync,
        "decision_gate": gate,
        "evidence_alert": evidence_alert,
    }


def _auto_reconcile_replay_wake_ready_for_row(
    store: Any,
    row: dict[str, Any],
    *,
    project_id: str,
    run_id: str,
    artifact_root: Path,
    gate: dict[str, Any],
    evidence_sync: dict[str, Any],
    requested_by: str,
) -> dict[str, Any]:
    has_decision_artifact = bool(gate.get("values"))
    replay_reason = (
        "auto replay: active row had no live worker run but durable decision artifact exists"
        if has_decision_artifact
        else "auto replay: active row had no live worker run and no durable decision artifact; lane released as no-paper completion"
    )
    callback = GateCallback(
        event_type="wake_ready",
        run_id=run_id,
        session_id=str(row.get("current_session_id") or ""),
        project_id=project_id,
        project_name=str(row.get("project_name") or project_id),
        source_event="control-plane-auto-reconcile",
        gate_state="wake_ready",
        process_tracking={
            "root_pid": None,
            "process_group_id": None,
            "processes": [],
            "live_process_count": 0,
        },
        telemetry={
            "replayed_by": requested_by,
            "artifact_root": str(artifact_root),
            "evidence_sync": evidence_sync,
            "missing_project_decision_artifact": not has_decision_artifact,
        },
        reason=replay_reason,
        idempotency_key=f"{run_id}:wake_ready:auto-reconcile:{requested_by}",
    )
    try:
        event_id, inserted, updated = store.record_worker_callback(
            callback, received_by="queue-alert-auto-reconcile"
        )
        decision_record = (
            store.record_project_decision_gate(
                project_id=project_id,
                run_id=run_id,
                artifact_root=artifact_root,
            )
            if has_decision_artifact and hasattr(store, "record_project_decision_gate")
            else {}
        )
        if decision_record.get("persisted"):
            store.update_project_dir(project_id, str(artifact_root))
        return {
            "ok": True,
            "project_id": project_id,
            "run_id": run_id,
            "event_id": event_id,
            "inserted_event": inserted,
            "queue_status": (updated or {}).get("status"),
            "artifact_root": str(artifact_root),
            "evidence_sync": evidence_sync,
            "decision_gate": gate,
            "decision_record": decision_record,
            "reason": (
                "replayed missing project decision artifact"
                if not has_decision_artifact
                else "replayed wake_ready"
            ),
        }
    except Exception as exc:
        return {
            "ok": False,
            "project_id": project_id,
            "run_id": run_id,
            "reason": f"{type(exc).__name__}: {exc}",
            "artifact_root": str(artifact_root),
            "evidence_sync": evidence_sync,
        }


def _auto_reconcile_stale_callback_ready(
    config: GateConfig,
    store: Any,
    status: DashboardStatusResponse,
    *,
    requested_by: str,
) -> list[dict[str, Any]]:
    if not status.active_items or not _status_has_no_live_worker_conflict(status):
        return []
    stale_rows = _status_stale_active_rows(status)
    rows_to_reconcile = stale_rows if stale_rows else status.active_items
    reconciled: list[dict[str, Any]] = []
    for row in rows_to_reconcile:
        if _queue_row_recent_callback(row):
            continue
        artifact_root, gate, evidence_sync, project_id, run_id = (
            _auto_reconcile_evidence_gate_for_row(config, row)
        )
        if not project_id or not run_id:
            continue
        missing_evidence = _auto_reconcile_missing_evidence_failure(
            config,
            store,
            project_id=project_id,
            run_id=run_id,
            artifact_root=artifact_root,
            gate=gate,
            evidence_sync=evidence_sync,
        )
        if missing_evidence is not None:
            reconciled.append(missing_evidence)
            continue
        reconciled.append(
            _auto_reconcile_replay_wake_ready_for_row(
                store,
                row,
                project_id=project_id,
                run_id=run_id,
                artifact_root=artifact_root,
                gate=gate,
                evidence_sync=evidence_sync,
                requested_by=requested_by,
            )
        )
    if reconciled:
        store.append_event(
            idempotency_key=f"queue-alert-auto-reconcile:{utc_now()}",
            event_type="queue_alert.auto_reconcile",
            entity_type="queue_alert",
            entity_id="active-lane",
            payload={"requested_by": requested_by, "results": reconciled},
        )
    return reconciled


def _dispatch_route_metadata(machine_target: str, target: Any) -> dict[str, Any]:
    return {
        "machine_target": machine_target,
        "wake_gate_url": target.wake_gate_url,
        "worker_role": target.role,
        "token_configured": bool(target.bearer_token),
    }


def _cp_mount_annotate_dispatch_route(
    candidate: dict[str, Any] | None, *, config: GateConfig
) -> dict[str, Any] | None:
    if not candidate:
        return candidate
    machine_target = str(candidate.get("machine_target") or "")
    target = config.resolved_worker_target(machine_target)
    return {
        **candidate,
        "dispatch_route": _dispatch_route_metadata(machine_target, target),
    }


def _cp_mount_worker_lane_key(
    config: GateConfig, candidate: dict[str, Any] | None
) -> str:
    if not candidate:
        return ""
    target = config.resolved_worker_target(str(candidate.get("machine_target") or ""))
    return (
        (target.wake_gate_url or str(candidate.get("machine_target") or ""))
        .strip()
        .rstrip("/")
    )


def _cp_mount_preflight_observation_lane_key(
    config: GateConfig, preflight: DashboardObservationRecord | None
) -> str:
    payload = preflight.payload if preflight else {}
    target = (
        str(payload.get("target") or "").strip() if isinstance(payload, dict) else ""
    )
    if not target:
        return _cp_mount_worker_lane_key(config, {"machine_target": ""})
    if "://" in target:
        if (urlparse(target).hostname or "") == DEFAULT_MACHINE_TARGET:
            return _cp_mount_worker_lane_key(config, {"machine_target": ""})
        return target.rstrip("/")
    return _cp_mount_worker_lane_key(config, {"machine_target": target})


def _cp_mount_preflight_observation_applies_to_candidate(
    config: GateConfig,
    preflight: DashboardObservationRecord | None,
    candidate: dict[str, Any] | None,
) -> bool:
    if not preflight or not candidate:
        return True
    preflight_lane = _cp_mount_preflight_observation_lane_key(config, preflight)
    if not preflight_lane:
        return True
    return preflight_lane == _cp_mount_worker_lane_key(config, candidate)


def _cp_mount_callback_acceptance_token_fingerprint(config: GateConfig) -> str:
    # /control/api/worker-callback is mounted on the control-plane router
    # and is protected by the same bearer dependency as other control APIs.
    # Worker preflight therefore has to compare the worker's configured
    # callback-delivery token against the token this endpoint will actually
    # accept, not the local completion_callback_token used by worker-mode
    # callback senders.
    token = (config.control_api_bearer_token or "").strip()
    if not token:
        return ""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _dispatch_sort_key(row: dict[str, Any]) -> tuple[int, int, str]:
    priority = _int_or_none(row.get("dispatch_priority"))
    rank = _int_or_none(row.get("selection_rank"))
    return (
        priority if priority is not None else 9999,
        rank if rank is not None else 9999,
        str(row.get("updated_at") or ""),
    )


def _cp_active_items_fast(store: Any, *, limit: int = 50) -> list[dict[str, Any]]:
    if hasattr(store, "active_items_sql"):
        return store.active_items_sql(limit=limit)  # type: ignore[attr-defined]
    return store.active_items()


def _cp_queued_dispatch_candidates(
    store: Any, rows: list[dict[str, Any]] | None = None
) -> list[dict[str, Any]]:
    candidates = [
        row
        for row in (rows if rows is not None else store.queue_rows())
        if _normal_status(row.get("status")) == "queued"
        and not _truthy_flag(row.get("manual_review_required"))
    ]
    candidates.sort(key=_dispatch_sort_key)
    return candidates


def _cp_queued_items_fast(store: Any, *, limit: int = 200) -> list[dict[str, Any]]:
    if hasattr(store, "queued_items_sql"):
        return store.queued_items_sql(limit=limit)  # type: ignore[attr-defined]
    return _cp_queued_dispatch_candidates(store, store.queue_rows())[:limit]


def _cp_recently_completed_items_fast(
    store: Any, *, limit: int = 50
) -> list[dict[str, Any]]:
    if hasattr(store, "recently_completed_items_sql"):
        return store.recently_completed_items_sql(limit=limit)  # type: ignore[attr-defined]
    rows = [
        row
        for row in store.queue_rows()
        if _normal_status(row.get("status")) == "completed"
        or _normal_status(row.get("last_run_state"))
        in {"wake_ready", "completed", "complete", "finished"}
    ]
    rows.sort(key=lambda row: str(row.get("updated_at") or ""), reverse=True)
    return rows[:limit]


def _cp_mount_open_worker_dispatch_candidate(
    store: Any,
    config: GateConfig,
    *,
    active: list[dict[str, Any]] | None = None,
    queued: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    if store.flags().queue_paused:
        return None
    active_lane_keys = {
        _cp_mount_worker_lane_key(config, row)
        for row in (active if active is not None else _cp_active_items_fast(store))
    }
    for candidate in _cp_queued_dispatch_candidates(store, queued):
        if _cp_mount_worker_lane_key(config, candidate) not in active_lane_keys:
            return candidate
    return None


def _worker_lane_summary_row(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    return {
        "project_id": str(row.get("project_id") or ""),
        "project_name": str(row.get("project_name") or ""),
        "project_dir": str(row.get("project_dir") or ""),
        "status": str(row.get("status") or ""),
        "machine_target": str(row.get("machine_target") or ""),
        "current_run_id": str(row.get("current_run_id") or ""),
        "updated_at": row.get("updated_at"),
        "dispatch_priority": row.get("dispatch_priority"),
        "selection_rank": row.get("selection_rank"),
    }


def _cp_mount_configured_worker_lanes(config: GateConfig) -> list[dict[str, Any]]:
    lanes: list[dict[str, Any]] = []
    seen: set[str] = set()
    for machine_target in sorted(config.worker_targets):
        target = config.resolved_worker_target(machine_target)
        lane_key = (target.wake_gate_url or machine_target).strip().rstrip("/")
        if not lane_key or lane_key in seen:
            continue
        seen.add(lane_key)
        lanes.append(
            {
                "lane_key": lane_key,
                "machine_target": machine_target,
                "worker_role": target.role or "worker",
                "wake_gate_url": target.wake_gate_url,
                "configured": True,
            }
        )
    default_target = config.resolved_worker_target("")
    default_key = (default_target.wake_gate_url or "").strip().rstrip("/")
    if default_key and default_key not in seen:
        lanes.append(
            {
                "lane_key": default_key,
                "machine_target": "",
                "worker_role": default_target.role or "default",
                "wake_gate_url": default_target.wake_gate_url,
                "configured": True,
            }
        )
    return lanes


def _cp_mount_rows_by_worker_lane(
    config: GateConfig, rows: list[dict[str, Any]]
) -> dict[str, list[dict[str, Any]]]:
    by_lane: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_lane.setdefault(_cp_mount_worker_lane_key(config, row), []).append(row)
    return by_lane


def _cp_mount_merge_unconfigured_worker_lanes(
    config: GateConfig,
    lanes_by_key: dict[str, dict[str, Any]],
    *row_groups: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    merged = dict(lanes_by_key)
    for rows in row_groups:
        for row in rows:
            lane_key = _cp_mount_worker_lane_key(config, row)
            if not lane_key or lane_key in merged:
                continue
            target = config.resolved_worker_target(str(row.get("machine_target") or ""))
            merged[lane_key] = {
                "lane_key": lane_key,
                "machine_target": str(row.get("machine_target") or ""),
                "worker_role": target.role or "worker",
                "wake_gate_url": target.wake_gate_url,
                "configured": False,
            }
    return merged


def _cp_mount_worker_lane_sort_key(lane: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(lane.get("worker_role") or ""),
        str(lane.get("machine_target") or ""),
        str(lane.get("lane_key") or ""),
    )


def _cp_mount_lane_dispatch_state(
    *,
    lane_active: list[dict[str, Any]],
    next_candidate: dict[str, Any] | None,
    global_blockers: list[str],
) -> tuple[bool, str, str]:
    if lane_active:
        return False, "", "lane active"
    if next_candidate and global_blockers:
        return False, "", global_blockers[0]
    if next_candidate:
        return True, "lane open with queued candidate", ""
    return False, "", "no queued candidate for lane"


def _cp_mount_worker_lane_capacity_entry(
    lane: dict[str, Any],
    *,
    active_by_lane: dict[str, list[dict[str, Any]]],
    queued_by_lane: dict[str, list[dict[str, Any]]],
    global_blockers: list[str],
    worker_preflight: DashboardObservationRecord | None = None,
    worker_preflight_lane_key: str = "",
    lane_worker_preflight: DashboardObservationRecord | None = None,
    lane_worker_preflight_key: str = "",
    lane_worker_dashboard: DashboardObservationRecord | None = None,
) -> dict[str, Any]:
    lane_key = str(lane["lane_key"])
    confirmation_preflight = lane_worker_preflight or worker_preflight
    confirmation_preflight_lane_key = (
        lane_worker_preflight_key or worker_preflight_lane_key
    )
    lane_active = sorted(
        active_by_lane.get(lane_key, []),
        key=lambda row: str(row.get("updated_at") or ""),
        reverse=True,
    )
    lane_queued = queued_by_lane.get(lane_key, [])
    next_candidate = lane_queued[0] if lane_queued else None
    dispatch_available, dispatch_reason, dispatch_blocker = (
        _cp_mount_lane_dispatch_state(
            lane_active=lane_active,
            next_candidate=next_candidate,
            global_blockers=global_blockers,
        )
    )
    active_item = lane_active[0] if lane_active else None
    return {
        **lane,
        "status": "active" if lane_active else "idle",
        "active_count": len(lane_active),
        "active_item": _worker_lane_summary_row(active_item),
        "active_confirmation": _active_lane_worker_confirmation(
            preflight=confirmation_preflight,
            preflight_lane_key=confirmation_preflight_lane_key,
            lane_key=lane_key,
            active_row=active_item,
        ),
        "worker_observations": {
            "worker_preflight": lane_worker_preflight,
            "worker_dashboard_api": lane_worker_dashboard,
        },
        "queued_count": len(lane_queued),
        "next_candidate": _worker_lane_summary_row(next_candidate),
        "dispatch_available": dispatch_available,
        "dispatch_reason": dispatch_reason,
        "dispatch_blocker": dispatch_blocker,
    }


def _cp_mount_worker_lane_capacity(
    config: GateConfig,
    store: Any,
    *,
    active: list[dict[str, Any]] | None = None,
    rows: list[dict[str, Any]] | None = None,
    global_blockers: list[str] | None = None,
    worker_preflight: DashboardObservationRecord | None = None,
) -> list[dict[str, Any]]:
    active_rows = list(active if active is not None else store.active_items())
    queue_rows = list(rows if rows is not None else store.queue_rows())
    queued_candidates = _cp_queued_dispatch_candidates(store, queue_rows)
    active_by_lane = _cp_mount_rows_by_worker_lane(config, active_rows)
    queued_by_lane = _cp_mount_rows_by_worker_lane(config, queued_candidates)
    lanes_by_key = {
        lane["lane_key"]: lane for lane in _cp_mount_configured_worker_lanes(config)
    }
    lanes_by_key = _cp_mount_merge_unconfigured_worker_lanes(
        config, lanes_by_key, active_rows, queued_candidates
    )
    blockers = [str(item) for item in (global_blockers or []) if str(item)]
    worker_preflight_lane_key = _cp_mount_preflight_observation_lane_key(
        config, _fresh_observation(worker_preflight)
    )
    capacity: list[dict[str, Any]] = []
    latest_observation = getattr(store, "latest_dashboard_observation", None)
    for lane in sorted(lanes_by_key.values(), key=_cp_mount_worker_lane_sort_key):
        lane_key = str(lane.get("lane_key") or "")
        lane_preflight = None
        lane_dashboard = None
        if callable(latest_observation) and lane_key:
            lane_preflight = latest_observation(
                source="worker_preflight", scope=f"lane:{lane_key}"
            )
            lane_dashboard = latest_observation(
                source="worker_dashboard_api", scope=f"lane:{lane_key}"
            )
        lane_preflight = _fresh_observation(lane_preflight)
        lane_dashboard = _fresh_observation(lane_dashboard)
        lane_preflight_key = (
            _cp_mount_preflight_observation_lane_key(config, lane_preflight)
            if lane_preflight is not None
            else ""
        )
        capacity.append(
            _cp_mount_worker_lane_capacity_entry(
                lane,
                active_by_lane=active_by_lane,
                queued_by_lane=queued_by_lane,
                global_blockers=blockers,
                worker_preflight=_fresh_observation(worker_preflight),
                worker_preflight_lane_key=worker_preflight_lane_key,
                lane_worker_preflight=lane_preflight,
                lane_worker_preflight_key=lane_preflight_key,
                lane_worker_dashboard=lane_dashboard,
            )
        )
    return capacity


def _cp_mount_worker_preflight_refresh_requests(
    config: GateConfig, *, expected_callback_token_fingerprint: str
) -> list[WorkerPreflightRequest]:
    if not config.live_dispatch_enabled:
        return []

    requests: list[WorkerPreflightRequest] = []
    seen: set[str] = set()

    def add_target(
        *,
        wake_gate_url: str,
        bearer_token: str,
        min_memory_available_mib: int | None = None,
    ) -> None:
        url = (wake_gate_url or "").strip()
        token = (bearer_token or "").strip()
        if not url or not token:
            return
        key = url.rstrip("/")
        if key in seen:
            return
        seen.add(key)
        requests.append(
            WorkerPreflightRequest(
                wake_gate_url=url,
                bearer_token=token,
                expected_callback_token_fingerprint=expected_callback_token_fingerprint,
                require_paused=False,
                strict=False,
                min_memory_available_mib=min_memory_available_mib or 16_384,
            )
        )

    default_target = config.resolved_worker_target("")
    add_target(
        wake_gate_url=default_target.wake_gate_url,
        bearer_token=default_target.bearer_token,
        min_memory_available_mib=default_target.min_memory_available_mib,
    )
    for machine_target in sorted(config.worker_targets):
        target = config.resolved_worker_target(machine_target)
        add_target(
            wake_gate_url=target.wake_gate_url,
            bearer_token=target.bearer_token,
            min_memory_available_mib=target.min_memory_available_mib,
        )
    return requests


def _cp_mount_lane_aware_worker_observation_refresher(
    ns: Mapping[str, Any],
) -> Callable[
    [dict[str, DashboardObservationRecord | None], list[dict[str, Any]]],
    dict[str, DashboardObservationRecord],
]:
    config: GateConfig = ns["config"]
    store: Any = ns["store"]
    callback_fingerprint = ns["_callback_acceptance_token_fingerprint"]
    record_preflight_observations = ns["_record_preflight_observations"]

    def refresh_worker_observations(
        observations: dict[str, DashboardObservationRecord | None],
        active: list[dict[str, Any]],
    ) -> dict[str, DashboardObservationRecord]:
        requests = _cp_mount_worker_preflight_refresh_requests(
            config,
            expected_callback_token_fingerprint=callback_fingerprint(),
        )
        if not requests:
            return {
                key: value for key, value in observations.items() if value is not None
            }
        for request in requests:
            record_preflight_observations(run_worker_preflight(request, store.flags()))
        return store.latest_dashboard_observations()

    return refresh_worker_observations


def _cp_mount_candidate_machine_target_conflict_set(
    config: GateConfig, candidate: dict[str, Any]
) -> set[str]:
    candidate_lane_key = _cp_mount_worker_lane_key(config, candidate)
    if not candidate_lane_key:
        machine_target = _normal_status(candidate.get("machine_target"))
        return {machine_target} if machine_target else {""}
    conflict_targets: set[str] = set()
    configured_targets = {
        "",
        *[str(target) for target in config.worker_targets.keys()],
    }
    for machine_target in configured_targets:
        normalized_target = _normal_status(machine_target)
        lane_key = _cp_mount_worker_lane_key(config, {"machine_target": machine_target})
        if lane_key == candidate_lane_key:
            conflict_targets.add(normalized_target)
    return conflict_targets or {_normal_status(candidate.get("machine_target")) or ""}


def _cp_mount_has_conflicting_active_lane(
    config: GateConfig, store: Any, candidate: dict[str, Any]
) -> bool:
    candidate_lane_key = _cp_mount_worker_lane_key(config, candidate)
    return any(
        _cp_mount_worker_lane_key(config, row) == candidate_lane_key
        for row in store.active_items()
    )


def create_control_plane_router(
    config: GateConfig, require_bearer: RequireBearer
) -> APIRouter:
    router = APIRouter(prefix="/control", tags=["control-plane"])
    store = _control_plane_store_for_config(config)
    _register_control_plane_routes(router, config, store, require_bearer)
    return router


def _register_control_plane_routes(
    router: APIRouter,
    config: GateConfig,
    store: Any,
    require_bearer: RequireBearer,
) -> None:
    _mount_control_plane_http_routes(router, config, store, require_bearer)


def _mount_control_plane_http_routes(
    router: APIRouter,
    config: GateConfig,
    store: Any,
    require_bearer: RequireBearer,
) -> None:
    _register_control_plane_http_routes(router, config, store, require_bearer)


def _register_control_plane_http_routes(
    router: APIRouter,
    config: GateConfig,
    store: Any,
    require_bearer: RequireBearer,
) -> None:
    _register_control_plane_http_route_handlers(router, config, store, require_bearer)
    _register_control_plane_sentry_smoke_route(router, require_bearer)


class EnochSentrySmokeError(RuntimeError):
    """Safe synthetic exception used to verify Sentry delivery."""


def _declare_non_store_mutating_post(action: str) -> None:
    """Document a POST route that performs no control-store mutation.

    Most POST routes must call `_require_writable_store` before mutating the
    control-plane store.  A few operator smoke-test endpoints are POST-only
    because they intentionally trigger a bounded external side effect while
    leaving the control-plane store untouched.  Calling this marker makes that
    boundary explicit and keeps the AST write-boundary test fail-closed for
    future POST routes.
    """
    if not action:
        raise AssertionError("non-mutating POST boundary action is required")


def _register_control_plane_sentry_smoke_route(
    router: APIRouter, require_bearer: RequireBearer
) -> None:
    @router.post("/api/v1/observability/sentry-smoke")
    def sentry_smoke(
        authorization: Annotated[str | None, Header()] = None,
    ) -> dict[str, Any]:
        require_bearer(authorization)
        _declare_non_store_mutating_post("sentry smoke")
        exc = EnochSentrySmokeError("enoch sentry smoke test")
        event_id = capture_exception(
            exc,
            component="control_plane",
            operation="sentry_smoke",
        )
        return {
            "ok": bool(event_id),
            "source": "control_api_v1_sentry_smoke",
            "authority": "safe synthetic exception capture; no request payload captured",
            "sentry_enabled": is_sentry_enabled(),
            "event_id": event_id or "",
            "generated_at": utc_now(),
        }


def _register_control_plane_llm_settings_routes(
    router: APIRouter,
    config: GateConfig,
    store: Any,
    require_bearer: RequireBearer,
) -> None:
    def _provider_by_id(settings: LLMSettings, provider_id: str):
        for provider in settings.providers:
            if provider.provider_id == provider_id:
                return provider
        raise HTTPException(status_code=404, detail="unknown LLM provider")

    def _model_by_id(settings: LLMSettings, model_id: str):
        for model in settings.models:
            if model.model_id == model_id:
                return model
        raise HTTPException(status_code=404, detail="unknown LLM model")

    def _provider_auth_headers(provider: Any) -> dict[str, str]:
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "User-Agent": "EnochControlPlane/llm-settings-test",
        }
        api_key = llm_provider_api_key(config, provider)
        host = (urlparse(provider.base_url).hostname or "").rstrip(".").lower()
        if api_key and host != "synthetic.int.exe.xyz":
            if provider.api_format == "anthropic_messages":
                headers["x-api-key"] = api_key
                headers["anthropic-version"] = "2023-06-01"
            else:
                headers["Authorization"] = f"Bearer {api_key}"
        return headers

    def _llm_test_response_preview(payload: dict[str, Any]) -> str:
        choices = payload.get("choices") or []
        if choices and isinstance(choices[0], dict):
            message = choices[0].get("message") or {}
            content = message.get("content")
            if isinstance(content, str):
                return content[:240]
        content = payload.get("content")
        if isinstance(content, list):
            text = "".join(
                str(part.get("text") or "")
                for part in content
                if isinstance(part, dict)
            )
            return text[:240]
        return ""

    def _llm_test_failure_kind(result: Mapping[str, Any]) -> str:
        status_code = int(result.get("status_code") or 0)
        error_text = str(result.get("error") or "").lower()
        if status_code in {401, 403}:
            return "auth_error"
        if status_code == 404:
            return "model_not_found"
        if status_code == 429:
            return "rate_limited"
        if status_code >= 500:
            return "server_error"
        if "timeout" in error_text or "timed out" in error_text:
            return "timeout"
        if not bool(result.get("ok")):
            return "unavailable"
        return ""

    def _scrub_llm_test_error(result: Mapping[str, Any], provider: Any) -> str:
        error = str(result.get("error") or "")[:500]
        if not error:
            return ""
        secret = llm_provider_api_key(config, provider)
        if secret:
            error = error.replace(secret, "[redacted]")
        return error

    def _record_llm_model_test_event(
        *,
        provider: Any,
        model: Any | None,
        result: Mapping[str, Any],
        source: str,
    ) -> str:
        append_event = getattr(store, "append_event", None)
        if not callable(append_event):
            return ""
        checked_at = utc_now()
        model_id = str(getattr(model, "model_id", "") or "")
        payload = {
            "provider_id": str(getattr(provider, "provider_id", "") or ""),
            "model_id": model_id,
            "ok": bool(result.get("ok")),
            "status_code": int(result.get("status_code") or 0),
            "latency_ms": int(result.get("latency_ms") or 0),
            "failure_kind": _llm_test_failure_kind(result),
            "error": _scrub_llm_test_error(result, provider),
            "source": source,
            "checked_at": checked_at,
        }
        entity_id = f"{payload['provider_id']}:{model_id or 'provider'}"
        try:
            event_id = append_event(
                idempotency_key=(f"llm-model-test:{entity_id}:{source}:{checked_at}"),
                event_type=read_models.LLM_MODEL_TEST_EVENT,
                entity_type="llm_model",
                entity_id=entity_id,
                payload=jsonable_encoder(payload),
            )
        except Exception as exc:  # noqa: BLE001 - health telemetry must not break test
            return f"{type(exc).__name__}: {exc}"
        return str(event_id or "")

    def _run_llm_provider_test(
        *,
        settings: LLMSettings,
        provider_id: str,
        model_id: str,
    ) -> dict[str, Any]:
        provider = _provider_by_id(settings, provider_id)
        model = _model_by_id(settings, model_id) if model_id else None
        if model is not None and model.provider_id != provider.provider_id:
            raise HTTPException(
                status_code=400, detail="model does not belong to provider"
            )
        if not llm_provider_api_key(config, provider) and (
            (urlparse(provider.base_url).hostname or "").rstrip(".").lower()
            != "synthetic.int.exe.xyz"
        ):
            raise HTTPException(
                status_code=400,
                detail="provider has no API key configured; paste a provider secret or configure an env var",
            )
        started = time.monotonic()
        try:
            if model is None:
                req = urllib.request.Request(
                    provider.base_url.rstrip("/") + "/models",
                    method="GET",
                    headers=_provider_auth_headers(provider),
                )
            elif provider.api_format == "anthropic_messages":
                req = urllib.request.Request(
                    provider.base_url.rstrip("/") + "/messages",
                    data=json.dumps(
                        {
                            "model": model.model_id,
                            "max_tokens": 12,
                            "temperature": 0,
                            "messages": [
                                {
                                    "role": "user",
                                    "content": "Reply with exactly: ok",
                                }
                            ],
                        }
                    ).encode("utf-8"),
                    method="POST",
                    headers=_provider_auth_headers(provider),
                )
            else:
                req = urllib.request.Request(
                    provider.base_url.rstrip("/") + "/chat/completions",
                    data=json.dumps(
                        {
                            "model": model.model_id,
                            "max_tokens": 12,
                            "temperature": 0,
                            "messages": [
                                {
                                    "role": "user",
                                    "content": "Reply with exactly: ok",
                                }
                            ],
                        }
                    ).encode("utf-8"),
                    method="POST",
                    headers=_provider_auth_headers(provider),
                )
            with urllib.request.urlopen(req, timeout=20) as response:  # noqa: S310 - operator-configured provider URL
                body = response.read(32768).decode("utf-8", errors="replace")
                try:
                    data = json.loads(body) if body else {}
                except json.JSONDecodeError:
                    data = {"raw_preview": body[:240]}
                return {
                    "ok": 200 <= int(response.status) < 300,
                    "provider_id": provider.provider_id,
                    "model_id": model.model_id if model is not None else "",
                    "status_code": int(response.status),
                    "latency_ms": int((time.monotonic() - started) * 1000),
                    "response_preview": _llm_test_response_preview(data)
                    or str(data.get("raw_preview") or "")[:240],
                }
        except urllib.error.HTTPError as exc:
            detail = exc.read(2048).decode("utf-8", errors="replace")
            return {
                "ok": False,
                "provider_id": provider.provider_id,
                "model_id": model.model_id if model is not None else "",
                "status_code": int(exc.code),
                "latency_ms": int((time.monotonic() - started) * 1000),
                "error": detail[:500] or str(exc),
            }
        except Exception as exc:  # noqa: BLE001 - operator diagnostic endpoint
            return {
                "ok": False,
                "provider_id": provider.provider_id,
                "model_id": model.model_id if model is not None else "",
                "status_code": 0,
                "latency_ms": int((time.monotonic() - started) * 1000),
                "error": f"{type(exc).__name__}: {exc}"[:500],
            }

    @router.get("/api/settings/llm")
    def dashboard_llm_settings(
        authorization: Annotated[str | None, Header()] = None,
    ) -> dict[str, Any]:
        require_bearer(authorization)
        settings = read_llm_settings(config)
        path = llm_settings_path(config)
        return {
            "ok": True,
            "source": "control_api_llm_settings",
            "authority": "validated file-backed provider/model settings",
            "path": str(path),
            "persisted": path.exists(),
            "settings": settings_response(settings, config),
            "model_health": read_models.llm_model_health_summary(store, settings),
            "generated_at": utc_now(),
        }

    @router.post("/api/settings/llm")
    def dashboard_update_llm_settings(
        payload: Annotated[dict[str, Any], Body()],
        authorization: Annotated[str | None, Header()] = None,
    ) -> dict[str, Any]:
        require_bearer(authorization)
        _require_writable_store("LLM provider settings update")
        body = payload or {}
        requested_by = str(body.get("requested_by") or "dashboard")[:80]
        settings_payload = body.get("settings", body)
        try:
            provider_secrets = body.get("provider_secrets") or {}
            if provider_secrets and not isinstance(provider_secrets, dict):
                raise ValueError(
                    "provider_secrets must be an object keyed by provider_id"
                )
            settings_payload, provider_secrets, recovered_provider_secrets = (
                settings_update_payload(settings_payload, provider_secrets)
            )
            settings = LLMSettings.model_validate(settings_payload)
            written_provider_secrets = write_llm_provider_secrets(
                config, provider_secrets, settings=settings
            )
            settings = write_llm_settings(config, settings, updated_by=requested_by)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        event_id = None
        event_error = ""
        try:
            event_id = store.append_event(
                idempotency_key=f"llm-settings:{settings.updated_at}:{requested_by}",
                event_type="settings.llm.updated",
                entity_type="settings",
                entity_id="llm",
                payload={
                    "requested_by": requested_by,
                    "settings_path": str(llm_settings_path(config)),
                    "providers": [
                        provider.provider_id for provider in settings.providers
                    ],
                    "workflows": [
                        workflow.workflow_id for workflow in settings.workflows
                    ],
                    "provider_secret_updates": written_provider_secrets,
                    "recovered_provider_secret_updates": recovered_provider_secrets,
                },
            )
        except Exception as exc:  # pragma: no cover - visibility only
            event_error = f"{type(exc).__name__}: {exc}"
        response = {
            "ok": True,
            "action": "llm_settings_updated",
            "event_id": event_id,
            "settings": settings_response(settings, config),
        }
        if event_error:
            response["event_error"] = event_error
        return response

    @router.post("/api/settings/llm/test")
    def dashboard_test_llm_settings(
        payload: Annotated[dict[str, Any], Body()],
        authorization: Annotated[str | None, Header()] = None,
    ) -> dict[str, Any]:
        require_bearer(authorization)
        _declare_non_store_mutating_post("LLM provider/model test")
        body = payload or {}
        provider_id = str(body.get("provider_id") or "").strip()
        model_id = str(body.get("model_id") or "").strip()
        if not provider_id:
            raise HTTPException(status_code=400, detail="provider_id is required")
        settings = read_llm_settings(config)
        result = _run_llm_provider_test(
            settings=settings, provider_id=provider_id, model_id=model_id
        )
        provider = _provider_by_id(settings, provider_id)
        model = _model_by_id(settings, model_id) if model_id else None
        if result.get("error"):
            result["error"] = _scrub_llm_test_error(result, provider)
        event_id = _record_llm_model_test_event(
            provider=provider,
            model=model,
            result=result,
            source="manual",
        )
        if event_id:
            result["event_id"] = event_id
        return {
            "source": "control_api_llm_settings_test",
            "authority": "bounded live provider/model smoke test; best-effort health event",
            "generated_at": utc_now(),
            **result,
        }

    @router.get("/api/settings/llm/health")
    def dashboard_llm_model_health(
        authorization: Annotated[str | None, Header()] = None,
    ) -> dict[str, Any]:
        require_bearer(authorization)
        settings = read_llm_settings(config)
        return {
            "source": "control_api_llm_model_health",
            "authority": "recent persisted LLM model test events joined to configured model catalog",
            "generated_at": utc_now(),
            **read_models.llm_model_health_summary(store, settings),
        }


class _ControlPlaneHttpRegistrationNamespace(dict):
    """Route-registration namespace: local bindings shadow module globals for exec."""

    __slots__ = ("_module_globals",)

    def __init__(
        self,
        module_globals: dict[str, Any],
        bindings: dict[str, Any],
    ) -> None:
        super().__init__(bindings)
        self._module_globals = module_globals

    def __missing__(self, key: str) -> Any:
        return self._module_globals[key]

    def __contains__(self, key: object) -> bool:
        return super().__contains__(key) or key in self._module_globals


def _control_plane_http_registration_namespace(
    router: APIRouter,
    config: GateConfig,
    store: Any,
    require_bearer: RequireBearer,
) -> _ControlPlaneHttpRegistrationNamespace:
    """Shared exec namespace: registration bindings shadow module globals."""
    return _ControlPlaneHttpRegistrationNamespace(
        globals(),
        {
            "router": router,
            "config": config,
            "store": store,
            "require_bearer": require_bearer,
        },
    )


def _exec_prepare_bindings(
    ns: _ControlPlaneHttpRegistrationNamespace, part: str
) -> None:
    exec(_HTTP_PREPARE_BINDINGS_SRC[part], ns, ns)


def _prepare_control_plane_http_bindings_core(
    ns: _ControlPlaneHttpRegistrationNamespace,
) -> None:
    _exec_prepare_bindings(ns, "_prepare_control_plane_http_bindings_core")


def _prepare_control_plane_http_bindings_dashboard(
    ns: _ControlPlaneHttpRegistrationNamespace,
) -> None:
    _exec_prepare_bindings(ns, "_prepare_control_plane_http_bindings_dashboard")
    ns["_refresh_worker_observations_if_needed"] = (
        _cp_mount_lane_aware_worker_observation_refresher(ns)
    )


def _prepare_control_plane_http_bindings_dispatch(
    ns: _ControlPlaneHttpRegistrationNamespace,
) -> None:
    _exec_prepare_bindings(ns, "_prepare_control_plane_http_bindings_dispatch")


def _prepare_control_plane_http_bindings_publication(
    ns: _ControlPlaneHttpRegistrationNamespace,
) -> None:
    _exec_prepare_bindings(ns, "_prepare_control_plane_http_bindings_publication")


def _prepare_control_plane_http_route_bindings(
    ns: _ControlPlaneHttpRegistrationNamespace,
) -> None:
    _prepare_control_plane_http_bindings_core(ns)
    _prepare_control_plane_http_bindings_dashboard(ns)
    _prepare_control_plane_http_bindings_dispatch(ns)
    _prepare_control_plane_http_bindings_publication(ns)


_HTTP_ROUTE_REGISTRAR_SRC: dict[str, str] = {
    "_register_control_plane_dashboard_shell_routes": '@router.get("/dashboard")\ndef dashboard() -> RedirectResponse:\n    """Legacy dashboard URL redirects to canonical Dashboard V2 (hash preserved client-side)."""\n    return RedirectResponse(url="/control/dashboard-v2", status_code=307)\n\n@router.get(\n    "/dashboard-v2", response_class=HTMLResponse, responses=_HTTP_503_DASHBOARD_V2\n)\ndef dashboard_v2() -> HTMLResponse:\n    index_path = DASHBOARD_V2_DIST_PATH / "index.html"\n    if not index_path.is_file():\n        raise HTTPException(\n            status_code=503,\n            detail="Dashboard V2 assets are missing; run npm --prefix dashboard run build.",\n        )\n    return HTMLResponse(\n        index_path.read_text(encoding="utf-8"),\n        headers={"Cache-Control": "no-store"},\n    )\n\n@router.get(\n    "/dashboard-v2/assets/{asset_path:path}", responses=_HTTP_404_DASHBOARD_ASSET\n)\ndef dashboard_v2_asset(asset_path: str) -> Response:\n    asset_root = (DASHBOARD_V2_DIST_PATH / "assets").resolve()\n    candidate = (asset_root / asset_path).resolve()\n    try:\n        candidate.relative_to(asset_root)\n    except ValueError:\n        raise HTTPException(status_code=404, detail="asset not found") from None\n    if not candidate.is_file():\n        raise HTTPException(status_code=404, detail="asset not found")\n    media_type = (\n        mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"\n    )\n    return Response(\n        candidate.read_bytes(),\n        media_type=media_type,\n        headers={"Cache-Control": "no-store"},\n    )\n\n@router.get("/health")\ndef health(authorization: Annotated[str | None, Header()] = None) -> dict:\n    authorize(authorization)\n    backend = config.control_plane_store_backend\n    db_path = str(getattr(store, "path", backend))\n    return {\n        "ok": True,\n        "service": "enoch-langgraph-control-plane",\n        "db_path": db_path,\n        "store_backend": backend,\n        "timestamp": utc_now(),\n    }\n\n@router.get("/state")\ndef get_state(\n    authorization: Annotated[str | None, Header()] = None,\n) -> ControlStateResponse:\n    authorize(authorization)\n    return state_response()\n\n@router.get("/api/status")\ndef dashboard_status(\n    refresh_worker: Annotated[bool, Query()] = False,\n    authorization: Annotated[str | None, Header()] = None,\n) -> DashboardStatusResponse:\n    authorize(authorization)\n    # Dashboard reads must be cheap and side-effect-free by default. Operators\n    # can still request a live worker refresh explicitly with refresh_worker=true.\n    return dashboard_status_response(\n        refresh_worker=refresh_worker, allow_worker_refresh=refresh_worker\n    )\n\n@router.post(\n    "/api/alerts/queue-check",\n    responses=_HTTP_500_UNRESOLVABLE_ARTIFACT_ROOT,\n)\ndef dashboard_queue_alert_check(\n    payload: dict[str, Any] | None = None,\n    authorization: Annotated[str | None, Header()] = None,\n) -> dict[str, Any]:\n    authorize(authorization)\n    request_payload = payload or {}\n    dry_run = bool(request_payload.get("dry_run", True))\n    requested_by = str(request_payload.get("requested_by") or "operator")\n    if not dry_run:\n        _require_writable_store("queue alert live check")\n    status = dashboard_status_response(\n        refresh_worker=bool(request_payload.get("refresh_worker", False))\n    )\n    auto_reconcile: list[dict[str, Any]] = []\n    if not dry_run:\n        auto_reconcile = _auto_reconcile_stale_callback_ready(\n            config, store, status, requested_by=requested_by\n        )\n        if any(item.get("ok") for item in auto_reconcile):\n            status = dashboard_status_response(refresh_worker=False)\n    alert = evaluate_and_notify_queue_alerts(\n        config=config,\n        store=store,\n        status=status,\n        dry_run=dry_run,\n        force_notify=bool(request_payload.get("force_notify", False)),\n        requested_by=requested_by,\n    )\n    if auto_reconcile:\n        alert["auto_reconcile"] = auto_reconcile\n        if (\n            any(item.get("ok") for item in auto_reconcile)\n            and not status.active_items\n        ):\n            alert.update(\n                {\n                    "should_alert": False,\n                    "sent": False,\n                    "suppressed_by_cooldown": False,\n                    "fingerprint": "auto-reconciled",\n                    "findings": [],\n                    "notification": {\n                        "attempted": False,\n                        "ok": True,\n                        "status_code": None,\n                        "detail": "auto reconciled stale callback",\n                    },\n                }\n            )\n    operator_trace = OperatorTrace.from_config(config)\n    trace_id = OperatorTrace.new_trace_id("queue-check")\n    operator_trace.record(\n        "queue_check.result",\n        trace_id=trace_id,\n        requested_by=requested_by,\n        dry_run=dry_run,\n        should_alert=alert.get("should_alert"),\n        sent=alert.get("sent"),\n        findings=_operator_trace_queue_findings(alert.get("findings", [])),\n        auto_reconcile=auto_reconcile[:10],\n        before={"active_count": len(status.active_items), "blockers": status.dispatch_blockers},\n    )\n    alert["trace_id"] = trace_id\n    return alert\n\n@router.get("/api/queue-health")\ndef dashboard_queue_health(\n    refresh_worker: Annotated[bool, Query()] = False,\n    authorization: Annotated[str | None, Header()] = None,\n) -> dict[str, Any]:\n    authorize(authorization)\n    status = dashboard_status_response(refresh_worker=refresh_worker)\n    active = status.active_items[0] if status.active_items else None\n    run_id = str((active or {}).get("current_run_id") or "")\n    project_id = str((active or {}).get("project_id") or "")\n    alert = evaluate_and_notify_queue_alerts(\n        config=config,\n        store=store,\n        status=status,\n        dry_run=True,\n        force_notify=False,\n        requested_by="dashboard.queue_health",\n    )\n    return {\n        "ok": True,\n        "source": "control_api_queue_health",\n        "authority": "aggregated queue health read model",\n        "generated_at": utc_now(),\n        "status": status.model_dump(mode="json"),\n        "active_run_detail": {\n            "queue_item": active,\n            "run": store.run_row(run_id) if run_id else None,\n            "project": store.project_row(project_id) if project_id else None,\n            "events": _project_events(project_id) if project_id else [],\n        },\n        "latest_alert_check": alert,\n        "recent_alert_events": store.event_rows(\n            limit=20, entity_type="queue_alert"\n        ),\n        "recent_worker_callbacks": store.event_rows(\n            limit=20, search="worker_callback."\n        ),\n    }\n\n@router.post(\n    "/api/worker-callback",\n    responses=_HTTP_500_UNRESOLVABLE_ARTIFACT_ROOT,\n)\ndef worker_callback(\n    callback: GateCallback, authorization: Annotated[str | None, Header()] = None\n) -> dict[str, Any]:\n    authorize(authorization)\n    _require_writable_store("worker callback recording")\n    try:\n        event_id, inserted, row = store.record_worker_callback(callback)\n    except IdempotencyConflict as exc:\n        raise HTTPException(status_code=409, detail=str(exc)) from exc\n    decision_sync: dict[str, Any] | None = None\n    callback_run_id = str(callback.run_id or "").strip()\n    row_run_id = str((row or {}).get("current_run_id") or "").strip()\n    row_last_run_state = str((row or {}).get("last_run_state") or "").strip()\n    should_sync_decision = (\n        inserted\n        and callback.event_type in {"wake_ready", "session_finished_ready"}\n        and bool(row)\n        and row_run_id == callback_run_id\n        and row_last_run_state in {"wake_ready", "session_finished_ready"}\n    )\n    if should_sync_decision and row:\n        project_id = str(row.get("project_id") or callback.project_id or "").strip()\n        artifact_root, project_dir_text = _artifact_root_for_queue_row(config, row)\n        decision_gate = paper_draft_decision_gate(artifact_root)\n        evidence_sync = _evidence_sync_skipped_by_gate(config, decision_gate)\n        if decision_gate.get("eligible") or not decision_gate.get("values"):\n            evidence_sync = _sync_remote_project_evidence(\n                config,\n                project_id=project_id,\n                artifact_root=artifact_root,\n                source_project_dir=project_dir_text,\n                source_run_id=str(callback.run_id or ""),\n                **_worker_evidence_sync_kwargs_for_row(config, row),\n            )\n            decision_gate = paper_draft_decision_gate(artifact_root)\n        decision_sync = {\n            "artifact_root": str(artifact_root),\n            "evidence_sync": evidence_sync,\n            "decision_gate": decision_gate,\n        }\n        local_evidence_present = _local_paper_evidence_present(artifact_root)\n        if (\n            config.paper_evidence_sync_enabled\n            and not local_evidence_present\n            and decision_gate.get("eligible")\n        ):\n            decision_sync["evidence_alert"] = _record_paper_evidence_blocked(\n                config,\n                store,\n                entity_type="project",\n                entity_id=project_id,\n                project_id=project_id,\n                run_id=str(callback.run_id or ""),\n                artifact_root=str(artifact_root),\n                evidence_sync=evidence_sync,\n            )\n        if local_evidence_present and hasattr(\n            store, "record_project_decision_gate"\n        ):\n            try:\n                decision_record = store.record_project_decision_gate(\n                    project_id=project_id,\n                    run_id=str(callback.run_id or ""),\n                    artifact_root=artifact_root,\n                )\n            except Exception as exc:\n                decision_record = {\n                    "ok": False,\n                    "persisted": False,\n                    "reason": "decision persistence failed",\n                    "error_type": type(exc).__name__,\n                }\n            decision_sync["decision_record"] = decision_record\n            if decision_record.get("persisted") and project_id:\n                store.update_project_dir(project_id, str(artifact_root))\n                row = store.queue_row(project_id) or row\n    return {\n        "ok": True,\n        "accepted": True,\n        "run_id": callback.run_id,\n        "session_id": callback.session_id,\n        "event_type": callback.event_type,\n        "state": callback.event_type,\n        "idempotency_key": callback.idempotency_key,\n        "event_id": event_id,\n        "inserted_event": inserted,\n        "queue_item": row,\n        "decision_sync": decision_sync,\n        "controller_action": "record_worker_callback",\n        "next_action_hint": row.get("next_action_hint")\n        if row\n        else "callback_recorded_no_queue_row",\n    }\n\n@router.get("/api/v1/research-quality")\ndef dashboard_v1_research_quality(\n    authorization: Annotated[str | None, Header()] = None,\n) -> dict[str, Any]:\n    authorize(authorization)\n    return _research_quality_payload()\n\n@router.get("/api/v1/source-lineage")\ndef dashboard_v1_source_lineage(\n    authorization: Annotated[str | None, Header()] = None,\n) -> dict[str, Any]:\n    authorize(authorization)\n    return _source_lineage_payload()\n\n@router.get("/api/v1/automation-readiness")\ndef dashboard_v1_automation_readiness(\n    authorization: Annotated[str | None, Header()] = None,\n) -> dict[str, Any]:\n    authorize(authorization)\n    return _automation_readiness_payload()\n\n@router.get("/api/v1/overview")\ndef dashboard_v1_overview(\n    authorization: Annotated[str | None, Header()] = None,\n    active_limit: Annotated[int, Query(ge=1, le=25)] = 5,\n    event_limit: Annotated[int, Query(ge=0, le=50)] = 10,\n) -> dict[str, Any]:\n    authorize(authorization)\n    # Compute worker-lane capacity once and feed it into the overview read\n    # model so `top_actions.dispatch_next` is lane-aware. Aggregate\n    # `counts.active` / `counts.queued` are NOT used to imply lane dispatch\n    # truth — the CPU lane being busy must not suppress dispatch on an\n    # idle GB10 lane and vice versa. Use the bounded `_active_items_fast`\n    # / `_queued_items_fast` helpers so the v1 dashboard contract (no\n    # `queue_rows()` / `paper_rows()` legacy reads) is preserved.\n    active_for_lanes = _active_items_fast()\n    queued_for_lanes = _queued_items_fast()\n    worker_lanes = _worker_lane_capacity(\n        active=active_for_lanes, rows=queued_for_lanes\n    )\n    try:\n        overview_min_admission_score = float(\n            os.environ.get("ENOCH_RESEARCH_ADMIT_THRESHOLD") or 72.0\n        )\n    except ValueError:\n        overview_min_admission_score = 72.0\n    lane_feed_pressure = _research_lane_feed_pressure(\n        active=active_for_lanes,\n        queued=queued_for_lanes,\n        lanes=worker_lanes,\n        min_queue_depth=_bounded_int_env(\n            "ENOCH_RESEARCH_MIN_QUEUE_DEPTH_PER_LANE", 25, 0, 100\n        ),\n        min_admission_score=overview_min_admission_score,\n    )\n    for lane in worker_lanes:\n        key = str(lane.get("machine_target") or lane.get("lane_key") or "")\n        if key in lane_feed_pressure:\n            lane["feed_pressure"] = lane_feed_pressure[key]\n    data = read_models.overview(\n        store,\n        active_limit=active_limit,\n        event_limit=event_limit,\n        worker_lanes=worker_lanes,\n        flags=store.flags(),\n    )\n    open_candidate = _open_worker_dispatch_candidate(\n        active=active_for_lanes, queued=queued_for_lanes\n    )\n    data["next_candidate"] = (\n        read_models.summarize_queue_row(open_candidate) if open_candidate else None\n    )\n    return {\n        "ok": True,\n        "source": "control_api_v1_overview",\n        "authority": "bounded dashboard read model",\n        "generated_at": utc_now(),\n        **data,\n        "links": {\n            "queue": "/control/api/v1/queue",\n            "runs": "/control/api/v1/runs",\n            "papers": "/control/api/v1/papers",\n            "events": "/control/api/v1/events",\n        },\n    }\n\n',
    "_register_control_plane_dashboard_v1_routes": '@router.post("/api/v1/followups/launch-next")\ndef launch_next_followup(\n    payload: FollowupLaunchRequest,\n    authorization: Annotated[str | None, Header()] = None,\n) -> FollowupLaunchResponse:\n    authorize(authorization)\n    if not payload.dry_run:\n        _require_writable_store("follow-up launch")\n    launcher = getattr(store, "launch_followup_candidate", None)\n    if not callable(launcher):\n        return FollowupLaunchResponse(\n            ok=True,\n            action="noop",\n            reason="store does not support follow-up branching",\n        )\n    result = launcher(\n        project_id=payload.project_id,\n        dry_run=payload.dry_run,\n        requested_by=payload.requested_by,\n        max_followup_depth=payload.max_followup_depth,\n    )\n    return FollowupLaunchResponse(\n        ok=bool(result.get("ok", True)),\n        action=result.get("action") or "noop",\n        reason=result.get("reason") or "",\n        candidate=result.get("candidate"),\n        followup=result.get("followup"),\n        event_id=result.get("event_id"),\n    )\n\n@router.get("/api/v1/lanes")\ndef dashboard_v1_lanes(\n    authorization: Annotated[str | None, Header()] = None,\n) -> dict[str, Any]:\n    authorize(authorization)\n    active_for_lanes = _active_items_fast(limit=10)\n    queued_for_lanes = _queued_items_fast()\n    active = [read_models.summarize_queue_row(row) for row in active_for_lanes]\n    next_candidate = _open_worker_dispatch_candidate(\n        active=active_for_lanes, queued=queued_for_lanes\n    )\n    return {\n        "ok": True,\n        "source": "control_api_v1_lanes",\n        "authority": "bounded active-lane read model",\n        "generated_at": utc_now(),\n        "active_items": active,\n        "next_candidate": read_models.summarize_queue_row(next_candidate)\n        if next_candidate\n        else None,\n        "counts": store.queue_counts_sql(),\n    }\n\n@router.get("/api/v1/queue")\ndef dashboard_v1_queue(\n    authorization: Annotated[str | None, Header()] = None,\n    queue: Annotated[str, Query()] = "all",\n    status: str = "",\n    search: str = "",\n    cursor: str = "",\n    page_size: Annotated[int, Query(ge=1, le=200)] = 50,\n    sort: str = "priority",\n) -> dict[str, Any]:\n    authorize(authorization)\n    safe_size = read_models.page_size(page_size)\n    rows, next_cursor, has_more = store.queue_page(\n        queue=queue,\n        status=status,\n        search=search,\n        cursor=cursor,\n        page_size=safe_size,\n        sort=sort,\n    )\n    out = [read_models.summarize_queue_list_row(row) for row in rows]\n    return {\n        "ok": True,\n        "source": "control_api_v1_queue",\n        "authority": "bounded SQL queue read model",\n        "generated_at": utc_now(),\n        "counts": store.queue_counts_sql(),\n        "page": read_models.page_response(\n            rows=out,\n            next_cursor=next_cursor,\n            has_more=has_more,\n            page_size_value=safe_size,\n            cursor=cursor,\n            filters={\n                "queue": queue,\n                "status": status,\n                "search": search,\n                "sort": sort,\n            },\n        ),\n        "rows": out,\n    }\n\n@router.get("/api/v1/runs")\ndef dashboard_v1_runs(\n    authorization: Annotated[str | None, Header()] = None,\n    state: str = "",\n    project_id: str = "",\n    search: str = "",\n    cursor: str = "",\n    page_size: Annotated[int, Query(ge=1, le=200)] = 50,\n    sort: str = "recent",\n) -> dict[str, Any]:\n    authorize(authorization)\n    safe_size = read_models.page_size(page_size)\n    rows, next_cursor, has_more = store.run_page(\n        state=state,\n        project_id=project_id,\n        search=search,\n        cursor=cursor,\n        page_size=safe_size,\n        sort=sort,\n    )\n    out = [read_models.summarize_run_list_row(row) for row in rows]\n    return {\n        "ok": True,\n        "source": "control_api_v1_runs",\n        "authority": "bounded SQL run read model",\n        "generated_at": utc_now(),\n        "page": read_models.page_response(\n            rows=out,\n            next_cursor=next_cursor,\n            has_more=has_more,\n            page_size_value=safe_size,\n            cursor=cursor,\n            filters={\n                "state": state,\n                "project_id": project_id,\n                "search": search,\n                "sort": sort,\n            },\n        ),\n        "rows": out,\n    }\n\n@router.get("/api/v1/runs/{run_id}", responses=_HTTP_404_RUN)\ndef dashboard_v1_run_detail(\n    run_id: str,\n    authorization: Annotated[str | None, Header()] = None,\n    event_limit: Annotated[int, Query(ge=0, le=100)] = 50,\n) -> dict[str, Any]:\n    authorize(authorization)\n    run = store.run_row(run_id)\n    if run is None:\n        raise HTTPException(status_code=404, detail="run not found")\n    project_id = str(run.get("project_id") or "")\n    events, next_cursor, has_more = store.event_page(\n        entity_id=run_id, page_size=event_limit, include_payload=False\n    )\n    papers, paper_cursor, paper_more = store.paper_page(run_id=run_id, page_size=25)\n    queue_item = store.queue_row(project_id) if project_id else None\n    if queue_item and str(queue_item.get("current_run_id") or "").strip() != run_id:\n        queue_item = None\n    return {\n        "ok": True,\n        "source": "control_api_v1_run",\n        "authority": "bounded SQL run detail read model",\n        "generated_at": utc_now(),\n        "run_id": run_id,\n        "run": read_models.summarize_run_row(run),\n        "project": store.project_row(project_id) if project_id else None,\n        "queue_item": read_models.summarize_queue_row(queue_item)\n        if queue_item\n        else None,\n        "papers": [read_models.summarize_paper_row(row) for row in papers],\n        "papers_page": read_models.page_response(\n            rows=papers,\n            next_cursor=paper_cursor,\n            has_more=paper_more,\n            page_size_value=25,\n            cursor="",\n            filters={"run_id": run_id},\n        ),\n        "events": events,\n        "events_page": read_models.page_response(\n            rows=events,\n            next_cursor=next_cursor,\n            has_more=has_more,\n            page_size_value=read_models.page_size(event_limit, cap=100),\n            cursor="",\n            filters={"entity_id": run_id},\n        ),\n    }\n\n@router.get("/api/v1/projects")\ndef dashboard_v1_projects(\n    authorization: Annotated[str | None, Header()] = None,\n    status: str = "",\n    search: str = "",\n    cursor: str = "",\n    page_size: Annotated[int, Query(ge=1, le=200)] = 50,\n    sort: str = "recent",\n) -> dict[str, Any]:\n    authorize(authorization)\n    safe_size = read_models.page_size(page_size)\n    rows, next_cursor, has_more = store.project_page(\n        status=status, search=search, cursor=cursor, page_size=safe_size, sort=sort\n    )\n    out = [read_models.summarize_project_list_row(row) for row in rows]\n    return {\n        "ok": True,\n        "source": "control_api_v1_projects",\n        "authority": "bounded SQL project read model",\n        "generated_at": utc_now(),\n        "page": read_models.page_response(\n            rows=out,\n            next_cursor=next_cursor,\n            has_more=has_more,\n            page_size_value=safe_size,\n            cursor=cursor,\n            filters={"status": status, "search": search, "sort": sort},\n        ),\n        "rows": out,\n    }\n\n@router.get("/api/v1/projects/{project_id}", responses=_HTTP_404_PROJECT)\ndef dashboard_v1_project_detail(\n    project_id: str,\n    authorization: Annotated[str | None, Header()] = None,\n    event_limit: Annotated[int, Query(ge=0, le=100)] = 50,\n) -> dict[str, Any]:\n    authorize(authorization)\n    project = store.project_row(project_id)\n    if project is None:\n        raise HTTPException(status_code=404, detail="project not found")\n    runs, run_cursor, run_more = store.run_page(project_id=project_id, page_size=25)\n    papers, paper_cursor, paper_more = store.paper_page(\n        project_id=project_id, page_size=25\n    )\n    events, event_cursor, event_more = store.event_page(\n        entity_id=project_id, page_size=event_limit, include_payload=False\n    )\n    queue_item = store.queue_row(project_id)\n    return {\n        "ok": True,\n        "source": "control_api_v1_project",\n        "authority": "bounded SQL project detail read model",\n        "generated_at": utc_now(),\n        "project_id": project_id,\n        "project": project,\n        "queue_item": read_models.summarize_queue_row(queue_item)\n        if queue_item\n        else None,\n        "runs": [read_models.summarize_run_row(row) for row in runs],\n        "runs_page": read_models.page_response(\n            rows=runs,\n            next_cursor=run_cursor,\n            has_more=run_more,\n            page_size_value=25,\n            cursor="",\n            filters={"project_id": project_id},\n        ),\n        "papers": [read_models.summarize_paper_row(row) for row in papers],\n        "papers_page": read_models.page_response(\n            rows=papers,\n            next_cursor=paper_cursor,\n            has_more=paper_more,\n            page_size_value=25,\n            cursor="",\n            filters={"project_id": project_id},\n        ),\n        "events": events,\n        "events_page": read_models.page_response(\n            rows=events,\n            next_cursor=event_cursor,\n            has_more=event_more,\n            page_size_value=read_models.page_size(event_limit, cap=100),\n            cursor="",\n            filters={"entity_id": project_id},\n        ),\n    }\n\n@router.get("/api/v1/papers")\ndef dashboard_v1_papers(\n    authorization: Annotated[str | None, Header()] = None,\n    status: str = "",\n    search: str = "",\n    cursor: str = "",\n    page_size: Annotated[int, Query(ge=1, le=200)] = 50,\n    sort: str = "recent",\n) -> dict[str, Any]:\n    authorize(authorization)\n    safe_size = read_models.page_size(page_size)\n    rows, next_cursor, has_more = store.paper_page(\n        status=status, search=search, cursor=cursor, page_size=safe_size, sort=sort\n    )\n    out = [read_models.summarize_paper_list_row(row) for row in rows]\n    return {\n        "ok": True,\n        "source": "control_api_v1_papers",\n        "authority": "bounded SQL paper read model",\n        "generated_at": utc_now(),\n        "counts": store.paper_counts_sql(),\n        "page": read_models.page_response(\n            rows=out,\n            next_cursor=next_cursor,\n            has_more=has_more,\n            page_size_value=safe_size,\n            cursor=cursor,\n            filters={"status": status, "search": search, "sort": sort},\n        ),\n        "rows": out,\n    }\n\n@router.get("/api/v1/papers/{paper_id}", responses=_HTTP_404_PAPER)\ndef dashboard_v1_paper_detail(\n    paper_id: str,\n    authorization: Annotated[str | None, Header()] = None,\n    event_limit: Annotated[int, Query(ge=0, le=100)] = 50,\n) -> dict[str, Any]:\n    authorize(authorization)\n    paper = store.paper_row(paper_id)\n    if paper is None:\n        raise HTTPException(status_code=404, detail=_HTTP_404_PAPER_DETAIL)\n    project_id = str(paper.get("project_id") or "")\n    run_id = str(paper.get("run_id") or "")\n    events, next_cursor, has_more = store.event_page(\n        entity_id=paper_id, page_size=event_limit, include_payload=False\n    )\n    run_row = store.run_row(run_id) if run_id else None\n    queue_item = store.queue_row(project_id) if project_id else None\n    return {\n        "ok": True,\n        "source": "control_api_v1_paper",\n        "authority": "bounded SQL paper detail read model",\n        "generated_at": utc_now(),\n        "paper_id": paper_id,\n        "paper": read_models.summarize_paper_row(paper),\n        "project": store.project_row(project_id) if project_id else None,\n        "run": read_models.summarize_run_row(run_row) if run_row else None,\n        "queue_item": read_models.summarize_queue_row(queue_item)\n        if queue_item\n        else None,\n        "events": events,\n        "events_page": read_models.page_response(\n            rows=events,\n            next_cursor=next_cursor,\n            has_more=has_more,\n            page_size_value=read_models.page_size(event_limit, cap=100),\n            cursor="",\n            filters={"entity_id": paper_id},\n        ),\n    }\n\n@router.get("/api/v1/events")\ndef dashboard_v1_events(\n    authorization: Annotated[str | None, Header()] = None,\n    event_id: str = "",\n    entity_type: str = "",\n    entity_id: str = "",\n    event_type: str = "",\n    search: str = "",\n    cursor: str = "",\n    page_size: Annotated[int, Query(ge=1, le=200)] = 50,\n    include_payload: bool = False,\n    sort: str = "recent",\n) -> dict[str, Any]:\n    authorize(authorization)\n    safe_size = read_models.page_size(page_size)\n    rows, next_cursor, has_more = store.event_page(\n        event_id=event_id,\n        entity_type=entity_type,\n        entity_id=entity_id,\n        event_type=event_type,\n        search=search,\n        cursor=cursor,\n        page_size=safe_size,\n        include_payload=include_payload,\n        sort=sort,\n    )\n    return {\n        "ok": True,\n        "source": "control_api_v1_events",\n        "authority": "bounded SQL event read model",\n        "generated_at": utc_now(),\n        "page": read_models.page_response(\n            rows=rows,\n            next_cursor=next_cursor,\n            has_more=has_more,\n            page_size_value=safe_size,\n            cursor=cursor,\n            filters={\n                "event_id": event_id,\n                "entity_type": entity_type,\n                "entity_id": entity_id,\n                "event_type": event_type,\n                "search": search,\n                "include_payload": include_payload,\n                "sort": sort,\n            },\n        ),\n        "rows": rows,\n    }\n\n@router.get("/api/v1/observability/health")\ndef dashboard_v1_observability_health(\n    authorization: Annotated[str | None, Header()] = None,\n) -> dict[str, Any]:\n    authorize(authorization)\n    latest_route_observation = None\n    if config.route_observability_enabled:\n        path = (\n            Path(config.route_observability_log_path).expanduser()\n            if config.route_observability_log_path\n            else config.expanded_state_dir / "route_observations.jsonl"\n        )\n        try:\n            with path.open("rb") as handle:\n                handle.seek(0, 2)\n                size = handle.tell()\n                handle.seek(max(0, size - 4096))\n                latest = handle.readlines()[-1:] or []\n                latest_route_observation = (\n                    latest[0].decode("utf-8", errors="replace").strip()\n                    if latest\n                    else None\n                )\n        except OSError:\n            latest_route_observation = None\n    return {\n        "ok": True,\n        "source": "control_api_v1_observability_health",\n        "authority": "bounded route observability read model",\n        "generated_at": utc_now(),\n        "route_observability_enabled": config.route_observability_enabled,\n        "route_observability_log_configured": bool(\n            config.route_observability_log_path\n        ),\n        "sentry_configured": bool(os.environ.get("SENTRY_DSN", "").strip()),\n        "sentry_enabled": is_sentry_enabled(),\n        "sentry_environment": os.environ.get("ENOCH_SENTRY_ENV")\n        or os.environ.get("ENOCH_ENV")\n        or "production",\n        "sentry_release": os.environ.get("ENOCH_SENTRY_RELEASE")\n        or os.environ.get("ENOCH_RELEASE")\n        or "unknown",\n        "latest_route_observation": latest_route_observation,\n    }\n\n@router.get("/api/v1/observability/memory")\ndef dashboard_v1_observability_memory(\n    authorization: Annotated[str | None, Header()] = None,\n) -> dict[str, Any]:\n    authorize(authorization)\n    rss = current_rss_mib()\n    peak = peak_rss_mib()\n    warn_threshold = config.route_observability_memory_warn_rss_mib\n    return {\n        "ok": True,\n        "source": "control_api_v1_observability_memory",\n        "authority": "current controller process memory sample",\n        "generated_at": utc_now(),\n        "rss_mib": rss,\n        "peak_rss_mib": peak,\n        "warn_threshold_mib": warn_threshold,\n        "memory_warn": bool(\n            warn_threshold and rss is not None and rss >= warn_threshold\n        ),\n        "route_observability_enabled": config.route_observability_enabled,\n    }\n\n',
    "_register_control_plane_api_read_routes": '@router.get("/api/queues/{queue}")\ndef dashboard_queue(\n    queue: str,\n    authorization: Annotated[str | None, Header()] = None,\n    page: Annotated[int, Query(ge=1)] = 1,\n    page_size: Annotated[int, Query(ge=1, le=500)] = 50,\n    search: str = "",\n    status: str = "",\n    sort: str = "dispatch_priority",\n) -> DashboardQueueResponse:\n    authorize(authorization)\n    all_rows = [_enrich_queue_row(row) for row in store.queue_rows()]\n    selected = (\n        [row for row in all_rows if queue in _classify_queue(row)]\n        if queue != "all"\n        else all_rows\n    )\n    if status:\n        selected = [\n            row\n            for row in selected\n            if _normal_status(row.get("status")) == _normal_status(status)\n        ]\n    selected = _sort_rows(_search_rows(selected, search), sort)\n    page_rows, safe_page, safe_size = _paginate(\n        selected, page=page, page_size=page_size\n    )\n    return DashboardQueueResponse(\n        queue=queue,\n        counts=_queue_counts(all_rows),\n        rows=page_rows,\n        page=DashboardPageMeta(\n            page=safe_page,\n            page_size=safe_size,\n            total=len(selected),\n            returned=len(page_rows),\n            queue=queue,\n            filters={"search": search, "status": status},\n            sort=sort,\n        ),\n        source_freshness=_db_freshness("canonical queue/project read model"),\n        conflicts=[],\n    )\n\n@router.get("/api/projects/{project_id}", responses=_HTTP_404_PROJECT)\ndef dashboard_project(\n    project_id: str, authorization: Annotated[str | None, Header()] = None\n) -> DashboardProjectDetailResponse:\n    authorize(authorization)\n    project = store.project_row(project_id)\n    queue_item = store.queue_row(project_id)\n    if project is None and queue_item is None:\n        raise HTTPException(status_code=404, detail="project not found")\n    runs = [row for row in store.run_rows() if row.get("project_id") == project_id]\n    papers = [\n        row for row in store.paper_rows() if row.get("project_id") == project_id\n    ]\n    observations = _worker_detail_observations(\n        project_id=project_id,\n        run_id=str((queue_item or {}).get("current_run_id") or ""),\n    )\n    warnings = []\n    active = bool(queue_item and "active" in _classify_queue(queue_item))\n    if (\n        queue_item\n        and "active" in _classify_queue(queue_item)\n        and not runs\n        and not (\n            observations.get("worker_dashboard_api_project")\n            or observations.get("worker_dashboard_api")\n        )\n    ):\n        warnings.append(\n            DashboardFinding(\n                severity="warn",\n                source="control_plane_db",\n                authority="project detail aggregate",\n                message="active queue item has no local run row or worker observation",\n                suggested_action="inspect worker and reconcile if process exited",\n            )\n        )\n    return DashboardProjectDetailResponse(\n        project_id=project_id,\n        project=project,\n        queue_item=_enrich_queue_row(queue_item) if queue_item else None,\n        runs=runs,\n        papers=papers,\n        events=_project_events(project_id),\n        worker_observations=observations,\n        source_freshness={\n            **_db_freshness("project/queue/run/paper aggregate"),\n            **_worker_detail_freshness(\n                "worker_dashboard_api",\n                "project-scoped cached worker detail",\n                f"project:{project_id}",\n            ),\n        },\n        warnings=warnings,\n        conflicts=_detail_conflicts(\n            active=active, worker_observations=observations\n        ),\n    )\n\n@router.get("/api/runs/{run_id}", responses=_HTTP_404_RUN)\ndef dashboard_run(\n    run_id: str, authorization: Annotated[str | None, Header()] = None\n) -> DashboardRunDetailResponse:\n    authorize(authorization)\n    run = store.run_row(run_id)\n    queue_item = next(\n        (row for row in store.queue_rows() if row.get("current_run_id") == run_id),\n        None,\n    )\n    project_id = str((run or queue_item or {}).get("project_id") or "")\n    if run is None and queue_item is None:\n        raise HTTPException(status_code=404, detail="run not found")\n    observations = _worker_detail_observations(project_id=project_id, run_id=run_id)\n    active = bool(queue_item and "active" in _classify_queue(queue_item))\n    return DashboardRunDetailResponse(\n        run_id=run_id,\n        run=run,\n        queue_item=_enrich_queue_row(queue_item) if queue_item else None,\n        project=store.project_row(project_id) if project_id else None,\n        papers=[row for row in store.paper_rows() if row.get("run_id") == run_id],\n        events=store.event_rows(limit=100, entity_id=run_id)\n        + (store.event_rows(limit=50, entity_id=project_id) if project_id else []),\n        worker_observations=observations,\n        source_freshness={\n            **_db_freshness("run/project/paper aggregate"),\n            **_worker_detail_freshness(\n                "worker_dashboard_api",\n                "run-scoped cached worker detail",\n                f"run:{run_id}",\n            ),\n        },\n        warnings=[]\n        if (\n            observations.get("worker_dashboard_api_run")\n            or observations.get("worker_dashboard_api")\n        )\n        else [\n            DashboardFinding(\n                severity="info",\n                source="worker_dashboard_api",\n                authority="run detail worker evidence",\n                message="no worker observation cached yet",\n                suggested_action="run /control/api/preflight or refresh run detail when available",\n            )\n        ],\n        conflicts=_detail_conflicts(\n            active=active, worker_observations=observations\n        ),\n    )\n\n',
    "_register_control_plane_publication_routes": '@router.post(\n    "/api/publication-automation/backfill",\n    responses=_HTTP_WRITABLE_IDEMPOTENCY_RESPONSES,\n)\n@router.post(\n    "/api/paper-reviews/backfill", responses=_HTTP_WRITABLE_IDEMPOTENCY_RESPONSES\n)\ndef dashboard_paper_reviews_backfill(\n    payload: PaperReviewBackfillRequest,\n    authorization: Annotated[str | None, Header()] = None,\n) -> PaperReviewBackfillResponse:\n    authorize(authorization)\n    _require_writable_store("publication automation backfill")\n    try:\n        inserted, created, updated, skipped, errors = store.backfill_paper_reviews(\n            payload\n        )\n    except IdempotencyConflict as exc:\n        raise HTTPException(status_code=409, detail=str(exc)) from exc\n    return PaperReviewBackfillResponse(\n        dry_run=payload.dry_run,\n        inserted_event=inserted,\n        created=created,\n        updated=updated,\n        skipped=skipped,\n        errors=errors,\n    )\n\n@router.get("/api/publication-automation")\ndef dashboard_publication_automation(\n    authorization: Annotated[str | None, Header()] = None,\n    page: Annotated[int, Query(ge=1)] = 1,\n    page_size: Annotated[int, Query(ge=1, le=500)] = 50,\n    review_status: str = "",\n    paper_status: str = "",\n    search: str = "",\n    sort: str = "-rank_score",\n    include_rank_reasons: bool = True,\n) -> DashboardPaperReviewsResponse:\n    return _dashboard_paper_reviews_response(\n        authorization=authorization,\n        page=page,\n        page_size=page_size,\n        review_status=review_status,\n        paper_status=paper_status,\n        search=search,\n        sort=sort,\n        include_rank_reasons=include_rank_reasons,\n        queue_label="publication_automation",\n    )\n\n@router.get("/api/paper-reviews")\ndef dashboard_paper_reviews(\n    authorization: Annotated[str | None, Header()] = None,\n    page: Annotated[int, Query(ge=1)] = 1,\n    page_size: Annotated[int, Query(ge=1, le=500)] = 50,\n    review_status: str = "",\n    paper_status: str = "",\n    search: str = "",\n    sort: str = "-rank_score",\n    include_rank_reasons: bool = True,\n) -> DashboardPaperReviewsResponse:\n    return _dashboard_paper_reviews_response(\n        authorization=authorization,\n        page=page,\n        page_size=page_size,\n        review_status=review_status,\n        paper_status=paper_status,\n        search=search,\n        sort=sort,\n        include_rank_reasons=include_rank_reasons,\n        queue_label="paper_reviews",\n    )\n\n@router.get(\n    "/api/publication-automation/next",\n    responses=_HTTP_404_PUBLICATION_AUTOMATION_NEXT,\n)\ndef dashboard_next_publication_automation(\n    authorization: Annotated[str | None, Header()] = None,\n    review_status: str = "",\n    paper_status: str = "publication_draft",\n    search: str = "",\n) -> DashboardPaperReviewDetailResponse:\n    try:\n        return _dashboard_next_paper_review_response(\n            authorization=authorization,\n            review_status=review_status,\n            paper_status=paper_status,\n            search=search,\n        )\n    except PublicationAutomationNotFoundError as exc:\n        raise HTTPException(status_code=404, detail=str(exc)) from exc\n\n@router.get(\n    "/api/paper-reviews/next", responses=_HTTP_404_PUBLICATION_AUTOMATION_NEXT\n)\ndef dashboard_next_paper_review(\n    authorization: Annotated[str | None, Header()] = None,\n    review_status: str = "",\n    paper_status: str = "publication_draft",\n    search: str = "",\n) -> DashboardPaperReviewDetailResponse:\n    try:\n        return _dashboard_next_paper_review_response(\n            authorization=authorization,\n            review_status=review_status,\n            paper_status=paper_status,\n            search=search,\n        )\n    except PublicationAutomationNotFoundError as exc:\n        raise HTTPException(status_code=404, detail=str(exc)) from exc\n\n@router.get(\n    "/api/publication-automation/{paper_id}",\n    responses=_HTTP_PUBLICATION_AUTOMATION_DETAIL_RESPONSES,\n)\ndef dashboard_publication_automation_item(\n    paper_id: str, authorization: Annotated[str | None, Header()] = None\n) -> DashboardPaperReviewDetailResponse:\n    authorize(authorization)\n    try:\n        return _paper_review_detail_response(paper_id)\n    except PublicationAutomationNotFoundError as exc:\n        raise HTTPException(\n            status_code=404, detail=PUBLICATION_AUTOMATION_ITEM_NOT_FOUND\n        ) from exc\n\n@router.get(\n    "/api/paper-reviews/{paper_id}",\n    responses=_HTTP_PUBLICATION_AUTOMATION_DETAIL_RESPONSES,\n)\ndef dashboard_paper_review(\n    paper_id: str, authorization: Annotated[str | None, Header()] = None\n) -> DashboardPaperReviewDetailResponse:\n    authorize(authorization)\n    try:\n        return _paper_review_detail_response(paper_id)\n    except PublicationAutomationNotFoundError as exc:\n        raise HTTPException(\n            status_code=404, detail=PUBLICATION_AUTOMATION_ITEM_NOT_FOUND\n        ) from exc\n\n@router.post(\n    "/api/publication-automation/{paper_id}/claim",\n    responses=_HTTP_PAPER_REVIEW_MUTATION_RESPONSES,\n)\n@router.post(\n    "/api/paper-reviews/{paper_id}/claim",\n    responses=_HTTP_PAPER_REVIEW_MUTATION_RESPONSES,\n)\ndef dashboard_paper_review_claim(\n    paper_id: str,\n    payload: PaperReviewClaimRequest,\n    authorization: Annotated[str | None, Header()] = None,\n) -> PaperReviewMutationResponse:\n    authorize(authorization)\n    _require_writable_store("publication automation claim")\n    try:\n        event_id, inserted, item = store.claim_paper_review(paper_id, payload)\n    except IdempotencyConflict as exc:\n        raise HTTPException(status_code=409, detail=str(exc)) from exc\n    except ValueError as exc:\n        raise HTTPException(status_code=400, detail=str(exc)) from exc\n    return PaperReviewMutationResponse(\n        inserted_event=inserted, event_id=event_id, item=item\n    )\n\n@router.post(\n    "/api/publication-automation/{paper_id}/checklist/{item_id}",\n    responses=_HTTP_PAPER_REVIEW_MUTATION_RESPONSES,\n)\n@router.post(\n    "/api/paper-reviews/{paper_id}/checklist/{item_id}",\n    responses=_HTTP_PAPER_REVIEW_MUTATION_RESPONSES,\n)\ndef dashboard_paper_review_checklist(\n    paper_id: str,\n    item_id: str,\n    payload: PaperReviewChecklistUpdateRequest,\n    authorization: Annotated[str | None, Header()] = None,\n) -> PaperReviewMutationResponse:\n    authorize(authorization)\n    _require_writable_store("publication automation checklist update")\n    try:\n        event_id, inserted, item = store.update_paper_review_checklist(\n            paper_id, item_id, payload\n        )\n    except IdempotencyConflict as exc:\n        raise HTTPException(status_code=409, detail=str(exc)) from exc\n    except ValueError as exc:\n        raise HTTPException(status_code=400, detail=str(exc)) from exc\n    return PaperReviewMutationResponse(\n        inserted_event=inserted, event_id=event_id, item=item\n    )\n\n@router.post(\n    "/api/publication-automation/{paper_id}/status",\n    responses=_HTTP_PAPER_REVIEW_MUTATION_RESPONSES,\n)\n@router.post(\n    "/api/paper-reviews/{paper_id}/status",\n    responses=_HTTP_PAPER_REVIEW_MUTATION_RESPONSES,\n)\ndef dashboard_paper_review_status(\n    paper_id: str,\n    payload: PaperReviewStatusUpdateRequest,\n    authorization: Annotated[str | None, Header()] = None,\n) -> PaperReviewMutationResponse:\n    authorize(authorization)\n    _require_writable_store("publication automation status update")\n    try:\n        event_id, inserted, item = store.update_paper_review_status(\n            paper_id, payload\n        )\n    except IdempotencyConflict as exc:\n        raise HTTPException(status_code=409, detail=str(exc)) from exc\n    except ValueError as exc:\n        raise HTTPException(status_code=400, detail=str(exc)) from exc\n    return PaperReviewMutationResponse(\n        inserted_event=inserted, event_id=event_id, item=item\n    )\n\n@router.post(\n    "/api/publication-automation/{paper_id}/approve-finalization",\n    responses=_HTTP_PAPER_REVIEW_MUTATION_RESPONSES,\n)\n@router.post(\n    "/api/paper-reviews/{paper_id}/approve-finalization",\n    responses=_HTTP_PAPER_REVIEW_MUTATION_RESPONSES,\n)\ndef dashboard_paper_review_approve_finalization(\n    paper_id: str,\n    payload: PaperReviewApproveFinalizationRequest,\n    authorization: Annotated[str | None, Header()] = None,\n) -> PaperReviewMutationResponse:\n    authorize(authorization)\n    _require_writable_store("publication automation finalization approval")\n    try:\n        event_id, inserted, item = store.approve_paper_review_finalization(\n            paper_id, payload\n        )\n    except IdempotencyConflict as exc:\n        raise HTTPException(status_code=409, detail=str(exc)) from exc\n    except ValueError as exc:\n        raise HTTPException(status_code=400, detail=str(exc)) from exc\n    return PaperReviewMutationResponse(\n        inserted_event=inserted, event_id=event_id, item=item\n    )\n\n@router.post(\n    "/api/publication-automation/rewrite-batch",\n    responses=_PAPER_REWRITE_DRAFT_RESPONSES,\n)\n@router.post(\n    "/api/paper-reviews/rewrite-batch",\n    responses=_PAPER_REWRITE_DRAFT_RESPONSES,\n)\ndef dashboard_paper_reviews_rewrite_batch(\n    payload: PaperReviewBulkRewriteRequest,\n    authorization: Annotated[str | None, Header()] = None,\n) -> PaperReviewBulkRewriteResponse:\n    authorize(authorization)\n    if not payload.dry_run:\n        _require_writable_store("publication automation rewrite batch")\n    rows = store.paper_review_rows(include_rank_reasons=True)\n    if payload.review_status:\n        rows = [\n            row\n            for row in rows\n            if _normal_status(row.get("review_status"))\n            == _normal_status(payload.review_status)\n        ]\n    else:\n        rows = [\n            row\n            for row in rows\n            if _normal_status(row.get("review_status"))\n            not in {\n                "blocked",\n                "changes_requested",\n                "finalized",\n                "in_review",\n                "rejected",\n                "unreviewed",\n            }\n        ]\n    if payload.paper_status:\n        rows = [\n            row\n            for row in rows\n            if _normal_status(row.get("paper_status"))\n            == _normal_status(payload.paper_status)\n        ]\n    if payload.skip_rewritten:\n        rows = [\n            row\n            for row in rows\n            if not store.event_rows(\n                limit=1,\n                entity_id=str(row.get("paper_id") or ""),\n                event_type=PAPER_REVIEW_DRAFT_REWRITTEN,\n            )\n        ]\n    rows = _sort_rows(_search_rows(rows, payload.search), "-rank_score")\n    matched = len(rows)\n    selected = rows[: payload.limit]\n    out_rows: list[dict[str, Any]] = []\n    if payload.dry_run:\n        for row in selected:\n            out_rows.append(\n                {\n                    "paper_id": row.get("paper_id"),\n                    "project_name": row.get("project_name"),\n                    "action": "would_rewrite",\n                }\n            )\n        return PaperReviewBulkRewriteResponse(\n            dry_run=True,\n            matched=matched,\n            processed=len(selected),\n            rewritten=0,\n            failed=0,\n            rows=out_rows,\n        )\n    rewritten = 0\n    failed = 0\n    for index, row in enumerate(selected, start=1):\n        pid = str(row.get("paper_id") or "")\n        try:\n            result = _rewrite_paper_review_draft(\n                pid,\n                PaperReviewRewriteDraftRequest(\n                    idempotency_key=f"{payload.idempotency_key}:{index}:{pid}",\n                    requested_by=payload.requested_by,\n                    force=payload.force,\n                ),\n            )\n            rewritten += 1\n            out_rows.append(\n                {\n                    "paper_id": pid,\n                    "project_name": row.get("project_name"),\n                    "ok": True,\n                    "provider": result.writer.get("provider"),\n                    "model": result.writer.get("model"),\n                    "evidence_sync": result.writer.get("evidence_sync"),\n                    "artifact_root": result.artifact_root,\n                }\n            )\n        except HTTPException as exc:\n            failed += 1\n            out_rows.append(\n                {\n                    "paper_id": pid,\n                    "project_name": row.get("project_name"),\n                    "ok": False,\n                    "error": exc.detail,\n                }\n            )\n        except (\n            PublicationAutomationNotFoundError,\n            PaperRewriteEvidenceRequiredError,\n            PaperArtifactRootNotInspectableError,\n            ValueError,\n        ) as exc:\n            failed += 1\n            out_rows.append(\n                {\n                    "paper_id": pid,\n                    "project_name": row.get("project_name"),\n                    "ok": False,\n                    "error": str(exc),\n                }\n            )\n        except (\n            Exception\n        ) as exc:  # pragma: no cover - defensive for live batch operations\n            failed += 1\n            out_rows.append(\n                {\n                    "paper_id": pid,\n                    "project_name": row.get("project_name"),\n                    "ok": False,\n                    "error": f"{type(exc).__name__}: {exc}",\n                }\n            )\n    return PaperReviewBulkRewriteResponse(\n        dry_run=False,\n        matched=matched,\n        processed=len(selected),\n        rewritten=rewritten,\n        failed=failed,\n        rows=out_rows,\n    )\n\n@router.post(\n    "/api/publication-automation/{paper_id}/rewrite-draft",\n    responses=_PAPER_REWRITE_DRAFT_RESPONSES,\n)\n@router.post(\n    "/api/paper-reviews/{paper_id}/rewrite-draft",\n    responses=_PAPER_REWRITE_DRAFT_RESPONSES,\n)\ndef dashboard_paper_review_rewrite_draft(\n    paper_id: str,\n    payload: PaperReviewRewriteDraftRequest,\n    authorization: Annotated[str | None, Header()] = None,\n) -> PaperReviewRewriteDraftResponse:\n    authorize(authorization)\n    _require_writable_store("publication automation draft rewrite")\n    try:\n        return _rewrite_paper_review_draft(paper_id, payload)\n    except PublicationAutomationNotFoundError as exc:\n        raise HTTPException(\n            status_code=404, detail=PUBLICATION_AUTOMATION_ITEM_NOT_FOUND\n        ) from exc\n    except PaperRewriteBlockedReviewStatusError as exc:\n        raise HTTPException(status_code=400, detail=str(exc)) from exc\n    except (\n        UnresolvableConfiguredProjectRootError,\n        PaperArtifactRootError,\n        PaperArtifactRootNotInspectableError,\n        PaperArtifactSnapshotReadError,\n    ) as exc:\n        raise HTTPException(status_code=400, detail=str(exc)) from exc\n    except PaperRewriteIdempotencyReuseError as exc:\n        raise HTTPException(status_code=409, detail=str(exc)) from exc\n    except PaperRewriteEvidenceRequiredError as exc:\n        raise HTTPException(\n            status_code=424,\n            detail={\n                "message": "paper rewrite requires synced project evidence",\n                "evidence_sync": exc.evidence_sync,\n            },\n        ) from exc\n    except IdempotencyConflict as exc:\n        raise HTTPException(status_code=409, detail=str(exc)) from exc\n    except ValueError as exc:\n        raise HTTPException(status_code=400, detail=str(exc)) from exc\n\n@router.post(\n    "/api/publication-automation/{paper_id}/prepare-finalization-package",\n    responses=_HTTP_500_UNRESOLVABLE_ARTIFACT_ROOT,\n)\n@router.post(\n    "/api/paper-reviews/{paper_id}/prepare-finalization-package",\n    responses=_HTTP_500_UNRESOLVABLE_ARTIFACT_ROOT,\n)\ndef dashboard_paper_review_prepare_finalization_package(\n    paper_id: str,\n    payload: PaperReviewPrepareFinalizationRequest,\n    authorization: Annotated[str | None, Header()] = None,\n) -> PaperReviewFinalizationPackageResponse:\n    authorize(authorization)\n    _require_writable_store("publication automation finalization package")\n    _require_safe_paper_artifact_root(paper_id)\n    try:\n        event_id, inserted, item, package_path, manifest = (\n            store.prepare_paper_review_finalization_package(\n                paper_id, payload, require_approval=False\n            )\n        )\n    except IdempotencyConflict as exc:\n        raise HTTPException(status_code=409, detail=str(exc)) from exc\n    except ValueError as exc:\n        raise HTTPException(status_code=400, detail=str(exc)) from exc\n    return PaperReviewFinalizationPackageResponse(\n        dry_run=payload.dry_run,\n        inserted_event=inserted,\n        event_id=event_id,\n        item=item,\n        package_path=package_path,\n        manifest=manifest,\n    )\n\n@router.get("/api/papers")\ndef dashboard_papers(\n    authorization: Annotated[str | None, Header()] = None,\n    page: Annotated[int, Query(ge=1)] = 1,\n    page_size: Annotated[int, Query(ge=1, le=500)] = 50,\n    search: str = "",\n    status: str = "",\n    sort: str = "-updated_at",\n) -> DashboardPapersResponse:\n    authorize(authorization)\n    rows = store.paper_rows()\n    all_counts = _paper_counts(rows)\n    if status:\n        rows = [\n            row\n            for row in rows\n            if _normal_status(row.get("paper_status")) == _normal_status(status)\n        ]\n    rows = _sort_rows(_search_rows(rows, search), sort)\n    page_rows, safe_page, safe_size = _paginate(\n        rows, page=page, page_size=page_size\n    )\n    for row in page_rows:\n        row["links"] = {\n            "paper": f"/control/api/papers/{row.get(\'paper_id\') or \'\'}",\n            "project": f"/control/api/projects/{row.get(\'project_id\') or \'\'}",\n            "run": f"/control/api/runs/{row.get(\'run_id\') or \'\'}"\n            if row.get("run_id")\n            else "",\n        }\n    return DashboardPapersResponse(\n        page=DashboardPageMeta(\n            page=safe_page,\n            page_size=safe_size,\n            total=len(rows),\n            returned=len(page_rows),\n            queue="papers",\n            filters={"search": search, "status": status},\n            sort=sort,\n        ),\n        counts=all_counts,\n        rows=page_rows,\n        source_freshness=_db_freshness("canonical paper queue read model"),\n        conflicts=[],\n    )\n\n@router.get(\n    "/api/papers/{paper_id}/artifact/{field}",\n    responses=_HTTP_500_UNRESOLVABLE_ARTIFACT_ROOT,\n)\ndef dashboard_paper_artifact(\n    paper_id: str, field: str, authorization: Annotated[str | None, Header()] = None\n) -> dict[str, Any]:\n    authorize(authorization)\n    paper = store.paper_row(paper_id)\n    if paper is None:\n        raise HTTPException(status_code=404, detail=_HTTP_404_PAPER_DETAIL)\n    path = _resolve_paper_artifact(paper, field)\n    max_bytes = 1_000_000\n    try:\n        data = path.read_bytes()\n        size_bytes = path.stat().st_size\n    except (OSError, RuntimeError, ValueError) as exc:\n        raise HTTPException(\n            status_code=404, detail=f"paper artifact is not readable: {field}"\n        ) from exc\n    truncated = len(data) > max_bytes\n    if truncated:\n        data = data[:max_bytes]\n    return {\n        "ok": True,\n        "paper_id": paper_id,\n        "project_id": str(paper.get("project_id") or ""),\n        "project_name": str(paper.get("project_name") or ""),\n        "field": field,\n        "path": str(paper.get(field) or ""),\n        "absolute_path": str(path),\n        "size_bytes": size_bytes,\n        "truncated": truncated,\n        "content": data.decode("utf-8", errors="replace"),\n    }\n\n@router.get("/api/papers/{paper_id}", responses=_HTTP_404_PAPER)\ndef dashboard_paper(\n    paper_id: str, authorization: Annotated[str | None, Header()] = None\n) -> DashboardPaperDetailResponse:\n    authorize(authorization)\n    paper = store.paper_row(paper_id)\n    if paper is None:\n        raise HTTPException(status_code=404, detail=_HTTP_404_PAPER_DETAIL)\n    project_id = str(paper.get("project_id") or "")\n    run_id = str(paper.get("run_id") or "")\n    missing = [\n        name\n        for name in (\n            "draft_markdown_path",\n            "draft_latex_path",\n            "evidence_bundle_path",\n            "claim_ledger_path",\n            "manifest_path",\n        )\n        if not paper.get(name)\n    ]\n    warnings = (\n        [\n            DashboardFinding(\n                severity="warn",\n                source="control_plane_db",\n                authority="paper artifact record",\n                message=f"paper is missing artifact path(s): {\', \'.join(missing)}",\n                suggested_action="generate or reconcile paper artifacts",\n            )\n        ]\n        if missing\n        else []\n    )\n    return DashboardPaperDetailResponse(\n        paper_id=paper_id,\n        paper=paper,\n        project=store.project_row(project_id) if project_id else None,\n        run=store.run_row(run_id) if run_id else None,\n        events=store.event_rows(limit=100, entity_id=paper_id)\n        + (store.event_rows(limit=50, entity_id=project_id) if project_id else []),\n        source_freshness=_db_freshness("paper/project/run aggregate"),\n        warnings=warnings,\n        conflicts=[],\n    )\n\n@router.get("/api/events")\ndef dashboard_events(\n    authorization: Annotated[str | None, Header()] = None,\n    page: Annotated[int, Query(ge=1)] = 1,\n    page_size: Annotated[int, Query(ge=1, le=500)] = 100,\n    entity_type: str = "",\n    entity_id: str = "",\n    event_type: str = "",\n    search: str = "",\n) -> DashboardEventsResponse:\n    authorize(authorization)\n    rows = store.event_rows(\n        limit=1000,\n        entity_type=entity_type,\n        entity_id=entity_id,\n        event_type=event_type,\n        search=search,\n    )\n    page_rows, safe_page, safe_size = _paginate(\n        rows, page=page, page_size=page_size\n    )\n    return DashboardEventsResponse(\n        page=DashboardPageMeta(\n            page=safe_page,\n            page_size=safe_size,\n            total=len(rows),\n            returned=len(page_rows),\n            queue="events",\n            filters={\n                "entity_type": entity_type,\n                "entity_id": entity_id,\n                "event_type": event_type,\n                "search": search,\n            },\n            sort="-event_id",\n        ),\n        rows=page_rows,\n        source_freshness=_db_freshness("append-only control event log"),\n        conflicts=[],\n    )\n\n@router.get("/api/intake/ideas")\ndef dashboard_ideas_intake(\n    authorization: Annotated[str | None, Header()] = None,\n    page_size: Annotated[int, Query(ge=1, le=200)] = 50,\n    include_latest_payload: Annotated[bool, Query()] = False,\n) -> DashboardIntakeResponse:\n    authorize(authorization)\n    return _dashboard_ideas_intake_response(\n        page_size=page_size, include_latest_payload=include_latest_payload\n    )\n\n@router.get("/api/research/facility")\ndef dashboard_research_facility(\n    authorization: Annotated[str | None, Header()] = None,\n    page_size: Annotated[int, Query(ge=1, le=200)] = 50,\n) -> dict[str, Any]:\n    authorize(authorization)\n    rows = (\n        store.research_facility_workbench_projection(limit=page_size)\n        if hasattr(store, "research_facility_workbench_projection")\n        else []\n    )\n    counts = (\n        store.research_facility_workbench_counts()\n        if hasattr(store, "research_facility_workbench_counts")\n        else {}\n    )\n    if not counts:\n        for row in rows:\n            status = str(row.get("status") or "unknown")\n            counts[status] = counts.get(status, 0) + 1\n    return {\n        "ok": True,\n        "authority": "Research Facility ledgers: sources, candidates, admissions, lineage",\n        "operator_summary": read_models.summarize_research_facility_workbench(\n            counts=counts, returned_rows=len(rows)\n        ),\n        "rows": rows,\n        "counts": counts,\n        "page": {\n            "page_size": page_size,\n            "returned": len(rows),\n            "counts_scope": "all_rows"\n            if hasattr(store, "research_facility_workbench_counts")\n            else "returned_rows",\n        },\n    }\n\n@router.post("/api/research/generate-batch", responses=_HTTP_501_SUPABASE_LEDGER)\ndef dashboard_research_generate_batch(\n    payload: Annotated[dict[str, Any] | None, Body()] = None,\n    authorization: Annotated[str | None, Header()] = None,\n) -> dict[str, Any]:\n    authorize(authorization)\n    from argparse import Namespace\n    from scripts import research_facility, research_facility_scan\n\n    body = payload or {}\n    dry_run = bool(body.get("dry_run", True))\n    max_candidates = _bounded_int_from_mapping(body, "max_candidates", 3, 1, 10)\n    requested_by = str(body.get("requested_by") or "dashboard")[:80]\n    if not dry_run:\n        _require_writable_store("Research Facility candidate generation")\n    source_specs = [\n        {\n            "title": "Provider-budget-aware idea generation scheduler",\n            "summary": "Test whether local idea generation should check provider quota, rolling budget, and queue state before spending inference requests on new research candidates.",\n            "url": "enoch://research-facility/smoke/provider-budget-scheduler",\n        },\n        {\n            "title": "Counterexample-first candidate admission gate",\n            "summary": "Test whether candidate ideas should carry explicit falsification probes before admission, reducing shallow incremental work and preventing positive-only framing.",\n            "url": "enoch://research-facility/smoke/counterexample-admission-gate",\n        },\n        {\n            "title": "Queue-safe candidate promotion ledger",\n            "summary": "Test whether generated candidates can be promoted to queued projects only through an auditable ledger that preserves dry-run evidence and prevents accidental dispatch.",\n            "url": "enoch://research-facility/smoke/queue-safe-promotion-ledger",\n        },\n    ][:max_candidates]\n    records = [\n        research_facility_scan.SourceRecord.from_parts(\n            source_kind="internal_generated",\n            title=spec["title"],\n            url=spec["url"],\n            summary=spec["summary"],\n            payload_json={"smoke_test": True, "requested_by": requested_by},\n        )\n        for spec in source_specs\n    ]\n    candidates = [\n        research_facility_scan.candidate_from_source(\n            record,\n            default_machine=os.environ.get(\n                "ENOCH_RESEARCH_DEFAULT_MACHINE", "research-facility-node"\n            ),  # NOSONAR\n            default_model=os.environ.get(\n                "ENOCH_RESEARCH_DEFAULT_MODEL", _DEFAULT_RESEARCH_MODEL\n            ),\n            default_sandbox=os.environ.get(\n                "ENOCH_RESEARCH_DEFAULT_SANDBOX", "danger-full-access"\n            ),\n        )\n        for record in records\n    ]\n    plans = research_facility.plan_candidates(\n        candidates,\n        Namespace(\n            default_machine=os.environ.get(\n                "ENOCH_RESEARCH_DEFAULT_MACHINE", "research-facility-node"\n            ),  # NOSONAR\n            default_model=os.environ.get(\n                "ENOCH_RESEARCH_DEFAULT_MODEL", _DEFAULT_RESEARCH_MODEL\n            ),\n            default_sandbox=os.environ.get(\n                "ENOCH_RESEARCH_DEFAULT_SANDBOX", "danger-full-access"\n            ),\n            admit_threshold=_bounded_float_from_mapping(\n                body, "admit_threshold", 72.0, 0.0, 100.0\n            ),\n            review_threshold=_bounded_float_from_mapping(\n                body, "review_threshold", 58.0, 0.0, 100.0\n            ),\n            history=[],\n        ),\n    )\n    plan_json = [plan.to_json() for plan in plans]\n    response = {\n        "ok": True,\n        "action": "dry_run_generate_candidates"\n        if dry_run\n        else "generate_candidates",\n        "dry_run": dry_run,\n        "queue_admitted": False,\n        "candidate_count": len(plans),\n        "admitted_count": sum(\n            1 for plan in plans if plan.admission_decision == "admitted"\n        ),\n        "needs_review_count": sum(\n            1 for plan in plans if plan.admission_decision == "needs_review"\n        ),\n        "rejected_count": sum(\n            1 for plan in plans if plan.admission_decision == "rejected"\n        ),\n        "queued_count": 0,\n        "plans": plan_json,\n    }\n    if dry_run:\n        return response\n    if not hasattr(store, "record_research_facility_plans"):\n        raise HTTPException(\n            status_code=501,\n            detail=RESEARCH_FACILITY_LEDGER_REQUIRES_SUPABASE_STORE,\n        )\n    response["ledger_result"] = store.record_research_facility_plans(\n        plans, requested_by=requested_by, queue_admitted=False\n    )\n    return response\n\n@router.post(\n    "/api/research/generate-provider-batch", responses=_HTTP_501_SUPABASE_LEDGER\n)\ndef dashboard_research_generate_provider_batch(\n    payload: Annotated[dict[str, Any] | None, Body()] = None,\n    authorization: Annotated[str | None, Header()] = None,\n) -> dict[str, Any]:\n    authorize(authorization)\n    from argparse import Namespace\n    from scripts import (\n        research_facility,\n        research_provider_budget,\n        research_provider_generate,\n    )\n\n    body = payload or {}\n    dry_run = bool(body.get("dry_run", True))\n    max_candidates = _bounded_int_from_mapping(body, "max_candidates", 2, 1, 5)\n    requested_by = str(body.get("requested_by") or "dashboard")[:80]\n    if not dry_run:\n        _require_writable_store("Research Facility provider generation")\n    provider_base_url = os.environ.get(\n        "ENOCH_RESEARCH_PROVIDER_BASE_URL", DEFAULT_RESEARCH_PROVIDER_BASE_URL\n    ).rstrip("/")\n    provider_openai_base_url = os.environ.get(\n        "ENOCH_RESEARCH_PROVIDER_OPENAI_BASE_URL", f"{provider_base_url}/openai/v1"\n    ).rstrip("/")\n    provider_model = str(\n        body.get("model")\n        or os.environ.get("ENOCH_RESEARCH_PROVIDER_MODEL")\n        or DEFAULT_ALLOWED_RESEARCH_MODELS[-1]\n    ).strip()\n    topic = str(body.get("topic") or "").strip()\n    temperature = _bounded_float_from_mapping(body, "temperature", 0.8, 0.0, 1.5)\n    seed = str(body.get("seed") or utc_now()).strip()\n    reserve_requests = _bounded_int_from_mapping(\n        body, "reserve_requests", 2, 1, 100\n    )\n    budget_timeout = _bounded_int_from_mapping(body, "budget_timeout", 20, 1, 60)\n    generation_timeout = _bounded_int_from_mapping(\n        body, "generation_timeout", 180, 10, 300\n    )\n    generation_max_tokens = _bounded_int_from_mapping(\n        body,\n        "generation_max_tokens",\n        _bounded_int_env("ENOCH_RESEARCH_PROVIDER_MAX_TOKENS", 8000, 1000, 16000),\n        1000,\n        16000,\n    )\n    generation_attempts = _bounded_int_from_mapping(\n        body,\n        "generation_attempts",\n        _bounded_int_env("ENOCH_RESEARCH_PROVIDER_ATTEMPTS", 2, 1, 3),\n        1,\n        3,\n    )\n    estimated_requests = generation_attempts\n    try:\n        quota_payload = research_provider_budget.fetch_json(\n            f"{provider_base_url}/v2/quotas", api_key="", timeout=budget_timeout\n        )\n        budget = research_provider_budget.synthetic_budget_status(\n            quota_payload,\n            min_remaining_credits=_bounded_float_from_mapping(\n                body, "min_remaining_credits", 5.0, 0.0, 1_000_000.0\n            ),\n            min_rolling_remaining=_bounded_int_from_mapping(\n                body, "min_rolling_remaining", 10, 0, 100_000\n            ),\n            estimated_requests=estimated_requests,\n            reserve_requests=reserve_requests,\n        )\n    except Exception as exc:  # noqa: BLE001 - generation must fail closed if budget cannot be checked\n        budget = {\n            "ok": False,\n            "provider": "synthetic",\n            "checked_at": utc_now(),\n            "estimated_requests": estimated_requests,\n            "reserve_requests": reserve_requests,\n            "failures": [f"provider budget check failed: {exc}"],\n        }\n    safe_budget_keys = {\n        "ok",\n        "provider",\n        "checked_at",\n        "estimated_requests",\n        "reserve_requests",\n        "remaining_credits",\n        "min_remaining_credits",\n        "rolling_remaining",\n        "rolling_max",\n        "rolling_limited",\n        "rolling_next_tick_at",\n        "weekly_next_regen_at",\n        "weekly_next_regen_credits",\n        "subscription_remaining",\n        "subscription_renews_at",\n        "failures",\n    }\n    safe_budget = {\n        key: budget.get(key) for key in safe_budget_keys if key in budget\n    }\n    response: dict[str, Any] = {\n        "ok": bool(budget.get("ok")),\n        "action": "dry_run_provider_generate_candidates"\n        if dry_run\n        else "provider_generate_candidates",\n        "dry_run": dry_run,\n        "queue_admitted": False,\n        "dispatch_started": False,\n        "provider": "synthetic.new",\n        "provider_model": provider_model,\n        "max_candidates": max_candidates,\n        "topic": topic,\n        "temperature": temperature,\n        "generation_max_tokens": generation_max_tokens,\n        "generation_attempts": generation_attempts,\n        "seed": seed,\n        "budget": safe_budget,\n        "queued_count": 0,\n    }\n    if not budget.get("ok"):\n        response["action"] = "provider_generation_blocked"\n        response["reason"] = "; ".join(\n            str(item)\n            for item in budget.get("failures") or ["provider budget unavailable"]\n        )\n        return response\n    if dry_run:\n        response["reason"] = (\n            "provider budget passed; no provider request spent and no ledger rows written"\n        )\n        return response\n    if not hasattr(store, "record_research_facility_plans"):\n        raise HTTPException(\n            status_code=501,\n            detail=RESEARCH_FACILITY_LEDGER_REQUIRES_SUPABASE_STORE,\n        )\n    try:\n        generated = research_provider_generate.generate_provider_candidates(\n            base_url=provider_openai_base_url,\n            model=provider_model,\n            api_key="",\n            max_candidates=max_candidates,\n            topic=topic,\n            temperature=temperature,\n            seed=seed,\n            timeout=generation_timeout,\n            max_tokens=generation_max_tokens,\n            attempts=generation_attempts,\n            default_machine=os.environ.get(\n                "ENOCH_RESEARCH_DEFAULT_MACHINE", "research-facility-node"\n            ),  # NOSONAR\n            default_model=os.environ.get(\n                "ENOCH_RESEARCH_DEFAULT_MODEL", _DEFAULT_RESEARCH_MODEL\n            ),\n            default_sandbox=os.environ.get(\n                "ENOCH_RESEARCH_DEFAULT_SANDBOX", "danger-full-access"\n            ),\n        )\n    except Exception as exc:  # noqa: BLE001 - provider generation must fail closed without ledger writes\n        response.update(\n            {\n                "ok": False,\n                "action": "provider_generation_failed",\n                "reason": f"provider generation failed before ledger write: {exc}",\n                "candidate_count": 0,\n                "admitted_count": 0,\n                "needs_review_count": 0,\n                "rejected_count": 0,\n            }\n        )\n        return response\n    generated_candidates = (generated.get("candidates") or [])[:max_candidates]\n    if not generated_candidates:\n        response.update(\n            {\n                "ok": False,\n                "action": "provider_generation_failed",\n                "reason": "provider generation returned 0 usable candidates; no ledger rows written",\n                "candidate_count": 0,\n                "admitted_count": 0,\n                "needs_review_count": 0,\n                "rejected_count": 0,\n                "provider_response_id": generated.get("provider_response_id", ""),\n            }\n        )\n        return response\n    plans = research_facility.plan_candidates(\n        generated_candidates,\n        Namespace(\n            default_machine=os.environ.get(\n                "ENOCH_RESEARCH_DEFAULT_MACHINE", "research-facility-node"\n            ),  # NOSONAR\n            default_model=os.environ.get(\n                "ENOCH_RESEARCH_DEFAULT_MODEL", _DEFAULT_RESEARCH_MODEL\n            ),\n            default_sandbox=os.environ.get(\n                "ENOCH_RESEARCH_DEFAULT_SANDBOX", "danger-full-access"\n            ),\n            admit_threshold=_bounded_float_from_mapping(\n                body, "admit_threshold", 72.0, 0.0, 100.0\n            ),\n            review_threshold=_bounded_float_from_mapping(\n                body, "review_threshold", 58.0, 0.0, 100.0\n            ),\n            history=[],\n        ),\n    )\n    response["candidate_count"] = len(plans)\n    response["admitted_count"] = sum(\n        1 for plan in plans if plan.admission_decision == "admitted"\n    )\n    response["needs_review_count"] = sum(\n        1 for plan in plans if plan.admission_decision == "needs_review"\n    )\n    response["rejected_count"] = sum(\n        1 for plan in plans if plan.admission_decision == "rejected"\n    )\n    response["provider_response_id"] = generated.get("provider_response_id", "")\n    response["attempts_used"] = generated.get("attempts_used", 1)\n    response["plans"] = [plan.to_json() for plan in plans]\n    response["ledger_result"] = store.record_research_facility_plans(\n        plans, requested_by=requested_by, queue_admitted=False\n    )\n    return response\n\n',
    "_register_control_plane_papers_events_routes": '@router.post(\n    "/api/research/run-cycle",\n    responses=_HTTP_400_RESEARCH_CANDIDATE_ID,\n)\ndef dashboard_research_run_cycle(\n    payload: Annotated[dict[str, Any] | None, Body()] = None,\n    authorization: Annotated[str | None, Header()] = None,\n) -> dict[str, Any]:\n    """Run one bounded Research Facility cycle.\n\n    This is intentionally a small automation step:\n    provider quota check -> optional generation/admission ledgers -> explicit\n    promotion of admitted candidates -> optional single dispatch -> optional\n    positive-gated paper draft/finalization. It never unpauses the broad\n    queue and every mutating stage is bounded by per-run limits.\n    """\n\n    authorize(authorization)\n    from argparse import Namespace\n    from scripts import (\n        research_facility,\n        research_provider_budget,\n        research_provider_generate,\n    )\n\n    body = payload or {}\n    dry_run = bool(body.get("dry_run", True))\n    enabled = bool(body.get("enabled", False))\n    requested_by = str(body.get("requested_by") or "dashboard")[:80]\n    operator_trace = OperatorTrace.from_config(config)\n    trace_id = OperatorTrace.new_trace_id("research-cycle")\n    run_cycle_id = OperatorTrace.new_trace_id("run-cycle")\n    if not dry_run:\n        _require_writable_store("Research Facility run-cycle")\n    if (\n        not hasattr(store, "research_facility_workbench_projection")\n        or not hasattr(store, "record_research_facility_plans")\n        or not hasattr(store, "promote_research_candidate")\n    ):\n        raise HTTPException(\n            status_code=501,\n            detail="Research Facility run-cycle requires the Supabase control-plane store",\n        )\n\n    model_resolution = _resolve_research_provider_model(body)\n    if isinstance(model_resolution, dict):\n        return model_resolution\n    provider_model, allowed_models = model_resolution\n\n    bounded_int = partial(_bounded_int_from_mapping, body)\n    bounded_float = partial(_bounded_float_from_mapping, body)\n\n    # The 3 inputs below feed (or parallel) the extracted resolver...\n    worker_lane_limit = max(1, min(4, len(_configured_worker_lanes()) or 1))\n    promotion_batch_limit = _bounded_int_env(\n        "ENOCH_RESEARCH_MAX_PROMOTIONS_PER_RUN_CAP", 25, 1, 100\n    )\n\n    params = _resolve_research_cycle_params(\n        body,\n        worker_lane_limit=worker_lane_limit,\n        promotion_batch_limit=promotion_batch_limit,\n    )\n\n    max_provider_requests = params.max_provider_requests\n    max_promotions = params.max_promotions\n    max_dispatches = params.max_dispatches\n    min_queue_depth_per_lane = params.min_queue_depth_per_lane\n    max_paper_drafts = params.max_paper_drafts\n    max_publication_rewrites = params.max_publication_rewrites\n    wait_for_completion = params.wait_for_completion\n    max_wait_seconds = params.max_wait_seconds\n    poll_interval_seconds = params.poll_interval_seconds\n    min_admission_score = params.min_admission_score\n    max_candidates = params.max_candidates\n    fresh_generation_backlog_threshold = params.fresh_generation_backlog_threshold\n    topic = params.topic\n    temperature = params.temperature\n    seed = params.seed\n    provider_base_url = params.provider_base_url\n    provider_openai_base_url = params.provider_openai_base_url\n    generation_timeout = params.generation_timeout\n    generation_max_tokens = params.generation_max_tokens\n    generation_attempts = params.generation_attempts\n\n    active = store.active_items()\n    counts = store.status_counts()\n    blocked_count = int(counts.get("blocked") or 0)\n    backpressure_reasons: list[str] = []\n    estimated_requests = max_provider_requests * generation_attempts\n    budget = _fetch_synthetic_research_budget(\n        provider_base_url=provider_base_url,\n        estimated_requests=estimated_requests,\n        bounded_int=bounded_int,\n        bounded_float=bounded_float,\n        research_provider_budget=research_provider_budget,\n    )\n    stop_reasons = _collect_research_cycle_stop_reasons(\n        body=body,\n        dry_run=dry_run,\n        enabled=enabled,\n        blocked_count=blocked_count,\n        budget=budget,\n        max_provider_requests=max_provider_requests,\n        backpressure_reasons=backpressure_reasons,\n    )\n\n    research_row_lane_key = partial(_research_row_lane_key, _worker_lane_key)\n    promotable_rows = partial(\n        _compute_promotable_rows,\n        store=store,\n        min_admission_score=min_admission_score,\n        active=active,\n        research_row_lane_key=research_row_lane_key,\n        research_facility=research_facility,\n    )\n\n    janitor_enabled = bool(body.get("janitor_enabled", True))\n    janitor_limit = bounded_int("janitor_limit", 250, 0, 500)\n    janitor_report = _compute_janitor_report(\n        store=store,\n        janitor_enabled=janitor_enabled,\n        janitor_limit=janitor_limit,\n        max_promotions=max_promotions,\n        dry_run=dry_run,\n        stop_reasons=stop_reasons,\n        backpressure_reasons=backpressure_reasons,\n        requested_by=requested_by,\n    )\n\n    initial_promotable = promotable_rows()\n    active_lane_keys = {_worker_lane_key(row) for row in active}\n    initial_open_lane_promotable = open_lane_research_rows(\n        initial_promotable,\n        active_lane_keys,\n        lane_key_func=research_row_lane_key,\n    )\n    initial_feed_lanes = _worker_lane_capacity(\n        active=active, rows=_queue_rows_for_lane_feed()\n    )\n    lane_feed_pressure = _research_lane_feed_pressure(\n        active=active,\n        queued=_queue_rows_for_lane_feed(),\n        lanes=initial_feed_lanes,\n        promotable=initial_promotable,\n        min_queue_depth=min_queue_depth_per_lane,\n        min_admission_score=min_admission_score,\n    )\n    generation_target_lane = _select_generation_target_lane(lane_feed_pressure)\n    operator_trace.record(\n        "research.run_cycle.start",\n        trace_id=trace_id,\n        run_cycle_id=run_cycle_id,\n        requested_by=requested_by,\n        dry_run=dry_run,\n        enabled=enabled,\n        active_count=len(active),\n        queued_count=int(counts.get("queued") or 0),\n        blocked_count=blocked_count,\n        max_provider_requests=max_provider_requests,\n        max_promotions=max_promotions,\n        max_dispatches=max_dispatches,\n    )\n    operator_trace.record(\n        "research.lanes.before",\n        trace_id=trace_id,\n        run_cycle_id=run_cycle_id,\n        requested_by=requested_by,\n        lanes=summarize_lane_snapshot(initial_feed_lanes),\n    )\n    operator_trace.record(\n        "research.generation_target.selected",\n        trace_id=trace_id,\n        run_cycle_id=run_cycle_id,\n        requested_by=requested_by,\n        machine_target=(generation_target_lane or {}).get("machine_target") if generation_target_lane else "",\n        lane_key=(generation_target_lane or {}).get("lane_key") if generation_target_lane else "",\n        target=generation_target_lane,\n    )\n    idle_queued_lane_available = _research_cycle_idle_queued_lane_available(\n        lanes=initial_feed_lanes, max_dispatches=max_dispatches\n    )\n    backpressure_reasons.extend(\n        _evaluate_research_cycle_backpressure(\n            active=active,\n            initial_open_lane_promotable=initial_open_lane_promotable,\n            generation_target_lane=generation_target_lane,\n            max_provider_requests=max_provider_requests,\n            idle_queued_lane_available=idle_queued_lane_available,\n        )\n    )\n    response = _build_research_cycle_initial_response(\n        params=_ResearchCycleInitialResponseParams(\n            dry_run=dry_run,\n            enabled=enabled,\n            provider_model=provider_model,\n            allowed_models=allowed_models,\n            body=body,\n            max_provider_requests=max_provider_requests,\n            max_promotions=max_promotions,\n            max_dispatches=max_dispatches,\n            min_queue_depth_per_lane=min_queue_depth_per_lane,\n            max_paper_drafts=max_paper_drafts,\n            max_publication_rewrites=max_publication_rewrites,\n            min_admission_score=min_admission_score,\n            wait_for_completion=wait_for_completion,\n            max_wait_seconds=max_wait_seconds,\n            fresh_generation_backlog_threshold=fresh_generation_backlog_threshold,\n            janitor_enabled=janitor_enabled,\n            janitor_limit=janitor_limit,\n            janitor_report=janitor_report,\n            budget=budget,\n            initial_promotable=initial_promotable,\n            initial_open_lane_promotable=initial_open_lane_promotable,\n            lane_feed_pressure=lane_feed_pressure,\n            generation_target_lane=generation_target_lane,\n            stop_reasons=stop_reasons,\n        ),\n    )\n    _append_research_cycle_queue_paused_guardrail(\n        store=store,\n        response=response,\n        dry_run=dry_run,\n        requested_by=requested_by,\n    )\n    early_response = _research_cycle_pre_live_exit(\n        store=store,\n        response=response,\n        dry_run=dry_run,\n        requested_by=requested_by,\n        stop_reasons=stop_reasons,\n        backpressure_reasons=backpressure_reasons,\n        active=active,\n        wait_for_completion=wait_for_completion,\n        max_wait_seconds=max_wait_seconds,\n        cycle_limits={\n            "max_provider_requests": max_provider_requests,\n            "max_promotions": max_promotions,\n            "max_dispatches": max_dispatches,\n            "max_paper_drafts": max_paper_drafts,\n            "max_publication_rewrites": max_publication_rewrites,\n        },\n    )\n    if early_response is not None:\n        early_response["trace_id"] = trace_id\n        early_response["run_cycle_id"] = run_cycle_id\n        operator_trace.record(\n            "research.run_cycle.end",\n            trace_id=trace_id,\n            run_cycle_id=run_cycle_id,\n            requested_by=requested_by,\n            reason=early_response.get("reason"),\n            action=early_response.get("action"),\n            backpressure=early_response.get("backpressure"),\n        )\n        return early_response\n\n    open_lane_research_rows_local = partial(\n        open_lane_research_rows, lane_key_func=research_row_lane_key\n    )\n\n    return _execute_live_research_cycle(\n        params=_LiveResearchCycleParams(\n            store=store,\n            requested_by=requested_by,\n            generation_target_lane=generation_target_lane,\n            initial_feed_lanes=initial_feed_lanes,\n            max_dispatches=max_dispatches,\n            max_provider_requests=max_provider_requests,\n            fresh_generation_backlog_threshold=fresh_generation_backlog_threshold,\n            initial_promotable=initial_promotable,\n            promotable_rows=promotable_rows,\n            open_lane_research_rows=open_lane_research_rows_local,\n            max_promotions=max_promotions,\n            provider_openai_base_url=provider_openai_base_url,\n            provider_model=provider_model,\n            max_candidates=max_candidates,\n            topic=topic,\n            temperature=temperature,\n            seed=seed,\n            generation_timeout=generation_timeout,\n            generation_max_tokens=generation_max_tokens,\n            generation_attempts=generation_attempts,\n            min_admission_score=min_admission_score,\n            bounded_float=bounded_float,\n            namespace_cls=Namespace,\n            research_provider_generate=research_provider_generate,\n            research_facility=research_facility,\n            wait_for_completion=wait_for_completion,\n            max_wait_seconds=max_wait_seconds,\n            poll_interval_seconds=poll_interval_seconds,\n            max_paper_drafts=max_paper_drafts,\n            max_publication_rewrites=max_publication_rewrites,\n            draft_next=draft_next,\n            rewrite_paper_review_draft=_rewrite_paper_review_draft,\n            control_api_bearer_token=config.control_api_bearer_token,\n            worker_lane_key=_worker_lane_key,\n            worker_lane_capacity=_worker_lane_capacity,\n            queue_rows_for_lane_feed=_queue_rows_for_lane_feed,\n            live_dispatch=_live_dispatch,\n            jsonable_encoder=jsonable_encoder,\n            research_row_lane_key=research_row_lane_key,\n            operator_trace=operator_trace,\n            trace_id=trace_id,\n            run_cycle_id=run_cycle_id,\n        ),\n        response={**response, "trace_id": trace_id, "run_cycle_id": run_cycle_id},\n    )\n\n@router.post(\n    "/api/research/promote-candidate",\n    responses=_HTTP_400_RESEARCH_CANDIDATE_ID,\n)\ndef dashboard_research_promote_candidate(\n    payload: Annotated[dict[str, Any] | None, Body()] = None,\n    authorization: Annotated[str | None, Header()] = None,\n) -> dict[str, Any]:\n    authorize(authorization)\n    body = payload or {}\n    candidate_id = _validate_research_candidate_id(\n        str(body.get("candidate_id") or "")\n    )\n    dry_run = bool(body.get("dry_run", True))\n    requested_by = str(body.get("requested_by") or "dashboard")[:80]\n    if not dry_run:\n        _require_writable_store("Research Facility candidate promotion")\n    if not hasattr(store, "promote_research_candidate"):\n        raise HTTPException(\n            status_code=501,\n            detail="Research Facility promotion requires the Supabase control-plane store",\n        )\n    return store.promote_research_candidate(\n        candidate_id, requested_by=requested_by, dry_run=dry_run\n    )\n\n@router.get("/api/research/provider-budget")\ndef dashboard_research_provider_budget(\n    authorization: Annotated[str | None, Header()] = None,\n    estimated_requests: Annotated[int, Query(ge=0, le=100)] = 2,\n    reserve_requests: Annotated[int, Query(ge=0, le=100)] = 2,\n    min_remaining_credits: Annotated[float, Query(ge=0.0)] = 5.0,\n    min_rolling_remaining: Annotated[int, Query(ge=0)] = 10,\n    timeout: Annotated[int, Query(ge=1, le=60)] = 20,\n) -> dict[str, Any]:\n    authorize(authorization)\n    from scripts import research_provider_budget\n\n    base_url = os.environ.get(\n        "ENOCH_RESEARCH_PROVIDER_BASE_URL", DEFAULT_RESEARCH_PROVIDER_BASE_URL\n    ).rstrip("/")\n    try:\n        payload = research_provider_budget.fetch_json(\n            f"{base_url}/v2/quotas", api_key="", timeout=timeout\n        )\n        result = research_provider_budget.synthetic_budget_status(\n            payload,\n            min_remaining_credits=min_remaining_credits,\n            min_rolling_remaining=min_rolling_remaining,\n            estimated_requests=estimated_requests,\n            reserve_requests=reserve_requests,\n        )\n    except Exception as exc:  # noqa: BLE001 - provider checks must fail closed but stay operator-readable\n        result = {\n            "ok": False,\n            "provider": "synthetic",\n            "checked_at": utc_now(),\n            "estimated_requests": estimated_requests,\n            "reserve_requests": reserve_requests,\n            "failures": [f"provider budget check failed: {exc}"],\n        }\n    safe_keys = {\n        "ok",\n        "provider",\n        "checked_at",\n        "estimated_requests",\n        "reserve_requests",\n        "remaining_credits",\n        "min_remaining_credits",\n        "rolling_remaining",\n        "rolling_max",\n        "rolling_limited",\n        "rolling_next_tick_at",\n        "weekly_next_regen_at",\n        "weekly_next_regen_credits",\n        "subscription_remaining",\n        "subscription_renews_at",\n        "failures",\n    }\n    response = {key: result.get(key) for key in safe_keys if key in result}\n    response.update(\n        {\n            "provider_endpoint": "configured",\n            "auth_mode": "exe_http_proxy",\n            "payload_json": None,\n        }\n    )\n    return response\n\n@router.get("/api/intake/notion", responses=_HTTP_410_LEGACY_NOTION_API)\ndef dashboard_notion_intake(\n    authorization: Annotated[str | None, Header()] = None,\n    page_size: Annotated[int, Query(ge=1, le=200)] = 50,\n    include_latest_payload: Annotated[bool, Query()] = False,\n) -> DashboardIntakeResponse:\n    authorize(authorization)\n    try:\n        _require_legacy_notion_api_enabled()\n    except LegacyNotionApiDisabledError as exc:\n        raise HTTPException(\n            status_code=410,\n            detail={\n                "message": str(exc),\n                "replacement": LEGACY_NOTION_API_REPLACEMENT_PATH,\n            },\n        ) from exc\n    return _dashboard_ideas_intake_response(\n        legacy_notion_alias=True,\n        page_size=page_size,\n        include_latest_payload=include_latest_payload,\n    )\n\n',
    "_register_control_plane_research_routes": '@router.post("/pause")\ndef pause(\n    payload: PauseRequest, authorization: Annotated[str | None, Header()] = None\n) -> ControlStateResponse:\n    authorize(authorization)\n    _require_writable_store("operator pause")\n    store.pause(\n        reason=payload.reason,\n        paused_by=payload.paused_by,\n        maintenance_mode=payload.maintenance_mode,\n    )\n    return state_response()\n\n@router.post("/resume")\ndef resume(\n    payload: ResumeRequest, authorization: Annotated[str | None, Header()] = None\n) -> ControlStateResponse:\n    authorize(authorization)\n    _require_writable_store("operator resume")\n    store.resume(\n        resumed_by=payload.resumed_by, maintenance_mode=payload.maintenance_mode\n    )\n    return state_response()\n\n@router.post(\n    "/queue/mark-paused",\n    responses=_HTTP_MARK_QUEUE_ITEM_PAUSED_RESPONSES,\n)\ndef mark_queue_item_paused(\n    payload: MarkQueueItemPausedRequest,\n    authorization: Annotated[str | None, Header()] = None,\n) -> ControlStateResponse:\n    authorize(authorization)\n    _require_writable_store("queue item pause")\n    if not store.mark_queue_item_paused(\n        project_id=payload.project_id,\n        reason=payload.reason,\n        updated_by=payload.updated_by,\n    ):\n        raise HTTPException(status_code=404, detail="queue item not found")\n    return state_response()\n\n@router.post(\n    "/import/legacy-snapshot", responses=_HTTP_WRITABLE_IDEMPOTENCY_RESPONSES\n)\ndef import_snapshot(\n    payload: ImportSnapshotRequest,\n    authorization: Annotated[str | None, Header()] = None,\n) -> ImportSnapshotResponse:\n    authorize(authorization)\n    _require_writable_store("legacy snapshot import")\n    try:\n        inserted, projects, queue_items, papers = store.import_snapshot(payload)\n    except IdempotencyConflict as exc:\n        raise HTTPException(status_code=409, detail=str(exc)) from exc\n    response = ImportSnapshotResponse(\n        inserted_event=inserted,\n        imported_projects=projects,\n        imported_queue_items=queue_items,\n        imported_papers=papers,\n    )\n    store.upsert_dashboard_observation(\n        source="snapshot_mirror",\n        status="ok",\n        ttl_seconds=900,\n        payload={\n            "source": payload.source,\n            "imported_projects": projects,\n            "imported_queue_items": queue_items,\n            "imported_papers": papers,\n            "inserted_event": inserted,\n        },\n    )\n    return response\n\n@router.post("/intake/notion-ideas", responses=_HTTP_NOTION_INTAKE_RESPONSES)\ndef intake_notion_ideas(\n    payload: NotionIntakeRequest,\n    authorization: Annotated[str | None, Header()] = None,\n) -> NotionIntakeResponse:\n    authorize(authorization)\n    try:\n        _require_legacy_notion_api_enabled()\n    except LegacyNotionApiDisabledError as exc:\n        raise HTTPException(\n            status_code=410,\n            detail={\n                "message": str(exc),\n                "replacement": LEGACY_NOTION_API_REPLACEMENT_PATH,\n            },\n        ) from exc\n    if not payload.dry_run:\n        _require_writable_store("Notion ideas intake")\n    if payload.default_machine_target == DEFAULT_MACHINE_TARGET:\n        configured_worker = urlparse(config.worker_wake_gate_url).hostname or ""\n        if configured_worker:\n            payload = payload.model_copy(\n                update={"default_machine_target": configured_worker}\n            )\n    if config.workload_machine_targets and not payload.workload_machine_targets:\n        payload = payload.model_copy(\n            update={"workload_machine_targets": config.workload_machine_targets}\n        )\n    try:\n        inserted, created, updated, skipped, candidates, skipped_rows = (\n            store.ingest_notion_ideas(payload)\n        )\n    except IdempotencyConflict as exc:\n        raise HTTPException(status_code=409, detail=str(exc)) from exc\n    response = NotionIntakeResponse(\n        dry_run=payload.dry_run,\n        inserted_event=inserted,\n        created=created,\n        updated=updated,\n        skipped=skipped,\n        candidates=candidates,\n        skipped_rows=skipped_rows,\n    )\n    if not payload.dry_run:\n        store.upsert_dashboard_observation(\n            source="notion_sync",\n            status="ok" if skipped == 0 else "warn",\n            ttl_seconds=3600,\n            payload=response.model_dump(mode="json"),\n        )\n    return response\n\n@router.post("/intake/ideas", responses=_HTTP_WRITABLE_IDEMPOTENCY_RESPONSES)\ndef intake_ideas(\n    payload: IdeaIntakeRequest,\n    authorization: Annotated[str | None, Header()] = None,\n) -> IdeaIntakeResponse:\n    authorize(authorization)\n    if not payload.dry_run:\n        _require_writable_store("ideas intake")\n    if payload.default_machine_target == DEFAULT_MACHINE_TARGET:\n        configured_worker = urlparse(config.worker_wake_gate_url).hostname or ""\n        if configured_worker:\n            payload = payload.model_copy(\n                update={"default_machine_target": configured_worker}\n            )\n    if config.workload_machine_targets and not payload.workload_machine_targets:\n        payload = payload.model_copy(\n            update={"workload_machine_targets": config.workload_machine_targets}\n        )\n    try:\n        inserted, created, updated, skipped, candidates, skipped_rows = (\n            store.ingest_ideas(payload)\n        )\n    except IdempotencyConflict as exc:\n        raise HTTPException(status_code=409, detail=str(exc)) from exc\n    response = IdeaIntakeResponse(\n        dry_run=payload.dry_run,\n        inserted_event=inserted,\n        created=created,\n        updated=updated,\n        skipped=skipped,\n        candidates=candidates,\n        skipped_rows=skipped_rows,\n    )\n    if not payload.dry_run:\n        store.upsert_dashboard_observation(\n            source="idea_intake",\n            status="ok" if skipped == 0 else "warn",\n            ttl_seconds=3600,\n            payload=response.model_dump(mode="json"),\n        )\n    return response\n\n@router.post(\n    "/api/intake/notion-observation", responses=_HTTP_410_LEGACY_NOTION_API\n)\ndef record_notion_observation(\n    payload: dict[str, Any], authorization: Annotated[str | None, Header()] = None\n) -> dict[str, Any]:\n    authorize(authorization)\n    try:\n        _require_legacy_notion_api_enabled()\n    except LegacyNotionApiDisabledError as exc:\n        raise HTTPException(\n            status_code=410,\n            detail={\n                "message": str(exc),\n                "replacement": LEGACY_NOTION_API_REPLACEMENT_PATH,\n            },\n        ) from exc\n    _require_writable_store("intake observation")\n    status = str(payload.get("status") or "ok")\n    if status not in {"ok", "warn", "error", "unavailable"}:\n        status = "warn"\n    observation = store.upsert_dashboard_observation(\n        source="notion_sync",\n        status=status,\n        ttl_seconds=int(payload.get("ttl_seconds") or 3600),\n        payload=payload.get("payload")\n        if isinstance(payload.get("payload"), dict)\n        else payload,\n    )\n    return {"ok": True, "observation": observation.model_dump(mode="json")}\n\n@router.post("/api/intake/ideas-observation")\ndef record_ideas_observation(\n    payload: dict[str, Any], authorization: Annotated[str | None, Header()] = None\n) -> dict[str, Any]:\n    authorize(authorization)\n    _require_writable_store("intake observation")\n    status = str(payload.get("status") or "ok")\n    if status not in {"ok", "warn", "error", "unavailable"}:\n        status = "warn"\n    observation = store.upsert_dashboard_observation(\n        source="idea_intake",\n        status=status,\n        ttl_seconds=int(payload.get("ttl_seconds") or 3600),\n        payload=payload.get("payload")\n        if isinstance(payload.get("payload"), dict)\n        else payload,\n    )\n    return {"ok": True, "observation": observation.model_dump(mode="json")}\n\n',
    "_register_control_plane_operator_legacy_routes": '@router.post("/worker/preflight", responses=_HTTP_503_WORKER_PREFLIGHT_URL)\ndef worker_preflight(\n    payload: WorkerPreflightRequest,\n    authorization: Annotated[str | None, Header()] = None,\n) -> WorkerPreflightResponse:\n    authorize(authorization)\n    try:\n        worker_url = _configured_worker_preflight_url()\n    except WorkerPreflightUrlNotConfiguredError as exc:\n        raise HTTPException(status_code=503, detail=str(exc)) from exc\n    payload = payload.model_copy(\n        update={\n            "wake_gate_url": worker_url,\n            "bearer_token": config.worker_wake_gate_bearer_token,\n            "expected_callback_token_fingerprint": payload.expected_callback_token_fingerprint\n            or _callback_acceptance_token_fingerprint(),\n        }\n    )\n    response = run_worker_preflight(payload, store.flags())\n    _record_preflight_observations(response)\n    return response\n\n@router.post(\n    "/api/preflight",\n    responses={**_HTTP_400_PREFLIGHT_WAKE_GATE, **_HTTP_503_WORKER_PREFLIGHT_URL},\n)\ndef dashboard_preflight(\n    payload: WorkerPreflightRequest,\n    authorization: Annotated[str | None, Header()] = None,\n) -> WorkerPreflightResponse:\n    authorize(authorization)\n    try:\n        payload = _target_aware_preflight_payload(payload)\n    except WakeGateUrlNotAllowedError as exc:\n        raise HTTPException(status_code=400, detail=str(exc)) from exc\n    except WorkerPreflightUrlNotConfiguredError as exc:\n        raise HTTPException(status_code=503, detail=str(exc)) from exc\n    response = run_worker_preflight(payload, store.flags())\n    _record_preflight_observations(response)\n    return response\n\n@router.post("/dispatch-next")\ndef dispatch_next(\n    payload: DispatchNextRequest,\n    authorization: Annotated[str | None, Header()] = None,\n) -> DispatchNextResponse:\n    authorize(authorization)\n    if not payload.dry_run:\n        _require_writable_store("live dispatch")\n        active = store.active_items()\n        candidate = _open_worker_dispatch_candidate()\n        if not candidate:\n            reason = (\n                "no queued candidate on an open worker lane"\n                if active\n                else "no queued candidate"\n            )\n            return DispatchNextResponse(\n                ok=True, action="noop", reason=reason, active_count=len(active)\n            )\n        live, event_id, updated_candidate = _live_dispatch(\n            candidate, payload.requested_by, payload.force_preflight\n        )\n        return DispatchNextResponse(\n            ok=True,\n            action="live_dispatch",\n            reason="live dispatch accepted by worker",\n            candidate=updated_candidate,\n            active_count=len(store.active_items()),\n            event_id=event_id,\n            live=live,\n        )\n    flags = store.flags()\n    if flags.queue_paused:\n        return DispatchNextResponse(\n            ok=True,\n            action="paused",\n            reason=flags.pause_reason or "queue paused",\n            candidate=None,\n            active_count=len(store.active_items()),\n            event_id=None,\n        )\n    candidate = _open_worker_dispatch_candidate()\n    action = "dry_run_dispatch" if candidate else "noop"\n    reason = (\n        "dry-run dispatch selected candidate"\n        if candidate\n        else "no queued candidate on an open worker lane"\n    )\n    return DispatchNextResponse(\n        ok=action in {"paused", "noop", "dry_run_dispatch"},\n        action=action,\n        reason=reason,\n        candidate=_annotate_dispatch_route(candidate),\n        active_count=len(store.active_items()),\n        event_id=None,\n    )\n\n@router.post("/dispatch-one", responses=_HTTP_DISPATCH_ONE_RESPONSES)\ndef dispatch_one(\n    payload: DispatchOneRequest,\n    authorization: Annotated[str | None, Header()] = None,\n) -> DispatchNextResponse:\n    authorize(authorization)\n    project_id = str(payload.project_id or "").strip()\n    if not project_id:\n        raise HTTPException(status_code=400, detail="project_id is required")\n    candidate = store.queue_row(project_id)\n    if not candidate:\n        raise HTTPException(\n            status_code=404, detail="project_id was not found in the queue"\n        )\n    if _normal_status(candidate.get("status")) != "queued":\n        raise HTTPException(status_code=409, detail="project_id is not queued")\n    manual_review = _truthy_flag(candidate.get("manual_review_required"))\n    if manual_review:\n        raise HTTPException(\n            status_code=409,\n            detail="project_id is blocked by manual_review_required",\n        )\n    if _has_conflicting_active_lane(candidate):\n        raise HTTPException(\n            status_code=409,\n            detail="active worker lane already exists for selected candidate target",\n        )\n    if payload.dry_run:\n        return DispatchNextResponse(\n            ok=True,\n            action="dry_run_dispatch_one",\n            reason="dry-run selected explicit queued candidate; no state mutated",\n            candidate=_annotate_dispatch_route(candidate),\n            active_count=0,\n        )\n    live, event_id, updated_candidate = _live_dispatch(\n        candidate,\n        payload.requested_by,\n        payload.force_preflight,\n        allow_paused=True,\n    )\n    return DispatchNextResponse(\n        ok=True,\n        action="live_dispatch_one",\n        reason="explicit live dispatch accepted by worker; global queue pause preserved",\n        candidate=updated_candidate,\n        active_count=1,\n        event_id=event_id,\n        live=live,\n    )\n\n@router.get("/queue")\ndef queue(authorization: Annotated[str | None, Header()] = None) -> dict:\n    authorize(authorization)\n    return {\n        "ok": True,\n        "rows": store.queue_rows(),\n        "counts": store.status_counts(),\n        "active": store.active_items(),\n    }\n\n@router.get("/papers")\ndef papers(authorization: Annotated[str | None, Header()] = None) -> dict:\n    authorize(authorization)\n    return {"ok": True, "rows": store.paper_rows()}\n\n@router.get("/export/snapshot")\ndef export_snapshot(\n    authorization: Annotated[str | None, Header()] = None,\n) -> ExportSnapshotResponse:\n    authorize(authorization)\n    snapshot = store.export_snapshot()\n    return ExportSnapshotResponse(\n        flags=store.flags(),\n        queue_rows=snapshot["queue_rows"],\n        paper_rows=snapshot["paper_rows"],\n        events=snapshot["events"],\n    )\n\n@router.get("/projections/notion/queue", responses=_HTTP_410_LEGACY_NOTION_API)\ndef notion_queue_projection(\n    authorization: Annotated[str | None, Header()] = None,\n) -> ProjectionResponse:\n    authorize(authorization)\n    try:\n        _require_legacy_notion_api_enabled()\n    except LegacyNotionApiDisabledError as exc:\n        raise HTTPException(\n            status_code=410,\n            detail={\n                "message": str(exc),\n                "replacement": LEGACY_NOTION_API_REPLACEMENT_PATH,\n            },\n        ) from exc\n    rows = store.queue_notion_projection()\n    return ProjectionResponse(rows=rows, counts=store.status_counts())\n\n@router.get("/projections/ideas/workbench")\ndef ideas_workbench_projection(\n    authorization: Annotated[str | None, Header()] = None,\n) -> ProjectionResponse:\n    authorize(authorization)\n    rows = (\n        store.idea_workbench_projection()\n        if hasattr(store, "idea_workbench_projection")\n        else store.queue_notion_projection()\n    )\n    counts: dict[str, int] = {}\n    for row in rows:\n        key = str(row.get("idea_status") or row.get("queue_status") or "unknown")\n        counts[key] = counts.get(key, 0) + 1\n    return ProjectionResponse(rows=rows, counts=counts)\n\n@router.get("/projections/notion/papers", responses=_HTTP_410_LEGACY_NOTION_API)\ndef notion_papers_projection(\n    authorization: Annotated[str | None, Header()] = None,\n) -> ProjectionResponse:\n    authorize(authorization)\n    try:\n        _require_legacy_notion_api_enabled()\n    except LegacyNotionApiDisabledError as exc:\n        raise HTTPException(\n            status_code=410,\n            detail={\n                "message": str(exc),\n                "replacement": LEGACY_NOTION_API_REPLACEMENT_PATH,\n            },\n        ) from exc\n    rows = store.paper_notion_projection()\n    counts: dict[str, int] = {}\n    for row in rows:\n        key = str(row.get("paper_status") or "unknown")\n        counts[key] = counts.get(key, 0) + 1\n    return ProjectionResponse(rows=rows, counts=counts)\n\n@router.get(\n    "/projections/notion/execution-updates", responses=_HTTP_410_LEGACY_NOTION_API\n)\ndef notion_execution_updates_projection(\n    authorization: Annotated[str | None, Header()] = None,\n) -> ProjectionResponse:\n    authorize(authorization)\n    try:\n        _require_legacy_notion_api_enabled()\n    except LegacyNotionApiDisabledError as exc:\n        raise HTTPException(\n            status_code=410,\n            detail={\n                "message": str(exc),\n                "replacement": LEGACY_NOTION_API_REPLACEMENT_PATH,\n            },\n        ) from exc\n    rows = store.notion_execution_update_projection()\n    return ProjectionResponse(rows=rows, counts={"updates": len(rows)})\n\n@router.post(\n    "/papers/draft-next",\n    responses=_HTTP_500_UNRESOLVABLE_ARTIFACT_ROOT,\n)\ndef draft_next(\n    payload: DraftNextRequest, authorization: Annotated[str | None, Header()] = None\n) -> DraftNextResponse:\n    authorize(authorization)\n    candidates = eligible_paper_draft_candidates(\n        store.queue_rows(), store.paper_rows()\n    )\n    skipped: list[dict[str, Any]] = []\n    if not candidates:\n        return DraftNextResponse(\n            ok=True,\n            action="noop",\n            reason="no eligible completed paper-draft candidate without paper remains",\n        )\n    for candidate in candidates:\n        decision_gate, artifact_root = _pre_evidence_paper_decision_gate(candidate)\n        if not decision_gate.get("eligible"):\n            skipped.append(\n                {\n                    "project_id": candidate.get("project_id"),\n                    "run_id": candidate.get("current_run_id"),\n                    "reason": "project decision is not paper-ready",\n                    "decision_gate": decision_gate,\n                    "artifact_root": artifact_root,\n                }\n            )\n            continue\n        if payload.dry_run:\n            paper = _paper_record_from_candidate(candidate)\n            dry_candidate = draft_candidate_payload(candidate)\n            dry_candidate["evidence_sync"] = {\n                "enabled": config.paper_evidence_sync_enabled,\n                "skipped": True,\n                "reason": "dry_run",\n            }\n            dry_candidate["decision_gate"] = decision_gate\n            return DraftNextResponse(\n                ok=True,\n                action="dry_run_draft",\n                reason="eligible paper-ready candidate found; dry_run prevented evidence sync and artifact writes",\n                paper=paper,\n                candidate=dry_candidate,\n            )\n        _require_writable_store("paper draft-next")\n        evidence = _prepare_draft_evidence(candidate)\n        if not evidence["local_evidence_present"]:\n            _record_paper_evidence_blocked(\n                config,\n                store,\n                entity_type="project",\n                entity_id=str(candidate.get("project_id") or ""),\n                project_id=str(candidate.get("project_id") or ""),\n                run_id=str(\n                    candidate.get("current_run_id") or candidate.get("run_id") or ""\n                ),\n                artifact_root=str(evidence.get("artifact_root") or ""),\n                evidence_sync=evidence.get("evidence_sync")\n                if isinstance(evidence.get("evidence_sync"), dict)\n                else {},\n            )\n            skipped.append(\n                {\n                    "project_id": candidate.get("project_id"),\n                    "run_id": candidate.get("current_run_id"),\n                    "reason": "missing paper evidence",\n                    "evidence_sync": evidence.get("evidence_sync"),\n                }\n            )\n            continue\n        post_sync_decision_gate = paper_draft_decision_gate(\n            str(evidence.get("artifact_root") or "")\n        )\n        if not post_sync_decision_gate.get("eligible"):\n            skipped.append(\n                {\n                    "project_id": candidate.get("project_id"),\n                    "run_id": candidate.get("current_run_id"),\n                    "reason": "project decision is not paper-ready after evidence sync",\n                    "decision_gate": post_sync_decision_gate,\n                    "artifact_root": evidence.get("artifact_root"),\n                    "evidence_sync": evidence.get("evidence_sync"),\n                }\n            )\n            continue\n        paper = _paper_record_from_candidate(candidate)\n        candidate_for_write = {\n            **candidate,\n            "project_dir": evidence.get("artifact_root")\n            or candidate.get("project_dir"),\n            "evidence_sync": evidence.get("evidence_sync"),\n        }\n        writer = write_paper_artifacts(\n            config, candidate_for_write, paper, force=payload.force\n        )\n        writer = {\n            **writer,\n            "evidence_sync": evidence.get("evidence_sync"),\n            "artifact_root": evidence.get("artifact_root"),\n            "decision_gate": post_sync_decision_gate,\n        }\n        paper_event_payload = {\n            "requested_by": payload.requested_by,\n            "paper": paper.model_dump(mode="json"),\n            "writer": writer,\n        }\n        record_paper_draft = getattr(store, "record_paper_draft", None)\n        if callable(record_paper_draft):\n            record_paper_draft(\n                paper=paper,\n                project_dir=str(candidate_for_write["project_dir"]),\n                idempotency_key=f"paper-draft:{paper.paper_id}:{paper.updated_at}",\n                event_payload=paper_event_payload,\n            )\n        else:\n            store.update_project_dir(\n                str(candidate.get("project_id") or ""),\n                str(candidate_for_write["project_dir"]),\n            )\n            store.upsert_paper(paper)\n            store.append_event(\n                idempotency_key=f"paper-draft:{paper.paper_id}:{paper.updated_at}",\n                event_type="paper.drafted",\n                entity_type="paper",\n                entity_id=paper.paper_id,\n                payload=paper_event_payload,\n            )\n        try:\n            (\n                backfill_inserted,\n                backfill_created,\n                backfill_updated,\n                backfill_skipped,\n                backfill_errors,\n            ) = store.backfill_paper_reviews(\n                PaperReviewBackfillRequest(\n                    idempotency_key=f"paper-review-backfill:{paper.paper_id}:{paper.updated_at}",\n                    requested_by=payload.requested_by,\n                    paper_ids=[paper.paper_id],\n                    dry_run=False,\n                )\n            )\n            writer["review_backfill"] = {\n                "inserted_event": backfill_inserted,\n                "created": backfill_created,\n                "updated": backfill_updated,\n                "skipped": backfill_skipped,\n                "errors": backfill_errors,\n            }\n        except IdempotencyConflict as exc:\n            writer["review_backfill"] = {\n                "inserted_event": False,\n                "created": 0,\n                "updated": 0,\n                "skipped": 0,\n                "errors": [{"reason": str(exc)}],\n            }\n        except Exception as exc:\n            writer["review_backfill"] = {\n                "inserted_event": False,\n                "created": 0,\n                "updated": 0,\n                "skipped": 0,\n                "errors": [{"reason": f"{type(exc).__name__}: {exc}"}],\n            }\n        reason = f"paper draft created with {writer.get(\'provider\')} / {writer.get(\'model\')}"\n        if writer.get("fallback_used"):\n            reason += " (fallback used)"\n        response_candidate = draft_candidate_payload(candidate)\n        response_candidate["writer"] = writer\n        return DraftNextResponse(\n            ok=True,\n            action="drafted",\n            reason=reason,\n            paper=paper,\n            candidate=response_candidate,\n        )\n    return DraftNextResponse(\n        ok=True,\n        action="noop",\n        reason="eligible paper-draft candidates were not paper-ready or lacked sufficient positive local or synced evidence",\n        candidate={"skipped": skipped[:10]},\n    )\n',
}


def _exec_route_block(
    ns: _ControlPlaneHttpRegistrationNamespace, registrar: str
) -> None:
    exec(_HTTP_ROUTE_REGISTRAR_SRC[registrar], ns, ns)


def _register_control_plane_http_route_handlers(
    router: APIRouter,
    config: GateConfig,
    store: Any,
    require_bearer: RequireBearer,
) -> None:
    global _ROUTER_GATE_CONFIG
    _ROUTER_GATE_CONFIG = config
    ns = _control_plane_http_registration_namespace(
        router, config, store, require_bearer
    )
    _prepare_control_plane_http_route_bindings(ns)
    _register_control_plane_dashboard_shell_routes(ns)
    _register_control_plane_dashboard_v1_routes(ns)
    _register_control_plane_api_read_routes(ns)
    _register_control_plane_publication_routes(ns)
    _register_control_plane_papers_events_routes(ns)
    _register_control_plane_research_routes(ns)
    _register_control_plane_operator_legacy_routes(ns)
    _register_control_plane_llm_settings_routes(router, config, store, require_bearer)


def _register_control_plane_dashboard_shell_routes(
    ns: _ControlPlaneHttpRegistrationNamespace,
) -> None:
    _exec_route_block(ns, "_register_control_plane_dashboard_shell_routes")


def _register_control_plane_dashboard_v1_routes(
    ns: _ControlPlaneHttpRegistrationNamespace,
) -> None:
    _exec_route_block(ns, "_register_control_plane_dashboard_v1_routes")


def _register_control_plane_api_read_routes(
    ns: _ControlPlaneHttpRegistrationNamespace,
) -> None:
    _exec_route_block(ns, "_register_control_plane_api_read_routes")


def _register_control_plane_publication_routes(
    ns: _ControlPlaneHttpRegistrationNamespace,
) -> None:
    _exec_route_block(ns, "_register_control_plane_publication_routes")


def _register_control_plane_papers_events_routes(
    ns: _ControlPlaneHttpRegistrationNamespace,
) -> None:
    _exec_route_block(ns, "_register_control_plane_papers_events_routes")


def _register_control_plane_research_routes(
    ns: _ControlPlaneHttpRegistrationNamespace,
) -> None:
    _exec_route_block(ns, "_register_control_plane_research_routes")


def _register_control_plane_operator_legacy_routes(
    ns: _ControlPlaneHttpRegistrationNamespace,
) -> None:
    _exec_route_block(ns, "_register_control_plane_operator_legacy_routes")
