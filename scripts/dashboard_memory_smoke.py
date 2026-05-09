#!/usr/bin/env python3
"""Poll Enoch dashboard/control endpoints and report timing/size/RSS headers.

This script is safe for production smoke checks: it performs GET requests only,
does not print bearer tokens, and emits a compact JSON report for before/after
memory comparisons. Server RSS fields are populated when the opt-in route
observability middleware is enabled.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import time
from dataclasses import dataclass
from typing import Any
from urllib import error, request


DEFAULT_ENDPOINTS = [
    "/healthz",
    "/control/api/v1/overview?active_limit=5&event_limit=5",
    "/control/api/v1/queue?page_size=25",
    "/control/api/v1/runs?page_size=25",
    "/control/api/v1/papers?page_size=25",
    "/control/api/v1/events?page_size=25",
    "/control/api/v1/observability/memory",
]


@dataclass
class Sample:
    endpoint: str
    ok: bool
    status: int | None
    elapsed_ms: float
    bytes_read: int
    route_duration_ms: float | None
    route_rss_mib: float | None
    route_peak_rss_mib: float | None
    error: str = ""


def _float_header(headers: Any, name: str) -> float | None:
    raw = headers.get(name)
    if raw is None:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def fetch(base_url: str, endpoint: str, token: str, timeout: float) -> Sample:
    url = base_url.rstrip("/") + endpoint
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = request.Request(url, headers=headers, method="GET")
    started = time.perf_counter()
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            return Sample(
                endpoint=endpoint,
                ok=200 <= resp.status < 300,
                status=resp.status,
                elapsed_ms=elapsed_ms,
                bytes_read=len(data),
                route_duration_ms=_float_header(resp.headers, "X-Enoch-Route-Duration-Ms"),
                route_rss_mib=_float_header(resp.headers, "X-Enoch-Route-RSS-MiB"),
                route_peak_rss_mib=_float_header(resp.headers, "X-Enoch-Route-Peak-RSS-MiB"),
            )
    except error.HTTPError as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        body = exc.read()
        return Sample(endpoint, False, exc.code, elapsed_ms, len(body), None, None, None, f"HTTPError: {exc.code}")
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return Sample(endpoint, False, None, elapsed_ms, 0, None, None, None, f"{type(exc).__name__}: {exc}")


def summarize(samples: list[Sample]) -> dict[str, Any]:
    by_endpoint: dict[str, list[Sample]] = {}
    for sample in samples:
        by_endpoint.setdefault(sample.endpoint, []).append(sample)
    endpoint_summaries = {}
    for endpoint, rows in by_endpoint.items():
        elapsed = [row.elapsed_ms for row in rows]
        rss_values = [row.route_rss_mib for row in rows if row.route_rss_mib is not None]
        endpoint_summaries[endpoint] = {
            "requests": len(rows),
            "ok": sum(1 for row in rows if row.ok),
            "failed": sum(1 for row in rows if not row.ok),
            "status_codes": sorted({row.status for row in rows if row.status is not None}),
            "transport_errors": sum(1 for row in rows if row.status is None),
            "bytes_total": sum(row.bytes_read for row in rows),
            "elapsed_ms_avg": statistics.fmean(elapsed) if elapsed else 0.0,
            "elapsed_ms_max": max(elapsed) if elapsed else 0.0,
            "route_rss_mib_first": rss_values[0] if rss_values else None,
            "route_rss_mib_last": rss_values[-1] if rss_values else None,
            "route_rss_mib_delta": None if len(rss_values) < 2 else rss_values[-1] - rss_values[0],
        }
    return endpoint_summaries


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.environ.get("ENOCH_CONTROL_URL", "http://127.0.0.1:8787"))
    parser.add_argument("--token-env", default="ENOCH_CONTROL_TOKEN")
    parser.add_argument("--endpoint", action="append", dest="endpoints", help="Endpoint path to poll; repeatable")
    parser.add_argument("--iterations", type=int, default=3)
    parser.add_argument("--sleep-sec", type=float, default=0.0)
    parser.add_argument("--timeout-sec", type=float, default=10.0)
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    token = os.environ.get(args.token_env) or os.environ.get("ENOCH_CONTROL_PLANE_TOKEN", "") or os.environ.get("OMX_INBOUND_BEARER_TOKEN", "")
    endpoints = args.endpoints or DEFAULT_ENDPOINTS
    samples: list[Sample] = []
    for _ in range(max(1, args.iterations)):
        for endpoint in endpoints:
            samples.append(fetch(args.base_url, endpoint, token, args.timeout_sec))
        if args.sleep_sec > 0:
            time.sleep(args.sleep_sec)

    report = {
        "ok": all(sample.ok for sample in samples),
        "base_url": args.base_url,
        "iterations": max(1, args.iterations),
        "sample_count": len(samples),
        "server_rss_headers_present": any(sample.route_rss_mib is not None for sample in samples),
        "summary": summarize(samples),
        "samples": [sample.__dict__ for sample in samples],
    }
    raw = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(raw + "\n")
    print(raw)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
