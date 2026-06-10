from __future__ import annotations

from pathlib import Path

from scripts.compare_structured_output_modes import ProbeRow, summarize


def _row(mode: str, *, schema_ok: bool, malformed_kind: str = "") -> ProbeRow:
    return ProbeRow(
        provider_id="openrouter",
        model_id="model-a",
        prompt_contract="candidate_json",
        structured_output_mode=mode,
        ok=True,
        status_code=200,
        valid_json=schema_ok or malformed_kind != "invalid_json",
        schema_ok=schema_ok,
        malformed_kind=malformed_kind,
        recoverable_json_shape=malformed_kind == "legacy_candidate_array_shape",
        candidate_count=1 if schema_ok else 0,
        candidate_title_complete=schema_ok,
        candidate_rationale_complete=schema_ok,
        finish_reason="stop",
        visible_chars=64,
        latency_ms=1000,
        response_format_type=mode,
        error="",
        response_preview="",
    )


def test_structured_output_mode_summary_tracks_shape_and_quality_rates() -> None:
    report = summarize(
        [
            _row("prompt_only", schema_ok=False, malformed_kind="invalid_json"),
            _row("json_object", schema_ok=True),
            _row("json_schema", schema_ok=True),
        ]
    )

    by_mode = report["mode_summary"]
    assert by_mode["prompt_only"]["schema_ok_rate"] == 0
    assert by_mode["prompt_only"]["invalid_json"] == 1
    assert by_mode["json_object"]["schema_ok_rate"] == 1
    assert by_mode["json_object"]["complete_candidate_rate"] == 1
    assert by_mode["json_schema"]["schema_ok_rate"] == 1
    assert by_mode["json_schema"]["complete_candidate_rate"] == 1


def test_structured_output_mode_script_does_not_import_mutation_surfaces() -> None:
    source = Path("scripts/compare_structured_output_modes.py").read_text(
        encoding="utf-8"
    )

    assert "write_llm_settings" not in source
    assert "save_llm_settings" not in source
    assert "_live_dispatch" not in source
    assert "append_event(" not in source
    assert "settings/llm/test" in source
