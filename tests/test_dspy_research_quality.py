from __future__ import annotations

import json
from pathlib import Path

from enoch_control_plane.research_quality.artifacts import build_quality_report
from enoch_control_plane.research_quality.datasets import CandidateRow, DecisionRow, classify_decision_quality
from scripts import dspy_research_quality


def test_quality_report_flags_supported_negative_decisions() -> None:
    report = build_quality_report(
        candidates=[
            CandidateRow(
                candidate_id="candidate-1",
                title="Anchor KV Compression",
                category="kv-compression",
                status="admitted",
                total_score=76.5,
                mechanism="retain exact anchor tokens",
                baseline_to_beat="uniform KV compression",
                success_threshold=">= 0.95 cosine",
                kill_condition="stop below threshold",
                required_evidence_count=4,
                expected_artifact_count=4,
            )
        ],
        decisions=[
            DecisionRow(
                project_id="project-1",
                project_name="Project 1",
                run_id="run-1",
                decision="finalize_negative",
                hypothesis_status="supported",
                evidence_strength="moderate",
                confidence="medium",
                followup_recommended=False,
                followup_type="",
                followup_title="",
                followup_hypothesis="",
                followup_required_evidence_count=0,
                followup_success_threshold="",
                followup_stop_condition="",
                recommended_next_action="Stop because partial support did not pass paper threshold.",
                stop_reason="Partial support was insufficient for paper-positive decision.",
                created_at="2026-05-11T00:00:00Z",
            )
        ],
    )

    assert report["mode"] == "read_only_sidecar"
    assert report["runtime_effect"] == "none"
    assert report["summary"]["candidate_count"] == 1
    assert report["summary"]["decision_count"] == 1
    assert report["summary"]["problem_counts"]["supported_but_negative_requires_review"] == 1
    assert "Inspect supported-but-negative decisions" in report["recommendations"][0]



def test_supported_negative_with_bounded_followup_is_not_a_quality_problem() -> None:
    score, problems = classify_decision_quality(
        DecisionRow(
            project_id="project-1",
            project_name="Project 1",
            run_id="run-1",
            decision="finalize_negative",
            hypothesis_status="supported",
            evidence_strength="moderate",
            confidence="medium",
            followup_recommended=True,
            followup_type="deepen",
            followup_title="Real-framework follow-up",
            followup_hypothesis="A real framework test should validate whether the proxy-supported mechanism holds.",
            followup_required_evidence_count=4,
            followup_success_threshold="At least 95% success with less than 2x overhead.",
            followup_stop_condition="Stop if framework-native checks already catch the faults or overhead exceeds 2x.",
            recommended_next_action="Stop this run as proxy-only/no-paper; launch a separate bounded real-framework follow-up.",
            stop_reason="Synthetic proxy evidence supports the narrow mechanism but is insufficient for a paper-positive decision on a real checkpoint stack.",
            created_at="2026-05-11T00:00:00Z",
        )
    )

    assert score == 1.0
    assert "supported_but_negative_requires_review" not in problems


def test_decision_quality_flags_thin_followup() -> None:
    score, problems = classify_decision_quality(
        DecisionRow(
            project_id="project-1",
            project_name="Project 1",
            run_id="run-1",
            decision="finalize_negative",
            hypothesis_status="mixed",
            evidence_strength="moderate",
            confidence="medium",
            followup_recommended=True,
            followup_type="branch",
            followup_title="Better branch",
            followup_hypothesis="",
            followup_required_evidence_count=1,
            followup_success_threshold="",
            followup_stop_condition="",
            recommended_next_action="Run a bounded adjacent test with concrete metrics.",
            stop_reason="The current proxy failed the paper gate.",
            created_at="2026-05-11T00:00:00Z",
        )
    )

    assert score < 1.0
    assert "followup_missing_hypothesis" in problems
    assert "followup_thin_required_evidence" in problems
    assert "followup_missing_success_threshold" in problems
    assert "followup_missing_stop_condition" in problems


def test_dspy_research_quality_script_accepts_fixture_json(tmp_path: Path) -> None:
    candidates = tmp_path / "candidates.json"
    decisions = tmp_path / "decisions.json"
    output = tmp_path / "report.json"
    candidates.write_text(
        json.dumps(
            [
                {
                    "candidate_id": "candidate-1",
                    "title": "Candidate 1",
                    "category": "spec-decoding",
                    "status": "admitted",
                    "total_score": 75.0,
                    "required_evidence": ["baseline", "metrics", "failure cases"],
                    "expected_artifacts": ["run_notes.md", "metrics.json", "failure_cases.json"],
                    "success_threshold": "1.2x speedup",
                    "kill_condition": "stop below 1.1x",
                }
            ]
        ),
        encoding="utf-8",
    )
    decisions.write_text(
        json.dumps(
            [
                {
                    "project_id": "project-1",
                    "project_name": "Project 1",
                    "run_id": "run-1",
                    "payload_json": {
                        "project_decision": {
                            "project_decision": "finalize_negative",
                            "hypothesis_status": "unsupported",
                            "evidence_strength": "moderate",
                            "recommended_next_action": "Stop because the baseline won.",
                            "stop_reason": "The measured result did not beat the baseline.",
                        }
                    },
                    "created_at": "2026-05-11T00:00:00Z",
                }
            ]
        ),
        encoding="utf-8",
    )

    assert dspy_research_quality.main(["--candidate-json", str(candidates), "--decision-json", str(decisions), "--output", str(output)]) == 0

    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["summary"]["candidate_count"] == 1
    assert report["summary"]["decision_count"] == 1
    assert report["metadata"]["dspy_runtime_used"] is False
