"""Deterministic operator-stage translation for control-plane rows."""

from __future__ import annotations

from typing import Any, NamedTuple

from .models import PaperStatus, QueueStatus
from .read_models import (
    DRAFT_PAPER_STATUSES,
    READY_REVIEW_STATUSES,
    _decision_summary_from_gate,
    _followup_from_row,
    _is_followup_candidate,
    _is_useful_signal,
    _normal,
    _paper_draft_gate_for_row,
    _paper_draft_gate_from_row_decision,
    _paper_finalization_package_present,
    _paper_imported,
    _paper_publication_artifacts_present,
    _stage,
    _text,
    _truthy,
    _useful_signal_from_row,
)
from .state_contract import (
    ACTIVE_QUEUE_STATUSES,
    ATTENTION_QUEUE_STATUSES,
    PAPER_DRAFT_NEXT_ACTION,
    OperatorLane,
    WAKE_GATE_COMPLETION_STATES,
)


class _OperatorStageInputs(NamedTuple):
    queue_status: str
    last_run_state: str
    next_action: str
    paper_status: str
    review_status: str
    has_paper: bool
    manual_review: bool


def _operator_stage_inputs(row: dict[str, Any]) -> _OperatorStageInputs:
    paper_status = _normal(row.get("paper_status") or row.get("related_paper_status"))
    return _OperatorStageInputs(
        queue_status=_normal(row.get("status") or row.get("queue_status")),
        last_run_state=_normal(
            row.get("last_run_state") or row.get("state") or row.get("gate_state")
        ),
        next_action=_normal(row.get("next_action_hint")),
        paper_status=paper_status,
        review_status=_normal(
            row.get("review_status") or row.get("related_review_status")
        ),
        has_paper=bool(
            _text(row.get("paper_id") or row.get("related_paper_id")) or paper_status
        ),
        manual_review=_truthy(row.get("manual_review_required")),
    )


def _project_decision_stage_fields(
    gate: dict[str, Any] | None,
    decision_summary: str,
    *,
    paper_draft_eligible: bool,
) -> dict[str, Any]:
    return {
        "paper_draft_eligible": paper_draft_eligible if gate is not None else None,
        "project_decision_summary": decision_summary,
        "project_decision_gate": gate,
    }


def _operator_stage_for_queue_terminal(
    ctx: _OperatorStageInputs,
) -> dict[str, Any] | None:
    if ctx.queue_status == QueueStatus.CANCELED.value and not ctx.manual_review:
        return _stage(
            "historical",
            lane=OperatorLane.HISTORICAL,
            tone="muted",
            attention=False,
            next_step="No action is needed for this terminal queue record.",
            explanation="Canceled queue work is terminal historical evidence, not current operator work.",
        )
    if ctx.queue_status in ATTENTION_QUEUE_STATUSES or ctx.manual_review:
        return _stage(
            "blocked_needs_operator",
            lane=OperatorLane.NEEDS_OPERATOR,
            tone="bad",
            attention=True,
            next_step="Open the item and resolve the blocker or worker question.",
            explanation="Queue status or manual-action flag requires operator action.",
        )
    if ctx.queue_status == QueueStatus.PAUSED.value:
        return _stage(
            "paused_work",
            lane=OperatorLane.PAUSED,
            tone="muted",
            attention=False,
            next_step="Resume only when maintenance policy says this project should re-enter the queue.",
            explanation="Paused work is tracked separately from operator blockers.",
        )
    return None


def _operator_stage_for_review_terminal(
    ctx: _OperatorStageInputs,
) -> dict[str, Any] | None:
    if ctx.review_status == "rejected" or ctx.paper_status == "archived":
        return _stage(
            "run_complete_no_paper",
            lane=OperatorLane.COMPLETE_NO_PAPER,
            tone="muted",
            attention=False,
            next_step="No paper publication action is needed for this record.",
            explanation="The paper/review record is rejected or archived.",
        )
    return None


def _operator_stage_for_active_worker(
    ctx: _OperatorStageInputs,
) -> dict[str, Any] | None:
    if (
        ctx.queue_status in ACTIVE_QUEUE_STATUSES
        or ctx.last_run_state in ACTIVE_QUEUE_STATUSES
    ):
        return _stage(
            "running",
            lane=OperatorLane.RUNNING,
            tone="info",
            attention=False,
            next_step="Wait for worker callback or gate completion.",
            explanation="The worker lane is active or awaiting wake callback.",
        )
    return None


def _operator_stage_for_published(
    ctx: _OperatorStageInputs,
    row: dict[str, Any],
) -> dict[str, Any] | None:
    if not (ctx.has_paper and _paper_imported(row)):
        return None
    return _stage(
        "published",
        lane=OperatorLane.PUBLISHED,
        tone="good",
        attention=False,
        next_step="No corpus-import action is needed; this paper is already represented by the import ledger.",
        explanation="The corpus import ledger contains this paper, so it is public/imported rather than publish work.",
    )


