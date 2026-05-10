#!/usr/bin/env python3
"""Scan grounded sources and emit Research Facility candidate batches.

This is a deterministic scout. It does not call LLM providers and does not write
to the database. It fetches or reads source records, hashes them, generates
bounded candidate specs, and writes JSON that can be passed to
`scripts/research_facility.py` for scoring/admission/SQL emission.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CATEGORY_TERMS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("long-context", ("long context", "retrieval", "memory", "mamba", "ssm", "state space", "ruler")),
    ("kv-compression", ("kv cache", "cache", "paged attention", "kivi", "attention")),
    ("spec-decoding", ("speculative", "draft", "eagle", "decoding", "inference")),
    ("quantization", ("quant", "bitnet", "bit", "ternary", "fp8", "int4", "int2")),
    ("home-training", ("qlora", "lora", "fine-tuning", "finetuning", "galore", "training")),
    ("distributed-training", ("distributed", "federated", "diloco", "volunteer", "decentralized")),
    ("agent-reliability", ("agent", "factual", "evidence", "benchmark", "verification", "swe-bench")),
)

MODE_BY_CATEGORY = {
    "long-context": "fresh_grounded",
    "kv-compression": "implementation_gap",
    "spec-decoding": "implementation_gap",
    "quantization": "home_hardware_accessibility",
    "home-training": "home_hardware_accessibility",
    "distributed-training": "moonshot",
    "agent-reliability": "implementation_gap",
}

DEFAULT_ARTIFACTS = ["run_notes.md", "metrics.json", "baseline_report.json", "failure_cases.json", ".enoch/project_decision.json"]
DEFAULT_EVIDENCE = ["source-grounded baseline", "metrics table", "ablation or control", "failure cases", "decision artifact"]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:96] or "source"


def sha256_text(value: str, length: int = 16) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


@dataclass
class SourceRecord:
    source_id: str
    source_kind: str
    title: str
    url: str
    external_id: str = ""
    retrieved_at: str = ""
    summary: str = ""
    payload_json: dict[str, Any] | None = None
    content_hash: str = ""

    @classmethod
    def from_parts(cls, *, source_kind: str, title: str, url: str, summary: str = "", external_id: str = "", payload_json: dict[str, Any] | None = None) -> "SourceRecord":
        title = clean_text(title)
        url = clean_text(url)
        summary = clean_text(summary)
        basis = "\n".join([source_kind, external_id, url, title, summary])
        return cls(
            source_id=f"{source_kind}-{sha256_text(external_id or url or title, 20)}",
            source_kind=source_kind,
            title=title,
            url=url,
            external_id=external_id,
            retrieved_at=utc_now(),
            summary=summary,
            payload_json=payload_json or {},
            content_hash=hashlib.sha256(basis.encode("utf-8")).hexdigest(),
        )


def fetch_text(url: str, *, timeout: int = 20) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "EnochResearchFacility/0.1 (+https://github.com/alias8818/enoch-agentic-research-system)"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def scan_arxiv(query: str, *, max_results: int, timeout: int) -> list[SourceRecord]:
    params = urllib.parse.urlencode(
        {
            "search_query": query,
            "start": 0,
            "max_results": max_results,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }
    )
    url = f"https://export.arxiv.org/api/query?{params}"
    xml_text = fetch_text(url, timeout=timeout)
    root = ET.fromstring(xml_text)
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    records: list[SourceRecord] = []
    for entry in root.findall("atom:entry", ns):
        title = clean_text(entry.findtext("atom:title", default="", namespaces=ns))
        summary = clean_text(entry.findtext("atom:summary", default="", namespaces=ns))
        entry_id = clean_text(entry.findtext("atom:id", default="", namespaces=ns))
        published = clean_text(entry.findtext("atom:published", default="", namespaces=ns))
        authors = [clean_text(author.findtext("atom:name", default="", namespaces=ns)) for author in entry.findall("atom:author", ns)]
        records.append(
            SourceRecord.from_parts(
                source_kind="arxiv",
                title=title,
                url=entry_id,
                external_id=entry_id.rsplit("/", 1)[-1],
                summary=summary,
                payload_json={"published": published, "authors": [a for a in authors if a], "query": query},
            )
        )
    return records


def load_source_json(path: Path) -> list[SourceRecord]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("sources") or data.get("records") or [data]
    records = []
    for item in data:
        if not isinstance(item, dict):
            continue
        if item.get("source_id") and item.get("source_kind"):
            records.append(SourceRecord(**{**item, "payload_json": item.get("payload_json") or {}}))
        else:
            records.append(
                SourceRecord.from_parts(
                    source_kind=str(item.get("source_kind") or "manual_note"),
                    title=str(item.get("title") or item.get("name") or "Untitled source"),
                    url=str(item.get("url") or item.get("source_external_url") or ""),
                    external_id=str(item.get("external_id") or ""),
                    summary=str(item.get("summary") or item.get("description") or ""),
                    payload_json=item,
                )
            )
    return records


def classify_category(text: str) -> str:
    lower = text.lower()
    weighted_scores: dict[str, int] = {}
    for category, terms in CATEGORY_TERMS:
        score = 0
        for term in terms:
            if term in lower:
                # Multi-word/domain-specific terms are stronger than broad words
                # such as memory, cache, or attention.
                score += 3 if " " in term or term in {"speculative", "qlora", "bitnet", "diloco"} else 1
        weighted_scores[category] = score
    best, score = max(weighted_scores.items(), key=lambda item: item[1])
    return best if score > 0 else "systems-research"


def score_from_source(source: SourceRecord, category: str) -> tuple[float, float, float, float]:
    text = f"{source.title} {source.summary}".lower()
    novelty = 7.0
    feasibility = 6.0
    accessibility = 6.0
    falsifiability = 7.0
    if category in {"spec-decoding", "kv-compression", "quantization"}:
        feasibility += 1.0
        accessibility += 1.0
    if category in {"long-context", "distributed-training"}:
        novelty += 1.0
    if any(term in text for term in ("benchmark", "evaluation", "dataset", "ruler", "swe-bench")):
        falsifiability += 1.0
    if any(term in text for term in ("efficient", "local", "memory", "compression", "low-bit", "throughput")):
        accessibility += 1.0
    return tuple(min(10.0, value) for value in (novelty, feasibility, accessibility, falsifiability))


def candidate_from_source(source: SourceRecord, *, default_machine: str, default_model: str, default_sandbox: str) -> dict[str, Any]:
    source_text = f"{source.title}. {source.summary}"
    category = classify_category(source_text)
    mode = MODE_BY_CATEGORY.get(category, "fresh_grounded")
    novelty, feasibility, accessibility, falsifiability = score_from_source(source, category)
    short_summary = source.summary[:700]
    title_slug = slugify(source.title)
    candidate_title = f"Local Probe: {source.title[:90]}" if not source.title.lower().startswith("local probe") else source.title
    baseline = {
        "long-context": "Vector RAG, sliding-window context, and periodic exact-anchor baselines at the same memory budget.",
        "kv-compression": "Uniform FP8/int4 KV cache compression and recency-only cache eviction at the same memory budget.",
        "spec-decoding": "No speculation plus fixed n-gram/suffix speculative decoding on the same local serving stack.",
        "quantization": "Naive ternary/2-bit quantization and int4 GPTQ/AWQ-style baselines at comparable memory.",
        "home-training": "Fixed QLoRA/LoRA recipe with manually tuned batch size and checkpointing.",
        "distributed-training": "FedAvg or DiLoCo-style unchecked local worker aggregation under the same simulated worker budget.",
        "agent-reliability": "Vanilla agent run and self-critique-only baseline on the same task set.",
    }.get(category, "The simplest direct implementation and the strongest existing local baseline identified during setup.")
    mechanism = {
        "long-context": "Convert the source mechanism into a bounded local memory wrapper and test whether exact anchors plus compressed state improve retrieval/reasoning beyond RAG.",
        "kv-compression": "Use the source mechanism to derive a mixed cache policy, then measure quality and latency against uniform compression.",
        "spec-decoding": "Translate the source into a non-LM or low-overhead drafting policy and gate drafts by measured acceptance cost.",
        "quantization": "Adapt the source idea into a post-training or light-tuning compression probe with explicit residual/critical-subspace ablations.",
        "home-training": "Turn the source into a scheduler or memory-planning probe for small-VRAM fine-tuning under a hard resource cap.",
        "distributed-training": "Simulate local workers and inject stale/random/poisoned updates to test whether the source mechanism survives adversarial or unreliable peers.",
        "agent-reliability": "Wrap the source idea in an evidence-ledger harness that measures unsupported claims and reproducibility against a baseline agent.",
    }.get(category, "Extract one practical local variant from the source and compare it against the simplest baseline with bounded metrics.")
    return {
        "candidate_id": f"{title_slug}-{sha256_text(source.content_hash, 10)}",
        "generation_mode": mode,
        "title": candidate_title,
        "category": category,
        "priority": "High" if novelty + accessibility >= 15 else "Medium",
        "source_kind": source.source_kind,
        "source_ids": [source.source_id],
        "source_urls": [source.url] if source.url else [],
        "source_records": [asdict(source)],
        "hypothesis": f"A practical local variant inspired by `{source.title}` can beat a simple baseline on {category} metrics without exceeding the home-hardware budget.",
        "mechanism": mechanism,
        "description": f"Grounded source summary: {short_summary}",
        "implementation": "Create a bounded prototype and fixture-driven benchmark first; run the strongest simple baseline; log metrics, ablations, failure cases, and a decision artifact. Keep the experiment small enough to finish on the configured worker before scaling.",
        "baseline_to_beat": baseline,
        "success_threshold": "Admit as positive only if the prototype beats the named baseline on the primary metric while staying within the declared memory/runtime budget and preserving correctness on failure-case probes.",
        "kill_condition": "Stop/no-paper if gains only appear on toy cases, require larger hardware than the configured worker, lack a baseline win, or cannot produce inspectable metrics and failure cases.",
        "accessibility_delta": "The candidate must improve local/home AI viability: lower VRAM/RAM, lower latency, cheaper fine-tuning, longer usable context, or more reliable small-agent operation.",
        "expected_artifacts": DEFAULT_ARTIFACTS,
        "required_evidence": DEFAULT_EVIDENCE,
        "estimated_runtime_class": "medium",
        "expected_token_budget": "medium",
        "machine_target": default_machine,
        "model": default_model,
        "sandbox": default_sandbox,
        "likely_failure_modes": [
            "Source result does not transfer to the local/hardware-bounded variant.",
            "Baseline was underpowered or unfairly configured.",
            "Measured improvement is too small or too narrow to matter.",
        ],
        "novelty_score": novelty,
        "feasibility_score": feasibility,
        "accessibility_score": accessibility,
        "falsifiability_score": falsifiability,
        "novelty_comparison": "Generated from a newly scanned source; compare dedupe_key and source mechanism against prior Enoch runs before queue promotion.",
        "risk_notes": "Heuristic deterministic candidate. A provider-backed generator may rewrite this into a sharper proposal, but source grounding and baseline/kill gates are already explicit.",
        "provider": "deterministic_source_scanner",
        "provider_model": "none",
        "prompt_version": "research_facility_scan_v1",
        "generated_by": "scripts/research_facility_scan.py",
        "raw_candidate_json": {"source": asdict(source), "category": category, "mode": mode},
    }


def write_outputs(records: list[SourceRecord], candidates: list[dict[str, Any]], output: Path, *, errors: list[dict[str, str]] | None = None) -> None:
    payload = {
        "ok": not errors,
        "generated_at": utc_now(),
        "source_count": len(records),
        "candidate_count": len(candidates),
        "errors": errors or [],
        "sources": [asdict(record) for record in records],
        "candidates": candidates,
    }
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arxiv-query", action="append", default=[], help="arXiv API query, e.g. cat:cs.LG AND all:speculative decoding")
    parser.add_argument("--source-json", action="append", type=Path, default=[], help="JSON file with source records to convert")
    parser.add_argument("--max-results", type=int, default=5)
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--strict-fetch", action="store_true", help="fail instead of recording scanner errors when a remote source fetch fails")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--default-machine", default="gb10")
    parser.add_argument("--default-model", default="gpt-5.5")
    parser.add_argument("--default-sandbox", default="danger-full-access")
    args = parser.parse_args(argv)

    records: list[SourceRecord] = []
    errors: list[dict[str, str]] = []
    for path in args.source_json:
        try:
            records.extend(load_source_json(path))
        except Exception as exc:  # noqa: BLE001 - scanner should preserve per-source failure evidence
            if args.strict_fetch:
                raise
            errors.append({"source": str(path), "error": str(exc)})
    for query in args.arxiv_query:
        try:
            records.extend(scan_arxiv(query, max_results=max(1, min(args.max_results, 50)), timeout=args.timeout))
        except Exception as exc:  # noqa: BLE001 - remote scanners can hit rate limits/timeouts
            if args.strict_fetch:
                raise
            errors.append({"source": f"arxiv:{query}", "error": str(exc)})
    unique: dict[str, SourceRecord] = {record.source_id: record for record in records}
    records = list(unique.values())
    candidates = [
        candidate_from_source(
            record,
            default_machine=args.default_machine,
            default_model=args.default_model,
            default_sandbox=args.default_sandbox,
        )
        for record in records
    ]
    write_outputs(records, candidates, args.output, errors=errors)
    print(json.dumps({"ok": not errors, "output": str(args.output), "source_count": len(records), "candidate_count": len(candidates), "error_count": len(errors)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
