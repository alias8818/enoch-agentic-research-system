from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.dashboard_v2_smoke import (
    API_OBSERVABILITY_HEALTH,
    API_PAPERS,
    API_QUEUE,
    API_READ_CHECKS,
    API_RUNS,
    CheckResult,
    SKIPPED_API_CHECK_NAMES,
    SmokeReport,
    V2_DASHBOARD_PATH,
    api_auth_status,
    check_assets,
    check_legacy_dashboard_redirect,
    check_shell,
    extract_asset_paths,
    first_event_id,
    normalize_redirect_location,
    redirect_target_is_dashboard_v2,
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
    html = (
        SAMPLE_INDEX_HTML
        + '\n<script src="/control/dashboard-v2/assets/index-abc123.js"></script>'
    )
    assert (
        extract_asset_paths(html).count("/control/dashboard-v2/assets/index-abc123.js")
        == 1
    )


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


def test_dashboard_v2_deploy_docs_do_not_put_bearer_token_in_argv() -> None:
    docs = Path("docs/dashboard-v2-deploy.md").read_text(encoding="utf-8")

    assert '--token "$ENOCH_CONTROL_TOKEN"' not in docs
    assert "Keep bearer tokens out of argv" in docs


def test_first_event_id_prefers_event_id_then_id() -> None:
    body = json.dumps({"rows": [{"event_id": "evt-1", "id": 9}]}).encode()
    assert first_event_id(body) == "evt-1"
    body = json.dumps({"rows": [{"id": 42}]}).encode()
    assert first_event_id(body) == "42"


def test_first_event_id_returns_none_for_empty_rows() -> None:
    assert first_event_id(json.dumps({"rows": []}).encode()) is None
    assert first_event_id(b"not-json") is None


def test_api_read_checks_include_queue_runs_papers_health() -> None:
    paths = {path for _, path in API_READ_CHECKS}
    assert API_QUEUE in paths
    assert API_RUNS in paths
    assert API_PAPERS in paths
    assert API_OBSERVABILITY_HEALTH in paths
    assert len(API_READ_CHECKS) == 4


def test_skipped_api_check_names_cover_expanded_endpoints() -> None:
    assert "api_queue" in SKIPPED_API_CHECK_NAMES
    assert "api_observability_health" in SKIPPED_API_CHECK_NAMES


def test_redirect_target_is_dashboard_v2_accepts_absolute_and_relative() -> None:
    base = "http://127.0.0.1:8787"
    assert redirect_target_is_dashboard_v2(V2_DASHBOARD_PATH, base)
    assert redirect_target_is_dashboard_v2(f"{V2_DASHBOARD_PATH}/", base)
    assert redirect_target_is_dashboard_v2(f"{base}{V2_DASHBOARD_PATH}", base)
    assert redirect_target_is_dashboard_v2(f"{base}{V2_DASHBOARD_PATH}#overview", base)
    assert not redirect_target_is_dashboard_v2("/control/dashboard", base)


def test_normalize_redirect_location_resolves_relative() -> None:
    base = "http://127.0.0.1:8787"
    assert (
        normalize_redirect_location(V2_DASHBOARD_PATH, base)
        == f"{base}{V2_DASHBOARD_PATH}"
    )


def test_check_legacy_dashboard_redirect_passes_on_v2_location(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen_token = None

    def fake_get_no_redirect(*_args, **_kwargs):
        nonlocal seen_token
        seen_token = _kwargs.get("token")
        return (
            307,
            {"Location": V2_DASHBOARD_PATH},
            b"",
            2.0,
            "",
        )

    monkeypatch.setattr(
        "scripts.dashboard_v2_smoke._http_get_no_redirect",
        fake_get_no_redirect,
    )
    result = check_legacy_dashboard_redirect(
        "http://127.0.0.1:8787", 1.0, token="secret"
    )
    assert result.ok is True
    assert result.status == "pass"
    assert seen_token == "secret"


def test_shell_and_asset_checks_forward_bearer_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str]] = []

    def fake_http_get(base_url, path, *, token="", timeout, accept="*/*"):
        calls.append((path, token))
        return 200, SAMPLE_INDEX_HTML.encode(), 1.0, ""

    monkeypatch.setattr("scripts.dashboard_v2_smoke._http_get", fake_http_get)

    shell_result, html = check_shell("http://example.test", 1.0, token="secret")
    asset_results = check_assets("http://example.test", html, 1.0, token="secret")

    assert shell_result.ok is True
    assert asset_results
    assert calls == [
        ("/control/dashboard-v2", "secret"),
        ("/control/dashboard-v2/assets/index-abc123.js", "secret"),
        ("/control/dashboard-v2/assets/index-def456.css", "secret"),
    ]


def test_check_legacy_dashboard_redirect_fails_without_location(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "scripts.dashboard_v2_smoke._http_get_no_redirect",
        lambda *_a, **_k: (302, {}, b"", 1.0, ""),
    )
    result = check_legacy_dashboard_redirect("http://example.test", 1.0)
    assert result.ok is False
    assert "Location" in result.detail