def _operator_stage_for_ready_to_publish(
    ctx: _OperatorStageInputs,
    row: dict[str, Any],
) -> dict[str, Any] | None:
    if not (
        ctx.paper_status
        in {PaperStatus.PUBLICATION_DRAFT.value, PaperStatus.DRAFT_REVIEW.value}
        and ctx.review_status in READY_REVIEW_STATUSES
        and _paper_finalization_package_present(row)
        and _paper_publication_artifacts_present(row)
    ):
        return None
    return _stage(
        "ready_to_publish",
        lane=OperatorLane.READY_TO_PUBLISH,
        tone="good",
        attention=False,
        next_step="Import this finalized publication draft into the public corpus.",
        explanation="Publication artifacts have required evidence paths, a finalized automation package, and no corpus-import ledger row is visible.",
    )


def _operator_stage_for_finalization_needed(
    ctx: _OperatorStageInputs,
) -> dict[str, Any] | None:
    if ctx.paper_status != PaperStatus.PUBLICATION_DRAFT.value:
        return None
    return _stage(
        "finalization_needed",
        lane=OperatorLane.AUTOMATE_PUBLICATION,
        tone="warn",
        attention=False,
        next_step="Run automated rewrite/finalization; no human approval is required.",
        explanation="Publication draft exists and should move through the automated finalization lane without operator approval.",
    )


def _operator_stage_for_draft_created(
    ctx: _OperatorStageInputs,
) -> dict[str, Any] | None:
    if not (
        ctx.paper_status in DRAFT_PAPER_STATUSES or (ctx.has_paper and ctx.paper_status)
    ):
        return None
    return _stage(
        "draft_created",
        lane=OperatorLane.AUTOMATE_PUBLICATION,
        tone="info",
        attention=False,
        next_step="Continue automated rewrite/finalization or inspect artifacts if automation failed.",
        explanation="A paper record exists, but it is not yet a finalized publication draft.",
    )


def _operator_stage_for_paper_lifecycle(
    ctx: _OperatorStageInputs,
    row: dict[str, Any],
) -> dict[str, Any] | None:
    for resolver in (
        lambda: _operator_stage_for_published(ctx, row),
        lambda: _operator_stage_for_ready_to_publish(ctx, row),
        lambda: _operator_stage_for_finalization_needed(ctx),
        lambda: _operator_stage_for_draft_created(ctx),
    ):
        if stage := resolver():
            return stage
    return None


def _operator_stage_for_queued(ctx: _OperatorStageInputs) -> dict[str, Any] | None:
    if ctx.queue_status != "queued":
        return None
    return _stage(
        "idea_queued",
        lane=OperatorLane.READY_QUEUE,
        tone="info",
        attention=False,
        next_step="Dispatch when the lane is available.",
        explanation="The idea is queued and not currently running.",
    )


def _operator_stage_compute_blocked_after_delivery(
    row: dict[str, Any],
    decision_summary: str,
    fields: dict[str, Any],
) -> dict[str, Any] | None:
    if not _is_useful_signal(row):
        return None
    signal = _useful_signal_from_row(row)
    if not signal["compute_scale_blocked"]:
        return None
    return _stage(
        "compute_scale_blocked",
        lane=OperatorLane.COMPUTE_SCALE_BLOCKED,
        tone="info",
        attention=False,
        next_step="Park as promising-if-scaled unless a cheaper bounded test is defined.",
        explanation=f"Worker delivery found a useful signal, but the remaining validation appears to exceed local compute/time limits: {decision_summary or 'not paper-ready'}.",
        **fields,
        **signal,
    )


def _operator_stage_when_draft_not_eligible(
    row: dict[str, Any],
    *,
    gate: dict[str, Any] | None,
    decision_summary: str,
) -> dict[str, Any]:
    fields = _project_decision_stage_fields(
        gate, decision_summary, paper_draft_eligible=False
    )
    if stage := _operator_stage_compute_blocked_after_delivery(
        row, decision_summary, fields
    ):
        return stage
    if _is_followup_candidate(row):
        followup = _followup_from_row(row)
        return _stage(
            "followup_candidate",
            lane=OperatorLane.FOLLOWUP_INVESTIGATION,
            tone="info",
            attention=False,
            next_step="Launch a bounded follow-up investigation if this adjacent test is still worth spending worker time on.",
            explanation=f"Worker delivery is complete and not paper-positive ({decision_summary or 'not eligible'}), but the decision artifact recommends a specific next investigation.",
            **fields,
            **followup,
        )
    if _is_useful_signal(row):
        signal = _useful_signal_from_row(row)
        return _stage(
            "useful_signal",
            lane=OperatorLane.USEFUL_SIGNAL,
            tone="info",
            attention=False,
            next_step="Prefer one bounded deepen run if it is cheap; otherwise keep the scoped useful signal as no-paper evidence.",
            explanation=f"Worker delivery found a useful local signal, but it is not yet paper-positive: {decision_summary or 'not paper-ready'}.",
            **fields,
            **signal,
        )
    return _stage(
        "run_complete_no_paper",
        lane=OperatorLane.COMPLETE_NO_PAPER,
        tone="muted",
        attention=False,
        next_step="No paper draft is needed; select the next project.",
        explanation=f"Worker delivery is complete, but the project decision is not a positive paper signal: {decision_summary or 'not eligible'}.",
        **fields,
    )


