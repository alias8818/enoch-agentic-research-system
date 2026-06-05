from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from enoch_control_plane.control_plane import alerts
from enoch_control_plane.control_plane.alerts import queue_alert_findings
from enoch_control_plane.control_plane.models import DashboardObservationRecord


@pytest.fixture(autouse=True)
def no_research_quality_report(monkeypatch) -> None:
    monkeypatch.setattr(
        alerts,
        "load_latest_quality_status",
        lambda *_args, **_kwargs: {},
    )


def test_queue_alert_findings_normalizes_datetime_freshness_observed_at() -> None:
    observed_at = datetime(2026, 5, 15, 12, 14, tzinfo=timezone.utc)
    status = SimpleNamespace(
        flags=SimpleNamespace(queue_paused=False, maintenance_mode=False),
        config=SimpleNamespace(live_dispatch_enabled=True),
        conflicts=[],
        active_items=[],
        warnings=[],
        source_freshness={
            "worker_preflight": SimpleNamespace(
                stale=True,
                authority="dashboard_observations",
                observed_at=observed_at,
            )
        },
    )

    findings = queue_alert_findings(status, hang_after_sec=3600)  # type: ignore[arg-type]

    assert len(findings) == 1
    assert findings[0].observed_at == observed_at.isoformat()


def test_queue_alert_findings_normalizes_datetime_active_lane_observed_at() -> None:
    updated_at = datetime(2026, 5, 15, 10, 0, tzinfo=timezone.utc)
    status = SimpleNamespace(
        flags=SimpleNamespace(queue_paused=False, maintenance_mode=False),
        config=SimpleNamespace(live_dispatch_enabled=True),
        conflicts=[],
        active_items=[
            {"project_id": "p", "current_run_id": "r", "updated_at": updated_at}
        ],
        warnings=[],
        source_freshness={},
    )

    findings = queue_alert_findings(status, hang_after_sec=1)  # type: ignore[arg-type]

    assert len(findings) == 1
    assert findings[0].observed_at == updated_at.isoformat()


def test_queue_alert_findings_treats_naive_database_timestamps_as_utc() -> None:
    updated_at = "2026-05-15 10:00:00"
    status = SimpleNamespace(
        flags=SimpleNamespace(queue_paused=False, maintenance_mode=False),
        config=SimpleNamespace(live_dispatch_enabled=True),
        conflicts=[],
        active_items=[
            {"project_id": "p", "current_run_id": "r", "updated_at": updated_at}
        ],
        warnings=[],
        source_freshness={},
    )

    findings = queue_alert_findings(status, hang_after_sec=1)  # type: ignore[arg-type]

    assert len(findings) == 1
    assert findings[0].observed_at == updated_at


def test_queue_alert_findings_preserves_conflicts_during_intentional_hold() -> None:
    conflict = SimpleNamespace(
        severity="critical",
        source="control_plane_db+worker_preflight",
        authority="cross-source active-lane reconciliation",
        message=(
            "cpu_worker worker reports live work but the control plane "
            "has no active row for that lane"
        ),
        observed_at=None,
        suggested_action="reconcile the orphan worker run",
        model_dump=lambda mode="json": {},
    )

    for queue_paused, maintenance_mode in (
        (True, False),
        (False, True),
        (True, True),
    ):
        status = SimpleNamespace(
            flags=SimpleNamespace(
                queue_paused=queue_paused, maintenance_mode=maintenance_mode
            ),
            config=SimpleNamespace(live_dispatch_enabled=True),
            conflicts=[conflict],
            active_items=[],
            warnings=[],
            source_freshness={},
        )

        findings = queue_alert_findings(status, hang_after_sec=3600)  # type: ignore[arg-type]

        assert findings == [conflict]


def test_queue_alert_findings_suppresses_live_dispatch_noise_during_hold() -> None:
    updated_at = datetime(2026, 5, 15, 10, 0, tzinfo=timezone.utc)
    status = SimpleNamespace(
        flags=SimpleNamespace(queue_paused=True, maintenance_mode=True),
        config=SimpleNamespace(live_dispatch_enabled=True),
        conflicts=[],
        active_items=[
            {"project_id": "p", "current_run_id": "r", "updated_at": updated_at}
        ],
        warnings=[],
        source_freshness={},
    )

    findings = queue_alert_findings(status, hang_after_sec=1)  # type: ignore[arg-type]

    assert findings == []


def test_queue_alert_findings_suppresses_research_quality_warning_during_hold(
    monkeypatch, tmp_path
) -> None:
    report_path = tmp_path / "research-quality.json"
    report_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        alerts,
        "load_latest_quality_status",
        lambda *_args, **_kwargs: {
            "ok": True,
            "status": "warnings",
            "label": "warnings",
            "severity_counts": {"warning": 2},
            "problem_counts": {"weak_or_missing_evidence_strength": 2},
            "report_mtime": "2000-01-01T00:00:00Z",
            "report_path": str(report_path),
            "post_prompt_monitor": {
                "malformed_provider_response_count": 7,
                "useful_adjacent_followup_delta": -4.0,
            },
            "problem_details": [
                {
                    "section": "decision_scores",
                    "severity": "info",
                    "problem": "supported_but_negative_requires_review",
                    "project_id": "project-info",
                    "run_id": "run-info",
                    "title": "Informational Project",
                },
                {
                    "section": "decision_scores",
                    "severity": "warning",
                    "problem": "weak_or_missing_evidence_strength",
                    "project_id": "project-1",
                    "run_id": "run-1",
                    "title": "Weak Evidence Project",
                },
            ],
        },
    )
    status = SimpleNamespace(
        flags=SimpleNamespace(queue_paused=True, maintenance_mode=True),
        config=SimpleNamespace(live_dispatch_enabled=True),
        conflicts=[],
        active_items=[],
        warnings=[],
        source_freshness={},
    )

    findings = queue_alert_findings(status, hang_after_sec=3600)  # type: ignore[arg-type]

    assert findings == []


def test_queue_alert_findings_suppresses_research_quality_warning_when_not_held(
    monkeypatch, tmp_path
) -> None:
    report_path = tmp_path / "research-quality.json"
    report_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        alerts,
        "load_latest_quality_status",
        lambda *_args, **_kwargs: {
            "ok": True,
            "status": "warnings",
            "label": "warnings",
            "severity_counts": {"warning": 2},
            "problem_counts": {"weak_or_missing_evidence_strength": 2},
            "report_mtime": "2000-01-01T00:00:00Z",
            "report_path": str(report_path),
            "post_prompt_monitor": {
                "malformed_provider_response_count": 7,
                "useful_adjacent_followup_delta": -4.0,
            },
            "problem_details": [
                {
                    "section": "decision_scores",
                    "severity": "info",
                    "problem": "supported_but_negative_requires_review",
                    "project_id": "project-info",
                    "run_id": "run-info",
                    "title": "Informational Project",
                },
                {
                    "section": "decision_scores",
                    "severity": "warning",
                    "problem": "weak_or_missing_evidence_strength",
                    "project_id": "project-1",
                    "run_id": "run-1",
                    "title": "Weak Evidence Project",
                },
            ],
        },
    )
    status = SimpleNamespace(
        flags=SimpleNamespace(queue_paused=False, maintenance_mode=False),
        config=SimpleNamespace(live_dispatch_enabled=True),
        conflicts=[],
        active_items=[],
        warnings=[],
        source_freshness={},
    )

    findings = queue_alert_findings(status, hang_after_sec=3600)  # type: ignore[arg-type]

    assert findings == []

    finding = alerts._research_quality_alert_finding(status)  # type: ignore[attr-defined,arg-type]
    assert finding is not None
    assert finding.severity == "warn"
    assert finding.source == "research_quality"
    assert finding.authority == "latest read-only DSPy/research-quality report"
    assert finding.message == "research quality warnings present"
    assert finding.data["status"] == "warnings"
    assert finding.data["warning_problem_count"] == 2
    assert finding.data["weak_evidence_count"] == 2
    assert finding.data["malformed_provider_response_count"] == 7
    assert finding.data["useful_adjacent_followup_delta"] == -4.0
    assert finding.data["report_is_stale"] is True
    assert finding.data["report_stale_after_hours"] == 48.0
    assert "quality report stale:" in finding.data["freshness_summary"]
    assert finding.data["top_problem_details"] == [
        {
            "severity": "warning",
            "problem": "weak_or_missing_evidence_strength",
            "project_id": "project-1",
            "run_id": "run-1",
            "title": "Weak Evidence Project",
        }
    ]


