from __future__ import annotations

import json
import signal
from pathlib import Path
from types import SimpleNamespace
from urllib import error

import pytest

from enoch_control_plane import callback_outbox
from enoch_control_plane.config import GateConfig
from enoch_control_plane.gate import WakeGate
from enoch_control_plane.models import ControlPlaneEvent, GateState, ProcessSnapshot, RunRecord, SourceEvent, TelemetrySample
from enoch_control_plane.process_tracker import ProcessTracker, _is_benign_project_process
from enoch_control_plane import telemetry as telemetry_mod


class _StaticTelemetry:
    def __init__(self, samples: list[TelemetrySample] | None = None) -> None:
        self.samples = samples or [TelemetrySample(cpu_pct=0, gpu_pct=0, memory_source="uma_meminfo", uma_allocatable_mib=999_999)]
        self.index = 0

    def sample(self) -> TelemetrySample:
        sample = self.samples[min(self.index, len(self.samples) - 1)]
        self.index += 1
        return sample


class _StaticTracker:
    def __init__(self, snapshot: ProcessSnapshot | None = None) -> None:
        self._snapshot = snapshot or ProcessSnapshot()
        self.reaped = []

    def snapshot(self, record: RunRecord, gpu_compute_pids=None) -> ProcessSnapshot:
        return self._snapshot

    def reap_stale_project_processes(self, *args, **kwargs):
        return self.reaped


def _config(**kwargs) -> GateConfig:
    base = {
        "state_dir": "/tmp/enoch-test",
        "project_root": "/tmp/enoch-test/projects",
        "dispatch_script_path": "/tmp/enoch-test/dispatch.sh",
        "control_api_bearer_token": "token",
        "completion_callback_url": "http://127.0.0.1/callback",
        "completion_callback_token": "callback",
        "sample_interval_sec": 1,
        "idle_sustain_sec": 30,
        "max_wait_after_idle_sec": 60,
    }
    base.update(kwargs)
    return GateConfig(**base)


def _record(**kwargs) -> RunRecord:
    base = {"run_id": "run", "session_id": "session", "project_id": "project", "gate_state": GateState.RUNNING}
    base.update(kwargs)
    return RunRecord(**base)


def test_apply_event_precedence_and_new_session_reset() -> None:
    gate = WakeGate(_config(), _StaticTracker(), _StaticTelemetry())
    record = _record(session_id="old-session", gate_state=GateState.WAKE_READY, idle_seen_at="old", last_idempotency_key="key")
    updated = gate.apply_event(record, ControlPlaneEvent(event=SourceEvent.SESSION_START, run_id="run", session_id="new-session", project_id="p2", root_pid=123, process_group_id=456))
    assert updated.gate_state == GateState.RUNNING
    assert updated.session_id == "new-session"
    assert updated.project_id == "p2"
    assert updated.root_pid == 123
    assert updated.process_group_id == 456
    assert updated.idle_seen_at is None
    assert updated.last_idempotency_key is None

    stopped = gate.apply_event(updated, ControlPlaneEvent(event=SourceEvent.SESSION_END, run_id="run", session_id="new-session"))
    assert stopped.gate_state == GateState.FINISHED_PENDING_GATE
    ignored = gate.apply_event(stopped, ControlPlaneEvent(event=SourceEvent.SESSION_IDLE, run_id="run", session_id="new-session"))
    assert ignored.gate_state == GateState.FINISHED_PENDING_GATE


def test_apply_event_sets_idle_question_and_stop_states() -> None:
    gate = WakeGate(_config(), _StaticTracker(), _StaticTelemetry())
    record = _record()
    idle = gate.apply_event(record, ControlPlaneEvent(event=SourceEvent.SESSION_IDLE, run_id="run", session_id="session"))
    assert idle.gate_state == GateState.PENDING_IDLE_GATE
    assert idle.idle_seen_at is not None
    question = gate.apply_event(idle, ControlPlaneEvent(event=SourceEvent.ASK_USER_QUESTION, run_id="run", session_id="session"))
    assert question.gate_state == GateState.QUESTION_PENDING
    stopped = gate.apply_event(question, ControlPlaneEvent(event=SourceEvent.SESSION_STOP, run_id="run", session_id="session"))
    assert stopped.gate_state == GateState.FINISHED_PENDING_GATE


