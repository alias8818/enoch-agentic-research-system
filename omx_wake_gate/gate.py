from __future__ import annotations

from datetime import datetime, timezone
from statistics import mean

from .config import GateConfig
from .models import GateCallback, GateState, OmxEvent, RunRecord, utc_now
from .process_tracker import ProcessTracker
from .telemetry import TelemetryCollector


_EVENT_PRECEDENCE = {
    "session-start": 0,
    "session-idle": 1,
    "ask-user-question": 2,
    "session-stop": 3,
    "session-end": 3,
}


class WakeGate:
    def __init__(
        self,
        config: GateConfig,
        process_tracker: ProcessTracker,
        telemetry: TelemetryCollector,
    ) -> None:
        self.config = config
        self.process_tracker = process_tracker
        self.telemetry = telemetry

    def apply_event(self, record: RunRecord, event: OmxEvent) -> RunRecord:
        new_session_start = (
            event.event.value == "session-start"
            and bool(record.session_id)
            and event.session_id != record.session_id
        )

        record.session_id = event.session_id
        record.project_id = event.project_id or record.project_id
        record.project_name = event.project_name or record.project_name
        record.root_pid = event.root_pid or record.root_pid
        record.process_group_id = event.process_group_id or record.process_group_id

        if new_session_start:
            record.gate_state = GateState.RUNNING
            record.idle_seen_at = None
            record.last_idempotency_key = None
            record.quiet_samples = []
            record.last_event = event.event
            record.last_event_at = event.timestamp
            record.updated_at = utc_now()
            return record

        current_rank = _EVENT_PRECEDENCE.get(record.last_event.value, -1) if record.last_event else -1
        incoming_rank = _EVENT_PRECEDENCE.get(event.event.value, -1)

        if incoming_rank < current_rank:
            record.updated_at = utc_now()
            return record

        record.last_event = event.event
        record.last_event_at = event.timestamp
        record.updated_at = utc_now()

        if event.event.value == "session-start":
            record.gate_state = GateState.RUNNING
            record.idle_seen_at = None
            record.quiet_samples = []
        elif event.event.value == "session-idle":
            record.gate_state = GateState.PENDING_IDLE_GATE
            record.idle_seen_at = event.timestamp
        elif event.event.value == "ask-user-question":
            record.gate_state = GateState.QUESTION_PENDING
        elif event.event.value in {"session-end", "session-stop"}:
            record.gate_state = GateState.FINISHED_PENDING_GATE

        return record

    def reconcile(self, record: RunRecord) -> tuple[RunRecord, bool]:
        if record.gate_state != GateState.RUNNING:
            return record, False

        sample = self.telemetry.sample()
        process_snapshot = self.process_tracker.snapshot(record, sample.gpu_compute_pids)
        if (
            process_snapshot.process_alive
            or process_snapshot.descendants_alive
            or process_snapshot.gpu_processes_alive
            or process_snapshot.project_cwd_processes_alive
        ):
            return record, False

        record.gate_state = GateState.PENDING_IDLE_GATE
        record.idle_seen_at = record.idle_seen_at or utc_now()
        record.updated_at = utc_now()
        record.quiet_samples = []
        return record, True

    def evaluate(self, record: RunRecord) -> tuple[RunRecord, GateCallback | None]:
        if record.gate_state not in {
            GateState.PENDING_IDLE_GATE,
            GateState.WAITING_FOR_PROCESS_EXIT,
            GateState.WAITING_FOR_QUIET_WINDOW,
            GateState.FINISHED_PENDING_GATE,
        }:
            return record, None

        if record.workload_profile is not None:
            workload_class = record.workload_class or self.config.normalize_workload_class(None)
            workload_profile = record.workload_profile
            if record.workload_class != workload_class:
                record.workload_class = workload_class
        else:
            workload_class, workload_profile = self.config.resolve_workload_profile(record.workload_class)
            if record.workload_class != workload_class:
                record.workload_class = workload_class
            if record.workload_profile != workload_profile:
                record.workload_profile = workload_profile

        sample = self.telemetry.sample()
        process_snapshot = self.process_tracker.snapshot(record, sample.gpu_compute_pids)
        record.quiet_samples.append(sample)
        max_samples = max(1, workload_profile.idle_sustain_sec // self.config.sample_interval_sec)
        record.quiet_samples = record.quiet_samples[-max_samples:]
        record.updated_at = utc_now()

        if (
            process_snapshot.process_alive
            or process_snapshot.descendants_alive
            or process_snapshot.gpu_processes_alive
            or process_snapshot.project_cwd_processes_alive
        ):
            record.gate_state = GateState.WAITING_FOR_PROCESS_EXIT
            # Any active tracked process invalidates the quiet window and
            # forces the gate to rebuild a fresh idle sample set afterward.
            record.quiet_samples = []
            return record, None

        cpu_avg = mean(item.cpu_pct for item in record.quiet_samples)
        gpu_avg = mean(item.gpu_pct for item in record.quiet_samples)
        gpu_peak = max(item.gpu_pct for item in record.quiet_samples)
        latest_sample = record.quiet_samples[-1]
        vram_current = latest_sample.vram_used_mib
        memory_source = latest_sample.memory_source
        if memory_source == "uma_meminfo" and not record.baseline_vram_mib:
            # DGX Spark/iGPU UMA memory is system memory pressure, not
            # dedicated VRAM. Older in-flight records may have a zero baseline
            # from the previous unsupported nvidia-smi/NVML path; rebase them
            # to the first observed UMA pressure sample so the quiet window can
            # complete when CPU/GPU/process state is otherwise idle.
            record.baseline_vram_mib = vram_current
        vram_baseline = record.baseline_vram_mib or 0
        if memory_source == "uma_meminfo":
            # UMA pressure is host allocator state, not dedicated framebuffer
            # occupancy. Python, npm, and filesystem cache often settle above
            # the launch baseline after a run has exited, so using a small VRAM
            # delta here can wedge the gate even when no project process and no
            # GPU work remain. On UMA, require enough allocatable memory for
            # another run instead of requiring pressure to return to baseline.
            memory_quiet_enough = latest_sample.uma_allocatable_mib > workload_profile.vram_delta_threshold_mib
        else:
            memory_quiet_enough = vram_current <= vram_baseline + workload_profile.vram_delta_threshold_mib

        quiet_enough = (
            len(record.quiet_samples) >= max_samples
            and cpu_avg < workload_profile.cpu_idle_threshold_pct
            and gpu_avg < workload_profile.gpu_idle_avg_threshold_pct
            and gpu_peak < workload_profile.gpu_idle_peak_threshold_pct
            and memory_quiet_enough
        )

        if not quiet_enough:
            record.gate_state = GateState.WAITING_FOR_QUIET_WINDOW
            return record, None

        if record.last_idempotency_key:
            last_seen = record.last_idempotency_key.rsplit(":", maxsplit=1)[-1]
            current_seen = record.idle_seen_at or record.last_event_at
            if current_seen == last_seen:
                return record, None

        if record.last_event and record.last_event.value == "session-end":
            record.gate_state = GateState.FINISHED_READY
            event_type = "session_finished_ready"
            reason = "session_ended_and_system_quiet"
        else:
            record.gate_state = GateState.WAKE_READY
            event_type = "wake_ready"
            reason = "codex_idle_and_system_quiet"

        idempotency_key = f"{record.run_id}:{event_type}:{record.idle_seen_at or record.last_event_at}"

        callback = GateCallback(
            event_type=event_type,
            run_id=record.run_id,
            session_id=record.session_id,
            project_id=record.project_id,
            project_name=record.project_name,
            source_event=(record.last_event.value if record.last_event else "unknown"),
            gate_state=record.gate_state.value,
            idle_seen_at=record.idle_seen_at,
            process_tracking=process_snapshot,
            telemetry={
                "cpu_avg_pct": cpu_avg,
                "gpu_avg_pct": gpu_avg,
                "gpu_peak_pct": gpu_peak,
                "vram_baseline_mib": vram_baseline,
                "vram_current_mib": vram_current,
                "memory_source": memory_source,
                "memory_quiet_enough": memory_quiet_enough,
                "uma_allocatable_mib": latest_sample.uma_allocatable_mib,
                "uma_pressure_mib": latest_sample.uma_pressure_mib,
                "memory_available_mib": latest_sample.memory_available_mib,
                "swap_free_mib": latest_sample.swap_free_mib,
                "quiet_window_sec": workload_profile.idle_sustain_sec,
                "workload_class": workload_class,
                "workload_profile_name": workload_class,
                "thresholds": workload_profile.model_dump(),
            },
            reason=reason,
            idempotency_key=idempotency_key,
        )
        return record, callback

    def is_timed_out(self, record: RunRecord) -> bool:
        if record.gate_state not in {
            GateState.PENDING_IDLE_GATE,
            GateState.WAITING_FOR_PROCESS_EXIT,
            GateState.WAITING_FOR_QUIET_WINDOW,
            GateState.FINISHED_PENDING_GATE,
        }:
            return False
        if not record.idle_seen_at:
            return False
        idle_seen_at = datetime.fromisoformat(record.idle_seen_at.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - idle_seen_at).total_seconds() >= self.config.max_wait_after_idle_sec