def test_check_legacy_dashboard_redirect_fails_when_not_redirect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "scripts.dashboard_v2_smoke._http_get_no_redirect",
        lambda *_a, **_k: (200, {}, b"<html></html>", 1.0, ""),
    )
    result = check_legacy_dashboard_redirect("http://example.test", 1.0)
    assert result.ok is False
    assert "expected redirect" in result.detail


def test_run_smoke_hits_expanded_api_endpoints_with_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called: list[str] = []

    def fake_health(*_args, **_kwargs):
        return CheckResult("healthz", True, "pass", "ok", 1.0)

    def fake_shell(*_args, **_kwargs):
        return CheckResult("dashboard_v2_shell", True, "pass", "ok", 1.0), ""

    def fake_api(base_url, name, path, token, timeout):
        called.append(path)
        return CheckResult(name, True, "pass", "ok", 1.0)

    def fake_http_get(base_url, path, *, token="", timeout, accept="*/*"):
        if "events" in path and "event_id=" not in path:
            body = json.dumps({"rows": [{"event_id": "evt-1"}]}).encode()
            return 200, body, 1.0, ""
        return 200, b"{}", 1.0, ""

    monkeypatch.setattr("scripts.dashboard_v2_smoke.check_health", fake_health)
    monkeypatch.setattr("scripts.dashboard_v2_smoke.check_shell", fake_shell)
    monkeypatch.setattr("scripts.dashboard_v2_smoke.check_api_endpoint", fake_api)
    monkeypatch.setattr("scripts.dashboard_v2_smoke._http_get", fake_http_get)

    report = run_smoke(
        "http://example.test", token="secret", timeout=1.0, shell_only=False
    )
    assert report.ok is True
    for _, path in API_READ_CHECKS:
        assert path in called


def test_run_smoke_optional_legacy_redirect_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_health(*_args, **_kwargs):
        return CheckResult("healthz", True, "pass", "ok", 1.0)

    def fake_shell(*_args, **_kwargs):
        return CheckResult("dashboard_v2_shell", True, "pass", "ok", 1.0), ""

    def fake_redirect(*_args, **_kwargs):
        return CheckResult("legacy_dashboard_redirect", True, "pass", "ok", 1.0)

    monkeypatch.setattr("scripts.dashboard_v2_smoke.check_health", fake_health)
    monkeypatch.setattr("scripts.dashboard_v2_smoke.check_shell", fake_shell)
    monkeypatch.setattr(
        "scripts.dashboard_v2_smoke.check_legacy_dashboard_redirect",
        fake_redirect,
    )
    monkeypatch.setattr(
        "scripts.dashboard_v2_smoke.check_api_endpoint",
        lambda *_a, **_k: CheckResult("api", True, "pass", "ok", 1.0),
    )
    monkeypatch.setattr(
        "scripts.dashboard_v2_smoke._http_get",
        lambda *_a, **_k: (200, json.dumps({"rows": []}).encode(), 1.0, ""),
    )

    report = run_smoke(
        "http://example.test",
        token="secret",
        timeout=1.0,
        shell_only=False,
        check_legacy_redirect=True,
    )
    assert any(check.name == "legacy_dashboard_redirect" for check in report.checks)


def test_run_smoke_fails_without_token_unless_shell_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_health(*_args, **_kwargs):
        return CheckResult("healthz", True, "pass", "ok", 1.0)

    def fake_shell(*_args, **_kwargs):
        return CheckResult(
            "dashboard_v2_shell", True, "pass", "ok", 1.0
        ), SAMPLE_INDEX_HTML

    def fake_assets(*_args, **_kwargs):
        return [CheckResult("asset:index-abc123.js", True, "pass", "ok", 1.0)]

    monkeypatch.setattr("scripts.dashboard_v2_smoke.check_health", fake_health)
    monkeypatch.setattr("scripts.dashboard_v2_smoke.check_shell", fake_shell)
    monkeypatch.setattr("scripts.dashboard_v2_smoke.check_assets", fake_assets)

    report = run_smoke("http://example.test", token="", timeout=1.0, shell_only=False)
    assert report.ok is False
    api_checks = [
        check for check in report.checks if check.name in SKIPPED_API_CHECK_NAMES
    ]
    assert len(api_checks) == len(SKIPPED_API_CHECK_NAMES)
    assert all(check.status == "skipped" for check in api_checks)
    assert any("missing bearer token" in check.detail for check in api_checks)


def test_run_smoke_shell_only_skips_api_without_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_health(*_args, **_kwargs):
        return CheckResult("healthz", True, "pass", "ok", 1.0)

    def fake_shell(*_args, **_kwargs):
        return CheckResult(
            "dashboard_v2_shell", True, "pass", "ok", 1.0
        ), SAMPLE_INDEX_HTML

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
