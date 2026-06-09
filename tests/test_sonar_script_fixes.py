from __future__ import annotations

from scripts import check_min_release_age, validate_agents_md


def test_validate_agents_md_reuses_backtick_pattern_constant() -> None:
    source = validate_agents_md.Path(validate_agents_md.__file__).read_text(
        encoding="utf-8"
    )

    assert source.count(r"`([^`]+)`") == 1


def test_validate_agents_md_uses_tuple_prefix_check_for_markdown_links() -> None:
    source = validate_agents_md.Path(validate_agents_md.__file__).read_text(
        encoding="utf-8"
    )

    assert 'link.startswith(("http", "#"))' in source
    assert 'link.startswith("http") or link.startswith("#")' not in source


def test_alerts_centralizes_control_plane_worker_preflight_source() -> None:
    source = (
        validate_agents_md.REPO_ROOT / "enoch_control_plane/control_plane/alerts.py"
    ).read_text(encoding="utf-8")

    assert 'CONTROL_PLANE_DB_WORKER_PREFLIGHT_SOURCE = "control_plane_db+worker_preflight"' in source
    assert source.count('"control_plane_db+worker_preflight"') == 1


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


def test_validate_agents_md_ignores_host_local_absolute_paths(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(validate_agents_md, "REPO_ROOT", tmp_path)
    validate_agents_md.errors.clear()

    validate_agents_md.check_file_references(
        "Marker: `/home/jeremy/.codex/state/enoch-linear-last-check.json`\n"
        "Parent: `/home/jeremy/Desktop/projects/enoch-release/AGENTS.md`\n"
    )

    assert validate_agents_md.errors == []


def test_min_release_age_main_uses_exit_side_effect_not_status_value(
    monkeypatch,
) -> None:
    monkeypatch.delenv("PR_BODY", raising=False)

    assert check_min_release_age.main() is None


def test_research_signal_quality_card_delegates_only_actionable_detail_sections() -> (
    None
):
    source = (
        validate_agents_md.REPO_ROOT / "dashboard/src/overviewPage.tsx"
    ).read_text(encoding="utf-8")
    start = source.index("function ResearchSignalQualityCard(")
    end = source.index("\nfunction recentActivityListKey", start)
    component_source = source[start:end]

    assert component_source.count('className="quality-snapshot-detail"') <= 4
    assert "ResearchQualityProviderEvidence" in component_source
    assert "ResearchQualityFollowupScope" in component_source
    assert "ResearchQualityFollowupReadiness" not in component_source
