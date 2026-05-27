from pathlib import Path


def test_error_to_issue_workflow_has_recursion_guard() -> None:
    workflow = Path(".github/workflows/error-to-issue.yml").read_text(encoding="utf-8")

    assert "issues:" in workflow
    assert "types: [labeled]" in workflow
    assert "github.actor != 'github-actions[bot]'" in workflow
    assert (
        "!startsWith(github.event.issue.title, '[P0-critical] Tracking:')" in workflow
    )
    assert "!startsWith(github.event.issue.title, '[P1-high] Tracking:')" in workflow
    assert "labels: [label, 'area:observability']" in workflow


def test_sonarqube_linear_sync_workflow_uses_guarded_script() -> None:
    workflow = Path(".github/workflows/sonarqube-linear-sync.yml").read_text(
        encoding="utf-8"
    )

    assert "schedule:" in workflow
    assert "scripts/sync_sonarqube_linear.py --skip-if-unconfigured" in workflow
    assert "SONARQUBE_TOKEN: ${{ secrets.SONARQUBE_TOKEN }}" in workflow
    assert "LINEAR_API_KEY: ${{ secrets.LINEAR_API_KEY }}" in workflow
