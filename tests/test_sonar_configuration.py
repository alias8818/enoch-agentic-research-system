from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _properties() -> dict[str, str]:
    props: dict[str, str] = {}
    for raw_line in (
        (ROOT / "sonar-project.properties").read_text(encoding="utf-8").splitlines()
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, value = line.split("=", 1)
        props[key.strip()] = value.strip()
    return props


def _csv(value: str) -> set[str]:
    return {item.strip() for item in value.split(",") if item.strip()}


def test_sonar_analysis_scope_excludes_generated_artifacts_and_classifies_tests() -> (
    None
):
    props = _properties()

    assert _csv(props["sonar.sources"]) == {
        "enoch_control_plane",
        "scripts",
        "deploy",
        "dashboard/src",
    }
    assert _csv(props["sonar.tests"]) == {"tests", "dashboard/src", "dashboard/e2e"}
    assert "tests/**/*.py" in _csv(props["sonar.test.inclusions"])
    assert "dashboard/src/**/*.test.tsx" in _csv(props["sonar.test.inclusions"])
    assert "artifacts/**" in _csv(props["sonar.exclusions"])
    assert "enoch_control_plane/control_plane/dashboard_v2/**" in _csv(
        props["sonar.exclusions"]
    )
    assert "dashboard/src/**/*.test.tsx" in _csv(props["sonar.exclusions"])
    assert "dashboard/src/components/WorkerLanes.tsx" in _csv(
        props["sonar.cpd.exclusions"]
    )
    assert "dashboard/src/components/ResearchPage.tsx" in _csv(
        props["sonar.cpd.exclusions"]
    )


def test_sonar_imports_python_coverage_and_ignores_non_product_coverage_debt() -> None:
    props = _properties()

    assert props["sonar.python.coverage.reportPaths"] == "coverage.xml"
    coverage_exclusions = _csv(props["sonar.coverage.exclusions"])
    assert "scripts/**" in coverage_exclusions
    assert "deploy/**" in coverage_exclusions
    assert "dashboard/src/**" in coverage_exclusions
    assert "enoch_control_plane/control_plane/dashboard_v2/**" in coverage_exclusions


def test_sonar_workflow_generates_coverage_before_scan_and_uses_node24_actions() -> (
    None
):
    workflow = (ROOT / ".github" / "workflows" / "build.yml").read_text(
        encoding="utf-8"
    )

    assert "FORCE_JAVASCRIPT_ACTIONS_TO_NODE24: true" in workflow
    assert "uv run coverage run -m pytest -q" in workflow
    assert "uv run coverage xml -o coverage.xml" in workflow
    assert workflow.index("uv run coverage xml -o coverage.xml") < workflow.index(
        "SonarSource/sonarqube-scan-action"
    )
    assert "actions/checkout@1af3b93b6815bc44a9784bd300feb67ff0d1eeb3" in workflow
    assert (
        "SonarSource/sonarqube-scan-action@a31c9398be7ace6bbfaf30c0bd5d415f843d45e9"
        in workflow
    )


def test_sonar_accepts_internal_http_for_research_control_plane() -> None:
    """Internal/dev http URLs are intentionally allowed (private nets, examples, no public TLS)."""
    props = _properties()
    assert "sonar.issue.ignore.multicriteria" in props
    assert "httpInternal" in props["sonar.issue.ignore.multicriteria"]
    # The actual rule keys are listed under the .httpInternal suffix
    http_rule = props.get("sonar.issue.ignore.multicriteria.httpInternal.ruleKey", "")
    assert "python:S5332" in http_rule
    assert "typescript:S5332" in http_rule
