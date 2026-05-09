from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..models import utc_now

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
                CREATE TABLE IF NOT EXISTS decisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    decision_key TEXT NOT NULL UNIQUE,
                    project_id TEXT,
                    run_id TEXT,
                    decision_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS projection_cache (
                    projection_key TEXT PRIMARY KEY,
                    projection_version TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    rebuilt_at TEXT NOT NULL
                );
                """
            )
            conn.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (SCHEMA_VERSION, utc_now()),
            )

    @staticmethod
    def canonical_json(payload: Any) -> str:
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

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
        payload_json = self.canonical_json(payload)
        payload_hash = self.payload_hash(payload)
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT id, payload_hash FROM events WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            if existing is not None:
                if existing["payload_hash"] != payload_hash:
                    raise IdempotencyConflict(
                        f"idempotency key {idempotency_key!r} was reused with different payload"
                    )
                return AppendResult(event_id=int(existing["id"]), inserted=False)
            cur = conn.execute(
                """
                INSERT INTO events(idempotency_key, event_type, source, payload_json, payload_hash, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (idempotency_key, event_type, source, payload_json, payload_hash, utc_now()),
            )
            return AppendResult(event_id=int(cur.lastrowid), inserted=True)

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
            existing = conn.execute(
                "SELECT id FROM snapshots WHERE idempotency_key = ?",
                (key,),
            ).fetchone()
            if existing is not None:
                return event, int(existing["id"])
            cur = conn.execute(
                """
                INSERT INTO snapshots(idempotency_key, snapshot_type, event_id, source, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (key, "n8n_queue", event.event_id, str(payload.get("source") or "n8n"), payload_json, utc_now()),
            )
            return event, int(cur.lastrowid)

    def latest_snapshot(self, snapshot_type: str = "n8n_queue") -> dict[str, Any] | None:
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
