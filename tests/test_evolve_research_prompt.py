from __future__ import annotations

import json
from pathlib import Path

from scripts import evolve_research_prompt


def _write_evalset(path: Path) -> None:
    rows = [
        {
            "schema_version": "enoch_research_quality_evalcase_v1",
            "case_id": "duplicateish_candidate:a",
            "case_type": "duplicateish_candidate",
        },
        {
            "schema_version": "enoch_research_quality_evalcase_v1",
            "case_id": "proxy_only_positive:b",
            "case_type": "proxy_only_positive",
        },
        {
            "schema_version": "enoch_research_quality_evalcase_v1",
            "case_id": "supported_but_negative_warning:c",
            "case_type": "supported_but_negative_warning",
        },
        {
            "schema_version": "enoch_research_quality_evalcase_v1",
            "case_id": "max_depth_followup_ending:d",
            "case_type": "max_depth_followup_ending",
        },
        {
            "schema_version": "enoch_research_quality_evalcase_v1",
            "case_id": "useful_adjacent_followup:e",
            "case_type": "useful_adjacent_followup",
        },
    ]
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def test_evolve_research_prompt_outputs_patch_only_artifacts(tmp_path: Path) -> None:
    evalset = tmp_path / "evalset.jsonl"
    source = tmp_path / "research_provider_generate.py"
    output_dir = tmp_path / "out"
    _write_evalset(evalset)
    source.write_text(
        'def build_generation_prompt():\n    return """\nAvoid fake citations. Avoid tiny hyperparameter or +0.05% ideas.\n"""\n',
        encoding="utf-8",
    )
    source_before = source.read_text(encoding="utf-8")

    assert (
        evolve_research_prompt.main(
            [
                "--evalset",
                str(evalset),
                "--source",
                str(source),
                "--output-dir",
                str(output_dir),
            ]
        )
        == 0
    )

    assert source.read_text(encoding="utf-8") == source_before
    report = json.loads(
        (output_dir / "evolution_report.json").read_text(encoding="utf-8")
    )
    patch = (output_dir / "research_provider_prompt.patch").read_text(encoding="utf-8")
    prompt = (output_dir / "research_provider_prompt_candidate.md").read_text(
        encoding="utf-8"
    )
    assert report["mode"] == "offline_patch_only"
    assert report["runtime_effect"] == "none"
    assert report["optimizer_runtime_used"] is False
    assert report["case_count"] == 5
    assert report["case_counts"]["duplicateish_candidate"] == 1
    assert "no database writes" in report["guardrails"]
    assert "Additional Research Quality policy" in patch
    assert "Do not treat proxy-only" in patch
    assert "Do not propose another automatic follow-up" in patch
    assert "Proposed Research Quality addendum" in prompt


def test_evolve_research_prompt_rejects_unknown_target(tmp_path: Path) -> None:
    evalset = tmp_path / "evalset.jsonl"
    source = tmp_path / "source.py"
    output_dir = tmp_path / "out"
    _write_evalset(evalset)
    source.write_text(
        "Avoid fake citations. Avoid tiny hyperparameter or +0.05% ideas.\n",
        encoding="utf-8",
    )
    try:
        evolve_research_prompt.main(
            [
                "--evalset",
                str(evalset),
                "--source",
                str(source),
                "--output-dir",
                str(output_dir),
                "--target",
                "worker-system-prompt",
            ]
        )
    except SystemExit as exc:
        assert "unsupported target" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected SystemExit")
    assert not output_dir.exists()
