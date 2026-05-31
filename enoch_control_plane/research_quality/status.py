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
QUALITY_FLOOR_THRESHOLD = 0.7


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


def _summary_count_mapping(value: Any, *, limit: int = 20) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    counts: dict[str, int] = {}
    for key, count in value.items():
        label = str(key or "").strip()
        if not label:
            continue
        try:
            counts[label] = int(count or 0)
        except (TypeError, ValueError):
            counts[label] = 0
        if len(counts) >= limit:
            break
    return counts


def _summary_count_rows(
    value: Any, *, required_label: str, optional_label: str = "", limit: int = 10
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    rows: list[dict[str, Any]] = []
    for raw in value:
        if not isinstance(raw, dict):
            continue
        label = str(raw.get(required_label) or "").strip()
        if not label:
            continue
        row: dict[str, Any] = {required_label: label}
        if optional_label:
            row[optional_label] = str(raw.get(optional_label) or "").strip()
        try:
            row["count"] = int(raw.get("count") or 0)
        except (TypeError, ValueError):
            row["count"] = 0
        rows.append(row)
        if len(rows) >= limit:
            break
    return rows


def _problem_list(value: Any, *, limit: int = 5) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()][:limit]


def _candidate_status_sample(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "candidate_id": str(row.get("candidate_id") or "").strip(),
        "title": str(row.get("title") or "").strip(),
        "status": str(row.get("status") or "").strip(),
        "deterministic_total_score": _safe_float(row.get("deterministic_total_score")),
        "contract_quality_score": _safe_float(row.get("contract_quality_score")),
        "problems": _problem_list(row.get("problems")),
    }


def _candidate_status_samples(
    value: Any, *, limit_per_status: int = 3
) -> dict[str, Any]:
    if not isinstance(value, list):
        return {}
    samples: dict[str, list[dict[str, Any]]] = {}
    for raw in value:
        if not isinstance(raw, dict):
            continue
        status = str(raw.get("status") or "").strip()
        candidate_id = str(raw.get("candidate_id") or "").strip()
        if not status or not candidate_id:
            continue
        status_samples = samples.setdefault(status, [])
        if len(status_samples) >= limit_per_status:
            continue
        status_samples.append(_candidate_status_sample(raw))
    return {status: rows for status, rows in samples.items() if rows}


def _decision_outcome_sample(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "project_id": str(row.get("project_id") or "").strip(),
        "project_name": str(row.get("project_name") or "").strip(),
        "run_id": str(row.get("run_id") or "").strip(),
        "decision": str(row.get("decision") or "").strip(),
        "hypothesis_status": str(row.get("hypothesis_status") or "").strip(),
        "evidence_strength": str(row.get("evidence_strength") or "").strip(),
        "research_outcome": str(row.get("research_outcome") or "").strip(),
        "followup_title": str(row.get("followup_title") or "").strip(),
        "problems": _problem_list(row.get("problems")),
    }


def _decision_outcome_key(row: dict[str, Any]) -> tuple[str, str]:
    return (
        str(row.get("decision") or "").strip(),
        str(row.get("hypothesis_status") or "").strip(),
    )


def _decision_outcome_samples_for_key(
    decision_scores: list[Any],
    *,
    decision: str,
    hypothesis_status: str,
    limit: int,
) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    for raw in decision_scores:
        if not isinstance(raw, dict):
            continue
        if _decision_outcome_key(raw) != (decision, hypothesis_status):
            continue
        samples.append(_decision_outcome_sample(raw))
        if len(samples) >= limit:
            break
    return samples


def _decision_outcome_samples(
    decision_counts: Any, decision_scores: Any, *, limit_per_outcome: int = 3
) -> list[dict[str, Any]]:
    if not isinstance(decision_counts, list) or not isinstance(decision_scores, list):
        return []
    rows: list[dict[str, Any]] = []
    for outcome in decision_counts:
        if not isinstance(outcome, dict):
            continue
        decision, hypothesis_status = _decision_outcome_key(outcome)
        if not decision:
            continue
        samples = _decision_outcome_samples_for_key(
            decision_scores,
            decision=decision,
            hypothesis_status=hypothesis_status,
            limit=limit_per_outcome,
        )
        if samples:
            rows.append(
                {
                    "decision": decision,
                    "hypothesis_status": hypothesis_status,
                    "samples": samples,
                }
            )
    return rows


def _quality_floor_candidate_sample(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "candidate_id": str(row.get("candidate_id") or "").strip(),
        "title": str(row.get("title") or "").strip(),
        "status": str(row.get("status") or "").strip(),
        "score": _safe_float(row.get("contract_quality_score")),
        "problems": _problem_list(row.get("problems")),
    }


