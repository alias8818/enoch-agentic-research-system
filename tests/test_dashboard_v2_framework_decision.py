from pathlib import Path

DOC = Path("docs/dashboard-v2-framework-decision.md")


def test_framework_decision_records_stay_with_vite() -> None:
    text = DOC.read_text(encoding="utf-8")
    assert "decision: stay-with-vite" in text
    assert "## Decision" in text
    assert "**Stay with Vite.**" in text
    for section in (
        "## Symptom / risk",
        "## Invariant",
        "## Evaluation criteria",
        "## Revisit triggers",
    ):
        assert section in text


def test_framework_decision_does_not_mandate_nextjs_migration() -> None:
    text = DOC.read_text(encoding="utf-8")
    assert "not justified" in text.lower()
