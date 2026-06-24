from __future__ import annotations

import signal
from pathlib import Path
from types import SimpleNamespace

import pytest
from hypothesis import given, settings, strategies as st

from enoch_control_plane.models import ProcessInfo
from enoch_control_plane.process_tracker import ProcessTracker


class _ProcStub:
    def __init__(
        self, *, create_time: float, running: bool = True, status: str = "running"
    ) -> None:
        self._create_time = create_time
        self._running = running
        self._status = status

    def create_time(self) -> float:
        return self._create_time

    def is_running(self) -> bool:
        return self._running

    def status(self) -> str:
        return self._status


def _tracked_info(*, pid: int = 1234, create_time: float = 100.0) -> ProcessInfo:
    return ProcessInfo(pid=pid, create_time=create_time, cmdline="python smoke.py")


def test_finalize_stale_reap_sends_kill_only_to_same_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tracker = ProcessTracker(Path("/tmp"))
    info = _tracked_info(create_time=100.0)
    signals: list[tuple[int, int]] = []

    def process_for_pid(pid: int) -> _ProcStub:
        return _ProcStub(create_time=100.0)

    def record_signal(pid: int, sig: int) -> None:
        signals.append((pid, sig))

    monkeypatch.setattr(
        "enoch_control_plane.process_tracker.psutil.Process", process_for_pid
    )
    monkeypatch.setattr("enoch_control_plane.process_tracker.os.kill", record_signal)

    assert tracker._finalize_stale_reap(info) == info
    assert signals == [(info.pid, signal.SIGKILL)]


def test_finalize_stale_reap_skips_pid_reused_during_term_grace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tracker = ProcessTracker(Path("/tmp"))
    info = _tracked_info(create_time=100.0)
    signals: list[tuple[int, int]] = []

    def process_for_pid(pid: int) -> _ProcStub:
        return _ProcStub(create_time=200.0)

    def record_signal(pid: int, sig: int) -> None:
        signals.append((pid, sig))

    monkeypatch.setattr(
        "enoch_control_plane.process_tracker.psutil.Process", process_for_pid
    )
    monkeypatch.setattr("enoch_control_plane.process_tracker.os.kill", record_signal)

    assert tracker._finalize_stale_reap(info) is None
    assert signals == []


@given(
    tracked_start=st.floats(
        min_value=1.0,
        max_value=1_000_000.0,
        allow_nan=False,
        allow_infinity=False,
        width=32,
    ),
    delta=st.one_of(
        st.floats(
            min_value=0.011,
            max_value=10_000.0,
            allow_nan=False,
            allow_infinity=False,
        ),
        st.floats(
            min_value=-10_000.0,
            max_value=-0.011,
            allow_nan=False,
            allow_infinity=False,
        ),
    ),
)
@settings(max_examples=80, deadline=None)
def test_finalize_stale_reap_never_signals_reused_pid_property(
    tracked_start: float,
    delta: float,
) -> None:
    tracker = ProcessTracker(Path("/tmp"))
    info = _tracked_info(create_time=tracked_start)
    signals: list[tuple[int, int]] = []

    def process_for_pid(pid: int) -> _ProcStub:
        return _ProcStub(create_time=tracked_start + delta)

    def record_signal(pid: int, sig: int) -> None:
        signals.append((pid, sig))

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(
            "enoch_control_plane.process_tracker.psutil.Process", process_for_pid
        )
        monkeypatch.setattr(
            "enoch_control_plane.process_tracker.os.kill", record_signal
        )

        assert tracker._finalize_stale_reap(info) is None
    assert signals == []


def test_finalize_stale_reap_treats_missing_process_as_already_gone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tracker = ProcessTracker(Path("/tmp"))
    info = _tracked_info()
    signals: list[tuple[int, int]] = []

    def no_such_process(pid: int) -> object:
        raise ProcessLookupError(pid)

    def record_signal(pid: int, sig: int) -> None:
        signals.append((pid, sig))

    monkeypatch.setattr(
        "enoch_control_plane.process_tracker.psutil.Process",
        no_such_process,
    )
    monkeypatch.setattr("enoch_control_plane.process_tracker.os.kill", record_signal)

    assert tracker._finalize_stale_reap(info) == info
    assert signals == []


def test_finalize_stale_reap_skips_when_process_identity_differs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tracker = ProcessTracker(Path("/tmp"))
    info = _tracked_info()
    signals: list[tuple[int, int]] = []

    def process_for_pid(pid: int) -> SimpleNamespace:
        return SimpleNamespace(create_time=lambda: 101.0)

    def record_signal(pid: int, sig: int) -> None:
        signals.append((pid, sig))

    monkeypatch.setattr(
        "enoch_control_plane.process_tracker.psutil.Process", process_for_pid
    )
    monkeypatch.setattr("enoch_control_plane.process_tracker.os.kill", record_signal)

    assert tracker._finalize_stale_reap(info) is None
    assert signals == []


def test_finish_stale_project_process_reap_filters_reused_pids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tracker = ProcessTracker(Path("/tmp"))
    original = _tracked_info(pid=111, create_time=10.0)
    reused = _tracked_info(pid=222, create_time=20.0)
    signals: list[tuple[int, int]] = []

    def process_for_pid(pid: int) -> _ProcStub:
        create_time = 10.0 if pid == original.pid else 99.0
        return _ProcStub(create_time=create_time)

    def record_signal(pid: int, sig: int) -> None:
        signals.append((pid, sig))

    monkeypatch.setattr(
        "enoch_control_plane.process_tracker.psutil.Process",
        process_for_pid,
    )
    monkeypatch.setattr("enoch_control_plane.process_tracker.os.kill", record_signal)

    assert tracker.finish_stale_project_process_reap([original, reused]) == [original]
    assert signals == [(original.pid, signal.SIGKILL)]
