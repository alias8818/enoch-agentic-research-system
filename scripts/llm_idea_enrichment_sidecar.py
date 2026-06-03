from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from enoch_control_plane.control_plane.llm_harness_telemetry import (
    LLM_HARNESS_COST_OBSERVATION_EVENT,
    LLM_HARNESS_OUTPUT_CONTRACT_EVENT,
    LLM_HARNESS_ROUTE_DECISION_EVENT,
    LLM_HARNESS_TOOL_CALL_EVENT,
    LLM_HARNESS_TOOL_RESULT_EVENT,
    record_llm_harness_event,
)
from enoch_control_plane.models import utc_now

WORKFLOW_ID = "idea_generation_enrichment"
POLICY_ID = "idea-generation-enrichment-read-only-v1"
ALLOWED_TOOLS = frozenset({"context7_docs", "exa_search", "web_search"})
READ_ONLY_SIDE_CAR_SOURCE = "llm_idea_enrichment_sidecar"
MUTATING_OUTPUT_KEYS = frozenset(
    {
        "queue_admitted",
        "paper_id",
        "paper_status",
        "publication_status",
        "readiness_status",
        "settings_patch",
        "dispatch_payload",
        "control_flags",
    }
)


class IdeaEnrichmentSidecarError(ValueError):
    """Raised when the read-only enrichment contract is violated."""


@dataclass(frozen=True)
class IdeaEnrichmentPolicy:
    allowed_tools: frozenset[str] = ALLOWED_TOOLS
    max_tool_calls: int = 4
    max_results_per_tool: int = 8
    timeout_seconds: int = 30
    cooldown_seconds: int = 3600
    max_estimated_cost_usd: float = 0.05


@dataclass(frozen=True)
class ToolObservation:
    tool_name: str
    query: str
    source_urls: tuple[str, ...] = ()
    source_titles: tuple[str, ...] = ()
    retrieval_timestamp: str = ""
    status: str = "ok"
    failure_kind: str = ""
    estimated_cost_usd: float = 0.0
    input_token_count: int = 0
    output_token_count: int = 0

    @property
    def result_count(self) -> int:
        return min(
            len(self.source_urls), len(self.source_titles) or len(self.source_urls)
        )


@dataclass(frozen=True)
class IdeaEnrichmentRequest:
    trace_id: str
    topic: str
    provider_id: str
    model_id: str
    requested_tools: tuple[str, ...]
    base_candidate: Mapping[str, Any] = field(default_factory=dict)
    started_at: str = ""
    source: str = READ_ONLY_SIDE_CAR_SOURCE
    policy: IdeaEnrichmentPolicy = field(default_factory=IdeaEnrichmentPolicy)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _json_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _bounded_text_list(values: Sequence[Any], *, limit: int) -> list[str]:
    return [_text(value)[:500] for value in values if _text(value)][:limit]


def _result_hashes(observation: ToolObservation) -> list[str]:
    pairs = zip(observation.source_urls, observation.source_titles, strict=False)
    return [
        f"sha256:{_json_hash({'url': url, 'title': title})}" for url, title in pairs
    ]


def validate_tool_allowlist(
    requested_tools: Sequence[str], policy: IdeaEnrichmentPolicy
) -> list[str]:
    tools = [_text(tool) for tool in requested_tools if _text(tool)]
    if not tools:
        raise IdeaEnrichmentSidecarError("at least one enrichment tool is required")
    if len(tools) > policy.max_tool_calls:
        raise IdeaEnrichmentSidecarError("requested tool count exceeds policy limit")
    disallowed = sorted(set(tools) - set(policy.allowed_tools))
    if disallowed:
        raise IdeaEnrichmentSidecarError(
            f"tool is not allowed for {WORKFLOW_ID}: {', '.join(disallowed)}"
        )
    return tools


def validate_read_only_candidate_patch(candidate: Mapping[str, Any]) -> None:
    present = sorted(key for key in MUTATING_OUTPUT_KEYS if key in candidate)
    if present:
        raise IdeaEnrichmentSidecarError(
            f"sidecar output contains mutating fields: {', '.join(present)}"
        )


def _source_records_for_observation(
    observation: ToolObservation, *, max_results: int
) -> list[dict[str, Any]]:
    urls = _bounded_text_list(observation.source_urls, limit=max_results)
    titles = _bounded_text_list(observation.source_titles, limit=max_results)
    out: list[dict[str, Any]] = []
    for index, url in enumerate(urls):
        title = titles[index] if index < len(titles) else url
        out.append(
            {
                "source_id": f"llm-harness-{_json_hash([observation.tool_name, url])[:16]}",
                "source_kind": observation.tool_name,
                "title": title,
                "url": url,
                "retrieved_at": observation.retrieval_timestamp,
                "summary": "read-only idea enrichment source suggestion",
                "content_hash": _json_hash({"url": url, "title": title}),
                "payload_json": {"tool_name": observation.tool_name},
            }
        )
    return out


