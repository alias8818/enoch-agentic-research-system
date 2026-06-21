from __future__ import annotations

import json
from pathlib import Path

from enoch_control_plane.research_quality.status import (
    classify_quality_report,
    load_latest_quality_status,
)


def _report_with_decision(
    problem: str,
    *,
    decision: str = "finalize_negative",
    hypothesis_status: str = "mixed",
) -> dict:
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


def test_weak_evidence_on_blocked_inconclusive_result_is_warning_not_blocked() -> None:
    status = classify_quality_report(
        _report_with_decision(
            "weak_or_missing_evidence_strength",
            decision="blocked",
            hypothesis_status="inconclusive",
        ),
        report_path="/tmp/report.json",
        report_mtime="2026-05-11T00:00:01Z",
    )

    assert status["ok"] is True
    assert status["status"] == "warnings"
    assert status["problem_counts"] == {"weak_or_missing_evidence_strength": 1}
    assert status["severity_counts"] == {"warning": 1}


def test_weak_evidence_on_negative_mixed_result_is_warning_not_blocked() -> None:
    status = classify_quality_report(
        _report_with_decision("weak_or_missing_evidence_strength"),
        report_path="/tmp/report.json",
        report_mtime="2026-05-11T00:00:01Z",
    )

    assert status["ok"] is True
    assert status["status"] == "warnings"
    assert status["decisions_checked"] == 1
    assert status["problem_counts"] == {"weak_or_missing_evidence_strength": 1}
    assert status["severity_counts"] == {"warning": 1}
    assert status["report_path"] == "/tmp/report.json"
    assert status["report_mtime"] == "2026-05-11T00:00:01Z"


def test_weak_evidence_on_supported_useful_signal_with_bounded_followup_is_warning_not_blocked() -> (
    None
):
    report = _report_with_decision(
        "weak_or_missing_evidence_strength",
        decision="finalize_negative",
        hypothesis_status="supported",
    )
    report["decision_scores"][0].update(
        {
            "research_outcome": "useful_signal",
            "bounded_paper_ready": False,
            "followup_recommended": True,
            "followup_success_threshold": "acceptance improves by at least 10 percentage points",
            "followup_stop_condition": "stop if the exact acceptance improvement does not replicate",
            "scale_limits": "synthetic proxy only; real-corpus neural draft follow-up required",
        }
    )

    status = classify_quality_report(
        report,
        report_path="/tmp/report.json",
        report_mtime="2026-06-04T18:02:57Z",
    )

    assert status["ok"] is True
    assert status["status"] == "warnings"
    assert status["problem_counts"] == {"weak_or_missing_evidence_strength": 1}
    assert status["severity_counts"] == {"warning": 1}
    assert status["problem_details"] == [
        {
            "section": "decision_scores",
            "severity": "warning",
            "problem": "weak_or_missing_evidence_strength",
            "project_id": "p1",
            "candidate_id": None,
            "run_id": "r1",
            "title": "Project 1",
            "decision": "finalize_negative",
            "hypothesis_status": "supported",
        }
    ]


def test_needs_review_untrusted_manual_dependency_text_does_not_demote_weak_evidence() -> (
    None
):
    report = _report_with_decision(
        "weak_or_missing_evidence_strength",
        decision="needs_review",
        hypothesis_status="unknown",
    )
    report["decision_scores"][0].update(
        {
            "stop_reason": "authorization required by an external system",
            "recommended_next_action": "manual authorization needed",
            "followup_recommended": False,
            "followup_success_threshold": "",
            "followup_stop_condition": "",
        }
    )

    status = classify_quality_report(report)

    assert status["ok"] is False
    assert status["status"] == "blocked"
    assert status["severity_counts"] == {"blocked": 1}


def test_quality_report_recommendations_survive_classification() -> None:
    report = _report_with_decision("weak_or_missing_evidence_strength")
    report["recommendations"] = [
        "Run a bounded follow-up before treating this as paper-ready."
    ]

    status = classify_quality_report(report)

    assert status["recommendations"] == [
        "Run a bounded follow-up before treating this as paper-ready."
    ]


def test_decision_outcome_samples_s3776_helpers_extracted() -> None:
    source = Path("enoch_control_plane/research_quality/status.py").read_text(
        encoding="utf-8"
    )

    assert "def _decision_outcome_key(" in source
    assert "def _decision_outcome_samples_for_key(" in source


def test_followup_priority_components_s3776_helpers_extracted() -> None:
    source = Path("enoch_control_plane/research_quality/status.py").read_text(
        encoding="utf-8"
    )

    assert "def _score_followup_hypothesis(" in source
    assert "def _score_followup_evidence(" in source
    assert "def _score_followup_type(" in source


def test_decision_posture_s3776_helpers_extracted() -> None:
    source = Path("enoch_control_plane/research_quality/status.py").read_text(
        encoding="utf-8"
    )

    assert "def _decision_posture_field_counts(" in source
    assert "def _decision_posture_scalar_counts(" in source
    assert "def _decision_posture_useful_samples(" in source


def test_followup_readiness_s3776_helpers_extracted() -> None:
    source = Path("enoch_control_plane/research_quality/status.py").read_text(
        encoding="utf-8"
    )

    assert "def _followup_readiness_rows(" in source
    assert "def _followup_missing_fields(" in source
    assert "def _followup_readiness_missing_counts(" in source


