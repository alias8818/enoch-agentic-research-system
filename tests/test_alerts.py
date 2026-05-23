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
        active_items=[
            {"project_id": "p", "current_run_id": "r", "updated_at": updated_at}
        ],
        warnings=[],
        source_freshness={},
    )

    findings = queue_alert_findings(status, hang_after_sec=1)  # type: ignore[arg-type]

    assert len(findings) == 1
    assert findings[0].observed_at == updated_at.isoformat()


def test_queue_alert_findings_treats_naive_database_timestamps_as_utc() -> None:
    updated_at = "2026-05-15 10:00:00"
    status = SimpleNamespace(
        flags=SimpleNamespace(queue_paused=False, maintenance_mode=False),
        config=SimpleNamespace(live_dispatch_enabled=True),
        conflicts=[],
        active_items=[
            {"project_id": "p", "current_run_id": "r", "updated_at": updated_at}
        ],
        warnings=[],
        source_freshness={},
    )

    findings = queue_alert_findings(status, hang_after_sec=1)  # type: ignore[arg-type]

    assert len(findings) == 1
    assert findings[0].observed_at == updated_at


def test_queue_alert_findings_suppresses_old_active_row_when_worker_is_live() -> None:
    updated_at = datetime(2026, 5, 15, 10, 0, tzinfo=timezone.utc)
    status = SimpleNamespace(
        flags=SimpleNamespace(queue_paused=False, maintenance_mode=False),
        config=SimpleNamespace(live_dispatch_enabled=True),
        conflicts=[],
        active_items=[
            {"project_id": "p", "current_run_id": "r", "updated_at": updated_at}
        ],
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
        active_items=[
            {"project_id": "p", "current_run_id": "r", "updated_at": updated_at}
        ],
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


def test_queue_alert_findings_suppresses_expired_stale_after_when_worker_is_live() -> (
    None
):
    stale_after = datetime(2026, 5, 15, 10, 0, tzinfo=timezone.utc)
    status = SimpleNamespace(
        flags=SimpleNamespace(queue_paused=False, maintenance_mode=False),
        config=SimpleNamespace(live_dispatch_enabled=True),
        conflicts=[],
        active_items=[
            {"project_id": "p", "current_run_id": "r", "stale_after": stale_after}
        ],
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
                                            "active_process_count": 1,
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


def test_queue_alert_findings_do_not_suppress_worker_stale_when_idle_lane_has_dispatchable_work() -> (
    None
):
    updated_at = datetime.now(timezone.utc)
    observed_at = datetime(2026, 5, 20, 12, 0, tzinfo=timezone.utc)
    status = SimpleNamespace(
        flags=SimpleNamespace(queue_paused=False, maintenance_mode=False),
        config=SimpleNamespace(live_dispatch_enabled=True),
        conflicts=[],
        active_items=[
            {
                "project_id": "active-cpu",
                "current_run_id": "run-cpu",
                "updated_at": updated_at,
                "machine_target": "cpu-proxmox-1",
            }
        ],
        next_candidate={"project_id": "queued-gb10", "machine_target": "gb10"},
        worker_lanes=[
            {
                "machine_target": "cpu-proxmox-1",
                "status": "active",
                "dispatch_available": False,
                "queued_count": 0,
            },
            {
                "machine_target": "gb10",
                "status": "idle",
                "dispatch_available": True,
                "queued_count": 1,
            },
        ],
        warnings=[],
        source_freshness={
            "worker_preflight": SimpleNamespace(
                stale=True,
                authority="cached worker preflight",
                observed_at=observed_at,
            )
        },
    )

    findings = queue_alert_findings(status, hang_after_sec=3600)  # type: ignore[arg-type]

    assert len(findings) == 1
    assert findings[0].source == "worker_preflight"
    assert "stale or missing" in findings[0].message


def test_send_pushover_rejects_non_http_api_url_before_urlopen(
    monkeypatch, tmp_path
) -> None:
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


def test_queue_alert_notify_does_not_treat_event_store_failure_as_cooldown(
    monkeypatch, tmp_path
) -> None:
    from enoch_control_plane.config import GateConfig
    from enoch_control_plane.control_plane import alerts
    from enoch_control_plane.control_plane.alerts import (
        PushoverResult,
        evaluate_and_notify_queue_alerts,
    )

    config = GateConfig(
        state_dir=str(tmp_path / "state"),
        project_root=str(tmp_path / "projects"),
        dispatch_script_path=str(tmp_path / "dispatch.sh"),
        control_api_bearer_token="control",
        completion_callback_url="http://callback",
        completion_callback_token="callback",
        live_dispatch_enabled=True,
        queue_alert_hang_after_sec=300,
        queue_alert_cooldown_sec=3600,
        pushover_alerts_enabled=True,
        pushover_app_token="app",
        pushover_user_key="user",
    )
    updated_at = datetime(2026, 5, 15, 10, 0, tzinfo=timezone.utc)
    status = SimpleNamespace(
        flags=SimpleNamespace(queue_paused=False, maintenance_mode=False),
        config=SimpleNamespace(live_dispatch_enabled=True),
        conflicts=[],
        active_items=[
            {"project_id": "p", "current_run_id": "r", "updated_at": updated_at}
        ],
        warnings=[],
        source_freshness={},
        dispatch_safe=False,
        dispatch_blockers=["active row stale"],
    )

    class Store:
        def event_rows(self, limit=100):  # noqa: ANN001 - alert store fake
            return []

        def append_event(self, **_kwargs):  # noqa: ANN003 - alert store fake
            raise RuntimeError("event store unavailable")

    monkeypatch.setattr(
        alerts,
        "send_pushover",
        lambda *args, **kwargs: PushoverResult(attempted=True, ok=True, detail="sent"),
    )

    result = evaluate_and_notify_queue_alerts(
        config=config,
        store=Store(),
        status=status,
        dry_run=False,
        force_notify=False,
        requested_by="test",
    )  # type: ignore[arg-type]

    assert result["should_alert"] is True
    assert result["sent"] is True
    assert result["suppressed_by_cooldown"] is False
    assert "event store unavailable" in result["event_append_error"]


def test_format_queue_alert_message_lists_first_five_findings() -> None:
    from enoch_control_plane.control_plane.alerts import _format_queue_alert_message
    from enoch_control_plane.control_plane.models import DashboardFinding

    status = SimpleNamespace(
        active_items=[{"project_id": "p"}],
        dispatch_blockers=["stale active row"],
    )
    findings = [
        DashboardFinding(
            severity="warn",
            source=f"source-{index}",
            authority="test",
            message=f"message-{index}",
            observed_at=None,
            suggested_action="inspect",
        )
        for index in range(7)
    ]

    message = _format_queue_alert_message(status, findings)  # type: ignore[arg-type]

    assert "message-0" in message
    assert "message-4" in message
    assert "message-5" not in message
    assert "+2 more" in message


def test_queue_alert_notify_suppresses_cooldown_duplicate(
    monkeypatch, tmp_path
) -> None:
    from enoch_control_plane.config import GateConfig
    from enoch_control_plane.control_plane import alerts
    from enoch_control_plane.control_plane.alerts import (
        evaluate_and_notify_queue_alerts,
    )

    config = GateConfig(
        state_dir=str(tmp_path / "state"),
        project_root=str(tmp_path / "projects"),
        dispatch_script_path=str(tmp_path / "dispatch.sh"),
        control_api_bearer_token="control",
        completion_callback_url="http://callback",
        completion_callback_token="callback",
        live_dispatch_enabled=True,
        queue_alert_hang_after_sec=300,
        queue_alert_cooldown_sec=3600,
        pushover_alerts_enabled=True,
        pushover_app_token="app",
        pushover_user_key="user",
    )
    updated_at = datetime(2026, 5, 15, 10, 0, tzinfo=timezone.utc)
    status = SimpleNamespace(
        flags=SimpleNamespace(queue_paused=False, maintenance_mode=False),
        config=SimpleNamespace(live_dispatch_enabled=True),
        conflicts=[],
        active_items=[
            {"project_id": "p", "current_run_id": "r", "updated_at": updated_at}
        ],
        warnings=[],
        source_freshness={},
        dispatch_safe=False,
        dispatch_blockers=["active row stale"],
    )

    class Store:
        def event_rows(self, limit=100):  # noqa: ANN001 - alert store fake
            return []

        def append_event(self, **_kwargs):  # noqa: ANN003 - alert store fake
            return ("evt-1", False)

    def fail_pushover(*_args, **_kwargs):  # noqa: ANN001 - test guard
        raise AssertionError("send_pushover should not run for cooldown duplicate")

    monkeypatch.setattr(alerts, "send_pushover", fail_pushover)

    result = evaluate_and_notify_queue_alerts(
        config=config,
        store=Store(),
        status=status,
        dry_run=False,
        force_notify=False,
        requested_by="test",
    )  # type: ignore[arg-type]

    assert result["should_alert"] is True
    assert result["sent"] is False
    assert result["suppressed_by_cooldown"] is True
    assert result["notification"]["detail"] == "cooldown duplicate suppressed"


def test_queue_alert_findings_includes_worker_settling_warning() -> None:
    status = SimpleNamespace(
        flags=SimpleNamespace(queue_paused=False, maintenance_mode=False),
        config=SimpleNamespace(live_dispatch_enabled=True),
        conflicts=[],
        active_items=[],
        warnings=[
            SimpleNamespace(
                severity="warn",
                source="worker_settling",
                authority="cross-source active-lane reconciliation",
                message="GB10 worker is settling a recent worker run with no active process",
                observed_at="2026-05-21T00:00:00+00:00",
                suggested_action="wait",
                data={},
            )
        ],
        source_freshness={},
    )

    findings = queue_alert_findings(status, hang_after_sec=3600)  # type: ignore[arg-type]

    assert len(findings) == 1
    assert findings[0].source == "worker_settling"
