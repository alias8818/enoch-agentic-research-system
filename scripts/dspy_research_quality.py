#!/usr/bin/env python3
"""Read-only Research Facility quality audit.

This is the Phase-1 DSPy integration point: it produces a quality report from
existing Research Facility candidates and project decision rows without changing
queue state, paper state, or database schema. If the optional DSPy dependency is
installed, this script records that DSPy signatures are available; it still uses
read-only deterministic heuristics by default so it is safe for CI and ops.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from enoch_control_plane.research_quality.artifacts import build_quality_report
from enoch_control_plane.research_quality.datasets import (
    CandidateRow,
    DecisionRow,
    as_bool,
    as_float,
    as_text,
)
from enoch_control_plane.research_quality.dspy_programs import dspy_available


def _json_len(value: Any) -> int:
    return len(value) if isinstance(value, list) else 0


def _candidate_from_mapping(row: dict[str, Any]) -> CandidateRow:
    return CandidateRow(
        candidate_id=as_text(row.get("candidate_id")),
        title=as_text(row.get("title")),
        category=as_text(row.get("category")),
        status=as_text(row.get("status")),
        total_score=as_float(row.get("total_score")),
        generation_mode=as_text(row.get("generation_mode")),
        mechanism=as_text(row.get("mechanism")),
        baseline_to_beat=as_text(row.get("baseline_to_beat")),
        success_threshold=as_text(row.get("success_threshold")),
        kill_condition=as_text(row.get("kill_condition")),
        required_evidence_count=_json_len(row.get("required_evidence")),
        expected_artifact_count=_json_len(row.get("expected_artifacts")),
        similar_prior_count=_json_len(row.get("similar_prior_projects")),
        novelty_comparison=as_text(row.get("novelty_comparison")),
    )


def _decision_from_mapping(row: dict[str, Any]) -> DecisionRow:
    payload = (
        row.get("payload_json") if isinstance(row.get("payload_json"), dict) else {}
    )
    project_decision = (
        payload.get("project_decision")
        if isinstance(payload.get("project_decision"), dict)
        else payload
    )
    return DecisionRow(
        project_id=as_text(row.get("project_id")),
        project_name=as_text(row.get("project_name")),
        run_id=as_text(row.get("run_id")),
        decision=as_text(
            row.get("decision") or project_decision.get("project_decision") or "unknown"
        ),
        hypothesis_status=as_text(
            row.get("hypothesis_status")
            or project_decision.get("hypothesis_status")
            or "unknown"
        ),
        evidence_strength=as_text(
            row.get("evidence_strength")
            or project_decision.get("evidence_strength")
            or "unknown"
        ),
        confidence=as_text(
            row.get("confidence") or project_decision.get("confidence") or "unknown"
        ),
        research_outcome=as_text(
            row.get("research_outcome") or project_decision.get("research_outcome")
        ),
        claim_scope=as_text(
            row.get("claim_scope") or project_decision.get("claim_scope")
        ),
        scale_limits=as_text(
            row.get("scale_limits") or project_decision.get("scale_limits")
        ),
        bounded_paper_ready=as_bool(
            row.get("bounded_paper_ready")
            if row.get("bounded_paper_ready") is not None
            else project_decision.get("bounded_paper_ready")
        ),
        compute_scale_blocked=as_bool(
            row.get("compute_scale_blocked")
            if row.get("compute_scale_blocked") is not None
            else project_decision.get("compute_scale_blocked")
        ),
        followup_recommended=as_bool(
            row.get("followup_recommended")
            if row.get("followup_recommended") is not None
            else project_decision.get("followup_recommended")
        ),
        followup_type=as_text(
            row.get("followup_type") or project_decision.get("followup_type")
        ),
        followup_title=as_text(
            row.get("followup_title") or project_decision.get("followup_title")
        ),
        followup_hypothesis=as_text(
            row.get("followup_hypothesis")
            or project_decision.get("followup_hypothesis")
        ),
        followup_required_evidence_count=_json_len(
            row.get("followup_required_evidence")
            or project_decision.get("followup_required_evidence")
        ),
        followup_success_threshold=as_text(
            row.get("followup_success_threshold")
            or project_decision.get("followup_success_threshold")
        ),
        followup_stop_condition=as_text(
            row.get("followup_stop_condition")
            or project_decision.get("followup_stop_condition")
        ),
        recommended_next_action=as_text(
            project_decision.get("recommended_next_action")
            or row.get("recommended_next_action")
        ),
        stop_reason=as_text(
            project_decision.get("stop_reason") or row.get("stop_reason")
        ),
        created_at=as_text(row.get("created_at") or row.get("decided_at")),
    )


def _load_json_rows(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("rows") or data.get("candidates") or data.get("decisions") or []
    if not isinstance(data, list):
        raise SystemExit(f"{path}: expected a JSON list or object with rows")
    return [row for row in data if isinstance(row, dict)]


def _fetch_from_database(
    database_url: str, *, limit: int
) -> tuple[list[CandidateRow], list[DecisionRow]]:
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
                       d.created_at, d.decided_at
                from project_decisions d
                left join projects p using(project_id)
                order by d.created_at desc, d.decision_id desc
                limit %s
                """,
                (safe_limit,),
            ).fetchall()
    return [_candidate_from_mapping(dict(row)) for row in candidate_rows], [
        _decision_from_mapping(dict(row)) for row in decision_rows
    ]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL", ""),
        help="Postgres URL for read-only audit input; defaults to DATABASE_URL",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="maximum candidate and decision rows to inspect",
    )
    parser.add_argument(
        "--output", type=Path, required=True, help="write report JSON here"
    )
    parser.add_argument(
        "--candidate-json",
        type=Path,
        help="optional JSON candidate fixture instead of DB candidates",
    )
    parser.add_argument(
        "--decision-json",
        type=Path,
        help="optional JSON decision fixture instead of DB decisions",
    )
    parser.add_argument(
        "--pretty", action="store_true", help="pretty-print JSON output"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.candidate_json or args.decision_json:
        candidates = [
            _candidate_from_mapping(row)
            for row in (
                _load_json_rows(args.candidate_json) if args.candidate_json else []
            )
        ]
        decisions = [
            _decision_from_mapping(row)
            for row in (
                _load_json_rows(args.decision_json) if args.decision_json else []
            )
        ]
    else:
        if not args.database_url:
            raise SystemExit(
                "--database-url or DATABASE_URL is required unless fixture JSON is provided"
            )
        candidates, decisions = _fetch_from_database(
            args.database_url, limit=args.limit
        )

    report = build_quality_report(
        candidates=candidates,
        decisions=decisions,
        metadata={
            "limit": max(1, min(args.limit, 1000)),
            "dspy_available": dspy_available(),
            "dspy_runtime_used": False,
            "note": "Phase-1 read-only sidecar audit; no queue, paper, or schema writes.",
        },
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2 if args.pretty else None, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {"ok": True, "output": str(args.output), "summary": report["summary"]},
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
