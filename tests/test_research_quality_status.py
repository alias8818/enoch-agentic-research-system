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


def test_quality_report_recommendations_survive_classification() -> None:
    report = _report_with_decision("weak_or_missing_evidence_strength")
    report["recommendations"] = [
        "Run a bounded follow-up before treating this as paper-ready."
    ]

    status = classify_quality_report(report)

    assert status["recommendations"] == [
        "Run a bounded follow-up before treating this as paper-ready."
    ]


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
            "followup_title": "Mixed follow-up",
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
            "followup_title": "Supported follow-up",
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
                "post": {
                    "candidate_count": 20,
                    "decision_count": 13,
                    "eval_case_counts": {
                        "proxy_only_positive": 4,
                        "useful_adjacent_followup": 2,
                    },
                    "high_similarity_pair_count": 0,
                    "moonshot_count": 10,
                    "moonshot_avg_score": 74.64,
                },
                "delta": {
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
