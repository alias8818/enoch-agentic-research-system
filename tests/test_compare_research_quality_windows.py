from __future__ import annotations

from enoch_control_plane.research_quality.datasets import CandidateRow, DecisionRow
from scripts.build_research_quality_evalset import RawDecision
from scripts.compare_research_quality_windows import compare_windows, summarize_window


def _candidate(
    candidate_id: str,
    title: str,
    *,
    mode: str = "moonshot",
    status: str = "admitted",
    score: float = 75.0,
) -> CandidateRow:
    return CandidateRow(
        candidate_id=candidate_id,
        title=title,
        category="kv-compression",
        status=status,
        total_score=score,
        generation_mode=mode,
        mechanism="exact anchor KV selection with query overlap",
        baseline_to_beat="recency KV retention",
        success_threshold="beat recency",
        kill_condition="stop if no lift",
        required_evidence_count=3,
        expected_artifact_count=3,
    )


def _decision(
    project_id: str, *, hypothesis_status: str, stop_reason: str
) -> RawDecision:
    row = {
        "followup_depth": 2,
        "payload_json": {
            "project_decision": {
                "project_decision": "finalize_negative",
                "hypothesis_status": hypothesis_status,
                "evidence_strength": "moderate",
                "stop_reason": stop_reason,
                "recommended_next_action": "Stop this proxy-only branch unless direct evidence changes.",
            }
        },
    }
    return RawDecision(
        row=row,
        decision=DecisionRow(
            project_id=project_id,
            project_name=project_id,
            run_id=f"{project_id}-run",
            decision="finalize_negative",
            hypothesis_status=hypothesis_status,
            evidence_strength="moderate",
            confidence="medium",
            followup_recommended=False,
            followup_type="",
            followup_title="",
            followup_hypothesis="",
            followup_required_evidence_count=0,
            followup_success_threshold="",
            followup_stop_condition="",
            recommended_next_action="Stop this proxy-only branch unless direct evidence changes.",
            stop_reason=stop_reason,
            created_at="2026-05-11T00:00:00Z",
        ),
    )


def test_summarize_window_reports_quality_metrics() -> None:
    summary = summarize_window(
        candidates=[
            _candidate("a", "Exact Anchor KV"),
            _candidate("b", "Exact Anchor KV Variant", status="needs_review", score=70),
        ],
        decisions=[
            _decision(
                "p",
                hypothesis_status="supported",
                stop_reason="Proxy-only evidence supports the mechanism but is not direct enough for publication readiness.",
            )
        ],
        max_followup_depth=2,
    )

    assert summary["candidate_count"] == 2
    assert summary["moonshot_count"] == 2
    assert summary["admitted_rate"] == 0.5
    assert summary["high_similarity_pair_count"] >= 1
    assert summary["eval_case_counts"]["proxy_only_positive"] == 1


def test_compare_windows_reports_deltas() -> None:
    pre = {
        "high_similarity_pair_count": 2,
        "moonshot_avg_score": 70,
        "admitted_rate": 0.5,
        "eval_case_counts": {"proxy_only_positive": 3, "useful_adjacent_followup": 1},
    }
    post = {
        "high_similarity_pair_count": 1,
        "moonshot_avg_score": 75,
        "admitted_rate": 0.75,
        "eval_case_counts": {"proxy_only_positive": 1, "useful_adjacent_followup": 2},
    }
    delta = compare_windows(pre, post)
    assert delta["duplicateish_delta"] == -1
    assert delta["proxy_only_positive_delta"] == -2
    assert delta["useful_adjacent_followup_delta"] == 1
    assert delta["moonshot_avg_score_delta"] == 5
    assert delta["admitted_rate_delta"] == 0.25
