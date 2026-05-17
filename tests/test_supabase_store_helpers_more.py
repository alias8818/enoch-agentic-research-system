from __future__ import annotations

from enoch_control_plane.control_plane import supabase_store as s
from enoch_control_plane.control_plane.models import ControlFlags, ImportSnapshotRequest
from enoch_control_plane.control_plane.store import QueueStatus


def test_decision_gate_state_and_summary_variants() -> None:
    assert s._decision_gate_state({"eligible": True}) == "positive"
    assert s._decision_gate_state({"reason": "missing project_decision"}) == "missing"
    assert s._decision_gate_state({"reason": "could not parse JSON"}) == "malformed"
    assert s._decision_gate_state({"decision": "finalize_negative"}) == "negative"
    assert s._decision_gate_state({"values": [("x", "project_decision", "needs_review")]}) == "unknown"
    assert s._decision_summary({"decision": "finalize_negative", "reason": "not positive"}) == "finalize_negative (not positive)"
    assert s._decision_summary({"values": [("json", "hypothesis_status", "mixed")]}) == "mixed"


def test_followup_payload_helpers() -> None:
    assert s._stable_followup_id("parent", "A Great Followup!", "hyp") == s._stable_followup_id("parent", "A Great Followup!", "hyp")
    assert s._followup_depth_from_payload(None) == 0
    assert s._followup_depth_from_payload({"followup_depth": "2"}) == 2
    assert s._followup_depth_from_payload({"source_payload_json": {"parent_followup_depth": "3"}}) == 3
    assert s._followup_depth_from_payload({"followup_depth": "bad"}) == 0
    assert s._enforced_followup_depth({"followup_depth": 1}, {"source_payload_json": {"followup_depth": 4}}) == 4
    assert s._jsonish_dict('{"a":1}') == {"a": 1}
    assert s._jsonish_dict('[1]') == {}
    assert s._jsonish_list('[1]') == [1]
    assert s._jsonish_list('{"a":1}') == []
    assert s._project_decision_payload_from_candidate({"decision_payload_json": {"project_decision": {"decision": "x"}}}) == {"decision": "x"}
    assert s._followup_required_evidence_items({"followup_required_evidence": '["a","b"]'}) == ["a", "b"]
    assert s._followup_required_evidence_items({"followup_required_evidence": "metric\nablation"}) == []
    assert s._followup_required_evidence_items({"followup_required_evidence": ["metric", ""]}) == ["metric"]
    assert not s._has_concrete_followup({
        "followup_title": "Too sparse",
        "followup_hypothesis": "signal holds",
        "followup_required_evidence": ["metric", ""],
        "followup_success_threshold": "beats baseline",
        "followup_stop_condition": "no lift",
    })


def test_followup_escalation_promising_and_standard() -> None:
    candidate = {
        "decision_payload_json": {
            "project_decision": "finalize_negative",
            "hypothesis_status": "mixed",
            "evidence_strength": "moderate",
        },
        "followup_title": "Deepen signal",
        "followup_hypothesis": "signal survives medium test",
        "followup_required_evidence": ["direct metric", "ablation"],
        "followup_success_threshold": "beats baseline",
        "followup_stop_condition": "no lift",
    }
    payload = s._followup_escalation_payload(candidate, 2)
    assert payload["promising_escalation"] is True
    assert payload["research_ladder_tier"] == 2
    assert "real baseline" in " ".join(payload["worker_prompt_guidance"])

    weak = dict(candidate, decision_payload_json={"project_decision": "continue"})
    standard = s._followup_escalation_payload(weak, 4)
    assert standard["promising_escalation"] is False
    assert standard["research_ladder_tier"] == 4


def test_readonly_store_basic_query_methods() -> None:
    class Cursor:
        def __init__(self):
            self.sql = ""
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def execute(self, sql, params=()):
            self.sql = sql
            self.params = params
        def fetchall(self):
            if "from control_flags" in self.sql:
                return [{"queue_paused": True, "maintenance_mode": False, "pause_reason": "ops", "paused_at": None, "paused_by": "tester", "updated_at": "now"}]
            if "from queue_items group by status" in self.sql:
                return [{"status": QueueStatus.QUEUED.value, "count": 2}, {"status": QueueStatus.RUNNING.value, "count": 1}]
            if "manual_review_required" in self.sql and "count(*) as count" in self.sql:
                return [{"count": 3}]
            if "from papers group by paper_status" in self.sql:
                return [{"paper_status": "publication_draft", "count": 4}]
            return []
    class Conn:
        closed = False
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def cursor(self): return Cursor()
        def close(self): self.closed = True

    store = s.SupabaseReadOnlyControlPlaneStore("postgres://example", connect=Conn)
    flags = store.flags()
    assert isinstance(flags, ControlFlags)
    assert flags.queue_paused is True
    counts = store.queue_counts_sql()
    assert counts["queued"] == 2
    assert counts["active"] == 1
    assert counts["blocked"] == 3
    papers = store.paper_counts_sql()
    assert papers == {"publication_draft": 4, "all": 4}
    try:
        store.pause()
    except s.ReadOnlyStoreError:
        pass
    else:
        raise AssertionError("pause should be read-only")