def test_queue_alert_notify_does_not_page_on_research_quality_warning(
    monkeypatch, tmp_path
) -> None:
    from enoch_control_plane.config import GateConfig
    from enoch_control_plane.control_plane import alerts
    from enoch_control_plane.control_plane.alerts import (
        evaluate_and_notify_queue_alerts,
    )

    report_path = tmp_path / "research-quality.json"
    report_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        alerts,
        "load_latest_quality_status",
        lambda *_args, **_kwargs: {
            "ok": True,
            "status": "warnings",
            "label": "Research quality: warnings",
            "severity_counts": {"warning": 1},
            "problem_counts": {"weak_or_missing_evidence_strength": 1},
            "report_mtime": datetime.now(timezone.utc).isoformat(),
            "report_path": str(report_path),
            "post_prompt_monitor": {
                "malformed_provider_response_count": 4,
                "useful_adjacent_followup_delta": 11.0,
            },
            "problem_details": [
                {
                    "section": "decision_scores",
                    "severity": "warning",
                    "problem": "weak_or_missing_evidence_strength",
                    "project_id": "project-1",
                    "run_id": "run-1",
                    "title": "Weak Evidence Project",
                }
            ],
        },
    )
    config = GateConfig(
        state_dir=str(tmp_path / "state"),
        project_root=str(tmp_path / "projects"),
        dispatch_script_path=str(tmp_path / "dispatch.sh"),
        control_api_bearer_token="control",
        completion_callback_url="http://callback",
        completion_callback_token="callback",
        live_dispatch_enabled=True,
        queue_alert_hang_after_sec=300,
        queue_alert_cooldown_sec=3600,
        pushover_alerts_enabled=True,
        pushover_app_token="app",
        pushover_user_key="user",
    )
    status = SimpleNamespace(
        flags=SimpleNamespace(queue_paused=False, maintenance_mode=False),
        config=SimpleNamespace(live_dispatch_enabled=True),
        conflicts=[],
        active_items=[],
        warnings=[],
        source_freshness={},
        dispatch_safe=True,
        dispatch_blockers=[],
    )

    class Store:
        def event_rows(self, limit=100):  # noqa: ANN001 - alert store fake
            return []

        def append_event(self, **_kwargs):  # noqa: ANN003 - alert store fake
            raise AssertionError("non-critical research quality must not append alert")

    def fail_pushover(*_args, **_kwargs):  # noqa: ANN001 - test guard
        raise AssertionError("non-critical research quality must not page Pushover")

    monkeypatch.setattr(alerts, "send_pushover", fail_pushover)

    result = evaluate_and_notify_queue_alerts(
        config=config,
        store=Store(),
        status=status,
        dry_run=False,
        force_notify=False,
        requested_by="test",
    )  # type: ignore[arg-type]

    assert result["should_alert"] is False
    assert result["sent"] is False
    assert result["fingerprint"] == "none"
    assert result["findings"] == []


