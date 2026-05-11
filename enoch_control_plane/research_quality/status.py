from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_REPORT_PATHS = (
    "/var/lib/enoch-control-plane/research-quality/latest-report.json",
    "/tmp/enoch-dspy-quality-report.after.json",
    "/tmp/enoch-dspy-quality-report.json",
)


def _utc_iso_from_mtime(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _problem_severity(problem: str, item: dict[str, Any]) -> str:
    decision = str(item.get("decision") or "").strip()
    hypothesis_status = str(item.get("hypothesis_status") or "").strip()
    if problem == "weak_or_missing_evidence_strength" and decision == "finalize_negative" and hypothesis_status in {"mixed", "unsupported"}:
        return "warning"
    if problem in {
        "missing_success_threshold",
        "missing_kill_condition",
        "thin_required_evidence",
        "thin_expected_artifacts",
        "similar_prior_without_novelty_comparison",
    }:
        return "warning"
    return "blocked"


def classify_quality_report(report: dict[str, Any], *, report_path: str = "", report_mtime: str = "") -> dict[str, Any]:
    summary = report.get("summary") or {}
    problem_counts = dict(summary.get("problem_counts") or {})
    severity_counts: Counter[str] = Counter()
    problem_details: list[dict[str, Any]] = []

    for section_name in ("candidate_scores", "decision_scores"):
        for item in report.get(section_name) or []:
            if not isinstance(item, dict):
                continue
            for problem in item.get("problems") or []:
                severity = _problem_severity(str(problem), item)
                severity_counts[severity] += 1
                problem_details.append(
                    {
                        "section": section_name,
                        "severity": severity,
                        "problem": str(problem),
                        "project_id": item.get("project_id"),
                        "candidate_id": item.get("candidate_id"),
                        "run_id": item.get("run_id"),
                        "title": item.get("project_name") or item.get("title"),
                        "decision": item.get("decision"),
                        "hypothesis_status": item.get("hypothesis_status"),
                    }
                )

    blocked = int(severity_counts.get("blocked") or 0)
    warnings = int(severity_counts.get("warning") or 0)
    status = "blocked" if blocked else "warnings" if warnings else "clean"
    label = {
        "clean": "Research quality: clean",
        "warnings": "Research quality: warnings",
        "blocked": "Research quality: BLOCKED",
    }[status]
    return {
        "ok": status != "blocked",
        "status": status,
        "label": label,
        "report_path": report_path,
        "report_mtime": report_mtime,
        "report_generated_at": report.get("generated_at") or "",
        "schema_version": report.get("schema_version") or "",
        "decisions_checked": int(summary.get("decision_count") or 0),
        "candidates_checked": int(summary.get("candidate_count") or 0),
        "problem_counts": problem_counts,
        "severity_counts": dict(severity_counts),
        "problem_details": problem_details[:25],
    }


def load_latest_quality_status(paths: list[str] | tuple[str, ...] = DEFAULT_REPORT_PATHS) -> dict[str, Any]:
    chosen = next((Path(path) for path in paths if path and Path(path).exists()), None)
    if chosen is None:
        report_path = str(paths[0]) if paths else ""
        return {
            "ok": False,
            "status": "blocked",
            "label": "Research quality: BLOCKED",
            "report_path": report_path,
            "report_mtime": "",
            "report_generated_at": "",
            "schema_version": "",
            "decisions_checked": 0,
            "candidates_checked": 0,
            "problem_counts": {"missing_quality_report": 1},
            "severity_counts": {"blocked": 1},
            "problem_details": [{"section": "report", "severity": "blocked", "problem": "missing_quality_report"}],
        }
    with chosen.open("r", encoding="utf-8") as handle:
        report = json.load(handle)
    return classify_quality_report(report, report_path=str(chosen), report_mtime=_utc_iso_from_mtime(chosen))
