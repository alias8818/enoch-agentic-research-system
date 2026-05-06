from __future__ import annotations

import hashlib
import json
import os
import threading
from pathlib import Path
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
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
    ReviewQueueItem,
    ReviewStatus,
    RunState,
)
from .store import (
    ACTIVE_STATUSES,
    ALLOWED_STATUS_TRANSITIONS,
    QueueStatus,
    _audit_rows,
    _bool,
    _checklist_progress,
    _default_review_checklist,
    _first_present,
    _hash,
    _int,
    _json,
    _json_dict,
    _json_list,
    _notion_page_id,
    _notion_page_id_from_url,
    _notion_status,
    _notion_title,
    _notion_url,
    _normalize_review_checklist,
    _priority_rank,
    _progress_for_items,
    _readiness_passed,
    _review_rank,
    _slug_id,
    _snapshot_rows,
    _text,
)


ConnectionFactory = Callable[[], Any]


class ReadOnlyStoreError(RuntimeError):
    """Raised when a write path is attempted through the Supabase read adapter."""


class SupabaseReadOnlyControlPlaneStore:
    """Read-only Postgres adapter for the Enoch control-plane schema.

    This adapter is intentionally narrow. It supports dashboard/status parity
    reads against the private `enoch` schema and rejects mutation attempts so a
    config flag cannot silently cut production writes over to Supabase.
    """

    def __init__(self, database_url: str, *, connect: ConnectionFactory | None = None) -> None:
        self.database_url = database_url.strip()
        if not self.database_url:
            raise ValueError("supabase_database_url is required for supabase backends")
        self._connect_factory = connect or self._psycopg_connect
        self._external_connect_factory = connect is not None
        self._conn_lock = threading.RLock()
        self._persistent_conn: Any | None = None

    def _psycopg_connect(self) -> Any:
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:  # pragma: no cover - dependency is declared in pyproject.
            raise RuntimeError("psycopg is required for the Supabase control-plane adapter") from exc
        return psycopg.connect(self.database_url, row_factory=dict_row)

    @contextmanager
    def _connect(self) -> Iterator[Any]:
        if self._external_connect_factory:
            conn = self._connect_factory()
            try:
                with conn:
                    with conn.cursor() as cur:
                        cur.execute("set search_path to enoch, public")
                    yield conn
            finally:
                close = getattr(conn, "close", None)
                if callable(close):
                    close()
            return

        with self._conn_lock:
            conn = self._persistent_conn
            if conn is None or getattr(conn, "closed", False):
                conn = self._connect_factory()
                self._persistent_conn = conn
            try:
                with conn.cursor() as cur:
                    cur.execute("set search_path to enoch, public")
                yield conn
                conn.commit()
            except Exception:
                rollback = getattr(conn, "rollback", None)
                if callable(rollback):
                    rollback()
                if getattr(conn, "closed", False):
                    self._persistent_conn = None
                raise

    def _query(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, tuple(params))
                rows = cur.fetchall()
        return [dict(row) for row in rows]

    def _one(self, sql: str, params: Sequence[Any] = ()) -> dict[str, Any] | None:
        rows = self._query(sql, params)
        return rows[0] if rows else None

    @staticmethod
    def _payload(value: Any) -> Any:
        if isinstance(value, str):
            return json.loads(value or "{}")
        return value if value is not None else {}

    @staticmethod
    def _json_text(value: Any) -> str:
        if isinstance(value, str):
            return value
        return json.dumps(value if value is not None else {}, sort_keys=True, separators=(",", ":"))

    def _read_only(self, *_args: Any, **_kwargs: Any) -> None:
        raise ReadOnlyStoreError("Supabase control-plane adapter is read-only in this migration phase")

    append_event = _read_only
    import_snapshot = _read_only
    pause = _read_only
    resume = _read_only
    upsert_dashboard_observation = _read_only

    def flags(self) -> ControlFlags:
        row = self._one("select * from control_flags where singleton = true")
        if not row:
            return ControlFlags()
        return ControlFlags(
            queue_paused=bool(row["queue_paused"]),
            maintenance_mode=bool(row["maintenance_mode"]),
            pause_reason=_text(row["pause_reason"]),
            paused_at=str(row["paused_at"]) if row.get("paused_at") is not None else None,
            paused_by=_text(row["paused_by"]),
            updated_at=str(row["updated_at"]),
        )

    def queue_counts_sql(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for row in self._query("select status, count(*) as count from queue_items group by status"):
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
        blocked = self._one(
            """
            select count(*) as count
            from queue_items
            where manual_review_required = true or status in (%s, %s, %s)
            """,
            (QueueStatus.BLOCKED.value, QueueStatus.NEEDS_REVIEW.value, QueueStatus.DISPATCH_ERROR.value),
        )
        counts["blocked"] = int((blocked or {}).get("count") or 0)
        for key in ("all", "active", "queued", "blocked", "paused", "completed"):
            counts.setdefault(key, 0)
        return counts

    def paper_counts_sql(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for row in self._query("select paper_status, count(*) as count from papers group by paper_status"):
            status = _text(row["paper_status"]) or "unknown"
            count = int(row["count"] or 0)
            counts[status] = count
            counts["all"] = counts.get("all", 0) + count
        counts.setdefault("all", 0)
        return counts

    def queue_rows(self) -> list[dict[str, Any]]:
        return self._queue_rows("order by q.dispatch_priority asc, q.updated_at desc")

    def operator_queue_rows_sql(self) -> list[dict[str, Any]]:
        return self._queue_rows(
            """
            where q.status <> %s or q.next_action_hint = %s or q.manual_review_required = true
            order by q.updated_at desc
            """,
            (QueueStatus.CANCELED.value, "draft_paper_or_select_next_project"),
        )

    def active_items_sql(self, *, limit: int = 10) -> list[dict[str, Any]]:
        safe_limit = max(1, min(limit, 50))
        placeholders = ",".join(["%s"] * len(ACTIVE_STATUSES))
        return self._queue_rows(
            f"where q.status in ({placeholders}) order by q.updated_at desc limit %s",
            (*sorted(ACTIVE_STATUSES), safe_limit),
        )

    def active_items(self) -> list[dict[str, Any]]:
        return self.active_items_sql(limit=50)

    def next_candidate_sql(self) -> dict[str, Any] | None:
        rows = self._queue_rows(
            "where q.status = %s order by q.dispatch_priority asc, q.updated_at desc limit 1",
            (QueueStatus.QUEUED.value,),
        )
        return rows[0] if rows else None

    def next_dispatch_candidate(self) -> dict[str, Any] | None:
        if self.flags().queue_paused:
            return None
        if self.active_items():
            return None
        rows = self._queue_rows(
            """
            where q.status = %s and q.manual_review_required = false
            order by q.dispatch_priority asc, q.selection_rank asc, q.updated_at asc
            limit 1
            """,
            (QueueStatus.QUEUED.value,),
        )
        return rows[0] if rows else None

    def _queue_rows(self, suffix: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        return self._query(
            f"""
            select q.*,
              p.project_name,
              p.project_dir,
              p.notion_page_url,
              p.notion_page_id,
              p.origin_idea_status,
              (
                select pa.paper_id
                from papers pa
                where pa.project_id = q.project_id
                  and (q.current_run_id = '' or pa.run_id = q.current_run_id)
                order by pa.updated_at desc
                limit 1
              ) as related_paper_id,
              (
                select pa.paper_status
                from papers pa
                where pa.project_id = q.project_id
                  and (q.current_run_id = '' or pa.run_id = q.current_run_id)
                order by pa.updated_at desc
                limit 1
              ) as related_paper_status,
              (
                select rv.automation_status
                from papers pa
                left join publication_automation_items rv using(paper_id)
                where pa.project_id = q.project_id
                  and (q.current_run_id = '' or pa.run_id = q.current_run_id)
                order by pa.updated_at desc
                limit 1
              ) as related_review_status,
              (
                select rv.finalization_package_path
                from papers pa
                left join publication_automation_items rv using(paper_id)
                where pa.project_id = q.project_id
                  and (q.current_run_id = '' or pa.run_id = q.current_run_id)
                order by pa.updated_at desc
                limit 1
              ) as related_finalization_package_path,
              p.created_at as project_created_at,
              p.updated_at as project_updated_at
            from queue_items q
            join projects p using(project_id)
            {suffix}
            """,
            params,
        )

    def paper_rows(self) -> list[dict[str, Any]]:
        return self._paper_rows("order by pa.updated_at desc")

    def operator_paper_rows_sql(self) -> list[dict[str, Any]]:
        return self.paper_rows()

    def _paper_rows(self, suffix: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        return self._query(
            f"""
            select pa.*,
              p.project_name,
              p.project_dir,
              p.notion_page_url,
              p.notion_page_id,
              rv.automation_status as review_status,
              rv.finalization_package_path,
              rv.finalized_at
            from papers pa
            left join projects p using(project_id)
            left join publication_automation_items rv using(paper_id)
            {suffix}
            """,
            params,
        )


    @staticmethod
    def _page(rows: list[dict[str, Any]], page_size: int, cursor: str) -> tuple[list[dict[str, Any]], str | None, bool]:
        safe_size = max(1, min(page_size, 200))
        offset = max(0, _int(cursor, 0))
        page_rows = rows[offset : offset + safe_size]
        has_more = len(rows) > offset + safe_size
        next_cursor = str(offset + safe_size) if has_more else None
        return page_rows, next_cursor, has_more

    @staticmethod
    def _matches(row: dict[str, Any], search: str, keys: Sequence[str]) -> bool:
        needle = search.strip().lower()
        if not needle:
            return True
        return any(needle in _text(row.get(key)).lower() for key in keys)

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
        rows = self.queue_rows()
        if queue == "active":
            rows = [row for row in rows if row.get("status") in ACTIVE_STATUSES]
        elif queue == "queued":
            rows = [row for row in rows if row.get("status") == QueueStatus.QUEUED.value]
        elif queue == "blocked":
            rows = [
                row for row in rows
                if row.get("manual_review_required") or row.get("status") in {
                    QueueStatus.BLOCKED.value,
                    QueueStatus.NEEDS_REVIEW.value,
                    QueueStatus.DISPATCH_ERROR.value,
                }
            ]
        elif queue == "paused":
            rows = [row for row in rows if row.get("status") == QueueStatus.PAUSED.value]
        elif queue == "completed":
            rows = [row for row in rows if row.get("status") in {QueueStatus.COMPLETED.value, QueueStatus.CANCELED.value}]
        elif queue not in {"", "all"}:
            rows = [row for row in rows if row.get("status") == queue]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        rows = [
            row for row in rows
            if self._matches(row, search, ["project_id", "project_name", "status", "next_action_hint", "current_run_id", "last_run_state"])
        ]
        if sort == "recent":
            rows.sort(key=lambda row: _text(row.get("updated_at")), reverse=True)
        elif sort == "oldest":
            rows.sort(key=lambda row: _text(row.get("updated_at")))
        elif sort == "name":
            rows.sort(key=lambda row: (_text(row.get("project_name")).lower(), _text(row.get("updated_at"))))
        elif sort == "status":
            rows.sort(key=lambda row: (_text(row.get("status")), _text(row.get("updated_at"))), reverse=True)
        return self._page(rows, page_size, cursor)

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
        rows = self.paper_rows()
        if status:
            rows = [row for row in rows if row.get("paper_status") == status]
        if project_id:
            rows = [row for row in rows if row.get("project_id") == project_id]
        if run_id:
            rows = [row for row in rows if row.get("run_id") == run_id]
        rows = [row for row in rows if self._matches(row, search, ["paper_id", "project_id", "run_id", "paper_status", "project_name"])]
        if sort == "status":
            rows.sort(key=lambda row: (_text(row.get("paper_status")), _text(row.get("updated_at"))), reverse=True)
        elif sort == "title":
            rows.sort(key=lambda row: (_text(row.get("project_name")).lower(), _text(row.get("updated_at"))))
        else:
            rows.sort(key=lambda row: (_text(row.get("updated_at")), _text(row.get("paper_id"))), reverse=True)
        return self._page(rows, page_size, cursor)

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
        rows = self.run_rows()
        if state:
            rows = [row for row in rows if row.get("state") == state or row.get("gate_state") == state]
        if project_id:
            rows = [row for row in rows if row.get("project_id") == project_id]
        rows = [row for row in rows if self._matches(row, search, ["run_id", "project_id", "session_id", "current_activity"])]
        rows.sort(key=lambda row: (_text(row.get("updated_at")), _text(row.get("run_id"))), reverse=(sort != "oldest"))
        return self._page(rows, page_size, cursor)

    def event_page(
        self,
        *,
        entity_type: str = "",
        entity_id: str = "",
        event_type: str = "",
        search: str = "",
        page_size: int = 50,
        cursor: str = "",
        include_payload: bool = False,
        sort: str = "recent",
    ) -> tuple[list[dict[str, Any]], str | None, bool]:
        limit = max(1, min(page_size, 200)) + max(0, _int(cursor, 0)) + 1
        rows = self.recent_events(limit)
        if entity_type:
            rows = [row for row in rows if row.get("entity_type") == entity_type]
        if entity_id:
            rows = [row for row in rows if row.get("entity_id") == entity_id]
        if event_type:
            rows = [row for row in rows if row.get("event_type") == event_type]
        rows = [row for row in rows if self._matches(row, search, ["event_type", "entity_id"])]
        if not include_payload:
            for row in rows:
                payload_json = self._json_text(row.pop("payload", {}))
                row["payload_summary"] = {"keys": [], "bytes": len(payload_json.encode("utf-8"))}
        if sort == "oldest":
            rows.sort(key=lambda row: int(row.get("event_id") or 0))
        else:
            rows.sort(key=lambda row: int(row.get("event_id") or 0), reverse=True)
        return self._page(rows, page_size, cursor)

    def run_rows(self) -> list[dict[str, Any]]:
        return self._query("select * from runs order by updated_at desc, run_id desc")

    def status_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for row in self._query("select status, count(*) as count from queue_items group by status"):
            counts[_text(row["status"]) or "unknown"] = int(row["count"] or 0)
        return counts

    def recent_events(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = self._query("select * from control_events order by event_id desc limit %s", (max(0, limit),))
        out: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["payload"] = self._payload(item.pop("payload_json"))
            item.pop("payload_hash", None)
            out.append(item)
        return out

    def project_row(self, project_id: str) -> dict[str, Any] | None:
        return self._one("select * from projects where project_id = %s", (project_id,))

    def queue_row(self, project_id: str) -> dict[str, Any] | None:
        rows = self._queue_rows("where q.project_id = %s", (project_id,))
        return rows[0] if rows else None

    def run_row(self, run_id: str) -> dict[str, Any] | None:
        return self._one("select * from runs where run_id = %s", (run_id,))

    def paper_row(self, paper_id: str) -> dict[str, Any] | None:
        rows = self._paper_rows("where pa.paper_id = %s", (paper_id,))
        return rows[0] if rows else None

    def latest_dashboard_observation(
        self,
        *,
        source: str,
        scope: str = "global",
    ) -> DashboardObservationRecord | None:
        row = self._one(
            """
            select *
            from operator_observations
            where source = %s and scope = %s
            order by observed_at desc, observation_id desc
            limit 1
            """,
            (source, scope),
        )
        return self._observation_from_row(row) if row else None

    def latest_dashboard_observations(self, *, scope: str = "global") -> dict[str, DashboardObservationRecord]:
        rows = self._query(
            """
            select distinct on (source) *
            from operator_observations
            where scope = %s
            order by source, observed_at desc, observation_id desc
            """,
            (scope,),
        )
        return {row["source"]: self._observation_from_row(row) for row in rows}

    def _observation_from_row(self, row: dict[str, Any]) -> DashboardObservationRecord:
        return DashboardObservationRecord(
            observation_id=int(row["observation_id"]),
            source=row["source"],
            scope=row["scope"],
            observed_at=str(row["observed_at"]),
            ttl_seconds=int(row["ttl_seconds"]),
            status=row["status"],
            payload=self._payload(row["payload_json"]),
            payload_hash=row["payload_hash"],
            created_at=str(row["created_at"]),
        )

    def export_snapshot(self, *, event_limit: int = 50) -> dict[str, Any]:
        return {
            "source": "supabase_readonly_control_plane",
            "generated_at": utc_now(),
            "flags": self.flags().model_dump(mode="json"),
            "queue_rows": self.queue_rows(),
            "paper_rows": self.paper_rows(),
            "events": self.recent_events(event_limit),
        }


class SupabaseControlPlaneStore(SupabaseReadOnlyControlPlaneStore):
    """Write-capable Postgres adapter for the private `enoch` control-plane schema.

    This intentionally starts with the shared control-plane write primitives
    needed for migration cutover safety and dashboard parity. Unimplemented
    high-risk workflow writes remain absent rather than silently falling back to
    SQLite semantics.
    """

    def append_event(self, *, idempotency_key: str, event_type: str, entity_type: str, entity_id: str, payload: dict[str, Any]) -> tuple[int, bool]:
        payload_json = _json(payload)
        payload_hash = _hash(payload)
        with self._connect() as conn:
            with conn.cursor() as cur:
                row = cur.execute(
                    "select event_id, payload_hash from control_events where idempotency_key = %s",
                    (idempotency_key,),
                ).fetchone()
                if row:
                    if row["payload_hash"] != payload_hash:
                        raise IdempotencyConflict(f"idempotency key {idempotency_key!r} was reused with different payload")
                    return int(row["event_id"]), False
                inserted = cur.execute(
                    """
                    insert into control_events(idempotency_key,event_type,entity_type,entity_id,payload_json,payload_hash,created_at)
                    values (%s,%s,%s,%s,%s::jsonb,%s,%s)
                    returning event_id
                    """,
                    (idempotency_key, event_type, entity_type, entity_id, payload_json, payload_hash, utc_now()),
                ).fetchone()
                return int(inserted["event_id"]), True

    def pause(self, *, reason: str, paused_by: str, maintenance_mode: bool) -> tuple[ControlFlags, int]:
        now = utc_now()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    update control_flags
                    set queue_paused=true, maintenance_mode=%s, pause_reason=%s, paused_at=%s, paused_by=%s, updated_at=%s
                    where singleton=true
                    """,
                    (maintenance_mode, reason, now, paused_by, now),
                )
        flags = self.flags()
        event_id, _ = self.append_event(
            idempotency_key=f"pause:{now}",
            event_type="control.pause",
            entity_type="control",
            entity_id="queue",
            payload=flags.model_dump(mode="json"),
        )
        return flags, event_id

    def resume(self, *, resumed_by: str, maintenance_mode: bool) -> tuple[ControlFlags, int]:
        now = utc_now()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    update control_flags
                    set queue_paused=false, maintenance_mode=%s, pause_reason='', paused_at=null, paused_by=%s, updated_at=%s
                    where singleton=true
                    """,
                    (maintenance_mode, resumed_by, now),
                )
        flags = self.flags()
        event_id, _ = self.append_event(
            idempotency_key=f"resume:{now}",
            event_type="control.resume",
            entity_type="control",
            entity_id="queue",
            payload=flags.model_dump(mode="json"),
        )
        return flags, event_id

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
        observed = observed_at or now
        with self._connect() as conn:
            with conn.cursor() as cur:
                row = cur.execute(
                    """
                    insert into operator_observations(source,scope,observed_at,ttl_seconds,status,payload_json,payload_hash,created_at)
                    values (%s,%s,%s,%s,%s,%s::jsonb,%s,%s)
                    returning observation_id
                    """,
                    (source, scope, observed, ttl_seconds, status, payload_json, payload_hash, now),
                ).fetchone()
        return DashboardObservationRecord(
            observation_id=int(row["observation_id"]),
            source=source,
            scope=scope,
            observed_at=observed,
            ttl_seconds=ttl_seconds,
            status=status,
            payload=payload_dict,
            payload_hash=payload_hash,
            created_at=now,
        )

    def dispatch_next_dry_run(self, *, requested_by: str) -> tuple[str, dict[str, Any] | None, int | None, str]:
        flags = self.flags()
        if flags.queue_paused:
            event_id, _ = self.append_event(
                idempotency_key=f"dispatch-paused:{utc_now()}",
                event_type="controller.dispatch_paused",
                entity_type="control",
                entity_id="queue",
                payload={"requested_by": requested_by, "flags": flags.model_dump(mode="json")},
            )
            return "paused", None, event_id, flags.pause_reason or "queue paused"
        active = self.active_items()
        if active:
            return "noop", None, None, "active GB10 lane already exists"
        candidate = self.next_dispatch_candidate()
        if not candidate:
            return "noop", None, None, "no queued candidate"
        event_id, _ = self.append_event(
            idempotency_key=f"dry-dispatch:{candidate['project_id']}:{utc_now()}",
            event_type="controller.dry_run_dispatch",
            entity_type="project",
            entity_id=candidate["project_id"],
            payload={"requested_by": requested_by, "candidate": candidate},
        )
        return "dry_run_dispatch", candidate, event_id, "dry-run dispatch selected candidate"

    def _paper_review_join_rows(self) -> list[dict[str, Any]]:
        return self._query(
            """
            select
              pa.*,
              p.project_name,
              p.project_dir,
              p.notion_page_url,
              p.notion_page_id,
              q.status as queue_status,
              q.manual_review_required,
              q.blocked_reason,
              q.next_action_hint,
              rv.automation_status as review_status,
              rv.automation_actor as reviewer,
              rv.blocker,
              rv.claimed_at,
              rv.checklist_json,
              rv.rank_score,
              rv.rank_reasons_json,
              rv.missing_signals_json,
              rv.rank_tiebreaker,
              rv.source_audit_path,
              rv.finalization_package_path,
              rv.finalized_at,
              rv.decision_summary,
              rv.created_at as review_created_at,
              rv.updated_at as review_updated_at
            from publication_automation_items rv
            join papers pa using(paper_id)
            left join projects p using(project_id)
            left join queue_items q using(project_id)
            order by rv.rank_score desc, pa.updated_at desc, pa.paper_id asc
            """
        )

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

    def _raw_paper_review_row(self, paper_id: str) -> dict[str, Any] | None:
        return self._one("select * from publication_automation_items where paper_id = %s", (paper_id,))

    def _require_paper_review(self, paper_id: str) -> dict[str, Any]:
        row = self._raw_paper_review_row(paper_id)
        if row is None:
            raise ValueError("paper review not found")
        return row

    def paper_review_checklist(self, paper_id: str) -> dict[str, Any]:
        row = self._raw_paper_review_row(paper_id)
        return _normalize_review_checklist(_json_dict(row.get("checklist_json")) if row else {})

    def _mutation_payload(self, request: Any, *, action: str) -> dict[str, Any]:
        payload = request.model_dump(mode="json")
        payload["action"] = action
        return payload

    def backfill_paper_reviews(self, request: PaperReviewBackfillRequest) -> tuple[bool, int, int, int, list[dict[str, Any]]]:
        audit_by_paper = _audit_rows(request.source_audit_path)
        requested_paper_ids = {_text(paper_id) for paper_id in request.paper_ids if _text(paper_id)}
        papers = [paper for paper in self.paper_rows() if not requested_paper_ids or _text(paper.get("paper_id")) in requested_paper_ids]
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
            with conn.cursor() as cur:
                for record in candidates:
                    existing = cur.execute("select * from publication_automation_items where paper_id = %s", (record.paper_id,)).fetchone()
                    rank_reasons_json = _json(record.rank_reasons)
                    missing_signals_json = _json(record.missing_signals)
                    if existing:
                        existing_status = _text(existing["automation_status"])
                        next_status = record.review_status.value if existing_status in {ReviewStatus.UNREVIEWED.value, ReviewStatus.TRIAGE_READY.value} else existing_status
                        changes = {
                            "automation_status": next_status,
                            "rank_score": record.rank_score,
                            "rank_reasons_json": rank_reasons_json,
                            "missing_signals_json": missing_signals_json,
                            "rank_tiebreaker": record.rank_tiebreaker,
                            "source_audit_path": record.source_audit_path,
                        }
                        if all(str(existing[key]) == str(value) for key, value in changes.items()):
                            skipped += 1
                            continue
                        cur.execute(
                            """
                            update publication_automation_items
                            set automation_status=%s, rank_score=%s, rank_reasons_json=%s::jsonb, missing_signals_json=%s::jsonb,
                                rank_tiebreaker=%s, source_audit_path=%s, updated_at=%s
                            where paper_id=%s
                            """,
                            (next_status, record.rank_score, rank_reasons_json, missing_signals_json, record.rank_tiebreaker, record.source_audit_path, now, record.paper_id),
                        )
                        updated += 1
                        continue
                    cur.execute(
                        """
                        insert into publication_automation_items(paper_id,automation_status,automation_actor,blocker,claimed_at,checklist_json,rank_score,rank_reasons_json,missing_signals_json,rank_tiebreaker,source_audit_path,finalization_package_path,finalized_at,decision_summary,created_at,updated_at)
                        values (%s,%s,%s,%s,%s,%s::jsonb,%s,%s::jsonb,%s::jsonb,%s,%s,%s,%s,%s,%s,%s)
                        """,
                        (record.paper_id, record.review_status.value, record.reviewer, record.blocker, None, _json(_normalize_review_checklist(record.checklist_json)), record.rank_score, rank_reasons_json, missing_signals_json, record.rank_tiebreaker, record.source_audit_path, record.finalization_package_path, None, record.decision_summary, now, now),
                    )
                    created += 1
        return inserted, created, updated, skipped, errors

    def claim_paper_review(self, paper_id: str, request: PaperReviewClaimRequest) -> tuple[int, bool, dict[str, Any]]:
        if not _text(request.reviewer):
            raise ValueError("reviewer is required")
        row = self._require_paper_review(paper_id)
        current = _text(row.get("automation_status"))
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
                with conn.cursor() as cur:
                    cur.execute(
                        "update publication_automation_items set automation_status=%s, automation_actor=%s, blocker=%s, claimed_at=%s, checklist_json=%s::jsonb, updated_at=%s where paper_id=%s",
                        (ReviewStatus.IN_REVIEW.value, _text(request.reviewer), "" if request.clear_blocker else _text(row.get("blocker")), now, _json(checklist), now, paper_id),
                    )
        return event_id, inserted, self.paper_review_row(paper_id) or {}

    def update_paper_review_status(self, paper_id: str, request: PaperReviewStatusUpdateRequest) -> tuple[int, bool, dict[str, Any]]:
        row = self._require_paper_review(paper_id)
        current = _text(row.get("automation_status"))
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
                with conn.cursor() as cur:
                    cur.execute("update publication_automation_items set automation_status=%s, blocker=%s, decision_summary=%s, updated_at=%s where paper_id=%s", (target, next_blocker, decision_summary, now, paper_id))
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
            raise ValueError("automated finalization approval must be pass or fail/pending")
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
                with conn.cursor() as cur:
                    cur.execute("update publication_automation_items set checklist_json=%s::jsonb, updated_at=%s where paper_id=%s", (_json(checklist), now, paper_id))
        return event_id, inserted, self.paper_review_row(paper_id) or {}

    def approve_paper_review_finalization(self, paper_id: str, request: PaperReviewApproveFinalizationRequest) -> tuple[int, bool, dict[str, Any]]:
        row = self._require_paper_review(paper_id)
        payload = self._mutation_payload(request, action="approve_finalization")
        payload.update({"to_status": ReviewStatus.APPROVED_FOR_FINALIZATION.value})
        replayed_event_id = self._replayed_event_id(request.idempotency_key, payload)
        if replayed_event_id is not None:
            return replayed_event_id, False, self.paper_review_row(paper_id) or {}
        current = _text(row.get("automation_status"))
        if current != ReviewStatus.IN_REVIEW.value:
            raise ValueError("approval requires review_status=in_review")
        checklist = _normalize_review_checklist(_json_dict(row.get("checklist_json")))
        blockers: list[str] = []
        for item in checklist["items"]:
            if not item.get("required"):
                continue
            status = _text(item.get("status"))
            if item["id"] == "final_human_approval" and status != "pass":
                blockers.append("automated finalization approval must pass")
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
                with conn.cursor() as cur:
                    cur.execute("update publication_automation_items set automation_status=%s, decision_summary=%s, updated_at=%s where paper_id=%s", (ReviewStatus.APPROVED_FOR_FINALIZATION.value, decision_summary, now, paper_id))
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
        root = Path(os.environ.get("ENOCH_SUPABASE_FINALIZATION_ROOT", "/tmp/enoch-supabase-finalization-packages")).expanduser()
        return root / _slug_id(paper_id) / _slug_id(idempotency_key) / "finalization_manifest.json"

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
        current = _text(row.get("automation_status"))
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
            "reviewer": _text(row.get("automation_actor")),
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
                with conn.cursor() as cur:
                    cur.execute(
                        "update publication_automation_items set automation_status=%s, finalization_package_path=%s, finalized_at=%s, updated_at=%s where paper_id=%s",
                        (ReviewStatus.FINALIZED.value, str(package_path), now, now, paper_id),
                    )
        item = self.paper_review_row(paper_id) or {}
        return event_id, inserted, item, str(package_path), manifest

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
            rank = _priority_rank(raw)
            candidates.append({
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
            with conn.cursor() as cur:
                for candidate in candidates:
                    existed = cur.execute("select 1 from queue_items where project_id = %s", (candidate["project_id"],)).fetchone() is not None
                    cur.execute(
                        """
                        insert into projects(project_id,project_name,project_dir,notion_page_url,notion_page_id,origin_idea_status,created_at,updated_at)
                        values (%s,%s,%s,%s,%s,%s,%s,%s)
                        on conflict (project_id) do update set
                          project_name=excluded.project_name, project_dir=excluded.project_dir, notion_page_url=excluded.notion_page_url,
                          notion_page_id=excluded.notion_page_id, origin_idea_status=excluded.origin_idea_status, updated_at=excluded.updated_at
                        """,
                        (candidate["project_id"], candidate["project_name"], candidate["project_dir"], candidate["notion_page_url"], candidate["notion_page_id"], candidate["origin_idea_status"], now, now),
                    )
                    if existed:
                        if request.override_existing_dispatch_metadata:
                            cur.execute(
                                """
                                update queue_items
                                set selection_rank=%s, dispatch_priority=%s, machine_target=%s, model=%s, sandbox=%s, updated_at=%s
                                where project_id=%s and status not in ('dispatching','running','awaiting_wake','wake_received','reconciling')
                                """,
                                (candidate["selection_rank"], candidate["dispatch_priority"], candidate["machine_target"], candidate["model"], candidate["sandbox"], now, candidate["project_id"]),
                            )
                        else:
                            cur.execute(
                                """
                                update queue_items
                                set selection_rank=%s, dispatch_priority=%s, updated_at=%s
                                where project_id=%s and status not in ('dispatching','running','awaiting_wake','wake_received','reconciling')
                                """,
                                (candidate["selection_rank"], candidate["dispatch_priority"], now, candidate["project_id"]),
                            )
                        updated += 1
                    else:
                        cur.execute(
                            """
                            insert into queue_items(project_id,status,selection_rank,dispatch_priority,auto_continue,continue_count,max_continues,retry_count,max_retries,current_run_id,current_session_id,last_run_state,last_event_type,next_action_hint,manual_review_required,blocked_reason,last_error,last_result_summary,machine_target,model,sandbox,last_dispatch_at,last_callback_at,stale_after,updated_at)
                            values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                            """,
                            (
                                candidate["project_id"], QueueStatus.QUEUED.value, candidate["selection_rank"], candidate["dispatch_priority"],
                                True, 0, 0, 0, 2, "", "", "", "", candidate["next_action_hint"], False, "", "", "",
                                candidate["machine_target"], candidate["model"], candidate["sandbox"], None, None, None, now,
                            ),
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
            merged = {**row, "paper_id": paper.get("paper_id") or "", "paper_status": paper.get("paper_status") or "", "paper_type": paper.get("paper_type") or "", "draft_markdown_path": paper.get("draft_markdown_path") or "", "paper_updated_at": paper.get("updated_at") or ""}
            page_url = merged.get("notion_page_url") or ""
            if not page_url:
                continue
            execution_state = state_map.get(merged.get("status") or "", "blocked")
            blocked_reason = merged.get("blocked_reason") or (merged.get("last_result_summary") if execution_state in {"blocked", "failed"} else "") or ""
            rows.append({
                "project_id": merged.get("project_id") or "",
                "page_id": merged.get("notion_page_id") or _notion_page_id_from_url(page_url),
                "notion_page_url": page_url,
                "properties": {
                    "Execution State": execution_state,
                    "Current Run ID": merged.get("current_run_id") or "",
                    "Next Action": merged.get("next_action_hint") or "",
                    "Blocked Reason": blocked_reason,
                    "Last Execution Update": merged.get("updated_at") or utc_now(),
                    "Execution Summary": merged.get("last_result_summary") or "",
                    "OMX Project ID": merged.get("project_id") or "",
                    "OMX Queue Status": merged.get("status") or "",
                    "OMX Last Run State": merged.get("last_run_state") or "",
                    "OMX Last Event Type": merged.get("last_event_type") or "",
                    "OMX Next Action Hint": merged.get("next_action_hint") or "",
                    "OMX Project Dir": merged.get("project_dir") or "",
                    "OMX Current Session ID": merged.get("current_session_id") or "",
                    "OMX Last Result Summary": merged.get("last_result_summary") or "",
                    "OMX Last Error": merged.get("last_error") or "",
                    "OMX Manual Review Required": "__YES__" if merged.get("manual_review_required") else "__NO__",
                    "OMX Dispatch Priority": merged.get("dispatch_priority") or 0,
                    "OMX Selection Rank": merged.get("selection_rank") or 0,
                    "OMX Paper ID": merged.get("paper_id") or "",
                    "OMX Paper Status": merged.get("paper_status") or "",
                    "OMX Paper Type": merged.get("paper_type") or "",
                    "OMX Paper Markdown Path": merged.get("draft_markdown_path") or "",
                    "OMX Paper Updated At": merged.get("paper_updated_at") or "",
                    "OMX Paper Updated At ISO": merged.get("paper_updated_at") or "",
                },
            })
        return rows

    def queue_notion_projection(self) -> list[dict[str, Any]]:
        return [{
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
        } for row in self.queue_rows()]

    def paper_notion_projection(self) -> list[dict[str, Any]]:
        return [{
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
        } for paper in self.paper_rows()]

    def _replayed_event_id(self, idempotency_key: str, payload: dict[str, Any]) -> int | None:
        payload_hash = _hash(payload)
        row = self._one(
            "select event_id, payload_hash from control_events where idempotency_key = %s",
            (idempotency_key,),
        )
        if row is None:
            return None
        if row["payload_hash"] != payload_hash:
            raise IdempotencyConflict(f"idempotency key {idempotency_key!r} was reused with different payload")
        return int(row["event_id"])

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
            with conn.cursor() as cur:
                cur.execute(
                    """
                    update queue_items
                    set status=%s, current_run_id=%s, current_session_id=%s, last_run_state=%s,
                        last_event_type=%s, next_action_hint=%s, last_error=%s, last_result_summary=%s,
                        last_dispatch_at=%s, updated_at=%s
                    where project_id=%s
                    """,
                    (
                        QueueStatus.AWAITING_WAKE.value, run_id, session_id, "dispatch_accepted",
                        "live_dispatch", "await_callback", "", "", now, now, project_id,
                    ),
                )
                cur.execute(
                    """
                    insert into runs(run_id,project_id,session_id,state,dispatch_mode,started_at,ended_at,last_callback_at,gate_state,current_activity,idempotency_key,updated_at)
                    values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    on conflict (run_id) do update set
                      project_id=excluded.project_id, session_id=excluded.session_id, state=excluded.state,
                      dispatch_mode=excluded.dispatch_mode, started_at=excluded.started_at, ended_at=excluded.ended_at,
                      last_callback_at=excluded.last_callback_at, gate_state=excluded.gate_state,
                      current_activity=excluded.current_activity, idempotency_key=excluded.idempotency_key, updated_at=excluded.updated_at
                    """,
                    (run_id, project_id, session_id, "running", "exec", now, None, None, "running", "dispatched", f"live-dispatch:{run_id}", now),
                )
        event_id, _ = self.append_event(
            idempotency_key=f"live-dispatch:{run_id}",
            event_type="controller.live_dispatch",
            entity_type="project",
            entity_id=project_id,
            payload={"requested_by": requested_by, "run_id": run_id, "session_id": session_id, "dispatch": dispatch_payload},
        )
        return event_id, self.queue_row(project_id) or {}

    def record_worker_callback(self, callback: Any, *, received_by: str = "worker-callback") -> tuple[int, bool, dict[str, Any]]:
        now = utc_now()
        payload = callback.model_dump(mode="json") if hasattr(callback, "model_dump") else dict(callback)
        run_id = _text(payload.get("run_id"))
        project_id = _text(payload.get("project_id"))
        event_type = _text(payload.get("event_type"))
        idempotency_key = _text(payload.get("idempotency_key")) or f"worker-callback:{run_id}:{event_type}:{now}"
        if not project_id and run_id:
            row = self._one("select project_id from runs where run_id = %s", (run_id,))
            project_id = _text(row.get("project_id") if row else "")
        status = QueueStatus.COMPLETED.value
        next_action_hint = "select_next_project"
        manual_review_required = False
        last_error = ""
        if event_type == "session_started":
            status = QueueStatus.RUNNING.value
            next_action_hint = "await_callback"
        elif event_type == "question_pending":
            status = QueueStatus.NEEDS_REVIEW.value
            next_action_hint = "answer_worker_question"
            manual_review_required = True
        elif event_type in {"gate_timeout", "gate_error"}:
            status = QueueStatus.BLOCKED.value
            next_action_hint = "inspect_worker_gate_failure"
            manual_review_required = True
            last_error = _text(payload.get("reason")) or event_type
        elif event_type in {"wake_ready", "session_finished_ready"}:
            next_action_hint = "draft_paper_or_select_next_project"
        else:
            status = QueueStatus.NEEDS_REVIEW.value
            next_action_hint = "inspect_unknown_worker_callback"
            manual_review_required = True
            last_error = _text(payload.get("reason")) or f"unknown worker callback: {event_type}"
        event_payload = {
            **payload,
            "received_by": received_by,
            "applied_status": status,
            "applied_next_action_hint": next_action_hint,
        }
        replayed_event_id = self._replayed_event_id(idempotency_key, event_payload)
        if replayed_event_id is not None:
            return replayed_event_id, False, self.queue_row(project_id) or {}
        summary = f"worker callback {event_type}: {_text(payload.get('reason')) or 'worker reported ready'}"
        run_state = RunState.RUNNING.value if event_type == "session_started" else event_type
        run_ended_at = None if event_type == "session_started" else now
        with self._connect() as conn:
            with conn.cursor() as cur:
                if project_id:
                    cur.execute(
                        """
                        update queue_items
                        set status=%s, current_session_id=coalesce(nullif(%s, ''), current_session_id), last_run_state=%s,
                            last_event_type=%s, next_action_hint=%s, manual_review_required=%s, last_error=%s,
                            last_result_summary=%s, last_callback_at=%s, updated_at=%s
                        where project_id=%s
                        """,
                        (status, _text(payload.get("session_id")), event_type, "worker_callback", next_action_hint, manual_review_required, last_error, summary, now, now, project_id),
                    )
                if run_id:
                    cur.execute(
                        """
                        update runs
                        set session_id=coalesce(nullif(%s, ''), session_id), state=%s, ended_at=%s, last_callback_at=%s,
                            gate_state=%s, current_activity=%s, updated_at=%s
                        where run_id=%s
                        """,
                        (_text(payload.get("session_id")), run_state, run_ended_at, now, _text(payload.get("gate_state")) or event_type, "worker_callback", now, run_id),
                    )
        event_id, inserted = self.append_event(
            idempotency_key=idempotency_key,
            event_type=f"worker_callback.{event_type}",
            entity_type="run",
            entity_id=run_id or project_id or "unknown",
            payload=event_payload,
        )
        return event_id, inserted, self.queue_row(project_id) or {}

    def mark_queue_item_paused(self, *, project_id: str, reason: str, updated_by: str = "operator") -> bool:
        now = utc_now()
        with self._connect() as conn:
            with conn.cursor() as cur:
                result = cur.execute(
                    """
                    update queue_items
                    set status=%s, next_action_hint=%s, last_result_summary=%s, updated_at=%s
                    where project_id=%s
                    """,
                    (QueueStatus.PAUSED.value, "maintenance_cutover_reconcile", reason, now, project_id),
                )
                if result.rowcount < 1:
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
            with conn.cursor() as cur:
                cur.execute(
                    "update projects set project_dir=%s, updated_at=%s where project_id=%s",
                    (_text(project_dir), now, project_id),
                )

    def upsert_paper(self, paper: PaperRecord) -> None:
        status = paper.paper_status.value if hasattr(paper.paper_status, "value") else str(paper.paper_status)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    insert into papers(paper_id,project_id,run_id,paper_type,paper_status,draft_markdown_path,draft_latex_path,evidence_bundle_path,claim_ledger_path,manifest_path,generated_at,updated_at)
                    values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    on conflict (paper_id) do update set
                      project_id=excluded.project_id, run_id=excluded.run_id, paper_type=excluded.paper_type,
                      paper_status=excluded.paper_status, draft_markdown_path=excluded.draft_markdown_path,
                      draft_latex_path=excluded.draft_latex_path, evidence_bundle_path=excluded.evidence_bundle_path,
                      claim_ledger_path=excluded.claim_ledger_path, manifest_path=excluded.manifest_path,
                      generated_at=excluded.generated_at, updated_at=excluded.updated_at
                    """,
                    (
                        paper.paper_id, paper.project_id, _text(paper.run_id) or None, paper.paper_type, status,
                        paper.draft_markdown_path, paper.draft_latex_path, paper.evidence_bundle_path,
                        paper.claim_ledger_path, paper.manifest_path, paper.generated_at, paper.updated_at,
                    ),
                )

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
            with conn.cursor() as cur:
                for raw in queue_rows:
                    project_id = _text(raw.get("project_id"))
                    if not project_id:
                        continue
                    status_value = _text(_first_present(raw, "status", "queue_status")) or QueueStatus.QUEUED.value
                    if status_value not in QueueStatus._value2member_map_:
                        status_value = QueueStatus.QUEUED.value
                    created_at = _text(_first_present(raw, "createdAt", "created_at")) or utc_now()
                    updated_at = _text(_first_present(raw, "updatedAt", "updated_at", "last_execution_update")) or utc_now()
                    cur.execute(
                        """
                        insert into projects(project_id,project_name,project_dir,notion_page_url,notion_page_id,origin_idea_status,created_at,updated_at)
                        values (%s,%s,%s,%s,%s,%s,%s,%s)
                        on conflict (project_id) do update set
                          project_name=excluded.project_name, project_dir=excluded.project_dir,
                          notion_page_url=excluded.notion_page_url, notion_page_id=excluded.notion_page_id,
                          origin_idea_status=excluded.origin_idea_status, updated_at=excluded.updated_at
                        """,
                        (
                            project_id,
                            _text(_first_present(raw, "project_name", "name", "title")) or project_id,
                            _text(_first_present(raw, "project_dir", "project_path")),
                            _text(_first_present(raw, "notion_page_url", "url")),
                            _text(_first_present(raw, "notion_page_id", "page_id", "id"))
                            or _notion_page_id_from_url(_text(_first_present(raw, "notion_page_url", "url"))),
                            _text(_first_present(raw, "origin_idea_status", "idea_status")),
                            created_at,
                            updated_at,
                        ),
                    )
                    projects += 1
                    cur.execute(
                        """
                        insert into queue_items(project_id,status,selection_rank,dispatch_priority,auto_continue,continue_count,max_continues,retry_count,max_retries,current_run_id,current_session_id,last_run_state,last_event_type,next_action_hint,manual_review_required,blocked_reason,last_error,last_result_summary,machine_target,model,sandbox,last_dispatch_at,last_callback_at,stale_after,updated_at)
                        values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        on conflict (project_id) do update set
                          status=excluded.status, selection_rank=excluded.selection_rank, dispatch_priority=excluded.dispatch_priority,
                          auto_continue=excluded.auto_continue, continue_count=excluded.continue_count, max_continues=excluded.max_continues,
                          retry_count=excluded.retry_count, max_retries=excluded.max_retries, current_run_id=excluded.current_run_id,
                          current_session_id=excluded.current_session_id, last_run_state=excluded.last_run_state, last_event_type=excluded.last_event_type,
                          next_action_hint=excluded.next_action_hint, manual_review_required=excluded.manual_review_required, blocked_reason=excluded.blocked_reason,
                          last_error=excluded.last_error, last_result_summary=excluded.last_result_summary, machine_target=excluded.machine_target,
                          model=excluded.model, sandbox=excluded.sandbox, last_dispatch_at=excluded.last_dispatch_at,
                          last_callback_at=excluded.last_callback_at, stale_after=excluded.stale_after, updated_at=excluded.updated_at
                        """,
                        (
                            project_id, status_value, _int(_first_present(raw, "selection_rank", "rank"), 50),
                            _int(_first_present(raw, "dispatch_priority", "priority"), 50),
                            _bool(_first_present(raw, "auto_continue", "autoContinue")),
                            _int(_first_present(raw, "continue_count", "continueCount"), 0),
                            _int(_first_present(raw, "max_continues", "maxContinues"), 0),
                            _int(_first_present(raw, "retry_count", "retryCount"), 0),
                            _int(_first_present(raw, "max_retries", "maxRetries"), 2),
                            _text(raw.get("current_run_id")), _text(raw.get("current_session_id")),
                            _text(raw.get("last_run_state")), _text(raw.get("last_event_type")),
                            _text(raw.get("next_action_hint")) or "controller_review", _bool(raw.get("manual_review_required")),
                            _text(raw.get("blocked_reason")), _text(raw.get("last_error")), _text(raw.get("last_result_summary")),
                            _text(raw.get("machine_target")) or "worker.example", _text(raw.get("model")) or "gpt-5.5",
                            _text(raw.get("sandbox")) or "danger-full-access", _first_present(raw, "last_dispatch_at", "last_execution_update"),
                            raw.get("last_callback_at"), raw.get("stale_after"), updated_at,
                        ),
                    )
                    queue_items += 1
                for raw in paper_rows:
                    paper_id = _text(raw.get("paper_id"))
                    project_id = _text(raw.get("project_id"))
                    if not paper_id or not project_id:
                        continue
                    cur.execute(
                        """
                        insert into projects(project_id,project_name,project_dir,notion_page_url,notion_page_id,origin_idea_status,created_at,updated_at)
                        values (%s,%s,%s,%s,%s,%s,%s,%s)
                        on conflict (project_id) do nothing
                        """,
                        (
                            project_id, _text(raw.get("project_name")) or project_id, _text(raw.get("project_dir")),
                            _text(raw.get("notion_page_url")),
                            _text(raw.get("notion_page_id")) or _notion_page_id_from_url(_text(raw.get("notion_page_url"))),
                            "", utc_now(), utc_now(),
                        ),
                    )
                    status = _text(raw.get("paper_status")) or PaperStatus.DRAFT_REVIEW.value
                    if status not in PaperStatus._value2member_map_:
                        status = PaperStatus.DRAFT_REVIEW.value
                    cur.execute(
                        """
                        insert into papers(paper_id,project_id,run_id,paper_type,paper_status,draft_markdown_path,draft_latex_path,evidence_bundle_path,claim_ledger_path,manifest_path,generated_at,updated_at)
                        values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        on conflict (paper_id) do update set
                          project_id=excluded.project_id, run_id=excluded.run_id, paper_type=excluded.paper_type,
                          paper_status=excluded.paper_status, draft_markdown_path=excluded.draft_markdown_path,
                          draft_latex_path=excluded.draft_latex_path, evidence_bundle_path=excluded.evidence_bundle_path,
                          claim_ledger_path=excluded.claim_ledger_path, manifest_path=excluded.manifest_path,
                          generated_at=excluded.generated_at, updated_at=excluded.updated_at
                        """,
                        (
                            paper_id, project_id, _text(raw.get("run_id")) or None, _text(raw.get("paper_type")) or "arxiv_draft", status,
                            _text(raw.get("draft_markdown_path")), _text(raw.get("draft_latex_path")),
                            _text(raw.get("evidence_bundle_path")), _text(raw.get("claim_ledger_path")),
                            _text(raw.get("manifest_path")), _text(raw.get("generated_at")) or utc_now(),
                            _text(raw.get("updated_at")) or utc_now(),
                        ),
                    )
                    papers += 1
        return inserted, projects, queue_items, papers


def resolve_supabase_database_url(configured_url: str) -> str:
    return configured_url.strip() or os.environ.get("ENOCH_SUPABASE_DATABASE_URL", "").strip()