def _quality_floor_decision_sample(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "project_id": str(row.get("project_id") or "").strip(),
        "project_name": str(row.get("project_name") or "").strip(),
        "run_id": str(row.get("run_id") or "").strip(),
        "decision": str(row.get("decision") or "").strip(),
        "hypothesis_status": str(row.get("hypothesis_status") or "").strip(),
        "score": _safe_float(row.get("decision_quality_score")),
        "problems": _problem_list(row.get("problems")),
    }


def _quality_floor_operator_action(
    *,
    below_floor_count: int,
    candidates_checked: int,
    decisions_checked: int,
) -> str:
    if below_floor_count > 0:
        return (
            f"review {below_floor_count} below-floor Research Quality artifacts "
            "before widening automation or treating outputs as externally useful"
        )
    return (
        f"quality floor satisfied across {candidates_checked} candidates and "
        f"{decisions_checked} decisions"
    )


def _quality_floor(
    candidate_scores: Any,
    decision_scores: Any,
    *,
    threshold: float = QUALITY_FLOOR_THRESHOLD,
) -> dict[str, Any]:
    candidates = [row for row in candidate_scores or [] if isinstance(row, dict)]
    decisions = [row for row in decision_scores or [] if isinstance(row, dict)]
    low_candidates = [
        row
        for row in candidates
        if _safe_float(row.get("contract_quality_score")) < threshold
    ]
    low_decisions = [
        row
        for row in decisions
        if _safe_float(row.get("decision_quality_score")) < threshold
    ]
    below_floor_count = len(low_candidates) + len(low_decisions)
    return {
        "available": bool(candidates or decisions),
        "threshold": threshold,
        "posture": "review_required" if below_floor_count else "satisfied",
        "candidates_checked": len(candidates),
        "decisions_checked": len(decisions),
        "candidate_below_floor_count": len(low_candidates),
        "decision_below_floor_count": len(low_decisions),
        "below_floor_count": below_floor_count,
        "candidate_samples": [
            _quality_floor_candidate_sample(row) for row in low_candidates[:3]
        ],
        "decision_samples": [
            _quality_floor_decision_sample(row) for row in low_decisions[:3]
        ],
        "operator_action": _quality_floor_operator_action(
            below_floor_count=below_floor_count,
            candidates_checked=len(candidates),
            decisions_checked=len(decisions),
        ),
    }


def _decision_posture_sample(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "project_id": str(row.get("project_id") or "").strip(),
        "project_name": str(row.get("project_name") or "").strip(),
        "run_id": str(row.get("run_id") or "").strip(),
        "decision": str(row.get("decision") or "").strip(),
        "hypothesis_status": str(row.get("hypothesis_status") or "").strip(),
        "evidence_strength": str(row.get("evidence_strength") or "").strip(),
        "research_outcome": str(row.get("research_outcome") or "").strip(),
        "bounded_paper_ready": as_bool(row.get("bounded_paper_ready")),
        "followup_recommended": as_bool(row.get("followup_recommended")),
        "followup_title": str(row.get("followup_title") or "").strip(),
        "recommended_next_action": str(
            row.get("recommended_next_action") or ""
        ).strip(),
    }


def _decision_posture_operator_action(
    *,
    decision_count: int,
    useful_signal_count: int,
    bounded_paper_ready_count: int,
) -> str:
    if decision_count <= 0:
        return "run or refresh Research Quality before judging output posture"
    if bounded_paper_ready_count > 0:
        return (
            "bounded-paper-ready decisions are present; inspect representative "
            "signals before publishing or widening automation"
        )
    if useful_signal_count > 0:
        return (
            "useful signals are present but none are bounded-paper-ready; run or "
            "review the listed follow-ups before treating this as publication output"
        )
    return (
        "no useful-signal decisions are present; treat current volume as negative "
        "or exploratory until a bounded signal appears"
    )


def _decision_publication_posture(
    *,
    decision_count: int,
    useful_signal_count: int,
    bounded_paper_ready_count: int,
    negative_count: int,
) -> str:
    if decision_count <= 0:
        return "unavailable"
    if bounded_paper_ready_count > 0:
        return "publication_ready"
    if useful_signal_count > 0:
        return "followup_only"
    if negative_count == decision_count:
        return "negative_only"
    return "no_publication_signal"


