from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from enoch_control_plane.research_quality.artifacts import build_quality_report
from enoch_control_plane.research_quality.datasets import (
    CandidateRow,
    DecisionRow,
    classify_decision_quality,
)
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
    assert (
        report["summary"]["problem_counts"]["supported_but_negative_requires_review"]
        == 1
    )
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


def test_supported_useful_signal_with_scope_limits_is_not_a_quality_problem() -> None:
    score, problems = classify_decision_quality(
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
            recommended_next_action="Stop as no-paper useful-signal evidence; any paper attempt requires broader validation.",
            stop_reason="Scoped direct validation supports the mechanism but remains too narrow for publication-grade claims.",
            created_at="2026-05-11T00:00:00Z",
            research_outcome="useful_signal",
            claim_scope="On a GPT-2-small local benchmark, the mechanism outperformed the named baseline at bounded retention settings.",
            scale_limits="Single local model and dataset only; no larger model families, production serving, or long-context tasks.",
            bounded_paper_ready=False,
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
                    "expected_artifacts": [
                        "run_notes.md",
                        "metrics.json",
                        "failure_cases.json",
                    ],
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

    candidates_before = candidates.read_text(encoding="utf-8")
    decisions_before = decisions.read_text(encoding="utf-8")

    assert (
        dspy_research_quality.main(
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

    assert candidates.read_text(encoding="utf-8") == candidates_before
    assert decisions.read_text(encoding="utf-8") == decisions_before
    assert sorted(path.name for path in tmp_path.iterdir()) == [
        "candidates.json",
        "decisions.json",
        "report.json",
    ]

    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["summary"]["candidate_count"] == 1
    assert report["summary"]["decision_count"] == 1
    assert report["metadata"]["dspy_runtime_used"] is False


def test_dspy_research_quality_parses_string_booleans() -> None:
    row = dspy_research_quality._decision_from_mapping(
        {
            "project_id": "project-1",
            "payload_json": {
                "project_decision": {
                    "project_decision": "finalize_negative",
                    "hypothesis_status": "supported",
                    "followup_recommended": "false",
                    "bounded_paper_ready": "false",
                    "compute_scale_blocked": "true",
                }
            },
        }
    )

    assert row is not None
    assert row.followup_recommended is False
    assert row.bounded_paper_ready is False
    assert row.compute_scale_blocked is True


def test_dspy_research_quality_skips_active_placeholder_decisions(
    tmp_path: Path,
) -> None:
    candidates = tmp_path / "candidates.json"
    decisions = tmp_path / "decisions.json"
    output = tmp_path / "report.json"
    candidates.write_text("[]", encoding="utf-8")
    decisions.write_text(
        json.dumps(
            [
                {
                    "project_id": "active-project",
                    "project_name": "Active Project",
                    "run_id": "active-run",
                    "payload_json": {
                        "project_decision": "scaffold_ready_for_worker",
                        "summary": "bootstrap placeholder awaiting worker output",
                    },
                    "created_at": "2026-06-30T06:00:00Z",
                },
                {
                    "project_id": "complete-project",
                    "project_name": "Complete Project",
                    "run_id": "complete-run",
                    "payload_json": {
                        "project_decision": {
                            "project_decision": "finalize_negative",
                            "hypothesis_status": "mixed",
                            "evidence_strength": "moderate",
                            "stop_reason": "The bounded result was useful but not paper-ready.",
                            "recommended_next_action": "Run a stronger follow-up.",
                        }
                    },
                    "created_at": "2026-06-30T05:00:00Z",
                },
            ]
        ),
        encoding="utf-8",
    )

    assert (
        dspy_research_quality.main(
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

    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["summary"]["decision_count"] == 1
    assert report["decision_scores"][0]["project_id"] == "complete-project"
    assert "unknown_decision" not in report["summary"]["problem_counts"]


def test_dspy_research_quality_uses_run_notes_final_decision_for_stale_scaffold(
    tmp_path: Path, monkeypatch: Any
) -> None:
    project_dir = tmp_path / "project-1"
    project_dir.mkdir()
    (project_dir / "run_notes.md").write_text(
        """
## Final Decision

Decision: `finalize_negative`

Research outcome: `useful_signal`

Rationale: this bounded toy mechanism is useful signal, but it is not publication-grade evidence for a paper-positive claim.
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(dspy_research_quality, "DEFAULT_PROJECT_ROOTS", (tmp_path,))

    row = dspy_research_quality._decision_from_mapping(
        {
            "project_id": "project-1",
            "project_name": "Project 1",
            "run_id": "run-1",
            "payload_json": {
                "project_decision": {
                    "decision": "scaffold_ready_for_worker",
                    "summary": "Bootstrap placeholder; replace with final project decision before handoff.",
                }
            },
        }
    )

    assert row.decision == "finalize_negative"
    assert row.hypothesis_status == "supported"
    assert row.evidence_strength == "moderate"
    assert row.research_outcome == "useful_signal"
    assert row.bounded_paper_ready is False
    _score, problems = classify_decision_quality(row)
    assert "unknown_decision" not in problems
    assert "weak_or_missing_evidence_strength" not in problems


def test_run_notes_fallback_rejects_project_id_path_escape(
    tmp_path: Path, monkeypatch: Any
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "run_notes.md").write_text(
        """
## Final Decision

Decision: `finalize_negative`

Rationale: attacker-controlled rationale outside the project root.
""",
        encoding="utf-8",
    )
    root = tmp_path / "projects"
    root.mkdir()
    monkeypatch.setattr(dspy_research_quality, "DEFAULT_PROJECT_ROOTS", (root,))

    assert (
        dspy_research_quality._project_decision_from_run_notes_fallback(
            {"project_id": "../outside"}
        )
        == {}
    )
    assert (
        dspy_research_quality._project_decision_from_run_notes_fallback(
            {"project_id": str(outside)}
        )
        == {}
    )


def test_run_notes_fallback_rejects_symlink_escape(
    tmp_path: Path, monkeypatch: Any
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "run_notes.md").write_text(
        """
## Final Decision

Decision: `finalize_negative`

Rationale: attacker-controlled rationale outside the project root.
""",
        encoding="utf-8",
    )
    root = tmp_path / "projects"
    root.mkdir()
    (root / "linked-project").symlink_to(outside, target_is_directory=True)
    monkeypatch.setattr(dspy_research_quality, "DEFAULT_PROJECT_ROOTS", (root,))

    assert (
        dspy_research_quality._project_decision_from_run_notes_fallback(
            {"project_id": "linked-project"}
        )
        == {}
    )


def test_supported_negative_does_not_pass_on_broad_real_or_direct_words_only() -> None:
    row = DecisionRow(
        project_id="p",
        project_name="P",
        run_id="r",
        decision="finalize_negative",
        hypothesis_status="supported",
        evidence_strength="moderate",
        confidence="medium",
        bounded_paper_ready=False,
        followup_recommended=False,
        followup_type="",
        followup_title="",
        followup_hypothesis="",
        followup_required_evidence_count=0,
        followup_success_threshold="",
        followup_stop_condition="",
        stop_reason="The run has real direct evidence and says do not write a paper, but gives no concrete scale limitation.",
        recommended_next_action="Stop at depth 4 because direct evidence exists, with no concrete local compute limitation.",
        created_at="2026-05-19T00:00:00Z",
    )

    _score, problems = classify_decision_quality(row)

    assert "supported_but_negative_requires_review" in problems
