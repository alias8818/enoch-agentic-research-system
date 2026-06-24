"""Deterministic coverage for `enoch_control_plane.observability.error_tracking`.

These tests pin the *capture/report* surface that ``test_sentry_observability``
deliberately leaves to the ``init`` path. The goal is to make regressions in:

- ``capture_exception`` dispatch (sentry capture vs. fallback logger)
- no-Sentry fallback (env unset, sdk unavailable)
- PII redaction wrapping ``capture_exception`` (sanitized context)
- ``before_send`` invocation path

visible to CI before they ship. See GitHub issue #229.
"""

from __future__ import annotations

import importlib
import logging
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


def _reload_error_tracking(**env: str):
    """Reload the module after clearing known Sentry env vars."""
    import os

    keys = [
        "SENTRY_DSN",
        "ENOCH_SENTRY_ENV",
        "ENOCH_SENTRY_RELEASE",
        "ENOCH_SENTRY_COMPONENT",
        "ENOCH_SENTRY_TRACES_SAMPLE_RATE",
        "ENOCH_SENTRY_SERVER_NAME",
    ]
    prior = {key: os.environ.pop(key, None) for key in keys}
    try:
        os.environ.update(env)
        import enoch_control_plane.observability.error_tracking as error_tracking

        return importlib.reload(error_tracking)
    finally:
        for key, value in prior.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@pytest.fixture
def error_tracking_module():
    """Yield a freshly reloaded error_tracking module with no Sentry env."""

    return _reload_error_tracking()


def test_capture_exception_without_sentry_logs_and_returns_none(
    error_tracking_module, caplog
) -> None:
    error_tracking = error_tracking_module
    # No SENTRY_DSN, no init_sentry() -> falls through to logger.error and returns None.
    with caplog.at_level(logging.ERROR, logger="enoch.error_tracking"):
        event_id = error_tracking.capture_exception(
            RuntimeError("boom"),
            component="control_plane",
            lane="gb10",
            project_id="proj-1",
            payload={"prompt": "private"},
            api_key="leaked-token",
        )

    assert event_id is None
    assert error_tracking.sentry_sdk is not None  # sdk present, but uninitialized
    assert error_tracking.is_sentry_enabled() is False
    # The single emitted record must carry the scrubbed context, not the raw key.
    records = [record for record in caplog.records if record.name == "enoch.error_tracking"]
    assert records, "expected fallback logger.error to fire"
    record = records[-1]
    assert record.project_id == "proj-1"
    assert record.lane == "gb10"
    assert record.payload == "[Filtered]"
    assert record.api_key == "[Filtered]"


def test_capture_exception_with_sentry_initialized_invokes_sdk_once(
    error_tracking_module,
) -> None:
    error_tracking = error_tracking_module
    error_tracking._sentry_initialized = True  # bypass env gate for unit test

    capture_mock = Mock(return_value="event-abc")
    scope = SimpleNamespace(set_tag=Mock(), set_extra=Mock())

    class _ScopeContext:
        def __enter__(self):
            return scope

        def __exit__(self, exc_type, exc, tb):
            return False

    error_tracking.sentry_sdk.configure_scope = lambda: _ScopeContext()
    error_tracking.sentry_sdk.capture_exception = capture_mock

    exc = ValueError("deterministic failure")
    event_id = error_tracking.capture_exception(
        exc,
        component="control_plane",
        lane="gb10",
        machine_target="gpu-a",
        payload={"paper": "private draft"},
        api_key="must-not-leak",
        project_id="proj-42",
    )

    assert event_id == "event-abc"
    assert capture_mock.call_count == 1
    assert capture_mock.call_args.args == (exc,)

    # Tag keys (component/lane/operation/machine_target) -> scope.set_tag.
    tag_calls = {
        call.args[0]: call.args[1]
        for call in scope.set_tag.call_args_list
        if call.args
    }
    assert tag_calls["component"] == "control_plane"
    assert tag_calls["lane"] == "gb10"
    assert tag_calls["machine_target"] == "gpu-a"

    # Non-tag context flows through set_extra after PII scrub.
    extra_calls = {
        call.args[0]: call.args[1]
        for call in scope.set_extra.call_args_list
        if call.args
    }
    assert extra_calls["project_id"] == "proj-42"
    assert extra_calls["payload"] == "[Filtered]"
    assert extra_calls["api_key"] == "[Filtered]"


