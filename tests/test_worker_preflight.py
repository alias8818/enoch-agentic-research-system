from __future__ import annotations

import unittest

from omx_wake_gate.control_plane.models import ControlFlags, WorkerPreflightRequest
from omx_wake_gate.control_plane.worker_adapter import HttpResult, post_worker_json, run_worker_preflight


class FakeWorkerTransport:
    def __init__(self, *, health_ok: bool = True, gpu_pct: float = 0.0, active: int = 0, memory: int = 120_000) -> None:
        self.health_ok = health_ok
        self.gpu_pct = gpu_pct
        self.active = active
        self.memory = memory
        self.calls: list[tuple[str, dict[str, str]]] = []

    def __call__(self, url: str, headers: dict[str, str]) -> HttpResult:
        self.calls.append((url, headers))
        if url.endswith("/healthz"):
            return HttpResult(ok=self.health_ok, status=200 if self.health_ok else 503, body={"ok": self.health_ok}, error="down" if not self.health_ok else "")
        if "/dashboard/api" in url:
            return HttpResult(ok=True, status=200, body={
                "telemetry": {
                    "gpu_pct": self.gpu_pct,
                    "gpu_compute_pids": [],
                    "memory_available_mib": self.memory,
                    "swap_free_mib": 0,
                },
                "totals": {"active_or_waiting": self.active, "live": self.active},
                "queue": {"active_count": self.active},
                "runs": [{"run_id": "run-1", "project_id": "project-1", "gate_state": "running"}],
            })
        raise AssertionError(f"unexpected url {url}")


class WorkerPreflightTests(unittest.TestCase):
    def test_preflight_passes_with_paused_control_and_idle_worker(self) -> None:
        transport = FakeWorkerTransport()
        response = run_worker_preflight(
            WorkerPreflightRequest(wake_gate_url="http://worker:8787", bearer_token="secret"),
            ControlFlags(queue_paused=True, maintenance_mode=True),
            transport=transport,
        )
        self.assertTrue(response.ok)
        self.assertEqual(response.summary, "worker preflight passed")
        self.assertIn("Authorization", transport.calls[1][1])
        checks = {check.name: check for check in response.checks}
        self.assertTrue(checks["worker_swapless_allowed"].ok)
        self.assertEqual(checks["worker_memory_available"].data["swap_free_mib"], 0)
        self.assertEqual(checks["wake_gate_dashboard_api"].data["body"]["runs"][0]["run_id"], "run-1")

    def test_preflight_fails_when_control_is_unpaused_but_pause_required(self) -> None:
        response = run_worker_preflight(
            WorkerPreflightRequest(wake_gate_url="http://worker:8787", bearer_token="secret"),
            ControlFlags(queue_paused=False, maintenance_mode=False),
            transport=FakeWorkerTransport(),
        )
        self.assertFalse(response.ok)
        self.assertFalse({check.name: check for check in response.checks}["control_queue_paused"].ok)

    def test_preflight_fails_on_active_worker(self) -> None:
        response = run_worker_preflight(
            WorkerPreflightRequest(wake_gate_url="http://worker:8787", bearer_token="secret"),
            ControlFlags(queue_paused=True, maintenance_mode=True),
            transport=FakeWorkerTransport(active=1),
        )
        self.assertFalse(response.ok)
        checks = {check.name: check for check in response.checks}
        self.assertFalse(checks["worker_no_live_runs"].ok)
        self.assertFalse(checks["worker_queue_snapshot_no_active"].ok)

    def test_preflight_without_bearer_only_requires_health_and_pause(self) -> None:
        response = run_worker_preflight(
            WorkerPreflightRequest(wake_gate_url="http://worker:8787", bearer_token=""),
            ControlFlags(queue_paused=True, maintenance_mode=True),
            transport=FakeWorkerTransport(active=1),
        )
        self.assertTrue(response.ok)
        checks = {check.name: check for check in response.checks}
        self.assertTrue(checks["wake_gate_dashboard_api"].data["skipped"])

    def test_post_worker_json_uses_bearer_and_json_transport(self) -> None:
        calls = []

        def transport(method, url, headers, payload):
            calls.append((method, url, headers, payload))
            return HttpResult(ok=True, status=200, body={"accepted": True})

        response = post_worker_json("http://worker:8787/", "/prepare-project", "secret", {"x": 1}, transport=transport)
        self.assertTrue(response.ok)
        self.assertEqual(calls[0][0], "POST")
        self.assertEqual(calls[0][1], "http://worker:8787/prepare-project")
        self.assertEqual(calls[0][2]["Authorization"], "Bearer secret")
        self.assertEqual(calls[0][3], {"x": 1})



if __name__ == "__main__":
    unittest.main()
