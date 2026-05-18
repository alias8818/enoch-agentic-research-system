from __future__ import annotations

import pytest

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


def test_supabase_native_intake_row_failure_does_not_consume_idempotency_key(monkeypatch) -> None:
    store = SupabaseControlPlaneStore("postgres://example", connect=lambda: None)
    events: dict[str, tuple[int, str]] = {}
    projects: set[str] = set()
    queue_items: set[str] = set()
    fail_project_insert = True

    class Cursor:
        def __init__(self, conn):
            self.conn = conn
            self._next = None
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def execute(self, sql, params=()):  # noqa: ANN001 - lightweight DB fake
            nonlocal fail_project_insert
            normalized = " ".join(str(sql).lower().split())
            if normalized.startswith("select event_id"):
                event = self.conn.pending_events.get(params[0])
                self._next = None if event is None else {"event_id": event[0], "payload_hash": event[1]}
            elif normalized.startswith("insert into control_events"):
                event_id = len(self.conn.pending_events) + 1
                self.conn.pending_events[params[0]] = (event_id, params[5])
                self._next = {"event_id": event_id}
            elif normalized.startswith("select 1 from queue_items"):
                self._next = None
            elif normalized.startswith("insert into ideas"):
                return self
            elif normalized.startswith("insert into projects"):
                if fail_project_insert:
                    fail_project_insert = False
                    raise RuntimeError("simulated native intake project write failure")
                self.conn.pending_projects.add(params[0])
            elif normalized.startswith("insert into queue_items"):
                self.conn.pending_queue_items.add(params[0])
            return self
        def fetchone(self):
            value = self._next
            self._next = None
            return value

    class Conn:
        def __enter__(self):
            self.pending_events = dict(events)
            self.pending_projects = set(projects)
            self.pending_queue_items = set(queue_items)
            return self
        def __exit__(self, exc_type, *_args):
            if exc_type is None:
                events.update(self.pending_events)
                projects.update(self.pending_projects)
                queue_items.update(self.pending_queue_items)
            return False
        def cursor(self): return Cursor(self)

    monkeypatch.setattr(store, "_connect", lambda: Conn())
    request = IdeaIntakeRequest(
        idempotency_key="supabase-native-intake-atomic-key",
        dry_run=False,
        ideas=[{
            "idea_id": "supabase-native-intake-atomic",
            "title": "Supabase Native Intake Atomic",
            "idea_status": "testing",
        }],
    )

    try:
        store.ingest_ideas(request)
    except RuntimeError as exc:
        assert "simulated native intake project write failure" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("expected simulated project write failure")
    inserted, created, updated, skipped, _candidates, skipped_rows = store.ingest_ideas(request)

    assert inserted is True
    assert (created, updated, skipped) == (1, 0, 0)
    assert skipped_rows == []
    assert projects == {"supabase-native-intake-atomic"}
    assert queue_items == {"supabase-native-intake-atomic"}


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


def test_supabase_launch_followup_append_failure_does_not_queue_followup(monkeypatch) -> None:
    store = SupabaseControlPlaneStore("postgres://example", connect=lambda: None)
    candidate = {
        "project_id": "parent-supabase-followup-atomic",
        "project_name": "Parent Supabase Followup Atomic",
        "current_run_id": "run-parent",
        "followup_depth": 1,
        "followup_type": "deepen",
        "followup_title": "Atomic Supabase Followup",
        "followup_hypothesis": "signal holds",
        "followup_required_evidence": ["metric", "ablation"],
        "followup_success_threshold": "beats baseline",
        "followup_stop_condition": "no lift",
        "machine_target": "gb10",
        "model": "gpt-5.5",
        "sandbox": "danger-full-access",
        "selection_rank": 40,
        "dispatch_priority": 40,
    }
    ideas: set[str] = set()
    projects: set[str] = set()
    queue_items: set[str] = set()
    monkeypatch.setattr(store, "next_followup_candidate", lambda **kwargs: candidate)

    class Cursor:
        def __init__(self, conn): self.conn = conn
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def execute(self, sql, params=()):  # noqa: ANN001 - lightweight DB fake
            normalized = " ".join(str(sql).lower().split())
            if normalized.startswith("insert into ideas"):
                self.conn.pending_ideas.add(params[0])
            elif normalized.startswith("insert into projects"):
                self.conn.pending_projects.add(params[0])
            elif normalized.startswith("insert into queue_items"):
                self.conn.pending_queue_items.add(params[0])
            return self

    class Conn:
        def __enter__(self):
            self.pending_ideas = set(ideas)
            self.pending_projects = set(projects)
            self.pending_queue_items = set(queue_items)
            return self
        def __exit__(self, exc_type, *_args):
            if exc_type is None:
                ideas.update(self.pending_ideas)
                projects.update(self.pending_projects)
                queue_items.update(self.pending_queue_items)
            return False
        def cursor(self): return Cursor(self)

    def fail_append_event(*_args, **_kwargs):
        raise RuntimeError("simulated follow-up event write failure")

    monkeypatch.setattr(store, "_connect", lambda: Conn())
    monkeypatch.setattr(store, "_append_event_in_cursor", fail_append_event)

    try:
        store.launch_followup_candidate(dry_run=False, requested_by="test")
    except RuntimeError as exc:
        assert "simulated follow-up event write failure" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("expected simulated event write failure")

    assert ideas == set()
    assert projects == set()
    assert queue_items == set()


