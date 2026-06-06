from __future__ import annotations

import json
import re
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


def test_sonar_workflow_isolates_coverage_from_secret_bearing_scan_and_uses_node24_actions() -> (
    None
):
    workflow = (ROOT / ".github" / "workflows" / "build.yml").read_text(
        encoding="utf-8"
    )

    assert "FORCE_JAVASCRIPT_ACTIONS_TO_NODE24: true" in workflow
    assert 'uv run pytest -q -n auto -m "not repo_root"' in workflow
    assert 'uv run pytest -q -m "repo_root"' in workflow
    assert "--cov-report=xml:coverage.xml" in workflow
    assert "coverage:" in workflow
    assert "sonar:" in workflow
    assert "needs: coverage" in workflow
    assert "permissions:\n      contents: read" in workflow
    assert re.search(
        r"actions/upload-artifact@[0-9a-f]{40}\s+# v\d+\.\d+\.\d+",
        workflow,
    )
    assert re.search(
        r"actions/download-artifact@[0-9a-f]{40}\s+# v\d+\.\d+\.\d+",
        workflow,
    )
    assert "persist-credentials: false" in workflow
    sonar_index = workflow.index("SonarSource/sonarqube-scan-action")
    assert workflow.index("--cov-report=xml:coverage.xml") < sonar_index
    assert workflow.index("actions/download-artifact") < sonar_index
    assert "actions/checkout@df4cb1c069e1874edd31b4311f1884172cec0e10" in workflow
    assert (
        "SonarSource/sonarqube-scan-action@7006c4492b2e0ee0f816d36501671557c97f5995"
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


def test_sonar_cognitive_complexity_policy_thresholds() -> None:
    """S3776 production threshold is 15; higher bands are documented review guidelines."""
    props = _properties()
    assert props["enoch.cognitiveComplexity.productionThreshold"] == "15"
    assert props["enoch.cognitiveComplexity.scriptGuidelineThreshold"] == "20"
    assert props["enoch.cognitiveComplexity.testGuidelineThreshold"] == "25"
    assert props["enoch.cognitiveComplexity.blockThreshold"] == "25"
    text = (ROOT / "sonar-project.properties").read_text(encoding="utf-8")
    assert "python:S3776" in text
    assert "typescript:S3776" in text
    assert "total cognitive complexity" in text.lower()


def test_sonarlint_s3776_threshold_is_fifteen_for_python_and_typescript() -> None:
    settings = json.loads(
        (ROOT / ".vscode" / "settings.json").read_text(encoding="utf-8")
    )
    rules = settings["sonarlint.rules"]
    assert rules["python:S3776"]["parameters"]["threshold"] == 15
    assert rules["typescript:S3776"]["parameters"]["threshold"] == 15
    assert rules["python:S3776"]["level"] == "on"
    assert rules["typescript:S3776"]["level"] == "on"
