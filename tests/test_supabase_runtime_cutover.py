from typing import Any, Sequence
import inspect

from scripts.validate_supabase_runtime_cutover import compare

from enoch_control_plane.control_plane import read_models
from enoch_control_plane.control_plane.supabase_store import SupabaseControlPlaneStore, _decision_gate_state, _decision_summary


def test_compare_accepts_matching_operator_counts_and_safe_pause() -> None:
    live = {
        "write_needed": 0,
        "raw_completed_no_paper_candidates": 215,
        "not_writable_by_decision_gate": 215,
        "publication_ready": 371,
        "needs_attention": 9,
        "flags": {"queue_paused": True, "maintenance_mode": True},
        "state_counts": {"queue_total": 482},
        "paper_counts": {"all": 496},
        "enoch_core": {"store_backend": "sqlite", "db_path": "/tmp/enoch_core.sqlite3"},
        "enoch_core": {"store_backend": "supabase", "db_path": "supabase"},
    }
    supabase = {
        "write_needed": 0,
        "raw_completed_no_paper_candidates": 215,
        "not_writable_by_decision_gate": 215,
        "publication_ready": 371,
        "needs_attention": 9,
        "table_counts": {"queue_items": 482, "papers": 496, "core_events": 0, "core_snapshots": 0},
    }

    result = compare(live, supabase)

    assert result.ok
    assert result.failures == []


def test_compare_rejects_mixed_ledgers_and_unpaused_runtime() -> None:
    live = {
        "write_needed": 0,
        "raw_completed_no_paper_candidates": 215,
        "not_writable_by_decision_gate": 215,
        "publication_ready": 371,
        "needs_attention": 9,
        "flags": {"queue_paused": False, "maintenance_mode": False},
        "state_counts": {"queue_total": 482},
        "paper_counts": {"all": 496},
    }
    supabase = {
        "write_needed": 1,
        "raw_completed_no_paper_candidates": 216,
        "not_writable_by_decision_gate": 215,
        "publication_ready": 374,
        "needs_attention": 9,
        "table_counts": {"queue_items": 481, "papers": 495},
    }

    result = compare(live, supabase)

    assert not result.ok
    assert any("write_needed mismatch" in failure for failure in result.failures)
    assert any("raw_completed_no_paper_candidates mismatch" in failure for failure in result.failures)
    assert any("publication_ready mismatch" in failure for failure in result.failures)
    assert any("queue_paused" in failure for failure in result.failures)
    assert any("queue_items count is lower" in failure for failure in result.failures)
    assert any("papers count does not match" in failure for failure in result.failures)
    assert any("enoch-core store_backend" in failure for failure in result.failures)
    assert any("Enoch core tables are missing" in failure for failure in result.failures)


def test_supabase_runtime_store_exposes_dashboard_and_dispatch_methods() -> None:
    store = SupabaseControlPlaneStore("postgresql://example.invalid/postgres", connect=lambda: None)

    for method_name in (
        "active_items",
        "next_dispatch_candidate",
        "dispatch_next_dry_run",
        "status_counts",
        "queue_rows",
        "paper_rows",
        "run_rows",
        "export_snapshot",
        "latest_dashboard_observations",
        "record_project_decision_gate",
    ):
        assert callable(getattr(store, method_name))


def test_supabase_runtime_store_reuses_connection_for_dashboard_reads() -> None:
    class FakeCursor:
        def __init__(self, conn: "FakeConnection") -> None:
            self.conn = conn

        def __enter__(self) -> "FakeCursor":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def execute(self, sql: str, params: Sequence[Any] = ()) -> None:
            self.conn.executed.append((sql, tuple(params)))

        def fetchall(self) -> list[dict[str, Any]]:
            return []

    class FakeConnection:
        def __init__(self) -> None:
            self.closed = False
            self.commits = 0
            self.closes = 0
            self.executed: list[tuple[str, tuple[Any, ...]]] = []

        def cursor(self) -> FakeCursor:
            return FakeCursor(self)

        def commit(self) -> None:
            self.commits += 1

        def rollback(self) -> None:
            return None

        def close(self) -> None:
            self.closes += 1
            self.closed = True

    connections: list[FakeConnection] = []

    def connect() -> FakeConnection:
        conn = FakeConnection()
        connections.append(conn)
        return conn

    store = SupabaseControlPlaneStore("postgresql://example.invalid/postgres", connect=connect)
    store._external_connect_factory = False

    store._query("select 1")
    store._query("select 2")

    assert len(connections) == 1
    assert connections[0].commits == 2
    assert connections[0].closes == 0
    assert any("set search_path" in sql for sql, _ in connections[0].executed)


