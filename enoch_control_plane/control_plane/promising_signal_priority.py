"""Deterministic promising-signal follow-up prioritization helpers.

These helpers intentionally derive priority only from persisted control-plane
fields. They do not read the public promising-signals repo and they do not ask
an LLM to classify rows at dispatch time.
"""

from __future__ import annotations

import json
from typing import Any

from enoch_control_plane.timeutils import parse_utc_datetime
from enoch_control_plane.url_safety import looks_like_external_source_reference

TOP_EXTERNAL_RESEARCHER_CANDIDATES = "top_external_researcher_candidates"
COMPUTE_SCALE_BLOCKED = "compute_scale_blocked"
FOLLOWUP_RECOMMENDED = "followup_recommended"
WEAK_LOCAL_ONLY_PRESERVED = "weak_local_only_preserved"
LIKELY_STALE_LOW_VALUE_ARCHIVE = "likely_stale_low_value_archive"

RANKING_BUCKET_ORDER = (
    TOP_EXTERNAL_RESEARCHER_CANDIDATES,
    COMPUTE_SCALE_BLOCKED,
    FOLLOWUP_RECOMMENDED,
    WEAK_LOCAL_ONLY_PRESERVED,
    LIKELY_STALE_LOW_VALUE_ARCHIVE,
)

MIN_FOLLOWUP_REQUIRED_EVIDENCE = 2

