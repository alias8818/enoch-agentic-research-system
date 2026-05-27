#!/usr/bin/env python3
"""Synchronize release metadata after semantic-release stamps a new version."""

from __future__ import annotations

import re
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_NAME = "enoch-control-plane"
SEMVER = re.compile(r"^\d+\.\d+\.\d+([+-][A-Za-z0-9.-]+)?$")


def read_version_file_text(raw: str) -> str:
    text = raw.strip()
    left, separator, right = text.partition("=")
    if separator and left.strip().lower() == "version":
        text = right.strip().strip("\"'")
    return text


def project_version(root: Path = ROOT) -> str:
    version = read_version_file_text((root / "VERSION").read_text(encoding="utf-8"))
    if not SEMVER.match(version):
        raise ValueError(f"VERSION is not semver-like: {version!r}")
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    pyproject_version = str(pyproject.get("project", {}).get("version") or "")
    if pyproject_version != version:
        raise ValueError(
            f"pyproject version {pyproject_version!r} != VERSION {version!r}"
        )
    return version


def sync_uv_lock(root: Path, version: str) -> bool:
    path = root / "uv.lock"
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(
        rf'(\[\[package\]\]\nname = "{re.escape(PACKAGE_NAME)}"\nversion = ")([^"]+)(")'
    )
    updated, count = pattern.subn(rf"\g<1>{version}\g<3>", text)
    if count != 1:
        raise ValueError(f"expected one {PACKAGE_NAME} package entry in uv.lock")
    if updated == text:
        return False
    path.write_text(updated, encoding="utf-8")
    return True


def release_changelog_entry(version: str, today: str | None = None) -> str:
    release_date = today or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return (
        f"## [{version}] - {release_date}\n\n"
        "### Changed\n\n"
        f"- Released the {version} control-plane metadata update.\n\n"
    )


def sync_changelog(root: Path, version: str) -> bool:
    path = root / "CHANGELOG.md"
    text = path.read_text(encoding="utf-8")
    if f"## [{version}]" in text:
        return False

    entry = release_changelog_entry(version)
    first_release_heading = text.find("\n## [")
    if first_release_heading >= 0:
        updated = f"{text[: first_release_heading + 1]}{entry}{text[first_release_heading + 1 :]}"
    elif text.endswith("\n"):
        updated = f"{text}\n{entry}"
    else:
        updated = f"{text}\n\n{entry}"
    path.write_text(updated, encoding="utf-8")
    return True


def main(root: Path = ROOT) -> int:
    version = project_version(root)
    changed = []
    if sync_changelog(root, version):
        changed.append("CHANGELOG.md")
    if sync_uv_lock(root, version):
        changed.append("uv.lock")
    print(f"ok release metadata {version}; changed={','.join(changed) or 'none'}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"FAIL {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
