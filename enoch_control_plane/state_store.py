from __future__ import annotations

import fcntl
import hashlib
import json
from pathlib import Path
import tempfile
import threading

from .models import RunRecord, utc_now

DEFAULT_EVENTS_LOG_MAX_BYTES = 8 * 1024 * 1024
DEFAULT_EVENTS_LOG_BACKUPS = 3


class StateStore:
    def __init__(
        self,
        root: Path,
        *,
        events_log_max_bytes: int = DEFAULT_EVENTS_LOG_MAX_BYTES,
        events_log_backups: int = DEFAULT_EVENTS_LOG_BACKUPS,
    ) -> None:
        self.root = root
        self.runs_dir = self.root / "runs"
        self.corrupt_runs_dir = self.runs_dir / "corrupt"
        self.events_log = self.root / "events.log"
        self.events_lock_file = self.root / "events.log.lock"
        self.events_log_max_bytes = events_log_max_bytes
        self.events_log_backups = events_log_backups
        self._events_lock = threading.Lock()
        self._event_sequence = 0
        self.runs_dir.mkdir(parents=True, exist_ok=True)

    def _safe_run_id(self, run_id: str) -> str:
        raw = str(run_id or "")
        safe = "".join(ch if ch.isalnum() or ch in "._-+" else "_" for ch in raw)
        if safe and safe == raw and len(safe) <= 100:
            return safe
        digest = hashlib.blake2s(raw.encode("utf-8"), digest_size=4).hexdigest()
        return f"{(safe or 'unknown-run')[:80]}-{digest}"

    def run_path(self, run_id: str) -> Path:
        return self.runs_dir / f"{self._safe_run_id(run_id)}.json"

    def _quarantine_corrupt_run_file(self, path: Path) -> None:
        self.corrupt_runs_dir.mkdir(parents=True, exist_ok=True)
        target = self.corrupt_runs_dir / f"{path.name}.corrupt"
        suffix = 1
        while target.exists():
            target = self.corrupt_runs_dir / f"{path.name}.{suffix}.corrupt"
            suffix += 1
        try:
            path.replace(target)
        except FileNotFoundError:
            return

    def load_run(self, run_id: str) -> RunRecord | None:
        path = self.run_path(run_id)
        if not path.exists():
            return None
        try:
            return RunRecord.model_validate_json(path.read_text())
        except Exception:
            self._quarantine_corrupt_run_file(path)
            return None

    def save_run(self, record: RunRecord) -> None:
        path = self.run_path(record.run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, delete=False
        ) as handle:
            handle.write(record.model_dump_json(indent=2, exclude_none=False))
            handle.write("\n")
            tmp = Path(handle.name)
        tmp.replace(path)

    def list_runs(self) -> list[RunRecord]:
        records: list[RunRecord] = []
        for path in sorted(self.runs_dir.glob("*.json")):
            try:
                records.append(RunRecord.model_validate_json(path.read_text()))
            except Exception:
                self._quarantine_corrupt_run_file(path)
                continue
        return records

    def _next_event_sequence(self) -> int:
        self._event_sequence += 1
        return self._event_sequence

    def _event_log_backup_path(self, index: int) -> Path:
        return self.events_log.with_name(f"{self.events_log.name}.{index}")

    def _rotate_events_log_if_needed(self, incoming_bytes: int) -> None:
        if self.events_log_max_bytes <= 0 or not self.events_log.exists():
            return
        if self.events_log.stat().st_size + incoming_bytes <= self.events_log_max_bytes:
            return
        if self.events_log_backups <= 0:
            self.events_log.unlink(missing_ok=True)
            return
        last_backup = self._event_log_backup_path(self.events_log_backups)
        last_backup.unlink(missing_ok=True)
        for index in range(self.events_log_backups - 1, 0, -1):
            source = self._event_log_backup_path(index)
            if source.exists():
                source.replace(self._event_log_backup_path(index + 1))
        self.events_log.replace(self._event_log_backup_path(1))

    def append_event(self, payload: dict) -> None:
        with self._events_lock:
            event = dict(payload)
            event.setdefault("appended_at", utc_now())
            event.setdefault("event_sequence", self._next_event_sequence())
            line = json.dumps(event, sort_keys=True) + "\n"
            incoming_bytes = len(line.encode("utf-8"))
            with self.events_lock_file.open("a", encoding="utf-8") as lock_handle:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
                try:
                    self._rotate_events_log_if_needed(incoming_bytes)
                    with self.events_log.open("a", encoding="utf-8") as handle:
                        handle.write(line)
                        handle.flush()
                finally:
                    fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
