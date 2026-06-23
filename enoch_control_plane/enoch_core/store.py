from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Generator

from ..models import utc_now
from ._canonical import canonical_json as _canonical_json

SCHEMA_VERSION = 1


class IdempotencyConflict(ValueError):
    """Raised when a key is reused with a different canonical payload."""


@dataclass(frozen=True)
class AppendResult:
    event_id: int
    inserted: bool


class EnochCoreStore:
    """SQLite append-only store for shadow protocol events and snapshots."""

    def __init__(self, path: Path) -> None:
        self.path = path.expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._writer_lock = threading.RLock()
        self._writer_conn: sqlite3.Connection | None = None
        self._init_db()

    @staticmethod
    def _configure_connection(conn: sqlite3.Connection) -> None:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")

    @contextmanager
    def _connect(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(self.path)
        self._configure_connection(conn)
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _writer_connection(self) -> sqlite3.Connection:
        if self._writer_conn is None:
            conn = sqlite3.connect(
                self.path,
                isolation_level=None,
                check_same_thread=False,
            )
            self._configure_connection(conn)
            self._writer_conn = conn
        return self._writer_conn

    @contextmanager
    def _write_transaction(self) -> Generator[sqlite3.Connection, None, None]:
        with self._writer_lock:
            conn = self._writer_connection()
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except Exception:
                conn.rollback()
                raise
            else:
                conn.commit()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    event_type TEXT NOT NULL,
                    source TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    snapshot_type TEXT NOT NULL,
                    event_id INTEGER NOT NULL REFERENCES events(id),
                    source TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                DROP TABLE IF EXISTS decisions;
                DROP TABLE IF EXISTS projection_cache;
                """
            )
            conn.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (SCHEMA_VERSION, utc_now()),
            )

    @staticmethod
    def canonical_json(payload: Any) -> str:
        return _canonical_json(payload)

    @classmethod
    def payload_hash(cls, payload: Any) -> str:
        return hashlib.sha256(cls.canonical_json(payload).encode("utf-8")).hexdigest()

    def append_event(
        self,
        *,
        idempotency_key: str,
        event_type: str,
        source: str,
        payload: dict[str, Any],
    ) -> AppendResult:
        with self._write_transaction() as conn:
            return self._append_event_in_conn(
                conn,
                idempotency_key=idempotency_key,
                event_type=event_type,
                source=source,
                payload=payload,
            )

    def _append_event_in_conn(
        self,
        conn: sqlite3.Connection,
        *,
        idempotency_key: str,
        event_type: str,
        source: str,
        payload: dict[str, Any],
    ) -> AppendResult:
        payload_json = self.canonical_json(payload)
        payload_hash = self.payload_hash(payload)
        existing = conn.execute(
            "SELECT id, event_type, source, payload_hash FROM events WHERE idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()
        if existing is not None:
            if (
                existing["event_type"] != event_type
                or existing["source"] != source
                or existing["payload_hash"] != payload_hash
            ):
                raise IdempotencyConflict(
                    f"idempotency key {idempotency_key!r} was reused with different event identity"
                )
            return AppendResult(event_id=int(existing["id"]), inserted=False)
        cur = conn.execute(
            """
            INSERT INTO events(idempotency_key, event_type, source, payload_json, payload_hash, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                idempotency_key,
                event_type,
                source,
                payload_json,
                payload_hash,
                utc_now(),
            ),
        )
        event_id = cur.lastrowid
        if (
            event_id is None
        ):  # pragma: no cover - SQLite INSERT should always return an id.
            raise RuntimeError("event insert did not return an id")
        return AppendResult(event_id=int(event_id), inserted=True)

    def save_queue_snapshot(self, payload: dict[str, Any]) -> tuple[AppendResult, int]:
        key = str(payload["idempotency_key"])
        payload_json = self.canonical_json(payload)
        with self._write_transaction() as conn:
            event = self._append_event_in_conn(
                conn,
                idempotency_key=key,
                event_type="n8n.queue_snapshot",
                source=str(payload.get("source") or "n8n"),
                payload=payload,
            )
            cur = conn.execute(
                """
                INSERT INTO snapshots(idempotency_key, snapshot_type, event_id, source, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(idempotency_key) DO UPDATE SET idempotency_key = excluded.idempotency_key
                RETURNING id
                """,
                (
                    key,
                    "n8n_queue",
                    event.event_id,
                    str(payload.get("source") or "n8n"),
                    payload_json,
                    utc_now(),
                ),
            )
            row = cur.fetchone()
            if row is None:  # pragma: no cover - SQLite RETURNING should always return.
                raise RuntimeError("snapshot upsert did not return an id")
            return event, int(row["id"])

    def latest_snapshot(
        self, snapshot_type: str = "n8n_queue"
    ) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT payload_json FROM snapshots
                WHERE snapshot_type = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (snapshot_type,),
            ).fetchone()
        if row is None:
            return None
        return json.loads(str(row["payload_json"]))

    def all_snapshots(self, snapshot_type: str = "n8n_queue") -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT payload_json FROM snapshots WHERE snapshot_type = ? ORDER BY id ASC",
                (snapshot_type,),
            ).fetchall()
        return [json.loads(str(row["payload_json"])) for row in rows]

    def rebuild_queue_projection(self) -> dict[str, Any]:
        # Deterministic replay rule for Phase 1: latest n8n queue snapshot wins.
        return self.latest_snapshot("n8n_queue") or {
            "source": "none",
            "queue_rows": [],
            "paper_rows": [],
            "captured_at": None,
        }
