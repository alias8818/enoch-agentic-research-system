#!/usr/bin/env python3
"""Render the small target state vocabulary and migration-safe raw-state map.

This is intentionally a planning/verification artifact, not a live migration.
The control plane still accepts historical compatibility values while the
operator UI derives simple lanes from read models.
"""

from __future__ import annotations

import argparse
from collections import OrderedDict
from pathlib import Path
from typing import Any

from enoch_control_plane.control_plane.state_contract import STATE_REDUCTION_PLAN

ACTION_BY_DISPOSITION = {
    "keep": "keep",
    "alias": "alias",
    "migrate_after_freeze": "migrate",
    "legacy_internal": "retire",
}

# Centralized surface name for the duplicated QUEUE_ITEMS_STATUS literal
# (addresses top remaining S1192, 13x in DOMAIN_TARGETS and state reduction mappings).
QUEUE_ITEMS_STATUS = "queue_items.status"

# Centralized surface name for the duplicated PROJECT_DECISIONS_DECISION_GATE_STATE literal
# (addresses current top remaining S1192 in the same file, 7x in DOMAIN_TARGETS surfaces and mappings).
PROJECT_DECISIONS_DECISION_GATE_STATE = "project_decisions.decision_gate_state"

# Centralized surface name for the duplicated PAPERS_PAPER_STATUS literal
# (addresses current top remaining S1192 in the same file, 10x in DOMAIN_TARGETS surfaces and mappings).
PAPERS_PAPER_STATUS = "papers.paper_status"

DOMAIN_TARGETS: "OrderedDict[str, dict[str, Any]]" = OrderedDict(
    {
        "Ideas": {
            "surfaces": ["ideas.idea_status"],
            "states": OrderedDict(
                {
                    "ready": "Candidate intake item that can become project work.",
                    "held": "Intentionally parked idea; no worker action.",
                    "discarded": "Rejected/deprecated idea; no worker action.",
                    "promoted": "Idea already became project/publication provenance.",
                    "historical": "Imported or incomplete source provenance only.",
                }
            ),
        },
        "Projects": {
            "surfaces": [
                QUEUE_ITEMS_STATUS,
                PROJECT_DECISIONS_DECISION_GATE_STATE,
                "projects.origin_idea_status",
            ],
            "states": OrderedDict(
                {
                    "ready": "Queued project work that can dispatch when policy allows.",
                    "running": "Project work is actively dispatching/running/reconciling.",
                    "needs_attention": "Project is blocked, failed, or waiting on an operator/irreducible input.",
                    "paused": "Project is held by maintenance or policy.",
                    "done_no_paper": "Completed or non-positive project; no paper action.",
                    "paper_positive": "Decision gate says the completed work is paper-actionable.",
                    "canceled": "Terminal canceled project work.",
                    "historical": "Source/provenance-only project field; not runtime state.",
                }
            ),
        },
        "Runs": {
            "surfaces": ["runs.state", "queue_items.last_run_state", "runs.gate_state"],
            "states": OrderedDict(
                {
                    "running": "Worker dispatch/callback is in progress.",
                    "needs_attention": "Run failed, timed out, asked a question, or needs external evidence.",
                    "delivered": "Worker callback delivered; decision/paper lanes decide next action.",
                    "settled": "Run evidence is reconciled and historical.",
                    "canceled": "Terminal canceled run.",
                    "decision_positive": "Detail-only positive decision hint; not a run lifecycle.",
                    "decision_no_paper": "Detail-only non-positive/missing/malformed decision hint.",
                    "historical": "Imported/blank/legacy detail evidence; not active work.",
                }
            ),
        },
        "Papers": {
            "surfaces": [
                PAPERS_PAPER_STATUS,
                "publication_automation_items.automation_status",
            ],
            "states": OrderedDict(
                {
                    "needed": "Paper-positive work has no draft yet.",
                    "drafting": "Draft generation is running.",
                    "finalizing": "Automated rewrite/finalization/package work is pending or running.",
                    "ready_to_publish": "Required evidence paths and finalization package exist, and corpus-import ledger is missing.",
                    "published": "Corpus import ledger represents the publication.",
                    "blocked": "Publication automation has a real blocker.",
                    "archived": "Terminal no-publication/no-action paper artifact.",
                }
            ),
        },
    }
)

