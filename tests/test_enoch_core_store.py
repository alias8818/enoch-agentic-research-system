from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from omx_wake_gate.enoch_core.store import EnochCoreStore, IdempotencyConflict


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
