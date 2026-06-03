from __future__ import annotations

from pathlib import Path

from scripts.compare_llm_routing_strategies import (
    INSUFFICIENT_DATA_DECISION,
    NATIVE_ROUTING_AUTHORITY,
    SIDECAR_REVIEW_DECISION,
    compare_routing_strategies,
    native_routing_metrics,
    sidecar_routing_metrics,
)


def _native_records() -> list[dict[str, object]]:
    return [
        {
            "status": "success",
            "estimated_cost_usd": 0.03,
            "promoted_count": 1,
            "malformed_provider_response_count": 0,
            "contract_status": "passed",
            "useful_source_count": 3,
            "checked_source_count": 5,
        },
        {
            "status": "success",
            "estimated_cost_usd": 0.03,
            "promoted_count": 1,
            "malformed_provider_response_count": 1,
            "contract_status": "passed",
            "useful_source_count": 2,
            "checked_source_count": 5,
        },
    ]


def _sidecar_events() -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    for index in range(2):
        trace_id = f"trace-{index}"
        events.extend(
            [
                {
                    "event_type": "llm_harness.route_decision",
                    "trace_id": trace_id,
                    "status": "ok",
                    "budget_gate_status": "passed",
                },
                {
                    "event_type": "llm_harness.tool_result",
                    "trace_id": trace_id,
                    "status": "ok",
                    "useful_source_count": 4,
                    "checked_source_count": 5,
                },
                {
                    "event_type": "llm_harness.output_contract",
                    "trace_id": trace_id,
                    "status": "ok",
                    "admitted_candidate_count": 2,
                },
                {
                    "event_type": "llm_harness.cost_observation",
                    "trace_id": trace_id,
                    "status": "ok",
                    "estimated_cost_usd": 0.01,
                },
            ]
        )
    return events


def test_native_routing_metrics_compute_required_rates() -> None:
    metrics = native_routing_metrics(_native_records())

    assert metrics.attempts == 2
    assert metrics.total_cost_usd == 0.06
    assert metrics.admitted_candidates == 2
    assert metrics.malformed_output_rate == 0.5
    assert metrics.source_usefulness_rate == 0.5
    assert metrics.cost_per_admitted_candidate == 0.03


def test_sidecar_metrics_use_harness_events_without_raw_payloads() -> None:
    metrics = sidecar_routing_metrics(_sidecar_events())

    assert metrics.attempts == 2
    assert metrics.total_cost_usd == 0.02
    assert metrics.admitted_candidates == 4
    assert metrics.output_contract_pass_rate == 1.0
    assert metrics.source_usefulness_rate == 0.8
    assert metrics.cost_per_admitted_candidate == 0.005


def test_comparison_refuses_all_pass_when_data_is_incomplete() -> None:
    report = compare_routing_strategies(
        _native_records(),
        [
            {
                "event_type": "llm_harness.route_decision",
                "trace_id": "trace-1",
                "status": "ok",
            }
        ],
        min_attempts=2,
    )

    assert report["production_authority"] == NATIVE_ROUTING_AUTHORITY
    assert report["decision"] == INSUFFICIENT_DATA_DECISION
    assert "sidecar attempts below minimum" in report["incomplete_reasons"]
    assert any(
        reason.startswith("missing metric:") for reason in report["incomplete_reasons"]
    )
    assert report["mutates_production_routing"] is False


def test_comparison_treats_missing_sidecar_cost_as_incomplete() -> None:
    sidecar_without_cost = [
        event
        for event in _sidecar_events()
        if event["event_type"] != "llm_harness.cost_observation"
    ]

    report = compare_routing_strategies(
        _native_records(), sidecar_without_cost, min_attempts=2
    )

    assert report["decision"] == INSUFFICIENT_DATA_DECISION
    assert report["sidecar_metrics"]["cost_per_admitted_candidate"] is None
    assert "missing metric: cost_per_admitted_candidate" in report["incomplete_reasons"]


def test_comparison_treats_missing_native_cost_as_incomplete() -> None:
    native_without_cost = [dict(row) for row in _native_records()]
    native_without_cost[0].pop("estimated_cost_usd")

    report = compare_routing_strategies(
        native_without_cost, _sidecar_events(), min_attempts=2
    )

    assert report["decision"] == INSUFFICIENT_DATA_DECISION
    assert report["native_metrics"]["cost_per_admitted_candidate"] is None
    assert "missing metric: cost_per_admitted_candidate" in report["incomplete_reasons"]


def test_comparison_marks_sidecar_candidate_only_with_complete_better_metrics() -> None:
    report = compare_routing_strategies(
        _native_records(), _sidecar_events(), min_attempts=2
    )

    assert report["production_authority"] == NATIVE_ROUTING_AUTHORITY
    assert report["decision"] == SIDECAR_REVIEW_DECISION
    assert report["incomplete_reasons"] == []
    assert all(
        row["result"] == "sidecar_better_or_equal" for row in report["comparisons"]
    )


def test_comparison_script_does_not_import_production_mutation_surfaces() -> None:
    source = Path("scripts/compare_llm_routing_strategies.py").read_text(
        encoding="utf-8"
    )

    assert "create_control_plane_router" not in source
    assert "save_llm_settings" not in source
    assert "_live_dispatch" not in source
    assert "append_event(" not in source
