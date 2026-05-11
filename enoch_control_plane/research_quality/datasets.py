from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Any, Iterable

STOPWORDS = {
    "the", "and", "with", "for", "from", "into", "using", "that", "this",
    "local", "agent", "agents", "model", "models", "research", "test",
    "probe", "validation", "system", "systems",
}


@dataclass(frozen=True)
class CandidateRow:
    candidate_id: str
    title: str
    category: str
    status: str
    total_score: float
    generation_mode: str = ""
    mechanism: str = ""
    baseline_to_beat: str = ""
    success_threshold: str = ""
    kill_condition: str = ""
    required_evidence_count: int = 0
    expected_artifact_count: int = 0
    similar_prior_count: int = 0
    novelty_comparison: str = ""


@dataclass(frozen=True)
class DecisionRow:
    project_id: str
    project_name: str
    run_id: str
    decision: str
    hypothesis_status: str
    evidence_strength: str
    confidence: str
    followup_recommended: bool
    followup_type: str
    followup_title: str
    followup_hypothesis: str
    followup_required_evidence_count: int
    followup_success_threshold: str
    followup_stop_condition: str
    recommended_next_action: str
    stop_reason: str
    created_at: str


def as_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def token_set(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", value.lower())
        if len(token) > 2 and token not in STOPWORDS
    }


def jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def top_category_counts(candidates: Iterable[CandidateRow]) -> list[dict[str, Any]]:
    counts = Counter(row.category or "unknown" for row in candidates)
    return [{"category": key, "count": value} for key, value in counts.most_common()]


def pairwise_similarity(rows: list[CandidateRow], *, threshold: float = 0.55, limit: int = 25) -> list[dict[str, Any]]:
    pairs: list[dict[str, Any]] = []
    tokens = [token_set(" ".join([row.title, row.mechanism, row.baseline_to_beat])) for row in rows]
    for i, left in enumerate(rows):
        for j in range(i + 1, len(rows)):
            score = jaccard(tokens[i], tokens[j])
            if score >= threshold:
                right = rows[j]
                pairs.append(
                    {
                        "left_candidate_id": left.candidate_id,
                        "left_title": left.title,
                        "right_candidate_id": right.candidate_id,
                        "right_title": right.title,
                        "similarity": round(score, 3),
                    }
                )
    pairs.sort(key=lambda item: item["similarity"], reverse=True)
    return pairs[:limit]


def classify_candidate_contract(row: CandidateRow) -> tuple[float, list[str]]:
    problems: list[str] = []
    if not row.success_threshold:
        problems.append("missing_success_threshold")
    if not row.kill_condition:
        problems.append("missing_kill_condition")
    if row.required_evidence_count < 3:
        problems.append("thin_required_evidence")
    if row.expected_artifact_count < 3:
        problems.append("thin_expected_artifacts")
    if row.similar_prior_count and not row.novelty_comparison:
        problems.append("similar_prior_without_novelty_comparison")
    score = 1.0 - min(len(problems) * 0.2, 1.0)
    return round(score, 3), problems


def has_bounded_followup(row: DecisionRow) -> bool:
    return (
        row.followup_recommended
        and bool(row.followup_title)
        and bool(row.followup_hypothesis)
        and row.followup_required_evidence_count >= 2
        and bool(row.followup_success_threshold)
        and bool(row.followup_stop_condition)
    )


def has_substantive_negative_rationale(row: DecisionRow) -> bool:
    combined = " ".join([row.stop_reason, row.recommended_next_action]).lower()
    if len(row.stop_reason) < 40 or len(row.recommended_next_action) < 40:
        return False
    paper_negative_markers = ("no-paper", "paper-positive", "paper positive", "paper-ready", "publishable", "proxy-only")
    evidence_limit_markers = ("proxy", "synthetic", "insufficient", "direct", "full-scale", "real")
    return any(marker in combined for marker in paper_negative_markers) and any(marker in combined for marker in evidence_limit_markers)


def classify_decision_quality(row: DecisionRow) -> tuple[float, list[str]]:
    problems: list[str] = []
    if row.decision == "unknown":
        problems.append("unknown_decision")
    if (
        row.decision == "finalize_negative"
        and row.hypothesis_status == "supported"
        and not (has_bounded_followup(row) and has_substantive_negative_rationale(row))
    ):
        problems.append("supported_but_negative_requires_review")
    if row.followup_recommended:
        if not row.followup_title:
            problems.append("followup_missing_title")
        if not row.followup_hypothesis:
            problems.append("followup_missing_hypothesis")
        if row.followup_required_evidence_count < 2:
            problems.append("followup_thin_required_evidence")
        if not row.followup_success_threshold:
            problems.append("followup_missing_success_threshold")
        if not row.followup_stop_condition:
            problems.append("followup_missing_stop_condition")
    if len(row.stop_reason) < 40 and len(row.recommended_next_action) < 40:
        problems.append("thin_stop_rationale")
    if row.evidence_strength in {"", "unknown", "none", "weak"}:
        problems.append("weak_or_missing_evidence_strength")
    score = 1.0 - min(len(problems) * 0.15, 1.0)
    return round(score, 3), problems