def _paper_readiness_blocker_reasons(row: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if not as_bool(row.get("bounded_paper_ready")):
        reasons.append("not_bounded_paper_ready")
    evidence = str(row.get("evidence_strength") or "").strip().lower()
    if evidence != "strong":
        reasons.append("non_strong_evidence")
    hypothesis = str(row.get("hypothesis_status") or "").strip().lower()
    if hypothesis in {"", "mixed", "unsupported", "inconclusive", "unknown"}:
        reasons.append("mixed_or_unsupported_hypothesis")
    if str(row.get("research_outcome") or "").strip() == "negative":
        reasons.append("negative_outcome")
    if as_bool(row.get("followup_recommended")):
        reasons.append("followup_required")
    if as_bool(row.get("compute_scale_blocked")):
        reasons.append("compute_scale_blocked")
    return reasons


def _paper_readiness_blocker_sample(
    row: dict[str, Any], reasons: list[str]
) -> dict[str, Any]:
    return {
        "project_id": str(row.get("project_id") or "").strip(),
        "project_name": str(row.get("project_name") or "").strip(),
        "run_id": str(row.get("run_id") or "").strip(),
        "hypothesis_status": str(row.get("hypothesis_status") or "").strip(),
        "evidence_strength": str(row.get("evidence_strength") or "").strip(),
        "research_outcome": str(row.get("research_outcome") or "").strip(),
        "bounded_paper_ready": as_bool(row.get("bounded_paper_ready")),
        "followup_recommended": as_bool(row.get("followup_recommended")),
        "followup_title": str(row.get("followup_title") or "").strip(),
        "recommended_next_action": str(
            row.get("recommended_next_action") or ""
        ).strip(),
        "blocker_reasons": reasons,
    }


def _paper_readiness_blocker_operator_action(
    *, blocker_counts: Counter[str], decision_count: int, paper_ready_count: int
) -> str:
    if decision_count <= 0:
        return "run or refresh Research Quality before judging paper readiness"
    if paper_ready_count > 0:
        return (
            "paper-ready decisions are present; inspect the samples before "
            "publication or widening automation"
        )
    if not blocker_counts:
        return "no paper-ready decisions; inspect decision rows before publication"
    dominant_reason, dominant_count = min(
        blocker_counts.items(), key=lambda item: (-item[1], item[0])
    )
    reason_labels = {
        "compute_scale_blocked": "compute-scale blocked",
        "followup_required": "follow-up required",
        "mixed_or_unsupported_hypothesis": "mixed or unsupported hypothesis",
        "negative_outcome": "negative outcome",
        "non_strong_evidence": "non-strong evidence",
        "not_bounded_paper_ready": "not bounded-paper-ready",
    }
    label = reason_labels.get(dominant_reason, dominant_reason.replace("_", " "))
    return (
        f"no paper-ready decisions; dominant blocker is {label} across "
        f"{dominant_count} decisions"
    )


def _paper_readiness_blockers(rows: list[dict[str, Any]]) -> dict[str, Any]:
    decision_count = len(rows)
    if decision_count <= 0:
        return {
            "available": False,
            "decisions_checked": 0,
            "paper_ready_count": 0,
            "blocker_counts": {},
            "samples": [],
            "operator_action": _paper_readiness_blocker_operator_action(
                blocker_counts=Counter(), decision_count=0, paper_ready_count=0
            ),
        }
    blocker_counts: Counter[str] = Counter()
    paper_ready_count = 0
    samples: list[dict[str, Any]] = []
    for row in rows:
        if as_bool(row.get("bounded_paper_ready")):
            paper_ready_count += 1
        reasons = _paper_readiness_blocker_reasons(row)
        blocker_counts.update(reasons)
        if reasons and len(samples) < 3:
            samples.append(_paper_readiness_blocker_sample(row, reasons))
    return {
        "available": True,
        "decisions_checked": decision_count,
        "paper_ready_count": paper_ready_count,
        "blocker_counts": dict(sorted(blocker_counts.items())),
        "samples": samples,
        "operator_action": _paper_readiness_blocker_operator_action(
            blocker_counts=blocker_counts,
            decision_count=decision_count,
            paper_ready_count=paper_ready_count,
        ),
    }


def _decision_posture_field_counts(
    rows: list[dict[str, Any]],
) -> tuple[Counter[str], Counter[str], Counter[str], Counter[str]]:
    outcome_counts: Counter[str] = Counter()
    hypothesis_counts: Counter[str] = Counter()
    evidence_counts: Counter[str] = Counter()
    decision_counts: Counter[str] = Counter()
    for row in rows:
        decision = str(row.get("decision") or "").strip()
        hypothesis = str(row.get("hypothesis_status") or "").strip()
        evidence = str(row.get("evidence_strength") or "").strip()
        outcome = str(row.get("research_outcome") or "").strip()
        if outcome:
            outcome_counts[outcome] += 1
        if hypothesis:
            hypothesis_counts[hypothesis] += 1
        if evidence:
            evidence_counts[evidence] += 1
        if decision:
            decision_counts[f"{decision}:{hypothesis or 'unknown'}"] += 1
    return outcome_counts, hypothesis_counts, evidence_counts, decision_counts


def _decision_posture_scalar_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "useful_signal_count": sum(
            1
            for row in rows
            if str(row.get("research_outcome") or "").strip() == "useful_signal"
        ),
        "negative_count": sum(
            1
            for row in rows
            if str(row.get("research_outcome") or "").strip() == "negative"
        ),
        "bounded_paper_ready_count": sum(
            1 for row in rows if as_bool(row.get("bounded_paper_ready"))
        ),
        "followup_recommended_count": sum(
            1 for row in rows if as_bool(row.get("followup_recommended"))
        ),
        "compute_scale_blocked_count": sum(
            1 for row in rows if as_bool(row.get("compute_scale_blocked"))
        ),
    }


