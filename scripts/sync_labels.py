#!/usr/bin/env python3
"""Synchronize GitHub issue labels from .github/labels.yml."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml

LABELS_FILE = Path(__file__).resolve().parent.parent / ".github" / "labels.yml"


def main() -> int:
    if not LABELS_FILE.exists():
        print(f"Labels file not found: {LABELS_FILE}")
        return 1

    with open(LABELS_FILE) as f:
        labels = yaml.safe_load(f)

    for label in labels:
        name = label["name"]
        color = label["color"]
        description = label.get("description", "")
        cmd = [
            "gh",
            "label",
            "create",
            name,
            "--color",
            color,
            "--description",
            description,
            "--force",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            print(f"  Created/updated: {name}")
        else:
            print(f"  Failed: {name} ({result.stderr.strip()})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
