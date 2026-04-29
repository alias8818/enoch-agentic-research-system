from __future__ import annotations

from datetime import datetime, timedelta, timezone
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from omx_wake_gate.config import GateConfig
from omx_wake_gate.gate import WakeGate
from omx_wake_gate.models import GateState, RunRecord, TelemetrySample
from omx_wake_gate.process_tracker import ProcessTracker


class _StaticTelemetry:
    def sample(self) -> TelemetrySample:
        return TelemetrySample(cpu_pct=0.0, gpu_pct=0.0, memory_source="uma_meminfo", uma_allocatable_mib=100_000)


class StaleProcessReaperTests(unittest.TestCase):
    def _config(self, project_root: str) -> GateConfig:
        return GateConfig(
            state_dir="/tmp/omx-wake-gate-test",
            project_root=project_root,
            dispatch_script_path="/tmp/omx-wake-gate-test/dispatch.sh",
            omx_inbound_bearer_token="secret",
            completion_callback_url="http://127.0.0.1/callback",
            completion_callback_token="callback-token",
            stale_project_process_grace_sec=0,
            stale_project_process_term_grace_sec=0.0,
            stale_project_process_command_markers=["python"],
        )

    def test_reaper_kills_stale_project_process_after_root_exits(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "project-a"
            project_dir.mkdir()
            proc = subprocess.Popen(
                [sys.executable, "-c", "import time; time.sleep(120)"],
                cwd=project_dir,
            )
            self.addCleanup(lambda: proc.poll() is None and proc.kill())
            try:
                tracker = ProcessTracker(Path(tmp))
                gate = WakeGate(self._config(tmp), tracker, _StaticTelemetry())
                old = (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat()
                record = RunRecord(
                    run_id="run-stale",
                    session_id="session-stale",
                    project_id="project-a",
                    project_dir=str(project_dir),
                    gate_state=GateState.WAITING_FOR_PROCESS_EXIT,
                    root_pid=999_999_999,
                    process_group_id=999_999_999,
                    idle_seen_at=old,
                    last_event_at=old,
                )

                reaped = gate.reap_stale_project_processes(record)

                self.assertEqual([item["pid"] for item in reaped], [proc.pid])
                for _ in range(20):
                    if proc.poll() is not None:
                        break
                    time.sleep(0.05)
                self.assertIsNotNone(proc.poll())
            finally:
                if proc.poll() is None:
                    proc.kill()

    def test_reaper_does_not_kill_when_codex_root_is_alive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "project-a"
            project_dir.mkdir()
            proc = subprocess.Popen(
                [sys.executable, "-c", "import time; time.sleep(120)"],
                cwd=project_dir,
            )
            self.addCleanup(lambda: proc.poll() is None and proc.kill())
            try:
                tracker = ProcessTracker(Path(tmp))
                gate = WakeGate(self._config(tmp), tracker, _StaticTelemetry())
                old = (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat()
                record = RunRecord(
                    run_id="run-active-root",
                    session_id="session-active-root",
                    project_id="project-a",
                    project_dir=str(project_dir),
                    gate_state=GateState.WAITING_FOR_PROCESS_EXIT,
                    root_pid=proc.pid,
                    process_group_id=proc.pid,
                    idle_seen_at=old,
                    last_event_at=old,
                )

                reaped = gate.reap_stale_project_processes(record)

                self.assertEqual(reaped, [])
                self.assertIsNone(proc.poll())
            finally:
                if proc.poll() is None:
                    proc.kill()

    def test_reaper_does_not_kill_without_root_pid_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "project-a"
            project_dir.mkdir()
            proc = subprocess.Popen(
                [sys.executable, "-c", "import time; time.sleep(120)"],
                cwd=project_dir,
            )
            self.addCleanup(lambda: proc.poll() is None and proc.kill())
            try:
                tracker = ProcessTracker(Path(tmp))
                gate = WakeGate(self._config(tmp), tracker, _StaticTelemetry())
                old = (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat()
                record = RunRecord(
                    run_id="run-no-root",
                    session_id="session-no-root",
                    project_id="project-a",
                    project_dir=str(project_dir),
                    gate_state=GateState.WAITING_FOR_PROCESS_EXIT,
                    root_pid=None,
                    process_group_id=None,
                    idle_seen_at=old,
                    last_event_at=old,
                )

                reaped = gate.reap_stale_project_processes(record)

                self.assertEqual(reaped, [])
                self.assertIsNone(proc.poll())
            finally:
                if proc.poll() is None:
                    proc.kill()


if __name__ == "__main__":
    unittest.main()
