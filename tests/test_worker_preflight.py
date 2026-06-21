from __future__ import annotations

import unittest

from enoch_control_plane.control_plane.models import (
    ControlFlags,
    WorkerPreflightRequest,
)
from enoch_control_plane.control_plane.worker_adapter import (
    HttpResult,
    post_worker_json,
    run_worker_preflight,
)


class FakeWorkerTransport:
    def __init__(
        self,
        *,
        health_ok: bool = True,
        gpu_pct: float = 0.0,
        active: int = 0,
        memory: int = 120_000,
    ) -> None:
        self.health_ok = health_ok
        self.gpu_pct = gpu_pct
        self.active = active
        self.memory = memory
        self.calls: list[tuple[str, dict[str, str]]] = []

    def __call__(self, url: str, headers: dict[str, str]) -> HttpResult:
        self.calls.append((url, headers))
        if url.endswith("/healthz"):
            return HttpResult(
                ok=self.health_ok,
                status=200 if self.health_ok else 503,
                body={"ok": self.health_ok},
                error="down" if not self.health_ok else "",
            )
        if "/dashboard/api" in url:
            return HttpResult(
                ok=True,
                status=200,
                body={
                    "service": {
                        "completion_callback_token_fingerprint": "expected-fingerprint"
                    },
                    "telemetry": {
                        "gpu_pct": self.gpu_pct,
                        "gpu_compute_pids": [],
                        "memory_available_mib": self.memory,
                        "swap_free_mib": 0,
                    },
                    "totals": {"active_or_waiting": self.active, "live": self.active},
                    "queue": {"active_count": self.active},
                    "runs": [
                        {
                            "run_id": "run-1",
                            "project_id": "project-1",
                            "gate_state": "running",
                        }
                    ],
                },
            )
        raise AssertionError(f"unexpected url {url}")


