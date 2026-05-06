from omx_wake_gate.control_plane.models import PaperStatus, QueueStatus, ReviewStatus, RunState
from omx_wake_gate.control_plane.state_contract import (
    PAPER_STATUSES,
    PUBLICATION_AUTOMATION_STATUSES,
    QUEUE_STATUSES,
    RUN_STATES,
    STATE_CONTRACT,
)
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