def advisory_candidate_suggestions(
    request: IdeaEnrichmentRequest, observations: Sequence[ToolObservation]
) -> list[dict[str, Any]]:
    validate_tool_allowlist(request.requested_tools, request.policy)
    base = dict(request.base_candidate)
    validate_read_only_candidate_patch(base)
    suggestions: list[dict[str, Any]] = []
    for observation in observations:
        if observation.tool_name not in request.policy.allowed_tools:
            raise IdeaEnrichmentSidecarError(
                f"tool observation is not allowed: {observation.tool_name}"
            )
        records = _source_records_for_observation(
            observation, max_results=request.policy.max_results_per_tool
        )
        suggestion = {
            **base,
            "status": "generated",
            "generation_mode": _text(base.get("generation_mode")) or "fresh_grounded",
            "source_kind": "llm_harness_tool_suggestion",
            "source_ids": [record["source_id"] for record in records],
            "source_urls": [record["url"] for record in records],
            "source_records": records,
            "generated_by": f"llm_harness.{WORKFLOW_ID}",
            "llm_harness_trace_id": request.trace_id,
            "llm_harness_tool_name": observation.tool_name,
        }
        validate_read_only_candidate_patch(suggestion)
        suggestions.append(suggestion)
    return suggestions


def _base_event_payload(
    request: IdeaEnrichmentRequest,
    *,
    completed_at: str,
    status: str,
    failure_kind: str = "",
    estimated_cost_usd: float = 0.0,
    input_token_count: int = 0,
    output_token_count: int = 0,
) -> dict[str, Any]:
    return {
        "workflow_id": WORKFLOW_ID,
        "trace_id": request.trace_id,
        "provider_id": request.provider_id,
        "model_id": request.model_id,
        "policy_id": POLICY_ID,
        "source": request.source,
        "started_at": request.started_at or completed_at,
        "completed_at": completed_at,
        "status": status,
        "failure_kind": failure_kind,
        "estimated_cost_usd": estimated_cost_usd,
        "input_token_count": input_token_count,
        "output_token_count": output_token_count,
    }


def _record_event(
    store: Any, event_type: str, payload: Mapping[str, Any]
) -> tuple[int, bool]:
    idempotency_key = (
        f"{event_type}:{payload.get('trace_id')}:{payload.get('tool_name', '')}:"
        f"{payload.get('completed_at')}:{_json_hash(payload)}"
    )
    return record_llm_harness_event(
        store,
        event_type=event_type,
        payload=payload,
        idempotency_key=idempotency_key,
    )


def record_sidecar_telemetry(
    store: Any,
    request: IdeaEnrichmentRequest,
    observations: Sequence[ToolObservation],
    suggestions: Sequence[Mapping[str, Any]],
    *,
    completed_at: str = "",
) -> list[tuple[int, bool]]:
    completed = completed_at or utc_now()
    allowed_tools = validate_tool_allowlist(request.requested_tools, request.policy)
    total_cost = round(sum(item.estimated_cost_usd for item in observations), 6)
    input_tokens = sum(item.input_token_count for item in observations)
    output_tokens = sum(item.output_token_count for item in observations)
    events: list[tuple[int, bool]] = []
    events.append(
        _record_event(
            store,
            LLM_HARNESS_ROUTE_DECISION_EVENT,
            {
                **_base_event_payload(
                    request,
                    completed_at=completed,
                    status="ok",
                    estimated_cost_usd=total_cost,
                    input_token_count=input_tokens,
                    output_token_count=output_tokens,
                ),
                "candidate_provider_ids": [request.provider_id],
                "candidate_model_ids": [request.model_id],
                "selected_provider_id": request.provider_id,
                "selected_model_id": request.model_id,
                "selection_reason": "read-only idea enrichment sidecar policy",
                "fallback_rank": 0,
                "budget_gate_status": "passed"
                if total_cost <= request.policy.max_estimated_cost_usd
                else "blocked",
                "health_gate_status": "not_live_checked",
            },
        )
    )
    for observation in observations:
        call_payload = {
            **_base_event_payload(
                request,
                completed_at=completed,
                status=observation.status,
                failure_kind=observation.failure_kind,
                estimated_cost_usd=observation.estimated_cost_usd,
                input_token_count=observation.input_token_count,
                output_token_count=observation.output_token_count,
            ),
            "tool_name": observation.tool_name,
            "tool_query_hash": _json_hash(observation.query),
        }
        events.append(_record_event(store, LLM_HARNESS_TOOL_CALL_EVENT, call_payload))
        events.append(
            _record_event(
                store,
                LLM_HARNESS_TOOL_RESULT_EVENT,
                {
                    **call_payload,
                    "result_count": observation.result_count,
                    "redacted_result_hashes": _result_hashes(observation),
                    "source_urls": _bounded_text_list(
                        observation.source_urls,
                        limit=request.policy.max_results_per_tool,
                    ),
                    "source_titles": _bounded_text_list(
                        observation.source_titles,
                        limit=request.policy.max_results_per_tool,
                    ),
                    "retrieval_timestamp": observation.retrieval_timestamp or completed,
                },
            )
        )
    events.append(
        _record_event(
            store,
            LLM_HARNESS_OUTPUT_CONTRACT_EVENT,
            {
                **_base_event_payload(
                    request,
                    completed_at=completed,
                    status="ok",
                    estimated_cost_usd=total_cost,
                    input_token_count=input_tokens,
                    output_token_count=output_tokens,
                ),
                "suggestion_count": len(suggestions),
                "allowed_tools": allowed_tools,
                "advisory_only": True,
            },
        )
    )
    events.append(
        _record_event(
            store,
            LLM_HARNESS_COST_OBSERVATION_EVENT,
            _base_event_payload(
                request,
                completed_at=completed,
                status="ok",
                estimated_cost_usd=total_cost,
                input_token_count=input_tokens,
                output_token_count=output_tokens,
            ),
        )
    )
    return events
