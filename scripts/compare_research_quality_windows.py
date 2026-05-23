#!/usr/bin/env python3
"""Compare Research Facility candidate/decision quality before and after a cutoff.

This is a read-only reporting tool for evaluating prompt/policy changes. It
summarizes recent candidate quality and eval-case types in two windows. It does
not write database state, enqueue work, dispatch workers, or apply prompt
patches.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from decimal import Decimal
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from enoch_control_plane.research_quality.datasets import (
    CandidateRow,
    pairwise_similarity,
)  # noqa: E402
from scripts.build_research_quality_evalset import RawDecision, build_eval_cases  # noqa: E402
from scripts.dspy_research_quality import (
    _candidate_from_mapping,
    _decision_from_mapping,
)  # noqa: E402


def _as_float(value: Any) -> float:
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def summarize_window(
    *,
    candidates: list[CandidateRow],
    decisions: list[RawDecision],
    max_followup_depth: int,
) -> dict[str, Any]:
    cases = build_eval_cases(
        candidates, decisions, max_followup_depth=max_followup_depth
    )
    case_counts = Counter(case["case_type"] for case in cases)
    status_counts = Counter(row.status or "unknown" for row in candidates)
    mode_counts = Counter(row.generation_mode or "unknown" for row in candidates)
    category_counts = Counter(row.category or "unknown" for row in candidates)
    moonshots = [row for row in candidates if row.generation_mode == "moonshot"]
    scores = [_as_float(row.total_score) for row in candidates]
    moonshot_scores = [_as_float(row.total_score) for row in moonshots]
    return {
        "candidate_count": len(candidates),
        "decision_count": len(decisions),
        "status_counts": dict(status_counts.most_common()),
        "generation_mode_counts": dict(mode_counts.most_common()),
        "category_counts": dict(category_counts.most_common()),
        "avg_total_score": round(sum(scores) / len(scores), 3) if scores else 0.0,
        "admitted_rate": round(status_counts.get("admitted", 0) / len(candidates), 3)
        if candidates
        else 0.0,
        "moonshot_count": len(moonshots),
        "moonshot_avg_score": round(sum(moonshot_scores) / len(moonshot_scores), 3)
        if moonshot_scores
        else 0.0,
        "high_similarity_pair_count": len(
            pairwise_similarity(candidates, threshold=0.55, limit=10_000)
        ),
        "eval_case_counts": dict(case_counts.most_common()),
    }


def compare_windows(pre: dict[str, Any], post: dict[str, Any]) -> dict[str, Any]:
    def delta(key: str) -> float:
        return round(float(post.get(key) or 0) - float(pre.get(key) or 0), 3)

    return {
        "duplicateish_delta": delta("high_similarity_pair_count"),
        "proxy_only_positive_delta": round(
            float(post.get("eval_case_counts", {}).get("proxy_only_positive", 0))
            - float(pre.get("eval_case_counts", {}).get("proxy_only_positive", 0)),
            3,
        ),
        "useful_adjacent_followup_delta": round(
            float(post.get("eval_case_counts", {}).get("useful_adjacent_followup", 0))
            - float(pre.get("eval_case_counts", {}).get("useful_adjacent_followup", 0)),
            3,
        ),
        "max_depth_followup_delta": round(
            float(post.get("eval_case_counts", {}).get("max_depth_followup_ending", 0))
            - float(
                pre.get("eval_case_counts", {}).get("max_depth_followup_ending", 0)
            ),
            3,
        ),
        "moonshot_avg_score_delta": delta("moonshot_avg_score"),
        "admitted_rate_delta": delta("admitted_rate"),
    }


def _fetch_window(
    database_url: str, *, cutoff: str, side: str, limit: int
) -> tuple[list[CandidateRow], list[RawDecision], dict[str, Any]]:
    import psycopg
    from psycopg.rows import dict_row

    op = ">=" if side == "post" else "<"
    direction = "asc" if side == "post" else "desc"
    safe_limit = max(1, min(limit, 1000))
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute("set search_path to enoch, public")
            candidate_rows = cur.execute(
                f"""
                select candidate_id, generation_mode, status, title, category, total_score,
                       mechanism, baseline_to_beat, success_threshold, kill_condition,
                       required_evidence, expected_artifacts, similar_prior_projects,
                       novelty_comparison, created_at, updated_at
                from research_candidates
                where created_at {op} %s::timestamptz
                order by created_at {direction}, candidate_id asc
                limit %s
                """,
                (cutoff, safe_limit),
            ).fetchall()
            decision_rows = cur.execute(
                f"""
                select d.project_id, p.project_name, d.run_id, d.payload_json,
                       d.followup_recommended, d.followup_type, d.followup_title,
                       d.followup_hypothesis, d.followup_required_evidence,
                       d.followup_success_threshold, d.followup_stop_condition,
                       d.followup_depth, d.created_at, d.decided_at,
                       coalesce(i.source_payload_json, '{{}}'::jsonb) as idea_source_payload_json,
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
                where d.created_at {op} %s::timestamptz
                order by d.created_at {direction}, d.decision_id asc
                limit %s
                """,
                (cutoff, safe_limit),
            ).fetchall()
    candidates = [_candidate_from_mapping(dict(row)) for row in candidate_rows]
    decisions = [
        RawDecision(row=dict(row), decision=_decision_from_mapping(dict(row)))
        for row in decision_rows
    ]
    meta = {
        "candidate_count": len(candidate_rows),
        "decision_count": len(decision_rows),
        "candidate_first_created_at": str(candidate_rows[0]["created_at"])
        if candidate_rows
        else None,
        "candidate_last_created_at": str(candidate_rows[-1]["created_at"])
        if candidate_rows
        else None,
        "decision_first_created_at": str(decision_rows[0]["created_at"])
        if decision_rows
        else None,
        "decision_last_created_at": str(decision_rows[-1]["created_at"])
        if decision_rows
        else None,
    }
    return candidates, decisions, meta


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url",
        default=os.environ.get("ENOCH_CONTROL_DATABASE_URL")
        or os.environ.get("ENOCH_SUPABASE_DATABASE_URL")
        or os.environ.get("DATABASE_URL")
        or "",
    )
    parser.add_argument(
        "--cutoff", required=True, help="ISO timestamp separating pre/post windows"
    )
    parser.add_argument(
        "--limit", type=int, default=20, help="candidate and decision rows per window"
    )
    parser.add_argument("--max-followup-depth", type=int, default=2)
    parser.add_argument("--output", type=Path, help="optional JSON report output")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.database_url:
        raise SystemExit(
            "--database-url or ENOCH_CONTROL_DATABASE_URL/ENOCH_SUPABASE_DATABASE_URL/DATABASE_URL is required"
        )
    pre_candidates, pre_decisions, pre_meta = _fetch_window(
        args.database_url, cutoff=args.cutoff, side="pre", limit=args.limit
    )
    post_candidates, post_decisions, post_meta = _fetch_window(
        args.database_url, cutoff=args.cutoff, side="post", limit=args.limit
    )
    pre = summarize_window(
        candidates=pre_candidates,
        decisions=pre_decisions,
        max_followup_depth=args.max_followup_depth,
    )
    post = summarize_window(
        candidates=post_candidates,
        decisions=post_decisions,
        max_followup_depth=args.max_followup_depth,
    )
    report = {
        "ok": True,
        "schema_version": "enoch_research_quality_window_comparison_v1",
        "runtime_effect": "none",
        "cutoff": args.cutoff,
        "limit": max(1, min(args.limit, 1000)),
        "pre_meta": pre_meta,
        "post_meta": post_meta,
        "pre": pre,
        "post": post,
        "delta": compare_windows(pre, post),
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
