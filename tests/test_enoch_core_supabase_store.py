from __future__ import annotations

import pytest

from enoch_control_plane.enoch_core.logic import eligible_paper_draft_candidates
from enoch_control_plane.enoch_core._canonical import canonical_json
from enoch_control_plane.enoch_core.supabase_store import SupabaseEnochCoreStore
from enoch_control_plane.enoch_core.store import EnochCoreStore, IdempotencyConflict


class Cursor:
    def __init__(self, state):
        self.state = state
        self.sql = ""
        self.params = ()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def execute(self, sql, params=()):
        self.sql = sql
        self.params = tuple(params)
        return self

    def fetchone(self):
        if "from core_events where idempotency_key" in self.sql:
            key = self.params[0]
            return self.state["events"].get(key)
        if "insert into core_events" in self.sql:
            event_id = len(self.state["events"]) + 1
            key = self.params[0]
            self.state["events"][key] = {
                "id": event_id,
                "event_type": self.params[1],
                "source": self.params[2],
                "payload_hash": self.params[4],
            }
            return {"id": event_id}
        if "select id from core_snapshots" in self.sql:
            return self.state["snapshots_by_key"].get(self.params[0])
        if "insert into core_snapshots" in self.sql:
            snap_id = len(self.state["snapshots"]) + 1
            self.state["snapshots_by_key"][self.params[0]] = {"id": snap_id}
            self.state["snapshots"].append(
                {
                    "id": snap_id,
                    "payload_json": self.params[4],
                    "snapshot_type": self.params[1],
                }
            )
            return {"id": snap_id}
        raise AssertionError(self.sql)

    def fetchall(self):
        normalized = " ".join(str(self.sql).lower().split())
        if "from queue_items q" in normalized:
            if "live_queue_rows" not in self.state:
                raise RuntimeError("live queue projection unavailable")
            return self.state["live_queue_rows"]
        if "from papers pa" in normalized:
            if "live_paper_rows" not in self.state:
                raise RuntimeError("live paper projection unavailable")
            return self.state["live_paper_rows"]
        if "from core_snapshots" in self.sql and "order by id desc" in self.sql:
            rows = [
                row
                for row in self.state["snapshots"]
                if row["snapshot_type"] == self.params[0]
            ]
            return rows[-1:] if rows else []
        if "from core_snapshots" in self.sql and "order by id asc" in self.sql:
            return [
                row
                for row in self.state["snapshots"]
                if row["snapshot_type"] == self.params[0]
            ]
        return []


class Conn:
    def __init__(self, state):
        self.state = state
        self.closed = False
        self.committed = False
        self.rolled_back = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def cursor(self):
        return Cursor(self.state)

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


def test_core_supabase_store_events_snapshots_and_projection() -> None:
    state = {"events": {}, "snapshots": [], "snapshots_by_key": {}}
    store = SupabaseEnochCoreStore("postgres://example", connect=lambda: Conn(state))
    payload = {"idempotency_key": "snap-1", "source": "unit", "queue_rows": [{"id": 1}]}
    event, snapshot_id = store.save_queue_snapshot(payload)
    assert event.inserted is True
    assert event.event_id == 1
    assert snapshot_id == 1
    replayed, replayed_snapshot_id = store.save_queue_snapshot(payload)
    assert replayed.inserted is False
    assert replayed_snapshot_id == 1
    assert store.latest_snapshot() == payload
    assert store.all_snapshots() == [payload]
    assert store.rebuild_queue_projection() == payload

    with pytest.raises(IdempotencyConflict):
        store.append_event(
            idempotency_key="snap-1",
            event_type="n8n.queue_snapshot",
            source="unit",
            payload={"different": True},
        )


def test_core_supabase_store_rejects_replayed_key_with_different_event_identity() -> (
    None
):
    state = {"events": {}, "snapshots": [], "snapshots_by_key": {}}
    store = SupabaseEnochCoreStore("postgres://example", connect=lambda: Conn(state))
    payload = {"same": True}

    first = store.append_event(
        idempotency_key="same-key",
        event_type="n8n.queue_snapshot",
        source="unit",
        payload=payload,
    )
    replay = store.append_event(
        idempotency_key="same-key",
        event_type="n8n.queue_snapshot",
        source="unit",
        payload=payload,
    )

    assert first.inserted is True
    assert replay.inserted is False
    assert replay.event_id == first.event_id

    with pytest.raises(IdempotencyConflict):
        store.append_event(
            idempotency_key="same-key",
            event_type="n8n.different_event",
            source="unit",
            payload=payload,
        )
    with pytest.raises(IdempotencyConflict):
        store.append_event(
            idempotency_key="same-key",
            event_type="n8n.queue_snapshot",
            source="different-source",
            payload=payload,
        )


def test_core_supabase_store_json_helpers_and_empty_projection() -> None:
    store = SupabaseEnochCoreStore(
        "postgres://example",
        connect=lambda: Conn({"events": {}, "snapshots": [], "snapshots_by_key": {}}),
    )
    payload = {"b": "ß", "a": 1}
    assert canonical_json(payload) == '{"a":1,"b":"ß"}'
    assert store.canonical_json(payload) == canonical_json(payload)
    assert EnochCoreStore.canonical_json(payload) == canonical_json(payload)
    assert store.payload_hash(payload) == EnochCoreStore.payload_hash(payload)
    assert store._json_payload(None) == {}
    assert store._json_payload('{"a":1}') == {"a": 1}
    assert store.latest_snapshot() is None
    assert store.all_snapshots() == []
    assert store.rebuild_queue_projection() == {
        "source": "none",
        "queue_rows": [],
        "paper_rows": [],
        "captured_at": None,
    }
    with pytest.raises(ValueError):
        SupabaseEnochCoreStore(" ")


def test_core_supabase_projection_rebuilds_from_live_control_plane_rows() -> None:
    state = {
        "events": {},
        "snapshots": [],
        "snapshots_by_key": {},
        "live_queue_rows": [
            {
                "project_id": "paper-scout-live",
                "project_name": "Paper Scout Live",
                "project_dir": "paper-scout-live",
                "notion_page_url": "",
                "status": "completed",
                "last_run_state": "wake_ready",
                "next_action_hint": "draft_paper_or_select_next_project",
                "current_run_id": "run-paper-scout-live",
                "manual_review_required": False,
                "project_decision": "finalize_negative",
                "research_outcome": "useful_signal",
                "bounded_paper_ready": True,
                "hypothesis_status": "supported",
                "evidence_strength": "strong",
                "claim_scope": "single local benchmark",
                "scale_limits": "toy-sized reproduction only",
            }
        ],
        "live_paper_rows": [],
    }
    store = SupabaseEnochCoreStore("postgres://example", connect=lambda: Conn(state))

    rebuilt = store.rebuild_queue_projection()

    assert rebuilt["source"] == "control_plane_db"
    assert rebuilt["queue_rows"] == state["live_queue_rows"]
    assert rebuilt["paper_rows"] == []
    assert rebuilt["captured_at"]
    candidates = eligible_paper_draft_candidates(
        rebuilt["queue_rows"], rebuilt["paper_rows"]
    )
    assert len(candidates) == 1
    assert candidates[0]["project_id"] == "paper-scout-live"
    assert candidates[0]["bounded_paper_ready"] is True