def test_research_quality_finding_explains_review_required_signal_during_hold(
    monkeypatch, tmp_path
) -> None:
    report_path = tmp_path / "research-quality.json"
    report_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        alerts,
        "load_latest_quality_status",
        lambda *_args, **_kwargs: {
            "ok": True,
            "status": "clean",
            "label": "Research quality: clean",
            "severity_counts": {},
            "problem_counts": {},
            "candidate_status_counts": {
                "admitted": 45,
                "needs_review": 53,
                "rejected": 2,
            },
            "decision_outcome_counts": [
                {
                    "decision": "finalize_negative",
                    "hypothesis_status": "mixed",
                    "count": 50,
                }
            ],
            "top_candidate_categories": [
                {"category": "home-training", "count": 22},
                {"category": "spec-decoding", "count": 18},
            ],
            "candidate_status_samples": {
                "admitted": [
                    {
                        "candidate_id": "candidate-admitted",
                        "title": "Admitted candidate",
                        "status": "admitted",
                        "deterministic_total_score": 76.4,
                        "contract_quality_score": 1.0,
                        "problems": [],
                    }
                ],
                "needs_review": [
                    {
                        "candidate_id": "candidate-needs-review",
                        "title": "Needs review candidate",
                        "status": "needs_review",
                        "deterministic_total_score": 64.2,
                        "contract_quality_score": 0.5,
                        "problems": ["thin_expected_artifacts"],
                    }
                ],
            },
            "decision_outcome_samples": [
                {
                    "decision": "finalize_negative",
                    "hypothesis_status": "mixed",
                    "samples": [
                        {
                            "project_id": "project-mixed",
                            "project_name": "Mixed project",
                            "run_id": "run-mixed",
                            "decision": "finalize_negative",
                            "hypothesis_status": "mixed",
                            "evidence_strength": "moderate",
                            "research_outcome": "useful_signal",
                            "followup_title": "Mixed follow-up",
                            "problems": [],
                        }
                    ],
                }
            ],
            "decision_posture": {
                "available": True,
                "decisions_checked": 3,
                "useful_signal_count": 2,
                "negative_count": 1,
                "bounded_paper_ready_count": 0,
                "followup_recommended_count": 2,
                "compute_scale_blocked_count": 0,
                "publication_posture": "followup_only",
                "research_outcome_counts": {"negative": 1, "useful_signal": 2},
                "hypothesis_status_counts": {
                    "mixed": 1,
                    "supported": 1,
                    "unsupported": 1,
                },
                "evidence_strength_counts": {"moderate": 3},
                "decision_counts": {
                    "finalize_negative:mixed": 1,
                    "finalize_negative:supported": 1,
                    "finalize_negative:unsupported": 1,
                },
                "representative_useful_signals": [
                    {
                        "project_id": "project-mixed",
                        "project_name": "Mixed project",
                        "run_id": "run-mixed",
                        "decision": "finalize_negative",
                        "hypothesis_status": "mixed",
                        "evidence_strength": "moderate",
                        "research_outcome": "useful_signal",
                        "bounded_paper_ready": False,
                        "followup_recommended": True,
                        "followup_title": "Mixed follow-up",
                        "recommended_next_action": (
                            "Run the mixed follow-up before treating this as "
                            "paper-ready."
                        ),
                    }
                ],
                "operator_action": (
                    "useful signals are present but none are bounded-paper-ready; "
                    "run or review the listed follow-ups before treating this as "
                    "publication output"
                ),
            },
            "followup_readiness": {
                "available": True,
                "recommended_count": 2,
                "bounded_ready_count": 1,
                "underspecified_count": 1,
                "missing_title_count": 0,
                "missing_success_threshold_count": 0,
                "missing_stop_condition_count": 1,
                "thin_required_evidence_count": 0,
                "followup_type_counts": {"deepen": 2},
                "ready_followups": [
                    {
                        "project_id": "project-mixed",
                        "project_name": "Mixed project",
                        "run_id": "run-mixed",
                        "followup_type": "deepen",
                        "followup_title": "Mixed follow-up",
                        "followup_required_evidence_count": 4,
                        "followup_success_threshold": (
                            "Mixed follow-up must improve accuracy by 5 points."
                        ),
                        "followup_stop_condition": (
                            "Stop mixed follow-up if accuracy does not improve."
                        ),
                        "recommended_next_action": (
                            "Run the mixed follow-up before treating this as "
                            "paper-ready."
                        ),
                    }
                ],
                "prioritized_followups": [
                    {
                        "project_id": "project-mixed",
                        "project_name": "Mixed project",
                        "run_id": "run-mixed",
                        "followup_type": "deepen",
                        "followup_title": "Mixed follow-up",
                        "followup_required_evidence_count": 4,
                        "followup_success_threshold": (
                            "Mixed follow-up must improve accuracy by 5 points."
                        ),
                        "followup_stop_condition": (
                            "Stop mixed follow-up if accuracy does not improve."
                        ),
                        "recommended_next_action": (
                            "Run the mixed follow-up before treating this as "
                            "paper-ready."
                        ),
                        "hypothesis_status": "mixed",
                        "evidence_strength": "moderate",
                        "priority_score": 75,
                        "priority_reasons": [
                            "mixed_hypothesis",
                            "moderate_evidence",
                            "deepen_followup",
                            "4_required_evidence_items",
                            "explicit_success_and_stop_bounds",
                        ],
                    }
                ],
                "underspecified_followups": [
                    {
                        "project_id": "project-supported",
                        "project_name": "Supported project",
                        "run_id": "run-supported",
                        "followup_type": "deepen",
                        "followup_title": "Supported follow-up",
                        "followup_required_evidence_count": 4,
                        "followup_success_threshold": (
                            "Supported follow-up must reproduce the effect."
                        ),
                        "followup_stop_condition": "",
                        "recommended_next_action": (
                            "Run the supported follow-up before treating this as "
                            "paper-ready."
                        ),
                        "missing_fields": ["missing_stop_condition"],
                    }
                ],
                "operator_action": (
                    "1 recommended follow-up is underspecified; fill missing "
                    "readiness fields before queueing it"
                ),
            },
            "quality_floor": {
                "available": True,
                "threshold": 0.7,
                "posture": "satisfied",
                "candidates_checked": 45,
                "decisions_checked": 50,
                "candidate_below_floor_count": 0,
                "decision_below_floor_count": 0,
                "below_floor_count": 0,
                "candidate_samples": [],
                "decision_samples": [],
                "operator_action": (
                    "quality floor satisfied across 45 candidates and 50 decisions"
                ),
            },
            "report_mtime": datetime.now(timezone.utc).isoformat(),
            "report_path": str(report_path),
            "post_prompt_monitor": {
                "window_comparison": {
                    "cutoff": "2026-05-11T09:58:00Z",
                    "limit": 20,
                    "delta": {
                        "admitted_rate_delta": 0.1,
                        "proxy_only_positive_delta": -4.0,
                        "useful_adjacent_followup_delta": -4.0,
                        "moonshot_avg_score_delta": 1.426,
                    },
                    "current": {
                        "candidate_count": 20,
                        "decision_count": 20,
                        "admitted_rate": 0.6,
                        "avg_total_score": 73.093,
                        "status_counts": {"admitted": 12, "rejected": 4},
                        "category_counts": {"home-training": 3, "long-context": 4},
                        "generation_mode_counts": {
                            "fresh_grounded": 9,
                            "moonshot": 10,
                        },
                        "eval_case_counts": {
                            "proxy_only_positive": 6,
                            "useful_adjacent_followup": 2,
                        },
                        "high_similarity_pair_count": 0,
                    },
                    "previous": {
                        "candidate_count": 20,
                        "decision_count": 20,
                        "admitted_rate": 0.5,
                        "avg_total_score": 71.82,
                        "status_counts": {"admitted": 10, "rejected": 2},
                        "category_counts": {"home-training": 4, "spec-decoding": 4},
                        "generation_mode_counts": {
                            "fresh_grounded": 7,
                            "moonshot": 7,
                        },
                        "eval_case_counts": {
                            "proxy_only_positive": 8,
                            "useful_adjacent_followup": 6,
                        },
                        "high_similarity_pair_count": 0,
                    },
                },
                "malformed_provider_response_count": 2,
                "malformed_provider_response_ticks": 1,
                "provider_generation_health": {
                    "available": True,
                    "rows_checked": 4,
                    "malformed_provider_response_count": 2,
                    "malformed_provider_response_ticks": 1,
                    "clean_tick_count": 3,
                    "consecutive_clean_ticks": 2,
                    "malformed_history_status": "active",
                    "active_malformed_warning": True,
                    "last_checked_at": "2026-05-30T04:00:30Z",
                    "last_malformed_at": "2026-05-30T03:00:30Z",
                    "malformed_provider_model_counts": {"hf:model-a": 2},
                    "latest_tick": {
                        "checked_at": "2026-05-30T04:00:30Z",
                        "recorded_at": "2026-05-30T04:04:45Z",
                        "trace_id": "research-cycle-trace-b",
                        "run_cycle_id": "run-cycle-b",
                        "provider_model": "hf:model-b",
                        "malformed_provider_response_count": 0,
                        "generated_count": 3,
                        "promoted_count": 1,
                        "dispatched_count": 0,
                        "status": "clean",
                        "operator_action": (
                            "provider generation is currently clean; keep "
                            "monitoring before widening automation"
                        ),
                    },
                    "last_malformed_tick": {
                        "checked_at": "2026-05-30T03:00:30Z",
                        "recorded_at": "2026-05-30T03:04:45Z",
                        "trace_id": "research-cycle-trace-a",
                        "run_cycle_id": "run-cycle-a",
                        "provider_model": "hf:model-a",
                        "malformed_provider_response_count": 2,
                        "generated_count": 0,
                        "promoted_count": 0,
                        "dispatched_count": 2,
                        "status": "malformed",
                        "operator_action": (
                            "inspect provider-generation output for this tick "
                            "before trusting new idea volume"
                        ),
                    },
                    "operator_action": (
                        "provider generation has 2 clean ticks since the last "
                        "malformed response; review the last malformed model "
                        "before widening automation"
                    ),
                },
                "useful_adjacent_followup_delta": -4.0,
                "useful_adjacent_followup_evidence": {
                    "current": [
                        {
                            "case_id": "useful_adjacent_followup:post-run",
                            "case_type": "useful_adjacent_followup",
                            "severity": "info",
                            "title": "Current follow-up",
                            "project_id": "post-project",
                            "project_name": "Current Project",
                            "run_id": "post-run",
                            "followup_title": "Current follow-up",
                            "followup_depth": 1,
                            "expected_behavior": "Prefer bounded follow-up.",
                        }
                    ],
                    "previous": [],
                    "delta": -4.0,
                },
                "recent_malformed_provider_responses": [
                    {
                        "checked_at": "2026-05-30T03:00:30Z",
                        "recorded_at": "2026-05-30T03:04:45Z",
                        "trace_id": "research-cycle-trace-a",
                        "run_cycle_id": "run-cycle-a",
                        "provider_model": "hf:model-a",
                        "malformed_provider_response_count": 2,
                        "generated_count": 0,
                        "promoted_count": 0,
                        "dispatched_count": 2,
                    }
                ],
            },
            "problem_details": [],
            "recommendations": [
                "No critical quality-layer warnings from the read-only audit heuristics."
            ],
            "refresh_status": {"available": True, "ok": True},
        },
    )
    status = SimpleNamespace(
        flags=SimpleNamespace(queue_paused=True, maintenance_mode=True),
        config=SimpleNamespace(live_dispatch_enabled=True),
        conflicts=[],
        active_items=[],
        warnings=[],
        source_freshness={},
    )

    finding = alerts._research_quality_alert_finding(status)  # type: ignore[attr-defined,arg-type]

    assert finding is not None
    assert finding.message == (
        "research signal requires review: Useful follow-up signal declined "
        "from 6 to 2; no bounded paper-ready outputs are available"
    )
    assert (
        finding.suggested_action
        == "Useful follow-up signal declined from 6 to 2; no bounded "
        "paper-ready outputs are available; inspect provider-generation "
        "failures before trusting new idea volume. Maintenance mode is "
        "holding automation; clear it only after the research-quality blockers "
        "are resolved."
    )
    assert finding.data["status"] == "clean"
    assert finding.data["operator_summary"] == (
        "quality=clean; quality floor=satisfied (95 checked; threshold 0.70); "
        "quality-window posture=followup only (2 useful; 0 paper-ready); "
        "quality-window follow-ups=1 ready / 2 recommended; weak evidence=0; "
        "provider malformed=active (2 responses across 1 recent tick); useful "
        "follow-up=active decline -4.0 (2 current vs 6 previous)"
    )
    assert finding.data["quality_floor"] == {
        "available": True,
        "threshold": 0.7,
        "posture": "satisfied",
        "candidates_checked": 45,
        "decisions_checked": 50,
        "candidate_below_floor_count": 0,
        "decision_below_floor_count": 0,
        "below_floor_count": 0,
        "candidate_samples": [],
        "decision_samples": [],
        "operator_action": (
            "quality floor satisfied across 45 candidates and 50 decisions"
        ),
    }
    assert finding.data["signal_verdict"] == "review_required"
    assert finding.data["signal_label"] == "Research signal: review required"
    assert (
        finding.data["signal_operator_action"]
        == "inspect provider-generation failures before trusting new idea volume"
    )
    assert finding.data["operator_recommendations"] == [
        "inspect provider-generation failures before trusting new idea volume",
        "review recent follow-up quality before increasing throughput",
        (
            "inspect provider-generation output for the listed ticks before "
            "trusting new idea volume"
        ),
    ]
    assert finding.data["research_output_readiness"]["state"] == (
        "blocked_by_quality_decline"
    )
    assert finding.data["research_output_readiness"]["blocked_by"] == (
        "research_quality"
    )
    assert finding.data["research_output_readiness"]["hold_state"] == (
        "maintenance_hold"
    )
    assert finding.data["research_output_readiness"]["failed_invariants"] == [
        {
            "code": "useful_followup_decline",
            "label": "Useful follow-up signal must not decline",
            "current": 2,
            "required": ">= 6",
            "previous": 6,
            "delta": -4.0,
        },
        {
            "code": "no_paper_ready_outputs",
            "label": "At least one bounded paper-ready output is required",
            "current": 0,
            "required": ">= 1",
            "useful_signal_count": 2,
            "publication_posture": "followup_only",
        },
    ]
    assert finding.data["signal_reasons"] == [
        {
            "code": "malformed_provider_responses",
            "severity": "warning",
            "message": "provider generation produced malformed responses",
            "operator_action": (
                "inspect provider-generation failures before trusting new idea volume"
            ),
            "status": "active",
            "active": True,
        },
        {
            "code": "useful_followup_decline",
            "severity": "warning",
            "message": "useful adjacent follow-up signal declined",
            "operator_action": (
                "review recent follow-up quality before increasing throughput"
            ),
            "status": "active",
            "active": True,
        },
    ]
    assert finding.data["post_prompt_warning_details"] == [
        {
            "code": "malformed_provider_responses",
            "severity": "warning",
            "message": "2 malformed provider responses across 1 recent tick",
            "operator_action": (
                "inspect provider-generation output for the listed ticks before "
                "trusting new idea volume"
            ),
        },
        {
            "code": "useful_followup_decline",
            "severity": "warning",
            "message": "useful adjacent follow-up signal declined by 4.0",
            "operator_action": (
                "review recent follow-up quality before increasing throughput"
            ),
        },
    ]
    assert finding.data["recent_malformed_provider_responses"] == [
        {
            "checked_at": "2026-05-30T03:00:30Z",
            "recorded_at": "2026-05-30T03:04:45Z",
            "trace_id": "research-cycle-trace-a",
            "run_cycle_id": "run-cycle-a",
            "provider_model": "hf:model-a",
            "malformed_provider_response_count": 2,
            "generated_count": 0,
            "promoted_count": 0,
            "dispatched_count": 2,
            "operator_action": (
                "inspect provider-generation output for this tick before "
                "trusting new idea volume"
            ),
        }
    ]
    assert finding.data["provider_generation_health"] == {
        "available": True,
        "rows_checked": 4,
        "malformed_provider_response_count": 2,
        "malformed_provider_response_ticks": 1,
        "clean_tick_count": 3,
        "consecutive_clean_ticks": 2,
        "malformed_history_status": "active",
        "active_malformed_warning": True,
        "last_checked_at": "2026-05-30T04:00:30Z",
        "last_malformed_at": "2026-05-30T03:00:30Z",
        "malformed_provider_model_counts": {"hf:model-a": 2},
        "latest_tick": {
            "checked_at": "2026-05-30T04:00:30Z",
            "recorded_at": "2026-05-30T04:04:45Z",
            "trace_id": "research-cycle-trace-b",
            "run_cycle_id": "run-cycle-b",
            "provider_model": "hf:model-b",
            "malformed_provider_response_count": 0,
            "generated_count": 3,
            "promoted_count": 1,
            "dispatched_count": 0,
            "status": "clean",
            "operator_action": (
                "provider generation is currently clean; keep monitoring "
                "before widening automation"
            ),
        },
        "last_malformed_tick": {
            "checked_at": "2026-05-30T03:00:30Z",
            "recorded_at": "2026-05-30T03:04:45Z",
            "trace_id": "research-cycle-trace-a",
            "run_cycle_id": "run-cycle-a",
            "provider_model": "hf:model-a",
            "malformed_provider_response_count": 2,
            "generated_count": 0,
            "promoted_count": 0,
            "dispatched_count": 2,
            "status": "malformed",
            "operator_action": (
                "inspect provider-generation output for this tick before "
                "trusting new idea volume"
            ),
        },
        "operator_action": (
            "provider generation has 2 clean ticks since the last malformed "
            "response; review the last malformed model before widening automation"
        ),
    }
    assert finding.data["useful_adjacent_followup_evidence"] == {
        "current": [
            {
                "case_id": "useful_adjacent_followup:post-run",
                "case_type": "useful_adjacent_followup",
                "severity": "info",
                "title": "Current follow-up",
                "project_id": "post-project",
                "project_name": "Current Project",
                "run_id": "post-run",
                "followup_title": "Current follow-up",
                "followup_depth": 1,
                "expected_behavior": "Prefer bounded follow-up.",
            }
        ],
        "previous": [],
        "delta": -4.0,
    }
    assert finding.data["candidate_status_counts"] == {
        "admitted": 45,
        "needs_review": 53,
        "rejected": 2,
    }
    assert finding.data["decision_outcome_counts"] == [
        {
            "decision": "finalize_negative",
            "hypothesis_status": "mixed",
            "count": 50,
        }
    ]
    assert finding.data["top_candidate_categories"] == [
        {"category": "home-training", "count": 22},
        {"category": "spec-decoding", "count": 18},
    ]
    assert finding.data["candidate_status_samples"] == {
        "admitted": [
            {
                "candidate_id": "candidate-admitted",
                "title": "Admitted candidate",
                "status": "admitted",
                "deterministic_total_score": 76.4,
                "contract_quality_score": 1.0,
                "problems": [],
            }
        ],
        "needs_review": [
            {
                "candidate_id": "candidate-needs-review",
                "title": "Needs review candidate",
                "status": "needs_review",
                "deterministic_total_score": 64.2,
                "contract_quality_score": 0.5,
                "problems": ["thin_expected_artifacts"],
            }
        ],
    }
    assert finding.data["decision_outcome_samples"] == [
        {
            "decision": "finalize_negative",
            "hypothesis_status": "mixed",
            "samples": [
                {
                    "project_id": "project-mixed",
                    "project_name": "Mixed project",
                    "run_id": "run-mixed",
                    "decision": "finalize_negative",
                    "hypothesis_status": "mixed",
                    "evidence_strength": "moderate",
                    "research_outcome": "useful_signal",
                    "followup_title": "Mixed follow-up",
                    "problems": [],
                }
            ],
        }
    ]
    project_mixed_links = {
        "project": "/control/api/v1/projects/project-mixed",
        "run": "/control/api/v1/runs/run-mixed",
        "legacy_project": "/control/api/projects/project-mixed",
        "legacy_run": "/control/api/runs/run-mixed",
    }
    project_supported_links = {
        "project": "/control/api/v1/projects/project-supported",
        "run": "/control/api/v1/runs/run-supported",
        "legacy_project": "/control/api/projects/project-supported",
        "legacy_run": "/control/api/runs/run-supported",
    }
    assert finding.data["decision_posture"] == {
        "available": True,
        "decisions_checked": 3,
        "useful_signal_count": 2,
        "negative_count": 1,
        "bounded_paper_ready_count": 0,
        "followup_recommended_count": 2,
        "compute_scale_blocked_count": 0,
        "publication_posture": "followup_only",
        "research_outcome_counts": {"negative": 1, "useful_signal": 2},
        "hypothesis_status_counts": {
            "mixed": 1,
            "supported": 1,
            "unsupported": 1,
        },
        "evidence_strength_counts": {"moderate": 3},
        "decision_counts": {
            "finalize_negative:mixed": 1,
            "finalize_negative:supported": 1,
            "finalize_negative:unsupported": 1,
        },
        "representative_useful_signals": [
            {
                "project_id": "project-mixed",
                "project_name": "Mixed project",
                "run_id": "run-mixed",
                "links": project_mixed_links,
                "decision": "finalize_negative",
                "hypothesis_status": "mixed",
                "evidence_strength": "moderate",
                "research_outcome": "useful_signal",
                "bounded_paper_ready": False,
                "followup_recommended": True,
                "followup_title": "Mixed follow-up",
                "recommended_next_action": (
                    "Run the mixed follow-up before treating this as paper-ready."
                ),
            }
        ],
        "operator_action": (
            "useful signals are present but none are bounded-paper-ready; run or "
            "review the listed follow-ups before treating this as publication output"
        ),
    }
    assert finding.data["followup_readiness"] == {
        "available": True,
        "recommended_count": 2,
        "bounded_ready_count": 1,
        "underspecified_count": 1,
        "missing_title_count": 0,
        "missing_success_threshold_count": 0,
        "missing_stop_condition_count": 1,
        "thin_required_evidence_count": 0,
        "followup_type_counts": {"deepen": 2},
        "ready_followups": [
            {
                "project_id": "project-mixed",
                "project_name": "Mixed project",
                "run_id": "run-mixed",
                "links": project_mixed_links,
                "followup_type": "deepen",
                "followup_title": "Mixed follow-up",
                "followup_required_evidence_count": 4,
                "followup_success_threshold": (
                    "Mixed follow-up must improve accuracy by 5 points."
                ),
                "followup_stop_condition": (
                    "Stop mixed follow-up if accuracy does not improve."
                ),
                "recommended_next_action": (
                    "Run the mixed follow-up before treating this as paper-ready."
                ),
            }
        ],
        "prioritized_followups": [
            {
                "project_id": "project-mixed",
                "project_name": "Mixed project",
                "run_id": "run-mixed",
                "links": project_mixed_links,
                "followup_type": "deepen",
                "followup_title": "Mixed follow-up",
                "followup_required_evidence_count": 4,
                "followup_success_threshold": (
                    "Mixed follow-up must improve accuracy by 5 points."
                ),
                "followup_stop_condition": (
                    "Stop mixed follow-up if accuracy does not improve."
                ),
                "recommended_next_action": (
                    "Run the mixed follow-up before treating this as paper-ready."
                ),
                "hypothesis_status": "mixed",
                "evidence_strength": "moderate",
                "priority_score": 75,
                "priority_reasons": [
                    "mixed_hypothesis",
                    "moderate_evidence",
                    "deepen_followup",
                    "4_required_evidence_items",
                    "explicit_success_and_stop_bounds",
                ],
            }
        ],
        "underspecified_followups": [
            {
                "project_id": "project-supported",
                "project_name": "Supported project",
                "run_id": "run-supported",
                "links": project_supported_links,
                "followup_type": "deepen",
                "followup_title": "Supported follow-up",
                "followup_required_evidence_count": 4,
                "followup_success_threshold": (
                    "Supported follow-up must reproduce the effect."
                ),
                "followup_stop_condition": "",
                "recommended_next_action": (
                    "Run the supported follow-up before treating this as paper-ready."
                ),
                "missing_fields": ["missing_stop_condition"],
            }
        ],
        "operator_action": (
            "1 recommended follow-up is underspecified; fill missing readiness "
            "fields before queueing it"
        ),
    }
    assert finding.data["window_comparison"] == {
        "cutoff": "2026-05-11T09:58:00Z",
        "limit": 20,
        "delta": {
            "admitted_rate_delta": 0.1,
            "proxy_only_positive_delta": -4.0,
            "useful_adjacent_followup_delta": -4.0,
            "moonshot_avg_score_delta": 1.426,
        },
        "current": {
            "candidate_count": 20,
            "decision_count": 20,
            "admitted_rate": 0.6,
            "avg_total_score": 73.093,
            "status_counts": {"admitted": 12, "rejected": 4},
            "category_counts": {"home-training": 3, "long-context": 4},
            "generation_mode_counts": {"fresh_grounded": 9, "moonshot": 10},
            "eval_case_counts": {
                "proxy_only_positive": 6,
                "useful_adjacent_followup": 2,
            },
            "high_similarity_pair_count": 0,
        },
        "previous": {
            "candidate_count": 20,
            "decision_count": 20,
            "admitted_rate": 0.5,
            "avg_total_score": 71.82,
            "status_counts": {"admitted": 10, "rejected": 2},
            "category_counts": {"home-training": 4, "spec-decoding": 4},
            "generation_mode_counts": {"fresh_grounded": 7, "moonshot": 7},
            "eval_case_counts": {
                "proxy_only_positive": 8,
                "useful_adjacent_followup": 6,
            },
            "high_similarity_pair_count": 0,
        },
    }


