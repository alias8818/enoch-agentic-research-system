from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from ..models import utc_now

LLM_HARNESS_EVENT_PREFIX = "llm_harness."
LLM_HARNESS_ROUTE_DECISION_EVENT = "llm_harness.route_decision"
LLM_HARNESS_TOOL_CALL_EVENT = "llm_harness.tool_call"
LLM_HARNESS_TOOL_RESULT_EVENT = "llm_harness.tool_result"
LLM_HARNESS_OUTPUT_CONTRACT_EVENT = "llm_harness.output_contract"
LLM_HARNESS_COST_OBSERVATION_EVENT = "llm_harness.cost_observation"

LLM_HARNESS_EVENT_TYPES = {
    LLM_HARNESS_ROUTE_DECISION_EVENT,
    LLM_HARNESS_TOOL_CALL_EVENT,
    LLM_HARNESS_TOOL_RESULT_EVENT,
    LLM_HARNESS_OUTPUT_CONTRACT_EVENT,
    LLM_HARNESS_COST_OBSERVATION_EVENT,
}

_COMMON_REQUIRED_FIELDS = {
    "workflow_id",
    "provider_id",
    "model_id",
    "policy_id",
    "source",
    "started_at",
    "completed_at",
    "status",
    "failure_kind",
    "estimated_cost_usd",
    "input_token_count",
    "output_token_count",
}
_ROUTE_DECISION_REQUIRED_FIELDS = {
    "candidate_provider_ids",
    "candidate_model_ids",
    "selected_provider_id",
    "selected_model_id",
    "selection_reason",
    "fallback_rank",
    "budget_gate_status",
    "health_gate_status",
}
_TOOL_RESULT_REQUIRED_FIELDS = {
    "result_count",
    "redacted_result_hashes",
    "source_urls",
    "source_titles",
    "retrieval_timestamp",
}
_TOOL_EVENT_TYPES = {LLM_HARNESS_TOOL_CALL_EVENT, LLM_HARNESS_TOOL_RESULT_EVENT}
_MAX_STRING_LENGTH = 1000
_MAX_LIST_LENGTH = 50
_MAX_DEPTH = 5

_SENSITIVE_KEY_RE = re.compile(
    r"(authorization|bearer|api[_-]?key|secret|password|credential|token)",
    re.IGNORECASE,
)
_SAFE_KEY_EXCEPTIONS = {
    "input_token_count",
    "output_token_count",
}
_RAW_PAYLOAD_KEYS = {
    "arguments",
    "messages",
    "provider_response",
    "raw_provider_response",
    "raw_response",
    "raw_tool_payload",
    "request_body",
    "request_headers",
    "request_payload",
    "response_body",
    "response_payload",
    "tool_payload",
}
_SECRET_VALUE_PATTERNS = (
    re.compile(r"\bbearer\s+[\w.~+/=-]{8,}", re.IGNORECASE),
    re.compile(r"\bsk-[\w-]{12,}\b"),
    re.compile(r"\bsk-or-v1-[\w-]{12,}\b"),
    re.compile(r"\bghp_\w{12,}\b"),
    re.compile(r"\bgithub_pat_\w{12,}\b"),
    re.compile(r"\blin_api_\w{12,}\b"),
)


class LLMHarnessTelemetryError(ValueError):
    """Raised when a tool-enabled LLM event violates the telemetry contract."""


def _text(value: Any) -> str:
    return str(value or "").strip()


def _json_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _missing_required_fields(event_type: str, payload: Mapping[str, Any]) -> list[str]:
    required = set(_COMMON_REQUIRED_FIELDS)
    if event_type == LLM_HARNESS_ROUTE_DECISION_EVENT:
        required.update(_ROUTE_DECISION_REQUIRED_FIELDS)
    if event_type == LLM_HARNESS_TOOL_RESULT_EVENT:
        required.update(_TOOL_RESULT_REQUIRED_FIELDS)
    if event_type in _TOOL_EVENT_TYPES:
        required.add("tool_name")
    missing = sorted(field for field in required if field not in payload)
    if not (_text(payload.get("run_id")) or _text(payload.get("trace_id"))):
        missing.append("run_id_or_trace_id")
    return missing


def _validate_numeric_fields(payload: Mapping[str, Any]) -> None:
    for field in ("estimated_cost_usd", "input_token_count", "output_token_count"):
        value = payload.get(field)
        try:
            numeric = Decimal(str(value))
        except (InvalidOperation, ValueError) as exc:
            raise LLMHarnessTelemetryError(f"{field} must be numeric") from exc
        if numeric < 0:
            raise LLMHarnessTelemetryError(f"{field} must be non-negative")