FINAL_STATE_OVERRIDES: dict[tuple[str, str], str] = {
    # Ideas / provenance
    ("ideas.idea_status", "unknown"): "historical",
    ("ideas.idea_status", "exploring"): "ready",
    ("ideas.idea_status", "testing"): "ready",
    ("ideas.idea_status", "validated"): "promoted",
    ("ideas.idea_status", "discarded"): "discarded",
    ("ideas.idea_status", "parked"): "held",
    ("ideas.idea_status", "deprecated"): "discarded",
    # Project queue
    (QUEUE_ITEMS_STATUS, "queued"): "ready",
    (QUEUE_ITEMS_STATUS, "dispatching"): "running",
    (QUEUE_ITEMS_STATUS, "running"): "running",
    (QUEUE_ITEMS_STATUS, "awaiting_wake"): "running",
    (QUEUE_ITEMS_STATUS, "wake_received"): "running",
    (QUEUE_ITEMS_STATUS, "reconciling"): "running",
    (QUEUE_ITEMS_STATUS, "completed"): "done_no_paper",
    (QUEUE_ITEMS_STATUS, "paused"): "paused",
    (QUEUE_ITEMS_STATUS, "canceled"): "canceled",
    (QUEUE_ITEMS_STATUS, "dispatch_error"): "needs_attention",
    (QUEUE_ITEMS_STATUS, "blocked"): "needs_attention",
    (QUEUE_ITEMS_STATUS, "needs_review"): "needs_attention",
    # Project decisions
    (PROJECT_DECISIONS_DECISION_GATE_STATE, "positive"): "paper_positive",
    (PROJECT_DECISIONS_DECISION_GATE_STATE, "negative"): "done_no_paper",
    (PROJECT_DECISIONS_DECISION_GATE_STATE, "needs_review"): "done_no_paper",
    (PROJECT_DECISIONS_DECISION_GATE_STATE, "missing"): "done_no_paper",
    (PROJECT_DECISIONS_DECISION_GATE_STATE, "malformed"): "done_no_paper",
    (PROJECT_DECISIONS_DECISION_GATE_STATE, "unknown"): "done_no_paper",
    # Runs and run/detail states
    ("runs.state", "prepared"): "running",
    ("runs.state", "dispatching"): "running",
    ("runs.state", "running"): "running",
    ("runs.state", "awaiting_wake"): "running",
    ("runs.state", "question_pending"): "needs_attention",
    ("runs.state", "wake_ready"): "delivered",
    ("runs.state", "session_finished_ready"): "delivered",
    ("runs.state", "gate_timeout"): "needs_attention",
    ("runs.state", "gate_error"): "needs_attention",
    ("runs.state", "reconciled"): "settled",
    ("runs.state", "dispatch_error"): "needs_attention",
    ("runs.state", "dispatch_accepted"): "running",
    ("runs.state", "needs_review"): "needs_attention",
    ("runs.state", "waiting_external_evidence"): "needs_attention",
    ("runs.state", "unknown"): "historical",
    ("runs.state", "cancelled"): "canceled",
    ("runs.state", "canceled"): "canceled",
    ("queue_items.last_run_state", "positive"): "decision_positive",
    ("queue_items.last_run_state", "negative"): "decision_no_paper",
    ("queue_items.last_run_state", "missing"): "decision_no_paper",
    ("queue_items.last_run_state", "malformed"): "decision_no_paper",
    ("queue_items.last_run_state", ""): "historical",
    ("runs.gate_state", ""): "historical",
    # Papers / publication automation
    (PAPERS_PAPER_STATUS, "eligible"): "needed",
    (PAPERS_PAPER_STATUS, "draft_generating"): "drafting",
    (PAPERS_PAPER_STATUS, "draft_review"): "finalizing",
    (PAPERS_PAPER_STATUS, "publication_generating"): "finalizing",
    (PAPERS_PAPER_STATUS, "publication_draft"): "finalizing",
    (PAPERS_PAPER_STATUS, "human_review_required"): "blocked",
    (PAPERS_PAPER_STATUS, "archived"): "archived",
    (PAPERS_PAPER_STATUS, "finalized"): "ready_to_publish",
    (PAPERS_PAPER_STATUS, "approved_for_corpus"): "published",
    ("publication_automation_items.automation_status", "queued"): "finalizing",
    ("publication_automation_items.automation_status", "claimed"): "finalizing",
    ("publication_automation_items.automation_status", "blocked"): "blocked",
    ("publication_automation_items.automation_status", "finalized"): "ready_to_publish",
    ("publication_automation_items.automation_status", "deferred"): "archived",
    ("publication_automation_items.automation_status", "triage_ready"): "finalizing",
    ("publication_automation_items.automation_status", "unreviewed"): "finalizing",
    ("publication_automation_items.automation_status", "in_review"): "finalizing",
    ("publication_automation_items.automation_status", "changes_requested"): "blocked",
    (
        "publication_automation_items.automation_status",
        "approved_for_finalization",
    ): "finalizing",
    ("publication_automation_items.automation_status", "rejected"): "archived",
}


