from __future__ import annotations

import json
from pathlib import Path

from .models import RunRecord


class StateStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.runs_dir = self.root / "runs"
        self.events_log = self.root / "events.log"
        self.runs_dir.mkdir(parents=True, exist_ok=True)

    def run_path(self, run_id: str) -> Path:
        return self.runs_dir / f"{run_id}.json"

    def load_run(self, run_id: str) -> RunRecord | None:
        path = self.run_path(run_id)
        if not path.exists():
            return None
        return RunRecord.model_validate_json(path.read_text())

    def save_run(self, record: RunRecord) -> None:
        self.run_path(record.run_id).write_text(
            record.model_dump_json(indent=2, exclude_none=False)
        )

    def list_runs(self) -> list[RunRecord]:
        records: list[RunRecord] = []
        for path in sorted(self.runs_dir.glob("*.json")):
            try:
                records.append(RunRecord.model_validate_json(path.read_text()))
            except Exception:
                continue
        return records

    def append_event(self, payload: dict) -> None:
        with self.events_log.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")
