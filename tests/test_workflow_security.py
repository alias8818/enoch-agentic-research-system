from pathlib import Path
import re

import yaml

from scripts.validate_promising_signals_release import validate_promising_signals


PINNED_SHA_REF = re.compile(r"@[0-9a-f]{40}(?:\s+#\s+v[\w.-]+)?$")


def _workflow_uses(workflow: str) -> list[str]:
    refs: list[str] = []
    for line in workflow.splitlines():
        stripped = line.strip()
        if stripped.startswith("- uses: "):
            refs.append(stripped.removeprefix("- uses: "))
        elif stripped.startswith("uses: "):
            refs.append(stripped.removeprefix("uses: "))
    return refs


def test_security_sensitive_workflows_pin_actions_to_commit_shas() -> None:
    workflows = [
        Path(".github/workflows/ci.yml"),
        Path(".github/workflows/dast.yml"),
        Path(".github/workflows/error-to-issue.yml"),
    ]

    action_refs = [
        ref
        for workflow in workflows
        for ref in _workflow_uses(workflow.read_text(encoding="utf-8"))
        if "/" in ref.split("@", 1)[0]
    ]

    assert action_refs
    assert all(PINNED_SHA_REF.search(ref) for ref in action_refs)


def test_public_release_integrity_scopes_supabase_secret_to_trusted_push() -> None:
    workflow = Path(".github/workflows/public-release-integrity.yml").read_text(
        encoding="utf-8"
    )

    assert "env:\n  ENOCH_SUPABASE_DATABASE_URL:" not in workflow
    assert "github.event_name == 'push' && github.ref == 'refs/heads/main'" in workflow
    assert "supabase/setup-cli@3c2f5e2ae34c34e428e8e206e2c4d21fa2d20fbf" in workflow
    assert (
        "ENOCH_SUPABASE_DATABASE_URL: ${{ secrets.ENOCH_SUPABASE_DATABASE_URL }}"
        in workflow
    )
    assert "::error::ENOCH_SUPABASE_DATABASE_URL is not configured" in workflow
    assert "skipping live ledger validation" not in workflow
    live_step = workflow.split(
        "- name: Validate live Supabase corpus import ledger", 1
    )[1]
    assert "exit 0" not in live_step
    assert (
        "uv run python3 scripts/validate_corpus_import_ledger.py --corpus ../enoch-ai-research-corpus"
        in live_step
    )


def test_release_workflow_does_not_skip_on_commit_message_substring() -> None:
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")

    assert (
        "contains(github.event.head_commit.message, 'chore(release)')" not in workflow
    )
    assert (
        'contains(github.event.head_commit.message, "chore(release)")' not in workflow
    )
    assert "concurrency:" in workflow
    assert "group: release" in workflow
    assert "cancel-in-progress: false" in workflow


def test_release_workflow_uses_minimal_scoped_token_permissions() -> None:
    workflow_text = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
    workflow = yaml.safe_load(workflow_text)

    assert workflow["permissions"] == {"contents": "write"}
    assert "secrets.GITHUB_TOKEN" not in workflow_text
    assert "GH_TOKEN: ${{ github.token }}" in workflow_text
    assert "GITHUB_TOKEN: ${{ github.token }}" in workflow_text


def test_ci_secret_scan_does_not_trust_pr_controlled_gitleaksignore() -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "--gitleaks-ignore-path" not in workflow


def test_ci_main_pushes_use_ephemeral_runners() -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "self-hosted" not in workflow
    assert "runs-on: ubuntu-latest" in workflow


def test_ci_pyright_typecheck_is_required() -> None:
    workflow_text = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    workflow = yaml.safe_load(workflow_text)
    pyright_config = yaml.safe_load(Path("pyrightconfig.ci.json").read_text())

    steps = workflow["jobs"]["tests"]["steps"]
    pyright_steps = [
        step for step in steps if step.get("name") == "Run Pyright type check"
    ]
    assert len(pyright_steps) == 1
    assert (
        pyright_steps[0]["run"]
        == "uv run pyright --project pyrightconfig.ci.json --level error"
    )
    assert "continue-on-error" not in pyright_steps[0]
    assert pyright_config["include"]
    assert "tests/test_workflow_security.py" in pyright_config["include"]


