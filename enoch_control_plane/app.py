from __future__ import annotations

import logging

import asyncio
from contextlib import asynccontextmanager
from collections import Counter
from collections import deque
from datetime import datetime, timezone
import hashlib
import heapq
import html
import hmac
import json
import os
import re
import subprocess
import tempfile
import threading
import urllib.error
from pathlib import Path
import time
from typing import Annotated, Any

from tenacity import RetryError
from fastapi import FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import ValidationError

from . import callback_outbox
from .callbacks import CallbackSender
from .control_plane.router import create_control_plane_router
from .config import GateConfig
from .enoch_core.router import create_enoch_core_router
from .gate import WakeGate
from .observability import RouteObservationMiddleware
from .observability import ProfilingMiddleware, init_sentry
from .observability.error_tracking import capture_exception
from .timeutils import parse_utc_datetime
from .enoch_core.logic import split_numbered_list_text
from .models import (
    DispatchRequest,
    GateCallback,
    GateState,
    PaperArtifactReadRequest,
    PaperArtifactRequest,
    PrepareProjectRequest,
    ProcessInfo,
    ProjectDecision,
    ProjectStatusResponse,
    RunRecord,
    SessionHistoryEntry,
    utc_now,
)
from .process_tracker import ProcessTracker
from .state_store import StateStore
from .telemetry import TelemetryCollector

# Centralized label for project directory checks (eliminates S1192 duplication
# of the literal across multiple _checked_exists / _checked_is_dir calls and
# error messages in the dashboard API handlers).

_logger = logging.getLogger(__name__)

PROJECT_DIRECTORY_LABEL = "project directory"
PAPER_ARTIFACT_ALLOWED_SUFFIXES = frozenset(
    {".json", ".md", ".markdown", ".txt", ".log", ".yaml", ".yml"}
)
PROJECT_JSON_FILENAME = "project.json"
ENOCH_PROJECT_DIRNAME = ".enoch"
_TRACEBACK_LINE = re.compile(
    r"^\s*(traceback \(most recent call last\)|file \"[^\"]+\", line \d+|"
    r"[a-zA-Z_][\w.]*(?:Error|Exception):)",
    re.I,
)


class ControlPlaneHttpError(Exception):
    """HTTP error from app helpers; converted to a response by the app exception handler."""

    def __init__(self, status_code: int, detail: str | dict[str, object]) -> None:
        super().__init__(detail if isinstance(detail, str) else str(detail))
        self.status_code = status_code
        self.detail = detail


def _http_responses(
    *parts: dict[int, dict[str, str]],
) -> dict[int, dict[str, str]]:
    merged: dict[int, dict[str, str]] = {}
    for part in parts:
        merged.update(part)
    return merged


_HTTP_401_INVALID_BEARER: dict[int, dict[str, str]] = {
    401: {"description": "Invalid or missing control API bearer token"},
}
_HTTP_400_INVALID_REQUEST: dict[int, dict[str, str]] = {
    400: {
        "description": (
            "Invalid path, metadata, workload class, or project resolution"
        ),
    },
}
_HTTP_403_FORBIDDEN_READ: dict[int, dict[str, str]] = {
    403: {
        "description": "Project directory or paper artifact is not readable",
    },
}
_HTTP_404_NOT_FOUND: dict[int, dict[str, str]] = {
    404: {"description": "Project directory, paper artifact, or run not found"},
}
_HTTP_409_FILE_EXISTS: dict[int, dict[str, str]] = {
    409: {"description": "Refusing to overwrite an existing file"},
}
_HTTP_413_PAYLOAD_TOO_LARGE: dict[int, dict[str, str]] = {
    413: {"description": "Paper artifact exceeds the allowed byte limit"},
}
_HTTP_415_UNSUPPORTED_MEDIA: dict[int, dict[str, str]] = {
    415: {"description": "Paper artifact is not UTF-8 text"},
}
_HTTP_500_INTERNAL: dict[int, dict[str, str]] = {
    500: {
        "description": (
            "Project metadata, path inspection, or dispatch configuration failure"
        ),
    },
}
_HTTP_502_BAD_GATEWAY: dict[int, dict[str, str]] = {
    502: {
        "description": "Dispatch subprocess failed or returned non-JSON output",
    },
}
_HTTP_504_GATEWAY_TIMEOUT: dict[int, dict[str, str]] = {
    504: {"description": "Dispatch subprocess timed out"},
}

_DASHBOARD_SNAPSHOT_RESPONSES = _http_responses(
    _HTTP_401_INVALID_BEARER,
    _HTTP_409_FILE_EXISTS,
)
_DASHBOARD_PAPER_ARTIFACT_RESPONSES = _http_responses(
    _HTTP_401_INVALID_BEARER,
    _HTTP_400_INVALID_REQUEST,
    _HTTP_403_FORBIDDEN_READ,
    _HTTP_404_NOT_FOUND,
    _HTTP_413_PAYLOAD_TOO_LARGE,
    _HTTP_415_UNSUPPORTED_MEDIA,
)
_DASHBOARD_API_RUN_RESPONSES = _http_responses(
    _HTTP_401_INVALID_BEARER,
    _HTTP_404_NOT_FOUND,
)
_PROJECT_STATUS_RESPONSES = _http_responses(
    _HTTP_401_INVALID_BEARER,
    _HTTP_400_INVALID_REQUEST,
    _HTTP_403_FORBIDDEN_READ,
)
_PREPARE_PROJECT_RESPONSES = _http_responses(
    _HTTP_401_INVALID_BEARER,
    _HTTP_400_INVALID_REQUEST,
    _HTTP_409_FILE_EXISTS,
)
_READ_PROJECT_PAPER_RESPONSES = _http_responses(
    _HTTP_401_INVALID_BEARER,
    _HTTP_400_INVALID_REQUEST,
    _HTTP_403_FORBIDDEN_READ,
    _HTTP_404_NOT_FOUND,
    _HTTP_413_PAYLOAD_TOO_LARGE,
    _HTTP_415_UNSUPPORTED_MEDIA,
)
_WRITE_PROJECT_PAPER_RESPONSES = _http_responses(
    _HTTP_401_INVALID_BEARER,
    _HTTP_400_INVALID_REQUEST,
    _HTTP_404_NOT_FOUND,
    _HTTP_413_PAYLOAD_TOO_LARGE,
)
_DISPATCH_RESPONSES = _http_responses(
    _HTTP_401_INVALID_BEARER,
    _HTTP_400_INVALID_REQUEST,
    _HTTP_500_INTERNAL,
    _HTTP_502_BAD_GATEWAY,
    _HTTP_504_GATEWAY_TIMEOUT,
)


class ConfigLoadError(RuntimeError):
    """Raised when the control-plane config cannot be loaded safely."""


_APP_ROOT = Path(__file__).resolve().parents[1]


def load_config(path: Path | None = None) -> GateConfig:
    env_path = os.environ.get("ENOCH_CONFIG") or os.environ.get(
        "ENOCH_CONTROL_PLANE_CONFIG"
    )
    config_path = path or (
        Path(env_path).expanduser() if env_path else (_APP_ROOT / "config.example.json")
    )
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
        return GateConfig.model_validate(data)
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        raise ConfigLoadError(f"failed to load config {config_path}: {exc}") from exc


config = load_config()
store = StateStore(config.expanded_state_dir)
telemetry = TelemetryCollector()
gate = WakeGate(config, ProcessTracker(config.expanded_project_root), telemetry)
sender = CallbackSender(config)
reconcile_task: asyncio.Task[None] | None = None


def _log_background_task_exception(
    task: asyncio.Task[None], task_name: str
) -> BaseException | None:
    if task.cancelled():
        return None
    try:
        exc = task.exception()
    except asyncio.CancelledError:
        return None
    if exc is None:
        return None
    _logger.exception("%s task failed", task_name, exc_info=exc)
    capture_exception(exc)
    return exc


def _reconcile_task_done(task: asyncio.Task[None]) -> None:
    global reconcile_task
    exc = _log_background_task_exception(task, "reconcile")
    if exc is None or reconcile_task is not task:
        return
    try:
        reconcile_task = asyncio.create_task(_reconcile_missing_idle_loop())
        reconcile_task.add_done_callback(_reconcile_task_done)
    except RuntimeError as restart_exc:
        _logger.exception("failed to restart reconcile task", exc_info=restart_exc)
        capture_exception(restart_exc)


def _start_reconcile_task() -> asyncio.Task[None]:
    task = asyncio.create_task(_reconcile_missing_idle_loop())
    task.add_done_callback(_reconcile_task_done)
    return task


def _reconcile_task_readiness_error() -> str:
    task = reconcile_task
    if task is None:
        return "reconcile task is not running"
    if task.cancelled():
        return "reconcile task is cancelled"
    if not task.done():
        return ""
    try:
        exc = task.exception()
    except asyncio.CancelledError:
        return "reconcile task is cancelled"
    if exc is None:
        return "reconcile task stopped"
    _logger.warning("reconcile task failed readiness check", exc_info=exc)
    return "reconcile task failed"


def _state_store_readiness_error() -> str:
    try:
        store.check_runs_dir_readable()
    except Exception as exc:
        _logger.warning("state store failed readiness check", exc_info=exc)
        return "state store unavailable"
    return ""


def _readiness_errors() -> list[str]:
    errors = []
    reconcile_error = _reconcile_task_readiness_error()
    if reconcile_error:
        errors.append(reconcile_error)
    store_error = _state_store_readiness_error()
    if store_error:
        errors.append(store_error)
    return errors


@asynccontextmanager
async def lifespan(app: FastAPI):
    global reconcile_task
    # Initialize error tracking if SENTRY_DSN is configured.
    init_sentry()
    # startup logic (replaces deprecated @app.on_event("startup"))
    if reconcile_task is None or reconcile_task.done():
        reconcile_task = _start_reconcile_task()
    try:
        yield
    finally:
        # shutdown logic (replaces deprecated @app.on_event("shutdown"))
        try:
            task = reconcile_task
            task.cancel()
            try:
                results = await asyncio.gather(task, return_exceptions=True)
                if results and isinstance(results[0], Exception):
                    raise results[0]
            finally:
                reconcile_task = None
        finally:
            telemetry.close()


app = FastAPI(title="enoch_worker_gate", version="0.1.0", lifespan=lifespan)

_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "base-uri 'none'; "
        "frame-ancestors 'none'; "
        "form-action 'none'"
    ),
}


@app.middleware("http")
async def _add_security_headers(request: Request, call_next: Any) -> Response:
    response = await call_next(request)
    for name, value in _SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)
    if request.url.scheme == "https":
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
    return response


@app.exception_handler(ControlPlaneHttpError)
async def _control_plane_http_error_handler(
    _request: object, exc: ControlPlaneHttpError
) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


if config.route_observability_enabled:
    route_observation_path = (
        Path(config.route_observability_log_path).expanduser()
        if config.route_observability_log_path
        else config.expanded_state_dir / "route_observations.jsonl"
    )
    app.add_middleware(
        RouteObservationMiddleware,
        observation_path=route_observation_path,
        slow_ms=config.route_observability_slow_ms,
        memory_warn_rss_mib=config.route_observability_memory_warn_rss_mib,
    )

# Profiling middleware: logs cProfile snapshots for requests exceeding 2s.
# Enabled via ENOCH_PROFILING_ENABLED=1 environment variable.
if os.environ.get("ENOCH_PROFILING_ENABLED", "").strip() in ("1", "true"):
    app.add_middleware(
        ProfilingMiddleware,
        profile_threshold_ms=int(
            os.environ.get("ENOCH_PROFILING_THRESHOLD_MS", "2000")
        ),
        enabled=True,
        sample_rate=float(os.environ.get("ENOCH_PROFILING_SAMPLE_RATE", "0.01")),
        log_cooldown_sec=float(
            os.environ.get("ENOCH_PROFILING_LOG_COOLDOWN_SEC", "60")
        ),
    )
