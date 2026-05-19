from __future__ import annotations

import json
from types import SimpleNamespace

from scripts import research_facility_synthesis as synth


def _candidate(idx: int, **overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "candidate_id": f"spec-branch-{idx}",
        "generation_mode": "implementation_gap",
        "status": "admitted",
        "title": [
            "SSD-lite Verification Outcome Prediction",
            "Dynamic Speculative Vocabulary",
            "Entropy Acceptance Controller",
            "Retrieval Suffix Cache Speculation",
            "Grammar Schema Aware Speculation",
        ][idx - 1],
        "category": "spec-decoding",
        "source_urls": ["https://arxiv.org/abs/2603.03251"],
        "hypothesis": "A DFlash branch may improve speculative decoding throughput.",
        "mechanism": "DFlash trace top-k entropy accept length suffix grammar vocabulary branch oracle",
        "baseline_to_beat": "Qwen3 DFlash b16 static speculative decoding baseline",
        "expected_artifacts": ["run_notes.md", "metrics.json", ".enoch/project_decision.json"],
        "required_evidence": ["baseline comparison", "metrics table", "decision artifact"],
        "likely_failure_modes": ["no signal"],
        "total_score": 75.0,
        "novelty_score": 8.0,
        "feasibility_score": 7.0,
        "accessibility_score": 8.0,
        "falsifiability_score": 8.0,
        "similar_prior_projects": [],
        "novelty_comparison": "Different branch from nearby speculative decoding variants.",
    }
    row.update(overrides)
    return row


def test_cluster_gate_collapses_related_spec_decoding_branches() -> None:
    clusters = synth.detect_candidate_clusters([_candidate(i) for i in range(1, 6)])

    assert len(clusters) == 1
    assert clusters[0]["cluster_key"] == "spec-decoding:https://arxiv.org/abs/2603.03251"
    assert {row["candidate_id"] for row in clusters[0]["candidates"]} == {f"spec-branch-{i}" for i in range(1, 6)}
    assert clusters[0]["requires_synthesis"] is True


def test_unrelated_candidates_do_not_trigger_synthesis() -> None:
    rows = [
        _candidate(1, candidate_id="kv", category="kv-compression", source_urls=["https://example.com/kv"], mechanism="kv cache"),
        _candidate(2, candidate_id="quant", category="quantization", source_urls=["https://example.com/q"], mechanism="quantization"),
        _candidate(3, candidate_id="agent", category="agent-reliability", source_urls=["https://example.com/a"], mechanism="agent ledger"),
    ]

    assert synth.detect_candidate_clusters(rows) == []


def test_reflection_patterns_use_successes_as_seed_context_not_truth() -> None:
    patterns = synth.extract_reflection_patterns(
        [
            {
                "project_id": "positive-1",
                "project_name": "Good Project",
                "decision_gate_state": "finalize_positive",
                "decision_summary": "Direct target-stack evidence beat the DFlash baseline with failure cases.",
                "category": "spec-decoding",
                "required_evidence": ["baseline comparison", "failure cases"],
            },
            {"project_id": "negative", "decision_gate_state": "finalize_negative", "decision_summary": "junk"},
        ]
    )

    assert patterns[0]["project_id"] == "positive-1"
    assert patterns[0]["use_as"] == "pattern_seed"
    assert patterns[0]["not_system_truth"] is True


def test_validates_oracle_candidate_requires_thresholds_and_artifacts() -> None:
    candidate = {
        "title": "Unified Oracle",
        "hypothesis": "One trace can rank branches.",
        "mechanism": "Trace and oracle analysis.",
        "success_threshold": "modelled gain is good",
        "kill_condition": "stop if no signal",
        "expected_artifacts": ["run_notes.md", "metrics.json"],
        "required_evidence": ["decision matrix"],
    }

    problems = synth.validate_synthesized_candidate(candidate)

    assert "missing expected artifact oracle_report.md" in problems
    assert "missing expected artifact .enoch/project_decision.json" in problems
    assert "success_threshold must include at least one numeric threshold" in problems


