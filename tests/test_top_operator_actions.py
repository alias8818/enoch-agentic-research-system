from __future__ import annotations

import unittest

from enoch_control_plane.control_plane.read_models import _safe_count, top_operator_actions


class TopOperatorActionsTests(unittest.TestCase):
    def test_idle_returns_empty_list(self) -> None:
        actions = top_operator_actions(
            operator_counts={"needs_attention": 0},
            paper_pipeline={"write_needed": 0, "finalize_needed": 0, "publish_ready": 0},
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
                "next_write_candidate": {"project_id": "p1", "project_name": "Alpha project"},
                "next_publish_candidate": {"paper_id": "paper-9", "project_name": "Bravo paper"},
            },
            investigation_pipeline={"ranked_followup_ready": 0},
            counts={"active": 1, "queued": 0},
        )
        kinds = [a["kind"] for a in actions]
        self.assertEqual(kinds, ["write_paper", "finalize_paper", "publish_paper"])
        self.assertEqual(actions[0]["priority"], 1)
        self.assertEqual(actions[2]["priority"], 3)
        self.assertEqual(actions[0]["target"], {"project_id": "p1", "name": "Alpha project"})
        self.assertEqual(actions[0]["action_hash"], "#papers?status=publication_draft")
        self.assertEqual(actions[2]["action_hash"], "#corpus")
        self.assertIn("Alpha project", actions[0]["summary"])
        self.assertIn("Bravo paper", actions[2]["summary"])

    def test_followup_promoted_when_pipeline_clear(self) -> None:
        actions = top_operator_actions(
            operator_counts={"needs_attention": 0},
            paper_pipeline={"write_needed": 0, "finalize_needed": 0, "publish_ready": 0},
            investigation_pipeline={
                "ranked_followup_ready": 2,
                "next_ranked_followup_candidate": {"project_id": "p7", "followup_title": "Adjacent FFT"},
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
            paper_pipeline={"write_needed": 0, "finalize_needed": 0, "publish_ready": 0},
            investigation_pipeline={"ranked_followup_ready": 0},
            counts={"active": 1, "queued": 5},
        )
        self.assertEqual(with_active, [])

        idle_with_queue = top_operator_actions(
            operator_counts={"needs_attention": 0},
            paper_pipeline={"write_needed": 0, "finalize_needed": 0, "publish_ready": 0},
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
            paper_pipeline={"write_needed": 0, "finalize_needed": 0, "publish_ready": 0},
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
            paper_pipeline={"write_needed": 0, "finalize_needed": 0, "publish_ready": 0},
            investigation_pipeline={"ranked_followup_ready": 0},
            counts={"active": 0, "queued": 7},
            worker_lanes=[
                {"machine_target": "cpu-proxmox-1", "dispatch_available": False, "queued_count": 3},
                {"machine_target": "gb10", "dispatch_available": False, "queued_count": 4},
            ],
        )
        self.assertEqual(actions, [])

    def test_results_are_bounded(self) -> None:
        actions = top_operator_actions(
            operator_counts={"needs_attention": 1},
            paper_pipeline={"write_needed": 1, "finalize_needed": 1, "publish_ready": 1},
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
            paper_pipeline={"write_needed": "🌶", "finalize_needed": "n/a", "publish_ready": "  "},
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
            paper_pipeline={"write_needed": False, "finalize_needed": True, "publish_ready": False},
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
            paper_pipeline={"write_needed": -1, "finalize_needed": -2, "publish_ready": -3},
            investigation_pipeline={"ranked_followup_ready": -10},
            counts={"active": -1, "queued": -1, "blocked": -1},
        )
        self.assertEqual(empty, [])

        only_write = top_operator_actions(
            operator_counts={"needs_attention": -2},
            paper_pipeline={"write_needed": 3, "finalize_needed": -2, "publish_ready": -1},
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
            paper_pipeline={"write_needed": 1, "finalize_needed": 1, "publish_ready": 1},
            investigation_pipeline={"ranked_followup_ready": 1},
            counts={"active": 0, "queued": 1},
            limit="bad",  # type: ignore[arg-type]
        )
        self.assertEqual(len(actions), 3)
        self.assertEqual([a["priority"] for a in actions], [1, 2, 3])

    def test_negative_limit_returns_empty_list(self) -> None:
        actions = top_operator_actions(
            operator_counts={"needs_attention": 1},
            paper_pipeline={"write_needed": 1, "finalize_needed": 1, "publish_ready": 1},
            investigation_pipeline={"ranked_followup_ready": 1},
            counts={"active": 0, "queued": 1},
            limit=-7,
        )
        self.assertEqual(actions, [])

    def test_oversized_limit_is_capped(self) -> None:
        actions = top_operator_actions(
            operator_counts={"needs_attention": 1},
            paper_pipeline={"write_needed": 1, "finalize_needed": 1, "publish_ready": 1},
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
            paper_pipeline={"write_needed": 0, "finalize_needed": 0, "publish_ready": 0},
            investigation_pipeline={"ranked_followup_ready": 0},
            counts={"active": 0, "queued": 0},
            worker_lanes=[
                None,  # type: ignore[list-item]
                {"machine_target": "cpu-proxmox-1"},  # missing dispatch_available
                {"machine_target": "gb10", "dispatch_available": "yes please", "queued_count": "two"},
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


if __name__ == "__main__":
    unittest.main()
