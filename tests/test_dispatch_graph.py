from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from enoch_control_plane.control_plane.graphs import build_dispatch_graph


class FakeDispatchStore:
    def __init__(self, *, queue_paused: bool) -> None:
        self.queue_paused = queue_paused
        self.next_dispatch_candidate_calls = 0
        self.dispatch_next_dry_run_calls = 0
        self.active_items_calls = 0
        self.candidate = {"project_id": "queued", "project_name": "Queued"}

    def flags(self) -> SimpleNamespace:
        return SimpleNamespace(
            queue_paused=self.queue_paused,
            pause_reason="maintenance window" if self.queue_paused else "",
        )

    def active_items(self) -> list[dict[str, str]]:
        self.active_items_calls += 1
        return []

    def next_dispatch_candidate(self) -> dict[str, str] | None:
        self.next_dispatch_candidate_calls += 1
        return self.candidate

    def dispatch_next_dry_run(
        self, *, requested_by: str
    ) -> tuple[str, dict[str, str] | None, int | None, str]:
        self.dispatch_next_dry_run_calls += 1
        return "dry_run_dispatch", self.candidate, 123, f"requested by {requested_by}"


def test_dispatch_graph_paused_branch_is_pure_read() -> None:
    store = FakeDispatchStore(queue_paused=True)
    graph = build_dispatch_graph(store)  # type: ignore[arg-type]

    result: dict[str, Any] = graph.invoke({"requested_by": "pytest"})

    assert result["action"] == "paused"
    assert result["candidate"] is None
    assert result["event_id"] is None
    assert result["reason"] == "maintenance window"
    assert store.next_dispatch_candidate_calls == 0
    assert store.dispatch_next_dry_run_calls == 0
    assert store.active_items_calls == 1


def test_dispatch_graph_open_lane_records_dry_run_once() -> None:
    store = FakeDispatchStore(queue_paused=False)
    graph = build_dispatch_graph(store)  # type: ignore[arg-type]

    result: dict[str, Any] = graph.invoke({"requested_by": "pytest"})

    assert result["action"] == "dry_run_dispatch"
    assert result["candidate"] == store.candidate
    assert result["event_id"] == 123
    assert result["reason"] == "requested by pytest"
    assert store.next_dispatch_candidate_calls == 1
    assert store.dispatch_next_dry_run_calls == 1
    assert store.active_items_calls == 2