def test_provider_synthesis_builds_one_valid_meta_candidate() -> None:
    cluster = synth.detect_candidate_clusters([_candidate(i) for i in range(1, 6)])[0]
    response = {
        "candidates": [
            {
                "candidate_id": "spec-trace-oracle-v0",
                "title": "Spec Trace Oracle v0",
                "generation_mode": "manual_import",
                "category": "spec-decoding",
                "priority": "High",
                "hypothesis": "One DFlash trace can rank speculative decoding branches.",
                "mechanism": "Log rounds and run oracle analyses.",
                "description": "Unified oracle project.",
                "implementation": "Log DFlash b16 rounds, top-k, entropy, accept length, vocab coverage, suffix hits, grammar frontier, then report branch decisions.",
                "baseline_to_beat": "Static DFlash b16 and AR mini-slice.",
                "success_threshold": "Continue if at least one branch has >=8% modeled gain and p95 regression <=5%.",
                "kill_condition": "Stop if all branches are <5% modeled gain or trace cannot finish in 2 days.",
                "accessibility_delta": "Saves local GB10 time by choosing the branch before implementation.",
                "expected_artifacts": ["run_notes.md", "metrics.json", "trace_schema.md", "oracle_report.md", "failure_cases.jsonl", ".enoch/project_decision.json"],
                "required_evidence": ["baseline comparison", "oracle metrics table", "decision matrix", "failure cases"],
                "likely_failure_modes": ["instrumentation overhead", "no branch clears threshold"],
                "estimated_runtime_class": "overnight",
                "expected_token_budget": "large",
                "machine_target": "gb10",
                "model": "gpt-5.5",
                "sandbox": "danger-full-access",
                "novelty_score": 9,
                "feasibility_score": 7,
                "accessibility_score": 9,
                "falsifiability_score": 10,
                "novelty_comparison": "Synthesizes branch candidates into one oracle before implementation.",
                "risk_notes": "Infrastructure may cost too much before signal.",
            }
        ]
    }

    report = synth.synthesize_clusters(
        [cluster],
        reflection_patterns=[],
        provider=lambda prompt: response,
        requested_by="unit",
    )

    assert report["ok"] is True
    assert report["synthesized_count"] == 1
    candidate = report["synthesized_candidates"][0]
    assert candidate["candidate_id"] == "spec-trace-oracle-v0"
    assert candidate["raw_candidate_json"]["synthesized_from"] == [f"spec-branch-{i}" for i in range(1, 6)]


def test_synthesis_sql_defers_branches_and_records_lineage() -> None:
    cluster = synth.detect_candidate_clusters([_candidate(i) for i in range(1, 6)])[0]
    synthesized = {
        "candidate_id": "spec-trace-oracle-v0",
        "title": "Spec Trace Oracle v0",
        "generation_mode": "manual_import",
        "category": "spec-decoding",
        "priority": "High",
        "source_urls": ["https://arxiv.org/abs/2603.03251"],
        "hypothesis": "One DFlash trace can rank branches.",
        "mechanism": "Trace and oracle analysis.",
        "description": "Unified oracle project.",
        "implementation": "Trace and report.",
        "baseline_to_beat": "Static DFlash.",
        "success_threshold": ">=8% modeled gain.",
        "kill_condition": "<5% modeled gain.",
        "accessibility_delta": "Avoids wasted branch implementations.",
        "expected_artifacts": ["run_notes.md", "metrics.json", "trace_schema.md", "oracle_report.md", "failure_cases.jsonl", ".enoch/project_decision.json"],
        "required_evidence": ["decision matrix"],
        "likely_failure_modes": ["no signal"],
        "estimated_runtime_class": "overnight",
        "expected_token_budget": "large",
        "machine_target": "gb10",
        "model": "gpt-5.5",
        "sandbox": "danger-full-access",
        "novelty_score": 9,
        "feasibility_score": 7,
        "accessibility_score": 9,
        "falsifiability_score": 10,
        "novelty_comparison": "Synthesized from related branches.",
        "risk_notes": "bounded",
    }
    report = {
        "clusters": [cluster],
        "synthesized_candidates": [synth.enrich_synthesized_candidate(synthesized, cluster, [], requested_by="unit")],
    }

    sql = synth.emit_synthesis_sql(report, requested_by="unit", queue_synthesized=True)

    assert "deferred_pending_oracle" in sql
    assert "synthesized_from" in sql
    assert "superseded_by" in sql
    assert "spec-trace-oracle-v0" in sql


def test_budget_checked_provider_fails_closed_before_provider_call() -> None:
    calls = {"provider": 0}

    def provider(_prompt: str) -> dict[str, object]:
        calls["provider"] += 1
        return {"candidates": []}

    wrapped = synth.budget_checked_provider(
        provider,
        budget_check=lambda: {"ok": False, "failures": ["rolling remaining too low"]},
    )

    try:
        wrapped("prompt")
    except RuntimeError as exc:
        assert "rolling remaining too low" in str(exc)
    else:
        raise AssertionError("budget failure should stop provider call")

    assert calls["provider"] == 0
