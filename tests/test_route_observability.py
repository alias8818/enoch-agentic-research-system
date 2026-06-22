from __future__ import annotations

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from enoch_control_plane.observability import (
    RouteObservationMiddleware,
    current_rss_mib,
    peak_rss_mib,
)
from enoch_control_plane.observability.middleware import _redact_observation
from enoch_control_plane.observability.profiling import ProfilingMiddleware
from scripts.dashboard_memory_smoke import Sample, summarize


def test_route_observability_middleware_adds_headers_and_jsonl(tmp_path) -> None:
    observation_path = tmp_path / "route_observations.jsonl"
    app = FastAPI()
    app.add_middleware(
        RouteObservationMiddleware,
        observation_path=observation_path,
        slow_ms=0,
        memory_warn_rss_mib=1,
    )

    @app.get("/hello")
    def hello() -> dict[str, str]:
        return {"ok": "yes"}

    response = TestClient(app).get("/hello?token=secret-query-value")

    assert response.status_code == 200
    assert "X-Enoch-Route-Duration-Ms" in response.headers
    assert "X-Enoch-Route-Peak-RSS-MiB" in response.headers
    rows = observation_path.read_text(encoding="utf-8").splitlines()
    assert len(rows) == 1
    payload = json.loads(rows[0])
    assert payload["method"] == "GET"
    assert payload["path"] == "/hello"
    assert payload["status_code"] == 200
    assert "secret-query-value" not in rows[0]
    assert payload["duration_ms"] >= 0
    assert payload["slow"] is False  # slow_ms=0 disables slow-route flagging


def test_route_observability_rss_helpers_are_safe() -> None:
    assert peak_rss_mib() > 0
    current = current_rss_mib()
    assert current is None or current > 0


def test_dashboard_memory_smoke_summary_tracks_rss_delta() -> None:
    rows = [
        Sample("/healthz", True, 200, 10.0, 12, 8.0, 100.0, 101.0),
        Sample("/healthz", True, 200, 20.0, 12, 9.0, 102.5, 103.0),
        Sample(
            "/control/api/status",
            False,
            500,
            30.0,
            100,
            None,
            None,
            None,
            "HTTPError: 500",
        ),
        Sample(
            "/control/api/status", False, None, 40.0, 0, None, None, None, "URLError"
        ),
    ]
    summary = summarize(rows)
    assert summary["/healthz"]["requests"] == 2
    assert summary["/healthz"]["ok"] == 2
    assert summary["/healthz"]["route_rss_mib_delta"] == 2.5
    assert summary["/control/api/status"]["failed"] == 2
    assert summary["/control/api/status"]["status_codes"] == [500]
    assert summary["/control/api/status"]["transport_errors"] == 1


def test_redact_observation_recurses_into_nested_headers_and_text() -> None:
    payload = {
        "request": {
            "headers": {
                "Authorization": "Bearer secret-token",
                "x-api-key": "secret-api-key",
            },
            "url": "/control/api/status?apikey=secret-query&ok=1",
            "events": [{"payload": "Authorization: Bearer nested-secret"}],
        },
        "safe": "value",
    }

    redacted = _redact_observation(payload)
    serialized = json.dumps(redacted, sort_keys=True)

    assert "secret-token" not in serialized
    assert "secret-api-key" not in serialized
    assert "secret-query" not in serialized
    assert "nested-secret" not in serialized
    assert redacted["request"]["headers"]["Authorization"] == "[REDACTED]"
    assert redacted["safe"] == "value"


def test_redact_observation_redacts_api_key_name_variants() -> None:
    payload = {
        "api_key": "underscore-secret",
        "api-key": "hyphen-secret",
        "api.key": "dot-secret",
        "apikey": "compact-secret",
    }

    redacted = _redact_observation(payload)
    serialized = json.dumps(redacted, sort_keys=True)

    assert "underscore-secret" not in serialized
    assert "hyphen-secret" not in serialized
    assert "dot-secret" not in serialized
    assert "compact-secret" not in serialized
    assert set(redacted.values()) == {"[REDACTED]"}


def test_profiling_middleware_samples_and_rate_limits_slow_logs(monkeypatch) -> None:
    middleware = ProfilingMiddleware(
        app=FastAPI(),
        enabled=True,
        sample_rate=0.25,
        log_cooldown_sec=10,
    )

    monkeypatch.setattr(
        "enoch_control_plane.observability.profiling._PROFILE_SAMPLER.random",
        lambda: 0.5,
    )
    assert middleware._should_profile() is False

    monkeypatch.setattr(
        "enoch_control_plane.observability.profiling._PROFILE_SAMPLER.random",
        lambda: 0.1,
    )
    assert middleware._should_profile() is True
    assert middleware._should_log_slow_profile("GET /slow", 100.0) is True
    assert middleware._should_log_slow_profile("GET /slow", 105.0) is False
    assert middleware._should_log_slow_profile("GET /slow", 111.0) is True
