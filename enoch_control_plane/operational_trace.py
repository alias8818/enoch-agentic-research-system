from __future__ import annotations

from collections.abc import Mapping
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import uuid
from typing import Any

from .models import utc_now

_SENSITIVE_KEY = re.compile(
    r"token|bearer|password|secret|api[_-]?key|authorization|credential",
    re.IGNORECASE,
)
_MAX_DEFAULT_PAYLOAD_BYTES = 16_384
_MIN_PAYLOAD_BYTES = 1024
_MAX_TRACE_FILE_BYTES = 5_000_000


def _redact_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): "[REDACTED]"
            if _SENSITIVE_KEY.search(str(key))
            else _redact_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    if isinstance(value, tuple):
        return [_redact_value(item) for item in value]
    return value


def _json_size(value: Mapping[str, Any]) -> int:
    return len(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def _bounded(
    value: Any, *, max_string: int = 512, max_list: int = 20, depth: int = 0
) -> Any:
    if depth > 6:
        return {"truncated": True, "reason": "max_depth"}
    if isinstance(value, str):
        raw = value.encode("utf-8")
        if len(raw) <= max_string:
            return value
        return {
            "truncated": True,
            "bytes": len(raw),
            "prefix": value[: max(0, max_string // 2)],
        }
    if isinstance(value, Mapping):
        return {
            str(key): _bounded(
                item, max_string=max_string, max_list=max_list, depth=depth + 1
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        items = value[:max_list]
        out = [
            _bounded(item, max_string=max_string, max_list=max_list, depth=depth + 1)
            for item in items
        ]
        if len(value) > max_list:
            out.append({"truncated": True, "omitted": len(value) - max_list})
        return out
    if isinstance(value, tuple):
        return _bounded(
            list(value), max_string=max_string, max_list=max_list, depth=depth
        )
    return value


def _fit_record(record: dict[str, Any], max_payload_bytes: int) -> dict[str, Any]:
    if _json_size(record) <= max_payload_bytes:
        return record
    bounded = _bounded(record)
    if isinstance(bounded, dict) and _json_size(bounded) <= max_payload_bytes:
        bounded["payload_truncated"] = True
        return bounded
    minimal = {
        "observed_at": record.get("observed_at"),
        "event": record.get("event"),
        "trace_id": record.get("trace_id"),
        "run_cycle_id": record.get("run_cycle_id"),
        "requested_by": record.get("requested_by"),
        "project_id": record.get("project_id"),
        "run_id": record.get("run_id"),
        "machine_target": record.get("machine_target"),
        "lane_key": record.get("lane_key"),
        "payload_truncated": True,
        "original_payload_bytes": _json_size(record),
    }
    return {key: value for key, value in minimal.items() if value not in (None, "")}


class OperatorTrace:
    """Append-only structured operator decision trace.

    This is an audit/diagnostic flight recorder, not an application log sink.
    It is intentionally best-effort: tracing failures must never affect queue,
    dispatch, or publication state transitions.
    """

    def __init__(
        self,
        *,
        enabled: bool,
        path: str | Path | None,
        max_payload_bytes: int = _MAX_DEFAULT_PAYLOAD_BYTES,
    ) -> None:
        self.enabled = bool(enabled)
        self.path = Path(path).expanduser() if path else None
        self.max_payload_bytes = max(
            _MIN_PAYLOAD_BYTES, int(max_payload_bytes or _MAX_DEFAULT_PAYLOAD_BYTES)
        )
        if self.enabled and self.path is not None:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
            except OSError:
                self.enabled = False

    @classmethod
    def from_config(cls, config: Any) -> "OperatorTrace":
        enabled = bool(getattr(config, "operational_trace_enabled", False))
        configured_path = str(
            getattr(config, "operational_trace_log_path", "") or ""
        ).strip()
        path = configured_path or (
            Path(str(getattr(config, "state_dir", "."))).expanduser()
            / "operator_trace.jsonl"
        )
        return cls(
            enabled=enabled,
            path=path,
            max_payload_bytes=int(
                getattr(
                    config,
                    "operational_trace_max_payload_bytes",
                    _MAX_DEFAULT_PAYLOAD_BYTES,
                )
                or _MAX_DEFAULT_PAYLOAD_BYTES
            ),
        )

    @staticmethod
    def new_trace_id(prefix: str = "trace") -> str:
        return f"{prefix}-{uuid.uuid4().hex[:16]}"

    def record(self, event: str, **fields: Any) -> None:
        if not self.enabled or self.path is None:
            return
        record = {
            "observed_at": utc_now(),
            "event": event,
            **{key: value for key, value in fields.items() if value not in (None, "")},
        }
        safe_record = _fit_record(_redact_value(record), self.max_payload_bytes)
        try:
            with self._exclusive_writer_lock():
                self._rotate_if_needed()
                with self.path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(safe_record, sort_keys=True) + "\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                self._fsync_parent_dir()
        except OSError:
            return

    @contextmanager
    def _exclusive_writer_lock(self):
        if self.path is None:
            yield
            return
        lock_path = self.path.with_name(self.path.name + ".lock")
        try:
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            lock_fd = os.open(lock_path, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
            os.fchmod(lock_fd, 0o600)
            lock_handle = os.fdopen(lock_fd, "a", encoding="utf-8")
        except OSError:
            yield
            return
        with lock_handle:
            try:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                raise
            try:
                yield
            finally:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)

    def _fsync_parent_dir(self) -> None:
        if self.path is None:
            return
        try:
            dir_fd = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
        except OSError:
            return
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)

    def _rotate_if_needed(self) -> None:
        if self.path is None or not self.path.exists():
            return
        if self.path.stat().st_size < _MAX_TRACE_FILE_BYTES:
            return
        rotated = self.path.with_suffix(self.path.suffix + ".1")
        try:
            if rotated.exists():
                rotated.unlink()
            self.path.rename(rotated)
            self._fsync_parent_dir()
        except OSError:
            return


def summarize_lane_snapshot(lanes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for lane in lanes:
        if not isinstance(lane, dict):
            continue
        active = (
            lane.get("active_item") if isinstance(lane.get("active_item"), dict) else {}
        )
        candidate = (
            lane.get("next_candidate")
            if isinstance(lane.get("next_candidate"), dict)
            else {}
        )
        feed = (
            lane.get("feed_pressure")
            if isinstance(lane.get("feed_pressure"), dict)
            else lane.get("feed")
        )
        if not isinstance(feed, dict):
            feed = {}
        out.append(
            {
                "lane_key": lane.get("lane_key"),
                "machine_target": lane.get("machine_target"),
                "worker_role": lane.get("worker_role"),
                "status": lane.get("status"),
                "active_count": lane.get("active_count"),
                "queued_count": lane.get("queued_count"),
                "dispatch_available": lane.get("dispatch_available"),
                "dispatch_blocker": lane.get("dispatch_blocker"),
                "active_project_id": active.get("project_id"),
                "active_run_id": active.get("current_run_id"),
                "next_project_id": candidate.get("project_id"),
                "feed_action": feed.get("next_autopilot_action"),
                "queue_deficit": feed.get("queue_deficit"),
            }
        )
    return out


def count_by_key(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = str(row.get(key) or "")
        counts[value] = counts.get(value, 0) + 1
    return counts
