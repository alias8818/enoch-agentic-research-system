#!/usr/bin/env python3
"""Validate the ALI-124 LLM agentic harness evaluation contract."""

from __future__ import annotations

from pathlib import Path

DOC = Path("docs/llm-agentic-harness-evaluation.md")
REQUIRED_WORKFLOWS = [
    "Research candidate generation",
    "Research janitor review",
    "Paper drafting and rewrite",
    "Evidence checks",
    "Model health probes",
    "Idea generation and enrichment",
]
REQUIRED_EVENTS = [
    "llm_harness.route_decision",
    "llm_harness.tool_call",
    "llm_harness.tool_result",
    "llm_harness.output_contract",
    "llm_harness.cost_observation",
]
REQUIRED_INVARIANTS = [
    "Tool output is advisory evidence, never system truth.",
    "Tool allowlists are per workflow, not global.",
    "Structured output must pass the existing workflow parser or schema",
]
REQUIRED_COMPARISON_METRICS = [
    "cost_per_admitted_candidate",
    "provider_failure_rate",
    "malformed_output_rate",
    "output_contract_pass_rate",
    "admitted_candidate_yield",
    "source_usefulness_rate",
]


def validation_failures(text: str) -> list[str]:
    failures: list[str] = []
    required_sections = [
        "## Recommendation",
        "## Current workflow inventory",
        "## Tool policy",
        "## Deterministic telemetry contract",
        "## Boundary invariants",
        "## Cost and risk estimate",
        "## Native versus sidecar comparison metrics",
        "## Proof-of-concept plan",
        "## Implementation issues to create",
    ]
    for section in required_sections:
        if section not in text:
            failures.append(f"missing section: {section}")
    for workflow in REQUIRED_WORKFLOWS:
        if workflow not in text:
            failures.append(f"missing workflow inventory row: {workflow}")
    for event in REQUIRED_EVENTS:
        if event not in text:
            failures.append(f"missing telemetry event: {event}")
    for invariant in REQUIRED_INVARIANTS:
        if invariant not in text:
            failures.append(f"missing invariant: {invariant}")
    for metric in REQUIRED_COMPARISON_METRICS:
        if metric not in text:
            failures.append(f"missing comparison metric: {metric}")
    if "Keep native Enoch provider routing as the production authority." not in text:
        failures.append("missing native-routing recommendation")
    if "Trial a bounded agentic sidecar" not in text:
        failures.append("missing bounded-sidecar trial recommendation")
    if "No raw provider response" not in text:
        failures.append("missing raw payload/secret exclusion")
    if "insufficient_data" not in text:
        failures.append("missing incomplete-data decision")
    if "sidecar_candidate_for_manual_review" not in text:
        failures.append("missing manual-review-only sidecar decision")
    return failures


def main() -> int:
    text = DOC.read_text(encoding="utf-8")
    failures = validation_failures(text)
    if failures:
        for failure in failures:
            print(f"FAIL {failure}")
        return 1
    print("PASS LLM agentic harness evaluation contract")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