def _decision_posture_useful_samples(
    rows: list[dict[str, Any]], *, limit: int = 3
) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    for row in rows:
        if str(row.get("research_outcome") or "").strip() != "useful_signal":
            continue
        samples.append(_decision_posture_sample(row))
        if len(samples) >= limit:
            break
    return samples


def _decision_posture(decision_scores: Any) -> dict[str, Any]:
    if not isinstance(decision_scores, list):
        return {
            "available": False,
            "decisions_checked": 0,
            "publication_posture": "unavailable",
            "operator_action": _decision_posture_operator_action(
                decision_count=0,
                useful_signal_count=0,
                bounded_paper_ready_count=0,
            ),
        }
    rows = [row for row in decision_scores if isinstance(row, dict)]
    outcome_counts, hypothesis_counts, evidence_counts, decision_counts = (
        _decision_posture_field_counts(rows)
    )
    scalar_counts = _decision_posture_scalar_counts(rows)
    decision_count = len(rows)
    return {
        "available": decision_count > 0,
        "decisions_checked": decision_count,
        **scalar_counts,
        "publication_posture": _decision_publication_posture(
            decision_count=decision_count,
            useful_signal_count=scalar_counts["useful_signal_count"],
            bounded_paper_ready_count=scalar_counts["bounded_paper_ready_count"],
            negative_count=scalar_counts["negative_count"],
        ),
        "research_outcome_counts": dict(sorted(outcome_counts.items())),
        "hypothesis_status_counts": dict(sorted(hypothesis_counts.items())),
        "evidence_strength_counts": dict(sorted(evidence_counts.items())),
        "decision_counts": dict(sorted(decision_counts.items())),
        "paper_readiness_blockers": _paper_readiness_blockers(rows),
        "representative_useful_signals": _decision_posture_useful_samples(rows),
        "operator_action": _decision_posture_operator_action(
            decision_count=decision_count,
            useful_signal_count=scalar_counts["useful_signal_count"],
            bounded_paper_ready_count=scalar_counts["bounded_paper_ready_count"],
        ),
    }


def _followup_required_evidence_count(row: dict[str, Any]) -> int:
    explicit_count = row.get("followup_required_evidence_count")
    if explicit_count not in (None, ""):
        try:
            return int(explicit_count)
        except (TypeError, ValueError):
            pass
    evidence = row.get("followup_required_evidence")
    if isinstance(evidence, list):
        return len([item for item in evidence if str(item or "").strip()])
    if isinstance(evidence, str):
        return len([item for item in evidence.splitlines() if item.strip()])
    return 0


def _followup_readiness_sample(
    row: dict[str, Any], *, missing_fields: list[str] | None = None
) -> dict[str, Any]:
    sample = {
        "project_id": str(row.get("project_id") or "").strip(),
        "project_name": str(row.get("project_name") or "").strip(),
        "run_id": str(row.get("run_id") or "").strip(),
        "followup_type": str(row.get("followup_type") or "").strip(),
        "followup_title": str(row.get("followup_title") or "").strip(),
        "followup_required_evidence_count": _followup_required_evidence_count(row),
        "followup_success_threshold": str(
            row.get("followup_success_threshold") or ""
        ).strip(),
        "followup_stop_condition": str(
            row.get("followup_stop_condition") or ""
        ).strip(),
        "recommended_next_action": str(
            row.get("recommended_next_action") or ""
        ).strip(),
    }
    if missing_fields is not None:
        sample["missing_fields"] = missing_fields
    return sample


