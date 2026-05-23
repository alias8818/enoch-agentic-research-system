from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .datasets import as_bool, is_supported_negative_nonblocking, negative_rationale

DEFAULT_REPORT_PATHS = (
    "/var/lib/enoch-control-plane/research-quality/latest-report.json",
    "/var/lib/enoch-control-plane/research-quality/dspy-quality-report.after.json",
    "/var/lib/enoch-control-plane/research-quality/dspy-quality-report.json",
)
DEFAULT_WINDOW_REPORT_PATH = (
    "/var/lib/enoch-control-plane/research-quality/latest-window-comparison.json"
)
DEFAULT_AUTOPILOT_HISTORY_PATH = (
    "/var/lib/enoch-control-plane/research-quality/autopilot-history.jsonl"
)

RESEARCH_QUALITY_LABEL_BLOCKED = "Research quality: BLOCKED"
RESEARCH_QUALITY_LABEL_CLEAN = "Research quality: clean"
RESEARCH_QUALITY_LABEL_WARNINGS = "Research quality: warnings"


def _utc_iso_from_mtime(path: Path) -> str:
    return (
        datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _problem_severity(problem: str, item: dict[str, Any]) -> str:
    decision = str(item.get("decision") or "").strip()
    hypothesis_status = str(item.get("hypothesis_status") or "").strip()
    if (
        decision == "finalize_negative"
        and hypothesis_status in {"mixed", "unsupported"}
    ) or (
        decision == "blocked"
        and hypothesis_status in {"inconclusive", "mixed", "unsupported", "unknown"}
    ):
        if problem in {
            "weak_or_missing_evidence_strength",
            "supported_but_negative_requires_review",
        }:
            return "warning"
    followup_recommended = as_bool(item.get("followup_recommended"))
    bounded_followup = (
        followup_recommended
        and bool(item.get("followup_success_threshold"))
        and bool(item.get("followup_stop_condition"))
    )
    if (
        problem == "supported_but_negative_requires_review"
        and is_supported_negative_nonblocking(
            decision=decision,
            hypothesis_status=hypothesis_status,
            followup_recommended=followup_recommended,
            rationale=negative_rationale(item),
            bounded_followup=bounded_followup,
            research_outcome=str(item.get("research_outcome") or "").strip(),
            claim_scope=str(item.get("claim_scope") or "").strip(),
            scale_limits=str(item.get("scale_limits") or "").strip(),
            evidence_strength=str(item.get("evidence_strength") or "").strip(),
            bounded_paper_ready=as_bool(item.get("bounded_paper_ready")),
        )
    ):
        return "info"
    if problem in {
        "missing_success_threshold",
        "missing_kill_condition",
        "thin_required_evidence",
        "thin_expected_artifacts",
        "similar_prior_without_novelty_comparison",
    }:
        return "warning"
    return "blocked"


def classify_quality_report(
    report: dict[str, Any], *, report_path: str = "", report_mtime: str = ""
) -> dict[str, Any]:
    summary_raw = report.get("summary")
    candidate_scores_raw = report.get("candidate_scores")
    decision_scores_raw = report.get("decision_scores")
    malformed_reasons: list[str] = []
    if not isinstance(summary_raw, dict):
        malformed_reasons.append("missing_or_invalid_summary")
    if not isinstance(candidate_scores_raw, list):
        malformed_reasons.append("missing_or_invalid_candidate_scores")
    if not isinstance(decision_scores_raw, list):
        malformed_reasons.append("missing_or_invalid_decision_scores")
    if malformed_reasons:
        return {
            "ok": False,
            "status": "blocked",
            "label": RESEARCH_QUALITY_LABEL_BLOCKED,
            "report_path": report_path,
            "report_mtime": report_mtime,
            "report_generated_at": report.get("generated_at") or "",
            "schema_version": report.get("schema_version") or "",
            "decisions_checked": 0,
            "candidates_checked": 0,
            "problem_counts": {"malformed_quality_report": 1},
            "raw_problem_counts": {},
            "severity_counts": {"blocked": 1},
            "problem_details": [
                {
                    "section": "report",
                    "severity": "blocked",
                    "problem": "malformed_quality_report",
                    "reason": "; ".join(malformed_reasons),
                }
            ],
        }
    summary = summary_raw
    raw_problem_counts = dict(summary.get("problem_counts") or {})
    actionable_problem_counts: Counter[str] = Counter()
    severity_counts: Counter[str] = Counter()
    problem_details: list[dict[str, Any]] = []

    for section_name in ("candidate_scores", "decision_scores"):
        for item in report.get(section_name) or []:
            if not isinstance(item, dict):
                continue
            for problem in item.get("problems") or []:
                severity = _problem_severity(str(problem), item)
                severity_counts[severity] += 1
                if severity in {"warning", "blocked"}:
                    actionable_problem_counts[str(problem)] += 1
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
        "clean": RESEARCH_QUALITY_LABEL_CLEAN,
        "warnings": RESEARCH_QUALITY_LABEL_WARNINGS,
        "blocked": RESEARCH_QUALITY_LABEL_BLOCKED,
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
        "problem_counts": dict(actionable_problem_counts),
        "raw_problem_counts": raw_problem_counts,
        "severity_counts": dict(severity_counts),
        "problem_details": problem_details[:25],
    }


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _safe_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _load_json_file(path: str) -> dict[str, Any] | None:
    if not path:
        return None
    candidate = Path(path)
    if not candidate.exists():
        return None
    try:
        with candidate.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _load_autopilot_history_summary(
    path: str, *, cutoff: str = "", max_rows: int = 200
) -> dict[str, Any]:
    if not path:
        return {"path": path, "available": False, "reason": "not_configured"}
    candidate = Path(path)
    if not candidate.exists():
        return {"path": path, "available": False, "reason": "missing_history"}
    try:
        lines = candidate.read_text(encoding="utf-8").splitlines()[-max_rows:]
    except OSError as exc:
        return {"path": path, "available": False, "reason": f"read_failed: {exc}"}

    rows: list[dict[str, Any]] = []
    for line in lines:
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(item, dict):
            continue
        if (
            cutoff
            and str(item.get("checked_at") or item.get("recorded_at") or "") < cutoff
        ):
            continue
        rows.append(item)

    malformed_rows = [
        item
        for item in rows
        if _safe_int(item.get("malformed_provider_response_count")) > 0
    ]
    return {
        "path": path,
        "available": True,
        "rows_checked": len(rows),
        "malformed_provider_response_ticks": len(malformed_rows),
        "malformed_provider_response_count": sum(
            _safe_int(item.get("malformed_provider_response_count")) for item in rows
        ),
        "last_malformed_at": str(
            malformed_rows[-1].get("checked_at")
            or malformed_rows[-1].get("recorded_at")
            or ""
        )
        if malformed_rows
        else "",
        "last_generated_count": _safe_int(rows[-1].get("generated_count"))
        if rows
        else 0,
        "last_checked_at": str(
            rows[-1].get("checked_at") or rows[-1].get("recorded_at") or ""
        )
        if rows
        else "",
    }


