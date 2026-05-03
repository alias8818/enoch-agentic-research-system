from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

ACTIVE_QUEUE_STATUSES = {"dispatching", "awaiting_wake", "running"}
WAKE_GATE_PAPER_STATES = {"wake_ready", "session_finished_ready"}
PAPER_DRAFT_NEXT_ACTION = "draft_paper_or_select_next_project"
EXCLUDED_DRAFT_NAME_FRAGMENT = (
    "human-validated",
    "human label",
    "human annotation",
    "human rater",
    "reviewer noise",
)
PAPER_DRAFT_POSITIVE_DECISION_TOKENS = (
    "finalize_positive",
    "positive",
    "promising",
    "viable",
    "proceed",
)
PAPER_DRAFT_SUPPORTED_TOKENS = ("supported",)
PAPER_DRAFT_BLOCKED_DECISION_TOKENS = (
    "negative",
    "not_promising",
    "do_not",
    "reject",
    "inconclusive",
    "needs_review",
    "proceed_with_caveats",
    "conditional_go_pilot",
)
PAPER_DECISION_FILES = (".omx/project_decision.json", "project_decision.json")
PAPER_PRIMARY_DECISION_FIELDS = (
    "project_decision",
    "decision",
    "verdict",
    "outcome",
    "recommendation",
)
PAPER_SUPPORTING_DECISION_FIELDS = ("hypothesis_status", "status")


def text(value: Any) -> str:
    return str(value or "").strip()


def truthy(value: Any) -> bool:
    return value is True or value in {1, "1", "true", "True", "TRUE"}


def integer(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normal(value: Any) -> str:
    return text(value).lower().replace("-", "_").replace(" ", "_")


def _paper_decision_json_values(artifact_root: str | Path) -> list[tuple[str, str, str]]:
    root = Path(artifact_root)
    values: list[tuple[str, str, str]] = []
    for relative in PAPER_DECISION_FILES:
        path = root / relative
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        for field in (*PAPER_PRIMARY_DECISION_FIELDS, *PAPER_SUPPORTING_DECISION_FIELDS):
            if field in payload:
                values.append((relative, field, text(payload.get(field))))
    return values


def paper_draft_decision_gate(artifact_root: str | Path) -> dict[str, Any]:
    """Return whether local project decision artifacts support paper drafting.

    The wake-gate callback state only says the worker is done and the controller
    may either draft or move on. The actual draft/no-draft polarity lives in the
    project decision artifact. Keep this intentionally conservative for primary
    decision fields so negative, needs-review, and caveat-only outcomes do not
    become publication drafts merely because the worker session completed.
    """
    values = _paper_decision_json_values(artifact_root)
    if not values:
        return {"eligible": False, "reason": "missing project decision artifact", "values": []}

    primary = [(source, field, _normal(value)) for source, field, value in values if field in PAPER_PRIMARY_DECISION_FIELDS]
    supporting = [(source, field, _normal(value)) for source, field, value in values if field in PAPER_SUPPORTING_DECISION_FIELDS]

    for source, field, value in primary:
        if any(token in value for token in PAPER_DRAFT_BLOCKED_DECISION_TOKENS):
            return {"eligible": False, "reason": "project decision is not positive", "source": source, "field": field, "decision": value, "values": values}

    for source, field, value in primary:
        if any(token in value for token in PAPER_DRAFT_POSITIVE_DECISION_TOKENS):
            return {"eligible": True, "reason": "project decision is positive", "source": source, "field": field, "decision": value, "values": values}

    if any(value == "continue" for _, _, value in primary) and any(
        any(token in value for token in PAPER_DRAFT_SUPPORTED_TOKENS) for _, _, value in supporting
    ):
        source, field, value = next((item for item in primary if item[2] == "continue"), primary[0])
        return {"eligible": True, "reason": "continue decision has supported hypothesis evidence", "source": source, "field": field, "decision": value, "values": values}

    return {"eligible": False, "reason": "project decision lacks positive draft signal", "values": values}


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

    def draft_ready(row: dict[str, Any]) -> bool:
        last_run_state = text(row.get("last_run_state"))
        if last_run_state == "finalize_positive":
            return True
        return (
            last_run_state in WAKE_GATE_PAPER_STATES
            and text(row.get("next_action_hint")) == PAPER_DRAFT_NEXT_ACTION
            and bool(text(row.get("current_run_id")) or text(row.get("run_id")))
            and bool(text(row.get("project_dir")) or text(row.get("notion_page_url")) or text(row.get("last_result_summary")))
        )

    candidates = [
        row
        for row in queue_rows
        if text(row.get("project_id"))
        and text(row.get("status")) == "completed"
        and draft_ready(row)
        and not truthy(row.get("manual_review_required"))
        and text(row.get("project_id")) not in drafted_project_ids
        and text(row.get("current_run_id") or row.get("run_id")) not in drafted_run_ids
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