def test_supabase_legacy_notion_intake_preserves_runtime_project_dir() -> None:
    source = inspect.getsource(SupabaseControlPlaneStore.ingest_notion_ideas)

    assert "project_dir=projects.project_dir" in source
    assert "notion_page_url=coalesce(nullif(excluded.notion_page_url,''), projects.notion_page_url)" in source


def test_project_decision_gate_state_classifies_mixed_as_unknown_not_writable() -> None:
    gate = {
        "eligible": False,
        "reason": "project decision lacks positive draft signal",
        "values": [
            (".omx/project_decision.json", "project_decision", "continue"),
            (".omx/project_decision.json", "hypothesis_status", "mixed"),
        ],
    }

    assert _decision_gate_state(gate) == "unknown"
    assert _decision_summary(gate) == "continue (project decision lacks positive draft signal)"


def test_project_decision_gate_state_classifies_finalize_negative_with_mixed_as_negative() -> None:
    gate = {
        "eligible": False,
        "reason": "project decision is not positive",
        "decision": "finalize_negative",
        "values": [
            (".omx/project_decision.json", "project_decision", "finalize_negative"),
            (".omx/project_decision.json", "hypothesis_status", "mixed"),
        ],
    }

    assert _decision_gate_state(gate) == "negative"

def test_project_decision_summary_prefers_status_over_long_recommendation() -> None:
    gate = {
        "eligible": False,
        "reason": "project decision lacks positive draft signal",
        "values": [
            (".omx/project_decision.json", "recommendation", "Do not scale this formulation without a revised mechanism."),
            (".omx/project_decision.json", "status", "negative_result"),
        ],
    }

    assert _decision_summary(gate) == "negative_result (project decision lacks positive draft signal)"