def _post_prompt_monitor(*, window_path: str, history_path: str) -> dict[str, Any]:
    window = _load_json_file(window_path)
    if not window:
        history = _load_autopilot_history_summary(history_path)
        return {
            "available": False,
            "reason": "missing_window_comparison",
            "window_path": window_path,
            "history": history,
        }

    post = window.get("post") or {}
    delta = window.get("delta") or {}
    meta = window.get("post_meta") or {}
    eval_counts = post.get("eval_case_counts") or {}
    candidate_count = _safe_int(
        post.get("candidate_count") or meta.get("candidate_count")
    )
    decision_count = _safe_int(post.get("decision_count") or meta.get("decision_count"))
    cutoff = str(window.get("cutoff") or "")
    history = _load_autopilot_history_summary(history_path, cutoff=cutoff)
    decision_coverage = (
        round(decision_count / candidate_count, 3) if candidate_count else 0.0
    )
    return {
        "available": True,
        "window_path": window_path,
        "cutoff": cutoff,
        "candidate_count": candidate_count,
        "decision_count": decision_count,
        "decision_coverage": decision_coverage,
        "proxy_only_positive": _safe_int(eval_counts.get("proxy_only_positive")),
        "proxy_only_positive_delta": _safe_float(
            delta.get("proxy_only_positive_delta")
        ),
        "useful_adjacent_followup": _safe_int(
            eval_counts.get("useful_adjacent_followup")
        ),
        "useful_adjacent_followup_delta": _safe_float(
            delta.get("useful_adjacent_followup_delta")
        ),
        "high_similarity_pair_count": _safe_int(post.get("high_similarity_pair_count")),
        "moonshot_count": _safe_int(post.get("moonshot_count")),
        "moonshot_avg_score": _safe_float(post.get("moonshot_avg_score")),
        "moonshot_avg_score_delta": _safe_float(delta.get("moonshot_avg_score_delta")),
        "malformed_provider_response_count": _safe_int(
            history.get("malformed_provider_response_count")
        ),
        "malformed_provider_response_ticks": _safe_int(
            history.get("malformed_provider_response_ticks")
        ),
        "last_malformed_at": history.get("last_malformed_at") or "",
        "last_checked_at": history.get("last_checked_at")
        or meta.get("candidate_last_created_at")
        or "",
    }


def load_latest_quality_status(
    paths: list[str] | tuple[str, ...] = DEFAULT_REPORT_PATHS,
    *,
    window_report_path: str = DEFAULT_WINDOW_REPORT_PATH,
    autopilot_history_path: str = DEFAULT_AUTOPILOT_HISTORY_PATH,
) -> dict[str, Any]:
    chosen = next((Path(path) for path in paths if path and Path(path).exists()), None)
    if chosen is None:
        report_path = str(paths[0]) if paths else ""
        return {
            "ok": False,
            "status": "blocked",
            "label": RESEARCH_QUALITY_LABEL_BLOCKED,
            "report_path": report_path,
            "report_mtime": "",
            "report_generated_at": "",
            "schema_version": "",
            "decisions_checked": 0,
            "candidates_checked": 0,
            "problem_counts": {"missing_quality_report": 1},
            "severity_counts": {"blocked": 1},
            "problem_details": [
                {
                    "section": "report",
                    "severity": "blocked",
                    "problem": "missing_quality_report",
                }
            ],
            "post_prompt_monitor": _post_prompt_monitor(
                window_path=window_report_path, history_path=autopilot_history_path
            ),
        }
    with chosen.open("r", encoding="utf-8") as handle:
        report = json.load(handle)
    status = classify_quality_report(
        report, report_path=str(chosen), report_mtime=_utc_iso_from_mtime(chosen)
    )
    status["post_prompt_monitor"] = _post_prompt_monitor(
        window_path=window_report_path, history_path=autopilot_history_path
    )
    return status