def test_queue_alert_findings_blocks_missing_research_quality_report_during_hold(
    monkeypatch, tmp_path
) -> None:
    missing_report = tmp_path / "missing-quality.json"
    monkeypatch.setattr(
        alerts,
        "load_latest_quality_status",
        lambda *_args, **_kwargs: {
            "ok": False,
            "status": "blocked",
            "label": "Research quality: BLOCKED",
            "severity_counts": {"blocked": 1},
            "problem_counts": {"missing_quality_report": 1},
            "report_mtime": "",
            "report_path": str(missing_report),
            "post_prompt_monitor": {},
            "problem_details": [
                {
                    "section": "report",
                    "severity": "blocked",
                    "problem": "missing_quality_report",
                }
            ],
        },
    )
    status = SimpleNamespace(
        flags=SimpleNamespace(queue_paused=True, maintenance_mode=True),
        config=SimpleNamespace(live_dispatch_enabled=True),
        conflicts=[],
        active_items=[],
        warnings=[],
        source_freshness={},
    )

    findings = queue_alert_findings(status, hang_after_sec=3600)  # type: ignore[arg-type]

    assert len(findings) == 1
    finding = findings[0]
    assert finding.severity == "critical"
    assert finding.source == "research_quality"
    assert finding.message == "research quality is blocked"
    assert finding.data["report_path"] == str(missing_report)
    assert finding.data["blocked_problem_count"] == 1
    assert finding.data["top_problem_details"] == [
        {
            "severity": "blocked",
            "problem": "missing_quality_report",
            "project_id": "",
            "run_id": "",
            "title": "",
        }
    ]


