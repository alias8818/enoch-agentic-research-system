#!/usr/bin/env python3
"""Bump the project version in VERSION, pyproject.toml, and CHANGELOG.md.

Usage:
    python3 scripts/bump_version.py patch   # 0.3.0 -> 0.3.1
    python3 scripts/bump_version.py minor   # 0.3.0 -> 0.4.0
    python3 scripts/bump_version.py major   # 0.3.0 -> 1.0.0
"""

from __future__ import annotations

import re
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
VERSION_FILE = REPO_ROOT / "VERSION"
PYPROJECT_FILE = REPO_ROOT / "pyproject.toml"
CHANGELOG_FILE = REPO_ROOT / "CHANGELOG.md"


def current_version() -> str:
    return VERSION_FILE.read_text().strip()


def bump_version(current: str, part: str) -> str:
    major, minor, patch = (int(x) for x in current.split("."))
    if part == "major":
        return f"{major + 1}.0.0"
    elif part == "minor":
        return f"{major}.{minor + 1}.0"
    elif part == "patch":
        return f"{major}.{minor}.{patch + 1}"
    else:
        raise ValueError(f"Unknown bump part: {part}")


def update_version_file(new_version: str) -> None:
    VERSION_FILE.write_text(new_version + "\n")


def update_pyproject(new_version: str, old_version: str) -> None:
    content = PYPROJECT_FILE.read_text()
    content = content.replace(
        f'version = "{old_version}"', f'version = "{new_version}"', 1
    )
    PYPROJECT_FILE.write_text(content)


def update_changelog(new_version: str) -> None:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    entry = f"\n## [{new_version}] - {today}\n\n- Release {new_version}.\n\n"
    content = CHANGELOG_FILE.read_text()
    # Insert after the header
    if content.startswith("# "):
        first_newline = content.index("\n")
        content = content[: first_newline + 1] + entry + content[first_newline + 1 :]
    else:
        content = entry + content
    CHANGELOG_FILE.write_text(content)


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in ("patch", "minor", "major"):
        print("Usage: python3 scripts/bump_version.py [patch|minor|major]")
        return 1

    part = sys.argv[1]
    old = current_version()
    new = bump_version(old, part)

    update_version_file(new)
    update_pyproject(new, old)
    update_changelog(new)

    print(f"Version bumped: {old} -> {new}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
