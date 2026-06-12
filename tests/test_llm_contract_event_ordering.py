from enoch_control_plane.control_plane.read_models import (
    _latest_llm_format_event_for_contract,
    _llm_format_contract_passed,
)


def test_latest_llm_format_event_prefers_newest_matching_event_over_stale_pass() -> None:
    newest_failure = {
        "prompt_contract": "strict_json",
        "structured_output_mode": "json_schema",
        "checked_at": "2026-06-12T18:00:00Z",
        "valid_json": False,
        "schema_ok": False,
        "malformed_kind": "schema_mismatch",
        "visible_chars": 120,
    }
    stale_pass = {
        "prompt_contract": "strict_json",
        "structured_output_mode": "json_schema",
        "checked_at": "2026-06-12T17:00:00Z",
        "valid_json": True,
        "schema_ok": True,
        "malformed_kind": "",
        "visible_chars": 120,
    }

    event = _latest_llm_format_event_for_contract(
        [newest_failure, stale_pass], "strict_json"
    )

    assert event is newest_failure
    assert not _llm_format_contract_passed(event)
