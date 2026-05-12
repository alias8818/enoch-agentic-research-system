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



def test_supported_negative_depth_capped_proxy_result_is_info_not_amber() -> None:
    report = _report_with_decision("supported_but_negative_requires_review", decision="finalize_negative", hypothesis_status="supported")
    report["decision_scores"][0].update({
        "followup_recommended": False,
        "stop_reason": "Positive synthetic/proxy result only; not full validation and not sufficient for a paper decision.",
        "recommended_next_action": "Stop at controller follow-up depth 2: proxy evidence is positive but not paper-ready.",
    })

    status = classify_quality_report(report)

    assert status["ok"] is True
    assert status["status"] == "clean"
    assert status["problem_counts"] == {}
    assert status["raw_problem_counts"] == {"supported_but_negative_requires_review": 1}
    assert status["severity_counts"] == {"info": 1}


def test_supported_negative_without_depth_cap_rationale_is_blocked() -> None:
    report = _report_with_decision("supported_but_negative_requires_review", decision="finalize_negative", hypothesis_status="supported")
    report["decision_scores"][0].update({
        "followup_recommended": False,
        "stop_reason": "Partial support did not pass the paper gate.",
        "recommended_next_action": "Stop without a follow-up.",
    })

    status = classify_quality_report(report)

    assert status["ok"] is False
    assert status["status"] == "blocked"


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


def test_quality_status_includes_post_prompt_monitor(tmp_path: Path) -> None:
    report_path = tmp_path / "quality.json"
    report_path.write_text(json.dumps(_report_with_decision("weak_or_missing_evidence_strength")), encoding="utf-8")
    window_path = tmp_path / "window.json"
    window_path.write_text(json.dumps({
        "schema_version": "enoch_research_quality_window_comparison_v1",
        "cutoff": "2026-05-11T09:58:00Z",
        "post": {
            "candidate_count": 20,
            "decision_count": 13,
            "eval_case_counts": {"proxy_only_positive": 4, "useful_adjacent_followup": 2},
            "high_similarity_pair_count": 0,
            "moonshot_count": 10,
            "moonshot_avg_score": 74.64,
        },
        "delta": {"proxy_only_positive_delta": -4, "useful_adjacent_followup_delta": -4, "moonshot_avg_score_delta": 1.426},
    }), encoding="utf-8")
    history_path = tmp_path / "history.jsonl"
    history_path.write_text(
        json.dumps({"checked_at": "2026-05-11T11:17:08Z", "malformed_provider_response_count": 1, "generated_count": 0}) + "\n"
        + json.dumps({"checked_at": "2026-05-11T11:37:28Z", "malformed_provider_response_count": 0, "generated_count": 2}) + "\n",
        encoding="utf-8",
    )

    status = load_latest_quality_status([str(report_path)], window_report_path=str(window_path), autopilot_history_path=str(history_path))

    monitor = status["post_prompt_monitor"]
    assert monitor["available"] is True
    assert monitor["candidate_count"] == 20
    assert monitor["decision_count"] == 13
    assert monitor["decision_coverage"] == 0.65
    assert monitor["proxy_only_positive"] == 4
    assert monitor["proxy_only_positive_delta"] == -4.0
    assert monitor["useful_adjacent_followup"] == 2
    assert monitor["malformed_provider_response_count"] == 1
    assert monitor["last_malformed_at"] == "2026-05-11T11:17:08Z"


def test_missing_quality_report_blocks_readiness() -> None:
    status = load_latest_quality_status(["/definitely/missing/research-quality.json"])

    assert status["ok"] is False
    assert status["status"] == "blocked"
    assert status["problem_counts"] == {"missing_quality_report": 1}


def test_supported_negative_with_bounded_followup_and_scale_limits_is_info() -> None:
    report = _report_with_decision("supported_but_negative_requires_review", decision="finalize_negative", hypothesis_status="supported")
    report["decision_scores"][0].update({
        "followup_recommended": True,
        "stop_reason": "Tier 1 real-model KV trace supports the mechanism, but it is small-model, short-context, trace-only, and not publication-grade full validation.",
        "recommended_next_action": "Do not write a paper; deepen with a bounded direct test using longer contexts and real memory/latency metrics.",
    })

    status = classify_quality_report(report)

    assert status["ok"] is True
    assert status["status"] == "clean"
    assert status["problem_counts"] == {}
    assert status["raw_problem_counts"] == {"supported_but_negative_requires_review": 1}
    assert status["severity_counts"] == {"info": 1}


def test_supported_negative_with_serving_path_followup_is_info() -> None:
    report = _report_with_decision("supported_but_negative_requires_review", decision="finalize_negative", hypothesis_status="supported")
    report["decision_scores"][0].update({
        "followup_recommended": True,
        "stop_reason": "Direct real-trace latency evidence supports the mechanism, but this run measures in-process count retrieval rather than a full production serving path with concurrency, update costs, memory pressure, and result materialization.",
        "recommended_next_action": "Stop paper gating for this run; treat the result as Tier 2 mechanism support and run one bounded end-to-end serving validation before considering publication.",
    })

    status = classify_quality_report(report)

    assert status["ok"] is True
    assert status["status"] == "clean"
    assert status["problem_counts"] == {}
    assert status["raw_problem_counts"] == {"supported_but_negative_requires_review": 1}
    assert status["severity_counts"] == {"info": 1}
