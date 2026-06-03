from pathlib import Path


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


def test_public_release_integrity_runs_promising_signals_validators() -> None:
    workflow = Path(".github/workflows/public-release-integrity.yml").read_text(
        encoding="utf-8"
    )

    promising_step = workflow.split(
        "- name: Validate promising signals release surfaces", 1
    )[1].split(
        "- name: Generate fresh manifest without overwriting committed public manifest",
        1,
    )[0]

    assert "working-directory: enoch-promising-signals" in promising_step
    assert "python3 scripts/validate.py" in promising_step
    assert "python3 scripts/validate_public_trust_surfaces.py" in promising_step
