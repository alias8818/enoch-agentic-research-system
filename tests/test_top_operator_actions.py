from __future__ import annotations

import unittest

from enoch_control_plane.control_plane.read_models import (
    _safe_count,
    movement_diagnosis,
    primary_operator_action,
    top_operator_actions,
)


class TopOperatorActionsTests(unittest.TestCase):
    def test_idle_returns_empty_list(self) -> None:
        actions = top_operator_actions(
            operator_counts={"needs_attention": 0},
            paper_pipeline={
                "write_needed": 0,
                "finalize_needed": 0,
                "publish_ready": 0,
            },
            investigation_pipeline={"ranked_followup_ready": 0},
            counts={"active": 0, "queued": 0},
        )
        self.assertEqual(actions, [])

    def test_needs_attention_outranks_pipeline(self) -> None:
        actions = top_operator_actions(
            operator_counts={"needs_attention": 4},
            paper_pipeline={
                "write_needed": 1,
                "finalize_needed": 0,
                "publish_ready": 0,
                "next_write_candidate": {"project_id": "p1", "project_name": "alpha"},
            },
            investigation_pipeline={"ranked_followup_ready": 0},
            counts={"active": 0, "queued": 0, "blocked": 4},
        )
        self.assertGreaterEqual(len(actions), 2)
        self.assertEqual(actions[0]["kind"], "needs_attention")
        self.assertEqual(actions[0]["priority"], 1)
        self.assertEqual(actions[0]["tone"], "warn")
        self.assertEqual(actions[0]["count"], 4)
        self.assertIn("attention", actions[0]["title"].lower())
        self.assertEqual(actions[0]["action_hash"], "#queue:blocked")

    def test_paper_pipeline_ordering_write_then_finalize_then_publish(self) -> None:
        actions = top_operator_actions(
            operator_counts={"needs_attention": 0},
            paper_pipeline={
                "write_needed": 2,
                "finalize_needed": 1,
                "publish_ready": 3,
                "next_write_candidate": {
                    "project_id": "p1",
                    "project_name": "Alpha project",
                },
                "next_publish_candidate": {
                    "paper_id": "paper-9",
                    "project_name": "Bravo paper",
                },
            },
            investigation_pipeline={"ranked_followup_ready": 0},
            counts={"active": 1, "queued": 0},
        )
        kinds = [a["kind"] for a in actions]
        self.assertEqual(kinds, ["write_paper", "finalize_paper", "publish_paper"])
        self.assertEqual(actions[0]["priority"], 1)
        self.assertEqual(actions[2]["priority"], 3)
        self.assertEqual(
            actions[0]["target"], {"project_id": "p1", "name": "Alpha project"}
        )
        self.assertEqual(actions[0]["action_hash"], "#papers?status=publication_draft")
        self.assertEqual(actions[2]["action_hash"], "#corpus")
        self.assertIn("Alpha project", actions[0]["summary"])
        self.assertIn("Bravo paper", actions[2]["summary"])

    def test_followup_promoted_when_pipeline_clear(self) -> None:
        actions = top_operator_actions(
            operator_counts={"needs_attention": 0},
            paper_pipeline={
                "write_needed": 0,
                "finalize_needed": 0,
                "publish_ready": 0,
            },
            investigation_pipeline={
                "ranked_followup_ready": 2,
                "next_ranked_followup_candidate": {
                    "project_id": "p7",
                    "followup_title": "Adjacent FFT",
                },
            },
            counts={"active": 0, "queued": 0},
        )
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["kind"], "investigate_followup")
        self.assertEqual(actions[0]["tone"], "info")
        self.assertEqual(actions[0]["action_hash"], "#research")
        self.assertIn("Adjacent FFT", actions[0]["summary"])

    def test_dispatch_omitted_without_lane_data(self) -> None:
        # The aggregate `counts.active` / `counts.queued` MUST NOT be used to
        # imply lane dispatch truth. Without `worker_lanes`, the projection
        # never emits a dispatch_next card, even on an apparently idle queue.
        with_active = top_operator_actions(
            operator_counts={"needs_attention": 0},
            paper_pipeline={
                "write_needed": 0,
                "finalize_needed": 0,
                "publish_ready": 0,
            },
            investigation_pipeline={"ranked_followup_ready": 0},
            counts={"active": 1, "queued": 5},
        )
        self.assertEqual(with_active, [])

        idle_with_queue = top_operator_actions(
            operator_counts={"needs_attention": 0},
            paper_pipeline={
                "write_needed": 0,
                "finalize_needed": 0,
                "publish_ready": 0,
            },
            investigation_pipeline={"ranked_followup_ready": 0},
            counts={"active": 0, "queued": 5},
        )
        self.assertEqual(idle_with_queue, [])

    def test_dispatch_only_when_a_lane_is_open(self) -> None:
        # When `worker_lanes` is provided AND at least one lane is
        # dispatch_available, dispatch_next is surfaced. The label and queued
        # count come from the open lane(s), not aggregate counts.
        actions = top_operator_actions(
            operator_counts={"needs_attention": 0},
            paper_pipeline={
                "write_needed": 0,
                "finalize_needed": 0,
                "publish_ready": 0,
            },
            investigation_pipeline={"ranked_followup_ready": 0},
            counts={"active": 1, "queued": 0},  # aggregate says busy; lane data wins
            worker_lanes=[
                {
                    "machine_target": "cpu-proxmox-1",
                    "worker_role": "cpu_worker",
                    "status": "active",
                    "queued_count": 1,
                    "dispatch_available": False,
                    "dispatch_blocker": "lane active",
                },
                {
                    "machine_target": "gb10",
                    "worker_role": "gpu_worker",
                    "status": "idle",
                    "queued_count": 2,
                    "dispatch_available": True,
                    "dispatch_reason": "lane open with queued candidate",
                },
            ],
        )
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["kind"], "dispatch_next")
        self.assertEqual(actions[0]["action_hash"], "#queue:queued")
        self.assertIn("GB10 lane", actions[0]["summary"])
        # Queued count must come from the lane row, not aggregate counts.
        self.assertEqual(actions[0]["count"], 2)

    def test_dispatch_suppressed_when_all_lanes_busy(self) -> None:
        # CPU lane busy + GB10 lane busy => no dispatch_next, even though the
        # aggregate counts say something is queued.
        actions = top_operator_actions(
            operator_counts={"needs_attention": 0},
            paper_pipeline={
                "write_needed": 0,
                "finalize_needed": 0,
                "publish_ready": 0,
            },
            investigation_pipeline={"ranked_followup_ready": 0},
            counts={"active": 0, "queued": 7},
            worker_lanes=[
                {
                    "machine_target": "cpu-proxmox-1",
                    "dispatch_available": False,
                    "queued_count": 3,
                },
                {
                    "machine_target": "gb10",
                    "dispatch_available": False,
                    "queued_count": 4,
                },
            ],
        )
        self.assertEqual(actions, [])

    def test_results_are_bounded(self) -> None:
        actions = top_operator_actions(
            operator_counts={"needs_attention": 1},
            paper_pipeline={
                "write_needed": 1,
                "finalize_needed": 1,
                "publish_ready": 1,
            },
            investigation_pipeline={"ranked_followup_ready": 1},
            counts={"active": 0, "queued": 1},
        )
        self.assertEqual(len(actions), 3)
        self.assertEqual([a["priority"] for a in actions], [1, 2, 3])

    def test_safe_against_missing_or_string_inputs(self) -> None:
        # The projection must not raise even if upstream sends odd types.
        actions = top_operator_actions(
            operator_counts={"needs_attention": "2"},
            paper_pipeline={
                "write_needed": "1",
                "finalize_needed": None,
                "publish_ready": "",
                "next_write_candidate": {},
            },
            investigation_pipeline={"ranked_followup_ready": None},
            counts={"active": "0", "queued": ""},
        )
        kinds = [a["kind"] for a in actions]
        self.assertIn("needs_attention", kinds)
        self.assertIn("write_paper", kinds)


