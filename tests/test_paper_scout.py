from types import SimpleNamespace
import sys

import pytest

from enoch_control_plane.enoch_core.store import IdempotencyConflict
from scripts import paper_scout
from scripts.paper_scout import ScoutRow, scout


def row(payload):
    return ScoutRow(
        decision_id=1,
        project_id="p1",
        project_name="P1",
        run_id="r1",
        decided_at="2026-05-16T00:00:00Z",
        payload={"project_decision": payload},
    )


def test_scout_marks_scoped_useful_signal_eligible():
    payload = {
        "project_decision": "finalize_negative",
        "research_outcome": "useful_signal",
        "hypothesis_status": "supported",
        "evidence_strength": "moderate",
        "bounded_paper_ready": False,
        "compute_scale_blocked": False,
        "claim_scope": "On GPT-2-small Wikitext-2 with three fixed seeds, method A beats baseline B under a scoped local benchmark.",
        "scale_limits": "Single local model and public dataset only; no larger model family, production serving, or long-context task validation.",
        "useful_signal_summary": "Method A reached 1.25x speed and 0.04 lower loss versus baseline B across 3 seeds and 128 prompts.",
        "stop_reason": "No-paper result only because broader publication-grade validation is still missing.",
        "recommended_next_action": "Prepare a scoped bounded paper; do not claim broad production readiness.",
    }
    result = scout([row(payload)], threshold=80)[0]
    assert result.eligible
    assert result.score >= 80


def test_scout_blocks_compute_scale_signal():
    payload = {
        "project_decision": "finalize_negative",
        "research_outcome": "useful_signal",
        "hypothesis_status": "supported",
        "evidence_strength": "strong",
        "bounded_paper_ready": False,
        "compute_scale_blocked": True,
        "claim_scope": "On GPT-2-small Wikitext-2 with three fixed seeds, method A beats baseline B under a scoped local benchmark.",
        "scale_limits": "Single local model and public dataset only; no larger model family, production serving, or long-context task validation.",
        "useful_signal_summary": "Method A reached 1.25x speed and 0.04 lower loss versus baseline B across 3 seeds and 128 prompts.",
        "stop_reason": "No-paper result only because broader publication-grade validation is still missing.",
        "recommended_next_action": "Prepare a scoped bounded paper; do not claim broad production readiness.",
    }
    result = scout([row(payload)], threshold=80)[0]
    assert not result.eligible
    assert "compute-scale blocked" in result.blockers


def test_apply_ready_conflicts_on_reused_event_key_with_different_identity(monkeypatch):
    payload = {
        "project_decision": "finalize_negative",
        "research_outcome": "useful_signal",
        "hypothesis_status": "supported",
        "evidence_strength": "moderate",
        "bounded_paper_ready": False,
        "compute_scale_blocked": False,
        "claim_scope": "On GPT-2-small Wikitext-2 with three fixed seeds, method A beats baseline B under a scoped local benchmark.",
        "scale_limits": "Single local model and public dataset only; no larger model family, production serving, or long-context task validation.",
        "useful_signal_summary": "Method A reached 1.25x speed and 0.04 lower loss versus baseline B across 3 seeds and 128 prompts.",
        "stop_reason": "No-paper result only because broader publication-grade validation is still missing.",
        "recommended_next_action": "Prepare a scoped bounded paper; do not claim broad production readiness.",
    }
    result = scout([row(payload)], threshold=80)[0]
    event_payload = {
        "decision_id": result.row.decision_id,
        "project_id": result.row.project_id,
        "run_id": result.row.run_id,
        "score": result.score,
        "reasons": result.reasons,
        "effect": "bounded_paper_ready_true",
        "requested_by": "unit",
    }
    event_json = paper_scout._canonical_event_json(event_payload)  # noqa: SLF001 - event invariant fixture

    class Cursor:
        rowcount = 1
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def execute(self, sql, params=()):
            normalized = " ".join(str(sql).lower().split())
            if normalized.startswith("select event_id"):
                self._fetchone = {
                    "event_id": 9,
                    "event_type": "paper_scout.other",
                    "entity_type": "project",
                    "entity_id": "p1",
                    "payload_hash": paper_scout._event_hash(event_json),  # noqa: SLF001 - event invariant fixture
                }
            elif normalized.startswith("insert into control_events"):
                raise AssertionError("conflicting replay must not insert")
            return self
        def fetchone(self):
            return getattr(self, "_fetchone", None)

    class Conn:
        committed = False
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def cursor(self): return Cursor()
        def commit(self): self.committed = True

    monkeypatch.setitem(sys.modules, "psycopg", SimpleNamespace(connect=lambda *_args, **_kwargs: Conn()))

    with pytest.raises(IdempotencyConflict):
        paper_scout.apply_ready("postgres://example", [result], max_apply=1, requested_by="unit")
