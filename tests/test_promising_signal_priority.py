from __future__ import annotations

from enoch_control_plane.control_plane.promising_signal_priority import (
    promising_followup_priority_key,
    promising_signal_bucket,
    ranked_followup_readiness,
)
from enoch_control_plane.control_plane.store import ControlPlaneStore


def _row(**overrides):
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
    monkeypatch, tmp_path
):
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

    assert store.next_followup_candidate()["project_id"] == "top"


def test_local_store_explicit_project_can_select_stale_archive(monkeypatch, tmp_path):
    store = ControlPlaneStore(tmp_path / "control.sqlite3")
    stale = _row(
        project_id="stale", hypothesis_status="unsupported", evidence_strength="weak"
    )
    monkeypatch.setattr(store, "operator_queue_rows_sql", lambda: [stale])

    assert store.next_followup_candidate() is None
    assert store.next_followup_candidate(project_id="stale")["project_id"] == "stale"