class TopOperatorActionsHardenedInputTests(unittest.TestCase):
    """Acceptance criterion: malformed top-action counts must not crash.

    These tests mirror the failure modes called out in PR 42 review:
    booleans, junk strings, negatives, and a malformed limit. They assert
    the projection degrades to "no ranked action" or a sensible bounded
    default rather than raising.
    """

    def test_malformed_string_count_does_not_crash(self) -> None:
        actions = top_operator_actions(
            operator_counts={"needs_attention": "bad"},
            paper_pipeline={
                "write_needed": "🌶",
                "finalize_needed": "n/a",
                "publish_ready": "  ",
            },
            investigation_pipeline={"ranked_followup_ready": "many"},
            counts={"active": "?", "queued": "lots"},
        )
        # Every count is malformed -> degrades to "no ranked action".
        self.assertEqual(actions, [])

    def test_booleans_are_not_treated_as_counts(self) -> None:
        # bool is a subclass of int in Python. A naive `int(True)` == 1 would
        # spuriously surface a "needs attention" card. The projection must
        # reject booleans explicitly.
        actions = top_operator_actions(
            operator_counts={"needs_attention": True},
            paper_pipeline={
                "write_needed": False,
                "finalize_needed": True,
                "publish_ready": False,
            },
            investigation_pipeline={"ranked_followup_ready": True},
            counts={"active": True, "queued": True, "blocked": False},
        )
        self.assertEqual(actions, [])

    def test_negative_counts_are_clamped_to_zero(self) -> None:
        # A negative upstream count must never produce a card. Two-way check:
        # all-negative -> empty list; mixed positive/negative -> only the
        # positive card surfaces.
        empty = top_operator_actions(
            operator_counts={"needs_attention": -5},
            paper_pipeline={
                "write_needed": -1,
                "finalize_needed": -2,
                "publish_ready": -3,
            },
            investigation_pipeline={"ranked_followup_ready": -10},
            counts={"active": -1, "queued": -1, "blocked": -1},
        )
        self.assertEqual(empty, [])

        only_write = top_operator_actions(
            operator_counts={"needs_attention": -2},
            paper_pipeline={
                "write_needed": 3,
                "finalize_needed": -2,
                "publish_ready": -1,
            },
            investigation_pipeline={"ranked_followup_ready": -1},
            counts={"active": 0, "queued": 0},
        )
        self.assertEqual([a["kind"] for a in only_write], ["write_paper"])
        self.assertEqual(only_write[0]["count"], 3)

    def test_malformed_limit_falls_back_to_default(self) -> None:
        # limit="bad" must not crash. The projection should still return a
        # bounded list (default 3) of the highest priority actions.
        actions = top_operator_actions(
            operator_counts={"needs_attention": 1},
            paper_pipeline={
                "write_needed": 1,
                "finalize_needed": 1,
                "publish_ready": 1,
            },
            investigation_pipeline={"ranked_followup_ready": 1},
            counts={"active": 0, "queued": 1},
            limit="bad",  # type: ignore[arg-type]
        )
        self.assertEqual(len(actions), 3)
        self.assertEqual([a["priority"] for a in actions], [1, 2, 3])

    def test_negative_limit_returns_empty_list(self) -> None:
        actions = top_operator_actions(
            operator_counts={"needs_attention": 1},
            paper_pipeline={
                "write_needed": 1,
                "finalize_needed": 1,
                "publish_ready": 1,
            },
            investigation_pipeline={"ranked_followup_ready": 1},
            counts={"active": 0, "queued": 1},
            limit=-7,
        )
        self.assertEqual(actions, [])

    def test_oversized_limit_is_capped(self) -> None:
        actions = top_operator_actions(
            operator_counts={"needs_attention": 1},
            paper_pipeline={
                "write_needed": 1,
                "finalize_needed": 1,
                "publish_ready": 1,
            },
            investigation_pipeline={"ranked_followup_ready": 1},
            counts={"active": 1, "queued": 0},
            limit=999,
        )
        # All five non-dispatch action kinds available; cap at 5.
        self.assertEqual(len(actions), 5)

    def test_malformed_worker_lanes_does_not_crash(self) -> None:
        # Junk lane payloads (None entries, missing dispatch_available, lists
        # in lane fields) must not propagate exceptions.
        actions = top_operator_actions(
            operator_counts={"needs_attention": 0},
            paper_pipeline={
                "write_needed": 0,
                "finalize_needed": 0,
                "publish_ready": 0,
            },
            investigation_pipeline={"ranked_followup_ready": 0},
            counts={"active": 0, "queued": 0},
            worker_lanes=[
                None,  # type: ignore[list-item]
                {"machine_target": "cpu-proxmox-1"},  # missing dispatch_available
                {
                    "machine_target": "gb10",
                    "dispatch_available": "yes please",
                    "queued_count": "two",
                },
                {"dispatch_available": True, "queued_count": -3, "machine_target": ""},
            ],
        )
        # The "yes please" + last entry are truthy under bool() so dispatch_next
        # surfaces, but queued_count='two'/'-3' must be coerced via _safe_count.
        kinds = [a["kind"] for a in actions]
        self.assertEqual(kinds, ["dispatch_next"])
        self.assertGreaterEqual(actions[0]["count"], 0)


