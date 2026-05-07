from pathlib import Path

from omx_wake_gate.control_plane.read_models import operator_counts_from_rows, operator_stage_for_record

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
    ]:
        assert required in text


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
            "followup_title": "Adjacent bounded test",
            "followup_hypothesis": "A narrower condition could still work.",
        }
    )
    assert followup["operator_stage"] == "followup_investigation"
    assert followup["operator_detail_stage"] == "followup_candidate"
    assert followup["operator_attention"] is False
    assert followup["paper_draft_eligible"] is False


def test_transition_map_matches_publication_readiness_invariants() -> None:
    draft_only = operator_stage_for_record({"paper_id": "p1", "paper_status": "publication_draft"})
    assert draft_only["operator_stage"] == "automate_publication"
    assert draft_only["operator_detail_stage"] == "finalization_needed"

    finalized = operator_stage_for_record(
        {
            "paper_id": "p1",
            "paper_status": "publication_draft",
            "review_status": "finalized",
            "finalization_package_path": "package.json",
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
