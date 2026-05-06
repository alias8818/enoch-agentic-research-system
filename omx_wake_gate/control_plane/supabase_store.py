from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from typing import Any

from ..models import utc_now
from .models import ControlFlags, DashboardObservationRecord
from .store import ACTIVE_STATUSES, QueueStatus, _int, _text


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
            raise ValueError("supabase_database_url is required for supabase_readonly backend")
        self._connect_factory = connect or self._psycopg_connect

    def _psycopg_connect(self) -> Any:
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:  # pragma: no cover - dependency is declared in pyproject.
            raise RuntimeError("psycopg is required for the Supabase control-plane adapter") from exc
        return psycopg.connect(self.database_url, row_factory=dict_row)

    @contextmanager
    def _connect(self) -> Iterator[Any]:
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
            if status == QueueStatus.QUEUED.value:
                counts["queued"] = counts.get("queued", 0) + count
            if status == QueueStatus.PAUSED.value:
                counts["paused"] = counts.get("paused", 0) + count
            if status in {QueueStatus.COMPLETED.value, QueueStatus.CANCELED.value}:
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

    def next_candidate_sql(self) -> dict[str, Any] | None:
        rows = self._queue_rows(
            "where q.status = %s order by q.dispatch_priority asc, q.updated_at desc limit 1",
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


def resolve_supabase_database_url(configured_url: str) -> str:
    return configured_url.strip() or os.environ.get("ENOCH_SUPABASE_DATABASE_URL", "").strip()