from enoch_control_plane.control_plane.models import IdeaIntakeRequest, NotionIntakeRequest
from enoch_control_plane.control_plane.supabase_store import SupabaseControlPlaneStore


def test_write_store_dry_run_intakes_build_candidates_and_skips_rows() -> None:
    store = SupabaseControlPlaneStore("postgres://example", connect=lambda: None)
    notion_inserted, notion_created, notion_updated, notion_skipped, notion_candidates, notion_skipped_rows = store.ingest_notion_ideas(
        NotionIntakeRequest(
            dry_run=True,
            include_statuses=["testing"],
            notion_rows=[
                {"title": "Keep This", "property_status": "Testing", "url": "https://notion.so/example/abc12345678901234567890123456789"},
                {"title": "Skip This", "property_status": "Archived"},
                {"property_status": "Testing"},
            ],
            default_machine_target="gb10",
            default_model="gpt-5.5",
        )
    )
    assert notion_inserted is False
    assert notion_created == notion_updated == 0
    assert notion_skipped == 2
    assert len(notion_candidates) == 1
    assert notion_candidates[0]["project_name"] == "Keep This"
    assert notion_candidates[0]["machine_target"] == "gb10"
    assert {row["reason"] for row in notion_skipped_rows} == {"status 'archived' not included", "missing title"}

    idea_inserted, idea_created, idea_updated, idea_skipped, idea_candidates, idea_skipped_rows = store.ingest_ideas(
        IdeaIntakeRequest(
            dry_run=True,
            include_statuses=["testing"],
            ideas=[
                {"idea_id": "idea-1", "title": "Good Idea", "idea_status": "testing", "selection_rank": "12", "machine_target": "gb10", "source_kind": "unit"},
                {"idea_id": "idea-2", "title": "Old Idea", "idea_status": "archived"},
                {"idea_id": "idea-3", "idea_status": "testing"},
            ],
        )
    )
    assert idea_inserted is False
    assert idea_created == idea_updated == 0
    assert idea_skipped == 2
    assert idea_candidates[0]["project_id"] == "idea-1"
    assert idea_candidates[0]["selection_rank"] == 12
    assert idea_candidates[0]["source_kind"] == "unit"
    assert {row["reason"] for row in idea_skipped_rows} == {"status 'archived' not included", "missing title"}