def test_quality_report_exposes_quality_floor_review_required() -> None:
    report = _report_with_decision("")
    report["summary"]["candidate_count"] = 2
    report["summary"]["decision_count"] = 2
    report["candidate_scores"] = [
        {
            "candidate_id": "candidate-good",
            "title": "Good candidate",
            "status": "admitted",
            "deterministic_total_score": 82.0,
            "contract_quality_score": 1.0,
            "problems": [],
        },
        {
            "candidate_id": "candidate-low",
            "title": "Thin candidate",
            "status": "needs_review",
            "deterministic_total_score": 52.0,
            "contract_quality_score": 0.55,
            "problems": ["thin_expected_artifacts"],
        },
    ]
    report["decision_scores"] = [
        {
            "project_id": "project-good",
            "project_name": "Good project",
            "run_id": "run-good",
            "decision": "finalize_negative",
            "hypothesis_status": "unsupported",
            "evidence_strength": "moderate",
            "decision_quality_score": 0.85,
            "problems": [],
        },
        {
            "project_id": "project-low",
            "project_name": "Thin decision",
            "run_id": "run-low",
            "decision": "blocked",
            "hypothesis_status": "unknown",
            "evidence_strength": "weak",
            "decision_quality_score": 0.4,
            "problems": ["weak_or_missing_evidence_strength"],
        },
    ]

    status = classify_quality_report(report)

    assert status["quality_floor"] == {
        "available": True,
        "threshold": 0.7,
        "posture": "review_required",
        "candidates_checked": 2,
        "decisions_checked": 2,
        "candidate_below_floor_count": 1,
        "decision_below_floor_count": 1,
        "below_floor_count": 2,
        "candidate_samples": [
            {
                "candidate_id": "candidate-low",
                "title": "Thin candidate",
                "status": "needs_review",
                "score": 0.55,
                "problems": ["thin_expected_artifacts"],
            }
        ],
        "decision_samples": [
            {
                "project_id": "project-low",
                "project_name": "Thin decision",
                "run_id": "run-low",
                "decision": "blocked",
                "hypothesis_status": "unknown",
                "score": 0.4,
                "problems": ["weak_or_missing_evidence_strength"],
            }
        ],
        "operator_action": (
            "review 2 below-floor Research Quality artifacts before widening "
            "automation or treating outputs as externally useful"
        ),
    }


def test_quality_report_exposes_satisfied_quality_floor() -> None:
    report = _report_with_decision("")
    report["summary"]["candidate_count"] = 1
    report["summary"]["decision_count"] = 1
    report["candidate_scores"] = [
        {
            "candidate_id": "candidate-good",
            "title": "Good candidate",
            "status": "admitted",
            "deterministic_total_score": 82.0,
            "contract_quality_score": 1.0,
            "problems": [],
        }
    ]
    report["decision_scores"] = [
        {
            "project_id": "project-good",
            "project_name": "Good project",
            "run_id": "run-good",
            "decision": "finalize_negative",
            "hypothesis_status": "unsupported",
            "evidence_strength": "moderate",
            "decision_quality_score": 1.0,
            "problems": [],
        }
    ]

    status = classify_quality_report(report)

    assert status["quality_floor"]["posture"] == "satisfied"
    assert status["quality_floor"]["threshold"] == 0.7
    assert status["quality_floor"]["candidate_below_floor_count"] == 0
    assert status["quality_floor"]["decision_below_floor_count"] == 0
    assert status["quality_floor"]["below_floor_count"] == 0
    assert status["quality_floor"]["operator_action"] == (
        "quality floor satisfied across 1 candidates and 1 decisions"
    )


