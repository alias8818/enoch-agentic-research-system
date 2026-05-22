from enoch_control_plane.control_plane.router import _project_prompt
from enoch_control_plane.control_plane.supabase_store import (
    _enforced_followup_depth,
    _followup_escalation_payload,
)


def test_followup_depth_uses_controller_lineage_over_worker_reset() -> None:
    assert (
        _enforced_followup_depth(
            {"followup_depth": 1}, {"source_payload_json": {"followup_depth": 2}}
        )
        == 2
    )
    assert (
        _enforced_followup_depth(
            {"followup_depth": 2}, {"source_payload_json": {"followup_depth": 1}}
        )
        == 2
    )


def test_worker_prompt_makes_controller_followup_depth_explicit() -> None:
    prompt = _project_prompt(
        {
            "project_id": "followup-1",
            "project_name": "Follow-up One",
            "idea_source_kind": "followup_branch",
            "source_followup_depth": 4,
        }
    )
    assert "Controller source kind: followup_branch" in prompt
    assert "Controller follow-up depth: 4" in prompt
    assert "copy that exact integer into `followup_depth`" in prompt
    assert "do not reset it to 1" in prompt
    assert "set `followup_recommended: false`" in prompt
    assert "current/controller follow-up depth is 4 or greater" in prompt


def test_promising_negative_followup_escalates_beyond_proxy() -> None:
    payload = _followup_escalation_payload(
        {
            "decision_payload_json": {
                "project_decision": {
                    "project_decision": "finalize_negative",
                    "hypothesis_status": "mixed",
                    "evidence_strength": "moderate",
                }
            },
            "followup_title": "Medium direct evidence follow-up",
            "followup_hypothesis": "The mechanism still holds on direct metrics.",
            "followup_required_evidence": [
                "direct baseline comparison",
                "fixed-seed ablation",
            ],
            "followup_success_threshold": "Beat the real baseline on target metrics.",
            "followup_stop_condition": "Stop if the direct metric regresses.",
        },
        2,
    )

    assert payload["promising_escalation"] is True
    assert payload["research_ladder_tier"] == 2
    assert "fixed seeds" in payload["research_ladder_label"]
    assert any("Do not close" in item for item in payload["worker_prompt_guidance"])


def test_worker_prompt_includes_controller_escalation_ladder() -> None:
    prompt = _project_prompt(
        {
            "project_id": "followup-2",
            "project_name": "Follow-up Two",
            "idea_source_kind": "followup_branch",
            "source_followup_depth": 2,
            "idea_source_payload_json": {
                "research_ladder_tier": 2,
                "research_ladder_label": "Tier 2: medium confirmation with fixed seeds, ablations, and a real baseline",
                "research_ladder_budget_hint": "large",
                "promising_escalation": True,
                "worker_prompt_guidance": [
                    "Use direct target metrics and a real baseline."
                ],
            },
        }
    )
    assert "## Controller escalation ladder" in prompt
    assert "Tier 2: medium confirmation" in prompt
    assert "Promising escalation: yes" in prompt
    assert "Use direct target metrics and a real baseline." in prompt


def test_worker_prompt_rejects_malformed_escalation_guidance() -> None:
    prompt = _project_prompt(
        {
            "project_id": "followup-3",
            "project_name": "Follow-up Three",
            "idea_source_kind": "followup_branch",
            "idea_source_payload_json": {
                "research_ladder_tier": 2,
                "worker_prompt_guidance": "do not iterate this string as guidance",
            },
        }
    )

    assert "## Controller escalation ladder" in prompt
    assert "do not iterate this string as guidance" not in prompt
    assert "Preserve the strict paper gate" in prompt
