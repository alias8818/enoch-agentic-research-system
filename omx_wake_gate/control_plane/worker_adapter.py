from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable
from urllib import error, request

from .models import ControlFlags, WorkerPreflightCheck, WorkerPreflightRequest, WorkerPreflightResponse


@dataclass
class HttpResult:
    ok: bool
    status: int | None
    body: dict[str, Any] | None
    error: str = ""


Transport = Callable[[str, dict[str, str]], HttpResult]
JsonTransport = Callable[[str, str, dict[str, str], dict[str, Any] | None], HttpResult]


def _http_request_json(method: str, url: str, headers: dict[str, str], payload: dict[str, Any] | None = None) -> HttpResult:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    merged_headers = {"Content-Type": "application/json", **headers}
    req = request.Request(url, data=data, headers=merged_headers, method=method)
    try:
        with request.urlopen(req, timeout=5) as resp:
            raw = resp.read().decode("utf-8")
            return HttpResult(ok=200 <= resp.status < 300, status=resp.status, body=json.loads(raw) if raw else {})
    except error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        return HttpResult(ok=False, status=exc.code, body=None, error=raw or str(exc))
    except Exception as exc:  # pragma: no cover - exercised in deployment
        return HttpResult(ok=False, status=None, body=None, error=f"{type(exc).__name__}: {exc}")


def _http_get_json(url: str, headers: dict[str, str]) -> HttpResult:
    return _http_request_json("GET", url, headers, None)


def post_worker_json(base_url: str, path: str, token: str, payload: dict[str, Any], *, transport: JsonTransport = _http_request_json) -> HttpResult:
    return transport("POST", base_url.rstrip("/") + path, _auth_headers(token), payload)


def _check(name: str, ok: bool, detail: str, data: dict[str, Any] | None = None) -> WorkerPreflightCheck:
    return WorkerPreflightCheck(name=name, ok=ok, detail=detail, data=data or {})


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"} if token else {}


def run_worker_preflight(
    payload: WorkerPreflightRequest,
    flags: ControlFlags,
    *,
    transport: Transport = _http_get_json,
) -> WorkerPreflightResponse:
    """Run non-dispatching checks before the VM can target a GB10 worker.

    This function intentionally performs no mutation and never starts work. It
    is safe while the queue is paused and during GB10 maintenance windows.
    """

    checks: list[WorkerPreflightCheck] = []
    if payload.require_paused:
        checks.append(_check("control_queue_paused", flags.queue_paused, "control plane queue is paused" if flags.queue_paused else "control plane queue is not paused"))
    checks.append(_check("control_maintenance_mode", flags.maintenance_mode, "maintenance mode is enabled" if flags.maintenance_mode else "maintenance mode is disabled"))

    base = payload.wake_gate_url.rstrip("/")
    health = transport(f"{base}/healthz", {})
    checks.append(
        _check(
            "wake_gate_healthz",
            bool(health.ok and health.body and health.body.get("ok") is True),
            "wake gate health endpoint returned ok" if health.ok else f"wake gate health failed: {health.error or health.status}",
            {"status": health.status, "body": health.body or {}},
        )
    )

    dashboard_body: dict[str, Any] | None = None
    if payload.bearer_token:
        dashboard = transport(f"{base}/dashboard/api?limit=5&event_limit=5", _auth_headers(payload.bearer_token))
        dashboard_body = dashboard.body if dashboard.ok and dashboard.body else None
        checks.append(
            _check(
                "wake_gate_dashboard_api",
                bool(dashboard_body),
                "dashboard API reachable" if dashboard_body else f"dashboard API unavailable: {dashboard.error or dashboard.status}",
                {"status": dashboard.status, "body": dashboard_body or {}},
            )
        )
        telemetry = (dashboard_body or {}).get("telemetry") or {}
        queue = (dashboard_body or {}).get("queue") or {}
        totals = (dashboard_body or {}).get("totals") or {}
        gpu_pct = float(telemetry.get("gpu_pct") or 0.0)
        mem_available = int(telemetry.get("memory_available_mib") or 0)
        swap_free = int(telemetry.get("swap_free_mib") or 0)
        gpu_pids = telemetry.get("gpu_compute_pids") or []
        active_or_waiting = int(totals.get("active_or_waiting") or 0)
        live = int(totals.get("live") or 0)
        queue_active = int(queue.get("active_count") or 0)
        checks.extend(
            [
                _check("worker_gpu_idle", gpu_pct <= payload.max_gpu_pct and not gpu_pids, f"gpu_pct={gpu_pct}, gpu_compute_pids={gpu_pids}", {"gpu_pct": gpu_pct, "gpu_compute_pids": gpu_pids}),
                _check("worker_memory_available", mem_available >= payload.min_memory_available_mib, f"memory_available_mib={mem_available}", {"memory_available_mib": mem_available, "swap_free_mib": swap_free}),
                _check("worker_no_live_runs", active_or_waiting == 0 and live == 0, f"active_or_waiting={active_or_waiting}, live={live}", {"active_or_waiting": active_or_waiting, "live": live}),
                _check("worker_queue_snapshot_no_active", queue_active == 0, f"queue_active_count={queue_active}", {"queue_active_count": queue_active}),
                _check("worker_swapless_allowed", True, f"swap_free_mib={swap_free}; swapless GB10 is allowed when earlyoom is active", {"swap_free_mib": swap_free}),
            ]
        )
    else:
        checks.append(_check("wake_gate_dashboard_api", True, "skipped authenticated dashboard checks; provide bearer_token for telemetry and active-run checks", {"skipped": True}))

    required_names = {"control_queue_paused", "wake_gate_healthz"} if payload.require_paused else {"wake_gate_healthz"}
    if payload.bearer_token:
        required_names.update({"wake_gate_dashboard_api", "worker_gpu_idle", "worker_memory_available", "worker_no_live_runs", "worker_queue_snapshot_no_active"})
    passed = all(check.ok for check in checks if check.name in required_names or payload.strict)
    summary = "worker preflight passed" if passed else "worker preflight failed"
    return WorkerPreflightResponse(ok=passed, target=payload.wake_gate_url, summary=summary, checks=checks)
