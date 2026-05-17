from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def parse_utc_datetime(value: Any) -> datetime | None:
    """Parse an ISO-like timestamp and normalize timezone-naive values to UTC."""

    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
