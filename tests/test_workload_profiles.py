from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from fastapi import HTTPException

from omx_wake_gate.app import (
    _normalize_prepare_metadata,
    _resolve_workload_profile_for_project_dir,
    _wake_decision_profile_evidence,
)
from omx_wake_gate.config import GateConfig
from omx_wake_gate.gate import WakeGate
from omx_wake_gate.models import GateState, ProcessSnapshot, RunRecord, TelemetrySample


class _StaticTelemetry:
    def __init__(self, sample: TelemetrySample) -> None:
        self.sample_value = sample

    def sample(self) -> TelemetrySample:
        return self.sample_value


class _NoopProcessTracker:
    def snapshot(self, record: RunRecord, gpu_compute_pids: list[int] | None = None) -> ProcessSnapshot:
        return ProcessSnapshot()


class WorkloadProfileTests(unittest.TestCase):
    def test_prepare_metadata_defaults_to_inference_eval(self) -> None:
        normalized = _normalize_prepare_metadata({})
        self.assertEqual(normalized["workload_class"], "inference_eval")

    def test_prepare_metadata_rejects_unknown_workload_class(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            _normalize_prepare_metadata({"workload_class": "burst_eval"})
        self.assertEqual(raised.exception.status_code, 400)

    def test_project_metadata_resolution_defaults_to_inference_eval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            workload_class, workload_profile = _resolve_workload_profile_for_project_dir(project_dir)
            self.assertEqual(workload_class, "inference_eval")
            self.assertEqual(workload_profile.idle_sustain_sec, 300)
            self.assertEqual(workload_profile.cpu_idle_threshold_pct, 20.0)

    def test_project_metadata_resolution_uses_explicit_training_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            metadata_dir = project_dir / ".omx"
            metadata_dir.mkdir(parents=True, exist_ok=True)
            (metadata_dir / "project.json").write_text(
                json.dumps({"metadata": {"workload_class": "training"}}),
                encoding="utf-8",
            )
            workload_class, workload_profile = _resolve_workload_profile_for_project_dir(project_dir)
            self.assertEqual(workload_class, "training")
            self.assertEqual(workload_profile.idle_sustain_sec, 180)
            self.assertEqual(workload_profile.cpu_idle_threshold_pct, 35.0)

    def test_inference_eval_profile_is_stricter_than_training(self) -> None:
        config = GateConfig(
            state_dir="/tmp/omx-wake-gate-test",
            project_root="/tmp/omx-wake-gate-test",
            dispatch_script_path="/tmp/omx-wake-gate-test/dispatch.sh",
            omx_inbound_bearer_token="secret",
            sample_interval_sec=60,
            completion_callback_url="http://127.0.0.1/callback",
            completion_callback_token="callback-token",
        )
        sample = TelemetrySample(
            cpu_pct=25.0,
            gpu_pct=0.0,
            vram_used_mib=512,
            memory_source="uma_meminfo",
            uma_allocatable_mib=100_000,
        )
        gate = WakeGate(config, _NoopProcessTracker(), _StaticTelemetry(sample))

        training_class, training_profile = config.resolve_workload_profile("training")
        training_record = RunRecord(
            run_id="run-training",
            session_id="session-training",
            workload_class=training_class,
            workload_profile=training_profile,
            gate_state=GateState.PENDING_IDLE_GATE,
            idle_seen_at="2026-04-23T00:00:00+00:00",
            baseline_vram_mib=512,
        )
        training_callback = None
        for _ in range(3):
            training_record, training_callback = gate.evaluate(training_record)
        self.assertIsNotNone(training_callback)
        self.assertEqual(training_record.gate_state, GateState.WAKE_READY)
        self.assertEqual(training_callback.telemetry["workload_class"], "training")
        self.assertEqual(training_callback.telemetry["workload_profile_name"], "training")
        self.assertEqual(training_callback.telemetry["thresholds"]["idle_sustain_sec"], 180)
        self.assertEqual(training_callback.telemetry["thresholds"]["cpu_idle_threshold_pct"], 35.0)

        inference_class, inference_profile = config.resolve_workload_profile("inference_eval")
        inference_record = RunRecord(
            run_id="run-inference",
            session_id="session-inference",
            workload_class=inference_class,
            workload_profile=inference_profile,
            gate_state=GateState.PENDING_IDLE_GATE,
            idle_seen_at="2026-04-23T00:00:00+00:00",
            baseline_vram_mib=512,
        )
        inference_callback = None
        for _ in range(5):
            inference_record, inference_callback = gate.evaluate(inference_record)
        self.assertIsNone(inference_callback)
        self.assertEqual(inference_record.gate_state, GateState.WAITING_FOR_QUIET_WINDOW)

    def test_wake_decision_profile_evidence_contains_resolved_thresholds(self) -> None:
        config = GateConfig(
            state_dir="/tmp/omx-wake-gate-test",
            project_root="/tmp/omx-wake-gate-test",
            dispatch_script_path="/tmp/omx-wake-gate-test/dispatch.sh",
            omx_inbound_bearer_token="secret",
            completion_callback_url="http://127.0.0.1/callback",
            completion_callback_token="callback-token",
        )
        workload_class, workload_profile = config.resolve_workload_profile("inference_eval")
        evidence = _wake_decision_profile_evidence(
            RunRecord(
                run_id="run-evidence",
                session_id="session-evidence",
                workload_class=workload_class,
                workload_profile=workload_profile,
            )
        )

        self.assertEqual(evidence["workload_class"], "inference_eval")
        self.assertEqual(evidence["workload_profile_name"], "inference_eval")
        self.assertEqual(evidence["workload_thresholds"]["idle_sustain_sec"], 300)
        self.assertEqual(evidence["workload_thresholds"]["cpu_idle_threshold_pct"], 20.0)
        self.assertEqual(evidence["workload_thresholds"]["gpu_idle_avg_threshold_pct"], 10.0)
        self.assertEqual(evidence["workload_thresholds"]["gpu_idle_peak_threshold_pct"], 20.0)
        self.assertEqual(evidence["workload_thresholds"]["vram_delta_threshold_mib"], 1024)

    def test_uma_pressure_above_baseline_does_not_wedge_quiet_gate(self) -> None:
        config = GateConfig(
            state_dir="/tmp/omx-wake-gate-test",
            project_root="/tmp/omx-wake-gate-test",
            dispatch_script_path="/tmp/omx-wake-gate-test/dispatch.sh",
            omx_inbound_bearer_token="secret",
            sample_interval_sec=60,
            completion_callback_url="http://127.0.0.1/callback",
            completion_callback_token="callback-token",
        )
        workload_class, workload_profile = config.resolve_workload_profile("inference_eval")
        sample = TelemetrySample(
            cpu_pct=0.4,
            gpu_pct=0.0,
            vram_used_mib=5_880,
            memory_source="uma_meminfo",
            memory_total_mib=124_546,
            memory_available_mib=118_666,
            swap_free_mib=0,
            uma_allocatable_mib=118_666,
            uma_pressure_mib=5_880,
        )
        gate = WakeGate(config, _NoopProcessTracker(), _StaticTelemetry(sample))
        record = RunRecord(
            run_id="run-uma",
            session_id="session-uma",
            workload_class=workload_class,
            workload_profile=workload_profile,
            gate_state=GateState.PENDING_IDLE_GATE,
            idle_seen_at="2026-04-24T14:04:57+00:00",
            last_event_at="2026-04-24T14:04:57+00:00",
            baseline_vram_mib=4_165,
        )

        callback = None
        for _ in range(4):
            record, callback = gate.evaluate(record)

        self.assertIsNone(callback)
        self.assertEqual(record.gate_state, GateState.WAITING_FOR_QUIET_WINDOW)
        record, callback = gate.evaluate(record)

        self.assertIsNotNone(callback)
        self.assertEqual(record.gate_state, GateState.WAKE_READY)
        self.assertEqual(callback.telemetry["memory_source"], "uma_meminfo")
        self.assertTrue(callback.telemetry["memory_quiet_enough"])
        self.assertEqual(callback.telemetry["vram_baseline_mib"], 4_165)
        self.assertEqual(callback.telemetry["vram_current_mib"], 5_880)


if __name__ == "__main__":
    unittest.main()
