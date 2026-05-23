from __future__ import annotations

from typing import Any


def dspy_available() -> bool:
    try:
        import dspy  # noqa: F401
    except ImportError:
        return False
    return True


def candidate_quality_signature() -> Any:
    """Return a DSPy Signature class when the optional dependency is installed."""

    import dspy

    class CandidateQuality(dspy.Signature):
        """Score whether an Enoch research candidate is novel, falsifiable, non-shallow, and worth bounded worker time."""

        candidate_json: str = dspy.InputField()
        recent_negative_patterns: str = dspy.InputField()
        quality_score: float = dspy.OutputField(
            desc="0.0 to 1.0 semantic quality score"
        )
        verdict: str = dspy.OutputField(desc="admit, needs_review, or reject")
        reason: str = dspy.OutputField(desc="short evidence-grounded explanation")

    return CandidateQuality


def decision_quality_signature() -> Any:
    """Return a DSPy Signature class when the optional dependency is installed."""

    import dspy

    class DecisionQuality(dspy.Signature):
        """Audit whether an Enoch project_decision artifact is specific, evidence-grounded, and safely follow-up bounded."""

        decision_json: str = dspy.InputField()
        run_artifact_summary: str = dspy.InputField()
        decision_quality_score: float = dspy.OutputField(
            desc="0.0 to 1.0 quality score"
        )
        paper_gate_risk: str = dspy.OutputField(desc="low, medium, or high")
        problems: list[str] = dspy.OutputField(desc="specific quality problems")

    return DecisionQuality
