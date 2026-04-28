from __future__ import annotations

import re
from collections import Counter
from typing import Any

ACTIVE_QUEUE_STATUSES = {"dispatching", "awaiting_wake", "running"}
EXCLUDED_DRAFT_NAME_FRAGMENT = (
    "human-validated",
    "human label",
    "human annotation",
    "human rater",
    "reviewer noise",
)


def text(value: Any) -> str:
    return str(value or "").strip()


def truthy(value: Any) -> bool:
    return value is True or value in {1, "1", "true", "True", "TRUE"}


def integer(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def queue_status_counts(queue_rows: list[dict[str, Any]]) -> dict[str, int]:
    return dict(Counter(text(row.get("status")) or "unknown" for row in queue_rows))


def run_state_counts(queue_rows: list[dict[str, Any]]) -> dict[str, int]:
    return dict(Counter(text(row.get("last_run_state")) or "unknown" for row in queue_rows))


def active_queue_rows(queue_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in queue_rows if text(row.get("status")) in ACTIVE_QUEUE_STATUSES]


def assert_single_active_lane(queue_rows: list[dict[str, Any]]) -> tuple[bool, str]:
    active = active_queue_rows(queue_rows)
    if len(active) <= 1:
        return True, "zero or one active GB10 lane row"
    names = ", ".join(text(row.get("project_name")) or text(row.get("project_id")) for row in active[:5])
    return False, f"multiple active GB10 lane rows: {names}"


def validate_branch_queued(row: dict[str, Any]) -> tuple[bool, str]:
    if (
        text(row.get("next_action_hint")) != "branch_queued"
        and text(row.get("last_run_state")) != "branch_queued"
    ):
        return True, "not a branch_queued row"
    summary = text(row.get("last_result_summary"))
    has_successor_id = bool(
        text(row.get("successor_project_id")) or re.search(r"\bidea-[0-9a-f]{8,}\b", summary)
    )
    has_successor_url = bool(text(row.get("successor_notion_url")) or "https://www.notion.so/" in summary)
    if has_successor_id and has_successor_url:
        return True, "branch_queued has concrete successor evidence"
    return False, "branch_queued requires successor project_id and notion_page_url evidence"


def _drafted_sets(paper_rows: list[dict[str, Any]]) -> tuple[set[str], set[str]]:
    project_ids = {text(row.get("project_id")) for row in paper_rows if text(row.get("project_id"))}
    run_ids = {text(row.get("run_id")) for row in paper_rows if text(row.get("run_id"))}
    return project_ids, run_ids


def eligible_paper_draft_candidates(
    queue_rows: list[dict[str, Any]],
    paper_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    drafted_project_ids, drafted_run_ids = _drafted_sets(paper_rows)

    def excluded(row: dict[str, Any]) -> bool:
        haystack = "\n".join(
            [text(row.get("project_name")), text(row.get("last_result_summary")), text(row.get("blocked_reason"))]
        ).lower()
        return any(fragment in haystack for fragment in EXCLUDED_DRAFT_NAME_FRAGMENT) or (
            "benchmark" in haystack and "human" in haystack
        )

    candidates = [
        row
        for row in queue_rows
        if text(row.get("project_id"))
        and text(row.get("status")) == "completed"
        and text(row.get("last_run_state")) == "finalize_positive"
        and not truthy(row.get("manual_review_required"))
        and text(row.get("project_id")) not in drafted_project_ids
        and text(row.get("current_run_id")) not in drafted_run_ids
        and not excluded(row)
    ]
    return sorted(
        candidates,
        key=lambda row: (
            text(row.get("updatedAt")) or text(row.get("last_callback_at")) or text(row.get("last_dispatch_at")),
            -integer(row.get("dispatch_priority"), 9999),
        ),
        reverse=True,
    )


def draft_candidate_payload(candidate: dict[str, Any]) -> dict[str, Any]:
    run_id = text(candidate.get("current_run_id"))
    return {
        "project_id": text(candidate.get("project_id")),
        "project_name": text(candidate.get("project_name")) or text(candidate.get("project_id")),
        "run_id": run_id,
        "notion_page_url": text(candidate.get("notion_page_url")),
        "project_dir": text(candidate.get("project_dir")),
        "draft_payload": {
            "project_id": text(candidate.get("project_id")),
            "run_id": run_id,
            "paper_type": "arxiv_draft",
            "force": False,
        },
    }


def _publication_ids(paper_rows: list[dict[str, Any]]) -> set[str]:
    return {
        text(row.get("paper_id"))
        for row in paper_rows
        if text(row.get("paper_status")) == "publication_draft"
        or text(row.get("paper_type")).startswith("publication")
    }


def eligible_paper_polish_candidates(paper_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    publication_ids = _publication_ids(paper_rows)
    candidates = [
        row
        for row in paper_rows
        if text(row.get("paper_status")) == "draft_review"
        and text(row.get("project_id"))
        and text(row.get("paper_id"))
        and text(row.get("draft_markdown_path"))
        and f"{text(row.get('paper_id'))}:publication_v1" not in publication_ids
    ]
    return sorted(
        candidates,
        key=lambda row: text(row.get("updated_at")) or text(row.get("generated_at")),
        reverse=True,
    )


def polish_candidate_payload(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "paper_id": text(candidate.get("paper_id")),
        "project_id": text(candidate.get("project_id")),
        "project_name": text(candidate.get("project_name")) or text(candidate.get("project_id")),
        "run_id": text(candidate.get("run_id")),
        "draft_markdown_path": text(candidate.get("draft_markdown_path")),
        "polish_payload": {
            "paper_id": text(candidate.get("paper_id")),
            "force": False,
            "model_id": "deterministic_template_v1",
        },
    }


def queue_projection(snapshot: dict[str, Any]) -> dict[str, Any]:
    queue_rows = list(snapshot.get("queue_rows") or [])
    paper_rows = list(snapshot.get("paper_rows") or [])
    single_active_ok, single_active_message = assert_single_active_lane(queue_rows)
    warnings = [] if single_active_ok else [single_active_message]
    return {
        "source": text(snapshot.get("source")),
        "captured_at": snapshot.get("captured_at"),
        "total_queue_rows": len(queue_rows),
        "total_paper_rows": len(paper_rows),
        "status_counts": queue_status_counts(queue_rows),
        "run_state_counts": run_state_counts(queue_rows),
        "active_rows": active_queue_rows(queue_rows),
        "draft_candidate_count": len(eligible_paper_draft_candidates(queue_rows, paper_rows)),
        "polish_candidate_count": len(eligible_paper_polish_candidates(paper_rows)),
        "warnings": warnings,
    }