evaluation_tasks: dict[str, asyncio.Task] = {}
evaluation_task_started_at: dict[str, float] = {}
evaluation_tasks_lock = threading.Lock()
EVALUATION_TASK_TTL_SECONDS = 24 * 60 * 60


DASHBOARD_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta http-equiv="refresh" content="0; url=/control/dashboard-v2" />
  <title>Enoch Control Plane</title>
</head>
<body>
  <p>Legacy dashboard shell retired. Use <a href="/control/dashboard-v2">Dashboard V2</a>.</p>
  <script>sessionStorage.setItem('enoch-dashboard-redirect', 'dashboard-v2');</script>
</body>
</html>
"""


def _readiness_payload() -> dict[str, Any]:
    errors = _readiness_errors()
    return {
        "ok": not errors,
        "service": "enoch_worker_gate",
        "timestamp": utc_now(),
        "reconcile_task": "running"
        if reconcile_task is not None and not reconcile_task.done()
        else "not_ready",
        "checks": {
            "reconcile_task": not any("reconcile task" in error for error in errors),
            "state_store": not any("state store" in error for error in errors),
        },
        "errors": errors,
    }


@app.get("/livez")
def livez() -> dict[str, Any]:
    return {"ok": True, "service": "enoch_worker_gate", "timestamp": utc_now()}


@app.get("/readyz")
def readyz() -> dict[str, Any]:
    payload = _readiness_payload()
    if not payload["ok"]:
        raise HTTPException(status_code=503, detail=payload)
    return payload


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    return readyz()


def _require_local_bearer(authorization: str | None) -> None:
    expected = f"Bearer {config.control_api_bearer_token}"
    if authorization is None or not hmac.compare_digest(
        authorization.encode("utf-8"), expected.encode("utf-8")
    ):
        raise ControlPlaneHttpError(status_code=401, detail="invalid bearer token")


def _require_dashboard_bearer(
    authorization: str | None, token: str | None = None
) -> None:
    if authorization is None and token:
        raise ControlPlaneHttpError(
            status_code=401,
            detail="dashboard bearer tokens must be sent in the Authorization header",
        )
    _require_local_bearer(authorization)


app.include_router(create_enoch_core_router(config, _require_local_bearer))
app.include_router(create_control_plane_router(config, _require_local_bearer))


def _resolve_under_root(path_str: str, root: Path) -> Path:
    try:
        raw = Path(path_str).expanduser()
    except RuntimeError as exc:
        raise ControlPlaneHttpError(
            status_code=400,
            detail=f"path contains an unexpandable user home: {path_str}",
        ) from exc
    candidate = raw if raw.is_absolute() else root / raw
    try:
        resolved = candidate.resolve()
        root_resolved = root.expanduser().resolve()
    except (OSError, RuntimeError, ValueError) as exc:
        raise ControlPlaneHttpError(
            status_code=400,
            detail=f"path could not be resolved under configured project root: {path_str}",
        ) from exc
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise ControlPlaneHttpError(
            status_code=400, detail=f"path escapes configured project root: {path_str}"
        ) from exc
    return resolved


def _safe_path_for_detail(path: str) -> str:
    name = Path(path).name
    return name if name else "[path]"


def _resolve_write_target(path: Path, root: Path | None = None) -> Path:
    try:
        if root is not None:
            root_resolved = root.resolve(strict=False)
            candidate = path if path.is_absolute() else root_resolved / path
            # Follow existing symlink components before the containment check.  A
            # purely lexical normpath/relative_to check can be bypassed when a
            # directory inside root is a symlink to an outside location.
            resolved = candidate.expanduser().resolve(strict=False)
            resolved.relative_to(root_resolved)
            resolved.parent.relative_to(root_resolved)
            return resolved
    except (OSError, RuntimeError, ValueError) as exc:
        raise ControlPlaneHttpError(
            status_code=400,
            detail=f"write target escapes configured project root: {_safe_path_for_detail(str(path))}",
        ) from exc
    return path


def _write_text(
    path: Path, text: str, overwrite: bool, *, root: Path | None = None
) -> None:
    target = _resolve_write_target(path, root)
    # codeql[py/path-injection] `_resolve_write_target` normalizes the target and,
    # for user-controlled project writes, requires it to remain under the explicit root.
    target.parent.mkdir(parents=True, exist_ok=True)  # codeql[py/path-injection]
    if _checked_exists(target, label="file target") and not overwrite:
        raise ControlPlaneHttpError(
            status_code=409, detail=f"refusing to overwrite existing file: {target}"
        )
    # codeql[py/path-injection] The temporary file is created beside the validated
    # target, and project-write callers pass an explicit root constraint above.
    tmp_fd, tmp_name = tempfile.mkstemp(  # codeql[py/path-injection]
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
    )
    # codeql[py/path-injection] `tmp_name` is returned by `mkstemp`, not supplied by
    # the request, and is only used for cleanup/atomic replacement.
    tmp_path = Path(tmp_name).resolve(strict=False)  # codeql[py/path-injection]
    existing_mode: int | None = None
    try:
        # codeql[py/path-injection] Target has been normalized/root-checked above.
        existing_mode = target.stat().st_mode & 0o777  # codeql[py/path-injection]
    except FileNotFoundError:
        existing_mode = None
    except OSError:
        existing_mode = None
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        tmp_fd = -1
        # codeql[py/path-injection] `tmp_path` was allocated by `mkstemp` and
        # `target` was normalized/root-checked above.
        os.chmod(  # codeql[py/path-injection]
            tmp_path, existing_mode if existing_mode is not None else 0o600
        )
        # codeql[py/path-injection] Atomic replacement is restricted to the
        # validated target path and the `mkstemp`-allocated temporary path.
        os.replace(tmp_path, target)  # codeql[py/path-injection]
    finally:
        if tmp_fd >= 0:
            try:
                os.close(tmp_fd)
            except OSError as exc:
                _logger.debug(
                    "failed to close temporary project artifact fd", exc_info=exc
                )
        try:
            # codeql[py/path-injection] Cleanup only touches the `mkstemp` path.
            if tmp_path.exists():  # codeql[py/path-injection]
                # codeql[py/path-injection] Cleanup only touches the `mkstemp` path.
                tmp_path.unlink()  # codeql[py/path-injection]
        except OSError as exc:
            _logger.debug(
                "failed to remove temporary project artifact file", exc_info=exc
            )


def _checked_path_predicate(
    path: Path,
    *,
    label: str,
    check_name: str,
    status_code: int,
    predicate: Any,
) -> bool:
    try:
        return bool(predicate())
    except (OSError, RuntimeError, ValueError) as exc:
        raise ControlPlaneHttpError(
            status_code=status_code,
            detail=f"{label} could not be inspected during {check_name}",
        ) from exc


def _checked_exists(path: Path, *, label: str, status_code: int = 500) -> bool:
    return _checked_path_predicate(
        path,
        label=label,
        check_name="exists",
        status_code=status_code,
        predicate=path.exists,
    )


def _checked_is_dir(path: Path, *, label: str, status_code: int = 500) -> bool:
    return _checked_path_predicate(
        path,
        label=label,
        check_name="is_dir",
        status_code=status_code,
        predicate=path.is_dir,
    )


def _normalize_prepare_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(metadata or {})
    try:
        workload_class, _ = config.resolve_workload_profile(
            normalized.get("workload_class")
        )
    except ValueError as exc:
        raise ControlPlaneHttpError(status_code=400, detail=str(exc)) from exc
    normalized["workload_class"] = workload_class
    return normalized


def _load_project_metadata(project_dir: Path) -> dict[str, Any]:
    path = project_dir / ENOCH_PROJECT_DIRNAME / PROJECT_JSON_FILENAME
    if not _checked_exists(path, label="project metadata"):
        legacy_path = project_dir / ".omx" / PROJECT_JSON_FILENAME
        if not _checked_exists(legacy_path, label="project metadata"):
            return {}
        path = legacy_path
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, RuntimeError) as exc:
        raise ControlPlaneHttpError(
            status_code=500, detail=f"project metadata could not be read: {path}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise ControlPlaneHttpError(
            status_code=500, detail=f"invalid project metadata JSON: {path}"
        ) from exc
    if not isinstance(payload, dict):
        raise ControlPlaneHttpError(
            status_code=500, detail=f"project metadata must be a JSON object: {path}"
        )
    return payload


def _resolve_workload_profile_for_project_dir(project_dir: Path) -> tuple[str, Any]:
    payload = _load_project_metadata(project_dir)
    metadata = payload.get("metadata")
    if metadata is not None and not isinstance(metadata, dict):
        raise ControlPlaneHttpError(
            status_code=500,
            detail=f"project metadata 'metadata' field must be an object: {project_dir / ENOCH_PROJECT_DIRNAME / PROJECT_JSON_FILENAME}",
        )
    try:
        return config.resolve_workload_profile((metadata or {}).get("workload_class"))
    except ValueError as exc:
        raise ControlPlaneHttpError(status_code=400, detail=str(exc)) from exc


def _assign_record_workload_profile(record: RunRecord) -> RunRecord:
    if record.workload_class and record.workload_profile is not None:
        return record

    project_dir: Path | None = None
    if record.project_dir:
        try:
            project_dir = _resolve_under_root(
                record.project_dir, config.expanded_project_root
            )
        except ControlPlaneHttpError:
            project_dir = None
    elif record.project_id:
        try:
            project_dir = _resolve_under_root(
                record.project_id, config.expanded_project_root
            )
        except ControlPlaneHttpError:
            project_dir = None

    if project_dir is not None:
        workload_class, workload_profile = _resolve_workload_profile_for_project_dir(
            project_dir
        )
        record.project_dir = str(project_dir)
    else:
        workload_class, workload_profile = config.resolve_workload_profile(
            record.workload_class
        )
    record.workload_class = workload_class
    record.workload_profile = workload_profile
    return record


def _wake_decision_profile_evidence(record: RunRecord) -> dict[str, Any]:
    workload_class = record.workload_class or config.normalize_workload_class(None)
    workload_profile = record.workload_profile
    if workload_profile is None:
        workload_class, workload_profile = config.resolve_workload_profile(
            workload_class
        )
    return {
        "workload_class": workload_class,
        "workload_profile_name": workload_class,
        "workload_thresholds": workload_profile.model_dump(),
    }


def _resolve_project_relative_path(project_dir: Path, relative_path: str) -> Path:
    raw = Path(relative_path)
    if raw.is_absolute():
        raise ControlPlaneHttpError(
            status_code=400,
            detail=f"paper artifact path must be relative: {relative_path}",
        )
    if not relative_path.strip():
        raise ControlPlaneHttpError(
            status_code=400, detail="paper artifact path cannot be empty"
        )
    if any(part in {"", ".", ".."} for part in raw.parts):
        raise ControlPlaneHttpError(
            status_code=400,
            detail=f"paper artifact path contains unsafe segment: {relative_path}",
        )

    try:
        resolved = (project_dir / raw).resolve()
        project_root = project_dir.resolve()
    except (OSError, RuntimeError, ValueError) as exc:
        raise ControlPlaneHttpError(
            status_code=400,
            detail=f"paper artifact path could not be resolved: {relative_path}",
        ) from exc
    try:
        resolved.relative_to(project_root)
    except ValueError as exc:
        raise ControlPlaneHttpError(
            status_code=400,
            detail=f"paper artifact path escapes {PROJECT_DIRECTORY_LABEL}: {relative_path}",
        ) from exc
    return resolved


def _read_project_paper_artifact_entry(
    project_dir: Path,
    relative_path: str,
    *,
    max_bytes: int,
    too_large_detail: str | None = None,
) -> dict[str, Any]:
    path = _resolve_project_relative_path(project_dir, relative_path)
    safe_relative_path = _safe_path_for_detail(relative_path)
    if path.suffix.lower() not in PAPER_ARTIFACT_ALLOWED_SUFFIXES:
        raise HTTPException(
            status_code=415,
            detail=f"paper artifact extension not allowed: {safe_relative_path}",
        )
    try:
        artifact_exists = path.exists() and path.is_file()
    except OSError as exc:
        raise HTTPException(
            status_code=403,
            detail=f"paper artifact is not readable: {safe_relative_path}",
        ) from exc
    if not artifact_exists:
        raise HTTPException(
            status_code=404, detail=f"paper artifact not found: {safe_relative_path}"
        )
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise HTTPException(
            status_code=403,
            detail=f"paper artifact is not readable: {safe_relative_path}",
        ) from exc
    if size > max_bytes:
        detail = too_large_detail or (
            f"paper artifact too large to read: {safe_relative_path}"
        )
        raise HTTPException(status_code=413, detail=detail)
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise HTTPException(
            status_code=403,
            detail=f"paper artifact is not readable: {safe_relative_path}",
        ) from exc
    except UnicodeDecodeError as exc:
        raise HTTPException(
            status_code=415,
            detail=f"paper artifact is not UTF-8 text: {safe_relative_path}",
        ) from exc
    return {
        "path": path.relative_to(project_dir).as_posix(),
        "bytes": size,
        "content": content,
    }


def _validate_paper_artifact_read_request(request: PaperArtifactReadRequest) -> None:
    if len(request.paths) > 20:
        raise HTTPException(
            status_code=400, detail="too many paper artifact paths; max 20"
        )
    if request.max_bytes_per_file < 1 or request.max_bytes_per_file > 2_000_000:
        raise HTTPException(
            status_code=400, detail="max_bytes_per_file must be between 1 and 2000000"
        )


def _find_run_record(project_id: str, run_id: str | None = None) -> RunRecord | None:
    if run_id:
        record = store.load_run(run_id)
        if record is not None:
            return record

    candidates = [
        record for record in store.list_runs() if record.project_id == project_id
    ]
    if not candidates:
        return None
    candidates.sort(
        key=lambda record: (
            record.updated_at or "",
            record.last_event_at or "",
            record.created_at or "",
        ),
        reverse=True,
    )
    return candidates[0]


def _resolve_project_dir(project_id: str, project_dir: str | None) -> Path:
    if project_dir:
        return _resolve_under_root(project_dir, config.expanded_project_root)
    return _resolve_under_root(project_id, config.expanded_project_root)


def _safe_read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"decision file not found: {path}") from exc
    except (OSError, RuntimeError) as exc:
        raise ValueError(f"decision file could not be read: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in decision file: {path}") from exc


_PROJECT_DECISION_ACTIONS = frozenset(
    {
        "continue",
        "finalize_negative",
        "finalize_positive",
        "branch_new_project",
        "blocked",
        "needs_review",
    }
)
_HYPOTHESIS_STATUSES = frozenset({"supported", "unsupported", "mixed", "inconclusive"})
_CONFIDENCE_LEVELS = frozenset({"low", "medium", "high"})
_EVIDENCE_STRENGTHS = frozenset({"weak", "moderate", "strong"})
_FOLLOWUP_TYPES = frozenset({"", "deepen", "branch", "retry"})


def _coerce_member_or_default(
    value: Any, *, default: str, allowed: frozenset[str]
) -> str:
    text = str(value or default).strip() or default
    return text if text in allowed else default


def _coerce_project_decision_action(raw: dict[str, Any]) -> str:
    action = str(raw.get("project_decision") or raw.get("decision") or "").strip()
    if action not in _PROJECT_DECISION_ACTIONS:
        raise ValueError(f"unsupported project decision: {action or '<missing>'}")
    return action


def _coerce_followup_type(raw: dict[str, Any]) -> str:
    followup_type = (
        str(raw.get("followup_type") or "").strip().lower().replace("-", "_")
    )
    return followup_type if followup_type in _FOLLOWUP_TYPES else ""


def _coerce_followup_required_evidence(raw_required: Any) -> list[str]:
    if isinstance(raw_required, list):
        return [
            part
            for item in raw_required
            for part in split_numbered_list_text(str(item))
            if part
        ]
    if isinstance(raw_required, str):
        return split_numbered_list_text(raw_required)
    return []


def _coerce_project_decision(
    raw: dict[str, Any], source: str, source_path: Path | None = None
) -> ProjectDecision:
    action = _coerce_project_decision_action(raw)
    hypothesis_status = _coerce_member_or_default(
        raw.get("hypothesis_status"),
        default="inconclusive",
        allowed=_HYPOTHESIS_STATUSES,
    )
    confidence = _coerce_member_or_default(
        raw.get("confidence"), default="medium", allowed=_CONFIDENCE_LEVELS
    )
    evidence_strength = _coerce_member_or_default(
        raw.get("evidence_strength"),
        default="moderate",
        allowed=_EVIDENCE_STRENGTHS,
    )
    raw_followup_type = _coerce_followup_type(raw)
    followup_required_evidence = _coerce_followup_required_evidence(
        raw.get("followup_required_evidence")
    )

    return ProjectDecision(
        project_decision=action,
        hypothesis_status=hypothesis_status,
        confidence=confidence,
        evidence_strength=evidence_strength,
        novelty_progress=bool(raw.get("novelty_progress", False)),
        results_changed=bool(raw.get("results_changed", False)),
        recommended_next_action=str(raw.get("recommended_next_action") or "").strip(),
        stop_reason=str(raw.get("stop_reason") or "").strip(),
        branch_project_name=str(raw.get("branch_project_name") or "").strip() or None,
        branch_reason=str(raw.get("branch_reason") or "").strip() or None,
        followup_recommended=bool(raw.get("followup_recommended", False)),
        followup_type=raw_followup_type,
        followup_title=str(raw.get("followup_title") or "").strip(),
        followup_hypothesis=str(raw.get("followup_hypothesis") or "").strip(),
        followup_required_evidence=followup_required_evidence,
        followup_success_threshold=str(
            raw.get("followup_success_threshold") or ""
        ).strip(),
        followup_stop_condition=str(raw.get("followup_stop_condition") or "").strip(),
        decision_source=source,
        source_path=source_path.as_posix() if source_path else None,
        updated_at=str(
            raw.get("updated_at")
            or raw.get("generated_at")
            or raw.get("prepared_at")
            or utc_now()
        ),
    )


def _project_decision_from_summary(
    summary: dict[str, Any], source_path: Path
) -> ProjectDecision:
    native = (
        summary.get("native_phase")
        if isinstance(summary.get("native_phase"), dict)
        else {}
    )
    alternative = (
        summary.get("alternative_deployment_branch")
        if isinstance(summary.get("alternative_deployment_branch"), dict)
        else {}
    )
    recommendation = str(summary.get("recommendation") or "").strip()
    native_kill = str(native.get("kill_condition_status") or "").strip()
    alternative_status = str(alternative.get("status") or "").strip()

    action = "continue"
    hypothesis_status = "inconclusive"
    confidence = "medium"
    evidence_strength = "moderate"
    stop_reason = ""
    branch_project_name = None
    branch_reason = None

    if native_kill == "supported" or "falsified" in recommendation.lower():
        action = "finalize_negative"
        hypothesis_status = "unsupported"
        confidence = "high"
        evidence_strength = "strong"
        stop_reason = "Static selective up-precision thesis is falsified on the current native evidence."
        if alternative_status.startswith("supported"):
            branch_project_name = "Bonsai-Up Profile Variation Branch"
            branch_reason = "Profile variation appears promising but should be treated as a separate project from the falsified static-mask thesis."
    elif alternative_status.startswith("supported"):
        action = "branch_new_project"
        hypothesis_status = "mixed"
        confidence = "medium"
        evidence_strength = "moderate"
        stop_reason = "A different profile-variation mechanism looks promising enough to split into its own project."
        branch_project_name = "Bonsai-Up Profile Variation Branch"
        branch_reason = "Alternative deployment branch cleared cost-normalized support while the original thesis remained mixed."

    return ProjectDecision(
        project_decision=action,
        hypothesis_status=hypothesis_status,
        confidence=confidence,
        evidence_strength=evidence_strength,
        novelty_progress=False,
        results_changed=True,
        recommended_next_action=recommendation,
        stop_reason=stop_reason or recommendation,
        branch_project_name=branch_project_name,
        branch_reason=branch_reason,
        decision_source="summary_fallback",
        source_path=source_path.as_posix(),
        updated_at=utc_now(),
    )


def _load_project_decision(
    project_dir: Path,
    *,
    include_summary_fallback: bool = True,
) -> tuple[ProjectDecision | None, str | None]:
    for explicit_path in (
        project_dir / ENOCH_PROJECT_DIRNAME / "project_decision.json",
        project_dir / ".omx" / "project_decision.json",
    ):
        try:
            explicit_exists = explicit_path.exists()
        except (OSError, RuntimeError, ValueError):
            return (
                None,
                f"project decision file could not be inspected: {explicit_path}",
            )
        if explicit_exists:
            try:
                return _coerce_project_decision(
                    _safe_read_json(explicit_path), "codex_turn", explicit_path
                ), None
            except ValueError as exc:
                return None, str(exc)

    if not include_summary_fallback:
        return None, None

    try:
        summary_candidates = sorted(
            project_dir.glob("results/**/project_decision_summary/summary.json")
        )
    except (OSError, RuntimeError, ValueError) as exc:
        return None, f"project decision summary files could not be listed: {exc}"
    for candidate in summary_candidates:
        try:
            return _project_decision_from_summary(
                _safe_read_json(candidate), candidate
            ), None
        except ValueError as exc:
            return None, str(exc)

    return None, None


def _tail_lines(path: Path, limit: int = 30) -> list[str]:
    try:
        if not path.exists() or not path.is_file():
            return []
    except (OSError, RuntimeError, ValueError):
        return []
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as handle:
            lines = [line.rstrip() for line in deque(handle, maxlen=limit)]
    except OSError:
        return []
    return [line for line in lines if line.strip()]


_RECENT_FILES_IGNORE_DIRS = frozenset(
    {
        ".venv",
        ".git",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "node_modules",
        "dist",
        "build",
        ".tox",
    }
)
_RECENT_FILES_IGNORED_ROOTS: tuple[tuple[str, ...], ...] = (
    ("results",),
    ("artifacts",),
    (ENOCH_PROJECT_DIRNAME, "state"),
    (ENOCH_PROJECT_DIRNAME, "logs"),
    (".omx", "state"),  # legacy compatibility
    (".omx", "logs"),  # legacy compatibility
)


def _recent_files_rel_root(root_path: Path, project_dir: Path) -> Path | None:
    try:
        return root_path.relative_to(project_dir)
    except ValueError:
        return None


def _recent_files_skip_directory(rel_root: Path) -> bool:
    if any(part in _RECENT_FILES_IGNORE_DIRS for part in rel_root.parts):
        return True
    return any(
        rel_root.parts[: len(parts)] == parts for parts in _RECENT_FILES_IGNORED_ROOTS
    )


def _recent_files_prune_dirs(dirs: list[str]) -> None:
    dirs[:] = [
        directory for directory in dirs if directory not in _RECENT_FILES_IGNORE_DIRS
    ]


def _recent_files_stat_mtime(
    root_path: Path, filename: str, project_dir: Path
) -> tuple[float, str] | None:
    path = root_path / filename
    try:
        stat = path.stat()
        rel_path = path.relative_to(project_dir)
    except (OSError, RuntimeError, ValueError):
        return None
    return (stat.st_mtime, f"{rel_path}")


def _recent_files_heap_add(
    collected: list[tuple[float, str]],
    *,
    limit: int,
    mtime: float,
    rel_path: str,
) -> None:
    entry = (mtime, rel_path)
    if len(collected) < limit:
        heapq.heappush(collected, entry)
    else:
        heapq.heappushpop(collected, entry)


def _recent_files_scan_should_stop(
    scanned: int, max_entries: int, deadline: float, *, inclusive_cap: bool
) -> bool:
    at_cap = scanned >= max_entries if inclusive_cap else scanned > max_entries
    return at_cap or time.monotonic() > deadline


def _recent_files_scan_directory_files(
    collected: list[tuple[float, str]],
    *,
    root_path: Path,
    files: list[str],
    project_dir: Path,
    limit: int,
    max_entries: int,
    deadline: float,
    scanned: int,
) -> int:
    for filename in files:
        scanned += 1
        if _recent_files_scan_should_stop(
            scanned, max_entries, deadline, inclusive_cap=False
        ):
            break
        entry = _recent_files_stat_mtime(root_path, filename, project_dir)
        if entry is None:
            continue
        _recent_files_heap_add(
            collected, limit=limit, mtime=entry[0], rel_path=entry[1]
        )
    return scanned


def _recent_files_scan(
    project_dir: Path,
    *,
    limit: int,
    max_entries: int,
    max_seconds: float,
) -> list[tuple[float, str]]:
    collected: list[tuple[float, str]] = []
    scanned = 0
    deadline = time.monotonic() + max_seconds
    walker = os.walk(project_dir, onerror=lambda _exc: None)
    for root, dirs, files in walker:
        if _recent_files_scan_should_stop(
            scanned, max_entries, deadline, inclusive_cap=True
        ):
            break
        root_path = Path(root)
        rel_root = _recent_files_rel_root(root_path, project_dir)
        if rel_root is None:
            continue
        if _recent_files_skip_directory(rel_root):
            dirs[:] = []
            continue
        _recent_files_prune_dirs(dirs)
        scanned = _recent_files_scan_directory_files(
            collected,
            root_path=root_path,
            files=files,
            project_dir=project_dir,
            limit=limit,
            max_entries=max_entries,
            deadline=deadline,
            scanned=scanned,
        )
    return collected


def _recent_files(
    project_dir: Path,
    limit: int = 12,
    *,
    max_entries: int = 2_500,
    max_seconds: float = 0.35,
) -> list[str]:
    try:
        collected = _recent_files_scan(
            project_dir,
            limit=limit,
            max_entries=max_entries,
            max_seconds=max_seconds,
        )
    except (OSError, RuntimeError, ValueError):
        return []
    return [
        f"{Path(path).as_posix()}"
        for _, path in sorted(collected, key=lambda item: item[0], reverse=True)
    ]


_RESULT_FOLDER_NAMES = ("results", "artifacts")
_RESULT_WALK_SKIP_DIRS = frozenset(
    {".git", "__pycache__", ".mypy_cache", ".pytest_cache"}
)


def _push_mtime_heap_entry(
    collected: list[tuple[float, str]],
    limit: int,
    entry: tuple[float, str],
) -> None:
    if len(collected) < limit:
        heapq.heappush(collected, entry)
    else:
        heapq.heappushpop(collected, entry)


def _result_file_mtime_entry(path: Path, project_dir: Path) -> tuple[float, str] | None:
    try:
        if not path.is_file():
            return None
        stat = path.stat()
        return (stat.st_mtime, path.relative_to(project_dir).as_posix())
    except (OSError, RuntimeError, ValueError):
        return None


def _collect_result_files_in_folder(
    folder_root: Path,
    project_dir: Path,
    collected: list[tuple[float, str]],
    *,
    limit: int,
    scanned: int,
    deadline: float,
    max_entries: int,
) -> int:
    try:
        walker = os.walk(folder_root, onerror=lambda _exc: None)
        for current_root, dirs, files in walker:
            if scanned >= max_entries or time.monotonic() > deadline:
                break
            dirs[:] = [
                directory
                for directory in dirs
                if directory not in _RESULT_WALK_SKIP_DIRS
            ]
            for filename in files:
                scanned += 1
                if scanned > max_entries or time.monotonic() > deadline:
                    break
                entry = _result_file_mtime_entry(
                    Path(current_root) / filename, project_dir
                )
                if entry is not None:
                    _push_mtime_heap_entry(collected, limit, entry)
    except (OSError, RuntimeError, ValueError):
        return scanned
    return scanned


def _result_files(
    project_dir: Path,
    limit: int = 20,
    *,
    max_entries: int = 2_500,
    max_seconds: float = 0.35,
) -> list[str]:
    collected: list[tuple[float, str]] = []
    scanned = 0
    deadline = time.monotonic() + max_seconds
    for folder_name in _RESULT_FOLDER_NAMES:
        root = project_dir / folder_name
        if not _path_exists(root):
            continue
        scanned = _collect_result_files_in_folder(
            root,
            project_dir,
            collected,
            limit=limit,
            scanned=scanned,
            deadline=deadline,
            max_entries=max_entries,
        )
        if scanned >= max_entries or time.monotonic() > deadline:
            break
    return [
        path for _, path in sorted(collected, key=lambda item: item[0], reverse=True)
    ]


def _path_exists(path: Path) -> bool:
    try:
        return path.exists()
    except (OSError, RuntimeError, ValueError):
        return False


def _tail_jsonl(path: Path, limit: int = 80) -> list[str]:
    if not _path_exists(path):
        return []
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as handle:
            return [line.rstrip("\n") for line in deque(handle, maxlen=limit)]
    except OSError:
        return []


def _latest_session(project_dir: Path) -> SessionHistoryEntry | None:
    history_path = (
        project_dir / ENOCH_PROJECT_DIRNAME / "logs" / "session-history.jsonl"
    )
    history_exists = _path_exists(history_path)
    if not history_exists:
        legacy_history_path = project_dir / ".omx" / "logs" / "session-history.jsonl"
        legacy_exists = _path_exists(legacy_history_path)
        if not legacy_exists:
            return None
        history_path = legacy_history_path
    latest: dict[str, Any] | None = None
    try:
        for line in history_path.read_text(
            encoding="utf-8", errors="ignore"
        ).splitlines():
            line = line.strip()
            if not line:
                continue
            latest = json.loads(line)
    except (OSError, json.JSONDecodeError):
        return None
    if latest is None:
        return None
    return SessionHistoryEntry.model_validate(latest)


def _activity_from_processes(
    processes: list[ProcessInfo], gate_state: str | None
) -> str:
    if not processes:
        return gate_state or "idle"

    preferred: ProcessInfo | None = None
    for process in processes:
        cmd = process.cmdline
        if any(
            marker in cmd
            for marker in (
                "notify-fallback",
                "notify-hook",
                "/bin/codex exec",
                "/usr/bin/codex exec",
            )
        ):
            continue
        if cmd.strip() in {
            "-bash",
            "bash",
            "-sh",
            "sh",
            "-zsh",
            "zsh",
            "fish",
            "-fish",
            "jq",
        } or cmd.startswith("tail -f "):
            continue
        preferred = process
        break
    preferred = preferred or processes[0]
    cmd = preferred.cmdline.strip()
    if len(cmd) > 160:
        cmd = cmd[:157] + "..."
    return f"running {cmd}" if cmd else (gate_state or "running")


def _read_recent_events(limit: int = 80) -> list[dict[str, Any]]:
    if not _path_exists(store.events_log):
        return []

    events: list[dict[str, Any]] = []
    for line in reversed(_tail_jsonl(store.events_log, max(limit * 8, limit, 80))):
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            event = {"kind": "unparseable_event", "raw": line}
        events.append(event)
        if len(events) >= limit:
            break
    return events


def _truncate(value: str | None, max_chars: int) -> str:
    text = value or ""
    if len(text) <= max_chars:
        return text
    return text[: max(0, max_chars - 20)].rstrip() + "\n[truncated]"


def _redact_stack_trace_text(value: str) -> str:
    lines = value.splitlines()
    if any(_TRACEBACK_LINE.search(line) for line in lines):
        return "[stack trace redacted]"
    return value


def _sanitize_dashboard_value(value: Any) -> Any:
    if isinstance(value, str):
        return _redact_stack_trace_text(value)
    if isinstance(value, list):
        return [_sanitize_dashboard_value(item) for item in value]
    if isinstance(value, dict):
        return {
            str(key): _sanitize_dashboard_value(item) for key, item in value.items()
        }
    return value


def _trim_event(event: dict[str, Any], max_chars: int = 1600) -> dict[str, Any]:
    event = _sanitize_dashboard_value(event)
    encoded = json.dumps(event, sort_keys=True)
    if len(encoded) <= max_chars:
        return event
    trimmed = {
        key: event.get(key)
        for key in (
            "kind",
            "event",
            "event_type",
            "run_id",
            "session_id",
            "project_id",
            "ok",
            "timestamp",
        )
        if key in event
    }
    trimmed["truncated"] = True
    return trimmed


def _parse_timestamp(value: str | None) -> datetime | None:
    return parse_utc_datetime(value)


def _record_age_seconds(record: RunRecord) -> float | None:
    parsed = _parse_timestamp(
        record.updated_at or record.last_event_at or record.created_at
    )
    if parsed is None:
        return None
    return (datetime.now(timezone.utc) - parsed).total_seconds()


def _callback_delivered(record: RunRecord) -> bool:
    if record.gate_state not in {GateState.WAKE_READY, GateState.FINISHED_READY}:
        return False
    if not record.last_idempotency_key:
        return False
    delivered_events = {"wake_ready", "session_finished_ready"}
    parts = record.last_idempotency_key.split(":")
    return (
        len(parts) >= 3 and parts[0] == record.run_id and parts[1] in delivered_events
    )


def _ready_callback_for_retry(record: RunRecord) -> GateCallback | None:
    if _callback_delivered(record):
        return None
    if record.gate_state == GateState.WAKE_READY:
        event_type = "wake_ready"
        reason = "retry_codex_idle_and_system_quiet"
    elif record.gate_state == GateState.FINISHED_READY:
        event_type = "session_finished_ready"
        reason = "retry_session_ended_and_system_quiet"
    else:
        return None
    idempotency_key = (
        f"{record.run_id}:{event_type}:{record.idle_seen_at or record.last_event_at}"
    )
    return GateCallback(
        event_type=event_type,
        run_id=record.run_id,
        session_id=record.session_id,
        project_id=record.project_id,
        project_name=record.project_name,
        source_event=(record.last_event.value if record.last_event else "unknown"),
        gate_state=record.gate_state.value,
        idle_seen_at=record.idle_seen_at,
        process_tracking=gate.process_tracker.snapshot(record, []),
        telemetry={"retry": True, "reason": reason},
        reason=reason,
        idempotency_key=idempotency_key,
    )


def _dashboard_record_sort_priority(truth: dict[str, Any]) -> int:
    if truth["is_live"]:
        return 0
    if truth["needs_attention"]:
        return 1
    return 2


def _dashboard_operator_view(
    record: RunRecord,
    active_processes: list[ProcessInfo],
    *,
    superseded: bool,
    stale_callback: bool,
    delivered: bool,
) -> tuple[str, str, str, bool, bool]:
    state = record.gate_state
    if active_processes or (state == GateState.RUNNING and not superseded):
        return (
            "active",
            "Active",
            "Codex or project-owned processes are still running.",
            True,
            False,
        )
    if superseded:
        return (
            "superseded",
            "Superseded",
            "A newer run exists for this project; this older record is historical evidence, not current attention.",
            False,
            False,
        )
    if state == GateState.QUESTION_PENDING:
        return (
            "question_pending",
            "Question pending",
            "Codex asked for input; this is a real operator hold.",
            True,
            True,
        )
    if state == GateState.ERROR:
        return (
            "attention",
            "Attention",
            "Wake-gate recorded an error for this run.",
            False,
            True,
        )
    if stale_callback:
        return (
            "stale_callback_ready",
            "Stale callback",
            "Wake-gate reached callback-ready but has no delivered idempotency key; inspect or reconcile.",
            False,
            True,
        )
    if state in {GateState.WAKE_READY, GateState.FINISHED_READY} and not delivered:
        return (
            "callback_pending",
            "Callback pending",
            "Wake-gate is ready and waiting for callback delivery confirmation.",
            True,
            False,
        )
    if delivered:
        lifecycle = (
            "callback_delivered"
            if state == GateState.WAKE_READY
            else "finished_delivered"
        )
        return (
            lifecycle,
            "Delivered",
            "The configured completion callback accepted the wake/finish event; this is historical evidence, not live work.",
            False,
            False,
        )
    if state in {
        GateState.PENDING_IDLE_GATE,
        GateState.WAITING_FOR_PROCESS_EXIT,
        GateState.WAITING_FOR_QUIET_WINDOW,
        GateState.FINISHED_PENDING_GATE,
    }:
        return (
            "settling",
            "Settling",
            "Wake-gate is waiting for process-exit or quiet-window evidence.",
            True,
            False,
        )
    return (
        "historical",
        "Historical",
        "Inactive historical run record.",
        False,
        False,
    )


def _dashboard_truth(
    record: RunRecord,
    active_processes: list[ProcessInfo],
    *,
    superseded: bool = False,
) -> dict[str, Any]:
    state = record.gate_state
    delivered = _callback_delivered(record)
    age_seconds = _record_age_seconds(record)
    stale_seconds = max(
        config.idle_sustain_sec * 2, config.sample_interval_sec * 12, 300
    )
    stale_callback = (
        state in {GateState.WAKE_READY, GateState.FINISHED_READY}
        and not delivered
        and age_seconds is not None
        and age_seconds > stale_seconds
    )
    lifecycle, status, detail, is_live, needs_attention = _dashboard_operator_view(
        record,
        active_processes,
        superseded=superseded,
        stale_callback=stale_callback,
        delivered=delivered,
    )

    return {
        "lifecycle_state": lifecycle,
        "operator_status": status,
        "operator_status_detail": detail,
        "callback_delivered": delivered,
        "is_live": is_live,
        "needs_attention": needs_attention,
        "is_historical": not is_live and not needs_attention,
        "age_seconds": age_seconds,
    }


def _latest_runs_by_project(records: list[RunRecord]) -> dict[str, RunRecord]:
    latest_by_project: dict[str, RunRecord] = {}
    for record in records:
        if not record.project_id:
            continue
        latest = latest_by_project.get(record.project_id)
        if latest is None or (
            record.updated_at or "",
            record.last_event_at or "",
            record.created_at or "",
        ) > (
            latest.updated_at or "",
            latest.last_event_at or "",
            latest.created_at or "",
        ):
            latest_by_project[record.project_id] = record
    return latest_by_project


def _is_superseded_record(
    record: RunRecord, latest_by_project: dict[str, RunRecord]
) -> bool:
    if not record.project_id:
        return False
    latest = latest_by_project.get(record.project_id)
    return latest is not None and latest.run_id != record.run_id


_RUN_DASHBOARD_PROCESS_STATES = {
    GateState.RUNNING,
    GateState.PENDING_IDLE_GATE,
    GateState.WAITING_FOR_PROCESS_EXIT,
    GateState.WAITING_FOR_QUIET_WINDOW,
    GateState.FINISHED_PENDING_GATE,
}


def _resolve_run_project_dir(record: RunRecord) -> Path | None:
    if not record.project_dir:
        return None
    try:
        return _resolve_under_root(record.project_dir, config.expanded_project_root)
    except ControlPlaneHttpError:
        return None


def _run_dashboard_active_processes(
    record: RunRecord, *, detail: bool
) -> list[ProcessInfo]:
    if detail or record.gate_state in _RUN_DASHBOARD_PROCESS_STATES:
        return gate.process_tracker.describe_processes(record)
    return []


def _run_dashboard_project_context(
    project_dir: Path | None, *, detail: bool
) -> tuple[
    SessionHistoryEntry | None,
    ProjectDecision | None,
    str | None,
    list[str],
    list[str],
    list[str],
]:
    if project_dir is None or not project_dir.exists():
        return None, None, None, [], [], []

    run_notes_tail = _tail_lines(
        project_dir / "run_notes.md", limit=30 if detail else 8
    )
    recent_files: list[str] = []
    result_files: list[str] = []
    if detail:
        recent_files = _recent_files(
            project_dir, limit=30, max_entries=6_000, max_seconds=0.9
        )
        result_files = _result_files(
            project_dir, limit=50, max_entries=6_000, max_seconds=0.9
        )
    project_decision, decision_error = _load_project_decision(
        project_dir,
        include_summary_fallback=detail,
    )
    latest_session = _latest_session(project_dir) if detail else None
    return (
        latest_session,
        project_decision,
        decision_error,
        run_notes_tail,
        recent_files,
        result_files,
    )


def _run_dashboard_item(
    record: RunRecord,
    *,
    detail: bool = False,
    superseded: bool = False,
) -> dict[str, Any]:
    active_processes = _run_dashboard_active_processes(record, detail=detail)
    project_dir = _resolve_run_project_dir(record)
    (
        latest_session,
        project_decision,
        decision_error,
        run_notes_tail,
        recent_files,
        result_files,
    ) = _run_dashboard_project_context(project_dir, detail=detail)

    truth = _dashboard_truth(record, active_processes, superseded=superseded)
    current_activity = _activity_from_processes(
        active_processes, record.gate_state.value
    )
    if not active_processes:
        current_activity = truth["operator_status_detail"]

    return {
        "run_id": record.run_id,
        "session_id": record.session_id,
        "project_id": record.project_id,
        "project_name": record.project_name,
        "project_dir": record.project_dir,
        "gate_state": record.gate_state.value,
        **truth,
        "current_activity": current_activity,
        "root_pid": record.root_pid,
        "process_group_id": record.process_group_id,
        "active_process_count": len(active_processes),
        "active_processes": [
            process.model_dump()
            for process in (active_processes if detail else active_processes[:8])
        ],
        "active_processes_truncated": (not detail and len(active_processes) > 8),
        "baseline_vram_mib": record.baseline_vram_mib,
        "idle_seen_at": record.idle_seen_at,
        "last_event": record.last_event.value if record.last_event else None,
        "last_event_at": record.last_event_at,
        "last_idempotency_key": record.last_idempotency_key,
        "quiet_samples": [
            sample.model_dump()
            for sample in record.quiet_samples[-(24 if detail else 6) :]
        ],
        "created_at": record.created_at,
        "updated_at": record.updated_at,
        "latest_session": latest_session.model_dump() if latest_session else None,
        "project_decision": project_decision.model_dump() if project_decision else None,
        "decision_error": decision_error,
        "run_notes_tail": [
            _truncate(_redact_stack_trace_text(line), 900 if detail else 360)
            for line in run_notes_tail
        ],
        "recent_files": recent_files,
        "result_files": result_files,
    }


@app.get("/dashboard", include_in_schema=False)
def dashboard() -> RedirectResponse:
    return RedirectResponse(url="/control/dashboard-v2", status_code=307)


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> Response:
    return Response(status_code=204)


def _queue_snapshot_path() -> Path:
    return config.expanded_state_dir / "queue_snapshot.json"


def _read_queue_snapshot() -> dict[str, Any]:
    path = _queue_snapshot_path()
    if not _path_exists(path):
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _snapshot_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


_MAX_QUEUE_SNAPSHOT_WARNINGS = 50
_MAX_QUEUE_SNAPSHOT_WARNING_CHARS = 500


def _snapshot_warnings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    warnings = [
        _truncate(str(item), _MAX_QUEUE_SNAPSHOT_WARNING_CHARS)
        for item in value[:_MAX_QUEUE_SNAPSHOT_WARNINGS]
    ]
    if len(value) > _MAX_QUEUE_SNAPSHOT_WARNINGS:
        warnings[-1:] = [
            f"{len(value) - _MAX_QUEUE_SNAPSHOT_WARNINGS + 1} additional warnings omitted"
        ]
    return warnings


def _queue_row_summary(row: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "project_id",
        "project_name",
        "notion_page_url",
        "project_dir",
        "current_run_id",
        "run_id",
        "status",
        "queue_status",
        "last_run_state",
        "run_state",
        "next_action_hint",
        "blocked_reason",
        "manual_review_required",
        "last_result_summary",
        "created_at",
        "updated_at",
    )
    summarized = {key: _truncate(str(row.get(key) or ""), 2000) for key in keys}
    summarized["queue_status"] = (
        summarized.get("queue_status") or summarized.get("status") or "unknown"
    )
    summarized["last_run_state"] = (
        summarized.get("last_run_state")
        or summarized.get("run_state")
        or summarized.get("next_action_hint")
        or "unknown"
    )
    return summarized


def _count_queue_field(rows: list[dict[str, Any]], field: str) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for row in rows:
        key = str(row.get(field) or "unknown").strip() or "unknown"
        counts[key] += 1
    return dict(sorted(counts.items()))


def _build_queue_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    raw_rows = (
        payload.get("rows")
        if isinstance(payload.get("rows"), list)
        else payload.get("queue_rows")
    )
    rows = (
        [_queue_row_summary(row) for row in raw_rows[:250] if isinstance(row, dict)]
        if isinstance(raw_rows, list)
        else []
    )
    rows.sort(
        key=lambda row: row.get("updated_at") or row.get("created_at") or "",
        reverse=True,
    )

    status_counts = (
        payload.get("status_counts")
        if isinstance(payload.get("status_counts"), dict)
        else _count_queue_field(rows, "queue_status")
    )
    run_state_counts = (
        payload.get("run_state_counts")
        if isinstance(payload.get("run_state_counts"), dict)
        else _count_queue_field(rows, "last_run_state")
    )

    active_statuses = {
        "dispatching",
        "awaiting_wake",
        "running",
        "wake_received",
        "reconciling",
    }
    active_rows = (
        payload.get("active_rows")
        if isinstance(payload.get("active_rows"), list)
        else [
            row
            for row in rows
            if (row.get("queue_status") or row.get("status")) in active_statuses
        ]
    )
    blocked_rows = (
        payload.get("blocked_rows")
        if isinstance(payload.get("blocked_rows"), list)
        else [
            row
            for row in rows
            if row.get("queue_status") == "blocked"
            or row.get("last_run_state") in {"blocked", "needs_review"}
        ]
    )
    total = _snapshot_int(payload.get("total"), len(rows))
    valid_projects = _snapshot_int(payload.get("valid_projects"), total)

    return {
        "updated_at": utc_now(),
        "source": str(payload.get("source") or "unknown"),
        "total": total,
        "valid_projects": valid_projects,
        "status_counts": status_counts,
        "run_state_counts": run_state_counts,
        "blocked_rows": blocked_rows,
        "active_rows": active_rows,
        "active_count": sum(
            _snapshot_int(status_counts.get(status)) for status in active_statuses
        )
        or len(active_rows),
        "blocked_count": _snapshot_int(status_counts.get("blocked"), len(blocked_rows)),
        "queued_count": _snapshot_int(status_counts.get("queued")),
        "completed_count": _snapshot_int(status_counts.get("completed")),
        "positive_count": _snapshot_int(run_state_counts.get("finalize_positive")),
        "negative_count": _snapshot_int(run_state_counts.get("finalize_negative")),
        "branch_count": _snapshot_int(run_state_counts.get("branch_new_project"))
        + _snapshot_int(run_state_counts.get("branch_queued")),
        "draft_candidate_count": _snapshot_int(payload.get("draft_candidate_count")),
        "polish_candidate_count": _snapshot_int(payload.get("polish_candidate_count")),
        "warnings": _snapshot_warnings(payload.get("warnings")),
        "rows": rows,
    }


@app.post("/dashboard/queue-snapshot", responses=_DASHBOARD_SNAPSHOT_RESPONSES)
def dashboard_queue_snapshot(
    payload: dict[str, Any],
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, Any]:
    _require_local_bearer(authorization)
    snapshot = _build_queue_snapshot(payload)
    path = _queue_snapshot_path()
    _write_text(
        path, json.dumps(snapshot, indent=2, sort_keys=True) + "\n", overwrite=True
    )
    return {"ok": True, "queue_snapshot": snapshot}


def _paper_snapshot_path() -> Path:
    return config.expanded_state_dir / "paper_snapshot.json"


def _read_paper_snapshot() -> dict[str, Any]:
    path = _paper_snapshot_path()
    if not _path_exists(path):
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _clean_snapshot_text(value: Any, max_chars: int = 2000) -> str:
    text = str(value or "").strip()
    if len(text) <= max_chars:
        return text
    return text[: max(0, max_chars - 15)].rstrip() + "\n[truncated]"


def _paper_row_summary(row: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "paper_id",
        "project_id",
        "project_name",
        "run_id",
        "session_id",
        "notion_page_url",
        "project_dir",
        "paper_status",
        "paper_type",
        "draft_markdown_path",
        "draft_latex_path",
        "evidence_bundle_path",
        "claim_ledger_path",
        "manifest_path",
        "generated_at",
        "updated_at",
        "model_used",
        "evidence_strength",
        "hypothesis_status",
        "project_decision",
        "review_notes",
        "last_error",
    )
    summarized = {key: _clean_snapshot_text(row.get(key), 2000) for key in keys}
    summarized["reviewable"] = bool(
        summarized.get("project_id")
        and (
            summarized.get("draft_markdown_path") or summarized.get("draft_latex_path")
        )
    )
    return summarized


def _count_by(rows: list[dict[str, Any]], field: str) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for row in rows:
        key = str(row.get(field) or "unknown").strip() or "unknown"
        counts[key] += 1
    return dict(sorted(counts.items()))


def _build_paper_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    raw_rows = (
        payload.get("latest_rows")
        if isinstance(payload.get("latest_rows"), list)
        else payload.get("rows")
    )
    rows = (
        [_paper_row_summary(row) for row in raw_rows[:120]]
        if isinstance(raw_rows, list)
        else []
    )
    rows.sort(
        key=lambda row: row.get("updated_at") or row.get("generated_at") or "",
        reverse=True,
    )
    status_counts = (
        payload.get("status_counts")
        if isinstance(payload.get("status_counts"), dict)
        else _count_by(rows, "paper_status")
    )
    type_counts = (
        payload.get("type_counts")
        if isinstance(payload.get("type_counts"), dict)
        else _count_by(rows, "paper_type")
    )
    reviewable_count = sum(1 for row in rows if row.get("reviewable"))
    publication_count = sum(
        1 for row in rows if row.get("paper_status") == "publication_draft"
    )
    return {
        "updated_at": utc_now(),
        "source": str(payload.get("source") or "unknown"),
        "total": int(payload.get("total") or len(rows)),
        "reviewable_count": int(payload.get("reviewable_count") or reviewable_count),
        "publication_count": int(payload.get("publication_count") or publication_count),
        "status_counts": status_counts,
        "type_counts": type_counts,
        "latest_rows": rows,
    }


@app.post("/dashboard/paper-snapshot", responses=_DASHBOARD_SNAPSHOT_RESPONSES)
def dashboard_paper_snapshot(
    payload: dict[str, Any],
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, Any]:
    _require_local_bearer(authorization)
    snapshot = _build_paper_snapshot(payload)
    path = _paper_snapshot_path()
    _write_text(
        path, json.dumps(snapshot, indent=2, sort_keys=True) + "\n", overwrite=True
    )
    return {"ok": True, "paper_snapshot": snapshot}


@app.get(
    "/dashboard/api/paper-artifact/{project_id}",
    responses=_DASHBOARD_PAPER_ARTIFACT_RESPONSES,
)
def dashboard_api_paper_artifact(
    project_id: str,
    path: Annotated[str, Query(min_length=1)],
    authorization: Annotated[str | None, Header()] = None,
    token: Annotated[str | None, Query()] = None,
    max_bytes: Annotated[int, Query(ge=1, le=2_000_000)] = 350_000,
) -> dict[str, Any]:
    _require_dashboard_bearer(authorization, token)
    project_dir = _resolve_project_dir(project_id, None)
    if not _checked_exists(
        project_dir, label=PROJECT_DIRECTORY_LABEL, status_code=403
    ) or not _checked_is_dir(
        project_dir, label=PROJECT_DIRECTORY_LABEL, status_code=403
    ):
        raise HTTPException(
            status_code=404, detail=f"{PROJECT_DIRECTORY_LABEL} not found: {project_id}"
        )
    entry = _read_project_paper_artifact_entry(
        project_dir,
        path,
        max_bytes=max_bytes,
        too_large_detail=f"paper artifact too large for dashboard preview: {path}",
    )
    return {
        "ok": True,
        "project_id": project_id,
        "project_dir": project_dir.as_posix(),
        "path": entry["path"],
        "bytes": entry["bytes"],
        "content": entry["content"],
        "timestamp": utc_now(),
    }


@app.get(
    "/dashboard/paper-artifact/{project_id}",
    response_class=HTMLResponse,
    responses=_DASHBOARD_PAPER_ARTIFACT_RESPONSES,
)
def dashboard_paper_artifact(
    project_id: str,
    path: Annotated[str, Query(min_length=1)],
    authorization: Annotated[str | None, Header()] = None,
    token: Annotated[str | None, Query()] = None,
) -> HTMLResponse:
    data = dashboard_api_paper_artifact(
        project_id, path, authorization=authorization, token=token, max_bytes=2_000_000
    )
    title = html.escape(f"{project_id} · {data['path']}")
    content = html.escape(data["content"])
    return HTMLResponse(
        f"""
