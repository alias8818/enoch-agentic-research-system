"""Shared promising-signal curation scoring.

Both the control-plane follow-up selector and the public promising-signal export
use this module so score and bucket semantics cannot drift between operator
queues and human-facing exports.
"""

from __future__ import annotations

from typing import Any, cast

from enoch_control_plane.url_safety import looks_like_external_source_reference

RANKING_SCHEMA_VERSION = "enoch_promising_signal_ranking_v1"

TOP_EXTERNAL_RESEARCHER_CANDIDATES = "top_external_researcher_candidates"
COMPUTE_SCALE_BLOCKED = "compute_scale_blocked"
FOLLOWUP_RECOMMENDED = "followup_recommended"
WEAK_LOCAL_ONLY_PRESERVED = "weak_local_only_preserved"
LIKELY_STALE_LOW_VALUE_ARCHIVE = "likely_stale_low_value_archive"

RANKING_BUCKETS: dict[str, str] = {
    TOP_EXTERNAL_RESEARCHER_CANDIDATES: "Top external-researcher candidates",
    COMPUTE_SCALE_BLOCKED: "Compute-scale blocked",
    FOLLOWUP_RECOMMENDED: "Follow-up recommended",
    WEAK_LOCAL_ONLY_PRESERVED: "Weak/local-only preserved signals",
    LIKELY_STALE_LOW_VALUE_ARCHIVE: "Likely stale/low-value archive",
}

RANKING_BUCKET_ORDER = (
    TOP_EXTERNAL_RESEARCHER_CANDIDATES,
    COMPUTE_SCALE_BLOCKED,
    FOLLOWUP_RECOMMENDED,
    WEAK_LOCAL_ONLY_PRESERVED,
    LIKELY_STALE_LOW_VALUE_ARCHIVE,
)


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace").strip()
    return str(value).strip()


def _normal(value: Any) -> str:
    return _text(value).lower().replace("-", "_").replace(" ", "_")


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return _text(value).lower() in {"1", "true", "yes", "y", "on"}


def _list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _strength_score(value: Any) -> tuple[int, str]:
    text = _normal(value)
    if text in {"strong", "high"}:
        return 35, "strong evidence_strength"
    if text in {"moderate", "medium"}:
        return 25, "moderate evidence_strength"
    if text in {"weak", "low"}:
        return 10, "weak evidence_strength"
    return 0, "missing or unclear evidence_strength"


def _hypothesis_score(value: Any) -> tuple[int, str]:
    text = _normal(value)
    if text in {"supported", "supportive", "confirmed"}:
        return 30, "supported hypothesis_status"
    if text in {"partially_supported", "partly_supported"}:
        return 20, "partially supported hypothesis_status"
    if text in {"mixed", "inconclusive_but_useful"}:
        return 15, "mixed hypothesis_status"
    if text in {"unsupported", "not_supported", "negative", "falsified"}:
        return -15, "unsupported hypothesis_status"
    return 0, "missing or unclear hypothesis_status"


def _has_external_source(sources: list[dict[str, Any]]) -> bool:
    for source in sources:
        if looks_like_external_source_reference(_text(source.get("url"))):
            return True
        if looks_like_external_source_reference(_text(source.get("source_id"))):
            return True
    return False


def _source_lineage_score(sources: list[dict[str, Any]]) -> tuple[int, list[str]]:
    reasons: list[str] = []
    if sources:
        score = 8
        reasons.append("source lineage present")
    else:
        score = -20
        reasons.append("source lineage missing")
    if _has_external_source(sources):
        score += 4
        reasons.append("external source URL present")
    return score, reasons


def _followup_score(followup: dict[str, Any]) -> tuple[int, list[str]]:
    reasons: list[str] = []
    score = 0
    if _truthy(followup.get("recommended")):
        score += 10
        reasons.append("bounded follow-up is specified")
    required_evidence = [
        _text(item) for item in _list(followup.get("required_evidence")) if _text(item)
    ]
    score += min(5, len(required_evidence) * 2)
    try:
        depth = int(followup.get("depth") or 0)
    except (TypeError, ValueError):
        depth = 0
    if depth > 2:
        score -= min(15, (depth - 2) * 5)
        reasons.append("follow-up depth is already high")
    return score, reasons


