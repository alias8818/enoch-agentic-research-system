#!/usr/bin/env python3
"""Validate Enoch release-version bookkeeping."""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")


def main() -> int:
    version_path = ROOT / "VERSION"
    pyproject_path = ROOT / "pyproject.toml"
    changelog_path = ROOT / "CHANGELOG.md"
    failures: list[str] = []

    version = (
        version_path.read_text(encoding="utf-8").strip()
        if version_path.exists()
        else ""
    )
    if not version:
        failures.append("VERSION is missing or empty")
    elif not SEMVER.match(version):
        failures.append(f"VERSION is not semver-like: {version}")

    try:
        pyproject = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
        package_version = str(pyproject.get("project", {}).get("version") or "")
    except Exception as exc:  # pragma: no cover - defensive CLI reporting
        package_version = ""
        failures.append(f"could not read pyproject.toml: {exc}")
    if package_version != version:
        failures.append(f"pyproject version {package_version!r} != VERSION {version!r}")

    changelog = (
        changelog_path.read_text(encoding="utf-8") if changelog_path.exists() else ""
    )
    if f"## [{version}]" not in changelog:
        failures.append(f"CHANGELOG.md has no entry for {version}")
    if "omx-wake-gate" in pyproject_path.read_text(encoding="utf-8"):
        failures.append(
            "pyproject.toml still references the old package name omx-wake-gate"
        )

    if failures:
        for failure in failures:
            print(f"FAIL {failure}")
        return 1
    print(f"ok version {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
