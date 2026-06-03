#!/usr/bin/env python3
"""Validate the Dashboard V2 operator inventory stays aligned with route policy."""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
INVENTORY = REPO_ROOT / "docs" / "dashboard-operator-inventory.md"
ROUTE_POLICY = REPO_ROOT / "dashboard" / "src" / "routePolicy.ts"

REQUIRED_ROUTE_SURFACES = [
    "#overview",
    "#projects",
    "#queue",
    "#research",
    "#intake",
    "#runs",
    "#papers",
    "#corpus",
    "#automation",
    "#events",
    "#observability",
    "#settings",
    "#project:...",
    "#run:...",
    "#paper:...",
    "#event:...",
    "#research:...",
    "#intake:...",
    "#automation:...",
]

REQUIRED_COMMAND_CENTER_SURFACES = [
    "Can I leave this running?",
    "Readiness check",
    "CPU / [GB10 runtime](current-runtime-snapshot.md) command surface",
    "Primary action",
    "Write -> Finalize -> Publish",
    "Top actions",
    "Research signal quality",
    "Research yield",
    "Recent activity stream",
    "Active work snapshot",
    "Automation readiness",
]

REQUIRED_RESOURCE_SURFACES = [
    "DataTable",
    "DetailPanel",
    "CandidateDetailPanel",
    "Intake idea detail",
    "Automation detail",
    "RawJsonDetails",
]

REQUIRED_DECISIONS = [
    "`#research` and `#intake` are not independent product areas",
    "`#corpus` and `#automation` are not independent product areas",
    "`#observability` and `#settings` are debug/support surfaces",
    "Raw JSON is evidence, not primary UX",
]


def _read(path: Path) -> str:
    if not path.exists():
        raise AssertionError(f"missing required file: {path.relative_to(REPO_ROOT)}")
    return path.read_text(encoding="utf-8")


def _route_hashes(route_policy: str) -> list[str]:
    return re.findall(r"hash: '(#[^']+)'", route_policy)


def _missing_entries(
    entries: list[str],
    content: str,
    *,
    label: str,
    backtick_wrapped: bool = False,
) -> list[str]:
    missing: list[str] = []
    for entry in entries:
        expected = f"`{entry}`" if backtick_wrapped else entry
        if expected not in content:
            missing.append(f"inventory missing {label}: {entry}")
    return missing


def _undocumented_policy_routes(route_policy: str) -> list[str]:
    documented_routes = set(REQUIRED_ROUTE_SURFACES)
    errors: list[str] = []
    for route_hash in _route_hashes(route_policy):
        normalized = route_hash.replace("…", "...")
        if ":" in normalized and not normalized.endswith("..."):
            continue
        if normalized not in documented_routes:
            errors.append(
                f"routePolicy route not documented in inventory: {route_hash}"
            )
    return errors


def validate() -> list[str]:
    errors: list[str] = []
    inventory = _read(INVENTORY)
    route_policy = _read(ROUTE_POLICY)

    errors.extend(
        _missing_entries(
            REQUIRED_ROUTE_SURFACES,
            inventory,
            label="route surface",
            backtick_wrapped=True,
        )
    )
    errors.extend(
        _missing_entries(
            REQUIRED_COMMAND_CENTER_SURFACES,
            inventory,
            label="command-center surface",
        )
    )
    errors.extend(
        _missing_entries(
            REQUIRED_RESOURCE_SURFACES, inventory, label="resource surface"
        )
    )
    errors.extend(
        _missing_entries(REQUIRED_DECISIONS, inventory, label="demotion/merge decision")
    )
    errors.extend(_undocumented_policy_routes(route_policy))

    return errors


def main() -> int:
    errors = validate()
    if errors:
        print(f"Dashboard operator inventory validation found {len(errors)} issue(s):")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("Dashboard operator inventory validation passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
