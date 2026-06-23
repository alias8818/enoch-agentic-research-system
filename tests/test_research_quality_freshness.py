from __future__ import annotations

from datetime import datetime, timezone

import pytest

from enoch_control_plane.control_plane.research_quality_freshness import (
    research_quality_report_freshness,
)


@pytest.mark.parametrize("report_mtime", [None, "", "not-a-timestamp"])
def test_unparseable_quality_report_mtime_is_stale(report_mtime: object) -> None:
    result = research_quality_report_freshness(
        report_mtime,
        now=datetime(2026, 6, 23, 12, 0, tzinfo=timezone.utc),
        stale_after_hours=48.0,
    )

    assert result["report_is_stale"] is True
    assert result["report_is_unparseable"] is True
    assert result["report_age_hours"] is None
    assert "freshness unavailable" in result["freshness_summary"]


def test_parseable_recent_quality_report_mtime_remains_fresh() -> None:
    result = research_quality_report_freshness(
        "2026-06-23T11:00:00+00:00",
        now=datetime(2026, 6, 23, 12, 0, tzinfo=timezone.utc),
        stale_after_hours=48.0,
    )

    assert result["report_is_stale"] is False
    assert result["report_is_unparseable"] is False
    assert result["report_age_hours"] == 1.0
