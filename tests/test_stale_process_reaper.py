from __future__ import annotations

from datetime import datetime, timedelta, timezone
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from pathlib import Path

from enoch_control_plane.config import GateConfig
from enoch_control_plane.gate import WakeGate
from enoch_control_plane.models import (
    GateState,
    ProcessInfo,
    RunRecord,
    TelemetrySample,
)
from enoch_control_plane.process_tracker import ProcessTracker, _safe_send_signal


class _StaticTelemetry:
    def sample(self) -> TelemetrySample:
        return TelemetrySample(
            cpu_pct=0.0,
            gpu_pct=0.0,
            memory_source="uma_meminfo",
            uma_allocatable_mib=100_000,
        )


class StaleProcessReaperTests(unittest.TestCase):
    def _terminate_process(self, proc: subprocess.Popen[bytes]) -> None:
        if proc.poll() is not None:
            return
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)

    def _config(self, project_root: str) -> GateConfig:
        return GateConfig(
            state_dir="/tmp/enoch-worker-gate-test",
            project_root=project_root,
            dispatch_script_path="/tmp/enoch-worker-gate-test/dispatch.sh",
            control_api_bearer_token="secret",
            completion_callback_url="https://callback.example.com/callback",
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
            self.addCleanup(self._terminate_process, proc)
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
                proc.wait(timeout=5)
            finally:
                self._terminate_process(proc)

    def test_reaper_does_not_kill_when_codex_root_is_alive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "project-a"
            project_dir.mkdir()
            proc = subprocess.Popen(
                [sys.executable, "-c", "import time; time.sleep(120)"],
                cwd=project_dir,
            )
            self.addCleanup(self._terminate_process, proc)
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
                self._terminate_process(proc)

    def test_reaper_does_not_kill_without_root_pid_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "project-a"
            project_dir.mkdir()
            proc = subprocess.Popen(
                [sys.executable, "-c", "import time; time.sleep(120)"],
                cwd=project_dir,
            )
            self.addCleanup(self._terminate_process, proc)
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
                self._terminate_process(proc)

    def test_tracker_rejects_project_dir_escape_outside_project_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "projects"
            root.mkdir()
            outside = Path(tmp) / "outside"
            outside.mkdir()
            tracker = ProcessTracker(root)

            self.assertIsNone(
                tracker._project_dir(
                    RunRecord(
                        run_id="run-relative-escape",
                        session_id="session-relative-escape",
                        project_id="project-a",
                        project_dir="../outside",
                    )
                )
            )
            self.assertIsNone(
                tracker._project_dir(
                    RunRecord(
                        run_id="run-absolute-escape",
                        session_id="session-absolute-escape",
                        project_id="project-a",
                        project_dir=str(outside),
                    )
                )
            )

    def test_reaper_returns_only_successfully_signaled_processes(self) -> None:
        class _LiveProcess:
            def create_time(self) -> float:
                return 1000.0

        tracker = ProcessTracker(Path("/tmp"))
        record = RunRecord(run_id="run", session_id="session", root_pid=999_999_999)
        candidate = ProcessInfo(
            pid=123456, elapsed_sec=999, create_time=1000.0, cmdline="python smoke.py"
        )
        with (
            patch.object(tracker, "stale_reap_candidates", return_value=[candidate]),
            patch(
                "enoch_control_plane.process_tracker.os.kill",
                side_effect=PermissionError,
            ),
            patch(
                "enoch_control_plane.process_tracker.psutil.Process",
                return_value=_LiveProcess(),
            ),
        ):
            self.assertEqual(
                tracker.reap_stale_project_processes(
                    record,
                    stale_after_sec=0,
                    command_markers=["python"],
                    term_grace_sec=0,
                ),
                [],
            )

    def test_reaper_ignores_candidate_that_exits_before_initial_term(self) -> None:
        import psutil

        tracker = ProcessTracker(Path("/tmp"))
        record = RunRecord(run_id="run", session_id="session", root_pid=999_999_999)
        candidate = ProcessInfo(
            pid=123456, elapsed_sec=999, create_time=1000.0, cmdline="python smoke.py"
        )

        with (
            patch.object(tracker, "stale_reap_candidates", return_value=[candidate]),
            patch("enoch_control_plane.process_tracker.os.kill") as kill_mock,
            patch(
                "enoch_control_plane.process_tracker.psutil.Process",
                side_effect=psutil.NoSuchProcess(123456),
            ),
        ):
            self.assertEqual(
                tracker.reap_stale_project_processes(
                    record,
                    stale_after_sec=0,
                    command_markers=["python"],
                    term_grace_sec=0,
                ),
                [],
            )
            kill_mock.assert_not_called()

    def test_safe_send_signal_refuses_unanchored_pid(self) -> None:
        with patch("enoch_control_plane.process_tracker.os.kill") as kill_mock:
            with self.assertRaises(ProcessLookupError):
                _safe_send_signal(123456, signal.SIGTERM)
            kill_mock.assert_not_called()

    def test_reaper_does_not_sigkill_reused_pid(self) -> None:
        class _ReusedProcess:
            pid = 123456

            def create_time(self) -> float:
                return 2000.0

            def is_running(self) -> bool:
                return True

            def status(self) -> str:
                return "running"

        tracker = ProcessTracker(Path("/tmp"))
        record = RunRecord(run_id="run", session_id="session", root_pid=999_999_999)
        candidate = ProcessInfo(
            pid=123456, elapsed_sec=999, create_time=1000.0, cmdline="python smoke.py"
        )
        signaled: list[tuple[int, int]] = []

        def _kill(pid: int, sig: int) -> None:
            signaled.append((pid, sig))

        with (
            patch.object(tracker, "stale_reap_candidates", return_value=[candidate]),
            patch("enoch_control_plane.process_tracker.os.kill", side_effect=_kill),
            patch(
                "enoch_control_plane.process_tracker.psutil.Process",
                return_value=_ReusedProcess(),
            ),
        ):
            self.assertEqual(
                tracker.reap_stale_project_processes(
                    record,
                    stale_after_sec=0,
                    command_markers=["python"],
                    term_grace_sec=0,
                ),
                [],
            )

        # Reused PID must not be signaled at TERM or SIGKILL.
        self.assertEqual(signaled, [])

    def test_reaper_audits_process_that_exits_during_identity_check(self) -> None:
        class _LiveProcess:
            def create_time(self) -> float:
                return 1000.0

        class _GoneProcess:
            pid = 123456

            def create_time(self) -> float:
                import psutil

                raise psutil.NoSuchProcess(123456)

        tracker = ProcessTracker(Path("/tmp"))
        record = RunRecord(run_id="run", session_id="session", root_pid=999_999_999)
        candidate = ProcessInfo(
            pid=123456, elapsed_sec=999, create_time=1000.0, cmdline="python smoke.py"
        )

        with (
            patch.object(tracker, "stale_reap_candidates", return_value=[candidate]),
            patch("enoch_control_plane.process_tracker.os.kill"),
            patch(
                "enoch_control_plane.process_tracker.psutil.Process",
                side_effect=[_LiveProcess(), _GoneProcess()],
            ),
        ):
            self.assertEqual(
                tracker.reap_stale_project_processes(
                    record,
                    stale_after_sec=0,
                    command_markers=["python"],
                    term_grace_sec=0,
                ),
                [candidate],
            )

    def test_reaper_audits_process_that_exits_before_sigkill(self) -> None:
        class _OriginalProcess:
            pid = 123456

            def create_time(self) -> float:
                return 1000.0

            def is_running(self) -> bool:
                return True

            def status(self) -> str:
                return "running"

        tracker = ProcessTracker(Path("/tmp"))
        record = RunRecord(run_id="run", session_id="session", root_pid=999_999_999)
        candidate = ProcessInfo(
            pid=123456, elapsed_sec=999, create_time=1000.0, cmdline="python smoke.py"
        )
        calls: list[int] = []

        def _kill(pid: int, sig: int) -> None:
            calls.append(sig)
            if len(calls) == 2:
                raise ProcessLookupError

        with (
            patch.object(tracker, "stale_reap_candidates", return_value=[candidate]),
            patch("enoch_control_plane.process_tracker.os.kill", side_effect=_kill),
            patch(
                "enoch_control_plane.process_tracker.psutil.Process",
                return_value=_OriginalProcess(),
            ),
        ):
            self.assertEqual(
                tracker.reap_stale_project_processes(
                    record,
                    stale_after_sec=0,
                    command_markers=["python"],
                    term_grace_sec=0,
                ),
                [candidate],
            )
            self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()
