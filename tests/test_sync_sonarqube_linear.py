from __future__ import annotations

from scripts import sync_sonarqube_linear as sync


def _issue(
    key: str,
    *,
    rule: str = "python:S6035",
    line: int = 15,
    message: str = "Replace this alternation with a character class.",
) -> sync.SonarIssue:
    return sync.SonarIssue.from_api(
        {
            "key": key,
            "rule": rule,
            "project": "project-key",
            "component": "project-key:scripts/sync_release_metadata.py",
            "severity": "MAJOR",
            "status": "OPEN",
            "message": message,
            "textRange": {"startLine": line, "endLine": line},
        }
    )


def test_group_issues_groups_same_file_and_line() -> None:
    groups = sync.group_issues(
        [
            _issue("one", rule="python:S6035"),
            _issue("two", rule="python:S5843"),
            _issue("three", line=20),
        ]
    )

    assert len(groups) == 2
    assert (
        groups[0].title == "SonarQube: scripts/sync_release_metadata.py:15 (2 issues)"
    )
    assert [issue.key for issue in groups[0].issues] == ["two", "one"]
    assert groups[1].title == "SonarQube: scripts/sync_release_metadata.py:20 (1 issue)"


def test_group_marker_is_stable_for_same_location() -> None:
    first = sync.group_issues([_issue("one")])[0]
    second = sync.group_issues([_issue("different-key")])[0]

    assert first.marker == second.marker
    assert first.marker.startswith("<!-- sonar-linear-sync:")


def test_build_description_includes_required_tracking_sections() -> None:
    group = sync.group_issues([_issue("sonar-key", rule="python:S5843")])[0]

    description = sync.build_description(
        group,
        sonar_url="https://sonar.example.test",
        project_key="project-key",
    )

    assert group.marker in description
    assert "## Source" in description
    assert "## Observed symptom or risk" in description
    assert "## Invariant" in description
    assert "## Planned fix or mitigation" in description
    assert "## Verification evidence" in description
    assert "`sonar-key` `python:S5843`" in description
    assert "https://sonar.example.test/project/issues" in description


def test_sonar_issue_url_targets_issue_key() -> None:
    url = sync.sonar_issue_url(
        "https://sonar.example.test/",
        "project-key",
        "issue-key",
    )

    assert url.startswith("https://sonar.example.test/project/issues?")
    assert "id=project-key" in url
    assert "issues=issue-key" in url
    assert "open=issue-key" in url


def test_missing_env_reports_unset_names(monkeypatch) -> None:
    monkeypatch.delenv("SONARQUBE_URL", raising=False)
    monkeypatch.setenv("SONARQUBE_TOKEN", "token")

    assert sync.missing_env(("SONARQUBE_URL", "SONARQUBE_TOKEN")) == ["SONARQUBE_URL"]
