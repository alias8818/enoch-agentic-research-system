from __future__ import annotations

import json
from pathlib import Path

from enoch_control_plane.source_lineage.status import classify_source_lineage_report, load_latest_source_lineage_status


def test_classify_source_lineage_report_clean() -> None:
    status = classify_source_lineage_report(
        {
            "schema_version": "enoch_source_lineage_report_v1",
            "status": "clean",
            "counts": {"candidates": 2, "followups": 1, "sources": 3, "lineages": 3, "problems": 0},
            "problem_counts": {},
            "problems": [],
        },
        report_path="/tmp/source-lineage.json",
        report_mtime="2026-05-19T18:00:00Z",
    )

    assert status["ok"] is True
    assert status["status"] == "clean"
    assert status["candidates_checked"] == 2
    assert status["followups_checked"] == 1
    assert status["missing_sources"] == 0
    assert status["missing_lineage"] == 0
    assert status["problem_counts"] == {}


def test_classify_source_lineage_report_blocks_missing_sources_and_lineage() -> None:
    status = classify_source_lineage_report(
        {
            "schema_version": "enoch_source_lineage_report_v1",
            "status": "blocked",
            "counts": {"candidates": 1, "followups": 1, "sources": 0, "lineages": 0, "problems": 3},
            "problem_counts": {
                "candidate_source_url_missing_source": 1,
                "followup_missing_parent_run_lineage": 1,
                "followup_missing_parent_project_lineage": 1,
            },
            "problems": [
                {"kind": "candidate_source_url_missing_source", "candidate_id": "c1"},
                {"kind": "followup_missing_parent_run_lineage", "project_id": "f1"},
                {"kind": "followup_missing_parent_project_lineage", "project_id": "f1"},
            ],
        },
        report_path="/tmp/source-lineage.json",
        report_mtime="2026-05-19T18:00:00Z",
    )

    assert status["ok"] is False
    assert status["status"] == "blocked"
    assert status["missing_sources"] == 1
    assert status["missing_lineage"] == 2
    assert status["problem_counts"]["candidate_source_url_missing_source"] == 1
    assert status["problem_details"][0]["kind"] == "candidate_source_url_missing_source"


def test_missing_source_lineage_report_blocks_readiness() -> None:
    status = load_latest_source_lineage_status(("/tmp/does-not-exist-source-lineage.json",))

    assert status["ok"] is False
    assert status["status"] == "blocked"
    assert status["problem_counts"] == {"missing_source_lineage_report": 1}


def test_load_latest_source_lineage_status_reads_report(tmp_path: Path) -> None:
    report = tmp_path / "latest-report.json"
    report.write_text(
        json.dumps(
            {
                "schema_version": "enoch_source_lineage_report_v1",
                "status": "clean",
                "counts": {"candidates": 0, "followups": 1, "sources": 4, "lineages": 5, "problems": 0},
                "problem_counts": {},
                "problems": [],
            }
        ),
        encoding="utf-8",
    )

    status = load_latest_source_lineage_status((str(report),))

    assert status["ok"] is True
    assert status["report_path"] == str(report)
    assert status["followups_checked"] == 1