def test_quality_report_portfolio_summary_survives_classification() -> None:
    report = _report_with_decision("")
    report["summary"].update(
        {
            "candidate_count": 100,
            "candidate_status_counts": {
                "admitted": 45,
                "needs_review": 53,
                "rejected": 2,
            },
            "decision_counts": [
                {
                    "decision": "finalize_negative",
                    "hypothesis_status": "mixed",
                    "count": 50,
                },
                {
                    "decision": "finalize_negative",
                    "hypothesis_status": "supported",
                    "count": 34,
                },
            ],
            "top_candidate_categories": [
                {"category": "home-training", "count": 22},
                {"category": "spec-decoding", "count": 18},
            ],
        }
    )
    report["candidate_scores"] = [
        {
            "candidate_id": "candidate-admitted",
            "title": "Admitted candidate",
            "status": "admitted",
            "deterministic_total_score": 76.4,
            "contract_quality_score": 1.0,
            "problems": [],
        },
        {
            "candidate_id": "candidate-needs-review",
            "title": "Needs review candidate",
            "status": "needs_review",
            "deterministic_total_score": 64.2,
            "contract_quality_score": 0.5,
            "problems": ["thin_expected_artifacts"],
        },
    ]
    report["decision_scores"] = [
        {
            "project_id": "project-mixed",
            "project_name": "Mixed project",
            "run_id": "run-mixed",
            "decision": "finalize_negative",
            "hypothesis_status": "mixed",
            "evidence_strength": "moderate",
            "research_outcome": "useful_signal",
            "bounded_paper_ready": False,
            "followup_recommended": True,
            "followup_type": "deepen",
            "followup_required_evidence_count": 4,
            "followup_title": "Mixed follow-up",
            "followup_success_threshold": "Mixed follow-up must improve accuracy by 5 points.",
            "followup_stop_condition": "Stop mixed follow-up if accuracy does not improve.",
            "recommended_next_action": "Run the mixed follow-up before treating this as paper-ready.",
            "problems": [],
        },
        {
            "project_id": "project-supported",
            "project_name": "Supported project",
            "run_id": "run-supported",
            "decision": "finalize_negative",
            "hypothesis_status": "supported",
            "evidence_strength": "moderate",
            "research_outcome": "useful_signal",
            "bounded_paper_ready": False,
            "followup_recommended": True,
            "followup_type": "deepen",
            "followup_required_evidence_count": 4,
            "followup_title": "Supported follow-up",
            "followup_success_threshold": "Supported follow-up must reproduce the effect.",
            "followup_stop_condition": "",
            "recommended_next_action": "Run the supported follow-up before treating this as paper-ready.",
            "problems": [],
        },
        {
            "project_id": "project-negative",
            "project_name": "Negative project",
            "run_id": "run-negative",
            "decision": "finalize_negative",
            "hypothesis_status": "unsupported",
            "evidence_strength": "moderate",
            "research_outcome": "negative",
            "bounded_paper_ready": False,
            "followup_recommended": False,
            "followup_type": "",
            "followup_required_evidence_count": 0,
            "followup_title": "",
            "followup_success_threshold": "",
            "followup_stop_condition": "",
            "recommended_next_action": "Stop this line.",
            "problems": [],
        },
    ]

    status = classify_quality_report(report)

    assert status["candidate_status_counts"] == {
        "admitted": 45,
        "needs_review": 53,
        "rejected": 2,
    }
    assert status["decision_outcome_counts"] == [
        {
            "decision": "finalize_negative",
            "hypothesis_status": "mixed",
            "count": 50,
        },
        {
            "decision": "finalize_negative",
            "hypothesis_status": "supported",
            "count": 34,
        },
    ]
    assert status["top_candidate_categories"] == [
        {"category": "home-training", "count": 22},
        {"category": "spec-decoding", "count": 18},
    ]
    assert status["candidate_status_samples"] == {
        "admitted": [
            {
                "candidate_id": "candidate-admitted",
                "title": "Admitted candidate",
                "status": "admitted",
                "deterministic_total_score": 76.4,
                "contract_quality_score": 1.0,
                "problems": [],
            }
        ],
        "needs_review": [
            {
                "candidate_id": "candidate-needs-review",
                "title": "Needs review candidate",
                "status": "needs_review",
                "deterministic_total_score": 64.2,
                "contract_quality_score": 0.5,
                "problems": ["thin_expected_artifacts"],
            }
        ],
    }
    assert status["decision_outcome_samples"] == [
        {
            "decision": "finalize_negative",
            "hypothesis_status": "mixed",
            "samples": [
                {
                    "project_id": "project-mixed",
                    "project_name": "Mixed project",
                    "run_id": "run-mixed",
                    "decision": "finalize_negative",
                    "hypothesis_status": "mixed",
                    "evidence_strength": "moderate",
                    "research_outcome": "useful_signal",
                    "followup_title": "Mixed follow-up",
                    "problems": [],
                }
            ],
        },
        {
            "decision": "finalize_negative",
            "hypothesis_status": "supported",
            "samples": [
                {
                    "project_id": "project-supported",
                    "project_name": "Supported project",
                    "run_id": "run-supported",
                    "decision": "finalize_negative",
                    "hypothesis_status": "supported",
                    "evidence_strength": "moderate",
                    "research_outcome": "useful_signal",
                    "followup_title": "Supported follow-up",
                    "problems": [],
                }
            ],
        },
    ]
    assert status["decision_posture"] == {
        "available": True,
        "decisions_checked": 3,
        "useful_signal_count": 2,
        "negative_count": 1,
        "bounded_paper_ready_count": 0,
        "followup_recommended_count": 2,
        "compute_scale_blocked_count": 0,
        "publication_posture": "followup_only",
        "research_outcome_counts": {"negative": 1, "useful_signal": 2},
        "hypothesis_status_counts": {"mixed": 1, "supported": 1, "unsupported": 1},
        "evidence_strength_counts": {"moderate": 3},
        "decision_counts": {
            "finalize_negative:mixed": 1,
            "finalize_negative:supported": 1,
            "finalize_negative:unsupported": 1,
        },
        "paper_readiness_blockers": {
            "available": True,
            "decisions_checked": 3,
            "paper_ready_count": 0,
            "blocker_counts": {
                "followup_required": 2,
                "mixed_or_unsupported_hypothesis": 2,
                "negative_outcome": 1,
                "non_strong_evidence": 3,
                "not_bounded_paper_ready": 3,
            },
            "samples": [
                {
                    "project_id": "project-mixed",
                    "project_name": "Mixed project",
                    "run_id": "run-mixed",
                    "hypothesis_status": "mixed",
                    "evidence_strength": "moderate",
                    "research_outcome": "useful_signal",
                    "bounded_paper_ready": False,
                    "followup_recommended": True,
                    "followup_title": "Mixed follow-up",
                    "recommended_next_action": (
                        "Run the mixed follow-up before treating this as paper-ready."
                    ),
                    "blocker_reasons": [
                        "not_bounded_paper_ready",
                        "non_strong_evidence",
                        "mixed_or_unsupported_hypothesis",
                        "followup_required",
                    ],
                },
                {
                    "project_id": "project-supported",
                    "project_name": "Supported project",
                    "run_id": "run-supported",
                    "hypothesis_status": "supported",
                    "evidence_strength": "moderate",
                    "research_outcome": "useful_signal",
                    "bounded_paper_ready": False,
                    "followup_recommended": True,
                    "followup_title": "Supported follow-up",
                    "recommended_next_action": (
                        "Run the supported follow-up before treating this as paper-ready."
                    ),
                    "blocker_reasons": [
                        "not_bounded_paper_ready",
                        "non_strong_evidence",
                        "followup_required",
                    ],
                },
                {
                    "project_id": "project-negative",
                    "project_name": "Negative project",
                    "run_id": "run-negative",
                    "hypothesis_status": "unsupported",
                    "evidence_strength": "moderate",
                    "research_outcome": "negative",
                    "bounded_paper_ready": False,
                    "followup_recommended": False,
                    "followup_title": "",
                    "recommended_next_action": "Stop this line.",
                    "blocker_reasons": [
                        "not_bounded_paper_ready",
                        "non_strong_evidence",
                        "mixed_or_unsupported_hypothesis",
                        "negative_outcome",
                    ],
                },
            ],
            "operator_action": (
                "no paper-ready decisions; dominant blocker is non-strong evidence "
                "across 3 decisions"
            ),
        },
        "representative_useful_signals": [
            {
                "project_id": "project-mixed",
                "project_name": "Mixed project",
                "run_id": "run-mixed",
                "decision": "finalize_negative",
                "hypothesis_status": "mixed",
                "evidence_strength": "moderate",
                "research_outcome": "useful_signal",
                "bounded_paper_ready": False,
                "followup_recommended": True,
                "followup_title": "Mixed follow-up",
                "recommended_next_action": "Run the mixed follow-up before treating this as paper-ready.",
            },
            {
                "project_id": "project-supported",
                "project_name": "Supported project",
                "run_id": "run-supported",
                "decision": "finalize_negative",
                "hypothesis_status": "supported",
                "evidence_strength": "moderate",
                "research_outcome": "useful_signal",
                "bounded_paper_ready": False,
                "followup_recommended": True,
                "followup_title": "Supported follow-up",
                "recommended_next_action": "Run the supported follow-up before treating this as paper-ready.",
            },
        ],
        "operator_action": (
            "useful signals are present but none are bounded-paper-ready; run or "
            "review the listed follow-ups before treating this as publication output"
        ),
    }
    assert status["followup_readiness"] == {
        "available": True,
        "recommended_count": 2,
        "bounded_ready_count": 1,
        "underspecified_count": 1,
        "missing_title_count": 0,
        "missing_success_threshold_count": 0,
        "missing_stop_condition_count": 1,
        "thin_required_evidence_count": 0,
        "followup_type_counts": {"deepen": 2},
        "ready_followups": [
            {
                "project_id": "project-mixed",
                "project_name": "Mixed project",
                "run_id": "run-mixed",
                "followup_type": "deepen",
                "followup_title": "Mixed follow-up",
                "followup_required_evidence_count": 4,
                "followup_success_threshold": (
                    "Mixed follow-up must improve accuracy by 5 points."
                ),
                "followup_stop_condition": (
                    "Stop mixed follow-up if accuracy does not improve."
                ),
                "recommended_next_action": (
                    "Run the mixed follow-up before treating this as paper-ready."
                ),
            }
        ],
        "prioritized_followups": [
            {
                "project_id": "project-mixed",
                "project_name": "Mixed project",
                "run_id": "run-mixed",
                "followup_type": "deepen",
                "followup_title": "Mixed follow-up",
                "followup_required_evidence_count": 4,
                "followup_success_threshold": (
                    "Mixed follow-up must improve accuracy by 5 points."
                ),
                "followup_stop_condition": (
                    "Stop mixed follow-up if accuracy does not improve."
                ),
                "recommended_next_action": (
                    "Run the mixed follow-up before treating this as paper-ready."
                ),
                "hypothesis_status": "mixed",
                "evidence_strength": "moderate",
                "priority_score": 75,
                "priority_reasons": [
                    "mixed_hypothesis",
                    "moderate_evidence",
                    "deepen_followup",
                    "4_required_evidence_items",
                    "explicit_success_and_stop_bounds",
                ],
            }
        ],
        "underspecified_followups": [
            {
                "project_id": "project-supported",
                "project_name": "Supported project",
                "run_id": "run-supported",
                "followup_type": "deepen",
                "followup_title": "Supported follow-up",
                "followup_required_evidence_count": 4,
                "followup_success_threshold": (
                    "Supported follow-up must reproduce the effect."
                ),
                "followup_stop_condition": "",
                "recommended_next_action": (
                    "Run the supported follow-up before treating this as paper-ready."
                ),
                "missing_fields": ["missing_stop_condition"],
            }
        ],
        "operator_action": (
            "1 recommended follow-up is underspecified; fill missing readiness "
            "fields before queueing it"
        ),
    }


