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
