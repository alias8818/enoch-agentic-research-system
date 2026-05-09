#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from enoch_control_plane.control_plane.state_contract import (  # noqa: E402
    OPERATOR_LANE_DESCRIPTIONS,
    STATE_CONTRACT,
    STATE_REDUCTION_PLAN,
    STATE_SURFACE_INVENTORY,
)
from scripts.validate_state_contract import validate  # noqa: E402


def _live_counts(database_url: str) -> dict[str, dict[str, int]]:
    result = validate(database_url=database_url)
    if not result["ok"]:
        raise SystemExit(f"state contract validation failed: {result['failures']}")
    return {
        surface: {value: count for value, count in rows}
        for surface, rows in (result.get("live_distincts") or {}).items()
    }


def _table_for_surface(surface: str, *, live: dict[str, dict[str, int]]) -> str:
    counts = live.get(surface, {})
    rows = [
        "| Raw value | Live rows | Operator lane | Disposition | Replacement | Reason |",
        "| --- | ---: | --- | --- | --- | --- |",
    ]
    for value in sorted(STATE_CONTRACT[surface]):
        decision = STATE_REDUCTION_PLAN[surface][value]
        rows.append(
            "| `{}` | {} | `{}` | `{}` | {} | {} |".format(
                value or "<blank>",
                counts.get(value, 0) if live else "",
                decision["operator_lane"],
                decision["disposition"],
                f"`{decision['replacement']}`" if decision.get("replacement") else "",
                decision.get("reason", "").replace("|", "\\|"),
            )
        )
    return "\n".join(rows)


def render(*, live: dict[str, dict[str, int]]) -> str:
    lines: list[str] = [
        "# State reduction audit",
        "",
        "Status: generated from `enoch_control_plane/control_plane/state_contract.py`.",
        "",
        "This audit is the bridge from the broad compatibility contract to the small user/operator model. "
        "Every raw persisted state is classified as one of:",
        "",
        "- `keep`: still a useful raw state.",
        "- `alias`: allowed, but semantically duplicates another raw state.",
        "- `legacy_internal`: allowed for history/compatibility, but not a current workflow state.",
        "- `migrate_after_freeze`: safe candidate to rewrite or collapse after the current automation freeze.",
        "",
        "Operator-facing surfaces should lead with the operator lane, not the raw value.",
        "",
        "## Operator lanes",
        "",
        "| Lane | Meaning |",
        "| --- | --- |",
    ]
    for lane, description in OPERATOR_LANE_DESCRIPTIONS.items():
        lines.append(f"| `{lane}` | {description} |")
    lines.extend(
        [
            "",
            "## Hard reduction rules",
            "",
            "1. `write_paper` is only derived from positive project decisions with no existing paper.",
            "2. `wake_ready` and `session_finished_ready` are delivery signals, not positive/negative outcomes.",
            "3. Negative, unknown, malformed, missing, or ambiguous project decisions map to `complete_no_paper`, not paper work.",
            "4. Publication readiness is `publication_draft` plus finalized publication automation package.",
            "5. Review/approval-like paper terms are compatibility/internal only; users see publication automation or artifact inspection.",
            "6. Idea/project source status is provenance. Runtime execution state lives in `queue_items`.",
            "",
            "## State-like surface inventory",
            "",
            "The schema also contains state-like flags, hints, event names, type discriminators, and provenance fields. "
            "These are classified here so they do not get promoted into lifecycle states by accident.",
            "",
            "| Surface | Class | Contract surface | Operator lane | Reason |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for surface, decision in sorted(STATE_SURFACE_INVENTORY.items()):
        contract_surface = decision.get("contract_surface") or ""
        lines.append(
            "| `{}` | `{}` | {} | `{}` | {} |".format(
                surface,
                decision.get("class", ""),
                f"`{contract_surface}`" if contract_surface else "",
                decision.get("operator_lane", ""),
                decision.get("reason", "").replace("|", "\\|"),
            )
        )
    lines.extend(
        [
            "",
            "## Surface-by-surface audit",
            "",
        ]
    )
    for surface in sorted(STATE_CONTRACT):
        lines.extend([f"### `{surface}`", "", _table_for_surface(surface, live=live), ""])
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate the raw-state reduction audit Markdown.")
    parser.add_argument("--database-url", default=os.environ.get("ENOCH_SUPABASE_DATABASE_URL", ""), help="Optional live Supabase/Postgres URL for live counts.")
    parser.add_argument("--output", type=Path, default=REPO_ROOT / "docs" / "state-reduction-audit.md")
    args = parser.parse_args()

    live = _live_counts(args.database_url) if args.database_url else {}
    text = render(live=live)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
