from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from enoch_control_plane.enoch_core.store import EnochCoreStore, IdempotencyConflict


class EnochCoreStoreTests(unittest.TestCase):
    def test_snapshot_ingest_is_idempotent_for_same_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = EnochCoreStore(Path(tmp) / "core.sqlite3")
            payload = {
                "idempotency_key": "snap-1",
                "source": "test",
                "mode": "shadow",
                "queue_rows": [],
                "paper_rows": [],
                "captured_at": "2026-04-23T00:00:00Z",
            }
            first_event, first_snapshot = store.save_queue_snapshot(payload)
            second_event, second_snapshot = store.save_queue_snapshot(payload)
            self.assertTrue(first_event.inserted)
            self.assertFalse(second_event.inserted)
            self.assertEqual(first_event.event_id, second_event.event_id)
            self.assertEqual(first_snapshot, second_snapshot)
            self.assertEqual(len(store.all_snapshots()), 1)

    def test_idempotency_key_conflict_rejects_different_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = EnochCoreStore(Path(tmp) / "core.sqlite3")
            payload = {
                "idempotency_key": "snap-1",
                "source": "test",
                "mode": "shadow",
                "queue_rows": [],
                "paper_rows": [],
                "captured_at": "2026-04-23T00:00:00Z",
            }
            store.save_queue_snapshot(payload)
            changed = {**payload, "queue_rows": [{"project_id": "p1"}]}
            with self.assertRaises(IdempotencyConflict):
                store.save_queue_snapshot(changed)

    def test_snapshot_failure_rolls_back_event_insert(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "core.sqlite3"
            store = EnochCoreStore(path)
            payload = {
                "idempotency_key": "snap-rollback",
                "source": "test",
                "mode": "shadow",
                "queue_rows": [],
                "paper_rows": [],
                "captured_at": "2026-04-23T00:00:00Z",
            }
            with sqlite3.connect(path) as conn:
                conn.executescript(
                    """
                    CREATE TRIGGER fail_snapshot_insert
                    BEFORE INSERT ON snapshots
                    BEGIN
                        SELECT RAISE(ABORT, 'snapshot insert failed');
                    END;
                    """
                )

            with self.assertRaises(sqlite3.IntegrityError):
                store.save_queue_snapshot(payload)

            with sqlite3.connect(path) as conn:
                event_count = conn.execute(
                    "SELECT COUNT(*) FROM events WHERE idempotency_key = ?",
                    ("snap-rollback",),
                ).fetchone()[0]

            self.assertEqual(event_count, 0)

    def test_event_idempotency_rejects_different_event_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = EnochCoreStore(Path(tmp) / "core.sqlite3")
            payload = {"same": True}
            first = store.append_event(
                idempotency_key="event-1",
                event_type="n8n.queue_snapshot",
                source="unit",
                payload=payload,
            )
            replay = store.append_event(
                idempotency_key="event-1",
                event_type="n8n.queue_snapshot",
                source="unit",
                payload=payload,
            )
            self.assertTrue(first.inserted)
            self.assertFalse(replay.inserted)
            self.assertEqual(first.event_id, replay.event_id)

            with self.assertRaises(IdempotencyConflict):
                store.append_event(
                    idempotency_key="event-1",
                    event_type="n8n.different_event",
                    source="unit",
                    payload=payload,
                )
            with self.assertRaises(IdempotencyConflict):
                store.append_event(
                    idempotency_key="event-1",
                    event_type="n8n.queue_snapshot",
                    source="different-source",
                    payload=payload,
                )

    def test_append_event_uses_reused_writer_connection_with_wal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = EnochCoreStore(Path(tmp) / "core.sqlite3")
            first_writer = store._writer_connection()
            store.append_event(
                idempotency_key="event-1",
                event_type="n8n.queue_snapshot",
                source="unit",
                payload={"same": True},
            )
            second_writer = store._writer_connection()

            self.assertIs(first_writer, second_writer)
            journal_mode = first_writer.execute("PRAGMA journal_mode").fetchone()[0]
            synchronous = first_writer.execute("PRAGMA synchronous").fetchone()[0]
            self.assertEqual(str(journal_mode).lower(), "wal")
            # NORMAL is represented as integer 1 by SQLite.
            self.assertEqual(int(synchronous), 1)

    def test_bootstrap_drops_dead_decision_and_projection_cache_tables(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "core.sqlite3"
            with sqlite3.connect(path) as conn:
                conn.executescript(
                    """
                    CREATE TABLE decisions(id INTEGER PRIMARY KEY);
                    CREATE TABLE projection_cache(projection_key TEXT PRIMARY KEY);
                    """
                )

            EnochCoreStore(path)

            with sqlite3.connect(path) as conn:
                tables = {
                    row[0]
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
            self.assertNotIn("decisions", tables)
            self.assertNotIn("projection_cache", tables)

    def test_projection_rebuild_uses_latest_snapshot_deterministically(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = EnochCoreStore(Path(tmp) / "core.sqlite3")
            first = {
                "idempotency_key": "snap-1",
                "source": "test",
                "mode": "shadow",
                "queue_rows": [{"project_id": "old"}],
                "paper_rows": [],
                "captured_at": "2026-04-23T00:00:00Z",
            }
            second = {
                "idempotency_key": "snap-2",
                "source": "test",
                "mode": "shadow",
                "queue_rows": [{"project_id": "new"}],
                "paper_rows": [],
                "captured_at": "2026-04-23T00:01:00Z",
            }
            store.save_queue_snapshot(first)
            store.save_queue_snapshot(second)
            rebuilt_once = store.rebuild_queue_projection()
            rebuilt_twice = store.rebuild_queue_projection()
            self.assertEqual(rebuilt_once, rebuilt_twice)
            self.assertEqual(rebuilt_once["queue_rows"][0]["project_id"], "new")


if __name__ == "__main__":
    unittest.main()