def final_state_for(surface: str, raw_value: str) -> str:
    if (surface, raw_value) in FINAL_STATE_OVERRIDES:
        return FINAL_STATE_OVERRIDES[(surface, raw_value)]
    if surface in {"projects.origin_idea_status"}:
        return "historical"
    if (
        surface in {"queue_items.last_run_state", "runs.gate_state"}
        and ("runs.state", raw_value) in FINAL_STATE_OVERRIDES
    ):
        return FINAL_STATE_OVERRIDES[("runs.state", raw_value)]
    raise KeyError(f"missing final state mapping for {surface}.{raw_value!r}")


def cleanup_action(disposition: str) -> str:
    return ACTION_BY_DISPOSITION[disposition]


def iter_mapping_rows() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    surface_to_domain = {
        surface: domain
        for domain, config in DOMAIN_TARGETS.items()
        for surface in config["surfaces"]
    }
    for surface, values in STATE_REDUCTION_PLAN.items():
        domain = surface_to_domain[surface]
        for raw_value, decision in sorted(values.items(), key=lambda item: item[0]):
            disposition = decision["disposition"]
            action = cleanup_action(disposition)
            target = str(decision.get("replacement") or "")
            safe = (
                "yes"
                if action in {"alias", "migrate"}
                else "no"
                if action == "retire"
                else "n/a"
            )
            rows.append(
                {
                    "domain": domain,
                    "surface": surface,
                    "raw_value": raw_value or "<blank>",
                    "final_state": final_state_for(surface, raw_value),
                    "cleanup_action": action,
                    "migration_target": target or "—",
                    "safe_auto_migrate": safe,
                    "operator_lane": decision["operator_lane"],
                    "reason": decision["reason"],
                }
            )
    return rows


def render() -> str:
    lines: list[str] = [
        "# State vocabulary reduction plan",
        "",
        "Status: migration-safe target vocabulary for Supabase-backed runtime state.",
        "",
        "This plan reduces operator and agent reasoning to small domain vocabularies while keeping raw compatibility values constrained and auditable. It is a planning and validation artifact: live data changes still go through `scripts/normalize_state_surfaces.py` dry-run/apply plus `scripts/state_doctor.py` evidence.",
        "",
        "## Cleanup action contract",
        "",
        "| Action | Meaning | Data migration rule |",
        "| --- | --- | --- |",
        "| `keep` | Canonical value may continue to be minted. | No cleanup migration. |",
        "| `alias` | Compatibility spelling or callback synonym. | Normalize when present and state doctor is otherwise clean. |",
        "| `migrate` | Old workflow value with a safe replacement after freeze. | Migrate only through reviewed normalization SQL. |",
        "| `retire` | Historical/import/provenance value accepted for audit only. | Do not mint; do not bulk rewrite without a provenance-preserving migration plan. |",
        "",
        "## Final small state sets",
        "",
    ]
    for domain, config in DOMAIN_TARGETS.items():
        lines.extend(
            [f"### {domain}", "", "| Final state | Meaning |", "| --- | --- |"]
        )
        for state, meaning in config["states"].items():
            lines.append(f"| `{state}` | {meaning} |")
        lines.append("")
    lines.extend(
        [
            "## Migration-safe raw-state mapping",
            "",
            "| Domain | Surface | Raw value | Final state | Cleanup action | Migration target | Safe auto-migrate? | Operator lane | Reason |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for row in iter_mapping_rows():
        lines.append(
            "| {domain} | `{surface}` | `{raw_value}` | `{final_state}` | `{cleanup_action}` | {migration_target} | {safe_auto_migrate} | `{operator_lane}` | {reason} |".format(
                **row
            )
        )
    lines.extend(
        [
            "",
            "## Supabase cleanup boundary",
            "",
            "- Supabase check constraints remain the guardrail against arbitrary raw state strings.",
            "- `scripts/normalize_state_surfaces.py` owns reviewed cleanup SQL and is dry-run by default.",
            "- `scripts/state_doctor.py` must pass after any cleanup and before unfreezing runtime automation.",
            "- `retire` rows are not noise if classified as inactive historical/attention residue; they remain visible as provenance.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Render the Enoch state vocabulary reduction plan."
    )
    parser.add_argument(
        "--output", type=Path, default=Path("docs/state-vocabulary-reduction-plan.md")
    )
    args = parser.parse_args()
    text = render()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
