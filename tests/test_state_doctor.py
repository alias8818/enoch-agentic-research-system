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
        }
    )

    assert not audit["ok"]
    assert audit["paper_pipeline_inconsistent"] is True


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
        "control_plane": {"checked": False},
    }

    evaluation = evaluate_report(report)

    assert evaluation["failures"] == []
    assert "legacy internal rows remain: runs.state.unknown has 2 row(s)" in evaluation["warnings"]
