from __future__ import annotations

import json
import difflib
from pathlib import Path

from scripts import evolve_research_prompt, validate_research_prompt_evolution


def _write_evalset(path: Path) -> None:
    rows = [
        {
            "schema_version": "enoch_research_quality_evalcase_v1",
            "case_id": "proxy_only_positive:x",
            "case_type": "proxy_only_positive",
        },
        {
            "schema_version": "enoch_research_quality_evalcase_v1",
            "case_id": "max_depth_followup_ending:y",
            "case_type": "max_depth_followup_ending",
        },
        {
            "schema_version": "enoch_research_quality_evalcase_v1",
            "case_id": "useful_adjacent_followup:z",
            "case_type": "useful_adjacent_followup",
        },
    ]
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def _source(path: Path) -> None:
    path.write_text(
        'def build_generation_prompt():\n    return """\nAvoid fake citations. Avoid tiny hyperparameter or +0.05% ideas.\n"""\n',
        encoding="utf-8",
    )


def test_validate_research_prompt_evolution_accepts_generated_artifacts(
    tmp_path: Path, capsys
) -> None:
    evalset = tmp_path / "evalset.jsonl"
    source = tmp_path / "research_provider_generate.py"
    output_dir = tmp_path / "out"
    _write_evalset(evalset)
    _source(source)
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
    capsys.readouterr()

    assert (
        validate_research_prompt_evolution.main(
            [
                "--source",
                str(source),
                "--report",
                str(output_dir / "evolution_report.json"),
                "--patch",
                str(output_dir / "research_provider_prompt.patch"),
                "--prompt-candidate",
                str(output_dir / "research_provider_prompt_candidate.md"),
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert result["ok"] is True
    assert result["runtime_effect"] == "none"
    assert result["failures"] == []
    assert source.read_text(encoding="utf-8") == source_before


def test_validate_research_prompt_evolution_rejects_missing_guardrail(
    tmp_path: Path, capsys
) -> None:
    evalset = tmp_path / "evalset.jsonl"
    source = tmp_path / "research_provider_generate.py"
    output_dir = tmp_path / "out"
    _write_evalset(evalset)
    _source(source)
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
    capsys.readouterr()
    report_path = output_dir / "evolution_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["guardrails"] = [
        item for item in report["guardrails"] if item != "no database writes"
    ]
    report_path.write_text(json.dumps(report), encoding="utf-8")

    assert (
        validate_research_prompt_evolution.main(
            [
                "--source",
                str(source),
                "--report",
                str(report_path),
                "--patch",
                str(output_dir / "research_provider_prompt.patch"),
                "--prompt-candidate",
                str(output_dir / "research_provider_prompt_candidate.md"),
            ]
        )
        == 1
    )
    result = json.loads(capsys.readouterr().out)
    assert result["ok"] is False
    assert any("missing guardrails" in failure for failure in result["failures"])


def test_validate_research_prompt_evolution_rejects_executable_patch_changes(
    tmp_path: Path, capsys
) -> None:
    source = tmp_path / "research_provider_generate.py"
    _source(source)
    report = tmp_path / "evolution_report.json"
    prompt = tmp_path / "prompt.md"
    patch = tmp_path / "prompt.patch"
    report.write_text(
        json.dumps(
            {
                "mode": "offline_patch_only",
                "runtime_effect": "none",
                "optimizer_runtime_used": False,
                "artifacts": {"patch": patch.name, "prompt_candidate": prompt.name},
                "guardrails": sorted(
                    validate_research_prompt_evolution.REQUIRED_GUARDRAILS
                ),
                "case_count": 1,
            }
        ),
        encoding="utf-8",
    )
    prompt.write_text("## Proposed Research Quality addendum\n", encoding="utf-8")
    source_text = source.read_text(encoding="utf-8")
    proposed_text = 'print("executed")\n' + source_text.replace(
        "Avoid fake citations. Avoid tiny hyperparameter or +0.05% ideas.",
        "Avoid fake citations. Avoid tiny hyperparameter or +0.05% ideas.\n"
        "Additional Research Quality policy:\n"
        "Do not treat proxy-only evidence as paper-positive.\n"
        "Do not propose another automatic follow-up.\n"
        "generation does not queue work until promotion policy allows it.",
    )
    patch.write_text(
        "".join(
            difflib.unified_diff(
                source_text.splitlines(keepends=True),
                proposed_text.splitlines(keepends=True),
                fromfile=str(source),
                tofile=f"{source} (proposed)",
            )
        ),
        encoding="utf-8",
    )

    assert (
        validate_research_prompt_evolution.main(
            [
                "--source",
                str(source),
                "--report",
                str(report),
                "--patch",
                str(patch),
                "--prompt-candidate",
                str(prompt),
            ]
        )
        == 1
    )
    result = json.loads(capsys.readouterr().out)
    assert any(
        "executable Python structure" in failure for failure in result["failures"]
    )
