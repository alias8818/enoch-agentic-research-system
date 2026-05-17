from __future__ import annotations

import json
import unittest
import tempfile
from pathlib import Path

from enoch_control_plane.enoch_core.logic import (
    assert_single_active_lane,
    bounded_useful_signal_row_gate,
    draft_candidate_payload,
    eligible_paper_draft_candidates,
    eligible_paper_polish_candidates,
    followup_candidate_from_decision_payload,
    paper_draft_decision_gate,
    project_decision_payload,
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


    def test_wake_ready_completion_is_paper_draft_candidate(self) -> None:
        queue_rows = [{
            "project_id": "idea-wake",
            "project_name": "Wake Ready",
            "project_dir": "idea-wake",
            "status": "completed",
            "last_run_state": "wake_ready",
            "next_action_hint": "draft_paper_or_select_next_project",
            "current_run_id": "run-wake",
        }]
        candidates = eligible_paper_draft_candidates(queue_rows, [])
        self.assertEqual([row["project_id"] for row in candidates], ["idea-wake"])

    def test_bounded_paper_ready_candidate_sorts_before_raw_recent_no_paper(self) -> None:
        queue_rows = [
            {
                "project_id": "raw-recent",
                "project_name": "Raw Recent",
                "project_dir": "raw-recent",
                "status": "completed",
                "last_run_state": "wake_ready",
                "next_action_hint": "draft_paper_or_select_next_project",
                "current_run_id": "run-raw",
                "updatedAt": "2026-05-16T18:09:00Z",
            },
            {
                "project_id": "scout-ready",
                "project_name": "Scout Ready",
                "project_dir": "scout-ready",
                "status": "completed",
                "last_run_state": "wake_ready",
                "next_action_hint": "draft_paper_or_select_next_project",
                "current_run_id": "run-scout",
                "updatedAt": "2026-05-16T14:01:00Z",
                "bounded_paper_ready": True,
            },
        ]
        candidates = eligible_paper_draft_candidates(queue_rows, [])
        self.assertEqual([row["project_id"] for row in candidates], ["scout-ready", "raw-recent"])

    def test_draft_candidate_payload_preserves_legacy_run_id_fallback(self) -> None:
        candidate = {
            "project_id": "idea-legacy",
            "project_name": "Legacy Run Field",
            "project_dir": "idea-legacy",
            "run_id": "run-legacy",
            "notion_page_url": "https://www.notion.so/example",
        }
        payload = draft_candidate_payload(candidate)
        self.assertEqual(payload["run_id"], "run-legacy")
        self.assertEqual(payload["draft_payload"]["run_id"], "run-legacy")

    def test_wake_ready_canonical_positive_decision_artifacts_pass_paper_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".enoch").mkdir()
            (root / ".enoch" / "project_decision.json").write_text('{"decision":"finalize_positive"}\n', encoding="utf-8")
            gate = paper_draft_decision_gate(root)
            self.assertTrue(gate["eligible"])

    def test_legacy_omx_positive_decision_artifacts_remain_supported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".omx").mkdir()
            (root / ".omx" / "project_decision.json").write_text('{"decision":"finalize_positive"}\n', encoding="utf-8")
            gate = paper_draft_decision_gate(root)
            self.assertTrue(gate["eligible"])

    def test_paper_draft_gate_rejects_positive_near_synonyms(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".omx").mkdir()
            for decision in ("promising_continue", "partial_viable", "promising_synthetic_positive", "proceed"):
                (root / ".omx" / "project_decision.json").write_text(json.dumps({"decision": decision}) + "\n", encoding="utf-8")
                gate = paper_draft_decision_gate(root)
                self.assertFalse(gate["eligible"], decision)

    def test_project_decision_payload_and_followup_metadata_are_separate_from_paper_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".omx").mkdir()
            payload = {
                "project_decision": "finalize_negative",
                "hypothesis_status": "mixed",
                "followup_recommended": True,
                "followup_type": "branch",
                "followup_title": "Test the adjacent runtime path",
                "followup_hypothesis": "A narrower runtime path may pass where the broad path failed.",
                "followup_required_evidence": ["runtime trace", "baseline comparison"],
                "followup_success_threshold": "beats baseline on two seeds",
                "followup_stop_condition": "stop if runtime trace reproduces the same failure",
            }
            (root / ".omx" / "project_decision.json").write_text(json.dumps(payload) + "\n", encoding="utf-8")

            self.assertEqual(project_decision_payload(root)["project_decision"], "finalize_negative")
            followup = followup_candidate_from_decision_payload(project_decision_payload(root))
            self.assertTrue(followup["followup_recommended"])
            self.assertEqual(followup["followup_type"], "branch")
            self.assertEqual(followup["followup_required_evidence"], ["runtime trace", "baseline comparison"])
            self.assertFalse(paper_draft_decision_gate(root)["eligible"])

    def test_bounded_useful_signal_can_pass_scoped_paper_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".enoch").mkdir()
            payload = {
                "project_decision": "finalize_negative",
                "research_outcome": "useful_signal",
                "bounded_paper_ready": True,
                "hypothesis_status": "supported",
                "evidence_strength": "moderate",
                "claim_scope": "GPT-2-small-class toy validation with a dense baseline.",
                "scale_limits": "No 7B or multi-node training was run.",
            }
            (root / ".enoch" / "project_decision.json").write_text(json.dumps(payload) + "\n", encoding="utf-8")
            gate = paper_draft_decision_gate(root)
            self.assertTrue(gate["eligible"])
            self.assertEqual(gate["reason"], "bounded useful signal is paper-scoped")

    def test_bounded_useful_signal_row_gate_accepts_paper_scout_db_state(self) -> None:
        gate = bounded_useful_signal_row_gate({
            "project_decision": "finalize_negative",
            "research_outcome": "useful_signal",
            "bounded_paper_ready": True,
            "hypothesis_status": "supported",
            "evidence_strength": "moderate",
            "claim_scope": "GPT-2-small-class direct local result with baseline comparison.",
            "scale_limits": "No datacenter-scale or long-horizon training was run.",
        })
        self.assertTrue(gate["eligible"])
        self.assertEqual(gate["source"], "control_plane_row")

    def test_bounded_useful_signal_row_gate_requires_explicit_ready_flag(self) -> None:
        gate = bounded_useful_signal_row_gate({
            "research_outcome": "useful_signal",
            "bounded_paper_ready": False,
            "hypothesis_status": "supported",
            "evidence_strength": "moderate",
            "claim_scope": "Scoped claim.",
            "scale_limits": "Scale limit.",
        })
        self.assertFalse(gate["eligible"])

    def test_useful_signal_without_scope_remains_no_paper(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".enoch").mkdir()
            payload = {
                "project_decision": "finalize_negative",
                "research_outcome": "useful_signal",
                "bounded_paper_ready": True,
                "hypothesis_status": "supported",
                "evidence_strength": "moderate",
                "scale_limits": "No large-scale training was run.",
            }
            (root / ".enoch" / "project_decision.json").write_text(json.dumps(payload) + "\n", encoding="utf-8")
            gate = paper_draft_decision_gate(root)
            self.assertFalse(gate["eligible"])

    def test_wake_ready_negative_decision_artifacts_fail_paper_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".omx").mkdir()
            (root / ".omx" / "project_decision.json").write_text('{"decision":"negative_result"}\n', encoding="utf-8")
            gate = paper_draft_decision_gate(root)
            self.assertFalse(gate["eligible"])


    def test_paper_draft_gate_rejects_negated_positive_words(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".omx").mkdir()
            for decision in ("not_positive", "nonpositive", "non-positive"):
                (root / ".omx" / "project_decision.json").write_text(f'{{"decision":"{decision}"}}\n', encoding="utf-8")
                gate = paper_draft_decision_gate(root)
                self.assertFalse(gate["eligible"], decision)

    def test_paper_draft_gate_requires_exact_supported_token(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".omx").mkdir()
            (root / ".omx" / "project_decision.json").write_text('{"decision":"continue","status":"unsupported"}\n', encoding="utf-8")
            gate = paper_draft_decision_gate(root)
            self.assertFalse(gate["eligible"])
            (root / ".omx" / "project_decision.json").write_text('{"decision":"continue","status":"not_supported"}\n', encoding="utf-8")
            gate = paper_draft_decision_gate(root)
            self.assertFalse(gate["eligible"])

    def test_paper_draft_gate_rejects_continue_even_when_supported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".enoch").mkdir()
            payload = {
                "project_decision": "continue",
                "hypothesis_status": "supported",
                "confidence": "medium",
                "evidence_strength": "moderate",
                "recommended_next_action": "Run a direct target-stack validation before any paper.",
            }
            (root / ".enoch" / "project_decision.json").write_text(json.dumps(payload) + "\n", encoding="utf-8")
            gate = paper_draft_decision_gate(root)
            self.assertFalse(gate["eligible"])
            self.assertEqual(gate["reason"], "continue decision is not paper-positive")

    def test_paper_draft_candidate_excludes_existing_run_even_for_new_project(self) -> None:
        queue_rows = [{
            "project_id": "p-new",
            "project_name": "Duplicate Run",
            "project_dir": "p-new",
            "status": "completed",
            "last_run_state": "wake_ready",
            "next_action_hint": "draft_paper_or_select_next_project",
            "current_run_id": "r-existing",
        }]
        paper_rows = [{"project_id": "p-old", "run_id": "r-existing", "paper_id": "p-old:r-existing:arxiv_draft"}]
        self.assertEqual(eligible_paper_draft_candidates(queue_rows, paper_rows), [])

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

    def test_reconciling_states_count_as_active_lane(self) -> None:
        ok, message = assert_single_active_lane([{"status": "wake_received"}, {"status": "reconciling"}])
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