def test_queue_alert_findings_blocks_research_quality_loader_errors_during_hold(
    monkeypatch, tmp_path
) -> None:
    report_path = tmp_path / "quality.json"

    def fail_load(*_args, **_kwargs):  # noqa: ANN002, ANN003
        raise ValueError("malformed quality report")

    monkeypatch.setenv("ENOCH_RESEARCH_QUALITY_REPORT_PATH", str(report_path))
    monkeypatch.setattr(alerts, "load_latest_quality_status", fail_load)
    status = SimpleNamespace(
        flags=SimpleNamespace(queue_paused=True, maintenance_mode=True),
        config=SimpleNamespace(live_dispatch_enabled=True),
        conflicts=[],
        active_items=[],
        warnings=[],
        source_freshness={},
    )

    findings = queue_alert_findings(status, hang_after_sec=3600)  # type: ignore[arg-type]

    assert len(findings) == 1
    finding = findings[0]
    assert finding.severity == "critical"
    assert finding.source == "research_quality"
    assert finding.message == "research quality is blocked"
    assert finding.data["report_path"] == str(report_path)
    assert finding.data["top_problem_details"][0]["problem"] == (
        "research_quality_status_load_failed"
    )


def test_queue_alert_findings_ignores_clean_research_quality(monkeypatch) -> None:
    monkeypatch.setattr(
        alerts,
        "load_latest_quality_status",
        lambda *_args, **_kwargs: {
            "ok": True,
            "status": "clean",
            "label": "clean",
            "severity_counts": {},
            "problem_counts": {},
            "post_prompt_monitor": {
                "malformed_provider_response_count": 0,
                "useful_adjacent_followup_delta": 0.0,
            },
        },
    )
    status = SimpleNamespace(
        flags=SimpleNamespace(queue_paused=True, maintenance_mode=True),
        config=SimpleNamespace(live_dispatch_enabled=True),
        conflicts=[],
        active_items=[],
        warnings=[],
        source_freshness={},
    )

    findings = queue_alert_findings(status, hang_after_sec=3600)  # type: ignore[arg-type]

    assert findings == []


def test_queue_alert_findings_ignores_recovered_provider_context_when_ready(
    monkeypatch, tmp_path
) -> None:
    report_path = tmp_path / "research-quality.json"
    report_path.write_text("{}", encoding="utf-8")
    fresh_report_mtime = datetime.now(timezone.utc).isoformat()
    monkeypatch.setattr(
        alerts,
        "load_latest_quality_status",
        lambda *_args, **_kwargs: {
            "ok": True,
            "status": "clean",
            "label": "Research quality: clean",
            "severity_counts": {},
            "problem_counts": {},
            "report_mtime": fresh_report_mtime,
            "report_path": str(report_path),
            "post_prompt_monitor": {
                "malformed_provider_response_count": 16,
                "malformed_provider_response_ticks": 8,
                "useful_adjacent_followup_delta": 12.0,
                "provider_generation_health": {
                    "available": True,
                    "malformed_provider_response_count": 16,
                    "malformed_provider_response_ticks": 8,
                    "consecutive_clean_ticks": 70,
                    "latest_tick": {
                        "status": "clean",
                        "malformed_provider_response_count": 0,
                    },
                    "operator_action": (
                        "provider generation has 70 clean ticks since the last "
                        "malformed response; review the last malformed model "
                        "before widening automation"
                    ),
                },
            },
            "decision_posture": {
                "available": True,
                "useful_signal_count": 97,
                "bounded_paper_ready_count": 1,
            },
        },
    )
    status = SimpleNamespace(
        flags=SimpleNamespace(queue_paused=False, maintenance_mode=False),
        config=SimpleNamespace(live_dispatch_enabled=True),
        conflicts=[],
        active_items=[],
        warnings=[],
        source_freshness={},
    )

    findings = queue_alert_findings(status, hang_after_sec=3600)  # type: ignore[arg-type]

    assert findings == []


def test_queue_alert_findings_ignores_provider_recovery_grace_when_latest_tick_yields(
    monkeypatch, tmp_path
) -> None:
    report_path = tmp_path / "research-quality.json"
    report_path.write_text("{}", encoding="utf-8")
    fresh_report_mtime = datetime.now(timezone.utc).isoformat()
    monkeypatch.setattr(
        alerts,
        "load_latest_quality_status",
        lambda *_args, **_kwargs: {
            "ok": True,
            "status": "clean",
            "label": "Research quality: clean",
            "severity_counts": {},
            "problem_counts": {},
            "report_mtime": fresh_report_mtime,
            "report_path": str(report_path),
            "post_prompt_monitor": {
                "malformed_provider_response_count": 16,
                "malformed_provider_response_ticks": 8,
                "useful_adjacent_followup_delta": 10.0,
                "provider_generation_health": {
                    "available": True,
                    "malformed_provider_response_count": 16,
                    "malformed_provider_response_ticks": 8,
                    "consecutive_clean_ticks": 1,
                    "latest_tick": {
                        "status": "clean",
                        "malformed_provider_response_count": 0,
                        "generated_count": 5,
                        "promoted_count": 1,
                        "dispatched_count": 1,
                        "provider_model": "hf:zai-org/GLM-5.1",
                    },
                    "last_malformed_tick": {
                        "status": "malformed",
                        "malformed_provider_response_count": 2,
                        "provider_model": "hf:moonshotai/Kimi-K2.6",
                    },
                    "operator_action": (
                        "provider generation has 1 clean tick since the last "
                        "malformed response; review the last malformed model "
                        "before widening automation"
                    ),
                },
                "window_comparison": {
                    "current": {"eval_case_counts": {"useful_adjacent_followup": 16}},
                    "previous": {"eval_case_counts": {"useful_adjacent_followup": 6}},
                },
            },
            "quality_floor": {
                "available": True,
                "posture": "satisfied",
                "candidate_below_floor_count": 0,
                "decision_below_floor_count": 0,
            },
            "decision_posture": {
                "available": True,
                "useful_signal_count": 98,
                "bounded_paper_ready_count": 1,
                "followup_recommended_count": 92,
            },
        },
    )
    status = SimpleNamespace(
        flags=SimpleNamespace(queue_paused=False, maintenance_mode=False),
        config=SimpleNamespace(live_dispatch_enabled=True),
        conflicts=[],
        active_items=[{"project_id": "active-project"}],
        warnings=[],
        source_freshness={},
    )

    findings = queue_alert_findings(status, hang_after_sec=3600)  # type: ignore[arg-type]

    assert findings == []


