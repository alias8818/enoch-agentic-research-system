"""Read-only Research Facility quality-audit helpers.

This package is intentionally sidecar-only. It must not dispatch work, mutate
queue state, or override deterministic Enoch gates.
"""

from .artifacts import build_quality_report

__all__ = ["build_quality_report"]