class SafeCountHelperTests(unittest.TestCase):
    """Direct contract tests for the deterministic _safe_count helper."""

    def test_accepts_real_ints(self) -> None:
        self.assertEqual(_safe_count(0), 0)
        self.assertEqual(_safe_count(7), 7)
        self.assertEqual(_safe_count(9999), 9999)

    def test_accepts_numeric_strings(self) -> None:
        self.assertEqual(_safe_count("0"), 0)
        self.assertEqual(_safe_count("12"), 12)
        self.assertEqual(_safe_count("  3 "), 3)
        self.assertEqual(_safe_count("4.7"), 4)
        self.assertEqual(_safe_count("+5"), 5)

    def test_rejects_booleans(self) -> None:
        # Default returned regardless of bool truthiness.
        self.assertEqual(_safe_count(True), 0)
        self.assertEqual(_safe_count(False), 0)
        self.assertEqual(_safe_count(True, default=99), 99)
        self.assertEqual(_safe_count(False, default=99), 99)

    def test_returns_default_on_malformed(self) -> None:
        self.assertEqual(_safe_count("bad"), 0)
        self.assertEqual(_safe_count("bad", default=4), 4)
        self.assertEqual(_safe_count(None), 0)
        self.assertEqual(_safe_count(None, default=4), 4)
        self.assertEqual(_safe_count("   "), 0)
        self.assertEqual(_safe_count(""), 0)
        self.assertEqual(_safe_count({"x": 1}), 0)
        self.assertEqual(_safe_count(["1"]), 0)
        self.assertEqual(_safe_count(object()), 0)
        self.assertEqual(_safe_count(float("nan")), 0)
        self.assertEqual(_safe_count(float("inf"), default=11), 11)

    def test_clamps_negative_values_to_zero(self) -> None:
        self.assertEqual(_safe_count(-1), 0)
        self.assertEqual(_safe_count(-9999), 0)
        self.assertEqual(_safe_count("-3"), 0)
        self.assertEqual(_safe_count(-2.5), 0)

    def test_default_is_normalized(self) -> None:
        # Negative or non-numeric defaults must be normalized so callers can
        # never smuggle a negative card count out of the helper.
        self.assertEqual(_safe_count("bad", default=-7), 0)
        self.assertEqual(_safe_count(None, default=True), 0)  # bool default rejected
        self.assertEqual(_safe_count(None, default="bad"), 0)