def _score_followup_hypothesis(row: dict[str, Any]) -> tuple[int, str]:
    hypothesis_status = str(row.get("hypothesis_status") or "").strip().lower()
    if hypothesis_status in {"supported", "confirmed", "supportive"}:
        return 40, "supported_hypothesis"
    if hypothesis_status in {"mixed", "inconclusive_but_useful"}:
        return 25, "mixed_hypothesis"
    if hypothesis_status in {"unsupported", "negative"}:
        return 0, "unsupported_hypothesis"
    return 10, "unknown_hypothesis"


def _score_followup_evidence(row: dict[str, Any]) -> tuple[int, str]:
    evidence_strength = str(row.get("evidence_strength") or "").strip().lower()
    if evidence_strength in {"strong", "high"}:
        return 30, "strong_evidence"
    if evidence_strength in {"moderate", "medium"}:
        return 20, "moderate_evidence"
    if evidence_strength in {"weak", "low"}:
        return 5, "weak_evidence"
    return 0, "unknown_evidence"


def _score_followup_type(row: dict[str, Any]) -> tuple[int, str]:
    followup_type = str(row.get("followup_type") or "").strip().lower()
    if followup_type == "branch":
        return 10, "branch_followup"
    if followup_type == "deepen":
        return 8, "deepen_followup"
    if followup_type == "retry":
        return 5, "retry_followup"
    if followup_type:
        return 0, f"{followup_type}_followup"
    return 0, "unknown_followup_type"


def _score_followup_required_evidence(row: dict[str, Any]) -> tuple[int, list[str]]:
    evidence_count = _followup_required_evidence_count(row)
    if evidence_count <= 0:
        return 0, []
    return min(12, evidence_count * 3), [f"{evidence_count}_required_evidence_items"]


def _score_followup_bounds(row: dict[str, Any]) -> tuple[int, list[str]]:
    has_success = bool(str(row.get("followup_success_threshold") or "").strip())
    has_stop = bool(str(row.get("followup_stop_condition") or "").strip())
    if not (has_success and has_stop):
        return 0, []
    return 10, ["explicit_success_and_stop_bounds"]


def _followup_priority_components(row: dict[str, Any]) -> tuple[int, list[str]]:
    scored_reasons = [
        _score_followup_hypothesis(row),
        _score_followup_evidence(row),
        _score_followup_type(row),
    ]
    score = sum(value for value, _reason in scored_reasons)
    reasons = [reason for _value, reason in scored_reasons]
    evidence_score, evidence_reasons = _score_followup_required_evidence(row)
    bounds_score, bounds_reasons = _score_followup_bounds(row)
    score += evidence_score + bounds_score
    reasons.extend(evidence_reasons)
    reasons.extend(bounds_reasons)
    return score, reasons


def _prioritized_followup_sample(row: dict[str, Any]) -> dict[str, Any]:
    score, reasons = _followup_priority_components(row)
    sample = _followup_readiness_sample(row)
    sample.update(
        {
            "hypothesis_status": str(row.get("hypothesis_status") or "").strip(),
            "evidence_strength": str(row.get("evidence_strength") or "").strip(),
            "priority_score": min(100, score),
            "priority_reasons": reasons,
        }
    )
    return sample


def _followup_priority_key(row: dict[str, Any]) -> tuple[int, str, str, str]:
    score, _ = _followup_priority_components(row)
    return (
        -min(100, score),
        str(row.get("project_id") or ""),
        str(row.get("run_id") or ""),
        str(row.get("followup_title") or ""),
    )


def _followup_readiness_operator_action(
    *, recommended_count: int, underspecified_count: int
) -> str:
    if recommended_count <= 0:
        return (
            "no follow-up recommendations are present; inspect decision posture "
            "before queueing more work"
        )
    if underspecified_count == 1:
        return (
            "1 recommended follow-up is underspecified; fill missing readiness "
            "fields before queueing it"
        )
    if underspecified_count > 1:
        return (
            f"{underspecified_count} recommended follow-ups are underspecified; "
            "fill missing readiness fields before queueing them"
        )
    return (
        "bounded follow-ups are ready; select representative follow-up work before "
        "treating useful-signal volume as publication output"
    )


def _followup_missing_fields(row: dict[str, Any]) -> list[str]:
    missing_fields: list[str] = []
    if not str(row.get("followup_title") or "").strip():
        missing_fields.append("missing_title")
    if not str(row.get("followup_success_threshold") or "").strip():
        missing_fields.append("missing_success_threshold")
    if not str(row.get("followup_stop_condition") or "").strip():
        missing_fields.append("missing_stop_condition")
    if _followup_required_evidence_count(row) < 2:
        missing_fields.append("thin_required_evidence")
    return missing_fields