def test_capture_exception_with_sentry_does_not_raise_on_sdk_failure(
    error_tracking_module, caplog
) -> None:
    error_tracking = error_tracking_module
    error_tracking._sentry_initialized = True

    def _boom(*_args, **_kwargs):
        raise RuntimeError("sdk unreachable")

    class _ScopeContext:
        def __enter__(self):
            return SimpleNamespace(set_tag=Mock(), set_extra=Mock())

        def __exit__(self, exc_type, exc, tb):
            return False

    error_tracking.sentry_sdk.configure_scope = _boom
    error_tracking.sentry_sdk.capture_exception = _boom

    with caplog.at_level(logging.DEBUG, logger="enoch.error_tracking"):
        event_id = error_tracking.capture_exception(
            RuntimeError("outer"),
            component="control_plane",
        )

    # Outer failure must be contained; the caller gets a None event_id, not a raise.
    assert event_id is None
    assert any(
        "Failed to capture exception in Sentry" in record.getMessage()
        for record in caplog.records
    )


def test_no_sentry_path_does_not_initialize_sdk_or_touch_sdk_calls(
    error_tracking_module,
) -> None:
    error_tracking = error_tracking_module
    init_mock = Mock(return_value=None)
    error_tracking.sentry_sdk.init = init_mock

    # Sanity: DSN is unset in the fixture environment.
    assert error_tracking.is_sentry_enabled() is False
    assert error_tracking.capture_exception(RuntimeError("x"), component="x") is None

    init_mock.assert_not_called()


def test_before_send_is_invoked_with_scrubbed_event(
    error_tracking_module,
) -> None:
    error_tracking = error_tracking_module
    event = {
        "request": {
            "url": "https://control.example/api/v1/queue?token=secret",
            "headers": {"Authorization": "Bearer secret", "X-Trace": "ok"},
            "data": {"prompt": "private", "safe": "ok"},
        },
        "extra": {
            "project_id": "proj-9",
            "payload": {"paper": "private"},
            "api_key": "leaked",
        },
        "contexts": {"trace": {"trace_id": "t-1"}},
        "tags": {"lane": "gb10"},
    }

    cleaned = error_tracking.before_send(event, {})

    # Request scrubbing
    assert cleaned["request"]["data"] == "[Filtered]"
    assert cleaned["request"]["headers"]["Authorization"] == "[Filtered]"
    assert cleaned["request"]["headers"]["X-Trace"] == "ok"
    assert "token=%5BFiltered%5D" in cleaned["request"]["url"]
    # Extra scrubbing
    assert cleaned["extra"]["project_id"] == "proj-9"
    assert cleaned["extra"]["payload"] == "[Filtered]"
    assert cleaned["extra"]["api_key"] == "[Filtered]"
    # Component tag is forced on so operators can filter
    assert cleaned["tags"]["component"] == "control_plane"
    assert cleaned["tags"]["lane"] == "gb10"


def test_init_sentry_idempotent_when_called_twice() -> None:
    error_tracking = _reload_error_tracking(
        SENTRY_DSN="https://public@example.invalid/1",
    )
    print("DBG: dsn=", error_tracking._sentry_dsn())
    print("DBG: runtime=", error_tracking._sentry_runtime_config("control_plane"))
    print("DBG: deps=", error_tracking._sentry_dependencies_available())
    init_mock = Mock(return_value=None)

    class _ScopeContext:
        def __enter__(self):
            return SimpleNamespace(set_tag=Mock())

        def __exit__(self, exc_type, exc, tb):
            return False

    error_tracking.sentry_sdk.init = init_mock
    error_tracking.sentry_sdk.configure_scope = lambda: _ScopeContext()

    print("DBG: init mock is", error_tracking.sentry_sdk.init)
    print("DBG: configure_scope mock is", error_tracking.sentry_sdk.configure_scope)
    print("DBG: init_sentry returns:", error_tracking.init_sentry(component="control_plane"))
    assert error_tracking.init_sentry(component="control_plane") is True
    init_mock.assert_called_once()

    # A second call must short-circuit on the module-level sentinel, not re-init.
    assert error_tracking.init_sentry(component="control_plane") is True
    assert init_mock.call_count == 1
