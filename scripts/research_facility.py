#!/usr/bin/env python3
"""Deterministic Research Facility candidate admission planner.

This is the non-provider core for Enoch idea generation. It does not call LLMs,
browse the web, or dispatch work. It validates generated candidates, scores the
operator contract, and can emit auditable SQL for the four Research Facility
ledgers plus optional admitted idea/project/queue rows.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from enoch_control_plane.timeutils import parse_utc_datetime

GENERATION_MODES = {
    "fresh_grounded",
    "followup_from_negative",
    "moonshot",
    "implementation_gap",
    "paper_replication_extension",
    "home_hardware_accessibility",
    "manual_import",
}

CANDIDATE_STATUSES = {
    "generated",
    "rejected",
    "admitted",
    "merged",
    "needs_review",
    "rewrite_needed",
    "deferred",
    "deferred_pending_oracle",
    "superseded",
}
REQUIRED_TEXT_FIELDS = (
    "title",
    "hypothesis",
    "mechanism",
    "baseline_to_beat",
    "success_threshold",
    "kill_condition",
    "accessibility_delta",
)
REQUIRED_ARRAY_FIELDS = (
    "expected_artifacts",
    "required_evidence",
    "likely_failure_modes",
)
SHALLOW_INCREMENT_PATTERNS = (
    r"\+\s*0\.0?5\s*%",
    r"tiny\s+parameter\s+tweak",
    r"just\s+try\s+different\s+(?:batch|learning rate|temperature|rank)",
    r"minor\s+hyperparameter",
)
DEFAULT_ARTIFACTS = [
    "run_notes.md",
    "metrics.json",
    "failure_cases.json",
    ".enoch/project_decision.json",
]
DEFAULT_EVIDENCE = [
    "baseline comparison",
    "metrics table",
    "failure cases",
    "decision artifact",
]
RUNTIME_CLASSES = {"", "small", "medium", "large", "overnight"}
TOKEN_BUDGETS = {"", "small", "medium", "large"}


def _parse_datetime(value: Any) -> datetime | None:
    text = _as_text(value)
    if not text:
        return None
    return parse_utc_datetime(text)


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _as_list(value: Any) -> list[Any]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        items: list[Any] = []
        for item in value:
            if not isinstance(item, str):
                if _as_text(item):
                    items.append(item)
                continue
            text = _as_text(item)
            if not text:
                continue
            items.extend(_split_numbered_list_text(text))
        return items
    return _split_numbered_list_text(_as_text(value))


def _split_numbered_list_text(value: str) -> list[str]:
    text = _as_text(value)
    if not text:
        return []
    markers = list(re.finditer(r"(?<!\S)\d+\.\s+", text))
    if len(markers) < 2:
        return [text]
    items: list[str] = []
    for index, marker in enumerate(markers):
        start = marker.end()
        end = markers[index + 1].start() if index + 1 < len(markers) else len(text)
        item = text[start:end].strip()
        if item:
            items.append(item)
    return items


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _bounded_score(value: Any) -> float:
    text = _as_text(value)
    from_fraction = False
    if "/" in text:
        left, _, right = text.partition("/")
        try:
            numerator = float(left.strip())
            denominator = float(right.strip())
        except ValueError:
            score = _as_float(value)
        else:
            from_fraction = True
            if denominator > 0:
                score = (
                    numerator if denominator == 10 else (numerator / denominator) * 10.0
                )
            else:
                score = 0.0
    else:
        score = _as_float(value)
    if not from_fraction and 0.0 < score <= 1.0:
        score *= 10.0
    return max(0.0, min(10.0, score))


def _runtime_class(value: Any) -> str:
    text = _as_text(value).lower()
    if text in RUNTIME_CLASSES:
        return text
    if any(term in text for term in ("overnight", "day", "days", "48", "24h", "long")):
        return "overnight"
    if any(term in text for term in ("large", "slow")):
        return "large"
    if any(term in text for term in ("small", "fast", "short", "hour")):
        return "small"
    if text:
        return "medium"
    return ""


def _token_budget(value: Any) -> str:
    text = _as_text(value).lower()
    if text in TOKEN_BUDGETS:
        return text
    if any(term in text for term in ("large", "million", "1m", "500k", "250k")):
        return "large"
    if any(term in text for term in ("small", "50k", "25k", "10k")):
        return "small"
    if text:
        return "medium"
    return ""


_RUNTIME_PENALTY_BY_CLASS = {
    "": 0.0,
    "small": 0.0,
    "medium": 1.0,
    "large": 3.0,
    "overnight": 5.0,
}

_TARGETED_SOURCE_HOSTS = ("github.com/", "dspy.ai/", "docs.vllm.ai/")


def _dispatch_lineage_bonus(
    *,
    mode: str,
    parent_project_id: str,
    parent_run_id: str,
    falsifiability_score: float,
) -> float:
    if mode == "followup_from_negative" or parent_project_id or parent_run_id:
        return 8.0
    if mode == "paper_replication_extension":
        return 5.0
    if mode == "implementation_gap":
        return 3.0
    if mode == "home_hardware_accessibility":
        return 2.0
    if mode == "moonshot":
        return 2.0 if falsifiability_score >= 7.0 else -6.0
    return 0.0


def _dispatch_targeted_source_bonus(
    *, source_kind: str, source_urls: list[str]
) -> float:
    bonus = 0.0
    if source_kind == "arxiv" or any("arxiv.org/abs/" in url for url in source_urls):
        bonus += 4.0
    if any(host in url for url in source_urls for host in _TARGETED_SOURCE_HOSTS):
        bonus += 1.5
    return bonus


def _dispatch_age_bonus(
    *, created: datetime | None, now_dt: datetime
) -> tuple[float, float]:
    if created is None:
        return 0.0, 0.0
    age_days = max(0.0, (now_dt - created).total_seconds() / 86400.0)
    return age_days, min(5.0, age_days * 0.25)


def _dispatch_saturation_penalty(
    *, category: str, category_counts: dict[str, int] | None
) -> tuple[float, int]:
    category_count = int((category_counts or {}).get(category, 0) or 0)
    if category_count <= 8:
        return 0.0, category_count
    return min(8.0, (category_count - 8) * 0.5), category_count


def _dispatch_duplicate_penalty(
    *, similar_prior: list[Any], novelty_comparison: str
) -> float:
    if not similar_prior:
        return 0.0
    penalty = 4.0
    if not novelty_comparison:
        penalty += 4.0
    return penalty


def _dispatch_runtime_penalty(*, runtime_class: str, token_budget: str) -> float:
    penalty = _RUNTIME_PENALTY_BY_CLASS.get(runtime_class, 1.0)
    if token_budget == "large":
        penalty += 1.0
    return penalty


def _dispatch_weak_contract_penalty(
    *,
    total_score: float,
    novelty_score: float,
    falsifiability_score: float,
) -> float:
    penalty = 0.0
    if total_score < 68.0:
        penalty += 6.0
    elif total_score < 72.0:
        penalty += 2.0
    if novelty_score and novelty_score < 7.0:
        penalty += 2.0
    if falsifiability_score and falsifiability_score < 7.0:
        penalty += 2.0
    return penalty


def dispatch_priority_breakdown(
    row: dict[str, Any],
    *,
    category_counts: dict[str, int] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return the queue-dispatch priority for an admitted candidate.

    ``total_score`` intentionally remains the admission/contract-completeness
    score. This priority score is a separate portfolio ranking signal used when
    choosing which already-admitted candidate gets promoted next. It spreads
    otherwise-close admission scores by preferring evidence-backed branches,
    targeted papers, bounded follow-ups, fresh-but-not-saturated categories, and
    older candidates that have waited long enough to avoid starvation.
    """

    now_dt = now or datetime.now(timezone.utc)
    category = _as_text(row.get("category")).lower()
    mode = _as_text(row.get("generation_mode"))
    source_kind = _as_text(row.get("source_kind")).lower()
    source_urls = [_as_text(url).lower() for url in _as_list(row.get("source_urls"))]
    similar_prior = _as_list(row.get("similar_prior_projects"))
    runtime_class = _runtime_class(row.get("estimated_runtime_class"))
    token_budget = _token_budget(row.get("expected_token_budget"))
    parent_project_id = _as_text(row.get("parent_project_id"))
    parent_run_id = _as_text(row.get("parent_run_id"))
    total_score = _as_float(row.get("total_score"))
    novelty_score = _as_float(row.get("novelty_score"))
    falsifiability_score = _as_float(row.get("falsifiability_score"))

    lineage_bonus = _dispatch_lineage_bonus(
        mode=mode,
        parent_project_id=parent_project_id,
        parent_run_id=parent_run_id,
        falsifiability_score=falsifiability_score,
    )
    targeted_source_bonus = _dispatch_targeted_source_bonus(
        source_kind=source_kind, source_urls=source_urls
    )
    created = _parse_datetime(row.get("created_at") or row.get("updated_at"))
    age_days, age_bonus = _dispatch_age_bonus(created=created, now_dt=now_dt)
    saturation_penalty, category_count = _dispatch_saturation_penalty(
        category=category, category_counts=category_counts
    )
    duplicate_penalty = _dispatch_duplicate_penalty(
        similar_prior=similar_prior,
        novelty_comparison=_as_text(row.get("novelty_comparison")),
    )
    runtime_penalty = _dispatch_runtime_penalty(
        runtime_class=runtime_class, token_budget=token_budget
    )
    weak_contract_penalty = _dispatch_weak_contract_penalty(
        total_score=total_score,
        novelty_score=novelty_score,
        falsifiability_score=falsifiability_score,
    )

    score = (
        total_score
        + lineage_bonus
        + targeted_source_bonus
        + age_bonus
        - saturation_penalty
        - duplicate_penalty
        - runtime_penalty
        - weak_contract_penalty
    )
    score = max(0.0, min(120.0, round(score, 2)))
    return {
        "dispatch_priority_score": score,
        "base_total_score": round(total_score, 2),
        "lineage_bonus": round(lineage_bonus, 2),
        "targeted_source_bonus": round(targeted_source_bonus, 2),
        "age_bonus": round(age_bonus, 2),
        "category_saturation_penalty": round(saturation_penalty, 2),
        "duplicate_penalty": round(duplicate_penalty, 2),
        "runtime_penalty": round(runtime_penalty, 2),
        "weak_contract_penalty": round(weak_contract_penalty, 2),
        "category_count": category_count,
        "age_days": round(age_days, 2),
        "generation_mode": mode,
        "category": category,
    }


