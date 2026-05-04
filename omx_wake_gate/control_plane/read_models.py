from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .store import ControlPlaneStore


def page_size(value: int, *, default: int = 50, cap: int = 200) -> int:
    try:
        requested = int(value)
    except (TypeError, ValueError):
        requested = default
    return max(1, min(requested, cap))


def row_age_seconds(row: dict[str, Any]) -> int | None:
    raw = str(row.get("updated_at") or row.get("created_at") or "")
    if not raw:
        return None
    try:
        ts = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return max(0, int((datetime.now(timezone.utc) - ts).total_seconds()))


def queue_links(row: dict[str, Any]) -> dict[str, str]:
    project_id = str(row.get("project_id") or "")
    run_id = str(row.get("current_run_id") or "")
    return {
        "project": f"/control/api/v1/projects/{project_id}" if project_id else "",
        "run": f"/control/api/v1/runs/{run_id}" if run_id else "",
        "legacy_project": f"/control/api/projects/{project_id}" if project_id else "",
        "legacy_run": f"/control/api/runs/{run_id}" if run_id else "",
    }


def paper_links(row: dict[str, Any]) -> dict[str, str]:
    paper_id = str(row.get("paper_id") or "")
    project_id = str(row.get("project_id") or "")
    run_id = str(row.get("run_id") or "")
    return {
        "paper": f"/control/api/v1/papers/{paper_id}" if paper_id else "",
        "project": f"/control/api/v1/projects/{project_id}" if project_id else "",
        "run": f"/control/api/v1/runs/{run_id}" if run_id else "",
        "legacy_paper": f"/control/api/papers/{paper_id}" if paper_id else "",
    }


def summarize_queue_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "project_id": row.get("project_id", ""),
        "project_name": row.get("project_name", ""),
        "status": row.get("status", ""),
        "dispatch_priority": row.get("dispatch_priority", 0),
        "selection_rank": row.get("selection_rank", 0),
        "current_run_id": row.get("current_run_id", ""),
        "current_session_id": row.get("current_session_id", ""),
        "last_run_state": row.get("last_run_state", ""),
        "next_action_hint": row.get("next_action_hint", ""),
        "manual_review_required": bool(row.get("manual_review_required")),
        "blocked_reason": row.get("blocked_reason", ""),
        "updated_at": row.get("updated_at", ""),
        "age_seconds": row_age_seconds(row),
        "links": queue_links(row),
    }


def summarize_paper_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "paper_id": row.get("paper_id", ""),
        "project_id": row.get("project_id", ""),
        "project_name": row.get("project_name", ""),
        "run_id": row.get("run_id", ""),
        "paper_type": row.get("paper_type", ""),
        "paper_status": row.get("paper_status", ""),
        "generated_at": row.get("generated_at", ""),
        "updated_at": row.get("updated_at", ""),
        "age_seconds": row_age_seconds(row),
        "artifact_paths_present": {
            name: bool(row.get(name))
            for name in ("draft_markdown_path", "draft_latex_path", "evidence_bundle_path", "claim_ledger_path", "manifest_path")
        },
        "links": paper_links(row),
    }


def summarize_run_row(row: dict[str, Any]) -> dict[str, Any]:
    run_id = str(row.get("run_id") or "")
    project_id = str(row.get("project_id") or "")
    return {
        "run_id": run_id,
        "project_id": project_id,
        "project_name": row.get("project_name", ""),
        "session_id": row.get("session_id", ""),
        "state": row.get("state", ""),
        "gate_state": row.get("gate_state", ""),
        "dispatch_mode": row.get("dispatch_mode", ""),
        "started_at": row.get("started_at", ""),
        "ended_at": row.get("ended_at", ""),
        "last_callback_at": row.get("last_callback_at", ""),
        "current_activity": row.get("current_activity", ""),
        "updated_at": row.get("updated_at", ""),
        "age_seconds": row_age_seconds(row),
        "links": {
            "run": f"/control/api/v1/runs/{run_id}" if run_id else "",
            "project": f"/control/api/v1/projects/{project_id}" if project_id else "",
            "legacy_run": f"/control/api/runs/{run_id}" if run_id else "",
        },
    }


def page_response(*, rows: list[dict[str, Any]], next_cursor: str | None, has_more: bool, page_size_value: int, cursor: str, filters: dict[str, Any]) -> dict[str, Any]:
    return {
        "page_size": page_size_value,
        "returned": len(rows),
        "cursor": cursor or "",
        "next_cursor": next_cursor or "",
        "has_more": has_more,
        "filters": filters,
    }


def overview(store: ControlPlaneStore, *, active_limit: int = 5, event_limit: int = 10) -> dict[str, Any]:
    counts = store.queue_counts_sql()
    paper_counts = store.paper_counts_sql()
    active = [summarize_queue_row(row) for row in store.active_items_sql(limit=active_limit)]
    next_candidate = store.next_candidate_sql()
    events, next_cursor, has_more = store.event_page(page_size=event_limit, include_payload=False)
    return {
        "counts": {
            **counts,
            "papers": paper_counts.get("all", 0),
        },
        "paper_counts": paper_counts,
        "active_items": active,
        "next_candidate": summarize_queue_row(next_candidate) if next_candidate else None,
        "recent_events": events,
        "recent_events_page": page_response(rows=events, next_cursor=next_cursor, has_more=has_more, page_size_value=page_size(event_limit), cursor="", filters={}),
    }
