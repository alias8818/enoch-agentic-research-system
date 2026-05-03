from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from ..enoch_core.store import IdempotencyConflict
from ..models import utc_now
from .models import (
    ControlFlags,
    DashboardObservationRecord,
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
    RunRecord,
)

SCHEMA_VERSION = 1
ACTIVE_STATUSES = {"dispatching", "running", "awaiting_wake", "wake_received", "reconciling"}


def _json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _hash(payload: Any) -> str:
    return hashlib.sha256(_json(payload).encode("utf-8")).hexdigest()


def _text(value: Any) -> str:
    return str(value or "").strip()



def _first_present(raw: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in raw and raw.get(name) not in (None, ""):
            return raw.get(name)
    return None


def _snapshot_rows(snapshot: dict[str, Any] | list[dict[str, Any]] | None, *, paper: bool = False) -> list[dict[str, Any]]:
    if snapshot is None:
        return []
    if isinstance(snapshot, list):
        return [row for row in snapshot if isinstance(row, dict)]
    if not isinstance(snapshot, dict):
        return []
    keys = ("latest_rows", "rows", "active_rows", "blocked_rows") if paper else ("rows", "active_rows", "blocked_rows")
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for key in keys:
        value = snapshot.get(key)
        if not isinstance(value, list):
            continue
        for row in value:
            if not isinstance(row, dict):
                continue
            row_key = _text(row.get("paper_id") if paper else row.get("project_id")) or _hash(row)
            if row_key in seen:
                continue
            seen.add(row_key)
            rows.append(row)
    return rows


def _slug_id(value: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "-" for ch in value).strip("-")[:80]


def _notion_prop(raw: dict[str, Any], *names: str) -> Any:
    candidates = []
    for name in names:
        candidates.extend([name, f"property_{name.lower().replace(' ', '_')}", name.lower().replace(" ", "_")])
    return _first_present(raw, *candidates)


def _notion_title(raw: dict[str, Any]) -> str:
    return _text(_notion_prop(raw, "Idea", "name", "title")) or _text(raw.get("name")) or _text(raw.get("title"))


def _notion_status(raw: dict[str, Any]) -> str:
    return _text(_notion_prop(raw, "Status"))


def _notion_url(raw: dict[str, Any]) -> str:
    return _text(_first_present(raw, "url", "notion_page_url", "public_url"))


def _notion_page_id_from_url(url: str) -> str:
    compact = _text(url).replace("-", "")
    matches = re.findall(r"[0-9a-fA-F]{32}", compact)
    return matches[-1].lower() if matches else ""


def _notion_page_id(raw: dict[str, Any]) -> str:
    return _text(_first_present(raw, "id", "page_id", "notion_page_id")) or _notion_page_id_from_url(_notion_url(raw))


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


REVIEW_CHECKLIST_DEFINITION = (
    ("artifact_readability", "Artifact readability", True),
    ("title_abstract_quality", "Title/abstract quality", True),
    ("claim_evidence_alignment", "Claim/evidence alignment", True),
    ("novelty_significance", "Novelty/significance", True),
    ("reproducibility", "Reproducibility", True),
    ("limitations_ethics", "Limitations/ethics", True),
    ("formatting_quality", "Formatting quality", True),
    ("target_venue_fit", "Target venue/application fit", False),
    ("final_human_approval", "Final human approval", True),
)
REVIEW_CHECKLIST_ITEMS = tuple(item_id for item_id, _label, _required in REVIEW_CHECKLIST_DEFINITION)
CHECKLIST_ITEM_STATUSES = {"pending", "pass", "fail", "accepted_risk", "not_applicable"}
SYSTEM_REVIEW_STATUSES = {ReviewStatus.UNREVIEWED.value, ReviewStatus.TRIAGE_READY.value}
ALLOWED_STATUS_TRANSITIONS = {
    ReviewStatus.UNREVIEWED.value: {ReviewStatus.TRIAGE_READY.value, ReviewStatus.BLOCKED.value, ReviewStatus.REJECTED.value},
    ReviewStatus.TRIAGE_READY.value: {ReviewStatus.IN_REVIEW.value, ReviewStatus.BLOCKED.value, ReviewStatus.REJECTED.value},
    ReviewStatus.IN_REVIEW.value: {ReviewStatus.CHANGES_REQUESTED.value, ReviewStatus.BLOCKED.value, ReviewStatus.APPROVED_FOR_FINALIZATION.value, ReviewStatus.REJECTED.value},
    ReviewStatus.CHANGES_REQUESTED.value: {ReviewStatus.IN_REVIEW.value, ReviewStatus.BLOCKED.value, ReviewStatus.REJECTED.value},
    ReviewStatus.BLOCKED.value: {ReviewStatus.TRIAGE_READY.value, ReviewStatus.IN_REVIEW.value, ReviewStatus.REJECTED.value},
    ReviewStatus.APPROVED_FOR_FINALIZATION.value: {ReviewStatus.FINALIZED.value, ReviewStatus.IN_REVIEW.value},
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
    counts = {"passed": 0, "accepted_risk": 0, "failed": 0, "pending": 0, "not_applicable": 0, "total": len(items)}
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
        {"id": item_id, "label": label, "required": required, "status": "pending", "note": "", "updated_at": "", "updated_by": ""}
        for item_id, label, required in REVIEW_CHECKLIST_DEFINITION
    ]
    return {"version": "publication_review_v1", "items": items, "accepted_risks": [], "progress": _progress_for_items(items)}


def _normalize_review_checklist(checklist: dict[str, Any] | None) -> dict[str, Any]:
    raw = checklist or {}
    by_id: dict[str, dict[str, Any]] = {}
    if isinstance(raw.get("items"), list):
        for item in raw.get("items") or []:
            if isinstance(item, dict) and _text(item.get("id")):
                by_id[_text(item.get("id"))] = item
    else:
        for item_id, value in raw.items():
            by_id[_text(item_id)] = {"id": _text(item_id), "status": _text(value) or "pending"}
    items: list[dict[str, Any]] = []
    for item_id, label, required in REVIEW_CHECKLIST_DEFINITION:
        existing = by_id.get(item_id, {})
        status = _text(existing.get("status")) or "pending"
        if status not in CHECKLIST_ITEM_STATUSES:
            status = "pending"
        items.append({
            "id": item_id,
            "label": label,
            "required": required,
            "status": status,
            "note": _text(existing.get("note")),
            "updated_at": _text(existing.get("updated_at")),
            "updated_by": _text(existing.get("updated_by")),
        })
    accepted_risks = raw.get("accepted_risks") if isinstance(raw.get("accepted_risks"), list) else []
    normalized = {"version": "publication_review_v1", "items": items, "accepted_risks": accepted_risks, "progress": _progress_for_items(items)}
    return normalized


def _checklist_progress(checklist: dict[str, Any]) -> dict[str, int]:
    return _normalize_review_checklist(checklist).get("progress", _progress_for_items([]))


def _audit_rows(source_audit_path: str) -> dict[str, dict[str, Any]]:
    if not source_audit_path:
        return {}
    path = Path(source_audit_path).expanduser()
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
    return bool(audit.get("ready") is True or audit.get("ok") is True or audit.get("semantic_ok") is True or audit.get("readiness_passed") is True)


def _review_rank(paper: dict[str, Any], queue_item: dict[str, Any] | None, audit: dict[str, Any], initial_missing: list[str]) -> tuple[int, list[str], list[str], str, str]:
    reasons: list[str] = []
    missing = list(dict.fromkeys(initial_missing))
    score = 0
    paper_status = _text(paper.get("paper_status"))
    if paper_status == PaperStatus.PUBLICATION_DRAFT.value:
        score += 100
        reasons.append("publication_draft +100")
    elif paper_status == PaperStatus.DRAFT_REVIEW.value:
        score += 40
        reasons.append("draft_review +40")

    audit_ready = _readiness_passed(audit)
    if audit_ready:
        score += 20
        reasons.append("readiness audit passed +20")
    elif not audit:
        missing.append("readiness_audit")

    required_json = ["evidence_bundle_path", "claim_ledger_path", "manifest_path"]
    if all(_text(paper.get(name)) for name in required_json):
        score += 10
        reasons.append("evidence/claim/manifest paths present +10")
    else:
        for name in required_json:
            if not _text(paper.get(name)):
                missing.append(name)

    if _text(paper.get("draft_markdown_path")) and _text(paper.get("draft_latex_path")):
        score += 5
        reasons.append("draft markdown/latex paths present +5")

    queue_item = queue_item or {}
    if _text(queue_item.get("blocked_reason")) or _text(queue_item.get("status")) in {QueueStatus.BLOCKED.value, QueueStatus.NEEDS_REVIEW.value, QueueStatus.DISPATCH_ERROR.value} or bool(queue_item.get("manual_review_required")):
        score -= 100
        reasons.append("blocked/manual-review queue signal -100")

    material_missing = sorted(set(missing))
    if material_missing:
        score -= 25
        reasons.append("material ranking inputs missing -25")

    status_priority = {PaperStatus.PUBLICATION_DRAFT.value: 0, PaperStatus.DRAFT_REVIEW.value: 1}.get(paper_status, 9)
    tiebreaker = f"{status_priority}:{_text(paper.get('updated_at'))}:{_text(paper.get('paper_id'))}"
    bucket = "blocked" if score < 0 else "ready" if score >= 100 else "review"
    return score, reasons, material_missing, tiebreaker, bucket


def _bool(value: Any) -> bool:
    return value is True or value in {1, "1", "true", "True", "TRUE", "yes", "YES"}


def _int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class ControlPlaneStore:
    def __init__(self, path: Path) -> None:
        self.path = path.expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

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
            conn.execute("INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)", (SCHEMA_VERSION, utc_now()))
            flags = ControlFlags()
            conn.execute(
                """
                INSERT OR IGNORE INTO control_flags(singleton, queue_paused, maintenance_mode, pause_reason, paused_at, paused_by, updated_at)
                VALUES (1, ?, ?, ?, ?, ?, ?)
                """,
                (int(flags.queue_paused), int(flags.maintenance_mode), flags.pause_reason, flags.paused_at, flags.paused_by, flags.updated_at),
            )
            project_columns = {row[1] for row in conn.execute("PRAGMA table_info(projects)").fetchall()}
            if "notion_page_id" not in project_columns:
                conn.execute("ALTER TABLE projects ADD COLUMN notion_page_id TEXT NOT NULL DEFAULT ''")
            conn.execute("""UPDATE projects
                SET notion_page_id = lower(replace(substr(notion_page_url, length(notion_page_url) - 31, 32), '-', ''))
                WHERE notion_page_id = ''
                  AND length(replace(substr(notion_page_url, length(notion_page_url) - 31, 32), '-', '')) = 32""")
            review_columns = {row[1] for row in conn.execute("PRAGMA table_info(paper_review_items)").fetchall()}
            if "claimed_at" not in review_columns:
                conn.execute("ALTER TABLE paper_review_items ADD COLUMN claimed_at TEXT NOT NULL DEFAULT ''")

    def append_event(self, *, idempotency_key: str, event_type: str, entity_type: str, entity_id: str, payload: dict[str, Any]) -> tuple[int, bool]:
        payload_json = _json(payload)
        payload_hash = _hash(payload)
        with self._connect() as conn:
            row = conn.execute("SELECT event_id, payload_hash FROM events WHERE idempotency_key = ?", (idempotency_key,)).fetchone()
            if row:
                if row["payload_hash"] != payload_hash:
                    raise IdempotencyConflict(f"idempotency key {idempotency_key!r} was reused with different payload")
                return int(row["event_id"]), False
            cur = conn.execute(
                "INSERT INTO events(idempotency_key,event_type,entity_type,entity_id,payload_json,payload_hash,created_at) VALUES (?,?,?,?,?,?,?)",
                (idempotency_key, event_type, entity_type, entity_id, payload_json, payload_hash, utc_now()),
            )
            return int(cur.lastrowid), True

    def flags(self) -> ControlFlags:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM control_flags WHERE singleton = 1").fetchone()
        return ControlFlags(
            queue_paused=bool(row["queue_paused"]), maintenance_mode=bool(row["maintenance_mode"]), pause_reason=row["pause_reason"],
            paused_at=row["paused_at"], paused_by=row["paused_by"], updated_at=row["updated_at"]
        )

    def pause(self, *, reason: str, paused_by: str, maintenance_mode: bool) -> tuple[ControlFlags, int]:
        now = utc_now()
        with self._connect() as conn:
            conn.execute(
                "UPDATE control_flags SET queue_paused=1, maintenance_mode=?, pause_reason=?, paused_at=?, paused_by=?, updated_at=? WHERE singleton=1",
                (int(maintenance_mode), reason, now, paused_by, now),
            )
        flags = self.flags()
        event_id, _ = self.append_event(idempotency_key=f"pause:{now}", event_type="control.pause", entity_type="control", entity_id="queue", payload=flags.model_dump(mode="json"))
        return flags, event_id

    def resume(self, *, resumed_by: str, maintenance_mode: bool) -> tuple[ControlFlags, int]:
        now = utc_now()
        with self._connect() as conn:
            conn.execute(
                "UPDATE control_flags SET queue_paused=0, maintenance_mode=?, pause_reason='', paused_at=NULL, paused_by=?, updated_at=? WHERE singleton=1",
                (int(maintenance_mode), resumed_by, now),
            )
        flags = self.flags()
        event_id, _ = self.append_event(idempotency_key=f"resume:{now}", event_type="control.resume", entity_type="control", entity_id="queue", payload=flags.model_dump(mode="json"))
        return flags, event_id

    def import_snapshot(self, request: ImportSnapshotRequest) -> tuple[bool, int, int, int]:
        queue_rows = [*request.queue_rows, *_snapshot_rows(request.queue_snapshot)]
        paper_rows = [*request.paper_rows, *_snapshot_rows(request.paper_snapshot, paper=True)]
        event_payload = request.model_dump(mode="json")
        event_payload["normalized_queue_row_count"] = len(queue_rows)
        event_payload["normalized_paper_row_count"] = len(paper_rows)
        _, inserted = self.append_event(
            idempotency_key=request.idempotency_key,
            event_type="legacy.import_snapshot",
            entity_type="snapshot",
            entity_id=request.source,
            payload=event_payload,
        )
        projects = queue_items = papers = 0
        with self._connect() as conn:
            for raw in queue_rows:
                project_id = _text(raw.get("project_id"))
                if not project_id:
                    continue
                project = ProjectRecord(
                    project_id=project_id,
                    project_name=_text(_first_present(raw, "project_name", "name", "title")) or project_id,
                    project_dir=_text(_first_present(raw, "project_dir", "project_path")),
                    notion_page_url=_text(_first_present(raw, "notion_page_url", "url")),
                    notion_page_id=_text(_first_present(raw, "notion_page_id", "page_id", "id")) or _notion_page_id_from_url(_text(_first_present(raw, "notion_page_url", "url"))),
                    origin_idea_status=_text(_first_present(raw, "origin_idea_status", "idea_status")),
                    created_at=_text(_first_present(raw, "createdAt", "created_at")) or utc_now(),
                    updated_at=_text(_first_present(raw, "updatedAt", "updated_at", "last_execution_update")) or utc_now(),
                )
                qi = QueueItemRecord(
                    project_id=project_id,
                    status=QueueStatus(_text(_first_present(raw, "status", "queue_status")) or "queued") if (_text(_first_present(raw, "status", "queue_status")) or "queued") in QueueStatus._value2member_map_ else QueueStatus.QUEUED,
                    selection_rank=_int(_first_present(raw, "selection_rank", "rank"), 50), dispatch_priority=_int(_first_present(raw, "dispatch_priority", "priority"), 50),
                    auto_continue=_bool(_first_present(raw, "auto_continue", "autoContinue")), continue_count=_int(_first_present(raw, "continue_count", "continueCount"), 0), max_continues=_int(_first_present(raw, "max_continues", "maxContinues"), 0),
                    retry_count=_int(_first_present(raw, "retry_count", "retryCount"), 0), max_retries=_int(_first_present(raw, "max_retries", "maxRetries"), 2), current_run_id=_text(raw.get("current_run_id")),
                    current_session_id=_text(raw.get("current_session_id")), last_run_state=_text(raw.get("last_run_state")), last_event_type=_text(raw.get("last_event_type")),
                    next_action_hint=_text(raw.get("next_action_hint")) or "controller_review", manual_review_required=_bool(raw.get("manual_review_required")),
                    blocked_reason=_text(raw.get("blocked_reason")), last_error=_text(raw.get("last_error")), last_result_summary=_text(raw.get("last_result_summary")),
                    machine_target=_text(raw.get("machine_target")) or "worker.example", model=_text(raw.get("model")) or "gpt-5.5", sandbox=_text(raw.get("sandbox")) or "danger-full-access",
                    last_dispatch_at=_first_present(raw, "last_dispatch_at", "last_execution_update"), last_callback_at=raw.get("last_callback_at"), stale_after=raw.get("stale_after"), updated_at=_text(_first_present(raw, "updatedAt", "updated_at", "last_execution_update")) or utc_now(),
                )
                conn.execute(
                    "INSERT OR REPLACE INTO projects(project_id,project_name,project_dir,notion_page_url,notion_page_id,origin_idea_status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)",
                    (project.project_id, project.project_name, project.project_dir, project.notion_page_url, project.notion_page_id, project.origin_idea_status, project.created_at, project.updated_at),
                )
                projects += 1
                conn.execute(
                    """INSERT OR REPLACE INTO queue_items(project_id,status,selection_rank,dispatch_priority,auto_continue,continue_count,max_continues,retry_count,max_retries,current_run_id,current_session_id,last_run_state,last_event_type,next_action_hint,manual_review_required,blocked_reason,last_error,last_result_summary,machine_target,model,sandbox,last_dispatch_at,last_callback_at,stale_after,updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (qi.project_id, qi.status.value, qi.selection_rank, qi.dispatch_priority, int(qi.auto_continue), qi.continue_count, qi.max_continues, qi.retry_count, qi.max_retries, qi.current_run_id, qi.current_session_id, qi.last_run_state, qi.last_event_type, qi.next_action_hint, int(qi.manual_review_required), qi.blocked_reason, qi.last_error, qi.last_result_summary, qi.machine_target, qi.model, qi.sandbox, qi.last_dispatch_at, qi.last_callback_at, qi.stale_after, qi.updated_at),
                )
                queue_items += 1
            for raw in paper_rows:
                paper_id = _text(raw.get("paper_id"))
                project_id = _text(raw.get("project_id"))
                if not paper_id or not project_id:
                    continue
                conn.execute(
                    "INSERT OR IGNORE INTO projects(project_id,project_name,project_dir,notion_page_url,notion_page_id,origin_idea_status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)",
                    (project_id, _text(raw.get("project_name")) or project_id, _text(raw.get("project_dir")), _text(raw.get("notion_page_url")), _text(raw.get("notion_page_id")) or _notion_page_id_from_url(_text(raw.get("notion_page_url"))), "", utc_now(), utc_now()),
                )
                status = _text(raw.get("paper_status")) or PaperStatus.DRAFT_REVIEW.value
                if status not in PaperStatus._value2member_map_:
                    status = PaperStatus.DRAFT_REVIEW.value
                conn.execute(
                    """INSERT OR REPLACE INTO papers(paper_id,project_id,run_id,paper_type,paper_status,draft_markdown_path,draft_latex_path,evidence_bundle_path,claim_ledger_path,manifest_path,generated_at,updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (paper_id, project_id, _text(raw.get("run_id")), _text(raw.get("paper_type")) or "arxiv_draft", status, _text(raw.get("draft_markdown_path")), _text(raw.get("draft_latex_path")), _text(raw.get("evidence_bundle_path")), _text(raw.get("claim_ledger_path")), _text(raw.get("manifest_path")), _text(raw.get("generated_at")) or utc_now(), _text(raw.get("updated_at")) or utc_now()),
                )
                papers += 1
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
                    p.created_at AS project_created_at,
                    p.updated_at AS project_updated_at
                FROM queue_items q JOIN projects p USING(project_id)
                ORDER BY q.dispatch_priority ASC, q.updated_at DESC"""
            ).fetchall()
        return [dict(row) for row in rows]

    def paper_rows(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT pa.*, p.project_name AS project_name, p.project_dir AS project_dir, p.notion_page_url AS notion_page_url, p.notion_page_id AS notion_page_id
                FROM papers pa LEFT JOIN projects p USING(project_id)
                ORDER BY pa.updated_at DESC"""
            ).fetchall()
        return [dict(row) for row in rows]


    def run_rows(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM runs ORDER BY updated_at DESC, run_id DESC").fetchall()
        return [dict(row) for row in rows]

    def run_row(self, run_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
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
                    p.created_at AS project_created_at,
                    p.updated_at AS project_updated_at
                FROM queue_items q JOIN projects p USING(project_id)
                WHERE q.project_id=?""",
                (project_id,),
            ).fetchone()
        return dict(row) if row else None

    def project_row(self, project_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM projects WHERE project_id=?", (project_id,)).fetchone()
        return dict(row) if row else None

    def paper_row(self, paper_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """SELECT pa.*, p.project_name AS project_name, p.project_dir AS project_dir, p.notion_page_url AS notion_page_url, p.notion_page_id AS notion_page_id
                FROM papers pa LEFT JOIN projects p USING(project_id)
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

    def _review_queue_item_from_row(self, row: dict[str, Any], *, include_rank_reasons: bool = True) -> dict[str, Any]:
        checklist = _json_dict(row.get("checklist_json")) or _default_review_checklist()
        rank_reasons = _json_list(row.get("rank_reasons_json")) if include_rank_reasons else []
        missing_signals = _json_list(row.get("missing_signals_json"))
        score = _int(row.get("rank_score"), 0)
        updated_at = _text(row.get("review_updated_at")) or _text(row.get("updated_at"))
        item = ReviewQueueItem(
            paper_id=_text(row.get("paper_id")),
            project_id=_text(row.get("project_id")),
            project_name=_text(row.get("project_name")),
            paper_status=_text(row.get("paper_status")),
            paper_type=_text(row.get("paper_type")),
            review_status=_text(row.get("review_status")) or ReviewStatus.UNREVIEWED.value,
            checklist_progress=_checklist_progress(checklist),
            blocker=_text(row.get("blocker")),
            reviewer=_text(row.get("reviewer")),
            claimed_at=_text(row.get("claimed_at")),
            updated_at=updated_at,
            rank_score=score,
            rank_bucket="blocked" if score < 0 else "ready" if score >= 100 else "review",
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
                "run": f"/control/api/runs/{_text(row.get('run_id'))}" if _text(row.get("run_id")) else "",
            },
        )
        return item.model_dump(mode="json")

    def paper_review_rows(self, *, include_rank_reasons: bool = True) -> list[dict[str, Any]]:
        return [self._review_queue_item_from_row(row, include_rank_reasons=include_rank_reasons) for row in self._paper_review_join_rows()]

    def paper_review_row(self, paper_id: str, *, include_rank_reasons: bool = True) -> dict[str, Any] | None:
        for row in self._paper_review_join_rows():
            if row.get("paper_id") == paper_id:
                return self._review_queue_item_from_row(row, include_rank_reasons=include_rank_reasons)
        return None

    def paper_review_checklist(self, paper_id: str) -> dict[str, Any]:
        row = self._raw_paper_review_row(paper_id)
        return _normalize_review_checklist(_json_dict(row.get("checklist_json")) if row else {})

    def backfill_paper_reviews(self, request: PaperReviewBackfillRequest) -> tuple[bool, int, int, int, list[dict[str, Any]]]:
        audit_by_paper = _audit_rows(request.source_audit_path)
        requested_paper_ids = {_text(paper_id) for paper_id in request.paper_ids if _text(paper_id)}
        papers = [
            paper
            for paper in self.paper_rows()
            if not requested_paper_ids or _text(paper.get("paper_id")) in requested_paper_ids
        ]
        errors: list[dict[str, Any]] = []
        candidates: list[PaperReviewRecord] = []
        for paper in papers:
            paper_id = _text(paper.get("paper_id"))
            mandatory = ["draft_markdown_path", "draft_latex_path", "evidence_bundle_path", "claim_ledger_path", "manifest_path"]
            missing_paths = [name for name in mandatory if not _text(paper.get(name))]
            if missing_paths:
                errors.append({"paper_id": paper_id, "reason": "missing mandatory artifact path", "missing_paths": missing_paths})
            audit = audit_by_paper.get(paper_id, {})
            initial_missing = ([] if audit else ["readiness_audit"]) + missing_paths
            queue_item = self.queue_row(_text(paper.get("project_id")))
            rank_score, rank_reasons, missing_signals, tiebreaker, _bucket = _review_rank(paper, queue_item, audit, initial_missing)
            status = ReviewStatus.TRIAGE_READY if _readiness_passed(audit) and not missing_paths else ReviewStatus.UNREVIEWED
            candidates.append(PaperReviewRecord(
                paper_id=paper_id,
                review_status=status,
                checklist_json=_default_review_checklist(),
                rank_score=rank_score,
                rank_reasons=rank_reasons,
                missing_signals=missing_signals,
                rank_tiebreaker=tiebreaker,
                source_audit_path=request.source_audit_path,
            ))
        if request.dry_run:
            return False, len(candidates), 0, 0, errors
        event_payload = request.model_dump(mode="json")
        event_payload.update({"candidate_count": len(candidates), "error_count": len(errors)})
        _, inserted = self.append_event(
            idempotency_key=request.idempotency_key,
            event_type="paper_review.backfill",
            entity_type="paper_reviews",
            entity_id="backfill",
            payload=event_payload,
        )
        created = updated = skipped = 0
        now = utc_now()
        with self._connect() as conn:
            for record in candidates:
                existing = conn.execute("SELECT * FROM paper_review_items WHERE paper_id=?", (record.paper_id,)).fetchone()
                rank_reasons_json = _json(record.rank_reasons)
                missing_signals_json = _json(record.missing_signals)
                if existing:
                    existing_review_status = _text(existing["review_status"])
                    next_review_status = (
                        record.review_status.value
                        if existing_review_status in {ReviewStatus.UNREVIEWED.value, ReviewStatus.TRIAGE_READY.value}
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
                        skipped += 1
                        continue
                    conn.execute(
                        """UPDATE paper_review_items
                        SET review_status=?, rank_score=?, rank_reasons_json=?, missing_signals_json=?, rank_tiebreaker=?, source_audit_path=?, updated_at=?
                        WHERE paper_id=?""",
                        (next_review_status, record.rank_score, rank_reasons_json, missing_signals_json, record.rank_tiebreaker, record.source_audit_path, now, record.paper_id),
                    )
                    updated += 1
                    continue
                conn.execute(
                    """INSERT INTO paper_review_items(paper_id,review_status,reviewer,blocker,claimed_at,checklist_json,rank_score,rank_reasons_json,missing_signals_json,rank_tiebreaker,source_audit_path,finalization_package_path,finalized_at,decision_summary,created_at,updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (record.paper_id, record.review_status.value, record.reviewer, record.blocker, record.claimed_at, _json(_normalize_review_checklist(record.checklist_json)), record.rank_score, rank_reasons_json, missing_signals_json, record.rank_tiebreaker, record.source_audit_path, record.finalization_package_path, record.finalized_at, record.decision_summary, now, now),
                )
                created += 1
        return inserted, created, updated, skipped, errors

    def _raw_paper_review_row(self, paper_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM paper_review_items WHERE paper_id=?", (paper_id,)).fetchone()
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

    def _replayed_event_id(self, idempotency_key: str, payload: dict[str, Any]) -> int | None:
        payload_hash = _hash(payload)
        with self._connect() as conn:
            row = conn.execute("SELECT event_id, payload_hash FROM events WHERE idempotency_key=?", (idempotency_key,)).fetchone()
        if row is None:
            return None
        if row["payload_hash"] != payload_hash:
            raise IdempotencyConflict(f"idempotency key {idempotency_key!r} was reused with different payload")
        return int(row["event_id"])

    def claim_paper_review(self, paper_id: str, request: PaperReviewClaimRequest) -> tuple[int, bool, dict[str, Any]]:
        if not _text(request.reviewer):
            raise ValueError("reviewer is required")
        row = self._require_paper_review(paper_id)
        current = _text(row.get("review_status"))
        if current in {ReviewStatus.FINALIZED.value, ReviewStatus.REJECTED.value, ReviewStatus.APPROVED_FOR_FINALIZATION.value}:
            raise ValueError(f"cannot claim paper review from {current}")
        if current == ReviewStatus.BLOCKED.value and _text(row.get("blocker")) and not request.clear_blocker:
            raise ValueError("blocked review requires clear_blocker=true to claim")
        if current not in {ReviewStatus.TRIAGE_READY.value, ReviewStatus.UNREVIEWED.value, ReviewStatus.CHANGES_REQUESTED.value, ReviewStatus.BLOCKED.value, ReviewStatus.IN_REVIEW.value}:
            raise ValueError(f"cannot claim paper review from {current}")
        payload = self._mutation_payload(request, action="claim")
        payload.update({"to_status": ReviewStatus.IN_REVIEW.value})
        event_id, inserted = self.append_event(idempotency_key=request.idempotency_key, event_type="paper_review.claimed", entity_type="paper_review", entity_id=paper_id, payload=payload)
        if inserted:
            now = utc_now()
            checklist = _normalize_review_checklist(_json_dict(row.get("checklist_json")))
            with self._connect() as conn:
                conn.execute(
                    """UPDATE paper_review_items
                    SET review_status=?, reviewer=?, blocker=?, claimed_at=?, checklist_json=?, updated_at=?
                    WHERE paper_id=?""",
                    (ReviewStatus.IN_REVIEW.value, _text(request.reviewer), "" if request.clear_blocker else _text(row.get("blocker")), now, _json(checklist), now, paper_id),
                )
        return event_id, inserted, self.paper_review_row(paper_id) or {}

    def update_paper_review_checklist(self, paper_id: str, item_id: str, request: PaperReviewChecklistUpdateRequest) -> tuple[int, bool, dict[str, Any]]:
        row = self._require_paper_review(paper_id)
        checklist = _normalize_review_checklist(_json_dict(row.get("checklist_json")))
        item = next((entry for entry in checklist["items"] if entry["id"] == item_id), None)
        if item is None:
            raise ValueError(f"unknown checklist item {item_id}")
        status = _text(request.status)
        note = _text(request.note)
        if status == "fail" and not note:
            raise ValueError("fail checklist status requires a note")
        if status == "accepted_risk" and not note:
            raise ValueError("accepted_risk checklist status requires a note")
        if item_id == "final_human_approval" and status in {"accepted_risk", "not_applicable"}:
            raise ValueError("final_human_approval must be pass or fail/pending")
        if status == "not_applicable" and item.get("required") and not note:
            raise ValueError("not_applicable on a required item requires a note")
        payload = self._mutation_payload(request, action="checklist_update")
        payload["item_id"] = item_id
        event_id, inserted = self.append_event(idempotency_key=request.idempotency_key, event_type="paper_review.checklist_updated", entity_type="paper_review", entity_id=paper_id, payload=payload)
        if inserted:
            now = utc_now()
            item.update({"status": status, "note": note, "updated_at": now, "updated_by": _text(request.requested_by)})
            risks = [risk for risk in checklist.get("accepted_risks", []) if isinstance(risk, dict) and risk.get("item_id") != item_id]
            if status == "accepted_risk":
                risks.append({"item_id": item_id, "risk": note, "accepted_by": _text(request.requested_by), "accepted_at": now})
            checklist["accepted_risks"] = risks
            checklist["progress"] = _progress_for_items(checklist["items"])
            with self._connect() as conn:
                conn.execute("UPDATE paper_review_items SET checklist_json=?, updated_at=? WHERE paper_id=?", (_json(checklist), now, paper_id))
        return event_id, inserted, self.paper_review_row(paper_id) or {}

    def update_paper_review_status(self, paper_id: str, request: PaperReviewStatusUpdateRequest) -> tuple[int, bool, dict[str, Any]]:
        row = self._require_paper_review(paper_id)
        current = _text(row.get("review_status"))
        target = request.review_status.value
        if target == ReviewStatus.APPROVED_FOR_FINALIZATION.value:
            raise ValueError("use approve-finalization endpoint for approval")
        if target in {ReviewStatus.FINALIZED.value}:
            raise ValueError("finalized status is reserved for finalization package workflow")
        if target not in ALLOWED_STATUS_TRANSITIONS.get(current, set()) and target != current:
            raise ValueError(f"invalid review status transition {current} -> {target}")
        blocker = _text(request.blocker)
        note = _text(request.note)
        if target in {ReviewStatus.BLOCKED.value, ReviewStatus.CHANGES_REQUESTED.value, ReviewStatus.REJECTED.value} and not (blocker or note):
            raise ValueError(f"{target} requires blocker or note")
        payload = self._mutation_payload(request, action="status_update")
        payload.update({"to_status": target})
        event_id, inserted = self.append_event(idempotency_key=request.idempotency_key, event_type="paper_review.status_changed", entity_type="paper_review", entity_id=paper_id, payload=payload)
        if inserted:
            now = utc_now()
            next_blocker = blocker if target == ReviewStatus.BLOCKED.value else ""
            decision_summary = note if target in {ReviewStatus.REJECTED.value, ReviewStatus.CHANGES_REQUESTED.value} else _text(row.get("decision_summary"))
            with self._connect() as conn:
                conn.execute("UPDATE paper_review_items SET review_status=?, blocker=?, decision_summary=?, updated_at=? WHERE paper_id=?", (target, next_blocker, decision_summary, now, paper_id))
        return event_id, inserted, self.paper_review_row(paper_id) or {}

    def approve_paper_review_finalization(self, paper_id: str, request: PaperReviewApproveFinalizationRequest) -> tuple[int, bool, dict[str, Any]]:
        row = self._require_paper_review(paper_id)
        payload = self._mutation_payload(request, action="approve_finalization")
        payload.update({"to_status": ReviewStatus.APPROVED_FOR_FINALIZATION.value})
        replayed_event_id = self._replayed_event_id(request.idempotency_key, payload)
        if replayed_event_id is not None:
            return replayed_event_id, False, self.paper_review_row(paper_id) or {}
        current = _text(row.get("review_status"))
        if current != ReviewStatus.IN_REVIEW.value:
            raise ValueError("approval requires review_status=in_review")
        checklist = _normalize_review_checklist(_json_dict(row.get("checklist_json")))
        blockers: list[str] = []
        for item in checklist["items"]:
            if not item.get("required"):
                continue
            status = _text(item.get("status"))
            if item["id"] == "final_human_approval" and status != "pass":
                blockers.append("final_human_approval must pass")
            elif status == "accepted_risk" and not _text(item.get("note")):
                blockers.append(f"{item['id']} accepted risk requires note")
            elif status != "pass" and status != "accepted_risk":
                blockers.append(f"{item['id']} must pass or be accepted_risk")
        if blockers:
            raise ValueError("; ".join(blockers))
        event_id, inserted = self.append_event(idempotency_key=request.idempotency_key, event_type="paper_review.approved_for_finalization", entity_type="paper_review", entity_id=paper_id, payload=payload)
        if inserted:
            now = utc_now()
            decision_summary = _text(request.note) or "approved for finalization"
            with self._connect() as conn:
                conn.execute("UPDATE paper_review_items SET review_status=?, decision_summary=?, updated_at=? WHERE paper_id=?", (ReviewStatus.APPROVED_FOR_FINALIZATION.value, decision_summary, now, paper_id))
        return event_id, inserted, self.paper_review_row(paper_id) or {}

    def _resolved_artifact(self, paper: dict[str, Any], field: str) -> dict[str, Any]:
        raw_path = _text(paper.get(field))
        project_dir = Path(_text(paper.get("project_dir"))).expanduser() if _text(paper.get("project_dir")) else None
        path = Path(raw_path).expanduser() if raw_path else Path()
        resolved = path if path.is_absolute() else (project_dir / path if project_dir else path)
        exists = bool(raw_path) and resolved.exists()
        readable = exists and resolved.is_file()
        size_bytes = resolved.stat().st_size if readable else 0
        return {"field": field, "path": raw_path, "absolute_path": str(resolved), "exists": exists, "readable": readable, "size_bytes": size_bytes}

    def _finalization_manifest_path(self, paper_id: str, idempotency_key: str) -> Path:
        return self.path.parent / "finalization_packages" / _slug_id(paper_id) / _slug_id(idempotency_key) / "finalization_manifest.json"

    def _load_manifest(self, package_path: str) -> dict[str, Any]:
        if not package_path:
            return {}
        path = Path(package_path)
        try:
            return _json_dict(path.read_text(encoding="utf-8")) if path.exists() else {}
        except OSError:
            return {}

    def prepare_paper_review_finalization_package(self, paper_id: str, request: PaperReviewPrepareFinalizationRequest, *, require_approval: bool = True) -> tuple[int | None, bool, dict[str, Any], str, dict[str, Any]]:
        row = self._require_paper_review(paper_id)
        payload = self._mutation_payload(request, action="prepare_finalization_package")
        payload.update({"to_status": ReviewStatus.FINALIZED.value, "require_approval": require_approval})
        if not request.dry_run:
            replayed_event_id = self._replayed_event_id(request.idempotency_key, payload)
            if replayed_event_id is not None:
                item = self.paper_review_row(paper_id) or {}
                return replayed_event_id, False, item, _text(item.get("finalization_package_path")), self._load_manifest(_text(item.get("finalization_package_path")))
        current = _text(row.get("review_status"))
        if not request.dry_run and current == ReviewStatus.FINALIZED.value:
            item = self.paper_review_row(paper_id) or {}
            path = _text(item.get("finalization_package_path"))
            return None, False, item, path, self._load_manifest(path)
        if not request.dry_run and require_approval and current != ReviewStatus.APPROVED_FOR_FINALIZATION.value:
            raise ValueError("finalization package requires review_status=approved_for_finalization")
        if not request.dry_run and not require_approval and current == ReviewStatus.REJECTED.value:
            raise ValueError("automated finalization cannot publish rejected paper reviews")
        paper = self.paper_row(paper_id)
        if paper is None:
            raise ValueError("paper row not found")
        checklist = self.paper_review_checklist(paper_id)
        artifacts = [self._resolved_artifact(paper, field) for field in ("draft_markdown_path", "draft_latex_path", "evidence_bundle_path", "claim_ledger_path", "manifest_path")]
        unreadable = [artifact["field"] for artifact in artifacts if not artifact["readable"]]
        if unreadable and not request.dry_run:
            raise ValueError(f"finalization package requires readable artifacts: {', '.join(unreadable)}")
        package_path = self._finalization_manifest_path(paper_id, request.idempotency_key)
        now = utc_now()
        manifest = {
            "schema": "paper_finalization_package_v1",
            "generated_at": now,
            "dry_run": request.dry_run,
            "requested_by": request.requested_by,
            "target_label": request.target_label,
            "paper_id": paper_id,
            "project_id": _text(paper.get("project_id")),
            "project_name": _text(paper.get("project_name")),
            "paper_status": _text(paper.get("paper_status")),
            "review_status": current,
            "reviewer": _text(row.get("reviewer")),
            "decision_summary": _text(row.get("decision_summary")),
            "require_approval": require_approval,
            "automated_publication": not require_approval,
            "artifacts": artifacts,
            "checklist": checklist,
            "review_item": self.paper_review_row(paper_id) or {},
            "no_submission_side_effects": True,
        }
        if request.dry_run:
            return None, False, self.paper_review_row(paper_id) or {}, str(package_path), manifest
        package_path.parent.mkdir(parents=True, exist_ok=True)
        package_path.write_text(_json(manifest), encoding="utf-8")
        event_id, inserted = self.append_event(idempotency_key=request.idempotency_key, event_type="paper_review.finalization_package_prepared", entity_type="paper_review", entity_id=paper_id, payload=payload)
        if inserted:
            with self._connect() as conn:
                conn.execute(
                    "UPDATE paper_review_items SET review_status=?, finalization_package_path=?, finalized_at=?, updated_at=? WHERE paper_id=?",
                    (ReviewStatus.FINALIZED.value, str(package_path), now, now, paper_id),
                )
        item = self.paper_review_row(paper_id) or {}
        return event_id, inserted, item, str(package_path), manifest

    def event_rows(self, limit: int = 100, *, entity_type: str = "", entity_id: str = "", event_type: str = "", search: str = "") -> list[dict[str, Any]]:
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
            clauses.append("(event_type LIKE ? OR entity_id LIKE ? OR payload_json LIKE ?)")
            needle = f"%{search}%"
            params.extend([needle, needle, needle])
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(1, min(limit, 1000)))
        with self._connect() as conn:
            rows = conn.execute(f"SELECT * FROM events {where} ORDER BY event_id DESC LIMIT ?", params).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            item["payload"] = json.loads(item.pop("payload_json"))
            item.pop("payload_hash", None)
            out.append(item)
        return out

    def active_items(self) -> list[dict[str, Any]]:
        return [row for row in self.queue_rows() if row.get("status") in ACTIVE_STATUSES]

    def status_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for row in self.queue_rows():
            key = _text(row.get("status")) or "unknown"
            counts[key] = counts.get(key, 0) + 1
        return counts

    def recent_events(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM events ORDER BY event_id DESC LIMIT ?", (limit,)).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            item["payload"] = json.loads(item.pop("payload_json"))
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
                (source, scope, observed_at or now, ttl_seconds, status, payload_json, payload_hash, now),
            )
            observation_id = int(cur.lastrowid)
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

    def latest_dashboard_observation(self, *, source: str, scope: str = "global") -> DashboardObservationRecord | None:
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

    def latest_dashboard_observations(self, *, scope: str = "global") -> dict[str, DashboardObservationRecord]:
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

    def next_dispatch_candidate(self) -> dict[str, Any] | None:
        if self.flags().queue_paused:
            return None
        if self.active_items():
            return None
        candidates = [
            row for row in self.queue_rows()
            if row.get("status") == QueueStatus.QUEUED.value and not row.get("manual_review_required")
        ]
        candidates.sort(key=lambda row: (_int(row.get("dispatch_priority"), 9999), _int(row.get("selection_rank"), 9999), _text(row.get("updated_at"))))
        return candidates[0] if candidates else None

    def dispatch_next_dry_run(self, *, requested_by: str) -> tuple[str, dict[str, Any] | None, int | None, str]:
        flags = self.flags()
        if flags.queue_paused:
            event_id, _ = self.append_event(idempotency_key=f"dispatch-paused:{utc_now()}", event_type="controller.dispatch_paused", entity_type="control", entity_id="queue", payload={"requested_by": requested_by, "flags": flags.model_dump(mode="json")})
            return "paused", None, event_id, flags.pause_reason or "queue paused"
        active = self.active_items()
        if active:
            return "noop", None, None, "active GB10 lane already exists"
        candidate = self.next_dispatch_candidate()
        if not candidate:
            return "noop", None, None, "no queued candidate"
        event_id, _ = self.append_event(idempotency_key=f"dry-dispatch:{candidate['project_id']}:{utc_now()}", event_type="controller.dry_run_dispatch", entity_type="project", entity_id=candidate["project_id"], payload={"requested_by": requested_by, "candidate": candidate})
        return "dry_run_dispatch", candidate, event_id, "dry-run dispatch selected candidate"


    def ingest_notion_ideas(self, request: NotionIntakeRequest) -> tuple[bool, int, int, int, list[dict[str, Any]], list[dict[str, Any]]]:
        include_statuses = {item.strip().lower() for item in request.include_statuses if item.strip()}
        candidates: list[dict[str, Any]] = []
        skipped_rows: list[dict[str, Any]] = []
        for raw in request.notion_rows:
            title = _notion_title(raw)
            status = _notion_status(raw).lower()
            page_id = _notion_page_id(raw)
            page_url = _notion_url(raw)
            if not title:
                skipped_rows.append({"reason": "missing title", "row": raw})
                continue
            if include_statuses and status and status not in include_statuses:
                skipped_rows.append({"reason": f"status {status!r} not included", "title": title, "status": status, "page_id": page_id})
                continue
            project_id = _slug_id(page_id.replace("-", "")) if page_id else f"notion-{_slug_id(title)}"
            if not project_id:
                skipped_rows.append({"reason": "missing project id", "title": title, "page_id": page_id})
                continue
            candidates.append({
                "project_id": project_id,
                "project_name": title,
                "project_dir": project_id,
                "notion_page_url": page_url,
                "notion_page_id": page_id,
                "origin_idea_status": status,
                "status": QueueStatus.QUEUED.value,
                "selection_rank": _priority_rank(raw),
                "dispatch_priority": _priority_rank(raw),
                "next_action_hint": "controller_review",
                "machine_target": request.default_machine_target,
                "model": request.default_model,
                "sandbox": request.default_sandbox,
                "source_row": raw,
            })
        if request.dry_run:
            return False, 0, 0, len(skipped_rows), candidates, skipped_rows
        event_payload = request.model_dump(mode="json")
        event_payload["candidate_count"] = len(candidates)
        event_payload["skipped_count"] = len(skipped_rows)
        _event_id, inserted = self.append_event(
            idempotency_key=request.idempotency_key,
            event_type="notion.intake",
            entity_type="snapshot",
            entity_id=request.source,
            payload=event_payload,
        )
        created = updated = 0
        if not inserted:
            return inserted, created, updated, len(skipped_rows), candidates, skipped_rows
        now = utc_now()
        with self._connect() as conn:
            for candidate in candidates:
                existed = conn.execute("SELECT 1 FROM queue_items WHERE project_id=?", (candidate["project_id"],)).fetchone() is not None
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
                    "INSERT OR REPLACE INTO projects(project_id,project_name,project_dir,notion_page_url,notion_page_id,origin_idea_status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)",
                    (project.project_id, project.project_name, project.project_dir, project.notion_page_url, project.notion_page_id, project.origin_idea_status, project.created_at, project.updated_at),
                )
                if existed:
                    conn.execute(
                        """UPDATE queue_items SET selection_rank=?, dispatch_priority=?, machine_target=?, model=?, sandbox=?, updated_at=?
                        WHERE project_id=? AND status NOT IN ('dispatching','running','awaiting_wake','wake_received','reconciling')""",
                        (qi.selection_rank, qi.dispatch_priority, qi.machine_target, qi.model, qi.sandbox, qi.updated_at, qi.project_id),
                    )
                    updated += 1
                else:
                    conn.execute(
                        """INSERT INTO queue_items(project_id,status,selection_rank,dispatch_priority,auto_continue,continue_count,max_continues,retry_count,max_retries,current_run_id,current_session_id,last_run_state,last_event_type,next_action_hint,manual_review_required,blocked_reason,last_error,last_result_summary,machine_target,model,sandbox,last_dispatch_at,last_callback_at,stale_after,updated_at)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (qi.project_id, qi.status.value, qi.selection_rank, qi.dispatch_priority, int(qi.auto_continue), qi.continue_count, qi.max_continues, qi.retry_count, qi.max_retries, qi.current_run_id, qi.current_session_id, qi.last_run_state, qi.last_event_type, qi.next_action_hint, int(qi.manual_review_required), qi.blocked_reason, qi.last_error, qi.last_result_summary, qi.machine_target, qi.model, qi.sandbox, qi.last_dispatch_at, qi.last_callback_at, qi.stale_after, qi.updated_at),
                    )
                    created += 1
        return inserted, created, updated, len(skipped_rows), candidates, skipped_rows

    def notion_execution_update_projection(self) -> list[dict[str, Any]]:
        state_map = {
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
        paper_by_project = {paper.get("project_id"): paper for paper in self.paper_rows()}
        rows = []
        for row in self.queue_rows():
            paper = paper_by_project.get(row.get("project_id")) or {}
            row = {**row, "paper_id": paper.get("paper_id") or "", "paper_status": paper.get("paper_status") or "", "paper_type": paper.get("paper_type") or "", "draft_markdown_path": paper.get("draft_markdown_path") or "", "paper_updated_at": paper.get("updated_at") or ""}
            page_url = row.get("notion_page_url") or ""
            if not page_url:
                continue
            execution_state = state_map.get(row.get("status") or "", "blocked")
            blocked_reason = row.get("blocked_reason") or (row.get("last_result_summary") if execution_state in {"blocked", "failed"} else "") or ""
            rows.append({
                "project_id": row.get("project_id") or "",
                "page_id": row.get("notion_page_id") or _notion_page_id_from_url(page_url),
                "notion_page_url": page_url,
                "properties": {
                    "Execution State": execution_state,
                    "Current Run ID": row.get("current_run_id") or "",
                    "Next Action": row.get("next_action_hint") or "",
                    "Blocked Reason": blocked_reason,
                    "Last Execution Update": row.get("updated_at") or utc_now(),
                    "Execution Summary": row.get("last_result_summary") or "",
                    "OMX Project ID": row.get("project_id") or "",
                    "OMX Queue Status": row.get("status") or "",
                    "OMX Last Run State": row.get("last_run_state") or "",
                    "OMX Last Event Type": row.get("last_event_type") or "",
                    "OMX Next Action Hint": row.get("next_action_hint") or "",
                    "OMX Project Dir": row.get("project_dir") or "",
                    "OMX Current Session ID": row.get("current_session_id") or "",
                    "OMX Last Result Summary": row.get("last_result_summary") or "",
                    "OMX Last Error": row.get("last_error") or "",
                    "OMX Manual Review Required": "__YES__" if row.get("manual_review_required") else "__NO__",
                    "OMX Dispatch Priority": row.get("dispatch_priority") or 0,
                    "OMX Selection Rank": row.get("selection_rank") or 0,
                    "OMX Paper ID": row.get("paper_id") or "",
                    "OMX Paper Status": row.get("paper_status") or "",
                    "OMX Paper Type": row.get("paper_type") or "",
                    "OMX Paper Markdown Path": row.get("draft_markdown_path") or "",
                    "OMX Paper Updated At": row.get("paper_updated_at") or "",
                    "OMX Paper Updated At ISO": row.get("paper_updated_at") or "",
                },
            })
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
            rows.append({
                "project_id": row.get("project_id") or "",
                "project_name": row.get("project_name") or "",
                "queue_status": row.get("status") or "",
                "next_action_hint": row.get("next_action_hint") or "",
                "last_run_state": row.get("last_run_state") or "",
                "last_event_type": row.get("last_event_type") or "",
                "current_run_id": row.get("current_run_id") or "",
                "current_session_id": row.get("current_session_id") or "",
                "machine_target": row.get("machine_target") or "",
                "manual_review_required": bool(row.get("manual_review_required")),
                "blocked_reason": row.get("blocked_reason") or "",
                "last_result_summary": row.get("last_result_summary") or "",
                "notion_page_url": row.get("notion_page_url") or "",
                "updated_at": row.get("updated_at") or "",
            })
        return rows

    def paper_notion_projection(self) -> list[dict[str, Any]]:
        rows = []
        for paper in self.paper_rows():
            rows.append({
                "paper_id": paper.get("paper_id") or "",
                "project_id": paper.get("project_id") or "",
                "project_name": paper.get("project_name") or paper.get("project_id") or "",
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
            })
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
        with self._connect() as conn:
            conn.execute(
                """UPDATE queue_items
                SET status=?, current_run_id=?, current_session_id=?, last_run_state=?, last_event_type=?, next_action_hint=?, last_error=?, last_result_summary=?, last_dispatch_at=?, updated_at=?
                WHERE project_id=?""",
                (
                    QueueStatus.AWAITING_WAKE.value,
                    run_id,
                    session_id,
                    "dispatch_accepted",
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
                (run_id, project_id, session_id, "running", "exec", now, None, None, "running", "dispatched", f"live-dispatch:{run_id}", now),
            )
        event_id, _ = self.append_event(
            idempotency_key=f"live-dispatch:{run_id}",
            event_type="controller.live_dispatch",
            entity_type="project",
            entity_id=project_id,
            payload={"requested_by": requested_by, "run_id": run_id, "session_id": session_id, "dispatch": dispatch_payload},
        )
        row = next((item for item in self.queue_rows() if item.get("project_id") == project_id), {})
        return event_id, row

    def record_worker_callback(self, callback: Any, *, received_by: str = "worker-callback") -> tuple[int, bool, dict[str, Any]]:
        now = utc_now()
        payload = callback.model_dump(mode="json") if hasattr(callback, "model_dump") else dict(callback)
        run_id = _text(payload.get("run_id"))
        project_id = _text(payload.get("project_id"))
        event_type = _text(payload.get("event_type"))
        idempotency_key = _text(payload.get("idempotency_key")) or f"worker-callback:{run_id}:{event_type}:{now}"
        if not project_id and run_id:
            with self._connect() as conn:
                found = conn.execute("SELECT project_id FROM runs WHERE run_id=?", (run_id,)).fetchone()
                project_id = found["project_id"] if found else ""
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
        elif event_type in {"wake_ready", "session_finished_ready"}:
            next_action_hint = "draft_paper_or_select_next_project"
        else:
            status = QueueStatus.NEEDS_REVIEW.value
            next_action_hint = "inspect_unknown_worker_callback"
            manual_review_required = 1
            last_error = _text(payload.get("reason")) or f"unknown worker callback: {event_type}"
        event_payload = {
            **payload,
            "received_by": received_by,
            "applied_status": status,
            "applied_next_action_hint": next_action_hint,
        }
        replayed_event_id = self._replayed_event_id(idempotency_key, event_payload)
        if replayed_event_id is not None:
            row = self.queue_row(project_id) if project_id else {}
            return replayed_event_id, False, row or {}
        summary = f"worker callback {event_type}: {_text(payload.get('reason')) or 'worker reported ready'}"
        run_state = RunState.RUNNING.value if event_type == "session_started" else event_type
        run_ended_at = None if event_type == "session_started" else now
        with self._connect() as conn:
            if project_id:
                conn.execute(
                    """UPDATE queue_items
                    SET status=?, current_session_id=COALESCE(NULLIF(?, ''), current_session_id), last_run_state=?,
                        last_event_type=?, next_action_hint=?, manual_review_required=?, last_error=?,
                        last_result_summary=?, last_callback_at=?, updated_at=?
                    WHERE project_id=?""",
                    (status, _text(payload.get("session_id")), event_type, "worker_callback", next_action_hint, manual_review_required, last_error, summary, now, now, project_id),
                )
            if run_id:
                conn.execute(
                    """UPDATE runs
                    SET session_id=COALESCE(NULLIF(?, ''), session_id), state=?, ended_at=?, last_callback_at=?,
                        gate_state=?, current_activity=?, updated_at=?
                    WHERE run_id=?""",
                    (_text(payload.get("session_id")), run_state, run_ended_at, now, _text(payload.get("gate_state")) or event_type, "worker_callback", now, run_id),
                )
        event_id, inserted = self.append_event(
            idempotency_key=idempotency_key,
            event_type=f"worker_callback.{event_type}",
            entity_type="run",
            entity_id=run_id or project_id or "unknown",
            payload=event_payload,
        )
        row = next((item for item in self.queue_rows() if item.get("project_id") == project_id), {})
        return event_id, inserted, row

    def mark_queue_item_paused(self, *, project_id: str, reason: str, updated_by: str = "operator") -> bool:
        now = utc_now()
        with self._connect() as conn:
            cur = conn.execute(
                """UPDATE queue_items
                SET status=?, next_action_hint=?, last_result_summary=?, updated_at=?
                WHERE project_id=?""",
                (QueueStatus.PAUSED.value, "maintenance_cutover_reconcile", reason, now, project_id),
            )
        if cur.rowcount < 1:
            return False
        self.append_event(
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

    def upsert_paper(self, paper: PaperRecord) -> None:
        with self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO papers(paper_id,project_id,run_id,paper_type,paper_status,draft_markdown_path,draft_latex_path,evidence_bundle_path,claim_ledger_path,manifest_path,generated_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (paper.paper_id, paper.project_id, paper.run_id, paper.paper_type, paper.paper_status.value, paper.draft_markdown_path, paper.draft_latex_path, paper.evidence_bundle_path, paper.claim_ledger_path, paper.manifest_path, paper.generated_at, paper.updated_at),
            )