def test_reconcile_promotes_running_record_when_processes_are_gone() -> None:
    gate = WakeGate(_config(), _StaticTracker(ProcessSnapshot()), _StaticTelemetry())
    record, changed = gate.reconcile(_record())
    assert changed is True
    assert record.gate_state == GateState.PENDING_IDLE_GATE
    assert record.quiet_samples == []

    busy_gate = WakeGate(_config(), _StaticTracker(ProcessSnapshot(process_alive=True)), _StaticTelemetry())
    busy_record, busy_changed = busy_gate.reconcile(_record())
    assert busy_changed is False
    assert busy_record.gate_state == GateState.RUNNING


def test_evaluate_waits_for_process_exit_and_then_emits_callbacks() -> None:
    busy = WakeGate(_config(), _StaticTracker(ProcessSnapshot(descendants_alive=True)), _StaticTelemetry())
    record, callback = busy.evaluate(_record(gate_state=GateState.PENDING_IDLE_GATE))
    assert callback is None
    assert record.gate_state == GateState.WAITING_FOR_PROCESS_EXIT
    assert record.quiet_samples == []

    quiet_cfg = _config(workload_profiles={"training": {"idle_sustain_sec": 30, "cpu_idle_threshold_pct": 90, "gpu_idle_avg_threshold_pct": 90, "gpu_idle_peak_threshold_pct": 90, "vram_delta_threshold_mib": 100}})
    quiet_gate = WakeGate(quiet_cfg, _StaticTracker(), _StaticTelemetry([TelemetrySample(cpu_pct=1, gpu_pct=1, memory_source="nvml_dedicated", vram_used_mib=50)] * 30))
    record = _record(gate_state=GateState.FINISHED_PENDING_GATE, workload_class="training", baseline_vram_mib=0, last_event=SourceEvent.SESSION_END, last_event_at="seen")
    for _ in range(30):
        record, callback = quiet_gate.evaluate(record)
    assert callback is not None
    assert callback.event_type == "session_finished_ready"
    assert record.gate_state == GateState.FINISHED_READY

    duplicate, duplicate_callback = quiet_gate.evaluate(record.model_copy(update={"last_idempotency_key": callback.idempotency_key}))
    assert duplicate_callback is None
    assert duplicate.gate_state == GateState.FINISHED_READY


def test_evaluate_rebases_uma_baseline_and_reports_not_quiet() -> None:
    cfg = _config(workload_profiles={"training": {"idle_sustain_sec": 30, "cpu_idle_threshold_pct": 0, "gpu_idle_avg_threshold_pct": 90, "gpu_idle_peak_threshold_pct": 90, "vram_delta_threshold_mib": 100}})
    gate = WakeGate(cfg, _StaticTracker(), _StaticTelemetry([TelemetrySample(cpu_pct=50, gpu_pct=1, vram_used_mib=123, memory_source="uma_meminfo", uma_allocatable_mib=10_000, uma_pressure_mib=123)]))
    record, callback = gate.evaluate(_record(gate_state=GateState.PENDING_IDLE_GATE, workload_class="training", baseline_vram_mib=0))
    assert callback is None
    assert record.baseline_vram_mib == 123
    assert record.gate_state == GateState.WAITING_FOR_QUIET_WINDOW


def test_timeout_and_reaper_guards() -> None:
    gate = WakeGate(_config(stale_project_process_reaper_enabled=False), _StaticTracker(), _StaticTelemetry())
    assert gate.reap_stale_project_processes(_record(gate_state=GateState.RUNNING)) == []
    assert gate.is_timed_out(_record(gate_state=GateState.RUNNING)) is False
    old = "2026-01-01T00:00:00+00:00"
    assert gate.is_timed_out(_record(gate_state=GateState.PENDING_IDLE_GATE, idle_seen_at=old)) is True


