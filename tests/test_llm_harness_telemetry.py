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


def test_validate_llm_harness_event_rejects_missing_run_or_trace() -> None:
    payload = _route_payload()
    payload.pop("run_id", None)
    payload.pop("trace_id", None)

    with pytest.raises(LLMHarnessTelemetryError, match="run_id_or_trace_id"):
        validate_llm_harness_event(LLM_HARNESS_ROUTE_DECISION_EVENT, payload)


def test_record_llm_harness_event_does_not_fallback_to_workflow_entity() -> None:
    class FakeStore:
        def __init__(self) -> None:
            self.events: list[dict[str, object]] = []

        def append_event(self, **kwargs: object) -> tuple[int, bool]:
            self.events.append(kwargs)
            return len(self.events), True

    store = FakeStore()
    payload = _route_payload()
    payload["run_id"] = "run-1"
    payload["workflow_id"] = "workflow-should-not-be-entity"

    event_id, inserted = record_llm_harness_event(
        store,
        event_type=LLM_HARNESS_ROUTE_DECISION_EVENT,
        payload=payload,
    )

    assert inserted is True
    assert event_id == 1
    assert store.events[0]["entity_id"] == "run-1"
    assert "workflow-should-not-be-entity" not in str(
        store.events[0]["idempotency_key"]
    )


def test_record_llm_harness_event_distinct_recorded_at_values_do_not_collide() -> None:
    class FakeStore:
        def __init__(self) -> None:
            self.keys: list[str] = []

        def append_event(
            self, *, idempotency_key: str, **_kwargs: object
        ) -> tuple[int, bool]:
            self.keys.append(idempotency_key)
            return len(self.keys), True

    store = FakeStore()
    first = _route_payload()
    second = _route_payload()
    first["recorded_at"] = "2026-06-03T03:00:04Z"
    second["recorded_at"] = "2026-06-03T03:00:05Z"

    record_llm_harness_event(
        store,
        event_type=LLM_HARNESS_ROUTE_DECISION_EVENT,
        payload=first,
    )
    record_llm_harness_event(
        store,
        event_type=LLM_HARNESS_ROUTE_DECISION_EVENT,
        payload=second,
    )

    assert len(store.keys) == 2
    assert store.keys[0] != store.keys[1]


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


@pytest.mark.parametrize(
    "unsafe_key",
    [
        "raw_provider_response",
        "request_headers",
        "authorization",
        "provider_secret",
        "api_key",
    ],
)
def test_validate_llm_harness_event_rejects_nested_raw_or_secret_keys(
    unsafe_key: str,
) -> None:
    payload = _tool_result_payload()
    payload["metadata"] = {"safe": True, unsafe_key: {"unsafe": True}}

    with pytest.raises(LLMHarnessTelemetryError, match=f"metadata.{unsafe_key}"):
        validate_llm_harness_event(LLM_HARNESS_TOOL_RESULT_EVENT, payload)


@pytest.mark.parametrize(
    "secret_value",
    [
        "use bearer sk-or-...3456",
        "use Bearer: abcdefghijklmnop",
        "use bearer=abcdefghijklmnop",
        "use SK-ABCDEF1234567890",
        "use sK-oR-v1-ABCDEF1234567890",
        "use GHP_ABCDEF1234567890",
        "use GITHUB_PAT_ABCDEF1234567890",
        "use LIN_API_ABCDEF1234567890",
        "use AKIA1234567890ABCDEF",
        "use xoxb-1234567890abcdef",
        "use eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjMifQ.signature",
        "-----BEGIN OPENSSH PRIVATE KEY-----",
    ],
)
def test_validate_llm_harness_event_rejects_secret_like_values(
    secret_value: str,
) -> None:
    payload = _route_payload()
    payload["selection_reason"] = secret_value

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
