from scripts.state_doctor import _dashboard_audit, _live_reduction_drift, evaluate_report


def test_dashboard_audit_rejects_detail_keys_in_operator_counts() -> None:
    audit = _dashboard_audit(
        {
            "operator_counts": {"write_paper": 0, "run_complete_draft_needed": 1, "needs_attention": 0},
            "operator_detail_counts": {"run_complete_draft_needed": 1},
            "paper_pipeline": {
                "write_needed": 0,
                "raw_completed_no_paper_candidates": 1,
                "not_writable_by_decision_gate": 1,
                "finalize_needed": 0,
                "publish_ready": 0,
            },
            "investigation_pipeline": {"followup_needed": 0, "max_followup_depth": 2},
        }
    )

    assert not audit["ok"]
    assert audit["raw_detail_keys_in_operator_counts"] == ["run_complete_draft_needed"]


def test_dashboard_audit_enforces_positive_only_pipeline_boundary() -> None:
    audit = _dashboard_audit(
        {
            "operator_counts": {"write_paper": 0, "needs_attention": 0},
            "operator_detail_counts": {},
            "paper_pipeline": {
                "write_needed": 0,
                "raw_completed_no_paper_candidates": 220,
                "not_writable_by_decision_gate": 219,
                "finalize_needed": 0,
                "publish_ready": 491,
            },
            "investigation_pipeline": {"followup_needed": 0, "max_followup_depth": 2},
        }
    )

    assert not audit["ok"]
    assert audit["paper_pipeline_inconsistent"] is True


def test_dashboard_audit_requires_investigation_pipeline_boundary() -> None:
    audit = _dashboard_audit(
        {
            "operator_counts": {"write_paper": 0, "needs_attention": 0},
            "operator_detail_counts": {},
            "paper_pipeline": {
                "write_needed": 0,
                "raw_completed_no_paper_candidates": 220,
                "not_writable_by_decision_gate": 220,
                "finalize_needed": 0,
                "publish_ready": 0,
            },
            "investigation_pipeline": {"followup_needed": 0},
        }
    )

    assert not audit["ok"]
    assert audit["missing_investigation_pipeline_keys"] == ["max_followup_depth"]


def test_reduction_drift_hard_fails_alias_and_migrate_after_freeze_rows() -> None:
    drift = _live_reduction_drift(
        {
            "queue_items.last_run_state": [("session_finished_ready", 2), ("wake_ready", 3)],
            "runs.state": [("needs_review", 1)],
        }
    )

    assert {row["value"] for row in drift["hard_rows"]} == {"session_finished_ready", "needs_review"}


def test_evaluate_report_treats_legacy_internal_rows_as_warning_only() -> None:
    report = {
        "state_contract": {"ok": True, "failures": []},
        "normalization": {"checked": True, "total_rows": 0},
        "live_reduction_drift": {
            "hard_rows": [],
            "warning_rows": [
                {
                    "surface": "runs.state",
                    "value": "unknown",
                    "rows": 2,
                    "disposition": "legacy_internal",
                }
            ],
        },
        "legacy_runtime_context": {"checked": True, "active_runtime_drift": []},
        "control_plane": {"checked": False},
    }

    evaluation = evaluate_report(report)

    assert evaluation["failures"] == []
    assert "legacy internal rows remain: runs.state.unknown has 2 row(s)" in evaluation["warnings"]


def test_evaluate_report_fails_legacy_internal_rows_on_active_runtime_lane() -> None:
    report = {
        "state_contract": {"ok": True, "failures": []},
        "normalization": {"checked": True, "total_rows": 0},
        "live_reduction_drift": {
            "hard_rows": [],
            "warning_rows": [
                {
                    "surface": "runs.gate_state",
                    "value": "",
                    "rows": 4,
                    "disposition": "legacy_internal",
                }
            ],
        },
        "legacy_runtime_context": {
            "checked": True,
            "active_runtime_drift": [
                {
                    "surface": "runs.gate_state.blank",
                    "active_queue": 1,
                    "total": 4,
                }
            ],
        },
        "control_plane": {"checked": False},
    }

    evaluation = evaluate_report(report)

    assert evaluation["failures"] == [
        "legacy/internal state attached to active runtime lane: runs.gate_state.blank has 1 active row(s) out of 4"
    ]


def test_evaluate_report_suppresses_classified_historical_residue_noise() -> None:
    report = {
        "state_contract": {"ok": True, "failures": []},
        "normalization": {"checked": True, "total_rows": 0},
        "live_reduction_drift": {
            "hard_rows": [],
            "warning_rows": [
                {
                    "surface": "runs.gate_state",
                    "value": "",
                    "rows": 722,
                    "disposition": "legacy_internal",
                },
                {
                    "surface": "runs.state",
                    "value": "unknown",
                    "rows": 240,
                    "disposition": "legacy_internal",
                },
            ],
        },
        "legacy_runtime_context": {
            "checked": True,
            "surfaces": {
                "runs.gate_state.blank": {
                    "classification": "historical_or_attention_residue",
                    "active_queue": 0,
                    "total": 722,
                },
                "runs.state.unknown": {
                    "classification": "historical_or_attention_residue",
                    "active_queue": 0,
                    "total": 240,
                },
            },
            "active_runtime_drift": [],
        },
        "control_plane": {"checked": False},
    }

    evaluation = evaluate_report(report)

    assert evaluation["failures"] == []
    assert not any("legacy internal rows remain" in item for item in evaluation["warnings"])


def test_state_doctor_allows_queued_item_without_last_run_state() -> None:
    report = {
        "state_contract": {"ok": True, "failures": []},
        "normalization": {"checked": True, "total_rows": 0},
        "live_reduction_drift": {
            "hard_rows": [],
            "warning_rows": [
                {
                    "surface": "queue_items.last_run_state",
                    "value": "",
                    "rows": 1,
                    "disposition": "legacy_internal",
                },
            ],
        },
        "legacy_runtime_context": {
            "checked": True,
            "surfaces": {
                "queue_items.last_run_state.blank": {
                    "classification": "historical_or_attention_residue",
                    "active_queue": 0,
                    "queued_without_run": 1,
                    "total": 1,
                },
            },
            "active_runtime_drift": [],
        },
        "control_plane": {"checked": False},
    }

    evaluation = evaluate_report(report)

    assert evaluation["failures"] == []
    assert not any("legacy internal rows remain" in item for item in evaluation["warnings"])
