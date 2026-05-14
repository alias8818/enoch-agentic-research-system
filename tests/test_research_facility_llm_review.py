from __future__ import annotations

from datetime import datetime, timezone

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

    assert decisions == [{"candidate_id": "a", "decision": "admit", "confidence": "high", "reason": "specific", "rewrite_notes": ""}]


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