def _followup_readiness_rows(decision_scores: list[Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in decision_scores:
        if not isinstance(row, dict) or not as_bool(row.get("followup_recommended")):
            continue
        followup_type = str(row.get("followup_type") or "unknown").strip() or "unknown"
        rows.append(
            {
                "row": row,
                "followup_type": followup_type,
                "missing_fields": _followup_missing_fields(row),
            }
        )
    return rows


def _followup_readiness_missing_counts(
    readiness_rows: list[dict[str, Any]],
) -> dict[str, int]:
    counts = Counter(
        field for item in readiness_rows for field in item.get("missing_fields", [])
    )
    return {
        "missing_title_count": counts["missing_title"],
        "missing_success_threshold_count": counts["missing_success_threshold"],
        "missing_stop_condition_count": counts["missing_stop_condition"],
        "thin_required_evidence_count": counts["thin_required_evidence"],
    }


def _followup_readiness(decision_scores: Any) -> dict[str, Any]:
    empty = {
        "available": False,
        "recommended_count": 0,
        "bounded_ready_count": 0,
        "underspecified_count": 0,
        "missing_title_count": 0,
        "missing_success_threshold_count": 0,
        "missing_stop_condition_count": 0,
        "thin_required_evidence_count": 0,
        "followup_type_counts": {},
        "ready_followups": [],
        "prioritized_followups": [],
        "underspecified_followups": [],
        "operator_action": _followup_readiness_operator_action(
            recommended_count=0,
            underspecified_count=0,
        ),
    }
    if not isinstance(decision_scores, list):
        return empty
    readiness_rows = _followup_readiness_rows(decision_scores)
    ready_items = [item for item in readiness_rows if not item["missing_fields"]]
    underspecified_items = [item for item in readiness_rows if item["missing_fields"]]
    ready_rows = [item["row"] for item in ready_items]
    type_counts = Counter(item["followup_type"] for item in readiness_rows)
    missing_counts = _followup_readiness_missing_counts(readiness_rows)
    recommended_count = len(readiness_rows)
    bounded_ready_count = len(ready_items)
    underspecified_count = recommended_count - bounded_ready_count
    return {
        "available": recommended_count > 0,
        "recommended_count": recommended_count,
        "bounded_ready_count": bounded_ready_count,
        "underspecified_count": underspecified_count,
        **missing_counts,
        "followup_type_counts": dict(sorted(type_counts.items())),
        "ready_followups": [
            _followup_readiness_sample(item["row"]) for item in ready_items[:3]
        ],
        "prioritized_followups": [
            _prioritized_followup_sample(row)
            for row in sorted(ready_rows, key=_followup_priority_key)[:3]
        ],
        "underspecified_followups": [
            _followup_readiness_sample(
                item["row"], missing_fields=item["missing_fields"]
            )
            for item in underspecified_items[:3]
        ],
        "operator_action": _followup_readiness_operator_action(
            recommended_count=recommended_count,
            underspecified_count=underspecified_count,
        ),
    }


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
        "candidate_status_counts": _summary_count_mapping(
            summary.get("candidate_status_counts")
        ),
        "decision_outcome_counts": _summary_count_rows(
            summary.get("decision_counts"),
            required_label="decision",
            optional_label="hypothesis_status",
        ),
        "top_candidate_categories": _summary_count_rows(
            summary.get("top_candidate_categories"),
            required_label="category",
        ),
        "candidate_status_samples": _candidate_status_samples(
            report.get("candidate_scores")
        ),
        "decision_outcome_samples": _decision_outcome_samples(
            summary.get("decision_counts"),
            report.get("decision_scores"),
        ),
        "quality_floor": _quality_floor(
            report.get("candidate_scores"), report.get("decision_scores")
        ),
        "decision_posture": _decision_posture(report.get("decision_scores")),
        "followup_readiness": _followup_readiness(report.get("decision_scores")),
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
    row = {
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
    for key in ("trace_id", "run_cycle_id"):
        value = str(item.get(key) or "")
        if value:
            row[key] = value
    return row


def _provider_generation_clean_operator_action() -> str:
    return (
        "provider generation is currently clean; keep monitoring before widening "
        "automation"
    )


def _provider_generation_tick(item: dict[str, Any] | None) -> dict[str, Any]:
    if not item:
        return {}
    malformed_count = _safe_int(item.get("malformed_provider_response_count"))
    status = "malformed" if malformed_count > 0 else "clean"
    row = {
        "checked_at": _autopilot_history_item_timestamp(item),
        "recorded_at": str(item.get("recorded_at") or ""),
        "provider_model": str(item.get("provider_model") or ""),
        "malformed_provider_response_count": malformed_count,
        "initial_promotable_count": _safe_int(item.get("initial_promotable_count")),
        "generated_count": _safe_int(item.get("generated_count")),
        "promoted_count": _safe_int(item.get("promoted_count")),
        "dispatched_count": _safe_int(item.get("dispatched_count")),
        "reason": str(item.get("reason") or ""),
        "status": status,
        "operator_action": _malformed_provider_operator_action()
        if status == "malformed"
        else _provider_generation_clean_operator_action(),
    }
    for key in ("trace_id", "run_cycle_id"):
        value = str(item.get(key) or "")
        if value:
            row[key] = value
    return row


def _consecutive_provider_zero_count(rows: list[dict[str, Any]], field: str) -> int:
    count = 0
    for item in reversed(rows):
        if _safe_int(item.get(field)) > 0:
            break
        count += 1
    return count


def _provider_generation_latest_yield_status(
    latest_tick: dict[str, Any],
) -> str:
    generated = _safe_int(latest_tick.get("generated_count"))
    promoted = _safe_int(latest_tick.get("promoted_count"))
    initial_promotable = _safe_int(latest_tick.get("initial_promotable_count"))
    if generated > 0 or promoted > 0:
        return "yielding"
    if initial_promotable > 0:
        return "backlog_satisfied"
    return "zero_yield"


def _provider_generation_yield_operator_action(
    latest_tick: dict[str, Any], *, latest_yield_status: str
) -> str:
    generated = _safe_int(latest_tick.get("generated_count"))
    promoted = _safe_int(latest_tick.get("promoted_count"))
    initial_promotable = _safe_int(latest_tick.get("initial_promotable_count"))
    if latest_yield_status == "yielding":
        return (
            f"provider generation yielded {generated} candidate(s) and promoted "
            f"{promoted}; use yield counts alongside malformed-output recovery"
        )
    if latest_yield_status == "backlog_satisfied":
        return (
            "fresh provider generation is not yielding new candidates because "
            f"{initial_promotable} promotable candidate(s) were already available; "
            "monitor yield before treating provider health as idea volume"
        )
    return (
        "latest provider tick produced no generated or promoted candidates; "
        "inspect provider budget, backlog, and model responses before trusting "
        "idea volume"
    )


def _provider_generation_health_operator_action(
    *,
    rows_checked: int,
    consecutive_clean_ticks: int,
    last_malformed: dict[str, Any] | None,
) -> str:
    if rows_checked <= 0:
        return "inspect provider-generation history before trusting new idea volume"
    if consecutive_clean_ticks <= 0:
        return (
            "provider generation is currently malformed; inspect latest provider "
            "output before trusting new idea volume"
        )
    if last_malformed:
        tick_label = "tick" if consecutive_clean_ticks == 1 else "ticks"
        return (
            f"provider generation has {consecutive_clean_ticks} clean {tick_label} "
            "since the last malformed response; review the last malformed model "
            "before widening automation"
        )
    tick_label = "tick" if consecutive_clean_ticks == 1 else "ticks"
    return (
        f"provider generation is clean across {consecutive_clean_ticks} recent "
        f"{tick_label}; keep monitoring before widening automation"
    )


def _provider_generation_health(
    *,
    rows: list[dict[str, Any]],
    malformed_rows: list[dict[str, Any]],
    model_counts: Counter[str],
) -> dict[str, Any]:
    consecutive_clean_ticks = 0
    for item in reversed(rows):
        if _safe_int(item.get("malformed_provider_response_count")) > 0:
            break
        consecutive_clean_ticks += 1
    last_row = rows[-1] if rows else None
    last_malformed = malformed_rows[-1] if malformed_rows else None
    latest_tick = _provider_generation_tick(last_row)
    latest_yield_status = _provider_generation_latest_yield_status(latest_tick)
    return {
        "available": True,
        "rows_checked": len(rows),
        "malformed_provider_response_count": sum(
            _safe_int(item.get("malformed_provider_response_count")) for item in rows
        ),
        "malformed_provider_response_ticks": len(malformed_rows),
        "clean_tick_count": sum(
            1
            for item in rows
            if _safe_int(item.get("malformed_provider_response_count")) == 0
        ),
        "consecutive_clean_ticks": consecutive_clean_ticks,
        "last_checked_at": _autopilot_history_item_timestamp(last_row)
        if last_row
        else "",
        "last_malformed_at": _autopilot_history_item_timestamp(last_malformed)
        if last_malformed
        else "",
        "malformed_provider_model_counts": dict(sorted(model_counts.items())),
        "latest_tick": latest_tick,
        "last_malformed_tick": _provider_generation_tick(last_malformed),
        "consecutive_zero_generated_ticks": _consecutive_provider_zero_count(
            rows, "generated_count"
        ),
        "consecutive_zero_promoted_ticks": _consecutive_provider_zero_count(
            rows, "promoted_count"
        ),
        "latest_yield_status": latest_yield_status,
        "yield_operator_action": _provider_generation_yield_operator_action(
            latest_tick,
            latest_yield_status=latest_yield_status,
        ),
        "operator_action": _provider_generation_health_operator_action(
            rows_checked=len(rows),
            consecutive_clean_ticks=consecutive_clean_ticks,
            last_malformed=last_malformed,
        ),
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
        "provider_generation_health": _provider_generation_health(
            rows=rows, malformed_rows=malformed_rows, model_counts=model_counts
        ),
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


def _window_eval_case_sample(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "case_id": str(item.get("case_id") or ""),
        "case_type": str(item.get("case_type") or ""),
        "severity": str(item.get("severity") or ""),
        "title": str(item.get("title") or ""),
        "project_id": str(item.get("project_id") or ""),
        "project_name": str(item.get("project_name") or ""),
        "run_id": str(item.get("run_id") or ""),
        "followup_title": str(item.get("followup_title") or ""),
        "followup_depth": _safe_int(item.get("followup_depth")),
        "expected_behavior": str(item.get("expected_behavior") or ""),
    }


def _window_eval_case_samples(
    window: dict[str, Any], side: str, case_type: str, *, limit: int = 3
) -> list[dict[str, Any]]:
    samples = window.get("eval_case_samples") or {}
    side_samples = samples.get(side) if isinstance(samples, dict) else {}
    case_samples = side_samples.get(case_type) if isinstance(side_samples, dict) else []
    rows: list[dict[str, Any]] = []
    for item in case_samples or []:
        if isinstance(item, dict):
            rows.append(_window_eval_case_sample(item))
        if len(rows) >= limit:
            break
    return rows


def _window_count_mapping(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    counts: dict[str, int] = {}
    for key, count in value.items():
        label = str(key or "")
        if label:
            counts[label] = _safe_int(count)
    return counts


def _window_delta_mapping(value: Any) -> dict[str, float]:
    if not isinstance(value, dict):
        return {}
    deltas: dict[str, float] = {}
    for key, delta in value.items():
        label = str(key or "")
        if label:
            deltas[label] = _safe_float(delta)
    return deltas


def _window_side_summary(value: Any) -> dict[str, Any]:
    side = value if isinstance(value, dict) else {}
    return {
        "candidate_count": _safe_int(side.get("candidate_count")),
        "decision_count": _safe_int(side.get("decision_count")),
        "admitted_rate": _safe_float(side.get("admitted_rate")),
        "avg_total_score": _safe_float(side.get("avg_total_score")),
        "status_counts": _window_count_mapping(side.get("status_counts")),
        "category_counts": _window_count_mapping(side.get("category_counts")),
        "generation_mode_counts": _window_count_mapping(
            side.get("generation_mode_counts")
        ),
        "eval_case_counts": _window_count_mapping(side.get("eval_case_counts")),
        "high_similarity_pair_count": _safe_int(side.get("high_similarity_pair_count")),
    }


def _window_comparison_summary(window: dict[str, Any]) -> dict[str, Any]:
    return {
        "cutoff": str(window.get("cutoff") or ""),
        "limit": _safe_int(window.get("limit")),
        "delta": _window_delta_mapping(window.get("delta")),
        "current": _window_side_summary(window.get("post")),
        "previous": _window_side_summary(window.get("pre")),
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
    useful_delta = _safe_float(delta.get("useful_adjacent_followup_delta"))
    return {
        "available": True,
        "window_path": window_path,
        "cutoff": cutoff,
        "window_comparison": _window_comparison_summary(window),
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
        "useful_adjacent_followup_delta": useful_delta,
        "useful_adjacent_followup_evidence": {
            "current": _window_eval_case_samples(
                window, "post", "useful_adjacent_followup"
            ),
            "previous": _window_eval_case_samples(
                window, "pre", "useful_adjacent_followup"
            ),
            "delta": useful_delta,
        },
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
        "provider_generation_health": history.get("provider_generation_health") or {},
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
