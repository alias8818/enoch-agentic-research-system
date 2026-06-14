from __future__ import annotations

import importlib.util
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch
import unittest

MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "deploy" / "enoch_queue_alert_check.py"
)
spec = importlib.util.spec_from_file_location("enoch_queue_alert_check", MODULE_PATH)
queue_pump = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(queue_pump)


class QueuePumpTests(unittest.TestCase):
    def test_base_url_defaults_to_plain_http_for_uvicorn_service(self) -> None:
        self.assertEqual(
            queue_pump._base_url({"listen_host": "0.0.0.0", "listen_port": 8787}),
            "http://127.0.0.1:8787",
        )

    def test_base_url_ignores_env_control_url_when_using_config_tokens(self) -> None:
        with patch.dict(
            queue_pump.os.environ,
            {"ENOCH_CONTROL_URL": "https://control.example:9443/"},
            clear=False,
        ):
            self.assertEqual(queue_pump._base_url({}), "http://127.0.0.1:8787")

    def _run_main(
        self, *, status: dict | None = None
    ) -> tuple[int, dict, list[tuple[str, str, str, dict]]]:
        calls: list[tuple[str, str, str, dict]] = []
        status = status or {
            "flags": {"queue_paused": False, "maintenance_mode": False},
            "dispatch_safe": True,
            "dispatch_blockers": [],
            "active_items": [],
            "next_candidate": {"project_id": "queued-idea"},
            "conflicts": [],
        }

        def fake_post(
            base_url: str, path: str, token: str, payload: dict, *, timeout: int = 30
        ) -> dict:
            calls.append((base_url, path, token, payload))
            if path == "/control/api/preflight":
                return {
                    "ok": True,
                    "target": "http://worker.example:8787",
                    "summary": "worker preflight passed",
                    "checks": [
                        {
                            "name": "wake_gate_dashboard_api",
                            "ok": True,
                            "data": {"body": {"rows": ["x" * 1000]}},
                        }
                    ],
                }
            if path == "/control/api/alerts/queue-check":
                return {"should_alert": False, "sent": False, "alerts_enabled": True}
            if path == "/control/papers/draft-next":
                return {
                    "action": "noop",
                    "reason": "no eligible completed paper-draft candidate without paper remains",
                }
            if path == "/control/api/v1/followups/launch-next":
                if payload.get("dry_run"):
                    return {
                        "action": "dry_run_followup",
                        "followup": {"idea_id": "followup-idea"},
                    }
                return {
                    "action": "followup_queued",
                    "followup": {"idea_id": "followup-idea"},
                }
            if path == "/control/dispatch-next":
                return {
                    "action": "live_dispatch",
                    "candidate": {
                        "project_id": payload.get("project_id", "queued-idea")
                    },
                }
            raise AssertionError(path)

        with (
            patch.object(
                queue_pump,
                "_load_config",
                return_value={
                    "listen_host": "127.0.0.1",
                    "listen_port": 8787,
                    "control_api_bearer_token": "t",
                    "worker_wake_gate_bearer_token": "worker-t",
                    "queue_pump_enabled": True,
                },
            ),
            patch.object(queue_pump, "_post_json", side_effect=fake_post),
            patch.object(queue_pump, "_get_json", return_value=status),
        ):
            out = io.StringIO()
            with redirect_stdout(out):
                code = queue_pump.main()
        return code, json.loads(out.getvalue()), calls

    def test_queue_pump_dispatches_when_safe_and_candidate_exists(self) -> None:
        code, output, calls = self._run_main()
        paths = [path for _base_url, path, _token, _payload in calls]
        self.assertEqual(code, 0)
        self.assertNotIn("/control/papers/draft-next", paths)
        self.assertIn("/control/dispatch-next", paths)
        self.assertEqual(output["dispatch"]["action"], "live_dispatch")
        self.assertEqual(
            output["paper_draft"]["reason"], "queue pump paper drafting disabled"
        )
        self.assertEqual(output["preflight"]["check_count"], 1)
        self.assertNotIn("checks", output["preflight"])
        self.assertLess(len(json.dumps(output)), 1000)

    def test_cli_dry_run_does_not_perform_queue_pump_side_effects(self) -> None:
        status = {
            "flags": {"queue_paused": False, "maintenance_mode": False},
            "dispatch_safe": True,
            "dispatch_blockers": [],
            "active_items": [],
            "next_candidate": {"project_id": "queued-idea"},
            "conflicts": [],
        }
        calls: list[tuple[str, dict[str, object]]] = []

        def fake_post(
            base_url: str,
            path: str,
            token: str,
            payload: dict[str, object],
            *,
            timeout: int = 30,
        ) -> dict[str, object]:
            calls.append((path, payload))
            if path == "/control/api/preflight":
                return {"ok": True, "checks": []}
            if path == "/control/api/alerts/queue-check":
                return {"should_alert": False, "sent": False, "alerts_enabled": True}
            raise AssertionError(
                f"dry-run must not call mutating queue-pump endpoint: {path}"
            )

        with (
            patch.object(
                queue_pump,
                "_load_config",
                return_value={
                    "listen_host": "127.0.0.1",
                    "listen_port": 8787,
                    "control_api_bearer_token": "t",
                    "queue_pump_enabled": True,
                    "queue_pump_paper_draft_enabled": True,
                    "queue_pump_followup_launch_enabled": True,
                },
            ),
            patch.object(queue_pump, "_post_json", side_effect=fake_post),
            patch.object(queue_pump, "_get_json", return_value=status),
            patch.object(
                queue_pump.sys,
                "argv",
                ["enoch_queue_alert_check.py", "--dry-run", "--json"],
            ),
        ):
            out = io.StringIO()
            with redirect_stdout(out):
                code = queue_pump.main()

        output = json.loads(out.getvalue())
        paths = [path for path, _payload in calls]
        alert_payloads = [
            payload
            for path, payload in calls
            if path == "/control/api/alerts/queue-check"
        ]
        self.assertEqual(code, 0)
        self.assertEqual(len(alert_payloads), 1)
        self.assertTrue(alert_payloads[0]["dry_run"])
        self.assertNotIn("/control/papers/draft-next", paths)
        self.assertNotIn("/control/api/v1/followups/launch-next", paths)
        self.assertNotIn("/control/dispatch-next", paths)
        self.assertEqual(output["dispatch"]["reason"], "cli dry-run")
        self.assertEqual(output["paper_draft"]["reason"], "cli dry-run")
        self.assertEqual(output["followup_launch"]["reason"], "cli dry-run")

    def test_queue_pump_reports_dispatch_conflict_without_crashing(self) -> None:
        calls: list[str] = []
        status = {
            "flags": {"queue_paused": False, "maintenance_mode": False},
            "dispatch_safe": True,
            "dispatch_blockers": [],
            "active_items": [],
            "next_candidate": {"project_id": "queued-idea"},
            "conflicts": [],
        }

        def fake_post(
            base_url: str,
            path: str,
            token: str,
            payload: dict[str, object],
            *,
            timeout: int = 30,
        ) -> dict[str, object]:
            calls.append(path)
            if path == "/control/api/preflight":
                return {"ok": True, "checks": []}
            if path == "/control/api/alerts/queue-check":
                return {"should_alert": False, "sent": False, "alerts_enabled": True}
            if path == "/control/papers/draft-next":
                return {"action": "noop"}
            if path == "/control/dispatch-next":
                raise queue_pump.error.HTTPError(
                    f"{base_url}{path}",
                    409,
                    "Conflict",
                    {},
                    io.BytesIO(b'{"detail":"worker_preflight not ok"}'),
                )
            raise AssertionError(path)

        with (
            patch.object(
                queue_pump,
                "_load_config",
                return_value={
                    "listen_host": "127.0.0.1",
                    "listen_port": 8787,
                    "control_api_bearer_token": "t",
                    "queue_pump_enabled": True,
                },
            ),
            patch.object(queue_pump, "_post_json", side_effect=fake_post),
            patch.object(queue_pump, "_get_json", return_value=status),
        ):
            out = io.StringIO()
            with redirect_stdout(out):
                code = queue_pump.main()

        output = json.loads(out.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(calls[-1], "/control/dispatch-next")
        self.assertEqual(output["dispatch"]["action"], "skipped")
        self.assertEqual(output["dispatch"]["reason"], "dispatch not safe")
        self.assertEqual(output["dispatch"]["http_status"], 409)
        self.assertEqual(output["dispatch"]["error_type"], "HTTPError")
        self.assertNotIn("response_body", output["dispatch"])
        self.assertEqual(output["dispatch"]["response_body_bytes"], 36)
        self.assertEqual(
            output["dispatch"]["response_body_sha256"],
            "bc3c0bfa75f9af39cd706634c0162c328f7f6dafe38e475f39792211a7db64d1",
        )

    def test_queue_pump_skips_alert_and_mutations_while_control_plane_held(
        self,
    ) -> None:
        status = {
            "flags": {
                "queue_paused": True,
                "maintenance_mode": True,
                "pause_reason": "operator maintenance",
            },
            "dispatch_safe": True,
            "dispatch_blockers": [],
            "active_items": [],
            "next_candidate": {"project_id": "queued-idea"},
            "conflicts": [],
        }
        code, output, calls = self._run_main(status=status)
        paths = [path for _base_url, path, _token, _payload in calls]

        self.assertEqual(code, 0)
        self.assertNotIn("/control/api/alerts/queue-check", paths)
        self.assertNotIn("/control/papers/draft-next", paths)
        self.assertNotIn("/control/api/v1/followups/launch-next", paths)
        self.assertNotIn("/control/dispatch-next", paths)
        self.assertEqual(output["alert"]["action"], "skipped")
        self.assertEqual(output["alert"]["reason"], "control plane held")
        self.assertEqual(output["dispatch"]["reason"], "control plane held")
        self.assertEqual(output["paper_draft"]["reason"], "control plane held")
        self.assertTrue(output["alert"]["hold_state"]["maintenance_mode"])
        self.assertTrue(output["alert"]["hold_state"]["queue_paused"])

    def test_queue_pump_dispatches_when_enabled_draft_next_fails(self) -> None:
        calls: list[str] = []
        status = {
            "flags": {"queue_paused": False, "maintenance_mode": False},
            "dispatch_safe": True,
            "dispatch_blockers": [],
            "active_items": [],
            "next_candidate": {"project_id": "queued-idea"},
            "conflicts": [],
        }

        def fake_post(
            base_url: str,
            path: str,
            token: str,
            payload: dict[str, object],
            *,
            timeout: int = 30,
        ) -> dict[str, object]:
            calls.append(path)
            if path == "/control/api/preflight":
                return {"ok": True, "checks": []}
            if path == "/control/api/alerts/queue-check":
                return {"should_alert": False, "sent": False, "alerts_enabled": True}
            if path == "/control/papers/draft-next":
                raise queue_pump.error.HTTPError(
                    f"{base_url}{path}", 500, "Internal Server Error", {}, None
                )
            if path == "/control/dispatch-next":
                return {
                    "action": "live_dispatch",
                    "candidate": {"project_id": "queued-idea"},
                }
            raise AssertionError(path)

        with (
            patch.object(
                queue_pump,
                "_load_config",
                return_value={
                    "listen_host": "127.0.0.1",
                    "listen_port": 8787,
                    "control_api_bearer_token": "t",
                    "queue_pump_enabled": True,
                    "queue_pump_paper_draft_enabled": True,
                },
            ),
            patch.object(queue_pump, "_post_json", side_effect=fake_post),
            patch.object(queue_pump, "_get_json", return_value=status),
        ):
            out = io.StringIO()
            with redirect_stdout(out):
                code = queue_pump.main()

        output = json.loads(out.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(calls[-1], "/control/dispatch-next")
        self.assertEqual(output["paper_draft"]["action"], "error")
        self.assertEqual(output["dispatch"]["action"], "live_dispatch")

    def test_queue_pump_does_not_dispatch_when_no_candidate_exists(self) -> None:
        status = {
            "flags": {"queue_paused": False, "maintenance_mode": False},
            "dispatch_safe": True,
            "dispatch_blockers": [],
            "active_items": [],
            "next_candidate": None,
            "conflicts": [],
        }
        code, output, calls = self._run_main(status=status)
        paths = [path for _base_url, path, _token, _payload in calls]
        self.assertEqual(code, 0)
        self.assertNotIn("/control/papers/draft-next", paths)
        self.assertNotIn("/control/dispatch-next", paths)
        self.assertEqual(output["dispatch"]["reason"], "no queued candidate")
        self.assertEqual(
            output["followup_launch"]["reason"], "queue pump follow-up launch disabled"
        )

    def test_queue_pump_can_launch_one_followup_when_idle_and_enabled(self) -> None:
        status = {
            "flags": {"queue_paused": False, "maintenance_mode": False},
            "dispatch_safe": False,
            "dispatch_blockers": ["no queued dispatch candidate"],
            "active_items": [],
            "next_candidate": None,
            "conflicts": [],
        }
        calls: list[tuple[str, dict]] = []

        def fake_post(
            base_url: str, path: str, token: str, payload: dict, *, timeout: int = 30
        ) -> dict:
            calls.append((path, payload))
            if path == "/control/api/preflight":
                return {"ok": True, "checks": []}
            if path == "/control/api/alerts/queue-check":
                return {"should_alert": False, "sent": False, "alerts_enabled": True}
            if path == "/control/api/v1/followups/launch-next":
                if payload.get("dry_run"):
                    return {
                        "action": "dry_run_followup",
                        "followup": {"idea_id": "followup-idea"},
                    }
                return {
                    "action": "followup_queued",
                    "followup": {"idea_id": "followup-idea"},
                }
            if path == "/control/dispatch-next":
                return {
                    "action": "live_dispatch",
                    "candidate": {"project_id": "followup-idea"},
                }
            raise AssertionError(path)

        with (
            patch.object(
                queue_pump,
                "_load_config",
                return_value={
                    "listen_host": "127.0.0.1",
                    "listen_port": 8787,
                    "control_api_bearer_token": "t",
                    "queue_pump_enabled": True,
                    "queue_pump_followup_launch_enabled": True,
                },
            ),
            patch.object(queue_pump, "_post_json", side_effect=fake_post),
            patch.object(queue_pump, "_get_json", return_value=status),
        ):
            out = io.StringIO()
            with redirect_stdout(out):
                code = queue_pump.main()

        output = json.loads(out.getvalue())
        paths = [path for path, _payload in calls]
        self.assertEqual(code, 0)
        self.assertEqual(
            [path for path in paths if path == "/control/api/v1/followups/launch-next"],
            [
                "/control/api/v1/followups/launch-next",
                "/control/api/v1/followups/launch-next",
            ],
        )
        self.assertTrue(calls[2][1]["dry_run"])
        self.assertFalse(calls[3][1]["dry_run"])
        self.assertIn("/control/dispatch-next", paths)
        self.assertEqual(output["followup_dry_run"]["action"], "dry_run_followup")
        self.assertEqual(output["followup_launch"]["action"], "followup_queued")
        self.assertEqual(output["dispatch"]["action"], "live_dispatch")

    def test_queue_pump_does_not_launch_followup_when_queued_candidate_exists(
        self,
    ) -> None:
        code, output, calls = self._run_main()
        paths = [path for _base_url, path, _token, _payload in calls]
        self.assertEqual(code, 0)
        self.assertNotIn("/control/api/v1/followups/launch-next", paths)
        self.assertEqual(
            output["followup_launch"]["reason"], "queued candidate already present"
        )

    def test_queue_pump_does_not_launch_followup_when_active_lane_exists(self) -> None:
        status = {
            "flags": {"queue_paused": False, "maintenance_mode": False},
            "dispatch_safe": True,
            "dispatch_blockers": [],
            "active_items": [{"project_id": "running"}],
            "next_candidate": None,
            "conflicts": [],
        }
        code, output, calls = self._run_main(status=status)
        paths = [path for _base_url, path, _token, _payload in calls]
        self.assertEqual(code, 0)
        self.assertNotIn("/control/api/v1/followups/launch-next", paths)
        self.assertNotIn("/control/dispatch-next", paths)
        self.assertEqual(
            output["followup_launch"]["reason"], "active worker lane present"
        )
        self.assertEqual(output["dispatch"]["reason"], "active worker lane present")

    def test_queue_pump_dispatches_open_lane_candidate_while_other_lane_active(
        self,
    ) -> None:
        status = {
            "flags": {"queue_paused": False, "maintenance_mode": False},
            "dispatch_safe": True,
            "dispatch_blockers": [],
            "active_items": [{"project_id": "running-gpu", "machine_target": "gb10"}],
            "next_candidate": {
                "project_id": "queued-cpu",
                "machine_target": "cpu-proxmox-1",
            },
            "conflicts": [],
        }
        code, output, calls = self._run_main(status=status)
        paths = [path for _base_url, path, _token, _payload in calls]
        self.assertEqual(code, 0)
        self.assertNotIn("/control/api/v1/followups/launch-next", paths)
        self.assertIn("/control/dispatch-next", paths)
        self.assertEqual(
            output["followup_launch"]["reason"], "queued candidate already present"
        )
        self.assertEqual(output["dispatch"]["action"], "live_dispatch")

    def test_queue_pump_never_sends_config_tokens_to_env_control_url(self) -> None:
        with patch.dict(
            queue_pump.os.environ,
            {"ENOCH_CONTROL_URL": "https://attacker.invalid:9443"},
            clear=False,
        ):
            code, _output, calls = self._run_main()

        self.assertEqual(code, 0)
        self.assertTrue(calls)
        self.assertEqual(
            {base_url for base_url, _path, _token, _payload in calls},
            {"http://127.0.0.1:8787"},
        )
        self.assertEqual({token for _base_url, _path, token, _payload in calls}, {"t"})
        preflight_payloads = [
            payload
            for _base_url, path, _token, payload in calls
            if path == "/control/api/preflight"
        ]
        self.assertEqual(len(preflight_payloads), 1)
        self.assertEqual(preflight_payloads[0].get("bearer_token"), "worker-t")


if __name__ == "__main__":
    unittest.main()