def test_followup_readiness_prioritizes_supported_ready_followups() -> None:
    report = _report_with_decision("")
    report["summary"]["decision_count"] = 2
    report["decision_scores"] = [
        {
            "project_id": "project-mixed",
            "project_name": "Mixed project",
            "run_id": "run-mixed",
            "hypothesis_status": "mixed",
            "evidence_strength": "moderate",
            "followup_recommended": True,
            "followup_type": "deepen",
            "followup_title": "Mixed follow-up",
            "followup_required_evidence_count": 4,
            "followup_success_threshold": "Mixed threshold.",
            "followup_stop_condition": "Mixed stop.",
            "recommended_next_action": "Run mixed.",
        },
        {
            "project_id": "project-supported",
            "project_name": "Supported project",
            "run_id": "run-supported",
            "hypothesis_status": "supported",
            "evidence_strength": "moderate",
            "followup_recommended": True,
            "followup_type": "deepen",
            "followup_title": "Supported follow-up",
            "followup_required_evidence_count": 4,
            "followup_success_threshold": "Supported threshold.",
            "followup_stop_condition": "Supported stop.",
            "recommended_next_action": "Run supported.",
        },
    ]

    status = classify_quality_report(report)

    prioritized = status["followup_readiness"]["prioritized_followups"]
    assert [row["project_id"] for row in prioritized] == [
        "project-supported",
        "project-mixed",
    ]
    assert prioritized[0]["priority_score"] == 90
    assert prioritized[0]["priority_reasons"] == [
        "supported_hypothesis",
        "moderate_evidence",
        "deepen_followup",
        "4_required_evidence_items",
        "explicit_success_and_stop_bounds",
    ]


def test_followup_readiness_counts_list_evidence_when_count_is_absent() -> None:
    report = _report_with_decision("")
    report["summary"]["decision_count"] = 1
    report["decision_scores"] = [
        {
            "project_id": "project-list-evidence",
            "project_name": "Project List Evidence",
            "run_id": "run-list-evidence",
            "hypothesis_status": "supported",
            "evidence_strength": "moderate",
            "followup_recommended": True,
            "followup_type": "deepen",
            "followup_title": "List evidence follow-up",
            "followup_required_evidence": [
                "held-out metric",
                "baseline comparison",
                "",
            ],
            "followup_success_threshold": "Improve by 5 points.",
            "followup_stop_condition": "Stop if there is no lift.",
            "recommended_next_action": "Run list evidence follow-up.",
        }
    ]

    status = classify_quality_report(report)

    readiness = status["followup_readiness"]
    assert readiness["bounded_ready_count"] == 1
    assert readiness["thin_required_evidence_count"] == 0
    assert readiness["ready_followups"][0]["followup_required_evidence_count"] == 2
    assert readiness["prioritized_followups"][0]["project_id"] == (
        "project-list-evidence"
    )


def test_weak_evidence_on_needs_review_inconclusive_with_bounded_followup_is_warning() -> (
    None
):
    report = _report_with_decision(
        "weak_or_missing_evidence_strength",
        decision="needs_review",
        hypothesis_status="inconclusive",
    )
    report["decision_scores"][0].update(
        {
            "followup_recommended": True,
            "followup_success_threshold": "Run a two-rater blinded adjudication and require agreement >= 0.60.",
            "followup_stop_condition": "Stop if agreement is below 0.40 after calibration.",
            "research_outcome": "needs_review",
            "claim_scope": "Autonomous run generated review packets but cannot supply human labels.",
            "scale_limits": "No human adjudications were obtained, so direct target evidence is missing.",
            "bounded_paper_ready": False,
        }
    )

    status = classify_quality_report(report)

    assert status["ok"] is True
    assert status["status"] == "warnings"
    assert status["problem_counts"] == {"weak_or_missing_evidence_strength": 1}
    assert status["severity_counts"] == {"warning": 1}


