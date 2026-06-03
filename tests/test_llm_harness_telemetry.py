from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from enoch_control_plane.control_plane import read_models
from enoch_control_plane.control_plane.llm_harness_telemetry import (
    LLMHarnessTelemetryError,
    LLM_HARNESS_ROUTE_DECISION_EVENT,
    LLM_HARNESS_TOOL_RESULT_EVENT,
    record_llm_harness_event,
    validate_llm_harness_event,
)
from enoch_control_plane.control_plane.store import ControlPlaneStore


def _base_payload() -> dict[str, object]:
    return {
        "workflow_id": "idea_generation_enrichment",
        "trace_id": "trace-1",
        "provider_id": "openrouter",
        "model_id": "cheap-model",
        "policy_id": "llm-harness-read-only-v1",
        "source": "pytest",
        "started_at": "2026-06-03T03:00:00Z",
        "completed_at": "2026-06-03T03:00:03Z",
        "status": "ok",
        "failure_kind": "",
        "estimated_cost_usd": "0.00012",
        "input_token_count": 123,
        "output_token_count": 45,
    }


def _route_payload() -> dict[str, object]:
    return {
        **_base_payload(),
        "candidate_provider_ids": ["openrouter", "synthetic"],
        "candidate_model_ids": ["cheap-model", "strong-model"],
        "selected_provider_id": "openrouter",
        "selected_model_id": "cheap-model",
        "selection_reason": "meets idea-enrichment contract below budget",
        "fallback_rank": 0,
        "budget_gate_status": "passed",
        "health_gate_status": "passed",
    }


def _tool_result_payload() -> dict[str, object]:
    return {
        **_base_payload(),
        "tool_name": "exa",
        "result_count": 2,
        "redacted_result_hashes": ["sha256:aaa", "sha256:bbb"],
        "source_urls": ["https://example.com/one", "https://example.com/two"],
        "source_titles": ["One", "Two"],
        "retrieval_timestamp": "2026-06-03T03:00:02Z",
    }


def test_validate_llm_harness_event_rejects_missing_required_fields() -> None:
    payload = _route_payload()
    payload.pop("workflow_id")

    with pytest.raises(LLMHarnessTelemetryError, match="workflow_id"):
        validate_llm_harness_event(LLM_HARNESS_ROUTE_DECISION_EVENT, payload)


@pytest.mark.parametrize(
    "unsafe_key",
    [
        "raw_provider_response",
        "raw_tool_payload",
        "authorization",
        "provider_secret",
        "api_key",
    ],
)
def test_validate_llm_harness_event_rejects_raw_or_secret_keys(
    unsafe_key: str,
) -> None:
    payload = _tool_result_payload()
    payload[unsafe_key] = {"unsafe": True}

    with pytest.raises(LLMHarnessTelemetryError, match=unsafe_key):
        validate_llm_harness_event(LLM_HARNESS_TOOL_RESULT_EVENT, payload)


def test_validate_llm_harness_event_rejects_secret_like_values() -> None:
    payload = _route_payload()
    payload["selection_reason"] = "use bearer sk-or-v1-thisShouldNeverPersist123456"

    with pytest.raises(LLMHarnessTelemetryError, match="secret-like"):
        validate_llm_harness_event(LLM_HARNESS_ROUTE_DECISION_EVENT, payload)


def test_record_llm_harness_event_persists_and_read_model_summarizes() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        store = ControlPlaneStore(Path(tmp) / "control.sqlite3")
        event_id, inserted = record_llm_harness_event(
            store,
            event_type=LLM_HARNESS_TOOL_RESULT_EVENT,
            payload=_tool_result_payload(),
            idempotency_key="llm-harness:test-tool-result",
        )

        assert inserted is True
        assert event_id > 0
        summary = read_models.llm_harness_telemetry_summary(store)

    assert summary["ok"] is True
    assert summary["event_count"] == 1
    assert summary["event_type_counts"] == {LLM_HARNESS_TOOL_RESULT_EVENT: 1}
    event = summary["recent_events"][0]
    assert event["tool_name"] == "exa"
    assert event["source_urls"] == [
        "https://example.com/one",
        "https://example.com/two",
    ]
    assert "raw_tool_payload" not in event
