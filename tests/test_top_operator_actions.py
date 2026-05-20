from __future__ import annotations

import unittest

from enoch_control_plane.control_plane.read_models import top_operator_actions


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

    def test_dispatch_only_when_no_other_actions_and_idle_lane(self) -> None:
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
        self.assertEqual(len(idle_with_queue), 1)
        self.assertEqual(idle_with_queue[0]["kind"], "dispatch_next")
        self.assertEqual(idle_with_queue[0]["action_hash"], "#queue:queued")

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


if __name__ == "__main__":
    unittest.main()
