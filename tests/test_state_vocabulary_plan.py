from scripts.generate_state_vocabulary_plan import DOMAIN_TARGETS, cleanup_action, final_state_for, iter_mapping_rows, render
from omx_wake_gate.control_plane.state_contract import STATE_REDUCTION_PLAN


def test_state_vocabulary_plan_covers_every_raw_state_contract_value() -> None:
    rows = iter_mapping_rows()
    expected = {(surface, value or "<blank>") for surface, values in STATE_REDUCTION_PLAN.items() for value in values}
    actual = {(row["surface"], row["raw_value"]) for row in rows}

    assert actual == expected


def test_state_vocabulary_plan_uses_only_declared_final_states_and_actions() -> None:
    allowed_states = {domain: set(config["states"]) for domain, config in DOMAIN_TARGETS.items()}
    for row in iter_mapping_rows():
        assert row["final_state"] in allowed_states[row["domain"]]
        assert row["cleanup_action"] in {"keep", "alias", "migrate", "retire"}
        if row["cleanup_action"] in {"alias", "migrate"}:
            assert row["safe_auto_migrate"] == "yes"
            assert row["migration_target"] != "—"
        if row["cleanup_action"] == "retire":
            assert row["safe_auto_migrate"] == "no"


def test_state_vocabulary_plan_locks_high_risk_boundaries() -> None:
    assert final_state_for("project_decisions.decision_gate_state", "positive") == "paper_positive"
    assert final_state_for("project_decisions.decision_gate_state", "negative") == "done_no_paper"
    assert final_state_for("project_decisions.decision_gate_state", "needs_review") == "done_no_paper"
    assert final_state_for("runs.state", "wake_ready") == "delivered"
    assert final_state_for("runs.gate_state", "") == "historical"
    assert final_state_for("papers.paper_status", "publication_draft") == "finalizing"
    assert cleanup_action("migrate_after_freeze") == "migrate"
    assert cleanup_action("legacy_internal") == "retire"


def test_rendered_state_vocabulary_plan_contains_migration_safe_table() -> None:
    text = render()
    assert "## Final small state sets" in text
    assert "## Migration-safe raw-state mapping" in text
    assert "| `retire` | Historical/import/provenance value accepted for audit only." in text
    assert "`write_needed`" not in text  # this is a paper-pipeline counter, not a raw state vocabulary item
