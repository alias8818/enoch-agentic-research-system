from __future__ import annotations

from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from .store import ControlPlaneStore


class DispatchGraphState(TypedDict, total=False):
    requested_by: str
    dry_run: bool
    action: str
    reason: str
    candidate: dict[str, Any] | None
    active_count: int
    event_id: int | None
    queue_paused: bool


def build_dispatch_graph(store: ControlPlaneStore):
    """Build the MVP LangGraph controller graph for guarded dispatch.

    Live dispatch remains intentionally disabled in this first slice; the graph
    proves the control-plane semantics that matter before GB10 work resumes:
    pause gate, single-lane gate, candidate selection, and durable eventing.
    """

    def load_control_flags(state: DispatchGraphState) -> DispatchGraphState:
        flags = store.flags()
        return {**state, "queue_paused": flags.queue_paused, "reason": flags.pause_reason}

    def paused(state: DispatchGraphState) -> DispatchGraphState:
        action, candidate, event_id, reason = store.dispatch_next_dry_run(
            requested_by=state.get("requested_by") or "operator"
        )
        return {**state, "action": action, "candidate": candidate, "event_id": event_id, "reason": reason, "active_count": len(store.active_items())}

    def assert_single_lane(state: DispatchGraphState) -> DispatchGraphState:
        active = store.active_items()
        if active:
            return {**state, "action": "noop", "reason": "active GB10 lane already exists", "active_count": len(active), "candidate": None, "event_id": None}
        return {**state, "active_count": 0}

    def select_candidate(state: DispatchGraphState) -> DispatchGraphState:
        if state.get("action") == "noop":
            return state
        candidate = store.next_dispatch_candidate()
        if not candidate:
            return {**state, "action": "noop", "reason": "no queued candidate", "candidate": None, "event_id": None}
        return {**state, "candidate": candidate}

    def record_dry_run_dispatch(state: DispatchGraphState) -> DispatchGraphState:
        if not state.get("candidate"):
            return state
        action, candidate, event_id, reason = store.dispatch_next_dry_run(
            requested_by=state.get("requested_by") or "operator"
        )
        return {**state, "action": action, "candidate": candidate, "event_id": event_id, "reason": reason, "active_count": len(store.active_items())}

    def route_after_flags(state: DispatchGraphState) -> Literal["paused", "assert_single_lane"]:
        return "paused" if state.get("queue_paused") else "assert_single_lane"

    graph = StateGraph(DispatchGraphState)
    graph.add_node("load_control_flags", load_control_flags)
    graph.add_node("paused", paused)
    graph.add_node("assert_single_lane", assert_single_lane)
    graph.add_node("select_candidate", select_candidate)
    graph.add_node("record_dry_run_dispatch", record_dry_run_dispatch)
    graph.add_edge(START, "load_control_flags")
    graph.add_conditional_edges("load_control_flags", route_after_flags)
    graph.add_edge("paused", END)
    graph.add_edge("assert_single_lane", "select_candidate")
    graph.add_edge("select_candidate", "record_dry_run_dispatch")
    graph.add_edge("record_dry_run_dispatch", END)
    return graph.compile()