def _validate_safe_key(key: str, *, path: str) -> None:
    normalized = key.lower().replace("-", "_")
    if normalized in _RAW_PAYLOAD_KEYS:
        raise LLMHarnessTelemetryError(f"{path} is not allowed in llm_harness events")
    if key not in _SAFE_KEY_EXCEPTIONS and _SENSITIVE_KEY_RE.search(key):
        raise LLMHarnessTelemetryError(f"{path} is not allowed in llm_harness events")


def _validate_safe_string(value: str, *, path: str) -> str:
    if len(value) > _MAX_STRING_LENGTH:
        raise LLMHarnessTelemetryError(f"{path} exceeds max telemetry string length")
    for pattern in _SECRET_VALUE_PATTERNS:
        if pattern.search(value):
            raise LLMHarnessTelemetryError(f"{path} contains secret-like value")
    return value


def _validate_safe_list(value: list[Any], *, path: str, depth: int) -> list[Any]:
    if len(value) > _MAX_LIST_LENGTH:
        raise LLMHarnessTelemetryError(f"{path} exceeds max telemetry list length")
    return [
        _validate_bounded_safe_value(item, path=f"{path}[{index}]", depth=depth + 1)
        for index, item in enumerate(value)
    ]


def _validate_safe_mapping(
    value: Mapping[Any, Any], *, path: str, depth: int
) -> dict[str, Any]:
    safe_mapping: dict[str, Any] = {}
    for raw_key, item in value.items():
        key = str(raw_key)
        nested_path = f"{path}.{key}"
        _validate_safe_key(key, path=nested_path)
        safe_mapping[key] = _validate_bounded_safe_value(
            item, path=nested_path, depth=depth + 1
        )
    return safe_mapping


def _validate_bounded_safe_value(value: Any, *, path: str, depth: int = 0) -> Any:
    if depth > _MAX_DEPTH:
        raise LLMHarnessTelemetryError(f"{path} exceeds max telemetry nesting depth")
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        return _validate_safe_string(value, path=path)
    if isinstance(value, list):
        return _validate_safe_list(value, path=path, depth=depth)
    if isinstance(value, Mapping):
        return _validate_safe_mapping(value, path=path, depth=depth)
    raise LLMHarnessTelemetryError(f"{path} has unsupported telemetry value type")


def _validate_safe_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for raw_key, value in payload.items():
        key = str(raw_key)
        _validate_safe_key(key, path=key)
        safe[key] = _validate_bounded_safe_value(value, path=key)
    return safe


def validate_llm_harness_event(
    event_type: str, payload: Mapping[str, Any]
) -> dict[str, Any]:
    """Validate and return the bounded payload allowed for persisted harness events."""
    if event_type not in LLM_HARNESS_EVENT_TYPES:
        raise LLMHarnessTelemetryError(
            f"unsupported llm_harness event_type: {event_type}"
        )
    if not isinstance(payload, Mapping):
        raise LLMHarnessTelemetryError("llm_harness payload must be an object")
    missing = _missing_required_fields(event_type, payload)
    if missing:
        raise LLMHarnessTelemetryError(
            f"llm_harness event missing required fields: {', '.join(missing)}"
        )
    _validate_numeric_fields(payload)
    safe = _validate_safe_payload(payload)
    safe.setdefault("recorded_at", utc_now())
    return safe


def record_llm_harness_event(
    store: Any,
    *,
    event_type: str,
    payload: Mapping[str, Any],
    idempotency_key: str = "",
) -> tuple[int, bool]:
    """Persist one validated harness event through the control-plane event store."""
    safe_payload = validate_llm_harness_event(event_type, payload)
    trace_or_run = _text(safe_payload.get("run_id") or safe_payload.get("trace_id"))
    entity_id = trace_or_run or _text(safe_payload.get("workflow_id"))
    event_key = idempotency_key or (
        f"{event_type}:{entity_id}:{_text(safe_payload.get('status'))}:"
        f"{_text(safe_payload.get('completed_at'))}:{_json_hash(safe_payload)}"
    )
    return store.append_event(
        idempotency_key=event_key,
        event_type=event_type,
        entity_type="llm_harness",
        entity_id=entity_id,
        payload=safe_payload,
    )