def test_finalize_positive_proxy_useful_signal_without_bounded_ready_is_not_paper_ready() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / ".enoch").mkdir()
        payload = {
            "project_decision": "finalize_positive",
            "research_outcome": "useful_signal",
            "bounded_paper_ready": False,
            "hypothesis_status": "supported",
            "evidence_strength": "weak",
            "claim_scope": "short proxy smoke only",
            "scale_limits": "no direct medium or full validation",
        }
        (root / ".enoch" / "project_decision.json").write_text(json.dumps(payload) + "\n", encoding="utf-8")
        gate = paper_draft_decision_gate(root)
        assert gate["eligible"] is False
        assert "bounded" in gate["reason"] or "proxy" in gate["reason"] or "useful" in gate["reason"]


def test_enoch_core_store_closes_sqlite_connections_after_context(monkeypatch) -> None:
    from pathlib import Path
    from enoch_control_plane.enoch_core.store import EnochCoreStore

    closed = 0

    class FakeConnection:
        row_factory = None
        def execute(self, *_args, **_kwargs):
            return self
        def executescript(self, *_args, **_kwargs):
            return self
        def fetchall(self):
            return []
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            return None
        def close(self):
            nonlocal closed
            closed += 1

    monkeypatch.setattr("enoch_control_plane.enoch_core.store.sqlite3.connect", lambda *_args, **_kwargs: FakeConnection())
    EnochCoreStore(Path("/tmp/fake-enoch-core.sqlite3"))

    assert closed == 1
