from scripts import validate_runtime_snapshot_links


def write(path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_flags_current_runtime_terms_without_snapshot_link(tmp_path) -> None:
    write(tmp_path / "docs/current-runtime-snapshot.md", "# Current Runtime Snapshot\n")
    write(tmp_path / "docs/operator.md", "The control plane runs on enoch-core.\n")

    failures = validate_runtime_snapshot_links.validate(tmp_path)

    assert len(failures) == 1
    assert "docs/operator.md" in failures[0]
    assert "enoch-core" in failures[0]


def test_accepts_current_runtime_terms_with_snapshot_link(tmp_path) -> None:
    write(tmp_path / "docs/current-runtime-snapshot.md", "# Current Runtime Snapshot\n")
    write(
        tmp_path / "docs/operator.md",
        "The worker gate runs on GB10. See "
        "[current runtime](current-runtime-snapshot.md).\n",
    )

    assert validate_runtime_snapshot_links.validate(tmp_path) == []


def test_excludes_historical_and_generated_surfaces(tmp_path) -> None:
    write(tmp_path / "docs/current-runtime-snapshot.md", "# Current Runtime Snapshot\n")
    write(tmp_path / "docs/historical/old.md", "GB10 wake gate notes.\n")
    write(tmp_path / "docs/state-reduction-audit.md", "write_needed state table.\n")
    write(
        tmp_path / "docs/end-to-end-workflow-audit.md",
        "Superseded runtime note retained only as historical audit context.\n"
        "local Postgres on enoch-core.\n",
    )

    assert validate_runtime_snapshot_links.validate(tmp_path) == []
