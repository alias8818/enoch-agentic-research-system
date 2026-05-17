from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from enoch_control_plane.control_plane.alerts import queue_alert_findings
from enoch_control_plane.control_plane.models import DashboardObservationRecord


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



def test_queue_alert_findings_normalizes_datetime_active_lane_observed_at() -> None:
    updated_at = datetime(2026, 5, 15, 10, 0, tzinfo=timezone.utc)
    status = SimpleNamespace(
        flags=SimpleNamespace(queue_paused=False, maintenance_mode=False),
        config=SimpleNamespace(live_dispatch_enabled=True),
        conflicts=[],
        active_items=[{"project_id": "p", "current_run_id": "r", "updated_at": updated_at}],
        warnings=[],
        source_freshness={},
    )

    findings = queue_alert_findings(status, hang_after_sec=1)  # type: ignore[arg-type]

    assert len(findings) == 1
    assert findings[0].observed_at == updated_at.isoformat()


def test_queue_alert_findings_suppresses_old_active_row_when_worker_is_live() -> None:
    updated_at = datetime(2026, 5, 15, 10, 0, tzinfo=timezone.utc)
    status = SimpleNamespace(
        flags=SimpleNamespace(queue_paused=False, maintenance_mode=False),
        config=SimpleNamespace(live_dispatch_enabled=True),
        conflicts=[],
        active_items=[{"project_id": "p", "current_run_id": "r", "updated_at": updated_at}],
        warnings=[],
        source_freshness={},
        observations={
            "worker_preflight": {
                "payload": {
                    "checks": [
                        {
                            "name": "wake_gate_runs",
                            "data": {
                                "body": {
                                    "runs": [
                                        {
                                            "run_id": "r",
                                            "is_live": True,
                                            "lifecycle_state": "active",
                                            "active_process_count": 3,
                                        }
                                    ]
                                }
                            },
                        }
                    ]
                }
            }
        },
    )

    findings = queue_alert_findings(status, hang_after_sec=1)  # type: ignore[arg-type]

    assert findings == []


def test_queue_alert_findings_reads_live_worker_run_from_observation_model() -> None:
    updated_at = datetime(2026, 5, 15, 10, 0, tzinfo=timezone.utc)
    status = SimpleNamespace(
        flags=SimpleNamespace(queue_paused=False, maintenance_mode=False),
        config=SimpleNamespace(live_dispatch_enabled=True),
        conflicts=[],
        active_items=[{"project_id": "p", "current_run_id": "r", "updated_at": updated_at}],
        warnings=[],
        source_freshness={},
        observations={
            "worker_preflight": DashboardObservationRecord(
                source="worker_preflight",
                status="warn",
                payload={
                    "ok": False,
                    "checks": [
                        {
                            "name": "wake_gate_runs",
                            "data": {
                                "body": {
                                    "runs": [
                                        {
                                            "run_id": "r",
                                            "is_live": True,
                                            "lifecycle_state": "active",
                                            "active_process_count": 3,
                                        }
                                    ]
                                }
                            },
                        }
                    ],
                },
            )
        },
    )

    findings = queue_alert_findings(status, hang_after_sec=1)  # type: ignore[arg-type]

    assert findings == []


def test_send_pushover_rejects_non_http_api_url_before_urlopen(monkeypatch, tmp_path) -> None:
    from enoch_control_plane.config import GateConfig
    from enoch_control_plane.control_plane import alerts

    config = GateConfig(
        state_dir=str(tmp_path / "state"),
        project_root=str(tmp_path / "projects"),
        dispatch_script_path=str(tmp_path / "dispatch.sh"),
        control_api_bearer_token="control",
        completion_callback_url="http://callback",
        completion_callback_token="callback",
        pushover_app_token="app",
        pushover_user_key="user",
        pushover_api_url="file:///etc/passwd",
    )

    def fake_urlopen(*_args, **_kwargs):
        raise AssertionError("urlopen should not run for unsafe pushover URL")

    monkeypatch.setattr(alerts.request, "urlopen", fake_urlopen)
    result = alerts.send_pushover(config, title="t", message="m")
    assert result.attempted is True
    assert result.ok is False
    assert "pushover api url must use http or https" in result.detail
