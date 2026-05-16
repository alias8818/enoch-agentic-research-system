from scripts.paper_scout import ScoutRow, scout


def row(payload):
    return ScoutRow(
        decision_id=1,
        project_id="p1",
        project_name="P1",
        run_id="r1",
        decided_at="2026-05-16T00:00:00Z",
        payload={"project_decision": payload},
    )


def test_scout_marks_scoped_useful_signal_eligible():
    payload = {
        "project_decision": "finalize_negative",
        "research_outcome": "useful_signal",
        "hypothesis_status": "supported",
        "evidence_strength": "moderate",
        "bounded_paper_ready": False,
        "compute_scale_blocked": False,
        "claim_scope": "On GPT-2-small Wikitext-2 with three fixed seeds, method A beats baseline B under a scoped local benchmark.",
        "scale_limits": "Single local model and public dataset only; no larger model family, production serving, or long-context task validation.",
        "useful_signal_summary": "Method A reached 1.25x speed and 0.04 lower loss versus baseline B across 3 seeds and 128 prompts.",
        "stop_reason": "No-paper result only because broader publication-grade validation is still missing.",
        "recommended_next_action": "Prepare a scoped bounded paper; do not claim broad production readiness.",
    }
    result = scout([row(payload)], threshold=80)[0]
    assert result.eligible
    assert result.score >= 80


def test_scout_blocks_compute_scale_signal():
    payload = {
        "project_decision": "finalize_negative",
        "research_outcome": "useful_signal",
        "hypothesis_status": "supported",
        "evidence_strength": "strong",
        "bounded_paper_ready": False,
        "compute_scale_blocked": True,
        "claim_scope": "On GPT-2-small Wikitext-2 with three fixed seeds, method A beats baseline B under a scoped local benchmark.",
        "scale_limits": "Single local model and public dataset only; no larger model family, production serving, or long-context task validation.",
        "useful_signal_summary": "Method A reached 1.25x speed and 0.04 lower loss versus baseline B across 3 seeds and 128 prompts.",
        "stop_reason": "No-paper result only because broader publication-grade validation is still missing.",
        "recommended_next_action": "Prepare a scoped bounded paper; do not claim broad production readiness.",
    }
    result = scout([row(payload)], threshold=80)[0]
    assert not result.eligible
    assert "compute-scale blocked" in result.blockers
