from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_REPORT_PATH = "/var/lib/enoch-control-plane/source-lineage/latest-report.json"

SOURCE_PROBLEM_TOKENS = ("missing_source", "missing_parent_run_source", "source_url_missing_source", "source_id_missing_source")
LINEAGE_PROBLEM_TOKENS = ("missing_lineage", "missing_parent_project_lineage", "missing_parent_run_lineage")


def _utc_iso_from_mtime(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _problem_buckets(problem_counts: dict[str, Any]) -> tuple[int, int]:
    missing_sources = 0
    missing_lineage = 0
    for raw_kind, raw_count in problem_counts.items():
        kind = str(raw_kind)
        count = _safe_int(raw_count)
        if any(token in kind for token in SOURCE_PROBLEM_TOKENS):
            missing_sources += count
        if any(token in kind for token in LINEAGE_PROBLEM_TOKENS):
            missing_lineage += count
    return missing_sources, missing_lineage


def classify_source_lineage_report(report: dict[str, Any], *, report_path: str = "", report_mtime: str = "") -> dict[str, Any]:
    counts_raw = report.get("counts")
    problem_counts_raw = report.get("problem_counts")
    problems_raw = report.get("problems")
    if not isinstance(counts_raw, dict) or not isinstance(problem_counts_raw, dict) or not isinstance(problems_raw, list):
        return {
            "ok": False,
            "status": "blocked",
            "label": "Source lineage: BLOCKED",
            "report_path": report_path,
            "report_mtime": report_mtime,
            "report_generated_at": report.get("checked_at") or report.get("generated_at") or "",
            "schema_version": report.get("schema_version") or "",
            "candidates_checked": 0,
            "followups_checked": 0,
            "sources_checked": 0,
            "lineages_checked": 0,
            "problem_counts": {"malformed_source_lineage_report": 1},
            "missing_sources": 0,
            "missing_lineage": 0,
            "problem_details": [{"kind": "malformed_source_lineage_report"}],
        }
    problem_counts = {str(key): _safe_int(value) for key, value in problem_counts_raw.items()}
    missing_sources, missing_lineage = _problem_buckets(problem_counts)
    problem_total = _safe_int(counts_raw.get("problems")) or sum(problem_counts.values())
    status = str(report.get("status") or ("blocked" if problem_total else "clean")).strip().lower()
    if status not in {"clean", "warnings", "blocked"}:
        status = "blocked" if problem_total else "clean"
    if problem_total and status == "clean":
        status = "blocked"
    label = {
        "clean": "Source lineage: clean",
        "warnings": "Source lineage: warnings",
        "blocked": "Source lineage: BLOCKED",
    }[status]
    return {
        "ok": status != "blocked",
        "status": status,
        "label": label,
        "report_path": report_path,
        "report_mtime": report_mtime,
        "report_generated_at": report.get("checked_at") or report.get("generated_at") or "",
        "schema_version": report.get("schema_version") or "",
        "created_after": report.get("created_after") or "",
        "candidates_checked": _safe_int(counts_raw.get("candidates")),
        "followups_checked": _safe_int(counts_raw.get("followups")),
        "sources_checked": _safe_int(counts_raw.get("sources")),
        "lineages_checked": _safe_int(counts_raw.get("lineages")),
        "problem_counts": dict(Counter(problem_counts)),
        "missing_sources": missing_sources,
        "missing_lineage": missing_lineage,
        "problem_details": [item for item in problems_raw if isinstance(item, dict)][:25],
    }


def load_latest_source_lineage_status(paths: tuple[str, ...] | list[str] = (DEFAULT_REPORT_PATH,)) -> dict[str, Any]:
    chosen = next((Path(path) for path in paths if path and Path(path).exists()), None)
    if chosen is None:
        report_path = str(paths[0]) if paths else ""
        return {
            "ok": False,
            "status": "blocked",
            "label": "Source lineage: BLOCKED",
            "report_path": report_path,
            "report_mtime": "",
            "report_generated_at": "",
            "schema_version": "",
            "candidates_checked": 0,
            "followups_checked": 0,
            "sources_checked": 0,
            "lineages_checked": 0,
            "problem_counts": {"missing_source_lineage_report": 1},
            "missing_sources": 0,
            "missing_lineage": 0,
            "problem_details": [{"kind": "missing_source_lineage_report"}],
        }
    try:
        with chosen.open("r", encoding="utf-8") as handle:
            report = json.load(handle)
    except (OSError, json.JSONDecodeError):
        report = {}
    return classify_source_lineage_report(report if isinstance(report, dict) else {}, report_path=str(chosen), report_mtime=_utc_iso_from_mtime(chosen))
