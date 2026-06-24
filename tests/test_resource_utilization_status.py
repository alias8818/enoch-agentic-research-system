"""Regression tests for #238: resource_utilization_status must respect severity.

The previous implementation collapsed every non-empty findings list into
``status="blocked"`` regardless of the per-finding ``severity``. These tests
lock in the new semantics:

  * ``"clean"`` when no findings
  * ``"warn"`` when at least one finding and none are ``"critical"``
  * ``"blocked"`` only when at least one finding is ``"critical"``

``ok`` continues to be ``False`` for any non-empty findings list so the
readiness-blocker path is preserved. ``status`` is now the operator-visible
severity classifier.
"""

from __future__ import annotations

import pytest

from enoch_control_plane.control_plane.models import DashboardFinding
from enoch_control_plane.control_plane.resource_utilization import (
    resource_utilization_status,
)


def _finding(severity: str) -> DashboardFinding:
    return DashboardFinding(
        severity=severity,  # type: ignore[arg-type]
        source="worker_resource_policy",
        authority="GB10 worker telemetry",
        message=f"test {severity}",
    )


def test_empty_findings_yields_clean_status_and_info_severity() -> None:
    result = resource_utilization_status([])

    assert result["ok"] is True
    assert result["status"] == "clean"
    assert result["highest_severity"] == "info"
    assert result["severity_counts"] == {"info": 0, "warn": 0, "critical": 0}
    assert result["finding_count"] == 0
    assert result["findings"] == []


def test_warn_only_findings_do_not_collapse_to_blocked() -> None:
    """Regression for #238: warn findings must surface as ``"warn"``.

    The bug was that every non-empty findings list was labelled
    ``"blocked"`` regardless of severity, which forced the manual-review
    flow even for informational signals.
    """
    findings = [_finding("warn"), _finding("warn")]

    result = resource_utilization_status(findings)

    assert result["ok"] is False
    assert result["status"] == "warn"
    assert result["highest_severity"] == "warn"
    assert result["severity_counts"] == {"info": 0, "warn": 2, "critical": 0}
    assert result["finding_count"] == 2


def test_critical_finding_escalates_status_to_blocked() -> None:
    findings = [_finding("warn"), _finding("critical")]

    result = resource_utilization_status(findings)

    assert result["ok"] is False
    assert result["status"] == "blocked"
    assert result["highest_severity"] == "critical"
    assert result["severity_counts"] == {"info": 0, "warn": 1, "critical": 1}


def test_info_only_findings_yield_warn_status() -> None:
    """An ``info`` finding is below ``warn`` severity but is still a finding.

    ``status`` must reflect "there is a finding" (so ``warn``), not the
    severity value itself (``info`` would imply no problem).
    """
    findings = [_finding("info")]

    result = resource_utilization_status(findings)

    assert result["ok"] is False
    assert result["status"] == "warn"
    assert result["highest_severity"] == "info"


def test_highest_severity_picks_max_across_mixed_findings() -> None:
    findings = [_finding("info"), _finding("warn"), _finding("info")]

    result = resource_utilization_status(findings)

    assert result["highest_severity"] == "warn"
    assert result["status"] == "warn"
    assert result["severity_counts"] == {"info": 2, "warn": 1, "critical": 0}


def test_blocked_status_requires_at_least_one_critical_finding() -> None:
    """Property: any findings list with no ``critical`` yields ``"warn"``."""
    severities = ("info", "warn")

    for n in range(1, 4):
        for combo in [tuple([s] * n) for s in severities] + [tuple(severities) * n]:
            findings = [_finding(s) for s in combo]
            result = resource_utilization_status(findings)
            assert result["status"] == "warn", (
                f"expected warn for severities={combo}, got {result['status']}"
            )


@pytest.mark.parametrize("n_critical", [1, 2, 3])
def test_blocked_status_holds_when_critical_is_present(n_critical: int) -> None:
    findings = [_finding("warn")] + [_finding("critical")] * n_critical

    result = resource_utilization_status(findings)

    assert result["status"] == "blocked"
    assert result["highest_severity"] == "critical"
    assert result["severity_counts"]["critical"] == n_critical


def test_finding_payloads_are_still_serialized_unchanged() -> None:
    findings = [_finding("warn")]

    result = resource_utilization_status(findings)

    assert len(result["findings"]) == 1
    assert result["findings"][0]["severity"] == "warn"
    assert result["findings"][0]["source"] == "worker_resource_policy"
