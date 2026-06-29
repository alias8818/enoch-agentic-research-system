from __future__ import annotations

from datetime import datetime, timedelta, timezone
from io import BytesIO
from email.message import Message
import importlib.util
from pathlib import Path
from typing import Any
from urllib import error

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "deploy" / "enoch_queue_alert_check.py"
spec = importlib.util.spec_from_file_location("enoch_queue_alert_check", MODULE_PATH)
assert spec and spec.loader
queue_alert_check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(queue_alert_check)


def test_dispatch_error_summary_does_not_log_raw_response_body() -> None:
    secret_body = b'{"detail":"worker token secret-token leaked in nested preflight"}'
    exc = error.HTTPError(
        url="http://127.0.0.1:8787/control/dispatch-next",
        code=409,
        msg="Conflict",
        hdrs=Message(),
        fp=BytesIO(secret_body),
    )

    summary = queue_alert_check._dispatch_error_summary(exc)
    serialized = str(summary)

    assert summary["http_status"] == 409
    assert "response_body" not in summary
    assert summary["response_body_bytes"] == len(secret_body)
    assert "response_body_sha256" in summary
    assert "secret-token" not in serialized
    assert "nested preflight" not in serialized


def test_readiness_alert_dry_run_does_not_notify(monkeypatch) -> None:
    monkeypatch.setattr(
        queue_alert_check,
        "_get_json",
        lambda *_args: {
            "ok": False,
            "label": "Long-haul mode: BLOCKED",
            "blockers": ["blocked/needs-attention items exist"],
        },
    )

    result = queue_alert_check._check_and_notify_readiness(
        {"state_dir": "/tmp/not-used"},
        "http://control.example",
        "token",
        dry_run=True,
    )

    assert result["should_alert"] is True
    assert result["dry_run"] is True
    assert result["notification"]["attempted"] is False
    assert result["hermes_webhook"]["attempted"] is False


def test_readiness_endpoint_refused_retries_before_alerting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []

    def fake_get_json(*_args: object) -> dict[str, Any]:
        calls.append(len(calls))
        if len(calls) == 1:
            raise error.URLError(ConnectionRefusedError(111, "Connection refused"))
        return {"ok": True, "label": "Long-haul mode: READY", "blockers": []}

    def fake_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr(queue_alert_check, "_get_json", fake_get_json)
    monkeypatch.setattr(queue_alert_check.time, "sleep", fake_sleep)

    result = queue_alert_check._check_and_notify_readiness(
        {"state_dir": "/tmp/not-used", "readiness_endpoint_retry_delay_sec": 2},
        "http://control.example",
        "token",
        dry_run=False,
    )

    assert calls == [0, 1]
    assert result == {"ok": True, "should_alert": False, "readiness_ok": True}


def test_readiness_endpoint_refused_waits_through_control_plane_restart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []
    sleeps = []

    def fake_get_json(*_args: object) -> dict[str, Any]:
        calls.append(len(calls))
        if len(calls) < 5:
            raise error.URLError(ConnectionRefusedError(111, "Connection refused"))
        return {"ok": True, "label": "Long-haul mode: READY", "blockers": []}

    def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(queue_alert_check, "_get_json", fake_get_json)
    monkeypatch.setattr(queue_alert_check.time, "sleep", fake_sleep)

    result = queue_alert_check._check_and_notify_readiness(
        {"state_dir": "/tmp/not-used"},
        "http://control.example",
        "token",
        dry_run=False,
    )

    assert calls == [0, 1, 2, 3, 4]
    assert sleeps == [5.0, 5.0, 5.0, 5.0]
    assert result == {"ok": True, "should_alert": False, "readiness_ok": True}


def test_readiness_endpoint_refused_reports_all_configured_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []

    def fake_get_json(*_args: object) -> dict[str, Any]:
        calls.append(len(calls))
        raise error.URLError(ConnectionRefusedError(111, "Connection refused"))

    def fake_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr(queue_alert_check, "_get_json", fake_get_json)
    monkeypatch.setattr(queue_alert_check.time, "sleep", fake_sleep)

    result = queue_alert_check._check_and_notify_readiness(
        {
            "state_dir": "/tmp/not-used",
            "readiness_endpoint_retry_attempts": 3,
            "readiness_endpoint_retry_delay_sec": 1,
        },
        "http://control.example",
        "token",
        dry_run=True,
    )

    assert calls == [0, 1, 2]
    assert result["should_alert"] is True
    assert "failed after 3 attempts" in result["message"]


def test_readiness_cooldown_suppresses_same_fingerprint(tmp_path: Path) -> None:
    readiness = {
        "ok": False,
        "label": "Long-haul mode: BLOCKED",
        "blockers": ["blocked/needs-attention items exist"],
    }
    fingerprint = queue_alert_check._readiness_fingerprint(readiness)
    now = datetime(2026, 6, 28, tzinfo=timezone.utc)
    state = tmp_path / queue_alert_check.READINESS_ALERT_STATE
    state.write_text(
        '{"fingerprint":"%s","last_sent_at":"%s"}\n'
        % (
            fingerprint,
            (now - timedelta(seconds=60)).isoformat().replace("+00:00", "Z"),
        ),
        encoding="utf-8",
    )

    assert queue_alert_check._cooldown_suppressed(
        {"state_dir": str(tmp_path), "queue_alert_cooldown_sec": 1800},
        fingerprint,
        now=now,
    )


def test_hermes_readiness_webhook_uses_hmac_not_authorization(monkeypatch) -> None:
    observed = {}

    class FakeResponse:
        status = 202

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, _limit: int) -> bytes:
            return b"accepted"

    def fake_urlopen(req, **_kwargs):  # noqa: ANN001 - urllib request object
        observed["headers"] = dict(req.header_items())
        observed["data"] = req.data
        return FakeResponse()

    monkeypatch.setattr(queue_alert_check, "urlopen_validated", fake_urlopen)

    result = queue_alert_check._post_hermes_webhook(
        {
            "hermes_alert_webhook_url": "http://127.0.0.1:8644/webhooks/enoch-alert",
            "hermes_alert_webhook_secret": "secret",
        },
        fingerprint="fp",
        message="blocked",
        readiness={"ok": False, "label": "blocked", "blockers": ["x"]},
    )

    normalized_headers = {
        key.lower(): value for key, value in observed["headers"].items()
    }
    assert result["ok"] is True
    assert "x-hub-signature-256" in normalized_headers
    assert "authorization" not in normalized_headers
