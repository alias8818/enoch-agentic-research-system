from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from omx_wake_gate.app import (
    _build_queue_snapshot,
    _dashboard_truth,
    _is_superseded_record,
    _latest_runs_by_project,
)
from omx_wake_gate.models import GateState, ProcessInfo, RunRecord


_NOW = datetime.now(timezone.utc)


def _record(
    run_id: str,
    state: GateState,
    *,
    project_id: str = "project-a",
    age_seconds: int = 10,
    idempotency_key: str | None = None,
) -> RunRecord:
    timestamp = (_NOW - timedelta(seconds=age_seconds)).isoformat()
    return RunRecord(
        run_id=run_id,
        session_id=f"session-{run_id}",
        project_id=project_id,
        gate_state=state,
        created_at=timestamp,
        updated_at=timestamp,
        last_event_at=timestamp,
        last_idempotency_key=idempotency_key,
    )


class DashboardTruthTests(unittest.TestCase):
    def test_callback_ready_states_distinguish_pending_delivered_and_stale(self) -> None:
        delivered = _record(
            "run-delivered",
            GateState.WAKE_READY,
            idempotency_key="run-delivered:wake_ready:2026-04-14T00:00:00+00:00",
        )
        pending = _record("run-pending", GateState.WAKE_READY)
        stale = _record("run-stale", GateState.WAKE_READY, age_seconds=999_999)

        self.assertEqual(_dashboard_truth(delivered, [])["lifecycle_state"], "callback_delivered")
        self.assertFalse(_dashboard_truth(delivered, [])["is_live"])
        self.assertEqual(_dashboard_truth(pending, [])["lifecycle_state"], "callback_pending")
        self.assertTrue(_dashboard_truth(pending, [])["is_live"])
        self.assertEqual(_dashboard_truth(stale, [])["lifecycle_state"], "stale_callback_ready")
        self.assertTrue(_dashboard_truth(stale, [])["needs_attention"])

    def test_errors_and_question_pending_are_attention_only_when_current(self) -> None:
        error = _record("run-error", GateState.ERROR)
        question = _record("run-question", GateState.QUESTION_PENDING)

        error_truth = _dashboard_truth(error, [])
        self.assertEqual(error_truth["lifecycle_state"], "attention")
        self.assertTrue(error_truth["needs_attention"])

        question_truth = _dashboard_truth(question, [])
        self.assertEqual(question_truth["lifecycle_state"], "question_pending")
        self.assertTrue(question_truth["is_live"])
        self.assertTrue(question_truth["needs_attention"])

        superseded_question = _dashboard_truth(question, [], superseded=True)
        self.assertEqual(superseded_question["lifecycle_state"], "superseded")
        self.assertFalse(superseded_question["is_live"])
        self.assertFalse(superseded_question["needs_attention"])

    def test_superseded_records_do_not_count_as_live_or_attention_without_processes(self) -> None:
        for state in (
            GateState.RUNNING,
            GateState.PENDING_IDLE_GATE,
            GateState.WAITING_FOR_PROCESS_EXIT,
            GateState.WAITING_FOR_QUIET_WINDOW,
            GateState.FINISHED_PENDING_GATE,
            GateState.ERROR,
            GateState.WAKE_READY,
            GateState.FINISHED_READY,
        ):
            with self.subTest(state=state.value):
                truth = _dashboard_truth(_record(f"old-{state.value}", state), [], superseded=True)
                self.assertEqual(truth["lifecycle_state"], "superseded")
                self.assertFalse(truth["is_live"])
                self.assertFalse(truth["needs_attention"])

    def test_live_processes_override_superseded_storage_state(self) -> None:
        process = ProcessInfo(pid=1234, cmdline="python active.py")
        truth = _dashboard_truth(_record("old-running", GateState.RUNNING), [process], superseded=True)
        self.assertEqual(truth["lifecycle_state"], "active")
        self.assertTrue(truth["is_live"])
        self.assertFalse(truth["needs_attention"])

    def test_superseded_detection_uses_latest_run_per_project(self) -> None:
        older = _record("older", GateState.ERROR, age_seconds=200)
        newer = _record("newer", GateState.WAKE_READY, age_seconds=10)
        latest_by_project = _latest_runs_by_project([older, newer])

        self.assertTrue(_is_superseded_record(older, latest_by_project))
        self.assertFalse(_is_superseded_record(newer, latest_by_project))

    def test_queue_snapshot_preserves_active_rows(self) -> None:
        snapshot = _build_queue_snapshot(
            {
                "source": "test",
                "total": 1,
                "valid_projects": 1,
                "status_counts": {"awaiting_wake": 1},
                "active_rows": [
                    {
                        "project_id": "idea-active",
                        "project_name": "Active Project",
                        "queue_status": "awaiting_wake",
                        "current_run_id": "run-active",
                        "next_action_hint": "await_callback",
                    }
                ],
            }
        )

        self.assertEqual(snapshot["active_rows"][0]["project_id"], "idea-active")

    def test_queue_snapshot_derives_dashboard_counts_from_rows(self) -> None:
        snapshot = _build_queue_snapshot(
            {
                "source": "test",
                "queue_rows": [
                    {
                        "project_id": "idea-active",
                        "project_name": "Active Project",
                        "status": "running",
                        "last_run_state": "continue",
                    },
                    {
                        "project_id": "idea-positive",
                        "project_name": "Positive Project",
                        "status": "completed",
                        "last_run_state": "finalize_positive",
                    },
                    {
                        "project_id": "idea-negative",
                        "project_name": "Negative Project",
                        "status": "completed",
                        "last_run_state": "finalize_negative",
                    },
                    {
                        "project_id": "idea-blocked",
                        "project_name": "Blocked Project",
                        "status": "blocked",
                        "last_run_state": "needs_review",
                    },
                ],
            }
        )

        self.assertEqual(snapshot["total"], 4)
        self.assertEqual(snapshot["active_count"], 1)
        self.assertEqual(snapshot["completed_count"], 2)
        self.assertEqual(snapshot["blocked_count"], 1)
        self.assertEqual(snapshot["positive_count"], 1)
        self.assertEqual(snapshot["negative_count"], 1)
        self.assertEqual(
            {row["project_id"] for row in snapshot["rows"]},
            {"idea-active", "idea-positive", "idea-negative", "idea-blocked"},
        )



if __name__ == "__main__":
    unittest.main()
