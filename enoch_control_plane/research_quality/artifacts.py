from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any

from .datasets import (
    CandidateRow,
    DecisionRow,
    classify_candidate_contract,
    classify_decision_quality,
    pairwise_similarity,
    top_category_counts,
)


def build_quality_report(
    *,
    candidates: list[CandidateRow],
    decisions: list[DecisionRow],
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    candidate_scores = []
    for row in candidates:
        score, problems = classify_candidate_contract(row)
        candidate_scores.append(
            {
                "candidate_id": row.candidate_id,
                "title": row.title,
                "status": row.status,
                "deterministic_total_score": row.total_score,
                "contract_quality_score": score,
                "problems": problems,
            }
        )

    decision_scores = []
    for row in decisions:
        score, problems = classify_decision_quality(row)
        decision_scores.append(
            {
                "project_id": row.project_id,
                "project_name": row.project_name,
                "run_id": row.run_id,
                "decision": row.decision,
                "hypothesis_status": row.hypothesis_status,
                "evidence_strength": row.evidence_strength,
                "research_outcome": row.research_outcome,
                "claim_scope": row.claim_scope,
                "scale_limits": row.scale_limits,
                "bounded_paper_ready": row.bounded_paper_ready,
                "compute_scale_blocked": row.compute_scale_blocked,
                "followup_recommended": row.followup_recommended,
                "followup_type": row.followup_type,
                "followup_title": row.followup_title,
                "followup_hypothesis": row.followup_hypothesis,
                "followup_required_evidence_count": row.followup_required_evidence_count,
                "followup_success_threshold": row.followup_success_threshold,
                "followup_stop_condition": row.followup_stop_condition,
                "recommended_next_action": row.recommended_next_action,
                "stop_reason": row.stop_reason,
                "decision_quality_score": score,
                "problems": problems,
                "created_at": row.created_at,
            }
        )

    decision_counts = Counter(
        (row.decision, row.hypothesis_status) for row in decisions
    )
    problem_counts = Counter(
        problem
        for item in candidate_scores + decision_scores
        for problem in item["problems"]
    )

    return {
        "schema_version": "enoch_research_quality_report_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "read_only_sidecar",
        "runtime_effect": "none",
        "metadata": metadata or {},
        "summary": {
            "candidate_count": len(candidates),
            "decision_count": len(decisions),
            "candidate_status_counts": dict(Counter(row.status for row in candidates)),
            "decision_counts": [
                {"decision": decision, "hypothesis_status": hypothesis, "count": count}
                for (decision, hypothesis), count in decision_counts.most_common()
            ],
            "top_candidate_categories": top_category_counts(candidates),
            "problem_counts": dict(problem_counts.most_common()),
            "high_similarity_pair_count": len(
                pairwise_similarity(candidates, threshold=0.55, limit=10_000)
            ),
        },
        "candidate_scores": candidate_scores,
        "decision_scores": decision_scores,
        "high_similarity_pairs": pairwise_similarity(candidates),
        "recommendations": recommendation_list(candidate_scores, decision_scores),
    }


def recommendation_list(
    candidate_scores: list[dict[str, Any]], decision_scores: list[dict[str, Any]]
) -> list[str]:
    recommendations: list[str] = []
    if any(
        "supported_but_negative_requires_review" in item["problems"]
        for item in decision_scores
    ):
        recommendations.append(
            "Inspect supported-but-negative decisions; they may indicate overly strict paper gating or weak evidence despite partial support."
        )
    if any(
        "followup_thin_required_evidence" in item["problems"]
        for item in decision_scores
    ):
        recommendations.append(
            "Strengthen follow-up required-evidence lists before allowing auto-branching from those decisions."
        )
    if any(
        "similar_prior_without_novelty_comparison" in item["problems"]
        for item in candidate_scores
    ):
        recommendations.append(
            "Require explicit novelty comparison when Research Facility candidates resemble prior work."
        )
    if not recommendations:
        recommendations.append(
            "No critical quality-layer warnings from the read-only audit heuristics."
        )
    return recommendations
