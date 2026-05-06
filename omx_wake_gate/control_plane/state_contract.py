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


OPERATOR_LANE_DESCRIPTIONS: Final[dict[str, str]] = {
    OperatorLane.RUNNING.value: "Work is dispatching, running, writing, finalizing, or waiting on a callback.",
    OperatorLane.READY_QUEUE.value: "Work is eligible to dispatch when pause policy allows it.",
    OperatorLane.NEEDS_OPERATOR.value: "A blocker, dispatch/gate failure, or worker question needs explicit operator action.",
    OperatorLane.COMPLETE_NO_PAPER.value: "Worker delivery is complete, but the paper decision gate is not actionable-positive.",
    OperatorLane.WRITE_PAPER.value: "A positive completed run has no paper yet and can be drafted by explicit bounded automation.",
    OperatorLane.AUTOMATE_PUBLICATION.value: "A paper artifact exists and should flow through automated rewrite/finalization/package steps.",
    OperatorLane.READY_TO_PUBLISH.value: "A publication draft has a finalized automation package and is ready for corpus import.",
    OperatorLane.PUBLISHED.value: "The paper is represented by a public/corpus import ledger.",
    OperatorLane.PAUSED.value: "Work is intentionally held by maintenance or policy.",
    OperatorLane.HISTORICAL.value: "Terminal, provenance, debug, or imported evidence that is not current operator work.",
}


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

STATE_SURFACE_CLASSES: Final[set[str]] = {
    "canonical_lifecycle",
    "derived_operator",
    "system_flag",
    "attention_flag",
    "operator_hint",
    "diagnostic_context",
    "provenance_text",
    "type_discriminator",
    "event_taxonomy",
    "projection_metadata",
}

STATE_LIKE_COLUMN_NAMES: Final[set[str]] = {
    "status",
    "state",
    "gate_state",
    "last_run_state",
    "idea_status",
    "origin_idea_status",
    "paper_status",
    "automation_status",
    "decision_gate_state",
    "queue_paused",
    "maintenance_mode",
    "manual_review_required",
    "auto_continue",
    "pause_reason",
    "paused_by",
    "last_event_type",
    "next_action_hint",
    "blocked_reason",
    "last_error",
    "last_result_summary",
    "current_activity",
    "decision_summary",
    "decision_key",
    "artifact_path",
    "dispatch_mode",
    "decision_type",
    "paper_type",
    "event_type",
    "entity_type",
    "snapshot_type",
    "projection_version",
}


def _surface(
    surface_class: str,
    *,
    contract_surface: str = "",
    operator_lane: OperatorLane | None = None,
    reason: str = "",
) -> dict[str, str]:
    if surface_class not in STATE_SURFACE_CLASSES:
        raise ValueError(f"unknown state surface class: {surface_class}")
    return {
        "class": surface_class,
        "contract_surface": contract_surface,
        "operator_lane": (operator_lane or OperatorLane.HISTORICAL).value,
        "reason": reason,
    }


