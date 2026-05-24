from __future__ import annotations

from scripts import check_min_release_age, validate_agents_md


def test_check_ci_workflows_validates_extracted_workflow_references(
    tmp_path, monkeypatch
) -> None:
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text("name: ci\n", encoding="utf-8")

    monkeypatch.setattr(validate_agents_md, "REPO_ROOT", tmp_path)
    validate_agents_md.errors.clear()

    refs = validate_agents_md._referenced_workflow_files(
        "Run `.github/workflows/ci.yml` before release."
    )
    validate_agents_md.check_ci_workflows(refs)

    assert validate_agents_md.errors == []


def test_min_release_age_main_uses_exit_side_effect_not_status_value(
    monkeypatch,
) -> None:
    monkeypatch.delenv("PR_BODY", raising=False)

    assert check_min_release_age.main() is None