def test_queue_alert_findings_ignores_no_paper_ready_only_research_quality(
    monkeypatch, tmp_path
) -> None:
    report_path = tmp_path / "research-quality.json"
    report_path.write_text("{}", encoding="utf-8")
    fresh_report_mtime = datetime.now(timezone.utc).isoformat()
    monkeypatch.setattr(
        alerts,
        "load_latest_quality_status",
        lambda *_args, **_kwargs: {
            "ok": True,
            "status": "clean",
            "label": "Research quality: clean",
            "severity_counts": {},
            "problem_counts": {},
            "report_mtime": fresh_report_mtime,
            "report_path": str(report_path),
            "post_prompt_monitor": {
                "malformed_provider_response_count": 20,
                "malformed_provider_response_ticks": 10,
                "useful_adjacent_followup_delta": 8.0,
                "provider_generation_health": {
                    "available": True,
                    "malformed_provider_response_count": 20,
                    "malformed_provider_response_ticks": 10,
                    "consecutive_clean_ticks": 36,
                    "latest_tick": {
                        "status": "clean",
                        "malformed_provider_response_count": 0,
                        "generated_count": 5,
                        "promoted_count": 2,
                        "dispatched_count": 2,
                    },
                    "operator_action": (
                        "provider generation has 36 clean ticks since the last "
                        "malformed response; review the last malformed model "
                        "before widening automation"
                    ),
                },
            },
            "quality_floor": {
                "available": True,
                "posture": "satisfied",
                "candidate_below_floor_count": 0,
                "decision_below_floor_count": 0,
            },
            "decision_posture": {
                "available": True,
                "useful_signal_count": 100,
                "bounded_paper_ready_count": 0,
                "followup_recommended_count": 92,
            },
        },
    )
    status = SimpleNamespace(
        flags=SimpleNamespace(queue_paused=False, maintenance_mode=False),
        config=SimpleNamespace(live_dispatch_enabled=True),
        conflicts=[],
        active_items=[],
        warnings=[],
        source_freshness={},
    )

    findings = queue_alert_findings(status, hang_after_sec=3600)  # type: ignore[arg-type]

    assert findings == []


def test_queue_alert_notify_alerts_on_conflict_during_intentional_hold(
    tmp_path,
) -> None:
    from enoch_control_plane.config import GateConfig
    from enoch_control_plane.control_plane.alerts import (
        evaluate_and_notify_queue_alerts,
    )

    config = GateConfig(
        state_dir=str(tmp_path / "state"),
        project_root=str(tmp_path / "projects"),
        dispatch_script_path=str(tmp_path / "dispatch.sh"),
        control_api_bearer_token="control",
        completion_callback_url="http://callback",
        completion_callback_token="callback",
        live_dispatch_enabled=True,
        queue_alert_hang_after_sec=300,
        queue_alert_cooldown_sec=3600,
        pushover_alerts_enabled=False,
    )
    status = SimpleNamespace(
        flags=SimpleNamespace(queue_paused=True, maintenance_mode=True),
        config=SimpleNamespace(live_dispatch_enabled=True),
        conflicts=[
            SimpleNamespace(
                severity="critical",
                source="control_plane_db+worker_preflight",
                authority="cross-source active-lane reconciliation",
                message=(
                    "cpu_worker worker reports live work but the control plane "
                    "has no active row for that lane"
                ),
                observed_at=None,
                suggested_action="reconcile the orphan worker run",
                model_dump=lambda mode="json": {
                    "severity": "critical",
                    "source": "control_plane_db+worker_preflight",
                    "authority": "cross-source active-lane reconciliation",
                    "message": (
                        "cpu_worker worker reports live work but the control "
                        "plane has no active row for that lane"
                    ),
                    "observed_at": None,
                    "suggested_action": "reconcile the orphan worker run",
                    "data": {},
                },
            )
        ],
        active_items=[],
        warnings=[],
        source_freshness={},
        dispatch_safe=False,
        dispatch_blockers=["maintenance mode is enabled"],
    )

    class Store:
        def event_rows(self, limit=100):  # noqa: ANN001 - alert store fake
            return []

        def append_event(self, **_kwargs):  # noqa: ANN003 - alert store fake
            return ("evt-1", True)

    result = evaluate_and_notify_queue_alerts(
        config=config,
        store=Store(),
        status=status,
        dry_run=True,
        force_notify=False,
        requested_by="test",
    )  # type: ignore[arg-type]

    assert result["should_alert"] is True
    assert result["findings"][0]["severity"] == "critical"


def test_queue_alert_findings_suppresses_old_active_row_when_worker_is_live() -> None:
    updated_at = datetime(2026, 5, 15, 10, 0, tzinfo=timezone.utc)
    status = SimpleNamespace(
        flags=SimpleNamespace(queue_paused=False, maintenance_mode=False),
        config=SimpleNamespace(live_dispatch_enabled=True),
        conflicts=[],
        active_items=[
            {"project_id": "p", "current_run_id": "r", "updated_at": updated_at}
        ],
        warnings=[],
        source_freshness={},
        observations={
            "worker_preflight": {
                "payload": {
                    "checks": [
                        {
                            "name": "wake_gate_runs",
                            "data": {
                                "body": {
                                    "runs": [
                                        {
                                            "run_id": "r",
                                            "is_live": True,
                                            "lifecycle_state": "active",
                                            "active_process_count": 3,
                                        }
                                    ]
                                }
                            },
                        }
                    ]
                }
            }
        },
    )

    findings = queue_alert_findings(status, hang_after_sec=1)  # type: ignore[arg-type]

    assert findings == []


def test_queue_alert_findings_reads_live_worker_run_from_observation_model() -> None:
    updated_at = datetime(2026, 5, 15, 10, 0, tzinfo=timezone.utc)
    status = SimpleNamespace(
        flags=SimpleNamespace(queue_paused=False, maintenance_mode=False),
        config=SimpleNamespace(live_dispatch_enabled=True),
        conflicts=[],
        active_items=[
            {"project_id": "p", "current_run_id": "r", "updated_at": updated_at}
        ],
        warnings=[],
        source_freshness={},
        observations={
            "worker_preflight": DashboardObservationRecord(
                source="worker_preflight",
                status="warn",
                payload={
                    "ok": False,
                    "checks": [
                        {
                            "name": "wake_gate_runs",
                            "data": {
                                "body": {
                                    "runs": [
                                        {
                                            "run_id": "r",
                                            "is_live": True,
                                            "lifecycle_state": "active",
                                            "active_process_count": 3,
                                        }
                                    ]
                                }
                            },
                        }
                    ],
                },
            )
        },
    )

    findings = queue_alert_findings(status, hang_after_sec=1)  # type: ignore[arg-type]

    assert findings == []


def test_queue_alert_findings_suppresses_expired_stale_after_when_worker_is_live() -> (
    None
):
    stale_after = datetime(2026, 5, 15, 10, 0, tzinfo=timezone.utc)
    status = SimpleNamespace(
        flags=SimpleNamespace(queue_paused=False, maintenance_mode=False),
        config=SimpleNamespace(live_dispatch_enabled=True),
        conflicts=[],
        active_items=[
            {"project_id": "p", "current_run_id": "r", "stale_after": stale_after}
        ],
        warnings=[],
        source_freshness={},
        observations={
            "worker_preflight": {
                "payload": {
                    "checks": [
                        {
                            "name": "wake_gate_runs",
                            "data": {
                                "body": {
                                    "runs": [
                                        {
                                            "run_id": "r",
                                            "is_live": True,
                                            "lifecycle_state": "active",
                                            "active_process_count": 1,
                                        }
                                    ]
                                }
                            },
                        }
                    ]
                }
            }
        },
    )

    findings = queue_alert_findings(status, hang_after_sec=1)  # type: ignore[arg-type]

    assert findings == []


def test_queue_alert_findings_do_not_suppress_worker_stale_when_idle_lane_has_dispatchable_work() -> (
    None
):
    updated_at = datetime.now(timezone.utc)
    observed_at = datetime(2026, 5, 20, 12, 0, tzinfo=timezone.utc)
    status = SimpleNamespace(
        flags=SimpleNamespace(queue_paused=False, maintenance_mode=False),
        config=SimpleNamespace(live_dispatch_enabled=True),
        conflicts=[],
        active_items=[
            {
                "project_id": "active-cpu",
                "current_run_id": "run-cpu",
                "updated_at": updated_at,
                "machine_target": "cpu-proxmox-1",
            }
        ],
        next_candidate={"project_id": "queued-gb10", "machine_target": "gb10"},
        worker_lanes=[
            {
                "machine_target": "cpu-proxmox-1",
                "status": "active",
                "dispatch_available": False,
                "queued_count": 0,
            },
            {
                "machine_target": "gb10",
                "status": "idle",
                "dispatch_available": True,
                "queued_count": 1,
            },
        ],
        warnings=[],
        source_freshness={
            "worker_preflight": SimpleNamespace(
                stale=True,
                authority="cached worker preflight",
                observed_at=observed_at,
            )
        },
    )

    findings = queue_alert_findings(status, hang_after_sec=3600)  # type: ignore[arg-type]

    assert len(findings) == 1
    assert findings[0].source == "worker_preflight"
    assert "stale or missing" in findings[0].message


