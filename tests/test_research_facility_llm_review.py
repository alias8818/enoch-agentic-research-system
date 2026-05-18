from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
import sys

import pytest

from enoch_control_plane.enoch_core.store import IdempotencyConflict
from scripts import research_facility_llm_review


def test_llm_review_budget_checks_weekly_percent(monkeypatch):
    payload = {
        "weeklyTokenLimit": {"remainingCredits": "$100.00", "percentRemaining": 24.9},
        "rollingFiveHourLimit": {"remaining": 2000, "max": 2500, "limited": False},
        "subscription": {"limit": 2500, "requests": 0},
    }
    monkeypatch.setattr(research_facility_llm_review.research_provider_budget, "fetch_json", lambda *args, **kwargs: payload)

    result = research_facility_llm_review.budget_status(
        base_url="https://synthetic.int.exe.xyz",
        estimated_requests=1,
        reserve_requests=5,
        min_remaining_credits=10.0,
        min_rolling_remaining=150,
        min_weekly_percent_remaining=25.0,
        timeout=10,
    )

    assert result["ok"] is False
    assert result["weekly_percent_remaining"] == 24.9
    assert "weekly percent remaining" in "; ".join(result["failures"])


def test_llm_review_normalizes_valid_decisions_only():
    batch = [
        {"candidate": {"candidate_id": "a"}, "janitor_action": {}},
        {"candidate": {"candidate_id": "b"}, "janitor_action": {}},
    ]
    raw = {
        "decisions": [
            {"candidate_id": "a", "decision": "admit", "confidence": "high", "reason": "specific", "rewrite_notes": ""},
            {"candidate_id": "b", "decision": "nonsense", "confidence": "high"},
            {"candidate_id": "c", "decision": "reject", "confidence": "high"},
        ]
    }

    decisions = research_facility_llm_review.normalize_decisions(raw, batch)

    assert decisions == [
        {"candidate_id": "a", "decision": "admit", "confidence": "high", "reason": "specific", "rewrite_notes": ""},
        {
            "candidate_id": "b",
            "decision": "keep_for_later",
            "confidence": "low",
            "reason": "LLM review omitted a valid decision; deferred fail-closed for later reconsideration.",
            "rewrite_notes": "",
        },
    ]


def test_llm_review_fills_missing_decisions_as_deferred():
    batch = [
        {"candidate": {"candidate_id": "a"}, "janitor_action": {}},
        {"candidate": {"candidate_id": "b"}, "janitor_action": {}},
    ]
    raw = {"decisions": [{"candidate_id": "a", "decision": "reject", "confidence": "medium", "reason": "duplicate"}]}

    decisions = research_facility_llm_review.normalize_decisions(raw, batch)

    assert [item["candidate_id"] for item in decisions] == ["a", "b"]
    assert decisions[1]["decision"] == "keep_for_later"
    assert decisions[1]["confidence"] == "low"


def test_llm_review_prompt_contains_allowed_decisions():
    prompt = research_facility_llm_review.build_review_prompt([
        {
            "candidate": {
                "candidate_id": "a",
                "title": "Candidate A",
                "hypothesis": "A specific hypothesis.",
                "mechanism": "A bounded mechanism.",
                "baseline_to_beat": "GPT-2 small baseline.",
            },
            "janitor_action": {"dispatch_priority": {"dispatch_priority_score": 65.0}},
        }
    ])

    assert "admit|rewrite_contract|keep_for_later|reject" in prompt
    assert "Candidate A" in prompt
    assert "proxy" in prompt.lower()


def test_llm_review_maps_non_admit_decisions_to_candidate_statuses():
    assert research_facility_llm_review._candidate_status_for_decision({"decision": "reject", "confidence": "low"}) == "rejected"
    assert research_facility_llm_review._candidate_status_for_decision({"decision": "rewrite_contract", "confidence": "high"}) == "rewrite_needed"
    assert research_facility_llm_review._candidate_status_for_decision({"decision": "keep_for_later", "confidence": "medium"}) == "deferred"


def test_llm_review_low_confidence_admit_is_deferred_not_admitted():
    assert research_facility_llm_review._candidate_status_for_decision({"decision": "admit", "confidence": "low"}) == "deferred"
    assert research_facility_llm_review._candidate_status_for_decision({"decision": "admit", "confidence": "medium"}) == "admitted"


def test_llm_review_cli_exposes_stored_decision_backfill_flags():
    parser = research_facility_llm_review.build_arg_parser()
    args = parser.parse_args([
        "--database-url",
        "postgresql:///enoch_control",
        "--apply",
        "--apply-stored-decisions-only",
        "--stored-decision-limit",
        "25",
    ])

    assert args.apply is True
    assert args.apply_stored_decisions_only is True
    assert args.stored_decision_limit == 25


def test_llm_review_record_conflicts_on_reused_event_key_with_different_identity(monkeypatch):
    decision = {"candidate_id": "candidate-1", "decision": "keep_for_later", "confidence": "medium", "reason": "later", "rewrite_notes": ""}
    batch = [{"candidate": {"candidate_id": "candidate-1"}, "janitor_action": {}}]

    class Cursor:
        rowcount = 1
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def execute(self, sql, params=()):
            normalized = " ".join(str(sql).lower().split())
            if normalized.startswith("set search_path"):
                return self
            if normalized.startswith("select event_id"):
                self._fetchone = {
                    "event_id": 12,
                    "event_type": "research.janitor.other",
                    "entity_type": "research_candidate",
                    "entity_id": "candidate-1",
                    "payload_hash": "same-hash-not-enough",
                }
                return self
            if normalized.startswith("insert into control_events"):
                raise AssertionError("conflicting replay must not insert")
            if normalized.startswith("update research_candidates"):
                return self
            if normalized.startswith("insert into research_admissions"):
                return self
            raise AssertionError(normalized)
        def fetchone(self):
            return getattr(self, "_fetchone", None)

    class Conn:
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def cursor(self): return Cursor()

    monkeypatch.setitem(sys.modules, "psycopg", SimpleNamespace(connect=lambda *_args, **_kwargs: Conn()))

    with pytest.raises(IdempotencyConflict):
        research_facility_llm_review.record_review(
            "postgres://example",
            decisions=[decision],
            batch=batch,
            requested_by="unit",
            provider_model="model",
            dry_run=False,
        )
