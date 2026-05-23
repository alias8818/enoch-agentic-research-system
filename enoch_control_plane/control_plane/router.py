from __future__ import annotations

from datetime import datetime, timedelta, timezone
from functools import partial
import io
import hashlib
import mimetypes
from pathlib import Path, PurePosixPath
import os
import re
import select
import shlex
import subprocess
import tarfile
import tempfile
import time
from typing import Annotated, Any, Callable, Mapping
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
from ..observability import current_rss_mib, peak_rss_mib
from ..timeutils import parse_utc_datetime
from .paper_writer import write_paper_artifacts
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

RequireBearer = Callable[[str | None], None]

_RUN_NOTES_MD = "run_notes.md"
_EVIDENCE_SYNC_METHOD_WORKER_HTTP_SSH = "worker_http+ssh"
_DEFAULT_RESEARCH_MODEL = "gpt-5.5"


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
        provider_base_url=os.environ.get(
            "ENOCH_RESEARCH_PROVIDER_BASE_URL", DEFAULT_RESEARCH_PROVIDER_BASE_URL
        ).rstrip("/"),
        provider_openai_base_url=os.environ.get(
            "ENOCH_RESEARCH_PROVIDER_OPENAI_BASE_URL",
            f"{os.environ.get('ENOCH_RESEARCH_PROVIDER_BASE_URL', DEFAULT_RESEARCH_PROVIDER_BASE_URL).rstrip('/')}/openai/v1",
        ).rstrip("/"),
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

# Single source of truth for allowed research provider/models (kills S1192 duplication
# in _resolve_research_provider_model getenv default + fallback list + provider default).
# Update here when the allow-list changes; the resolver and any callers stay in sync.
DEFAULT_ALLOWED_RESEARCH_MODELS: list[str] = [
    "hf:moonshotai/Kimi-K2.6",
    "hf:zai-org/GLM-5.1",
]

# Centralized default for the top remaining S1192 duplication (synthetic research
# provider base URL used in getenv defaults and f-string fallbacks).
DEFAULT_RESEARCH_PROVIDER_BASE_URL = "https://synthetic.int.exe.xyz"

# Centralized reason constant for the top remaining S1192 duplication
# (worker preflight error paths and messages in router.py).
WORKER_PREFLIGHT_FAILED_REASON = "worker preflight failed"

# Dashboard finding source for cross-source control-plane DB + worker preflight.
CONTROL_PLANE_DB_WORKER_PREFLIGHT_SOURCE = "control_plane_db+worker_preflight"

# Centralized event type / status constant for the top remaining S1192 duplication
# (paper_review draft rewrite events and comparisons in router.py).
PAPER_REVIEW_DRAFT_REWRITTEN = "paper_review.draft_rewritten"

# Centralized authority label for Supabase-native ideas workbench freshness paths.
SUPABASE_NATIVE_IDEAS_WORKBENCH_AUTHORITY = "Supabase-native ideas workbench"


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


def _safe_tar_target(artifact_root: Path, member_name: str) -> Path | None:
    raw = PurePosixPath(str(member_name or ""))
    if (
        raw.is_absolute()
        or not raw.parts
        or any(part in {"", ".", ".."} for part in raw.parts)
    ):
        return None
    try:
        target = (artifact_root / Path(*raw.parts)).resolve()
        target.relative_to(artifact_root.resolve())
    except (OSError, RuntimeError, ValueError):
        return None
    return target


def _append_tar_skip(
    skipped: list[dict[str, Any]], *, path: str, status: str, error: str
) -> None:
    skipped.append({"path": path, "status": status, "error": error})


def _extract_tar_member(
    archive: tarfile.TarFile,
    member: tarfile.TarInfo,
    artifact_root: Path,
    *,
    max_file_bytes: int,
    max_total_bytes: int,
    written: list[str],
    skipped: list[dict[str, Any]],
    total_bytes: int,
) -> int:
    target = _safe_tar_target(artifact_root, member.name)
    if target is None:
        _append_tar_skip(
            skipped,
            path=member.name,
            status="unsafe_path",
            error="tar member path escapes artifact root",
        )
        return total_bytes
    if member.isdir():
        target.mkdir(parents=True, exist_ok=True)
        return total_bytes
    if not member.isfile():
        _append_tar_skip(
            skipped,
            path=member.name,
            status="unsupported_member",
            error="tar member is not a regular file",
        )
        return total_bytes
    if member.size > max_file_bytes or total_bytes + member.size > max_total_bytes:
        _append_tar_skip(
            skipped,
            path=member.name,
            status="too_large",
            error="tar member exceeds evidence extraction byte limit",
        )
        return total_bytes
    extracted = archive.extractfile(member)
    if extracted is None:
        _append_tar_skip(
            skipped,
            path=member.name,
            status="read_failed",
            error="tar member could not be read",
        )
        return total_bytes
    content = extracted.read(max_file_bytes + 1)
    if len(content) > max_file_bytes:
        _append_tar_skip(
            skipped,
            path=member.name,
            status="too_large",
            error="tar member exceeds evidence extraction byte limit",
        )
        return total_bytes
    _atomic_write_bytes(target, content)
    written.append(member.name)
    return total_bytes + len(content)


def _extract_safe_tar_bytes(
    payload: bytes,
    artifact_root: Path,
    *,
    max_file_bytes: int = 8_000_000,
    max_total_bytes: int = 64_000_000,
) -> dict[str, Any]:
    try:
        artifact_root = artifact_root.resolve()
        artifact_root.mkdir(parents=True, exist_ok=True)
    except (OSError, RuntimeError, ValueError) as exc:
        return {
            "ok": False,
            "reason": "artifact_root_unusable",
            "files": 0,
            "paths": [],
            "skipped": [],
            "error": f"{type(exc).__name__}: {exc}",
        }
    written: list[str] = []
    skipped: list[dict[str, Any]] = []
    total_bytes = 0
    try:
        # NOSONAR - safe extraction; _safe_tar_target prevents traversal
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
            for member in archive.getmembers():
                total_bytes = _extract_tar_member(
                    archive,
                    member,
                    artifact_root,
                    max_file_bytes=max_file_bytes,
                    max_total_bytes=max_total_bytes,
                    written=written,
                    skipped=skipped,
                    total_bytes=total_bytes,
                )
    except (tarfile.TarError, OSError, RuntimeError, ValueError) as exc:
        return {
            "ok": False,
            "reason": "extract_failed",
            "files": len(written),
            "paths": written[:30],
            "skipped": skipped[:30],
            "error": f"{type(exc).__name__}: {exc}",
        }
    return {
        "ok": bool(written),
        "reason": "safe_tar_extracted" if written else "no_safe_tar_evidence",
        "files": len(written),
        "paths": written[:30],
        "skipped": skipped[:30],
    }


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
            raise HTTPException(
                status_code=500, detail="configured artifact roots are not resolvable"
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
        raise HTTPException(
            status_code=404, detail="publication automation item not found"
        )
    review_status = _normal_status(item.get("review_status"))
    if review_status in _PAPER_REWRITE_BLOCKED_REVIEW_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"publication automation items with review_status={review_status} "
                "cannot be rewritten or auto-published"
            ),
        )
    return paper, item


