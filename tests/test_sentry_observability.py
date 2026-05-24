from __future__ import annotations

import importlib
from types import SimpleNamespace
from unittest.mock import Mock


def _reload_error_tracking(monkeypatch, **env: str):
    for key in list(env):
        monkeypatch.setenv(key, env[key])
    import enoch_control_plane.observability.error_tracking as error_tracking

    return importlib.reload(error_tracking)


def test_sentry_initialization_is_disabled_without_dsn(monkeypatch) -> None:
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    error_tracking = _reload_error_tracking(monkeypatch)

    assert error_tracking.init_sentry() is False
    assert error_tracking.is_sentry_enabled() is False


def test_sentry_initialization_sets_release_environment_and_scrubber(
    monkeypatch,
) -> None:
    error_tracking = _reload_error_tracking(
        monkeypatch,
        SENTRY_DSN="https://public@example.invalid/1",
        ENOCH_SENTRY_ENV="test-env",
        ENOCH_SENTRY_RELEASE="abc1234",
        ENOCH_SENTRY_TRACES_SAMPLE_RATE="0.03",
        ENOCH_SENTRY_SERVER_NAME="enoch-core-test",
    )
    init_mock = Mock(return_value=None)
    scope = SimpleNamespace(set_tag=Mock())

    class ScopeContext:
        def __enter__(self):
            return scope

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(error_tracking.sentry_sdk, "init", init_mock)
    monkeypatch.setattr(
        error_tracking.sentry_sdk, "configure_scope", lambda: ScopeContext()
    )

    assert error_tracking.init_sentry(component="control_plane") is True

    kwargs = init_mock.call_args.kwargs
    assert kwargs["dsn"] == "https://public@example.invalid/1"
    assert kwargs["environment"] == "test-env"
    assert kwargs["release"] == "abc1234"
    assert kwargs["traces_sample_rate"] == 0.03
    assert kwargs["send_default_pii"] is False
    assert kwargs["server_name"] == "enoch-core-test"
    assert callable(kwargs["before_send"])
    assert "initial_scope" not in kwargs
    scope.set_tag.assert_any_call("component", "control_plane")
    scope.set_tag.assert_any_call("environment", "test-env")
    scope.set_tag.assert_any_call("release", "abc1234")


def test_sentry_before_send_removes_request_bodies_and_sensitive_context(
    monkeypatch,
) -> None:
    error_tracking = _reload_error_tracking(monkeypatch)
    event = {
        "request": {
            "url": "https://control.example/control/api/v1/overview?token=secret",
            "query_string": "token=secret&safe=yes",
            "headers": {
                "Authorization": "Bearer secret",
                "X-Request-ID": "req-1",
                "Cookie": "session=secret",
            },
            "cookies": {"session": "secret"},
            "data": {"prompt": "private research prompt", "safe": "value"},
        },
        "extra": {
            "project_id": "proj-1",
            "lane": "gb10",
            "payload": {"paper": "private draft"},
            "evidence_bundle": {"claim": "private evidence"},
            "api_key": "secret",
        },
        "contexts": {
            "trace": {"trace_id": "abc"},
            "artifact": {"content": "private paper"},
        },
        "tags": {"lane": "gb10"},
    }

    cleaned = error_tracking.before_send(event, {})

    assert cleaned["request"]["data"] == "[Filtered]"
    assert cleaned["request"]["cookies"] == "[Filtered]"
    assert cleaned["request"]["query_string"] == "[Filtered]"
    assert cleaned["request"]["headers"]["Authorization"] == "[Filtered]"
    assert cleaned["request"]["headers"]["Cookie"] == "[Filtered]"
    assert cleaned["request"]["headers"]["X-Request-ID"] == "req-1"
    assert cleaned["extra"]["project_id"] == "proj-1"
    assert cleaned["extra"]["lane"] == "gb10"
    assert cleaned["extra"]["payload"] == "[Filtered]"
    assert cleaned["extra"]["evidence_bundle"] == "[Filtered]"
    assert cleaned["extra"]["api_key"] == "[Filtered]"
    assert cleaned["contexts"]["artifact"] == "[Filtered]"


def test_capture_exception_returns_event_id_and_sanitizes_context(monkeypatch) -> None:
    error_tracking = _reload_error_tracking(monkeypatch)
    error_tracking._sentry_initialized = True
    event_id_mock = Mock(return_value="event-123")
    scope = SimpleNamespace(set_tag=Mock(), set_extra=Mock())

    class ScopeContext:
        def __enter__(self):
            return scope

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(
        error_tracking.sentry_sdk, "configure_scope", lambda: ScopeContext()
    )
    monkeypatch.setattr(error_tracking.sentry_sdk, "capture_exception", event_id_mock)

    event_id = error_tracking.capture_exception(
        RuntimeError("safe smoke"),
        component="control_plane",
        lane="gb10",
        payload={"prompt": "private"},
        project_id="proj-1",
    )

    assert event_id == "event-123"
    scope.set_tag.assert_any_call("component", "control_plane")
    scope.set_tag.assert_any_call("lane", "gb10")
    scope.set_extra.assert_any_call("project_id", "proj-1")
    scope.set_extra.assert_any_call("payload", "[Filtered]")
