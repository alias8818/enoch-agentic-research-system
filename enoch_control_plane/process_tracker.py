from __future__ import annotations

import os
import signal
import time
from pathlib import Path

try:
    import psutil
except ImportError:  # pragma: no cover - dependency may not be installed yet
    psutil = None

from .models import ProcessInfo, ProcessSnapshot, RunRecord


def _is_benign_project_process(cmdline: str) -> bool:
    normalized = cmdline.strip()
    if not normalized:
        return True
    if normalized in {"-bash", "bash", "-sh", "sh", "-zsh", "zsh", "fish", "-fish"}:
        return True
    if normalized == "jq":
        return True
    if normalized.startswith("tail -f "):
        return True
    return False


class ProcessTracker:
    """Track whether a run still owns any live local processes."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root.expanduser().resolve()

    def _project_dir(self, record: RunRecord) -> Path | None:
        raw = (record.project_dir or '').strip()
        if raw:
            try:
                return Path(raw).expanduser().resolve()
            except OSError:
                return None
        if record.project_id:
            try:
                return (self.project_root / record.project_id).resolve()
            except OSError:
                return None
        return None

    def _process_in_project_dir(self, proc: object, project_dir: Path) -> bool:
        try:
            cwd = Path(proc.cwd()).resolve()
        except (FileNotFoundError, PermissionError, psutil.NoSuchProcess, psutil.AccessDenied):
            return False
        try:
            cwd.relative_to(project_dir)
            return True
        except ValueError:
            return False

    def _project_owned_processes(self, record: RunRecord) -> dict[int, object]:
        if psutil is None:
            return {}

        project_dir = self._project_dir(record)
        if project_dir is None or not project_dir.exists():
            return {}

        owned: dict[int, object] = {}
        for proc in psutil.process_iter(['pid']):
            try:
                if self._process_in_project_dir(proc, project_dir):
                    owned[proc.pid] = proc
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return owned

    def _tracked_processes(self, record: RunRecord) -> dict[int, object]:
        if psutil is None:
            return {}

        tracked: dict[int, object] = {}
        if record.root_pid is not None:
            try:
                root = psutil.Process(record.root_pid)
                tracked[root.pid] = root
                for child in root.children(recursive=True):
                    tracked[child.pid] = child
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        if record.process_group_id is not None:
            for proc in psutil.process_iter(["pid"]):
                try:
                    if os.getpgid(proc.pid) == record.process_group_id:
                        tracked[proc.pid] = proc
                except (ProcessLookupError, PermissionError, psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

        tracked.update(self._project_owned_processes(record))
        return tracked

    def _root_exited(self, record: RunRecord) -> bool:
        if psutil is None or record.root_pid is None:
            return False
        try:
            root = psutil.Process(record.root_pid)
            return not (root.is_running() and root.status() != psutil.STATUS_ZOMBIE)
        except psutil.NoSuchProcess:
            return True
        except psutil.AccessDenied:
            # Lack of access is not proof that the root is gone. Keep the gate
            # conservative and do not reap project processes in this case.
            return False

    @staticmethod
    def _process_info(proc: object) -> ProcessInfo | None:
        try:
            if not proc.is_running() or proc.status() == psutil.STATUS_ZOMBIE:
                return None
            cmdline_parts = proc.cmdline()
            cmdline = " ".join(cmdline_parts).strip() or proc.name()
            try:
                pgid = os.getpgid(proc.pid)
            except (ProcessLookupError, PermissionError):
                pgid = None
            create_time = proc.create_time()
            return ProcessInfo(
                pid=proc.pid,
                ppid=proc.ppid(),
                pgid=pgid,
                elapsed_sec=int(max(0, time.time() - create_time)),
                create_time=create_time,
                cmdline=cmdline,
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return None

    def snapshot(self, record: RunRecord, gpu_compute_pids: list[int] | None = None) -> ProcessSnapshot:
        if psutil is None:
            return ProcessSnapshot(
                tracked=record.root_pid is not None,
                root_pid=record.root_pid,
                process_alive=False,
                descendants_alive=False,
                gpu_processes_alive=False,
                project_cwd_processes_alive=False,
            )

        tracked = self._tracked_processes(record)
        process_alive = False
        descendants_alive = False
        project_cwd_processes_alive = False
        alive_pids: set[int] = set()
        project_dir = self._project_dir(record)

        for pid, proc in tracked.items():
            try:
                if proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE:
                    alive_pids.add(pid)
                    if pid == record.root_pid:
                        process_alive = True
                    else:
                        descendants_alive = True
                    if project_dir is not None and self._process_in_project_dir(proc, project_dir):
                        cmdline = " ".join(proc.cmdline()).strip() or proc.name()
                        if not _is_benign_project_process(cmdline):
                            project_cwd_processes_alive = True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        gpu_processes_alive = any(pid in alive_pids for pid in (gpu_compute_pids or []))

        return ProcessSnapshot(
            tracked=record.root_pid is not None,
            root_pid=record.root_pid,
            process_alive=process_alive,
            descendants_alive=descendants_alive,
            gpu_processes_alive=gpu_processes_alive,
            project_cwd_processes_alive=project_cwd_processes_alive,
        )

    def describe_processes(self, record: RunRecord) -> list[ProcessInfo]:
        if psutil is None:
            return []

        described: list[ProcessInfo] = []
        for pid, proc in sorted(self._tracked_processes(record).items()):
            info = self._process_info(proc)
            if info is not None:
                described.append(info)
        return described

    def stale_reap_candidates(
        self,
        record: RunRecord,
        *,
        gpu_compute_pids: list[int] | None = None,
        stale_after_sec: int,
        command_markers: list[str],
    ) -> list[ProcessInfo]:
        """Return project-owned processes safe to reap after the Codex root exited.

        The wake gate intentionally treats any process with cwd under the project
        as live work so background benchmarks cannot be orphaned. That safety net
        can wedge the queue when a bounded smoke command (for example
        ``timeout 45s llama-cli ...``) survives after the Codex session has gone
        idle/dead. Reaping is intentionally narrow: the root process must be
        gone, the process must live under the project directory, it must be older
        than the configured grace window, and it must either appear in GPU
        compute telemetry or match an explicit stale-command marker.
        """
        if psutil is None or not self._root_exited(record):
            return []

        project_dir = self._project_dir(record)
        if project_dir is None or not project_dir.exists():
            return []

        markers = [marker.lower() for marker in command_markers if marker.strip()]
        gpu_pids = set(gpu_compute_pids or [])
        candidates: list[ProcessInfo] = []
        for pid, proc in sorted(self._project_owned_processes(record).items()):
            if pid == record.root_pid:
                continue
            info = self._process_info(proc)
            if info is None:
                continue
            if _is_benign_project_process(info.cmdline):
                continue
            if (info.elapsed_sec or 0) < stale_after_sec:
                continue
            cmd = info.cmdline.lower()
            marker_match = any(marker in cmd for marker in markers)
            gpu_match = pid in gpu_pids
            if marker_match or gpu_match:
                candidates.append(info)
        return candidates

    @staticmethod
    def _same_process(proc: object, info: ProcessInfo) -> bool | None:
        if info.create_time is None:
            return False
        try:
            return abs(proc.create_time() - info.create_time) < 0.01
        except psutil.NoSuchProcess:
            return None
        except psutil.AccessDenied:
            return False

    def reap_stale_project_processes(
        self,
        record: RunRecord,
        *,
        gpu_compute_pids: list[int] | None = None,
        stale_after_sec: int,
        command_markers: list[str],
        term_grace_sec: float = 5.0,
    ) -> list[ProcessInfo]:
        candidates = self.stale_reap_candidates(
            record,
            gpu_compute_pids=gpu_compute_pids,
            stale_after_sec=stale_after_sec,
            command_markers=command_markers,
        )
        if not candidates:
            return []

        term_signaled: list[ProcessInfo] = []
        for info in candidates:
            try:
                os.kill(info.pid, signal.SIGTERM)
                term_signaled.append(info)
            except (ProcessLookupError, PermissionError):
                continue

        if term_grace_sec > 0:
            time.sleep(term_grace_sec)

        reaped: list[ProcessInfo] = []
        for info in term_signaled:
            try:
                proc = psutil.Process(info.pid) if psutil is not None else None
                if proc is None:
                    continue
                same_process = self._same_process(proc, info)
                if same_process is None:
                    reaped.append(info)
                    continue
                if not same_process:
                    # PID was reused during the TERM grace window. Never signal
                    # the new occupant.
                    continue
                if not proc.is_running() or proc.status() == psutil.STATUS_ZOMBIE:
                    reaped.append(info)
                    continue
                os.kill(info.pid, signal.SIGKILL)
                reaped.append(info)
            except (psutil.NoSuchProcess, ProcessLookupError):
                reaped.append(info)
            except (PermissionError, psutil.AccessDenied):
                continue
        return reaped
