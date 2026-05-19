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
    research_outcome: str = ""
    claim_scope: str = ""
    scale_limits: str = ""
    bounded_paper_ready: bool = False
    compute_scale_blocked: bool = False


def as_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "y", "on"}:
            return True
        if normalized in {"0", "false", "no", "n", "off", ""}:
            return False
    return bool(value)


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


PAPER_LIMIT_MARKERS = (
    "no-paper",
    "paper-positive",
    "paper positive",
    "paper-ready",
    "publishable",
    "proxy-only",
    "do not write a paper",
    "publication-grade",
    "publication ready",
    "publication-ready",
    "paper gating",
    "paper gate",
    "considering publication",
    "paper promotion",
    "tier-4 paper-ready",
)

EVIDENCE_LIMIT_MARKERS = (
    "proxy-only",
    "proxy only",
    "synthetic/proxy",
    "synthetic proxy",
    "synthetic",
    "insufficient",
    "full-scale",
    "full validation",
    "trace",
    "small-model",
    "small model",
    "gpt-2",
    "distilgpt2",
    "short-context",
    "token streams",
    "in-process",
    "serving path",
    "production serving",
    "end-to-end",
    "memory pressure",
    "concurrency",
    "reconstructed",
    "actual production trace",
    "production-grade",
    "unoptimized",
    "rather than",
    "limited to",
)

DEPTH_CAP_MARKERS = (
    "follow-up depth",
    "followup depth",
    "depth 2",
    "depth-2",
    "depth 3",
    "depth-3",
    "depth 4",
    "depth-4",
    "lineage cap",
    "controller lineage cap",
    "max follow",
    "cap prevents recommending",
)


def negative_rationale(row_or_item: Any) -> str:
    if isinstance(row_or_item, dict):
        return " ".join([
            as_text(row_or_item.get("stop_reason")),
            as_text(row_or_item.get("recommended_next_action")),
        ]).lower()
    return " ".join([row_or_item.stop_reason, row_or_item.recommended_next_action]).lower()


def has_marker(value: str, markers: tuple[str, ...]) -> bool:
    return any(marker in value for marker in markers)


def has_paper_limit_rationale(value: str) -> bool:
    return has_marker(value, PAPER_LIMIT_MARKERS)


def has_evidence_limit_rationale(value: str) -> bool:
    return has_marker(value, EVIDENCE_LIMIT_MARKERS)


def has_depth_cap_rationale(value: str) -> bool:
    return has_marker(value, DEPTH_CAP_MARKERS)


def has_substantive_negative_rationale(row: DecisionRow) -> bool:
    if len(row.stop_reason) < 40 or len(row.recommended_next_action) < 40:
        return False
    combined = negative_rationale(row)
    return has_paper_limit_rationale(combined) and has_evidence_limit_rationale(combined)


def is_supported_negative_nonblocking(
    *,
    decision: str,
    hypothesis_status: str,
    followup_recommended: bool,
    rationale: str,
    bounded_followup: bool = False,
    research_outcome: str = "",
    claim_scope: str = "",
    scale_limits: str = "",
    evidence_strength: str = "",
    bounded_paper_ready: bool = False,
) -> bool:
    """Return true for supported no-paper decisions that are intentional.

    A supported mechanism can still be a correct no-paper result when the run is
    explicitly bounded by scale/evidence limits and either launches a concrete
    next tier or has reached a controller lineage/depth cap. This is the core
    Research Quality distinction that prevents long-haul readiness from being
    blocked by healthy ladder behavior.
    """

    if decision != "finalize_negative" or hypothesis_status != "supported":
        return False
    scoped_useful_signal = (
        research_outcome == "useful_signal"
        and not bounded_paper_ready
        and evidence_strength in {"moderate", "strong"}
        and len(claim_scope.strip()) >= 40
        and len(scale_limits.strip()) >= 40
        and (has_paper_limit_rationale(rationale) or has_evidence_limit_rationale(rationale))
    )
    if scoped_useful_signal:
        return True
    paper_limited = has_paper_limit_rationale(rationale)
    evidence_limited = has_evidence_limit_rationale(rationale)
    depth_capped = has_depth_cap_rationale(rationale)
    if followup_recommended:
        return bounded_followup or paper_limited or evidence_limited
    return depth_capped and paper_limited and evidence_limited


def classify_decision_quality(row: DecisionRow) -> tuple[float, list[str]]:
    problems: list[str] = []
    if row.decision == "unknown":
        problems.append("unknown_decision")
    if row.decision == "finalize_negative" and row.hypothesis_status == "supported":
        bounded_followup = has_bounded_followup(row) and has_substantive_negative_rationale(row)
        if not is_supported_negative_nonblocking(
            decision=row.decision,
            hypothesis_status=row.hypothesis_status,
            followup_recommended=row.followup_recommended,
            rationale=negative_rationale(row),
            bounded_followup=bounded_followup,
            research_outcome=row.research_outcome,
            claim_scope=row.claim_scope,
            scale_limits=row.scale_limits,
            evidence_strength=row.evidence_strength,
            bounded_paper_ready=row.bounded_paper_ready,
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