def test_write_store_dispatch_and_projection_helpers(monkeypatch) -> None:
    store = SupabaseControlPlaneStore("postgres://example", connect=lambda: None)
    monkeypatch.setattr(store, "flags", lambda: ControlFlags(queue_paused=True, pause_reason="maintenance"))
    assert store.dispatch_next_dry_run(requested_by="operator") == ("paused", None, None, "maintenance")

    monkeypatch.setattr(store, "flags", lambda: ControlFlags(queue_paused=False))
    monkeypatch.setattr(store, "active_items", lambda: [{"project_id": "active"}])
    assert store.dispatch_next_dry_run(requested_by="operator")[3] == "active GB10 lane already exists"

    monkeypatch.setattr(store, "active_items", lambda: [])
    monkeypatch.setattr(store, "next_dispatch_candidate", lambda: None)
    assert store.dispatch_next_dry_run(requested_by="operator")[3] == "no queued candidate"

    candidate = {"project_id": "queued", "project_name": "Queued"}
    monkeypatch.setattr(store, "next_dispatch_candidate", lambda: candidate)
    assert store.dispatch_next_dry_run(requested_by="operator") == ("dry_run_dispatch", candidate, None, "dry-run dispatch selected candidate")

    queue_rows = [
        {"project_id": "p1", "project_name": "One", "status": QueueStatus.RUNNING.value, "notion_page_url": "https://notion.so/x/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "notion_page_id": "page", "current_run_id": "run", "next_action_hint": "wait", "updated_at": "now"},
        {"project_id": "p2", "project_name": "Two", "status": QueueStatus.BLOCKED.value, "notion_page_url": "", "last_result_summary": "blocked"},
    ]
    paper_rows = [{"project_id": "p1", "paper_id": "paper", "paper_status": "publication_draft", "paper_type": "note", "draft_markdown_path": "paper.md", "updated_at": "paper-now"}]
    monkeypatch.setattr(store, "queue_rows", lambda: queue_rows)
    monkeypatch.setattr(store, "paper_rows", lambda: paper_rows)
    notion_projection = store.notion_execution_update_projection()
    assert len(notion_projection) == 1
    props = notion_projection[0]["properties"]
    assert props["Execution State"] == "running"
    assert props["Enoch Paper ID"] == "paper"
    assert store.queue_notion_projection()[0]["queue_status"] == QueueStatus.RUNNING.value


def test_launch_followup_candidate_dry_run_and_noop(monkeypatch) -> None:
    store = SupabaseControlPlaneStore("postgres://example", connect=lambda: None)
    monkeypatch.setattr(store, "next_followup_candidate", lambda **kwargs: None)
    assert store.launch_followup_candidate(dry_run=True)["action"] == "noop"

    candidate = {
        "project_id": "parent",
        "project_name": "Parent Project",
        "current_run_id": "run-parent",
        "followup_depth": 1,
        "followup_type": "deepen",
        "followup_title": "Check medium scale",
        "followup_hypothesis": "signal holds",
        "followup_required_evidence": ["metric", "ablation"],
        "followup_success_threshold": "beats baseline",
        "followup_stop_condition": "no lift",
        "decision_payload_json": {"project_decision": "finalize_negative", "hypothesis_status": "supported", "evidence_strength": "strong"},
    }
    monkeypatch.setattr(store, "next_followup_candidate", lambda **kwargs: candidate)
    result = store.launch_followup_candidate(dry_run=True, requested_by="unit")
    assert result["action"] == "dry_run_followup"
    assert result["followup"]["parent_project_id"] == "parent"
    assert result["followup"]["followup_depth"] == 2
    assert result["followup"]["promising_escalation"] is True


def test_supabase_store_resolved_artifact_rejects_paths_outside_project(tmp_path) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    store = SupabaseControlPlaneStore("postgres://example", connect=lambda: None)

    artifact = store._resolved_artifact({"project_dir": str(project_dir), "evidence_bundle_path": str(outside)}, "evidence_bundle_path")

    assert artifact["exists"] is True
    assert artifact["safe"] is False
    assert artifact["readable"] is False


def test_supabase_worker_callback_without_key_dedupes_exact_retry(monkeypatch) -> None:
    store = SupabaseControlPlaneStore("postgres://example", connect=lambda: None)
    events: dict[str, tuple[int, str]] = {}

    def fake_one(sql, params=()):  # noqa: ANN001 - lightweight store fake
        if "from control_events" in sql:
            key = params[0]
            if key in events:
                event_id, payload_hash = events[key]
                return {"event_id": event_id, "payload_hash": payload_hash}
        return None

    class Cursor:
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def execute(self, *args, **kwargs): return None

    class Conn:
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def cursor(self): return Cursor()

    def fake_connect():
        return Conn()

    def fake_append_event(_cur, *, idempotency_key, event_type, entity_type, entity_id, payload):  # noqa: ANN001 - signature mirrors store
        del event_type, entity_type, entity_id
        event_id = len(events) + 1
        events[idempotency_key] = (event_id, s._hash(payload))
        return event_id, True

    monkeypatch.setattr(store, "_one", fake_one)
    monkeypatch.setattr(store, "_connect", fake_connect)
    monkeypatch.setattr(store, "_append_event_in_cursor", fake_append_event)
    monkeypatch.setattr(store, "queue_row", lambda project_id: {})

    callback = {
        "event_type": "wake_ready",
        "run_id": "run-no-key",
        "session_id": "session-no-key",
        "project_id": "",
        "gate_state": "wake_ready",
        "reason": "retry without worker key",
    }

    first_event_id, first_inserted, _ = store.record_worker_callback(callback)
    second_event_id, second_inserted, _ = store.record_worker_callback(callback)

    assert first_event_id == second_event_id
    assert first_inserted is True
    assert second_inserted is False
    assert len(events) == 1

def test_supabase_worker_callback_without_identifiers_dedupes_by_payload(monkeypatch) -> None:
    store = SupabaseControlPlaneStore("postgres://example", connect=lambda: None)
    events: dict[str, tuple[int, str]] = {}

    def fake_one(sql, params=()):  # noqa: ANN001 - lightweight store fake
        if "from control_events" in sql:
            key = params[0]
            if key in events:
                event_id, payload_hash = events[key]
                return {"event_id": event_id, "payload_hash": payload_hash}
        return None

    class Cursor:
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def execute(self, *args, **kwargs): return None

    class Conn:
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def cursor(self): return Cursor()

    def fake_connect():
        return Conn()

    def fake_append_event(_cur, *, idempotency_key, event_type, entity_type, entity_id, payload):  # noqa: ANN001 - signature mirrors store
        del event_type, entity_type, entity_id
        event_id = len(events) + 1
        events[idempotency_key] = (event_id, s._hash(payload))
        return event_id, True

    monkeypatch.setattr(store, "_one", fake_one)
    monkeypatch.setattr(store, "_connect", fake_connect)
    monkeypatch.setattr(store, "_append_event_in_cursor", fake_append_event)
    monkeypatch.setattr(store, "queue_row", lambda project_id: {})

    callback = {"source_event": "malformed-worker-callback", "reason": "missing worker identifiers"}

    first_event_id, first_inserted, _ = store.record_worker_callback(callback)
    second_event_id, second_inserted, _ = store.record_worker_callback(callback)

    assert first_event_id == second_event_id
    assert first_inserted is True
    assert second_inserted is False
    assert len(events) == 1

def test_supabase_worker_callback_missing_run_id_does_not_mutate_active_project(monkeypatch) -> None:
    store = SupabaseControlPlaneStore("postgres://example", connect=lambda: None)
    events: dict[str, dict] = {}
    executed: list[tuple[tuple, dict]] = []
    queue = {
        "project_id": "idea-active",
        "status": "awaiting_wake",
        "current_run_id": "run-active",
        "current_session_id": "session-active",
        "last_run_state": "awaiting_wake",
        "next_action_hint": "await_callback",
    }

    def fake_one(sql, params=()):  # noqa: ANN001 - lightweight store fake
        if "from queue_items" in sql:
            return queue
        if "from control_events" in sql:
            key = params[0]
            event = events.get(key)
            if event:
                return {"event_id": event["event_id"], "payload_hash": event["payload_hash"]}
        return None

    class Cursor:
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def execute(self, *args, **kwargs):
            executed.append((args, kwargs))
            return None

    class Conn:
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def cursor(self): return Cursor()

    def fake_append_event(_cur, *, idempotency_key, event_type, entity_type, entity_id, payload):  # noqa: ANN001 - signature mirrors store
        event_id = len(events) + 1
        events[idempotency_key] = {
            "event_id": event_id,
            "payload_hash": s._hash(payload),
            "event_type": event_type,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "payload": payload,
        }
        return event_id, True

    monkeypatch.setattr(store, "_one", fake_one)
    monkeypatch.setattr(store, "_connect", lambda: Conn())
    monkeypatch.setattr(store, "_append_event_in_cursor", fake_append_event)
    monkeypatch.setattr(store, "queue_row", lambda project_id: queue)

    event_id, inserted, row = store.record_worker_callback({
        "project_id": "idea-active",
        "event_type": "",
        "reason": "malformed callback without run id",
    })

    assert inserted is True
    assert event_id == 1
    assert row["status"] == "awaiting_wake"
    assert executed == []
    event = next(iter(events.values()))
    assert event["payload"]["stale_callback_ignored"] is True
    assert event["payload"]["ignore_reason"] == "missing_run_id_for_active_project"


def test_supabase_worker_callback_missing_run_id_does_not_mutate_active_project_with_empty_current_run(monkeypatch) -> None:
    store = SupabaseControlPlaneStore("postgres://example", connect=lambda: None)
    events: dict[str, dict] = {}
    executed: list[tuple[tuple, dict]] = []
    queue = {
        "project_id": "idea-active-empty",
        "status": "awaiting_wake",
        "current_run_id": "",
        "current_session_id": "session-active",
        "last_run_state": "awaiting_wake",
        "next_action_hint": "await_callback",
    }

    def fake_one(sql, params=()):  # noqa: ANN001 - lightweight store fake
        if "from queue_items" in sql:
            return queue
        if "from control_events" in sql:
            key = params[0]
            event = events.get(key)
            if event:
                return {"event_id": event["event_id"], "payload_hash": event["payload_hash"]}
        return None

    class Cursor:
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def execute(self, *args, **kwargs):
            executed.append((args, kwargs))
            return None

    class Conn:
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def cursor(self): return Cursor()

    def fake_append_event(_cur, *, idempotency_key, event_type, entity_type, entity_id, payload):  # noqa: ANN001 - signature mirrors store
        event_id = len(events) + 1
        events[idempotency_key] = {
            "event_id": event_id,
            "payload_hash": s._hash(payload),
            "event_type": event_type,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "payload": payload,
        }
        return event_id, True

    monkeypatch.setattr(store, "_one", fake_one)
    monkeypatch.setattr(store, "_connect", lambda: Conn())
    monkeypatch.setattr(store, "_append_event_in_cursor", fake_append_event)
    monkeypatch.setattr(store, "queue_row", lambda project_id: queue)

    event_id, inserted, row = store.record_worker_callback({
        "project_id": "idea-active-empty",
        "event_type": "wake_ready",
        "reason": "project-only callback without run id",
    })

    assert inserted is True
    assert event_id == 1
    assert row["status"] == "awaiting_wake"
    assert executed == []
    event = next(iter(events.values()))
    assert event["payload"]["stale_callback_ignored"] is True
    assert event["payload"]["ignore_reason"] == "missing_run_id_for_active_project"


def test_supabase_worker_callback_missing_run_id_does_not_complete_queued_project(monkeypatch) -> None:
    store = SupabaseControlPlaneStore("postgres://example", connect=lambda: None)
    events: dict[str, dict] = {}
    executed: list[tuple[tuple, dict]] = []
    queue = {
        "project_id": "idea-queued-project-only",
        "status": "queued",
        "current_run_id": "",
        "current_session_id": "",
        "last_run_state": "",
        "next_action_hint": "controller_review",
    }

    def fake_one(sql, params=()):  # noqa: ANN001 - lightweight store fake
        if "from queue_items" in sql:
            return queue
        if "from control_events" in sql:
            key = params[0]
            event = events.get(key)
            if event:
                return {"event_id": event["event_id"], "payload_hash": event["payload_hash"]}
        return None

    class Cursor:
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def execute(self, *args, **kwargs):
            executed.append((args, kwargs))
            return None

    class Conn:
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def cursor(self): return Cursor()

    def fake_append_event(_cur, *, idempotency_key, event_type, entity_type, entity_id, payload):  # noqa: ANN001 - signature mirrors store
        event_id = len(events) + 1
        events[idempotency_key] = {
            "event_id": event_id,
            "payload_hash": s._hash(payload),
            "event_type": event_type,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "payload": payload,
        }
        return event_id, True

    monkeypatch.setattr(store, "_one", fake_one)
    monkeypatch.setattr(store, "_connect", lambda: Conn())
    monkeypatch.setattr(store, "_append_event_in_cursor", fake_append_event)
    monkeypatch.setattr(store, "queue_row", lambda project_id: queue)

    event_id, inserted, row = store.record_worker_callback({
        "project_id": "idea-queued-project-only",
        "event_type": "wake_ready",
        "reason": "project-only callback without run id",
    })

    assert inserted is True
    assert event_id == 1
    assert row["status"] == "queued"
    assert executed == []
    event = next(iter(events.values()))
    assert event["payload"]["stale_callback_ignored"] is True
    assert event["payload"]["ignore_reason"] == "missing_run_id_for_project_callback"



def test_supabase_stale_worker_callback_replay_stays_idempotent_after_current_run_completes(monkeypatch) -> None:
    store = SupabaseControlPlaneStore("postgres://example", connect=lambda: None)
    events: dict[str, dict] = {}
    executed: list[tuple[tuple, dict]] = []
    queue = {
        "project_id": "idea-stale-replay",
        "status": "awaiting_wake",
        "current_run_id": "run-current",
        "current_session_id": "session-current",
        "last_run_state": "awaiting_wake",
        "next_action_hint": "await_callback",
    }

    def fake_one(sql, params=()):  # noqa: ANN001 - lightweight store fake
        if "from control_events" in sql:
            key = params[0]
            event = events.get(key)
            if event:
                return {"event_id": event["event_id"], "payload_hash": event["payload_hash"], "payload_json": event["payload"]}
        if "from queue_items" in sql:
            return queue
        return None

    class Cursor:
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def execute(self, *args, **kwargs):
            executed.append((args, kwargs))
            return None

    class Conn:
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def cursor(self): return Cursor()

    def fake_append_event(_cur, *, idempotency_key, event_type, entity_type, entity_id, payload):  # noqa: ANN001 - signature mirrors store
        event_id = len(events) + 1
        events[idempotency_key] = {
            "event_id": event_id,
            "payload_hash": s._hash(payload),
            "event_type": event_type,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "payload": payload,
        }
        return event_id, True

    monkeypatch.setattr(store, "_one", fake_one)
    monkeypatch.setattr(store, "_connect", lambda: Conn())
    monkeypatch.setattr(store, "_append_event_in_cursor", fake_append_event)
    monkeypatch.setattr(store, "queue_row", lambda project_id: queue)

    stale_callback = {
        "project_id": "idea-stale-replay",
        "run_id": "run-old",
        "session_id": "session-old",
        "event_type": "wake_ready",
        "reason": "old worker retry",
        "idempotency_key": "stale-replay-key",
    }
    first_event_id, first_inserted, first_row = store.record_worker_callback(stale_callback)
    assert first_inserted is True
    assert first_row["status"] == "awaiting_wake"

    queue.update({
        "status": "completed",
        "last_run_state": "wake_ready",
        "next_action_hint": "draft_paper_or_select_next_project",
    })
    executed.clear()

    second_event_id, second_inserted, second_row = store.record_worker_callback(stale_callback)

    assert second_event_id == first_event_id
    assert second_inserted is False
    assert second_row["status"] == "completed"
    assert executed == []
    assert len(events) == 1
    assert events["stale-replay-key"]["payload"]["stale_callback_ignored"] is True



def test_supabase_mark_dispatch_started_append_failure_does_not_mutate_runtime_state(monkeypatch) -> None:
    store = SupabaseControlPlaneStore("postgres://example", connect=lambda: None)
    project_id = "idea-dispatch-atomic"
    run_id = "run-dispatch-atomic"
    queue = {
        "project_id": project_id,
        "status": "queued",
        "current_run_id": "",
        "current_session_id": "",
        "last_run_state": "",
        "next_action_hint": "start_next_candidate",
    }
    runs: dict[str, dict] = {}

    class Cursor:
        def __init__(self, conn):
            self.conn = conn
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def execute(self, sql, params=()):  # noqa: ANN001 - lightweight DB fake
            normalized = " ".join(str(sql).lower().split())
            if normalized.startswith("update queue_items"):
                pending_queue = self.conn.pending_queue
                pending_queue["status"] = params[0]
                pending_queue["current_run_id"] = params[1]
                pending_queue["current_session_id"] = params[2]
                pending_queue["last_run_state"] = params[3]
                pending_queue["next_action_hint"] = params[5]
            elif normalized.startswith("insert into runs"):
                self.conn.pending_runs[params[0]] = {
                    "run_id": params[0],
                    "project_id": params[1],
                    "session_id": params[2],
                    "state": params[3],
                    "gate_state": params[8],
                }
            return self

    class Conn:
        def __enter__(self):
            self.pending_queue = dict(queue)
            self.pending_runs = {key: dict(value) for key, value in runs.items()}
            return self
        def __exit__(self, exc_type, *_args):
            if exc_type is None:
                queue.update(self.pending_queue)
                runs.clear()
                runs.update(self.pending_runs)
            return False
        def cursor(self): return Cursor(self)

    def fail_append_event(*_args, **_kwargs):
        raise RuntimeError("simulated dispatch event write failure")

    monkeypatch.setattr(store, "_connect", lambda: Conn())
    monkeypatch.setattr(store, "_append_event_in_cursor", fail_append_event)

    try:
        store.mark_dispatch_started(
            project_id=project_id,
            run_id=run_id,
            session_id="session-after",
            dispatch_payload={"project_id": project_id},
            requested_by="test",
        )
    except RuntimeError as exc:
        assert "simulated dispatch event write failure" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("expected simulated event write failure")

    assert queue["status"] == "queued"
    assert queue["current_run_id"] == ""
    assert queue["current_session_id"] == ""
    assert queue["last_run_state"] == ""
    assert queue["next_action_hint"] == "start_next_candidate"
    assert runs == {}


def test_supabase_worker_callback_append_failure_does_not_mutate_runtime_state(monkeypatch) -> None:
    store = SupabaseControlPlaneStore("postgres://example", connect=lambda: None)
    project_id = "idea-callback-atomic"
    run_id = "run-callback-atomic"
    queue = {
        "project_id": project_id,
        "status": "awaiting_wake",
        "current_run_id": run_id,
        "current_session_id": "session-before",
        "last_run_state": "awaiting_wake",
        "next_action_hint": "await_callback",
    }
    run = {
        "run_id": run_id,
        "project_id": project_id,
        "session_id": "session-before",
        "state": "running",
        "gate_state": "running",
    }

    def fake_one(sql, params=()):  # noqa: ANN001 - lightweight store fake
        if "from control_events" in sql:
            return None
        if "from queue_items" in sql:
            return dict(queue)
        if "from runs" in sql:
            return dict(run)
        return None

    class Cursor:
        def __init__(self, conn):
            self.conn = conn
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def execute(self, sql, params=()):  # noqa: ANN001 - lightweight DB fake
            normalized = " ".join(str(sql).lower().split())
            if normalized.startswith("update queue_items"):
                pending_queue = self.conn.pending_queue
                pending_queue["status"] = params[0]
                pending_queue["current_session_id"] = params[1] or pending_queue["current_session_id"]
                pending_queue["last_run_state"] = params[2]
                pending_queue["next_action_hint"] = params[4]
            elif normalized.startswith("update runs"):
                pending_run = self.conn.pending_run
                pending_run["session_id"] = params[0] or pending_run["session_id"]
                pending_run["state"] = params[1]
                pending_run["gate_state"] = params[4]
            return self

    class Conn:
        def __enter__(self):
            self.pending_queue = dict(queue)
            self.pending_run = dict(run)
            return self
        def __exit__(self, exc_type, *_args):
            if exc_type is None:
                queue.update(self.pending_queue)
                run.update(self.pending_run)
            return False
        def cursor(self): return Cursor(self)

    def fail_append_event(*_args, **_kwargs):
        raise RuntimeError("simulated event write failure")

    monkeypatch.setattr(store, "_one", fake_one)
    monkeypatch.setattr(store, "_connect", lambda: Conn())
    monkeypatch.setattr(store, "_append_event_in_cursor", fail_append_event)

    callback = {
        "event_type": "wake_ready",
        "run_id": run_id,
        "session_id": "session-after",
        "project_id": project_id,
        "gate_state": "wake_ready",
        "reason": "worker ready",
        "idempotency_key": "callback-atomic-key",
    }
    try:
        store.record_worker_callback(callback)
    except RuntimeError as exc:
        assert "simulated event write failure" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("expected simulated event write failure")

    assert queue["status"] == "awaiting_wake"
    assert queue["current_session_id"] == "session-before"
    assert queue["last_run_state"] == "awaiting_wake"
    assert queue["next_action_hint"] == "await_callback"
    assert run["session_id"] == "session-before"
    assert run["state"] == "running"
    assert run["gate_state"] == "running"


def test_supabase_worker_callback_idempotency_rejects_payload_subset_reuse(monkeypatch) -> None:
    store = SupabaseControlPlaneStore("postgres://example", connect=lambda: None)
    events: dict[str, dict] = {}
    queue = {
        "project_id": "idea-subset-reuse",
        "status": "awaiting_wake",
        "current_run_id": "run-subset-reuse",
        "current_session_id": "session-subset-reuse",
        "last_run_state": "awaiting_wake",
        "next_action_hint": "await_callback",
    }

    def fake_one(sql, params=()):  # noqa: ANN001 - lightweight store fake
        if "from control_events" in sql:
            event = events.get(params[0])
            if event:
                return {"event_id": event["event_id"], "payload_hash": event["payload_hash"], "payload_json": event["payload"]}
        if "from queue_items" in sql:
            return queue
        return None

    class Cursor:
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def execute(self, *args, **kwargs): return None

    class Conn:
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def cursor(self): return Cursor()

    def fake_append_event(_cur, *, idempotency_key, event_type, entity_type, entity_id, payload):  # noqa: ANN001 - signature mirrors store
        event_id = len(events) + 1
        events[idempotency_key] = {
            "event_id": event_id,
            "payload_hash": s._hash(payload),
            "event_type": event_type,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "payload": payload,
        }
        return event_id, True

    monkeypatch.setattr(store, "_one", fake_one)
    monkeypatch.setattr(store, "_connect", lambda: Conn())
    monkeypatch.setattr(store, "_append_event_in_cursor", fake_append_event)
    monkeypatch.setattr(store, "queue_row", lambda project_id: queue)

    original = {
        "event_type": "wake_ready",
        "run_id": "run-subset-reuse",
        "session_id": "session-subset-reuse",
        "project_id": "idea-subset-reuse",
        "gate_state": "wake_ready",
        "reason": "original worker ready",
        "telemetry": {"exit_code": 0},
        "idempotency_key": "subset-reuse-key",
    }
    first_event_id, first_inserted, _row = store.record_worker_callback(original)
    assert first_inserted is True
    assert first_event_id == 1

    subset = {
        "event_type": "wake_ready",
        "run_id": "run-subset-reuse",
        "session_id": "session-subset-reuse",
        "project_id": "idea-subset-reuse",
        "idempotency_key": "subset-reuse-key",
    }

    try:
        store.record_worker_callback(subset)
    except s.IdempotencyConflict:
        pass
    else:
        raise AssertionError("subset callback reused idempotency key")


def test_supabase_import_snapshot_preserves_active_runtime_with_empty_current_run(monkeypatch) -> None:
    store = SupabaseControlPlaneStore("postgres://example", connect=lambda: None)
    queue_upserts: list[tuple] = []
    existing_queue = {
        "status": "reconciling",
        "current_run_id": "",
        "current_session_id": "session-active",
        "last_run_state": "wake_received",
        "last_event_type": "worker_callback",
        "next_action_hint": "await_callback",
        "manual_review_required": False,
        "blocked_reason": "",
        "last_error": "",
        "last_result_summary": "waiting",
        "last_dispatch_at": "2026-01-01T00:00:00Z",
        "last_callback_at": "2026-01-01T00:01:00Z",
        "stale_after": "",
    }

    class Cursor:
        def __init__(self) -> None:
            self._next = None
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def execute(self, sql, params=()):  # noqa: ANN001 - lightweight DB fake
            normalized = " ".join(str(sql).split())
            if normalized.startswith("select status,current_run_id"):
                self._next = existing_queue
            elif normalized.startswith("insert into queue_items"):
                queue_upserts.append(tuple(params))
            return self
        def fetchone(self):
            value = self._next
            self._next = None
            return value

    class Conn:
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def cursor(self): return Cursor()

    monkeypatch.setattr(store, "_connect", lambda: Conn())
    monkeypatch.setattr(store, "append_event", lambda **kwargs: (1, True))

    store.import_snapshot(ImportSnapshotRequest(
        idempotency_key="supabase-import-preserve-active-empty-run",
        queue_rows=[{
            "project_id": "idea-active-empty-import",
            "project_name": "Active Empty Import",
            "project_dir": "idea-active-empty-import",
            "status": "completed",
            "current_run_id": "",
            "next_action_hint": "select_next_project",
            "last_run_state": "finalize_negative",
        }],
        paper_rows=[],
    ))

    assert queue_upserts
    params = queue_upserts[0]
    assert params[1] == "reconciling"
    assert params[9] == ""
    assert params[10] == "session-active"
    assert params[11] == "wake_received"
    assert params[13] == "await_callback"


def test_supabase_import_snapshot_idempotency_replay_does_not_connect(monkeypatch) -> None:
    store = SupabaseControlPlaneStore("postgres://example", connect=lambda: None)
    monkeypatch.setattr(store, "append_event", lambda **kwargs: (7, False))

    def fail_connect():
        raise AssertionError("duplicate import snapshot must not mutate rows")

    monkeypatch.setattr(store, "_connect", fail_connect)

    inserted, projects, queue_items, papers = store.import_snapshot(ImportSnapshotRequest(
        idempotency_key="supabase-import-replay-no-connect",
        queue_rows=[{
            "project_id": "idea-supabase-replay",
            "project_name": "Supabase Replay",
            "status": "queued",
        }],
        paper_rows=[],
    ))

    assert inserted is False
    assert (projects, queue_items, papers) == (0, 0, 0)


def test_supabase_queue_rows_query_prefers_run_specific_project_decisions() -> None:
    store = s.SupabaseReadOnlyControlPlaneStore("postgres://example", connect=lambda: None)

    sql = " ".join(store._queue_rows_query("where q.project_id = %s").split()).lower()

    assert "case when d.run_id = nullif(q.current_run_id, '') then 0 else 1 end" in sql


def test_supabase_queue_rows_query_treats_null_current_run_as_project_level_paper_join() -> None:
    store = s.SupabaseReadOnlyControlPlaneStore("postgres://example", connect=lambda: None)

    sql = " ".join(store._queue_rows_query("where q.project_id = %s").split()).lower()

    assert "coalesce(q.current_run_id, '') = '' or pa.run_id = q.current_run_id" in sql
    assert "q.current_run_id = '' or pa.run_id = q.current_run_id" not in sql
