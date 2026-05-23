from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import sys

import pytest

from enoch_control_plane.enoch_core.store import IdempotencyConflict
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

    fresh_priority = research_facility.dispatch_priority_score(
        fresh, category_counts={"long-context": 2}, now=now
    )
    followup_priority = research_facility.dispatch_priority_score(
        followup, category_counts={"long-context": 2}, now=now
    )

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
    report = research_facility_maintenance.build_report(
        [], actions, applied=False, apply_result=None
    )
    assert report["dry_run"] is True
    assert report["action_counts"] == {"reject": 1}


def test_janitor_keeps_saturated_fresh_rows_out_of_promote_lane() -> None:
    rows = [
        _row(
            candidate_id=f"candidate-{idx}",
            generation_mode="fresh_grounded",
            parent_project_id="",
            source_urls=["https://example.com"],
            total_score=71.8,
        )
        for idx in range(20)
    ]

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


def test_janitor_apply_skips_admission_when_promote_update_matches_no_rows(
    monkeypatch,
) -> None:
    admissions: list[tuple] = []
    events: list[tuple] = []

    class Cursor:
        rowcount = 0

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def execute(self, sql, params=()):
            normalized = " ".join(sql.lower().split())
            if normalized.startswith("set search_path"):
                self.rowcount = 0
            elif (
                normalized.startswith("update research_candidates")
                and "status = 'admitted'" in normalized
            ):
                self.rowcount = 0
            elif normalized.startswith("insert into research_admissions"):
                admissions.append(params)
                self.rowcount = 1
            elif normalized.startswith("select event_id"):
                self.rowcount = 0
                self._fetchone = None
            elif normalized.startswith("insert into control_events"):
                events.append(params)
                self.rowcount = 1

        def fetchone(self):
            return getattr(self, "_fetchone", None)

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def cursor(self):
            return Cursor()

    monkeypatch.setitem(
        sys.modules,
        "psycopg",
        SimpleNamespace(connect=lambda *_args, **_kwargs: Conn()),
    )

    result = research_facility_maintenance.apply_actions(
        "postgres://example",
        [
            {
                "candidate_id": "already-moved",
                "action": "promote",
                "reason": "race",
                "dispatch_priority": {},
            }
        ],
        requested_by="unit",
        apply_rejections=False,
    )

    assert result["promoted"] == 0
    assert result["admissions_inserted"] == 0
    assert result["events_inserted"] == 0
    assert admissions == []
    assert events == []


def test_janitor_non_mutating_events_allow_changed_observation_payloads(
    monkeypatch,
) -> None:
    action = {
        "candidate_id": "candidate-1",
        "action": "keep",
        "reason": "still reviewable",
        "dispatch_priority": {"age_days": 3.0},
    }
    old_payload = {
        "requested_by": "unit",
        "janitor_action": {**action, "dispatch_priority": {"age_days": 2.0}},
    }
    old_hash = research_facility_maintenance._payload_hash(old_payload)
    selected_keys: list[str] = []
    inserted_keys: list[str] = []

    class Cursor:
        rowcount = 0

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def execute(self, sql, params=()):
            normalized = " ".join(sql.lower().split())
            if normalized.startswith("set search_path"):
                return self
            if normalized.startswith("select event_id"):
                selected_keys.append(params[0])
                if params[0] == "research-janitor:keep:candidate-1":
                    self._fetchone = {
                        "event_id": 11,
                        "event_type": "research.janitor.keep",
                        "entity_type": "research_candidate",
                        "entity_id": "candidate-1",
                        "payload_hash": old_hash,
                    }
                else:
                    self._fetchone = None
                return self
            if normalized.startswith("insert into control_events"):
                inserted_keys.append(params[0])
                self.rowcount = 1
                return self
            raise AssertionError(normalized)

        def fetchone(self):
            return getattr(self, "_fetchone", None)

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def cursor(self):
            return Cursor()

    monkeypatch.setitem(
        sys.modules,
        "psycopg",
        SimpleNamespace(connect=lambda *_args, **_kwargs: Conn()),
    )

    result = research_facility_maintenance.apply_actions(
        "postgres://example",
        [action],
        requested_by="unit",
        apply_rejections=False,
    )

    assert result["events_inserted"] == 1
    assert selected_keys == [inserted_keys[0]]
    assert inserted_keys[0].startswith("research-janitor:keep:candidate-1:")