def test_has_idle_lane_dispatch_opportunity_s3776_helpers_extracted() -> None:
    """AGENTS.md guard for lowest OPEN alerts.py S3776 (~20 at _has_idle_lane_dispatch_opportunity)."""
    from pathlib import Path

    src = Path("enoch_control_plane/control_plane/alerts.py").read_text(
        encoding="utf-8"
    )
    assert "def _lane_has_dispatchable_queued_work(" in src
    assert "def _worker_lane_dicts(" in src

    from enoch_control_plane.control_plane.alerts import (
        _has_idle_lane_dispatch_opportunity,
        _lane_has_dispatchable_queued_work,
        _worker_lane_dicts,
    )

    status = SimpleNamespace(
        next_candidate=None,
        worker_lanes=[
            {"dispatch_available": False, "queued_count": 2},
            {"dispatch_available": True, "queued_count": 1},
            "not-a-lane",
        ],
    )
    assert _lane_has_dispatchable_queued_work(
        {"dispatch_available": True, "queued_count": 1}
    )
    assert not _lane_has_dispatchable_queued_work(
        {"dispatch_available": True, "queued_count": 0}
    )
    assert _worker_lane_dicts(status) == [  # type: ignore[arg-type]
        {"dispatch_available": False, "queued_count": 2},
        {"dispatch_available": True, "queued_count": 1},
    ]
    assert _has_idle_lane_dispatch_opportunity(status) is True  # type: ignore[arg-type]


def test_research_quality_alert_finding_s3776_helpers_extracted() -> None:
    """Guard the Research Quality alert path against returning to one large branch/data builder."""
    from pathlib import Path

    src = Path("enoch_control_plane/control_plane/alerts.py").read_text(
        encoding="utf-8"
    )
    assert "def _research_quality_alert_suggested_action(" in src
    assert "def _research_quality_alert_data(" in src


def test_send_pushover_rejects_non_http_api_url_before_urlopen(
    monkeypatch, tmp_path
) -> None:
    from enoch_control_plane.config import GateConfig
    from enoch_control_plane.control_plane import alerts

    config = GateConfig(
        state_dir=str(tmp_path / "state"),
        project_root=str(tmp_path / "projects"),
        dispatch_script_path=str(tmp_path / "dispatch.sh"),
        control_api_bearer_token="control",
        completion_callback_url="http://callback",
        completion_callback_token="callback",
        pushover_app_token="app",
        pushover_user_key="user",
        pushover_api_url="file:///etc/passwd",
    )

    def fake_urlopen(*_args, **_kwargs):
        raise AssertionError("urlopen should not run for unsafe pushover URL")

    monkeypatch.setattr(alerts.request, "urlopen", fake_urlopen)
    result = alerts.send_pushover(config, title="t", message="m")
    assert result.attempted is True
    assert result.ok is False
    assert "pushover api url must use http or https" in result.detail


def test_queue_alert_notify_does_not_treat_event_store_failure_as_cooldown(
    monkeypatch, tmp_path
) -> None:
    from enoch_control_plane.config import GateConfig
    from enoch_control_plane.control_plane import alerts
    from enoch_control_plane.control_plane.alerts import (
        PushoverResult,
        evaluate_and_notify_queue_alerts,
    )

    config = GateConfig(
        state_dir=str(tmp_path / "state"),
        project_root=str(tmp_path / "projects"),
        dispatch_script_path=str(tmp_path / "dispatch.sh"),
        control_api_bearer_token="control",
        completion_callback_url="http://callback",
        completion_callback_token="callback",
        live_dispatch_enabled=True,
        queue_alert_hang_after_sec=300,
        queue_alert_cooldown_sec=3600,
        pushover_alerts_enabled=True,
        pushover_app_token="app",
        pushover_user_key="user",
    )
    updated_at = datetime(2026, 5, 15, 10, 0, tzinfo=timezone.utc)
    status = SimpleNamespace(
        flags=SimpleNamespace(queue_paused=False, maintenance_mode=False),
        config=SimpleNamespace(live_dispatch_enabled=True),
        conflicts=[],
        active_items=[
            {"project_id": "p", "current_run_id": "r", "updated_at": updated_at}
        ],
        warnings=[],
        source_freshness={},
        dispatch_safe=False,
        dispatch_blockers=["active row stale"],
    )

    class Store:
        def event_rows(self, limit=100):  # noqa: ANN001 - alert store fake
            return []

        def append_event(self, **_kwargs):  # noqa: ANN003 - alert store fake
            raise RuntimeError("event store unavailable")

    monkeypatch.setattr(
        alerts,
        "send_pushover",
        lambda *args, **kwargs: PushoverResult(attempted=True, ok=True, detail="sent"),
    )

    result = evaluate_and_notify_queue_alerts(
        config=config,
        store=Store(),
        status=status,
        dry_run=False,
        force_notify=False,
        requested_by="test",
    )  # type: ignore[arg-type]

    assert result["should_alert"] is True
    assert result["sent"] is True
    assert result["suppressed_by_cooldown"] is False
    assert "event store unavailable" in result["event_append_error"]


def test_format_queue_alert_message_lists_first_five_findings() -> None:
    from enoch_control_plane.control_plane.alerts import _format_queue_alert_message
    from enoch_control_plane.control_plane.models import DashboardFinding

    status = SimpleNamespace(
        active_items=[{"project_id": "p"}],
        dispatch_blockers=["stale active row"],
    )
    findings = [
        DashboardFinding(
            severity="warn",
            source=f"source-{index}",
            authority="test",
            message=f"message-{index}",
            observed_at=None,
            suggested_action="inspect",
        )
        for index in range(7)
    ]

    message = _format_queue_alert_message(status, findings)  # type: ignore[arg-type]

    assert "message-0" in message
    assert "message-4" in message
    assert "message-5" not in message
    assert "+2 more" in message


def test_queue_alert_notify_suppresses_cooldown_duplicate(
    monkeypatch, tmp_path
) -> None:
    from enoch_control_plane.config import GateConfig
    from enoch_control_plane.control_plane import alerts
    from enoch_control_plane.control_plane.alerts import (
        evaluate_and_notify_queue_alerts,
    )

    config = GateConfig(
        state_dir=str(tmp_path / "state"),
        project_root=str(tmp_path / "projects"),
        dispatch_script_path=str(tmp_path / "dispatch.sh"),
        control_api_bearer_token="control",
        completion_callback_url="http://callback",
        completion_callback_token="callback",
        live_dispatch_enabled=True,
        queue_alert_hang_after_sec=300,
        queue_alert_cooldown_sec=3600,
        pushover_alerts_enabled=True,
        pushover_app_token="app",
        pushover_user_key="user",
    )
    updated_at = datetime(2026, 5, 15, 10, 0, tzinfo=timezone.utc)
    status = SimpleNamespace(
        flags=SimpleNamespace(queue_paused=False, maintenance_mode=False),
        config=SimpleNamespace(live_dispatch_enabled=True),
        conflicts=[],
        active_items=[
            {"project_id": "p", "current_run_id": "r", "updated_at": updated_at}
        ],
        warnings=[],
        source_freshness={},
        dispatch_safe=False,
        dispatch_blockers=["active row stale"],
    )

    class Store:
        def event_rows(self, limit=100):  # noqa: ANN001 - alert store fake
            return []

        def append_event(self, **_kwargs):  # noqa: ANN003 - alert store fake
            return ("evt-1", False)

    def fail_pushover(*_args, **_kwargs):  # noqa: ANN001 - test guard
        raise AssertionError("send_pushover should not run for cooldown duplicate")

    monkeypatch.setattr(alerts, "send_pushover", fail_pushover)

    result = evaluate_and_notify_queue_alerts(
        config=config,
        store=Store(),
        status=status,
        dry_run=False,
        force_notify=False,
        requested_by="test",
    )  # type: ignore[arg-type]

    assert result["should_alert"] is True
    assert result["sent"] is False
    assert result["suppressed_by_cooldown"] is True
    assert result["notification"]["detail"] == "cooldown duplicate suppressed"


