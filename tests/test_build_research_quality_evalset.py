from __future__ import annotations

import json
from pathlib import Path

from scripts import build_research_quality_evalset as evalset


def _write_json(path: Path, rows: list[dict]) -> None:
    path.write_text(json.dumps(rows), encoding="utf-8")


def test_build_evalset_script_emits_required_case_types(tmp_path: Path) -> None:
    candidates = tmp_path / "candidates.json"
    decisions = tmp_path / "decisions.json"
    output = tmp_path / "evalset.jsonl"
    _write_json(
        candidates,
        [
            {
                "candidate_id": "candidate-a",
                "title": "Exact Anchor KV Selection",
                "category": "kv-compression",
                "status": "admitted",
                "total_score": 82,
                "mechanism": "select exact anchor KV tokens by query overlap",
                "baseline_to_beat": "recency KV retention",
                "success_threshold": "beat recency by 10 points",
                "kill_condition": "stop if no lift",
                "required_evidence": ["baseline", "metrics", "failure cases"],
                "expected_artifacts": [
                    "run_notes.md",
                    "metrics.json",
                    "failure_cases.json",
                ],
                "similar_prior_projects": [{"project_id": "old-anchor"}],
                "novelty_comparison": "",
            },
            {
                "candidate_id": "candidate-b",
                "title": "Exact Anchor KV Selection Variant",
                "category": "kv-compression",
                "status": "generated",
                "total_score": 79,
                "mechanism": "select exact anchor KV tokens by query overlap",
                "baseline_to_beat": "recency KV retention",
                "success_threshold": "beat recency by 10 points",
                "kill_condition": "stop if no lift",
                "required_evidence": ["baseline", "metrics", "failure cases"],
                "expected_artifacts": [
                    "run_notes.md",
                    "metrics.json",
                    "failure_cases.json",
                ],
            },
        ],
    )
    _write_json(
        decisions,
        [
            {
                "project_id": "supported-neg",
                "project_name": "Supported Negative",
                "run_id": "run-supported-neg",
                "payload_json": {
                    "project_decision": {
                        "project_decision": "finalize_negative",
                        "hypothesis_status": "supported",
                        "evidence_strength": "moderate",
                        "recommended_next_action": "Stop because proxy-only support is insufficient for paper writing.",
                        "stop_reason": "Proxy-only evidence supports the mechanism but not enough for paper-positive direct validation.",
                    }
                },
                "created_at": "2026-05-11T00:00:00Z",
            },
            {
                "project_id": "depth-capped",
                "project_name": "Depth Capped",
                "run_id": "run-depth-capped",
                "followup_depth": 2,
                "payload_json": {
                    "project_decision": {
                        "project_decision": "finalize_negative",
                        "hypothesis_status": "mixed",
                        "evidence_strength": "moderate",
                        "recommended_next_action": "Stop because max follow-up depth is reached and further work needs manual branching.",
                        "stop_reason": "The current adjacent run is mixed and does not establish a stronger mechanism.",
                    }
                },
                "created_at": "2026-05-11T00:00:01Z",
            },
            {
                "project_id": "bounded-followup",
                "project_name": "Bounded Followup",
                "run_id": "run-bounded-followup",
                "followup_depth": 1,
                "followup_recommended": True,
                "followup_title": "Direct real-model validation",
                "followup_hypothesis": "A direct real-model test should validate whether the proxy result survives stronger baselines.",
                "followup_required_evidence": ["baseline", "metrics", "failure cases"],
                "followup_success_threshold": "Beat baseline by 10 points.",
                "followup_stop_condition": "Stop if the direct test fails to beat baseline.",
                "payload_json": {
                    "project_decision": {
                        "project_decision": "finalize_negative",
                        "hypothesis_status": "mixed",
                        "evidence_strength": "moderate",
                        "recommended_next_action": "Launch the bounded direct real-model follow-up with clear stop condition.",
                        "stop_reason": "Current proxy result is not paper-ready but suggests a changed direct validation branch.",
                    }
                },
                "created_at": "2026-05-11T00:00:02Z",
            },
        ],
    )

    assert (
        evalset.main(
            [
                "--candidate-json",
                str(candidates),
                "--decision-json",
                str(decisions),
                "--output",
                str(output),
            ]
        )
        == 0
    )
    rows = [
        json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()
    ]
    case_types = {row["case_type"] for row in rows}
    assert "duplicateish_candidate" in case_types
    assert "proxy_only_positive" in case_types
    assert "supported_but_negative_warning" in case_types
    assert "max_depth_followup_ending" in case_types
    assert "useful_adjacent_followup" in case_types
    assert all(
        row["schema_version"] == "enoch_research_quality_evalcase_v1" for row in rows
    )
    assert all("expected_behavior" in row and row["expected_behavior"] for row in rows)


def test_build_evalset_is_read_only_for_fixture_inputs(tmp_path: Path) -> None:
    candidates = tmp_path / "candidates.json"
    decisions = tmp_path / "decisions.json"
    output = tmp_path / "evalset.jsonl"
    _write_json(candidates, [])
    _write_json(decisions, [])
    before_candidates = candidates.read_text(encoding="utf-8")
    before_decisions = decisions.read_text(encoding="utf-8")

    assert (
        evalset.main(
            [
                "--candidate-json",
                str(candidates),
                "--decision-json",
                str(decisions),
                "--output",
                str(output),
            ]
        )
        == 0
    )

    assert candidates.read_text(encoding="utf-8") == before_candidates
    assert decisions.read_text(encoding="utf-8") == before_decisions
    assert output.exists()
    assert output.read_text(encoding="utf-8") == ""
