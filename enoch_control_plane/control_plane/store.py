from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from ..enoch_core.store import IdempotencyConflict
from ..models import utc_now
from ..timeutils import parse_utc_datetime
from .models import (
    ControlFlags,
    DashboardObservationRecord,
    IdeaIntakeRequest,
    ImportSnapshotRequest,
    NotionIntakeRequest,
    PaperRecord,
    PaperReviewApproveFinalizationRequest,
    PaperReviewBackfillRequest,
    PaperReviewChecklistUpdateRequest,
    PaperReviewClaimRequest,
    PaperReviewPrepareFinalizationRequest,
    PaperReviewRecord,
    PaperReviewStatusUpdateRequest,
    PaperStatus,
    ProjectRecord,
    QueueItemRecord,
    QueueStatus,
    ReviewQueueItem,
    ReviewStatus,
    RunState,
)
from .workload_routing import route_machine_target
from .promising_signal_priority import (
    promising_followup_priority_key,
    ranked_followup_readiness,
)
from .state_contract import RUN_STATES

SCHEMA_VERSION = 1
ACTIVE_STATUSES = {
    "dispatching",
    "running",
    "awaiting_wake",
    "wake_received",
    "reconciling",
}
# Centralized SQL fragment for queue status equality filters (Sonar S1192).
_QUEUE_STATUS_EQ = "q.status = ?"
TERMINAL_SUCCESS_CALLBACK_STATES = {"wake_ready", "session_finished_ready"}
WORKER_CALLBACK_AUDIT_KEYS = {
    "delivered_at",
    "received_by",
    "seen_at",
    "applied_status",
    "applied_next_action_hint",
    "stale_callback_ignored",
    "late_callback_ignored",
    "ignore_reason",
    "current_run_id",
    "current_last_run_state",
}
MISSING_TITLE_REASON = "missing title"


def _json(payload: Any) -> str:
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, delete=False
        ) as handle:
            handle.write(text)
            tmp = Path(handle.name)
        tmp.replace(path)
    finally:
        if tmp is not None:
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError:
                pass


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("wb", dir=path.parent, delete=False) as handle:
            handle.write(data)
            tmp = Path(handle.name)
        tmp.replace(path)
    finally:
        if tmp is not None:
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError:
                pass


def _restore_or_remove_path(path: Path, *, existed: bool, content: bytes) -> None:
    if existed:
        _atomic_write_bytes(path, content)
        return
    try:
        if path.exists():
            path.unlink()
    except (OSError, RuntimeError, ValueError):
        pass


def _existing_file_snapshot(path: Path, *, label: str) -> tuple[bool, bytes]:
    try:
        exists = path.exists()
    except (OSError, RuntimeError, ValueError) as exc:
        raise ValueError(f"could not inspect existing {label}: {path}") from exc
    if not exists:
        return False, b""
    try:
        if not path.is_file():
            raise ValueError(f"existing {label} is not a file: {path}")
        return True, path.read_bytes()
    except ValueError:
        raise
    except (OSError, RuntimeError) as exc:
        raise ValueError(f"could not read existing {label}: {path}") from exc


def _hash(payload: Any) -> str:
    return hashlib.sha256(_json(payload).encode("utf-8")).hexdigest()


def _required_lastrowid(cursor: sqlite3.Cursor, *, operation: str) -> int:
    if cursor.lastrowid is None:
        raise RuntimeError(f"{operation} did not return a sqlite lastrowid")
    return int(cursor.lastrowid)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _row_or(row: dict[str, Any], key: str, default: Any = "") -> Any:
    return row.get(key) or default


def _normal(value: Any) -> str:
    return _text(value).lower().replace("-", "_").replace(" ", "_")


def _expanduser_or_none(value: str) -> Path | None:
    try:
        return Path(value).expanduser()
    except RuntimeError:
        return None


def _unresolved_artifact(field: str, raw_path: str) -> dict[str, Any]:
    return {
        "field": field,
        "path": raw_path,
        "absolute_path": "",
        "exists": False,
        "readable": False,
        "safe": False,
        "size_bytes": 0,
    }


def _resolve_artifact_absolute_path(
    path: Path, project_dir: Path | None
) -> Path | None:
    try:
        candidate = (
            path
            if path.is_absolute()
            else (project_dir / path if project_dir else path)
        )
        return candidate.resolve()
    except (OSError, RuntimeError, ValueError):
        return None


def _artifact_path_within_project(resolved: Path, project_dir: Path | None) -> bool:
    if project_dir is None:
        return True
    try:
        resolved.relative_to(project_dir.resolve())
        return True
    except (OSError, RuntimeError, ValueError):
        return False


def _artifact_access_stats(
    resolved: Path, raw_path: str, safe: bool
) -> tuple[bool, bool, int]:
    try:
        exists = bool(raw_path) and resolved.exists()
        readable = safe and exists and resolved.is_file()
        size_bytes = resolved.stat().st_size if readable else 0
        return exists, readable, size_bytes
    except (OSError, RuntimeError, ValueError):
        return bool(raw_path), False, 0


def _default_supabase_finalization_root() -> Path:
    """User-private storage for Supabase finalization manifests (not world-writable /tmp)."""
    return (
        Path.home()
        / ".local"
        / "state"
        / "enoch-worker-gate"
        / "supabase-finalization-packages"
    )


def _is_older_timestamp(incoming: Any, existing: Any) -> bool:
    incoming_dt = parse_utc_datetime(incoming)
    existing_dt = parse_utc_datetime(existing)
    return bool(incoming_dt and existing_dt and incoming_dt < existing_dt)


def _contract_worker_callback_states(
    event_type: str, gate_state: str = ""
) -> tuple[str, str, str]:
    """Normalize worker callback labels into contract-safe persisted states.

    `last_event_type` and the append-only event stream preserve the exact raw
    callback. The lifecycle/detail columns should stay inside the finite state
    contract so Supabase constraints can reject accidental new workflow states.
    """

    event = _normal(event_type)
    raw_gate_state = _normal(gate_state)
    if event == "session_started":
        run_state = RunState.RUNNING.value
        last_run_state = RunState.RUNNING.value
    elif event in RUN_STATES:
        run_state = event
        last_run_state = event
    else:
        run_state = "needs_review"
        last_run_state = "needs_review"
    persisted_gate_state = raw_gate_state if raw_gate_state in RUN_STATES else run_state
    return last_run_state, run_state, persisted_gate_state


def _completed_success_queue_row(row: dict[str, Any] | None, run_id: str) -> bool:
    if not row:
        return False
    return (
        _text(row.get("status")) == QueueStatus.COMPLETED.value
        and _text(row.get("current_run_id")) == _text(run_id)
        and _text(row.get("last_run_state")) in TERMINAL_SUCCESS_CALLBACK_STATES
    )


def _worker_callback_payload(callback: Any) -> dict[str, Any]:
    if hasattr(callback, "model_dump"):
        return callback.model_dump(mode="json")
    return dict(callback)


def _derived_worker_callback_idempotency_key(
    payload: dict[str, Any], *, run_id: str, event_type: str, idempotency_key: str
) -> str:
    if idempotency_key:
        return idempotency_key
    session_part = _text(payload.get("session_id")) or "no-session"
    payload_part = _hash(payload)[:16]
    return (
        f"worker-callback:{run_id or 'unknown'}:{event_type or 'unknown'}:"
        f"{session_part}:{payload_part}"
    )


def _worker_callback_event_type_name(event_type: str) -> str:
    return f"worker_callback.{event_type}"


def _worker_callback_entity_id(run_id: str, project_id: str) -> str:
    return run_id or project_id or "unknown"


def _worker_callback_transition(
    event_type: str, payload: dict[str, Any]
) -> tuple[str, str, int, str]:
    status = QueueStatus.COMPLETED.value
    next_action_hint = "select_next_project"
    manual_review_required = 0
    last_error = ""
    if event_type == "session_started":
        status = QueueStatus.RUNNING.value
        next_action_hint = "await_callback"
    elif event_type == "question_pending":
        status = QueueStatus.NEEDS_REVIEW.value
        next_action_hint = "answer_worker_question"
        manual_review_required = 1
    elif event_type in {"gate_timeout", "gate_error"}:
        status = QueueStatus.BLOCKED.value
        next_action_hint = "inspect_worker_gate_failure"
        manual_review_required = 1
        last_error = _text(payload.get("reason")) or event_type
    elif event_type in TERMINAL_SUCCESS_CALLBACK_STATES:
        next_action_hint = "draft_paper_or_select_next_project"
    else:
        status = QueueStatus.NEEDS_REVIEW.value
        next_action_hint = "inspect_unknown_worker_callback"
        manual_review_required = 1
        last_error = (
            _text(payload.get("reason")) or f"unknown worker callback: {event_type}"
        )
    return status, next_action_hint, manual_review_required, last_error


def _stale_worker_callback_ignore_reason(*, run_id: str, current_status: str) -> str:
    if not run_id and current_status in ACTIVE_STATUSES:
        return "missing_run_id_for_active_project"
    if not run_id:
        return "missing_run_id_for_project_callback"
    return "run_id_mismatch"


def _late_terminal_success_worker_callback_payload(
    payload: dict[str, Any],
    current_queue_row: dict[str, Any],
    *,
    received_by: str,
) -> dict[str, Any]:
    return {
        **payload,
        "received_by": received_by,
        "applied_status": _text(current_queue_row.get("status")),
        "applied_next_action_hint": _text(current_queue_row.get("next_action_hint")),
        "late_callback_ignored": True,
        "ignore_reason": "terminal_success_precedence",
        "current_run_id": _text(current_queue_row.get("current_run_id")),
        "current_last_run_state": _text(current_queue_row.get("last_run_state")),
    }


def _stale_worker_callback_payload(
    payload: dict[str, Any],
    current_queue_row: dict[str, Any],
    *,
    received_by: str,
    status: str,
    next_action_hint: str,
    ignore_reason: str,
) -> dict[str, Any]:
    return {
        **payload,
        "received_by": received_by,
        "applied_status": status,
        "applied_next_action_hint": next_action_hint,
        "stale_callback_ignored": True,
        "ignore_reason": ignore_reason,
        "current_run_id": _text(current_queue_row.get("current_run_id")),
    }