def test_queue_alert_forwards_inserted_alert_to_hermes_webhook(
    monkeypatch, tmp_path
) -> None:
    from enoch_control_plane.config import GateConfig
    from enoch_control_plane.control_plane import alerts
    from enoch_control_plane.control_plane.alerts import (
        PushoverResult,
        WebhookResult,
        evaluate_and_notify_queue_alerts,
    )

    config = GateConfig(
        state_dir=str(tmp_path / "state"),
        project_root=str(tmp_path / "projects"),
        dispatch_script_path=str(tmp_path / "dispatch.sh"),
        control_api_bearer_token="control",
        completion_callback_url="http://callback",
        completion_callback_token="callback",
        live_dispatch_enabled=True,
        queue_alert_hang_after_sec=300,
        queue_alert_cooldown_sec=3600,
        pushover_alerts_enabled=True,
        pushover_app_token="app",
        pushover_user_key="user",
        hermes_alert_webhook_enabled=True,
        hermes_alert_webhook_url="http://127.0.0.1:8644/webhooks/enoch-alert",
    )
    updated_at = datetime(2026, 5, 15, 10, 0, tzinfo=timezone.utc)
    status = SimpleNamespace(
        flags=SimpleNamespace(queue_paused=False, maintenance_mode=False),
        config=SimpleNamespace(live_dispatch_enabled=True),
        conflicts=[],
        active_items=[
            {"project_id": "p", "current_run_id": "r", "updated_at": updated_at}
        ],
        warnings=[],
        source_freshness={},
        dispatch_safe=False,
        dispatch_blockers=["active row stale"],
    )

    class Store:
        def event_rows(self, limit=100):  # noqa: ANN001 - alert store fake
            return []

        def append_event(self, **_kwargs):  # noqa: ANN003 - alert store fake
            return ("evt-1", True)

    seen: dict[str, object] = {}

    monkeypatch.setattr(
        alerts,
        "send_pushover",
        lambda *args, **kwargs: PushoverResult(attempted=True, ok=True, detail="sent"),
    )

    def fake_webhook(*_args, **kwargs):  # noqa: ANN001 - test guard
        seen.update(kwargs)
        return WebhookResult(
            attempted=True, ok=True, status_code=202, detail="accepted"
        )

    monkeypatch.setattr(alerts, "send_hermes_alert_webhook", fake_webhook)

    result = evaluate_and_notify_queue_alerts(
        config=config,
        store=Store(),
        status=status,
        dry_run=False,
        force_notify=False,
        requested_by="test",
    )  # type: ignore[arg-type]

    assert result["should_alert"] is True
    assert result["sent"] is True
    assert result["hermes_webhook"] == {
        "attempted": True,
        "ok": True,
        "status_code": 202,
        "detail": "accepted",
    }
    assert seen["fingerprint"] == result["fingerprint"]
    assert seen["event_id"] == "evt-1"
    assert seen["payload"]["fingerprint"] == result["fingerprint"]


def test_queue_alert_does_not_forward_cooldown_duplicate_to_hermes_webhook(
    monkeypatch, tmp_path
) -> None:
    from enoch_control_plane.config import GateConfig
    from enoch_control_plane.control_plane import alerts
    from enoch_control_plane.control_plane.alerts import (
        evaluate_and_notify_queue_alerts,
    )

    config = GateConfig(
        state_dir=str(tmp_path / "state"),
        project_root=str(tmp_path / "projects"),
        dispatch_script_path=str(tmp_path / "dispatch.sh"),
        control_api_bearer_token="control",
        completion_callback_url="http://callback",
        completion_callback_token="callback",
        live_dispatch_enabled=True,
        queue_alert_hang_after_sec=300,
        queue_alert_cooldown_sec=3600,
        pushover_alerts_enabled=True,
        pushover_app_token="app",
        pushover_user_key="user",
        hermes_alert_webhook_enabled=True,
        hermes_alert_webhook_url="http://127.0.0.1:8644/webhooks/enoch-alert",
    )
    updated_at = datetime(2026, 5, 15, 10, 0, tzinfo=timezone.utc)
    status = SimpleNamespace(
        flags=SimpleNamespace(queue_paused=False, maintenance_mode=False),
        config=SimpleNamespace(live_dispatch_enabled=True),
        conflicts=[],
        active_items=[
            {"project_id": "p", "current_run_id": "r", "updated_at": updated_at}
        ],
        warnings=[],
        source_freshness={},
        dispatch_safe=False,
        dispatch_blockers=["active row stale"],
    )

    class Store:
        def event_rows(self, limit=100):  # noqa: ANN001 - alert store fake
            return []

        def append_event(self, **_kwargs):  # noqa: ANN003 - alert store fake
            return ("evt-1", False)

    def fail_webhook(*_args, **_kwargs):  # noqa: ANN001 - test guard
        raise AssertionError("Hermes webhook should not run for cooldown duplicate")

    monkeypatch.setattr(alerts, "send_hermes_alert_webhook", fail_webhook)

    result = evaluate_and_notify_queue_alerts(
        config=config,
        store=Store(),
        status=status,
        dry_run=False,
        force_notify=False,
        requested_by="test",
    )  # type: ignore[arg-type]

    assert result["should_alert"] is True
    assert result["suppressed_by_cooldown"] is True
    assert result["hermes_webhook"]["attempted"] is False
    assert result["hermes_webhook"]["ok"] is True
    assert result["hermes_webhook"]["detail"] == "cooldown duplicate suppressed"


def test_send_hermes_alert_webhook_uses_hmac_signature_header(
    monkeypatch, tmp_path
) -> None:
    import hashlib
    import hmac
    import json

    from enoch_control_plane.config import GateConfig
    from enoch_control_plane.control_plane import alerts
    from enoch_control_plane.control_plane.models import DashboardFinding

    config = GateConfig(
        state_dir=str(tmp_path / "state"),
        project_root=str(tmp_path / "projects"),
        dispatch_script_path=str(tmp_path / "dispatch.sh"),
        control_api_bearer_token="control",
        completion_callback_url="http://callback",
        completion_callback_token="callback",
        hermes_alert_webhook_url="http://127.0.0.1:8644/webhooks/enoch-alert",
        hermes_alert_webhook_secret="route-secret",
    )
    seen: dict[str, object] = {}

    class FakeResponse:
        status = 202

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _limit=2048):
            return b"accepted"

    def fake_urlopen(req, timeout=0):  # noqa: ANN001 - urllib request fake
        seen["timeout"] = timeout
        seen["data"] = req.data
        seen["headers"] = dict(req.header_items())
        return FakeResponse()

    monkeypatch.setattr(alerts.request, "urlopen", fake_urlopen)
    result = alerts.send_hermes_alert_webhook(
        config,
        fingerprint="fp",
        event_id="evt",
        message="message",
        findings=[
            DashboardFinding(
                severity="critical",
                source="test",
                authority="test",
                message="critical test",
                suggested_action="inspect",
            )
        ],
        payload={"fingerprint": "fp"},
    )

    headers = seen["headers"]
    data = seen["data"]
    assert result.ok is True
    assert (
        headers["X-hub-signature-256"]
        == "sha256=" + hmac.new(b"route-secret", data, hashlib.sha256).hexdigest()
    )
    assert "Authorization" not in headers
    body = json.loads(data.decode())
    assert body["fingerprint"] == "fp"
    assert body["queue_alert"]["fingerprint"] == "fp"


def test_send_hermes_alert_webhook_rejects_non_http_url_before_urlopen(
    monkeypatch, tmp_path
) -> None:
    from enoch_control_plane.config import GateConfig
    from enoch_control_plane.control_plane import alerts
    from enoch_control_plane.control_plane.models import DashboardFinding

    config = GateConfig(
        state_dir=str(tmp_path / "state"),
        project_root=str(tmp_path / "projects"),
        dispatch_script_path=str(tmp_path / "dispatch.sh"),
        control_api_bearer_token="control",
        completion_callback_url="http://callback",
        completion_callback_token="callback",
        hermes_alert_webhook_url="file:///etc/passwd",
    )

    def fake_urlopen(*_args, **_kwargs):  # noqa: ANN001 - test guard
        raise AssertionError("urlopen should not run for unsafe Hermes webhook URL")

    monkeypatch.setattr(alerts.request, "urlopen", fake_urlopen)
    result = alerts.send_hermes_alert_webhook(
        config,
        fingerprint="fp",
        event_id="evt",
        message="message",
        findings=[
            DashboardFinding(
                severity="critical",
                source="test",
                authority="test",
                message="critical test",
                suggested_action="inspect",
            )
        ],
        payload={"fingerprint": "fp"},
    )

    assert result.attempted is True
    assert result.ok is False
    assert "hermes alert webhook url must use http or https" in result.detail


def test_queue_alert_findings_suppresses_worker_settling_warning() -> None:
    status = SimpleNamespace(
        flags=SimpleNamespace(queue_paused=False, maintenance_mode=False),
        config=SimpleNamespace(live_dispatch_enabled=True),
        conflicts=[],
        active_items=[],
        warnings=[
            SimpleNamespace(
                severity="warn",
                source="worker_settling",
                authority="cross-source active-lane reconciliation",
                message="GB10 worker is settling a recent worker run with no active process",
                observed_at="2026-05-21T00:00:00+00:00",
                suggested_action="wait",
                data={},
            )
        ],
        source_freshness={},
    )

    findings = queue_alert_findings(status, hang_after_sec=3600)  # type: ignore[arg-type]

    assert findings == []
