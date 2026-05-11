#!/usr/bin/env python3
"""Build deterministic eval cases for offline Research Facility prompt/policy evolution.

The output is JSONL intended for offline DSPy/GEPA experiments. This script is
read-only: it reads recent Research Facility candidates and project decisions,
then emits cases that ask an optimizer/reviewer to preserve or improve specific
policy boundaries. It does not enqueue work, dispatch workers, draft papers, or
write database state.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from enoch_control_plane.research_quality.datasets import (  # noqa: E402
    CandidateRow,
    DecisionRow,
    classify_candidate_contract,
    classify_decision_quality,
    has_bounded_followup,
    jaccard,
    token_set,
)
from scripts.dspy_research_quality import _candidate_from_mapping, _decision_from_mapping, _load_json_rows  # noqa: E402


@dataclass(frozen=True)
class RawDecision:
    row: dict[str, Any]
    decision: DecisionRow


def _json_len(value: Any) -> int:
    return len(value) if isinstance(value, list) else 0


def _as_text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _payload(row: dict[str, Any]) -> dict[str, Any]:
    payload = row.get("payload_json")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            payload = {}
    return payload if isinstance(payload, dict) else {}


def _project_decision_payload(row: dict[str, Any]) -> dict[str, Any]:
    payload = _payload(row)
    project_decision = payload.get("project_decision")
    return project_decision if isinstance(project_decision, dict) else payload


def _followup_depth(row: dict[str, Any]) -> int:
    payload = _project_decision_payload(row)
    idea_payload = row.get("idea_source_payload_json")
    if isinstance(idea_payload, str):
        try:
            idea_payload = json.loads(idea_payload)
        except json.JSONDecodeError:
            idea_payload = {}
    if not isinstance(idea_payload, dict):
        idea_payload = {}
    return max(
        _as_int(row.get("followup_depth")),
        _as_int(row.get("source_followup_depth")),
        _as_int(payload.get("followup_depth")),
        _as_int(payload.get("parent_followup_depth")),
        _as_int(idea_payload.get("followup_depth")),
        _as_int(idea_payload.get("parent_followup_depth")),
    )


def _combined_rationale(row: DecisionRow) -> str:
    return " ".join([row.stop_reason, row.recommended_next_action]).lower()


def _proxy_only(row: DecisionRow) -> bool:
    text = _combined_rationale(row)
    return any(marker in text for marker in ("proxy-only", "proxy only", "proxy/early", "proxy early", "synthetic proxy", "trace-only", "not full validation"))


def _case_id(case_type: str, entity_id: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_.:-]+", "-", entity_id).strip("-") or "unknown"
    return f"{case_type}:{cleaned}"


def _compact_candidate(row: CandidateRow) -> dict[str, Any]:
    return {
        "candidate_id": row.candidate_id,
        "title": row.title,
        "category": row.category,
        "status": row.status,
        "total_score": row.total_score,
        "generation_mode": row.generation_mode,
        "mechanism": row.mechanism,
        "baseline_to_beat": row.baseline_to_beat,
        "success_threshold": row.success_threshold,
        "kill_condition": row.kill_condition,
        "required_evidence_count": row.required_evidence_count,
        "expected_artifact_count": row.expected_artifact_count,
        "similar_prior_count": row.similar_prior_count,
        "novelty_comparison": row.novelty_comparison,
    }


def _compact_decision(row: DecisionRow, raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "project_id": row.project_id,
        "project_name": row.project_name,
        "run_id": row.run_id,
        "decision": row.decision,
        "hypothesis_status": row.hypothesis_status,
        "evidence_strength": row.evidence_strength,
        "confidence": row.confidence,
        "followup_recommended": row.followup_recommended,
        "followup_type": row.followup_type,
        "followup_title": row.followup_title,
        "followup_hypothesis": row.followup_hypothesis,
        "followup_required_evidence_count": row.followup_required_evidence_count,
        "followup_success_threshold": row.followup_success_threshold,
        "followup_stop_condition": row.followup_stop_condition,
        "followup_depth": _followup_depth(raw),
        "recommended_next_action": row.recommended_next_action,
        "stop_reason": row.stop_reason,
        "created_at": row.created_at,
    }


def _case(case_type: str, label: str, severity: str, entity_id: str, title: str, input_payload: dict[str, Any], expected_behavior: str, rationale: str) -> dict[str, Any]:
    return {
        "schema_version": "enoch_research_quality_evalcase_v1",
        "case_id": _case_id(case_type, entity_id),
        "case_type": case_type,
        "label": label,
        "severity": severity,
        "title": title,
        "input": input_payload,
        "expected_behavior": expected_behavior,
        "rationale": rationale,
    }


def candidate_cases(candidates: list[CandidateRow]) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    seen: set[str] = set()
    tokens = [token_set(" ".join([row.title, row.mechanism, row.baseline_to_beat])) for row in candidates]
    for index, left in enumerate(candidates):
        _, problems = classify_candidate_contract(left)
        if "similar_prior_without_novelty_comparison" in problems:
            case = _case(
                "duplicateish_candidate",
                "reject_or_require_stronger_novelty",
                "warning",
                left.candidate_id,
                left.title,
                {"candidate": _compact_candidate(left), "problems": problems},
                "Do not admit or promote a candidate that resembles prior work unless the novelty comparison explains a changed mechanism, stronger evidence, or a materially different baseline.",
                "Candidate records with similar prior work and no novelty comparison are a repeat-negative risk.",
            )
            cases.append(case)
            seen.add(case["case_id"])
        for right_index in range(index + 1, len(candidates)):
            similarity = jaccard(tokens[index], tokens[right_index])
            if similarity < 0.55:
                continue
            right = candidates[right_index]
            entity = f"{left.candidate_id}:{right.candidate_id}"
            case = _case(
                "duplicateish_candidate",
                "prefer_one_or_require_changed_mechanism",
                "info",
                entity,
                f"{left.title} / {right.title}",
                {
                    "left_candidate": _compact_candidate(left),
                    "right_candidate": _compact_candidate(right),
                    "similarity": round(similarity, 3),
                },
                "Treat high-overlap candidates as an eval failure unless the policy keeps only one or requires a concrete changed mechanism before admission.",
                "High lexical/mechanism overlap is a deterministic proxy for duplicated exploration pressure.",
            )
            if case["case_id"] not in seen:
                cases.append(case)
                seen.add(case["case_id"])
    return cases


def decision_cases(raw_decisions: list[RawDecision], *, max_followup_depth: int) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_decisions:
        row = raw.decision
        score, problems = classify_decision_quality(row)
        compact = _compact_decision(row, raw.row)
        if "supported_but_negative_requires_review" in problems:
            cases.append(
                _case(
                    "supported_but_negative_warning",
                    "warn_not_block_or_write_paper",
                    "warning",
                    row.run_id or row.project_id,
                    row.project_name,
                    {"decision": compact, "quality_score": score, "problems": problems},
                    "Classify as a Research Quality warning for operator inspection; do not count as paper-positive and do not block long-haul readiness unless stronger evidence says the gate is wrong.",
                    "Supported-but-negative decisions can be legitimate proxy/support cases, but they are exactly where prompt and paper-gate policy should be evaluated.",
                )
            )
        if _proxy_only(row) and row.hypothesis_status in {"supported", "mixed"} and row.decision == "finalize_negative":
            cases.append(
                _case(
                    "proxy_only_positive",
                    "require_direct_evidence_before_paper",
                    "info",
                    row.run_id or row.project_id,
                    row.project_name,
                    {"decision": compact},
                    "Keep the result out of the paper-writing lane unless a follow-up provides direct artifact-backed evidence against the target baseline.",
                    "Proxy-only or early-falsification support should guide follow-up policy, not become publication work.",
                )
            )
        if _followup_depth(raw.row) >= max_followup_depth and row.decision == "finalize_negative":
            cases.append(
                _case(
                    "max_depth_followup_ending",
                    "stop_or_require_manual_new_branch",
                    "info",
                    row.run_id or row.project_id,
                    row.project_name,
                    {"decision": compact, "max_followup_depth": max_followup_depth},
                    "Do not auto-branch again at or above max follow-up depth; require a manually justified new mechanism if work continues.",
                    "Depth-capped negative endings are useful eval cases for preventing infinite adjacent variants.",
                )
            )
        if has_bounded_followup(row) and _followup_depth(raw.row) < max_followup_depth and row.decision == "finalize_negative":
            case = _case(
                "useful_adjacent_followup",
                "promote_bounded_followup_candidate",
                "info",
                row.run_id or row.project_id,
                row.followup_title or row.project_name,
                {"decision": compact},
                "Prefer promoting a bounded follow-up when it has a changed hypothesis, at least two required evidence items, a success threshold, and a stop condition.",
                "This is the positive eval class for follow-up branching policy: adjacent work is allowed when the branch is bounded and mechanism-changing.",
            )
            if case["case_id"] not in seen:
                cases.append(case)
                seen.add(case["case_id"])
    return cases


def _load_candidates(path: Path | None) -> list[CandidateRow]:
    if not path:
        return []
    return [_candidate_from_mapping(row) for row in _load_json_rows(path)]


def _load_decisions(path: Path | None) -> list[RawDecision]:
    if not path:
        return []
    rows = _load_json_rows(path)
    return [RawDecision(row=row, decision=_decision_from_mapping(row)) for row in rows]


def _fetch_from_database(database_url: str, *, limit: int) -> tuple[list[CandidateRow], list[RawDecision]]:
    import psycopg
    from psycopg.rows import dict_row

    safe_limit = max(1, min(limit, 1000))
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute("set search_path to enoch, public")
            candidate_rows = cur.execute(
                """
                select candidate_id, generation_mode, status, title, category, total_score,
                       mechanism, baseline_to_beat, success_threshold, kill_condition,
                       required_evidence, expected_artifacts, similar_prior_projects,
                       novelty_comparison
                from research_candidates
                order by updated_at desc, total_score desc, candidate_id asc
                limit %s
                """,
                (safe_limit,),
            ).fetchall()
            decision_rows = cur.execute(
                """
                select d.project_id, p.project_name, d.run_id, d.payload_json,
                       d.followup_recommended, d.followup_type, d.followup_title,
                       d.followup_hypothesis, d.followup_required_evidence,
                       d.followup_success_threshold, d.followup_stop_condition,
                       d.followup_depth, d.created_at, d.decided_at,
                       coalesce(i.source_payload_json, '{}'::jsonb) as idea_source_payload_json,
                       case
                         when coalesce(i.source_payload_json->>'followup_depth', '') ~ '^[0-9]+$'
                         then (i.source_payload_json->>'followup_depth')::integer
                         when coalesce(i.source_payload_json->>'parent_followup_depth', '') ~ '^[0-9]+$'
                         then (i.source_payload_json->>'parent_followup_depth')::integer
                         else 0
                       end as source_followup_depth
                from project_decisions d
                left join projects p using(project_id)
                left join ideas i on i.idea_id = d.project_id
                order by d.created_at desc, d.decision_id desc
                limit %s
                """,
                (safe_limit,),
            ).fetchall()
    candidates = [_candidate_from_mapping(dict(row)) for row in candidate_rows]
    decisions = [RawDecision(row=dict(row), decision=_decision_from_mapping(dict(row))) for row in decision_rows]
    return candidates, decisions


def build_eval_cases(candidates: list[CandidateRow], decisions: list[RawDecision], *, max_followup_depth: int = 2) -> list[dict[str, Any]]:
    cases = [*candidate_cases(candidates), *decision_cases(decisions, max_followup_depth=max_followup_depth)]
    cases.sort(key=lambda item: (item["case_type"], item["case_id"]))
    return cases


def write_jsonl(path: Path, cases: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for case in cases:
            handle.write(json.dumps(case, sort_keys=True, separators=(",", ":")) + "\n")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=os.environ.get("ENOCH_CONTROL_DATABASE_URL") or os.environ.get("ENOCH_SUPABASE_DATABASE_URL") or os.environ.get("DATABASE_URL") or "", help="Postgres URL for read-only input; defaults to ENOCH_CONTROL_DATABASE_URL/ENOCH_SUPABASE_DATABASE_URL/DATABASE_URL")
    parser.add_argument("--candidate-json", type=Path, help="optional JSON candidate fixture instead of DB candidates")
    parser.add_argument("--decision-json", type=Path, help="optional JSON decision fixture instead of DB decisions")
    parser.add_argument("--limit", type=int, default=100, help="maximum candidate and decision rows to inspect")
    parser.add_argument("--max-followup-depth", type=int, default=2, help="automatic follow-up depth cap used for eval labels")
    parser.add_argument("--output", type=Path, required=True, help="write JSONL eval cases here")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.candidate_json or args.decision_json:
        candidates = _load_candidates(args.candidate_json)
        decisions = _load_decisions(args.decision_json)
    else:
        if not args.database_url:
            raise SystemExit("--database-url or fixture JSON is required")
        candidates, decisions = _fetch_from_database(args.database_url, limit=args.limit)

    cases = build_eval_cases(candidates, decisions, max_followup_depth=max(0, args.max_followup_depth))
    write_jsonl(args.output, cases)
    counts: dict[str, int] = {}
    for case in cases:
        counts[case["case_type"]] = counts.get(case["case_type"], 0) + 1
    print(json.dumps({"ok": True, "output": str(args.output), "case_count": len(cases), "case_counts": counts}, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