class _CapturingSupabaseStore(SupabaseControlPlaneStore):
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        super().__init__("postgresql://example.invalid/postgres", connect=lambda: None)
        self.rows = rows
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def _query(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        self.calls.append((sql, tuple(params)))
        return self.rows


def test_supabase_event_page_uses_bounded_sql_pagination_without_payload_body() -> None:
    store = _CapturingSupabaseStore(
        [
            {
                "event_id": event_id,
                "idempotency_key": f"event-{event_id}",
                "event_type": "paper.draft",
                "entity_type": "paper",
                "entity_id": "paper-1",
                "payload_bytes": 1234,
                "created_at": "2026-05-06T12:00:00+00:00",
            }
            for event_id in (300, 299, 298)
        ]
    )

    rows, next_cursor, has_more = store.event_page(page_size=2, cursor="301", include_payload=False)

    assert [row["event_id"] for row in rows] == [300, 299]
    assert rows[0]["payload_summary"] == {"keys": [], "bytes": 1234}
    assert next_cursor == "299"
    assert has_more is True
    assert len(store.calls) == 1
    sql, params = store.calls[0]
    normalized_sql = " ".join(sql.lower().split())
    assert "select *" not in normalized_sql
    assert "payload_json," not in normalized_sql
    assert "pg_column_size(payload_json) as payload_bytes" in normalized_sql
    assert "order by event_id desc limit %s" in normalized_sql
    assert params == (301, 3)


def test_supabase_event_page_offset_sorts_stay_bounded() -> None:
    store = _CapturingSupabaseStore([])

    store.event_page(page_size=50, cursor="200", include_payload=False, sort="type")

    sql, params = store.calls[0]
    normalized_sql = " ".join(sql.lower().split())
    assert "limit %s offset %s" in normalized_sql
    assert "select *" not in normalized_sql
    assert params == (51, 200)


def test_supabase_queue_page_pushes_filters_sort_and_pagination_into_sql() -> None:
    store = _CapturingSupabaseStore([{"project_id": "p1"}, {"project_id": "p2"}, {"project_id": "p3"}])

    rows, next_cursor, has_more = store.queue_page(
        queue="blocked",
        search="decoder",
        page_size=2,
        cursor="50",
        sort="recent",
    )

    assert [row["project_id"] for row in rows] == ["p1", "p2"]
    assert next_cursor == "52"
    assert has_more is True
    assert len(store.calls) == 1
    sql, params = store.calls[0]
    normalized_sql = " ".join(sql.lower().split())
    assert "from queue_items q" in normalized_sql
    assert "manual_review_required = true or q.status in" in normalized_sql
    assert "p.project_name ilike %s" in normalized_sql
    assert "order by q.updated_at desc, q.project_id desc limit %s offset %s" in normalized_sql
    assert params[-2:] == (3, 50)


def test_supabase_paper_page_pushes_filters_sort_and_pagination_into_sql() -> None:
    store = _CapturingSupabaseStore([{"paper_id": "paper-1"}, {"paper_id": "paper-2"}])

    rows, next_cursor, has_more = store.paper_page(
        status="publication_draft",
        project_id="project-1",
        search="mamba",
        page_size=1,
        cursor="10",
        sort="title",
    )

    assert rows == [{"paper_id": "paper-1"}]
    assert next_cursor == "11"
    assert has_more is True
    sql, params = store.calls[0]
    normalized_sql = " ".join(sql.lower().split())
    assert "from papers pa" in normalized_sql
    assert "pa.paper_status = %s" in normalized_sql
    assert "pa.project_id = %s" in normalized_sql
    assert "p.project_name ilike %s" in normalized_sql
    assert "order by lower(coalesce(p.project_name, '')) asc, pa.updated_at desc, pa.paper_id desc limit %s offset %s" in normalized_sql
    assert params[-2:] == (2, 10)


def test_supabase_run_page_pushes_filters_sort_and_pagination_into_sql() -> None:
    store = _CapturingSupabaseStore([{"run_id": "run-1"}, {"run_id": "run-2"}, {"run_id": "run-3"}])

    rows, next_cursor, has_more = store.run_page(
        state="completed",
        project_id="project-1",
        search="callback",
        page_size=2,
        cursor="0",
        sort="state",
    )

    assert [row["run_id"] for row in rows] == ["run-1", "run-2"]
    assert next_cursor == "2"
    assert has_more is True
    sql, params = store.calls[0]
    normalized_sql = " ".join(sql.lower().split())
    assert "select r.* from runs r" in normalized_sql
    assert "(r.state = %s or r.gate_state = %s)" in normalized_sql
    assert "r.project_id = %s" in normalized_sql
    assert "r.current_activity ilike %s" in normalized_sql
    assert "order by r.state asc, r.updated_at desc, r.run_id desc limit %s offset %s" in normalized_sql
    assert params[-2:] == (3, 0)


def test_overview_uses_supabase_batched_read_parts_when_available() -> None:
    class BatchedOnlyStore:
        def __init__(self) -> None:
            self.called = False

        def overview_read_model_parts(self, *, active_limit: int, event_limit: int) -> dict[str, Any]:
            self.called = True
            assert active_limit == 1
            assert event_limit == 0
            return {
                "counts": {"all": 0, "active": 0, "queued": 0, "blocked": 0, "paused": 0, "completed": 0},
                "paper_counts": {"all": 0},
                "active_items": [],
                "next_candidate": None,
                "raw_queue_rows": [],
                "raw_paper_rows": [],
                "events_page": ([], None, False),
            }

        def __getattr__(self, name: str) -> Any:
            raise AssertionError(f"overview should not call unbatched store method {name}")

    store = BatchedOnlyStore()

    data = read_models.overview(store, active_limit=1, event_limit=0)  # type: ignore[arg-type]

    assert store.called
    assert data["paper_pipeline"]["write_needed"] == 0
    assert data["recent_events"] == []
