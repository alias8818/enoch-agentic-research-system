from pathlib import Path


def test_public_release_integrity_scopes_supabase_secret_to_trusted_push() -> None:
    workflow = Path(".github/workflows/public-release-integrity.yml").read_text(encoding="utf-8")

    assert "env:\n  ENOCH_SUPABASE_DATABASE_URL:" not in workflow
    assert "github.event_name == 'push' && github.ref == 'refs/heads/main'" in workflow
    assert "supabase/setup-cli@df56b21da46c98abb12a9804e4fb1f657773e333" in workflow
    assert "ENOCH_SUPABASE_DATABASE_URL: ${{ secrets.ENOCH_SUPABASE_DATABASE_URL }}" in workflow
    assert "is not configured; skipping live ledger validation" in workflow
