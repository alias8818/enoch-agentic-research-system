from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from ..models import utc_now


_logger = logging.getLogger(__name__)

logger = logging.getLogger("enoch.analytics")

# Lightweight product analytics for the internal control plane.
# Records feature usage events to a JSONL file, enabling operators and agents
# to measure which API endpoints and features are actually used.


class AnalyticsCollector:
    """File-backed analytics event collector.

    Records named events with metadata to a JSONL file. No external
    analytics service is required. Events can be analyzed with jq or
    any JSON processing tool.

    Usage:
        analytics = AnalyticsCollector(Path(".local/state/analytics.jsonl"))
        analytics.track("dispatch_attempt", lane="cpu", project_id="abc")
    """

    def __init__(self, path: Path | None = None) -> None:
        self._path = path
        if self._path is not None:
            self._path.parent.mkdir(parents=True, exist_ok=True)

    def track(self, event: str, **properties: Any) -> None:
        """Record a named analytics event with optional properties."""
        if self._path is None:
            logger.debug(
                "Analytics event (no path configured): %s %s", event, properties
            )
            return

        record = {
            "event": event,
            "timestamp": utc_now(),
            "properties": properties,
        }
        try:
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, sort_keys=True) + "\n")
        except OSError:
            logger.debug("Failed to write analytics event: %s", event)

    def count_events(self, event: str | None = None) -> int:
        """Count recorded events, optionally filtered by name."""
        if self._path is None or not self._path.exists():
            return 0
        count = 0
        try:
            with self._path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    if event is None:
                        count += 1
                    else:
                        record = json.loads(line)
                        if record.get("event") == event:
                            count += 1
        except (OSError, json.JSONDecodeError) as exc:
            _logger.debug("failed to read route observation row", exc_info=exc)
        return count
