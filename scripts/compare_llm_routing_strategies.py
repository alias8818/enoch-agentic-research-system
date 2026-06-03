#!/usr/bin/env python3
"""Compare native provider routing with read-only LLM sidecar routing evidence."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from dataclasses import asdict, dataclass, field
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
    missing_metrics: tuple[str, ...] = ()

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
        for metric in METRIC_DEFINITIONS:
            data[metric] = None if metric in self.missing_metrics else _metric_value(self, metric)
        return data


@dataclass
class SidecarMetricAccumulator:
    trace_ids: set[str] = field(default_factory=set)
    route_failures: int = 0
    malformed_outputs: int = 0
    contract_passes: int = 0
    contract_checks: int = 0
    admitted_candidates: int = 0
    useful_sources: int = 0
    checked_sources: int = 0
    cost_by_trace: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    unscoped_cost: float = 0.0
    valid_cost_observations: int = 0

    def observe(self, payload: Mapping[str, Any]) -> None:
        event_type = _text(payload.get("event_type"))
        trace_id = _text(payload.get("trace_id") or payload.get("run_id"))
        handlers = {
            "llm_harness.route_decision": self._observe_route_decision,
            "llm_harness.output_contract": self._observe_output_contract,
            "llm_harness.tool_result": self._observe_tool_result,
            "llm_harness.cost_observation": self._observe_cost_observation,
        }
        handler = handlers.get(event_type)
        if handler:
            handler(payload, trace_id)

    def _observe_route_decision(
        self, payload: Mapping[str, Any], trace_id: str
    ) -> None:
        if trace_id:
            self.trace_ids.add(trace_id)
        blocked = _text(payload.get("budget_gate_status")) == "blocked"
        if _status_failed(payload) or blocked:
            self.route_failures += 1

    def _observe_output_contract(
        self, payload: Mapping[str, Any], _trace_id: str
    ) -> None:
        self.contract_checks += 1
        if _contract_passed(payload):
            self.contract_passes += 1
        else:
            self.malformed_outputs += 1
        self.admitted_candidates += _integer(
            payload, "admitted_candidate_count", "accepted_candidate_count"
        )

    def _observe_tool_result(self, payload: Mapping[str, Any], _trace_id: str) -> None:
        self.useful_sources += _integer(payload, "useful_source_count")
        self.checked_sources += _integer(payload, "checked_source_count")

    def _observe_cost_observation(
        self, payload: Mapping[str, Any], trace_id: str
    ) -> None:
        cost = _number_optional(payload, "estimated_cost_usd")
        if cost is None:
            return
        self.valid_cost_observations += 1
        if trace_id:
            self.cost_by_trace[trace_id] += cost
        else:
            self.unscoped_cost += cost

    def metrics(self) -> RoutingMetrics:
        missing_metrics = (
            ("cost_per_admitted_candidate",) if self.valid_cost_observations <= 0 else ()
        )
        return RoutingMetrics(
            attempts=len(self.trace_ids),
            total_cost_usd=round(
                sum(self.cost_by_trace.values()) + self.unscoped_cost, 6
            ),
            admitted_candidates=self.admitted_candidates,
            provider_failures=self.route_failures,
            malformed_outputs=self.malformed_outputs,
            output_contract_passes=self.contract_passes,
            output_contract_checks=self.contract_checks,
            useful_sources=self.useful_sources,
            checked_sources=self.checked_sources,
            missing_metrics=missing_metrics,
        )


def _rate(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 6)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _number_optional(row: Mapping[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = row.get(key)
        if value is None or value == "":
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _number(row: Mapping[str, Any], *keys: str) -> float:
    return _number_optional(row, *keys) or 0.0


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
    missing_metrics = []
    if attempts and any(_number_optional(row, "estimated_cost_usd", "cost_usd") is None for row in rows):
        missing_metrics.append("cost_per_admitted_candidate")
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
        missing_metrics=tuple(missing_metrics),
    )


def _event_payload(row: Mapping[str, Any]) -> Mapping[str, Any]:
    payload = row.get("payload")
    return payload if isinstance(payload, Mapping) else row


def sidecar_routing_metrics(events: Iterable[Mapping[str, Any]]) -> RoutingMetrics:
    accumulator = SidecarMetricAccumulator()
    for row in events:
        accumulator.observe(_event_payload(row))
    return accumulator.metrics()


def _metric_value(metrics: RoutingMetrics, name: str) -> float | None:
    if name in metrics.missing_metrics:
        return None
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
