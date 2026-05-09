from enoch_control_plane.control_plane.router import _project_prompt
from enoch_control_plane.control_plane.supabase_store import _enforced_followup_depth


def test_followup_depth_uses_controller_lineage_over_worker_reset() -> None:
    assert _enforced_followup_depth({"followup_depth": 1}, {"source_payload_json": {"followup_depth": 2}}) == 2
    assert _enforced_followup_depth({"followup_depth": 2}, {"source_payload_json": {"followup_depth": 1}}) == 2


def test_worker_prompt_makes_controller_followup_depth_explicit() -> None:
    prompt = _project_prompt({
        "project_id": "followup-1",
        "project_name": "Follow-up One",
        "idea_source_kind": "followup_branch",
        "source_followup_depth": 2,
    })
    assert "Controller source kind: followup_branch" in prompt
    assert "Controller follow-up depth: 2" in prompt
    assert "copy that exact integer into `followup_depth`" in prompt
    assert "do not reset it to 1" in prompt
    assert "set `followup_recommended: false`" in prompt