def dispatch_priority_score(
    row: dict[str, Any],
    *,
    category_counts: dict[str, int] | None = None,
    now: datetime | None = None,
) -> float:
    return float(
        dispatch_priority_breakdown(row, category_counts=category_counts, now=now)[
            "dispatch_priority_score"
        ]
    )


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:96] or "research-candidate"


def stable_hash(value: str, length: int = 12) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


def stable_candidate_id(row: dict[str, Any]) -> str:
    if _as_text(row.get("candidate_id")):
        return _as_text(row["candidate_id"])
    title = _as_text(row.get("title"))
    basis = "\n".join(
        [
            _as_text(row.get("generation_mode")),
            title,
            _as_text(row.get("hypothesis")),
            _as_text(row.get("mechanism")),
        ]
    )
    return f"{slugify(title)}-{stable_hash(basis)}"


def stable_dedupe_key(row: dict[str, Any]) -> str:
    explicit = _as_text(row.get("dedupe_key"))
    if explicit:
        return explicit
    basis = " ".join(
        [
            _as_text(row.get("category")),
            _as_text(row.get("title")),
            _as_text(row.get("mechanism")),
            _as_text(row.get("baseline_to_beat")),
        ]
    )
    tokens = re.findall(r"[a-z0-9]+", basis.lower())
    stop = {"the", "and", "with", "for", "from", "into", "using", "that", "this"}
    kept = [token for token in tokens if token not in stop]
    return "research:" + "-".join(kept[:14]) + ":" + stable_hash(" ".join(kept))