def test_supabase_prepare_finalization_event_failure_restores_manifest(monkeypatch, tmp_path) -> None:
    store = SupabaseControlPlaneStore("postgres://example", connect=lambda: None)
    monkeypatch.setenv("ENOCH_SUPABASE_FINALIZATION_ROOT", str(tmp_path / "packages"))
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    for filename in ["paper.md", "paper.tex", "evidence.json", "claims.json", "manifest.json"]:
        (project_dir / filename).write_text("{}" if filename.endswith(".json") else "content", encoding="utf-8")
    paper_id = "supabase-package-event-fail:run-1:arxiv_draft"
    review_row = {
        "paper_id": paper_id,
        "automation_status": "claimed",
        "automation_actor": "alice",
        "decision_summary": "",
        "checklist_json": {},
    }
    paper = {
        "paper_id": paper_id,
        "project_id": "supabase-package-event-fail",
        "project_name": "Supabase Package Event Fail",
        "paper_status": "publication_draft",
        "project_dir": str(project_dir),
        "draft_markdown_path": "paper.md",
        "draft_latex_path": "paper.tex",
        "evidence_bundle_path": "evidence.json",
        "claim_ledger_path": "claims.json",
        "manifest_path": "manifest.json",
    }
    monkeypatch.setattr(store, "_require_paper_review", lambda _paper_id: review_row)
    monkeypatch.setattr(store, "paper_row", lambda _paper_id: paper)
    monkeypatch.setattr(store, "paper_review_checklist", lambda _paper_id: {})
    monkeypatch.setattr(store, "paper_review_row", lambda _paper_id: dict(review_row, review_status=review_row["automation_status"], finalization_package_path=""))
    package_path = store._finalization_manifest_path(paper_id, "supabase-package-event-fails")
    package_path.parent.mkdir(parents=True, exist_ok=True)
    package_path.write_text("previous manifest", encoding="utf-8")

    class Cursor:
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def execute(self, *_args, **_kwargs): return self

    class Conn:
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def cursor(self): return Cursor()

    def fail_append_event(*_args, **_kwargs):
        raise RuntimeError("simulated finalization event write failure")

    monkeypatch.setattr(store, "_replayed_event_id", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(store, "_connect", lambda: Conn())
    monkeypatch.setattr(store, "_append_event_in_cursor", fail_append_event)

    try:
        store.prepare_paper_review_finalization_package(
            paper_id,
            s.PaperReviewPrepareFinalizationRequest(idempotency_key="supabase-package-event-fails", requested_by="alice", target_label="first-paper", dry_run=False),
            require_approval=False,
        )
    except RuntimeError as exc:
        assert "simulated finalization event write failure" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("expected simulated event write failure")

    assert package_path.read_text(encoding="utf-8") == "previous manifest"
    assert review_row["automation_status"] == "claimed"


def test_supabase_claim_paper_review_update_failure_does_not_consume_idempotency_key(monkeypatch) -> None:
    store = SupabaseControlPlaneStore("postgres://example", connect=lambda: None)
    paper_id = "supabase-claim-atomic:run-1:arxiv_draft"
    review_row = {
        "paper_id": paper_id,
        "automation_status": "queued",
        "automation_actor": "",
        "blocker": "",
        "checklist_json": {},
    }
    events: dict[str, tuple[int, str]] = {}
    fail_review_update = True
    monkeypatch.setattr(store, "_require_paper_review", lambda _paper_id: review_row)
    monkeypatch.setattr(store, "paper_review_row", lambda _paper_id: dict(review_row, review_status=review_row["automation_status"], reviewer=review_row["automation_actor"]))

    class Cursor:
        def __init__(self, conn):
            self.conn = conn
            self._next = None
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def execute(self, sql, params=()):  # noqa: ANN001 - lightweight DB fake
            nonlocal fail_review_update
            normalized = " ".join(str(sql).lower().split())
            if normalized.startswith("select event_id"):
                event = self.conn.pending_events.get(params[0])
                self._next = None if event is None else {"event_id": event[0], "payload_hash": event[1]}
            elif normalized.startswith("insert into control_events"):
                event_id = len(self.conn.pending_events) + 1
                self.conn.pending_events[params[0]] = (event_id, params[5])
                self._next = {"event_id": event_id}
            elif normalized.startswith("update publication_automation_items"):
                if fail_review_update:
                    fail_review_update = False
                    raise RuntimeError("simulated paper review claim update failure")
                self.conn.pending_review.update({
                    "automation_status": params[0],
                    "automation_actor": params[1],
                    "blocker": params[2],
                    "claimed_at": params[3],
                    "checklist_json": params[4],
                })
            return self
        def fetchone(self):
            value = self._next
            self._next = None
            return value

    class Conn:
        def __enter__(self):
            self.pending_events = dict(events)
            self.pending_review = dict(review_row)
            return self
        def __exit__(self, exc_type, *_args):
            if exc_type is None:
                events.update(self.pending_events)
                review_row.update(self.pending_review)
            return False
        def cursor(self): return Cursor(self)

    monkeypatch.setattr(store, "_connect", lambda: Conn())

    try:
        store.claim_paper_review(paper_id, s.PaperReviewClaimRequest(idempotency_key="supabase-claim-atomic-key", requested_by="alice", reviewer="alice"))
    except RuntimeError as exc:
        assert "simulated paper review claim update failure" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("expected simulated update failure")
    event_id, inserted, item = store.claim_paper_review(paper_id, s.PaperReviewClaimRequest(idempotency_key="supabase-claim-atomic-key", requested_by="alice", reviewer="alice"))

    assert inserted is True
    assert event_id == 1
    assert item["review_status"] == "claimed"
    assert item["reviewer"] == "alice"


def test_supabase_backfill_paper_reviews_row_failure_does_not_consume_idempotency_key(monkeypatch) -> None:
    store = SupabaseControlPlaneStore("postgres://example", connect=lambda: None)
    paper_id = "supabase-backfill-atomic:run-1:arxiv_draft"
    monkeypatch.setattr(store, "paper_rows", lambda: [{
        "paper_id": paper_id,
        "project_id": "supabase-backfill-atomic",
        "paper_status": "publication_draft",
        "draft_markdown_path": "paper.md",
        "draft_latex_path": "paper.tex",
        "evidence_bundle_path": "evidence.json",
        "claim_ledger_path": "claims.json",
        "manifest_path": "manifest.json",
    }])
    monkeypatch.setattr(store, "queue_row", lambda _project_id: {})
    events: dict[str, tuple[int, str]] = {}
    reviews: dict[str, dict] = {}
    fail_review_insert = True

    class Cursor:
        def __init__(self, conn):
            self.conn = conn
            self._next = None
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def execute(self, sql, params=()):  # noqa: ANN001 - lightweight DB fake
            nonlocal fail_review_insert
            normalized = " ".join(str(sql).lower().split())
            if normalized.startswith("select event_id"):
                event = self.conn.pending_events.get(params[0])
                self._next = None if event is None else {"event_id": event[0], "payload_hash": event[1]}
            elif normalized.startswith("insert into control_events"):
                event_id = len(self.conn.pending_events) + 1
                self.conn.pending_events[params[0]] = (event_id, params[5])
                self._next = {"event_id": event_id}
            elif normalized.startswith("select * from publication_automation_items"):
                self._next = self.conn.pending_reviews.get(params[0])
            elif normalized.startswith("insert into publication_automation_items"):
                if fail_review_insert:
                    fail_review_insert = False
                    raise RuntimeError("simulated paper review backfill insert failure")
                self.conn.pending_reviews[params[0]] = {
                    "paper_id": params[0],
                    "automation_status": params[1],
                }
            return self
        def fetchone(self):
            value = self._next
            self._next = None
            return value

    class Conn:
        def __enter__(self):
            self.pending_events = dict(events)
            self.pending_reviews = dict(reviews)
            return self
        def __exit__(self, exc_type, *_args):
            if exc_type is None:
                events.update(self.pending_events)
                reviews.update(self.pending_reviews)
            return False
        def cursor(self): return Cursor(self)

    monkeypatch.setattr(store, "_connect", lambda: Conn())
    request = s.PaperReviewBackfillRequest(idempotency_key="supabase-backfill-atomic-key", dry_run=False)

    try:
        store.backfill_paper_reviews(request)
    except RuntimeError as exc:
        assert "simulated paper review backfill insert failure" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("expected simulated insert failure")
    inserted, created, updated, skipped, errors = store.backfill_paper_reviews(request)

    assert inserted is True
    assert (created, updated, skipped) == (1, 0, 0)
    assert errors == []
    assert reviews[paper_id]["automation_status"] == "queued"


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
    events: dict[str, dict] = {}

    def fake_one(sql, params=()):  # noqa: ANN001 - lightweight store fake
        if "from control_events" in sql:
                key = params[0]
                if key in events:
                    return events[key]
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
        event_id = len(events) + 1
        events[idempotency_key] = {
            "event_id": event_id,
            "event_type": event_type,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "payload_hash": s._hash(payload),
        }
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


def test_supabase_replayed_event_id_conflicts_on_different_event_identity(monkeypatch) -> None:
    store = SupabaseControlPlaneStore("postgres://example", connect=lambda: None)
    payload = {"same": True}

    def fake_one(sql, params=()):  # noqa: ANN001 - focused helper invariant
        assert "from control_events" in sql
        assert params == ("same-key",)
        return {
            "event_id": 7,
            "event_type": "first.event",
            "entity_type": "project",
            "entity_id": "project-1",
            "payload_hash": s._hash(payload),
        }

    monkeypatch.setattr(store, "_one", fake_one)

    assert (
        store._replayed_event_id(  # noqa: SLF001 - focused invariant test
            "same-key",
            payload,
            event_type="first.event",
            entity_type="project",
            entity_id="project-1",
        )
        == 7
    )
    try:
        store._replayed_event_id(  # noqa: SLF001 - focused invariant test
            "same-key",
            payload,
            event_type="second.event",
            entity_type="project",
            entity_id="project-1",
        )
    except s.IdempotencyConflict:
        pass
    else:
        raise AssertionError("different event_type must conflict")

    try:
        store._replayed_event_id(  # noqa: SLF001 - focused invariant test
            "same-key",
            payload,
            event_type="first.event",
            entity_type="run",
            entity_id="run-1",
        )
    except s.IdempotencyConflict:
        pass
    else:
        raise AssertionError("different entity identity must conflict")


def test_supabase_dispatch_started_replay_does_not_mutate_queue(monkeypatch) -> None:
    store = SupabaseControlPlaneStore("postgres://example", connect=lambda: None)
    executed: list[str] = []

    class Cursor:
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def execute(self, sql, params=()):  # noqa: ANN001 - lightweight cursor fake
            del params
            executed.append(str(sql))
            return None

    class Conn:
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def cursor(self): return Cursor()

    def fake_append_event(_cur, *, idempotency_key, event_type, entity_type, entity_id, payload):  # noqa: ANN001 - signature mirrors store
        del idempotency_key, event_type, entity_type, entity_id, payload
        return 7, False

    monkeypatch.setattr(store, "_connect", lambda: Conn())
    monkeypatch.setattr(store, "_append_event_in_cursor", fake_append_event)
    monkeypatch.setattr(store, "queue_row", lambda project_id: {"project_id": project_id, "status": "completed", "last_run_state": "wake_ready"})

    event_id, row = store.mark_dispatch_started(
        project_id="idea-dispatch-replay",
        run_id="run-dispatch-replay",
        session_id="session-dispatch-replay",
        dispatch_payload={"project_id": "idea-dispatch-replay"},
        requested_by="test",
    )

    assert event_id == 7
    assert row["status"] == "completed"
    assert executed == []


def test_supabase_dispatch_claim_replay_does_not_mutate_queue(monkeypatch) -> None:
    store = SupabaseControlPlaneStore("postgres://example", connect=lambda: None)
    executed: list[str] = []

    class Result:
        rowcount = 1

    class Cursor:
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def execute(self, sql, params=()):  # noqa: ANN001 - lightweight cursor fake
            del params
            executed.append(" ".join(str(sql).lower().split()))
            return Result()

    class Conn:
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def cursor(self): return Cursor()

    monkeypatch.setattr(store, "_connect", lambda: Conn())
    monkeypatch.setattr(store, "_replayed_event_id", lambda _key, _payload, **_identity: 7)
    monkeypatch.setattr(store, "queue_row", lambda project_id: {"project_id": project_id, "status": "queued", "current_run_id": ""})

    replay = store.claim_dispatch_candidate(
        project_id="idea-claim-replay",
        run_id="run-claim-replay",
        requested_by="test",
    )

    assert replay is None
    assert executed == []


def test_supabase_release_dispatch_claim_does_not_emit_event_without_update(monkeypatch) -> None:
    store = SupabaseControlPlaneStore("postgres://example", connect=lambda: None)
    append_calls: list[dict] = []

    class Result:
        rowcount = 0

    class Cursor:
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def execute(self, *args, **kwargs):  # noqa: ANN001 - lightweight cursor fake
            del args, kwargs
            return Result()

    class Conn:
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def cursor(self): return Cursor()

    def fake_append_event(_cur, **kwargs):  # noqa: ANN001 - signature mirrors store
        append_calls.append(kwargs)
        return 1, True

    monkeypatch.setattr(store, "_connect", lambda: Conn())
    monkeypatch.setattr(store, "_append_event_in_cursor", fake_append_event)
    monkeypatch.setattr(store, "queue_row", lambda project_id: {"project_id": project_id, "status": "queued"})

    row = store.release_dispatch_claim(
        project_id="idea-release-stale",
        run_id="stale-run",
        reason="stale worker preflight failure",
    )

    assert row["status"] == "queued"
    assert append_calls == []


def test_supabase_worker_callback_without_identifiers_dedupes_by_payload(monkeypatch) -> None:
    store = SupabaseControlPlaneStore("postgres://example", connect=lambda: None)
    events: dict[str, dict] = {}

    def fake_one(sql, params=()):  # noqa: ANN001 - lightweight store fake
        if "from control_events" in sql:
                key = params[0]
                if key in events:
                    return events[key]
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
        event_id = len(events) + 1
        events[idempotency_key] = {
            "event_id": event_id,
            "event_type": event_type,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "payload_hash": s._hash(payload),
        }
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



def test_supabase_mark_queue_item_paused_append_failure_does_not_mutate_queue_state(monkeypatch) -> None:
    store = SupabaseControlPlaneStore("postgres://example", connect=lambda: None)
    project_id = "idea-pause-item-atomic"
    queue = {
        "project_id": project_id,
        "status": "queued",
        "next_action_hint": "start_next_candidate",
        "last_result_summary": "",
    }

    class Cursor:
        rowcount = 0
        def __init__(self, conn): self.conn = conn
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def execute(self, sql, params=()):  # noqa: ANN001 - lightweight DB fake
            if "update queue_items" in str(sql).lower():
                self.rowcount = 1
                self.conn.pending_queue["status"] = params[0]
                self.conn.pending_queue["next_action_hint"] = params[1]
                self.conn.pending_queue["last_result_summary"] = params[2]
            return self

    class Conn:
        def __enter__(self):
            self.pending_queue = dict(queue)
            return self
        def __exit__(self, exc_type, *_args):
            if exc_type is None:
                queue.update(self.pending_queue)
            return False
        def cursor(self): return Cursor(self)

    def fail_append_event(*_args, **_kwargs):
        raise RuntimeError("simulated queue pause event write failure")

    monkeypatch.setattr(store, "_connect", lambda: Conn())
    monkeypatch.setattr(store, "_append_event_in_cursor", fail_append_event)

    try:
        store.mark_queue_item_paused(project_id=project_id, reason="operator pause", updated_by="test")
    except RuntimeError as exc:
        assert "simulated queue pause event write failure" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("expected simulated event write failure")

    assert queue["status"] == "queued"
    assert queue["next_action_hint"] == "start_next_candidate"
    assert queue["last_result_summary"] == ""


def test_supabase_pause_append_failure_does_not_mutate_control_flags(monkeypatch) -> None:
    store = SupabaseControlPlaneStore("postgres://example", connect=lambda: None)
    flags = {
        "queue_paused": False,
        "maintenance_mode": False,
        "pause_reason": "",
        "paused_at": None,
        "paused_by": "system",
    }

    class Cursor:
        def __init__(self, conn): self.conn = conn
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def execute(self, sql, params=()):  # noqa: ANN001 - lightweight DB fake
            if "update control_flags" in str(sql).lower():
                self.conn.pending_flags.update({
                    "queue_paused": True,
                    "maintenance_mode": params[0],
                    "pause_reason": params[1],
                    "paused_at": params[2],
                    "paused_by": params[3],
                })
            return self

    class Conn:
        def __enter__(self):
            self.pending_flags = dict(flags)
            return self
        def __exit__(self, exc_type, *_args):
            if exc_type is None:
                flags.update(self.pending_flags)
            return False
        def cursor(self): return Cursor(self)

    def fail_append_event(*_args, **_kwargs):
        raise RuntimeError("simulated pause event write failure")

    monkeypatch.setattr(store, "_connect", lambda: Conn())
    monkeypatch.setattr(store, "_append_event_in_cursor", fail_append_event)

    try:
        store.pause(reason="maintenance", paused_by="test", maintenance_mode=True)
    except RuntimeError as exc:
        assert "simulated pause event write failure" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("expected simulated event write failure")

    assert flags["queue_paused"] is False
    assert flags["maintenance_mode"] is False
    assert flags["pause_reason"] == ""


def test_supabase_resume_append_failure_does_not_mutate_control_flags(monkeypatch) -> None:
    store = SupabaseControlPlaneStore("postgres://example", connect=lambda: None)
    flags = {
        "queue_paused": True,
        "maintenance_mode": True,
        "pause_reason": "maintenance",
        "paused_at": "2026-05-17T00:00:00Z",
        "paused_by": "test",
    }

    class Cursor:
        def __init__(self, conn): self.conn = conn
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def execute(self, sql, params=()):  # noqa: ANN001 - lightweight DB fake
            if "update control_flags" in str(sql).lower():
                self.conn.pending_flags.update({
                    "queue_paused": False,
                    "maintenance_mode": params[0],
                    "pause_reason": "",
                    "paused_at": None,
                    "paused_by": params[1],
                })
            return self

    class Conn:
        def __enter__(self):
            self.pending_flags = dict(flags)
            return self
        def __exit__(self, exc_type, *_args):
            if exc_type is None:
                flags.update(self.pending_flags)
            return False
        def cursor(self): return Cursor(self)

    def fail_append_event(*_args, **_kwargs):
        raise RuntimeError("simulated resume event write failure")

    monkeypatch.setattr(store, "_connect", lambda: Conn())
    monkeypatch.setattr(store, "_append_event_in_cursor", fail_append_event)

    try:
        store.resume(resumed_by="test", maintenance_mode=False)
    except RuntimeError as exc:
        assert "simulated resume event write failure" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("expected simulated event write failure")

    assert flags["queue_paused"] is True
    assert flags["maintenance_mode"] is True
    assert flags["pause_reason"] == "maintenance"


def test_supabase_dispatch_claim_append_failure_does_not_mutate_queue_state(monkeypatch) -> None:
    store = SupabaseControlPlaneStore("postgres://example", connect=lambda: None)
    project_id = "idea-claim-atomic"
    queue = {
        "project_id": project_id,
        "status": "queued",
        "current_run_id": "",
        "next_action_hint": "start_next_candidate",
    }

    class Cursor:
        rowcount = 0
        def __init__(self, conn): self.conn = conn
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def execute(self, sql, params=()):  # noqa: ANN001 - lightweight DB fake
            normalized = " ".join(str(sql).lower().split())
            if normalized.startswith("update queue_items"):
                if self.conn.pending_queue["status"] == params[11]:
                    self.rowcount = 1
                    self.conn.pending_queue["status"] = params[0]
                    self.conn.pending_queue["current_run_id"] = params[1]
                    self.conn.pending_queue["next_action_hint"] = params[5]
                else:
                    self.rowcount = 0
            return self

    class Conn:
        def __enter__(self):
            self.pending_queue = dict(queue)
            return self
        def __exit__(self, exc_type, *_args):
            if exc_type is None:
                queue.update(self.pending_queue)
            return False
        def cursor(self): return Cursor(self)

    def fail_append_event(*_args, **_kwargs):
        raise RuntimeError("simulated claim event write failure")

    monkeypatch.setattr(store, "_connect", lambda: Conn())
    monkeypatch.setattr(store, "_replayed_event_id", lambda _key, _payload, **_identity: None)
    monkeypatch.setattr(store, "_append_event_in_cursor", fail_append_event)

    try:
        store.claim_dispatch_candidate(project_id=project_id, run_id="run-claim-atomic", requested_by="test")
    except RuntimeError as exc:
        assert "simulated claim event write failure" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("expected simulated event write failure")

    assert queue["status"] == "queued"
    assert queue["current_run_id"] == ""
    assert queue["next_action_hint"] == "start_next_candidate"


def test_supabase_dispatch_claim_release_append_failure_does_not_mutate_queue_state(monkeypatch) -> None:
    store = SupabaseControlPlaneStore("postgres://example", connect=lambda: None)
    project_id = "idea-release-atomic"
    run_id = "run-release-atomic"
    queue = {
        "project_id": project_id,
        "status": "dispatching",
        "current_run_id": run_id,
        "current_session_id": "",
        "last_run_state": "dispatching",
        "next_action_hint": "prepare_worker_dispatch",
    }

    class Cursor:
        def __init__(self, conn): self.conn = conn
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def execute(self, sql, params=()):  # noqa: ANN001 - lightweight DB fake
            normalized = " ".join(str(sql).lower().split())
            if normalized.startswith("update queue_items"):
                self.conn.pending_queue["status"] = params[0]
                self.conn.pending_queue["current_run_id"] = ""
                self.conn.pending_queue["current_session_id"] = ""
                self.conn.pending_queue["last_run_state"] = ""
                self.conn.pending_queue["next_action_hint"] = params[2]
            return self

    class Conn:
        def __enter__(self):
            self.pending_queue = dict(queue)
            return self
        def __exit__(self, exc_type, *_args):
            if exc_type is None:
                queue.update(self.pending_queue)
            return False
        def cursor(self): return Cursor(self)

    def fail_append_event(*_args, **_kwargs):
        raise RuntimeError("simulated release event write failure")

    monkeypatch.setattr(store, "_connect", lambda: Conn())
    monkeypatch.setattr(store, "_append_event_in_cursor", fail_append_event)

    try:
        store.release_dispatch_claim(project_id=project_id, run_id=run_id, reason="worker preflight failed")
    except RuntimeError as exc:
        assert "simulated release event write failure" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("expected simulated event write failure")

    assert queue["status"] == "dispatching"
    assert queue["current_run_id"] == run_id
    assert queue["last_run_state"] == "dispatching"
    assert queue["next_action_hint"] == "prepare_worker_dispatch"


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
    monkeypatch.setattr(store, "_append_event_in_cursor", lambda *args, **kwargs: (1, True))

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


def test_supabase_import_snapshot_idempotency_replay_does_not_mutate_rows(monkeypatch) -> None:
    store = SupabaseControlPlaneStore("postgres://example", connect=lambda: None)

    class Cursor:
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def execute(self, sql, params=()):  # noqa: ANN001 - lightweight DB fake
            if "insert into projects" in str(sql).lower() or "insert into queue_items" in str(sql).lower():
                raise AssertionError("duplicate import snapshot must not mutate rows")
            return self

    class Conn:
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def cursor(self): return Cursor()

    monkeypatch.setattr(store, "_connect", lambda: Conn())
    monkeypatch.setattr(store, "_append_event_in_cursor", lambda *args, **kwargs: (7, False))

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


def test_supabase_import_snapshot_row_failure_does_not_consume_idempotency_key(monkeypatch) -> None:
    store = SupabaseControlPlaneStore("postgres://example", connect=lambda: None)
    events: dict[str, tuple[int, str]] = {}
    projects: set[str] = set()
    queue_items: set[str] = set()
    fail_project_insert = True

    class Cursor:
        def __init__(self, conn):
            self.conn = conn
            self._next = None
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def execute(self, sql, params=()):  # noqa: ANN001 - lightweight DB fake
            nonlocal fail_project_insert
            normalized = " ".join(str(sql).lower().split())
            if normalized.startswith("select event_id"):
                event = self.conn.pending_events.get(params[0])
                self._next = None if event is None else {"event_id": event[0], "payload_hash": event[1]}
            elif normalized.startswith("insert into control_events"):
                event_id = len(self.conn.pending_events) + 1
                self.conn.pending_events[params[0]] = (event_id, params[5])
                self._next = {"event_id": event_id}
            elif normalized.startswith("insert into projects"):
                if fail_project_insert:
                    fail_project_insert = False
                    raise RuntimeError("simulated import row write failure")
                self.conn.pending_projects.add(params[0])
            elif normalized.startswith("select status,current_run_id"):
                self._next = None
            elif normalized.startswith("insert into queue_items"):
                self.conn.pending_queue_items.add(params[0])
            return self
        def fetchone(self):
            value = self._next
            self._next = None
            return value

    class Conn:
        def __enter__(self):
            self.pending_events = dict(events)
            self.pending_projects = set(projects)
            self.pending_queue_items = set(queue_items)
            return self
        def __exit__(self, exc_type, *_args):
            if exc_type is None:
                events.update(self.pending_events)
                projects.update(self.pending_projects)
                queue_items.update(self.pending_queue_items)
            return False
        def cursor(self): return Cursor(self)

    monkeypatch.setattr(store, "_connect", lambda: Conn())
    request = ImportSnapshotRequest(
        idempotency_key="supabase-import-row-failure-retry",
        queue_rows=[{
            "project_id": "supabase-import-retry-project",
            "project_name": "Supabase Import Retry Project",
            "status": "queued",
        }],
        paper_rows=[],
    )

    try:
        store.import_snapshot(request)
    except RuntimeError as exc:
        assert "simulated import row write failure" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("expected simulated row write failure")
    inserted, created_projects, created_queue_items, papers = store.import_snapshot(request)

    assert inserted is True
    assert (created_projects, created_queue_items, papers) == (1, 1, 0)
    assert projects == {"supabase-import-retry-project"}
    assert queue_items == {"supabase-import-retry-project"}


def test_supabase_queue_rows_query_prefers_run_specific_project_decisions() -> None:
    store = s.SupabaseReadOnlyControlPlaneStore("postgres://example", connect=lambda: None)

    sql = " ".join(store._queue_rows_query("where q.project_id = %s").split()).lower()

    assert "case when d.run_id = nullif(q.current_run_id, '') then 0 else 1 end" in sql


def test_supabase_queue_rows_query_treats_null_current_run_as_project_level_paper_join() -> None:
    store = s.SupabaseReadOnlyControlPlaneStore("postgres://example", connect=lambda: None)

    sql = " ".join(store._queue_rows_query("where q.project_id = %s").split()).lower()

    assert "coalesce(q.current_run_id, '') = '' or pa.run_id = q.current_run_id" in sql
    assert "q.current_run_id = '' or pa.run_id = q.current_run_id" not in sql


def test_supabase_append_event_idempotency_conflicts_on_different_event_identity() -> None:
    class Cursor:
        def __init__(self) -> None:
            self.row = None
            self.inserted = {"event_id": 123}
            self._last_query = ""

        def execute(self, sql, params=()):  # noqa: ANN001 - cursor test double
            lowered = " ".join(str(sql).lower().split())
            self._last_query = lowered
            if lowered.startswith("select event_id"):
                return self
            if lowered.startswith("insert into control_events"):
                self.last_insert = params
                return self
            raise AssertionError(f"unexpected sql: {sql}")

        def fetchone(self):
            if self._last_query.startswith("select event_id"):
                return self.row
            return self.inserted

    store = s.SupabaseControlPlaneStore("postgresql://example")
    cur = Cursor()
    event_id, inserted = store._append_event_in_cursor(  # noqa: SLF001 - focused adapter invariant
        cur,
        idempotency_key="same-key",
        event_type="first.event",
        entity_type="project",
        entity_id="project-1",
        payload={"same": True},
    )
    assert event_id == 123
    assert inserted is True

    payload_hash = s._hash({"same": True})
    cur.row = {
        "event_id": 123,
        "event_type": "first.event",
        "entity_type": "project",
        "entity_id": "project-1",
        "payload_hash": payload_hash,
    }
    replay_id, replay_inserted = store._append_event_in_cursor(  # noqa: SLF001
        cur,
        idempotency_key="same-key",
        event_type="first.event",
        entity_type="project",
        entity_id="project-1",
        payload={"same": True},
    )
    assert replay_id == 123
    assert replay_inserted is False

    try:
        store._append_event_in_cursor(  # noqa: SLF001
            cur,
            idempotency_key="same-key",
            event_type="second.event",
            entity_type="project",
            entity_id="project-1",
            payload={"same": True},
        )
    except s.IdempotencyConflict:
        pass
    else:  # pragma: no cover - regression guard
        raise AssertionError("expected idempotency conflict for changed event_type")


def test_supabase_promote_candidate_conflicts_on_reused_admission_key_with_different_identity() -> None:
    from enoch_control_plane.enoch_core.store import IdempotencyConflict
    from enoch_control_plane.control_plane.supabase_store import SupabaseControlPlaneStore

    store = SupabaseControlPlaneStore("postgres://example", connect=lambda: None)

    class Cursor:
        rowcount = 0
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def execute(self, sql, params=()):  # noqa: ANN001 - lightweight DB fake
            normalized = " ".join(str(sql).lower().split())
            if "from research_facility_workbench" in normalized:
                self._fetchone = {
                    "candidate_id": "candidate-1",
                    "status": "admitted",
                    "title": "Candidate 1",
                    "admission_decision": "admitted",
                    "admission_reason": "ready",
                    "admitted_idea_id": "",
                }
                return self
            if "from research_candidates" in normalized:
                self._fetchone = {
                    "candidate_id": "candidate-1",
                    "title": "Candidate 1",
                    "category": "systems",
                    "priority": "High",
                    "source_urls": [],
                    "description": "desc",
                    "hypothesis": "hyp",
                    "implementation": "impl",
                    "baseline_to_beat": "base",
                    "kill_condition": "kill",
                    "accessibility_delta": "access",
                    "expected_token_budget": "small",
                    "novelty_score": 8,
                    "machine_target": "gb10",
                    "model": "gpt-5.5",
                    "sandbox": "danger-full-access",
                    "score_breakdown": {"score": 90},
                    "raw_candidate_json": {},
                }
                return self
            if normalized.startswith("insert into ideas") or normalized.startswith("insert into projects"):
                self.rowcount = 1
                return self
            if normalized.startswith("insert into queue_items"):
                self.rowcount = 1
                return self
            if normalized.startswith("select admission_id"):
                assert params == ("research-promotion:candidate-1:candidate-1",)
                self._fetchone = {
                    "admission_id": 13,
                    "candidate_id": "candidate-1",
                    "admission_decision": "rejected",
                    "admission_reason": "old contrary decision",
                    "score_breakdown": {},
                    "admitted_idea_id": None,
                    "operator": "unit",
                }
                return self
            if normalized.startswith("insert into research_admissions"):
                raise AssertionError("conflicting admission replay must not insert")
            if normalized.startswith("insert into research_lineage"):
                self.rowcount = 1
                return self
            raise AssertionError(normalized)
        def fetchone(self):
            return getattr(self, "_fetchone", None)

    class Conn:
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def cursor(self): return Cursor()

    store._connect = lambda: Conn()  # type: ignore[method-assign]

    with pytest.raises(IdempotencyConflict):
        store.promote_research_candidate("candidate-1", requested_by="unit", dry_run=False)
