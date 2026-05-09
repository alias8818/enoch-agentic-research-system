from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from typing import Any

from ..models import utc_now
from .store import AppendResult, IdempotencyConflict

ConnectionFactory = Callable[[], Any]


class SupabaseEnochCoreStore:
    """Postgres/Supabase implementation of the Enoch core shadow store.

    The public `/enoch-core/*` API remains proposal-only; this store only moves
    its shadow snapshots/events off local SQLite and into the private `enoch`
    Supabase schema so there is not a second local runtime database after the
    Supabase cutover.
    """

    def __init__(self, database_url: str, *, connect: ConnectionFactory | None = None) -> None:
        self.database_url = database_url.strip()
        if not self.database_url:
            raise ValueError("supabase_database_url is required for the Supabase Enoch core store")
        self._connect_factory = connect or self._psycopg_connect
        self._external_connect_factory = connect is not None

    def _psycopg_connect(self) -> Any:
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:  # pragma: no cover - dependency is declared in pyproject.
            raise RuntimeError("psycopg is required for the Supabase Enoch core store") from exc
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

        conn = self._connect_factory()
        try:
            with conn.cursor() as cur:
                cur.execute("set statement_timeout to '45s'")
                cur.execute("set idle_in_transaction_session_timeout to '30s'")
                cur.execute("set search_path to enoch, public")
            yield conn
            conn.commit()
        except Exception:
            rollback = getattr(conn, "rollback", None)
            if callable(rollback):
                rollback()
            raise
        finally:
            close = getattr(conn, "close", None)
            if callable(close):
                close()

    @staticmethod
    def canonical_json(payload: Any) -> str:
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    @classmethod
    def payload_hash(cls, payload: Any) -> str:
        return hashlib.sha256(cls.canonical_json(payload).encode("utf-8")).hexdigest()

    @staticmethod
    def _json_payload(value: Any) -> Any:
        if value is None:
            return {}
        if isinstance(value, str):
            return json.loads(value or "{}")
        return value

    def _query(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, tuple(params))
                rows = cur.fetchall()
        return [dict(row) for row in rows]

    def append_event(
        self,
        *,
        idempotency_key: str,
        event_type: str,
        source: str,
        payload: dict[str, Any],
    ) -> AppendResult:
        payload_json = self.canonical_json(payload)
        payload_hash = self.payload_hash(payload)
        with self._connect() as conn:
            with conn.cursor() as cur:
                existing = cur.execute(
                    "select id, payload_hash from core_events where idempotency_key = %s",
                    (idempotency_key,),
                ).fetchone()
                if existing is not None:
                    if existing["payload_hash"] != payload_hash:
                        raise IdempotencyConflict(
                            f"idempotency key {idempotency_key!r} was reused with different payload"
                        )
                    return AppendResult(event_id=int(existing["id"]), inserted=False)
                row = cur.execute(
                    """
                    insert into core_events(idempotency_key, event_type, source, payload_json, payload_hash, created_at)
                    values (%s, %s, %s, %s::jsonb, %s, %s)
                    returning id
                    """,
                    (idempotency_key, event_type, source, payload_json, payload_hash, utc_now()),
                ).fetchone()
                return AppendResult(event_id=int(row["id"]), inserted=True)

    def save_queue_snapshot(self, payload: dict[str, Any]) -> tuple[AppendResult, int]:
        key = str(payload["idempotency_key"])
        event = self.append_event(
            idempotency_key=key,
            event_type="n8n.queue_snapshot",
            source=str(payload.get("source") or "n8n"),
            payload=payload,
        )
        payload_json = self.canonical_json(payload)
        with self._connect() as conn:
            with conn.cursor() as cur:
                existing = cur.execute(
                    "select id from core_snapshots where idempotency_key = %s",
                    (key,),
                ).fetchone()
                if existing is not None:
                    return event, int(existing["id"])
                row = cur.execute(
                    """
                    insert into core_snapshots(idempotency_key, snapshot_type, event_id, source, payload_json, created_at)
                    values (%s, %s, %s, %s, %s::jsonb, %s)
                    returning id
                    """,
                    (key, "n8n_queue", event.event_id, str(payload.get("source") or "n8n"), payload_json, utc_now()),
                ).fetchone()
                return event, int(row["id"])

    def latest_snapshot(self, snapshot_type: str = "n8n_queue") -> dict[str, Any] | None:
        rows = self._query(
            """
            select payload_json from core_snapshots
            where snapshot_type = %s
            order by id desc
            limit 1
            """,
            (snapshot_type,),
        )
        if not rows:
            return None
        return self._json_payload(rows[0]["payload_json"])

    def all_snapshots(self, snapshot_type: str = "n8n_queue") -> list[dict[str, Any]]:
        rows = self._query(
            "select payload_json from core_snapshots where snapshot_type = %s order by id asc",
            (snapshot_type,),
        )
        return [self._json_payload(row["payload_json"]) for row in rows]

    def rebuild_queue_projection(self) -> dict[str, Any]:
        return self.latest_snapshot("n8n_queue") or {
            "source": "none",
            "queue_rows": [],
            "paper_rows": [],
            "captured_at": None,
        }