def test_callback_outbox_reuses_existing_metadata_and_marks_delivered(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"run_id": "run/unsafe", "gate_state": "wake_ready", "idempotency_key": "idem"}
    path = callback_outbox.write_pending(tmp_path, payload)
    stored = json.loads(path.read_text())
    assert path.name == "run_unsafe.json"
    assert stored["attempt_count"] == 0

    stored["attempt_count"] = 7
    stored["last_error"] = "previous"
    path.write_text(json.dumps(stored))
    path2 = callback_outbox.write_pending(tmp_path, payload)
    assert json.loads(path2.read_text())["attempt_count"] == 7

    run_state = tmp_path / "runs" / "run_unsafe.json"
    run_state.parent.mkdir()
    run_state.write_text(json.dumps({"gate_state": "pending"}))
    monkeypatch.setattr(callback_outbox, "deliver_payload", lambda payload, **kwargs: callback_outbox.DeliveryResult(ok=True, status_code=204, detail="ok"))
    result = callback_outbox.deliver_pending_file(path2, state_dir=tmp_path, url="http://example", token="t", timeout=1)
    assert result.ok is True
    assert not path2.exists()
    assert Path(result.path).exists()
    assert json.loads(run_state.read_text())["gate_state"] == "wake_ready"


def test_callback_outbox_failure_and_replay_limits(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValueError):
        callback_outbox.write_pending(tmp_path, {"no_run_id": True})
    first = callback_outbox.write_pending(tmp_path, {"run_id": "b"})
    second = callback_outbox.write_pending(tmp_path, {"run_id": "a"})
    monkeypatch.setattr(callback_outbox, "deliver_payload", lambda payload, **kwargs: callback_outbox.DeliveryResult(ok=False, status_code=500, detail="boom"))
    result = callback_outbox.deliver_pending_file(first, state_dir=tmp_path, url="http://example", token="t", timeout=1)
    assert result.ok is False
    assert json.loads(first.read_text())["last_error"] == "boom"
    assert callback_outbox.replay_pending(state_dir=tmp_path, url="", token="t") == []
    results = callback_outbox.replay_pending(state_dir=tmp_path, url="http://example", token="t", limit=1)
    assert len(results) == 1
    assert results[0].ok is False
    assert second.exists()


def test_deliver_payload_handles_http_and_url_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Resp:
        status = 201
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def read(self, n): return b"created"

    monkeypatch.setattr(callback_outbox.request, "urlopen", lambda req, timeout: _Resp())
    ok = callback_outbox.deliver_payload({"run_id": "run"}, url="http://example", token="t", timeout=1)
    assert ok.ok is True and ok.status_code == 201

    class _HTTP(error.HTTPError):
        def read(self, n=-1): return b"denied"

    monkeypatch.setattr(callback_outbox.request, "urlopen", lambda req, timeout: _HTTP("http://example", 403, "Forbidden", {}, None))
    denied = callback_outbox.deliver_payload({"run_id": "run"}, url="http://example", token="t", timeout=1)
    assert denied.ok is False and denied.status_code == 403 and denied.detail == "denied"

    monkeypatch.setattr(callback_outbox.request, "urlopen", lambda req, timeout: (_ for _ in ()).throw(RuntimeError("down")))
    down = callback_outbox.deliver_payload({"run_id": "run"}, url="http://example", token="t", timeout=1)
    assert down.ok is False and "RuntimeError" in down.detail