def _first_present(raw: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in raw and raw.get(name) not in (None, ""):
            return raw.get(name)
    return None


def _snapshot_row_key(row: dict[str, Any], *, paper: bool) -> str:
    id_field = "paper_id" if paper else "project_id"
    return _text(row.get(id_field)) or _hash(row)


def _register_snapshot_row(
    row: dict[str, Any],
    *,
    paper: bool,
    seen: dict[str, str],
    rows: list[dict[str, Any]],
) -> None:
    row_key = _snapshot_row_key(row, paper=paper)
    if row_key in seen:
        if seen[row_key] != _json(row):
            raise ValueError(f"conflicting snapshot row identity for {row_key!r}")
        return
    seen[row_key] = _json(row)
    rows.append(row)


def _snapshot_rows_from_dict(
    snapshot: dict[str, Any], *, paper: bool
) -> list[dict[str, Any]]:
    keys = (
        ("latest_rows", "rows", "active_rows", "blocked_rows")
        if paper
        else ("rows", "active_rows", "blocked_rows")
    )
    rows: list[dict[str, Any]] = []
    seen: dict[str, str] = {}
    for key in keys:
        value = snapshot.get(key)
        if not isinstance(value, list):
            continue
        for row in value:
            if isinstance(row, dict):
                _register_snapshot_row(row, paper=paper, seen=seen, rows=rows)
    return rows


def _snapshot_rows(
    snapshot: dict[str, Any] | list[dict[str, Any]] | None, *, paper: bool = False
) -> list[dict[str, Any]]:
    if snapshot is None:
        return []
    if isinstance(snapshot, list):
        return [row for row in snapshot if isinstance(row, dict)]
    if not isinstance(snapshot, dict):
        return []
    return _snapshot_rows_from_dict(snapshot, paper=paper)


def _reject_conflicting_snapshot_rows(
    rows: list[dict[str, Any]],
    *,
    key_fields: tuple[str, ...],
    identity_fields: tuple[tuple[str, ...], ...],
    label: str,
) -> None:
    seen: dict[str, tuple[str, ...]] = {}
    for row in rows:
        key = _text(_first_present(row, *key_fields))
        if not key:
            continue
        identity = tuple(
            _text(_first_present(row, *fields)) for fields in identity_fields
        )
        existing = seen.get(key)
        if existing is not None and existing != identity:
            raise ValueError(f"conflicting {label} identity for {key!r}")
        seen[key] = identity


def _paper_identity_conflicts(
    existing: Any, paper: PaperRecord | dict[str, Any]
) -> bool:
    if not existing:
        return False
    project_id = _text(
        paper.project_id if isinstance(paper, PaperRecord) else paper.get("project_id")
    )
    run_id = _text(
        paper.run_id if isinstance(paper, PaperRecord) else paper.get("run_id")
    )
    paper_type = (
        _text(
            paper.paper_type
            if isinstance(paper, PaperRecord)
            else paper.get("paper_type")
        )
        or "arxiv_draft"
    )
    existing_run_id = _text(existing["run_id"])
    return (
        _text(existing["project_id"]) != project_id
        or (existing_run_id and existing_run_id != run_id)
        or _text(existing["paper_type"]) != paper_type
    )


def _validate_import_snapshot_rows(
    queue_rows: list[dict[str, Any]], paper_rows: list[dict[str, Any]]
) -> None:
    _reject_conflicting_snapshot_rows(
        queue_rows,
        key_fields=("project_id",),
        identity_fields=(
            ("project_name", "name", "title"),
            ("project_dir", "project_path"),
            ("status", "queue_status"),
            ("current_run_id",),
        ),
        label="queue project",
    )
    _reject_conflicting_snapshot_rows(
        paper_rows,
        key_fields=("paper_id",),
        identity_fields=(
            ("project_id",),
            ("run_id",),
            ("paper_type",),
            ("paper_status",),
            ("draft_markdown_path",),
            ("draft_latex_path",),
            ("evidence_bundle_path",),
            ("claim_ledger_path",),
            ("manifest_path",),
        ),
        label="paper",
    )


def _import_snapshot_event_payload(
    request: ImportSnapshotRequest,
    queue_rows: list[dict[str, Any]],
    paper_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    event_payload = request.model_dump(mode="json")
    event_payload["normalized_queue_row_count"] = len(queue_rows)
    event_payload["normalized_paper_row_count"] = len(paper_rows)
    return event_payload


def _queue_status_from_import_raw(raw: dict[str, Any]) -> QueueStatus:
    status_text = _text(_first_present(raw, "status", "queue_status")) or "queued"
    if status_text in QueueStatus._value2member_map_:
        return QueueStatus(status_text)
    return QueueStatus.QUEUED


def _project_record_from_import_queue_raw(
    raw: dict[str, Any], project_id: str
) -> ProjectRecord:
    return ProjectRecord(
        project_id=project_id,
        project_name=_text(_first_present(raw, "project_name", "name", "title"))
        or project_id,
        project_dir=_text(_first_present(raw, "project_dir", "project_path")),
        notion_page_url=_text(_first_present(raw, "notion_page_url", "url")),
        notion_page_id=_text(_first_present(raw, "notion_page_id", "page_id", "id"))
        or _notion_page_id_from_url(
            _text(_first_present(raw, "notion_page_url", "url"))
        ),
        origin_idea_status=_text(
            _first_present(raw, "origin_idea_status", "idea_status")
        )
        or "unknown",
        created_at=_text(_first_present(raw, "createdAt", "created_at")) or utc_now(),
        updated_at=_text(
            _first_present(raw, "updatedAt", "updated_at", "last_execution_update")
        )
        or utc_now(),
    )


def _queue_item_record_from_import_raw(
    raw: dict[str, Any], project_id: str
) -> QueueItemRecord:
    return QueueItemRecord(
        project_id=project_id,
        status=_queue_status_from_import_raw(raw),
        selection_rank=_int(_first_present(raw, "selection_rank", "rank"), 50),
        dispatch_priority=_int(
            _first_present(raw, "dispatch_priority", "priority"), 50
        ),
        auto_continue=_bool(_first_present(raw, "auto_continue", "autoContinue")),
        continue_count=_int(_first_present(raw, "continue_count", "continueCount"), 0),
        max_continues=_int(_first_present(raw, "max_continues", "maxContinues"), 0),
        retry_count=_int(_first_present(raw, "retry_count", "retryCount"), 0),
        max_retries=_int(_first_present(raw, "max_retries", "maxRetries"), 2),
        current_run_id=_text(raw.get("current_run_id")),
        current_session_id=_text(raw.get("current_session_id")),
        last_run_state=_text(raw.get("last_run_state")),
        last_event_type=_text(raw.get("last_event_type")),
        next_action_hint=_text(raw.get("next_action_hint")) or "controller_review",
        manual_review_required=_bool(raw.get("manual_review_required")),
        blocked_reason=_text(raw.get("blocked_reason")),
        last_error=_text(raw.get("last_error")),
        last_result_summary=_text(raw.get("last_result_summary")),
        machine_target=_text(raw.get("machine_target")) or "worker.example",
        model=_text(raw.get("model")) or "gpt-5.5",
        sandbox=_text(raw.get("sandbox")) or "danger-full-access",
        last_dispatch_at=_first_present(
            raw, "last_dispatch_at", "last_execution_update"
        ),
        last_callback_at=raw.get("last_callback_at"),
        stale_after=raw.get("stale_after"),
        updated_at=_text(
            _first_present(raw, "updatedAt", "updated_at", "last_execution_update")
        )
        or utc_now(),
    )


def _upsert_import_project(conn: sqlite3.Connection, project: ProjectRecord) -> None:
    conn.execute(
        """INSERT INTO projects(project_id,project_name,project_dir,notion_page_url,notion_page_id,origin_idea_status,created_at,updated_at)
        VALUES (?,?,?,?,?,?,?,?)
        ON CONFLICT(project_id) DO UPDATE SET
            project_name=excluded.project_name,
            project_dir=COALESCE(NULLIF(projects.project_dir,''), excluded.project_dir),
            notion_page_url=COALESCE(NULLIF(excluded.notion_page_url,''), projects.notion_page_url),
            notion_page_id=COALESCE(NULLIF(excluded.notion_page_id,''), projects.notion_page_id),
            origin_idea_status=COALESCE(NULLIF(excluded.origin_idea_status,''), projects.origin_idea_status),
            updated_at=excluded.updated_at
        WHERE excluded.updated_at >= projects.updated_at""",
        (
            project.project_id,
            project.project_name,
            project.project_dir,
            project.notion_page_url,
            project.notion_page_id,
            project.origin_idea_status,
            project.created_at,
            project.updated_at,
        ),
    )


def _existing_queue_row_for_import(
    conn: sqlite3.Connection, project_id: str
) -> dict[str, Any] | None:
    existing_row = conn.execute(
        "SELECT status,current_run_id,current_session_id,last_run_state,last_event_type,next_action_hint,manual_review_required,blocked_reason,last_error,last_result_summary,last_dispatch_at,last_callback_at,stale_after,updated_at FROM queue_items WHERE project_id=?",
        (project_id,),
    ).fetchone()
    return dict(existing_row) if existing_row else None


def _preserve_active_runtime_on_import(
    qi: QueueItemRecord,
    existing_queue: dict[str, Any],
    raw: dict[str, Any],
) -> None:
    existing_run_id = _text(existing_queue.get("current_run_id"))
    incoming_run_id = _text(raw.get("current_run_id"))
    preserve_active_runtime = bool(
        _text(existing_queue["status"]) in ACTIVE_STATUSES
        and (
            not existing_run_id
            or incoming_run_id != existing_run_id
            or qi.status.value not in ACTIVE_STATUSES
        )
    )
    if not preserve_active_runtime:
        return
    qi.status = QueueStatus(_text(existing_queue["status"]))
    qi.current_run_id = existing_run_id
    qi.current_session_id = _text(existing_queue["current_session_id"])
    qi.last_run_state = _text(existing_queue["last_run_state"])
    qi.last_event_type = _text(existing_queue["last_event_type"])
    qi.next_action_hint = _text(existing_queue["next_action_hint"]) or "await_callback"
    qi.manual_review_required = _bool(existing_queue["manual_review_required"])
    qi.blocked_reason = _text(existing_queue["blocked_reason"])
    qi.last_error = _text(existing_queue["last_error"])
    qi.last_result_summary = _text(existing_queue["last_result_summary"])
    qi.last_dispatch_at = existing_queue["last_dispatch_at"]
    qi.last_callback_at = existing_queue["last_callback_at"]
    qi.stale_after = existing_queue["stale_after"]


def _upsert_import_queue_item(conn: sqlite3.Connection, qi: QueueItemRecord) -> None:
    conn.execute(
        """INSERT OR REPLACE INTO queue_items(project_id,status,selection_rank,dispatch_priority,auto_continue,continue_count,max_continues,retry_count,max_retries,current_run_id,current_session_id,last_run_state,last_event_type,next_action_hint,manual_review_required,blocked_reason,last_error,last_result_summary,machine_target,model,sandbox,last_dispatch_at,last_callback_at,stale_after,updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            qi.project_id,
            qi.status.value,
            qi.selection_rank,
            qi.dispatch_priority,
            int(qi.auto_continue),
            qi.continue_count,
            qi.max_continues,
            qi.retry_count,
            qi.max_retries,
            qi.current_run_id,
            qi.current_session_id,
            qi.last_run_state,
            qi.last_event_type,
            qi.next_action_hint,
            int(qi.manual_review_required),
            qi.blocked_reason,
            qi.last_error,
            qi.last_result_summary,
            qi.machine_target,
            qi.model,
            qi.sandbox,
            qi.last_dispatch_at,
            qi.last_callback_at,
            qi.stale_after,
            qi.updated_at,
        ),
    )


def _import_queue_row(conn: sqlite3.Connection, raw: dict[str, Any]) -> tuple[int, int]:
    project_id = _text(raw.get("project_id"))
    if not project_id:
        return 0, 0
    project = _project_record_from_import_queue_raw(raw, project_id)
    qi = _queue_item_record_from_import_raw(raw, project_id)
    _upsert_import_project(conn, project)
    projects = 1
    existing_queue = _existing_queue_row_for_import(conn, project_id)
    if existing_queue and _is_older_timestamp(
        qi.updated_at, existing_queue.get("updated_at")
    ):
        return projects, 0
    if existing_queue:
        _preserve_active_runtime_on_import(qi, existing_queue, raw)
    _upsert_import_queue_item(conn, qi)
    return projects, 1


def _paper_status_from_import_raw(raw: dict[str, Any]) -> str:
    status = _text(raw.get("paper_status")) or PaperStatus.DRAFT_REVIEW.value
    if status not in PaperStatus._value2member_map_:
        return PaperStatus.DRAFT_REVIEW.value
    return status


def _ensure_import_project_for_paper(
    conn: sqlite3.Connection, raw: dict[str, Any], project_id: str
) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO projects(project_id,project_name,project_dir,notion_page_url,notion_page_id,origin_idea_status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)",
        (
            project_id,
            _text(raw.get("project_name")) or project_id,
            _text(raw.get("project_dir")),
            _text(raw.get("notion_page_url")),
            _text(raw.get("notion_page_id"))
            or _notion_page_id_from_url(_text(raw.get("notion_page_url"))),
            "unknown",
            utc_now(),
            utc_now(),
        ),
    )


def _import_paper_row(conn: sqlite3.Connection, raw: dict[str, Any]) -> int:
    paper_id = _text(raw.get("paper_id"))
    project_id = _text(raw.get("project_id"))
    if not paper_id or not project_id:
        return 0
    _ensure_import_project_for_paper(conn, raw, project_id)
    status = _paper_status_from_import_raw(raw)
    existing_paper = conn.execute(
        "SELECT project_id, run_id, paper_type, updated_at FROM papers WHERE paper_id=?",
        (paper_id,),
    ).fetchone()
    if _paper_identity_conflicts(
        existing_paper,
        {
            "project_id": project_id,
            "run_id": _text(raw.get("run_id")),
            "paper_type": _text(raw.get("paper_type")) or "arxiv_draft",
        },
    ):
        raise IdempotencyConflict(
            f"paper id {paper_id!r} was reused with different paper identity"
        )
    if existing_paper and _is_older_timestamp(
        raw.get("updated_at"), existing_paper["updated_at"]
    ):
        return 0
    conn.execute(
        """INSERT OR REPLACE INTO papers(paper_id,project_id,run_id,paper_type,paper_status,draft_markdown_path,draft_latex_path,evidence_bundle_path,claim_ledger_path,manifest_path,generated_at,updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            paper_id,
            project_id,
            _text(raw.get("run_id")),
            _text(raw.get("paper_type")) or "arxiv_draft",
            status,
            _text(raw.get("draft_markdown_path")),
            _text(raw.get("draft_latex_path")),
            _text(raw.get("evidence_bundle_path")),
            _text(raw.get("claim_ledger_path")),
            _text(raw.get("manifest_path")),
            _text(raw.get("generated_at")) or utc_now(),
            _text(raw.get("updated_at")) or utc_now(),
        ),
    )
    return 1


def _slug_id(value: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "-" for ch in value).strip("-")[:80]


def _notion_prop(raw: dict[str, Any], *names: str) -> Any:
    candidates = []
    for name in names:
        candidates.extend(
            [
                name,
                f"property_{name.lower().replace(' ', '_')}",
                name.lower().replace(" ", "_"),
            ]
        )
    return _first_present(raw, *candidates)


def _notion_title(raw: dict[str, Any]) -> str:
    return (
        _text(_notion_prop(raw, "Idea", "name", "title"))
        or _text(raw.get("name"))
        or _text(raw.get("title"))
    )


def _notion_status(raw: dict[str, Any]) -> str:
    return _text(_notion_prop(raw, "Status"))


def _notion_url(raw: dict[str, Any]) -> str:
    return _text(_first_present(raw, "url", "notion_page_url", "public_url"))


def _notion_page_id_from_url(url: str) -> str:
    compact = _text(url).replace("-", "")
    matches = re.findall(r"[0-9a-fA-F]{32}", compact)
    return matches[-1].lower() if matches else ""


def _notion_page_id(raw: dict[str, Any]) -> str:
    return _text(
        _first_present(raw, "id", "page_id", "notion_page_id")
    ) or _notion_page_id_from_url(_notion_url(raw))


def _notion_intake_row_result(
    raw: dict[str, Any],
    *,
    include_statuses: set[str],
    default_machine_target: str,
    workload_machine_targets: dict[str, str] | None,
    default_model: str,
    default_sandbox: str,
    source: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    title = _notion_title(raw)
    status = _notion_status(raw).lower()
    page_id = _notion_page_id(raw)
    page_url = _notion_url(raw)
    if not title:
        return None, {"reason": MISSING_TITLE_REASON, "row": raw}
    if include_statuses and not status:
        return None, {
            "reason": "missing status",
            "title": title,
            "status": status,
            "page_id": page_id,
        }
    if include_statuses and status not in include_statuses:
        return None, {
            "reason": f"status {status!r} not included",
            "title": title,
            "status": status,
            "page_id": page_id,
        }
    project_id = (
        _slug_id(page_id.replace("-", "")) if page_id else f"notion-{_slug_id(title)}"
    )
    if not project_id:
        return None, {
            "reason": "missing project id",
            "title": title,
            "page_id": page_id,
        }
    rank = _priority_rank(raw)
    routing = route_machine_target(
        raw,
        default_machine_target=default_machine_target,
        workload_machine_targets=workload_machine_targets,
    )
    return {
        "project_id": project_id,
        "project_name": title,
        "project_dir": project_id,
        "notion_page_url": page_url,
        "notion_page_id": page_id,
        "origin_idea_status": status,
        "status": QueueStatus.QUEUED.value,
        "selection_rank": rank,
        "dispatch_priority": rank,
        "next_action_hint": "controller_review",
        "machine_target": routing["machine_target"],
        "workload_class": routing["workload_class"],
        "routing_reason": routing["routing_reason"],
        "model": default_model,
        "sandbox": default_sandbox,
        "source_kind": source or "notion",
        "source_row": raw,
    }, None


_NOTION_EXECUTION_STATE_MAP = {
    QueueStatus.QUEUED.value: "queued",
    QueueStatus.DISPATCHING.value: "running",
    QueueStatus.RUNNING.value: "running",
    QueueStatus.AWAITING_WAKE.value: "waiting",
    QueueStatus.WAKE_RECEIVED.value: "waiting",
    QueueStatus.RECONCILING.value: "waiting",
    QueueStatus.COMPLETED.value: "completed",
    QueueStatus.PAUSED.value: "blocked",
    QueueStatus.CANCELED.value: "completed",
    QueueStatus.DISPATCH_ERROR.value: "failed",
    QueueStatus.BLOCKED.value: "blocked",
    QueueStatus.NEEDS_REVIEW.value: "blocked",
}


def _queue_row_merged_with_paper(
    row: dict[str, Any], paper_by_project: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    paper = paper_by_project.get(row.get("project_id")) or {}
    return {
        **row,
        "paper_id": paper.get("paper_id") or "",
        "paper_status": paper.get("paper_status") or "",
        "paper_type": paper.get("paper_type") or "",
        "draft_markdown_path": paper.get("draft_markdown_path") or "",
        "paper_updated_at": paper.get("updated_at") or "",
    }


def _notion_execution_blocked_reason(row: dict[str, Any], execution_state: str) -> str:
    return (
        row.get("blocked_reason")
        or (
            row.get("last_result_summary")
            if execution_state in {"blocked", "failed"}
            else ""
        )
        or ""
    )


def _notion_manual_review_required(row: dict[str, Any]) -> str:
    return "__YES__" if _bool(row.get("manual_review_required")) else "__NO__"


def _notion_execution_core_properties(
    row: dict[str, Any], *, execution_state: str, blocked_reason: str
) -> dict[str, Any]:
    return {
        "Execution State": execution_state,
        "Current Run ID": _row_or(row, "current_run_id"),
        "Next Action": _row_or(row, "next_action_hint"),
        "Blocked Reason": blocked_reason,
        "Last Execution Update": _row_or(row, "updated_at", utc_now()),
        "Execution Summary": _row_or(row, "last_result_summary"),
    }


def _notion_execution_enoch_properties(row: dict[str, Any]) -> dict[str, Any]:
    paper_updated_at = _row_or(row, "paper_updated_at")
    return {
        "Enoch Project ID": _row_or(row, "project_id"),
        "Enoch Queue Status": _row_or(row, "status"),
        "Enoch Last Run State": _row_or(row, "last_run_state"),
        "Enoch Last Event Type": _row_or(row, "last_event_type"),
        "Enoch Next Action Hint": _row_or(row, "next_action_hint"),
        "Enoch Project Dir": _row_or(row, "project_dir"),
        "Enoch Current Session ID": _row_or(row, "current_session_id"),
        "Enoch Last Result Summary": _row_or(row, "last_result_summary"),
        "Enoch Last Error": _row_or(row, "last_error"),
        "Enoch Manual Review Required": _notion_manual_review_required(row),
        "Enoch Dispatch Priority": _row_or(row, "dispatch_priority", 0),
        "Enoch Selection Rank": _row_or(row, "selection_rank", 0),
        "Enoch Paper ID": _row_or(row, "paper_id"),
        "Enoch Paper Status": _row_or(row, "paper_status"),
        "Enoch Paper Type": _row_or(row, "paper_type"),
        "Enoch Paper Markdown Path": _row_or(row, "draft_markdown_path"),
        "Enoch Paper Updated At": paper_updated_at,
        "Enoch Paper Updated At ISO": paper_updated_at,
    }


def _notion_execution_update_properties(
    row: dict[str, Any], *, execution_state: str, blocked_reason: str
) -> dict[str, Any]:
    return {
        **_notion_execution_core_properties(
            row, execution_state=execution_state, blocked_reason=blocked_reason
        ),
        **_notion_execution_enoch_properties(row),
    }


def _notion_execution_update_row(
    row: dict[str, Any], state_map: dict[str, str]
) -> dict[str, Any] | None:
    page_url = row.get("notion_page_url") or ""
    if not page_url:
        return None
    execution_state = state_map.get(row.get("status") or "", "blocked")
    blocked_reason = _notion_execution_blocked_reason(row, execution_state)
    return {
        "project_id": row.get("project_id") or "",
        "page_id": row.get("notion_page_id") or _notion_page_id_from_url(page_url),
        "notion_page_url": page_url,
        "properties": _notion_execution_update_properties(
            row,
            execution_state=execution_state,
            blocked_reason=blocked_reason,
        ),
    }


def _priority_rank(raw: dict[str, Any]) -> int:
    priority = _text(_notion_prop(raw, "Priority")).lower()
    if priority == "high":
        return 10
    if priority == "medium":
        return 50
    if priority == "low":
        return 90
    novelty = _int(_notion_prop(raw, "Novelty Score"), 0)
    confidence = _int(_notion_prop(raw, "Confidence"), 0)
    if novelty or confidence:
        return max(1, 100 - max(novelty, confidence))
    return 50


def _notion_intake_skip_row(
    raw: dict[str, Any],
    *,
    title: str,
    status: str,
    page_id: str,
    include_statuses: set[str],
) -> dict[str, Any] | None:
    if not title:
        return {"reason": MISSING_TITLE_REASON, "row": raw}
    if include_statuses and not status:
        return {
            "reason": "missing status",
            "title": title,
            "status": status,
            "page_id": page_id,
        }
    if include_statuses and status not in include_statuses:
        return {
            "reason": f"status {status!r} not included",
            "title": title,
            "status": status,
            "page_id": page_id,
        }
    return None


def _notion_intake_candidate(
    raw: dict[str, Any],
    request: NotionIntakeRequest,
    *,
    title: str,
    status: str,
    page_id: str,
    page_url: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    project_id = (
        _slug_id(page_id.replace("-", "")) if page_id else f"notion-{_slug_id(title)}"
    )
    if not project_id:
        return None, {
            "reason": "missing project id",
            "title": title,
            "page_id": page_id,
        }
    routing = route_machine_target(
        raw,
        default_machine_target=request.default_machine_target,
        workload_machine_targets=request.workload_machine_targets,
    )
    priority = _priority_rank(raw)
    return (
        {
            "project_id": project_id,
            "project_name": title,
            "project_dir": project_id,
            "notion_page_url": page_url,
            "notion_page_id": page_id,
            "origin_idea_status": status,
            "status": QueueStatus.QUEUED.value,
            "selection_rank": priority,
            "dispatch_priority": priority,
            "next_action_hint": "controller_review",
            "machine_target": routing["machine_target"],
            "workload_class": routing["workload_class"],
            "routing_reason": routing["routing_reason"],
            "model": request.default_model,
            "sandbox": request.default_sandbox,
            "source_row": raw,
        },
        None,
    )


def _idea_title(raw: dict[str, Any]) -> str:
    return _text(
        _first_present(raw, "title", "idea", "name", "project_name", "property_idea")
    )


def _idea_status(raw: dict[str, Any]) -> str:
    return _text(
        _first_present(
            raw, "idea_status", "status", "origin_idea_status", "property_status"
        )
    )


def _idea_id(raw: dict[str, Any], title: str) -> str:
    provided = _text(_first_present(raw, "idea_id", "project_id", "id"))
    if provided:
        return _slug_id(provided)
    return f"idea-{_slug_id(title)}" if title else ""


def _collect_idea_intake_candidates(
    request: IdeaIntakeRequest,
    include_statuses: set[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    candidates: list[dict[str, Any]] = []
    skipped_rows: list[dict[str, Any]] = []
    for raw in request.ideas:
        title = _idea_title(raw)
        origin_status = _idea_status(raw).lower()
        status = origin_status or "exploring"
        if not title:
            skipped_rows.append({"reason": MISSING_TITLE_REASON, "row": raw})
            continue
        if include_statuses and status and status not in include_statuses:
            skipped_rows.append(
                {
                    "reason": f"status {status!r} not included",
                    "title": title,
                    "status": status,
                    "idea_id": _text(
                        _first_present(raw, "idea_id", "project_id", "id")
                    ),
                }
            )
            continue
        project_id = _idea_id(raw, title)
        if not project_id:
            skipped_rows.append({"reason": "missing idea id", "title": title})
            continue
        rank = _int(
            _first_present(raw, "selection_rank", "dispatch_priority"),
            _priority_rank(raw),
        )
        dispatch_priority = _int(
            _first_present(raw, "dispatch_priority", "selection_rank"), rank
        )
        routing = route_machine_target(
            raw,
            default_machine_target=request.default_machine_target,
            workload_machine_targets=request.workload_machine_targets,
        )
        candidates.append(
            {
                "project_id": project_id,
                "idea_id": project_id,
                "project_name": title,
                "project_dir": project_id,
                "origin_idea_status": origin_status,
                "status": QueueStatus.QUEUED.value,
                "selection_rank": rank,
                "dispatch_priority": dispatch_priority,
                "next_action_hint": "controller_review",
                "machine_target": routing["machine_target"],
                "workload_class": routing["workload_class"],
                "routing_reason": routing["routing_reason"],
                "model": _text(_first_present(raw, "model", "default_model"))
                or request.default_model,
                "sandbox": _text(_first_present(raw, "sandbox", "default_sandbox"))
                or request.default_sandbox,
                "source_kind": _text(raw.get("source_kind"))
                or request.source
                or "supabase_native",
                "source_row": raw,
            }
        )
    return candidates, skipped_rows


REVIEW_CHECKLIST_DEFINITION = (
    ("artifact_readability", "Artifact readability", True),
    ("title_abstract_quality", "Title/abstract quality", True),
    ("claim_evidence_alignment", "Claim/evidence alignment", True),
    ("novelty_significance", "Novelty/significance", True),
    ("reproducibility", "Reproducibility", True),
    ("limitations_ethics", "Limitations/ethics", True),
    ("formatting_quality", "Formatting quality", True),
    ("target_venue_fit", "Target venue/application fit", False),
    ("final_human_approval", "Automated finalization approval", True),
)
REVIEW_CHECKLIST_ITEMS = tuple(
    item_id for item_id, _label, _required in REVIEW_CHECKLIST_DEFINITION
)
CHECKLIST_ITEM_STATUSES = {"pending", "pass", "fail", "accepted_risk", "not_applicable"}
_FINALIZATION_PACKAGE_ARTIFACT_FIELDS = (
    "draft_markdown_path",
    "draft_latex_path",
    "evidence_bundle_path",
    "claim_ledger_path",
    "manifest_path",
)
_AUTOMATED_FINALIZATION_BLOCKED_STATUSES = frozenset(
    {
        ReviewStatus.BLOCKED.value,
        ReviewStatus.CHANGES_REQUESTED.value,
        ReviewStatus.IN_REVIEW.value,
        ReviewStatus.REJECTED.value,
        ReviewStatus.UNREVIEWED.value,
    }
)
SYSTEM_REVIEW_STATUSES = {
    ReviewStatus.QUEUED.value,
    ReviewStatus.UNREVIEWED.value,
    ReviewStatus.TRIAGE_READY.value,
}
ALLOWED_STATUS_TRANSITIONS = {
    ReviewStatus.QUEUED.value: {
        ReviewStatus.CLAIMED.value,
        ReviewStatus.BLOCKED.value,
        ReviewStatus.DEFERRED.value,
        ReviewStatus.REJECTED.value,
    },
    ReviewStatus.CLAIMED.value: {
        ReviewStatus.QUEUED.value,
        ReviewStatus.BLOCKED.value,
        ReviewStatus.FINALIZED.value,
        ReviewStatus.REJECTED.value,
    },
    ReviewStatus.BLOCKED.value: {
        ReviewStatus.QUEUED.value,
        ReviewStatus.CLAIMED.value,
        ReviewStatus.REJECTED.value,
    },
    ReviewStatus.DEFERRED.value: {
        ReviewStatus.QUEUED.value,
        ReviewStatus.REJECTED.value,
    },
    # Legacy compatibility transitions. New automation should prefer queued/claimed.
    ReviewStatus.UNREVIEWED.value: {
        ReviewStatus.QUEUED.value,
        ReviewStatus.TRIAGE_READY.value,
        ReviewStatus.BLOCKED.value,
        ReviewStatus.REJECTED.value,
    },
    ReviewStatus.TRIAGE_READY.value: {
        ReviewStatus.QUEUED.value,
        ReviewStatus.CLAIMED.value,
        ReviewStatus.IN_REVIEW.value,
        ReviewStatus.BLOCKED.value,
        ReviewStatus.REJECTED.value,
    },
    ReviewStatus.IN_REVIEW.value: {
        ReviewStatus.CLAIMED.value,
        ReviewStatus.CHANGES_REQUESTED.value,
        ReviewStatus.BLOCKED.value,
        ReviewStatus.APPROVED_FOR_FINALIZATION.value,
        ReviewStatus.REJECTED.value,
    },
    ReviewStatus.CHANGES_REQUESTED.value: {
        ReviewStatus.BLOCKED.value,
        ReviewStatus.QUEUED.value,
        ReviewStatus.CLAIMED.value,
        ReviewStatus.IN_REVIEW.value,
        ReviewStatus.REJECTED.value,
    },
    ReviewStatus.APPROVED_FOR_FINALIZATION.value: {
        ReviewStatus.FINALIZED.value,
        ReviewStatus.CLAIMED.value,
        ReviewStatus.IN_REVIEW.value,
    },
    ReviewStatus.FINALIZED.value: set(),
    ReviewStatus.REJECTED.value: set(),
}


def _json_list(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError:
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def _concrete_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_text(item) for item in value if _text(item)]


def _json_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if value in (None, ""):
        return {}
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError:
        return {}
    return dict(parsed) if isinstance(parsed, dict) else {}


def _progress_for_items(items: list[dict[str, Any]]) -> dict[str, int]:
    counts = {
        "passed": 0,
        "accepted_risk": 0,
        "failed": 0,
        "pending": 0,
        "not_applicable": 0,
        "total": len(items),
    }
    for item in items:
        status = _text(item.get("status")) or "pending"
        if status == "pass":
            counts["passed"] += 1
        elif status == "fail":
            counts["failed"] += 1
        elif status == "accepted_risk":
            counts["accepted_risk"] += 1
        elif status == "not_applicable":
            counts["not_applicable"] += 1
        else:
            counts["pending"] += 1
    return counts


def _default_review_checklist() -> dict[str, Any]:
    items = [
        _checklist_item_record(item_id, label, required, {})
        for item_id, label, required in REVIEW_CHECKLIST_DEFINITION
    ]
    return {
        "version": "publication_review_v1",
        "items": items,
        "accepted_risks": [],
        "progress": _progress_for_items(items),
    }


def _checklist_status(existing: dict[str, Any]) -> str:
    status = _text(existing.get("status")) or "pending"
    if status not in CHECKLIST_ITEM_STATUSES:
        return "pending"
    return status


def _checklist_items_by_id(raw: dict[str, Any]) -> dict[str, dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    if isinstance(raw.get("items"), list):
        for item in raw.get("items") or []:
            if isinstance(item, dict) and _text(item.get("id")):
                by_id[_text(item.get("id"))] = item
        return by_id
    for item_id, value in raw.items():
        by_id[_text(item_id)] = {
            "id": _text(item_id),
            "status": _text(value) or "pending",
        }
    return by_id


def _checklist_item_record(
    item_id: str, label: str, required: bool, existing: dict[str, Any]
) -> dict[str, Any]:
    return {
        "id": item_id,
        "label": label,
        "required": required,
        "status": _checklist_status(existing),
        "note": _text(existing.get("note")),
        "updated_at": _text(existing.get("updated_at")),
        "updated_by": _text(existing.get("updated_by")),
    }


def _normalized_review_checklist_items(
    by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        _checklist_item_record(item_id, label, required, by_id.get(item_id, {}))
        for item_id, label, required in REVIEW_CHECKLIST_DEFINITION
    ]


def _normalize_review_checklist(checklist: dict[str, Any] | None) -> dict[str, Any]:
    raw = checklist or {}
    items = _normalized_review_checklist_items(_checklist_items_by_id(raw))
    accepted_risks = (
        raw.get("accepted_risks") if isinstance(raw.get("accepted_risks"), list) else []
    )
    return {
        "version": "publication_review_v1",
        "items": items,
        "accepted_risks": accepted_risks,
        "progress": _progress_for_items(items),
    }


def _checklist_progress(checklist: dict[str, Any]) -> dict[str, int]:
    return _normalize_review_checklist(checklist).get(
        "progress", _progress_for_items([])
    )


def _audit_rows(source_audit_path: str) -> dict[str, dict[str, Any]]:
    if not source_audit_path:
        return {}
    path = _expanduser_or_none(source_audit_path)
    if path is None:
        return {}
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    candidates = payload.get("papers") if isinstance(payload, dict) else None
    if candidates is None and isinstance(payload, dict):
        candidates = payload.get("rows") or payload.get("paper_rows")
    if not isinstance(candidates, list):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for row in candidates:
        if isinstance(row, dict):
            paper_id = _text(row.get("paper_id"))
            if paper_id:
                out[paper_id] = row
    return out


def _readiness_passed(audit: dict[str, Any]) -> bool:
    return bool(
        audit.get("ready") is True
        or audit.get("ok") is True
        or audit.get("semantic_ok") is True
        or audit.get("readiness_passed") is True
    )


_REVIEW_REQUIRED_JSON = (
    "evidence_bundle_path",
    "claim_ledger_path",
    "manifest_path",
)
_BLOCKING_QUEUE_STATUSES = frozenset(
    {
        QueueStatus.BLOCKED.value,
        QueueStatus.NEEDS_REVIEW.value,
        QueueStatus.DISPATCH_ERROR.value,
    }
)


def _paper_status_review_score(paper_status: str) -> tuple[int, str | None]:
    if paper_status == PaperStatus.PUBLICATION_DRAFT.value:
        return 100, "publication_draft +100"
    if paper_status == PaperStatus.DRAFT_REVIEW.value:
        return 40, "draft_review +40"
    return 0, None


def _audit_review_adjustment(
    audit: dict[str, Any], missing: list[str]
) -> tuple[int, list[str], str | None]:
    if _readiness_passed(audit):
        return 20, missing, "readiness audit passed +20"
    updated = list(missing)
    if not audit:
        updated.append("readiness_audit")
    return 0, updated, None


def _required_json_review_adjustment(
    paper: dict[str, Any], missing: list[str]
) -> tuple[int, list[str], str | None]:
    if all(_text(paper.get(name)) for name in _REVIEW_REQUIRED_JSON):
        return 10, missing, "evidence/claim/manifest paths present +10"
    updated = list(missing)
    for name in _REVIEW_REQUIRED_JSON:
        if not _text(paper.get(name)):
            updated.append(name)
    return 0, updated, None


def _draft_paths_review_score(paper: dict[str, Any]) -> tuple[int, str | None]:
    if _text(paper.get("draft_markdown_path")) and _text(paper.get("draft_latex_path")):
        return 5, "draft markdown/latex paths present +5"
    return 0, None


def _queue_blocks_review(queue_item: dict[str, Any]) -> bool:
    return bool(
        _text(queue_item.get("blocked_reason"))
        or _text(queue_item.get("status")) in _BLOCKING_QUEUE_STATUSES
        or bool(queue_item.get("manual_review_required"))
    )


def _review_rank_bucket(score: int) -> str:
    if score < 0:
        return "blocked"
    if score >= 100:
        return "ready"
    return "review"


def _review_rank_tiebreaker(paper: dict[str, Any], paper_status: str) -> str:
    status_priority = {
        PaperStatus.PUBLICATION_DRAFT.value: 0,
        PaperStatus.DRAFT_REVIEW.value: 1,
    }.get(paper_status, 9)
    return (
        f"{status_priority}:{_text(paper.get('updated_at'))}:"
        f"{_text(paper.get('paper_id'))}"
    )


def _review_rank(
    paper: dict[str, Any],
    queue_item: dict[str, Any] | None,
    audit: dict[str, Any],
    initial_missing: list[str],
) -> tuple[int, list[str], list[str], str, str]:
    reasons: list[str] = []
    missing = list(dict.fromkeys(initial_missing))
    score = 0
    paper_status = _text(paper.get("paper_status"))

    status_score, status_reason = _paper_status_review_score(paper_status)
    score += status_score
    if status_reason:
        reasons.append(status_reason)

    audit_score, missing, audit_reason = _audit_review_adjustment(audit, missing)
    score += audit_score
    if audit_reason:
        reasons.append(audit_reason)

    paths_score, missing, paths_reason = _required_json_review_adjustment(
        paper, missing
    )
    score += paths_score
    if paths_reason:
        reasons.append(paths_reason)

    draft_score, draft_reason = _draft_paths_review_score(paper)
    score += draft_score
    if draft_reason:
        reasons.append(draft_reason)

    if _queue_blocks_review(queue_item or {}):
        score -= 100
        reasons.append("blocked/manual-action queue signal -100")

    material_missing = sorted(set(missing))
    if material_missing:
        score -= 25
        reasons.append("material ranking inputs missing -25")

    tiebreaker = _review_rank_tiebreaker(paper, paper_status)
    bucket = _review_rank_bucket(score)
    return score, reasons, material_missing, tiebreaker, bucket


def _bool(value: Any) -> bool:
    return value is True or value in {1, "1", "true", "True", "TRUE", "yes", "YES"}


def _int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


_EVENT_PAGE_ORDER_BY = {
    "recent": "event_id DESC",
    "oldest": "event_id ASC",
    "type": "event_type ASC, event_id DESC",
    "entity": "entity_type ASC, entity_id ASC, event_id DESC",
}


def _event_page_filter_clauses(
    *,
    event_id: str = "",
    entity_type: str = "",
    entity_id: str = "",
    event_type: str = "",
    search: str = "",
    cursor: str = "",
) -> tuple[list[str], list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    event_id_int = _int(event_id, 0)
    if event_id_int > 0:
        clauses.append("event_id = ?")
        params.append(event_id_int)
    if entity_type:
        clauses.append("entity_type = ?")
        params.append(entity_type)
    if entity_id:
        clauses.append("entity_id = ?")
        params.append(entity_id)
    if event_type:
        clauses.append("event_type = ?")
        params.append(event_type)
    if search:
        clauses.append("(event_type LIKE ? OR entity_id LIKE ? OR payload_json LIKE ?)")
        needle = f"%{search}%"
        params.extend([needle, needle, needle])
    cursor_id = _int(cursor, 0)
    if cursor_id > 0:
        clauses.append("event_id < ?")
        params.append(cursor_id)
    return clauses, params


def _event_page_order_by(sort: str) -> str:
    return _EVENT_PAGE_ORDER_BY.get(sort, "event_id DESC")


def _event_page_attach_payload_fields(
    item: dict[str, Any], *, include_payload: bool
) -> None:
    payload_json = item.pop("payload_json", "{}")
    item.pop("payload_hash", None)
    if include_payload:
        item["payload"] = json.loads(payload_json)
        return
    try:
        payload = json.loads(payload_json)
        item["payload_summary"] = {
            "keys": sorted(payload.keys())[:12] if isinstance(payload, dict) else [],
            "bytes": len(payload_json.encode("utf-8")),
        }
    except json.JSONDecodeError:
        item["payload_summary"] = {
            "keys": [],
            "bytes": len(payload_json.encode("utf-8")),
            "invalid_json": True,
        }


class ControlPlaneStore:
    def __init__(self, path: Path) -> None:
        self.path = path.expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS control_flags(
                    singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
                    queue_paused INTEGER NOT NULL,
                    maintenance_mode INTEGER NOT NULL,
                    pause_reason TEXT NOT NULL,
                    paused_at TEXT,
                    paused_by TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events(
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    event_type TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS projects(
                    project_id TEXT PRIMARY KEY,
                    project_name TEXT NOT NULL,
                    project_dir TEXT NOT NULL,
                    notion_page_url TEXT NOT NULL,
                    notion_page_id TEXT NOT NULL DEFAULT '',
                    origin_idea_status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS queue_items(
                    project_id TEXT PRIMARY KEY REFERENCES projects(project_id),
                    status TEXT NOT NULL,
                    selection_rank INTEGER NOT NULL,
                    dispatch_priority INTEGER NOT NULL,
                    auto_continue INTEGER NOT NULL,
                    continue_count INTEGER NOT NULL,
                    max_continues INTEGER NOT NULL,
                    retry_count INTEGER NOT NULL,
                    max_retries INTEGER NOT NULL,
                    current_run_id TEXT NOT NULL,
                    current_session_id TEXT NOT NULL,
                    last_run_state TEXT NOT NULL,
                    last_event_type TEXT NOT NULL,
                    next_action_hint TEXT NOT NULL,
                    manual_review_required INTEGER NOT NULL,
                    blocked_reason TEXT NOT NULL,
                    last_error TEXT NOT NULL,
                    last_result_summary TEXT NOT NULL,
                    machine_target TEXT NOT NULL,
                    model TEXT NOT NULL,
                    sandbox TEXT NOT NULL,
                    last_dispatch_at TEXT,
                    last_callback_at TEXT,
                    stale_after TEXT,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS runs(
                    run_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(project_id),
                    session_id TEXT NOT NULL,
                    state TEXT NOT NULL,
                    dispatch_mode TEXT NOT NULL,
                    started_at TEXT,
                    ended_at TEXT,
                    last_callback_at TEXT,
                    gate_state TEXT NOT NULL,
                    current_activity TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS papers(
                    paper_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(project_id),
                    run_id TEXT NOT NULL,
                    paper_type TEXT NOT NULL,
                    paper_status TEXT NOT NULL,
                    draft_markdown_path TEXT NOT NULL,
                    draft_latex_path TEXT NOT NULL,
                    evidence_bundle_path TEXT NOT NULL,
                    claim_ledger_path TEXT NOT NULL,
                    manifest_path TEXT NOT NULL,
                    generated_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS paper_review_items(
                    paper_id TEXT PRIMARY KEY REFERENCES papers(paper_id),
                    review_status TEXT NOT NULL,
                    reviewer TEXT NOT NULL,
                    blocker TEXT NOT NULL,
                    claimed_at TEXT NOT NULL DEFAULT '',
                    checklist_json TEXT NOT NULL,
                    rank_score INTEGER NOT NULL,
                    rank_reasons_json TEXT NOT NULL,
                    missing_signals_json TEXT NOT NULL,
                    rank_tiebreaker TEXT NOT NULL,
                    source_audit_path TEXT NOT NULL,
                    finalization_package_path TEXT NOT NULL,
                    finalized_at TEXT NOT NULL,
                    decision_summary TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_paper_review_items_status
                    ON paper_review_items(review_status, rank_score DESC, updated_at DESC);
                CREATE TABLE IF NOT EXISTS corpus_imports(
                    corpus_import_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    paper_id TEXT NOT NULL REFERENCES papers(paper_id),
                    corpus_repo TEXT NOT NULL DEFAULT '',
                    artifact_slug TEXT NOT NULL DEFAULT '',
                    commit_sha TEXT NOT NULL DEFAULT '',
                    manifest_path TEXT NOT NULL DEFAULT '',
                    manifest_hash TEXT NOT NULL DEFAULT '',
                    source_record_fingerprint TEXT NOT NULL DEFAULT '',
                    public_artifact_id TEXT NOT NULL DEFAULT '',
                    public_index_path TEXT NOT NULL DEFAULT '',
                    hf_dataset_synced INTEGER NOT NULL DEFAULT 0,
                    hf_dataset_url TEXT NOT NULL DEFAULT '',
                    imported_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(paper_id, corpus_repo)
                );
                CREATE INDEX IF NOT EXISTS idx_corpus_imports_fingerprint
                    ON corpus_imports(source_record_fingerprint);
                CREATE TABLE IF NOT EXISTS dashboard_observations(
                    observation_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    ttl_seconds INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_dashboard_observations_latest
                    ON dashboard_observations(source, scope, observed_at DESC, observation_id DESC);
                """
            )
            conn.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (SCHEMA_VERSION, utc_now()),
            )
            flags = ControlFlags()
            conn.execute(
                """
                INSERT OR IGNORE INTO control_flags(singleton, queue_paused, maintenance_mode, pause_reason, paused_at, paused_by, updated_at)
                VALUES (1, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(flags.queue_paused),
                    int(flags.maintenance_mode),
                    flags.pause_reason,
                    flags.paused_at,
                    flags.paused_by,
                    flags.updated_at,
                ),
            )
            project_columns = {
                row[1] for row in conn.execute("PRAGMA table_info(projects)").fetchall()
            }
            if "notion_page_id" not in project_columns:
                conn.execute(
                    "ALTER TABLE projects ADD COLUMN notion_page_id TEXT NOT NULL DEFAULT ''"
                )
            conn.execute("""UPDATE projects
                SET notion_page_id = lower(replace(substr(notion_page_url, length(notion_page_url) - 31, 32), '-', ''))
                WHERE notion_page_id = ''
                  AND length(replace(substr(notion_page_url, length(notion_page_url) - 31, 32), '-', '')) = 32""")
            review_columns = {
                row[1]
                for row in conn.execute(
                    "PRAGMA table_info(paper_review_items)"
                ).fetchall()
            }
            if "claimed_at" not in review_columns:
                conn.execute(
                    "ALTER TABLE paper_review_items ADD COLUMN claimed_at TEXT NOT NULL DEFAULT ''"
                )

    def _append_event_in_conn(
        self,
        conn: sqlite3.Connection,
        *,
        idempotency_key: str,
        event_type: str,
        entity_type: str,
        entity_id: str,
        payload: dict[str, Any],
    ) -> tuple[int, bool]:
        payload_json = _json(payload)
        payload_hash = _hash(payload)
        row = conn.execute(
            "SELECT event_id, event_type, entity_type, entity_id, payload_hash FROM events WHERE idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()
        if row:
            if (
                row["event_type"] != event_type
                or row["entity_type"] != entity_type
                or row["entity_id"] != entity_id
                or row["payload_hash"] != payload_hash
            ):
                raise IdempotencyConflict(
                    f"idempotency key {idempotency_key!r} was reused with different payload"
                )
            return int(row["event_id"]), False
        cur = conn.execute(
            "INSERT INTO events(idempotency_key,event_type,entity_type,entity_id,payload_json,payload_hash,created_at) VALUES (?,?,?,?,?,?,?)",
            (
                idempotency_key,
                event_type,
                entity_type,
                entity_id,
                payload_json,
                payload_hash,
                utc_now(),
            ),
        )
        return _required_lastrowid(cur, operation="append_event"), True

    def append_event(
        self,
        *,
        idempotency_key: str,
        event_type: str,
        entity_type: str,
        entity_id: str,
        payload: dict[str, Any],
    ) -> tuple[int, bool]:
        with self._connect() as conn:
            return self._append_event_in_conn(
                conn,
                idempotency_key=idempotency_key,
                event_type=event_type,
                entity_type=entity_type,
                entity_id=entity_id,
                payload=payload,
            )

    def event_by_idempotency_key(self, idempotency_key: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT event_id, idempotency_key, event_type, entity_type, entity_id, created_at FROM events WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
        return dict(row) if row else None

    def flags(self) -> ControlFlags:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM control_flags WHERE singleton = 1"
            ).fetchone()
        return ControlFlags(
            queue_paused=bool(row["queue_paused"]),
            maintenance_mode=bool(row["maintenance_mode"]),
            pause_reason=row["pause_reason"],
            paused_at=row["paused_at"],
            paused_by=row["paused_by"],
            updated_at=row["updated_at"],
        )

    def _flags_from_conn(self, conn: sqlite3.Connection) -> ControlFlags:
        row = conn.execute("SELECT * FROM control_flags WHERE singleton = 1").fetchone()
        return ControlFlags(
            queue_paused=bool(row["queue_paused"]),
            maintenance_mode=bool(row["maintenance_mode"]),
            pause_reason=row["pause_reason"],
            paused_at=row["paused_at"],
            paused_by=row["paused_by"],
            updated_at=row["updated_at"],
        )

    def pause(
        self, *, reason: str, paused_by: str, maintenance_mode: bool
    ) -> tuple[ControlFlags, int]:
        now = utc_now()
        with self._connect() as conn:
            conn.execute(
                "UPDATE control_flags SET queue_paused=1, maintenance_mode=?, pause_reason=?, paused_at=?, paused_by=?, updated_at=? WHERE singleton=1",
                (int(maintenance_mode), reason, now, paused_by, now),
            )
            flags = self._flags_from_conn(conn)
            event_id, _ = self._append_event_in_conn(
                conn,
                idempotency_key=f"pause:{now}",
                event_type="control.pause",
                entity_type="control",
                entity_id="queue",
                payload=flags.model_dump(mode="json"),
            )
        return flags, event_id

    def resume(
        self, *, resumed_by: str, maintenance_mode: bool
    ) -> tuple[ControlFlags, int]:
        now = utc_now()
        with self._connect() as conn:
            conn.execute(
                "UPDATE control_flags SET queue_paused=0, maintenance_mode=?, pause_reason='', paused_at=NULL, paused_by=?, updated_at=? WHERE singleton=1",
                (int(maintenance_mode), resumed_by, now),
            )
            flags = self._flags_from_conn(conn)
            event_id, _ = self._append_event_in_conn(
                conn,
                idempotency_key=f"resume:{now}",
                event_type="control.resume",
                entity_type="control",
                entity_id="queue",
                payload=flags.model_dump(mode="json"),
            )
        return flags, event_id

    def import_snapshot(
        self, request: ImportSnapshotRequest
    ) -> tuple[bool, int, int, int]:
        queue_rows = [*request.queue_rows, *_snapshot_rows(request.queue_snapshot)]
        paper_rows = [
            *request.paper_rows,
            *_snapshot_rows(request.paper_snapshot, paper=True),
        ]
        _validate_import_snapshot_rows(queue_rows, paper_rows)
        event_payload = _import_snapshot_event_payload(request, queue_rows, paper_rows)
        projects = queue_items = papers = 0
        with self._connect() as conn:
            _, inserted = self._append_event_in_conn(
                conn,
                idempotency_key=request.idempotency_key,
                event_type="legacy.import_snapshot",
                entity_type="snapshot",
                entity_id=request.source,
                payload=event_payload,
            )
            if not inserted:
                return False, 0, 0, 0
            for raw in queue_rows:
                row_projects, row_queue_items = _import_queue_row(conn, raw)
                projects += row_projects
                queue_items += row_queue_items
            for raw in paper_rows:
                papers += _import_paper_row(conn, raw)
        return inserted, projects, queue_items, papers

    def queue_rows(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT q.*,
                    p.project_name AS project_name,
                    p.project_dir AS project_dir,
                    p.notion_page_url AS notion_page_url,
                    p.notion_page_id AS notion_page_id,
                    p.origin_idea_status AS origin_idea_status,
                    (SELECT pa.paper_id FROM papers pa WHERE pa.project_id = q.project_id AND (pa.run_id = q.current_run_id OR (q.current_run_id = '' AND q.status NOT IN ('awaiting_wake','dispatching','reconciling','running','wake_received'))) ORDER BY pa.updated_at DESC LIMIT 1) AS related_paper_id,
                    (SELECT pa.paper_status FROM papers pa WHERE pa.project_id = q.project_id AND (pa.run_id = q.current_run_id OR (q.current_run_id = '' AND q.status NOT IN ('awaiting_wake','dispatching','reconciling','running','wake_received'))) ORDER BY pa.updated_at DESC LIMIT 1) AS related_paper_status,
                    (SELECT rv.review_status FROM papers pa LEFT JOIN paper_review_items rv USING(paper_id) WHERE pa.project_id = q.project_id AND (pa.run_id = q.current_run_id OR (q.current_run_id = '' AND q.status NOT IN ('awaiting_wake','dispatching','reconciling','running','wake_received'))) ORDER BY pa.updated_at DESC LIMIT 1) AS related_review_status,
                    (SELECT rv.finalization_package_path FROM papers pa LEFT JOIN paper_review_items rv USING(paper_id) WHERE pa.project_id = q.project_id AND (pa.run_id = q.current_run_id OR (q.current_run_id = '' AND q.status NOT IN ('awaiting_wake','dispatching','reconciling','running','wake_received'))) ORDER BY pa.updated_at DESC LIMIT 1) AS related_finalization_package_path,
                    (SELECT pa.draft_markdown_path FROM papers pa WHERE pa.project_id = q.project_id AND (pa.run_id = q.current_run_id OR (q.current_run_id = '' AND q.status NOT IN ('awaiting_wake','dispatching','reconciling','running','wake_received'))) ORDER BY pa.updated_at DESC LIMIT 1) AS related_draft_markdown_path,
                    (SELECT pa.evidence_bundle_path FROM papers pa WHERE pa.project_id = q.project_id AND (pa.run_id = q.current_run_id OR (q.current_run_id = '' AND q.status NOT IN ('awaiting_wake','dispatching','reconciling','running','wake_received'))) ORDER BY pa.updated_at DESC LIMIT 1) AS related_evidence_bundle_path,
                    (SELECT pa.claim_ledger_path FROM papers pa WHERE pa.project_id = q.project_id AND (pa.run_id = q.current_run_id OR (q.current_run_id = '' AND q.status NOT IN ('awaiting_wake','dispatching','reconciling','running','wake_received'))) ORDER BY pa.updated_at DESC LIMIT 1) AS related_claim_ledger_path,
                    (SELECT pa.manifest_path FROM papers pa WHERE pa.project_id = q.project_id AND (pa.run_id = q.current_run_id OR (q.current_run_id = '' AND q.status NOT IN ('awaiting_wake','dispatching','reconciling','running','wake_received'))) ORDER BY pa.updated_at DESC LIMIT 1) AS related_manifest_path,
                    (SELECT ci.corpus_import_id FROM papers pa LEFT JOIN corpus_imports ci USING(paper_id) WHERE pa.project_id = q.project_id AND (pa.run_id = q.current_run_id OR (q.current_run_id = '' AND q.status NOT IN ('awaiting_wake','dispatching','reconciling','running','wake_received'))) ORDER BY pa.updated_at DESC LIMIT 1) AS related_corpus_import_id,
                    (SELECT ci.artifact_slug FROM papers pa LEFT JOIN corpus_imports ci USING(paper_id) WHERE pa.project_id = q.project_id AND (pa.run_id = q.current_run_id OR (q.current_run_id = '' AND q.status NOT IN ('awaiting_wake','dispatching','reconciling','running','wake_received'))) ORDER BY pa.updated_at DESC LIMIT 1) AS related_artifact_slug,
                    (SELECT ci.source_record_fingerprint FROM papers pa LEFT JOIN corpus_imports ci USING(paper_id) WHERE pa.project_id = q.project_id AND (pa.run_id = q.current_run_id OR (q.current_run_id = '' AND q.status NOT IN ('awaiting_wake','dispatching','reconciling','running','wake_received'))) ORDER BY pa.updated_at DESC LIMIT 1) AS related_source_record_fingerprint,
                    (SELECT CASE WHEN ci.paper_id IS NULL THEN 0 ELSE 1 END FROM papers pa LEFT JOIN corpus_imports ci USING(paper_id) WHERE pa.project_id = q.project_id AND (pa.run_id = q.current_run_id OR (q.current_run_id = '' AND q.status NOT IN ('awaiting_wake','dispatching','reconciling','running','wake_received'))) ORDER BY pa.updated_at DESC LIMIT 1) AS related_corpus_imported,
                    EXISTS (SELECT 1 FROM events ev WHERE ev.event_type = 'followup.launch' AND ev.entity_type = 'project' AND ev.entity_id = q.project_id) AS followup_launched,
                    p.created_at AS project_created_at,
                    p.updated_at AS project_updated_at
                FROM queue_items q JOIN projects p USING(project_id)
                ORDER BY q.dispatch_priority ASC, q.updated_at DESC"""
            ).fetchall()
        return [dict(row) for row in rows]

    def queue_counts_sql(self) -> dict[str, int]:
        """Return queue group counts without materializing queue rows."""

        counts: dict[str, int] = {}
        with self._connect() as conn:
            for row in conn.execute(
                "SELECT status, COUNT(*) AS count FROM queue_items GROUP BY status"
            ).fetchall():
                status = _text(row["status"]) or "unknown"
                count = int(row["count"] or 0)
                counts[status] = count
                counts["all"] = counts.get("all", 0) + count
                if status in ACTIVE_STATUSES:
                    counts["active"] = counts.get("active", 0) + count
                # The status bucket key already records queued/paused counts.
                # Do not add the same row count twice under the same public key.
                if status == QueueStatus.CANCELED.value:
                    counts["completed"] = counts.get("completed", 0) + count
            manual_blocked = conn.execute(
                """SELECT COUNT(*) AS count FROM queue_items
                WHERE manual_review_required = 1
                   OR status IN (?, ?, ?)""",
                (
                    QueueStatus.BLOCKED.value,
                    QueueStatus.NEEDS_REVIEW.value,
                    QueueStatus.DISPATCH_ERROR.value,
                ),
            ).fetchone()
            counts["blocked"] = int((manual_blocked or {})["count"] or 0)
        counts.setdefault("all", 0)
        counts.setdefault("active", 0)
        counts.setdefault("queued", 0)
        counts.setdefault("blocked", 0)
        counts.setdefault("paused", 0)
        counts.setdefault("completed", 0)
        return counts

    def queue_page(
        self,
        *,
        queue: str = "all",
        status: str = "",
        search: str = "",
        page_size: int = 50,
        cursor: str = "",
        sort: str = "priority",
    ) -> tuple[list[dict[str, Any]], str | None, bool]:
        safe_size = max(1, min(page_size, 200))
        offset = max(0, _int(cursor, 0))
        clauses: list[str] = []
        params: list[Any] = []
        if queue == "active":
            clauses.append(f"q.status IN ({','.join('?' for _ in ACTIVE_STATUSES)})")
            params.extend(sorted(ACTIVE_STATUSES))
        elif queue == "queued":
            clauses.append(_QUEUE_STATUS_EQ)
            params.append(QueueStatus.QUEUED.value)
        elif queue == "blocked":
            clauses.append("(q.manual_review_required = 1 OR q.status IN (?, ?, ?))")
            params.extend(
                [
                    QueueStatus.BLOCKED.value,
                    QueueStatus.NEEDS_REVIEW.value,
                    QueueStatus.DISPATCH_ERROR.value,
                ]
            )
        elif queue == "paused":
            clauses.append(_QUEUE_STATUS_EQ)
            params.append(QueueStatus.PAUSED.value)
        elif queue == "completed":
            clauses.append("q.status IN (?, ?)")
            params.extend([QueueStatus.COMPLETED.value, QueueStatus.CANCELED.value])
        elif queue not in {"", "all"}:
            clauses.append(_QUEUE_STATUS_EQ)
            params.append(queue)
        if status:
            clauses.append(_QUEUE_STATUS_EQ)
            params.append(status)
        if search.strip():
            needle = f"%{search.strip()}%"
            clauses.append(
                """(q.project_id LIKE ? OR p.project_name LIKE ? OR q.status LIKE ?
                OR q.next_action_hint LIKE ? OR q.current_run_id LIKE ? OR q.last_run_state LIKE ?)"""
            )
            params.extend([needle] * 6)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        order_by = {
            "priority": "q.dispatch_priority ASC, q.updated_at DESC",
            "recent": "q.updated_at DESC, q.dispatch_priority ASC",
            "oldest": "q.updated_at ASC, q.dispatch_priority ASC",
            "created": "p.created_at DESC, q.updated_at DESC",
            "name": "p.project_name COLLATE NOCASE ASC, q.updated_at DESC",
            "status": "q.status ASC, q.updated_at DESC",
        }.get(sort, "q.dispatch_priority ASC, q.updated_at DESC")
        sql = f"""SELECT q.*,
                    p.project_name AS project_name,
                    p.project_dir AS project_dir,
                    p.notion_page_url AS notion_page_url,
                    p.notion_page_id AS notion_page_id,
                    p.origin_idea_status AS origin_idea_status,
                    (SELECT pa.paper_id FROM papers pa WHERE pa.project_id = q.project_id AND (pa.run_id = q.current_run_id OR (q.current_run_id = '' AND q.status NOT IN ('awaiting_wake','dispatching','reconciling','running','wake_received'))) ORDER BY pa.updated_at DESC LIMIT 1) AS related_paper_id,
                    (SELECT pa.paper_status FROM papers pa WHERE pa.project_id = q.project_id AND (pa.run_id = q.current_run_id OR (q.current_run_id = '' AND q.status NOT IN ('awaiting_wake','dispatching','reconciling','running','wake_received'))) ORDER BY pa.updated_at DESC LIMIT 1) AS related_paper_status,
                    (SELECT rv.review_status FROM papers pa LEFT JOIN paper_review_items rv USING(paper_id) WHERE pa.project_id = q.project_id AND (pa.run_id = q.current_run_id OR (q.current_run_id = '' AND q.status NOT IN ('awaiting_wake','dispatching','reconciling','running','wake_received'))) ORDER BY pa.updated_at DESC LIMIT 1) AS related_review_status,
                    (SELECT rv.finalization_package_path FROM papers pa LEFT JOIN paper_review_items rv USING(paper_id) WHERE pa.project_id = q.project_id AND (pa.run_id = q.current_run_id OR (q.current_run_id = '' AND q.status NOT IN ('awaiting_wake','dispatching','reconciling','running','wake_received'))) ORDER BY pa.updated_at DESC LIMIT 1) AS related_finalization_package_path,
                    (SELECT pa.draft_markdown_path FROM papers pa WHERE pa.project_id = q.project_id AND (pa.run_id = q.current_run_id OR (q.current_run_id = '' AND q.status NOT IN ('awaiting_wake','dispatching','reconciling','running','wake_received'))) ORDER BY pa.updated_at DESC LIMIT 1) AS related_draft_markdown_path,
                    (SELECT pa.evidence_bundle_path FROM papers pa WHERE pa.project_id = q.project_id AND (pa.run_id = q.current_run_id OR (q.current_run_id = '' AND q.status NOT IN ('awaiting_wake','dispatching','reconciling','running','wake_received'))) ORDER BY pa.updated_at DESC LIMIT 1) AS related_evidence_bundle_path,
                    (SELECT pa.claim_ledger_path FROM papers pa WHERE pa.project_id = q.project_id AND (pa.run_id = q.current_run_id OR (q.current_run_id = '' AND q.status NOT IN ('awaiting_wake','dispatching','reconciling','running','wake_received'))) ORDER BY pa.updated_at DESC LIMIT 1) AS related_claim_ledger_path,
                    (SELECT pa.manifest_path FROM papers pa WHERE pa.project_id = q.project_id AND (pa.run_id = q.current_run_id OR (q.current_run_id = '' AND q.status NOT IN ('awaiting_wake','dispatching','reconciling','running','wake_received'))) ORDER BY pa.updated_at DESC LIMIT 1) AS related_manifest_path,
                    (SELECT ci.corpus_import_id FROM papers pa LEFT JOIN corpus_imports ci USING(paper_id) WHERE pa.project_id = q.project_id AND (pa.run_id = q.current_run_id OR (q.current_run_id = '' AND q.status NOT IN ('awaiting_wake','dispatching','reconciling','running','wake_received'))) ORDER BY pa.updated_at DESC LIMIT 1) AS related_corpus_import_id,
                    (SELECT ci.artifact_slug FROM papers pa LEFT JOIN corpus_imports ci USING(paper_id) WHERE pa.project_id = q.project_id AND (pa.run_id = q.current_run_id OR (q.current_run_id = '' AND q.status NOT IN ('awaiting_wake','dispatching','reconciling','running','wake_received'))) ORDER BY pa.updated_at DESC LIMIT 1) AS related_artifact_slug,
                    (SELECT ci.source_record_fingerprint FROM papers pa LEFT JOIN corpus_imports ci USING(paper_id) WHERE pa.project_id = q.project_id AND (pa.run_id = q.current_run_id OR (q.current_run_id = '' AND q.status NOT IN ('awaiting_wake','dispatching','reconciling','running','wake_received'))) ORDER BY pa.updated_at DESC LIMIT 1) AS related_source_record_fingerprint,
                    (SELECT CASE WHEN ci.paper_id IS NULL THEN 0 ELSE 1 END FROM papers pa LEFT JOIN corpus_imports ci USING(paper_id) WHERE pa.project_id = q.project_id AND (pa.run_id = q.current_run_id OR (q.current_run_id = '' AND q.status NOT IN ('awaiting_wake','dispatching','reconciling','running','wake_received'))) ORDER BY pa.updated_at DESC LIMIT 1) AS related_corpus_imported,
                    EXISTS (SELECT 1 FROM events ev WHERE ev.event_type = 'followup.launch' AND ev.entity_type = 'project' AND ev.entity_id = q.project_id) AS followup_launched,
                    p.created_at AS project_created_at,
                    p.updated_at AS project_updated_at
                FROM queue_items q JOIN projects p USING(project_id)
                {where}
                ORDER BY {order_by}
                LIMIT ? OFFSET ?"""
        with self._connect() as conn:
            rows = conn.execute(sql, (*params, safe_size + 1, offset)).fetchall()
        page_rows = [dict(row) for row in rows[:safe_size]]
        has_more = len(rows) > safe_size
        next_cursor = str(offset + safe_size) if has_more else None
        return page_rows, next_cursor, has_more

    def project_page(
        self,
        *,
        status: str = "",
        search: str = "",
        page_size: int = 50,
        cursor: str = "",
        sort: str = "recent",
    ) -> tuple[list[dict[str, Any]], str | None, bool]:
        safe_size = max(1, min(page_size, 200))
        offset = max(0, _int(cursor, 0))
        clauses: list[str] = []
        params: list[Any] = []
        if status:
            clauses.append("(p.origin_idea_status = ? OR q.status = ?)")
            params.extend([status, status])
        if search.strip():
            needle = f"%{search.strip()}%"
            clauses.append(
                """(p.project_id LIKE ? OR p.project_name LIKE ? OR p.origin_idea_status LIKE ?
                OR q.status LIKE ? OR q.current_run_id LIKE ?)"""
            )
            params.extend([needle] * 5)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        order_by = {
            "recent": "p.updated_at DESC, p.project_id DESC",
            "oldest": "p.updated_at ASC, p.project_id ASC",
            "created": "p.created_at DESC, p.updated_at DESC",
            "name": "p.project_name COLLATE NOCASE ASC, p.updated_at DESC",
            "status": "COALESCE(q.status, p.origin_idea_status) ASC, p.updated_at DESC",
        }.get(sort, "p.updated_at DESC, p.project_id DESC")
        sql = f"""SELECT p.project_id,
                    p.project_name,
                    p.notion_page_url,
                    p.notion_page_id,
                    p.origin_idea_status,
                    p.created_at AS project_created_at,
                    p.updated_at AS project_updated_at,
                    q.status AS queue_status,
                    q.current_run_id AS current_run_id,
                    q.dispatch_priority AS dispatch_priority,
                    q.next_action_hint AS next_action_hint,
                    (SELECT r.run_id FROM runs r WHERE r.project_id = p.project_id ORDER BY r.updated_at DESC, r.run_id DESC LIMIT 1) AS latest_run_id,
                    (SELECT r.state FROM runs r WHERE r.project_id = p.project_id ORDER BY r.updated_at DESC, r.run_id DESC LIMIT 1) AS latest_run_state,
                    (SELECT pa.paper_id FROM papers pa WHERE pa.project_id = p.project_id ORDER BY pa.updated_at DESC LIMIT 1) AS related_paper_id,
                    (SELECT pa.paper_status FROM papers pa WHERE pa.project_id = p.project_id ORDER BY pa.updated_at DESC LIMIT 1) AS related_paper_status
                FROM projects p
                LEFT JOIN queue_items q USING(project_id)
                {where}
                ORDER BY {order_by}
                LIMIT ? OFFSET ?"""
        with self._connect() as conn:
            rows = conn.execute(sql, (*params, safe_size + 1, offset)).fetchall()
        page_rows = [dict(row) for row in rows[:safe_size]]
        has_more = len(rows) > safe_size
        next_cursor = str(offset + safe_size) if has_more else None
        return page_rows, next_cursor, has_more

    def paper_rows(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT pa.*, p.project_name AS project_name, p.project_dir AS project_dir, p.notion_page_url AS notion_page_url, p.notion_page_id AS notion_page_id,
                    rv.review_status AS review_status,
                    rv.finalization_package_path AS finalization_package_path,
                    rv.finalized_at AS finalized_at,
                    ci.corpus_import_id AS corpus_import_id,
                    ci.artifact_slug AS artifact_slug,
                    ci.commit_sha AS corpus_commit_sha,
                    ci.manifest_path AS corpus_manifest_path,
                    ci.manifest_hash AS corpus_manifest_hash,
                    ci.source_record_fingerprint AS source_record_fingerprint,
                    ci.hf_dataset_synced AS hf_dataset_synced,
                    CASE WHEN ci.paper_id IS NULL THEN 0 ELSE 1 END AS corpus_imported
                FROM papers pa LEFT JOIN projects p USING(project_id)
                LEFT JOIN paper_review_items rv USING(paper_id)
                LEFT JOIN corpus_imports ci USING(paper_id)
                ORDER BY pa.updated_at DESC"""
            ).fetchall()
        return [dict(row) for row in rows]

    def paper_counts_sql(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        with self._connect() as conn:
            for row in conn.execute(
                "SELECT paper_status, COUNT(*) AS count FROM papers GROUP BY paper_status"
            ).fetchall():
                status = _text(row["paper_status"]) or "unknown"
                count = int(row["count"] or 0)
                counts[status] = count
                counts["all"] = counts.get("all", 0) + count
        counts.setdefault("all", 0)
        return counts

    def paper_page(
        self,
        *,
        status: str = "",
        project_id: str = "",
        run_id: str = "",
        search: str = "",
        page_size: int = 50,
        cursor: str = "",
        sort: str = "recent",
    ) -> tuple[list[dict[str, Any]], str | None, bool]:
        safe_size = max(1, min(page_size, 200))
        offset = max(0, _int(cursor, 0))
        clauses: list[str] = []
        params: list[Any] = []
        if status:
            clauses.append("pa.paper_status = ?")
            params.append(status)
        if project_id:
            clauses.append("pa.project_id = ?")
            params.append(project_id)
        if run_id:
            clauses.append("pa.run_id = ?")
            params.append(run_id)
        if search.strip():
            needle = f"%{search.strip()}%"
            clauses.append(
                """(pa.paper_id LIKE ? OR pa.project_id LIKE ? OR pa.run_id LIKE ?
                OR pa.paper_status LIKE ? OR p.project_name LIKE ?)"""
            )
            params.extend([needle] * 5)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        order_by = {
            "recent": "pa.updated_at DESC, pa.paper_id DESC",
            "created": "pa.generated_at DESC, pa.updated_at DESC",
            "status": "pa.paper_status ASC, pa.updated_at DESC",
            "title": "p.project_name COLLATE NOCASE ASC, pa.updated_at DESC",
        }.get(sort, "pa.updated_at DESC, pa.paper_id DESC")
        sql = f"""SELECT pa.*, p.project_name AS project_name, p.project_dir AS project_dir,
                    p.notion_page_url AS notion_page_url, p.notion_page_id AS notion_page_id,
                    rv.review_status AS review_status,
                    rv.finalization_package_path AS finalization_package_path,
                    rv.finalized_at AS finalized_at,
                    ci.corpus_import_id AS corpus_import_id,
                    ci.artifact_slug AS artifact_slug,
                    ci.commit_sha AS corpus_commit_sha,
                    ci.manifest_path AS corpus_manifest_path,
                    ci.manifest_hash AS corpus_manifest_hash,
                    ci.source_record_fingerprint AS source_record_fingerprint,
                    ci.hf_dataset_synced AS hf_dataset_synced,
                    CASE WHEN ci.paper_id IS NULL THEN 0 ELSE 1 END AS corpus_imported
                FROM papers pa LEFT JOIN projects p USING(project_id)
                LEFT JOIN paper_review_items rv USING(paper_id)
                LEFT JOIN corpus_imports ci USING(paper_id)
                {where}
                ORDER BY {order_by}
                LIMIT ? OFFSET ?"""
        with self._connect() as conn:
            rows = conn.execute(sql, (*params, safe_size + 1, offset)).fetchall()
        page_rows = [dict(row) for row in rows[:safe_size]]
        has_more = len(rows) > safe_size
        next_cursor = str(offset + safe_size) if has_more else None
        return page_rows, next_cursor, has_more

    def operator_paper_rows_sql(self) -> list[dict[str, Any]]:
        """Return paper rows with review metadata for normalized operator aggregation."""

        with self._connect() as conn:
            rows = conn.execute(
                """SELECT pa.*, p.project_name AS project_name, p.project_dir AS project_dir,
                    p.notion_page_url AS notion_page_url, p.notion_page_id AS notion_page_id,
                    rv.review_status AS review_status,
                    rv.finalization_package_path AS finalization_package_path,
                    rv.finalized_at AS finalized_at,
                    ci.corpus_import_id AS corpus_import_id,
                    ci.artifact_slug AS artifact_slug,
                    ci.commit_sha AS corpus_commit_sha,
                    ci.manifest_path AS corpus_manifest_path,
                    ci.manifest_hash AS corpus_manifest_hash,
                    ci.source_record_fingerprint AS source_record_fingerprint,
                    ci.hf_dataset_synced AS hf_dataset_synced,
                    CASE WHEN ci.paper_id IS NULL THEN 0 ELSE 1 END AS corpus_imported
                FROM papers pa LEFT JOIN projects p USING(project_id)
                LEFT JOIN paper_review_items rv USING(paper_id)
                LEFT JOIN corpus_imports ci USING(paper_id)
                ORDER BY pa.updated_at DESC"""
            ).fetchall()
        return [dict(row) for row in rows]

    def run_rows(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM runs ORDER BY updated_at DESC, run_id DESC"
            ).fetchall()
        return [dict(row) for row in rows]

    def run_page(
        self,
        *,
        state: str = "",
        project_id: str = "",
        search: str = "",
        page_size: int = 50,
        cursor: str = "",
        sort: str = "recent",
    ) -> tuple[list[dict[str, Any]], str | None, bool]:
        safe_size = max(1, min(page_size, 200))
        offset = max(0, _int(cursor, 0))
        clauses: list[str] = []
        params: list[Any] = []
        if state:
            clauses.append("(r.state = ? OR r.gate_state = ?)")
            params.extend([state, state])
        if project_id:
            clauses.append("r.project_id = ?")
            params.append(project_id)
        if search.strip():
            needle = f"%{search.strip()}%"
            clauses.append(
                "(r.run_id LIKE ? OR r.project_id LIKE ? OR p.project_name LIKE ? OR r.session_id LIKE ? OR r.current_activity LIKE ?)"
            )
            params.extend([needle] * 5)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        order_by = {
            "recent": "r.updated_at DESC, r.run_id DESC",
            "oldest": "r.updated_at ASC, r.run_id ASC",
            "started": "r.started_at DESC, r.updated_at DESC",
            "ended": "r.ended_at DESC, r.updated_at DESC",
            "state": "r.state ASC, r.updated_at DESC",
            "project": "p.project_name COLLATE NOCASE ASC, r.updated_at DESC",
        }.get(sort, "r.updated_at DESC, r.run_id DESC")
        sql = f"""SELECT r.*, p.project_name AS project_name, p.project_dir AS project_dir,
                (SELECT pa.paper_id FROM papers pa WHERE pa.run_id = r.run_id ORDER BY pa.updated_at DESC LIMIT 1) AS related_paper_id,
                (SELECT pa.paper_status FROM papers pa WHERE pa.run_id = r.run_id ORDER BY pa.updated_at DESC LIMIT 1) AS related_paper_status,
                (SELECT rv.review_status FROM papers pa LEFT JOIN paper_review_items rv USING(paper_id) WHERE pa.run_id = r.run_id ORDER BY pa.updated_at DESC LIMIT 1) AS related_review_status,
                (SELECT rv.finalization_package_path FROM papers pa LEFT JOIN paper_review_items rv USING(paper_id) WHERE pa.run_id = r.run_id ORDER BY pa.updated_at DESC LIMIT 1) AS related_finalization_package_path,
                (SELECT pa.draft_markdown_path FROM papers pa WHERE pa.run_id = r.run_id ORDER BY pa.updated_at DESC LIMIT 1) AS related_draft_markdown_path,
                (SELECT pa.evidence_bundle_path FROM papers pa WHERE pa.run_id = r.run_id ORDER BY pa.updated_at DESC LIMIT 1) AS related_evidence_bundle_path,
                (SELECT pa.claim_ledger_path FROM papers pa WHERE pa.run_id = r.run_id ORDER BY pa.updated_at DESC LIMIT 1) AS related_claim_ledger_path,
                (SELECT pa.manifest_path FROM papers pa WHERE pa.run_id = r.run_id ORDER BY pa.updated_at DESC LIMIT 1) AS related_manifest_path
            FROM runs r LEFT JOIN projects p USING(project_id)
            {where}
            ORDER BY {order_by}
            LIMIT ? OFFSET ?"""
        with self._connect() as conn:
            rows = conn.execute(sql, (*params, safe_size + 1, offset)).fetchall()
        page_rows = [dict(row) for row in rows[:safe_size]]
        has_more = len(rows) > safe_size
        next_cursor = str(offset + safe_size) if has_more else None
        return page_rows, next_cursor, has_more

    def run_row(self, run_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """SELECT r.*, p.project_name AS project_name, p.project_dir AS project_dir,
                (SELECT pa.paper_id FROM papers pa WHERE pa.run_id = r.run_id ORDER BY pa.updated_at DESC LIMIT 1) AS related_paper_id,
                (SELECT pa.paper_status FROM papers pa WHERE pa.run_id = r.run_id ORDER BY pa.updated_at DESC LIMIT 1) AS related_paper_status,
                (SELECT rv.review_status FROM papers pa LEFT JOIN paper_review_items rv USING(paper_id) WHERE pa.run_id = r.run_id ORDER BY pa.updated_at DESC LIMIT 1) AS related_review_status,
                (SELECT rv.finalization_package_path FROM papers pa LEFT JOIN paper_review_items rv USING(paper_id) WHERE pa.run_id = r.run_id ORDER BY pa.updated_at DESC LIMIT 1) AS related_finalization_package_path,
                (SELECT pa.draft_markdown_path FROM papers pa WHERE pa.run_id = r.run_id ORDER BY pa.updated_at DESC LIMIT 1) AS related_draft_markdown_path,
                (SELECT pa.evidence_bundle_path FROM papers pa WHERE pa.run_id = r.run_id ORDER BY pa.updated_at DESC LIMIT 1) AS related_evidence_bundle_path,
                (SELECT pa.claim_ledger_path FROM papers pa WHERE pa.run_id = r.run_id ORDER BY pa.updated_at DESC LIMIT 1) AS related_claim_ledger_path,
                (SELECT pa.manifest_path FROM papers pa WHERE pa.run_id = r.run_id ORDER BY pa.updated_at DESC LIMIT 1) AS related_manifest_path
                FROM runs r LEFT JOIN projects p USING(project_id)
                WHERE r.run_id=?""",
                (run_id,),
            ).fetchone()
        return dict(row) if row else None

    def queue_row(self, project_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """SELECT q.*,
                    p.project_name AS project_name,
                    p.project_dir AS project_dir,
                    p.notion_page_url AS notion_page_url,
                    p.notion_page_id AS notion_page_id,
                    p.origin_idea_status AS origin_idea_status,
                    (SELECT pa.paper_id FROM papers pa WHERE pa.project_id = q.project_id AND (pa.run_id = q.current_run_id OR (q.current_run_id = '' AND q.status NOT IN ('awaiting_wake','dispatching','reconciling','running','wake_received'))) ORDER BY pa.updated_at DESC LIMIT 1) AS related_paper_id,
                    (SELECT pa.paper_status FROM papers pa WHERE pa.project_id = q.project_id AND (pa.run_id = q.current_run_id OR (q.current_run_id = '' AND q.status NOT IN ('awaiting_wake','dispatching','reconciling','running','wake_received'))) ORDER BY pa.updated_at DESC LIMIT 1) AS related_paper_status,
                    (SELECT rv.review_status FROM papers pa LEFT JOIN paper_review_items rv USING(paper_id) WHERE pa.project_id = q.project_id AND (pa.run_id = q.current_run_id OR (q.current_run_id = '' AND q.status NOT IN ('awaiting_wake','dispatching','reconciling','running','wake_received'))) ORDER BY pa.updated_at DESC LIMIT 1) AS related_review_status,
                    (SELECT rv.finalization_package_path FROM papers pa LEFT JOIN paper_review_items rv USING(paper_id) WHERE pa.project_id = q.project_id AND (pa.run_id = q.current_run_id OR (q.current_run_id = '' AND q.status NOT IN ('awaiting_wake','dispatching','reconciling','running','wake_received'))) ORDER BY pa.updated_at DESC LIMIT 1) AS related_finalization_package_path,
                    (SELECT pa.draft_markdown_path FROM papers pa WHERE pa.project_id = q.project_id AND (pa.run_id = q.current_run_id OR (q.current_run_id = '' AND q.status NOT IN ('awaiting_wake','dispatching','reconciling','running','wake_received'))) ORDER BY pa.updated_at DESC LIMIT 1) AS related_draft_markdown_path,
                    (SELECT pa.evidence_bundle_path FROM papers pa WHERE pa.project_id = q.project_id AND (pa.run_id = q.current_run_id OR (q.current_run_id = '' AND q.status NOT IN ('awaiting_wake','dispatching','reconciling','running','wake_received'))) ORDER BY pa.updated_at DESC LIMIT 1) AS related_evidence_bundle_path,
                    (SELECT pa.claim_ledger_path FROM papers pa WHERE pa.project_id = q.project_id AND (pa.run_id = q.current_run_id OR (q.current_run_id = '' AND q.status NOT IN ('awaiting_wake','dispatching','reconciling','running','wake_received'))) ORDER BY pa.updated_at DESC LIMIT 1) AS related_claim_ledger_path,
                    (SELECT pa.manifest_path FROM papers pa WHERE pa.project_id = q.project_id AND (pa.run_id = q.current_run_id OR (q.current_run_id = '' AND q.status NOT IN ('awaiting_wake','dispatching','reconciling','running','wake_received'))) ORDER BY pa.updated_at DESC LIMIT 1) AS related_manifest_path,
                    (SELECT ci.corpus_import_id FROM papers pa LEFT JOIN corpus_imports ci USING(paper_id) WHERE pa.project_id = q.project_id AND (pa.run_id = q.current_run_id OR (q.current_run_id = '' AND q.status NOT IN ('awaiting_wake','dispatching','reconciling','running','wake_received'))) ORDER BY pa.updated_at DESC LIMIT 1) AS related_corpus_import_id,
                    (SELECT ci.artifact_slug FROM papers pa LEFT JOIN corpus_imports ci USING(paper_id) WHERE pa.project_id = q.project_id AND (pa.run_id = q.current_run_id OR (q.current_run_id = '' AND q.status NOT IN ('awaiting_wake','dispatching','reconciling','running','wake_received'))) ORDER BY pa.updated_at DESC LIMIT 1) AS related_artifact_slug,
                    (SELECT ci.source_record_fingerprint FROM papers pa LEFT JOIN corpus_imports ci USING(paper_id) WHERE pa.project_id = q.project_id AND (pa.run_id = q.current_run_id OR (q.current_run_id = '' AND q.status NOT IN ('awaiting_wake','dispatching','reconciling','running','wake_received'))) ORDER BY pa.updated_at DESC LIMIT 1) AS related_source_record_fingerprint,
                    (SELECT CASE WHEN ci.paper_id IS NULL THEN 0 ELSE 1 END FROM papers pa LEFT JOIN corpus_imports ci USING(paper_id) WHERE pa.project_id = q.project_id AND (pa.run_id = q.current_run_id OR (q.current_run_id = '' AND q.status NOT IN ('awaiting_wake','dispatching','reconciling','running','wake_received'))) ORDER BY pa.updated_at DESC LIMIT 1) AS related_corpus_imported,
                    EXISTS (SELECT 1 FROM events ev WHERE ev.event_type = 'followup.launch' AND ev.entity_type = 'project' AND ev.entity_id = q.project_id) AS followup_launched,
                    p.created_at AS project_created_at,
                    p.updated_at AS project_updated_at
                FROM queue_items q JOIN projects p USING(project_id)
                WHERE q.project_id=?""",
                (project_id,),
            ).fetchone()
        return dict(row) if row else None

    def project_row(self, project_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM projects WHERE project_id=?", (project_id,)
            ).fetchone()
        return dict(row) if row else None

    def paper_row(self, paper_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """SELECT pa.*, p.project_name AS project_name, p.project_dir AS project_dir, p.notion_page_url AS notion_page_url, p.notion_page_id AS notion_page_id,
                    rv.review_status AS review_status,
                    rv.finalization_package_path AS finalization_package_path,
                    rv.finalized_at AS finalized_at,
                    ci.corpus_import_id AS corpus_import_id,
                    ci.artifact_slug AS artifact_slug,
                    ci.commit_sha AS corpus_commit_sha,
                    ci.manifest_path AS corpus_manifest_path,
                    ci.manifest_hash AS corpus_manifest_hash,
                    ci.source_record_fingerprint AS source_record_fingerprint,
                    ci.hf_dataset_synced AS hf_dataset_synced,
                    CASE WHEN ci.paper_id IS NULL THEN 0 ELSE 1 END AS corpus_imported
                FROM papers pa LEFT JOIN projects p USING(project_id)
                LEFT JOIN paper_review_items rv USING(paper_id)
                LEFT JOIN corpus_imports ci USING(paper_id)
                WHERE pa.paper_id=?""",
                (paper_id,),
            ).fetchone()
        return dict(row) if row else None

    def _paper_review_join_rows(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT
                    pa.*,
                    p.project_name AS project_name,
                    p.project_dir AS project_dir,
                    p.notion_page_url AS notion_page_url,
                    p.notion_page_id AS notion_page_id,
                    q.status AS queue_status,
                    q.manual_review_required AS manual_review_required,
                    q.blocked_reason AS blocked_reason,
                    q.next_action_hint AS next_action_hint,
                    rv.review_status AS review_status,
                    rv.reviewer AS reviewer,
                    rv.blocker AS blocker,
                    rv.claimed_at AS claimed_at,
                    rv.checklist_json AS checklist_json,
                    rv.rank_score AS rank_score,
                    rv.rank_reasons_json AS rank_reasons_json,
                    rv.missing_signals_json AS missing_signals_json,
                    rv.rank_tiebreaker AS rank_tiebreaker,
                    rv.source_audit_path AS source_audit_path,
                    rv.finalization_package_path AS finalization_package_path,
                    rv.finalized_at AS finalized_at,
                    rv.decision_summary AS decision_summary,
                    rv.created_at AS review_created_at,
                    rv.updated_at AS review_updated_at
                FROM paper_review_items rv
                JOIN papers pa USING(paper_id)
                LEFT JOIN projects p USING(project_id)
                LEFT JOIN queue_items q USING(project_id)
                ORDER BY rv.rank_score DESC, pa.updated_at DESC, pa.paper_id ASC"""
            ).fetchall()
        return [dict(row) for row in rows]

    def _review_queue_item_from_row(
        self, row: dict[str, Any], *, include_rank_reasons: bool = True
    ) -> dict[str, Any]:
        checklist = _json_dict(row.get("checklist_json")) or _default_review_checklist()
        rank_reasons = (
            _json_list(row.get("rank_reasons_json")) if include_rank_reasons else []
        )
        missing_signals = _json_list(row.get("missing_signals_json"))
        score = _int(row.get("rank_score"), 0)
        updated_at = _text(row.get("review_updated_at")) or _text(row.get("updated_at"))
        item = ReviewQueueItem(
            paper_id=_text(row.get("paper_id")),
            project_id=_text(row.get("project_id")),
            project_name=_text(row.get("project_name")),
            paper_status=_text(row.get("paper_status")),
            paper_type=_text(row.get("paper_type")),
            review_status=_text(row.get("review_status")) or ReviewStatus.QUEUED.value,
            checklist_progress=_checklist_progress(checklist),
            blocker=_text(row.get("blocker")),
            reviewer=_text(row.get("reviewer")),
            claimed_at=_text(row.get("claimed_at")),
            updated_at=updated_at,
            rank_score=score,
            rank_bucket="blocked"
            if score < 0
            else "ready"
            if score >= 100
            else "review",
            rank_reasons=rank_reasons,
            missing_signals=missing_signals,
            rank_tiebreaker=_text(row.get("rank_tiebreaker")),
            draft_markdown_path=_text(row.get("draft_markdown_path")),
            draft_latex_path=_text(row.get("draft_latex_path")),
            evidence_bundle_path=_text(row.get("evidence_bundle_path")),
            claim_ledger_path=_text(row.get("claim_ledger_path")),
            manifest_path=_text(row.get("manifest_path")),
            finalization_package_path=_text(row.get("finalization_package_path")),
            finalized_at=_text(row.get("finalized_at")),
            decision_summary=_text(row.get("decision_summary")),
            links={
                "review": f"/control/api/paper-reviews/{_text(row.get('paper_id'))}",
                "paper": f"/control/api/papers/{_text(row.get('paper_id'))}",
                "project": f"/control/api/projects/{_text(row.get('project_id'))}",
                "run": f"/control/api/runs/{_text(row.get('run_id'))}"
                if _text(row.get("run_id"))
                else "",
            },
        )
        return item.model_dump(mode="json")

    def paper_review_rows(
        self, *, include_rank_reasons: bool = True
    ) -> list[dict[str, Any]]:
        return [
            self._review_queue_item_from_row(
                row, include_rank_reasons=include_rank_reasons
            )
            for row in self._paper_review_join_rows()
        ]

    def paper_review_row(
        self, paper_id: str, *, include_rank_reasons: bool = True
    ) -> dict[str, Any] | None:
        for row in self._paper_review_join_rows():
            if row.get("paper_id") == paper_id:
                return self._review_queue_item_from_row(
                    row, include_rank_reasons=include_rank_reasons
                )
        return None

    def paper_review_checklist(self, paper_id: str) -> dict[str, Any]:
        row = self._raw_paper_review_row(paper_id)
        return _normalize_review_checklist(
            _json_dict(row.get("checklist_json")) if row else {}
        )

    def _papers_for_review_backfill(
        self, request: PaperReviewBackfillRequest
    ) -> list[dict[str, Any]]:
        requested_paper_ids = {
            _text(paper_id) for paper_id in request.paper_ids if _text(paper_id)
        }
        return [
            paper
            for paper in self.paper_rows()
            if not requested_paper_ids
            or _text(paper.get("paper_id")) in requested_paper_ids
        ]

    def _paper_review_backfill_candidate(
        self,
        paper: dict[str, Any],
        audit_by_paper: dict[str, dict[str, Any]],
        source_audit_path: str,
    ) -> tuple[PaperReviewRecord, dict[str, Any] | None]:
        paper_id = _text(paper.get("paper_id"))
        mandatory = [
            "draft_markdown_path",
            "draft_latex_path",
            "evidence_bundle_path",
            "claim_ledger_path",
            "manifest_path",
        ]
        missing_paths = [name for name in mandatory if not _text(paper.get(name))]
        error = (
            {
                "paper_id": paper_id,
                "reason": "missing mandatory artifact path",
                "missing_paths": missing_paths,
            }
            if missing_paths
            else None
        )
        audit = audit_by_paper.get(paper_id, {})
        initial_missing = ([] if audit else ["readiness_audit"]) + missing_paths
        queue_item = self.queue_row(_text(paper.get("project_id")))
        rank_score, rank_reasons, missing_signals, tiebreaker, _bucket = _review_rank(
            paper, queue_item, audit, initial_missing
        )
        status = ReviewStatus.QUEUED if not missing_paths else ReviewStatus.BLOCKED
        record = PaperReviewRecord(
            paper_id=paper_id,
            review_status=status,
            checklist_json=_default_review_checklist(),
            rank_score=rank_score,
            rank_reasons=rank_reasons,
            missing_signals=missing_signals,
            rank_tiebreaker=tiebreaker,
            source_audit_path=source_audit_path,
        )
        return record, error

    def _apply_paper_review_backfill_record(
        self,
        conn: sqlite3.Connection,
        record: PaperReviewRecord,
        now: str,
    ) -> str:
        existing = conn.execute(
            "SELECT * FROM paper_review_items WHERE paper_id=?",
            (record.paper_id,),
        ).fetchone()
        rank_reasons_json = _json(record.rank_reasons)
        missing_signals_json = _json(record.missing_signals)
        if not existing:
            conn.execute(
                """INSERT INTO paper_review_items(paper_id,review_status,reviewer,blocker,claimed_at,checklist_json,rank_score,rank_reasons_json,missing_signals_json,rank_tiebreaker,source_audit_path,finalization_package_path,finalized_at,decision_summary,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    record.paper_id,
                    record.review_status.value,
                    record.reviewer,
                    record.blocker,
                    record.claimed_at,
                    _json(_normalize_review_checklist(record.checklist_json)),
                    record.rank_score,
                    rank_reasons_json,
                    missing_signals_json,
                    record.rank_tiebreaker,
                    record.source_audit_path,
                    record.finalization_package_path,
                    record.finalized_at,
                    record.decision_summary,
                    now,
                    now,
                ),
            )
            return "created"
        existing_review_status = _normal(existing["review_status"])
        next_review_status = (
            record.review_status.value
            if existing_review_status in SYSTEM_REVIEW_STATUSES
            else existing_review_status
        )
        changes = {
            "review_status": next_review_status,
            "rank_score": record.rank_score,
            "rank_reasons_json": rank_reasons_json,
            "missing_signals_json": missing_signals_json,
            "rank_tiebreaker": record.rank_tiebreaker,
            "source_audit_path": record.source_audit_path,
        }
        if all(str(existing[key]) == str(value) for key, value in changes.items()):
            return "skipped"
        conn.execute(
            """UPDATE paper_review_items
            SET review_status=?, rank_score=?, rank_reasons_json=?, missing_signals_json=?, rank_tiebreaker=?, source_audit_path=?, updated_at=?
            WHERE paper_id=?""",
            (
                next_review_status,
                record.rank_score,
                rank_reasons_json,
                missing_signals_json,
                record.rank_tiebreaker,
                record.source_audit_path,
                now,
                record.paper_id,
            ),
        )
        return "updated"

    def backfill_paper_reviews(
        self, request: PaperReviewBackfillRequest
    ) -> tuple[bool, int, int, int, list[dict[str, Any]]]:
        audit_by_paper = _audit_rows(request.source_audit_path)
        errors: list[dict[str, Any]] = []
        candidates: list[PaperReviewRecord] = []
        for paper in self._papers_for_review_backfill(request):
            record, error = self._paper_review_backfill_candidate(
                paper, audit_by_paper, request.source_audit_path
            )
            if error:
                errors.append(error)
            candidates.append(record)
        if request.dry_run:
            return False, len(candidates), 0, 0, errors
        event_payload = request.model_dump(mode="json")
        event_payload.update(
            {"candidate_count": len(candidates), "error_count": len(errors)}
        )
        created = updated = skipped = 0
        now = utc_now()
        with self._connect() as conn:
            _, inserted = self._append_event_in_conn(
                conn,
                idempotency_key=request.idempotency_key,
                event_type="paper_review.backfill",
                entity_type="paper_reviews",
                entity_id="backfill",
                payload=event_payload,
            )
            if not inserted:
                return False, 0, 0, 0, errors
            for record in candidates:
                outcome = self._apply_paper_review_backfill_record(conn, record, now)
                if outcome == "created":
                    created += 1
                elif outcome == "updated":
                    updated += 1
                else:
                    skipped += 1
        return inserted, created, updated, skipped, errors

    def _raw_paper_review_row(self, paper_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM paper_review_items WHERE paper_id=?", (paper_id,)
            ).fetchone()
        return dict(row) if row else None

    def _require_paper_review(self, paper_id: str) -> dict[str, Any]:
        row = self._raw_paper_review_row(paper_id)
        if row is None:
            raise ValueError("paper review not found")
        return row

    def _mutation_payload(self, request: Any, *, action: str) -> dict[str, Any]:
        payload = request.model_dump(mode="json")
        payload["action"] = action
        return payload

    def _replayed_event_id(
        self,
        idempotency_key: str,
        payload: dict[str, Any],
        *,
        event_type: str,
        entity_type: str,
        entity_id: str,
    ) -> int | None:
        payload_hash = _hash(payload)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT event_id, event_type, entity_type, entity_id, payload_hash FROM events WHERE idempotency_key=?",
                (idempotency_key,),
            ).fetchone()
        if row is None:
            return None
        if (
            row["event_type"] != event_type
            or row["entity_type"] != entity_type
            or row["entity_id"] != entity_id
            or row["payload_hash"] != payload_hash
        ):
            raise IdempotencyConflict(
                f"idempotency key {idempotency_key!r} was reused with different event identity"
            )
        return int(row["event_id"])

    def _replayed_worker_callback_event_id(
        self, idempotency_key: str, incoming_payload: dict[str, Any]
    ) -> int | None:
        """Return existing worker callback event id for an exact incoming retry.

        Worker callback event payloads include state-derived audit fields such as
        applied_status. A retry of the same callback can arrive after the queue
        has legitimately moved on, so idempotency must compare the immutable
        incoming callback fields, not a newly derived augmented payload.
        """

        with self._connect() as conn:
            row = conn.execute(
                "SELECT event_id, payload_json FROM events WHERE idempotency_key=?",
                (idempotency_key,),
            ).fetchone()
        if row is None:
            return None
        try:
            existing_payload = json.loads(row["payload_json"] or "{}")
        except (TypeError, json.JSONDecodeError) as exc:
            raise IdempotencyConflict(
                f"idempotency key {idempotency_key!r} has unreadable payload"
            ) from exc
        if not isinstance(existing_payload, dict):
            raise IdempotencyConflict(
                f"idempotency key {idempotency_key!r} has non-object payload"
            )
        existing_callback_payload = {
            key: value
            for key, value in existing_payload.items()
            if key not in WORKER_CALLBACK_AUDIT_KEYS
        }
        incoming_callback_payload = {
            key: value
            for key, value in incoming_payload.items()
            if key not in WORKER_CALLBACK_AUDIT_KEYS
        }
        if existing_callback_payload != incoming_callback_payload:
            raise IdempotencyConflict(
                f"idempotency key {idempotency_key!r} was reused with different callback payload"
            )
        return int(row["event_id"])

    def _resolve_worker_callback_project_id(self, project_id: str, run_id: str) -> str:
        if project_id or not run_id:
            return project_id
        with self._connect() as conn:
            found = conn.execute(
                "SELECT project_id FROM runs WHERE run_id=?", (run_id,)
            ).fetchone()
        return found["project_id"] if found else ""

    def _worker_callback_queue_snapshot(
        self, project_id: str, run_id: str
    ) -> tuple[dict[str, Any] | None, bool, str]:
        if not project_id:
            return None, False, ""
        with self._connect() as conn:
            found = conn.execute(
                "SELECT status,current_run_id,current_session_id,last_run_state,next_action_hint FROM queue_items WHERE project_id=?",
                (project_id,),
            ).fetchone()
        current_queue_row = dict(found) if found else None
        current_run_id = _text((current_queue_row or {}).get("current_run_id"))
        current_status = _text((current_queue_row or {}).get("status"))
        stale_callback = bool(
            current_queue_row is not None and (not run_id or current_run_id != run_id)
        )
        return current_queue_row, stale_callback, current_status

    def _worker_callback_result_row(
        self, project_id: str, *, scan_all_queue_rows: bool = False
    ) -> dict[str, Any]:
        if not project_id:
            return {}
        if scan_all_queue_rows:
            return next(
                (
                    item
                    for item in self.queue_rows()
                    if item.get("project_id") == project_id
                ),
                {},
            )
        return self.queue_row(project_id) or {}

    def _emit_worker_callback_side_effect(
        self,
        *,
        idempotency_key: str,
        event_payload: dict[str, Any],
        event_type: str,
        run_id: str,
        project_id: str,
    ) -> tuple[int, bool, dict[str, Any]]:
        event_type_name = _worker_callback_event_type_name(event_type)
        entity_id = _worker_callback_entity_id(run_id, project_id)
        replayed_event_id = self._replayed_event_id(
            idempotency_key,
            event_payload,
            event_type=event_type_name,
            entity_type="run",
            entity_id=entity_id,
        )
        if replayed_event_id is not None:
            return (
                replayed_event_id,
                False,
                self._worker_callback_result_row(project_id),
            )
        event_id, inserted = self.append_event(
            idempotency_key=idempotency_key,
            event_type=event_type_name,
            entity_type="run",
            entity_id=entity_id,
            payload=event_payload,
        )
        return event_id, inserted, self._worker_callback_result_row(project_id)

    def _try_record_late_terminal_success_worker_callback(
        self,
        *,
        payload: dict[str, Any],
        current_queue_row: dict[str, Any] | None,
        run_id: str,
        project_id: str,
        event_type: str,
        idempotency_key: str,
        received_by: str,
    ) -> tuple[int, bool, dict[str, Any]] | None:
        if not (
            _completed_success_queue_row(current_queue_row, run_id)
            and event_type not in TERMINAL_SUCCESS_CALLBACK_STATES
        ):
            return None
        assert current_queue_row is not None
        event_payload = _late_terminal_success_worker_callback_payload(
            payload, current_queue_row, received_by=received_by
        )
        return self._emit_worker_callback_side_effect(
            idempotency_key=idempotency_key,
            event_payload=event_payload,
            event_type=event_type,
            run_id=run_id,
            project_id=project_id,
        )

    def _try_record_stale_worker_callback(
        self,
        *,
        payload: dict[str, Any],
        current_queue_row: dict[str, Any] | None,
        stale_callback: bool,
        run_id: str,
        project_id: str,
        event_type: str,
        idempotency_key: str,
        received_by: str,
        current_status: str,
    ) -> tuple[int, bool, dict[str, Any]] | None:
        if not (stale_callback and current_queue_row):
            return None
        preserved_status = (
            _text(current_queue_row.get("status")) or QueueStatus.NEEDS_REVIEW.value
        )
        preserved_hint = (
            _text(current_queue_row.get("next_action_hint")) or "await_callback"
        )
        _ = _text(current_queue_row.get("last_run_state")) or preserved_status
        event_payload = _stale_worker_callback_payload(
            payload,
            current_queue_row,
            received_by=received_by,
            status=preserved_status,
            next_action_hint=preserved_hint,
            ignore_reason=_stale_worker_callback_ignore_reason(
                run_id=run_id, current_status=current_status
            ),
        )
        return self._emit_worker_callback_side_effect(
            idempotency_key=idempotency_key,
            event_payload=event_payload,
            event_type=event_type,
            run_id=run_id,
            project_id=project_id,
        )

    def _persist_applied_worker_callback(
        self,
        conn: sqlite3.Connection,
        *,
        now: str,
        payload: dict[str, Any],
        project_id: str,
        run_id: str,
        event_type: str,
        idempotency_key: str,
        event_payload: dict[str, Any],
        status: str,
        next_action_hint: str,
        manual_review_required: int,
        last_error: str,
    ) -> tuple[int, bool]:
        summary = (
            f"worker callback {event_type}: "
            f"{_text(payload.get('reason')) or 'worker reported ready'}"
        )
        last_run_state, run_state, gate_state = _contract_worker_callback_states(
            event_type, _text(payload.get("gate_state"))
        )
        run_ended_at = None if event_type == "session_started" else now
        if project_id:
            conn.execute(
                """UPDATE queue_items
                SET status=?, current_session_id=COALESCE(NULLIF(?, ''), current_session_id), last_run_state=?,
                    last_event_type=?, next_action_hint=?, manual_review_required=?, last_error=?,
                    last_result_summary=?, last_callback_at=?, updated_at=?
                WHERE project_id=?""",
                (
                    status,
                    _text(payload.get("session_id")),
                    last_run_state,
                    "worker_callback",
                    next_action_hint,
                    manual_review_required,
                    last_error,
                    summary,
                    now,
                    now,
                    project_id,
                ),
            )
        if run_id and project_id:
            conn.execute(
                """INSERT INTO runs(run_id,project_id,session_id,state,dispatch_mode,started_at,ended_at,last_callback_at,gate_state,current_activity,idempotency_key,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(run_id) DO UPDATE SET
                    session_id=COALESCE(NULLIF(excluded.session_id, ''), runs.session_id),
                    state=excluded.state,
                    ended_at=excluded.ended_at,
                    last_callback_at=excluded.last_callback_at,
                    gate_state=excluded.gate_state,
                    current_activity=excluded.current_activity,
                    updated_at=excluded.updated_at""",
                (
                    run_id,
                    project_id,
                    _text(payload.get("session_id")),
                    run_state,
                    "callback",
                    now,
                    run_ended_at,
                    now,
                    gate_state,
                    "worker_callback",
                    idempotency_key,
                    now,
                ),
            )
        return self._append_event_in_conn(
            conn,
            idempotency_key=idempotency_key,
            event_type=_worker_callback_event_type_name(event_type),
            entity_type="run",
            entity_id=_worker_callback_entity_id(run_id, project_id),
            payload=event_payload,
        )

    def claim_paper_review(
        self, paper_id: str, request: PaperReviewClaimRequest
    ) -> tuple[int, bool, dict[str, Any]]:
        if not _text(request.reviewer):
            raise ValueError("reviewer is required")
        row = self._require_paper_review(paper_id)
        current = _normal(row.get("review_status"))
        if current in {
            ReviewStatus.FINALIZED.value,
            ReviewStatus.REJECTED.value,
            ReviewStatus.APPROVED_FOR_FINALIZATION.value,
        }:
            raise ValueError(f"cannot claim paper review from {current}")
        if (
            current == ReviewStatus.BLOCKED.value
            and _text(row.get("blocker"))
            and not request.clear_blocker
        ):
            raise ValueError("blocked review requires clear_blocker=true to claim")
        if current not in {
            ReviewStatus.QUEUED.value,
            ReviewStatus.CLAIMED.value,
            ReviewStatus.TRIAGE_READY.value,
            ReviewStatus.UNREVIEWED.value,
            ReviewStatus.CHANGES_REQUESTED.value,
            ReviewStatus.BLOCKED.value,
            ReviewStatus.IN_REVIEW.value,
        }:
            raise ValueError(f"cannot claim paper review from {current}")
        payload = self._mutation_payload(request, action="claim")
        payload.update({"to_status": ReviewStatus.CLAIMED.value})
        now = utc_now()
        checklist = _normalize_review_checklist(_json_dict(row.get("checklist_json")))
        with self._connect() as conn:
            event_id, inserted = self._append_event_in_conn(
                conn,
                idempotency_key=request.idempotency_key,
                event_type="paper_review.claimed",
                entity_type="paper_review",
                entity_id=paper_id,
                payload=payload,
            )
            if inserted:
                conn.execute(
                    """UPDATE paper_review_items
                    SET review_status=?, reviewer=?, blocker=?, claimed_at=?, checklist_json=?, updated_at=?
                    WHERE paper_id=?""",
                    (
                        ReviewStatus.CLAIMED.value,
                        _text(request.reviewer),
                        "" if request.clear_blocker else _text(row.get("blocker")),
                        now,
                        _json(checklist),
                        now,
                        paper_id,
                    ),
                )
        return event_id, inserted, self.paper_review_row(paper_id) or {}

    def update_paper_review_checklist(
        self, paper_id: str, item_id: str, request: PaperReviewChecklistUpdateRequest
    ) -> tuple[int, bool, dict[str, Any]]:
        row = self._require_paper_review(paper_id)
        checklist = _normalize_review_checklist(_json_dict(row.get("checklist_json")))
        item = next(
            (entry for entry in checklist["items"] if entry["id"] == item_id), None
        )
        if item is None:
            raise ValueError(f"unknown checklist item {item_id}")
        status = _text(request.status)
        note = _text(request.note)
        if status == "fail" and not note:
            raise ValueError("fail checklist status requires a note")
        if status == "accepted_risk" and not note:
            raise ValueError("accepted_risk checklist status requires a note")
        if item_id == "final_human_approval" and status in {
            "accepted_risk",
            "not_applicable",
        }:
            raise ValueError(
                "automated finalization approval must be pass or fail/pending"
            )
        if status == "not_applicable" and item.get("required") and not note:
            raise ValueError("not_applicable on a required item requires a note")
        payload = self._mutation_payload(request, action="checklist_update")
        payload["item_id"] = item_id
        now = utc_now()
        item.update(
            {
                "status": status,
                "note": note,
                "updated_at": now,
                "updated_by": _text(request.requested_by),
            }
        )
        risks = [
            risk
            for risk in checklist.get("accepted_risks", [])
            if isinstance(risk, dict) and risk.get("item_id") != item_id
        ]
        if status == "accepted_risk":
            risks.append(
                {
                    "item_id": item_id,
                    "risk": note,
                    "accepted_by": _text(request.requested_by),
                    "accepted_at": now,
                }
            )
        checklist["accepted_risks"] = risks
        checklist["progress"] = _progress_for_items(checklist["items"])
        with self._connect() as conn:
            event_id, inserted = self._append_event_in_conn(
                conn,
                idempotency_key=request.idempotency_key,
                event_type="paper_review.checklist_updated",
                entity_type="paper_review",
                entity_id=paper_id,
                payload=payload,
            )
            if inserted:
                conn.execute(
                    "UPDATE paper_review_items SET checklist_json=?, updated_at=? WHERE paper_id=?",
                    (_json(checklist), now, paper_id),
                )
        return event_id, inserted, self.paper_review_row(paper_id) or {}

    def update_paper_review_status(
        self, paper_id: str, request: PaperReviewStatusUpdateRequest
    ) -> tuple[int, bool, dict[str, Any]]:
        row = self._require_paper_review(paper_id)
        current = _normal(row.get("review_status"))
        target = request.review_status.value
        if target == ReviewStatus.APPROVED_FOR_FINALIZATION.value:
            raise ValueError("use approve-finalization endpoint for approval")
        if target in {ReviewStatus.FINALIZED.value}:
            raise ValueError(
                "finalized status is reserved for finalization package workflow"
            )
        if (
            target not in ALLOWED_STATUS_TRANSITIONS.get(current, set())
            and target != current
        ):
            raise ValueError(f"invalid review status transition {current} -> {target}")
        blocker = _text(request.blocker)
        note = _text(request.note)
        if target in {
            ReviewStatus.BLOCKED.value,
            ReviewStatus.CHANGES_REQUESTED.value,
            ReviewStatus.REJECTED.value,
        } and not (blocker or note):
            raise ValueError(f"{target} requires blocker or note")
        payload = self._mutation_payload(request, action="status_update")
        payload.update({"to_status": target})
        now = utc_now()
        next_blocker = blocker if target == ReviewStatus.BLOCKED.value else ""
        decision_summary = (
            note
            if target
            in {ReviewStatus.REJECTED.value, ReviewStatus.CHANGES_REQUESTED.value}
            else _text(row.get("decision_summary"))
        )
        with self._connect() as conn:
            event_id, inserted = self._append_event_in_conn(
                conn,
                idempotency_key=request.idempotency_key,
                event_type="paper_review.status_changed",
                entity_type="paper_review",
                entity_id=paper_id,
                payload=payload,
            )
            if inserted:
                conn.execute(
                    "UPDATE paper_review_items SET review_status=?, blocker=?, decision_summary=?, updated_at=? WHERE paper_id=?",
                    (target, next_blocker, decision_summary, now, paper_id),
                )
        return event_id, inserted, self.paper_review_row(paper_id) or {}

    def approve_paper_review_finalization(
        self, paper_id: str, request: PaperReviewApproveFinalizationRequest
    ) -> tuple[int, bool, dict[str, Any]]:
        raise ValueError(
            "manual paper approval has been removed; use automated prepare-finalization-package or rewrite-draft"
        )

    def _resolved_artifact(self, paper: dict[str, Any], field: str) -> dict[str, Any]:
        raw_path = _text(paper.get(field))
        project_dir_text = _text(paper.get("project_dir"))
        project_dir = (
            _expanduser_or_none(project_dir_text) if project_dir_text else None
        )
        path = _expanduser_or_none(raw_path) if raw_path else Path()
        if project_dir_text and project_dir is None:
            return _unresolved_artifact(field, raw_path)
        if raw_path and path is None:
            return _unresolved_artifact(field, raw_path)
        path = path or Path()
        resolved = _resolve_artifact_absolute_path(path, project_dir)
        if resolved is None:
            return _unresolved_artifact(field, raw_path)
        safe = _artifact_path_within_project(resolved, project_dir)
        exists, readable, size_bytes = _artifact_access_stats(resolved, raw_path, safe)
        return {
            "field": field,
            "path": raw_path,
            "absolute_path": str(resolved),
            "exists": exists,
            "readable": readable,
            "safe": safe,
            "size_bytes": size_bytes,
        }

    def _read_finalization_json_artifact(
        self, artifact: dict[str, Any]
    ) -> dict[str, Any]:
        if not artifact.get("readable"):
            return {}
        try:
            return _json_dict(
                Path(_text(artifact.get("absolute_path"))).read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError):
            return {}

    def _semantic_finalization_artifact_failures(
        self, artifacts: list[dict[str, Any]]
    ) -> list[str]:
        by_field = {
            str(artifact.get("field") or ""): artifact for artifact in artifacts
        }
        failures: list[str] = []

        evidence = self._read_finalization_json_artifact(
            by_field.get("evidence_bundle_path", {})
        )
        public_files = [
            item
            for item in evidence.get("public_evidence_files") or []
            if isinstance(item, dict)
        ]
        if not public_files:
            failures.append("evidence_bundle_path has no public_evidence_files")
        elif not any(
            _text(item.get("source_path")) and _text(item.get("content"))
            for item in public_files
        ):
            failures.append("evidence_bundle_path has no public evidence content")

        claim_ledger = self._read_finalization_json_artifact(
            by_field.get("claim_ledger_path", {})
        )
        claims = [
            item for item in claim_ledger.get("claims") or [] if isinstance(item, dict)
        ]
        ledger_status = _text(claim_ledger.get("ledger_status"))
        if not claims:
            failures.append("claim_ledger_path has no claims")
        if ledger_status not in {"claims_reference_evidence", "claims_require_review"}:
            failures.append(
                "claim_ledger_path ledger_status is not an evidence-linked status"
            )
        if any(
            not [
                ref for ref in claim.get("evidence_refs") or [] if isinstance(ref, dict)
            ]
            for claim in claims
        ):
            failures.append("claim_ledger_path contains claims without evidence_refs")
        if _int(claim_ledger.get("unsupported_claim_count"), 0) > 0:
            failures.append("claim_ledger_path contains unsupported claims")

        manifest = self._read_finalization_json_artifact(
            by_field.get("manifest_path", {})
        )
        if _int(manifest.get("evidence_file_count"), 0) < 1:
            failures.append("manifest_path evidence_file_count is zero")
        if _int(manifest.get("claim_count"), 0) < 1:
            failures.append("manifest_path claim_count is zero")
        if _text(manifest.get("claim_ledger_status")) not in {
            "claims_reference_evidence",
            "claims_require_review",
        }:
            failures.append(
                "manifest_path claim_ledger_status is not an evidence-linked status"
            )
        return failures

    def _finalization_manifest_path(self, paper_id: str, idempotency_key: str) -> Path:
        return (
            self.path.parent
            / "finalization_packages"
            / _slug_id(paper_id)
            / _slug_id(idempotency_key)
            / "finalization_manifest.json"
        )

    def _load_manifest(self, package_path: str) -> dict[str, Any]:
        if not package_path:
            return {}
        path = Path(package_path)
        try:
            return _json_dict(path.read_text(encoding="utf-8")) if path.exists() else {}
        except OSError:
            return {}

    def _replay_paper_review_finalization_if_any(
        self,
        paper_id: str,
        request: PaperReviewPrepareFinalizationRequest,
        payload: dict[str, Any],
    ) -> tuple[int | None, bool, dict[str, Any], str, dict[str, Any]] | None:
        if request.dry_run:
            return None
        replayed_event_id = self._replayed_event_id(
            request.idempotency_key,
            payload,
            event_type="paper_review.finalization_package_prepared",
            entity_type="paper_review",
            entity_id=paper_id,
        )
        if replayed_event_id is None:
            return None
        item = self.paper_review_row(paper_id) or {}
        path = _text(item.get("finalization_package_path"))
        return replayed_event_id, False, item, path, self._load_manifest(path)

    def _ensure_finalization_review_status(
        self,
        current: str,
        *,
        require_approval: bool,
        dry_run: bool,
    ) -> None:
        if dry_run:
            return
        if require_approval and current != ReviewStatus.APPROVED_FOR_FINALIZATION.value:
            raise ValueError(
                "legacy approval-gated finalization requires internal approved_for_finalization state"
            )
        if not require_approval and current in _AUTOMATED_FINALIZATION_BLOCKED_STATUSES:
            raise ValueError(
                f"automated finalization cannot publish paper reviews with review_status={current}"
            )

    def _collect_finalization_artifacts(
        self, paper: dict[str, Any]
    ) -> list[dict[str, Any]]:
        return [
            self._resolved_artifact(paper, field)
            for field in _FINALIZATION_PACKAGE_ARTIFACT_FIELDS
        ]

    def _check_finalization_artifact_gates(
        self, artifacts: list[dict[str, Any]], *, dry_run: bool
    ) -> list[str]:
        unreadable = [
            artifact["field"] for artifact in artifacts if not artifact["readable"]
        ]
        if unreadable and not dry_run:
            raise ValueError(
                f"finalization package requires readable artifacts: {', '.join(unreadable)}"
            )
        semantic_failures = (
            []
            if unreadable
            else self._semantic_finalization_artifact_failures(artifacts)
        )
        if semantic_failures and not dry_run:
            raise ValueError(
                f"semantic evidence gate failed: {', '.join(semantic_failures)}"
            )
        return semantic_failures

    def _build_finalization_package_manifest(
        self,
        *,
        paper_id: str,
        request: PaperReviewPrepareFinalizationRequest,
        paper: dict[str, Any],
        row: dict[str, Any],
        current: str,
        require_approval: bool,
        artifacts: list[dict[str, Any]],
        semantic_failures: list[str],
        checklist: list[dict[str, Any]],
        now: str,
    ) -> dict[str, Any]:
        return {
            "schema": "paper_finalization_package_v1",
            "generated_at": now,
            "dry_run": request.dry_run,
            "requested_by": request.requested_by,
            "target_label": request.target_label,
            "paper_id": paper_id,
            "project_id": _text(paper.get("project_id")),
            "project_name": _text(paper.get("project_name")),
            "paper_status": _text(paper.get("paper_status")),
            "automation_status": current,
            "automation_actor": _text(row.get("reviewer")),
            "decision_summary": _text(row.get("decision_summary")),
            "require_approval": require_approval,
            "automated_publication": not require_approval,
            "artifacts": artifacts,
            "semantic_evidence_gate": {
                "ok": not semantic_failures,
                "failures": semantic_failures,
            },
            "checklist": checklist,
            "review_item": self.paper_review_row(paper_id) or {},
            "no_submission_side_effects": True,
        }

    def _persist_finalization_package(
        self,
        paper_id: str,
        request: PaperReviewPrepareFinalizationRequest,
        payload: dict[str, Any],
        package_path: Path,
        manifest: dict[str, Any],
        now: str,
    ) -> tuple[int | None, bool, dict[str, Any], str, dict[str, Any]]:
        previous_manifest_exists, previous_manifest_content = _existing_file_snapshot(
            package_path,
            label="finalization package manifest",
        )
        _atomic_write_text(package_path, _json(manifest))
        try:
            with self._connect() as conn:
                event_id, inserted = self._append_event_in_conn(
                    conn,
                    idempotency_key=request.idempotency_key,
                    event_type="paper_review.finalization_package_prepared",
                    entity_type="paper_review",
                    entity_id=paper_id,
                    payload=payload,
                )
                if inserted:
                    conn.execute(
                        "UPDATE paper_review_items SET review_status=?, finalization_package_path=?, finalized_at=?, updated_at=? WHERE paper_id=?",
                        (
                            ReviewStatus.FINALIZED.value,
                            str(package_path),
                            now,
                            now,
                            paper_id,
                        ),
                    )
        except Exception:
            _restore_or_remove_path(
                package_path,
                existed=previous_manifest_exists,
                content=previous_manifest_content,
            )
            raise
        item = self.paper_review_row(paper_id) or {}
        return event_id, inserted, item, str(package_path), manifest

    def prepare_paper_review_finalization_package(
        self,
        paper_id: str,
        request: PaperReviewPrepareFinalizationRequest,
        *,
        require_approval: bool = True,
    ) -> tuple[int | None, bool, dict[str, Any], str, dict[str, Any]]:
        row = self._require_paper_review(paper_id)
        payload = self._mutation_payload(request, action="prepare_finalization_package")
        payload.update(
            {
                "to_status": ReviewStatus.FINALIZED.value,
                "require_approval": require_approval,
            }
        )
        replay = self._replay_paper_review_finalization_if_any(
            paper_id, request, payload
        )
        if replay is not None:
            return replay
        current = _normal(row.get("review_status"))
        self._ensure_finalization_review_status(
            current, require_approval=require_approval, dry_run=request.dry_run
        )
        paper = self.paper_row(paper_id)
        if paper is None:
            raise ValueError("paper row not found")
        artifacts = self._collect_finalization_artifacts(paper)
        semantic_failures = self._check_finalization_artifact_gates(
            artifacts, dry_run=request.dry_run
        )
        if not request.dry_run and current == ReviewStatus.FINALIZED.value:
            item = self.paper_review_row(paper_id) or {}
            path = _text(item.get("finalization_package_path"))
            return None, False, item, path, self._load_manifest(path)
        package_path = self._finalization_manifest_path(
            paper_id, request.idempotency_key
        )
        now = utc_now()
        manifest = self._build_finalization_package_manifest(
            paper_id=paper_id,
            request=request,
            paper=paper,
            row=row,
            current=current,
            require_approval=require_approval,
            artifacts=artifacts,
            semantic_failures=semantic_failures,
            checklist=self.paper_review_checklist(paper_id),
            now=now,
        )
        if request.dry_run:
            return (
                None,
                False,
                self.paper_review_row(paper_id) or {},
                str(package_path),
                manifest,
            )
        return self._persist_finalization_package(
            paper_id, request, payload, package_path, manifest, now
        )

    def event_rows(
        self,
        limit: int = 100,
        *,
        entity_type: str = "",
        entity_id: str = "",
        event_type: str = "",
        search: str = "",
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if entity_type:
            clauses.append("entity_type = ?")
            params.append(entity_type)
        if entity_id:
            clauses.append("entity_id = ?")
            params.append(entity_id)
        if event_type:
            clauses.append("event_type = ?")
            params.append(event_type)
        if search:
            clauses.append(
                "(event_type LIKE ? OR entity_id LIKE ? OR payload_json LIKE ?)"
            )
            needle = f"%{search}%"
            params.extend([needle, needle, needle])
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(1, min(limit, 1000)))
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM events {where} ORDER BY event_id DESC LIMIT ?", params
            ).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            item["payload"] = json.loads(item.pop("payload_json"))
            item.pop("payload_hash", None)
            out.append(item)
        return out

    def event_page(
        self,
        *,
        event_id: str = "",
        entity_type: str = "",
        entity_id: str = "",
        event_type: str = "",
        search: str = "",
        page_size: int = 50,
        cursor: str = "",
        include_payload: bool = False,
        sort: str = "recent",
    ) -> tuple[list[dict[str, Any]], str | None, bool]:
        safe_size = max(1, min(page_size, 200))
        clauses, params = _event_page_filter_clauses(
            event_id=event_id,
            entity_type=entity_type,
            entity_id=entity_id,
            event_type=event_type,
            search=search,
            cursor=cursor,
        )
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        order_by = _event_page_order_by(sort)
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM events {where} ORDER BY {order_by} LIMIT ?",
                (*params, safe_size + 1),
            ).fetchall()
        out = []
        for row in rows[:safe_size]:
            item = dict(row)
            _event_page_attach_payload_fields(item, include_payload=include_payload)
            out.append(item)
        has_more = len(rows) > safe_size
        next_cursor = str(out[-1]["event_id"]) if has_more and out else None
        return out, next_cursor, has_more

    def operator_queue_rows_sql(self) -> list[dict[str, Any]]:
        """Return queue rows needed for normalized operator-count aggregation.

        This intentionally stays SQL-backed so v1 overview does not regress to
        legacy full-list helper methods that tests guard against.
        """

        with self._connect() as conn:
            rows = conn.execute(
                """SELECT q.*,
                    p.project_name AS project_name,
                    p.project_dir AS project_dir,
                    p.notion_page_url AS notion_page_url,
                    p.notion_page_id AS notion_page_id,
                    p.origin_idea_status AS origin_idea_status,
                    (SELECT pa.paper_id FROM papers pa WHERE pa.project_id = q.project_id AND (pa.run_id = q.current_run_id OR (q.current_run_id = '' AND q.status NOT IN ('awaiting_wake','dispatching','reconciling','running','wake_received'))) ORDER BY pa.updated_at DESC LIMIT 1) AS related_paper_id,
                    (SELECT pa.paper_status FROM papers pa WHERE pa.project_id = q.project_id AND (pa.run_id = q.current_run_id OR (q.current_run_id = '' AND q.status NOT IN ('awaiting_wake','dispatching','reconciling','running','wake_received'))) ORDER BY pa.updated_at DESC LIMIT 1) AS related_paper_status,
                    (SELECT rv.review_status FROM papers pa LEFT JOIN paper_review_items rv USING(paper_id) WHERE pa.project_id = q.project_id AND (pa.run_id = q.current_run_id OR (q.current_run_id = '' AND q.status NOT IN ('awaiting_wake','dispatching','reconciling','running','wake_received'))) ORDER BY pa.updated_at DESC LIMIT 1) AS related_review_status,
                    (SELECT rv.finalization_package_path FROM papers pa LEFT JOIN paper_review_items rv USING(paper_id) WHERE pa.project_id = q.project_id AND (pa.run_id = q.current_run_id OR (q.current_run_id = '' AND q.status NOT IN ('awaiting_wake','dispatching','reconciling','running','wake_received'))) ORDER BY pa.updated_at DESC LIMIT 1) AS related_finalization_package_path,
                    (SELECT pa.draft_markdown_path FROM papers pa WHERE pa.project_id = q.project_id AND (pa.run_id = q.current_run_id OR (q.current_run_id = '' AND q.status NOT IN ('awaiting_wake','dispatching','reconciling','running','wake_received'))) ORDER BY pa.updated_at DESC LIMIT 1) AS related_draft_markdown_path,
                    (SELECT pa.evidence_bundle_path FROM papers pa WHERE pa.project_id = q.project_id AND (pa.run_id = q.current_run_id OR (q.current_run_id = '' AND q.status NOT IN ('awaiting_wake','dispatching','reconciling','running','wake_received'))) ORDER BY pa.updated_at DESC LIMIT 1) AS related_evidence_bundle_path,
                    (SELECT pa.claim_ledger_path FROM papers pa WHERE pa.project_id = q.project_id AND (pa.run_id = q.current_run_id OR (q.current_run_id = '' AND q.status NOT IN ('awaiting_wake','dispatching','reconciling','running','wake_received'))) ORDER BY pa.updated_at DESC LIMIT 1) AS related_claim_ledger_path,
                    (SELECT pa.manifest_path FROM papers pa WHERE pa.project_id = q.project_id AND (pa.run_id = q.current_run_id OR (q.current_run_id = '' AND q.status NOT IN ('awaiting_wake','dispatching','reconciling','running','wake_received'))) ORDER BY pa.updated_at DESC LIMIT 1) AS related_manifest_path,
                    (SELECT ci.corpus_import_id FROM papers pa LEFT JOIN corpus_imports ci USING(paper_id) WHERE pa.project_id = q.project_id AND (pa.run_id = q.current_run_id OR (q.current_run_id = '' AND q.status NOT IN ('awaiting_wake','dispatching','reconciling','running','wake_received'))) ORDER BY pa.updated_at DESC LIMIT 1) AS related_corpus_import_id,
                    (SELECT ci.artifact_slug FROM papers pa LEFT JOIN corpus_imports ci USING(paper_id) WHERE pa.project_id = q.project_id AND (pa.run_id = q.current_run_id OR (q.current_run_id = '' AND q.status NOT IN ('awaiting_wake','dispatching','reconciling','running','wake_received'))) ORDER BY pa.updated_at DESC LIMIT 1) AS related_artifact_slug,
                    (SELECT ci.source_record_fingerprint FROM papers pa LEFT JOIN corpus_imports ci USING(paper_id) WHERE pa.project_id = q.project_id AND (pa.run_id = q.current_run_id OR (q.current_run_id = '' AND q.status NOT IN ('awaiting_wake','dispatching','reconciling','running','wake_received'))) ORDER BY pa.updated_at DESC LIMIT 1) AS related_source_record_fingerprint,
                    (SELECT CASE WHEN ci.paper_id IS NULL THEN 0 ELSE 1 END FROM papers pa LEFT JOIN corpus_imports ci USING(paper_id) WHERE pa.project_id = q.project_id AND (pa.run_id = q.current_run_id OR (q.current_run_id = '' AND q.status NOT IN ('awaiting_wake','dispatching','reconciling','running','wake_received'))) ORDER BY pa.updated_at DESC LIMIT 1) AS related_corpus_imported,
                    EXISTS (SELECT 1 FROM events ev WHERE ev.event_type = 'followup.launch' AND ev.entity_type = 'project' AND ev.entity_id = q.project_id) AS followup_launched,
                    p.created_at AS project_created_at,
                    p.updated_at AS project_updated_at
                FROM queue_items q JOIN projects p USING(project_id)
                WHERE q.status != ?
                   OR q.next_action_hint = ?
                   OR q.manual_review_required = 1
                ORDER BY q.updated_at DESC""",
                (QueueStatus.CANCELED.value, "draft_paper_or_select_next_project"),
            ).fetchall()
        return [dict(row) for row in rows]

    def active_items(self) -> list[dict[str, Any]]:
        return [
            row for row in self.queue_rows() if row.get("status") in ACTIVE_STATUSES
        ]

    def active_items_sql(self, *, limit: int = 10) -> list[dict[str, Any]]:
        safe_limit = max(1, min(limit, 50))
        with self._connect() as conn:
            rows = conn.execute(
                f"""SELECT q.*,
                    p.project_name AS project_name,
                    p.project_dir AS project_dir,
                    p.notion_page_url AS notion_page_url,
                    p.notion_page_id AS notion_page_id,
                    p.origin_idea_status AS origin_idea_status,
                    (SELECT pa.paper_id FROM papers pa WHERE pa.project_id = q.project_id AND (pa.run_id = q.current_run_id OR (q.current_run_id = '' AND q.status NOT IN ('awaiting_wake','dispatching','reconciling','running','wake_received'))) ORDER BY pa.updated_at DESC LIMIT 1) AS related_paper_id,
                    (SELECT pa.paper_status FROM papers pa WHERE pa.project_id = q.project_id AND (pa.run_id = q.current_run_id OR (q.current_run_id = '' AND q.status NOT IN ('awaiting_wake','dispatching','reconciling','running','wake_received'))) ORDER BY pa.updated_at DESC LIMIT 1) AS related_paper_status,
                    (SELECT rv.review_status FROM papers pa LEFT JOIN paper_review_items rv USING(paper_id) WHERE pa.project_id = q.project_id AND (pa.run_id = q.current_run_id OR (q.current_run_id = '' AND q.status NOT IN ('awaiting_wake','dispatching','reconciling','running','wake_received'))) ORDER BY pa.updated_at DESC LIMIT 1) AS related_review_status,
                    (SELECT rv.finalization_package_path FROM papers pa LEFT JOIN paper_review_items rv USING(paper_id) WHERE pa.project_id = q.project_id AND (pa.run_id = q.current_run_id OR (q.current_run_id = '' AND q.status NOT IN ('awaiting_wake','dispatching','reconciling','running','wake_received'))) ORDER BY pa.updated_at DESC LIMIT 1) AS related_finalization_package_path,
                    (SELECT pa.draft_markdown_path FROM papers pa WHERE pa.project_id = q.project_id AND (pa.run_id = q.current_run_id OR (q.current_run_id = '' AND q.status NOT IN ('awaiting_wake','dispatching','reconciling','running','wake_received'))) ORDER BY pa.updated_at DESC LIMIT 1) AS related_draft_markdown_path,
                    (SELECT pa.evidence_bundle_path FROM papers pa WHERE pa.project_id = q.project_id AND (pa.run_id = q.current_run_id OR (q.current_run_id = '' AND q.status NOT IN ('awaiting_wake','dispatching','reconciling','running','wake_received'))) ORDER BY pa.updated_at DESC LIMIT 1) AS related_evidence_bundle_path,
                    (SELECT pa.claim_ledger_path FROM papers pa WHERE pa.project_id = q.project_id AND (pa.run_id = q.current_run_id OR (q.current_run_id = '' AND q.status NOT IN ('awaiting_wake','dispatching','reconciling','running','wake_received'))) ORDER BY pa.updated_at DESC LIMIT 1) AS related_claim_ledger_path,
                    (SELECT pa.manifest_path FROM papers pa WHERE pa.project_id = q.project_id AND (pa.run_id = q.current_run_id OR (q.current_run_id = '' AND q.status NOT IN ('awaiting_wake','dispatching','reconciling','running','wake_received'))) ORDER BY pa.updated_at DESC LIMIT 1) AS related_manifest_path,
                    (SELECT ci.corpus_import_id FROM papers pa LEFT JOIN corpus_imports ci USING(paper_id) WHERE pa.project_id = q.project_id AND (pa.run_id = q.current_run_id OR (q.current_run_id = '' AND q.status NOT IN ('awaiting_wake','dispatching','reconciling','running','wake_received'))) ORDER BY pa.updated_at DESC LIMIT 1) AS related_corpus_import_id,
                    (SELECT ci.artifact_slug FROM papers pa LEFT JOIN corpus_imports ci USING(paper_id) WHERE pa.project_id = q.project_id AND (pa.run_id = q.current_run_id OR (q.current_run_id = '' AND q.status NOT IN ('awaiting_wake','dispatching','reconciling','running','wake_received'))) ORDER BY pa.updated_at DESC LIMIT 1) AS related_artifact_slug,
                    (SELECT ci.source_record_fingerprint FROM papers pa LEFT JOIN corpus_imports ci USING(paper_id) WHERE pa.project_id = q.project_id AND (pa.run_id = q.current_run_id OR (q.current_run_id = '' AND q.status NOT IN ('awaiting_wake','dispatching','reconciling','running','wake_received'))) ORDER BY pa.updated_at DESC LIMIT 1) AS related_source_record_fingerprint,
                    (SELECT CASE WHEN ci.paper_id IS NULL THEN 0 ELSE 1 END FROM papers pa LEFT JOIN corpus_imports ci USING(paper_id) WHERE pa.project_id = q.project_id AND (pa.run_id = q.current_run_id OR (q.current_run_id = '' AND q.status NOT IN ('awaiting_wake','dispatching','reconciling','running','wake_received'))) ORDER BY pa.updated_at DESC LIMIT 1) AS related_corpus_imported,
                    p.created_at AS project_created_at,
                    p.updated_at AS project_updated_at
                FROM queue_items q JOIN projects p USING(project_id)
                WHERE q.status IN ({",".join("?" for _ in ACTIVE_STATUSES)})
                ORDER BY q.updated_at DESC
                LIMIT ?""",
                (*sorted(ACTIVE_STATUSES), safe_limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def queued_items_sql(self, *, limit: int = 200) -> list[dict[str, Any]]:
        safe_limit = max(1, min(limit, 500))
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT q.*,
                    p.project_name AS project_name,
                    p.project_dir AS project_dir,
                    p.notion_page_url AS notion_page_url,
                    p.notion_page_id AS notion_page_id,
                    p.origin_idea_status AS origin_idea_status,
                    p.created_at AS project_created_at,
                    p.updated_at AS project_updated_at
                FROM queue_items q JOIN projects p USING(project_id)
                WHERE q.status = ? AND q.manual_review_required = 0
                ORDER BY q.dispatch_priority ASC, q.selection_rank ASC, q.updated_at ASC
                LIMIT ?""",
                (QueueStatus.QUEUED.value, safe_limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def recently_completed_items_sql(self, *, limit: int = 50) -> list[dict[str, Any]]:
        safe_limit = max(1, min(limit, 200))
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT q.*,
                    p.project_name AS project_name,
                    p.project_dir AS project_dir,
                    p.notion_page_url AS notion_page_url,
                    p.notion_page_id AS notion_page_id,
                    p.origin_idea_status AS origin_idea_status,
                    p.created_at AS project_created_at,
                    p.updated_at AS project_updated_at
                FROM queue_items q JOIN projects p USING(project_id)
                WHERE q.status = ?
                   OR q.last_run_state IN ('wake_ready', 'completed', 'complete', 'finished')
                ORDER BY q.updated_at DESC
                LIMIT ?""",
                (QueueStatus.COMPLETED.value, safe_limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def next_candidate_sql(self) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """SELECT q.*,
                    p.project_name AS project_name,
                    p.project_dir AS project_dir,
                    p.notion_page_url AS notion_page_url,
                    p.notion_page_id AS notion_page_id,
                    p.origin_idea_status AS origin_idea_status,
                    (SELECT pa.paper_id FROM papers pa WHERE pa.project_id = q.project_id AND (pa.run_id = q.current_run_id OR (q.current_run_id = '' AND q.status NOT IN ('awaiting_wake','dispatching','reconciling','running','wake_received'))) ORDER BY pa.updated_at DESC LIMIT 1) AS related_paper_id,
                    (SELECT pa.paper_status FROM papers pa WHERE pa.project_id = q.project_id AND (pa.run_id = q.current_run_id OR (q.current_run_id = '' AND q.status NOT IN ('awaiting_wake','dispatching','reconciling','running','wake_received'))) ORDER BY pa.updated_at DESC LIMIT 1) AS related_paper_status,
                    (SELECT rv.review_status FROM papers pa LEFT JOIN paper_review_items rv USING(paper_id) WHERE pa.project_id = q.project_id AND (pa.run_id = q.current_run_id OR (q.current_run_id = '' AND q.status NOT IN ('awaiting_wake','dispatching','reconciling','running','wake_received'))) ORDER BY pa.updated_at DESC LIMIT 1) AS related_review_status,
                    (SELECT rv.finalization_package_path FROM papers pa LEFT JOIN paper_review_items rv USING(paper_id) WHERE pa.project_id = q.project_id AND (pa.run_id = q.current_run_id OR (q.current_run_id = '' AND q.status NOT IN ('awaiting_wake','dispatching','reconciling','running','wake_received'))) ORDER BY pa.updated_at DESC LIMIT 1) AS related_finalization_package_path,
                    (SELECT pa.draft_markdown_path FROM papers pa WHERE pa.project_id = q.project_id AND (pa.run_id = q.current_run_id OR (q.current_run_id = '' AND q.status NOT IN ('awaiting_wake','dispatching','reconciling','running','wake_received'))) ORDER BY pa.updated_at DESC LIMIT 1) AS related_draft_markdown_path,
                    (SELECT pa.evidence_bundle_path FROM papers pa WHERE pa.project_id = q.project_id AND (pa.run_id = q.current_run_id OR (q.current_run_id = '' AND q.status NOT IN ('awaiting_wake','dispatching','reconciling','running','wake_received'))) ORDER BY pa.updated_at DESC LIMIT 1) AS related_evidence_bundle_path,
                    (SELECT pa.claim_ledger_path FROM papers pa WHERE pa.project_id = q.project_id AND (pa.run_id = q.current_run_id OR (q.current_run_id = '' AND q.status NOT IN ('awaiting_wake','dispatching','reconciling','running','wake_received'))) ORDER BY pa.updated_at DESC LIMIT 1) AS related_claim_ledger_path,
                    (SELECT pa.manifest_path FROM papers pa WHERE pa.project_id = q.project_id AND (pa.run_id = q.current_run_id OR (q.current_run_id = '' AND q.status NOT IN ('awaiting_wake','dispatching','reconciling','running','wake_received'))) ORDER BY pa.updated_at DESC LIMIT 1) AS related_manifest_path,
                    (SELECT ci.corpus_import_id FROM papers pa LEFT JOIN corpus_imports ci USING(paper_id) WHERE pa.project_id = q.project_id AND (pa.run_id = q.current_run_id OR (q.current_run_id = '' AND q.status NOT IN ('awaiting_wake','dispatching','reconciling','running','wake_received'))) ORDER BY pa.updated_at DESC LIMIT 1) AS related_corpus_import_id,
                    (SELECT ci.artifact_slug FROM papers pa LEFT JOIN corpus_imports ci USING(paper_id) WHERE pa.project_id = q.project_id AND (pa.run_id = q.current_run_id OR (q.current_run_id = '' AND q.status NOT IN ('awaiting_wake','dispatching','reconciling','running','wake_received'))) ORDER BY pa.updated_at DESC LIMIT 1) AS related_artifact_slug,
                    (SELECT ci.source_record_fingerprint FROM papers pa LEFT JOIN corpus_imports ci USING(paper_id) WHERE pa.project_id = q.project_id AND (pa.run_id = q.current_run_id OR (q.current_run_id = '' AND q.status NOT IN ('awaiting_wake','dispatching','reconciling','running','wake_received'))) ORDER BY pa.updated_at DESC LIMIT 1) AS related_source_record_fingerprint,
                    (SELECT CASE WHEN ci.paper_id IS NULL THEN 0 ELSE 1 END FROM papers pa LEFT JOIN corpus_imports ci USING(paper_id) WHERE pa.project_id = q.project_id AND (pa.run_id = q.current_run_id OR (q.current_run_id = '' AND q.status NOT IN ('awaiting_wake','dispatching','reconciling','running','wake_received'))) ORDER BY pa.updated_at DESC LIMIT 1) AS related_corpus_imported,
                    p.created_at AS project_created_at,
                    p.updated_at AS project_updated_at
                FROM queue_items q JOIN projects p USING(project_id)
                WHERE q.status = ?
                ORDER BY q.dispatch_priority ASC, q.updated_at DESC
                LIMIT 1""",
                (QueueStatus.QUEUED.value,),
            ).fetchone()
        return dict(row) if row else None

    def status_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for row in self.queue_rows():
            key = _text(row.get("status")) or "unknown"
            counts[key] = counts.get(key, 0) + 1
        return counts

    def recent_events(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM events ORDER BY event_id DESC LIMIT ?", (limit,)
            ).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            payload_json = item.pop("payload_json")
            item["payload"] = {
                "payload_omitted": True,
                "payload_bytes": len(payload_json.encode("utf-8")),
            }
            item.pop("payload_hash", None)
            out.append(item)
        return out

    def upsert_dashboard_observation(
        self,
        *,
        source: str,
        scope: str = "global",
        observed_at: str | None = None,
        ttl_seconds: int = 300,
        status: str = "ok",
        payload: dict[str, Any] | None = None,
    ) -> DashboardObservationRecord:
        now = utc_now()
        payload_dict = payload or {}
        payload_json = _json(payload_dict)
        payload_hash = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
        with self._connect() as conn:
            cur = conn.execute(
                """INSERT INTO dashboard_observations(source,scope,observed_at,ttl_seconds,status,payload_json,payload_hash,created_at)
                VALUES (?,?,?,?,?,?,?,?)""",
                (
                    source,
                    scope,
                    observed_at or now,
                    ttl_seconds,
                    status,
                    payload_json,
                    payload_hash,
                    now,
                ),
            )
            observation_id = _required_lastrowid(
                cur, operation="upsert_dashboard_observation"
            )
        return DashboardObservationRecord(
            observation_id=observation_id,
            source=source,  # type: ignore[arg-type]
            scope=scope,
            observed_at=observed_at or now,
            ttl_seconds=ttl_seconds,
            status=status,  # type: ignore[arg-type]
            payload=payload_dict,
            payload_hash=payload_hash,
            created_at=now,
        )

    def latest_dashboard_observation(
        self, *, source: str, scope: str = "global"
    ) -> DashboardObservationRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                """SELECT * FROM dashboard_observations
                WHERE source=? AND scope=?
                ORDER BY observed_at DESC, observation_id DESC
                LIMIT 1""",
                (source, scope),
            ).fetchone()
        if row is None:
            return None
        item = dict(row)
        payload = json.loads(item.pop("payload_json"))
        return DashboardObservationRecord(
            observation_id=item["observation_id"],
            source=item["source"],
            scope=item["scope"],
            observed_at=item["observed_at"],
            ttl_seconds=item["ttl_seconds"],
            status=item["status"],
            payload=payload,
            payload_hash=item["payload_hash"],
            created_at=item["created_at"],
        )

    def latest_dashboard_observation_summary(
        self, *, source: str, scope: str = "global"
    ) -> DashboardObservationRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                """SELECT observation_id, source, scope, observed_at, ttl_seconds, status,
                          payload_hash, created_at, payload_json, length(payload_json) AS payload_bytes
                FROM dashboard_observations
                WHERE source=? AND scope=?
                ORDER BY observed_at DESC, observation_id DESC
                LIMIT 1""",
                (source, scope),
            ).fetchone()
        if row is None:
            return None
        item = dict(row)
        payload = json.loads(item.pop("payload_json"))
        skipped_reasons: dict[str, int] = {}
        for skipped in payload.get("skipped_rows") or []:
            reason = (
                str(skipped.get("reason") or "unknown")
                if isinstance(skipped, dict)
                else "unknown"
            )
            skipped_reasons[reason] = skipped_reasons.get(reason, 0) + 1
        return DashboardObservationRecord(
            observation_id=item["observation_id"],
            source=item["source"],
            scope=item["scope"],
            observed_at=item["observed_at"],
            ttl_seconds=item["ttl_seconds"],
            status=item["status"],
            payload={
                "payload_omitted": True,
                "payload_bytes": item["payload_bytes"],
                "skipped_row_count": len(payload.get("skipped_rows") or []),
                "skipped_reasons": skipped_reasons,
            },
            payload_hash=item["payload_hash"],
            created_at=item["created_at"],
        )

    def latest_dashboard_observations(
        self, *, scope: str = "global"
    ) -> dict[str, DashboardObservationRecord]:
        out: dict[str, DashboardObservationRecord] = {}
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT d.* FROM dashboard_observations d
                JOIN (
                    SELECT source, scope, MAX(observed_at || printf('%020d', observation_id)) AS latest_key
                    FROM dashboard_observations
                    WHERE scope=?
                    GROUP BY source, scope
                ) latest ON latest.source=d.source
                    AND latest.scope=d.scope
                    AND latest.latest_key=(d.observed_at || printf('%020d', d.observation_id))
                ORDER BY d.source""",
                (scope,),
            ).fetchall()
        for row in rows:
            item = dict(row)
            payload = json.loads(item.pop("payload_json"))
            out[item["source"]] = DashboardObservationRecord(
                observation_id=item["observation_id"],
                source=item["source"],
                scope=item["scope"],
                observed_at=item["observed_at"],
                ttl_seconds=item["ttl_seconds"],
                status=item["status"],
                payload=payload,
                payload_hash=item["payload_hash"],
                created_at=item["created_at"],
            )
        return out

    def active_machine_targets(self) -> set[str]:
        return {_normal(row.get("machine_target")) for row in self.active_items()}

    def next_dispatch_candidate(
        self, *, blocked_machine_targets: set[str] | None = None
    ) -> dict[str, Any] | None:
        if self.flags().queue_paused:
            return None
        blocked = (
            self.active_machine_targets()
            if blocked_machine_targets is None
            else {_normal(item) for item in blocked_machine_targets}
        )
        candidates = [
            row
            for row in self.queue_rows()
            if _normal(row.get("status")) == QueueStatus.QUEUED.value
            and not _bool(row.get("manual_review_required"))
            and _normal(row.get("machine_target")) not in blocked
        ]
        candidates.sort(
            key=lambda row: (
                _int(row.get("dispatch_priority"), 9999),
                _int(row.get("selection_rank"), 9999),
                _text(row.get("updated_at")),
            )
        )
        return candidates[0] if candidates else None

    def next_followup_candidate(
        self, *, project_id: str = "", max_followup_depth: int = 4
    ) -> dict[str, Any] | None:
        rows = self.operator_queue_rows_sql()
        candidates = [
            row
            for row in rows
            if (not project_id or _text(row.get("project_id")) == project_id)
            and ranked_followup_readiness(
                row,
                max_followup_depth=max_followup_depth,
                explicit_project=bool(project_id),
            )["ready"]
        ]
        candidates.sort(key=promising_followup_priority_key)
        return candidates[0] if candidates else None

    def launch_followup_candidate(
        self,
        *,
        project_id: str = "",
        dry_run: bool = True,
        requested_by: str = "operator",
        max_followup_depth: int = 4,
    ) -> dict[str, Any]:
        candidate = self.next_followup_candidate(
            project_id=project_id, max_followup_depth=max_followup_depth
        )
        if not candidate:
            return {
                "ok": True,
                "action": "noop",
                "reason": "no follow-up candidate",
                "candidate": None,
                "followup": None,
            }
        title = (
            _text(candidate.get("followup_title"))
            or f"Follow-up: {_text(candidate.get('project_name')) or _text(candidate.get('project_id'))}"
        )
        seed = f"{_text(candidate.get('project_id'))}:{title}:{_text(candidate.get('followup_hypothesis'))}"
        followup_id = f"{_slug_id(title)[:58]}-{hashlib.sha256(seed.encode('utf-8')).hexdigest()[:10]}"[
            :80
        ]
        followup = {
            "idea_id": followup_id,
            "title": title,
            "parent_project_id": _text(candidate.get("project_id")),
            "parent_run_id": _text(candidate.get("current_run_id")),
            "followup_depth": _int(candidate.get("followup_depth"), 0) + 1,
            "followup_type": _normal(candidate.get("followup_type")),
            "followup_hypothesis": _text(candidate.get("followup_hypothesis")),
            "followup_required_evidence": _concrete_string_list(
                candidate.get("followup_required_evidence")
            ),
            "followup_success_threshold": _text(
                candidate.get("followup_success_threshold")
            ),
            "followup_stop_condition": _text(candidate.get("followup_stop_condition")),
        }
        if dry_run:
            return {
                "ok": True,
                "action": "dry_run_followup",
                "reason": "follow-up candidate selected; no row inserted",
                "candidate": candidate,
                "followup": followup,
            }
        now = utc_now()
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO projects(project_id,project_name,project_dir,notion_page_url,notion_page_id,origin_idea_status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)",
                (followup_id, title, followup_id, "", "", "testing", now, now),
            )
            conn.execute(
                "INSERT OR IGNORE INTO queue_items(project_id,status,selection_rank,dispatch_priority,auto_continue,continue_count,max_continues,retry_count,max_retries,current_run_id,current_session_id,last_run_state,last_event_type,next_action_hint,manual_review_required,blocked_reason,last_error,last_result_summary,machine_target,model,sandbox,last_dispatch_at,last_callback_at,stale_after,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    followup_id,
                    QueueStatus.QUEUED.value,
                    _int(candidate.get("selection_rank"), 50),
                    _int(candidate.get("dispatch_priority"), 50),
                    1,
                    0,
                    0,
                    0,
                    2,
                    "",
                    "",
                    "",
                    "",
                    "controller_review",
                    0,
                    "",
                    "",
                    "",
                    _text(candidate.get("machine_target")),
                    _text(candidate.get("model")),
                    _text(candidate.get("sandbox")),
                    None,
                    None,
                    None,
                    now,
                ),
            )
            event_id, _ = self._append_event_in_conn(
                conn,
                idempotency_key=f"followup.launch:{followup['parent_project_id']}:{followup_id}",
                event_type="followup.launch",
                entity_type="project",
                entity_id=followup["parent_project_id"],
                payload={"requested_by": requested_by, "followup": followup},
            )
        return {
            "ok": True,
            "action": "followup_queued",
            "reason": "bounded follow-up queued",
            "candidate": candidate,
            "followup": followup,
            "event_id": event_id,
        }

    def dispatch_next_dry_run(
        self, *, requested_by: str
    ) -> tuple[str, dict[str, Any] | None, int | None, str]:
        flags = self.flags()
        if flags.queue_paused:
            return "paused", None, None, flags.pause_reason or "queue paused"
        active = self.active_items()
        candidate = self.next_dispatch_candidate()
        if not candidate:
            return (
                "noop",
                None,
                None,
                "no queued candidate on an open worker lane"
                if active
                else "no queued candidate",
            )
        return (
            "dry_run_dispatch",
            candidate,
            None,
            "dry-run dispatch selected candidate",
        )

    def claim_dispatch_candidate(
        self,
        *,
        project_id: str,
        run_id: str,
        requested_by: str,
        conflicting_machine_targets: set[str] | None = None,
    ) -> dict[str, Any] | None:
        """Atomically reserve a queued project before worker-side dispatch."""
        payload = {"requested_by": requested_by, "run_id": run_id}
        if (
            self._replayed_event_id(
                f"dispatch-claim:{run_id}",
                payload,
                event_type="controller.dispatch_claimed",
                entity_type="project",
                entity_id=project_id,
            )
            is not None
        ):
            return None
        now = utc_now()
        active_placeholders = ",".join("?" for _ in ACTIVE_STATUSES)
        conflict_targets = sorted(
            {_normal(item) for item in conflicting_machine_targets or []}
        )
        conflict_clause = "" if conflicting_machine_targets is None else " AND 0"
        conflict_params: tuple[str, ...] = ()
        if conflict_targets:
            conflict_placeholders = ",".join("?" for _ in conflict_targets)
            conflict_clause = f" AND lower(replace(replace(trim(coalesce(active.machine_target, '')), '-', '_'), ' ', '_')) IN ({conflict_placeholders})"
            conflict_params = tuple(conflict_targets)
        with self._connect() as conn:
            cur = conn.execute(
                f"""UPDATE queue_items
                SET status=?, current_run_id=?, current_session_id=?, last_run_state=?,
                    last_event_type=?, next_action_hint=?, last_error=?, last_result_summary=?,
                    last_dispatch_at=?, updated_at=?
                WHERE project_id=?
                  AND status=?
                  AND manual_review_required=0
                  AND NOT EXISTS (
                    SELECT 1 FROM queue_items active
                    WHERE active.status IN ({active_placeholders})
                    {conflict_clause}
                  )""",
                (
                    QueueStatus.DISPATCHING.value,
                    run_id,
                    "",
                    QueueStatus.DISPATCHING.value,
                    "dispatch_claimed",
                    "prepare_worker_dispatch",
                    "",
                    "",
                    now,
                    now,
                    project_id,
                    QueueStatus.QUEUED.value,
                    *sorted(ACTIVE_STATUSES),
                    *conflict_params,
                ),
            )
            claimed = cur.rowcount == 1
            if claimed:
                self._append_event_in_conn(
                    conn,
                    idempotency_key=f"dispatch-claim:{run_id}",
                    event_type="controller.dispatch_claimed",
                    entity_type="project",
                    entity_id=project_id,
                    payload=payload,
                )
        if not claimed:
            return None
        return self.queue_row(project_id)

    def release_dispatch_claim(
        self, *, project_id: str, run_id: str, reason: str
    ) -> dict[str, Any]:
        now = utc_now()
        with self._connect() as conn:
            cur = conn.execute(
                """UPDATE queue_items
                SET status=?, current_run_id='', current_session_id='', last_run_state='',
                    last_event_type=?, next_action_hint=?, last_error=?, updated_at=?
                WHERE project_id=? AND current_run_id=? AND status=?""",
                (
                    QueueStatus.QUEUED.value,
                    "dispatch_claim_released",
                    "controller_review",
                    reason,
                    now,
                    project_id,
                    run_id,
                    QueueStatus.DISPATCHING.value,
                ),
            )
            if cur.rowcount == 1:
                self._append_event_in_conn(
                    conn,
                    idempotency_key=f"dispatch-claim-release:{run_id}",
                    event_type="controller.dispatch_claim_released",
                    entity_type="project",
                    entity_id=project_id,
                    payload={"run_id": run_id, "reason": reason},
                )
        return self.queue_row(project_id) or {}

    def _persist_notion_intake_candidate(
        self,
        conn: sqlite3.Connection,
        candidate: dict[str, Any],
        *,
        override_existing_dispatch_metadata: bool,
        now: str,
    ) -> str:
        existed = (
            conn.execute(
                "SELECT 1 FROM queue_items WHERE project_id=?",
                (candidate["project_id"],),
            ).fetchone()
            is not None
        )
        project = ProjectRecord(
            project_id=candidate["project_id"],
            project_name=candidate["project_name"],
            project_dir=candidate["project_dir"],
            notion_page_url=candidate["notion_page_url"],
            notion_page_id=candidate["notion_page_id"],
            origin_idea_status=candidate["origin_idea_status"],
            created_at=now,
            updated_at=now,
        )
        qi = QueueItemRecord(
            project_id=project.project_id,
            status=QueueStatus.QUEUED,
            selection_rank=int(candidate["selection_rank"]),
            dispatch_priority=int(candidate["dispatch_priority"]),
            next_action_hint=candidate["next_action_hint"],
            machine_target=candidate["machine_target"],
            model=candidate["model"],
            sandbox=candidate["sandbox"],
            updated_at=now,
        )
        conn.execute(
            """INSERT INTO projects(project_id,project_name,project_dir,notion_page_url,notion_page_id,origin_idea_status,created_at,updated_at)
            VALUES (?,?,?,?,?,?,?,?)
            ON CONFLICT(project_id) DO UPDATE SET
                project_name=excluded.project_name,
                project_dir=projects.project_dir,
                notion_page_url=COALESCE(NULLIF(excluded.notion_page_url,''), projects.notion_page_url),
                notion_page_id=COALESCE(NULLIF(excluded.notion_page_id,''), projects.notion_page_id),
                origin_idea_status=COALESCE(NULLIF(excluded.origin_idea_status,''), projects.origin_idea_status),
                updated_at=excluded.updated_at""",
            (
                project.project_id,
                project.project_name,
                project.project_dir,
                project.notion_page_url,
                project.notion_page_id,
                project.origin_idea_status,
                project.created_at,
                project.updated_at,
            ),
        )
        if existed:
            if override_existing_dispatch_metadata:
                conn.execute(
                    """UPDATE queue_items SET selection_rank=?, dispatch_priority=?, machine_target=?, model=?, sandbox=?, updated_at=?
                    WHERE project_id=? AND status NOT IN ('dispatching','running','awaiting_wake','wake_received','reconciling')""",
                    (
                        qi.selection_rank,
                        qi.dispatch_priority,
                        qi.machine_target,
                        qi.model,
                        qi.sandbox,
                        qi.updated_at,
                        qi.project_id,
                    ),
                )
            else:
                conn.execute(
                    """UPDATE queue_items SET selection_rank=?, dispatch_priority=?, updated_at=?
                    WHERE project_id=? AND status NOT IN ('dispatching','running','awaiting_wake','wake_received','reconciling')""",
                    (
                        qi.selection_rank,
                        qi.dispatch_priority,
                        qi.updated_at,
                        qi.project_id,
                    ),
                )
            return "updated"
        conn.execute(
            """INSERT INTO queue_items(project_id,status,selection_rank,dispatch_priority,auto_continue,continue_count,max_continues,retry_count,max_retries,current_run_id,current_session_id,last_run_state,last_event_type,next_action_hint,manual_review_required,blocked_reason,last_error,last_result_summary,machine_target,model,sandbox,last_dispatch_at,last_callback_at,stale_after,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                qi.project_id,
                qi.status.value,
                qi.selection_rank,
                qi.dispatch_priority,
                int(qi.auto_continue),
                qi.continue_count,
                qi.max_continues,
                qi.retry_count,
                qi.max_retries,
                qi.current_run_id,
                qi.current_session_id,
                qi.last_run_state,
                qi.last_event_type,
                qi.next_action_hint,
                int(qi.manual_review_required),
                qi.blocked_reason,
                qi.last_error,
                qi.last_result_summary,
                qi.machine_target,
                qi.model,
                qi.sandbox,
                qi.last_dispatch_at,
                qi.last_callback_at,
                qi.stale_after,
                qi.updated_at,
            ),
        )
        return "created"

    def ingest_notion_ideas(
        self, request: NotionIntakeRequest
    ) -> tuple[bool, int, int, int, list[dict[str, Any]], list[dict[str, Any]]]:
        include_statuses = {
            item.strip().lower() for item in request.include_statuses if item.strip()
        }
        candidates: list[dict[str, Any]] = []
        skipped_rows: list[dict[str, Any]] = []
        for raw in request.notion_rows:
            title = _notion_title(raw)
            status = _notion_status(raw).lower()
            page_id = _notion_page_id(raw)
            page_url = _notion_url(raw)
            skip = _notion_intake_skip_row(
                raw,
                title=title,
                status=status,
                page_id=page_id,
                include_statuses=include_statuses,
            )
            if skip is not None:
                skipped_rows.append(skip)
                continue
            candidate, skip = _notion_intake_candidate(
                raw,
                request,
                title=title,
                status=status,
                page_id=page_id,
                page_url=page_url,
            )
            if skip is not None:
                skipped_rows.append(skip)
                continue
            candidates.append(candidate)
        if request.dry_run:
            return False, 0, 0, len(skipped_rows), candidates, skipped_rows
        event_payload = request.model_dump(mode="json")
        event_payload["candidate_count"] = len(candidates)
        event_payload["skipped_count"] = len(skipped_rows)
        created = updated = 0
        now = utc_now()
        with self._connect() as conn:
            _event_id, inserted = self._append_event_in_conn(
                conn,
                idempotency_key=request.idempotency_key,
                event_type="notion.intake",
                entity_type="snapshot",
                entity_id=request.source,
                payload=event_payload,
            )
            if not inserted:
                return (
                    inserted,
                    created,
                    updated,
                    len(skipped_rows),
                    candidates,
                    skipped_rows,
                )
            for candidate in candidates:
                outcome = self._persist_notion_intake_candidate(
                    conn,
                    candidate,
                    override_existing_dispatch_metadata=request.override_existing_dispatch_metadata,
                    now=now,
                )
                if outcome == "created":
                    created += 1
                else:
                    updated += 1
        return inserted, created, updated, len(skipped_rows), candidates, skipped_rows

    def _apply_idea_intake_candidate(
        self,
        conn: sqlite3.Connection,
        candidate: dict[str, Any],
        *,
        override_existing_dispatch_metadata: bool,
        now: str,
    ) -> bool:
        """Persist one idea intake candidate. Returns True if queue row was updated."""
        existed = (
            conn.execute(
                "SELECT 1 FROM queue_items WHERE project_id=?",
                (candidate["project_id"],),
            ).fetchone()
            is not None
        )
        project = ProjectRecord(
            project_id=candidate["project_id"],
            project_name=candidate["project_name"],
            project_dir=candidate["project_dir"],
            origin_idea_status=candidate["origin_idea_status"],
            created_at=now,
            updated_at=now,
        )
        qi = QueueItemRecord(
            project_id=project.project_id,
            status=QueueStatus.QUEUED,
            selection_rank=int(candidate["selection_rank"]),
            dispatch_priority=int(candidate["dispatch_priority"]),
            next_action_hint=candidate["next_action_hint"],
            machine_target=candidate["machine_target"],
            model=candidate["model"],
            sandbox=candidate["sandbox"],
            updated_at=now,
        )
        conn.execute(
            """INSERT INTO projects(project_id,project_name,project_dir,notion_page_url,notion_page_id,origin_idea_status,created_at,updated_at)
            VALUES (?,?,?,?,?,?,?,?)
            ON CONFLICT(project_id) DO UPDATE SET
                project_name=excluded.project_name,
                project_dir=excluded.project_dir,
                origin_idea_status=COALESCE(NULLIF(excluded.origin_idea_status,''), projects.origin_idea_status),
                updated_at=excluded.updated_at""",
            (
                project.project_id,
                project.project_name,
                project.project_dir,
                "",
                "",
                project.origin_idea_status,
                project.created_at,
                project.updated_at,
            ),
        )
        if existed:
            if override_existing_dispatch_metadata:
                conn.execute(
                    """UPDATE queue_items SET selection_rank=?, dispatch_priority=?, machine_target=?, model=?, sandbox=?, updated_at=?
                    WHERE project_id=? AND status NOT IN ('dispatching','running','awaiting_wake','wake_received','reconciling')""",
                    (
                        qi.selection_rank,
                        qi.dispatch_priority,
                        qi.machine_target,
                        qi.model,
                        qi.sandbox,
                        qi.updated_at,
                        qi.project_id,
                    ),
                )
            else:
                conn.execute(
                    """UPDATE queue_items SET selection_rank=?, dispatch_priority=?, updated_at=?
                    WHERE project_id=? AND status NOT IN ('dispatching','running','awaiting_wake','wake_received','reconciling')""",
                    (
                        qi.selection_rank,
                        qi.dispatch_priority,
                        qi.updated_at,
                        qi.project_id,
                    ),
                )
            return True
        conn.execute(
            """INSERT INTO queue_items(project_id,status,selection_rank,dispatch_priority,auto_continue,continue_count,max_continues,retry_count,max_retries,current_run_id,current_session_id,last_run_state,last_event_type,next_action_hint,manual_review_required,blocked_reason,last_error,last_result_summary,machine_target,model,sandbox,last_dispatch_at,last_callback_at,stale_after,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                qi.project_id,
                qi.status.value,
                qi.selection_rank,
                qi.dispatch_priority,
                int(qi.auto_continue),
                qi.continue_count,
                qi.max_continues,
                qi.retry_count,
                qi.max_retries,
                qi.current_run_id,
                qi.current_session_id,
                qi.last_run_state,
                qi.last_event_type,
                qi.next_action_hint,
                int(qi.manual_review_required),
                qi.blocked_reason,
                qi.last_error,
                qi.last_result_summary,
                qi.machine_target,
                qi.model,
                qi.sandbox,
                qi.last_dispatch_at,
                qi.last_callback_at,
                qi.stale_after,
                qi.updated_at,
            ),
        )
        return False

    def ingest_ideas(
        self, request: IdeaIntakeRequest
    ) -> tuple[bool, int, int, int, list[dict[str, Any]], list[dict[str, Any]]]:
        include_statuses = {
            item.strip().lower() for item in request.include_statuses if item.strip()
        }
        candidates, skipped_rows = _collect_idea_intake_candidates(
            request, include_statuses
        )
        if request.dry_run:
            return False, 0, 0, len(skipped_rows), candidates, skipped_rows
        event_payload = request.model_dump(mode="json")
        event_payload["candidate_count"] = len(candidates)
        event_payload["skipped_count"] = len(skipped_rows)
        created = updated = 0
        now = utc_now()
        with self._connect() as conn:
            _event_id, inserted = self._append_event_in_conn(
                conn,
                idempotency_key=request.idempotency_key,
                event_type="ideas.intake",
                entity_type="snapshot",
                entity_id=request.source,
                payload=event_payload,
            )
            if not inserted:
                return (
                    inserted,
                    created,
                    updated,
                    len(skipped_rows),
                    candidates,
                    skipped_rows,
                )
            for candidate in candidates:
                if self._apply_idea_intake_candidate(
                    conn,
                    candidate,
                    override_existing_dispatch_metadata=request.override_existing_dispatch_metadata,
                    now=now,
                ):
                    updated += 1
                else:
                    created += 1
        return inserted, created, updated, len(skipped_rows), candidates, skipped_rows

    def idea_workbench_projection(self) -> list[dict[str, Any]]:
        return [
            {
                **row,
                "idea_id": row.get("project_id") or "",
                "title": row.get("project_name") or "",
                "idea_status": row.get("origin_idea_status")
                or row.get("queue_status")
                or "",
                "source_kind": "sqlite_project_snapshot",
            }
            for row in self.queue_notion_projection()
        ]

    def research_facility_workbench_projection(
        self, *, limit: int = 200
    ) -> list[dict[str, Any]]:
        # The SQLite compatibility store predates the Research Facility ledgers.
        # Returning an empty projection keeps legacy/local smokes working while
        # the Supabase/Postgres store owns the real source/candidate/admission
        # workbench.
        return []

    def research_facility_workbench_counts(self) -> dict[str, int]:
        return {}

    def notion_execution_update_projection(self) -> list[dict[str, Any]]:
        paper_by_project = {
            paper.get("project_id"): paper for paper in self.paper_rows()
        }
        rows: list[dict[str, Any]] = []
        for row in self.queue_rows():
            merged = _queue_row_merged_with_paper(row, paper_by_project)
            update = _notion_execution_update_row(merged, _NOTION_EXECUTION_STATE_MAP)
            if update is not None:
                rows.append(update)
        return rows

    def export_snapshot(self, *, event_limit: int = 50) -> dict[str, Any]:
        return {
            "source": "langgraph_control_plane",
            "generated_at": utc_now(),
            "flags": self.flags().model_dump(mode="json"),
            "queue_rows": self.queue_rows(),
            "paper_rows": self.paper_rows(),
            "events": self.recent_events(event_limit),
        }

    def queue_notion_projection(self) -> list[dict[str, Any]]:
        rows = []
        for row in self.queue_rows():
            rows.append(
                {
                    "project_id": row.get("project_id") or "",
                    "project_name": row.get("project_name") or "",
                    "origin_idea_status": row.get("origin_idea_status") or "",
                    "queue_status": row.get("status") or "",
                    "next_action_hint": row.get("next_action_hint") or "",
                    "last_run_state": row.get("last_run_state") or "",
                    "last_event_type": row.get("last_event_type") or "",
                    "current_run_id": row.get("current_run_id") or "",
                    "current_session_id": row.get("current_session_id") or "",
                    "machine_target": row.get("machine_target") or "",
                    "manual_review_required": _bool(row.get("manual_review_required")),
                    "blocked_reason": row.get("blocked_reason") or "",
                    "last_result_summary": row.get("last_result_summary") or "",
                    "notion_page_url": row.get("notion_page_url") or "",
                    "updated_at": row.get("updated_at") or "",
                }
            )
        return rows

    def paper_notion_projection(self) -> list[dict[str, Any]]:
        rows = []
        for paper in self.paper_rows():
            rows.append(
                {
                    "paper_id": paper.get("paper_id") or "",
                    "project_id": paper.get("project_id") or "",
                    "project_name": paper.get("project_name")
                    or paper.get("project_id")
                    or "",
                    "paper_status": paper.get("paper_status") or "",
                    "paper_type": paper.get("paper_type") or "",
                    "run_id": paper.get("run_id") or "",
                    "draft_markdown_path": paper.get("draft_markdown_path") or "",
                    "draft_latex_path": paper.get("draft_latex_path") or "",
                    "evidence_bundle_path": paper.get("evidence_bundle_path") or "",
                    "claim_ledger_path": paper.get("claim_ledger_path") or "",
                    "manifest_path": paper.get("manifest_path") or "",
                    "notion_page_url": paper.get("notion_page_url") or "",
                    "updated_at": paper.get("updated_at") or "",
                }
            )
        return rows

    def mark_dispatch_started(
        self,
        *,
        project_id: str,
        run_id: str,
        session_id: str,
        dispatch_payload: dict[str, Any],
        requested_by: str,
    ) -> tuple[int, dict[str, Any]]:
        now = utc_now()
        event_payload = {
            "requested_by": requested_by,
            "run_id": run_id,
            "session_id": session_id,
            "dispatch": dispatch_payload,
        }
        with self._connect() as conn:
            event_id, inserted = self._append_event_in_conn(
                conn,
                idempotency_key=f"live-dispatch:{run_id}",
                event_type="controller.live_dispatch",
                entity_type="project",
                entity_id=project_id,
                payload=event_payload,
            )
            if not inserted:
                row = next(
                    (
                        item
                        for item in self.queue_rows()
                        if item.get("project_id") == project_id
                    ),
                    {},
                )
                return event_id, row
            conn.execute(
                """UPDATE queue_items
                SET status=?, current_run_id=?, current_session_id=?, last_run_state=?, last_event_type=?, next_action_hint=?, last_error=?, last_result_summary=?, last_dispatch_at=?, updated_at=?
                WHERE project_id=?""",
                (
                    QueueStatus.AWAITING_WAKE.value,
                    run_id,
                    session_id,
                    QueueStatus.AWAITING_WAKE.value,
                    "live_dispatch",
                    "await_callback",
                    "",
                    "",
                    now,
                    now,
                    project_id,
                ),
            )
            conn.execute(
                """INSERT OR REPLACE INTO runs(run_id,project_id,session_id,state,dispatch_mode,started_at,ended_at,last_callback_at,gate_state,current_activity,idempotency_key,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    run_id,
                    project_id,
                    session_id,
                    "running",
                    "exec",
                    now,
                    None,
                    None,
                    "running",
                    "dispatched",
                    f"live-dispatch:{run_id}",
                    now,
                ),
            )
        row = next(
            (
                item
                for item in self.queue_rows()
                if item.get("project_id") == project_id
            ),
            {},
        )
        return event_id, row

    def record_worker_callback(
        self, callback: Any, *, received_by: str = "worker-callback"
    ) -> tuple[int, bool, dict[str, Any]]:
        now = utc_now()
        payload = _worker_callback_payload(callback)
        run_id = _text(payload.get("run_id"))
        project_id = _text(payload.get("project_id"))
        event_type = _normal(payload.get("event_type"))
        idempotency_key = _derived_worker_callback_idempotency_key(
            payload,
            run_id=run_id,
            event_type=event_type,
            idempotency_key=_text(payload.get("idempotency_key")),
        )
        project_id = self._resolve_worker_callback_project_id(project_id, run_id)
        replayed_callback_event_id = self._replayed_worker_callback_event_id(
            idempotency_key, payload
        )
        if replayed_callback_event_id is not None:
            return (
                replayed_callback_event_id,
                False,
                self._worker_callback_result_row(project_id),
            )
        current_queue_row, stale_callback, current_status = (
            self._worker_callback_queue_snapshot(project_id, run_id)
        )
        late_result = self._try_record_late_terminal_success_worker_callback(
            payload=payload,
            current_queue_row=current_queue_row,
            run_id=run_id,
            project_id=project_id,
            event_type=event_type,
            idempotency_key=idempotency_key,
            received_by=received_by,
        )
        if late_result is not None:
            return late_result
        status, next_action_hint, manual_review_required, last_error = (
            _worker_callback_transition(event_type, payload)
        )
        stale_result = self._try_record_stale_worker_callback(
            payload=payload,
            current_queue_row=current_queue_row,
            stale_callback=stale_callback,
            run_id=run_id,
            project_id=project_id,
            event_type=event_type,
            idempotency_key=idempotency_key,
            received_by=received_by,
            current_status=current_status,
        )
        if stale_result is not None:
            return stale_result
        event_payload = {
            **payload,
            "received_by": received_by,
            "applied_status": status,
            "applied_next_action_hint": next_action_hint,
        }
        replayed_event_id = self._replayed_event_id(
            idempotency_key,
            event_payload,
            event_type=_worker_callback_event_type_name(event_type),
            entity_type="run",
            entity_id=_worker_callback_entity_id(run_id, project_id),
        )
        if replayed_event_id is not None:
            return (
                replayed_event_id,
                False,
                self._worker_callback_result_row(project_id),
            )
        with self._connect() as conn:
            event_id, inserted = self._persist_applied_worker_callback(
                conn,
                now=now,
                payload=payload,
                project_id=project_id,
                run_id=run_id,
                event_type=event_type,
                idempotency_key=idempotency_key,
                event_payload=event_payload,
                status=status,
                next_action_hint=next_action_hint,
                manual_review_required=manual_review_required,
                last_error=last_error,
            )
        return (
            event_id,
            inserted,
            self._worker_callback_result_row(project_id, scan_all_queue_rows=True),
        )

    def mark_queue_item_paused(
        self, *, project_id: str, reason: str, updated_by: str = "operator"
    ) -> bool:
        now = utc_now()
        with self._connect() as conn:
            cur = conn.execute(
                """UPDATE queue_items
                SET status=?, next_action_hint=?, last_result_summary=?, updated_at=?
                WHERE project_id=?""",
                (
                    QueueStatus.PAUSED.value,
                    "maintenance_cutover_reconcile",
                    reason,
                    now,
                    project_id,
                ),
            )
            if cur.rowcount < 1:
                return False
            self._append_event_in_conn(
                conn,
                idempotency_key=f"queue-item-paused:{project_id}:{now}",
                event_type="queue.item_paused",
                entity_type="project",
                entity_id=project_id,
                payload={"reason": reason, "updated_by": updated_by},
            )
        return True

    def update_project_dir(self, project_id: str, project_dir: str) -> None:
        now = utc_now()
        with self._connect() as conn:
            conn.execute(
                "UPDATE projects SET project_dir=?, updated_at=? WHERE project_id=?",
                (_text(project_dir), now, project_id),
            )

    def _upsert_paper_in_conn(
        self, conn: sqlite3.Connection, paper: PaperRecord
    ) -> None:
        existing = conn.execute(
            "SELECT project_id, run_id, paper_type, updated_at FROM papers WHERE paper_id=?",
            (paper.paper_id,),
        ).fetchone()
        if _paper_identity_conflicts(existing, paper):
            raise IdempotencyConflict(
                f"paper id {paper.paper_id!r} was reused with different paper identity"
            )
        if existing and _is_older_timestamp(paper.updated_at, existing["updated_at"]):
            return
        conn.execute(
            """INSERT OR REPLACE INTO papers(paper_id,project_id,run_id,paper_type,paper_status,draft_markdown_path,draft_latex_path,evidence_bundle_path,claim_ledger_path,manifest_path,generated_at,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                paper.paper_id,
                paper.project_id,
                paper.run_id,
                paper.paper_type,
                paper.paper_status.value,
                paper.draft_markdown_path,
                paper.draft_latex_path,
                paper.evidence_bundle_path,
                paper.claim_ledger_path,
                paper.manifest_path,
                paper.generated_at,
                paper.updated_at,
            ),
        )

    def upsert_paper(self, paper: PaperRecord) -> None:
        with self._connect() as conn:
            self._upsert_paper_in_conn(conn, paper)

    def record_paper_draft(
        self,
        *,
        paper: PaperRecord,
        project_dir: str,
        idempotency_key: str,
        event_payload: dict[str, Any],
    ) -> tuple[int, bool]:
        now = utc_now()
        with self._connect() as conn:
            conn.execute(
                "UPDATE projects SET project_dir=?, updated_at=? WHERE project_id=?",
                (_text(project_dir), now, paper.project_id),
            )
            self._upsert_paper_in_conn(conn, paper)
            return self._append_event_in_conn(
                conn,
                idempotency_key=idempotency_key,
                event_type="paper.drafted",
                entity_type="paper",
                entity_id=paper.paper_id,
                payload=event_payload,
            )