def test_weak_evidence_on_needs_review_inconclusive_gated_auth_is_warning() -> None:
    report = _report_with_decision(
        "weak_or_missing_evidence_strength",
        decision="needs_review",
        hypothesis_status="inconclusive",
    )
    report["decision_scores"][0].update(
        {
            "evidence_strength": "weak",
            "followup_recommended": False,
            "followup_success_threshold": "",
            "followup_stop_condition": "",
            "research_outcome": "needs_review",
            "bounded_paper_ready": False,
            "stop_reason": "Needs review because direct validation requires manual/private Hugging Face gated-model authorization.",
            "recommended_next_action": "Obtain authorized access to the official checkpoint, then rerun the benchmark.",
        }
    )

    status = classify_quality_report(report)

    assert status["ok"] is True
    assert status["status"] == "warnings"
    assert status["problem_counts"] == {"weak_or_missing_evidence_strength": 1}
    assert status["severity_counts"] == {"warning": 1}


def test_supported_negative_depth_capped_proxy_result_is_info_not_amber() -> None:
    report = _report_with_decision(
        "supported_but_negative_requires_review",
        decision="finalize_negative",
        hypothesis_status="supported",
    )
    report["decision_scores"][0].update(
        {
            "followup_recommended": False,
            "stop_reason": "Positive synthetic/proxy result only; not full validation and not sufficient for a paper decision.",
            "recommended_next_action": "Stop at controller follow-up depth 2: proxy evidence is positive but not paper-ready.",
        }
    )

    status = classify_quality_report(report)

    assert status["ok"] is True
    assert status["status"] == "clean"
    assert status["problem_counts"] == {}
    assert status["raw_problem_counts"] == {"supported_but_negative_requires_review": 1}
    assert status["severity_counts"] == {"info": 1}


def test_supported_negative_without_depth_cap_rationale_is_blocked() -> None:
    report = _report_with_decision(
        "supported_but_negative_requires_review",
        decision="finalize_negative",
        hypothesis_status="supported",
    )
    report["decision_scores"][0].update(
        {
            "followup_recommended": False,
            "stop_reason": "Partial support did not pass the paper gate.",
            "recommended_next_action": "Stop without a follow-up.",
        }
    )

    status = classify_quality_report(report)

    assert status["ok"] is False
    assert status["status"] == "blocked"


def test_structural_decision_problem_is_blocked() -> None:
    status = classify_quality_report(
        _report_with_decision(
            "unknown_decision", decision="unknown", hypothesis_status="unknown"
        )
    )

    assert status["ok"] is False
    assert status["status"] == "blocked"
    assert status["severity_counts"] == {"blocked": 1}


def test_load_latest_quality_status_reads_report_without_mutating_it(
    tmp_path: Path,
) -> None:
    report_path = tmp_path / "quality.json"
    report = _report_with_decision("weak_or_missing_evidence_strength")
    report_path.write_text(json.dumps(report), encoding="utf-8")
    before = report_path.read_text(encoding="utf-8")

    status = load_latest_quality_status([str(report_path)])

    assert status["status"] == "warnings"
    assert status["report_path"] == str(report_path)
    assert report_path.read_text(encoding="utf-8") == before


