from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from enoch_control_plane.timeutils import parse_utc_datetime


QUALITY_REPORT_STALE_AFTER_HOURS = 48.0


def research_quality_report_freshness(
    report_mtime: Any,
    *,
    now: datetime | None = None,
    stale_after_hours: float = QUALITY_REPORT_STALE_AFTER_HOURS,
) -> dict[str, Any]:
    checked_at = now or datetime.now(timezone.utc)
    if checked_at.tzinfo is None:
        checked_at = checked_at.replace(tzinfo=timezone.utc)
    parsed = parse_utc_datetime(str(report_mtime or ""))
    if parsed is None:
        return {
            "report_age_hours": None,
            "report_stale_after_hours": stale_after_hours,
            "report_is_stale": False,
            "freshness_summary": (
                "quality report freshness unavailable; refresh before relying on "
                "unattended automation"
            ),
        }
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    age_hours = round(
        max(0.0, (checked_at.astimezone(timezone.utc) - parsed).total_seconds())
        / 3600.0,
        1,
    )
    is_stale = age_hours > stale_after_hours
    state = "stale" if is_stale else "fresh"
    action = "refresh before relying on" if is_stale else "safe for"
    return {
        "report_age_hours": age_hours,
        "report_stale_after_hours": stale_after_hours,
        "report_is_stale": is_stale,
        "freshness_summary": (
            f"quality report {state}: {age_hours:.1f}h old; "
            f"{action} unattended automation"
        ),
    }
