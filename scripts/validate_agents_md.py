#!/usr/bin/env python3
"""Validate AGENTS.md commands and references stay consistent with the codebase.

Checks performed:
1. Makefile targets referenced in AGENTS.md actually exist in the Makefile.
2. Key files and directories referenced in AGENTS.md exist on disk.
3. Config fields listed in AGENTS.md are present in config.example.json.
4. CI workflow files referenced in AGENTS.md exist in .github/workflows/.
5. Key dependencies listed in AGENTS.md are in pyproject.toml.
6. Markdown link references point to existing files.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
AGENTS_MD = REPO_ROOT / "AGENTS.md"
MAKEFILE = REPO_ROOT / "Makefile"
PYPROJECT = REPO_ROOT / "pyproject.toml"
CONFIG_EXAMPLE = REPO_ROOT / "config.example.json"

errors: list[str] = []


def _read(path: Path) -> str:
    if not path.exists():
        errors.append(f"File not found: {path.relative_to(REPO_ROOT)}")
        return ""
    return path.read_text(encoding="utf-8")


def check_makefile_targets(agents_content: str) -> None:
    """Verify make targets referenced in AGENTS.md exist in Makefile."""
    makefile_content = _read(MAKEFILE)
    if not makefile_content:
        return

    # Extract declared targets from Makefile
    declared = set(
        re.findall(r"^([a-zA-Z_][a-zA-Z0-9_-]*):", makefile_content, re.MULTILINE)
    )

    # Find 'make <target>' references in AGENTS.md
    referenced = set(re.findall(r"\bmake\s+([a-zA-Z_][a-zA-Z0-9_-]*)", agents_content))

    missing = referenced - declared
    for target in sorted(missing):
        errors.append(
            f"Make target 'make {target}' referenced in AGENTS.md but not in Makefile"
        )


def _strip_code_blocks(content: str) -> str:
    """Remove fenced code blocks from markdown content to avoid false matches."""
    return re.sub(r"```[\s\S]*?```", "", content)


def check_file_references(agents_content: str) -> None:
    """Verify key files/directories referenced in AGENTS.md exist."""
    # Work on content outside code blocks to avoid matching code examples
    stripped = _strip_code_blocks(agents_content)

    # Match backtick-quoted paths that look like project-relative references
    for match in re.finditer(r"`([^`]+)`", stripped):
        ref = match.group(1).strip()
        # Skip URLs
        if ref.startswith("http") or ref.startswith("https"):
            continue
        # Skip wildcards
        if "*" in ref or "?" in ref:
            continue
        # Skip short labels that aren't paths (no slash or extension)
        if "/" not in ref and not re.search(r"\.\w{1,4}$", ref):
            continue
        # Skip env variable names and flag patterns
        if ref.startswith("ENOCH_") or ref.startswith("--"):
            continue
        resolved = REPO_ROOT / ref
        if not resolved.exists():
            errors.append(
                f"File/directory referenced in AGENTS.md does not exist: {ref}"
            )


def check_config_fields(agents_content: str) -> None:
    """Verify config fields listed in AGENTS.md exist in config.example.json."""
    config_content = _read(CONFIG_EXAMPLE)
    if not config_content:
        return
    try:
        config_data = json.loads(config_content)
    except json.JSONDecodeError:
        errors.append("config.example.json is not valid JSON")
        return

    config_keys = set(config_data.keys())

    # Find backtick-quoted config field names in AGENTS.md
    for match in re.finditer(r"`([^`]+)`", agents_content):
        field = match.group(1)
        # Only check fields that look like config keys (snake_case)
        if re.match(r"^[a-z][a-z0-9_]*$", field) and "_" in field:
            if field not in config_keys:
                errors.append(
                    f"Config field '{field}' referenced in AGENTS.md not in config.example.json"
                )


def check_ci_workflows(agents_content: str) -> None:
    """Verify CI workflow files referenced in AGENTS.md exist."""
    workflows_dir = REPO_ROOT / ".github" / "workflows"
    for match in re.finditer(
        r"\.github/workflows/([a-zA-Z0-9_-]+\.yml)", agents_content
    ):
        workflow_file = match.group(1)
        if not (workflows_dir / workflow_file).exists():
            errors.append(
                f"CI workflow '.github/workflows/{workflow_file}' referenced in AGENTS.md does not exist"
            )


def check_dependencies(agents_content: str) -> None:
    """Verify key dependencies listed in AGENTS.md are in pyproject.toml."""
    pyproject_content = _read(PYPROJECT)
    if not pyproject_content:
        return

    # Known deps from AGENTS.md "Key Dependencies" section
    known_deps = {
        "fastapi",
        "langgraph",
        "psycopg",
        "pydantic",
        "uvicorn",
        "psutil",
        "pynvml",
        "tenacity",
    }
    for dep in known_deps:
        if dep not in pyproject_content:
            errors.append(
                f"Dependency '{dep}' referenced in AGENTS.md not found in pyproject.toml"
            )


def check_markdown_links(agents_content: str) -> None:
    """Verify relative markdown links in AGENTS.md point to existing files."""
    for match in re.finditer(r"\[([^\]]+)\]\(([^)]+)\)", agents_content):
        link = match.group(2)
        if link.startswith("http") or link.startswith("#"):
            continue
        resolved = REPO_ROOT / link
        if not resolved.exists():
            errors.append(f"Link target does not exist: {link}")


def main() -> int:
    agents_content = _read(AGENTS_MD)
    if not agents_content:
        print("AGENTS.md not found or empty")
        return 1

    check_makefile_targets(agents_content)
    check_file_references(agents_content)
    check_config_fields(agents_content)
    check_ci_workflows(agents_content)
    check_dependencies(agents_content)
    check_markdown_links(agents_content)

    if errors:
        print(f"AGENTS.md validation found {len(errors)} issue(s):")
        for err in errors:
            print(f"  - {err}")
        return 1

    print("AGENTS.md validation passed: all references and commands are consistent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