# Inventory for every state-like persisted column admitted by the Supabase schema.
# Only `canonical_lifecycle` entries participate in STATE_CONTRACT. The other
# entries are intentionally classified so agents do not promote flags, event
# taxonomy, or type discriminators into user-facing lifecycle states.
STATE_SURFACE_INVENTORY: Final[dict[str, dict[str, str]]] = {
    **{
        surface: _surface(
            "canonical_lifecycle",
            contract_surface=surface,
            reason="raw persisted lifecycle/detail state with explicit allowed values",
        )
        for surface in STATE_CONTRACT
    },
    "control_flags.queue_paused": _surface("system_flag", operator_lane=OperatorLane.PAUSED, reason="global dispatch pause switch, not a per-project lifecycle"),
    "control_flags.maintenance_mode": _surface("system_flag", operator_lane=OperatorLane.PAUSED, reason="global maintenance policy flag"),
    "control_flags.pause_reason": _surface("provenance_text", operator_lane=OperatorLane.PAUSED, reason="pause explanation text; queue_paused is the state-bearing flag"),
    "control_flags.paused_by": _surface("provenance_text", operator_lane=OperatorLane.PAUSED, reason="pause actor audit field"),
    "queue_items.manual_review_required": _surface("attention_flag", operator_lane=OperatorLane.NEEDS_OPERATOR, reason="explicit operator-attention boolean that decorates queue status"),
    "queue_items.auto_continue": _surface("system_flag", operator_lane=OperatorLane.RUNNING, reason="automation policy flag; lifecycle still comes from queue status"),
    "queue_items.last_event_type": _surface("event_taxonomy", reason="last callback/event taxonomy for evidence only"),
    "queue_items.next_action_hint": _surface("operator_hint", reason="planner hint; paper actionability is still derived from decision gate and paper ledgers"),
    "queue_items.blocked_reason": _surface("diagnostic_context", operator_lane=OperatorLane.NEEDS_OPERATOR, reason="blocker explanation text, not a finite state vocabulary"),
    "queue_items.last_error": _surface("diagnostic_context", operator_lane=OperatorLane.NEEDS_OPERATOR, reason="error explanation text, not a finite state vocabulary"),
    "queue_items.last_result_summary": _surface("provenance_text", reason="worker result summary/provenance text"),
    "runs.dispatch_mode": _surface("type_discriminator", reason="dispatch strategy/provenance, not lifecycle"),
    "runs.current_activity": _surface("provenance_text", operator_lane=OperatorLane.RUNNING, reason="free-form worker activity label"),
    "project_decisions.decision_type": _surface("type_discriminator", reason="decision record kind; paper polarity lives in decision_gate_state"),
    "project_decisions.decision_summary": _surface("provenance_text", reason="human-readable decision summary; actionability lives in decision_gate_state"),
    "project_decisions.artifact_path": _surface("provenance_text", reason="decision artifact provenance path"),
    "papers.paper_type": _surface("type_discriminator", reason="artifact kind such as arxiv draft; paper lifecycle lives in paper_status"),
    "publication_automation_items.decision_summary": _surface("provenance_text", reason="automation decision summary; lifecycle lives in automation_status"),
    "idea_events.event_type": _surface("event_taxonomy", reason="Supabase-native idea workbench event taxonomy"),
    "control_events.event_type": _surface("event_taxonomy", reason="append-only event taxonomy for audit/logging"),
    "control_events.entity_type": _surface("event_taxonomy", reason="event target taxonomy for audit/logging"),
    "operator_observations.status": _surface("projection_metadata", reason="health/observation status, not work lifecycle"),
    "core_events.event_type": _surface("event_taxonomy", reason="Enoch core shadow/proposal event taxonomy"),
    "core_snapshots.snapshot_type": _surface("type_discriminator", reason="snapshot/projection kind"),
    "core_decisions.decision_key": _surface("type_discriminator", reason="domain decision lookup key; not a lifecycle state"),
    "core_decisions.decision_type": _surface("type_discriminator", reason="core decision kind; domain-specific payload owns details"),
    "core_projection_cache.projection_version": _surface("projection_metadata", reason="cache schema/version metadata"),
}


STATE_DISPOSITIONS: Final[set[str]] = {
    "keep",
    "alias",
    "legacy_internal",
    "migrate_after_freeze",
}


def _decision(
    lane: OperatorLane,
    disposition: str,
    *,
    replacement: str = "",
    reason: str = "",
) -> dict[str, str]:
    if disposition not in STATE_DISPOSITIONS:
        raise ValueError(f"unknown state disposition: {disposition}")
    return {
        "operator_lane": lane.value,
        "disposition": disposition,
        "replacement": replacement,
        "reason": reason,
    }


