from pathlib import Path

from scripts.run_public_corpus_release import build_steps, parse_args


def test_release_plan_includes_validation_by_default(tmp_path: Path) -> None:
    args = parse_args(["--root", str(tmp_path), "--dry-run"])
    steps = build_steps(args)
    names = [step.name for step in steps]

    assert names[:4] == [
        "audit strict claim evidence",
        "scan corpus quality",
        "build corpus index",
        "validate corpus trust surfaces",
    ]
    assert "validate public release" in names
    assert all("publish Hugging Face" not in name for name in names)


def test_release_plan_with_agentic_publish_lanes(tmp_path: Path) -> None:
    args = parse_args([
        "--root",
        str(tmp_path),
        "--import-from-control-plane",
        "--token",
        "token",
        "--build-hf",
        "--reconcile-control-plane",
        "--sync-corpus-ledger",
        "--ledger-use-linked",
        "--ledger-sql-output",
        "/tmp/ledger.sql",
        "--dry-run",
    ])
    names = [step.name for step in build_steps(args)]

    assert names[0] == "import finalized papers"
    assert "build Hugging Face export" in names
    assert "reconcile control-plane papers" in names
    assert "render Supabase corpus_imports sync SQL" in names
    assert "apply Supabase corpus_imports sync SQL" in names
    assert "validate Supabase corpus_imports" in names
    import_step = next(step for step in build_steps(args) if step.name == "import finalized papers")
    assert "--token" not in import_step.cmd
    assert import_step.env == {"ENOCH_CONTROL_TOKEN": "token"}
    sync_step = next(step for step in build_steps(args) if step.name == "render Supabase corpus_imports sync SQL")
    assert "--prune-stale" in sync_step.cmd


def test_release_plan_passes_ledger_database_url_via_env_not_argv(tmp_path: Path) -> None:
    args = parse_args([
        "--root",
        str(tmp_path),
        "--sync-corpus-ledger",
        "--ledger-database-url",
        "postgresql://user:secret@example/db",
        "--dry-run",
    ])
    steps = build_steps(args)

    sync_step = next(step for step in steps if step.name == "sync Supabase corpus_imports")
    validate_step = next(step for step in steps if step.name == "validate Supabase corpus_imports")
    assert "postgresql://user:secret@example/db" not in " ".join(sync_step.cmd)
    assert "postgresql://user:secret@example/db" not in " ".join(validate_step.cmd)
    assert sync_step.env == {"ENOCH_SUPABASE_DATABASE_URL": "postgresql://user:secret@example/db"}
    assert validate_step.env == {"ENOCH_SUPABASE_DATABASE_URL": "postgresql://user:secret@example/db"}
