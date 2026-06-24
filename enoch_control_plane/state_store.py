from __future__ import annotations

import fcntl
import hashlib
import json
from pathlib import Path
import tempfile
import threading

from .models import RunRecord


class StateStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.runs_dir = self.root / "runs"
        self.corrupt_runs_dir = self.runs_dir / "corrupt"
        self.events_log = self.root / "events.log"
        self._events_lock = threading.Lock()
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

    def append_event(self, payload: dict) -> None:
        line = json.dumps(payload, sort_keys=True) + "\n"
        with self._events_lock:
            with self.events_log.open("a", encoding="utf-8") as handle:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                try:
                    handle.write(line)
                    handle.flush()
                finally:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
