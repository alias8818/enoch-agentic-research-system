from enoch_control_plane.control_plane.models import (
    PaperStatus,
    QueueStatus,
    ReviewStatus,
    RunState,
)
from enoch_control_plane.control_plane.state_contract import (
    PAPER_READINESS_CONTRACT,
    PAPER_STATUSES,
    PUBLICATION_AUTOMATION_STATUSES,
    QUEUE_STATUSES,
    RUN_STATES,
    STATE_CONTRACT,
    STATE_SURFACE_INVENTORY,
    STATE_REDUCTION_PLAN,
)
from scripts.generate_state_reduction_audit import render
from scripts.validate_state_contract import validate


def test_model_enums_are_covered_by_state_contract() -> None:
    assert {item.value for item in QueueStatus} <= QUEUE_STATUSES
    assert {item.value for item in RunState} <= RUN_STATES
    assert {item.value for item in PaperStatus} <= PAPER_STATUSES
    assert {item.value for item in ReviewStatus} <= PUBLICATION_AUTOMATION_STATUSES


def test_state_contract_validator_covers_migration_literals() -> None:
    result = validate()
    assert result["ok"], result["failures"]


def test_state_contract_names_all_persisted_state_surfaces() -> None:
    expected = {
        "queue_items.status",
        "queue_items.last_run_state",
        "runs.state",
        "runs.gate_state",
        "papers.paper_status",
        "publication_automation_items.automation_status",
        "project_decisions.decision_gate_state",
        "ideas.idea_status",
        "projects.origin_idea_status",
    }
    assert expected <= set(STATE_CONTRACT)


def test_state_reduction_plan_covers_every_raw_state_value() -> None:
    assert set(STATE_REDUCTION_PLAN) == set(STATE_CONTRACT)
    for surface, values in STATE_CONTRACT.items():
        assert set(STATE_REDUCTION_PLAN[surface]) == values
        for value, decision in STATE_REDUCTION_PLAN[surface].items():
            assert decision["operator_lane"]
            assert decision["disposition"] in {
                "keep",
                "alias",
                "legacy_internal",
                "migrate_after_freeze",
            }


def test_state_surface_inventory_classifies_non_lifecycle_signals() -> None:
    for surface in STATE_CONTRACT:
        assert STATE_SURFACE_INVENTORY[surface]["class"] == "canonical_lifecycle"
    assert (
        STATE_SURFACE_INVENTORY["queue_items.manual_review_required"]["class"]
        == "attention_flag"
    )
    assert (
        STATE_SURFACE_INVENTORY["queue_items.next_action_hint"]["class"]
        == "operator_hint"
    )
    assert (
        STATE_SURFACE_INVENTORY["control_events.event_type"]["class"]
        == "event_taxonomy"
    )
    assert (
        STATE_SURFACE_INVENTORY["runs.dispatch_mode"]["class"] == "type_discriminator"
    )


def test_generated_state_reduction_audit_includes_state_surface_inventory() -> None:
    text = render(live={})
    assert "## State-like surface inventory" in text
    assert "`queue_items.manual_review_required` | `attention_flag`" in text
    assert "`queue_items.status` | `canonical_lifecycle` | `queue_items.status`" in text


def test_paper_readiness_contract_covers_every_maturity_state() -> None:
    states = PAPER_READINESS_CONTRACT["maturity_states"]
    transitions = PAPER_READINESS_CONTRACT["transitions"]

    assert set(states) == {
        "execution_complete",
        "pilot_signal",
        "analysis_ready",
        "deepen_required",
        "paper_candidate",
        "paper_ready",
        "archive_no_paper",
    }
    for state, definition in states.items():
        assert definition["definition"]
        assert definition["allowed_inputs"]
        assert definition["allowed_outputs"]
        assert definition["operator_lane"]

    transition_sources = {item["from"] for item in transitions}
    transition_targets = {item["to"] for item in transitions}
    assert transition_sources | transition_targets <= set(states) | {"run_completed"}


def test_paper_readiness_contract_names_hard_gate_and_score_floors() -> None:
    hard_gate = PAPER_READINESS_CONTRACT["hard_gate_requirements"]
    score_floors = PAPER_READINESS_CONTRACT["score_floors"]

    assert {
        "hypothesis_declared",
        "baseline_or_comparator_present",
        "metric_result_table_present",
        "success_threshold_declared",
        "artifact_manifest_present",
        "claim_ledger_present",
        "failure_cases_present",
        "reproduction_command_or_bounded_replay_present",
        "related_work_or_novelty_check_present",
        "claim_scope_and_scale_limits_present",
        "no_unresolved_central_claim_contradiction",
    } <= set(hard_gate)
    assert score_floors["total"] == 78
    assert score_floors["evidence_directness"] == 4
    assert score_floors["claim_support"] == 4