def _configured_project_root_or_400(config: GateConfig) -> Path:
    try:
        return config.expanded_project_root.resolve()
    except (OSError, RuntimeError, ValueError) as exc:
        raise HTTPException(
            status_code=400, detail="configured project root could not be resolved"
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
        raise HTTPException(
            status_code=400, detail="paper artifact root could not be resolved"
        ) from exc
    try:
        return resolved.exists(), resolved
    except (OSError, RuntimeError) as exc:
        raise HTTPException(
            status_code=400,
            detail="paper artifact root could not be inspected",
        ) from exc


def _resolve_paper_rewrite_artifact_root(
    config: GateConfig,
    *,
    project_id: str,
    project: dict[str, Any] | None,
) -> tuple[Path, bool]:
    configured_root = _configured_project_root_or_400(config)
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
        raise HTTPException(
            status_code=400, detail="paper artifact root could not be resolved"
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
        raise HTTPException(
            status_code=409,
            detail=(
                f"idempotency key {payload.idempotency_key!r} was reused with "
                "different payload"
            ),
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
            raise HTTPException(
                status_code=400,
                detail=f"paper artifact snapshot could not be read: {rel_path}",
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
    draft_event_committed = False
    try:
        writer = write_paper_artifacts(config, candidate, record, force=payload.force)
        if not use_current_dir:
            store.update_project_dir(project_id, str(artifact_root))
        store.upsert_paper(record)
        event_payload = {
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
        event_id, inserted = store.append_event(
            idempotency_key=payload.idempotency_key,
            event_type=PAPER_REVIEW_DRAFT_REWRITTEN,
            entity_type="paper_review",
            entity_id=record.paper_id,
            payload=event_payload,
        )
        draft_event_committed = True
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
    except IdempotencyConflict as exc:
        if not draft_event_committed:
            _restore_paper_rewrite_side_effects(
                store,
                artifact_snapshots=artifact_snapshots,
                original_record=original_record,
                original_project_dir=original_project_dir,
                project_id=project_id,
            )
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        if not draft_event_committed:
            _restore_paper_rewrite_side_effects(
                store,
                artifact_snapshots=artifact_snapshots,
                original_record=original_record,
                original_project_dir=original_project_dir,
                project_id=project_id,
            )
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        if not draft_event_committed:
            _restore_paper_rewrite_side_effects(
                store,
                artifact_snapshots=artifact_snapshots,
                original_record=original_record,
                original_project_dir=original_project_dir,
                project_id=project_id,
            )
        raise
    refreshed = (
        store.paper_review_row(record.paper_id, include_rank_reasons=True)
        or finalized_item
        or item
    )
    writer_with_sync = {
        **writer,
        "evidence_sync": evidence_sync,
        "automated_finalization": {
            "inserted_event": finalization_inserted,
            "event_id": finalization_event_id,
            "package_path": package_path,
            "review_status": str((refreshed or {}).get("review_status") or ""),
        },
    }
    return PaperReviewRewriteDraftResponse(
        inserted_event=inserted,
        event_id=event_id,
        item=refreshed,
        paper=store.paper_row(record.paper_id),
        writer=writer_with_sync,
        artifact_root=str(artifact_root),
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
            if not ready:
                if proc.poll() is None:
                    continue
                try:
                    chunk = os.read(fd, min(1024 * 1024, max_bytes - total + 1))
                except BlockingIOError:
                    break
            else:
                try:
                    chunk = os.read(fd, min(1024 * 1024, max_bytes - total + 1))
                except BlockingIOError:
                    continue
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                return b"".join(chunks), True
            chunks.append(chunk)
    finally:
        if previous_blocking is not None:
            try:
                os.set_blocking(fd, previous_blocking)
            except OSError:
                pass
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
    _assert_live_dispatch_preconditions(
        config=config,
        store=store,
        require_writable_store=require_writable_store,
        allow_paused=allow_paused,
    )
    project_id, project_dir, run_id = _live_dispatch_project_context(candidate)
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
    preflight = _run_live_dispatch_preflight(
        worker_target=worker_target,
        store=store,
        project_id=project_id,
        run_id=run_id,
        force_preflight=force_preflight,
        callback_acceptance_token_fingerprint=callback_acceptance_token_fingerprint,
        record_preflight_observations=record_preflight_observations,
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


def _recent_worker_settling_without_vm_match(
    *, preflight: DashboardObservationRecord | None
) -> dict[str, Any] | None:
    no_live = _preflight_check(preflight, "worker_no_live_runs")
    if not no_live or no_live.get("ok") is not False:
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
    no_live = _preflight_check(preflight, "worker_no_live_runs")
    if not no_live or no_live.get("ok") is not False:
        return None

    completed_run_ids: set[str] = set()
    terminal_run_states = set(TERMINAL_SUCCESS_CALLBACK_STATES) | {
        "completed",
        "complete",
        "finished",
    }
    for row in queue_rows:
        status = _normal_status(row.get("status"))
        last_run_state = _normal_status(row.get("last_run_state"))
        run_id = str(row.get("current_run_id") or "").strip()
        if status in ACTIVE_STATUSES:
            continue
        if status == "completed" or last_run_state in terminal_run_states:
            if run_id:
                completed_run_ids.add(run_id)

    for row in run_rows:
        state = _normal_status(row.get("state"))
        gate_state = _normal_status(row.get("gate_state"))
        if state not in terminal_run_states and gate_state not in terminal_run_states:
            continue
        run_id = str(row.get("run_id") or "").strip()
        if run_id:
            completed_run_ids.add(run_id)

    if not completed_run_ids:
        return None

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


def _select_generation_target_lane(
    lane_feed_pressure: dict, max_dispatches: int
) -> str | None:
    """Extracted from dashboard_research_run_cycle (reduces cognitive complexity in the 1595 giant).

    Computes the best lane to target for fresh generation based on queue deficit,
    promotable count, and dispatch pressure. Pure and testable.
    """
    if not lane_feed_pressure:
        return None

    generation_target_actions = {"generate_candidate"}
    if max_dispatches <= 0:
        generation_target_actions.add("dispatch_queued")

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
    followup_candidate = None
    followup_branch_taken = False
    if hasattr(store, "next_followup_candidate"):
        followup_candidate = store.next_followup_candidate(max_followup_depth=4)
    if followup_candidate:
        followup_lane_key = research_row_lane_key(followup_candidate)
        generation_lane_key = str((generation_target_lane or {}).get("lane_key") or "")
        followup_starves_target_lane = (
            bool(generation_target_lane)
            and bool(max_provider_requests)
            and bool(followup_lane_key)
            and bool(generation_lane_key)
            and followup_lane_key != generation_lane_key
        )
        if followup_starves_target_lane:
            response["followup_launch"] = {
                "action": "skipped",
                "reason": "bounded follow-up candidate targets a different lane than the largest empty queue deficit",
                "candidate": followup_candidate,
                "candidate_lane_key": followup_lane_key,
                "generation_target_lane": generation_target_lane,
            }
            response["stages"].append(
                {
                    "stage": "followup_launch",
                    "ok": True,
                    "action": "skipped",
                    "reason": response["followup_launch"]["reason"],
                    "parent_project_id": followup_candidate.get("project_id"),
                    "candidate_lane_key": followup_lane_key,
                    "generation_lane_key": generation_lane_key,
                }
            )
        elif max_dispatches:
            followup_launch = store.launch_followup_candidate(
                project_id=str(followup_candidate.get("project_id") or ""),
                dry_run=False,
                requested_by=requested_by,
                max_followup_depth=4,
            )
            response["followup_launch"] = followup_launch
            response["stages"].append(
                {
                    "stage": "followup_launch",
                    "ok": followup_launch.get("action") == "followup_queued",
                    "action": followup_launch.get("action"),
                    "parent_project_id": (followup_launch.get("candidate") or {}).get(
                        "project_id"
                    ),
                    "project_id": (followup_launch.get("followup") or {}).get(
                        "idea_id"
                    ),
                    "reason": followup_launch.get("reason"),
                }
            )
            if followup_launch.get("action") == "followup_queued":
                followup_branch_taken = True
                response["queued_count"] = 1
                followup_project_id = str(
                    (followup_launch.get("followup") or {}).get("idea_id") or ""
                ).strip()
                if followup_project_id:
                    dispatch_queued_project(followup_project_id)
        else:
            response["followup_launch"] = {
                "action": "skipped",
                "reason": "bounded follow-up candidate exists but dispatch is disabled for this run",
                "candidate": followup_candidate,
            }
            response["stages"].append(
                {
                    "stage": "followup_launch",
                    "ok": True,
                    "action": "skipped",
                    "reason": "bounded follow-up candidate exists but dispatch is disabled for this run",
                    "parent_project_id": followup_candidate.get("project_id"),
                }
            )
        response["fresh_generation_skipped"] = followup_branch_taken
        response["fresh_promotion_skipped"] = followup_branch_taken
        if followup_branch_taken:
            response["reason"] = (
                "bounded follow-up branch took priority over fresh idea generation"
            )
    else:
        response["fresh_generation_skipped"] = False
        response["fresh_promotion_skipped"] = False

    if (
        not response.get("fresh_generation_skipped")
        and max_provider_requests
        and fresh_generation_backlog_threshold
        and len(initial_promotable) >= fresh_generation_backlog_threshold
        and not generation_target_lane
    ):
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


def _execute_provider_generation(
    *,
    max_provider_requests: int,
    response: dict[str, Any],
    generation_target_lane: Any,
    provider_openai_base_url: str,
    provider_model: str,
    max_candidates: int,
    topic: str,
    temperature: float,
    seed: str,
    generation_timeout: int,
    generation_max_tokens: int,
    generation_attempts: int,
    min_admission_score: float,
    bounded_float: Callable,
    namespace_cls: Any,
    research_provider_generate: Any,
    research_facility: Any,
    store: Any,
    requested_by: str,
) -> dict[str, Any]:
    """Extracted from dashboard_research_run_cycle (large live execution path contributing to 1595/remaining S3776).

    Handles lane-pressure-aware topic construction, provider candidate generation call,
    planning, ledger recording, stages append, and error handling. Thin delegation left in the giant.
    """
    generated_plans = []
    if max_provider_requests and not response.get("fresh_generation_skipped"):
        try:
            generation_machine_target = _provider_generation_machine_target(
                generation_target_lane
            )
            generation_topic = _provider_generation_topic(
                topic=topic,
                generation_target_lane=generation_target_lane,
                generation_machine_target=generation_machine_target,
            )
            generated = research_provider_generate.generate_provider_candidates(
                base_url=provider_openai_base_url,
                model=provider_model,
                api_key="",
                max_candidates=max_candidates,
                topic=generation_topic,
                temperature=temperature,
                seed=seed,
                timeout=generation_timeout,
                max_tokens=generation_max_tokens,
                attempts=generation_attempts,
                default_machine=generation_machine_target,
                default_model=os.environ.get(
                    "ENOCH_RESEARCH_DEFAULT_MODEL", _DEFAULT_RESEARCH_MODEL
                ),
                default_sandbox=os.environ.get(
                    "ENOCH_RESEARCH_DEFAULT_SANDBOX", "danger-full-access"
                ),
            )
            generated_plans = research_facility.plan_candidates(
                (generated.get("candidates") or [])[:max_candidates],
                namespace_cls(
                    default_machine=os.environ.get(
                        "ENOCH_RESEARCH_DEFAULT_MACHINE", "research-facility-node"
                    ),
                    default_model=os.environ.get(
                        "ENOCH_RESEARCH_DEFAULT_MODEL", "gpt-5.5"
                    ),
                    default_sandbox=os.environ.get(
                        "ENOCH_RESEARCH_DEFAULT_SANDBOX", "danger-full-access"
                    ),
                    admit_threshold=min_admission_score,
                    review_threshold=bounded_float(
                        "review_threshold", 58.0, 0.0, 100.0
                    ),
                    history=[],
                ),
            )
            ledger_result = store.record_research_facility_plans(
                generated_plans, requested_by=requested_by, queue_admitted=False
            )
            response["generated_count"] = len(generated_plans)
            response["provider_response_id"] = generated.get("provider_response_id", "")
            response["attempts_used"] = generated.get("attempts_used", 1)
            response["generation_target_lane"] = generation_target_lane
            response["ledger_result"] = ledger_result
            response["stages"].append(
                {
                    "stage": "provider_generation",
                    "ok": True,
                    "candidate_count": len(generated_plans),
                    "ledger_result": ledger_result,
                    "generation_target_lane": str(
                        (generation_target_lane or {}).get("machine_target") or ""
                    ),
                }
            )
        except Exception as exc:  # noqa: BLE001 - provider output is external and must not break long-haul ticks
            warning = f"provider generation skipped: {exc}"
            response.setdefault("warnings", []).append(warning)
            response["stages"].append(
                {"stage": "provider_generation", "ok": False, "reason": warning}
            )

    return response


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
) -> dict[str, Any]:
    """Extracted from dashboard_research_run_cycle (self-contained promotion loop contributing to 1595/remaining S3776).

    Filters open_lane promotable candidates, calls store.promote_research_candidate for up to max_promotions,
    captures the promoted list, updates response counts/stages, and dispatches promoted items if dispatch capacity remains.
    Thin delegation left in the giant.
    """
    promoted: list[dict[str, Any]] = []
    if not response.get("fresh_promotion_skipped"):
        promotion_candidates = _resolve_open_lane_promotion_candidates(
            promotable_rows=promotable_rows,
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
) -> bool:
    """Extracted from dashboard_research_run_cycle (self-contained dispatch helper contributing to 1595/remaining S3776).

    Handles claim, live_dispatch with 409 backpressure handling, heavy response mutation
    (dispatch_started, dispatched_count, dispatch record, stages, dispatches list), and returns success.
    Thin delegation wrapper left in the giant so all call sites remain unchanged.
    """
    candidate = store.queue_row(project_id)
    if candidate and str(candidate.get("status") or "") == "queued":
        try:
            live, event_id, updated_candidate = _live_dispatch(
                candidate, requested_by, force_preflight=True, allow_paused=True
            )
        except HTTPException as exc:
            if int(exc.status_code) != 409:
                raise
            response["dispatch"] = {
                "event_id": None,
                "candidate": candidate,
                "live": None,
                "backpressure": True,
                "detail": jsonable_encoder(exc.detail),
            }
            response["stages"].append(
                {
                    "stage": "dispatch",
                    "ok": True,
                    "action": "dispatch_backpressure",
                    "project_id": project_id,
                    "reason": "dispatch conflict/backpressure; queued work remains safe for the queue pump or next tick",
                    "detail": jsonable_encoder(exc.detail),
                }
            )
            return False
        response["dispatch_started"] = True
        response["dispatched_count"] = int(response.get("dispatched_count") or 0) + 1
        dispatch_record = {
            "event_id": event_id,
            "candidate": updated_candidate,
            "live": live,
        }
        response["dispatch"] = dispatch_record
        response.setdefault("dispatches", []).append(dispatch_record)
        response["stages"].append(
            {
                "stage": "dispatch",
                "ok": True,
                "project_id": project_id,
                "event_id": event_id,
            }
        )
        return True
    response["stages"].append(
        {
            "stage": "dispatch",
            "ok": False,
            "reason": "queued project was not dispatchable",
            "project_id": project_id,
        }
    )
    return False


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
) -> list[str]:
    """Extracted from dashboard_research_run_cycle (lane backpressure gate contributing to S3776)."""
    if (
        active
        and not initial_open_lane_promotable
        and not (generation_target_lane and max_provider_requests)
    ):
        return [
            "active worker lane already exists and no promotable candidate targets an idle lane"
        ]
    return []


def _build_research_cycle_initial_response(
    *,
    dry_run: bool,
    enabled: bool,
    provider_model: str,
    allowed_models: list[str],
    body: dict[str, Any],
    max_provider_requests: int,
    max_promotions: int,
    max_dispatches: int,
    min_queue_depth_per_lane: int,
    max_paper_drafts: int,
    max_publication_rewrites: int,
    min_admission_score: float,
    wait_for_completion: bool,
    max_wait_seconds: int,
    fresh_generation_backlog_threshold: int,
    janitor_enabled: bool,
    janitor_limit: int,
    janitor_report: dict[str, Any],
    budget: dict[str, Any],
    initial_promotable: list[dict[str, Any]],
    initial_open_lane_promotable: list[dict[str, Any]],
    lane_feed_pressure: dict[str, Any],
    generation_target_lane: Any,
    stop_reasons: list[str],
) -> dict[str, Any]:
    """Extracted from dashboard_research_run_cycle (large response skeleton contributing to S3776)."""
    return {
        "ok": not stop_reasons,
        "action": "dry_run_research_cycle" if dry_run else "research_cycle",
        "dry_run": dry_run,
        "enabled": enabled,
        "queue_admitted": False,
        "dispatch_started": False,
        "provider": "synthetic.new",
        "provider_model": provider_model,
        "allowed_models": allowed_models,
        "policy": {
            "max_provider_requests_per_run": max_provider_requests,
            "max_promotions_per_run": max_promotions,
            "max_dispatches_per_run": max_dispatches,
            "min_queue_depth_per_lane": min_queue_depth_per_lane,
            "max_paper_drafts_per_run": max_paper_drafts,
            "max_publication_rewrites_per_run": max_publication_rewrites,
            "min_admission_score": min_admission_score,
            "require_budget_ok": True,
            "stop_if_queue_active": True,
            "stop_if_dashboard_attention": bool(
                body.get("stop_if_dashboard_attention", True)
            ),
            "wait_for_completion": wait_for_completion,
            "max_wait_seconds": max_wait_seconds,
            "fresh_generation_backlog_threshold": fresh_generation_backlog_threshold,
            "janitor_enabled": janitor_enabled,
            "janitor_limit": janitor_limit,
        },
        "janitor": janitor_report,
        "budget": {
            key: budget.get(key)
            for key in _RESEARCH_CYCLE_BUDGET_RESPONSE_KEYS
            if key in budget
        },
        "initial_promotable_count": len(initial_promotable),
        "planned_promotions": [
            row.get("candidate_id")
            for row in (initial_open_lane_promotable or initial_promotable)[
                :max_promotions
            ]
        ],
        "open_lane_promotable_count": len(initial_open_lane_promotable),
        "lane_feed_pressure": lane_feed_pressure,
        "generation_target_lane": generation_target_lane,
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
        response["reason"] = "; ".join(stop_reasons)
        if hasattr(store, "append_event"):
            store.append_event(
                idempotency_key=f"research-cycle:{'dry' if dry_run else 'live'}:{requested_by}:{utc_now()}",
                event_type="research.run_cycle.blocked",
                entity_type="research",
                entity_id="run-cycle",
                payload=jsonable_encoder(response),
            )
        return response
    if backpressure_reasons:
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
        if hasattr(store, "append_event"):
            try:
                store.append_event(
                    idempotency_key=(
                        f"research-cycle:backpressure:{'dry' if dry_run else 'live'}:{requested_by}:"
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
    if dry_run:
        response["reason"] = (
            "dry-run only; provider was not called and no ledgers, queue rows, dispatches, or papers were written"
        )
        response["would_generate"] = cycle_limits["max_provider_requests"] > 0
        response["would_promote_up_to"] = cycle_limits["max_promotions"]
        response["would_dispatch_up_to"] = cycle_limits["max_dispatches"]
        response["would_wait_for_completion"] = (
            wait_for_completion and max_wait_seconds > 0
        )
        response["would_draft_papers_up_to"] = cycle_limits["max_paper_drafts"]
        response["would_finalize_papers_up_to"] = cycle_limits[
            "max_publication_rewrites"
        ]
        if hasattr(store, "append_event"):
            store.append_event(
                idempotency_key=f"research-cycle:dry:{requested_by}:{utc_now()}",
                event_type="research.run_cycle.dry_run",
                entity_type="research",
                entity_id="run-cycle",
                payload=jsonable_encoder(response),
            )
        return response
    return None


def _wait_for_completion(
    *,
    store: Any,
    response: dict[str, Any],
    wait_for_completion: bool,
    max_wait_seconds: int,
    poll_interval_seconds: int,
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
        polls = 0
        last_status = ""
        while True:
            polls += 1
            row = (
                store.queue_row(dispatched_project_id)
                if dispatched_project_id
                else None
            )
            active_now = store.active_items()
            last_status = str((row or {}).get("status") or "")
            if not active_now and last_status not in {
                "dispatching",
                "running",
                "awaiting_wake",
                "wake_received",
                "reconciling",
            }:
                wait_result = {
                    "action": "completed",
                    "project_id": dispatched_project_id,
                    "status": last_status,
                    "polls": polls,
                }
                break
            if time.monotonic() >= deadline:
                wait_result = {
                    "action": "timeout",
                    "project_id": dispatched_project_id,
                    "status": last_status,
                    "active_count": len(active_now),
                    "polls": polls,
                }
                break
            time.sleep(poll_interval_seconds)
    response["wait"] = wait_result
    response["stages"].append({"stage": "wait_for_completion", **wait_result})
    return wait_result


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
            rewrite_response = rewrite_paper_review_draft(
                paper_id,
                PaperReviewRewriteDraftRequest(
                    idempotency_key=f"research-cycle:{requested_by}:{draft_index}:{paper_id}:{utc_now()}",
                    requested_by=requested_by,
                    force=True,
                ),
            )
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


def _execute_live_research_cycle(
    *,
    store: Any,
    response: dict[str, Any],
    requested_by: str,
    generation_target_lane: Any,
    max_dispatches: int,
    max_provider_requests: int,
    fresh_generation_backlog_threshold: int,
    initial_promotable: list[dict[str, Any]],
    promotable_rows: Callable[[], list[dict[str, Any]]],
    open_lane_research_rows: Callable[..., list[dict[str, Any]]],
    max_promotions: int,
    provider_openai_base_url: str,
    provider_model: str,
    max_candidates: int,
    topic: str,
    temperature: float,
    seed: str,
    generation_timeout: int,
    generation_max_tokens: int,
    generation_attempts: int,
    min_admission_score: float,
    bounded_float: Callable[[str, float, float, float], float],
    namespace_cls: Any,
    research_provider_generate: Any,
    research_facility: Any,
    wait_for_completion: bool,
    max_wait_seconds: int,
    poll_interval_seconds: int,
    max_paper_drafts: int,
    max_publication_rewrites: int,
    draft_next: Callable[..., Any],
    rewrite_paper_review_draft: Callable[..., Any],
    control_api_bearer_token: str,
    _worker_lane_key: Callable[[dict[str, Any]], str],
    _live_dispatch: Callable[..., Any],
    jsonable_encoder: Callable[..., Any],
    research_row_lane_key: Callable[[dict[str, Any]], str],
) -> dict[str, Any]:
    """Extracted from dashboard_research_run_cycle (live path orchestration contributing to S3776)."""

    def dispatch_queued_project(project_id: str) -> bool:
        return _dispatch_queued_project(
            project_id,
            store=store,
            response=response,
            requested_by=requested_by,
            _live_dispatch=_live_dispatch,
            jsonable_encoder=jsonable_encoder,
        )

    response = _handle_followup_and_early_skips(
        store=store,
        generation_target_lane=generation_target_lane,
        max_dispatches=max_dispatches,
        max_provider_requests=max_provider_requests,
        fresh_generation_backlog_threshold=fresh_generation_backlog_threshold,
        initial_promotable=initial_promotable,
        response=response,
        requested_by=requested_by,
        dispatch_queued_project=dispatch_queued_project,
        research_row_lane_key=research_row_lane_key,
    )
    response = _execute_provider_generation(
        max_provider_requests=max_provider_requests,
        response=response,
        generation_target_lane=generation_target_lane,
        provider_openai_base_url=provider_openai_base_url,
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
        namespace_cls=namespace_cls,
        research_provider_generate=research_provider_generate,
        research_facility=research_facility,
        store=store,
        requested_by=requested_by,
    )
    response = _execute_promotion(
        promotable_rows=promotable_rows,
        open_lane_research_rows=open_lane_research_rows,
        max_promotions=max_promotions,
        max_dispatches=max_dispatches,
        store=store,
        requested_by=requested_by,
        response=response,
        _worker_lane_key=_worker_lane_key,
        dispatch_queued_project=dispatch_queued_project,
    )
    wait_result = _wait_for_completion(
        store=store,
        response=response,
        wait_for_completion=wait_for_completion,
        max_wait_seconds=max_wait_seconds,
        poll_interval_seconds=poll_interval_seconds,
    )
    drafted_papers, finalized_papers = _execute_research_paper_stages(
        store=store,
        response=response,
        max_paper_drafts=max_paper_drafts,
        max_publication_rewrites=max_publication_rewrites,
        wait_for_completion=wait_for_completion,
        wait_result=wait_result,
        requested_by=requested_by,
        draft_next=draft_next,
        rewrite_paper_review_draft=rewrite_paper_review_draft,
        control_api_bearer_token=control_api_bearer_token,
    )
    response["paper_drafts"] = drafted_papers
    response["paper_drafted_count"] = sum(
        1 for item in drafted_papers if item.get("action") == "drafted"
    )
    response["publication_finalizations"] = finalized_papers
    response["publication_finalized_count"] = len(finalized_papers)
    if not response.get("reason"):
        response["reason"] = (
            "bounded research cycle completed; broad queue pause preserved and paper stages were positive-gated"
        )
    if hasattr(store, "append_event"):
        store.append_event(
            idempotency_key=f"research-cycle:live:{requested_by}:{utc_now()}",
            event_type="research.run_cycle.live",
            entity_type="research",
            entity_id="run-cycle",
            payload=jsonable_encoder(response),
        )
    return response


def _research_row_lane_key(
    worker_lane_key: Callable[[dict[str, Any]], str], row: dict[str, Any]
) -> str:
    """Map a research workbench row to a worker lane key (extracted from dashboard_research_run_cycle)."""
    return worker_lane_key({"machine_target": str(row.get("machine_target") or "")})


def research_row_lane_key(row: dict[str, Any]) -> str:
    """Top-level name retained for extraction validators; requires a worker_lane_key at call sites."""
    raise NotImplementedError(
        "Use partial(_research_row_lane_key, worker_lane_key) inside create_control_plane_router"
    )


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
        # Fallback only for direct top-level calls; inside the giant the thin wrapper passes the local one.
        raise NotImplementedError(
            "lane_key_func must be provided when calling the top-level version directly"
        )
    return [row for row in rows if lane_key_func(row) not in active_lane_keys]


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
        if not hasattr(store, "research_facility_workbench_projection"):
            promotable_rows_for_feed: list[dict[str, Any]] = []
        else:
            try:
                workbench_rows = list(
                    store.research_facility_workbench_projection(limit=100)
                )  # type: ignore[attr-defined]
            except Exception:
                workbench_rows = []
            promotable_rows_for_feed = [
                row
                for row in workbench_rows
                if str(row.get("admission_decision") or "") == "admitted"
                and not str(row.get("admitted_idea_id") or "").strip()
                and float(row.get("total_score") or 0) >= min_admission_score
            ]
    else:
        promotable_rows_for_feed = list(promotable)

    queued_by_lane: dict[str, list[dict[str, Any]]] = {}
    promotable_by_lane: dict[str, list[dict[str, Any]]] = {}
    for row in _queued_dispatch_candidates(queued_rows):
        queued_by_lane.setdefault(_worker_lane_key(row), []).append(row)
    for row in promotable_rows_for_feed:
        promotable_by_lane.setdefault(_worker_lane_key(row), []).append(row)

    pressure: dict[str, dict[str, Any]] = {}
    min_queue_depth = max(0, min(int(min_queue_depth), 100))
    for lane in lane_rows:
        lane_key = str(lane.get("lane_key") or "")
        machine_target = str(lane.get("machine_target") or "")
        label = (
            "GB10 lane"
            if "gb10" in machine_target.lower()
            or "gpu" in str(lane.get("worker_role") or "").lower()
            else "CPU lane"
            if "cpu" in machine_target.lower()
            or "cpu" in str(lane.get("worker_role") or "").lower()
            else f"{machine_target or 'default'} lane"
        )
        queued_count = len(queued_by_lane.get(lane_key, []))
        promotable_count = len(promotable_by_lane.get(lane_key, []))
        active_count = int(lane.get("active_count") or 0)
        queue_deficit = max(0, min_queue_depth - queued_count)
        if not queue_deficit:
            next_action = "queue_depth_satisfied"
            summary = f"{label} has queued depth {queued_count}/{min_queue_depth}; no feed action needed."
        elif queued_count and not active_count:
            next_action = "dispatch_queued"
            summary = f"{label} idle with queued work; autopilot should dispatch the queued candidate."
        elif promotable_count:
            next_action = "promote_candidate"
            summary = f"{label} needs queued depth {queued_count}/{min_queue_depth}; autopilot should promote {promotable_count} admitted candidate(s)."
        else:
            next_action = "generate_candidate"
            if "gb10" in machine_target.lower():
                target_label = "GB10"
            elif "cpu" in machine_target.lower():
                target_label = "CPU"
            else:
                target_label = machine_target or "default"
            if queued_count:
                summary = f"{label} active with queued depth {queued_count}/{min_queue_depth}; autopilot should generate {target_label}-targeted work to fill the remaining deficit."
            else:
                summary = f"{label} {'idle ' if not active_count else ''}with no queued candidate; autopilot should generate {target_label}-targeted work."
        pressure[machine_target or lane_key] = {
            "lane_key": lane_key,
            "machine_target": machine_target,
            "worker_role": lane.get("worker_role"),
            "desired_queue_depth": min_queue_depth,
            "active_count": active_count,
            "queued_count": queued_count,
            "promotable_count": promotable_count,
            "queue_deficit": queue_deficit,
            "next_autopilot_action": next_action,
            "operator_summary": summary,
        }
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


def create_control_plane_router(
    config: GateConfig, require_bearer: RequireBearer
) -> APIRouter:
    router = APIRouter(prefix="/control", tags=["control-plane"])
    if config.control_plane_store_backend == "supabase_readonly":
        store = SupabaseReadOnlyControlPlaneStore(
            resolve_supabase_database_url(config.supabase_database_url)
        )
    elif config.control_plane_store_backend == "supabase":
        store = SupabaseControlPlaneStore(
            resolve_supabase_database_url(config.supabase_database_url)
        )
    else:
        store = ControlPlaneStore(config.expanded_state_dir / "control_plane.sqlite3")

    def authorize(authorization: str | None) -> None:
        require_bearer(authorization)

    def _require_writable_store(action: str) -> None:
        if config.control_plane_store_backend == "supabase_readonly":
            raise HTTPException(
                status_code=501,
                detail=f"{action} requires a writable control-plane store; supabase_readonly is read-only",
            )

    def _alert_paper_evidence_blocked(
        *, project_id: str, run_id: str = "", paper_id: str = "", reason: str = ""
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

    def _record_paper_evidence_blocked(
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
        # Bucket by UTC day, not hour. A missing-evidence paper candidate is
        # durable until evidence arrives or the row is no longer paper-ready;
        # hourly timer retries should not produce hourly Pushover noise.
        bucket = utc_now()[:10]
        key = ":".join(
            [
                "paper-evidence-sync-blocked",
                entity_type,
                _safe_slug(entity_id, "unknown"),
                _safe_slug(run_id or paper_id or "unknown", "unknown"),
                bucket,
            ]
        )
        try:
            event_id, inserted = store.append_event(
                idempotency_key=key,
                event_type="paper.evidence_sync_blocked",
                entity_type=entity_type,
                entity_id=entity_id,
                payload={
                    "project_id": project_id,
                    "run_id": run_id,
                    "paper_id": paper_id,
                    "artifact_root": artifact_root,
                    "reason": reason,
                    "evidence_sync_summary": {
                        "enabled": evidence_sync.get("enabled"),
                        "synced": evidence_sync.get("synced"),
                        "method": evidence_sync.get("method"),
                        "local_evidence_present": evidence_sync.get(
                            "local_evidence_present"
                        ),
                        "reason": reason,
                    },
                },
            )
        except IdempotencyConflict as exc:
            return {
                "attempted": False,
                "ok": True,
                "detail": "duplicate paper evidence alert suppressed",
                "event_id": None,
                "event_store_conflict": True,
                "event_store_error": str(exc)[:300],
            }
        except Exception as exc:  # noqa: BLE001 - alerting must survive event-store failures
            notification = _alert_paper_evidence_blocked(
                project_id=project_id, run_id=run_id, paper_id=paper_id, reason=reason
            )
            return {
                **notification,
                "event_id": None,
                "event_store_failed": True,
                "event_store_error": f"{type(exc).__name__}: {exc}"[:300],
            }
        if not inserted:
            return {
                "attempted": False,
                "ok": True,
                "detail": "duplicate paper evidence alert suppressed",
                "event_id": event_id,
            }
        notification = _alert_paper_evidence_blocked(
            project_id=project_id, run_id=run_id, paper_id=paper_id, reason=reason
        )
        return {**notification, "event_id": event_id}

    def _dispatch_route_metadata(machine_target: str, target: Any) -> dict[str, Any]:
        return {
            "machine_target": machine_target,
            "wake_gate_url": target.wake_gate_url,
            "worker_role": target.role,
            "token_configured": bool(target.bearer_token),
        }

    def _annotate_dispatch_route(
        candidate: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        if not candidate:
            return candidate
        machine_target = str(candidate.get("machine_target") or "")
        target = config.resolved_worker_target(machine_target)
        return {
            **candidate,
            "dispatch_route": _dispatch_route_metadata(machine_target, target),
        }

    def _worker_lane_key(candidate: dict[str, Any] | None) -> str:
        if not candidate:
            return ""
        target = config.resolved_worker_target(
            str(candidate.get("machine_target") or "")
        )
        return (
            (target.wake_gate_url or str(candidate.get("machine_target") or ""))
            .strip()
            .rstrip("/")
        )

    def _preflight_observation_lane_key(
        preflight: DashboardObservationRecord | None,
    ) -> str:
        payload = preflight.payload if preflight else {}
        target = (
            str(payload.get("target") or "").strip()
            if isinstance(payload, dict)
            else ""
        )
        if not target:
            return _worker_lane_key({"machine_target": ""})
        if "://" in target:
            if (urlparse(target).hostname or "") == DEFAULT_MACHINE_TARGET:
                return _worker_lane_key({"machine_target": ""})
            return target.rstrip("/")
        return _worker_lane_key({"machine_target": target})

    def _preflight_observation_applies_to_candidate(
        preflight: DashboardObservationRecord | None, candidate: dict[str, Any] | None
    ) -> bool:
        if not preflight or not candidate:
            return True
        preflight_lane = _preflight_observation_lane_key(preflight)
        if not preflight_lane:
            return True
        return preflight_lane == _worker_lane_key(candidate)

    def _callback_acceptance_token_fingerprint() -> str:
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

    def _active_items_fast(*, limit: int = 50) -> list[dict[str, Any]]:
        if hasattr(store, "active_items_sql"):
            return store.active_items_sql(limit=limit)  # type: ignore[attr-defined]
        return store.active_items()

    def _queued_items_fast(*, limit: int = 200) -> list[dict[str, Any]]:
        if hasattr(store, "queued_items_sql"):
            return store.queued_items_sql(limit=limit)  # type: ignore[attr-defined]
        return _queued_dispatch_candidates(store.queue_rows())[:limit]

    def _recently_completed_items_fast(*, limit: int = 50) -> list[dict[str, Any]]:
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

    def _queued_dispatch_candidates(
        rows: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        candidates = [
            row
            for row in (rows if rows is not None else store.queue_rows())
            if _normal_status(row.get("status")) == "queued"
            and not _truthy_flag(row.get("manual_review_required"))
        ]
        candidates.sort(key=_dispatch_sort_key)
        return candidates

    def _open_worker_dispatch_candidate(
        *,
        active: list[dict[str, Any]] | None = None,
        queued: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any] | None:
        if store.flags().queue_paused:
            return None
        active_lane_keys = {
            _worker_lane_key(row)
            for row in (active if active is not None else _active_items_fast())
        }
        # Keep dashboard/status reads bounded when a queued window is provided, but for
        # authoritative dispatch selection always evaluate the full queued candidate set.
        for candidate in _queued_dispatch_candidates(queued):
            if _worker_lane_key(candidate) not in active_lane_keys:
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

    def _configured_worker_lanes() -> list[dict[str, Any]]:
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

    def _worker_lane_capacity(
        *,
        active: list[dict[str, Any]] | None = None,
        rows: list[dict[str, Any]] | None = None,
        global_blockers: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        active_rows = list(active if active is not None else store.active_items())
        queue_rows = list(rows if rows is not None else store.queue_rows())
        active_by_lane: dict[str, list[dict[str, Any]]] = {}
        queued_by_lane: dict[str, list[dict[str, Any]]] = {}
        for row in active_rows:
            active_by_lane.setdefault(_worker_lane_key(row), []).append(row)
        queued_candidates = _queued_dispatch_candidates(queue_rows)
        for row in queued_candidates:
            queued_by_lane.setdefault(_worker_lane_key(row), []).append(row)

        lanes_by_key = {lane["lane_key"]: lane for lane in _configured_worker_lanes()}
        for row in [*active_rows, *queued_candidates]:
            lane_key = _worker_lane_key(row)
            if lane_key and lane_key not in lanes_by_key:
                target = config.resolved_worker_target(
                    str(row.get("machine_target") or "")
                )
                lanes_by_key[lane_key] = {
                    "lane_key": lane_key,
                    "machine_target": str(row.get("machine_target") or ""),
                    "worker_role": target.role or "worker",
                    "wake_gate_url": target.wake_gate_url,
                    "configured": False,
                }

        global_blockers = [str(item) for item in (global_blockers or []) if str(item)]
        output: list[dict[str, Any]] = []
        for lane in sorted(
            lanes_by_key.values(),
            key=lambda item: (
                str(item.get("worker_role") or ""),
                str(item.get("machine_target") or ""),
                str(item.get("lane_key") or ""),
            ),
        ):
            lane_key = str(lane["lane_key"])
            lane_active = sorted(
                active_by_lane.get(lane_key, []),
                key=lambda row: str(row.get("updated_at") or ""),
                reverse=True,
            )
            lane_queued = queued_by_lane.get(lane_key, [])
            next_candidate = lane_queued[0] if lane_queued else None
            dispatch_available = False
            dispatch_reason = ""
            dispatch_blocker = ""
            if lane_active:
                dispatch_blocker = "lane active"
            elif next_candidate and global_blockers:
                dispatch_blocker = global_blockers[0]
            elif next_candidate:
                dispatch_available = True
                dispatch_reason = "lane open with queued candidate"
            else:
                dispatch_blocker = "no queued candidate for lane"
            output.append(
                {
                    **lane,
                    "status": "active" if lane_active else "idle",
                    "active_count": len(lane_active),
                    "active_item": _worker_lane_summary_row(
                        lane_active[0] if lane_active else None
                    ),
                    "queued_count": len(lane_queued),
                    "next_candidate": _worker_lane_summary_row(next_candidate),
                    "dispatch_available": dispatch_available,
                    "dispatch_reason": dispatch_reason,
                    "dispatch_blocker": dispatch_blocker,
                }
            )
        return output

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

    def _candidate_machine_target_conflict_set(candidate: dict[str, Any]) -> set[str]:
        candidate_lane_key = _worker_lane_key(candidate)
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
            lane_key = _worker_lane_key({"machine_target": machine_target})
            if lane_key == candidate_lane_key:
                conflict_targets.add(normalized_target)
        return conflict_targets or {
            _normal_status(candidate.get("machine_target")) or ""
        }

    def _has_conflicting_active_lane(candidate: dict[str, Any]) -> bool:
        candidate_lane_key = _worker_lane_key(candidate)
        return any(
            _worker_lane_key(row) == candidate_lane_key for row in store.active_items()
        )

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

        base_url = os.environ.get(
            "ENOCH_RESEARCH_PROVIDER_BASE_URL", DEFAULT_RESEARCH_PROVIDER_BASE_URL
        ).rstrip("/")
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
                f"{base_url}/v2/quotas",
                api_key="",
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
        except Exception as exc:  # noqa: BLE001 - readiness must fail closed if the provider cannot be checked
            result = {
                "ok": False,
                "provider": "synthetic",
                "checked_at": utc_now(),
                "estimated_requests": estimated_requests,
                "reserve_requests": reserve_requests,
                "failures": [f"provider budget check failed: {exc}"],
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
        state = state_response().model_dump(mode="json")
        overview = read_models.overview(store, active_limit=5, event_limit=5)
        timers, services = _automation_timer_snapshot()
        status = dashboard_status_response(refresh_worker=False)
        resource_findings = [
            item for item in status.warnings if item.source == "worker_resource_policy"
        ]
        readiness = evaluate_longhaul_readiness(
            state=state,
            overview=overview,
            timers=timers,
            services=services,
            provider_budget=_provider_budget_for_readiness(),
            research_quality=_research_quality_payload(),
            source_lineage=_source_lineage_payload(),
            resource_utilization=resource_utilization_status(resource_findings),
        )
        return {
            "source": "control_api_v1_automation_readiness",
            "authority": "live control-plane state, systemd timers, provider budget, latest research-quality report, and bounded dashboard read model",
            "timers": timers,
            "services": services,
            **readiness,
        }

    def _record_preflight_observations(response: WorkerPreflightResponse) -> None:
        if config.control_plane_store_backend == "supabase_readonly":
            return
        preflight_payload = _compact_worker_preflight_payload(
            response.model_dump(mode="json")
        )
        store.upsert_dashboard_observation(
            source="worker_preflight",
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
            store.upsert_dashboard_observation(
                source="worker_dashboard_api",
                status="ok" if dashboard_check.ok else "unavailable",
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
        *, refresh_worker: bool, active: list[dict]
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
        if refresh_worker or _worker_observations_need_refresh(observations, active):
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
                worker_live_matches_active or worker_settling
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
                    authority="cross-source active-lane reconciliation",
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
                    authority="cross-source active-lane reconciliation",
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
        *, refresh_worker: bool = False
    ) -> DashboardStatusResponse:
        rows = _queued_items_fast()
        paper_counts = (
            store.paper_counts_sql() if hasattr(store, "paper_counts_sql") else {}
        )
        flags = store.flags()
        active = _active_items_fast()
        observations = _fetch_dashboard_status_observations(
            refresh_worker=refresh_worker, active=active
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
        has_critical = any(item.severity == "critical" for item in conflicts)
        dispatch_safe = not blockers and not has_critical
        worker_lanes = _worker_lane_capacity(
            active=active, rows=rows, global_blockers=blockers
        )
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

    def _intake_freshness() -> dict[str, DashboardFreshness]:
        return {
            **_db_freshness(SUPABASE_NATIVE_IDEAS_WORKBENCH_AUTHORITY),
            **_cached_observation_freshness(
                "idea_intake", "latest Supabase-native ideas intake observation"
            ),
        }

    def _require_legacy_notion_api_enabled() -> None:
        if not config.legacy_notion_api_enabled:
            raise HTTPException(
                status_code=410,
                detail={
                    "message": "Legacy Notion control-plane APIs are disabled; use Supabase-native /control/intake/ideas and /control/api/intake/ideas.",
                    "replacement": "/control/intake/ideas",
                },
            )

    @router.get("/dashboard")
    def dashboard() -> RedirectResponse:
        """Legacy dashboard URL redirects to canonical Dashboard V2 (hash preserved client-side)."""
        return RedirectResponse(url="/control/dashboard-v2", status_code=307)

    @router.get("/dashboard-v2", response_class=HTMLResponse)
    def dashboard_v2() -> HTMLResponse:
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

    @router.get("/dashboard-v2/assets/{asset_path:path}")
    def dashboard_v2_asset(asset_path: str) -> Response:
        asset_root = (DASHBOARD_V2_DIST_PATH / "assets").resolve()
        candidate = (asset_root / asset_path).resolve()
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
    def health(authorization: str | None = Header(default=None)) -> dict:
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
        authorization: str | None = Header(default=None),
    ) -> ControlStateResponse:
        authorize(authorization)
        return state_response()

    @router.get("/api/status")
    def dashboard_status(
        refresh_worker: Annotated[bool, Query()] = False,
        authorization: Annotated[str | None, Header()] = None,
    ) -> DashboardStatusResponse:
        authorize(authorization)
        return dashboard_status_response(refresh_worker=refresh_worker)

    def _artifact_root_for_queue_row(row: dict[str, Any]) -> tuple[Path, str]:
        project_id = str(row.get("project_id") or "").strip()
        project_dir_text = str(row.get("project_dir") or project_id).strip()
        return _local_artifact_root(
            config, project_id=project_id, project_dir_text=project_dir_text
        ), project_dir_text

    def _evidence_sync_skipped_by_gate(gate: dict[str, Any]) -> dict[str, Any]:
        return {
            "enabled": config.paper_evidence_sync_enabled,
            "synced": False,
            "skipped": True,
            "reason": "decision_gate_not_writable",
            "decision_gate_reason": str(gate.get("reason") or ""),
        }

    def _worker_evidence_sync_kwargs_for_row(row: dict[str, Any]) -> dict[str, Any]:
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

    def _auto_reconcile_stale_callback_ready(
        status: DashboardStatusResponse, *, requested_by: str
    ) -> list[dict[str, Any]]:
        if not status.active_items:
            return []
        has_no_live_conflict = any(
            item.source == CONTROL_PLANE_DB_WORKER_PREFLIGHT_SOURCE
            and "no live worker run" in item.message
            for item in [*status.conflicts, *status.warnings]
        )
        if not has_no_live_conflict:
            return []
        reconciled: list[dict[str, Any]] = []
        for row in status.active_items:
            project_id = str(row.get("project_id") or "").strip()
            run_id = str(row.get("current_run_id") or "").strip()
            if not project_id or not run_id:
                continue
            artifact_root, project_dir_text = _artifact_root_for_queue_row(row)
            gate = paper_draft_decision_gate(artifact_root)
            evidence_sync = _evidence_sync_skipped_by_gate(gate)
            if gate.get("eligible") or not gate.get("values"):
                evidence_sync = _sync_remote_project_evidence(
                    config,
                    project_id=project_id,
                    artifact_root=artifact_root,
                    source_project_dir=project_dir_text,
                    source_run_id=run_id,
                    **_worker_evidence_sync_kwargs_for_row(row),
                )
                gate = paper_draft_decision_gate(artifact_root)
            local_evidence_present = _local_paper_evidence_present(artifact_root)
            if (
                config.paper_evidence_sync_enabled
                and not local_evidence_present
                and gate.get("eligible")
            ):
                evidence_alert = _record_paper_evidence_blocked(
                    entity_type="project",
                    entity_id=project_id,
                    project_id=project_id,
                    run_id=run_id,
                    artifact_root=str(artifact_root),
                    evidence_sync=evidence_sync,
                )
                reconciled.append(
                    {
                        "ok": False,
                        "project_id": project_id,
                        "run_id": run_id,
                        "reason": "missing paper evidence",
                        "artifact_root": str(artifact_root),
                        "evidence_sync": evidence_sync,
                        "decision_gate": gate,
                        "evidence_alert": evidence_alert,
                    }
                )
                continue
            if not gate.get("values"):
                reconciled.append(
                    {
                        "ok": False,
                        "project_id": project_id,
                        "run_id": run_id,
                        "reason": "missing project decision artifact",
                        "artifact_root": str(artifact_root),
                        "evidence_sync": evidence_sync,
                    }
                )
                continue
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
                },
                reason="auto replay: active row had no live worker run but durable decision artifact exists",
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
                    if hasattr(store, "record_project_decision_gate")
                    else {}
                )
                if decision_record.get("persisted"):
                    store.update_project_dir(project_id, str(artifact_root))
                reconciled.append(
                    {
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
                    }
                )
            except Exception as exc:
                reconciled.append(
                    {
                        "ok": False,
                        "project_id": project_id,
                        "run_id": run_id,
                        "reason": f"{type(exc).__name__}: {exc}",
                        "artifact_root": str(artifact_root),
                        "evidence_sync": evidence_sync,
                    }
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

    @router.post("/api/alerts/queue-check")
    def dashboard_queue_alert_check(
        payload: dict[str, Any] | None = None,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        authorize(authorization)
        request_payload = payload or {}
        dry_run = bool(request_payload.get("dry_run", True))
        requested_by = str(request_payload.get("requested_by") or "operator")
        if not dry_run:
            _require_writable_store("queue alert live check")
        status = dashboard_status_response(
            refresh_worker=bool(request_payload.get("refresh_worker", False))
        )
        auto_reconcile: list[dict[str, Any]] = []
        if not dry_run:
            auto_reconcile = _auto_reconcile_stale_callback_ready(
                status, requested_by=requested_by
            )
            if any(item.get("ok") for item in auto_reconcile):
                status = dashboard_status_response(refresh_worker=False)
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
                        "findings": [],
                        "notification": {
                            "attempted": False,
                            "ok": True,
                            "status_code": None,
                            "detail": "auto reconciled stale callback",
                        },
                    }
                )
        return alert

    @router.get("/api/queue-health")
    def dashboard_queue_health(
        refresh_worker: bool = Query(default=False),
        authorization: str | None = Header(default=None),
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

    @router.post("/api/worker-callback")
    def worker_callback(
        callback: GateCallback, authorization: str | None = Header(default=None)
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
            artifact_root, project_dir_text = _artifact_root_for_queue_row(row)
            decision_gate = paper_draft_decision_gate(artifact_root)
            evidence_sync = _evidence_sync_skipped_by_gate(decision_gate)
            if decision_gate.get("eligible") or not decision_gate.get("values"):
                evidence_sync = _sync_remote_project_evidence(
                    config,
                    project_id=project_id,
                    artifact_root=artifact_root,
                    source_project_dir=project_dir_text,
                    source_run_id=str(callback.run_id or ""),
                    **_worker_evidence_sync_kwargs_for_row(row),
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
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        authorize(authorization)
        return _research_quality_payload()

    @router.get("/api/v1/source-lineage")
    def dashboard_v1_source_lineage(
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        authorize(authorization)
        return _source_lineage_payload()

    @router.get("/api/v1/automation-readiness")
    def dashboard_v1_automation_readiness(
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        authorize(authorization)
        return _automation_readiness_payload()

    @router.get("/api/v1/overview")
    def dashboard_v1_overview(
        authorization: str | None = Header(default=None),
        active_limit: int = Query(default=5, ge=1, le=25),
        event_limit: int = Query(default=10, ge=0, le=50),
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

    @router.post("/api/v1/followups/launch-next")
    def launch_next_followup(
        payload: FollowupLaunchRequest, authorization: str | None = Header(default=None)
    ) -> FollowupLaunchResponse:
        authorize(authorization)
        if not payload.dry_run:
            _require_writable_store("follow-up launch")
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
        authorization: str | None = Header(default=None),
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
        authorization: str | None = Header(default=None),
        queue: str = Query(default="all"),
        status: str = "",
        search: str = "",
        cursor: str = "",
        page_size: int = Query(default=50, ge=1, le=200),
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
        authorization: str | None = Header(default=None),
        state: str = "",
        project_id: str = "",
        search: str = "",
        cursor: str = "",
        page_size: int = Query(default=50, ge=1, le=200),
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

    @router.get("/api/v1/runs/{run_id}")
    def dashboard_v1_run_detail(
        run_id: str,
        authorization: str | None = Header(default=None),
        event_limit: int = Query(default=50, ge=0, le=100),
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
        authorization: str | None = Header(default=None),
        status: str = "",
        search: str = "",
        cursor: str = "",
        page_size: int = Query(default=50, ge=1, le=200),
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

    @router.get("/api/v1/projects/{project_id}")
    def dashboard_v1_project_detail(
        project_id: str,
        authorization: str | None = Header(default=None),
        event_limit: int = Query(default=50, ge=0, le=100),
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
        authorization: str | None = Header(default=None),
        status: str = "",
        search: str = "",
        cursor: str = "",
        page_size: int = Query(default=50, ge=1, le=200),
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

    @router.get("/api/v1/papers/{paper_id}")
    def dashboard_v1_paper_detail(
        paper_id: str,
        authorization: str | None = Header(default=None),
        event_limit: int = Query(default=50, ge=0, le=100),
    ) -> dict[str, Any]:
        authorize(authorization)
        paper = store.paper_row(paper_id)
        if paper is None:
            raise HTTPException(status_code=404, detail="paper not found")
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
        authorization: str | None = Header(default=None),
        event_id: str = "",
        entity_type: str = "",
        entity_id: str = "",
        event_type: str = "",
        search: str = "",
        cursor: str = "",
        page_size: int = Query(default=50, ge=1, le=200),
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
        authorization: str | None = Header(default=None),
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
            "latest_route_observation": latest_route_observation,
        }

    @router.get("/api/v1/observability/memory")
    def dashboard_v1_observability_memory(
        authorization: str | None = Header(default=None),
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

    @router.get("/api/queues/{queue}")
    def dashboard_queue(
        queue: str,
        authorization: str | None = Header(default=None),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=50, ge=1, le=500),
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
                    authority="cross-source active-lane reconciliation",
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

    @router.get("/api/projects/{project_id}")
    def dashboard_project(
        project_id: str, authorization: str | None = Header(default=None)
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

    @router.get("/api/runs/{run_id}")
    def dashboard_run(
        run_id: str, authorization: str | None = Header(default=None)
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

    @router.post(
        "/api/publication-automation/backfill",
    )
    @router.post("/api/paper-reviews/backfill")
    def dashboard_paper_reviews_backfill(
        payload: PaperReviewBackfillRequest,
        authorization: str | None = Header(default=None),
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

    def _dashboard_paper_reviews_response(
        *,
        authorization: str | None = Header(default=None),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=50, ge=1, le=500),
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

    @router.get("/api/publication-automation")
    def dashboard_publication_automation(
        authorization: str | None = Header(default=None),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=50, ge=1, le=500),
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
        authorization: str | None = Header(default=None),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=50, ge=1, le=500),
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

    def _paper_review_detail_response(
        paper_id: str,
    ) -> DashboardPaperReviewDetailResponse:
        item = store.paper_review_row(paper_id, include_rank_reasons=True)
        paper = store.paper_row(paper_id)
        if item is None or paper is None:
            raise HTTPException(
                status_code=404, detail="publication automation item not found"
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
        authorization: str | None = Header(default=None),
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
            raise HTTPException(
                status_code=404, detail="no matching publication automation item"
            )
        return _paper_review_detail_response(str(rows[0].get("paper_id") or ""))

    @router.get(
        "/api/publication-automation/next",
    )
    def dashboard_next_publication_automation(
        authorization: str | None = Header(default=None),
        review_status: str = "",
        paper_status: str = "publication_draft",
        search: str = "",
    ) -> DashboardPaperReviewDetailResponse:
        return _dashboard_next_paper_review_response(
            authorization=authorization,
            review_status=review_status,
            paper_status=paper_status,
            search=search,
        )

    @router.get("/api/paper-reviews/next")
    def dashboard_next_paper_review(
        authorization: str | None = Header(default=None),
        review_status: str = "",
        paper_status: str = "publication_draft",
        search: str = "",
    ) -> DashboardPaperReviewDetailResponse:
        return _dashboard_next_paper_review_response(
            authorization=authorization,
            review_status=review_status,
            paper_status=paper_status,
            search=search,
        )

    @router.get(
        "/api/publication-automation/{paper_id}",
    )
    def dashboard_publication_automation_item(
        paper_id: str, authorization: str | None = Header(default=None)
    ) -> DashboardPaperReviewDetailResponse:
        authorize(authorization)
        return _paper_review_detail_response(paper_id)

    @router.get(
        "/api/paper-reviews/{paper_id}",
    )
    def dashboard_paper_review(
        paper_id: str, authorization: str | None = Header(default=None)
    ) -> DashboardPaperReviewDetailResponse:
        authorize(authorization)
        return _paper_review_detail_response(paper_id)

    @router.post(
        "/api/publication-automation/{paper_id}/claim",
    )
    @router.post(
        "/api/paper-reviews/{paper_id}/claim",
    )
    def dashboard_paper_review_claim(
        paper_id: str,
        payload: PaperReviewClaimRequest,
        authorization: str | None = Header(default=None),
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
    )
    @router.post(
        "/api/paper-reviews/{paper_id}/checklist/{item_id}",
    )
    def dashboard_paper_review_checklist(
        paper_id: str,
        item_id: str,
        payload: PaperReviewChecklistUpdateRequest,
        authorization: str | None = Header(default=None),
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
    )
    @router.post(
        "/api/paper-reviews/{paper_id}/status",
    )
    def dashboard_paper_review_status(
        paper_id: str,
        payload: PaperReviewStatusUpdateRequest,
        authorization: str | None = Header(default=None),
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
    )
    @router.post(
        "/api/paper-reviews/{paper_id}/approve-finalization",
    )
    def dashboard_paper_review_approve_finalization(
        paper_id: str,
        payload: PaperReviewApproveFinalizationRequest,
        authorization: str | None = Header(default=None),
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

    def _rewrite_paper_review_draft(
        paper_id: str, payload: PaperReviewRewriteDraftRequest
    ) -> PaperReviewRewriteDraftResponse:
        paper, item = _paper_rewrite_rows_or_404(store, paper_id)
        project_id = str(paper.get("project_id") or "")
        project = store.project_row(project_id) if project_id else None
        artifact_root, use_current_dir = _resolve_paper_rewrite_artifact_root(
            config, project_id=project_id, project=project
        )
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
                entity_type="paper",
                entity_id=paper_id,
                project_id=project_id,
                run_id=str(paper.get("run_id") or ""),
                paper_id=paper_id,
                artifact_root=str(artifact_root),
                evidence_sync=evidence_sync,
            )
            raise HTTPException(
                status_code=424,
                detail={
                    "message": "paper rewrite requires synced project evidence",
                    "evidence_sync": evidence_sync,
                },
            )
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
            raise HTTPException(status_code=404, detail="paper not found")
        project_id = str(paper.get("project_id") or "").strip()
        project_dir_text = str(paper.get("project_dir") or project_id).strip()
        safe_root = _local_artifact_root(
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

    @router.post(
        "/api/publication-automation/rewrite-batch",
    )
    @router.post(
        "/api/paper-reviews/rewrite-batch",
    )
    def dashboard_paper_reviews_rewrite_batch(
        payload: PaperReviewBulkRewriteRequest,
        authorization: str | None = Header(default=None),
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
    )
    @router.post(
        "/api/paper-reviews/{paper_id}/rewrite-draft",
    )
    def dashboard_paper_review_rewrite_draft(
        paper_id: str,
        payload: PaperReviewRewriteDraftRequest,
        authorization: str | None = Header(default=None),
    ) -> PaperReviewRewriteDraftResponse:
        authorize(authorization)
        _require_writable_store("publication automation draft rewrite")
        return _rewrite_paper_review_draft(paper_id, payload)

    @router.post(
        "/api/publication-automation/{paper_id}/prepare-finalization-package",
    )
    @router.post(
        "/api/paper-reviews/{paper_id}/prepare-finalization-package",
    )
    def dashboard_paper_review_prepare_finalization_package(
        paper_id: str,
        payload: PaperReviewPrepareFinalizationRequest,
        authorization: str | None = Header(default=None),
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
        authorization: str | None = Header(default=None),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=50, ge=1, le=500),
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
            _local_artifact_root(
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
        resolved = (
            path
            if path.is_absolute()
            else ((project_dir / path) if project_dir else path)
        )
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

    @router.get("/api/papers/{paper_id}/artifact/{field}")
    def dashboard_paper_artifact(
        paper_id: str, field: str, authorization: str | None = Header(default=None)
    ) -> dict[str, Any]:
        authorize(authorization)
        paper = store.paper_row(paper_id)
        if paper is None:
            raise HTTPException(status_code=404, detail="paper not found")
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

    @router.get("/api/papers/{paper_id}")
    def dashboard_paper(
        paper_id: str, authorization: str | None = Header(default=None)
    ) -> DashboardPaperDetailResponse:
        authorize(authorization)
        paper = store.paper_row(paper_id)
        if paper is None:
            raise HTTPException(status_code=404, detail="paper not found")
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
        authorization: str | None = Header(default=None),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=100, ge=1, le=500),
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

    @router.get("/api/intake/ideas")
    def dashboard_ideas_intake(
        authorization: str | None = Header(default=None),
        page_size: int = Query(default=50, ge=1, le=200),
        include_latest_payload: bool = Query(default=False),
    ) -> DashboardIntakeResponse:
        authorize(authorization)
        return _dashboard_ideas_intake_response(
            page_size=page_size, include_latest_payload=include_latest_payload
        )

    @router.get("/api/research/facility")
    def dashboard_research_facility(
        authorization: str | None = Header(default=None),
        page_size: int = Query(default=50, ge=1, le=200),
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

    @router.post("/api/research/generate-batch")
    def dashboard_research_generate_batch(
        payload: dict[str, Any] | None = Body(default=None),
        authorization: str | None = Header(default=None),
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
                detail="Research Facility ledger writes require the Supabase control-plane store",
            )
        response["ledger_result"] = store.record_research_facility_plans(
            plans, requested_by=requested_by, queue_admitted=False
        )
        return response

    @router.post("/api/research/generate-provider-batch")
    def dashboard_research_generate_provider_batch(
        payload: dict[str, Any] | None = Body(default=None),
        authorization: str | None = Header(default=None),
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
                detail="Research Facility ledger writes require the Supabase control-plane store",
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

    @router.post("/api/research/run-cycle")
    def dashboard_research_run_cycle(
        payload: dict[str, Any] | None = Body(default=None),
        authorization: str | None = Header(default=None),
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
        generation_timeout = params.generation_timeout
        generation_max_tokens = params.generation_max_tokens
        generation_attempts = params.generation_attempts

        active = store.active_items()
        counts = store.status_counts()
        blocked_count = int(counts.get("blocked") or 0)
        backpressure_reasons: list[str] = []
        estimated_requests = max_provider_requests * generation_attempts
        budget = _fetch_synthetic_research_budget(
            provider_base_url=provider_base_url,
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
        generation_target_lane = _select_generation_target_lane(
            lane_feed_pressure, max_dispatches
        )
        backpressure_reasons.extend(
            _evaluate_research_cycle_backpressure(
                active=active,
                initial_open_lane_promotable=initial_open_lane_promotable,
                generation_target_lane=generation_target_lane,
                max_provider_requests=max_provider_requests,
            )
        )
        response = _build_research_cycle_initial_response(
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
            return early_response

        open_lane_research_rows_local = partial(
            open_lane_research_rows, lane_key_func=research_row_lane_key
        )

        return _execute_live_research_cycle(
            store=store,
            response=response,
            requested_by=requested_by,
            generation_target_lane=generation_target_lane,
            max_dispatches=max_dispatches,
            max_provider_requests=max_provider_requests,
            fresh_generation_backlog_threshold=fresh_generation_backlog_threshold,
            initial_promotable=initial_promotable,
            promotable_rows=promotable_rows,
            open_lane_research_rows=open_lane_research_rows_local,
            max_promotions=max_promotions,
            provider_openai_base_url=provider_openai_base_url,
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
            _worker_lane_key=_worker_lane_key,
            _live_dispatch=_live_dispatch,
            jsonable_encoder=jsonable_encoder,
            research_row_lane_key=research_row_lane_key,
        )

    @router.post("/api/research/promote-candidate")
    def dashboard_research_promote_candidate(
        payload: dict[str, Any] | None = Body(default=None),
        authorization: str | None = Header(default=None),
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
        authorization: str | None = Header(default=None),
        estimated_requests: int = Query(default=2, ge=0, le=100),
        reserve_requests: int = Query(default=2, ge=0, le=100),
        min_remaining_credits: float = Query(default=5.0, ge=0.0),
        min_rolling_remaining: int = Query(default=10, ge=0),
        timeout: int = Query(default=20, ge=1, le=60),
    ) -> dict[str, Any]:
        authorize(authorization)
        from scripts import research_provider_budget

        base_url = os.environ.get(
            "ENOCH_RESEARCH_PROVIDER_BASE_URL", DEFAULT_RESEARCH_PROVIDER_BASE_URL
        ).rstrip("/")
        try:
            payload = research_provider_budget.fetch_json(
                f"{base_url}/v2/quotas", api_key="", timeout=timeout
            )
            result = research_provider_budget.synthetic_budget_status(
                payload,
                min_remaining_credits=min_remaining_credits,
                min_rolling_remaining=min_rolling_remaining,
                estimated_requests=estimated_requests,
                reserve_requests=reserve_requests,
            )
        except Exception as exc:  # noqa: BLE001 - provider checks must fail closed but stay operator-readable
            result = {
                "ok": False,
                "provider": "synthetic",
                "checked_at": utc_now(),
                "estimated_requests": estimated_requests,
                "reserve_requests": reserve_requests,
                "failures": [f"provider budget check failed: {exc}"],
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
            "failures",
        }
        response = {key: result.get(key) for key in safe_keys if key in result}
        response.update(
            {
                "provider_endpoint": "configured",
                "auth_mode": "exe_http_proxy",
                "payload_json": None,
            }
        )
        return response

    @router.get("/api/intake/notion")
    def dashboard_notion_intake(
        authorization: str | None = Header(default=None),
        page_size: int = Query(default=50, ge=1, le=200),
        include_latest_payload: bool = Query(default=False),
    ) -> DashboardIntakeResponse:
        authorize(authorization)
        _require_legacy_notion_api_enabled()
        return _dashboard_ideas_intake_response(
            legacy_notion_alias=True,
            page_size=page_size,
            include_latest_payload=include_latest_payload,
        )

    @router.post("/pause")
    def pause(
        payload: PauseRequest, authorization: str | None = Header(default=None)
    ) -> ControlStateResponse:
        authorize(authorization)
        _require_writable_store("operator pause")
        store.pause(
            reason=payload.reason,
            paused_by=payload.paused_by,
            maintenance_mode=payload.maintenance_mode,
        )
        return state_response()

    @router.post("/resume")
    def resume(
        payload: ResumeRequest, authorization: str | None = Header(default=None)
    ) -> ControlStateResponse:
        authorize(authorization)
        _require_writable_store("operator resume")
        store.resume(
            resumed_by=payload.resumed_by, maintenance_mode=payload.maintenance_mode
        )
        return state_response()

    @router.post("/queue/mark-paused")
    def mark_queue_item_paused(
        payload: MarkQueueItemPausedRequest,
        authorization: str | None = Header(default=None),
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

    @router.post("/import/legacy-snapshot")
    def import_snapshot(
        payload: ImportSnapshotRequest, authorization: str | None = Header(default=None)
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

    @router.post("/intake/notion-ideas")
    def intake_notion_ideas(
        payload: NotionIntakeRequest, authorization: str | None = Header(default=None)
    ) -> NotionIntakeResponse:
        authorize(authorization)
        _require_legacy_notion_api_enabled()
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

    @router.post("/intake/ideas")
    def intake_ideas(
        payload: IdeaIntakeRequest, authorization: str | None = Header(default=None)
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

    @router.post("/api/intake/notion-observation")
    def record_notion_observation(
        payload: dict[str, Any], authorization: str | None = Header(default=None)
    ) -> dict[str, Any]:
        authorize(authorization)
        _require_legacy_notion_api_enabled()
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
        payload: dict[str, Any], authorization: str | None = Header(default=None)
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

    def _configured_worker_preflight_url() -> str:
        worker_url = (config.worker_wake_gate_url or "").strip()
        worker_host = urlparse(worker_url).hostname or ""
        if not worker_url or worker_host == DEFAULT_MACHINE_TARGET:
            raise HTTPException(
                status_code=503,
                detail="worker preflight requires configured worker_wake_gate_url",
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
            raise HTTPException(
                status_code=400,
                detail="wake_gate_url must match configured worker_wake_gate_url or a configured worker target; use machine_target for named routes",
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

    @router.post("/worker/preflight")
    def worker_preflight(
        payload: WorkerPreflightRequest,
        authorization: str | None = Header(default=None),
    ) -> WorkerPreflightResponse:
        authorize(authorization)
        payload = payload.model_copy(
            update={
                "wake_gate_url": _configured_worker_preflight_url(),
                "bearer_token": config.worker_wake_gate_bearer_token,
                "expected_callback_token_fingerprint": payload.expected_callback_token_fingerprint
                or _callback_acceptance_token_fingerprint(),
            }
        )
        response = run_worker_preflight(payload, store.flags())
        _record_preflight_observations(response)
        return response

    @router.post("/api/preflight")
    def dashboard_preflight(
        payload: WorkerPreflightRequest,
        authorization: Annotated[str | None, Header()] = None,
    ) -> WorkerPreflightResponse:
        authorize(authorization)
        payload = _target_aware_preflight_payload(payload)
        response = run_worker_preflight(payload, store.flags())
        if _preflight_targets_default_worker(payload):
            _record_preflight_observations(response)
        return response

    @router.post("/dispatch-next")
    def dispatch_next(
        payload: DispatchNextRequest, authorization: str | None = Header(default=None)
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

    @router.post("/dispatch-one")
    def dispatch_one(
        payload: DispatchOneRequest, authorization: str | None = Header(default=None)
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
    def queue(authorization: str | None = Header(default=None)) -> dict:
        authorize(authorization)
        return {
            "ok": True,
            "rows": store.queue_rows(),
            "counts": store.status_counts(),
            "active": store.active_items(),
        }

    @router.get("/papers")
    def papers(authorization: str | None = Header(default=None)) -> dict:
        authorize(authorization)
        return {"ok": True, "rows": store.paper_rows()}

    @router.get("/export/snapshot")
    def export_snapshot(
        authorization: str | None = Header(default=None),
    ) -> ExportSnapshotResponse:
        authorize(authorization)
        snapshot = store.export_snapshot()
        return ExportSnapshotResponse(
            flags=store.flags(),
            queue_rows=snapshot["queue_rows"],
            paper_rows=snapshot["paper_rows"],
            events=snapshot["events"],
        )

    @router.get("/projections/notion/queue")
    def notion_queue_projection(
        authorization: str | None = Header(default=None),
    ) -> ProjectionResponse:
        authorize(authorization)
        _require_legacy_notion_api_enabled()
        rows = store.queue_notion_projection()
        return ProjectionResponse(rows=rows, counts=store.status_counts())

    @router.get("/projections/ideas/workbench")
    def ideas_workbench_projection(
        authorization: str | None = Header(default=None),
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

    @router.get("/projections/notion/papers")
    def notion_papers_projection(
        authorization: str | None = Header(default=None),
    ) -> ProjectionResponse:
        authorize(authorization)
        _require_legacy_notion_api_enabled()
        rows = store.paper_notion_projection()
        counts: dict[str, int] = {}
        for row in rows:
            key = str(row.get("paper_status") or "unknown")
            counts[key] = counts.get(key, 0) + 1
        return ProjectionResponse(rows=rows, counts=counts)

    @router.get("/projections/notion/execution-updates")
    def notion_execution_updates_projection(
        authorization: str | None = Header(default=None),
    ) -> ProjectionResponse:
        authorize(authorization)
        _require_legacy_notion_api_enabled()
        rows = store.notion_execution_update_projection()
        return ProjectionResponse(rows=rows, counts={"updates": len(rows)})

    def _candidate_project_dir(candidate: dict[str, Any]) -> Path:
        project_id = str(candidate.get("project_id") or "").strip()
        project_dir_text = str(candidate.get("project_dir") or project_id).strip()
        # Completed worker rows can carry worker-absolute or stale relative paths
        # that are not valid on the VM. Use a VM-local artifact root and keep the
        # original source path only for evidence sync.
        return _local_artifact_root(
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

    @router.post("/papers/draft-next")
    def draft_next(
        payload: DraftNextRequest, authorization: str | None = Header(default=None)
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
            evidence = _prepare_draft_evidence(candidate)
            if not evidence["local_evidence_present"]:
                _record_paper_evidence_blocked(
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

    return router