def _json_obj(row: dict[str, Any], key: str, default: Any) -> Any:
    value = row.get(key, default)
    return default if value is None else value


def token_set(value: str) -> set[str]:
    stop = {
        "the",
        "and",
        "with",
        "for",
        "from",
        "into",
        "using",
        "that",
        "this",
        "local",
        "probe",
    }
    return {
        token
        for token in re.findall(r"[a-z0-9]+", value.lower())
        if token not in stop and len(token) > 2
    }


def jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def load_history(path: Path | None) -> list[dict[str, Any]]:
    if path is None:
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("history") or data.get("rows") or data.get("projects") or []
    return [row for row in data if isinstance(row, dict)]


def fetch_history_from_database(
    database_url: str, *, limit: int = 1000
) -> list[dict[str, Any]]:
    if not database_url:
        return []
    import psycopg
    from psycopg.rows import dict_row

    query = """
        select
          coalesce(i.idea_id, p.project_id, c.candidate_id) as project_id,
          coalesce(i.title, p.project_name, c.title, '') as title,
          coalesce(c.dedupe_key, '') as dedupe_key,
          coalesce(pd.decision_gate_state, '') as decision_gate_state,
          coalesce(pd.decision_summary, '') as decision_summary,
          coalesce(c.novelty_comparison, '') as novelty_comparison
        from enoch.projects p
        full join enoch.ideas i on i.idea_id = p.project_id
        full join enoch.research_candidates c on c.candidate_id = coalesce(i.idea_id, p.project_id)
        left join lateral (
          select decision_gate_state, decision_summary
          from enoch.project_decisions pd
          where pd.project_id = coalesce(i.idea_id, p.project_id, c.candidate_id)
          order by pd.decided_at desc, pd.decision_id desc
          limit 1
        ) pd on true
        order by coalesce(i.updated_at, p.updated_at, c.updated_at) desc nulls last
        limit %s
    """
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute("set search_path to enoch, public")
            cur.execute(query, (max(1, min(limit, 10000)),))
            return [dict(row) for row in cur.fetchall()]


def compare_history(
    row: dict[str, Any],
    history: Sequence[dict[str, Any]],
    *,
    similarity_threshold: float = 0.52,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    exact: list[dict[str, Any]] = []
    similar: list[dict[str, Any]] = []
    candidate_tokens = token_set(
        " ".join(
            [
                row.get("title", ""),
                row.get("mechanism", ""),
                row.get("baseline_to_beat", ""),
            ]
        )
    )
    for prior in history:
        prior_id = _as_text(
            prior.get("project_id") or prior.get("idea_id") or prior.get("candidate_id")
        )
        if not prior_id or prior_id == row.get("candidate_id"):
            continue
        prior_dedupe = _as_text(prior.get("dedupe_key"))
        prior_title = _as_text(prior.get("title") or prior.get("project_name"))
        prior_tokens = token_set(
            " ".join(
                [
                    prior_title,
                    _as_text(prior.get("mechanism")),
                    _as_text(prior.get("baseline_to_beat")),
                ]
            )
        )
        similarity = (
            1.0
            if prior_dedupe and prior_dedupe == row.get("dedupe_key")
            else jaccard(candidate_tokens, prior_tokens)
        )
        if similarity >= 0.98 or slugify(prior_title) == slugify(row.get("title", "")):
            exact.append(
                {
                    "project_id": prior_id,
                    "title": prior_title,
                    "decision_gate_state": _as_text(prior.get("decision_gate_state")),
                    "similarity": round(similarity, 3),
                }
            )
        elif similarity >= similarity_threshold:
            similar.append(
                {
                    "project_id": prior_id,
                    "title": prior_title,
                    "decision_gate_state": _as_text(prior.get("decision_gate_state")),
                    "similarity": round(similarity, 3),
                }
            )
    similar.sort(key=lambda item: item["similarity"], reverse=True)
    return exact, similar[:5]


@dataclass
class CandidatePlan:
    candidate: dict[str, Any]
    hard_failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    score_breakdown: dict[str, Any] = field(default_factory=dict)
    admission_decision: str = "rejected"
    admission_reason: str = ""
    admitted_idea_id: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "candidate": self.candidate,
            "hard_failures": self.hard_failures,
            "warnings": self.warnings,
            "score_breakdown": self.score_breakdown,
            "admission_decision": self.admission_decision,
            "admission_reason": self.admission_reason,
            "admitted_idea_id": self.admitted_idea_id,
        }


