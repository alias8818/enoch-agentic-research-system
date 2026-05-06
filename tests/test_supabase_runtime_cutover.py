from typing import Any, Sequence

from scripts.validate_supabase_runtime_cutover import compare

from omx_wake_gate.control_plane import read_models
from omx_wake_gate.control_plane.supabase_store import SupabaseControlPlaneStore, _decision_gate_state, _decision_summary


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
