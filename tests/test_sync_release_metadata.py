from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from scripts import sync_release_metadata


def _write_release_fixture(root: Path, *, version: str, locked_version: str) -> None:
    (root / "VERSION").write_text(f'version = "{version}"\n', encoding="utf-8")
    (root / "pyproject.toml").write_text(
        f'[project]\nname = "enoch-control-plane"\nversion = "{version}"\n',
        encoding="utf-8",
    )
    (root / "CHANGELOG.md").write_text(
        "# Changelog\n\nRelease notes.\n\n"
        "## [1.4.8] - 2026-05-27\n\n"
        "### Changed\n\n"
        "- Released the 1.4.8 control-plane metadata update.\n",
        encoding="utf-8",
    )
    (root / "uv.lock").write_text(
        "[[package]]\n"
        'name = "dotty-dict"\n'
        'version = "1.3.1"\n'
        "\n"
        "[[package]]\n"
        'name = "enoch-control-plane"\n'
        f'version = "{locked_version}"\n'
        'source = { editable = "." }\n',
        encoding="utf-8",
    )


def test_sync_release_metadata_updates_changelog_and_uv_lock(tmp_path: Path) -> None:
    _write_release_fixture(tmp_path, version="1.4.9", locked_version="1.4.8")

    assert sync_release_metadata.main(tmp_path) == 0

    changelog = (tmp_path / "CHANGELOG.md").read_text(encoding="utf-8")
    uv_lock = (tmp_path / "uv.lock").read_text(encoding="utf-8")
    assert "## [1.4.9]" in changelog
    assert changelog.index("## [1.4.9]") < changelog.index("## [1.4.8]")
    assert 'name = "dotty-dict"\nversion = "1.3.1"' in uv_lock
    assert 'name = "enoch-control-plane"\nversion = "1.4.9"' in uv_lock


def test_sync_release_metadata_is_idempotent(tmp_path: Path) -> None:
    _write_release_fixture(tmp_path, version="1.4.9", locked_version="1.4.9")
    sync_release_metadata.main(tmp_path)
    before = {
        path.name: path.read_text(encoding="utf-8")
        for path in (tmp_path / "CHANGELOG.md", tmp_path / "uv.lock")
    }

    assert sync_release_metadata.main(tmp_path) == 0

    after = {
        path.name: path.read_text(encoding="utf-8")
        for path in (tmp_path / "CHANGELOG.md", tmp_path / "uv.lock")
    }
    assert after == before


def test_sync_release_metadata_fails_on_version_mismatch(tmp_path: Path) -> None:
    _write_release_fixture(tmp_path, version="1.4.9", locked_version="1.4.8")
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        pyproject.read_text(encoding="utf-8").replace("1.4.9", "1.5.0"),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="pyproject version"):
        sync_release_metadata.project_version(tmp_path)


def test_semantic_release_tracks_metadata_sync_assets() -> None:
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")

    assert 'assets = ["CHANGELOG.md", "uv.lock"]' in pyproject
    assert 'build_command = "python3 scripts/sync_release_metadata.py"' in pyproject


def test_release_workflow_validates_metadata_after_release() -> None:
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")

    assert "scripts/validate_versioning.py" in workflow


def test_sync_release_metadata_matches_current_repo(tmp_path: Path) -> None:
    for name in ("VERSION", "pyproject.toml", "CHANGELOG.md", "uv.lock"):
        shutil.copy2(name, tmp_path / name)

    assert sync_release_metadata.main(tmp_path) == 0