class MovementDiagnosisTests(unittest.TestCase):
    def test_queue_pause_is_primary_blocker(self) -> None:
        diagnosis = movement_diagnosis(
            flags={"queue_paused": True, "maintenance_mode": False},
            worker_lanes=[
                {
                    "machine_target": "gb10",
                    "worker_role": "gpu_worker",
                    "status": "idle",
                    "queued_count": 1,
                    "dispatch_available": True,
                },
            ],
            paper_pipeline={},
        )

        self.assertEqual(diagnosis["status"], "blocked")
        self.assertEqual(diagnosis["primary_reason"], "Queue is paused.")
        self.assertEqual(diagnosis["blockers"][0]["kind"], "queue_paused")

    def test_global_pause_suppresses_lane_dispatch_actions(self) -> None:
        diagnosis = movement_diagnosis(
            flags={"queue_paused": True, "maintenance_mode": True},
            worker_lanes=[
                {
                    "machine_target": "cpu-proxmox-1",
                    "worker_role": "cpu_worker",
                    "status": "idle",
                    "queued_count": 3,
                    "dispatch_available": True,
                },
                {
                    "machine_target": "gb10",
                    "worker_role": "gpu_worker",
                    "status": "idle",
                    "queued_count": 2,
                    "dispatch_available": True,
                },
            ],
            paper_pipeline={"not_writable_by_decision_gate": 10},
        )

        self.assertEqual(diagnosis["status"], "blocked")
        kinds = [item["kind"] for item in diagnosis["blockers"]]
        self.assertEqual(kinds[:2], ["maintenance_mode", "queue_paused"])
        self.assertNotIn("dispatch_available", kinds)
        self.assertNotIn("followup_ready", kinds)

    def test_open_lane_is_actionable_not_blocked(self) -> None:
        diagnosis = movement_diagnosis(
            flags={"queue_paused": False, "maintenance_mode": False},
            worker_lanes=[
                {
                    "machine_target": "cpu-proxmox-1",
                    "worker_role": "cpu_worker",
                    "status": "active",
                    "queued_count": 0,
                    "dispatch_available": False,
                    "dispatch_blocker": "lane active",
                },
                {
                    "machine_target": "gb10",
                    "worker_role": "gpu_worker",
                    "status": "idle",
                    "queued_count": 2,
                    "dispatch_available": True,
                },
            ],
            paper_pipeline={},
        )

        self.assertEqual(diagnosis["status"], "actionable")
        self.assertEqual(
            diagnosis["primary_reason"], "GB10 lane can dispatch queued work."
        )
        kinds = [item["kind"] for item in diagnosis["blockers"]]
        self.assertIn("lane_active", kinds)
        self.assertIn("dispatch_available", kinds)

    def test_followup_ready_is_not_command_hero_blocker(self) -> None:
        # ALI-148 regression: "Bounded follow-up is ready" is useful
        # research-pipeline detail, but it is confusing as a main-page command
        # hero blocker/action while autopilot can handle it. Keep it out of
        # movement diagnosis blockers so the first viewport stays operational.
        diagnosis = movement_diagnosis(
            flags={"queue_paused": False, "maintenance_mode": False},
            worker_lanes=[
                {
                    "machine_target": "cpu-proxmox-1",
                    "worker_role": "cpu_worker",
                    "status": "active",
                    "queued_count": 1,
                    "dispatch_available": False,
                    "dispatch_blocker": "lane active",
                }
            ],
            paper_pipeline={"paper_write_blocked": 0, "finalize_needed": 0},
        )

        blocker_text = " ".join(
            f"{item.get('title', '')} {item.get('summary', '')}"
            for item in diagnosis["blockers"]
        )
        kinds = [item["kind"] for item in diagnosis["blockers"]]
        self.assertNotIn("followup_ready", kinds)
        self.assertNotIn("Bounded follow-up is ready", blocker_text)

    def test_idle_empty_lane_reports_no_admitted_candidates(self) -> None:
        diagnosis = movement_diagnosis(
            flags={"queue_paused": False, "maintenance_mode": False},
            worker_lanes=[
                {
                    "machine_target": "gb10",
                    "worker_role": "gpu_worker",
                    "status": "idle",
                    "queued_count": 0,
                    "dispatch_available": False,
                    "dispatch_blocker": "no queued candidate for lane",
                    "feed_pressure": {"next_autopilot_action": "generate_candidate"},
                },
            ],
            paper_pipeline={},
        )

        self.assertEqual(diagnosis["status"], "blocked")
        self.assertEqual(diagnosis["blockers"][0]["kind"], "no_admitted_candidates")
        self.assertIn("generate", diagnosis["blockers"][0]["summary"].lower())

    def test_paper_gate_archive_is_not_reported_as_blocker(self) -> None:
        diagnosis = movement_diagnosis(
            flags={"queue_paused": False, "maintenance_mode": False},
            worker_lanes=[],
            paper_pipeline={
                "not_writable_by_decision_gate": 3,
                "paper_gate_archive_count": 3,
                "paper_write_blocked": 0,
                "finalize_needed": 2,
            },
        )

        kinds = [item["kind"] for item in diagnosis["blockers"]]
        self.assertNotIn("paper_gate_blocked", kinds)
        self.assertNotIn("paper_write_blocked", kinds)
        self.assertIn("evidence_missing", kinds)

    def test_positive_paper_write_blocked_is_reported(self) -> None:
        diagnosis = movement_diagnosis(
            flags={"queue_paused": False, "maintenance_mode": False},
            worker_lanes=[],
            paper_pipeline={"paper_write_blocked": 2, "finalize_needed": 0},
        )

        kinds = [item["kind"] for item in diagnosis["blockers"]]
        self.assertIn("paper_write_blocked", kinds)

    def test_duplicate_active_on_single_lane_is_hard_blocker(self) -> None:
        diagnosis = movement_diagnosis(
            flags={"queue_paused": False, "maintenance_mode": False},
            worker_lanes=[
                {
                    "machine_target": "cpu-proxmox-1",
                    "worker_role": "cpu_worker",
                    "status": "active",
                    "active_count": 2,
                    "queued_count": 0,
                    "dispatch_available": False,
                },
                {
                    "machine_target": "gb10",
                    "worker_role": "gpu_worker",
                    "status": "idle",
                    "active_count": 0,
                    "queued_count": 0,
                    "dispatch_available": False,
                },
            ],
            paper_pipeline={},
        )

        self.assertEqual(diagnosis["status"], "blocked")
        self.assertIn(
            "violates the single-active-run lane invariant", diagnosis["primary_reason"]
        )
        kinds = [item["kind"] for item in diagnosis["blockers"]]
        self.assertIn("lane_conflict_active", kinds)


