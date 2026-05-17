from __future__ import annotations

import json
from pathlib import Path

from scripts.agentic_property_testing import execute_proposals, write_prompt


def test_agentic_property_testing_writes_llm_prompt(tmp_path: Path) -> None:
    repo = tmp_path
    target = repo / "sample.py"
    target.write_text("def identity(value):\n    return value\n", encoding="utf-8")
    output = repo / "prompt.md"

    write_prompt(repo, target, output, max_chars=1000)

    text = output.read_text(encoding="utf-8")
    assert "Agentic property-based testing request" in text
    assert "def identity" in text
    assert "hypothesis" in text.lower()


def test_agentic_property_testing_records_counterexample_report(tmp_path: Path) -> None:
    repo = tmp_path
    module = repo / "buggy_module.py"
    module.write_text("def absolute(value: int) -> int:\n    return value\n", encoding="utf-8")
    proposals = repo / "proposals.json"
    proposals.write_text(
        json.dumps(
            {
                "tests": [
                    {
                        "name": "absolute_is_non_negative",
                        "rationale": "absolute values should be non-negative",
                        "code": "from hypothesis import given, strategies as st\nfrom buggy_module import absolute\n\n@given(st.integers(max_value=-1))\ndef test_absolute_is_non_negative(value):\n    assert absolute(value) >= 0\n",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    result = execute_proposals(repo, proposals, repo / "reports")

    assert result["status"] == "counterexample_found"
    assert "agent" in result["next_action"]
    assert "human" not in result["next_action"].lower()
    report = Path(result["report_path"]).read_text(encoding="utf-8")
    assert "absolute_is_non_negative" in report
    assert "Exit code: `1`" in report
    assert "No operator action required" in report


def test_agentic_property_testing_classifies_collection_errors_as_proposal_error(tmp_path: Path) -> None:
    repo = tmp_path
    proposals = repo / "proposals.json"
    proposals.write_text(
        json.dumps(
            {
                "tests": [
                    {
                        "name": "invalid_collection_time_api",
                        "rationale": "invalid generated test code should not count as a product counterexample",
                        "code": "from hypothesis import given, strategies as st\n\n@given(st.paths())\ndef test_invalid(value):\n    assert value\n",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    result = execute_proposals(repo, proposals, repo / "reports")

    assert result["status"] == "proposal_error"
    assert result["agentic_terminal"] is True
    assert "regenerate" in result["next_action"]
    assert "human" not in result["next_action"].lower()
    report = Path(result["report_path"]).read_text(encoding="utf-8")
    assert "Agentic PBT report - proposal_error" in report
    assert "Exit code: `2`" in report
    assert "No operator action required" in report
