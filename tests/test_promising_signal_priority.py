from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest

from enoch_control_plane.control_plane.promising_signal_priority import (
    _followup_exceeds_local_compute,
    _timestamp_sort_value,
    promising_followup_priority_key,
    promising_signal_bucket,
    ranked_followup_readiness,
)
from enoch_control_plane.control_plane.store import ControlPlaneStore


def _row(**overrides: Any) -> dict[str, Any]:
    row = {
        "project_id": "row",
        "project_name": "Row",
        "status": "completed",
        "manual_review_required": False,
        "research_outcome": "useful_signal",
        "hypothesis_status": "supported",
        "evidence_strength": "strong",
        "claim_scope": "bounded local toy-model signal",
        "scale_limits": "small local validation only",
        "source_url": "https://arxiv.org/abs/2605.06546",
        "artifact_paths": ["metrics.json", "project_decision.json"],
        "followup_recommended": True,
        "followup_launched": False,
        "followup_type": "branch",
        "followup_title": "Bounded branch",
        "followup_hypothesis": "The signal survives a small local ablation.",
        "followup_required_evidence": ["small local metric", "ablation vs baseline"],
        "followup_success_threshold": "beat the baseline in the local toy run",
        "followup_stop_condition": "stop after one bounded local miss",
        "followup_depth": 0,
        "updated_at": "2026-05-19T10:00:00+00:00",
    }
    row.update(overrides)
    return row


def test_promising_signal_bucket_matches_export_ranking_contract():
    assert promising_signal_bucket(_row()) == "top_external_researcher_candidates"
    assert (
        promising_signal_bucket(_row(compute_scale_blocked=True))
        == "compute_scale_blocked"
    )
    assert (
        promising_signal_bucket(
            _row(hypothesis_status="unsupported", evidence_strength="weak")
        )
        == "likely_stale_low_value_archive"
    )


def test_ranked_followup_readiness_requires_bounded_evidence_and_excludes_stale():
    assert ranked_followup_readiness(_row())["ready"] is True

    sparse = ranked_followup_readiness(
        _row(followup_required_evidence=["one metric only"])
    )
    assert sparse["ready"] is False
    assert "required_evidence" in sparse["reason"]

    scale_only = ranked_followup_readiness(
        _row(
            compute_scale_blocked=True,
            followup_required_evidence=[
                "datacenter 70B training run",
                "multi-gpu replication",
            ],
            followup_success_threshold="beat the 70B baseline",
            followup_stop_condition="stop after the hyperscaler run",
        )
    )
    assert scale_only["ready"] is False
    assert scale_only["reason"] == "compute_scale_blocked"

    scale_blocked_without_markers = ranked_followup_readiness(
        _row(
            compute_scale_blocked=True,
            followup_required_evidence=[
                "validate with the prepared setup",
                "compare against prior run",
            ],
            followup_success_threshold="confirm improvement against the prior baseline",
            followup_stop_condition="stop after one failed bounded attempt",
        )
    )
    assert scale_blocked_without_markers["ready"] is False
    assert scale_blocked_without_markers["reason"] == "compute_scale_blocked"

    stale = ranked_followup_readiness(
        _row(hypothesis_status="unsupported", evidence_strength="weak")
    )
    assert stale["ready"] is False
    assert stale["reason"] == "likely_stale_low_value_archive"


