from pathlib import Path

from scripts.validate_promising_signals_release import validate_promising_signals


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
    assert "is not configured; skipping live ledger validation" in workflow


def test_public_release_integrity_authenticates_github_metadata_fetches() -> None:
    workflow = Path(".github/workflows/public-release-integrity.yml").read_text(
        encoding="utf-8"
    )

    validate_step = workflow.split(
        "- name: Validate committed public release accounting and wording", 1
    )[1].split("- name: Render Supabase corpus import ledger validation SQL", 1)[0]
    assert "GH_TOKEN: ${{ github.token }}" in validate_step
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
