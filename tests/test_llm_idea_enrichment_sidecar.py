from __future__ import annotations

import tempfile
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from enoch_control_plane.control_plane import read_models
from enoch_control_plane.control_plane.store import ControlPlaneStore
from scripts import research_facility
from scripts.llm_idea_enrichment_sidecar import (
    IdeaEnrichmentRequest,
    IdeaEnrichmentSidecarError,
    ToolObservation,
    advisory_candidate_suggestions,
    record_sidecar_telemetry,
    validate_tool_allowlist,
)


def _candidate() -> dict[str, object]:
    return {
        "title": "Context7-grounded KV cache audit for local small models",
        "category": "kv-compression",
        "priority": "high",
        "generation_mode": "fresh_grounded",
        "hypothesis": "Source-grounded cache anchor checks catch regressions earlier.",
        "mechanism": "Compare anchor-aware cache compression against exact baseline.",
        "description": "Use retrieved implementation notes only as candidate context.",
        "implementation": "Run a bounded local transformer cache compression benchmark.",
        "baseline_to_beat": "Exact KV cache with no compression.",
        "success_threshold": "At least 20 percent memory reduction with no accuracy loss.",
        "kill_condition": "Stop if exact baseline parity fails.",
        "accessibility_delta": "Runs on the CPU lane or GB10 without cloud services.",
        "novelty_comparison": "Different from prior cache tests by grounding source claims.",
        "risk_notes": "External docs are advisory and must not bypass evidence gates.",
        "expected_artifacts": [
            "run_notes.md",
            "metrics.json",
            "failure_cases.json",
            ".enoch/project_decision.json",
        ],
        "required_evidence": [
            "baseline comparison",
            "metrics table",
            "failure cases",
            "decision artifact",
        ],
        "likely_failure_modes": [
            "retrieved documentation is too generic",
            "cache benchmark does not reproduce a measurable regression",
        ],
        "novelty_score": 9,
        "feasibility_score": 8,
        "accessibility_score": 9,
        "falsifiability_score": 8,
        "estimated_runtime_class": "small",
        "expected_token_budget": "small",
    }


def _request(base_candidate: dict[str, object] | None = None) -> IdeaEnrichmentRequest:
    return IdeaEnrichmentRequest(
        trace_id="trace-enrichment-1",
        topic="KV cache compression",
        provider_id="openrouter",
        model_id="cheap-useful-model",
        requested_tools=("context7_docs",),
        base_candidate=base_candidate or _candidate(),
        started_at="2026-06-03T04:00:00Z",
    )


def _observation() -> ToolObservation:
    return ToolObservation(
        tool_name="context7_docs",
        query="KV cache compression implementation docs",
        source_urls=("https://example.com/kv-cache",),
        source_titles=("KV Cache Notes",),
        retrieval_timestamp="2026-06-03T04:00:01Z",
        estimated_cost_usd=0.001,
        input_token_count=40,
        output_token_count=12,
    )


def test_validate_tool_allowlist_rejects_mutating_tools() -> None:
    with pytest.raises(IdeaEnrichmentSidecarError, match="not allowed"):
        validate_tool_allowlist(("shell",), _request().policy)


def test_advisory_candidate_suggestions_do_not_mutate_base_or_queue_state() -> None:
    base = _candidate()
    original = deepcopy(base)
    suggestions = advisory_candidate_suggestions(_request(base), [_observation()])

    assert base == original
    assert len(suggestions) == 1
    suggestion = suggestions[0]
    assert suggestion["generated_by"] == "llm_harness.idea_generation_enrichment"
    assert suggestion["source_kind"] == "llm_harness_tool_suggestion"
    assert suggestion["source_urls"] == ["https://example.com/kv-cache"]
    assert "queue_admitted" not in suggestion
    assert "paper_status" not in suggestion


def test_advisory_suggestions_still_pass_existing_planning_gate() -> None:
    suggestions = advisory_candidate_suggestions(_request(), [_observation()])

    plans = research_facility.plan_candidates(
        suggestions,
        SimpleNamespace(
            default_machine="gb10",
            default_model="gpt-5.5",
            default_sandbox="danger-full-access",
            admit_threshold=72.0,
            review_threshold=58.0,
            history=[],
        ),
    )

    assert len(plans) == 1
    assert plans[0].admission_decision == "admitted"
    assert plans[0].candidate["source_records"]
    assert (
        plans[0].candidate["generated_by"] == "llm_harness.idea_generation_enrichment"
    )


def test_advisory_candidate_suggestions_reject_mutating_output_fields() -> None:
    candidate = {**_candidate(), "queue_admitted": True}

    with pytest.raises(IdeaEnrichmentSidecarError, match="mutating fields"):
        advisory_candidate_suggestions(_request(candidate), [_observation()])


def test_record_sidecar_telemetry_emits_bounded_llm_harness_events() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        store = ControlPlaneStore(Path(tmp) / "control.sqlite3")
        request = _request()
        observations = [_observation()]
        suggestions = advisory_candidate_suggestions(request, observations)
        events = record_sidecar_telemetry(
            store,
            request,
            observations,
            suggestions,
            completed_at="2026-06-03T04:00:03Z",
        )
        summary = read_models.llm_harness_telemetry_summary(store)

    assert len(events) == 5
    assert summary["event_count"] == 5
    assert summary["ok"] is True
    assert summary["estimated_cost_usd"] == 0.001
    assert summary["event_type_counts"]["llm_harness.tool_call"] == 1
    assert summary["event_type_counts"]["llm_harness.tool_result"] == 1
    assert all("raw_tool_payload" not in event for event in summary["recent_events"])