def _operator_stage_for_completed_draft_action(
    row: dict[str, Any],
    ctx: _OperatorStageInputs,
) -> dict[str, Any] | None:
    if not (
        ctx.queue_status == "completed"
        and ctx.last_run_state in WAKE_GATE_COMPLETION_STATES
        and ctx.next_action == PAPER_DRAFT_NEXT_ACTION
    ):
        return None
    gate = _paper_draft_gate_from_row_decision(row) or _paper_draft_gate_for_row(row)
    decision_summary = _decision_summary_from_gate(gate)
    if gate is None or not bool(gate.get("eligible")):
        return _operator_stage_when_draft_not_eligible(
            row, gate=gate, decision_summary=decision_summary
        )
    return _stage(
        "run_complete_draft_needed",
        lane=OperatorLane.WRITE_PAPER,
        tone="warn",
        attention=False,
        next_step="Run draft-next because the decision artifacts are positive.",
        explanation="Worker delivery is complete and the project decision artifacts indicate a positive paper signal.",
        **_project_decision_stage_fields(
            gate, decision_summary, paper_draft_eligible=True
        ),
    )


def _operator_stage_useful_signal_after_wake(
    row: dict[str, Any],
) -> dict[str, Any] | None:
    if not _is_useful_signal(row):
        return None
    signal = _useful_signal_from_row(row)
    if signal["compute_scale_blocked"]:
        return _stage(
            "compute_scale_blocked",
            lane=OperatorLane.COMPUTE_SCALE_BLOCKED,
            tone="info",
            attention=False,
            next_step="Park as promising-if-scaled unless a cheaper bounded test is defined.",
            explanation="The prior run found a useful signal, but remaining validation exceeds local compute/time limits.",
            **signal,
        )
    return _stage(
        "useful_signal",
        lane=OperatorLane.USEFUL_SIGNAL,
        tone="info",
        attention=False,
        next_step="Prefer one bounded deepen run if it is cheap; otherwise keep the scoped useful signal as no-paper evidence.",
        explanation="The prior run found a bounded useful signal but no current paper-draft signal is visible.",
        **signal,
    )


def _operator_stage_for_completed_wake(
    row: dict[str, Any],
    ctx: _OperatorStageInputs,
) -> dict[str, Any] | None:
    if not (
        ctx.queue_status == "completed"
        or ctx.last_run_state in WAKE_GATE_COMPLETION_STATES
    ):
        return None
    if not ctx.has_paper:
        if stage := _operator_stage_useful_signal_after_wake(row):
            return stage
        if _is_followup_candidate(row):
            followup = _followup_from_row(row)
            return _stage(
                "followup_candidate",
                lane=OperatorLane.FOLLOWUP_INVESTIGATION,
                tone="info",
                attention=False,
                next_step="Launch a bounded follow-up investigation if this adjacent test is still worth spending worker time on.",
                explanation="The prior run is complete and no-paper, but its decision artifact recommends a specific next investigation.",
                **followup,
            )
    return _stage(
        "run_complete_no_paper",
        lane=OperatorLane.COMPLETE_NO_PAPER,
        tone="muted",
        attention=False,
        next_step="Select the next project unless separate paper evidence appears.",
        explanation="The worker run is complete; no current draft-needed signal is visible in this row.",
    )


def _operator_stage_for_unknown() -> dict[str, Any]:
    return _stage(
        "blocked_needs_operator",
        lane=OperatorLane.NEEDS_OPERATOR,
        tone="warn",
        attention=True,
        next_step="Inspect raw state because this row does not match a known operator lifecycle stage.",
        explanation="Unknown or inconsistent raw state.",
    )


def operator_stage_for_record(row: dict[str, Any]) -> dict[str, Any]:
    """Translate raw control-plane state into a deterministic operator stage.

    Raw queue/run/paper/review values remain available for detail/debugging, but
    the dashboard should lead with this normalized stage. `wake_ready` and
    `session_finished_ready` are worker-delivery callbacks, not publication
    polarity; paper polarity is decided by artifacts/review state.
    """

    ctx = _operator_stage_inputs(row)
    for resolver in (
        lambda: _operator_stage_for_queue_terminal(ctx),
        lambda: _operator_stage_for_review_terminal(ctx),
        lambda: _operator_stage_for_active_worker(ctx),
        lambda: _operator_stage_for_paper_lifecycle(ctx, row),
        lambda: _operator_stage_for_queued(ctx),
        lambda: _operator_stage_for_completed_draft_action(row, ctx),
        lambda: _operator_stage_for_completed_wake(row, ctx),
    ):
        if stage := resolver():
            return stage
    return _operator_stage_for_unknown()