# State-reduction plan for every raw value admitted by STATE_CONTRACT. This is
# intentionally separate from the compatibility contract above: STATE_CONTRACT
# answers "what may exist without corrupting the ledgers?", while this table
# answers "what should a user/agent do with it, and can we reduce it later?".
STATE_REDUCTION_PLAN: Final[dict[str, dict[str, dict[str, str]]]] = {
    "queue_items.status": {
        "queued": _decision(OperatorLane.READY_QUEUE, "keep", reason="primary dispatchable queue state"),
        "dispatching": _decision(OperatorLane.RUNNING, "keep", reason="dispatch request is in flight"),
        "running": _decision(OperatorLane.RUNNING, "keep", reason="worker is active"),
        "awaiting_wake": _decision(OperatorLane.RUNNING, "keep", reason="worker callback is expected"),
        "wake_received": _decision(OperatorLane.RUNNING, "alias", replacement="reconciling", reason="callback has arrived but reconciliation is not done"),
        "reconciling": _decision(OperatorLane.RUNNING, "keep", reason="control plane is settling callback evidence"),
        "completed": _decision(OperatorLane.COMPLETE_NO_PAPER, "keep", reason="paper action is derived from project decision and paper ledgers"),
        "paused": _decision(OperatorLane.PAUSED, "keep", reason="explicit maintenance/policy hold"),
        "canceled": _decision(OperatorLane.HISTORICAL, "keep", reason="terminal no-action state"),
        "dispatch_error": _decision(OperatorLane.NEEDS_OPERATOR, "keep", reason="dispatch failed and needs inspection"),
        "blocked": _decision(OperatorLane.NEEDS_OPERATOR, "keep", reason="explicit blocker"),
        "needs_review": _decision(OperatorLane.NEEDS_OPERATOR, "migrate_after_freeze", replacement="blocked", reason="legacy queue attention wording"),
    },
    "runs.state": {
        "prepared": _decision(OperatorLane.RUNNING, "alias", replacement="dispatching", reason="pre-dispatch transient"),
        "dispatching": _decision(OperatorLane.RUNNING, "keep", reason="dispatch request is in flight"),
        "running": _decision(OperatorLane.RUNNING, "keep", reason="worker is active"),
        "awaiting_wake": _decision(OperatorLane.RUNNING, "keep", reason="worker callback is expected"),
        "question_pending": _decision(OperatorLane.NEEDS_OPERATOR, "keep", reason="worker needs an answer"),
        "wake_ready": _decision(OperatorLane.HISTORICAL, "keep", reason="delivery signal only; not a paper-positive signal"),
        "session_finished_ready": _decision(OperatorLane.HISTORICAL, "alias", replacement="wake_ready", reason="alternate delivery-complete callback"),
        "gate_timeout": _decision(OperatorLane.NEEDS_OPERATOR, "keep", reason="wake gate timed out"),
        "gate_error": _decision(OperatorLane.NEEDS_OPERATOR, "keep", reason="wake gate failed"),
        "reconciled": _decision(OperatorLane.HISTORICAL, "keep", reason="settled historical run"),
        "dispatch_error": _decision(OperatorLane.NEEDS_OPERATOR, "keep", reason="dispatch failed"),
        "dispatch_accepted": _decision(OperatorLane.RUNNING, "legacy_internal", replacement="awaiting_wake or reconciled when superseded", reason="old dispatch bridge state"),
        "needs_review": _decision(OperatorLane.NEEDS_OPERATOR, "migrate_after_freeze", replacement="gate_error", reason="legacy run attention wording"),
        "waiting_external_evidence": _decision(OperatorLane.NEEDS_OPERATOR, "keep", reason="external/worker evidence is missing"),
        "unknown": _decision(OperatorLane.HISTORICAL, "legacy_internal", reason="imported run rows without reliable lifecycle evidence"),
        "cancelled": _decision(OperatorLane.HISTORICAL, "alias", replacement="canceled", reason="British spelling alias"),
        "canceled": _decision(OperatorLane.HISTORICAL, "keep", reason="terminal no-action state"),
    },
    "queue_items.last_run_state": {},
    "runs.gate_state": {},
    "papers.paper_status": {
        "eligible": _decision(OperatorLane.WRITE_PAPER, "legacy_internal", replacement="draft_generating", reason="paper eligibility now lives in paper_eligibility/write_needed"),
        "draft_generating": _decision(OperatorLane.RUNNING, "keep", reason="draft writer is active"),
        "draft_review": _decision(OperatorLane.AUTOMATE_PUBLICATION, "migrate_after_freeze", replacement="publication_draft", reason="legacy first-draft label; operator should see first draft or automation"),
        "publication_generating": _decision(OperatorLane.RUNNING, "keep", reason="publication rewrite/finalization is active"),
        "publication_draft": _decision(OperatorLane.AUTOMATE_PUBLICATION, "keep", reason="publication readiness also requires finalized automation package"),
        "human_review_required": _decision(OperatorLane.NEEDS_OPERATOR, "migrate_after_freeze", replacement="blocked", reason="manual paper review is not a normal workflow"),
        "archived": _decision(OperatorLane.HISTORICAL, "keep", reason="terminal no-action paper state"),
        "finalized": _decision(OperatorLane.READY_TO_PUBLISH, "legacy_internal", replacement="publication_draft + publication_automation.finalized", reason="old flattened paper readiness state"),
        "approved_for_corpus": _decision(OperatorLane.PUBLISHED, "legacy_internal", replacement="corpus import ledger", reason="old flattened public-import state"),
    },
    "publication_automation_items.automation_status": {
        "queued": _decision(OperatorLane.AUTOMATE_PUBLICATION, "keep", reason="automation work is queued"),
        "claimed": _decision(OperatorLane.AUTOMATE_PUBLICATION, "keep", reason="automation actor has claimed the item"),
        "blocked": _decision(OperatorLane.NEEDS_OPERATOR, "keep", reason="automation blocker"),
        "finalized": _decision(OperatorLane.READY_TO_PUBLISH, "keep", reason="finalization package is ready"),
        "deferred": _decision(OperatorLane.HISTORICAL, "keep", reason="intentionally skipped automation item"),
        "triage_ready": _decision(OperatorLane.AUTOMATE_PUBLICATION, "migrate_after_freeze", replacement="queued", reason="legacy paper-review queue state"),
        "unreviewed": _decision(OperatorLane.AUTOMATE_PUBLICATION, "migrate_after_freeze", replacement="queued", reason="legacy paper-review queue state"),
        "in_review": _decision(OperatorLane.AUTOMATE_PUBLICATION, "migrate_after_freeze", replacement="claimed", reason="legacy paper-review running state"),
        "changes_requested": _decision(OperatorLane.NEEDS_OPERATOR, "migrate_after_freeze", replacement="blocked", reason="legacy paper-review correction state"),
        "approved_for_finalization": _decision(OperatorLane.AUTOMATE_PUBLICATION, "migrate_after_freeze", replacement="queued", reason="approval wording is internal compatibility only"),
        "rejected": _decision(OperatorLane.HISTORICAL, "keep", reason="terminal non-publication automation state"),
    },
    "project_decisions.decision_gate_state": {
        "positive": _decision(OperatorLane.WRITE_PAPER, "keep", reason="only state allowed to create actionable write_needed"),
        "negative": _decision(OperatorLane.COMPLETE_NO_PAPER, "keep", reason="not writable"),
        "needs_review": _decision(OperatorLane.COMPLETE_NO_PAPER, "migrate_after_freeze", replacement="unknown", reason="ambiguous decisions must not become paper work"),
        "missing": _decision(OperatorLane.COMPLETE_NO_PAPER, "keep", reason="missing decision is not writable"),
        "malformed": _decision(OperatorLane.COMPLETE_NO_PAPER, "keep", reason="malformed decision is not writable"),
        "unknown": _decision(OperatorLane.COMPLETE_NO_PAPER, "keep", reason="unknown decision is not writable"),
    },
    "ideas.idea_status": {
        "unknown": _decision(OperatorLane.HISTORICAL, "legacy_internal", reason="source/provenance status only"),
        "exploring": _decision(OperatorLane.READY_QUEUE, "keep", reason="included by default intake policy"),
        "testing": _decision(OperatorLane.READY_QUEUE, "keep", reason="included by default intake policy"),
        "validated": _decision(OperatorLane.HISTORICAL, "keep", reason="source/provenance status only"),
        "discarded": _decision(OperatorLane.HISTORICAL, "keep", reason="source/provenance status only"),
        "parked": _decision(OperatorLane.HISTORICAL, "keep", reason="source/provenance status only"),
        "deprecated": _decision(OperatorLane.HISTORICAL, "keep", reason="source/provenance status only"),
    },
    "projects.origin_idea_status": {},
}

STATE_REDUCTION_PLAN["queue_items.last_run_state"] = {
    value: dict(STATE_REDUCTION_PLAN["runs.state"].get(value, STATE_REDUCTION_PLAN["project_decisions.decision_gate_state"].get(value, _decision(OperatorLane.HISTORICAL, "legacy_internal", reason="blank detail state"))))
    for value in STATE_CONTRACT["queue_items.last_run_state"]
}
STATE_REDUCTION_PLAN["runs.gate_state"] = {
    value: dict(STATE_REDUCTION_PLAN["runs.state"].get(value, _decision(OperatorLane.HISTORICAL, "legacy_internal", reason="blank gate detail state")))
    for value in STATE_CONTRACT["runs.gate_state"]
}
STATE_REDUCTION_PLAN["projects.origin_idea_status"] = {
    value: dict(STATE_REDUCTION_PLAN["ideas.idea_status"][value])
    for value in STATE_CONTRACT["projects.origin_idea_status"]
}