def _bounded_evidence_score(signal: dict[str, Any]) -> tuple[int, list[str]]:
    reasons: list[str] = []
    raw_evidence = signal.get("evidence")
    evidence = (
        cast(dict[str, Any], raw_evidence) if isinstance(raw_evidence, dict) else {}
    )
    artifact_paths = [
        _text(item) for item in _list(evidence.get("artifact_paths")) if _text(item)
    ]
    score = min(10, len(artifact_paths) * 2)
    if artifact_paths:
        reasons.append("local evidence artifact paths are present")
    joined_paths = " ".join(path.lower() for path in artifact_paths)
    if "metrics" in joined_paths:
        score += 4
        reasons.append("metrics artifact is present")
    if "project_decision" in joined_paths:
        score += 4
        reasons.append("project decision artifact is present")
    raw_disclaimer = signal.get("do_not_overclaim")
    disclaimer = (
        cast(dict[str, Any], raw_disclaimer) if isinstance(raw_disclaimer, dict) else {}
    )
    if (
        disclaimer.get("not_a_paper") is True
        and _text(signal.get("claim_scope"))
        and _text(signal.get("scale_limits"))
    ):
        score += 4
    return score, reasons


def _ranking_bucket(
    signal: dict[str, Any], *, score: int, followup: dict[str, Any]
) -> str:
    if _text(signal.get("status")) == COMPUTE_SCALE_BLOCKED:
        return COMPUTE_SCALE_BLOCKED
    hypothesis_text = _normal(signal.get("hypothesis_status"))
    if (
        hypothesis_text in {"unsupported", "not_supported", "negative", "falsified"}
        or score < 35
    ):
        return LIKELY_STALE_LOW_VALUE_ARCHIVE
    if score >= 85 and _normal(signal.get("evidence_strength")) in {
        "strong",
        "high",
        "moderate",
        "medium",
    }:
        return TOP_EXTERNAL_RESEARCHER_CANDIDATES
    if _truthy(followup.get("recommended")) and score >= 45:
        return FOLLOWUP_RECOMMENDED
    return WEAK_LOCAL_ONLY_PRESERVED


def rank_signal(signal: dict[str, Any]) -> dict[str, Any]:
    """Return deterministic curation metadata derived only from signal fields."""

    score_breakdown: dict[str, int] = {}
    reasons: list[str] = []

    evidence_score, evidence_reason = _strength_score(signal.get("evidence_strength"))
    score_breakdown["evidence_strength"] = evidence_score
    reasons.append(evidence_reason)

    hypothesis_score, hypothesis_reason = _hypothesis_score(
        signal.get("hypothesis_status")
    )
    score_breakdown["hypothesis_status"] = hypothesis_score
    reasons.append(hypothesis_reason)

    raw_sources = signal.get("sources")
    sources = (
        cast(list[dict[str, Any]], raw_sources) if isinstance(raw_sources, list) else []
    )
    source_score, source_reasons = _source_lineage_score(sources)
    score_breakdown["source_lineage"] = source_score
    reasons.extend(source_reasons)

    raw_followup = signal.get("followup")
    followup = (
        cast(dict[str, Any], raw_followup) if isinstance(raw_followup, dict) else {}
    )
    followup_score, followup_reasons = _followup_score(followup)
    score_breakdown["followup"] = followup_score
    reasons.extend(followup_reasons)

    bounded_score, bounded_reasons = _bounded_evidence_score(signal)
    score_breakdown["bounded_evidence"] = bounded_score
    reasons.extend(bounded_reasons)

    raw_score = sum(score_breakdown.values())
    score = max(0, min(100, raw_score))
    bucket = _ranking_bucket(signal, score=score, followup=followup)

    return {
        "schema_version": RANKING_SCHEMA_VERSION,
        "score": score,
        "bucket": bucket,
        "bucket_label": RANKING_BUCKETS[bucket],
        "score_breakdown": score_breakdown,
        "reasons": reasons,
    }