_SCALE_ONLY_MARKERS = (
    "datacenter",
    "hyperscaler",
    "multi-gpu",
    "multi gpu",
    "cluster",
    "large model",
    "large-model",
    "larger model",
    "70b",
    "7b",
    "train for days",
    "full scale",
    "full-scale",
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


def _listish(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return [text]
        if isinstance(parsed, list):
            return parsed
        return [parsed]
    return [value]


def _payload(row: dict[str, Any]) -> dict[str, Any]:
    value = row.get("source_payload_json") or row.get("idea_source_payload_json") or {}
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            value = {}
    return value if isinstance(value, dict) else {}


def _sources_present(row: dict[str, Any]) -> tuple[bool, bool]:
    payload = _payload(row)
    records = _listish(row.get("source_records") or payload.get("source_records"))
    source_ids = _listish(row.get("source_ids") or payload.get("source_ids"))
    source_urls = _listish(row.get("source_urls") or payload.get("source_urls"))
    source_url = _text(row.get("source_url") or payload.get("source_url"))
    source_id = _text(row.get("source_id") or payload.get("source_id"))
    has_source = bool(records or source_ids or source_urls or source_url or source_id)
    candidates = [
        _text(source_url),
        _text(source_id),
        *[_text(v) for v in source_urls],
        *[_text(v) for v in source_ids],
    ]
    for record in records:
        if isinstance(record, dict):
            candidates.extend(
                [_text(record.get("url")), _text(record.get("source_id"))]
            )
        else:
            candidates.append(_text(record))
    has_external = any(
        looks_like_external_source_reference(item) for item in candidates if item
    )
    return has_source, has_external


def _strength_score(value: Any) -> int:
    text = _normal(value)
    if text in {"strong", "high"}:
        return 35
    if text in {"moderate", "medium"}:
        return 25
    if text in {"weak", "low"}:
        return 10
    return 0


def _hypothesis_score(value: Any) -> int:
    text = _normal(value)
    if text in {"supported", "supportive", "confirmed"}:
        return 30
    if text in {"partially_supported", "partly_supported"}:
        return 20
    if text in {"mixed", "inconclusive_but_useful"}:
        return 15
    if text in {"unsupported", "not_supported", "negative", "falsified"}:
        return -15
    return 0


def _followup_evidence(row: dict[str, Any]) -> list[str]:
    return [
        _text(item)
        for item in _listish(row.get("followup_required_evidence"))
        if _text(item)
    ]


def _followup_score(row: dict[str, Any]) -> int:
    score = 0
    if _truthy(row.get("followup_recommended")):
        score += 10
    score += min(5, len(_followup_evidence(row)) * 2)
    try:
        depth = int(row.get("followup_depth") or row.get("source_followup_depth") or 0)
    except (TypeError, ValueError):
        depth = 0
    if depth > 2:
        score -= min(15, (depth - 2) * 5)
    return score


def _bounded_evidence_score(row: dict[str, Any]) -> int:
    artifact_paths = [
        _text(item) for item in _listish(row.get("artifact_paths")) if _text(item)
    ]
    score = min(10, len(artifact_paths) * 2)
    joined_paths = " ".join(path.lower() for path in artifact_paths)
    if "metrics" in joined_paths:
        score += 4
    if "project_decision" in joined_paths:
        score += 4
    if _text(row.get("claim_scope")) and _text(row.get("scale_limits")):
        score += 4
    return score


def _has_promising_signal_fields(row: dict[str, Any]) -> bool:
    return any(
        _text(row.get(key))
        for key in (
            "research_outcome",
            "hypothesis_status",
            "evidence_strength",
            "claim_scope",
            "scale_limits",
            "useful_signal_summary",
        )
    )


def promising_signal_score(row: dict[str, Any]) -> int:
    """Return the deterministic 0-100 promising-signal score for a queue row."""

    source_present, external_present = _sources_present(row)
    source_score = 0
    if source_present:
        source_score += 8
    else:
        source_score -= 20
    if external_present:
        source_score += 4
    raw = (
        _strength_score(row.get("evidence_strength"))
        + _hypothesis_score(row.get("hypothesis_status"))
        + source_score
        + _followup_score(row)
        + _bounded_evidence_score(row)
    )
    return max(0, min(100, raw))


def promising_signal_bucket(row: dict[str, Any]) -> str:
    """Bucket a persisted row using the same deterministic ranking contract as export."""

    if _truthy(row.get("compute_scale_blocked")):
        return COMPUTE_SCALE_BLOCKED
    hypothesis = _normal(row.get("hypothesis_status"))
    score = promising_signal_score(row)
    if hypothesis in {"unsupported", "not_supported", "negative", "falsified"}:
        return LIKELY_STALE_LOW_VALUE_ARCHIVE
    if _has_promising_signal_fields(row) and score < 35:
        return LIKELY_STALE_LOW_VALUE_ARCHIVE
    if score >= 85 and _normal(row.get("evidence_strength")) in {
        "strong",
        "high",
        "moderate",
        "medium",
    }:
        return TOP_EXTERNAL_RESEARCHER_CANDIDATES
    if _truthy(row.get("followup_recommended")) and score >= 45:
        return FOLLOWUP_RECOMMENDED
    return WEAK_LOCAL_ONLY_PRESERVED


def _followup_exceeds_local_compute(row: dict[str, Any]) -> bool:
    haystack = " ".join(
        [
            _text(row.get("followup_hypothesis")),
            *_followup_evidence(row),
            _text(row.get("followup_success_threshold")),
            _text(row.get("followup_stop_condition")),
        ]
    ).lower()
    return any(marker in haystack for marker in _SCALE_ONLY_MARKERS)


def _followup_depth(row: dict[str, Any]) -> int:
    values: list[int] = []
    for key in ("followup_depth", "source_followup_depth"):
        try:
            values.append(int(row.get(key) or 0))
        except (TypeError, ValueError):
            values.append(0)
    return max(values or [0])


def _followup_not_ready_reason(
    row: dict[str, Any],
    *,
    bucket: str,
    max_followup_depth: int,
    explicit_project: bool,
) -> str | None:
    if not _truthy(row.get("followup_recommended")):
        return "followup_not_recommended"
    if _normal(row.get("status") or row.get("queue_status")) != "completed":
        return "not_completed"
    if _truthy(row.get("manual_review_required")):
        return "manual_review_required"
    if _truthy(row.get("followup_launched")):
        return "followup_already_launched"
    if _truthy(row.get("compute_scale_blocked")):
        return "compute_scale_blocked"
    if _followup_depth(row) >= max_followup_depth:
        return "max_followup_depth"
    if _normal(row.get("followup_type")) not in {"deepen", "branch", "retry"}:
        return "unsupported_followup_type"
    if not _text(row.get("followup_title")) or not _text(
        row.get("followup_hypothesis")
    ):
        return "missing_followup_identity"
    if len(_followup_evidence(row)) < MIN_FOLLOWUP_REQUIRED_EVIDENCE:
        return "required_evidence_too_sparse"
    if not _text(row.get("followup_success_threshold")) or not _text(
        row.get("followup_stop_condition")
    ):
        return "missing_followup_bounds"
    if _followup_exceeds_local_compute(row):
        return "followup_exceeds_local_compute"
    if bucket == LIKELY_STALE_LOW_VALUE_ARCHIVE and not explicit_project:
        return LIKELY_STALE_LOW_VALUE_ARCHIVE
    return None


def ranked_followup_readiness(
    row: dict[str, Any], *, max_followup_depth: int = 4, explicit_project: bool = False
) -> dict[str, Any]:
    """Return deterministic readiness metadata for auto follow-up selection."""

    bucket = promising_signal_bucket(row)
    score = promising_signal_score(row)
    not_ready = _followup_not_ready_reason(
        row,
        bucket=bucket,
        max_followup_depth=max_followup_depth,
        explicit_project=explicit_project,
    )
    if not_ready:
        return {
            "ready": False,
            "reason": not_ready,
            "bucket": bucket,
            "score": score,
        }
    return {
        "ready": True,
        "reason": "ranked_bounded_followup_ready",
        "bucket": bucket,
        "score": score,
    }


def _timestamp_sort_value(value: Any) -> float:
    text = _text(value)
    if not text:
        return 0.0
    parsed = parse_utc_datetime(text)
    return parsed.timestamp() if parsed is not None else 0.0


def promising_followup_priority_key(row: dict[str, Any]) -> tuple[int, int, float]:
    """Sort key for bounded follow-ups. Lower is higher priority."""

    bucket = promising_signal_bucket(row)
    bucket_rank = {
        TOP_EXTERNAL_RESEARCHER_CANDIDATES: 0,
        COMPUTE_SCALE_BLOCKED: 1,
        FOLLOWUP_RECOMMENDED: 2,
        WEAK_LOCAL_ONLY_PRESERVED: 3,
        LIKELY_STALE_LOW_VALUE_ARCHIVE: 9,
    }.get(bucket, 8)
    return (
        bucket_rank,
        -promising_signal_score(row),
        -_timestamp_sort_value(row.get("updated_at")),
    )
