from pathlib import Path

from enoch_control_plane.control_plane.read_models import (
    operator_counts_from_rows,
    operator_stage_for_record,
)

DOC = Path("docs/state-transition-map.md")


def test_transition_map_documents_every_lifecycle_edge() -> None:
    text = DOC.read_text(encoding="utf-8")
    for edge in [
        "Idea -> Queue",
        "Queue -> Run",
        "Run -> Decision",
        "Decision -> Follow-up Investigation",
        "Decision -> Paper",
        "Paper -> Publication",
        "Publication -> Corpus",
        "Corpus -> Public release/HF",
    ]:
        assert edge in text
    for required in [
        "Source of truth",
        "Writer/owner",
        "Validation gate",
        "Invalid/impossible transition",
        "Operator lane shown",
        "Paper readiness decision tree",
        "Evidence maturity",
        "Claim readiness gate",
    ]:
        assert required in text


def test_transition_map_documents_paper_readiness_contract() -> None:
    text = DOC.read_text(encoding="utf-8")
    for state in [
        "execution_complete",
        "pilot_signal",
        "analysis_ready",
        "deepen_required",
        "paper_candidate",
        "paper_ready",
        "archive_no_paper",
    ]:
        assert state in text
    for edge in [
        "run_completed --> execution_complete",
        "execution_complete --> pilot_signal",
        "analysis_ready --> deepen_required",
        "paper_candidate --> paper_ready",
    ]:
        assert edge in text


def test_transition_map_matches_decision_gate_operator_invariants() -> None:
    base = {
        "status": "completed",
        "last_run_state": "wake_ready",
        "next_action_hint": "draft_paper_or_select_next_project",
        "current_run_id": "run-1",
    }
    positive = operator_stage_for_record({**base, "decision_gate_state": "positive"})
    assert positive["operator_stage"] == "write_paper"
    assert positive["operator_detail_stage"] == "run_complete_draft_needed"

    for state in ("negative", "missing", "malformed", "unknown", "needs_review"):
        row = operator_stage_for_record({**base, "decision_gate_state": state})
        assert row["operator_stage"] == "complete_no_paper"
        assert row["operator_detail_stage"] == "run_complete_no_paper"
        assert row["operator_attention"] is False

    followup = operator_stage_for_record(
        {
            **base,
            "decision_gate_state": "negative",
            "followup_recommended": True,
            "followup_type": "deepen",
            "followup_title": "Adjacent bounded test",
            "followup_hypothesis": "A narrower condition could still work.",
            "followup_required_evidence": ["baseline", "metrics"],
            "followup_success_threshold": "beat baseline",
            "followup_stop_condition": "stop on miss",
        }
    )
    assert followup["operator_stage"] == "followup_investigation"
    assert followup["operator_detail_stage"] == "followup_candidate"
    assert followup["operator_attention"] is False
    assert followup["paper_draft_eligible"] is False

    followup_row = {
        **base,
        "decision_gate_state": "negative",
        "followup_recommended": True,
        "followup_type": "deepen",
        "followup_title": "Adjacent bounded test",
        "followup_hypothesis": "A narrower condition could still work.",
        "followup_required_evidence": ["baseline", "metrics"],
        "followup_success_threshold": "beat baseline",
        "followup_stop_condition": "stop on miss",
    }
    launched_followup = operator_stage_for_record(
        {**followup_row, "followup_launched": True}
    )
    assert launched_followup["operator_stage"] == "complete_no_paper"
    assert launched_followup["operator_detail_stage"] == "run_complete_no_paper"

    unbounded_followup = operator_stage_for_record(
        {**followup_row, "followup_required_evidence": ["baseline"]}
    )
    assert unbounded_followup["operator_stage"] == "complete_no_paper"
    assert unbounded_followup["operator_detail_stage"] == "run_complete_no_paper"

    capped_followup = operator_stage_for_record({**followup_row, "followup_depth": 4})
    assert capped_followup["operator_stage"] == "complete_no_paper"
    assert capped_followup["operator_detail_stage"] == "run_complete_no_paper"

    source_capped_followup = operator_stage_for_record(
        {**followup_row, "followup_depth": 1, "source_followup_depth": 4}
    )
    assert source_capped_followup["operator_stage"] == "complete_no_paper"
    assert source_capped_followup["operator_detail_stage"] == "run_complete_no_paper"


def test_transition_map_matches_publication_readiness_invariants() -> None:
    draft_only = operator_stage_for_record(
        {"paper_id": "p1", "paper_status": "publication_draft"}
    )
    assert draft_only["operator_stage"] == "automate_publication"
    assert draft_only["operator_detail_stage"] == "finalization_needed"

    finalized = operator_stage_for_record(
        {
            "paper_id": "p1",
            "paper_status": "publication_draft",
            "review_status": "finalized",
            "artifact_paths_present": {
                "finalization_package_path": True,
                "draft_markdown_path": True,
                "evidence_bundle_path": True,
                "claim_ledger_path": True,
                "manifest_path": True,
            },
        }
    )
    assert finalized["operator_stage"] == "ready_to_publish"
    assert finalized["operator_detail_stage"] == "ready_to_publish"


def test_operator_counts_do_not_promote_detail_stages() -> None:
    counts = operator_counts_from_rows(
        [
            {
                "status": "completed",
                "last_run_state": "wake_ready",
                "next_action_hint": "draft_paper_or_select_next_project",
                "current_run_id": "run-1",
                "decision_gate_state": "positive",
            }
        ]
    )
    assert counts["write_paper"] == 1
    assert "run_complete_draft_needed" not in counts
