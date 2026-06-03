from __future__ import annotations

from enoch_control_plane.control_plane.read_models import (
    blocked_attention_samples_from_rows,
)


def test_blocked_attention_samples_include_non_blocked_attention_rows() -> None:
    rows = [
        {
            "project_id": "needs-review-row",
            "project_name": "Needs Review Candidate",
            "status": "needs_review",
            "next_action_hint": "inspect_evidence",
            "current_run_id": "run-needs-review",
            "manual_review_required": True,
        },
        {
            "project_id": "queued-row",
            "project_name": "Queued Candidate",
            "status": "queued",
            "manual_review_required": False,
        },
    ]

    samples = blocked_attention_samples_from_rows(rows)

    assert samples == [
        {
            "project_id": "needs-review-row",
            "project_name": "Needs Review Candidate",
            "status": "needs_review",
            "next_action_hint": "inspect_evidence",
            "current_run_id": "run-needs-review",
            "operator_lane": "needs_operator",
            "operator_detail_stage": "blocked_needs_operator",
        }
    ]