def normalize_candidate(
    raw: dict[str, Any],
    *,
    default_machine: str,
    default_model: str,
    default_sandbox: str,
) -> dict[str, Any]:
    row = dict(raw)
    row["candidate_id"] = stable_candidate_id(row)
    row["generation_mode"] = _as_text(
        row.get("generation_mode") or row.get("idea_type") or "manual_import"
    )
    row["status"] = _as_text(row.get("status") or "generated")
    row["title"] = _as_text(row.get("title"))
    row["category"] = _as_text(row.get("category"))
    row["priority"] = _as_text(row.get("priority"))
    row["source_kind"] = _as_text(row.get("source_kind"))
    row["source_ids"] = _as_list(row.get("source_ids"))
    row["source_urls"] = _as_list(
        row.get("source_urls")
        or ([row.get("source_external_url")] if row.get("source_external_url") else [])
    )
    row["source_records"] = _as_list(row.get("source_records"))
    row["parent_project_id"] = _as_text(row.get("parent_project_id"))
    row["parent_run_id"] = _as_text(row.get("parent_run_id"))
    for key in (
        "hypothesis",
        "mechanism",
        "description",
        "implementation",
        "baseline_to_beat",
        "success_threshold",
        "kill_condition",
        "accessibility_delta",
        "novelty_comparison",
        "risk_notes",
    ):
        row[key] = _as_text(row.get(key))
    row["expected_artifacts"] = (
        _as_list(row.get("expected_artifacts"))
        if "expected_artifacts" in row
        else DEFAULT_ARTIFACTS
    )
    row["required_evidence"] = (
        _as_list(row.get("required_evidence"))
        if "required_evidence" in row
        else DEFAULT_EVIDENCE
    )
    row["likely_failure_modes"] = _as_list(row.get("likely_failure_modes"))
    row["estimated_runtime_class"] = _runtime_class(row.get("estimated_runtime_class"))
    row["expected_token_budget"] = _token_budget(row.get("expected_token_budget"))
    row["machine_target"] = _as_text(row.get("machine_target") or default_machine)
    candidate_model = _as_text(row.get("model"))
    # Provider model IDs describe the candidate generator. They are not valid
    # Codex execution models, and dispatching them would fail the worker run
    # before any experiment starts.
    row["model"] = (
        default_model
        if (not candidate_model or candidate_model.startswith("hf:"))
        else candidate_model
    )
    row["sandbox"] = _as_text(row.get("sandbox") or default_sandbox)
    row["novelty_score"] = _bounded_score(row.get("novelty_score"))
    row["feasibility_score"] = _bounded_score(
        row.get("feasibility_score") or row.get("feasibility")
    )
    row["accessibility_score"] = _bounded_score(
        row.get("accessibility_score") or row.get("accessibility_delta_score")
    )
    row["falsifiability_score"] = _bounded_score(row.get("falsifiability_score"))
    row["dedupe_key"] = stable_dedupe_key(row)
    row["similar_prior_projects"] = _as_list(row.get("similar_prior_projects"))
    row["provider"] = _as_text(row.get("provider"))
    row["provider_model"] = _as_text(row.get("provider_model"))
    row["prompt_version"] = _as_text(row.get("prompt_version"))
    row["generated_by"] = _as_text(row.get("generated_by"))
    row["raw_candidate_json"] = _json_obj(row, "raw_candidate_json", raw)
    return row