<!doctype html>
<html lang=\"en\"><head><meta charset=\"utf-8\"><title>{title}</title>
<style>body{{margin:0;background:#05070b;color:#eef6ff;font-family:ui-sans-serif,system-ui}}header{{position:sticky;top:0;background:#0b1320;border-bottom:1px solid rgba(148,163,184,.3);padding:14px 18px}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;margin:0;padding:18px;font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;line-height:1.45}}.small{{color:#9fb0c3;font-size:.9rem}}</style>
</head><body><header><strong>{title}</strong><div class=\"small\">{data["bytes"]} bytes · {html.escape(data["timestamp"])}</div></header><pre>{content}</pre></body></html>
"""
    )


@app.get("/dashboard/api", responses=_HTTP_401_INVALID_BEARER)
def dashboard_api(
    authorization: Annotated[str | None, Header()] = None,
    token: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=250)] = 40,
    event_limit: Annotated[int, Query(ge=0, le=200)] = 30,
    detail: Annotated[bool, Query()] = False,
) -> dict[str, Any]:
    _require_dashboard_bearer(authorization, token)

    records = store.list_runs()
    latest_by_project = _latest_runs_by_project(records)

    truth_by_run = {
        record.run_id: _dashboard_truth(
            record,
            [],
            superseded=_is_superseded_record(record, latest_by_project),
        )
        for record in records
    }
    records.sort(
        key=lambda record: (
            record.updated_at or "",
            record.last_event_at or "",
            record.created_at or "",
        ),
        reverse=True,
    )
    records.sort(
        key=lambda record: _dashboard_record_sort_priority(truth_by_run[record.run_id])
    )
    visible_records = records[:limit]
    state_counts = Counter(record.gate_state.value for record in records)
    run_items = [
        _run_dashboard_item(
            record,
            detail=detail,
            superseded=_is_superseded_record(record, latest_by_project),
        )
        for record in visible_records
    ]
    lifecycle_counts = Counter(
        item["lifecycle_state"] for item in truth_by_run.values()
    )
    live_count = sum(1 for item in truth_by_run.values() if item["is_live"])
    attention_count = sum(
        1 for item in truth_by_run.values() if item["needs_attention"]
    )
    callback_pending_count = lifecycle_counts.get("callback_pending", 0)
    stale_callback_count = lifecycle_counts.get("stale_callback_ready", 0)
    callback_delivered_count = lifecycle_counts.get(
        "callback_delivered", 0
    ) + lifecycle_counts.get("finished_delivered", 0)
    telemetry_sample = telemetry.sample()

    callback_token_fingerprint = hashlib.sha256(
        config.completion_callback_token.encode("utf-8")
    ).hexdigest()

    return {
        "timestamp": utc_now(),
        "service": {
            "name": "enoch_worker_gate",
            "listen_host": config.listen_host,
            "listen_port": config.listen_port,
            "state_dir": config.expanded_state_dir.as_posix(),
            "project_root": config.expanded_project_root.as_posix(),
            "completion_callback_url": config.completion_callback_url,
            "completion_callback_token_fingerprint": callback_token_fingerprint,
            "idle_sustain_sec": config.idle_sustain_sec,
            "sample_interval_sec": config.sample_interval_sec,
        },
        "totals": {
            "runs": len(records),
            "shown": len(visible_records),
            "active_or_waiting": live_count,
            "live": live_count,
            "needs_attention": attention_count,
            "callback_pending": callback_pending_count,
            "stale_callbacks": stale_callback_count,
            "callback_delivered": callback_delivered_count,
            "by_state": dict(sorted(state_counts.items())),
            "by_lifecycle": dict(sorted(lifecycle_counts.items())),
        },
        "telemetry": telemetry_sample.model_dump(),
        "queue": _read_queue_snapshot(),
        "papers": _read_paper_snapshot(),
        "runs": run_items,
        "events": [_trim_event(event) for event in _read_recent_events(event_limit)],
    }


@app.get(
    "/dashboard/api/run/{run_id}",
    responses=_DASHBOARD_API_RUN_RESPONSES,
)
def dashboard_api_run(
    run_id: str,
    authorization: Annotated[str | None, Header()] = None,
    token: Annotated[str | None, Query()] = None,
) -> dict[str, Any]:
    _require_dashboard_bearer(authorization, token)
    record = store.load_run(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail="run not found")
    latest_by_project = _latest_runs_by_project(store.list_runs())
    return {
        "timestamp": utc_now(),
        "run": _run_dashboard_item(
            record,
            detail=True,
            superseded=_is_superseded_record(record, latest_by_project),
        ),
        "events": [
            _trim_event(event, max_chars=3000)
            for event in _read_recent_events(200)
            if event.get("run_id") == run_id
        ],
    }


@app.get(
    "/project-status/{project_id}",
    responses=_PROJECT_STATUS_RESPONSES,
)
async def project_status(
    project_id: str,
    authorization: Annotated[str | None, Header()] = None,
    run_id: Annotated[str | None, Query()] = None,
    project_dir: Annotated[str | None, Query()] = None,
) -> dict[str, Any]:
    _require_local_bearer(authorization)

    try:
        resolved_project_dir = _resolve_project_dir(project_id, project_dir)
    except ControlPlaneHttpError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    record = _find_run_record(project_id, run_id)
    latest_session = _latest_session(resolved_project_dir)
    run_notes_tail = _tail_lines(resolved_project_dir / "run_notes.md")
    recent_files = _recent_files(resolved_project_dir)
    result_files = _result_files(resolved_project_dir)
    project_decision, decision_error = _load_project_decision(resolved_project_dir)

    active_processes: list[ProcessInfo] = []
    gate_state = record.gate_state.value if record is not None else None
    if record is not None:
        active_processes = gate.process_tracker.describe_processes(record)

    project_available = _checked_exists(
        resolved_project_dir, label=PROJECT_DIRECTORY_LABEL, status_code=403
    )
    response = ProjectStatusResponse(
        project_id=project_id,
        project_dir=resolved_project_dir.as_posix(),
        available=project_available,
        run_id=record.run_id if record is not None else run_id,
        session_id=record.session_id if record is not None else None,
        project_name=(record.project_name if record is not None else None)
        or project_id,
        gate_state=gate_state,
        current_activity=_activity_from_processes(active_processes, gate_state),
        run_notes_tail=run_notes_tail,
        recent_files=recent_files,
        result_files=result_files,
        active_processes=active_processes,
        latest_session=latest_session,
        project_decision=project_decision,
        decision_error=decision_error,
    )
    return response.model_dump(exclude_none=False)


@app.post("/prepare-project", responses=_PREPARE_PROJECT_RESPONSES)
async def prepare_project(
    request: PrepareProjectRequest,
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, Any]:
    _require_local_bearer(authorization)
    metadata = _normalize_prepare_metadata(request.metadata)

    project_root = config.expanded_project_root
    project_root.mkdir(parents=True, exist_ok=True)

    project_dir = _resolve_under_root(request.project_dir, project_root)
    prompt_file = _resolve_under_root(request.prompt_file, project_root)
    resume_prompt_file = (
        _resolve_under_root(request.resume_prompt_file, project_root)
        if request.resume_prompt_file
        else None
    )

    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / ENOCH_PROJECT_DIRNAME).mkdir(parents=True, exist_ok=True)

    _write_text(prompt_file, request.prompt_text, request.overwrite, root=project_root)
    if resume_prompt_file and request.resume_prompt_text is not None:
        _write_text(
            resume_prompt_file,
            request.resume_prompt_text,
            request.overwrite,
            root=project_root,
        )

    metadata_path = project_dir / ENOCH_PROJECT_DIRNAME / "project.json"
    metadata_payload = {
        "run_id": request.run_id,
        "project_id": request.project_id,
        "project_name": request.project_name,
        "notion_page_url": request.notion_page_url,
        "project_dir": str(project_dir),
        "prompt_file": str(prompt_file),
        "resume_prompt_file": str(resume_prompt_file) if resume_prompt_file else "",
        "prompt_length": len(request.prompt_text),
        "resume_prompt_length": len(request.resume_prompt_text or ""),
        "prepared_at": utc_now(),
        "metadata": metadata,
    }
    _write_text(
        metadata_path,
        json.dumps(metadata_payload, indent=2, sort_keys=True),
        overwrite=True,
        root=project_root,
    )

    return {
        "accepted": True,
        "prepared": {
            "project_dir": str(project_dir),
            "prompt_file": str(prompt_file),
            "resume_prompt_file": str(resume_prompt_file) if resume_prompt_file else "",
            "metadata_file": str(metadata_path),
        },
        "timestamp": utc_now(),
    }


@app.post(
    "/project-paper/{project_id}/read",
    responses=_READ_PROJECT_PAPER_RESPONSES,
)
async def read_project_paper(
    project_id: str,
    request: PaperArtifactReadRequest,
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, Any]:
    _require_local_bearer(authorization)
    _validate_paper_artifact_read_request(request)

    project_dir = _resolve_project_dir(project_id, None)
    if not _checked_exists(
        project_dir, label=PROJECT_DIRECTORY_LABEL, status_code=403
    ) or not _checked_is_dir(
        project_dir, label=PROJECT_DIRECTORY_LABEL, status_code=403
    ):
        raise HTTPException(
            status_code=404, detail=f"{PROJECT_DIRECTORY_LABEL} not found: {project_id}"
        )

    files = [
        _read_project_paper_artifact_entry(
            project_dir, relative, max_bytes=request.max_bytes_per_file
        )
        for relative in request.paths
    ]

    return {
        "ok": True,
        "project_id": project_id,
        "project_dir": project_dir.as_posix(),
        "files": files,
        "timestamp": utc_now(),
    }


@app.post(
    "/project-paper/{project_id}",
    responses=_WRITE_PROJECT_PAPER_RESPONSES,
)
async def write_project_paper(
    project_id: str,
    request: PaperArtifactRequest,
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, Any]:
    _require_local_bearer(authorization)
    if len(request.files) > 20:
        raise HTTPException(
            status_code=400, detail="too many paper artifact files; max 20"
        )

    project_dir = _resolve_project_dir(project_id, None)
    if not _checked_exists(
        project_dir, label=PROJECT_DIRECTORY_LABEL, status_code=403
    ) or not _checked_is_dir(
        project_dir, label=PROJECT_DIRECTORY_LABEL, status_code=403
    ):
        raise HTTPException(
            status_code=404, detail=f"{PROJECT_DIRECTORY_LABEL} not found: {project_id}"
        )

    written: list[dict[str, Any]] = []
    for artifact in request.files:
        if len(artifact.content.encode("utf-8")) > 2_000_000:
            raise HTTPException(
                status_code=413, detail=f"paper artifact too large: {artifact.path}"
            )
        path = _resolve_project_relative_path(project_dir, artifact.path)
        _write_text(path, artifact.content, request.overwrite, root=project_dir)
        written.append(
            {
                "path": path.relative_to(project_dir).as_posix(),
                "bytes": len(artifact.content.encode("utf-8")),
            }
        )

    manifest_path = _resolve_project_relative_path(
        project_dir, f"papers/{request.run_id}/paper_manifest.json"
    )
    manifest = {
        "project_id": project_id,
        "run_id": request.run_id,
        "paper_id": request.paper_id,
        "written": written,
        "updated_at": utc_now(),
    }
    _write_text(
        manifest_path,
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        True,
        root=project_dir,
    )
    return {
        "ok": True,
        "project_id": project_id,
        "run_id": request.run_id,
        "paper_id": request.paper_id,
        "project_dir": project_dir.as_posix(),
        "written": written,
        "manifest_path": manifest_path.relative_to(project_dir).as_posix(),
        "timestamp": utc_now(),
    }


def _path_is_under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _resolve_dispatch_script_path(raw_path: str) -> Path:
    try:
        raw = Path(raw_path).expanduser()
        candidate = raw if raw.is_absolute() else _APP_ROOT / raw
        script_path = candidate.resolve(strict=False)
        trusted_roots = (
            _APP_ROOT.resolve(strict=False),
            config.expanded_project_root.resolve(strict=False),
        )
    except (OSError, RuntimeError, ValueError) as exc:
        raise HTTPException(
            status_code=500,
            detail="dispatch script path could not be resolved under a trusted root",
        ) from exc
    if not any(_path_is_under(script_path, root) for root in trusted_roots):
        raise HTTPException(
            status_code=500,
            detail="dispatch script path escapes trusted roots",
        )
    return script_path


def _require_dispatch_script() -> Path:
    script_path = _resolve_dispatch_script_path(config.dispatch_script_path)
    if not script_path.exists():
        raise HTTPException(
            status_code=500, detail=f"dispatch script not found: {script_path}"
        )
    return script_path


def _build_dispatch_cmd(
    script_path: Path,
    request: DispatchRequest,
    project_dir: Path,
    prompt_file: Path,
) -> list[str]:
    cmd = [
        str(script_path),
        "--run-id",
        request.run_id,
        "--project-dir",
        str(project_dir),
        "--prompt-file",
        str(prompt_file),
        "--mode",
        request.mode,
        "--sandbox",
        request.sandbox,
    ]
    if request.project_id:
        cmd.extend(["--project-id", request.project_id])
    if request.session_id:
        cmd.extend(["--session-id", request.session_id])
    if request.last:
        cmd.append("--last")
    if request.model:
        cmd.extend(["--model", request.model])
    if request.reasoning_effort:
        cmd.extend(["--reasoning-effort", request.reasoning_effort])
    if request.log_dir:
        log_dir = _resolve_under_root(request.log_dir, config.expanded_project_root)
        cmd.extend(["--log-dir", str(log_dir)])
    return cmd


def _dispatch_subprocess_env() -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "ENOCH_COMPLETION_CALLBACK_URL": config.completion_callback_url,
            "ENOCH_COMPLETION_CALLBACK_TOKEN": config.completion_callback_token,
            "ENOCH_COMPLETION_CALLBACK_TIMEOUT_SEC": str(
                config.completion_callback_timeout_sec
            ),
            "ENOCH_COMPLETION_CALLBACK_HMAC_SECRET": config.completion_callback_hmac_secret,
            "ENOCH_WORKER_STATE_DIR": str(config.expanded_state_dir),
        }
    )
    return env


async def _run_dispatch_subprocess(
    cmd: list[str],
) -> subprocess.CompletedProcess[str]:
    try:
        return await asyncio.to_thread(
            subprocess.run,
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=config.dispatch_timeout_sec,
            env=_dispatch_subprocess_env(),
        )
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(
            status_code=504,
            detail=f"dispatch timed out after {config.dispatch_timeout_sec}s",
        ) from exc


def _parse_dispatch_subprocess_result(
    result: subprocess.CompletedProcess[str],
) -> dict[str, Any]:
    if result.returncode != 0:
        stderr = result.stderr or ""
        raise HTTPException(
            status_code=502,
            detail={
                "message": "dispatch failed",
                "returncode": result.returncode,
                "stderr_present": bool(stderr.strip()),
                "stderr_bytes": len(stderr.encode("utf-8", errors="replace")),
            },
        )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        stdout = result.stdout or ""
        stderr = result.stderr or ""
        raise HTTPException(
            status_code=502,
            detail={
                "message": "dispatch returned non-json output",
                "stdout_present": bool(stdout.strip()),
                "stdout_bytes": len(stdout.encode("utf-8", errors="replace")),
                "stderr_present": bool(stderr.strip()),
                "stderr_bytes": len(stderr.encode("utf-8", errors="replace")),
            },
        ) from exc


def _persist_dispatch_envelope_event(
    *,
    envelope_id: str,
    state: str,
    request: DispatchRequest,
    project_dir: Path,
    prompt_file: Path,
    detail: Any | None = None,
) -> None:
    event: dict[str, Any] = {
        "kind": "dispatch_envelope",
        "envelope_id": envelope_id,
        "state": state,
        "run_id": request.run_id,
        "project_id": request.project_id,
        "project_dir": str(project_dir),
        "prompt_file": str(prompt_file),
        "timestamp": utc_now(),
    }
    if detail is not None:
        event["detail"] = detail
    store.append_event(event)


def _apply_dispatch_baseline_vram(record: RunRecord) -> None:
    baseline_sample = telemetry.sample()
    if record.baseline_vram_mib is None or (
        baseline_sample.memory_source == "uma_meminfo" and record.baseline_vram_mib == 0
    ):
        record.baseline_vram_mib = baseline_sample.vram_used_mib


def _persist_dispatch_run_record(
    request: DispatchRequest,
    project_dir: Path,
    workload_class: str,
    workload_profile: Any,
    payload: dict[str, Any],
) -> None:
    record = store.load_run(request.run_id) or RunRecord(
        run_id=request.run_id,
        session_id=request.session_id or "",
        project_id=request.project_id,
        project_name=request.project_id,
    )
    record.session_id = request.session_id or record.session_id
    record.project_id = request.project_id or record.project_id
    record.project_name = request.project_id or record.project_name
    record.project_dir = str(project_dir)
    record.workload_class = workload_class
    record.workload_profile = workload_profile
    record.root_pid = payload.get("pid") or record.root_pid
    record.process_group_id = payload.get("pgid") or record.process_group_id
    record.gate_state = GateState.RUNNING
    record.idle_seen_at = None
    record.last_event = None
    record.last_event_at = None
    record.last_idempotency_key = None
    record.quiet_samples = []
    record.updated_at = utc_now()
    _apply_dispatch_baseline_vram(record)
    store.save_run(record)


@app.post("/dispatch", responses=_DISPATCH_RESPONSES)
async def dispatch_run(
    request: DispatchRequest,
    authorization: Annotated[str | None, Header()] = None,
) -> dict:
    _require_local_bearer(authorization)
    project_dir = _resolve_under_root(request.project_dir, config.expanded_project_root)
    prompt_file = _resolve_under_root(request.prompt_file, config.expanded_project_root)
    workload_class, workload_profile = _resolve_workload_profile_for_project_dir(
        project_dir
    )

    script_path = _require_dispatch_script()
    cmd = _build_dispatch_cmd(script_path, request, project_dir, prompt_file)
    envelope_id = request.run_id
    _persist_dispatch_envelope_event(
        envelope_id=envelope_id,
        state="accepted",
        request=request,
        project_dir=project_dir,
        prompt_file=prompt_file,
    )
    try:
        result = await _run_dispatch_subprocess(cmd)
        payload = _parse_dispatch_subprocess_result(result)
    except HTTPException as exc:
        _persist_dispatch_envelope_event(
            envelope_id=envelope_id,
            state="failed",
            request=request,
            project_dir=project_dir,
            prompt_file=prompt_file,
            detail=exc.detail,
        )
        raise
    _persist_dispatch_run_record(
        request, project_dir, workload_class, workload_profile, payload
    )
    _persist_dispatch_envelope_event(
        envelope_id=envelope_id,
        state="started",
        request=request,
        project_dir=project_dir,
        prompt_file=prompt_file,
        detail=payload,
    )

    return {
        "accepted": True,
        "envelope_id": envelope_id,
        "dispatch": payload,
        "timestamp": utc_now(),
    }


_CALLBACK_DELIVERY_FAILURES = (
    RetryError,
    TimeoutError,
    OSError,
    urllib.error.URLError,
    urllib.error.HTTPError,
)


async def _deliver_callback(callback: GateCallback) -> tuple[bool, str]:
    loop = asyncio.get_running_loop()
    try:
        status, text = await loop.run_in_executor(None, sender.send, callback)
        return True, f"{status}:{text}"
    except _CALLBACK_DELIVERY_FAILURES as exc:
        # Network/HTTP delivery failures are part of the gate state machine: the
        # caller records a callback_attempt event and may retry or mark the gate
        # errored. Programming errors while constructing the payload must still
        # crash loudly instead of being persisted as indistinguishable delivery
        # failures.
        return False, f"{type(exc).__name__}: {exc}"


async def _replay_callback_outbox_once() -> None:
    if not config.completion_callback_url or not config.completion_callback_token:
        return
    results = await asyncio.to_thread(
        callback_outbox.replay_pending,
        state_dir=config.expanded_state_dir,
        url=config.completion_callback_url,
        token=config.completion_callback_token,
        timeout=float(config.completion_callback_timeout_sec),
        limit=10,
        hmac_secret=config.completion_callback_hmac_secret,
    )
    for result in results:
        store.append_event(
            {
                "kind": "callback_outbox_replay",
                "ok": result.ok,
                "status_code": result.status_code,
                "detail": result.detail,
                "path": result.path,
                "timestamp": utc_now(),
            }
        )


async def _reap_and_log_stale_project_processes(record: RunRecord) -> None:
    term_signaled = await asyncio.to_thread(
        gate.begin_stale_project_process_reap, record
    )
    if not term_signaled:
        return
    term_grace_sec = config.stale_project_process_term_grace_sec
    if term_grace_sec > 0:
        await asyncio.sleep(term_grace_sec)
    reaped_processes = await asyncio.to_thread(
        gate.finish_stale_project_process_reap, term_signaled
    )
    if not reaped_processes:
        return
    store.append_event(
        {
            "kind": "stale_project_process_reaped",
            "run_id": record.run_id,
            "session_id": record.session_id,
            "project_id": record.project_id,
            "timestamp": utc_now(),
            "reason": "root session exited/idle; project-owned stale smoke process exceeded grace window",
            "stale_after_sec": config.stale_project_process_grace_sec,
            "processes": reaped_processes,
        }
    )


def _build_gate_timeout_callback(
    record: RunRecord,
    timeout_idempotency_key: str,
    profile_evidence: dict[str, Any],
) -> GateCallback:
    return GateCallback(
        event_type="gate_timeout",
        run_id=record.run_id,
        session_id=record.session_id,
        project_id=record.project_id,
        project_name=record.project_name,
        source_event=(record.last_event.value if record.last_event else "unknown"),
        gate_state=record.gate_state.value,
        idle_seen_at=record.idle_seen_at,
        process_tracking=gate.process_tracker.snapshot(record, []),
        telemetry={
            "workload_class": profile_evidence["workload_class"],
            "workload_profile_name": profile_evidence["workload_profile_name"],
            "thresholds": profile_evidence["workload_thresholds"],
        },
        reason="idle_gate_timeout",
        idempotency_key=timeout_idempotency_key,
    )


async def _process_retry_callback(record: RunRecord) -> bool:
    retry_callback = _ready_callback_for_retry(record)
    if retry_callback is None:
        return False
    ok, detail = await _deliver_callback(retry_callback)
    profile_evidence = _wake_decision_profile_evidence(record)
    store.append_event(
        {
            "kind": "callback_retry",
            "run_id": record.run_id,
            "event_type": retry_callback.event_type,
            "ok": ok,
            "detail": detail,
            "timestamp": utc_now(),
            **profile_evidence,
        }
    )
    if not ok:
        return False
    record.last_idempotency_key = retry_callback.idempotency_key
    store.save_run(record)
    return True


async def _process_gate_timeout(record: RunRecord) -> bool:
    if not gate.is_timed_out(record):
        return False
    timeout_idempotency_key = (
        f"{record.run_id}:gate_timeout:{record.idle_seen_at or record.last_event_at}"
    )
    if record.last_idempotency_key == timeout_idempotency_key:
        return True
    profile_evidence = _wake_decision_profile_evidence(record)
    timeout_callback = _build_gate_timeout_callback(
        record, timeout_idempotency_key, profile_evidence
    )
    record.gate_state = GateState.ERROR
    record.last_idempotency_key = timeout_callback.idempotency_key
    store.save_run(record)
    ok, detail = await _deliver_callback(timeout_callback)
    store.append_event(
        {
            "kind": "callback_attempt",
            "run_id": record.run_id,
            "event_type": timeout_callback.event_type,
            "ok": ok,
            "detail": detail,
            "timestamp": utc_now(),
            **profile_evidence,
        }
    )
    store.save_run(record)
    return True


async def _process_gate_evaluation(record: RunRecord) -> bool:
    record, callback = gate.evaluate(record)
    store.save_run(record)
    if callback is None:
        return False
    ok, detail = await _deliver_callback(callback)
    profile_evidence = _wake_decision_profile_evidence(record)
    store.append_event(
        {
            "kind": "callback_attempt",
            "run_id": record.run_id,
            "event_type": callback.event_type,
            "ok": ok,
            "detail": detail,
            "timestamp": utc_now(),
            **profile_evidence,
        }
    )
    if not ok:
        return False
    record.last_idempotency_key = callback.idempotency_key
    store.save_run(record)
    return True


async def _evaluate_until_ready(run_id: str) -> None:
    current_task = asyncio.current_task()
    try:
        while True:
            record = store.load_run(run_id)
            if record is None:
                return
            record = _assign_record_workload_profile(record)

            await _reap_and_log_stale_project_processes(record)

            if await _process_retry_callback(record):
                return
            if await _process_gate_timeout(record):
                return
            if await _process_gate_evaluation(record):
                return

            await asyncio.sleep(config.sample_interval_sec)
    finally:
        with evaluation_tasks_lock:
            current = evaluation_tasks.get(run_id)
            if current is current_task or (current is not None and current.done()):
                evaluation_tasks.pop(run_id, None)
                evaluation_task_started_at.pop(run_id, None)


async def _evaluate_until_ready_guarded(run_id: str) -> None:
    try:
        await _evaluate_until_ready(run_id)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        _logger.exception("evaluation task failed for run %s", run_id, exc_info=exc)
        capture_exception(exc)


def _ensure_evaluator(run_id: str) -> None:
    now = time.monotonic()
    with evaluation_tasks_lock:
        current = evaluation_tasks.get(run_id)
        started_at = evaluation_task_started_at.get(run_id, now)
        if current is not None and not current.done():
            if now - started_at <= EVALUATION_TASK_TTL_SECONDS:
                return
            current.cancel()
        task = asyncio.create_task(_evaluate_until_ready_guarded(run_id))
        evaluation_tasks[run_id] = task
        evaluation_task_started_at[run_id] = now


async def _reconcile_missing_idle_once() -> None:
    await _replay_callback_outbox_once()
    for record in store.list_runs():
        record = _assign_record_workload_profile(record)
        if record.gate_state == GateState.RUNNING:
            await _reap_and_log_stale_project_processes(record)
            record, changed = gate.reconcile(record)
            if changed:
                store.append_event(
                    {
                        "kind": "reconciled_missing_idle",
                        "run_id": record.run_id,
                        "session_id": record.session_id,
                        "timestamp": utc_now(),
                    }
                )
                store.save_run(record)
        if record.gate_state in {
            GateState.PENDING_IDLE_GATE,
            GateState.WAITING_FOR_PROCESS_EXIT,
            GateState.WAITING_FOR_QUIET_WINDOW,
            GateState.FINISHED_PENDING_GATE,
            GateState.WAKE_READY,
            GateState.FINISHED_READY,
        }:
            _ensure_evaluator(record.run_id)


async def _reconcile_missing_idle_loop() -> None:
    while True:
        try:
            await _reconcile_missing_idle_once()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _logger.exception("reconcile tick failed", exc_info=exc)
            capture_exception(exc)
        await asyncio.sleep(config.sample_interval_sec)


# NOTE: startup/shutdown logic moved to the lifespan context manager above
# (modern FastAPI pattern, removes on_event deprecation warnings).
