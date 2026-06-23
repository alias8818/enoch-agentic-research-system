from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from deploy import enoch_source_lineage_check as check


def test_main_skips_source_lineage_sidecar_during_control_hold(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "state_dir": str(tmp_path / "state"),
                "project_root": str(tmp_path / "projects"),
                "dispatch_script_path": str(tmp_path / "dispatch.sh"),
                "control_api_bearer_token": "token",
                "completion_callback_url": "http://example.invalid/callback",
                "completion_callback_token": "callback-token",
                "supabase_database_url": "postgres://example",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        check,
        "_get_control_status",
        lambda _config: {
            "flags": {
                "queue_paused": True,
                "maintenance_mode": True,
                "pause_reason": "operator maintenance",
            }
        },
    )
    monkeypatch.setattr(
        check,
        "_build_report",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("source-lineage report must not run while held")
        ),
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "enoch_source_lineage_check.py",
            "--config",
            str(config),
            "--json",
        ],
    )

    assert check.main() == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["action"] == "skipped"
    assert payload["hold_state"]["queue_paused"] is True
    assert payload["hold_state"]["maintenance_mode"] is True


def test_main_skips_source_lineage_sidecar_when_hold_status_unreachable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "state_dir": str(tmp_path / "state"),
                "project_root": str(tmp_path / "projects"),
                "dispatch_script_path": str(tmp_path / "dispatch.sh"),
                "control_api_bearer_token": "token",
                "completion_callback_url": "http://example.invalid/callback",
                "completion_callback_token": "callback-token",
                "supabase_database_url": "postgres://example",
            }
        ),
        encoding="utf-8",
    )

    def unreachable_status(_config: object) -> dict[str, object]:
        raise OSError("offline")

    def forbidden_build_report(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise AssertionError("source-lineage report must not run without hold status")

    monkeypatch.setattr(check, "_get_control_status", unreachable_status)
    monkeypatch.setattr(check, "_build_report", forbidden_build_report)
    monkeypatch.setattr(
        "sys.argv",
        [
            "enoch_source_lineage_check.py",
            "--config",
            str(config),
            "--json",
        ],
    )

    assert check.main() == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["action"] == "skipped"
    assert payload["control_status_unreachable"] is True
    assert "could not be verified" in payload["reason"]


def test_run_check_writes_report_and_does_not_alert_when_clean(
    monkeypatch, tmp_path: Path
) -> None:
    report_path = tmp_path / "source-lineage" / "latest-report.json"
    calls = []

    monkeypatch.setattr(
        check,
        "_build_report",
        lambda database_url, created_after: {
            "schema_version": "enoch_source_lineage_report_v1",
            "status": "clean",
            "ok": True,
            "counts": {"problems": 0},
            "problem_counts": {},
            "problems": [],
            "created_after": created_after,
        },
    )
    monkeypatch.setattr(
        check, "_send_alert", lambda *args, **kwargs: calls.append((args, kwargs))
    )

    result = check.run_check(
        database_url="postgres://example",
        created_after="2026-05-19T17:51:00Z",
        output=report_path,
        config=SimpleNamespace(pushover_alerts_enabled=True),
        state_dir=tmp_path,
    )

    assert result["ok"] is True
    assert report_path.exists()
    assert json.loads(report_path.read_text(encoding="utf-8"))["status"] == "clean"
    assert calls == []


def test_run_check_alerts_once_for_new_post_cutover_failures(
    monkeypatch, tmp_path: Path
) -> None:
    report = {
        "schema_version": "enoch_source_lineage_report_v1",
        "status": "blocked",
        "ok": False,
        "counts": {"candidates": 0, "followups": 1, "problems": 1},
        "problem_counts": {"followup_missing_parent_run_source": 1},
        "problems": [
            {"kind": "followup_missing_parent_run_source", "project_id": "f1"}
        ],
        "created_after": "2026-05-19T17:51:00Z",
    }
    sent = []

    monkeypatch.setattr(
        check, "_build_report", lambda database_url, created_after: dict(report)
    )
    monkeypatch.setattr(
        check,
        "_send_alert",
        lambda config, report: sent.append(report) or {"attempted": True, "ok": True},
    )

    args = dict(
        database_url="postgres://example",
        created_after="2026-05-19T17:51:00Z",
        output=tmp_path / "latest-report.json",
        config=SimpleNamespace(pushover_alerts_enabled=True),
        state_dir=tmp_path,
    )
    first = check.run_check(**args)
    second = check.run_check(**args)

    assert first["alert"]["sent"] is True
    assert second["alert"]["suppressed_by_fingerprint"] is True
    assert len(sent) == 1


def test_run_check_does_not_alert_for_historical_warning_report(
    monkeypatch, tmp_path: Path
) -> None:
    report = {
        "schema_version": "enoch_source_lineage_report_v1",
        "status": "warnings",
        "ok": True,
        "counts": {"problems": 70},
        "problem_counts": {"historical_source_lineage_gap": 70},
        "problems": [],
    }
    sent = []

    monkeypatch.setattr(
        check, "_build_report", lambda database_url, created_after: dict(report)
    )
    monkeypatch.setattr(
        check,
        "_send_alert",
        lambda config, report: sent.append(report) or {"attempted": True, "ok": True},
    )

    result = check.run_check(
        database_url="postgres://example",
        created_after="2026-05-19T17:51:00Z",
        output=tmp_path / "latest-report.json",
        config=SimpleNamespace(pushover_alerts_enabled=True),
        state_dir=tmp_path,
    )

    assert result["ok"] is True
    assert result["alert"]["sent"] is False
    assert sent == []