class WorkerPreflightTests(unittest.TestCase):
    def test_preflight_passes_with_paused_control_and_idle_worker(self) -> None:
        transport = FakeWorkerTransport()
        response = run_worker_preflight(
            WorkerPreflightRequest(
                wake_gate_url="http://worker:8787", bearer_token="secret"
            ),
            ControlFlags(queue_paused=True, maintenance_mode=True),
            transport=transport,
        )
        self.assertTrue(response.ok)
        self.assertEqual(response.summary, "worker preflight passed")
        self.assertIn("Authorization", transport.calls[1][1])
        checks = {check.name: check for check in response.checks}
        self.assertTrue(checks["worker_swapless_allowed"].ok)
        self.assertEqual(checks["worker_memory_available"].data["swap_free_mib"], 0)
        self.assertEqual(
            checks["wake_gate_dashboard_api"].data["body"]["runs"][0]["run_id"], "run-1"
        )
        self.assertTrue(
            checks["wake_gate_dashboard_api"].data["body"]["body_compacted"]
        )

    def test_preflight_treats_stale_zero_process_worker_gate_as_idle(self) -> None:
        def transport(url: str, headers: dict[str, str]) -> HttpResult:
            if url.endswith("/healthz"):
                return HttpResult(ok=True, status=200, body={"ok": True})
            if "/dashboard/api" in url:
                return HttpResult(
                    ok=True,
                    status=200,
                    body={
                        "service": {
                            "completion_callback_token_fingerprint": "expected-fingerprint"
                        },
                        "telemetry": {
                            "gpu_pct": 0,
                            "gpu_compute_pids": [],
                            "memory_available_mib": 120_000,
                            "swap_free_mib": 0,
                        },
                        "totals": {"active_or_waiting": 1, "live": 1},
                        "queue": {"active_count": 0},
                        "runs": [
                            {
                                "run_id": "stale-run",
                                "project_id": "project-stale",
                                "gate_state": "running",
                                "lifecycle_state": "active",
                                "is_live": True,
                                "active_process_count": 0,
                                "active_processes": [],
                                "active_processes_truncated": False,
                                "age_seconds": 600,
                                "needs_attention": False,
                            }
                        ],
                    },
                )
            raise AssertionError(f"unexpected url {url}")

        response = run_worker_preflight(
            WorkerPreflightRequest(
                wake_gate_url="http://worker:8787",
                bearer_token="secret",
                require_paused=False,
            ),
            ControlFlags(queue_paused=False, maintenance_mode=False),
            transport=transport,
        )

        checks = {check.name: check for check in response.checks}
        self.assertTrue(response.ok)
        self.assertTrue(checks["worker_no_live_runs"].ok)
        self.assertTrue(checks["worker_no_live_runs"].data["stale_worker_gate_only"])
        self.assertEqual(checks["worker_no_live_runs"].data["effective_live"], 0)

    def test_preflight_does_not_treat_fresh_zero_process_live_run_as_idle(self) -> None:
        def transport(url: str, headers: dict[str, str]) -> HttpResult:
            if url.endswith("/healthz"):
                return HttpResult(ok=True, status=200, body={"ok": True})
            if "/dashboard/api" in url:
                return HttpResult(
                    ok=True,
                    status=200,
                    body={
                        "service": {
                            "completion_callback_token_fingerprint": "expected-fingerprint"
                        },
                        "telemetry": {
                            "gpu_pct": 0,
                            "gpu_compute_pids": [],
                            "memory_available_mib": 120_000,
                            "swap_free_mib": 0,
                        },
                        "totals": {"active_or_waiting": 1, "live": 1},
                        "queue": {"active_count": 0},
                        "runs": [
                            {
                                "run_id": "fresh-run",
                                "project_id": "project-fresh",
                                "lifecycle_state": "active",
                                "is_live": True,
                                "active_process_count": 0,
                                "active_processes": [],
                                "active_processes_truncated": False,
                                "age_seconds": 30,
                                "needs_attention": False,
                            }
                        ],
                    },
                )
            raise AssertionError(f"unexpected url {url}")

        response = run_worker_preflight(
            WorkerPreflightRequest(
                wake_gate_url="http://worker:8787",
                bearer_token="secret",
                require_paused=False,
            ),
            ControlFlags(queue_paused=False, maintenance_mode=False),
            transport=transport,
        )

        checks = {check.name: check for check in response.checks}
        self.assertFalse(response.ok)
        self.assertFalse(checks["worker_no_live_runs"].ok)
        self.assertFalse(checks["worker_no_live_runs"].data["stale_worker_gate_only"])
        self.assertEqual(checks["worker_no_live_runs"].data["effective_live"], 1)

    def test_preflight_bounds_large_dashboard_payloads(self) -> None:
        large_note = "x" * 50_000

        def transport(url: str, headers: dict[str, str]) -> HttpResult:
            if url.endswith("/healthz"):
                return HttpResult(ok=True, status=200, body={"ok": True})
            if "/dashboard/api" in url:
                return HttpResult(
                    ok=True,
                    status=200,
                    body={
                        "service": {"completion_callback_token_fingerprint": "abc"},
                        "telemetry": {
                            "gpu_pct": 0,
                            "gpu_compute_pids": [],
                            "memory_available_mib": 120_000,
                            "swap_free_mib": 0,
                        },
                        "totals": {"active_or_waiting": 0, "live": 0},
                        "queue": {"active_count": 0},
                        "runs": [
                            {
                                "run_id": "run-large",
                                "project_id": "project-large",
                                "run_notes_tail": large_note,
                                "quiet_samples": [{"sample": large_note}],
                                "project_decision": {"long_internal_notes": large_note},
                            }
                        ],
                    },
                )
            raise AssertionError(f"unexpected url {url}")

        response = run_worker_preflight(
            WorkerPreflightRequest(
                wake_gate_url="http://worker:8787", bearer_token="secret"
            ),
            ControlFlags(queue_paused=True, maintenance_mode=True),
            transport=transport,
        )

        payload = response.model_dump(mode="json")
        checks = {check.name: check for check in response.checks}
        dashboard_body = checks["wake_gate_dashboard_api"].data["body"]
        compact_run = dashboard_body["runs"][0]
        self.assertTrue(dashboard_body["body_compacted"])
        self.assertEqual(compact_run["run_id"], "run-large")
        self.assertTrue(compact_run["run_notes_tail_omitted"])
        self.assertTrue(compact_run["quiet_samples_omitted"])
        self.assertTrue(compact_run["project_decision_omitted"])
        self.assertNotIn(large_note, str(payload))
        self.assertNotIn("long_internal_notes", str(payload))

    def test_preflight_marks_disabled_maintenance_mode_as_safe(self) -> None:
        response = run_worker_preflight(
            WorkerPreflightRequest(
                wake_gate_url="http://worker:8787",
                bearer_token="secret",
                require_paused=False,
            ),
            ControlFlags(queue_paused=False, maintenance_mode=False),
            transport=FakeWorkerTransport(),
        )

        checks = {check.name: check for check in response.checks}
        self.assertTrue(response.ok)
        self.assertTrue(checks["control_maintenance_mode"].ok)
        self.assertEqual(
            checks["control_maintenance_mode"].detail, "maintenance mode is disabled"
        )

    def test_preflight_fails_when_control_is_unpaused_but_pause_required(self) -> None:
        response = run_worker_preflight(
            WorkerPreflightRequest(
                wake_gate_url="http://worker:8787", bearer_token="secret"
            ),
            ControlFlags(queue_paused=False, maintenance_mode=False),
            transport=FakeWorkerTransport(),
        )
        self.assertFalse(response.ok)
        self.assertFalse(
            {check.name: check for check in response.checks}["control_queue_paused"].ok
        )

    def test_preflight_fails_on_active_worker(self) -> None:
        response = run_worker_preflight(
            WorkerPreflightRequest(
                wake_gate_url="http://worker:8787", bearer_token="secret"
            ),
            ControlFlags(queue_paused=True, maintenance_mode=True),
            transport=FakeWorkerTransport(active=1),
        )
        self.assertFalse(response.ok)
        checks = {check.name: check for check in response.checks}
        self.assertFalse(checks["worker_no_live_runs"].ok)
        self.assertFalse(checks["worker_queue_snapshot_no_active"].ok)

    def test_preflight_requires_callback_token_fingerprint_match_when_expected(
        self,
    ) -> None:
        response = run_worker_preflight(
            WorkerPreflightRequest(
                wake_gate_url="http://worker:8787",
                bearer_token="secret",
                expected_callback_token_fingerprint="expected-fingerprint",
            ),
            ControlFlags(queue_paused=True, maintenance_mode=True),
            transport=FakeWorkerTransport(),
        )

        self.assertTrue(response.ok)
        checks = {check.name: check for check in response.checks}
        self.assertTrue(checks["worker_callback_token_compatible"].ok)

    def test_preflight_fails_when_callback_token_fingerprint_mismatch(self) -> None:
        response = run_worker_preflight(
            WorkerPreflightRequest(
                wake_gate_url="http://worker:8787",
                bearer_token="secret",
                expected_callback_token_fingerprint="different-fingerprint",
            ),
            ControlFlags(queue_paused=True, maintenance_mode=True),
            transport=FakeWorkerTransport(),
        )

        self.assertFalse(response.ok)
        checks = {check.name: check for check in response.checks}
        self.assertFalse(checks["worker_callback_token_compatible"].ok)

    def test_preflight_without_bearer_only_requires_health_and_pause(self) -> None:
        response = run_worker_preflight(
            WorkerPreflightRequest(wake_gate_url="http://worker:8787", bearer_token=""),
            ControlFlags(queue_paused=True, maintenance_mode=True),
            transport=FakeWorkerTransport(active=1),
        )
        self.assertTrue(response.ok)
        checks = {check.name: check for check in response.checks}
        self.assertTrue(checks["wake_gate_dashboard_api"].data["skipped"])

    def test_preflight_malformed_worker_numbers_fail_closed_without_exception(
        self,
    ) -> None:
        def transport(url: str, headers: dict[str, str]) -> HttpResult:
            if url.endswith("/healthz"):
                return HttpResult(ok=True, status=200, body={"ok": True})
            if "/dashboard/api" in url:
                return HttpResult(
                    ok=True,
                    status=200,
                    body={
                        "telemetry": {
                            "gpu_pct": "not-a-number",
                            "gpu_compute_pids": [],
                            "memory_available_mib": "unknown",
                            "swap_free_mib": "unknown",
                        },
                        "totals": {"active_or_waiting": "unknown", "live": "unknown"},
                        "queue": {"active_count": "unknown"},
                    },
                )
            raise AssertionError(f"unexpected url {url}")

        response = run_worker_preflight(
            WorkerPreflightRequest(
                wake_gate_url="http://worker:8787", bearer_token="secret"
            ),
            ControlFlags(queue_paused=True, maintenance_mode=True),
            transport=transport,
        )

        self.assertFalse(response.ok)
        checks = {check.name: check for check in response.checks}
        self.assertFalse(checks["worker_gpu_idle"].ok)
        self.assertEqual(checks["worker_gpu_idle"].data["gpu_pct"], 101.0)
        self.assertFalse(checks["worker_memory_available"].ok)
        self.assertFalse(checks["worker_no_live_runs"].ok)
        self.assertFalse(checks["worker_queue_snapshot_no_active"].ok)

    def test_preflight_malformed_health_body_fails_closed_without_exception(
        self,
    ) -> None:
        def transport(url: str, headers: dict[str, str]) -> HttpResult:
            if url.endswith("/healthz"):
                return HttpResult(ok=True, status=200, body=[{"ok": True}])  # type: ignore[arg-type]
            raise AssertionError(
                "dashboard API should not be required to prove malformed health handling"
            )

        response = run_worker_preflight(
            WorkerPreflightRequest(wake_gate_url="http://worker:8787", bearer_token=""),
            ControlFlags(queue_paused=True, maintenance_mode=True),
            transport=transport,
        )

        self.assertFalse(response.ok)
        checks = {check.name: check for check in response.checks}
        self.assertFalse(checks["wake_gate_healthz"].ok)
        self.assertIn("malformed", checks["wake_gate_healthz"].detail)

    def test_preflight_malformed_dashboard_body_fails_closed_without_exception(
        self,
    ) -> None:
        bodies = [[{"not": "an-object"}]]

        def transport(url: str, headers: dict[str, str]) -> HttpResult:
            if url.endswith("/healthz"):
                return HttpResult(ok=True, status=200, body={"ok": True})
            if "/dashboard/api" in url:
                return HttpResult(ok=True, status=200, body=bodies.pop(0))  # type: ignore[arg-type]
            raise AssertionError(f"unexpected url {url}")

        response = run_worker_preflight(
            WorkerPreflightRequest(
                wake_gate_url="http://worker:8787", bearer_token="secret"
            ),
            ControlFlags(queue_paused=True, maintenance_mode=True),
            transport=transport,
        )

        self.assertFalse(response.ok)
        checks = {check.name: check for check in response.checks}
        self.assertFalse(checks["wake_gate_dashboard_api"].ok)
        self.assertIn("malformed", checks["wake_gate_dashboard_api"].detail)

    def test_post_worker_json_uses_bearer_and_json_transport(self) -> None:
        calls = []

        def transport(method, url, headers, payload):
            calls.append((method, url, headers, payload))
            return HttpResult(ok=True, status=200, body={"accepted": True})

        response = post_worker_json(
            "http://worker:8787/",
            "/prepare-project",
            "secret",
            {"x": 1},
            transport=transport,
        )
        self.assertTrue(response.ok)
        self.assertEqual(calls[0][0], "POST")
        self.assertEqual(calls[0][1], "http://worker:8787/prepare-project")
        self.assertEqual(calls[0][2]["Authorization"], "Bearer secret")
        self.assertEqual(calls[0][3], {"x": 1})


if __name__ == "__main__":
    unittest.main()


def test_http_request_json_rejects_file_scheme_before_urlopen(monkeypatch) -> None:
    from enoch_control_plane.control_plane import worker_adapter

    def fake_urlopen(*args, **kwargs):
        raise AssertionError("urlopen should not run for unsafe worker URL")

    monkeypatch.setattr(worker_adapter, "urlopen_validated", fake_urlopen)
    result = worker_adapter._http_request_json("GET", "file:///etc/passwd", {}, None)
    assert result.ok is False
    assert result.status is None
    assert "worker url must use http or https" in result.error


def test_http_request_json_rejects_non_object_json(monkeypatch) -> None:
    from enoch_control_plane.control_plane import worker_adapter

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return b'[{"ok": true}]'

    monkeypatch.setattr(
        worker_adapter, "urlopen_validated", lambda *_args, **_kwargs: Response()
    )

    result = worker_adapter._http_request_json(
        "GET", "http://worker.example/healthz", {}, None
    )

    assert result.ok is False
    assert result.status == 200
    assert "JSON body is not an object" in result.error