def test_public_release_integrity_authenticates_github_metadata_fetches() -> None:
    workflow = Path(".github/workflows/public-release-integrity.yml").read_text(
        encoding="utf-8"
    )

    validate_step = workflow.split(
        "- name: Validate committed public release accounting and wording", 1
    )[1].split("- name: Render Supabase corpus import ledger validation SQL", 1)[0]
    assert "GH_TOKEN: ${{ github.token }}" in validate_step
    assert "python3 scripts/validate_public_release.py" in validate_step


def test_public_release_integrity_regenerates_graph_before_validation() -> None:
    workflow = Path(".github/workflows/public-release-integrity.yml").read_text(
        encoding="utf-8"
    )

    graph_step = workflow.split(
        "- name: Generate fresh paper material graph before validation", 1
    )[1].split("- name: Validate committed public release accounting and wording", 1)[0]
    validate_step = workflow.split(
        "- name: Validate committed public release accounting and wording", 1
    )[1].split("- name: Render Supabase corpus import ledger validation SQL", 1)[0]
    assert "python3 scripts/build_paper_material_graph.py" in graph_step
    assert (
        "--json-output docs/paper-material-graph/paper-material-graph.json"
        in graph_step
    )
    assert "python3 scripts/validate_public_release.py" in validate_step


def test_public_release_integrity_treats_promising_signals_checkout_as_data() -> None:
    workflow = Path(".github/workflows/public-release-integrity.yml").read_text(
        encoding="utf-8"
    )

    promising_step = workflow.split(
        "- name: Validate promising signals release surfaces", 1
    )[1].split(
        "- name: Generate fresh manifest without overwriting committed public manifest",
        1,
    )[0]

    assert "working-directory: enoch-agentic-research-system" in promising_step
    assert (
        "python3 scripts/validate_promising_signals_release.py --promising ../enoch-promising-signals"
        in promising_step
    )
    assert "working-directory: enoch-promising-signals" not in promising_step
    assert "python3 scripts/validate.py" not in promising_step
    assert "python3 scripts/validate_public_trust_surfaces.py" not in promising_step


def test_promising_signals_validator_checks_public_data_without_running_repo_code(
    tmp_path: Path,
) -> None:
    promising = tmp_path / "enoch-promising-signals"
    (promising / "data").mkdir(parents=True)
    (promising / "docs").mkdir()
    (promising / "schemas").mkdir()
    (promising / "signals").mkdir()
    for rel in ("README.md", "SECURITY.md", "CONTRIBUTING.md"):
        (promising / rel).write_text("AI-generated signal caveat\n", encoding="utf-8")
    (promising / "docs" / "export-policy.md").write_text(
        "not peer-reviewed\n", encoding="utf-8"
    )
    (promising / "schemas" / "promising-signal.schema.json").write_text(
        '{"type":"object"}\n', encoding="utf-8"
    )
    (promising / "signals" / "index.md").write_text("# Index\n", encoding="utf-8")
    (promising / "signals" / "ranked-index.md").write_text(
        "# Ranked\n", encoding="utf-8"
    )
    (promising / "signals" / "signal-1.md").write_text(
        "# Signal 1\nnot independently replicated\n", encoding="utf-8"
    )
    (promising / "data" / "manifest.json").write_text(
        (
            '{"data_file":"data/signals.jsonl",'
            '"ranking_file":"data/ranking.json",'
            '"schema_file":"schemas/promising-signal.schema.json",'
            '"index_file":"signals/index.md",'
            '"ranked_index_file":"signals/ranked-index.md",'
            '"project_ids":["signal-1"]}\n'
        ),
        encoding="utf-8",
    )
    (promising / "data" / "ranking.json").write_text(
        '{"items":[{"project_id":"signal-1"}]}\n', encoding="utf-8"
    )
    (promising / "data" / "signals.jsonl").write_text(
        '{"project_id":"signal-1","title":"Signal 1"}\n', encoding="utf-8"
    )

    report = validate_promising_signals(promising)

    assert report["ok"] is True
    assert report["signal_count"] == 1
