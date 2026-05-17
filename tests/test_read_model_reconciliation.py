from __future__ import annotations

from hypothesis import given, settings, strategies as st

from enoch_control_plane.control_plane.read_models import operator_counts_from_rows, operator_detail_counts_from_rows
from enoch_control_plane.control_plane.state_contract import OperatorLane

safe_id = st.text(
    alphabet=st.characters(whitelist_categories=("Ll", "Lu", "Nd"), whitelist_characters="-_"),
    min_size=1,
    max_size=40,
).filter(lambda value: value.strip("-_"))


def _active_queue(project_id: str, run_id: str, **extra: object) -> dict[str, object]:
    return {
        "project_id": project_id,
        "project_name": project_id,
        "status": "awaiting_wake",
        "last_run_state": "awaiting_wake",
        "current_run_id": run_id,
        "next_action_hint": "await_callback",
        **extra,
    }


def _completed_draft_ready(project_id: str, run_id: str, **extra: object) -> dict[str, object]:
    return {
        "project_id": project_id,
        "project_name": project_id,
        "status": "completed",
        "last_run_state": "wake_ready",
        "current_run_id": run_id,
        "next_action_hint": "draft_paper_or_select_next_project",
        "decision_gate_state": "positive",
        **extra,
    }


def _paper(project_id: str, run_id: str, paper_id: str, **extra: object) -> dict[str, object]:
    return {
        "paper_id": paper_id,
        "project_id": project_id,
        "run_id": run_id,
        "paper_status": "publication_draft",
        "review_status": "finalized",
        "finalization_package_path": "package.json",
        **extra,
    }


@given(project_id=safe_id, run_id=safe_id, stale_paper_id=safe_id)
@settings(max_examples=80)
def test_active_queue_row_survives_stale_related_paper_reference(project_id: str, run_id: str, stale_paper_id: str) -> None:
    row = _active_queue(project_id, run_id, related_paper_id=f"stale-{stale_paper_id}")

    counts = operator_counts_from_rows([row])
    detail = operator_detail_counts_from_rows([row])

    assert counts[OperatorLane.RUNNING.value] == 1
    assert counts["total_operator_items"] == 1
    assert detail["running"] == 1


@given(project_id=safe_id, run_id=safe_id, paper_id=safe_id)
@settings(max_examples=80)
def test_completed_queue_with_matching_live_related_paper_counts_as_paper_only(project_id: str, run_id: str, paper_id: str) -> None:
    paper_id = f"paper-{paper_id}"
    rows = [
        _completed_draft_ready(project_id, run_id, related_paper_id=paper_id),
        _paper(project_id, run_id, paper_id),
    ]

    counts = operator_counts_from_rows(rows)
    detail = operator_detail_counts_from_rows(rows)

    assert counts[OperatorLane.READY_TO_PUBLISH.value] == 1
    assert counts.get(OperatorLane.WRITE_PAPER.value, 0) == 0
    assert counts["total_operator_items"] == 1
    assert detail["ready_to_publish"] == 1
    assert "run_complete_draft_needed" not in detail


@given(project_id=safe_id, active_run_id=safe_id, completed_run_id=safe_id, paper_id=safe_id)
@settings(max_examples=80)
def test_active_queue_precedence_over_completed_duplicate_rows(project_id: str, active_run_id: str, completed_run_id: str, paper_id: str) -> None:
    rows = [
        _completed_draft_ready(project_id, completed_run_id, related_paper_id=f"paper-{paper_id}"),
        _active_queue(project_id, active_run_id),
    ]

    counts = operator_counts_from_rows(rows)
    detail = operator_detail_counts_from_rows(rows)

    assert counts[OperatorLane.RUNNING.value] == 1
    assert counts["total_operator_items"] == 1
    assert detail["running"] == 1
    assert "run_complete_draft_needed" not in detail


def test_operator_counts_match_detail_counts_for_mixed_lifecycle_rows() -> None:
    rows = [
        _active_queue("active-project", "active-run"),
        _completed_draft_ready("paper-project", "paper-run", related_paper_id="paper-1"),
        _paper("paper-project", "paper-run", "paper-1"),
        {"project_id": "queued-project", "status": "queued"},
        {"project_id": "blocked-project", "status": "blocked"},
        {"paper_id": "imported-paper", "project_id": "imported-project", "paper_status": "publication_draft", "corpus_imported": True},
    ]

    counts = operator_counts_from_rows(rows)
    detail = operator_detail_counts_from_rows(rows)

    assert counts[OperatorLane.RUNNING.value] == detail["running"] == 1
    assert counts[OperatorLane.READY_TO_PUBLISH.value] == detail["ready_to_publish"] == 1
    assert counts[OperatorLane.READY_QUEUE.value] == detail["idea_queued"] == 1
    assert counts[OperatorLane.NEEDS_OPERATOR.value] == detail["blocked_needs_operator"] == 1
    assert counts[OperatorLane.PUBLISHED.value] == detail["published"] == 1
    assert counts["needs_attention"] == 1
    assert counts["total_operator_items"] == 5
