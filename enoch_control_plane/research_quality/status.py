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
DEFAULT_REFRESH_STATUS_PATH = (
    "/var/lib/enoch-control-plane/research-quality/latest-refresh.json"
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


def _weak_evidence_problem_severity(
    problem: str,
    *,
    decision: str,
    hypothesis_status: str,
    followup_recommended: bool = False,
    bounded_followup: bool = False,
    bounded_paper_ready: bool = False,
) -> str | None:
    weak_evidence_problems = {
        "weak_or_missing_evidence_strength",
        "supported_but_negative_requires_review",
    }
    demote_decision = (
        decision == "finalize_negative"
        and hypothesis_status in {"mixed", "unsupported"}
    ) or (
        decision == "blocked"
        and hypothesis_status in {"inconclusive", "mixed", "unsupported", "unknown"}
    )
    needs_external_review = (
        decision == "needs_review"
        and hypothesis_status in {"inconclusive", "mixed", "unsupported", "unknown"}
        and followup_recommended
        and bounded_followup
        and not bounded_paper_ready
    )
    if (demote_decision or needs_external_review) and problem in weak_evidence_problems:
        return "warning"
    return None


def _problem_severity(problem: str, item: dict[str, Any]) -> str:
    decision = str(item.get("decision") or "").strip()
    hypothesis_status = str(item.get("hypothesis_status") or "").strip()
    followup_recommended = as_bool(item.get("followup_recommended"))
    bounded_followup = (
        followup_recommended
        and bool(item.get("followup_success_threshold"))
        and bool(item.get("followup_stop_condition"))
    )
    demoted = _weak_evidence_problem_severity(
        problem,
        decision=decision,
        hypothesis_status=hypothesis_status,
        followup_recommended=followup_recommended,
        bounded_followup=bounded_followup,
        bounded_paper_ready=as_bool(item.get("bounded_paper_ready")),
    )
    if demoted is not None:
        return demoted
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


def _quality_report_malformed_reasons(report: dict[str, Any]) -> list[str]:
    malformed_reasons: list[str] = []
    if not isinstance(report.get("summary"), dict):
        malformed_reasons.append("missing_or_invalid_summary")
    if not isinstance(report.get("candidate_scores"), list):
        malformed_reasons.append("missing_or_invalid_candidate_scores")
    if not isinstance(report.get("decision_scores"), list):
        malformed_reasons.append("missing_or_invalid_decision_scores")
    return malformed_reasons


def _blocked_malformed_quality_report(
    report: dict[str, Any],
    *,
    report_path: str,
    report_mtime: str,
    malformed_reasons: list[str],
) -> dict[str, Any]:
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


def _blocked_unreadable_quality_report(
    *,
    report_path: str,
    report_mtime: str,
    problem: str,
    reason: str,
) -> dict[str, Any]:
    return {
        "ok": False,
        "status": "blocked",
        "label": RESEARCH_QUALITY_LABEL_BLOCKED,
        "report_path": report_path,
        "report_mtime": report_mtime,
        "report_generated_at": "",
        "schema_version": "",
        "decisions_checked": 0,
        "candidates_checked": 0,
        "problem_counts": {problem: 1},
        "raw_problem_counts": {},
        "severity_counts": {"blocked": 1},
        "problem_details": [
            {
                "section": "report",
                "severity": "blocked",
                "problem": problem,
                "reason": reason,
            }
        ],
    }


def _quality_problem_detail(
    section_name: str,
    problem: str,
    severity: str,
    item: dict[str, Any],
) -> dict[str, Any]:
    return {
        "section": section_name,
        "severity": severity,
        "problem": problem,
        "project_id": item.get("project_id"),
        "candidate_id": item.get("candidate_id"),
        "run_id": item.get("run_id"),
        "title": item.get("project_name") or item.get("title"),
        "decision": item.get("decision"),
        "hypothesis_status": item.get("hypothesis_status"),
    }


def _collect_quality_problem_metrics(
    report: dict[str, Any],
) -> tuple[Counter[str], Counter[str], list[dict[str, Any]]]:
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
                    _quality_problem_detail(section_name, str(problem), severity, item)
                )

    return actionable_problem_counts, severity_counts, problem_details


def _quality_status_from_severity_counts(
    severity_counts: Counter[str],
) -> tuple[str, str]:
    blocked = int(severity_counts.get("blocked") or 0)
    warnings = int(severity_counts.get("warning") or 0)
    if blocked:
        status = "blocked"
    elif warnings:
        status = "warnings"
    else:
        status = "clean"
    label = {
        "clean": RESEARCH_QUALITY_LABEL_CLEAN,
        "warnings": RESEARCH_QUALITY_LABEL_WARNINGS,
        "blocked": RESEARCH_QUALITY_LABEL_BLOCKED,
    }[status]
    return status, label


def classify_quality_report(
    report: dict[str, Any], *, report_path: str = "", report_mtime: str = ""
) -> dict[str, Any]:
    malformed_reasons = _quality_report_malformed_reasons(report)
    if malformed_reasons:
        return _blocked_malformed_quality_report(
            report,
            report_path=report_path,
            report_mtime=report_mtime,
            malformed_reasons=malformed_reasons,
        )

    summary = report["summary"]
    raw_problem_counts = dict(summary.get("problem_counts") or {})
    actionable_problem_counts, severity_counts, problem_details = (
        _collect_quality_problem_metrics(report)
    )
    status, label = _quality_status_from_severity_counts(severity_counts)
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
        "recommendations": [
            str(item)
            for item in report.get("recommendations") or []
            if str(item).strip()
        ][:10],
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