class PrimaryOperatorActionTests(unittest.TestCase):
    def test_dispatch_lane_beats_feed(self) -> None:
        lanes = [
            {
                "machine_target": "gb10",
                "worker_role": "gpu_worker",
                "status": "idle",
                "queued_count": 2,
                "dispatch_available": True,
                "next_candidate": {
                    "project_id": "gb10-job",
                    "project_name": "GB10 job",
                },
            }
        ]
        movement = movement_diagnosis(
            flags={"queue_paused": False, "maintenance_mode": False},
            worker_lanes=lanes,
            paper_pipeline={},
        )
        action = primary_operator_action(worker_lanes=lanes, movement=movement)
        self.assertIsNotNone(action)
        assert action is not None
        self.assertEqual(action["kind"], "dispatch_next")
        self.assertEqual(action["project_id"], "gb10-job")

    def test_queue_paused_blocker_beats_dispatch_lane(self) -> None:
        lanes = [
            {
                "machine_target": "gb10",
                "worker_role": "gpu_worker",
                "status": "idle",
                "queued_count": 2,
                "dispatch_available": True,
                "next_candidate": {
                    "project_id": "gb10-job",
                    "project_name": "GB10 job",
                },
            }
        ]
        movement = movement_diagnosis(
            flags={"queue_paused": True, "maintenance_mode": False},
            worker_lanes=lanes,
            paper_pipeline={},
        )
        action = primary_operator_action(worker_lanes=lanes, movement=movement)
        self.assertIsNotNone(action)
        assert action is not None
        self.assertEqual(action["kind"], "open_blocker")
        self.assertEqual(action["blocker_kind"], "queue_paused")

    def test_maintenance_mode_blocker_beats_dispatch_lane(self) -> None:
        lanes = [
            {
                "machine_target": "gb10",
                "worker_role": "gpu_worker",
                "status": "idle",
                "queued_count": 2,
                "dispatch_available": True,
                "next_candidate": {
                    "project_id": "gb10-job",
                    "project_name": "GB10 job",
                },
            }
        ]
        movement = movement_diagnosis(
            flags={"queue_paused": False, "maintenance_mode": True},
            worker_lanes=lanes,
            paper_pipeline={},
        )
        action = primary_operator_action(worker_lanes=lanes, movement=movement)
        self.assertIsNotNone(action)
        assert action is not None
        self.assertEqual(action["kind"], "open_blocker")
        self.assertEqual(action["blocker_kind"], "maintenance_mode")

    def test_feed_lane_when_no_dispatch(self) -> None:
        lanes = [
            {
                "machine_target": "gb10",
                "worker_role": "gpu_worker",
                "status": "idle",
                "queued_count": 0,
                "dispatch_available": False,
                "feed_pressure": {"next_autopilot_action": "generate_candidate"},
            }
        ]
        movement = {
            "status": "ready",
            "primary_reason": "No dispatch blocker.",
            "blockers": [],
        }
        action = primary_operator_action(worker_lanes=lanes, movement=movement)
        self.assertIsNotNone(action)
        assert action is not None
        self.assertEqual(action["kind"], "feed_lanes")

    def test_open_blocker_when_blocked(self) -> None:
        lanes = [
            {
                "machine_target": "gb10",
                "worker_role": "gpu_worker",
                "status": "idle",
                "queued_count": 1,
                "dispatch_available": False,
            }
        ]
        movement = movement_diagnosis(
            flags={"queue_paused": True, "maintenance_mode": False},
            worker_lanes=lanes,
            paper_pipeline={},
        )
        action = primary_operator_action(worker_lanes=lanes, movement=movement)
        self.assertIsNotNone(action)
        assert action is not None
        self.assertEqual(action["kind"], "open_blocker")

    def test_open_blocker_beats_feed_when_movement_blocked(self) -> None:
        lanes = [
            {
                "machine_target": "gb10",
                "worker_role": "gpu_worker",
                "status": "idle",
                "queued_count": 0,
                "dispatch_available": False,
                "feed_pressure": {"next_autopilot_action": "generate_candidate"},
            }
        ]
        movement = movement_diagnosis(
            flags={"queue_paused": True, "maintenance_mode": False},
            worker_lanes=lanes,
            paper_pipeline={},
        )
        action = primary_operator_action(worker_lanes=lanes, movement=movement)
        self.assertIsNotNone(action)
        assert action is not None
        self.assertEqual(action["kind"], "open_blocker")

    def test_returns_none_when_healthy_and_idle(self) -> None:
        lanes = [
            {
                "machine_target": "gb10",
                "worker_role": "gpu_worker",
                "status": "active",
                "queued_count": 0,
                "dispatch_available": False,
                "active_item": {"project_id": "active"},
            }
        ]
        movement = movement_diagnosis(
            flags={"queue_paused": False, "maintenance_mode": False},
            worker_lanes=lanes,
            paper_pipeline={},
        )
        self.assertIsNone(
            primary_operator_action(worker_lanes=lanes, movement=movement)
        )


if __name__ == "__main__":
    unittest.main()
