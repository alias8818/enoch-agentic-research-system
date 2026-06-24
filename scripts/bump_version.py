#!/usr/bin/env python3
"""Bump the project version in VERSION, pyproject.toml, and CHANGELOG.md.

Usage:
    python3 scripts/bump_version.py patch             # 0.3.0 -> 0.3.1
    python3 scripts/bump_version.py minor --dry-run   # show diff only
    python3 scripts/bump_version.py major --confirm-major
"""

from __future__ import annotations

import argparse
import difflib
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
VERSION_FILE = REPO_ROOT / "VERSION"
PYPROJECT_FILE = REPO_ROOT / "pyproject.toml"
CHANGELOG_FILE = REPO_ROOT / "CHANGELOG.md"
VERSION_VALUE = r"\d+\.\d+\.\d+(?:(?:-|\+)(?:[A-Za-z0-9]|\.|-)+)?"
VERSION_ASSIGNMENT = re.compile(
    rf"^version\s*=\s*(?:\"|')?(?P<version>{VERSION_VALUE})(?:\"|')?\s*$",
    re.IGNORECASE,
)


def read_version_file_text(raw: str) -> str:
    text = raw.strip()
    if match := VERSION_ASSIGNMENT.match(text):
        return match.group("version")
    return text


def format_version_file(version: str) -> str:
    return f'version = "{version}"\n'


def current_version() -> str:
    return read_version_file_text(VERSION_FILE.read_text(encoding="utf-8"))


def pyproject_version() -> str:
    content = PYPROJECT_FILE.read_text(encoding="utf-8")
    matches = re.findall(r'^version\s*=\s*"([^"]+)"\s*$', content, re.MULTILINE)
    if len(matches) != 1:
        raise RuntimeError("pyproject.toml must contain exactly one project version")
    return matches[0]


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


def _atomic_write_text(path: Path, content: str) -> None:
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        handle.write(content)
        tmp = Path(handle.name)
    try:
        os.replace(tmp, path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def updated_version_file_text(new_version: str) -> str:
    return format_version_file(new_version)


def update_version_file(new_version: str) -> None:
    _atomic_write_text(VERSION_FILE, updated_version_file_text(new_version))


def updated_pyproject_text(new_version: str, old_version: str) -> str:
    content = PYPROJECT_FILE.read_text(encoding="utf-8")
    pattern = re.compile(
        rf'^(version\s*=\s*"){re.escape(old_version)}("\s*)$', re.MULTILINE
    )
    content, replacements = pattern.subn(rf"\g<1>{new_version}\2", content, count=1)
    if replacements != 1:
        raise RuntimeError(
            f'pyproject.toml does not contain exactly one version = "{old_version}" entry'
        )
    return content


def update_pyproject(new_version: str, old_version: str) -> None:
    _atomic_write_text(PYPROJECT_FILE, updated_pyproject_text(new_version, old_version))


def updated_changelog_text(new_version: str) -> str:
    content = CHANGELOG_FILE.read_text(encoding="utf-8")
    if not content.startswith("# "):
        raise RuntimeError("CHANGELOG.md must start with a top-level '# ' heading")
    if re.search(rf"^## \[{re.escape(new_version)}\]", content, re.MULTILINE):
        raise RuntimeError(f"CHANGELOG.md already contains version {new_version}")

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    entry = f"\n## [{new_version}] - {today}\n\n- Release {new_version}.\n\n"
    first_newline = content.index("\n")
    return content[: first_newline + 1] + entry + content[first_newline + 1 :]


def update_changelog(new_version: str) -> None:
    _atomic_write_text(CHANGELOG_FILE, updated_changelog_text(new_version))


def planned_updates(new_version: str, old_version: str) -> dict[Path, str]:
    return {
        VERSION_FILE: updated_version_file_text(new_version),
        PYPROJECT_FILE: updated_pyproject_text(new_version, old_version),
        CHANGELOG_FILE: updated_changelog_text(new_version),
    }


def print_diff(updates: dict[Path, str]) -> None:
    for path, new_text in updates.items():
        old_text = path.read_text(encoding="utf-8")
        sys.stdout.writelines(
            difflib.unified_diff(
                old_text.splitlines(keepends=True),
                new_text.splitlines(keepends=True),
                fromfile=str(path.relative_to(REPO_ROOT)),
                tofile=str(path.relative_to(REPO_ROOT)),
            )
        )


def verify_release_metadata_matches() -> str:
    version = current_version()
    pyproject = pyproject_version()
    if version != pyproject:
        raise RuntimeError(
            f"VERSION ({version}) and pyproject.toml ({pyproject}) are out of sync"
        )
    return version


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Bump VERSION, pyproject.toml, and CHANGELOG.md together."
    )
    parser.add_argument("part", choices=("patch", "minor", "major"))
    parser.add_argument(
        "--dry-run", action="store_true", help="print the planned unified diff only"
    )
    parser.add_argument(
        "--confirm-major",
        action="store_true",
        help="required when bumping the major version",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.part == "major" and not args.confirm_major:
        print("Refusing major bump without --confirm-major", file=sys.stderr)
        return 2

    old = verify_release_metadata_matches()
    part = args.part
    new = bump_version(old, part)
    updates = planned_updates(new, old)

    print_diff(updates)
    if args.dry_run:
        print(f"Dry run: version would be bumped: {old} -> {new}")
        return 0

    for path, content in updates.items():
        _atomic_write_text(path, content)
    if verify_release_metadata_matches() != new:
        raise RuntimeError("release metadata verification failed after bump")

    print(f"Version bumped: {old} -> {new}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