def _collect_candidate_hard_failures(row: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    mode = row["generation_mode"]
    if mode not in GENERATION_MODES:
        failures.append(f"unsupported generation_mode: {mode}")
    if row["status"] not in CANDIDATE_STATUSES:
        failures.append(f"unsupported status: {row['status']}")
    for key in REQUIRED_TEXT_FIELDS:
        if not row[key]:
            failures.append(f"missing {key}")
    for key in REQUIRED_ARRAY_FIELDS:
        if not row[key]:
            failures.append(f"missing {key}")
    if mode == "fresh_grounded" and not row["source_ids"] and not row["source_urls"]:
        failures.append("fresh_grounded requires source_ids or source_urls")
    if (
        mode == "followup_from_negative"
        and not row["parent_project_id"]
        and not row["parent_run_id"]
    ):
        failures.append(
            "followup_from_negative requires parent_project_id or parent_run_id"
        )
    if row["similar_prior_projects"] and not row["novelty_comparison"]:
        failures.append("similar_prior_projects requires novelty_comparison")
    text = "\n".join(
        [
            row["title"],
            row["hypothesis"],
            row["mechanism"],
            row["implementation"],
            row["risk_notes"],
        ]
    ).lower()
    if any(re.search(pattern, text) for pattern in SHALLOW_INCREMENT_PATTERNS):
        failures.append("candidate looks like shallow incremental sludge")
    return failures


def _resolved_accessibility_score(row: dict[str, Any], accessibility: float) -> float:
    if not accessibility and row["accessibility_delta"]:
        return 5.0
    return accessibility


def _resolved_falsifiability_score(row: dict[str, Any], falsifiability: float) -> float:
    if not falsifiability and row["success_threshold"] and row["kill_condition"]:
        return 6.0
    return falsifiability


def _candidate_mode_bonus(
    mode: str,
    row: dict[str, Any],
    *,
    accessibility: float,
    falsifiability: float,
) -> float:
    if mode == "moonshot":
        return 4.0 if falsifiability >= 7 else -8.0
    if mode == "home_hardware_accessibility":
        return 4.0 if accessibility >= 7 else -5.0
    if mode == "followup_from_negative":
        return 3.0 if row["novelty_comparison"] else -8.0
    return {
        "fresh_grounded": 2.0,
        "implementation_gap": 2.0,
        "paper_replication_extension": 1.0,
        "manual_import": 0.0,
    }.get(mode, 0.0)


def _compute_candidate_total_score(
    *,
    novelty: float,
    feasibility: float,
    accessibility: float,
    falsifiability: float,
    mode_bonus: float,
    hard_failure_count: int,
) -> float:
    missing_field_penalty = 6.0 * hard_failure_count
    total = (
        (novelty * 2.6)
        + (feasibility * 1.7)
        + (accessibility * 2.5)
        + (falsifiability * 2.2)
        + mode_bonus
        - missing_field_penalty
    )
    return max(0.0, min(100.0, round(total, 2)))


def _build_candidate_score_breakdown(
    *,
    novelty: float,
    feasibility: float,
    accessibility: float,
    falsifiability: float,
    mode_bonus: float,
    missing_field_penalty: float,
    admit_threshold: float,
    review_threshold: float,
) -> dict[str, float]:
    return {
        "novelty_weighted": round(novelty * 2.6, 2),
        "feasibility_weighted": round(feasibility * 1.7, 2),
        "accessibility_weighted": round(accessibility * 2.5, 2),
        "falsifiability_weighted": round(falsifiability * 2.2, 2),
        "mode_bonus": mode_bonus,
        "hard_failure_penalty": missing_field_penalty,
        "admit_threshold": admit_threshold,
        "review_threshold": review_threshold,
    }


def _apply_candidate_admission(
    plan: CandidatePlan,
    row: dict[str, Any],
    total: float,
    *,
    admit_threshold: float,
    review_threshold: float,
) -> None:
    if plan.hard_failures:
        plan.admission_decision = "rejected"
        plan.admission_reason = "; ".join(plan.hard_failures)
        return
    if total >= admit_threshold:
        plan.admission_decision = "admitted"
        plan.admission_reason = (
            f"score {total} >= admit threshold {admit_threshold} "
            "with required research contract present"
        )
        plan.admitted_idea_id = row["candidate_id"]
        return
    if total >= review_threshold:
        plan.admission_decision = "needs_review"
        plan.admission_reason = (
            f"score {total} below admit threshold {admit_threshold} "
            f"but above review threshold {review_threshold}"
        )
        return
    plan.admission_decision = "rejected"
    plan.admission_reason = f"score {total} below review threshold {review_threshold}"


def _status_for_admission_decision(decision: str) -> str:
    if decision == "admitted":
        return "admitted"
    if decision == "needs_review":
        return "needs_review"
    return "rejected"


def evaluate_candidate(
    row: dict[str, Any],
    *,
    admit_threshold: float = 72.0,
    review_threshold: float = 58.0,
) -> CandidatePlan:
    plan = CandidatePlan(candidate=row)
    mode = row["generation_mode"]
    plan.hard_failures = _collect_candidate_hard_failures(row)

    novelty = row["novelty_score"]
    feasibility = row["feasibility_score"]
    accessibility = _resolved_accessibility_score(row, row["accessibility_score"])
    falsifiability = _resolved_falsifiability_score(row, row["falsifiability_score"])
    mode_bonus = _candidate_mode_bonus(
        mode, row, accessibility=accessibility, falsifiability=falsifiability
    )
    missing_field_penalty = 6.0 * len(plan.hard_failures)
    total = _compute_candidate_total_score(
        novelty=novelty,
        feasibility=feasibility,
        accessibility=accessibility,
        falsifiability=falsifiability,
        mode_bonus=mode_bonus,
        hard_failure_count=len(plan.hard_failures),
    )
    row["accessibility_score"] = accessibility
    row["falsifiability_score"] = falsifiability
    row["total_score"] = total
    row["score_breakdown"] = _build_candidate_score_breakdown(
        novelty=novelty,
        feasibility=feasibility,
        accessibility=accessibility,
        falsifiability=falsifiability,
        mode_bonus=mode_bonus,
        missing_field_penalty=missing_field_penalty,
        admit_threshold=admit_threshold,
        review_threshold=review_threshold,
    )
    plan.score_breakdown = row["score_breakdown"] | {"total_score": total}

    _apply_candidate_admission(
        plan,
        row,
        total,
        admit_threshold=admit_threshold,
        review_threshold=review_threshold,
    )
    row["status"] = _status_for_admission_decision(plan.admission_decision)
    return plan


def load_candidates(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"```(?:json)?\s*(\[.*?\]|\{.*?\})\s*```", text, flags=re.S)
        if not match:
            match = re.search(r"(\[\s*\{.*\}\s*\])", text, flags=re.S)
        if not match:
            raise SystemExit(f"{path}: no JSON array/object found")
        data = json.loads(match.group(1))
    if isinstance(data, dict):
        if "candidates" in data:
            data = data.get("candidates") or []
        elif "ideas" in data:
            data = data.get("ideas") or []
        else:
            data = [data]
    if not isinstance(data, list):
        raise SystemExit(f"{path}: expected JSON list or object")
    return [item for item in data if isinstance(item, dict)]


def sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def sql_json(value: Any) -> str:
    return (
        sql_literal(json.dumps(value, sort_keys=True, separators=(",", ":")))
        + "::jsonb"
    )


# Indented fragments for sql_raise_if_exists guards (Sonar S1192 in emit_sql).
_SQL_GUARD_EXISTS_SELECT = "    select 1"
# Opening AND clause for identity-conflict guards (Sonar S1192 in emit_sql).
_SQL_GUARD_AND_OPEN = "      and ("


def sql_raise_if_exists(query: str, message: str) -> str:
    return "\n".join(
        [
            "do $$",
            "begin",
            "  if exists (",
            query.rstrip(),
            "  ) then",
            f"    raise exception {sql_literal(message)};",
            "  end if;",
            "end $$;",
        ]
    )


def _emit_source_record_sql(
    lines: list[str], source: dict[str, Any], candidate: dict[str, Any]
) -> None:
    source_id = _as_text(source.get("source_id")) or "source-" + stable_hash(
        _as_text(source.get("url") or source.get("title")), 24
    )
    source_kind = _as_text(
        source.get("source_kind") or candidate.get("source_kind") or "other"
    )
    lines.append(
        sql_raise_if_exists(
            "\n".join(
                [
                    _SQL_GUARD_EXISTS_SELECT,
                    "    from enoch.research_sources",
                    f"    where source_id = {sql_literal(source_id)}",
                    _SQL_GUARD_AND_OPEN,
                    f"        source_kind is distinct from {sql_literal(source_kind)}",
                    f"        or url is distinct from {sql_literal(_as_text(source.get('url')))}",
                    f"        or external_id is distinct from {sql_literal(_as_text(source.get('external_id')))}",
                    "      )",
                ]
            ),
            "conflicting research source identity",
        )
    )
    lines.append(
        "insert into enoch.research_sources(source_id, source_kind, title, url, external_id, retrieved_at, summary, payload_json, content_hash) values "
        f"({sql_literal(source_id)}, {sql_literal(source_kind)}, {sql_literal(_as_text(source.get('title') or candidate['title']))}, {sql_literal(_as_text(source.get('url')))}, {sql_literal(_as_text(source.get('external_id')))}, "
        f"nullif({sql_literal(_as_text(source.get('retrieved_at')))}, '')::timestamptz, {sql_literal(_as_text(source.get('summary')))}, {sql_json(source.get('payload_json') or {})}, {sql_literal(_as_text(source.get('content_hash')) or stable_hash(json.dumps(source, sort_keys=True), 64))}) "
        "on conflict (source_id) do update set title = excluded.title, url = excluded.url, summary = excluded.summary, payload_json = excluded.payload_json, content_hash = excluded.content_hash, updated_at = now();"
    )


def _emit_url_source_sql(lines: list[str], url: Any, candidate: dict[str, Any]) -> None:
    source_id = "url-" + stable_hash(_as_text(url), 24)
    lines.append(
        sql_raise_if_exists(
            "\n".join(
                [
                    _SQL_GUARD_EXISTS_SELECT,
                    "    from enoch.research_sources",
                    f"    where source_id = {sql_literal(source_id)}",
                    _SQL_GUARD_AND_OPEN,
                    f"        url is distinct from {sql_literal(_as_text(url))}",
                    "      )",
                ]
            ),
            "conflicting research source identity",
        )
    )
    lines.append(
        "insert into enoch.research_sources(source_id, source_kind, title, url, content_hash, payload_json) values "
        f"({sql_literal(source_id)}, {sql_literal(candidate['source_kind'] or 'other')}, {sql_literal(candidate['title'])}, {sql_literal(_as_text(url))}, {sql_literal(stable_hash(_as_text(url), 64))}, {sql_json({'url': _as_text(url)})}) "
        "on conflict (source_id) do update set title = excluded.title, url = excluded.url, updated_at = now();"
    )


def _emit_candidate_sql(
    lines: list[str], candidate: dict[str, Any], plan: CandidatePlan
) -> None:
    c = candidate
    lines.append(
        sql_raise_if_exists(
            "\n".join(
                [
                    _SQL_GUARD_EXISTS_SELECT,
                    "    from enoch.research_candidates",
                    f"    where candidate_id = {sql_literal(c['candidate_id'])}",
                    _SQL_GUARD_AND_OPEN,
                    f"        generation_mode is distinct from {sql_literal(c['generation_mode'])}",
                    f"        or dedupe_key is distinct from {sql_literal(c['dedupe_key'])}",
                    f"        or title is distinct from {sql_literal(c['title'])}",
                    "      )",
                ]
            ),
            "conflicting research candidate identity",
        )
    )
    lines.append(
        "insert into enoch.research_candidates("
        "candidate_id, generation_mode, status, title, category, priority, source_kind, source_ids, source_urls, "
        "parent_project_id, parent_run_id, hypothesis, mechanism, description, implementation, baseline_to_beat, "
        "success_threshold, kill_condition, accessibility_delta, expected_artifacts, required_evidence, likely_failure_modes, "
        "estimated_runtime_class, expected_token_budget, machine_target, model, sandbox, novelty_score, feasibility_score, "
        "accessibility_score, falsifiability_score, total_score, score_breakdown, dedupe_key, similar_prior_projects, "
        "novelty_comparison, risk_notes, rejection_reason, provider, provider_model, prompt_version, generated_by, raw_candidate_json"
        ") values ("
        f"{sql_literal(c['candidate_id'])}, {sql_literal(c['generation_mode'])}, {sql_literal(c['status'])}, {sql_literal(c['title'])}, "
        f"{sql_literal(c['category'])}, {sql_literal(c['priority'])}, {sql_literal(c['source_kind'])}, {sql_json(c['source_ids'])}, {sql_json(c['source_urls'])}, "
        f"{sql_literal(c['parent_project_id'])}, {sql_literal(c['parent_run_id'])}, {sql_literal(c['hypothesis'])}, {sql_literal(c['mechanism'])}, "
        f"{sql_literal(c['description'])}, {sql_literal(c['implementation'])}, {sql_literal(c['baseline_to_beat'])}, {sql_literal(c['success_threshold'])}, "
        f"{sql_literal(c['kill_condition'])}, {sql_literal(c['accessibility_delta'])}, {sql_json(c['expected_artifacts'])}, {sql_json(c['required_evidence'])}, {sql_json(c['likely_failure_modes'])}, "
        f"{sql_literal(c['estimated_runtime_class'])}, {sql_literal(c['expected_token_budget'])}, {sql_literal(c['machine_target'])}, {sql_literal(c['model'])}, {sql_literal(c['sandbox'])}, "
        f"{c['novelty_score']:.2f}, {c['feasibility_score']:.2f}, {c['accessibility_score']:.2f}, {c['falsifiability_score']:.2f}, {c['total_score']:.2f}, "
        f"{sql_json(c['score_breakdown'])}, {sql_literal(c['dedupe_key'])}, {sql_json(c['similar_prior_projects'])}, {sql_literal(c['novelty_comparison'])}, {sql_literal(c['risk_notes'])}, "
        f"{sql_literal(plan.admission_reason if plan.admission_decision == 'rejected' else '')}, {sql_literal(c['provider'])}, {sql_literal(c['provider_model'])}, {sql_literal(c['prompt_version'])}, {sql_literal(c['generated_by'])}, {sql_json(c['raw_candidate_json'])}"
        ") on conflict (candidate_id) do update set "
        "status = case when enoch.research_candidates.status not in ('admitted', 'rejected', 'merged') then excluded.status else enoch.research_candidates.status end, "
        "total_score = excluded.total_score, score_breakdown = excluded.score_breakdown, updated_at = now() "
        "where enoch.research_candidates.status not in ('admitted', 'rejected', 'merged');"
    )


def _emit_lineage_sql(lines: list[str], candidate: dict[str, Any]) -> None:
    for source_id in candidate["source_ids"]:
        lines.append(
            "insert into enoch.research_lineage(source_type, source_id, target_type, target_id, relation_type, evidence_json) values "
            f"('source', {sql_literal(_as_text(source_id))}, 'candidate', {sql_literal(candidate['candidate_id'])}, 'generated_from', {sql_json({'source_ids': candidate['source_ids']})});"
        )
    for url in candidate["source_urls"]:
        source_id = "url-" + stable_hash(_as_text(url), 24)
        lines.append(
            "insert into enoch.research_lineage(source_type, source_id, target_type, target_id, relation_type, evidence_json) values "
            f"('source', {sql_literal(source_id)}, 'candidate', {sql_literal(candidate['candidate_id'])}, 'generated_from', {sql_json({'url': _as_text(url)})});"
        )


def _emit_admitted_queue_sql(
    lines: list[str],
    candidate: dict[str, Any],
    plan: CandidatePlan,
    *,
    requested_by: str,
) -> None:
    c = candidate
    idea_id = plan.admitted_idea_id
    lines.append(
        sql_raise_if_exists(
            "\n".join(
                [
                    _SQL_GUARD_EXISTS_SELECT,
                    "    from enoch.ideas",
                    f"    where idea_id = {sql_literal(idea_id)}",
                    _SQL_GUARD_AND_OPEN,
                    "        source_kind is distinct from 'research_facility'",
                    "      )",
                ]
            ),
            "conflicting research facility idea identity",
        )
    )
    lines.append(
        "insert into enoch.ideas(idea_id, title, idea_status, category, priority, source_kind, source_external_url, description, implementation, baseline_to_beat, kill_condition, accessibility_delta, expected_token_budget, novelty_score, machine_target, model, sandbox, selection_rank, dispatch_priority, source_payload_json) values "
        f"({sql_literal(idea_id)}, {sql_literal(c['title'])}, 'testing', {sql_literal(c['category'])}, {sql_literal(c['priority'])}, 'research_facility', {sql_literal(c['source_urls'][0] if c['source_urls'] else '')}, {sql_literal(c['description'] or c['hypothesis'])}, {sql_literal(c['implementation'])}, {sql_literal(c['baseline_to_beat'])}, {sql_literal(c['kill_condition'])}, {sql_literal(c['accessibility_delta'])}, {sql_literal(c['expected_token_budget'])}, {sql_literal(str(c['novelty_score']))}, {sql_literal(c['machine_target'])}, {sql_literal(c['model'])}, {sql_literal(c['sandbox'])}, 50, 50, {sql_json(c)}) "
        "on conflict (idea_id) do update set title = excluded.title, source_payload_json = excluded.source_payload_json, updated_at = now();"
    )
    lines.append(
        sql_raise_if_exists(
            "\n".join(
                [
                    _SQL_GUARD_EXISTS_SELECT,
                    "    from enoch.projects",
                    f"    where project_id = {sql_literal(idea_id)}",
                    _SQL_GUARD_AND_OPEN,
                    f"        project_dir is distinct from {sql_literal(idea_id)}",
                    "        or origin_idea_status is distinct from 'testing'",
                    "      )",
                ]
            ),
            "conflicting research facility project identity",
        )
    )
    lines.append(
        "insert into enoch.projects(project_id, project_name, project_dir, origin_idea_status) values "
        f"({sql_literal(idea_id)}, {sql_literal(c['title'])}, {sql_literal(idea_id)}, 'testing') "
        "on conflict (project_id) do update set project_name = excluded.project_name, updated_at = now();"
    )
    lines.append(
        sql_raise_if_exists(
            "\n".join(
                [
                    _SQL_GUARD_EXISTS_SELECT,
                    "    from enoch.queue_items",
                    f"    where project_id = {sql_literal(idea_id)}",
                    _SQL_GUARD_AND_OPEN,
                    "        status is distinct from 'queued'",
                    "        or coalesce(current_run_id, '') <> ''",
                    "        or coalesce(next_action_hint, '') not in ('', 'controller_review')",
                    "      )",
                ]
            ),
            "conflicting research facility queue promotion identity",
        )
    )
    lines.append(
        "insert into enoch.queue_items(project_id, status, selection_rank, dispatch_priority, auto_continue, continue_count, max_continues, retry_count, max_retries, next_action_hint, manual_review_required, machine_target, model, sandbox, updated_at) values "
        f"({sql_literal(idea_id)}, 'queued', 50, 50, true, 0, 0, 0, 2, 'controller_review', false, {sql_literal(c['machine_target'])}, {sql_literal(c['model'])}, {sql_literal(c['sandbox'])}, now()) "
        "on conflict (project_id) do update set machine_target = excluded.machine_target, model = excluded.model, sandbox = excluded.sandbox, updated_at = now() "
        "where enoch.queue_items.status not in ('dispatching', 'running', 'awaiting_wake', 'wake_received', 'reconciling');"
    )
    lines.append(
        "insert into enoch.research_lineage(source_type, source_id, target_type, target_id, relation_type, evidence_json) values "
        f"('candidate', {sql_literal(c['candidate_id'])}, 'idea', {sql_literal(idea_id)}, 'admitted_as', {sql_json({'admission_reason': plan.admission_reason})}), "
        f"('idea', {sql_literal(idea_id)}, 'project', {sql_literal(idea_id)}, 'queued_as', {sql_json({'queued_by': requested_by})});"
    )


def _emit_admission_sql(
    lines: list[str],
    candidate: dict[str, Any],
    plan: CandidatePlan,
    *,
    requested_by: str,
    queue_admitted: bool,
    idempotency_key: str,
) -> None:
    c = candidate
    admitted_idea_sql = (
        sql_literal(plan.admitted_idea_id)
        if (queue_admitted and plan.admitted_idea_id)
        else "null"
    )
    lines.append(
        sql_raise_if_exists(
            "\n".join(
                [
                    _SQL_GUARD_EXISTS_SELECT,
                    "    from enoch.research_admissions",
                    f"    where idempotency_key = {sql_literal(idempotency_key)}",
                    _SQL_GUARD_AND_OPEN,
                    f"        candidate_id is distinct from {sql_literal(c['candidate_id'])}",
                    f"        or admission_decision is distinct from {sql_literal(plan.admission_decision)}",
                    f"        or admission_reason is distinct from {sql_literal(plan.admission_reason)}",
                    f"        or score_breakdown is distinct from {sql_json(plan.score_breakdown)}",
                    f"        or admitted_idea_id is distinct from {admitted_idea_sql}",
                    f"        or operator is distinct from {sql_literal(requested_by)}",
                    "      )",
                ]
            ),
            "conflicting research admission idempotency key",
        )
    )
    lines.append(
        "insert into enoch.research_admissions(candidate_id, admission_decision, admission_reason, score_breakdown, admitted_idea_id, operator, idempotency_key) values "
        f"({sql_literal(c['candidate_id'])}, {sql_literal(plan.admission_decision)}, {sql_literal(plan.admission_reason)}, {sql_json(plan.score_breakdown)}, {admitted_idea_sql}, {sql_literal(requested_by)}, {sql_literal(idempotency_key)}) "
        "on conflict (idempotency_key) do nothing;"
    )


def emit_sql(
    plans: list[CandidatePlan], *, requested_by: str, queue_admitted: bool
) -> str:
    lines = [
        "-- Generated by scripts/research_facility.py",
        "-- Inserts Research Facility ledger rows. Candidate admission is idempotent by idempotency_key.",
        "begin;",
        "",
    ]
    for plan in plans:
        c = plan.candidate
        for source in c.get("source_records", []):
            if isinstance(source, dict):
                _emit_source_record_sql(lines, source, c)
        for url in c["source_urls"]:
            _emit_url_source_sql(lines, url, c)
        _emit_candidate_sql(lines, c, plan)
        idempotency_key = (
            f"research-admission:{c['candidate_id']}:{plan.admission_decision}"
        )
        _emit_lineage_sql(lines, c)
        if plan.admission_decision == "admitted" and queue_admitted:
            _emit_admitted_queue_sql(lines, c, plan, requested_by=requested_by)
        _emit_admission_sql(
            lines,
            c,
            plan,
            requested_by=requested_by,
            queue_admitted=queue_admitted,
            idempotency_key=idempotency_key,
        )
        lines.append("")
    lines.append("commit;")
    return "\n".join(lines) + "\n"


def plan_candidates(
    candidates: list[dict[str, Any]], args: argparse.Namespace
) -> list[CandidatePlan]:
    seen: dict[str, str] = {}
    plans: list[CandidatePlan] = []
    history = list(getattr(args, "history", []) or [])
    for raw in candidates:
        row = normalize_candidate(
            raw,
            default_machine=args.default_machine,
            default_model=args.default_model,
            default_sandbox=args.default_sandbox,
        )
        exact_history, similar_history = (
            compare_history(row, history) if history else ([], [])
        )
        if similar_history and not row["similar_prior_projects"]:
            row["similar_prior_projects"] = similar_history
        plan = evaluate_candidate(
            row,
            admit_threshold=args.admit_threshold,
            review_threshold=args.review_threshold,
        )
        previous = seen.get(row["dedupe_key"])
        if previous:
            plan.admission_decision = "rejected"
            plan.admission_reason = f"duplicate dedupe_key also used by {previous}"
            plan.admitted_idea_id = ""
            plan.hard_failures.append(plan.admission_reason)
            row["status"] = "rejected"
        elif exact_history:
            plan.admission_decision = "merged"
            plan.admission_reason = (
                f"merged with historical duplicate {exact_history[0]['project_id']}"
            )
            plan.admitted_idea_id = ""
            row["status"] = "merged"
            row["similar_prior_projects"] = exact_history
        else:
            seen[row["dedupe_key"]] = row["candidate_id"]
        plans.append(plan)
    return plans


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "input", type=Path, help="JSON/markdown file containing candidate objects"
    )
    parser.add_argument(
        "--output", type=Path, help="write JSON admission plan here; default stdout"
    )
    parser.add_argument(
        "--emit-sql", type=Path, help="write idempotent SQL ledger plan here"
    )
    parser.add_argument(
        "--queue-admitted",
        action="store_true",
        help="when emitting SQL, also upsert admitted ideas/projects/queue_items",
    )
    parser.add_argument("--admit-threshold", type=float, default=72.0)
    parser.add_argument("--review-threshold", type=float, default=58.0)
    parser.add_argument("--requested-by", default="research_facility")
    parser.add_argument("--default-machine", default="gb10")
    parser.add_argument("--default-model", default="gpt-5.5")
    parser.add_argument("--default-sandbox", default="danger-full-access")
    parser.add_argument(
        "--history-json",
        type=Path,
        help="optional prior idea/project/run history JSON for dedupe and novelty comparison",
    )
    parser.add_argument(
        "--database-url",
        default="",
        help="optional Postgres URL to query prior Enoch ideas/projects/decisions for dedupe",
    )
    parser.add_argument("--history-limit", type=int, default=1000)
    args = parser.parse_args(argv)
    history = load_history(args.history_json)
    if args.database_url:
        history.extend(
            fetch_history_from_database(args.database_url, limit=args.history_limit)
        )
    args.history = history

    candidates = load_candidates(args.input)
    plans = plan_candidates(candidates, args)
    payload = {
        "ok": True,
        "input": str(args.input),
        "candidate_count": len(plans),
        "history_count": len(history),
        "admitted_count": sum(
            1 for plan in plans if plan.admission_decision == "admitted"
        ),
        "needs_review_count": sum(
            1 for plan in plans if plan.admission_decision == "needs_review"
        ),
        "rejected_count": sum(
            1 for plan in plans if plan.admission_decision == "rejected"
        ),
        "plans": [plan.to_json() for plan in plans],
    }
    text = json.dumps(payload, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    if args.emit_sql:
        args.emit_sql.write_text(
            emit_sql(
                plans,
                requested_by=args.requested_by,
                queue_admitted=args.queue_admitted,
            ),
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
