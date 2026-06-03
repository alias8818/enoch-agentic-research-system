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
REQUIRED_SECTIONS = [
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
REQUIRED_PHRASES = {
    "Keep native Enoch provider routing as the production authority.": (
        "missing native-routing recommendation"
    ),
    "Trial a bounded agentic sidecar": "missing bounded-sidecar trial recommendation",
    "No raw provider response": "missing raw payload/secret exclusion",
    "insufficient_data": "missing incomplete-data decision",
    "sidecar_candidate_for_manual_review": (
        "missing manual-review-only sidecar decision"
    ),
}


def _missing_entries(text: str, entries: list[str], message: str) -> list[str]:
    return [message.format(item=item) for item in entries if item not in text]


def _missing_phrases(text: str) -> list[str]:
    return [
        message for phrase, message in REQUIRED_PHRASES.items() if phrase not in text
    ]


def validation_failures(text: str) -> list[str]:
    return [
        *_missing_entries(text, REQUIRED_SECTIONS, "missing section: {item}"),
        *_missing_entries(
            text, REQUIRED_WORKFLOWS, "missing workflow inventory row: {item}"
        ),
        *_missing_entries(text, REQUIRED_EVENTS, "missing telemetry event: {item}"),
        *_missing_entries(text, REQUIRED_INVARIANTS, "missing invariant: {item}"),
        *_missing_entries(
            text, REQUIRED_COMPARISON_METRICS, "missing comparison metric: {item}"
        ),
        *_missing_phrases(text),
    ]


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
