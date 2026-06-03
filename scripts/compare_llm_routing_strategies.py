#!/usr/bin/env python3
"""Compare native provider routing with read-only LLM sidecar routing evidence."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

NATIVE_ROUTING_AUTHORITY = "native_enoch_provider_routing"
SIDECAR_REVIEW_DECISION = "sidecar_candidate_for_manual_review"
KEEP_NATIVE_DECISION = "keep_native_authority"
INSUFFICIENT_DATA_DECISION = "insufficient_data"

METRIC_DEFINITIONS = {
    "cost_per_admitted_candidate": (
        "total estimated provider/tool cost divided by admitted candidate count"
    ),
    "provider_failure_rate": "failed route/provider attempts divided by attempts",
    "malformed_output_rate": "malformed or rejected structured outputs divided by attempts",
    "output_contract_pass_rate": "passed structured-output contracts divided by checked contracts",
    "admitted_candidate_yield": "admitted candidates divided by attempts",
    "source_usefulness_rate": "useful sources divided by checked sources",
}


@dataclass(frozen=True)
class RoutingMetrics:
    attempts: int
    total_cost_usd: float
    admitted_candidates: int
    provider_failures: int
    malformed_outputs: int
    output_contract_passes: int
    output_contract_checks: int
    useful_sources: int
    checked_sources: int

    @property
    def cost_per_admitted_candidate(self) -> float | None:
        if self.admitted_candidates <= 0:
            return None
        return round(self.total_cost_usd / self.admitted_candidates, 6)

    @property
    def provider_failure_rate(self) -> float | None:
        return _rate(self.provider_failures, self.attempts)

    @property
    def malformed_output_rate(self) -> float | None:
        return _rate(self.malformed_outputs, self.attempts)

    @property
    def output_contract_pass_rate(self) -> float | None:
        return _rate(self.output_contract_passes, self.output_contract_checks)

    @property
    def admitted_candidate_yield(self) -> float | None:
        return _rate(self.admitted_candidates, self.attempts)

    @property
    def source_usefulness_rate(self) -> float | None:
        return _rate(self.useful_sources, self.checked_sources)

    def report(self) -> dict[str, Any]:
        data = asdict(self)
        data.update(
            {
                "cost_per_admitted_candidate": self.cost_per_admitted_candidate,
                "provider_failure_rate": self.provider_failure_rate,
                "malformed_output_rate": self.malformed_output_rate,
                "output_contract_pass_rate": self.output_contract_pass_rate,
                "admitted_candidate_yield": self.admitted_candidate_yield,
                "source_usefulness_rate": self.source_usefulness_rate,
            }
        )
        return data


def _rate(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 6)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _number(row: Mapping[str, Any], *keys: str) -> float:
    for key in keys:
        value = row.get(key)
        if value is None or value == "":
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return 0.0


def _integer(row: Mapping[str, Any], *keys: str) -> int:
    return int(_number(row, *keys))


def _status_failed(row: Mapping[str, Any]) -> bool:
    status = _text(row.get("status")).lower()
    if status in {"ok", "success", "succeeded", "healthy", "passed"}:
        return False
    if status in {"failed", "error", "unhealthy", "blocked", "rejected"}:
        return True
    return bool(_text(row.get("failure_kind") or row.get("error_kind")))


def _contract_passed(row: Mapping[str, Any]) -> bool:
    status = _text(row.get("contract_status") or row.get("status")).lower()
    return status in {"ok", "success", "succeeded", "passed", "accepted"}


def _contract_checked(row: Mapping[str, Any]) -> bool:
    return bool(
        _text(row.get("contract_status"))
        or _text(row.get("status"))
        or _integer(row, "output_contract_checks", "contract_checks")
    )


def native_routing_metrics(records: Iterable[Mapping[str, Any]]) -> RoutingMetrics:
    rows = list(records)
    attempts = len(rows)
    contract_checks = sum(
        _integer(row, "output_contract_checks", "contract_checks")
        or (1 if _contract_checked(row) else 0)
        for row in rows
    )
    contract_passes = sum(
        _integer(row, "output_contract_passes", "contract_passes")
        or (1 if _contract_passed(row) else 0)
        for row in rows
    )
    return RoutingMetrics(
        attempts=attempts,
        total_cost_usd=round(
            sum(_number(row, "estimated_cost_usd", "cost_usd") for row in rows), 6
        ),
        admitted_candidates=sum(
            _integer(row, "admitted_candidate_count", "promoted_count") for row in rows
        ),
        provider_failures=sum(1 for row in rows if _status_failed(row)),
        malformed_outputs=sum(
            _integer(
                row,
                "malformed_output_count",
                "malformed_provider_response_count",
                "rejected_output_count",
            )
            for row in rows
        ),
        output_contract_passes=contract_passes,
        output_contract_checks=contract_checks,
        useful_sources=sum(_integer(row, "useful_source_count") for row in rows),
        checked_sources=sum(_integer(row, "checked_source_count") for row in rows),
    )


def _event_payload(row: Mapping[str, Any]) -> Mapping[str, Any]:
    payload = row.get("payload")
    return payload if isinstance(payload, Mapping) else row


def sidecar_routing_metrics(events: Iterable[Mapping[str, Any]]) -> RoutingMetrics:
    payloads = [_event_payload(row) for row in events]
    trace_ids: set[str] = set()
    route_failures = 0
    malformed_outputs = 0
    contract_passes = 0
    contract_checks = 0
    admitted_candidates = 0
    useful_sources = 0
    checked_sources = 0
    cost_by_trace: dict[str, float] = defaultdict(float)
    unscoped_cost = 0.0

    for payload in payloads:
        event_type = _text(payload.get("event_type"))
        trace_id = _text(payload.get("trace_id") or payload.get("run_id"))
        if event_type == "llm_harness.route_decision":
            if trace_id:
                trace_ids.add(trace_id)
            if (
                _status_failed(payload)
                or _text(payload.get("budget_gate_status")) == "blocked"
            ):
                route_failures += 1
        if event_type == "llm_harness.output_contract":
            contract_checks += 1
            if _contract_passed(payload):
                contract_passes += 1
            else:
                malformed_outputs += 1
            admitted_candidates += _integer(
                payload, "admitted_candidate_count", "accepted_candidate_count"
            )
        if event_type == "llm_harness.tool_result":
            useful_sources += _integer(payload, "useful_source_count")
            checked_sources += _integer(payload, "checked_source_count")
        if event_type == "llm_harness.cost_observation":
            cost = _number(payload, "estimated_cost_usd")
            if trace_id:
                cost_by_trace[trace_id] += cost
            else:
                unscoped_cost += cost

    return RoutingMetrics(
        attempts=len(trace_ids),
        total_cost_usd=round(sum(cost_by_trace.values()) + unscoped_cost, 6),
        admitted_candidates=admitted_candidates,
        provider_failures=route_failures,
        malformed_outputs=malformed_outputs,
        output_contract_passes=contract_passes,
        output_contract_checks=contract_checks,
        useful_sources=useful_sources,
        checked_sources=checked_sources,
    )


def _metric_value(metrics: RoutingMetrics, name: str) -> float | None:
    value = getattr(metrics, name)
    return value() if callable(value) else value


def _comparison_row(
    native: RoutingMetrics,
    sidecar: RoutingMetrics,
    name: str,
    *,
    higher_is_better: bool,
) -> dict[str, Any]:
    native_value = _metric_value(native, name)
    sidecar_value = _metric_value(sidecar, name)
    if native_value is None or sidecar_value is None:
        result = "incomplete"
    elif higher_is_better:
        result = (
            "sidecar_better_or_equal"
            if sidecar_value >= native_value
            else "native_better"
        )
    else:
        result = (
            "sidecar_better_or_equal"
            if sidecar_value <= native_value
            else "native_better"
        )
    return {
        "metric": name,
        "native": native_value,
        "sidecar": sidecar_value,
        "higher_is_better": higher_is_better,
        "result": result,
    }


def compare_routing_strategies(
    native_records: Iterable[Mapping[str, Any]],
    sidecar_events: Iterable[Mapping[str, Any]],
    *,
    min_attempts: int = 5,
) -> dict[str, Any]:
    native = native_routing_metrics(native_records)
    sidecar = sidecar_routing_metrics(sidecar_events)
    comparisons = [
        _comparison_row(
            native, sidecar, "cost_per_admitted_candidate", higher_is_better=False
        ),
        _comparison_row(
            native, sidecar, "provider_failure_rate", higher_is_better=False
        ),
        _comparison_row(
            native, sidecar, "malformed_output_rate", higher_is_better=False
        ),
        _comparison_row(
            native, sidecar, "output_contract_pass_rate", higher_is_better=True
        ),
        _comparison_row(
            native, sidecar, "admitted_candidate_yield", higher_is_better=True
        ),
        _comparison_row(
            native, sidecar, "source_usefulness_rate", higher_is_better=True
        ),
    ]
    incomplete_reasons: list[str] = []
    if native.attempts < min_attempts:
        incomplete_reasons.append("native attempts below minimum")
    if sidecar.attempts < min_attempts:
        incomplete_reasons.append("sidecar attempts below minimum")
    incomplete_reasons.extend(
        f"missing metric: {row['metric']}"
        for row in comparisons
        if row["result"] == "incomplete"
    )
    if incomplete_reasons:
        decision = INSUFFICIENT_DATA_DECISION
    elif all(row["result"] == "sidecar_better_or_equal" for row in comparisons):
        decision = SIDECAR_REVIEW_DECISION
    else:
        decision = KEEP_NATIVE_DECISION
    return {
        "production_authority": NATIVE_ROUTING_AUTHORITY,
        "decision": decision,
        "min_attempts": min_attempts,
        "incomplete_reasons": incomplete_reasons,
        "metric_definitions": METRIC_DEFINITIONS,
        "native_metrics": native.report(),
        "sidecar_metrics": sidecar.report(),
        "comparisons": comparisons,
        "mutates_production_routing": False,
    }


def _read_json(path: str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare native LLM routing with sidecar routing telemetry."
    )
    parser.add_argument(
        "--native-json", required=True, help="JSON array of native records"
    )
    parser.add_argument(
        "--sidecar-json", required=True, help="JSON array of sidecar events"
    )
    parser.add_argument("--min-attempts", type=int, default=5)
    args = parser.parse_args()
    report = compare_routing_strategies(
        _read_json(args.native_json),
        _read_json(args.sidecar_json),
        min_attempts=max(1, args.min_attempts),
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