def test_followup_scale_markers_use_word_boundaries_and_negation() -> None:
    assert (
        _followup_exceeds_local_compute(
            _row(
                followup_required_evidence=[
                    "requires a 70B model",
                    "multi-gpu run",
                ]
            )
        )
        is True
    )
    assert (
        _followup_exceeds_local_compute(
            _row(
                followup_required_evidence=[
                    "evaluate whether the 7B subset is enough",
                    "ticket 7b-1234 is unrelated metadata",
                ],
                followup_success_threshold="beat the local 7b params baseline",
            )
        )
        is False
    )
    assert (
        _followup_exceeds_local_compute(
            _row(
                followup_hypothesis="we do not train for days",
                followup_required_evidence=[
                    "no datacenter replication",
                    "without full scale training",
                ],
                followup_success_threshold="training-free local replay",
            )
        )
        is False
    )
    assert (
        _followup_exceeds_local_compute(
            _row(
                followup_required_evidence=[
                    "no toy proxy; datacenter replication required",
                    "not enough local baseline; requires 70B model",
                ],
                followup_success_threshold="do not use small model; use 70B",
            )
        )
        is True
    )


def test_missing_promising_signal_fields_cannot_auto_launch_followup() -> None:
    row = _row(
        research_outcome="",
        hypothesis_status="",
        evidence_strength="",
        claim_scope="",
        scale_limits="",
        useful_signal_summary="",
    )

    readiness = ranked_followup_readiness(row)

    assert promising_signal_bucket(row) == "weak_local_only_preserved"
    assert readiness["ready"] is False
    assert readiness["reason"] == "missing_promising_signal_fields"


def test_timestamp_sort_value_treats_naive_timestamps_as_utc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    naive = "2026-05-19T10:00:00"

    monkeypatch.setenv("TZ", "UTC")
    time.tzset()
    utc_value = _timestamp_sort_value(naive)

    monkeypatch.setenv("TZ", "America/Los_Angeles")
    time.tzset()
    pacific_value = _timestamp_sort_value(naive)

    assert pacific_value == utc_value
    assert utc_value == _timestamp_sort_value("2026-05-19T10:00:00+00:00")


def test_ranked_followup_priority_orders_top_and_bounded_scale_before_regular_followups():
    top = _row(project_id="top", updated_at="2026-05-18T00:00:00+00:00")
    scale = _row(
        project_id="scale",
        compute_scale_blocked=True,
        evidence_strength="moderate",
        updated_at="2026-05-17T00:00:00+00:00",
    )
    regular = _row(
        project_id="regular",
        evidence_strength="weak",
        hypothesis_status="mixed",
        source_url="",
        updated_at="2026-05-19T00:00:00+00:00",
    )

    ordered = sorted([regular, scale, top], key=promising_followup_priority_key)

    assert [row["project_id"] for row in ordered] == ["top", "scale", "regular"]


def test_local_store_next_followup_candidate_uses_ranked_priority(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store = ControlPlaneStore(tmp_path / "control.sqlite3")
    top = _row(project_id="top", updated_at="2026-05-18T00:00:00+00:00")
    scale = _row(
        project_id="scale",
        compute_scale_blocked=True,
        evidence_strength="moderate",
        updated_at="2026-05-17T00:00:00+00:00",
    )
    regular_newer = _row(
        project_id="regular",
        evidence_strength="weak",
        hypothesis_status="mixed",
        source_url="",
        updated_at="2026-05-19T00:00:00+00:00",
    )
    stale = _row(
        project_id="stale",
        hypothesis_status="unsupported",
        evidence_strength="weak",
        updated_at="2026-05-20T00:00:00+00:00",
    )

    monkeypatch.setattr(
        store, "operator_queue_rows_sql", lambda: [regular_newer, stale, scale, top]
    )

    candidate = store.next_followup_candidate()
    assert candidate is not None
    assert candidate["project_id"] == "top"


def test_local_store_explicit_project_can_select_stale_archive(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store = ControlPlaneStore(tmp_path / "control.sqlite3")
    stale = _row(
        project_id="stale", hypothesis_status="unsupported", evidence_strength="weak"
    )
    monkeypatch.setattr(store, "operator_queue_rows_sql", lambda: [stale])

    assert store.next_followup_candidate() is None
    explicit_candidate = store.next_followup_candidate(project_id="stale")
    assert explicit_candidate is not None
    assert explicit_candidate["project_id"] == "stale"
