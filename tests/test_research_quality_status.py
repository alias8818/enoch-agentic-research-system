from __future__ import annotations

import json
from pathlib import Path

from enoch_control_plane.research_quality.status import classify_quality_report, load_latest_quality_status


def _report_with_decision(problem: str, *, decision: str = "finalize_negative", hypothesis_status: str = "mixed") -> dict:
    return {
        "schema_version": "enoch_research_quality_report_v1",
        "generated_at": "2026-05-11T00:00:00Z",
        "summary": {
            "candidate_count": 0,
            "decision_count": 1,
            "problem_counts": {problem: 1},
        },
        "candidate_scores": [],
        "decision_scores": [
            {
                "project_id": "p1",
                "project_name": "Project 1",
                "run_id": "r1",
                "decision": decision,
                "hypothesis_status": hypothesis_status,
                "evidence_strength": "weak",
                "problems": [problem],
            }
        ],
    }


def test_weak_evidence_on_negative_mixed_result_is_warning_not_blocked() -> None:
    status = classify_quality_report(_report_with_decision("weak_or_missing_evidence_strength"), report_path="/tmp/report.json", report_mtime="2026-05-11T00:00:01Z")

    assert status["ok"] is True
    assert status["status"] == "warnings"
    assert status["decisions_checked"] == 1
    assert status["problem_counts"] == {"weak_or_missing_evidence_strength": 1}
    assert status["severity_counts"] == {"warning": 1}
    assert status["report_path"] == "/tmp/report.json"
    assert status["report_mtime"] == "2026-05-11T00:00:01Z"


def test_structural_decision_problem_is_blocked() -> None:
    status = classify_quality_report(_report_with_decision("unknown_decision", decision="unknown", hypothesis_status="unknown"))

    assert status["ok"] is False
    assert status["status"] == "blocked"
    assert status["severity_counts"] == {"blocked": 1}


def test_load_latest_quality_status_reads_report_without_mutating_it(tmp_path: Path) -> None:
    report_path = tmp_path / "quality.json"
    report = _report_with_decision("weak_or_missing_evidence_strength")
    report_path.write_text(json.dumps(report), encoding="utf-8")
    before = report_path.read_text(encoding="utf-8")

    status = load_latest_quality_status([str(report_path)])

    assert status["status"] == "warnings"
    assert status["report_path"] == str(report_path)
    assert report_path.read_text(encoding="utf-8") == before


def test_missing_quality_report_blocks_readiness() -> None:
    status = load_latest_quality_status(["/definitely/missing/research-quality.json"])

    assert status["ok"] is False
    assert status["status"] == "blocked"
    assert status["problem_counts"] == {"missing_quality_report": 1}
