#!/usr/bin/env python3
"""Synthesize related Research Facility candidates into bounded oracle projects.

This module is intentionally deterministic around clustering, validation, and SQL
emission. Provider output is never accepted as system truth until it passes the
Research Facility candidate contract and the additional oracle-project checks.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import research_facility, research_provider_budget, research_provider_generate

REQUIRED_ORACLE_ARTIFACTS = {
    "run_notes.md",
    "metrics.json",
    "trace_schema.md",
    "oracle_report.md",
    "failure_cases.jsonl",
    ".enoch/project_decision.json",
}
SUCCESS_STATES = {"positive", "finalize_positive", "paper_positive", "published", "strict_pass"}
USEFUL_STATES = {"useful_signal", "supported_but_negative", "finalize_negative"}
REQUIRED_STANDARD_TEXT_FIELDS = (
    "title",
    "hypothesis",
    "mechanism",
    "description",
    "implementation",
    "baseline_to_beat",
    "success_threshold",
    "kill_condition",
    "accessibility_delta",
    "novelty_comparison",
    "risk_notes",
)
REQUIRED_STANDARD_ARRAY_FIELDS = ("expected_artifacts", "required_evidence", "likely_failure_modes")
REQUIRED_SCORE_FIELDS = ("novelty_score", "feasibility_score", "accessibility_score", "falsifiability_score")


def _text(value: Any) -> str:
    return str(value or "").strip()


def _as_list(value: Any) -> list[Any]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        items: list[Any] = []
        for item in value:
            if not isinstance(item, str):
                if _text(item):
                    items.append(item)
                continue
            text = _text(item)
            if not text:
                continue
            items.extend(_split_numbered_list_text(text))
        return items
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, dict):
        return list(value)
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return _split_numbered_list_text(value)
        return _as_list(decoded) if isinstance(decoded, list) else _split_numbered_list_text(value)
    return [value]


def _split_numbered_list_text(value: str) -> list[str]:
    text = _text(value)
    if not text:
        return []
    markers = list(re.finditer(r"(?<!\S)\d+\.\s+", text))
    if len(markers) < 2:
        return [text]
    items: list[str] = []
    for index, marker in enumerate(markers):
        start = marker.end()
        end = markers[index + 1].start() if index + 1 < len(markers) else len(text)
        item = text[start:end].strip()
        if item:
            items.append(item)
    return items


def _tokens(value: str) -> set[str]:
    stop = {
        "the", "and", "with", "from", "into", "using", "that", "this", "branch",
        "test", "local", "probe", "speculative", "decoding", "dflash", "baseline",
    }
    return {token for token in re.findall(r"[a-z0-9]+", value.lower()) if len(token) > 2 and token not in stop}


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _primary_url(row: dict[str, Any]) -> str:
    urls = [_text(item) for item in _as_list(row.get("source_urls")) if _text(item)]
    return urls[0] if urls else ""


def _cluster_key(row: dict[str, Any]) -> str:
    category = _text(row.get("category")).lower() or "uncategorized"
    url = _primary_url(row)
    if url:
        return f"{category}:{url}"
    mechanism = "-".join(sorted(list(_tokens(" ".join([_text(row.get("title")), _text(row.get("mechanism")), _text(row.get("baseline_to_beat"))])))[:5]))
    return f"{category}:mechanism:{mechanism or 'unknown'}"


def detect_candidate_clusters(candidates: Iterable[dict[str, Any]], *, min_size: int = 3, similarity_floor: float = 0.32) -> list[dict[str, Any]]:
    """Return candidate clusters that should be synthesized before queueing."""

    rows = [dict(row) for row in candidates]
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[_cluster_key(row)].append(row)

    clusters: list[dict[str, Any]] = []
    for key, members in grouped.items():
        if len(members) < min_size:
            continue
        token_sets = [_tokens(" ".join([_text(row.get("title")), _text(row.get("mechanism")), _text(row.get("baseline_to_beat"))])) for row in members]
        pairs = []
        for idx, left in enumerate(token_sets):
            for right in token_sets[idx + 1:]:
                pairs.append(_jaccard(left, right))
        mean_similarity = round(sum(pairs) / len(pairs), 3) if pairs else 1.0
        shared_setup = _shared_setup_signal(members)
        if mean_similarity < similarity_floor and not shared_setup:
            continue
        clusters.append(
            {
                "cluster_key": key,
                "category": _text(members[0].get("category")).lower(),
                "source_url": _primary_url(members[0]),
                "candidate_count": len(members),
                "mean_similarity": mean_similarity,
                "shared_setup": shared_setup,
                "requires_synthesis": True,
                "reason": "related candidates share source/category/setup; synthesize one oracle before branch implementation",
                "candidates": members,
            }
        )
    clusters.sort(key=lambda item: (item["candidate_count"], item["mean_similarity"]), reverse=True)
    return clusters


def _shared_setup_signal(rows: list[dict[str, Any]]) -> bool:
    text = "\n".join(" ".join([_text(row.get("implementation")), _text(row.get("expected_artifacts")), _text(row.get("mechanism"))]) for row in rows).lower()
    markers = ("trace", "harness", "instrument", "oracle", "baseline", "dflash", "top-k", "metrics")
    return sum(1 for marker in markers if marker in text) >= 2


def extract_reflection_patterns(rows: Iterable[dict[str, Any]], *, limit: int = 8) -> list[dict[str, Any]]:
    """Summarize old successes/useful signals as inspiration patterns only."""

    patterns: list[dict[str, Any]] = []
    for row in rows:
        state = _text(row.get("decision_gate_state") or row.get("research_outcome") or row.get("decision") or row.get("status")).lower()
        summary = _text(row.get("decision_summary") or row.get("summary") or row.get("project_decision_summary"))
        is_positive = state in SUCCESS_STATES or "finalize_positive" in state or "paper_positive" in state
        is_useful = is_positive or "useful" in state or (state in USEFUL_STATES and "useful" in summary.lower())
        if not is_positive and not is_useful:
            continue
        patterns.append(
            {
                "project_id": _text(row.get("project_id") or row.get("idea_id") or row.get("candidate_id")),
                "title": _text(row.get("project_name") or row.get("title")),
                "category": _text(row.get("category")),
                "decision_gate_state": state,
                "evidence_pattern": summary[:800],
                "required_evidence": _as_list(row.get("required_evidence")),
                "use_as": "pattern_seed",
                "not_system_truth": True,
            }
        )
    return patterns[:limit]


def build_synthesis_prompt(cluster: dict[str, Any], reflection_patterns: list[dict[str, Any]]) -> str:
    compact_candidates = [
        {
            "candidate_id": _text(row.get("candidate_id")),
            "title": _text(row.get("title")),
            "hypothesis": _text(row.get("hypothesis")),
            "mechanism": _text(row.get("mechanism")),
            "baseline_to_beat": _text(row.get("baseline_to_beat")),
            "success_threshold": _text(row.get("success_threshold")),
            "kill_condition": _text(row.get("kill_condition")),
        }
        for row in cluster.get("candidates", [])
    ]
    return f"""
