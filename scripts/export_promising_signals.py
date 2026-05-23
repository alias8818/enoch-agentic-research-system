#!/usr/bin/env python3
"""Export bounded Enoch useful/promising signals to a companion repo.

This export is intentionally separate from the paper corpus. It preserves
bounded local evidence and scale-limited leads without turning them into papers.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

from enoch_control_plane.timeutils import parse_utc_datetime

SCHEMA_VERSION = "enoch_promising_signal_v1"
MANIFEST_SCHEMA_VERSION = "enoch_promising_signal_manifest_v1"
MANIFEST_JSON = "manifest.json"
RANKING_SCHEMA_VERSION = "enoch_promising_signal_ranking_v1"
DISCLAIMER = (
    "These are not validated papers, not peer-reviewed results, and not "
    "publication-positive Enoch corpus artifacts. This entry preserves bounded "
    "local evidence that may be useful for larger-compute follow-up."
)
EXPORT_STATUSES = {"useful_signal", "promising_if_scaled", "compute_scale_blocked"}
RANKING_BUCKETS: dict[str, str] = {
    "top_external_researcher_candidates": "Top external-researcher candidates",
    "compute_scale_blocked": "Compute-scale blocked",
    "followup_recommended": "Follow-up recommended",
    "weak_local_only_preserved": "Weak/local-only preserved signals",
    "likely_stale_low_value_archive": "Likely stale/low-value archive",
}
DEFAULT_SOURCE_LINEAGE_CUTOFF = "2026-05-19T17:51:00Z"

RANKING_BUCKET_ORDER = [
    "top_external_researcher_candidates",
    "compute_scale_blocked",
    "followup_recommended",
    "weak_local_only_preserved",
    "likely_stale_low_value_archive",
]
SOURCE_ROOT = "/var/lib/enoch-control-plane"
PRIVATE_PATH_ROOTS = (
    "/var/lib/enoch-control-plane",
    "/opt/enoch-control-plane",
    "/home/jeremy",
    "/root",
)

PROMISING_SIGNAL_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://github.com/alias8818/enoch-promising-signals/schemas/promising-signal.schema.json",
    "title": "Enoch Promising Signal",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "project_id",
        "run_id",
        "title",
        "status",
        "decision_summary",
        "hypothesis_status",
        "evidence_strength",
        "claim_scope",
        "scale_limits",
        "useful_signal_summary",
        "stop_reason",
        "recommended_next_action",
        "sources",
        "followup",
        "evidence",
        "curation",
        "do_not_overclaim",
    ],
    "properties": {
        "schema_version": {"const": SCHEMA_VERSION},
        "project_id": {"type": "string", "minLength": 1},
        "run_id": {"type": "string", "minLength": 1},
        "title": {"type": "string", "minLength": 1},
        "status": {"enum": sorted(EXPORT_STATUSES)},
        "decision_summary": {"type": "string", "minLength": 1},
        "hypothesis_status": {"type": "string", "minLength": 1},
        "evidence_strength": {"type": "string", "minLength": 1},
        "claim_scope": {"type": "string", "minLength": 1},
        "scale_limits": {"type": "string", "minLength": 1},
        "useful_signal_summary": {"type": "string", "minLength": 1},
        "stop_reason": {"type": "string", "minLength": 1},
        "recommended_next_action": {"type": "string", "minLength": 1},
        "sources": {"type": "array", "items": {"type": "object"}},
        "followup": {"type": "object"},
        "evidence": {"type": "object"},
        "curation": {"type": "object"},
        "do_not_overclaim": {"type": "object"},
        "updated_at": {"type": "string"},
    },
}


class ExportRows(list[dict[str, Any]]):
    selection_summary: dict[str, int]

    def __init__(
        self,
        rows: Iterable[dict[str, Any]],
        selection_summary: dict[str, int] | None = None,
    ) -> None:
        super().__init__(rows)
        self.selection_summary = selection_summary or {}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return _text(value).lower() in {"1", "true", "t", "yes", "y", "on"}


def _parse_time(value: Any) -> datetime | None:
    return parse_utc_datetime(value)


def slugify(value: str, fallback: str = "signal") -> str:
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip()).strip("-._").lower()
    return (slug or fallback)[:140]


def _safe_path_text(value: Any) -> str:
    text = _text(value)
    if not text:
        return ""
    redacted = text
    for root in PRIVATE_PATH_ROOTS:
        redacted = redacted.replace(root, "<local-path>")
    return redacted


def _public_safe_text(value: Any) -> str:
    text = _text(value)
    return re.sub(r"\bpublication[- ]ready\b", "paper-positive", text, flags=re.I)


def _list(value: Any) -> list[Any]:
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
        except (json.JSONDecodeError, ValueError, RecursionError):
            return [text]
        if isinstance(parsed, list):
            return parsed
        return [text]
    return [value]


def _export_status(row: dict[str, Any]) -> str:
    outcome = (
        _text(row.get("research_outcome")).lower().replace("-", "_").replace(" ", "_")
    )
    if outcome not in {"useful_signal", "promising_if_scaled"}:
        return ""
    if _truthy(row.get("compute_scale_blocked")):
        return "compute_scale_blocked"
    if outcome in {"useful_signal", "promising_if_scaled"}:
        return outcome
    return ""


def is_exportable_row(row: dict[str, Any]) -> bool:
    if _truthy(row.get("write_needed")) or _truthy(row.get("has_live_paper_row")):
        return False
    if _truthy(row.get("bounded_paper_ready")):
        return False
    if (
        _text(row.get("paper_id"))
        or _text(row.get("paper_status"))
        or _text(row.get("corpus_imported_at"))
    ):
        return False
    return _export_status(row) in EXPORT_STATUSES


def _source_dict(record: dict[str, Any]) -> dict[str, str]:
    return {
        "source_id": _text(record.get("source_id")),
        "url": _text(record.get("url")),
        "title": _text(record.get("title")),
    }


def _normalize_source_record(record: Any) -> dict[str, Any] | None:
    if isinstance(record, str):
        try:
            parsed = json.loads(record)
        except Exception:
            parsed = None
        record = parsed if isinstance(parsed, dict) else {"source_id": record}
    if not isinstance(record, dict):
        return None
    return record


def _append_unique_source(
    sources: list[dict[str, str]],
    seen: set[tuple[str, str, str]],
    source: dict[str, str],
) -> None:
    key = (source["source_id"], source["url"], source["title"])
    if any(source.values()) and key not in seen:
        sources.append(source)
        seen.add(key)


def _sources_from_source_records(records: list[Any]) -> list[dict[str, str]]:
    sources: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for record in records:
        normalized = _normalize_source_record(record)
        if normalized is None:
            continue
        _append_unique_source(sources, seen, _source_dict(normalized))
    sources.sort(key=lambda item: (item["source_id"], item["url"], item["title"]))
    return sources


def _parallel_source_value(values: list[str], index: int, *, fallback: str = "") -> str:
    if index < len(values):
        return values[index]
    return fallback if index == 0 else ""


def _sources_from_parallel_fields(row: dict[str, Any]) -> list[dict[str, str]]:
    ids = [_text(item) for item in _list(row.get("source_ids"))]
    urls = [_text(item) for item in _list(row.get("source_urls"))]
    titles = [_text(item) for item in _list(row.get("source_titles"))]
    count = max(
        len(ids), len(urls), len(titles), 1 if _text(row.get("source_url")) else 0
    )
    sources: list[dict[str, str]] = []
    for index in range(count):
        source = {
            "source_id": _parallel_source_value(ids, index),
            "url": _parallel_source_value(
                urls, index, fallback=_text(row.get("source_url"))
            ),
            "title": _parallel_source_value(
                titles, index, fallback=_text(row.get("source_paper"))
            ),
        }
        if any(source.values()):
            sources.append(source)
    return sources


def _sources_from_row(row: dict[str, Any]) -> list[dict[str, str]]:
    sources = _sources_from_source_records(_list(row.get("source_records")))
    if sources:
        return sources
    return _sources_from_parallel_fields(row)


def _strength_score(value: Any) -> tuple[int, str]:
    text = _text(value).lower().replace("-", "_").replace(" ", "_")
    if text in {"strong", "high"}:
        return 35, "strong evidence_strength"
    if text in {"moderate", "medium"}:
        return 25, "moderate evidence_strength"
    if text in {"weak", "low"}:
        return 10, "weak evidence_strength"
    return 0, "missing or unclear evidence_strength"


def _hypothesis_score(value: Any) -> tuple[int, str]:
    text = _text(value).lower().replace("-", "_").replace(" ", "_")
    if text in {"supported", "supportive", "confirmed"}:
        return 30, "supported hypothesis_status"
    if text in {"partially_supported", "partly_supported"}:
        return 20, "partially supported hypothesis_status"
    if text in {"mixed", "inconclusive_but_useful"}:
        return 15, "mixed hypothesis_status"
    if text in {"unsupported", "not_supported", "negative", "falsified"}:
        return -15, "unsupported hypothesis_status"
    return 0, "missing or unclear hypothesis_status"


def _has_external_source_url(sources: list[dict[str, Any]]) -> bool:
    for source in sources:
        url = _text(source.get("url")).lower()
        source_id = _text(source.get("source_id")).lower()
        if url.startswith(("arxiv:", "doi:")):
            return True
        if urlparse(url).scheme in {"http", "https"}:
            return True
        if source_id.startswith(("arxiv:", "doi:")):
            return True
    return False


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

    sources = signal.get("sources") if isinstance(signal.get("sources"), list) else []
    source_score = 0
    if sources:
        source_score += 8
        reasons.append("source lineage present")
    else:
        source_score -= 20
        reasons.append("source lineage missing")
    if _has_external_source_url(sources):
        source_score += 4
        reasons.append("external source URL present")
    score_breakdown["source_lineage"] = source_score

    followup = (
        signal.get("followup") if isinstance(signal.get("followup"), dict) else {}
    )
    followup_score = 0
    if _truthy(followup.get("recommended")):
        followup_score += 10
        reasons.append("bounded follow-up is specified")
    required_evidence = [
        _text(item) for item in _list(followup.get("required_evidence")) if _text(item)
    ]
    followup_score += min(5, len(required_evidence) * 2)
    depth = int(followup.get("depth") or 0)
    if depth > 2:
        followup_score -= min(15, (depth - 2) * 5)
        reasons.append("follow-up depth is already high")
    score_breakdown["followup"] = followup_score

    evidence = (
        signal.get("evidence") if isinstance(signal.get("evidence"), dict) else {}
    )
    artifact_paths = [
        _text(item) for item in _list(evidence.get("artifact_paths")) if _text(item)
    ]
    bounded_score = min(10, len(artifact_paths) * 2)
    if artifact_paths:
        reasons.append("local evidence artifact paths are present")
    joined_paths = " ".join(path.lower() for path in artifact_paths)
    if "metrics" in joined_paths:
        bounded_score += 4
        reasons.append("metrics artifact is present")
    if "project_decision" in joined_paths:
        bounded_score += 4
        reasons.append("project decision artifact is present")
    disclaimer = (
        signal.get("do_not_overclaim")
        if isinstance(signal.get("do_not_overclaim"), dict)
        else {}
    )
    if (
        disclaimer.get("not_a_paper") is True
        and _text(signal.get("claim_scope"))
        and _text(signal.get("scale_limits"))
    ):
        bounded_score += 4
    score_breakdown["bounded_evidence"] = bounded_score

    raw_score = sum(score_breakdown.values())
    score = max(0, min(100, raw_score))
    hypothesis_text = (
        _text(signal.get("hypothesis_status"))
        .lower()
        .replace("-", "_")
        .replace(" ", "_")
    )
    status = _text(signal.get("status"))
    if status == "compute_scale_blocked":
        bucket = "compute_scale_blocked"
    elif (
        hypothesis_text in {"unsupported", "not_supported", "negative", "falsified"}
        or score < 35
    ):
        bucket = "likely_stale_low_value_archive"
    elif score >= 85 and _text(signal.get("evidence_strength")).lower() in {
        "strong",
        "high",
        "moderate",
        "medium",
    }:
        bucket = "top_external_researcher_candidates"
    elif _truthy(followup.get("recommended")) and score >= 45:
        bucket = "followup_recommended"
    else:
        bucket = "weak_local_only_preserved"

    return {
        "schema_version": RANKING_SCHEMA_VERSION,
        "score": score,
        "bucket": bucket,
        "bucket_label": RANKING_BUCKETS[bucket],
        "score_breakdown": score_breakdown,
        "reasons": reasons,
    }


def signal_from_row(row: dict[str, Any]) -> dict[str, Any]:
    source_paths = [
        _safe_path_text(item)
        for item in _list(row.get("artifact_paths"))
        if _text(item)
    ]
    artifact_root = _safe_path_text(row.get("artifact_root"))
    signal = {
        "schema_version": SCHEMA_VERSION,
        "project_id": _text(row.get("project_id")),
        "run_id": _text(row.get("run_id") or row.get("current_run_id")),
        "title": _text(row.get("project_name") or row.get("title")),
        "status": _export_status(row),
        "decision_summary": _text(row.get("decision_summary")),
        "hypothesis_status": _text(row.get("hypothesis_status")),
        "evidence_strength": _text(row.get("evidence_strength")),
        "claim_scope": _public_safe_text(row.get("claim_scope")),
        "scale_limits": _public_safe_text(row.get("scale_limits")),
        "useful_signal_summary": _public_safe_text(row.get("useful_signal_summary")),
        "stop_reason": _public_safe_text(row.get("stop_reason")),
        "recommended_next_action": _public_safe_text(
            row.get("recommended_next_action")
        ),
        "sources": _sources_from_row(row),
        "followup": {
            "recommended": _truthy(row.get("followup_recommended")),
            "type": _text(row.get("followup_type")),
            "title": _text(row.get("followup_title")),
            "hypothesis": _text(row.get("followup_hypothesis")),
            "required_evidence": [
                _text(item)
                for item in _list(row.get("followup_required_evidence"))
                if _text(item)
            ],
            "success_threshold": _text(row.get("followup_success_threshold")),
            "stop_condition": _text(row.get("followup_stop_condition")),
            "depth": int(row.get("followup_depth") or 0),
        },
        "evidence": {
            "artifact_root": artifact_root,
            "artifact_paths": source_paths,
            "local_only": True,
            "public_evidence_copied": False,
        },
        "do_not_overclaim": {
            "not_a_paper": True,
            "not_peer_reviewed": True,
            "not_publication_validated": True,
            "not_in_main_corpus": True,
            "disclaimer": DISCLAIMER,
        },
        "updated_at": _text(row.get("updated_at"))
        or datetime.now(timezone.utc).isoformat(),
    }
    signal["curation"] = rank_signal(signal)
    return signal


def validate_signal(signal: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    for field in PROMISING_SIGNAL_SCHEMA["required"]:
        value = signal.get(field)
        if value in (None, "", [], {}):
            issues.append(f"{field}:required")
    if signal.get("schema_version") != SCHEMA_VERSION:
        issues.append("schema_version:invalid")
    if signal.get("status") not in EXPORT_STATUSES:
        issues.append("status:invalid")
    disclaimer = (
        signal.get("do_not_overclaim")
        if isinstance(signal.get("do_not_overclaim"), dict)
        else {}
    )
    for key in ("not_a_paper", "not_publication_validated", "not_in_main_corpus"):
        if disclaimer.get(key) is not True:
            issues.append(f"do_not_overclaim.{key}:required_true")
    if "not validated papers" not in str(disclaimer.get("disclaimer") or ""):
        issues.append("do_not_overclaim.disclaimer:missing_not_validated_papers")
    evidence = (
        signal.get("evidence") if isinstance(signal.get("evidence"), dict) else {}
    )
    if evidence.get("public_evidence_copied") is not False:
        issues.append("evidence.public_evidence_copied:must_be_false")
    curation = (
        signal.get("curation") if isinstance(signal.get("curation"), dict) else {}
    )
    expected_curation = rank_signal(signal)
    if curation.get("schema_version") != RANKING_SCHEMA_VERSION:
        issues.append("curation.schema_version:invalid")
    if curation.get("bucket") not in RANKING_BUCKETS:
        issues.append("curation.bucket:invalid")
    for key in ("score", "bucket", "bucket_label", "score_breakdown", "reasons"):
        if curation.get(key) != expected_curation.get(key):
            issues.append(f"curation.{key}:drift")
    serialized = json.dumps(signal, sort_keys=True)
    for private_root in PRIVATE_PATH_ROOTS:
        if private_root in serialized:
            issues.append(f"private_path_not_redacted:{private_root}")
    return sorted(set(issues))


def export_signals(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    latest_by_project: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not is_exportable_row(row):
            continue
        signal = signal_from_row(row)
        project_id = signal["project_id"]
        previous = latest_by_project.get(project_id)
        if previous is None or (
            signal.get("updated_at") or "",
            signal.get("run_id") or "",
        ) > (previous.get("updated_at") or "", previous.get("run_id") or ""):
            latest_by_project[project_id] = signal
    signals = list(latest_by_project.values())
    signals.sort(key=lambda item: (item["project_id"], item["run_id"]))
    return signals


def ranked_signals(signals: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    materialized = list(signals)
    return sorted(
        materialized,
        key=lambda signal: (
            -int((signal.get("curation") or {}).get("score") or 0),
            _text(signal.get("title")).lower(),
            _text(signal.get("project_id")),
        ),
    )


def export_ranking(signals: Iterable[dict[str, Any]]) -> dict[str, Any]:
    ranked = ranked_signals(signals)
    bucket_counts = Counter(
        str((signal.get("curation") or {}).get("bucket") or "") for signal in ranked
    )
    return {
        "schema_version": RANKING_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "bucket_labels": RANKING_BUCKETS,
        "bucket_counts": {
            bucket: bucket_counts[bucket]
            for bucket in RANKING_BUCKET_ORDER
            if bucket_counts.get(bucket, 0)
        },
        "items": [
            {
                "project_id": signal["project_id"],
                "run_id": signal["run_id"],
                "title": signal["title"],
                "status": signal["status"],
                "score": int((signal.get("curation") or {}).get("score") or 0),
                "bucket": _text((signal.get("curation") or {}).get("bucket")),
                "bucket_label": _text(
                    (signal.get("curation") or {}).get("bucket_label")
                ),
                "reasons": list((signal.get("curation") or {}).get("reasons") or []),
            }
            for signal in ranked
        ],
    }


def export_manifest(
    signals: list[dict[str, Any]], *, selection_summary: dict[str, int] | None = None
) -> dict[str, Any]:
    status_counts = Counter(str(signal.get("status") or "") for signal in signals)
    ranking_counts = Counter(
        str((signal.get("curation") or {}).get("bucket") or "") for signal in signals
    )
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "record_count": len(signals),
        "status_counts": {
            status: status_counts[status] for status in sorted(status_counts)
        },
        "ranking_summary": {
            bucket: ranking_counts[bucket]
            for bucket in RANKING_BUCKET_ORDER
            if ranking_counts.get(bucket, 0)
        },
        "project_ids": [signal["project_id"] for signal in signals],
        "data_file": "data/signals.jsonl",
        "ranking_file": "data/ranking.json",
        "index_file": "signals/index.md",
        "ranked_index_file": "signals/ranked-index.md",
        "schema_file": "schemas/promising-signal.schema.json",
        "public_evidence_copied": False,
        "export_statuses": sorted(EXPORT_STATUSES),
        "ranking_buckets": RANKING_BUCKETS,
        "selection_summary": selection_summary
        or {
            "total_candidate_rows": len(signals),
            "export_cleanly_now": len(signals),
            "backfilled_exportable": 0,
            "missing_required_evidence_or_fields": 0,
            "excluded_paper_or_corpus": 0,
            "hard_negative_or_stale": 0,
        },
    }


def _records_from_repo(repo_root: Path) -> list[dict[str, Any]]:
    data_path = repo_root / "data" / "signals.jsonl"
    if not data_path.exists():
        return []
    return [
        json.loads(line)
        for line in data_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def validate_export_repo(repo_root: Path) -> list[str]:
    issues: list[str] = []
    records = _records_from_repo(repo_root)
    manifest_path = repo_root / "data" / MANIFEST_JSON
    if not manifest_path.exists():
        return ["manifest:missing"]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return ["manifest:invalid_json"]
    expected = export_manifest(
        records,
        selection_summary=manifest.get("selection_summary")
        if isinstance(manifest.get("selection_summary"), dict)
        else None,
    )
    for record in records:
        project_id = _text(record.get("project_id")) or "unknown_project"
        for issue in validate_signal(record):
            issues.append(f"signal.{project_id}.{issue}")
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        issues.append("manifest.schema_version:invalid")
    if manifest.get("record_count") != expected["record_count"]:
        issues.append(
            f"manifest.record_count:{manifest.get('record_count')} != {expected['record_count']}"
        )
    actual_status_counts = (
        manifest.get("status_counts")
        if isinstance(manifest.get("status_counts"), dict)
        else {}
    )
    for status in sorted(set(actual_status_counts) | set(expected["status_counts"])):
        if actual_status_counts.get(status) != expected["status_counts"].get(status, 0):
            issues.append(
                f"manifest.status_counts.{status}:{actual_status_counts.get(status)} != {expected['status_counts'].get(status, 0)}"
            )
    if manifest.get("project_ids") != expected["project_ids"]:
        issues.append("manifest.project_ids:drift")
    if manifest.get("ranking_summary") != expected["ranking_summary"]:
        issues.append("manifest.ranking_summary:drift")
    if manifest.get("public_evidence_copied") is not False:
        issues.append("manifest.public_evidence_copied:must_be_false")
    ranking_path = repo_root / "data" / "ranking.json"
    if not ranking_path.exists():
        issues.append("ranking:missing")
    else:
        ranking = json.loads(ranking_path.read_text(encoding="utf-8"))
        expected_ranking = export_ranking(records)
        if ranking.get("schema_version") != RANKING_SCHEMA_VERSION:
            issues.append("ranking.schema_version:invalid")
        if ranking.get("bucket_counts") != expected_ranking["bucket_counts"]:
            issues.append("ranking.bucket_counts:drift")
        actual_items = [
            {
                "project_id": item.get("project_id"),
                "score": item.get("score"),
                "bucket": item.get("bucket"),
                "reasons": item.get("reasons"),
            }
            for item in ranking.get("items", [])
            if isinstance(item, dict)
        ]
        expected_items = [
            {
                "project_id": item.get("project_id"),
                "score": item.get("score"),
                "bucket": item.get("bucket"),
                "reasons": item.get("reasons"),
            }
            for item in expected_ranking["items"]
        ]
        if actual_items != expected_items:
            issues.append("ranking.items:drift")
    return sorted(issues)


def validate_repo_against_rows(
    rows: Iterable[dict[str, Any]], repo_root: Path
) -> list[str]:
    materialized = list(rows)
    issues = validate_export_repo(repo_root)
    report = audit_backfill(materialized)
    expected_summary = report["summary"]
    manifest_path = repo_root / "data" / MANIFEST_JSON
    if not manifest_path.exists():
        return sorted(set(issues + ["manifest:missing"]))
    if "manifest:invalid_json" in issues:
        return sorted(set(issues))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    actual_summary = (
        manifest.get("selection_summary")
        if isinstance(manifest.get("selection_summary"), dict)
        else {}
    )
    for key, expected in expected_summary.items():
        actual = actual_summary.get(key)
        if actual != expected:
            issues.append(f"selection_summary.{key}:{actual} != {expected}")
    if manifest.get("record_count") != expected_summary["export_cleanly_now"]:
        issues.append(
            f"manifest.record_count:{manifest.get('record_count')} != export_cleanly_now:{expected_summary['export_cleanly_now']}"
        )
    policy = validate_source_backfill_policy(
        materialized,
        created_after=os.environ.get(
            "ENOCH_PROMISING_SIGNALS_SOURCE_CUTOFF", DEFAULT_SOURCE_LINEAGE_CUTOFF
        ),
    )
    if not policy.get("ok", True):
        for problem in policy.get("problems") or []:
            issues.append(
                "source_backfill_policy."
                f"{problem.get('kind')}:{problem.get('project_id')}:{problem.get('run_id')}"
            )
    return sorted(set(issues))


def validate_source_backfill_policy(
    rows: Iterable[dict[str, Any]],
    *,
    created_after: str = DEFAULT_SOURCE_LINEAGE_CUTOFF,
) -> dict[str, Any]:
    cutoff = _parse_time(created_after)
    summary = {
        "legacy_backfilled_source_ok": 0,
        "new_missing_source_lineage_blocked": 0,
    }
    problems: list[dict[str, Any]] = []
    for row in rows:
        if not is_exportable_row(row):
            continue
        if _sources_from_row(row):
            continue
        backfilled = backfill_promising_signal_row(row)
        meta = (
            backfilled.get("_promising_signal_backfill")
            if isinstance(backfilled.get("_promising_signal_backfill"), dict)
            else {}
        )
        actions = set(_list(meta.get("actions")))
        if "source_records:queue_project_metadata" not in actions:
            continue
        updated_at = _parse_time(row.get("updated_at"))
        if cutoff and updated_at and updated_at >= cutoff:
            summary["new_missing_source_lineage_blocked"] += 1
            problems.append(
                {
                    "kind": "new_missing_source_lineage_blocked",
                    "project_id": _text(row.get("project_id")),
                    "run_id": _text(row.get("run_id") or row.get("current_run_id")),
                    "updated_at": _text(row.get("updated_at")),
                    "backfill_actions": sorted(actions),
                }
            )
        else:
            summary["legacy_backfilled_source_ok"] += 1
    return {
        "schema_version": "enoch_promising_signal_source_backfill_policy_v1",
        "ok": not problems,
        "created_after": created_after,
        "summary": summary,
        "problems": problems,
    }


def _markdown(signal: dict[str, Any]) -> str:
    sources = signal.get("sources") or []
    source_lines = [
        f"- {src.get('title') or src.get('source_id') or 'source'}: {src.get('url') or src.get('source_id') or ''}"
        for src in sources
    ]
    followup = signal.get("followup") or {}
    evidence = signal.get("evidence") or {}
    curation = (
        signal.get("curation")
        if isinstance(signal.get("curation"), dict)
        else rank_signal(signal)
    )
    breakdown = (
        curation.get("score_breakdown")
        if isinstance(curation.get("score_breakdown"), dict)
        else {}
    )
    return "\n".join(
        [
            f"# {signal['title']}",
            "",
            f"Status: `{signal['status']}`",
            f"Curation bucket: `{curation.get('bucket')}`",
            f"Curation score: `{curation.get('score')}`",
            f"Project ID: `{signal['project_id']}`",
            f"Run ID: `{signal['run_id']}`",
            "",
            "> This is a promising-signal record, not a paper. It is bounded local evidence preserved for possible larger-compute follow-up.",
            "",
            "## Deterministic curation",
            "",
            f"- Bucket: {curation.get('bucket_label') or curation.get('bucket')}",
            f"- Score: `{curation.get('score')}`",
            f"- Score breakdown: `{json.dumps(breakdown, sort_keys=True)}`",
            "",
            "Reasons:",
            *(f"- {reason}" for reason in curation.get("reasons") or []),
            "",
            "## Source",
            "",
            *(source_lines or ["- No source URL recorded."]),
            "",
            "## What looked useful",
            "",
            signal["useful_signal_summary"],
            "",
            "## Boundaries and scale limits",
            "",
            signal["scale_limits"],
            "",
            "## Claim scope",
            "",
            signal["claim_scope"],
            "",
            "## Why it stopped",
            "",
            signal["stop_reason"],
            "",
            "## Recommended next action",
            "",
            signal["recommended_next_action"],
            "",
            "## Follow-up",
            "",
            f"- Recommended: `{str(bool(followup.get('recommended'))).lower()}`",
            f"- Type: `{followup.get('type') or ''}`",
            f"- Title: {followup.get('title') or ''}",
            f"- Success threshold: {followup.get('success_threshold') or ''}",
            f"- Stop condition: {followup.get('stop_condition') or ''}",
            "",
            "## Evidence references",
            "",
            f"- Artifact root: `{evidence.get('artifact_root') or ''}`",
            *[f"- `{path}`" for path in evidence.get("artifact_paths") or []],
            "",
            "## Do not overclaim",
            "",
            signal["do_not_overclaim"]["disclaimer"],
            "",
        ]
    )


def _paper_or_corpus_excluded(row: dict[str, Any]) -> bool:
    return (
        _truthy(row.get("write_needed"))
        or _truthy(row.get("has_live_paper_row"))
        or bool(_text(row.get("paper_id")))
        or bool(_text(row.get("paper_status")))
        or bool(_text(row.get("corpus_imported_at")))
    )


def _extract_project_decision(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except Exception:
            return {}
    if not isinstance(value, dict):
        return {}
    nested = value.get("project_decision")
    if isinstance(nested, dict):
        return nested
    return value


def _source_records_from_candidate_metadata(
    row: dict[str, Any],
) -> list[dict[str, str]]:
    records = _sources_from_row(
        {
            "source_records": row.get("candidate_source_records"),
            "source_ids": row.get("candidate_source_ids")
            or row.get("research_candidate_source_ids"),
            "source_urls": row.get("candidate_source_urls")
            or row.get("research_candidate_source_urls"),
            "source_titles": row.get("candidate_source_titles")
            or row.get("research_candidate_source_titles"),
            "source_url": row.get("candidate_source_url")
            or row.get("research_candidate_source_url"),
            "source_paper": row.get("candidate_source_title")
            or row.get("research_candidate_source_title"),
        }
    )
    return records


def _dedupe_source_records(records: Iterable[dict[str, Any]]) -> list[dict[str, str]]:
    deduped: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for record in records:
        if not isinstance(record, dict):
            continue
        source = {
            "source_id": _text(record.get("source_id")),
            "url": _text(record.get("url")),
            "title": _text(record.get("title")),
        }
        key = (source["source_id"], source["url"], source["title"])
        if any(source.values()) and key not in seen:
            deduped.append(source)
            seen.add(key)
    deduped.sort(key=lambda item: (item["source_id"], item["url"], item["title"]))
    return deduped


def backfill_promising_signal_row(row: dict[str, Any]) -> dict[str, Any]:
    """Return a deterministically enriched copy of a promising-signal row.

    This function only copies facts from structured row/artifact fields or
    creates an explicit internal-generated source from project metadata. It
    never invents external URLs, titles, measurements, or claims.
    """

    repaired = dict(row)
    classification: list[str] = []
    actions: list[str] = []

    decision = _extract_project_decision(
        row.get("decision_payload")
        or row.get("payload_json")
        or row.get("project_decision")
    )
    decision_field_map = {
        "research_outcome": "research_outcome",
        "hypothesis_status": "hypothesis_status",
        "evidence_strength": "evidence_strength",
        "claim_scope": "claim_scope",
        "scale_limits": "scale_limits",
        "useful_signal_summary": "useful_signal_summary",
        "recommended_next_action": "recommended_next_action",
        "stop_reason": "stop_reason",
        "bounded_paper_ready": "bounded_paper_ready",
        "compute_scale_blocked": "compute_scale_blocked",
    }
    for row_field, decision_field in decision_field_map.items():
        if repaired.get(row_field) in (None, "", [], {}):
            value = decision.get(decision_field)
            if value not in (None, "", [], {}):
                repaired[row_field] = value
                if "missing_decision_field" not in classification:
                    classification.append("missing_decision_field")
                actions.append(f"{row_field}:project_decision")

    if not _sources_from_row(repaired):
        candidate_sources = _source_records_from_candidate_metadata(row)
        if candidate_sources:
            repaired["source_records"] = candidate_sources
            classification.append("missing_research_source_lineage")
            actions.append("source_records:research_candidate_metadata")
        else:
            project_id = _text(row.get("project_id"))
            title = _text(row.get("project_name") or row.get("title"))
            if project_id and title:
                repaired["source_records"] = [
                    {
                        "source_id": f"internal_generated:{project_id}",
                        "url": "",
                        "title": f"Internal Enoch project: {title}",
                    }
                ]
                classification.append("missing_research_source_lineage")
                actions.append("source_records:queue_project_metadata")
            else:
                classification.append("unrecoverable_project_identity")

    signal = signal_from_row(repaired)
    issues = validate_signal(signal)
    if (
        "sources:required" in issues
        and "missing_research_source_lineage" not in classification
    ):
        classification.append("missing_research_source_lineage")
    if any(issue.startswith("sources") for issue in issues) and _sources_from_row(
        repaired
    ):
        classification.append("missing_source_url_or_title")
    if not _text(row.get("artifact_root")) and not _list(row.get("artifact_paths")):
        classification.append("missing_evidence_claim_boundary")

    repaired["_promising_signal_backfill"] = {
        "classification": sorted(set(classification)),
        "actions": sorted(set(actions)),
        "remaining_issues": issues,
    }
    return repaired


def _latest_project_keys(rows: Iterable[dict[str, Any]]) -> set[tuple[str, str]]:
    latest: dict[str, tuple[str, str]] = {}
    for row in rows:
        project_id = _text(row.get("project_id"))
        if not project_id:
            continue
        row_key = (
            _text(row.get("updated_at")),
            _text(row.get("run_id") or row.get("current_run_id")),
        )
        if project_id not in latest or row_key > latest[project_id]:
            latest[project_id] = row_key
    return {(project_id, run_id) for project_id, (_updated, run_id) in latest.items()}


def _audit_row_summary(
    row: dict[str, Any],
    issues: list[str],
    *,
    backfill: dict[str, Any] | None = None,
    include_identifiers: bool = True,
) -> dict[str, Any]:
    summary = {
        "issues": sorted(set(issues)),
    }
    if include_identifiers:
        summary.update(
            {
                "project_id": _text(row.get("project_id")),
                "run_id": _text(row.get("run_id") or row.get("current_run_id")),
                "title": _text(row.get("project_name") or row.get("title")),
                "research_outcome": _text(row.get("research_outcome")),
                "compute_scale_blocked": _truthy(row.get("compute_scale_blocked")),
            }
        )
    if backfill is not None:
        summary["backfill"] = {
            "classification": sorted(set(_list(backfill.get("classification")))),
            "actions": sorted(set(_list(backfill.get("actions")))),
            "remaining_issues": sorted(set(_list(backfill.get("remaining_issues")))),
        }
    return summary


def audit_backfill(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    materialized = list(rows)
    latest_keys = _latest_project_keys(materialized)
    buckets: dict[str, list[dict[str, Any]]] = {
        "export_cleanly_now": [],
        "missing_required_evidence_or_fields": [],
        "excluded_paper_or_corpus": [],
        "hard_negative_or_stale": [],
    }
    backfilled_exportable = 0
    total = 0
    for row in materialized:
        total += 1
        project_id = _text(row.get("project_id"))
        run_id = _text(row.get("run_id") or row.get("current_run_id"))
        if project_id and (project_id, run_id) not in latest_keys:
            buckets["hard_negative_or_stale"].append(
                _audit_row_summary(
                    row,
                    ["stale_duplicate_superseded"],
                    backfill={
                        "classification": ["stale_duplicate_superseded"],
                        "actions": [],
                        "remaining_issues": [],
                    },
                    include_identifiers=False,
                )
            )
            continue
        if _paper_or_corpus_excluded(row):
            buckets["excluded_paper_or_corpus"].append(
                _audit_row_summary(
                    row,
                    ["paper_or_corpus_row"],
                    backfill={
                        "classification": [],
                        "actions": [],
                        "remaining_issues": [],
                    },
                    include_identifiers=False,
                )
            )
            continue
        backfilled = backfill_promising_signal_row(row)
        backfill_meta = (
            backfilled.get("_promising_signal_backfill")
            if isinstance(backfilled.get("_promising_signal_backfill"), dict)
            else {}
        )
        status = _export_status(backfilled)
        if status not in EXPORT_STATUSES:
            buckets["hard_negative_or_stale"].append(
                _audit_row_summary(
                    backfilled,
                    ["research_outcome:not_export_status"],
                    backfill=backfill_meta,
                    include_identifiers=False,
                )
            )
            continue
        signal = signal_from_row(backfilled)
        issues = validate_signal(signal)
        if issues:
            buckets["missing_required_evidence_or_fields"].append(
                _audit_row_summary(backfilled, issues, backfill=backfill_meta)
            )
            continue
        if backfill_meta.get("actions"):
            backfilled_exportable += 1
        buckets["export_cleanly_now"].append(
            _audit_row_summary(backfilled, [], backfill=backfill_meta)
        )
    for key in buckets:
        buckets[key].sort(
            key=lambda item: (item.get("project_id") or "", item.get("run_id") or "")
        )
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total_candidate_rows": total,
            "export_cleanly_now": len(buckets["export_cleanly_now"]),
            "backfilled_exportable": backfilled_exportable,
            "missing_required_evidence_or_fields": len(
                buckets["missing_required_evidence_or_fields"]
            ),
            "excluded_paper_or_corpus": len(buckets["excluded_paper_or_corpus"]),
            "hard_negative_or_stale": len(buckets["hard_negative_or_stale"]),
        },
        "buckets": buckets,
    }


def clean_export_rows(rows: Iterable[dict[str, Any]]) -> ExportRows:
    materialized = list(rows)
    report = audit_backfill(materialized)
    clean_keys = {
        (row["project_id"], row["run_id"])
        for row in report["buckets"]["export_cleanly_now"]
    }
    clean_rows = [
        backfill_promising_signal_row(row)
        for row in materialized
        if (
            _text(row.get("project_id")),
            _text(row.get("run_id") or row.get("current_run_id")),
        )
        in clean_keys
    ]
    return ExportRows(clean_rows, selection_summary=report["summary"])


def audit_backfill_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary") or {}
    buckets = report.get("buckets") or {}
    labels = [
        ("Export cleanly now", "export_cleanly_now"),
        ("Backfilled exportable", "backfilled_exportable"),
        ("Missing required evidence/fields", "missing_required_evidence_or_fields"),
        ("Excluded because paper/corpus", "excluded_paper_or_corpus"),
        ("Hard negative or stale", "hard_negative_or_stale"),
    ]
    lines = [
        "# Promising signals backfill audit",
        "",
        f"Generated: `{report.get('generated_at') or ''}`",
        "",
        "This is a dry-run classification report. It does not export rows or change the companion repo.",
        "",
        "## Summary",
        "",
        "| Bucket | Count |",
        "|---|---:|",
        f"| Total candidate rows | {summary.get('total_candidate_rows', 0)} |",
    ]
    for label, key in labels:
        lines.append(f"| {label} | {summary.get(key, 0)} |")
    lines.extend(
        [
            "",
            "## Backfill plan",
            "",
            "1. Export rows in `export_cleanly_now` first; they already satisfy the deterministic public record contract.",
            "2. Backfill rows in `missing_required_evidence_or_fields` only after source/evidence fields are recovered from control-plane or worker artifacts.",
            "3. Leave `excluded_paper_or_corpus` out of the promising-signals repo; those belong to the paper/corpus lane.",
            "4. Leave `hard_negative_or_stale` out unless a new deterministic decision record changes their status.",
            "",
        ]
    )
    for label, key in labels:
        rows = buckets.get(key) or []
        if key == "backfilled_exportable":
            rows = [
                row
                for row in buckets.get("export_cleanly_now") or []
                if (row.get("backfill") or {}).get("actions")
            ]
        else:
            rows = buckets.get(key) or []
        lines.extend(
            [
                f"## {label}",
                "",
                "| Project | Outcome | Issues | Backfill |",
                "|---|---|---|---|",
            ]
        )
        if not rows:
            lines.append("| _none_ |  |  |  |")
        for row in rows:
            project = row.get("project_id") or row.get("title") or "unknown"
            outcome = row.get("research_outcome") or (
                "compute_scale_blocked" if row.get("compute_scale_blocked") else ""
            )
            issues = ", ".join(row.get("issues") or [])
            backfill = (
                row.get("backfill") if isinstance(row.get("backfill"), dict) else {}
            )
            backfill_text = "; ".join(
                part
                for part in [
                    ", ".join(backfill.get("classification") or []),
                    ", ".join(backfill.get("actions") or []),
                ]
                if part
            )
            lines.append(f"| `{project}` | `{outcome}` | {issues} | {backfill_text} |")
        lines.append("")
    return "\n".join(lines)


def write_schema(repo_root: Path) -> None:
    schema_dir = repo_root / "schemas"
    schema_dir.mkdir(parents=True, exist_ok=True)
    (schema_dir / "promising-signal.schema.json").write_text(
        json.dumps(PROMISING_SIGNAL_SCHEMA, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _bucket_file_slug(bucket: str) -> str:
    return bucket.replace("_", "-")


def _ranked_table_rows(
    signals: Iterable[dict[str, Any]], *, limit: int | None = None
) -> list[str]:
    lines: list[str] = []
    for signal in ranked_signals(signals)[:limit]:
        curation = signal.get("curation") or {}
        slug = slugify(signal["project_id"])
        reasons = "; ".join(
            str(reason) for reason in (curation.get("reasons") or [])[:3]
        )
        lines.append(
            f"| [{signal['title']}]({slug}.md) | `{curation.get('score')}` | "
            f"{curation.get('bucket_label') or curation.get('bucket')} | `{signal['status']}` | "
            f"{signal['evidence_strength']} | {reasons} |"
        )
    return lines


def _write_ranking_indexes(repo_root: Path, signals: list[dict[str, Any]]) -> None:
    ranking = export_ranking(signals)
    buckets_dir = repo_root / "signals" / "buckets"
    buckets_dir.mkdir(parents=True, exist_ok=True)
    live_bucket_files = {
        f"{_bucket_file_slug(bucket)}.md" for bucket in RANKING_BUCKETS
    }
    for path in buckets_dir.glob("*.md"):
        if path.name not in live_bucket_files:
            path.unlink()

    ranked_lines = [
        "# Ranked promising signal index",
        "",
        "Ranking is deterministic. It is computed only from exported signal fields: evidence strength, hypothesis status, source lineage, bounded follow-up metadata, follow-up depth, compute-scale status, and local evidence artifact references.",
        "",
        "| Title | Score | Bucket | Status | Evidence | Reasons |",
        "|---|---:|---|---|---|---|",
        *_ranked_table_rows(signals),
        "",
        "## Bucket indexes",
        "",
    ]
    for bucket in RANKING_BUCKET_ORDER:
        count = ranking["bucket_counts"].get(bucket, 0)
        ranked_lines.append(
            f"- [{RANKING_BUCKETS[bucket]}](buckets/{_bucket_file_slug(bucket)}.md): `{count}`"
        )
    (repo_root / "signals" / "ranked-index.md").write_text(
        "\n".join(ranked_lines) + "\n", encoding="utf-8"
    )

    by_bucket: dict[str, list[dict[str, Any]]] = {
        bucket: [] for bucket in RANKING_BUCKETS
    }
    for signal in signals:
        by_bucket.setdefault(
            _text((signal.get("curation") or {}).get("bucket")), []
        ).append(signal)
    for bucket in RANKING_BUCKET_ORDER:
        bucket_signals = by_bucket.get(bucket, [])
        lines = [
            f"# {RANKING_BUCKETS[bucket]}",
            "",
            "This bucket is generated from deterministic exported fields, not from manual or LLM review.",
            "",
            f"Count: `{len(bucket_signals)}`",
            "",
            "| Title | Score | Status | Evidence | Reasons |",
            "|---|---:|---|---|---|",
        ]
        for signal in ranked_signals(bucket_signals):
            curation = signal.get("curation") or {}
            slug = slugify(signal["project_id"])
            reasons = "; ".join(
                str(reason) for reason in (curation.get("reasons") or [])[:3]
            )
            lines.append(
                f"| [{signal['title']}](../{slug}.md) | `{curation.get('score')}` | `{signal['status']}` | {signal['evidence_strength']} | {reasons} |"
            )
        (buckets_dir / f"{_bucket_file_slug(bucket)}.md").write_text(
            "\n".join(lines) + "\n", encoding="utf-8"
        )


def _write_readme(
    repo_root: Path, signals: list[dict[str, Any]], manifest: dict[str, Any]
) -> None:
    ranking_summary = (
        manifest.get("ranking_summary")
        if isinstance(manifest.get("ranking_summary"), dict)
        else {}
    )
    status_counts = (
        manifest.get("status_counts")
        if isinstance(manifest.get("status_counts"), dict)
        else {}
    )
    lines = [
        "# Enoch Promising Signals",
        "",
        "Public companion repository for bounded Enoch research results that looked useful but did **not** qualify for the public paper corpus.",
        "",
        "These records are **not validated papers**, **not peer reviewed**, **not publication-positive Enoch corpus artifacts**, and **not the paper corpus**. They preserve local/toy/small-scale evidence, stop reasons, and next-test ideas so promising leads do not rot when the next useful test exceeds local compute or wall-clock limits.",
        "",
        "## Current export",
        "",
        f"The current export contains {len(signals)} deterministic, contract-clean signals from the Enoch control plane.",
        "",
        "Status counts:",
        *(
            f"- `{status}`: {status_counts.get(status, 0)}"
            for status in sorted(status_counts)
        ),
        "",
        "Deterministic curation buckets:",
        *(
            f"- [{RANKING_BUCKETS[bucket]}](signals/buckets/{_bucket_file_slug(bucket)}.md): {ranking_summary.get(bucket, 0)}"
            for bucket in RANKING_BUCKET_ORDER
        ),
        "",
        "Start with the generated [ranked index](signals/ranked-index.md). The generated title index is in [signals/index.md](signals/index.md). Machine-readable source of truth is [data/signals.jsonl](data/signals.jsonl), ranking metadata is in [data/ranking.json](data/ranking.json), and count/status accounting is in [data/manifest.json](data/manifest.json).",
        "",
        "## What belongs here",
        "",
        "A record belongs here only when deterministic control-plane fields mark it as one of:",
        "",
        "- `useful_signal`",
        "- `promising_if_scaled`",
        "- `compute_scale_blocked`",
        "",
        "A record does **not** belong here when it is paper-positive, already imported into the public corpus, missing required claim/evidence boundaries, or only supported by an LLM interpretation without a deterministic control-plane field.",
        "",
        "## Ranking rule",
        "",
        "Ranking is deterministic. Bucket labels and scores are derived only from exported fields: evidence strength, hypothesis status, source lineage, compute-scale status, follow-up metadata/depth, and local evidence artifact references. No LLM review or manual judgment is allowed to become ranking truth unless a validator can recompute it.",
        "",
        "## Public-release rule",
        "",
        "This repository is public, but every entry remains a preservation record rather than an endorsement. Promoting a signal into the paper corpus requires a separate future run that independently becomes paper-positive and passes the normal paper/corpus release gates.",
        "",
        "## Regeneration",
        "",
        "The exporter lives in the system repo:",
        "",
        "```bash",
        "python3 scripts/export_promising_signals.py --output-repo ../enoch-promising-signals --clean-only",
        "```",
        "",
        "Validate the generated repository with:",
        "",
        "```bash",
        "python3 scripts/validate.py",
        "python3 scripts/validate_public_trust_surfaces.py",
        "```",
        "",
    ]
    (repo_root / "README.md").write_text("\n".join(lines), encoding="utf-8")


def write_export(rows: Iterable[dict[str, Any]], repo_root: Path) -> dict[str, Any]:
    selection_summary = getattr(rows, "selection_summary", None)
    signals = export_signals(rows)
    failures = []
    for signal in signals:
        issues = validate_signal(signal)
        if issues:
            failures.append({"project_id": signal.get("project_id"), "issues": issues})
    if failures:
        raise SystemExit(
            json.dumps(
                {"error": "schema_validation_failed", "failures": failures}, indent=2
            )
        )
    (repo_root / "data").mkdir(parents=True, exist_ok=True)
    (repo_root / "signals").mkdir(parents=True, exist_ok=True)
    write_schema(repo_root)
    live_signal_files = {f"{slugify(signal['project_id'])}.md" for signal in signals}
    for path in (repo_root / "signals").glob("*.md"):
        if path.name != "index.md" and path.name not in live_signal_files:
            path.unlink()
    ranking = export_ranking(signals)
    manifest = export_manifest(signals, selection_summary=selection_summary)
    (repo_root / "data" / "signals.jsonl").write_text(
        "".join(json.dumps(signal, sort_keys=True) + "\n" for signal in signals),
        encoding="utf-8",
    )
    (repo_root / "data" / "ranking.json").write_text(
        json.dumps(ranking, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (repo_root / "data" / MANIFEST_JSON).write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    index_lines = [
        "# Promising signal index",
        "",
        "These records are bounded local signals, not papers and not publication-positive claims.",
        "",
        "For triage, start with the [ranked index](ranked-index.md).",
        "",
        "| Title | Status | Evidence strength | Follow-up |",
        "|---|---|---|---|",
    ]
    for signal in signals:
        slug = slugify(signal["project_id"])
        path = repo_root / "signals" / f"{slug}.md"
        path.write_text(_markdown(signal), encoding="utf-8")
        followup = signal.get("followup") or {}
        index_lines.append(
            f"| [{signal['title']}]({slug}.md) | `{signal['status']}` | {signal['evidence_strength']} | {followup.get('title') or ''} |"
        )
    (repo_root / "signals" / "index.md").write_text(
        "\n".join(index_lines) + "\n", encoding="utf-8"
    )
    _write_ranking_indexes(repo_root, signals)
    _write_readme(repo_root, signals, manifest)
    return {
        "count": len(signals),
        "signals": [signal["project_id"] for signal in signals],
    }


def _fetch_postgres_rows(project_ids: list[str], query: str) -> list[dict[str, Any]]:
    try:
        import psycopg
        from psycopg.rows import dict_row
    except Exception as exc:  # pragma: no cover - env-specific
        raise SystemExit(
            f"psycopg is required for live Postgres export: {exc}"
        ) from exc
    url = os.environ.get("ENOCH_SUPABASE_DATABASE_URL") or os.environ.get(
        "DATABASE_URL"
    )
    if not url:
        raise SystemExit("ENOCH_SUPABASE_DATABASE_URL or DATABASE_URL is required")
    where = []
    params: list[Any] = []
    if project_ids:
        where.append("pe.project_id = any(%s)")
        params.append(project_ids)
    if query:
        where.append("(pe.project_id ilike %s or pe.project_name ilike %s)")
        params.extend([f"%{query}%", f"%{query}%"])
    where_sql = " and ".join(where) if where else "true"
    sql = f"""
    select
      pe.project_id, pe.project_name, pe.run_id, pe.decision_summary,
      pe.research_outcome, pe.hypothesis_status, pe.evidence_strength,
      pe.claim_scope, pe.scale_limits, pe.useful_signal_summary,
      pe.recommended_next_action, pe.stop_reason,
      pe.followup_recommended, pe.followup_type, pe.followup_title,
      pe.followup_hypothesis, pe.followup_required_evidence,
      pe.followup_success_threshold, pe.followup_stop_condition,
      pe.followup_depth, pe.bounded_paper_ready, pe.compute_scale_blocked,
      pe.write_needed, pe.has_live_paper_row,
      qi.updated_at, p.paper_id, p.paper_status, ci.imported_at as corpus_imported_at,
      coalesce(array_remove(array_cat(array_cat(array_cat(array_agg(distinct rs.source_id), array_agg(distinct parent_rs.source_id)), array_agg(distinct idea_rs.source_id)), array_agg(distinct candidate_rs.source_id)), null), '{{}}') as source_ids,
      coalesce(array_remove(array_cat(array_cat(array_cat(array_agg(distinct rs.url), array_agg(distinct parent_rs.url)), array_agg(distinct idea_rs.url)), array_agg(distinct candidate_rs.url)), null), '{{}}') as source_urls,
      coalesce(array_remove(array_cat(array_cat(array_cat(array_agg(distinct rs.title), array_agg(distinct parent_rs.title)), array_agg(distinct idea_rs.title)), array_agg(distinct candidate_rs.title)), null), '{{}}') as source_titles,
      (
        coalesce(
          jsonb_agg(distinct jsonb_build_object('source_id', rs.source_id, 'url', rs.url, 'title', rs.title))
          filter (where rs.source_id is not null),
          '[]'::jsonb
        ) || coalesce(
          jsonb_agg(distinct jsonb_build_object('source_id', parent_rs.source_id, 'url', parent_rs.url, 'title', parent_rs.title))
          filter (where parent_rs.source_id is not null),
          '[]'::jsonb
        ) || coalesce(
          jsonb_agg(distinct jsonb_build_object('source_id', idea_rs.source_id, 'url', idea_rs.url, 'title', idea_rs.title))
          filter (where idea_rs.source_id is not null),
          '[]'::jsonb
        ) || coalesce(
          jsonb_agg(distinct jsonb_build_object('source_id', candidate_rs.source_id, 'url', candidate_rs.url, 'title', candidate_rs.title))
          filter (where candidate_rs.source_id is not null),
          '[]'::jsonb
        )
      ) as source_records,
      cp.project_dir as artifact_root,
      array['run_notes.md','.enoch/project_decision.json','.enoch/metrics.json','results/smoke.json'] as artifact_paths
    from enoch.paper_eligibility pe
    left join enoch.queue_items qi on qi.project_id=pe.project_id
    left join enoch.papers p on p.project_id=pe.project_id or p.run_id=pe.run_id
    left join enoch.corpus_imports ci on ci.paper_id=p.paper_id
    left join enoch.research_lineage rl on rl.target_type='candidate' and rl.target_id=pe.project_id
    left join enoch.research_sources rs on rs.source_id=rl.source_id
    left join enoch.research_lineage idea_source_rl on idea_source_rl.target_type='idea' and idea_source_rl.target_id=pe.project_id and idea_source_rl.source_type='source' and idea_source_rl.relation_type='generated_from'
    left join enoch.research_sources idea_rs on idea_rs.source_id=idea_source_rl.source_id
    left join enoch.research_lineage queued_rl on queued_rl.target_type='project' and queued_rl.target_id=pe.project_id and queued_rl.source_type='idea' and queued_rl.relation_type='queued_as'
    left join enoch.research_lineage admitted_rl on admitted_rl.target_type='idea' and admitted_rl.target_id=queued_rl.source_id and admitted_rl.source_type='candidate' and admitted_rl.relation_type='admitted_as'
    left join enoch.research_lineage candidate_source_rl on candidate_source_rl.target_type='candidate' and candidate_source_rl.target_id=admitted_rl.source_id and candidate_source_rl.source_type='source' and candidate_source_rl.relation_type='generated_from'
    left join enoch.research_sources candidate_rs on candidate_rs.source_id=candidate_source_rl.source_id
    left join enoch.paper_eligibility parent_pe on lower(parent_pe.followup_title)=lower(pe.project_name) and parent_pe.project_id<>pe.project_id
    left join enoch.research_lineage parent_rl on parent_rl.target_type='candidate' and parent_rl.target_id=parent_pe.project_id
    left join enoch.research_sources parent_rs on parent_rs.source_id=parent_rl.source_id
    left join enoch.projects cp on cp.project_id=pe.project_id
    where {where_sql}
    group by pe.project_id, pe.project_name, pe.run_id, pe.decision_summary,
      pe.research_outcome, pe.hypothesis_status, pe.evidence_strength,
      pe.claim_scope, pe.scale_limits, pe.useful_signal_summary,
      pe.recommended_next_action, pe.stop_reason,
      pe.followup_recommended, pe.followup_type, pe.followup_title,
      pe.followup_hypothesis, pe.followup_required_evidence,
      pe.followup_success_threshold, pe.followup_stop_condition,
      pe.followup_depth, pe.bounded_paper_ready, pe.compute_scale_blocked,
      pe.write_needed, pe.has_live_paper_row,
      qi.updated_at, p.paper_id, p.paper_status, ci.imported_at, cp.project_dir
    """
    with psycopg.connect(url, row_factory=dict_row) as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return [dict(row) for row in cur.fetchall()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-repo", required=True, type=Path)
    parser.add_argument(
        "--input-json",
        type=Path,
        help="JSON array of rows for deterministic/offline export",
    )
    parser.add_argument("--project-id", action="append", default=[])
    parser.add_argument("--query", default="")
    parser.add_argument(
        "--clean-only",
        action="store_true",
        help="Export only rows that pass the deterministic promising-signal contract; summarize skipped rows in manifest.",
    )
    parser.add_argument(
        "--audit-report",
        type=Path,
        help="Write a dry-run backfill audit JSON report instead of exporting rows",
    )
    parser.add_argument(
        "--audit-markdown", type=Path, help="Optional Markdown path for --audit-report"
    )
    parser.add_argument(
        "--validate-output-repo",
        action="store_true",
        help="Validate output repo manifest against the fetched control-plane selection without rewriting files.",
    )
    args = parser.parse_args(argv)
    if args.input_json:
        rows = json.loads(args.input_json.read_text(encoding="utf-8"))
        if not isinstance(rows, list):
            raise SystemExit("--input-json must contain a JSON list")
    else:
        rows = _fetch_postgres_rows(args.project_id, args.query)
    if args.audit_report:
        report = audit_backfill(rows)
        args.audit_report.parent.mkdir(parents=True, exist_ok=True)
        args.audit_report.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        if args.audit_markdown:
            args.audit_markdown.parent.mkdir(parents=True, exist_ok=True)
            args.audit_markdown.write_text(
                audit_backfill_markdown(report) + "\n", encoding="utf-8"
            )
        print(
            json.dumps(
                {"audit_report": str(args.audit_report), **report["summary"]},
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    if args.validate_output_repo:
        issues = validate_repo_against_rows(rows, args.output_repo)
        if issues:
            print(
                json.dumps({"ok": False, "issues": issues}, indent=2, sort_keys=True),
                file=sys.stderr,
            )
            return 1
        records = _records_from_repo(args.output_repo)
        print(json.dumps({"ok": True, "count": len(records)}, indent=2, sort_keys=True))
        return 0
    if args.clean_only:
        rows = clean_export_rows(rows)
    result = write_export(rows, args.output_repo)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