def test_janitor_apply_conflicts_on_reused_event_key_with_different_identity(
    monkeypatch,
) -> None:
    action = {
        "candidate_id": "candidate-1",
        "action": "promote",
        "reason": "admit now",
        "dispatch_priority": {"score": 90},
    }
    payload = {"requested_by": "unit", "janitor_action": action}
    existing_payload_hash = research_facility_maintenance._payload_hash(payload)

    class Cursor:
        rowcount = 0

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def execute(self, sql, params=()):
            normalized = " ".join(sql.lower().split())
            if normalized.startswith("set search_path"):
                return self
            if (
                normalized.startswith("update research_candidates")
                and "status = 'admitted'" in normalized
            ):
                self.rowcount = 1
                return self
            if normalized.startswith("select admission_id"):
                self._fetchone = None
                return self
            if normalized.startswith("insert into research_admissions"):
                self.rowcount = 1
                return self
            if normalized.startswith("select event_id"):
                assert params == ("research-janitor:promote:candidate-1",)
                self._fetchone = {
                    "event_id": 11,
                    "event_type": "research.janitor.keep",
                    "entity_type": "research_candidate",
                    "entity_id": "candidate-1",
                    "payload_hash": existing_payload_hash,
                }
                return self
            if normalized.startswith("insert into control_events"):
                raise AssertionError("conflicting replay must not insert a new event")
            raise AssertionError(normalized)

        def fetchone(self):
            return getattr(self, "_fetchone", None)

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def cursor(self):
            return Cursor()

    monkeypatch.setitem(
        sys.modules,
        "psycopg",
        SimpleNamespace(connect=lambda *_args, **_kwargs: Conn()),
    )

    with pytest.raises(IdempotencyConflict):
        research_facility_maintenance.apply_actions(
            "postgres://example",
            [action],
            requested_by="unit",
            apply_rejections=False,
        )


def test_janitor_apply_conflicts_on_reused_admission_key_with_different_identity(
    monkeypatch,
) -> None:
    action = {
        "candidate_id": "candidate-1",
        "action": "promote",
        "reason": "admit now",
        "dispatch_priority": {"score": 90},
    }

    class Cursor:
        rowcount = 0

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def execute(self, sql, params=()):
            normalized = " ".join(sql.lower().split())
            if normalized.startswith("set search_path"):
                return self
            if (
                normalized.startswith("update research_candidates")
                and "status = 'admitted'" in normalized
            ):
                self.rowcount = 1
                return self
            if normalized.startswith("select admission_id"):
                assert params == ("research-janitor:admit:candidate-1",)
                self._fetchone = {
                    "admission_id": 7,
                    "candidate_id": "candidate-1",
                    "admission_decision": "rejected",
                    "admission_reason": "old contrary decision",
                    "score_breakdown": {},
                    "admitted_idea_id": None,
                    "operator": "unit",
                }
                return self
            if normalized.startswith("insert into research_admissions"):
                raise AssertionError("conflicting admission replay must not insert")
            if normalized.startswith("select event_id"):
                self._fetchone = None
                return self
            if normalized.startswith("insert into control_events"):
                self.rowcount = 1
                return self
            raise AssertionError(normalized)

        def fetchone(self):
            return getattr(self, "_fetchone", None)

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def cursor(self):
            return Cursor()

    monkeypatch.setitem(
        sys.modules,
        "psycopg",
        SimpleNamespace(connect=lambda *_args, **_kwargs: Conn()),
    )

    with pytest.raises(IdempotencyConflict):
        research_facility_maintenance.apply_actions(
            "postgres://example",
            [action],
            requested_by="unit",
            apply_rejections=False,
        )