Return ONLY compact JSON. No markdown. Top-level object must be {{"candidates":[one_candidate]}}.

Synthesize these related Enoch Research Facility branch candidates into exactly one oracle/meta-experiment candidate.
Do not implement each branch separately. Design a single bounded first-pass experiment that ranks which branch deserves implementation.

Hard constraints:
- Single GB10-class local machine.
- Bounded runtime; no datacenter-scale training.
- Negative result must be useful.
- LLM output is not system truth; include deterministic success and kill thresholds.
- Use prior successes only as pattern seeds, not proof.

The candidate must include all standard Research Facility fields plus:
- expected_artifacts containing run_notes.md, metrics.json, trace_schema.md, oracle_report.md, failure_cases.jsonl, .enoch/project_decision.json
- numeric success_threshold and kill_condition
- non-empty description, implementation, accessibility_delta, required_evidence, likely_failure_modes, and risk_notes
- novelty_score, feasibility_score, accessibility_score, and falsifiability_score as 0-10 numbers
- novelty_comparison explaining why this is not a clone of branch candidates or prior successes

Cluster:
{json.dumps({k: v for k, v in cluster.items() if k != 'candidates'}, sort_keys=True)}

Branch candidates:
{json.dumps(compact_candidates, sort_keys=True)}

Reflection pattern seeds:
{json.dumps(reflection_patterns, sort_keys=True)}
""".strip()


def validate_synthesized_candidate(candidate: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    artifacts = {_text(item) for item in _as_list(candidate.get("expected_artifacts"))}
    for artifact in sorted(REQUIRED_ORACLE_ARTIFACTS):
        if artifact not in artifacts:
            problems.append(f"missing expected artifact {artifact}")
    for key in REQUIRED_STANDARD_TEXT_FIELDS:
        if not _text(candidate.get(key)):
            problems.append(f"missing {key}")
    for key in REQUIRED_STANDARD_ARRAY_FIELDS:
        if not _as_list(candidate.get(key)):
            problems.append(f"missing {key}")
    for key in REQUIRED_SCORE_FIELDS:
        try:
            score = float(candidate.get(key))
        except (TypeError, ValueError):
            problems.append(f"{key} must be a 0-10 number")
            continue
        if score < 0.0 or score > 10.0:
            problems.append(f"{key} must be a 0-10 number")
    for key in ("success_threshold", "kill_condition"):
        if not re.search(r"\d", _text(candidate.get(key))):
            problems.append(f"{key} must include at least one numeric threshold")
    if "oracle" not in " ".join([_text(candidate.get("title")), _text(candidate.get("implementation")), _text(candidate.get("mechanism"))]).lower():
        problems.append("synthesized candidate must explicitly describe an oracle/meta-experiment")
    return problems


def enrich_synthesized_candidate(candidate: dict[str, Any], cluster: dict[str, Any], reflection_patterns: list[dict[str, Any]], *, requested_by: str) -> dict[str, Any]:
    row = dict(candidate)
    source_ids = [_text(row.get("candidate_id")) for row in cluster.get("candidates", []) if _text(row.get("candidate_id"))]
    for key in REQUIRED_STANDARD_ARRAY_FIELDS:
        if key in row:
            row[key] = _as_list(row.get(key))
    row.setdefault("generation_mode", "manual_import")
    row.setdefault("category", cluster.get("category") or "systems-research")
    row.setdefault("priority", "High")
    row.setdefault("machine_target", "gb10")
    row.setdefault("model", "gpt-5.5")
    row.setdefault("sandbox", "danger-full-access")
    row.setdefault("source_kind", "research_synthesis")
    row.setdefault("source_ids", [])
    row.setdefault("source_urls", [cluster.get("source_url")] if cluster.get("source_url") else [])
    row.setdefault("provider", "synthetic_synthesis")
    row.setdefault("provider_model", "provider_synthesis")
    row.setdefault("prompt_version", "research_facility_synthesis_v1")
    row.setdefault("generated_by", "scripts/research_facility_synthesis.py")
    row["raw_candidate_json"] = {
        **(row.get("raw_candidate_json") if isinstance(row.get("raw_candidate_json"), dict) else {}),
        "synthesized_from": source_ids,
        "reflection_source_ids": [_text(pattern.get("project_id")) for pattern in reflection_patterns if _text(pattern.get("project_id"))],
        "cluster_key": cluster.get("cluster_key"),
        "requested_by": requested_by,
    }
    return row


def synthesize_clusters(
    clusters: list[dict[str, Any]],
    *,
    reflection_patterns: list[dict[str, Any]],
    provider: Callable[[str], dict[str, Any]],
    requested_by: str,
) -> dict[str, Any]:
    synthesized: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    prompts: list[dict[str, Any]] = []
    for cluster in clusters:
        prompt = build_synthesis_prompt(cluster, reflection_patterns)
        prompts.append({"cluster_key": cluster.get("cluster_key"), "prompt": prompt})
        try:
            response = provider(prompt)
        except Exception as exc:  # pragma: no cover - defensive CLI path
            failures.append({"cluster_key": cluster.get("cluster_key"), "error": str(exc)})
            continue
        candidates = response.get("candidates") if isinstance(response, dict) else None
        if not isinstance(candidates, list) or len(candidates) != 1 or not isinstance(candidates[0], dict):
            failures.append({"cluster_key": cluster.get("cluster_key"), "error": "provider must return exactly one candidate"})
            continue
        candidate = enrich_synthesized_candidate(candidates[0], cluster, reflection_patterns, requested_by=requested_by)
        problems = validate_synthesized_candidate(candidate)
        if problems:
            failures.append({"cluster_key": cluster.get("cluster_key"), "candidate_id": candidate.get("candidate_id"), "problems": problems})
            continue
        synthesized.append(candidate)
    return {
        "schema_version": "enoch_research_synthesis_report_v1",
        "ok": not failures,
        "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "requested_by": requested_by,
        "cluster_count": len(clusters),
        "synthesized_count": len(synthesized),
        "clusters": clusters,
        "reflection_patterns": reflection_patterns,
        "synthesized_candidates": synthesized,
        "failures": failures,
        "prompts": prompts,
    }


def emit_synthesis_sql(report: dict[str, Any], *, requested_by: str, queue_synthesized: bool) -> str:
    candidates = [row for row in report.get("synthesized_candidates", []) if isinstance(row, dict)]
    args = argparse.Namespace(
        default_machine="gb10",
        default_model="gpt-5.5",
        default_sandbox="danger-full-access",
        admit_threshold=72.0,
        review_threshold=58.0,
        history=[],
    )
    plans = research_facility.plan_candidates(candidates, args)
    failed_plans = [plan for plan in plans if plan.admission_decision != "admitted"]
    if failed_plans:
        summary = "; ".join(
            f"{plan.candidate.get('candidate_id')}: {plan.admission_decision} ({plan.admission_reason})"
            for plan in failed_plans
        )
        raise ValueError(f"synthesized candidates must pass admission before SQL emission: {summary}")
    sql = research_facility.emit_sql(plans, requested_by=requested_by, queue_admitted=queue_synthesized)
    lines = [sql.rstrip(), "", "begin;", ""]
    for cluster, candidate in zip(report.get("clusters", []), candidates, strict=False):
        synthesized_id = _text(candidate.get("candidate_id"))
        if not synthesized_id:
            continue
        for branch in cluster.get("candidates", []):
            branch_id = _text(branch.get("candidate_id"))
            if not branch_id:
                continue
            lines.append(
                "update enoch.research_candidates "
                "set status = 'deferred_pending_oracle', updated_at = now(), "
                "raw_candidate_json = coalesce(raw_candidate_json, '{}'::jsonb) || "
                f"{research_facility.sql_json({'superseded_by': synthesized_id, 'synthesis_reason': cluster.get('reason', '')})} "
                f"where candidate_id = {research_facility.sql_literal(branch_id)} "
                "and status in ('generated','needs_review','admitted');"
            )
            for source_type, source_id, target_type, target_id, relation in (
                ("candidate", branch_id, "candidate", synthesized_id, "synthesized_from"),
                ("candidate", branch_id, "candidate", synthesized_id, "superseded_by"),
            ):
                lines.append(
                    "insert into enoch.research_lineage(source_type, source_id, target_type, target_id, relation_type, evidence_json) values "
                    f"({research_facility.sql_literal(source_type)}, {research_facility.sql_literal(source_id)}, {research_facility.sql_literal(target_type)}, {research_facility.sql_literal(target_id)}, {research_facility.sql_literal(relation)}, "
                    f"{research_facility.sql_json({'cluster_key': cluster.get('cluster_key'), 'requested_by': requested_by})}) "
                    "on conflict do nothing;"
                )
        for pattern in report.get("reflection_patterns", []):
            source_id = _text(pattern.get("project_id"))
            if source_id:
                lines.append(
                    "insert into enoch.research_lineage(source_type, source_id, target_type, target_id, relation_type, evidence_json) values "
                    f"('project', {research_facility.sql_literal(source_id)}, 'candidate', {research_facility.sql_literal(synthesized_id)}, 'inspired_by_success', {research_facility.sql_json({'not_system_truth': True})}) "
                    "on conflict do nothing;"
                )
    lines.extend(["", "commit;", ""])
    return "\n".join(lines)


def budget_checked_provider(
    provider: Callable[[str], dict[str, Any]],
    *,
    budget_check: Callable[[], dict[str, Any]],
) -> Callable[[str], dict[str, Any]]:
    checked: dict[str, Any] | None = None

    def call(prompt: str) -> dict[str, Any]:
        nonlocal checked
        if checked is None:
            checked = budget_check()
        if not checked.get("ok"):
            failures = checked.get("failures") or ["provider budget preflight failed"]
            raise RuntimeError("; ".join(_text(item) for item in failures if _text(item)))
        return provider(prompt)

    return call


def _provider_from_args(args: argparse.Namespace) -> Callable[[str], dict[str, Any]]:
    if args.provider_response_json:
        payload = json.loads(Path(args.provider_response_json).read_text(encoding="utf-8"))
        return lambda _prompt: payload

    def call(prompt: str) -> dict[str, Any]:
        payload = research_provider_generate.call_openai_compatible_chat(
            base_url=args.provider_base_url,
            model=args.provider_model,
            prompt=prompt,
            api_key=args.provider_api_key or os.environ.get("SYNTHETIC_API_KEY", ""),
            temperature=args.temperature,
            max_tokens=args.max_tokens,
            timeout=args.timeout,
        )
        return research_provider_generate.extract_json_object(research_provider_generate._extract_chat_content(payload))

    if args.skip_budget_preflight:
        return call

    def budget_check() -> dict[str, Any]:
        base_url = str(args.budget_base_url).rstrip("/")
        payload = research_provider_budget.fetch_json(
            f"{base_url}/v2/quotas",
            api_key="" if args.budget_no_auth else (args.provider_api_key or os.environ.get("SYNTHETIC_API_KEY", "")),
            timeout=args.timeout,
        )
        return research_provider_budget.synthetic_budget_status(
            payload,
            min_remaining_credits=args.min_remaining_credits,
            min_rolling_remaining=args.min_rolling_remaining,
            estimated_requests=max(1, int(args.estimated_requests)),
            reserve_requests=max(0, int(args.reserve_requests)),
        )

    return budget_checked_provider(call, budget_check=budget_check)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="candidate JSON file")
    parser.add_argument("--history-json", type=Path, help="optional prior successes/useful signals JSON")
    parser.add_argument("--output", type=Path, help="write synthesis report JSON")
    parser.add_argument("--emit-sql", type=Path, help="write SQL for synthesized candidate and branch deferral")
    parser.add_argument("--queue-synthesized", action="store_true")
    parser.add_argument("--requested-by", default="research_facility_synthesis")
    parser.add_argument("--provider-response-json", default="", help="test/offline provider response JSON")
    parser.add_argument("--provider-base-url", default=research_provider_generate.DEFAULT_OPENAI_BASE_URL)
    parser.add_argument("--provider-model", default=research_provider_generate.DEFAULT_MODEL)
    parser.add_argument("--provider-api-key", default="")
    parser.add_argument("--temperature", type=float, default=0.4)
    parser.add_argument("--max-tokens", type=int, default=6000)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--skip-budget-preflight", action="store_true")
    parser.add_argument("--budget-base-url", default=research_provider_budget.SYNTHETIC_BASE_URL)
    parser.add_argument("--budget-no-auth", action="store_true")
    parser.add_argument("--estimated-requests", type=int, default=1)
    parser.add_argument("--reserve-requests", type=int, default=2)
    parser.add_argument("--min-remaining-credits", type=float, default=5.0)
    parser.add_argument("--min-rolling-remaining", type=int, default=5)
    args = parser.parse_args(argv)

    candidates = research_facility.load_candidates(args.input)
    clusters = detect_candidate_clusters(candidates)
    history = research_facility.load_history(args.history_json)
    reflection_patterns = extract_reflection_patterns(history)
    report = synthesize_clusters(clusters, reflection_patterns=reflection_patterns, provider=_provider_from_args(args), requested_by=args.requested_by) if clusters else {
        "schema_version": "enoch_research_synthesis_report_v1",
        "ok": True,
        "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "requested_by": args.requested_by,
        "cluster_count": 0,
        "synthesized_count": 0,
        "clusters": [],
        "reflection_patterns": reflection_patterns,
        "synthesized_candidates": [],
        "failures": [],
        "prompts": [],
    }
    text = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    if args.emit_sql:
        args.emit_sql.write_text(emit_synthesis_sql(report, requested_by=args.requested_by, queue_synthesized=args.queue_synthesized), encoding="utf-8")
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
