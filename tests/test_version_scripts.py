from __future__ import annotations

from pathlib import Path

import pytest

from scripts import bump_version, validate_versioning


@pytest.mark.parametrize("module", [bump_version, validate_versioning])
def test_version_assignment_regex_avoids_sonar_duplicate_character_class(
    module,
) -> None:
    assert "[0-9A-Za-z.-]" not in module.VERSION_ASSIGNMENT.pattern
    assert "[-+]" not in module.VERSION_ASSIGNMENT.pattern
    assert r"[\"\']" not in module.VERSION_ASSIGNMENT.pattern


@pytest.mark.parametrize("module", [bump_version, validate_versioning])
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('version = "1.2.3"', "1.2.3"),
        ("version = '1.2.3-alpha.1'", "1.2.3-alpha.1"),
        ('version = "1.2.3+build.7"', "1.2.3+build.7"),
        ("1.2.3", "1.2.3"),
    ],
)
def test_read_version_file_text_keeps_existing_version_forms(
    module, raw, expected
) -> None:
    assert module.read_version_file_text(raw) == expected


def _write_bump_fixture(root: Path, *, version: str = "1.2.3") -> None:
    (root / "VERSION").write_text(f'version = "{version}"\n', encoding="utf-8")
    (root / "pyproject.toml").write_text(
        f'[project]\nname = "enoch-control-plane"\nversion = "{version}"\n',
        encoding="utf-8",
    )
    (root / "CHANGELOG.md").write_text(
        "# Changelog\n\nOlder notes.\n", encoding="utf-8"
    )


def _point_bump_script_at_fixture(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
    monkeypatch.setattr(bump_version, "REPO_ROOT", root)
    monkeypatch.setattr(bump_version, "VERSION_FILE", root / "VERSION")
    monkeypatch.setattr(bump_version, "PYPROJECT_FILE", root / "pyproject.toml")
    monkeypatch.setattr(bump_version, "CHANGELOG_FILE", root / "CHANGELOG.md")


def test_bump_version_dry_run_prints_diff_without_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_bump_fixture(tmp_path)
    _point_bump_script_at_fixture(monkeypatch, tmp_path)
    before = {
        path.name: path.read_text(encoding="utf-8") for path in tmp_path.iterdir()
    }
    monkeypatch.setattr("sys.argv", ["bump_version.py", "patch", "--dry-run"])

    assert bump_version.main() == 0

    assert {
        path.name: path.read_text(encoding="utf-8") for path in tmp_path.iterdir()
    } == before
    output = capsys.readouterr().out
    assert "--- VERSION" in output
    assert "+++ pyproject.toml" in output
    assert "Dry run: version would be bumped: 1.2.3 -> 1.2.4" in output


def test_bump_version_refuses_major_without_confirmation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_bump_fixture(tmp_path)
    _point_bump_script_at_fixture(monkeypatch, tmp_path)
    monkeypatch.setattr("sys.argv", ["bump_version.py", "major"])

    assert bump_version.main() == 2
    assert (tmp_path / "VERSION").read_text(encoding="utf-8") == 'version = "1.2.3"\n'


def test_bump_version_aborts_before_writing_when_metadata_drift_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_bump_fixture(tmp_path)
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "enoch-control-plane"\nversion = "1.2.99"\n',
        encoding="utf-8",
    )
    _point_bump_script_at_fixture(monkeypatch, tmp_path)
    before = {
        path.name: path.read_text(encoding="utf-8") for path in tmp_path.iterdir()
    }
    monkeypatch.setattr("sys.argv", ["bump_version.py", "patch"])

    with pytest.raises(RuntimeError, match="out of sync"):
        bump_version.main()

    assert {
        path.name: path.read_text(encoding="utf-8") for path in tmp_path.iterdir()
    } == before
