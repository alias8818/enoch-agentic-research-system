#!/usr/bin/env python3
"""Audit Research Facility candidates for near-duplicate loss risk.

This is intentionally read-only. It does not undo dedupe, promote ideas, or write
queue rows. It classifies recent generated/admitted/rejected candidates into:

- duplicate_suppress: very similar mechanism/test path; safe to keep suppressed.
- variant_hold: similar topic family but materially different test/mechanism.
- branch_candidate: variant appears to address a prior failure and deserves a
  bounded follow-up/campaign review.

The audit can only see rows that reached Research Facility ledgers. If a provider
candidate was rejected before ledger persistence or collided on a unique key
without an audit row, this script cannot recover it.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

import psycopg
from psycopg.rows import dict_row

TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_+.-]{2,}", re.I)
STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "that",
    "this",
    "from",
    "into",
    "using",
    "use",
    "can",
    "will",
    "would",
    "could",
    "should",
    "than",
    "then",
    "when",
    "where",
    "while",
    "model",
    "models",
    "test",
    "tests",
    "run",
    "runs",
    "local",
    "data",
    "evidence",
    "mechanism",
    "baseline",
    "compare",
    "against",
    "candidate",
}
BRANCH_TERMS = {
    "failure",
    "fails",
    "failed",
    "negative",
    "collapse",
    "addresses",
    "address",
    "instead",
    "alternative",
    "control",
    "ablation",
    "scale",
    "scaled",
    "medium",
    "full",
    "direct",
    "gpt",
    "gpt2",
    "gpt-2",
    "followup",
    "follow-up",
    "diagnostic",
    "diagnosis",
    "capacity",
    "dataset",
    "seed",
    "robustness",
    "replicate",
    "replication",
}
DELTA_FIELDS = [
    "mechanism",
    "implementation",
    "baseline_to_beat",
    "success_threshold",
    "kill_condition",
    "required_evidence_text",
]


@dataclass
class AuditFinding:
    cluster_id: str
    candidate_id: str
    candidate_title: str
    candidate_status: str
    admission_decision: str
    candidate_score: float
    canonical_project: str
    canonical_title: str
    prior_decision: str
    prior_hypothesis_status: str
    similarity: float
    variant_type: str
    could_have_been_good_branch: bool
    material_deltas: list[str]
    dedupe_reason: str
    recommended_action: str


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True)
    return str(value)


def tokens(text: str) -> set[str]:
    return {
        m.group(0).lower()
        for m in TOKEN_RE.finditer(text)
        if m.group(0).lower() not in STOPWORDS
    }


def token_similarity(left_tokens: set[str], right_tokens: set[str]) -> float:
    if not left_tokens or not right_tokens:
        return 0.0
    return round(len(left_tokens & right_tokens) / len(left_tokens | right_tokens), 4)


def text_similarity(left: str, right: str) -> float:
    return token_similarity(tokens(left), tokens(right))


def _field_similarity(left: str, right: str) -> float:
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0
    return text_similarity(left, right)


def required_evidence_text(row: dict[str, Any]) -> str:
    return " ".join(_text(x) for x in (row.get("required_evidence") or []))


def material_deltas(candidate: dict[str, Any], prior: dict[str, Any]) -> list[str]:
    enriched = dict(candidate)
    enriched["required_evidence_text"] = required_evidence_text(candidate)
    prior_enriched = dict(prior)
    prior_enriched["required_evidence_text"] = _text(
        prior.get("prior_required_evidence")
    )
    deltas: list[str] = []
    for field in DELTA_FIELDS:
        sim = _field_similarity(
            _text(enriched.get(field)), _text(prior_enriched.get(field))
        )
        if sim < 0.55:
            deltas.append(field)
    return deltas


def looks_like_branch(
    candidate: dict[str, Any], prior: dict[str, Any], deltas: list[str]
) -> bool:
    haystack = "\n".join(
        [
            _text(candidate.get("title")),
            _text(candidate.get("hypothesis")),
            _text(candidate.get("mechanism")),
            _text(candidate.get("implementation")),
            _text(candidate.get("novelty_comparison")),
            _text(candidate.get("risk_notes")),
            _text(candidate.get("kill_condition")),
            _text(prior.get("stop_reason")),
            _text(prior.get("recommended_next_action")),
        ]
    ).lower()
    has_branch_language = bool(tokens(haystack) & BRANCH_TERMS)
    prior_negative = _text(prior.get("decision_gate_state")) in {
        "negative",
        "unknown",
        "needs_review",
    }
    has_material_delta = len(deltas) >= 2
    return bool(prior_negative and has_material_delta and has_branch_language)


def classify(
    candidate: dict[str, Any], prior: dict[str, Any], similarity: float
) -> tuple[str, bool, list[str], str, str]:
    deltas = material_deltas(candidate, prior)
    decision = _text(candidate.get("admission_decision") or candidate.get("status"))
    if similarity >= 0.82 and len(deltas) <= 1:
        return (
            "duplicate_suppress",
            False,
            deltas,
            "same topic with no material mechanism/test/baseline/evidence delta",
            "Keep suppressed; no bounded branch recommended.",
        )
    if looks_like_branch(candidate, prior, deltas):
        return (
            "branch_candidate",
            True,
            deltas,
            f"near duplicate but materially changes {', '.join(deltas[:4])} and addresses a prior non-positive result",
            "Review for bounded follow-up promotion; require direct evidence tied to the changed mechanism.",
        )
    action = "Hold as a variant; do not auto-promote unless portfolio coverage or prior failure analysis calls for it."
    if decision == "admitted":
        action = "Admitted but unpromoted near-duplicate; dry-run promotion only if it adds a new control, dataset, scale, or failure escape route."
    return (
        "variant_hold",
        False,
        deltas,
        f"similar topic family with material deltas: {', '.join(deltas[:4]) or 'limited'}",
        action,
    )


def candidate_text(row: dict[str, Any]) -> str:
    return "\n".join(
        _text(row.get(k))
        for k in [
            "title",
            "category",
            "hypothesis",
            "mechanism",
            "description",
            "implementation",
            "baseline_to_beat",
            "success_threshold",
            "kill_condition",
            "novelty_comparison",
            "risk_notes",
        ]
    )


def prior_text(row: dict[str, Any]) -> str:
    return "\n".join(
        _text(row.get(k))
        for k in [
            "project_name",
            "idea_title",
            "category",
            "description",
            "implementation",
            "baseline_to_beat",
            "kill_condition",
            "stop_reason",
            "recommended_next_action",
        ]
    )


def fetch_rows(
    dsn: str, *, candidate_limit: int, prior_limit: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        candidates = conn.execute(
            """
            select c.candidate_id, c.generation_mode, c.status, c.title, c.category,
                   c.hypothesis, c.mechanism, c.description, c.implementation,
                   c.baseline_to_beat, c.success_threshold, c.kill_condition,
                   c.required_evidence, c.similar_prior_projects, c.novelty_comparison,
                   c.risk_notes, c.total_score, c.dedupe_key, c.updated_at,
                   a.admission_decision, a.admission_reason, a.admitted_idea_id
            from enoch.research_candidates c
            left join lateral (
                select admission_decision, admission_reason, admitted_idea_id
                from enoch.research_admissions a
                where a.candidate_id = c.candidate_id
                order by created_at desc, admission_id desc
                limit 1
            ) a on true
            order by c.updated_at desc, c.total_score desc
            limit %s
            """,
            (candidate_limit,),
        ).fetchall()
        priors = conn.execute(
            """
            select p.project_id, p.project_name, i.title as idea_title, i.category,
                   i.description, i.implementation, i.baseline_to_beat, i.kill_condition,
                   d.decision_gate_state,
                   d.payload_json->'project_decision'->>'project_decision' as project_decision,
                   d.payload_json->'project_decision'->>'hypothesis_status' as hypothesis_status,
                   d.payload_json->'project_decision'->>'stop_reason' as stop_reason,
                   d.payload_json->'project_decision'->>'recommended_next_action' as recommended_next_action,
                   d.payload_json->'project_decision'->'followup_required_evidence' as prior_required_evidence,
                   d.updated_at
            from enoch.project_decisions d
            join enoch.projects p on p.project_id = d.project_id
            left join enoch.ideas i on i.idea_id = p.project_id
            order by d.updated_at desc
            limit %s
            """,
            (prior_limit,),
        ).fetchall()
    return [dict(r) for r in candidates], [dict(r) for r in priors]


def audit(
    candidates: Iterable[dict[str, Any]],
    priors: Iterable[dict[str, Any]],
    *,
    threshold: float,
) -> dict[str, Any]:
    findings: list[AuditFinding] = []
    prior_list = list(priors)
    prior_index = []
    for prior in prior_list:
        prior_index.append(
            (prior, tokens(prior_text(prior)), _text(prior.get("category")).lower())
        )
    for candidate in candidates:
        # Already-promoted admitted candidates are represented in the queue; this audit is about lost/held variants.
        if _text(candidate.get("admitted_idea_id")):
            continue
        best: tuple[float, dict[str, Any]] | None = None
        c_tokens = tokens(candidate_text(candidate))
        c_category = _text(candidate.get("category")).lower()
        for prior, p_tokens, p_category in prior_index:
            if c_category and p_category and c_category != p_category:
                # Cross-category duplicates are rare; skipping them makes the audit fast and reduces noise.
                continue
            sim = token_similarity(c_tokens, p_tokens)
            if best is None or sim > best[0]:
                best = (sim, prior)
        if not best or best[0] < threshold:
            continue
        similarity, prior = best
        variant_type, could_branch, deltas, reason, action = classify(
            candidate, prior, similarity
        )
        cluster_id = f"{_text(candidate.get('category')) or 'uncategorized'}:{_text(prior.get('project_id'))}"
        findings.append(
            AuditFinding(
                cluster_id=cluster_id,
                candidate_id=_text(candidate.get("candidate_id")),
                candidate_title=_text(candidate.get("title")),
                candidate_status=_text(candidate.get("status")),
                admission_decision=_text(candidate.get("admission_decision")),
                candidate_score=float(candidate.get("total_score") or 0),
                canonical_project=_text(prior.get("project_id")),
                canonical_title=_text(
                    prior.get("project_name") or prior.get("idea_title")
                ),
                prior_decision=_text(
                    prior.get("project_decision") or prior.get("decision_gate_state")
                ),
                prior_hypothesis_status=_text(prior.get("hypothesis_status")),
                similarity=similarity,
                variant_type=variant_type,
                could_have_been_good_branch=could_branch,
                material_deltas=deltas,
                dedupe_reason=reason,
                recommended_action=action,
            )
        )
    order = {"branch_candidate": 0, "variant_hold": 1, "duplicate_suppress": 2}
    findings.sort(
        key=lambda f: (
            order.get(f.variant_type, 9),
            -f.candidate_score,
            -f.similarity,
            f.candidate_id,
        )
    )
    counts: dict[str, int] = {}
    for finding in findings:
        counts[finding.variant_type] = counts.get(finding.variant_type, 0) + 1
    return {
        "summary": {
            "candidate_rows_checked": len(list(candidates))
            if not isinstance(candidates, list)
            else len(candidates),
            "prior_decisions_checked": len(prior_list),
            "similarity_threshold": threshold,
            "finding_count": len(findings),
            "variant_type_counts": counts,
            "limitation": "Rows absent from Research Facility ledgers cannot be recovered by this audit.",
        },
        "findings": [asdict(f) for f in findings],
    }


def write_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# Research dedupe-loss audit",
        "",
        f"Candidates checked: {summary['candidate_rows_checked']}",
        f"Prior decisions checked: {summary['prior_decisions_checked']}",
        f"Similarity threshold: {summary['similarity_threshold']}",
        f"Findings: {summary['finding_count']}",
        "",
        "## Variant type counts",
        "",
    ]
    for key, value in sorted(summary["variant_type_counts"].items()):
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Ranked findings", ""])
    for idx, row in enumerate(report["findings"], 1):
        lines.extend(
            [
                f"### {idx}. {row['variant_type']} — {row['candidate_title']}",
                "",
                f"- candidate_id: `{row['candidate_id']}`",
                f"- candidate_status/admission: `{row['candidate_status']}` / `{row['admission_decision']}`",
                f"- candidate_score: `{row['candidate_score']}`",
                f"- canonical_project: `{row['canonical_project']}` — {row['canonical_title']}",
                f"- prior_decision: `{row['prior_decision']}` / hypothesis `{row['prior_hypothesis_status']}`",
                f"- similarity: `{row['similarity']}`",
                f"- material_deltas: {', '.join(row['material_deltas']) or 'none'}",
                f"- could_have_been_good_branch: `{str(row['could_have_been_good_branch']).lower()}`",
                f"- dedupe_reason: {row['dedupe_reason']}",
                f"- recommended_action: {row['recommended_action']}",
                "",
            ]
        )
    lines.extend(["## Limitation", "", summary["limitation"], ""])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url",
        default=os.environ.get("ENOCH_DATABASE_URL")
        or os.environ.get("SUPABASE_DATABASE_URL")
        or os.environ.get("DATABASE_URL")
        or "",
    )
    parser.add_argument("--candidate-limit", type=int, default=500)
    parser.add_argument("--prior-limit", type=int, default=1000)
    parser.add_argument("--similarity-threshold", type=float, default=0.14)
    parser.add_argument("--output-json", type=Path)
    parser.add_argument("--output-md", type=Path)
    args = parser.parse_args(argv)
    if not args.database_url:
        raise SystemExit(
            "database URL required via --database-url or ENOCH_DATABASE_URL/SUPABASE_DATABASE_URL/DATABASE_URL"
        )
    candidates, priors = fetch_rows(
        args.database_url,
        candidate_limit=args.candidate_limit,
        prior_limit=args.prior_limit,
    )
    report = audit(candidates, priors, threshold=args.similarity_threshold)
    text = json.dumps(report, indent=2, sort_keys=True)
    if args.output_json:
        args.output_json.write_text(text + "\n", encoding="utf-8")
    if args.output_md:
        args.output_md.write_text(write_markdown(report), encoding="utf-8")
    if not args.output_json and not args.output_md:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
