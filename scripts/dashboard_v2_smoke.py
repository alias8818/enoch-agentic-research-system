#!/usr/bin/env python3
"""Post-deploy smoke checks for Dashboard V2 shell, assets, and bounded v1 APIs.

This script performs GET requests only. It verifies deploy health (shell marker,
hashed static assets, healthz, authenticated read-model endpoints). It cannot
prove rendering invariants such as "no raw JSON above the fold"; those belong
in Vitest DOM tests run in CI.

Auth:
  - /healthz and /control/dashboard-v2 require no bearer token.
  - /control/api/v1/* require --token or ENOCH_CONTROL_TOKEN unless
    --allow-unauthenticated-shell-only is passed (API checks are then skipped).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from typing import Any
from urllib import error, parse, request

SHELL_PATH = "/control/dashboard-v2"
ROOT_MARKER = 'id="enoch-dashboard-v2-root"'
ASSET_PATTERN = re.compile(r"/control/dashboard-v2/assets/[^\"'>\s]+")

API_OVERVIEW = "/control/api/v1/overview"
API_EVENTS_INDEX = "/control/api/v1/events?page_size=50&sort=recent"
API_QUEUE = "/control/api/v1/queue?page_size=25"
API_RUNS = "/control/api/v1/runs?page_size=25"
API_PAPERS = "/control/api/v1/papers?page_size=25"
API_OBSERVABILITY_HEALTH = "/control/api/v1/observability/health"

LEGACY_DASHBOARD_PATH = "/control/dashboard"
V2_DASHBOARD_PATH = "/control/dashboard-v2"

API_READ_CHECKS: tuple[tuple[str, str], ...] = (
    ("api_queue", API_QUEUE),
    ("api_runs", API_RUNS),
    ("api_papers", API_PAPERS),
    ("api_observability_health", API_OBSERVABILITY_HEALTH),
)

SKIPPED_API_CHECK_NAMES: tuple[str, ...] = (
    "api_overview",
    "api_events_index",
    "api_event_detail",
    *(name for name, _ in API_READ_CHECKS),
)


@dataclass
class CheckResult:
    name: str
    ok: bool
    status: str  # pass | fail | skipped | warn
    detail: str = ""
    elapsed_ms: float = 0.0


@dataclass
class SmokeReport:
    ok: bool
    base_url: str
    checks: list[CheckResult] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "base_url": self.base_url,
            "warnings": self.warnings,
            "checks": [
                {
                    "name": check.name,
                    "ok": check.ok,
                    "status": check.status,
                    "detail": check.detail,
                    "elapsed_ms": round(check.elapsed_ms, 2),
                }
                for check in self.checks
            ],
        }


def extract_asset_paths(index_html: str) -> list[str]:
    """Return unique /control/dashboard-v2/assets/... paths from index.html."""
    seen: set[str] = set()
    paths: list[str] = []
    for match in ASSET_PATTERN.finditer(index_html):
        path = match.group(0)
        if path not in seen:
            seen.add(path)
            paths.append(path)
    return paths


class _NoRedirectHandler(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


def _http_get(
    base_url: str,
    path: str,
    *,
    token: str = "",
    timeout: float,
    accept: str = "*/*",
) -> tuple[int | None, bytes, float, str]:
    url = base_url.rstrip("/") + path
    headers = {"Accept": accept}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = request.Request(url, headers=headers, method="GET")
    started = time.perf_counter()
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            return resp.status, body, elapsed_ms, ""
    except error.HTTPError as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        body = exc.read()
        return exc.code, body, elapsed_ms, f"HTTP {exc.code}"
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return None, b"", elapsed_ms, f"{type(exc).__name__}: {exc}"


def _http_get_no_redirect(
    base_url: str,
    path: str,
    *,
    timeout: float,
    accept: str = "*/*",
) -> tuple[int | None, dict[str, str], bytes, float, str]:
    url = base_url.rstrip("/") + path
    headers = {"Accept": accept}
    req = request.Request(url, headers=headers, method="GET")
    opener = request.build_opener(_NoRedirectHandler())
    started = time.perf_counter()
    try:
        with opener.open(req, timeout=timeout) as resp:
            body = resp.read()
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            return resp.status, dict(resp.headers), body, elapsed_ms, ""
    except error.HTTPError as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        body = exc.read()
        return exc.code, dict(exc.headers), body, elapsed_ms, f"HTTP {exc.code}"
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return None, {}, b"", elapsed_ms, f"{type(exc).__name__}: {exc}"


def normalize_redirect_location(location: str, base_url: str) -> str:
    """Return an absolute URL for a redirect Location header."""
    return parse.urljoin(base_url.rstrip("/") + "/", location)


def redirect_target_is_dashboard_v2(location: str, base_url: str) -> bool:
    """True when Location resolves to the V2 dashboard shell path."""
    absolute = normalize_redirect_location(location, base_url)
    parsed = parse.urlparse(absolute)
    path = parsed.path.rstrip("/") or "/"
    return path == V2_DASHBOARD_PATH


def resolve_token(cli_token: str, token_env: str) -> str:
    if cli_token:
        return cli_token
    for env_name in (
        token_env,
        "ENOCH_CONTROL_PLANE_TOKEN",
        "OMX_INBOUND_BEARER_TOKEN",
    ):
        value = os.environ.get(env_name, "")
        if value:
            return value
    return ""


def api_auth_status(token: str, shell_only: bool) -> tuple[bool, str]:
    """Return (run_api_checks, detail_if_skipped)."""
    if token:
        return True, ""
    if shell_only:
        return False, "skipped (--allow-unauthenticated-shell-only)"
    return False, "missing bearer token; pass --token or set ENOCH_CONTROL_TOKEN"


def check_health(base_url: str, timeout: float) -> CheckResult:
    status, body, elapsed_ms, err = _http_get(base_url, "/healthz", timeout=timeout)
    if status is None:
        return CheckResult("healthz", False, "fail", err, elapsed_ms)
    if not (200 <= status < 300):
        return CheckResult("healthz", False, "fail", f"HTTP {status}", elapsed_ms)
    text = body.decode("utf-8", errors="replace").lower()
    if "ok" not in text and "healthy" not in text and text.strip() not in {"true", "1"}:
        return CheckResult(
            "healthz", False, "fail", "response body did not look healthy", elapsed_ms
        )
    return CheckResult("healthz", True, "pass", "ok", elapsed_ms)


def check_shell(base_url: str, timeout: float) -> tuple[CheckResult, str]:
    status, body, elapsed_ms, err = _http_get(
        base_url,
        SHELL_PATH,
        timeout=timeout,
        accept="text/html",
    )
    if status is None:
        return CheckResult("dashboard_v2_shell", False, "fail", err, elapsed_ms), ""
    if not (200 <= status < 300):
        return CheckResult(
            "dashboard_v2_shell", False, "fail", f"HTTP {status}", elapsed_ms
        ), ""
    html = body.decode("utf-8", errors="replace")
    if ROOT_MARKER not in html:
        return CheckResult(
            "dashboard_v2_shell",
            False,
            "fail",
            f"missing root marker {ROOT_MARKER}",
            elapsed_ms,
        ), html
    return CheckResult(
        "dashboard_v2_shell", True, "pass", "root marker present", elapsed_ms
    ), html


def check_assets(base_url: str, index_html: str, timeout: float) -> list[CheckResult]:
    paths = extract_asset_paths(index_html)
    results: list[CheckResult] = []
    if not paths:
        results.append(
            CheckResult(
                "dashboard_v2_assets",
                False,
                "fail",
                "no /control/dashboard-v2/assets/ references found in index.html",
            )
        )
        return results
    js_paths = [path for path in paths if path.endswith(".js")]
    if not js_paths:
        results.append(
            CheckResult(
                "dashboard_v2_assets_js",
                False,
                "fail",
                "index.html references assets but no .js bundle was found",
            )
        )
    for path in paths:
        status, _, elapsed_ms, err = _http_get(base_url, path, timeout=timeout)
        name = f"asset:{path.rsplit('/', 1)[-1]}"
        if status is None:
            results.append(CheckResult(name, False, "fail", err, elapsed_ms))
        elif not (200 <= status < 300):
            results.append(
                CheckResult(name, False, "fail", f"HTTP {status}", elapsed_ms)
            )
        else:
            results.append(CheckResult(name, True, "pass", "ok", elapsed_ms))
    return results


def check_api_endpoint(
    base_url: str,
    name: str,
    path: str,
    token: str,
    timeout: float,
) -> CheckResult:
    status, body, elapsed_ms, err = _http_get(
        base_url,
        path,
        token=token,
        timeout=timeout,
        accept="application/json",
    )
    if status is None:
        return CheckResult(name, False, "fail", err, elapsed_ms)
    if not (200 <= status < 300):
        snippet = body.decode("utf-8", errors="replace")[:200]
        return CheckResult(name, False, "fail", f"HTTP {status}: {snippet}", elapsed_ms)
    return CheckResult(name, True, "pass", "ok", elapsed_ms)


def check_legacy_dashboard_redirect(
    base_url: str,
    timeout: float,
    *,
    query: str = "",
) -> CheckResult:
    """Verify legacy /control/dashboard redirects to /control/dashboard-v2 (post-cutover).

    Hash fragments are not sent to the server; browsers preserve them after redirect.
    """
    path = LEGACY_DASHBOARD_PATH
    if query:
        path += query if query.startswith("?") else f"?{query}"
    status, headers, _, elapsed_ms, err = _http_get_no_redirect(
        base_url,
        path,
        timeout=timeout,
        accept="text/html",
    )
    if status is None:
        return CheckResult("legacy_dashboard_redirect", False, "fail", err, elapsed_ms)
    if status not in {301, 302, 303, 307, 308}:
        return CheckResult(
            "legacy_dashboard_redirect",
            False,
            "fail",
            f"expected redirect, got HTTP {status}",
            elapsed_ms,
        )
    location = headers.get("Location") or headers.get("location") or ""
    if not location:
        return CheckResult(
            "legacy_dashboard_redirect",
            False,
            "fail",
            "redirect response missing Location header",
            elapsed_ms,
        )
    if not redirect_target_is_dashboard_v2(location, base_url):
        return CheckResult(
            "legacy_dashboard_redirect",
            False,
            "fail",
            f"Location {location!r} does not target {V2_DASHBOARD_PATH}",
            elapsed_ms,
        )
    return CheckResult(
        "legacy_dashboard_redirect",
        True,
        "pass",
        f"redirects to {normalize_redirect_location(location, base_url)}",
        elapsed_ms,
    )


def first_event_id(events_body: bytes) -> str | None:
    try:
        payload = json.loads(events_body.decode("utf-8"))
    except json.JSONDecodeError:
        return None
    rows = payload.get("rows") if isinstance(payload, dict) else None
    if not isinstance(rows, list) or not rows:
        return None
    first = rows[0]
    if not isinstance(first, dict):
        return None
    for key in ("event_id", "id"):
        value = first.get(key)
        if value is not None and str(value).strip():
            return str(value)
    return None


def run_smoke(
    base_url: str,
    *,
    token: str,
    timeout: float,
    shell_only: bool,
    check_legacy_redirect: bool = False,
) -> SmokeReport:
    report = SmokeReport(ok=True, base_url=base_url)
    run_api, api_skip_detail = api_auth_status(token, shell_only)

    health = check_health(base_url, timeout)
    report.checks.append(health)
    if not health.ok:
        report.ok = False

    shell_check, index_html = check_shell(base_url, timeout)
    report.checks.append(shell_check)
    if not shell_check.ok:
        report.ok = False
    elif index_html:
        for asset_check in check_assets(base_url, index_html, timeout):
            report.checks.append(asset_check)
            if not asset_check.ok:
                report.ok = False

    if not run_api:
        for name in SKIPPED_API_CHECK_NAMES:
            report.checks.append(CheckResult(name, True, "skipped", api_skip_detail))
        if not shell_only:
            report.ok = False
        if check_legacy_redirect:
            redirect = check_legacy_dashboard_redirect(base_url, timeout)
            report.checks.append(redirect)
            if not redirect.ok:
                report.ok = False
        return report

    overview = check_api_endpoint(
        base_url, "api_overview", API_OVERVIEW, token, timeout
    )
    report.checks.append(overview)
    if not overview.ok:
        report.ok = False

    events_status, events_body, events_elapsed, events_err = _http_get(
        base_url,
        API_EVENTS_INDEX,
        token=token,
        timeout=timeout,
        accept="application/json",
    )
    if events_status is None or not (200 <= events_status < 300):
        detail = events_err or f"HTTP {events_status}"
        report.checks.append(
            CheckResult("api_events_index", False, "fail", detail, events_elapsed)
        )
        report.ok = False
        report.checks.append(
            CheckResult("api_event_detail", True, "skipped", "events index failed")
        )
    else:
        report.checks.append(
            CheckResult("api_events_index", True, "pass", "ok", events_elapsed)
        )
        event_id = first_event_id(events_body)
        if not event_id:
            report.warnings.append(
                "events index returned no rows; event detail check skipped"
            )
            report.checks.append(
                CheckResult(
                    "api_event_detail",
                    True,
                    "warn",
                    "no events in index response",
                )
            )
        else:
            detail_path = (
                f"/control/api/v1/events?event_id={request.quote(event_id, safe='')}"
                "&include_payload=true&page_size=1&sort=recent"
            )
            detail = check_api_endpoint(
                base_url,
                "api_event_detail",
                detail_path,
                token,
                timeout,
            )
            report.checks.append(detail)
            if not detail.ok:
                report.ok = False

    for api_name, api_path in API_READ_CHECKS:
        result = check_api_endpoint(base_url, api_name, api_path, token, timeout)
        report.checks.append(result)
        if not result.ok:
            report.ok = False

    if check_legacy_redirect:
        redirect = check_legacy_dashboard_redirect(base_url, timeout)
        report.checks.append(redirect)
        if not redirect.ok:
            report.ok = False

    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=os.environ.get("ENOCH_CONTROL_URL", "http://127.0.0.1:8787"),
    )
    parser.add_argument(
        "--token", default="", help="Bearer token for /control/api/v1/* checks"
    )
    parser.add_argument("--token-env", default="ENOCH_CONTROL_TOKEN")
    parser.add_argument("--timeout-sec", type=float, default=15.0)
    parser.add_argument(
        "--allow-unauthenticated-shell-only",
        action="store_true",
        help="Run shell/asset/health checks only; skip API checks when no token is set",
    )
    parser.add_argument(
        "--check-legacy-dashboard-redirect",
        action="store_true",
        help=(
            "After V1→V2 cutover: require GET /control/dashboard to redirect to "
            "/control/dashboard-v2"
        ),
    )
    parser.add_argument("--json", action="store_true", help="Emit compact JSON report")
    args = parser.parse_args(argv)

    token = resolve_token(args.token, args.token_env)
    report = run_smoke(
        args.base_url,
        token=token,
        timeout=args.timeout_sec,
        shell_only=args.allow_unauthenticated_shell_only,
        check_legacy_redirect=args.check_legacy_dashboard_redirect,
    )

    if args.json:
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    else:
        print(json.dumps(report.to_dict(), indent=2))
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
