"""Deterministic promising-signal follow-up prioritization helpers.

These helpers intentionally derive priority only from persisted control-plane
fields. They do not read the public promising-signals repo and they do not ask
an LLM to classify rows at dispatch time.
"""

from __future__ import annotations

import json
from typing import Any

from enoch_control_plane.control_plane.promising_signal_scoring import (
    COMPUTE_SCALE_BLOCKED,
    FOLLOWUP_RECOMMENDED,
    LIKELY_STALE_LOW_VALUE_ARCHIVE,
    TOP_EXTERNAL_RESEARCHER_CANDIDATES,
    WEAK_LOCAL_ONLY_PRESERVED,
    rank_signal,
)
from enoch_control_plane.timeutils import parse_utc_datetime

MIN_FOLLOWUP_REQUIRED_EVIDENCE = 2
FOLLOWUP_LAUNCH_SELECTION_RANK = 25
FOLLOWUP_LAUNCH_DISPATCH_PRIORITY = 25

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


def _sources_from_row(row: dict[str, Any]) -> list[dict[str, str]]:
    payload = _payload(row)
    records = _listish(row.get("source_records") or payload.get("source_records"))
    source_ids = _listish(row.get("source_ids") or payload.get("source_ids"))
    source_urls = _listish(row.get("source_urls") or payload.get("source_urls"))
    source_url = _text(row.get("source_url") or payload.get("source_url"))
    source_id = _text(row.get("source_id") or payload.get("source_id"))

    sources: list[dict[str, str]] = []
    max_parallel = max(len(source_urls), len(source_ids))
    for index in range(max_parallel):
        sources.append(
            {
                "url": _text(source_urls[index]) if index < len(source_urls) else "",
                "source_id": _text(source_ids[index])
                if index < len(source_ids)
                else "",
            }
        )
    if source_url or source_id:
        sources.append({"url": source_url, "source_id": source_id})
    for record in records:
        if isinstance(record, dict):
            sources.append(
                {
                    "url": _text(record.get("url")),
                    "source_id": _text(record.get("source_id")),
                }
            )
        else:
            sources.append({"url": "", "source_id": _text(record)})
    return [source for source in sources if source["url"] or source["source_id"]]


def _followup_evidence(row: dict[str, Any]) -> list[str]:
    return [
        _text(item)
        for item in _listish(row.get("followup_required_evidence"))
        if _text(item)
    ]


def _scoring_signal_from_row(row: dict[str, Any]) -> dict[str, Any]:
    try:
        followup_depth = int(
            row.get("followup_depth") or row.get("source_followup_depth") or 0
        )
    except (TypeError, ValueError):
        followup_depth = 0
    return {
        "status": COMPUTE_SCALE_BLOCKED
        if _truthy(row.get("compute_scale_blocked"))
        else _text(row.get("status") or row.get("queue_status")),
        "hypothesis_status": _text(row.get("hypothesis_status")),
        "evidence_strength": _text(row.get("evidence_strength")),
        "claim_scope": _text(row.get("claim_scope")),
        "scale_limits": _text(row.get("scale_limits")),
        "sources": _sources_from_row(row),
        "followup": {
            "recommended": _truthy(row.get("followup_recommended")),
            "required_evidence": _followup_evidence(row),
            "depth": followup_depth,
        },
        "evidence": {"artifact_paths": _listish(row.get("artifact_paths"))},
        "do_not_overclaim": {"not_a_paper": True},
    }


def promising_signal_score(row: dict[str, Any]) -> int:
    """Return the deterministic 0-100 promising-signal score for a queue row."""

    return int(rank_signal(_scoring_signal_from_row(row))["score"])


def promising_signal_bucket(row: dict[str, Any]) -> str:
    """Bucket a persisted row using the same deterministic ranking contract as export."""

    return str(rank_signal(_scoring_signal_from_row(row))["bucket"])


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


def _followup_status_not_ready_reason(row: dict[str, Any]) -> str | None:
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
    return None


def _followup_not_ready_reason(
    row: dict[str, Any],
    *,
    bucket: str,
    max_followup_depth: int,
    explicit_project: bool,
) -> str | None:
    if reason := _followup_status_not_ready_reason(row):
        return reason
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


def _intish(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def followup_launch_queue_priorities(row: dict[str, Any]) -> tuple[int, int]:
    """Return queue priorities for a newly launched bounded follow-up branch.

    Follow-up branches are generated from completed useful-signal rows that the
    strict paper gate intentionally kept out of paper writing. They should not
    sit behind the default fresh-idea backlog indefinitely, but they also should
    not override already higher-priority emergency/operator work.
    """

    selection_rank = min(
        _intish(row.get("selection_rank"), 50), FOLLOWUP_LAUNCH_SELECTION_RANK
    )
    dispatch_priority = min(
        _intish(row.get("dispatch_priority"), 50), FOLLOWUP_LAUNCH_DISPATCH_PRIORITY
    )
    return selection_rank, dispatch_priority


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
