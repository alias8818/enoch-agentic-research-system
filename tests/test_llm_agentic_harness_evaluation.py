from __future__ import annotations

from pathlib import Path

from scripts import validate_llm_agentic_harness_evaluation as validator


def test_llm_agentic_harness_evaluation_contract_is_valid() -> None:
    text = Path("docs/llm-agentic-harness-evaluation.md").read_text(encoding="utf-8")

    assert validator.validation_failures(text) == []


def test_llm_agentic_harness_evaluation_requires_all_workflows() -> None:
    text = Path("docs/llm-agentic-harness-evaluation.md").read_text(encoding="utf-8")
    broken = text.replace("Model health probes", "Model probes")

    assert "missing workflow inventory row: Model health probes" in (
        validator.validation_failures(broken)
    )


def test_llm_agentic_harness_evaluation_requires_comparison_metrics() -> None:
    text = Path("docs/llm-agentic-harness-evaluation.md").read_text(encoding="utf-8")
    broken = text.replace("source_usefulness_rate", "source_rate")

    assert "missing comparison metric: source_usefulness_rate" in (
        validator.validation_failures(broken)
    )
