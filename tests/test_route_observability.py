from __future__ import annotations

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from omx_wake_gate.observability import RouteObservationMiddleware, current_rss_mib, peak_rss_mib
from scripts.dashboard_memory_smoke import Sample, summarize


def test_route_observability_middleware_adds_headers_and_jsonl(tmp_path) -> None:
    observation_path = tmp_path / "route_observations.jsonl"
    app = FastAPI()
    app.add_middleware(RouteObservationMiddleware, observation_path=observation_path, slow_ms=0, memory_warn_rss_mib=1)

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
        Sample("/control/api/status", False, 500, 30.0, 100, None, None, None, "HTTPError: 500"),
        Sample("/control/api/status", False, None, 40.0, 0, None, None, None, "URLError"),
    ]
    summary = summarize(rows)
    assert summary["/healthz"]["requests"] == 2
    assert summary["/healthz"]["ok"] == 2
    assert summary["/healthz"]["route_rss_mib_delta"] == 2.5
    assert summary["/control/api/status"]["failed"] == 2
    assert summary["/control/api/status"]["status_codes"] == [500]
    assert summary["/control/api/status"]["transport_errors"] == 1
