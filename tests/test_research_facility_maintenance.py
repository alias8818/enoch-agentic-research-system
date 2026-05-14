from __future__ import annotations

from datetime import datetime, timedelta, timezone

from scripts import research_facility, research_facility_maintenance


def _row(**overrides: object) -> dict[str, object]:
    now = datetime(2026, 5, 14, tzinfo=timezone.utc)
    row: dict[str, object] = {
        "candidate_id": "borderline-followup",
        "generation_mode": "followup_from_negative",
        "status": "needs_review",
        "title": "Borderline Follow-up",
        "category": "long-context",
        "source_urls": ["https://arxiv.org/abs/2605.06546"],
        "parent_project_id": "prior-negative",
        "total_score": 71.6,
        "novelty_score": 8,
        "feasibility_score": 7,
        "accessibility_score": 8,
        "falsifiability_score": 8,
        "created_at": (now - timedelta(days=2)).isoformat(),
        "updated_at": (now - timedelta(days=1)).isoformat(),
        "similar_prior_projects": [],
        "novelty_comparison": "Different branch target and metric.",
        "estimated_runtime_class": "small",
        "expected_token_budget": "small",
    }
    row.update(overrides)
    return row


def test_dispatch_priority_spreads_close_admission_scores() -> None:
    now = datetime(2026, 5, 14, tzinfo=timezone.utc)
    fresh = _row(
        candidate_id="fresh",
        generation_mode="fresh_grounded",
        source_urls=["https://example.com/post"],
        parent_project_id="",
        total_score=72.0,
    )
    followup = _row(candidate_id="followup", total_score=71.6)

    fresh_priority = research_facility.dispatch_priority_score(fresh, category_counts={"long-context": 2}, now=now)
    followup_priority = research_facility.dispatch_priority_score(followup, category_counts={"long-context": 2}, now=now)

    assert followup_priority > fresh_priority
    assert followup_priority - fresh_priority >= 8


def test_janitor_promotes_strong_borderline_followup() -> None:
    actions = research_facility_maintenance.classify_rows(
        [_row(total_score=71.6)],
        policy=research_facility_maintenance.JanitorPolicy(),
        now=datetime(2026, 5, 14, tzinfo=timezone.utc),
    )

    assert actions[0]["action"] == "promote"
    assert actions[0]["dispatch_priority"]["lineage_bonus"] >= 8


def test_janitor_rejects_stale_weak_rows_without_auto_applying() -> None:
    old = datetime(2026, 5, 1, tzinfo=timezone.utc).isoformat()
    actions = research_facility_maintenance.classify_rows(
        [
            _row(
                candidate_id="weak-old",
                generation_mode="fresh_grounded",
                source_urls=[],
                parent_project_id="",
                total_score=63.0,
                novelty_score=5,
                falsifiability_score=5,
                created_at=old,
                updated_at=old,
            )
        ],
        policy=research_facility_maintenance.JanitorPolicy(),
        now=datetime(2026, 5, 14, tzinfo=timezone.utc),
    )

    assert actions[0]["action"] == "reject"
    report = research_facility_maintenance.build_report([], actions, applied=False, apply_result=None)
    assert report["dry_run"] is True
    assert report["action_counts"] == {"reject": 1}


def test_janitor_keeps_saturated_fresh_rows_out_of_promote_lane() -> None:
    rows = [_row(candidate_id=f"candidate-{idx}", generation_mode="fresh_grounded", parent_project_id="", source_urls=["https://example.com"], total_score=71.8) for idx in range(20)]

    actions = research_facility_maintenance.classify_rows(
        rows,
        policy=research_facility_maintenance.JanitorPolicy(),
        now=datetime(2026, 5, 14, tzinfo=timezone.utc),
    )

    assert all(action["action"] == "rewrite_suggested" for action in actions)


def test_janitor_does_not_promote_borderline_fresh_without_priority_signal() -> None:
    actions = research_facility_maintenance.classify_rows(
        [
            _row(
                candidate_id="borderline-fresh",
                generation_mode="fresh_grounded",
                source_urls=["https://example.com/post"],
                parent_project_id="",
                total_score=71.9,
            )
        ],
        policy=research_facility_maintenance.JanitorPolicy(),
        now=datetime(2026, 5, 14, tzinfo=timezone.utc),
    )

    assert actions[0]["action"] == "rewrite_suggested"
