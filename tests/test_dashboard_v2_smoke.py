from __future__ import annotations

import json

import pytest

from scripts.dashboard_v2_smoke import (
    CheckResult,
    SmokeReport,
    api_auth_status,
    extract_asset_paths,
    first_event_id,
    run_smoke,
)


SAMPLE_INDEX_HTML = """<!doctype html>
<html lang="en">
  <head>
    <script type="module" crossorigin src="/control/dashboard-v2/assets/index-abc123.js"></script>
    <link rel="stylesheet" crossorigin href="/control/dashboard-v2/assets/index-def456.css">
  </head>
  <body>
    <div id="enoch-dashboard-v2-root"></div>
  </body>
</html>
"""


def test_extract_asset_paths_finds_js_and_css() -> None:
    paths = extract_asset_paths(SAMPLE_INDEX_HTML)
    assert paths == [
        "/control/dashboard-v2/assets/index-abc123.js",
        "/control/dashboard-v2/assets/index-def456.css",
    ]


def test_extract_asset_paths_deduplicates() -> None:
    html = SAMPLE_INDEX_HTML + '\n<script src="/control/dashboard-v2/assets/index-abc123.js"></script>'
    assert extract_asset_paths(html).count("/control/dashboard-v2/assets/index-abc123.js") == 1


def test_api_auth_status_requires_token_by_default() -> None:
    run_api, detail = api_auth_status("", shell_only=False)
    assert run_api is False
    assert "missing bearer token" in detail


def test_api_auth_status_shell_only_skips_api() -> None:
    run_api, detail = api_auth_status("", shell_only=True)
    assert run_api is False
    assert detail.startswith("skipped")


def test_api_auth_status_with_token_runs_api() -> None:
    run_api, detail = api_auth_status("secret", shell_only=False)
    assert run_api is True
    assert detail == ""


def test_first_event_id_prefers_event_id_then_id() -> None:
    body = json.dumps({"rows": [{"event_id": "evt-1", "id": 9}]}).encode()
    assert first_event_id(body) == "evt-1"
    body = json.dumps({"rows": [{"id": 42}]}).encode()
    assert first_event_id(body) == "42"


def test_first_event_id_returns_none_for_empty_rows() -> None:
    assert first_event_id(json.dumps({"rows": []}).encode()) is None
    assert first_event_id(b"not-json") is None


def test_run_smoke_fails_without_token_unless_shell_only(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_health(*_args, **_kwargs):
        return CheckResult("healthz", True, "pass", "ok", 1.0)

    def fake_shell(*_args, **_kwargs):
        return CheckResult("dashboard_v2_shell", True, "pass", "ok", 1.0), SAMPLE_INDEX_HTML

    def fake_assets(*_args, **_kwargs):
        return [CheckResult("asset:index-abc123.js", True, "pass", "ok", 1.0)]

    monkeypatch.setattr("scripts.dashboard_v2_smoke.check_health", fake_health)
    monkeypatch.setattr("scripts.dashboard_v2_smoke.check_shell", fake_shell)
    monkeypatch.setattr("scripts.dashboard_v2_smoke.check_assets", fake_assets)

    report = run_smoke("http://example.test", token="", timeout=1.0, shell_only=False)
    assert report.ok is False
    api_checks = [check for check in report.checks if check.name.startswith("api_")]
    assert all(check.status == "skipped" for check in api_checks)
    assert any("missing bearer token" in check.detail for check in api_checks)


def test_run_smoke_shell_only_skips_api_without_token(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_health(*_args, **_kwargs):
        return CheckResult("healthz", True, "pass", "ok", 1.0)

    def fake_shell(*_args, **_kwargs):
        return CheckResult("dashboard_v2_shell", True, "pass", "ok", 1.0), SAMPLE_INDEX_HTML

    def fake_assets(*_args, **_kwargs):
        return [
            CheckResult("asset:index-abc123.js", True, "pass", "ok", 1.0),
            CheckResult("asset:index-def456.css", True, "pass", "ok", 1.0),
        ]

    monkeypatch.setattr("scripts.dashboard_v2_smoke.check_health", fake_health)
    monkeypatch.setattr("scripts.dashboard_v2_smoke.check_shell", fake_shell)
    monkeypatch.setattr("scripts.dashboard_v2_smoke.check_assets", fake_assets)

    report = run_smoke("http://example.test", token="", timeout=1.0, shell_only=True)
    assert report.ok is True
    assert all(check.status in {"pass", "skipped"} for check in report.checks)


def test_smoke_report_to_dict() -> None:
    report = SmokeReport(
        ok=True,
        base_url="http://example.test",
        checks=[CheckResult("healthz", True, "pass", "ok", 12.5)],
        warnings=["example warning"],
    )
    payload = report.to_dict()
    assert payload["ok"] is True
    assert payload["warnings"] == ["example warning"]
    assert payload["checks"][0]["elapsed_ms"] == 12.5