def test_quality_status_includes_post_prompt_monitor(tmp_path: Path) -> None:
    report_path = tmp_path / "quality.json"
    report_path.write_text(
        json.dumps(_report_with_decision("weak_or_missing_evidence_strength")),
        encoding="utf-8",
    )
    window_path = tmp_path / "window.json"
    window_path.write_text(
        json.dumps(
            {
                "schema_version": "enoch_research_quality_window_comparison_v1",
                "cutoff": "2026-05-11T09:58:00Z",
                "limit": 20,
                "post": {
                    "candidate_count": 20,
                    "decision_count": 13,
                    "admitted_rate": 0.6,
                    "avg_total_score": 73.093,
                    "status_counts": {
                        "admitted": 12,
                        "needs_review": 1,
                        "rejected": 4,
                    },
                    "category_counts": {
                        "home-training": 3,
                        "long-context": 4,
                    },
                    "generation_mode_counts": {
                        "fresh_grounded": 9,
                        "moonshot": 10,
                    },
                    "eval_case_counts": {
                        "proxy_only_positive": 4,
                        "useful_adjacent_followup": 2,
                    },
                    "high_similarity_pair_count": 0,
                    "moonshot_count": 10,
                    "moonshot_avg_score": 74.64,
                },
                "pre": {
                    "candidate_count": 20,
                    "decision_count": 13,
                    "admitted_rate": 0.5,
                    "avg_total_score": 71.82,
                    "status_counts": {
                        "admitted": 10,
                        "needs_review": 2,
                        "rejected": 2,
                    },
                    "category_counts": {
                        "home-training": 4,
                        "spec-decoding": 4,
                    },
                    "generation_mode_counts": {
                        "fresh_grounded": 7,
                        "moonshot": 7,
                    },
                    "eval_case_counts": {
                        "proxy_only_positive": 8,
                        "useful_adjacent_followup": 6,
                    },
                    "high_similarity_pair_count": 0,
                },
                "delta": {
                    "admitted_rate_delta": 0.1,
                    "proxy_only_positive_delta": -4,
                    "useful_adjacent_followup_delta": -4,
                    "moonshot_avg_score_delta": 1.426,
                },
                "eval_case_samples": {
                    "pre": {
                        "useful_adjacent_followup": [
                            {
                                "case_id": "useful_adjacent_followup:pre-run",
                                "case_type": "useful_adjacent_followup",
                                "severity": "info",
                                "title": "Previous follow-up",
                                "project_id": "pre-project",
                                "project_name": "Previous Project",
                                "run_id": "pre-run",
                                "followup_title": "Previous follow-up",
                                "followup_depth": 0,
                                "expected_behavior": "Prefer bounded follow-up.",
                            }
                        ]
                    },
                    "post": {
                        "useful_adjacent_followup": [
                            {
                                "case_id": "useful_adjacent_followup:post-run",
                                "case_type": "useful_adjacent_followup",
                                "severity": "info",
                                "title": "Current follow-up",
                                "project_id": "post-project",
                                "project_name": "Current Project",
                                "run_id": "post-run",
                                "followup_title": "Current follow-up",
                                "followup_depth": 1,
                                "expected_behavior": "Prefer bounded follow-up.",
                            }
                        ]
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    history_path = tmp_path / "history.jsonl"
    history_path.write_text(
        json.dumps(
            {
                "checked_at": "2026-05-11T11:17:08Z",
                "malformed_provider_response_count": 1,
                "generated_count": 0,
            }
        )
        + "\n"
        + json.dumps(
            {
                "checked_at": "2026-05-11T11:37:28Z",
                "malformed_provider_response_count": 0,
                "generated_count": 2,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    status = load_latest_quality_status(
        [str(report_path)],
        window_report_path=str(window_path),
        autopilot_history_path=str(history_path),
    )

    monitor = status["post_prompt_monitor"]
    assert monitor["available"] is True
    assert monitor["candidate_count"] == 20
    assert monitor["decision_count"] == 13
    assert monitor["decision_coverage"] == 0.65
    assert monitor["proxy_only_positive"] == 4
    assert monitor["proxy_only_positive_delta"] == -4.0
    assert monitor["useful_adjacent_followup"] == 2
    assert monitor["window_comparison"] == {
        "cutoff": "2026-05-11T09:58:00Z",
        "limit": 20,
        "delta": {
            "admitted_rate_delta": 0.1,
            "proxy_only_positive_delta": -4.0,
            "useful_adjacent_followup_delta": -4.0,
            "moonshot_avg_score_delta": 1.426,
        },
        "current": {
            "candidate_count": 20,
            "decision_count": 13,
            "admitted_rate": 0.6,
            "avg_total_score": 73.093,
            "status_counts": {
                "admitted": 12,
                "needs_review": 1,
                "rejected": 4,
            },
            "category_counts": {
                "home-training": 3,
                "long-context": 4,
            },
            "generation_mode_counts": {
                "fresh_grounded": 9,
                "moonshot": 10,
            },
            "eval_case_counts": {
                "proxy_only_positive": 4,
                "useful_adjacent_followup": 2,
            },
            "high_similarity_pair_count": 0,
        },
        "previous": {
            "candidate_count": 20,
            "decision_count": 13,
            "admitted_rate": 0.5,
            "avg_total_score": 71.82,
            "status_counts": {
                "admitted": 10,
                "needs_review": 2,
                "rejected": 2,
            },
            "category_counts": {
                "home-training": 4,
                "spec-decoding": 4,
            },
            "generation_mode_counts": {
                "fresh_grounded": 7,
                "moonshot": 7,
            },
            "eval_case_counts": {
                "proxy_only_positive": 8,
                "useful_adjacent_followup": 6,
            },
            "high_similarity_pair_count": 0,
        },
    }
    assert monitor["useful_adjacent_followup_evidence"] == {
        "current": [
            {
                "case_id": "useful_adjacent_followup:post-run",
                "case_type": "useful_adjacent_followup",
                "severity": "info",
                "title": "Current follow-up",
                "project_id": "post-project",
                "project_name": "Current Project",
                "run_id": "post-run",
                "followup_title": "Current follow-up",
                "followup_depth": 1,
                "expected_behavior": "Prefer bounded follow-up.",
            }
        ],
        "previous": [
            {
                "case_id": "useful_adjacent_followup:pre-run",
                "case_type": "useful_adjacent_followup",
                "severity": "info",
                "title": "Previous follow-up",
                "project_id": "pre-project",
                "project_name": "Previous Project",
                "run_id": "pre-run",
                "followup_title": "Previous follow-up",
                "followup_depth": 0,
                "expected_behavior": "Prefer bounded follow-up.",
            }
        ],
        "delta": -4.0,
    }
    assert monitor["malformed_provider_response_count"] == 1
    assert monitor["last_malformed_at"] == "2026-05-11T11:17:08Z"
    assert monitor["recent_malformed_provider_responses"] == [
        {
            "checked_at": "2026-05-11T11:17:08Z",
            "recorded_at": "",
            "provider_model": "",
            "malformed_provider_response_count": 1,
            "generated_count": 0,
            "promoted_count": 0,
            "dispatched_count": 0,
            "operator_action": (
                "inspect provider-generation output for this tick before "
                "trusting new idea volume"
            ),
        }
    ]


def test_quality_status_summarizes_recent_malformed_provider_history(
    tmp_path: Path,
) -> None:
    report_path = tmp_path / "quality.json"
    report_path.write_text(json.dumps(_report_with_decision("")), encoding="utf-8")
    window_path = tmp_path / "window.json"
    window_path.write_text(
        json.dumps(
            {
                "schema_version": "enoch_research_quality_window_comparison_v1",
                "cutoff": "2026-05-11T09:58:00Z",
                "post": {"candidate_count": 10, "decision_count": 10},
                "delta": {},
            }
        ),
        encoding="utf-8",
    )
    history_path = tmp_path / "history.jsonl"
    history_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "checked_at": "2026-05-11T10:00:00Z",
                        "recorded_at": "2026-05-11T10:02:00Z",
                        "trace_id": "research-cycle-trace-a",
                        "run_cycle_id": "run-cycle-a",
                        "provider_model": "hf:model-a",
                        "malformed_provider_response_count": 1,
                        "generated_count": 0,
                        "promoted_count": 1,
                        "dispatched_count": 0,
                    }
                ),
                json.dumps(
                    {
                        "checked_at": "2026-05-11T11:00:00Z",
                        "recorded_at": "2026-05-11T11:02:00Z",
                        "trace_id": "research-cycle-trace-b",
                        "run_cycle_id": "run-cycle-b",
                        "provider_model": "hf:model-b",
                        "malformed_provider_response_count": 2,
                        "generated_count": 0,
                        "promoted_count": 0,
                        "dispatched_count": 1,
                    }
                ),
                json.dumps(
                    {
                        "checked_at": "2026-05-11T12:00:00Z",
                        "recorded_at": "2026-05-11T12:02:00Z",
                        "trace_id": "research-cycle-trace-c",
                        "run_cycle_id": "run-cycle-c",
                        "provider_model": "hf:model-c",
                        "malformed_provider_response_count": 0,
                        "generated_count": 1,
                        "promoted_count": 1,
                        "dispatched_count": 0,
                    }
                ),
                json.dumps(
                    {
                        "checked_at": "2026-05-11T13:00:00Z",
                        "recorded_at": "2026-05-11T13:02:00Z",
                        "trace_id": "research-cycle-trace-d",
                        "run_cycle_id": "run-cycle-d",
                        "provider_model": "hf:model-c",
                        "malformed_provider_response_count": 0,
                        "generated_count": 3,
                        "promoted_count": 2,
                        "dispatched_count": 0,
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    status = load_latest_quality_status(
        [str(report_path)],
        window_report_path=str(window_path),
        autopilot_history_path=str(history_path),
    )

    monitor = status["post_prompt_monitor"]
    assert monitor["malformed_provider_response_count"] == 3
    assert monitor["malformed_provider_response_ticks"] == 2
    assert monitor["provider_generation_health"] == {
        "available": True,
        "rows_checked": 4,
        "malformed_provider_response_count": 3,
        "malformed_provider_response_ticks": 2,
        "clean_tick_count": 2,
        "consecutive_clean_ticks": 2,
        "last_checked_at": "2026-05-11T13:00:00Z",
        "last_malformed_at": "2026-05-11T11:00:00Z",
        "malformed_provider_model_counts": {
            "hf:model-a": 1,
            "hf:model-b": 2,
        },
        "latest_tick": {
            "checked_at": "2026-05-11T13:00:00Z",
            "recorded_at": "2026-05-11T13:02:00Z",
            "trace_id": "research-cycle-trace-d",
            "run_cycle_id": "run-cycle-d",
            "provider_model": "hf:model-c",
            "malformed_provider_response_count": 0,
            "initial_promotable_count": 0,
            "generated_count": 3,
            "promoted_count": 2,
            "dispatched_count": 0,
            "reason": "",
            "status": "clean",
            "operator_action": (
                "provider generation is currently clean; keep monitoring "
                "before widening automation"
            ),
        },
        "last_malformed_tick": {
            "checked_at": "2026-05-11T11:00:00Z",
            "recorded_at": "2026-05-11T11:02:00Z",
            "trace_id": "research-cycle-trace-b",
            "run_cycle_id": "run-cycle-b",
            "provider_model": "hf:model-b",
            "malformed_provider_response_count": 2,
            "initial_promotable_count": 0,
            "generated_count": 0,
            "promoted_count": 0,
            "dispatched_count": 1,
            "reason": "",
            "status": "malformed",
            "operator_action": (
                "inspect provider-generation output for this tick before "
                "trusting new idea volume"
            ),
        },
        "consecutive_zero_generated_ticks": 0,
        "consecutive_zero_promoted_ticks": 0,
        "latest_yield_status": "yielding",
        "yield_operator_action": (
            "provider generation yielded 3 candidate(s) and promoted 2; use "
            "yield counts alongside malformed-output recovery"
        ),
        "operator_action": (
            "provider generation has 2 clean ticks since the last malformed "
            "response; review the last malformed model before widening automation"
        ),
    }
    assert monitor["malformed_provider_model_counts"] == {
        "hf:model-a": 1,
        "hf:model-b": 2,
    }
    assert monitor["recent_malformed_provider_responses"] == [
        {
            "checked_at": "2026-05-11T11:00:00Z",
            "recorded_at": "2026-05-11T11:02:00Z",
            "trace_id": "research-cycle-trace-b",
            "run_cycle_id": "run-cycle-b",
            "provider_model": "hf:model-b",
            "malformed_provider_response_count": 2,
            "generated_count": 0,
            "promoted_count": 0,
            "dispatched_count": 1,
            "operator_action": (
                "inspect provider-generation output for this tick before "
                "trusting new idea volume"
            ),
        },
        {
            "checked_at": "2026-05-11T10:00:00Z",
            "recorded_at": "2026-05-11T10:02:00Z",
            "trace_id": "research-cycle-trace-a",
            "run_cycle_id": "run-cycle-a",
            "provider_model": "hf:model-a",
            "malformed_provider_response_count": 1,
            "generated_count": 0,
            "promoted_count": 1,
            "dispatched_count": 0,
            "operator_action": (
                "inspect provider-generation output for this tick before "
                "trusting new idea volume"
            ),
        },
    ]


def test_quality_status_exposes_provider_generation_yield_posture(
    tmp_path: Path,
) -> None:
    report_path = tmp_path / "quality.json"
    report_path.write_text(json.dumps(_report_with_decision("")), encoding="utf-8")
    window_path = tmp_path / "window.json"
    window_path.write_text(json.dumps({"ok": True}), encoding="utf-8")
    history_path = tmp_path / "history.jsonl"
    history_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "checked_at": "2026-05-11T10:00:00Z",
                        "recorded_at": "2026-05-11T10:02:00Z",
                        "provider_model": "hf:model-a",
                        "malformed_provider_response_count": 0,
                        "initial_promotable_count": 3,
                        "generated_count": 0,
                        "promoted_count": 0,
                        "dispatched_count": 0,
                        "reason": (
                            "bounded research cycle completed; broad queue pause "
                            "preserved and paper stages were positive-gated"
                        ),
                    }
                ),
                json.dumps(
                    {
                        "checked_at": "2026-05-11T11:00:00Z",
                        "recorded_at": "2026-05-11T11:02:00Z",
                        "provider_model": "hf:model-b",
                        "malformed_provider_response_count": 0,
                        "initial_promotable_count": 2,
                        "generated_count": 0,
                        "promoted_count": 0,
                        "dispatched_count": 0,
                        "reason": (
                            "bounded research cycle completed; broad queue pause "
                            "preserved and paper stages were positive-gated"
                        ),
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    status = load_latest_quality_status(
        [str(report_path)],
        window_report_path=str(window_path),
        autopilot_history_path=str(history_path),
    )

    provider_health = status["post_prompt_monitor"]["provider_generation_health"]
    assert provider_health["latest_tick"]["initial_promotable_count"] == 2
    assert provider_health["latest_tick"]["reason"] == (
        "bounded research cycle completed; broad queue pause preserved and paper "
        "stages were positive-gated"
    )
    assert provider_health["consecutive_zero_generated_ticks"] == 2
    assert provider_health["consecutive_zero_promoted_ticks"] == 2
    assert provider_health["latest_yield_status"] == "backlog_satisfied"
    assert provider_health["yield_operator_action"] == (
        "fresh provider generation is not yielding new candidates because 2 "
        "promotable candidate(s) were already available; monitor yield before "
        "treating provider health as idea volume"
    )


def test_quality_status_includes_refresh_sidecar_status(tmp_path: Path) -> None:
    report_path = tmp_path / "quality.json"
    report_path.write_text(
        json.dumps(_report_with_decision("weak_or_missing_evidence_strength")),
        encoding="utf-8",
    )
    refresh_status_path = tmp_path / "latest-refresh.json"
    refresh_status_path.write_text(
        json.dumps(
            {
                "ok": False,
                "action": "research_quality_refresh_skipped",
                "reason": "missing database URL",
                "recorded_at": "2026-05-30T14:41:25Z",
                "output": str(report_path),
            }
        ),
        encoding="utf-8",
    )

    status = load_latest_quality_status(
        [str(report_path)], refresh_status_path=str(refresh_status_path)
    )

    assert status["refresh_status"] == {
        "available": True,
        "ok": False,
        "action": "research_quality_refresh_skipped",
        "reason": "missing database URL",
        "recorded_at": "2026-05-30T14:41:25Z",
        "output": str(report_path),
        "path": str(refresh_status_path),
    }


def test_missing_quality_report_blocks_readiness() -> None:
    status = load_latest_quality_status(["/definitely/missing/research-quality.json"])

    assert status["ok"] is False
    assert status["status"] == "blocked"
    assert status["problem_counts"] == {"missing_quality_report": 1}


def test_malformed_quality_report_blocks_readiness_instead_of_passing_clean() -> None:
    status = classify_quality_report({})

    assert status["ok"] is False
    assert status["status"] == "blocked"
    assert status["problem_counts"] == {"malformed_quality_report": 1}
    assert status["severity_counts"] == {"blocked": 1}
    assert status["problem_details"][0]["problem"] == "malformed_quality_report"


def test_malformed_quality_report_file_blocks_readiness(tmp_path: Path) -> None:
    report_path = tmp_path / "quality.json"
    report_path.write_text("{not-json", encoding="utf-8")

    status = load_latest_quality_status([str(report_path)])

    assert status["ok"] is False
    assert status["status"] == "blocked"
    assert status["report_path"] == str(report_path)
    assert status["problem_counts"] == {"malformed_quality_report": 1}
    assert status["severity_counts"] == {"blocked": 1}
    assert status["problem_details"][0]["problem"] == "malformed_quality_report"


def test_supported_negative_with_bounded_followup_and_scale_limits_is_info() -> None:
    report = _report_with_decision(
        "supported_but_negative_requires_review",
        decision="finalize_negative",
        hypothesis_status="supported",
    )
    report["decision_scores"][0].update(
        {
            "followup_recommended": True,
            "stop_reason": "Tier 1 real-model KV trace supports the mechanism, but it is small-model, short-context, trace-only, and not publication-grade full validation.",
            "recommended_next_action": "Do not write a paper; deepen with a bounded direct test using longer contexts and real memory/latency metrics.",
        }
    )

    status = classify_quality_report(report)

    assert status["ok"] is True
    assert status["status"] == "clean"
    assert status["problem_counts"] == {}
    assert status["raw_problem_counts"] == {"supported_but_negative_requires_review": 1}
    assert status["severity_counts"] == {"info": 1}


def test_supported_negative_with_serving_path_followup_is_info() -> None:
    report = _report_with_decision(
        "supported_but_negative_requires_review",
        decision="finalize_negative",
        hypothesis_status="supported",
    )
    report["decision_scores"][0].update(
        {
            "followup_recommended": True,
            "stop_reason": "Direct real-trace latency evidence supports the mechanism, but this run measures in-process count retrieval rather than a full production serving path with concurrency, update costs, memory pressure, and result materialization.",
            "recommended_next_action": "Stop paper gating for this run; treat the result as Tier 2 mechanism support and run one bounded end-to-end serving validation before considering publication.",
        }
    )

    status = classify_quality_report(report)

    assert status["ok"] is True
    assert status["status"] == "clean"
    assert status["problem_counts"] == {}
    assert status["raw_problem_counts"] == {"supported_but_negative_requires_review": 1}
    assert status["severity_counts"] == {"info": 1}


def test_supported_negative_depth4_reconstructed_trace_is_info() -> None:
    report = _report_with_decision(
        "supported_but_negative_requires_review",
        decision="finalize_negative",
        hypothesis_status="supported",
    )
    report["decision_scores"][0].update(
        {
            "followup_recommended": False,
            "stop_reason": "Mechanism support was demonstrated on public DNS-rank labels with deterministic reconstructed URL/key suffixes, not on an actual production trace or production-grade concurrent implementation.",
            "recommended_next_action": "Stop paper promotion for this depth-4 branch: the replay supports the mechanism but is reconstructed and is not publication-grade.",
        }
    )

    status = classify_quality_report(report)

    assert status["ok"] is True
    assert status["status"] == "clean"
    assert status["problem_counts"] == {}
    assert status["raw_problem_counts"] == {"supported_but_negative_requires_review": 1}
    assert status["severity_counts"] == {"info": 1}


def test_supported_negative_depth4_real_streaming_limits_is_info() -> None:
    report = _report_with_decision(
        "supported_but_negative_requires_review",
        decision="finalize_negative",
        hypothesis_status="supported",
    )
    report["decision_scores"][0].update(
        {
            "followup_recommended": False,
            "stop_reason": "Mechanism support was replicated on distilgpt2 and gpt2 with real past_key_values pruning, but validation remains limited to small GPT-2-family models, 768-token streams, and unoptimized Python cache mutation rather than long-context production serving.",
            "recommended_next_action": "Stop this depth-4 follow-up: the bounded real-streaming evidence supports the mechanism but is not Tier-4 paper-ready, and controller lineage cap prevents recommending another deepen/retry follow-up.",
        }
    )

    status = classify_quality_report(report)

    assert status["ok"] is True
    assert status["status"] == "clean"
    assert status["problem_counts"] == {}
    assert status["raw_problem_counts"] == {"supported_but_negative_requires_review": 1}
    assert status["severity_counts"] == {"info": 1}
