from __future__ import annotations

import os
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
            try:
                if not proc.is_running() or proc.status() == psutil.STATUS_ZOMBIE:
                    continue
                cmdline_parts = proc.cmdline()
                cmdline = " ".join(cmdline_parts).strip() or proc.name()
                try:
                    pgid = os.getpgid(proc.pid)
                except (ProcessLookupError, PermissionError):
                    pgid = None
                described.append(
                    ProcessInfo(
                        pid=proc.pid,
                        ppid=proc.ppid(),
                        pgid=pgid,
                        elapsed_sec=int(max(0, time.time() - proc.create_time())),
                        cmdline=cmdline,
                    )
                )
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return described