def _load_refresh_status(path: str) -> dict[str, Any]:
    if not path:
        return {"available": False, "reason": "not_configured", "path": path}
    payload = _load_json_file(path)
    if payload is None:
        return {"available": False, "reason": "missing_refresh_status", "path": path}
    return {
        "available": True,
        "ok": bool(payload.get("ok")),
        "action": str(payload.get("action") or ""),
        "reason": str(payload.get("reason") or ""),
        "recorded_at": str(payload.get("recorded_at") or ""),
        "output": str(payload.get("output") or ""),
        "path": path,
    }


def _autopilot_history_item_timestamp(item: dict[str, Any]) -> str:
    return str(item.get("checked_at") or item.get("recorded_at") or "")


def _parse_autopilot_history_row(line: str, cutoff: str) -> dict[str, Any] | None:
    try:
        item = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(item, dict):
        return None
    if cutoff and _autopilot_history_item_timestamp(item) < cutoff:
        return None
    return item


def _collect_autopilot_history_rows(
    lines: list[str], cutoff: str
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in lines:
        row = _parse_autopilot_history_row(line, cutoff)
        if row is not None:
            rows.append(row)
    return rows


def _malformed_provider_operator_action() -> str:
    return (
        "inspect provider-generation output for this tick before trusting new "
        "idea volume"
    )


def _malformed_provider_row(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "checked_at": _autopilot_history_item_timestamp(item),
        "recorded_at": str(item.get("recorded_at") or ""),
        "provider_model": str(item.get("provider_model") or ""),
        "malformed_provider_response_count": _safe_int(
            item.get("malformed_provider_response_count")
        ),
        "generated_count": _safe_int(item.get("generated_count")),
        "promoted_count": _safe_int(item.get("promoted_count")),
        "dispatched_count": _safe_int(item.get("dispatched_count")),
        "operator_action": _malformed_provider_operator_action(),
    }


def _autopilot_history_summary_from_rows(
    path: str, rows: list[dict[str, Any]]
) -> dict[str, Any]:
    malformed_rows = [
        item
        for item in rows
        if _safe_int(item.get("malformed_provider_response_count")) > 0
    ]
    last_row = rows[-1] if rows else None
    last_malformed = malformed_rows[-1] if malformed_rows else None
    model_counts: Counter[str] = Counter()
    for item in malformed_rows:
        model = str(item.get("provider_model") or "").strip()
        if model:
            model_counts[model] += _safe_int(
                item.get("malformed_provider_response_count")
            )
    return {
        "path": path,
        "available": True,
        "rows_checked": len(rows),
        "malformed_provider_response_ticks": len(malformed_rows),
        "malformed_provider_response_count": sum(
            _safe_int(item.get("malformed_provider_response_count")) for item in rows
        ),
        "last_malformed_at": _autopilot_history_item_timestamp(last_malformed)
        if last_malformed
        else "",
        "last_generated_count": _safe_int(last_row.get("generated_count"))
        if last_row
        else 0,
        "last_checked_at": _autopilot_history_item_timestamp(last_row)
        if last_row
        else "",
        "malformed_provider_model_counts": dict(sorted(model_counts.items())),
        "recent_malformed_provider_responses": [
            _malformed_provider_row(item) for item in reversed(malformed_rows[-3:])
        ],
    }


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

    rows = _collect_autopilot_history_rows(lines, cutoff)
    return _autopilot_history_summary_from_rows(path, rows)


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
        "malformed_provider_model_counts": history.get(
            "malformed_provider_model_counts"
        )
        or {},
        "recent_malformed_provider_responses": history.get(
            "recent_malformed_provider_responses"
        )
        or [],
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
    refresh_status_path: str = DEFAULT_REFRESH_STATUS_PATH,
) -> dict[str, Any]:
    refresh_status = _load_refresh_status(refresh_status_path)
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
            "refresh_status": refresh_status,
        }
    report_mtime = _utc_iso_from_mtime(chosen)
    try:
        with chosen.open("r", encoding="utf-8") as handle:
            report = json.load(handle)
    except json.JSONDecodeError as exc:
        status = _blocked_unreadable_quality_report(
            report_path=str(chosen),
            report_mtime=report_mtime,
            problem="malformed_quality_report",
            reason=str(exc),
        )
        status["post_prompt_monitor"] = _post_prompt_monitor(
            window_path=window_report_path, history_path=autopilot_history_path
        )
        status["refresh_status"] = refresh_status
        return status
    except OSError as exc:
        status = _blocked_unreadable_quality_report(
            report_path=str(chosen),
            report_mtime=report_mtime,
            problem="unreadable_quality_report",
            reason=str(exc),
        )
        status["post_prompt_monitor"] = _post_prompt_monitor(
            window_path=window_report_path, history_path=autopilot_history_path
        )
        status["refresh_status"] = refresh_status
        return status
    if not isinstance(report, dict):
        status = _blocked_unreadable_quality_report(
            report_path=str(chosen),
            report_mtime=report_mtime,
            problem="malformed_quality_report",
            reason="top-level report payload must be an object",
        )
        status["post_prompt_monitor"] = _post_prompt_monitor(
            window_path=window_report_path, history_path=autopilot_history_path
        )
        status["refresh_status"] = refresh_status
        return status
    status = classify_quality_report(
        report, report_path=str(chosen), report_mtime=report_mtime
    )
    status["post_prompt_monitor"] = _post_prompt_monitor(
        window_path=window_report_path, history_path=autopilot_history_path
    )
    status["refresh_status"] = refresh_status
    return status