def test_process_helpers_cover_benign_and_same_process(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _is_benign_project_process("") is True
    assert _is_benign_project_process("tail -f logs/out") is True
    assert _is_benign_project_process("python train.py") is False
    tracker = ProcessTracker(Path("/tmp"))
    assert tracker._project_dir(_record(project_dir="")) == (Path("/tmp") / "project").resolve()

    class _Gone:
        def create_time(self):
            raise telemetry_mod.psutil.NoSuchProcess(1)
    assert tracker._same_process(_Gone(), SimpleNamespace(create_time=1.0)) is None
    assert tracker._same_process(SimpleNamespace(create_time=lambda: 1.005), SimpleNamespace(create_time=1.0)) is True
    assert tracker._same_process(SimpleNamespace(create_time=lambda: 2.0), SimpleNamespace(create_time=1.0)) is False


def test_reaper_sends_sigkill_when_term_does_not_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    tracker = ProcessTracker(Path("/tmp"))
    candidate = SimpleNamespace(pid=123, create_time=1.0, cmdline="python smoke.py")
    signals: list[int] = []
    monkeypatch.setattr(tracker, "stale_reap_candidates", lambda *args, **kwargs: [candidate])
    monkeypatch.setattr("enoch_control_plane.process_tracker.time.sleep", lambda _s: None)
    monkeypatch.setattr("enoch_control_plane.process_tracker.os.kill", lambda _pid, sig: signals.append(sig))
    monkeypatch.setattr("enoch_control_plane.process_tracker.psutil.Process", lambda _pid: SimpleNamespace(create_time=lambda: 1.0, is_running=lambda: True, status=lambda: "running"))
    reaped = tracker.reap_stale_project_processes(_record(), stale_after_sec=0, command_markers=["python"], term_grace_sec=1)
    assert reaped == [candidate]
    assert signals == [signal.SIGTERM, signal.SIGKILL]


def test_meminfo_and_uma_memory_paths(tmp_path: Path) -> None:
    meminfo = tmp_path / "meminfo"
    meminfo.write_text("MemTotal: 4096000 kB\nMemAvailable: 1024000 kB\nSwapTotal: 2048000 kB\nSwapFree: 512000 kB\nBad: nope kB\n")
    values = telemetry_mod._read_meminfo(meminfo)
    assert values["MemTotal"] == 4_096_000
    uma = telemetry_mod._uma_memory_from_meminfo(values)
    assert uma["memory_total_mib"] == 4000
    assert uma["uma_allocatable_mib"] == 1500

    huge = telemetry_mod._uma_memory_from_meminfo({"MemTotal": 4096000, "HugePages_Total": 4, "HugePages_Free": 2, "Hugepagesize": 2048, "SwapFree": 999999})
    assert huge["uma_allocatable_mib"] == 4
    assert huge["swap_free_mib"] == 0
    assert telemetry_mod._read_meminfo(tmp_path / "missing") == {}


def test_telemetry_collector_without_optional_backends(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(telemetry_mod, "psutil", None)
    monkeypatch.setattr(telemetry_mod, "nvmlInit", None)
    monkeypatch.setattr(telemetry_mod, "_read_meminfo", lambda: {"MemTotal": 2048000, "MemAvailable": 1024000})
    collector = telemetry_mod.TelemetryCollector()
    sample = collector.sample()
    assert sample.cpu_pct == 0.0
    assert sample.memory_source == "uma_meminfo"
    assert sample.uma_allocatable_mib == 1000
    collector.close()


def test_telemetry_collector_uses_nvml_dedicated_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(telemetry_mod, "psutil", SimpleNamespace(cpu_percent=lambda interval=None: 12.5))
    monkeypatch.setattr(telemetry_mod, "_read_meminfo", lambda: {"MemTotal": 2048000, "MemAvailable": 1024000})
    monkeypatch.setattr(telemetry_mod, "nvmlInit", lambda: None)
    monkeypatch.setattr(telemetry_mod, "nvmlShutdown", lambda: None)
    monkeypatch.setattr(telemetry_mod, "nvmlDeviceGetHandleByIndex", lambda _idx: "handle")
    monkeypatch.setattr(telemetry_mod, "nvmlDeviceGetUtilizationRates", lambda _handle: SimpleNamespace(gpu=42))
    monkeypatch.setattr(telemetry_mod, "nvmlDeviceGetComputeRunningProcesses", lambda _handle: [SimpleNamespace(pid=111), SimpleNamespace(pid=None)])
    monkeypatch.setattr(telemetry_mod, "nvmlDeviceGetMemoryInfo", lambda _handle: SimpleNamespace(total=8 * 1024 * 1024, used=3 * 1024 * 1024))
    collector = telemetry_mod.TelemetryCollector()
    sample = collector.sample()
    assert sample.cpu_pct == 12.5
    assert sample.gpu_pct == 42.0
    assert sample.gpu_compute_pids == [111]
    assert sample.memory_source == "nvml_dedicated"
    assert sample.vram_used_mib == 3
    collector.close()
