from __future__ import annotations

import unittest

from omx_wake_gate.enoch_core.logic import (
    assert_single_active_lane,
    eligible_paper_draft_candidates,
    eligible_paper_polish_candidates,
    queue_projection,
    validate_branch_queued,
)


class EnochCoreLogicTests(unittest.TestCase):
    def test_paper_draft_candidate_excludes_existing_project_and_run(self) -> None:
        queue_rows = [
            {
                "project_id": "p1",
                "project_name": "Already Drafted",
                "status": "completed",
                "last_run_state": "finalize_positive",
                "current_run_id": "r1",
            },
            {
                "project_id": "p2",
                "project_name": "New Useful Project",
                "status": "completed",
                "last_run_state": "finalize_positive",
                "current_run_id": "r2",
                "updatedAt": "2026-04-23T00:01:00Z",
            },
        ]
        paper_rows = [{"project_id": "p1", "run_id": "r1", "paper_id": "p1:r1:arxiv_draft"}]
        candidates = eligible_paper_draft_candidates(queue_rows, paper_rows)
        self.assertEqual([row["project_id"] for row in candidates], ["p2"])

    def test_paper_draft_candidate_noops_when_manual_review_required(self) -> None:
        queue_rows = [
            {
                "project_id": "p1",
                "project_name": "Manual Review",
                "status": "completed",
                "last_run_state": "finalize_positive",
                "current_run_id": "r1",
                "manual_review_required": True,
            }
        ]
        self.assertEqual(eligible_paper_draft_candidates(queue_rows, []), [])

    def test_paper_polish_candidate_excludes_existing_publication(self) -> None:
        paper_rows = [
            {
                "paper_id": "p1:r1:arxiv_draft",
                "project_id": "p1",
                "paper_status": "draft_review",
                "draft_markdown_path": "papers/r1/paper.md",
            },
            {
                "paper_id": "p1:r1:arxiv_draft:publication_v1",
                "project_id": "p1",
                "paper_status": "publication_draft",
                "paper_type": "publication_v1",
            },
            {
                "paper_id": "p2:r2:arxiv_draft",
                "project_id": "p2",
                "paper_status": "draft_review",
                "draft_markdown_path": "papers/r2/paper.md",
            },
        ]
        candidates = eligible_paper_polish_candidates(paper_rows)
        self.assertEqual([row["project_id"] for row in candidates], ["p2"])

    def test_single_active_lane_invariant(self) -> None:
        ok, _ = assert_single_active_lane([{"status": "awaiting_wake"}])
        self.assertTrue(ok)
        ok, message = assert_single_active_lane([{"status": "awaiting_wake"}, {"status": "running"}])
        self.assertFalse(ok)
        self.assertIn("multiple active", message)

    def test_branch_queued_requires_concrete_successor_evidence(self) -> None:
        ok, _ = validate_branch_queued({"next_action_hint": "branch_queued", "last_result_summary": ""})
        self.assertFalse(ok)
        ok, _ = validate_branch_queued(
            {
                "next_action_hint": "branch_queued",
                "last_result_summary": "Branch successor queued: idea-12345678abcdef\nNotion: https://www.notion.so/example",
            }
        )
        self.assertTrue(ok)

    def test_queue_projection_counts_candidates_and_warnings(self) -> None:
        projection = queue_projection(
            {
                "source": "test",
                "captured_at": "now",
                "queue_rows": [
                    {
                        "project_id": "p1",
                        "status": "completed",
                        "last_run_state": "finalize_positive",
                        "current_run_id": "r1",
                    },
                    {"project_id": "active", "status": "running"},
                ],
                "paper_rows": [
                    {
                        "paper_id": "p2:r2:arxiv_draft",
                        "project_id": "p2",
                        "paper_status": "draft_review",
                        "draft_markdown_path": "papers/r2/paper.md",
                    }
                ],
            }
        )
        self.assertEqual(projection["status_counts"]["completed"], 1)
        self.assertEqual(projection["draft_candidate_count"], 1)
        self.assertEqual(projection["polish_candidate_count"], 1)
        self.assertEqual(len(projection["active_rows"]), 1)


if __name__ == "__main__":
    unittest.main()
