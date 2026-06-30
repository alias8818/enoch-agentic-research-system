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
import re
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


DEFAULT_PROJECT_ROOTS = (
    Path(os.environ.get("ENOCH_PROJECT_ROOT", ""))
    if os.environ.get("ENOCH_PROJECT_ROOT")
    else None,
    Path("/var/lib/enoch-control-plane/projects"),
)


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


def _project_decision_from_row(row: dict[str, Any]) -> dict[str, Any]:
    payload = row.get("payload_json")
    if not isinstance(payload, dict):
        return {}
    nested = payload.get("project_decision")
    if isinstance(nested, dict):
        return nested
    return payload


def _is_placeholder_decision(project_decision: dict[str, Any]) -> bool:
    action = as_text(
        project_decision.get("project_decision") or project_decision.get("decision")
    )
    summary = as_text(project_decision.get("summary")).lower()
    return (
        action in {"", "scaffold_ready_for_worker"}
        or "bootstrap placeholder" in summary
    )


def _extract_final_decision_from_run_notes(text: str) -> dict[str, Any]:
    """Return a conservative structured decision from a worker's final notes.

    Some older worker scaffolds left the bootstrap `project_decision.json` in
    place while writing a concrete `## Final Decision` block in `run_notes.md`.
    Research Quality should not page forever on the stale bootstrap artifact
    when a deterministic final-decision block exists next to it.
    """

    marker = re.search(r"(?im)^##\s+Final Decision\s*$", text)
    if not marker:
        return {}
    tail = text[marker.end() : marker.end() + 4000]
    decision_match = re.search(r"(?im)^\s*Decision:\s*`?([a-z_]+)`?\s*$", tail)
    outcome_match = re.search(r"(?im)^\s*Research outcome:\s*`?([a-z_]+)`?\s*$", tail)
    rationale_match = re.search(r"(?ims)^\s*Rationale:\s*(.+?)(?:\n\s*\n|\Z)", tail)
    decision = as_text(decision_match.group(1) if decision_match else "")
    if decision not in {
        "finalize_negative",
        "finalize_positive",
        "blocked",
        "needs_review",
    }:
        return {}
    rationale = as_text(rationale_match.group(1) if rationale_match else "")
    outcome = as_text(outcome_match.group(1) if outcome_match else "")
    hypothesis_status = "supported" if outcome == "useful_signal" else "inconclusive"
    if decision == "finalize_positive":
        hypothesis_status = "supported"
    return {
        "project_decision": decision,
        "hypothesis_status": hypothesis_status,
        "evidence_strength": "moderate",
        "confidence": "medium",
        "research_outcome": outcome,
        "bounded_paper_ready": decision == "finalize_positive",
        "stop_reason": rationale,
        "recommended_next_action": (
            "Treat this as no-paper useful-signal evidence unless a later "
            "bounded follow-up supplies broader publication-grade validation."
        ),
        "decision_source": "run_notes_final_decision_fallback",
    }


def _project_decision_from_run_notes_fallback(row: dict[str, Any]) -> dict[str, Any]:
    project_id = as_text(row.get("project_id"))
    if not project_id:
        return {}
    for root in DEFAULT_PROJECT_ROOTS:
        if root is None:
            continue
        path = root / project_id / "run_notes.md"
        try:
            if not path.is_file():
                continue
            extracted = _extract_final_decision_from_run_notes(
                path.read_text(encoding="utf-8", errors="ignore")
            )
        except OSError:
            continue
        if extracted:
            return extracted
    return {}


def _coalesce_text(
    row: dict[str, Any],
    project_decision: dict[str, Any],
    row_key: str,
    *,
    payload_key: str | None = None,
    default: str = "",
    prefer_payload: bool = False,
) -> str:
    payload_key = payload_key if payload_key is not None else row_key
    row_value = row.get(row_key)
    payload_value = project_decision.get(payload_key)
    if prefer_payload:
        raw = payload_value or row_value or default
    else:
        raw = row_value or payload_value or default
    return as_text(raw)


def _coalesce_bool(
    row: dict[str, Any], project_decision: dict[str, Any], key: str
) -> bool:
    row_value = row.get(key)
    source = row_value if row_value is not None else project_decision.get(key)
    return as_bool(source)


def _decision_from_mapping(row: dict[str, Any]) -> DecisionRow | None:
    project_decision = _project_decision_from_row(row)
    if _is_placeholder_decision(project_decision):
        fallback = _project_decision_from_run_notes_fallback(row)
        if not fallback:
            return None
        project_decision = fallback
    return DecisionRow(
        project_id=as_text(row.get("project_id")),
        project_name=as_text(row.get("project_name")),
        run_id=as_text(row.get("run_id")),
        decision=_coalesce_text(
            row,
            project_decision,
            "decision",
            payload_key="project_decision",
            default="unknown",
        ),
        hypothesis_status=_coalesce_text(
            row, project_decision, "hypothesis_status", default="unknown"
        ),
        evidence_strength=_coalesce_text(
            row, project_decision, "evidence_strength", default="unknown"
        ),
        confidence=_coalesce_text(
            row, project_decision, "confidence", default="unknown"
        ),
        research_outcome=_coalesce_text(row, project_decision, "research_outcome"),
        claim_scope=_coalesce_text(row, project_decision, "claim_scope"),
        scale_limits=_coalesce_text(row, project_decision, "scale_limits"),
        bounded_paper_ready=_coalesce_bool(
            row, project_decision, "bounded_paper_ready"
        ),
        compute_scale_blocked=_coalesce_bool(
            row, project_decision, "compute_scale_blocked"
        ),
        followup_recommended=_coalesce_bool(
            row, project_decision, "followup_recommended"
        ),
        followup_type=_coalesce_text(row, project_decision, "followup_type"),
        followup_title=_coalesce_text(row, project_decision, "followup_title"),
        followup_hypothesis=_coalesce_text(
            row, project_decision, "followup_hypothesis"
        ),
        followup_required_evidence_count=_json_len(
            row.get("followup_required_evidence")
            or project_decision.get("followup_required_evidence")
        ),
        followup_success_threshold=_coalesce_text(
            row, project_decision, "followup_success_threshold"
        ),
        followup_stop_condition=_coalesce_text(
            row, project_decision, "followup_stop_condition"
        ),
        recommended_next_action=_coalesce_text(
            row,
            project_decision,
            "recommended_next_action",
            prefer_payload=True,
        ),
        stop_reason=_coalesce_text(
            row, project_decision, "stop_reason", prefer_payload=True
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


def _decision_rows_from_mappings(rows: list[dict[str, Any]]) -> list[DecisionRow]:
    decisions: list[DecisionRow] = []
    for row in rows:
        decision = _decision_from_mapping(row)
        if decision is not None:
            decisions.append(decision)
    return decisions


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
    return [
        _candidate_from_mapping(dict(row)) for row in candidate_rows
    ], _decision_rows_from_mappings([dict(row) for row in decision_rows])


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
        decisions = _decision_rows_from_mappings(
            _load_json_rows(args.decision_json) if args.decision_json else []
        )
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
