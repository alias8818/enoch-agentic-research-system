from __future__ import annotations

import importlib.util
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch
import unittest

MODULE_PATH = Path(__file__).resolve().parents[1] / "deploy" / "enoch_queue_alert_check.py"
spec = importlib.util.spec_from_file_location("enoch_queue_alert_check", MODULE_PATH)
queue_pump = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(queue_pump)


class QueuePumpTests(unittest.TestCase):
    def _run_main(self, *, status: dict | None = None) -> tuple[int, dict, list[str]]:
        calls: list[str] = []
        status = status or {
            "flags": {"queue_paused": False, "maintenance_mode": False},
            "dispatch_safe": True,
            "dispatch_blockers": [],
            "active_items": [],
            "next_candidate": {"project_id": "queued-idea"},
            "conflicts": [],
        }

        def fake_post(base_url: str, path: str, token: str, payload: dict) -> dict:
            calls.append(path)
            if path == "/control/api/preflight":
                return {"ok": True, "target": "http://worker.example:8787", "summary": "worker preflight passed", "checks": [{"name": "wake_gate_dashboard_api", "ok": True, "data": {"body": {"rows": ["x" * 1000]}}}]}
            if path == "/control/api/alerts/queue-check":
                return {"should_alert": False, "sent": False, "alerts_enabled": True}
            if path == "/control/dispatch-next":
                return {"action": "live_dispatch", "candidate": {"project_id": "queued-idea"}}
            raise AssertionError(path)

        with patch.object(queue_pump, "_load_config", return_value={"listen_host": "127.0.0.1", "listen_port": 8787, "omx_inbound_bearer_token": "t", "queue_pump_enabled": True}), \
             patch.object(queue_pump, "_post_json", side_effect=fake_post), \
             patch.object(queue_pump, "_get_json", return_value=status):
            out = io.StringIO()
            with redirect_stdout(out):
                code = queue_pump.main()
        return code, json.loads(out.getvalue()), calls

    def test_queue_pump_dispatches_when_safe_and_candidate_exists(self) -> None:
        code, output, calls = self._run_main()
        self.assertEqual(code, 0)
        self.assertNotIn("/control/papers/draft-next", calls)
        self.assertIn("/control/dispatch-next", calls)
        self.assertEqual(output["dispatch"]["action"], "live_dispatch")
        self.assertEqual(output["preflight"]["check_count"], 1)
        self.assertNotIn("checks", output["preflight"])
        self.assertLess(len(json.dumps(output)), 1000)

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
        self.assertEqual(code, 0)
        self.assertNotIn("/control/papers/draft-next", calls)
        self.assertNotIn("/control/dispatch-next", calls)
        self.assertEqual(output["dispatch"]["reason"], "no queued candidate")


if __name__ == "__main__":
    unittest.main()
