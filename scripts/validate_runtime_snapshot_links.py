#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

SNAPSHOT_DOC = Path("docs/current-runtime-snapshot.md")
SNAPSHOT_LINK = "current-runtime-snapshot.md"

EXCLUDED_DIR_PARTS = {
    "historical",
    "archive",
    "archives",
    "generated",
    "outreach",
    "release",
}
EXCLUDED_FILES = {
    SNAPSHOT_DOC,
    Path("docs/state-reduction-audit.md"),
    Path("docs/featured-paper-selection.md"),
}
EXCLUDED_PREFIXES = (
    "docs/launch-",
)
HISTORICAL_MARKERS = (
    "Status: historical",
    "retained only as historical",
    "historical audit context",
)

TOPOLOGY_TERMS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("enoch-core", re.compile(r"\benoch-core\b", re.I)),
    ("/opt/enoch-control-plane", re.compile(r"/opt/enoch-control-plane")),
    ("GB10", re.compile(r"\bGB10\b")),
    ("worker gate", re.compile(r"\bworker[- ]gate\b", re.I)),
    ("local Postgres", re.compile(r"\blocal Postgres\b", re.I)),
    ("control-plane storage", re.compile(r"\bcontrol-plane storage\b", re.I)),
    (".enoch/project_decision.json", re.compile(r"\.enoch/project_decision\.json")),
    (".omx/project_decision.json", re.compile(r"\.omx/project_decision\.json")),
    ("Research Facility", re.compile(r"\bResearch Facility\b")),
    ("write_needed", re.compile(r"\bwrite_needed\b")),
)


def line_for(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def iter_markdown_files(root: Path) -> list[Path]:
    candidates = [root / "README.md"]
    docs_dir = root / "docs"
    if docs_dir.exists():
        candidates.extend(docs_dir.rglob("*.md"))
    return sorted(path for path in candidates if path.exists())


def is_excluded(root: Path, path: Path) -> bool:
    rel = path.relative_to(root)
    rel_posix = rel.as_posix()
    if rel in EXCLUDED_FILES:
        return True
    if any(rel_posix.startswith(prefix) for prefix in EXCLUDED_PREFIXES):
        return True
    if any(part in EXCLUDED_DIR_PARTS for part in rel.parts):
        return True
    head = path.read_text(encoding="utf-8", errors="replace")[:1200]
    return any(marker in head for marker in HISTORICAL_MARKERS)


def find_terms(text: str) -> list[tuple[str, int]]:
    found: list[tuple[str, int]] = []
    for label, pattern in TOPOLOGY_TERMS:
        match = pattern.search(text)
        if match:
            found.append((label, line_for(text, match.start())))
    return found


def validate(root: Path) -> list[str]:
    failures: list[str] = []
    if not (root / SNAPSHOT_DOC).exists():
        failures.append(f"missing canonical runtime snapshot: {SNAPSHOT_DOC}")
        return failures

    for path in iter_markdown_files(root):
        rel = path.relative_to(root)
        if is_excluded(root, path):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        terms = find_terms(text)
        if terms and SNAPSHOT_LINK not in text:
            detail = ", ".join(f"{term} at line {line}" for term, line in terms)
            failures.append(f"{rel}: mentions current runtime topology without linking to {SNAPSHOT_LINK}: {detail}")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Ensure current runtime topology claims link to docs/current-runtime-snapshot.md."
    )
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="Repository root to scan.")
    args = parser.parse_args()

    root = args.root.resolve()
    failures = validate(root)
    if failures:
        print("Runtime snapshot link validation failed:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1
    print("Runtime snapshot link validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
