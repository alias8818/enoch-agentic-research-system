from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from enoch_control_plane.control_plane.alerts import queue_alert_findings


def test_queue_alert_findings_normalizes_datetime_freshness_observed_at() -> None:
    observed_at = datetime(2026, 5, 15, 12, 14, tzinfo=timezone.utc)
    status = SimpleNamespace(
        flags=SimpleNamespace(queue_paused=False, maintenance_mode=False),
        config=SimpleNamespace(live_dispatch_enabled=True),
        conflicts=[],
        active_items=[],
        warnings=[],
        source_freshness={
            "worker_preflight": SimpleNamespace(
                stale=True,
                authority="dashboard_observations",
                observed_at=observed_at,
            )
        },
    )

    findings = queue_alert_findings(status, hang_after_sec=3600)  # type: ignore[arg-type]

    assert len(findings) == 1
    assert findings[0].observed_at == observed_at.isoformat()
