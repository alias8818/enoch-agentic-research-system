from __future__ import annotations

from enum import Enum
from typing import Final


class OperatorLane(str, Enum):
    """Small operator vocabulary for dashboard/user-facing state.

    Raw database states are intentionally more detailed. Operator lanes answer
    what a human/user needs to know without leaking callback, review, or legacy
    workflow jargon.
    """

    RUNNING = "running"
    READY_QUEUE = "ready_queue"
    NEEDS_OPERATOR = "needs_operator"
    COMPLETE_NO_PAPER = "complete_no_paper"
    WRITE_PAPER = "write_paper"
    AUTOMATE_PUBLICATION = "automate_publication"
    READY_TO_PUBLISH = "ready_to_publish"
    PUBLISHED = "published"
    PAUSED = "paused"
    HISTORICAL = "historical"


QUEUE_STATUSES: Final[set[str]] = {
    "queued",
    "dispatching",
    "running",
    "awaiting_wake",
    "wake_received",
    "reconciling",
    "completed",
    "paused",
    "canceled",
    "dispatch_error",
    "blocked",
    "needs_review",
}

RUN_STATES: Final[set[str]] = {
    "prepared",
    "dispatching",
    "running",
    "awaiting_wake",
    "question_pending",
    "wake_ready",
    "session_finished_ready",
    "gate_timeout",
    "gate_error",
    "reconciled",
    "dispatch_error",
    # Historical/control-plane import and callback bridge states. Keep allowed so
    # old ledgers validate, but do not expose them as primary operator language.
    "dispatch_accepted",
    "needs_review",
    "waiting_external_evidence",
    "unknown",
    "cancelled",
    "canceled",
}

WAKE_GATE_COMPLETION_STATES: Final[set[str]] = {"wake_ready", "session_finished_ready"}
ACTIVE_QUEUE_STATUSES: Final[set[str]] = {"dispatching", "running", "awaiting_wake", "wake_received", "reconciling"}
ATTENTION_QUEUE_STATUSES: Final[set[str]] = {"blocked", "needs_review", "dispatch_error"}

PAPER_STATUSES: Final[set[str]] = {
    "eligible",
    "draft_generating",
    "draft_review",
    "publication_generating",
    "publication_draft",
    "human_review_required",
    "archived",
    # Historical/publication ledger aliases preserved for imported rows and old
    # reconciliation code. New writable/publication flow should use
    # publication_draft + publication_automation_items.finalized.
    "finalized",
    "approved_for_corpus",
}

DRAFT_PAPER_STATUSES: Final[set[str]] = {
    "draft_review",
    "draft_generating",
    "publication_generating",
    "human_review_required",
}

PUBLICATION_AUTOMATION_STATUSES: Final[set[str]] = {
    # New simple automation lane.
    "queued",
    "claimed",
    "blocked",
    "finalized",
    "deferred",
    # Backward-compatible internal states from the former paper-review lane.
    "triage_ready",
    "unreviewed",
    "in_review",
    "changes_requested",
    "approved_for_finalization",
    "rejected",
}

PUBLICATION_READY_AUTOMATION_STATUSES: Final[set[str]] = {"finalized"}

PROJECT_DECISION_GATE_STATES: Final[set[str]] = {"positive", "negative", "needs_review", "missing", "malformed", "unknown"}

IDEA_STATUSES: Final[set[str]] = {"unknown", "exploring", "testing", "validated", "discarded", "parked", "deprecated"}

PAPER_DRAFT_NEXT_ACTION: Final[str] = "draft_paper_or_select_next_project"

STATE_CONTRACT: Final[dict[str, set[str]]] = {
    "queue_items.status": QUEUE_STATUSES,
    "runs.state": RUN_STATES,
    "queue_items.last_run_state": RUN_STATES | PROJECT_DECISION_GATE_STATES | {""},
    "runs.gate_state": RUN_STATES | {""},
    "papers.paper_status": PAPER_STATUSES,
    "publication_automation_items.automation_status": PUBLICATION_AUTOMATION_STATUSES,
    "project_decisions.decision_gate_state": PROJECT_DECISION_GATE_STATES,
    "ideas.idea_status": IDEA_STATUSES,
    "projects.origin_idea_status": IDEA_STATUSES,
}
