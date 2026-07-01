#!/usr/bin/env python3
"""Build an Enoch paper-material graph from public paper and signal artifacts.

The graph is deliberately file-based and inspectable. It is a first slice of the
"memory for better papers" system: papers, promising/scale-blocked signals,
sources, and topic-similarity edges are exported as stable JSON plus a readable
Markdown summary.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

GRAPH_SCHEMA_VERSION = "enoch_paper_material_graph_v1"
PRIVATE_PATH_ROOTS = (
    "/var/lib/enoch-control-plane",
    "/opt/enoch-control-plane",
    "/home/jeremy",
    "/root",
    "/mnt/usb",
)
PRIVATE_IPV4 = re.compile(
    r"\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}|127\.\d{1,3}\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[0-1])\.\d{1,3}\.\d{1,3})\b"
)
LOCAL_ONLY_PUBLIC_TEXT = (
    "Local-only operational evidence is omitted from the public graph."
)
MAX_SIMILAR_TERM_POSTINGS = 128
STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "without",
    "from",
    "that",
    "this",
    "into",
    "onto",
    "over",
    "under",
    "via",
    "using",
    "use",
    "uses",
    "agent",
    "agents",
    "all",
    "also",
    "been",
    "being",
    "can",
    "could",
    "did",
    "does",
    "false",
    "had",
    "has",
    "have",
    "local",
    "log",
    "logs",
    "mean",
    "not",
    "paper",
    "papers",
    "produced",
    "public",
    "result",
    "results",
    "show",
    "showed",
    "shown",
    "than",
    "then",
    "there",
    "these",
    "those",
    "was",
    "were",
    "while",
    "fixed",
    "same",
    "used",
    "within",
    "benchmark",
    "validation",
    "test",
    "tests",
    "study",
    "pilot",
    "evidence",
    "enoch",
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _safe_text(value: Any) -> str:
    text = _text(value)
    for root in PRIVATE_PATH_ROOTS:
        text = text.replace(root, "<local-path>")
    text = PRIVATE_IPV4.sub("<private-ip>", text)
    return text


def _is_local_only_signal(record: dict[str, Any]) -> bool:
    evidence_value = record.get("evidence")
    evidence = evidence_value if isinstance(evidence_value, dict) else {}
    return (
        evidence.get("local_only") is True
        and evidence.get("public_evidence_copied") is False
    )


def _public_signal_text(record: dict[str, Any], key: str) -> str:
    if _is_local_only_signal(record):
        return LOCAL_ONLY_PUBLIC_TEXT
    return _safe_text(record.get(key))


def _is_safe_existing_child(root: Path, path: Path) -> bool:
    if path.is_symlink():
        return False
    try:
        path.resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        return False
    return True


def _reject_existing_symlink_components(path: Path) -> None:
    for candidate in (path, *path.parents):
        if candidate.is_symlink():
            raise OSError(f"refusing to write through symlinked path: {candidate}")
        if candidate.exists():
            continue


def _candidate_slug(signal_id: Any, title: Any) -> str:
    seed = _text(signal_id).removeprefix("signal:") or _text(title) or "candidate"
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", seed.lower()).strip("-")
    return slug[:96] or "candidate"


def _read_json(path: Path, *, root: Path | None = None) -> dict[str, Any]:
    if root is not None and not _is_safe_existing_child(root, path):
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _first_markdown_heading(path: Path, *, root: Path | None = None) -> str:
    if root is not None and not _is_safe_existing_child(root, path):
        return ""
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("# "):
                return line[2:].strip()
    except OSError:
        return ""
    return ""


def _markdown_excerpt(
    path: Path, max_chars: int = 900, *, root: Path | None = None
) -> str:
    if root is not None and not _is_safe_existing_child(root, path):
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    text = re.sub(r"\s+", " ", text).strip()
    return _safe_text(text[:max_chars])


def _tokens(*parts: Any) -> list[str]:
    seen: set[str] = set()
    tokens: list[str] = []
    text = " ".join(_text(part) for part in parts)
    for token in re.findall(r"[a-zA-Z][a-zA-Z0-9+-]{2,}", text.lower()):
        token = token.strip("-+")
        if len(token) < 3 or token in STOPWORDS or token in seen:
            continue
        seen.add(token)
        tokens.append(token)
    return tokens


def _source_id(url: str) -> str:
    return f"source:{url}"


def _paper_node(paper_dir: Path) -> dict[str, Any] | None:
    papers_root = paper_dir.parent
    if not _is_safe_existing_child(papers_root, paper_dir):
        return None
    paper_md = paper_dir / "paper.md"
    if not paper_md.exists() or not _is_safe_existing_child(papers_root, paper_md):
        return None
    manifest = _read_json(paper_dir / "paper_manifest.json", root=papers_root)
    title = (
        _first_markdown_heading(paper_md, root=papers_root)
        or paper_dir.name.replace("-", " ").title()
    )
    excerpt = _markdown_excerpt(paper_md, root=papers_root)
    return {
        "id": f"paper:{paper_dir.name}",
        "kind": "paper",
        "slug": paper_dir.name,
        "title": _safe_text(title),
        "status": "published",
        "outcome": "paper_positive",
        "paper_id": _safe_text(manifest.get("paper_id")),
        "generated_at": _safe_text(manifest.get("generated_at")),
        "writer_provider": manifest.get("writer_provider") or {},
        "path": _safe_text(str(paper_dir.relative_to(paper_dir.parents[1]))),
        "summary_text": excerpt,
        "terms": _tokens(title, excerpt),
    }


def load_paper_nodes(corpus_repo: Path) -> list[dict[str, Any]]:
    papers_root = corpus_repo / "papers"
    if not papers_root.exists():
        return []
    nodes = [
        _paper_node(path) for path in sorted(papers_root.iterdir()) if path.is_dir()
    ]
    return [node for node in nodes if node is not None]


def _load_signal_records(promising_repo: Path) -> list[dict[str, Any]]:
    data_path = promising_repo / "data" / "signals.jsonl"
    if not data_path.exists() or not _is_safe_existing_child(promising_repo, data_path):
        return []
    records: list[dict[str, Any]] = []
    for line in data_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict):
            records.append(value)
    return records


def _signal_node(record: dict[str, Any]) -> dict[str, Any]:
    project_id = _safe_text(record.get("project_id"))
    title = _safe_text(record.get("title")) or project_id
    claim_scope = _public_signal_text(record, "claim_scope")
    useful_summary = _public_signal_text(record, "useful_signal_summary")
    return {
        "id": f"signal:{project_id}",
        "kind": "signal",
        "project_id": project_id,
        "run_id": _safe_text(record.get("run_id")),
        "title": title,
        "status": _safe_text(record.get("status")),
        "outcome": _safe_text(record.get("status")),
        "hypothesis_status": _safe_text(record.get("hypothesis_status")),
        "evidence_strength": _safe_text(record.get("evidence_strength")),
        "claim_scope": claim_scope,
        "scale_limits": _public_signal_text(record, "scale_limits"),
        "useful_signal_summary": useful_summary,
        "curation": record.get("curation") or {},
        "followup": record.get("followup") or {},
        "evidence": _safe_json(record.get("evidence") or {}),
        "sources": _safe_json(record.get("sources") or []),
        "updated_at": _safe_text(record.get("updated_at")),
        "terms": _tokens(title, claim_scope, useful_summary),
    }


def _safe_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _safe_json(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_safe_json(v) for v in value]
    if isinstance(value, str):
        return _safe_text(value)
    return value


def load_signal_nodes(promising_repo: Path) -> list[dict[str, Any]]:
    return [_signal_node(record) for record in _load_signal_records(promising_repo)]


def _edge(source: str, target: str, kind: str, **attrs: Any) -> dict[str, Any]:
    if source > target and kind in {"similar_topic", "same_project"}:
        source, target = target, source
    return {"source": source, "target": target, "kind": kind, **attrs}


def _source_edges_and_nodes(
    nodes: Iterable[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    source_nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    for node in nodes:
        for source in node.get("sources") or []:
            if not isinstance(source, dict):
                continue
            url = _safe_text(source.get("url"))
            source_key = url or _safe_text(source.get("source_id"))
            if not source_key:
                continue
            source_id = _source_id(source_key)
            source_nodes.setdefault(
                source_id,
                {
                    "id": source_id,
                    "kind": "source",
                    "title": _safe_text(source.get("title")) or source_key,
                    "url": url,
                    "source_id": _safe_text(source.get("source_id")),
                    "terms": _tokens(source.get("title"), source_key),
                },
            )
            edges.append(
                _edge(
                    node["id"],
                    source_id,
                    "cites_source",
                    weight=1.0,
                    reason="signal source lineage",
                )
            )
    return list(source_nodes.values()), edges


def _similar_topic_edge_candidates(
    nodes: list[dict[str, Any]], *, min_shared_terms: int
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    comparable = [node for node in nodes if node.get("kind") in {"paper", "signal"}]
    term_index: dict[str, list[int]] = defaultdict(list)
    for index, node in enumerate(comparable):
        for term in sorted(set(node.get("terms") or [])):
            term_index[term].append(index)

    # The production graph now includes thousands of promising signals.  The
    # original all-pairs comparison was O(n^2) and could outlive the corpus
    # autopilot systemd timeout.  Build candidate pairs through the inverted
    # index instead, and ignore extremely broad terms that cannot produce useful
    # local-neighborhood edges but can create millions of pair increments.
    pair_shared_counts: Counter[tuple[int, int]] = Counter()
    for postings in term_index.values():
        if len(postings) < 2 or len(postings) > MAX_SIMILAR_TERM_POSTINGS:
            continue
        for left_offset, left_index in enumerate(postings):
            for right_index in postings[left_offset + 1 :]:
                pair_shared_counts[(left_index, right_index)] += 1

    for (left_index, right_index), shared_count in pair_shared_counts.items():
        if shared_count < min_shared_terms:
            continue
        left = comparable[left_index]
        right = comparable[right_index]
        candidate = _similar_topic_edge_candidate(
            left,
            right,
            left_terms=set(left.get("terms") or []),
            min_shared_terms=min_shared_terms,
        )
        if candidate is not None:
            candidates.append(candidate)
    return candidates


def _similar_topic_edge_candidate(
    left: dict[str, Any],
    right: dict[str, Any],
    *,
    left_terms: set[str],
    min_shared_terms: int,
) -> dict[str, Any] | None:
    right_terms = set(right.get("terms") or [])
    shared = sorted(left_terms & right_terms)
    if len(shared) < min_shared_terms:
        return None
    # Prefer cross-outcome paper/signal edges, but keep strong same-kind clusters too.
    if left.get("kind") == right.get("kind") and len(shared) < min_shared_terms + 1:
        return None
    weight = round(len(shared) / max(len(left_terms | right_terms), 1), 4)
    return _edge(
        left["id"],
        right["id"],
        "similar_topic",
        weight=weight,
        shared_terms=shared[:12],
        shared_term_count=len(shared),
    )


def _sorted_similar_topic_edges(edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        edges,
        key=lambda edge: (
            -float(edge.get("weight") or 0),
            -int(edge.get("shared_term_count") or 0),
            edge["source"],
            edge["target"],
        ),
    )


def _bounded_similar_topic_edges(
    candidates: list[dict[str, Any]], *, max_similar_per_node: int
) -> list[dict[str, Any]]:
    if max_similar_per_node <= 0:
        return candidates
    degree: Counter[str] = Counter()
    kept: list[dict[str, Any]] = []
    for edge in candidates:
        if _similar_topic_edge_exceeds_degree(
            edge, degree, max_similar_per_node=max_similar_per_node
        ):
            continue
        kept.append(edge)
        degree[edge["source"]] += 1
        degree[edge["target"]] += 1
    return kept


def _similar_topic_edge_exceeds_degree(
    edge: dict[str, Any], degree: Counter[str], *, max_similar_per_node: int
) -> bool:
    return (
        degree[edge["source"]] >= max_similar_per_node
        or degree[edge["target"]] >= max_similar_per_node
    )


def _similar_topic_edges(
    nodes: list[dict[str, Any]], *, min_shared_terms: int, max_similar_per_node: int
) -> list[dict[str, Any]]:
    candidates = _similar_topic_edge_candidates(
        nodes, min_shared_terms=min_shared_terms
    )
    candidates = _sorted_similar_topic_edges(candidates)
    return _bounded_similar_topic_edges(
        candidates, max_similar_per_node=max_similar_per_node
    )


def _same_project_edges(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_project: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for node in nodes:
        project = node.get("project_id") or node.get("slug")
        if project:
            by_project[str(project)].append(node)
    edges: list[dict[str, Any]] = []
    for project_nodes in by_project.values():
        if len(project_nodes) < 2:
            continue
        for index, left in enumerate(project_nodes):
            for right in project_nodes[index + 1 :]:
                edges.append(_edge(left["id"], right["id"], "same_project", weight=1.0))
    return edges


def _dedupe_edges(edges: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[tuple[str, str, str], dict[str, Any]] = {}
    for edge in edges:
        key = (edge["source"], edge["target"], edge["kind"])
        previous = deduped.get(key)
        if previous is None or float(edge.get("weight") or 0) > float(
            previous.get("weight") or 0
        ):
            deduped[key] = edge
    return sorted(deduped.values(), key=lambda e: (e["kind"], e["source"], e["target"]))


def _component_adjacency(
    nodes: list[dict[str, Any]], edges: list[dict[str, Any]]
) -> dict[str, set[str]]:
    adjacency: dict[str, set[str]] = {node["id"]: set() for node in nodes}
    for edge in edges:
        adjacency.setdefault(edge["source"], set()).add(edge["target"])
        adjacency.setdefault(edge["target"], set()).add(edge["source"])
    return adjacency


def _component_members(
    start_node_id: str, adjacency: dict[str, set[str]], seen: set[str]
) -> list[str]:
    stack = [start_node_id]
    members: list[str] = []
    seen.add(start_node_id)
    while stack:
        current = stack.pop()
        members.append(current)
        for neighbor in sorted(adjacency.get(current, set())):
            if neighbor not in seen:
                seen.add(neighbor)
                stack.append(neighbor)
    return members


def _connected_component_summary(
    members: list[str], node_by_id: dict[str, dict[str, Any]], *, component_index: int
) -> dict[str, Any] | None:
    if len(members) <= 1:
        return None
    kind_counts = Counter(
        node_by_id.get(member, {}).get("kind", "unknown") for member in members
    )
    return {
        "id": f"component:{component_index}",
        "size": len(members),
        "kind_counts": dict(sorted(kind_counts.items())),
        "sample_member_ids": sorted(members)[:25],
        "sample_titles": _connected_component_sample_titles(members, node_by_id),
    }


def _connected_component_sample_titles(
    members: list[str], node_by_id: dict[str, dict[str, Any]]
) -> list[str]:
    return [
        node_by_id[member].get("title", member)
        for member in sorted(members)
        if member in node_by_id and node_by_id[member].get("kind") != "source"
    ][:8]


def _connected_components(
    nodes: list[dict[str, Any]], edges: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    adjacency = _component_adjacency(nodes, edges)
    seen: set[str] = set()
    components: list[dict[str, Any]] = []
    node_by_id = {node["id"]: node for node in nodes}
    for node_id in sorted(adjacency):
        if node_id in seen:
            continue
        members = _component_members(node_id, adjacency, seen)
        summary = _connected_component_summary(
            members, node_by_id, component_index=len(components) + 1
        )
        if summary is not None:
            components.append(summary)
    components.sort(key=lambda item: (-item["size"], item["id"]))
    return components


def _synthesis_related_material(
    nodes: list[dict[str, Any]], edges: list[dict[str, Any]]
) -> tuple[dict[str, dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    node_by_id = {node["id"]: node for node in nodes}
    related: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for edge in edges:
        if edge.get("kind") not in {"similar_topic", "cites_source"}:
            continue
        _record_synthesis_edge_material(edge, node_by_id, related)
    return node_by_id, related


def _record_synthesis_edge_material(
    edge: dict[str, Any],
    node_by_id: dict[str, dict[str, Any]],
    related: dict[str, list[dict[str, Any]]],
) -> None:
    for source_id, target_id in (
        (edge["source"], edge["target"]),
        (edge["target"], edge["source"]),
    ):
        source = node_by_id.get(source_id)
        target = node_by_id.get(target_id)
        if source and target and source.get("kind") == "signal":
            related[source_id].append({"edge": edge, "node": target})


def _synthesis_candidate_from_related(
    signal_id: str, signal: dict[str, Any], items: list[dict[str, Any]]
) -> dict[str, Any] | None:
    related_papers = [item for item in items if item["node"].get("kind") == "paper"]
    if not related_papers:
        return None
    related_sources = [item for item in items if item["node"].get("kind") == "source"]
    status = _text(signal.get("status"))
    curation_obj = signal.get("curation")
    curation: dict[str, Any] = curation_obj if isinstance(curation_obj, dict) else {}
    followup_obj = signal.get("followup")
    followup: dict[str, Any] = followup_obj if isinstance(followup_obj, dict) else {}
    return {
        "signal_id": signal_id,
        "packet_path": f"candidates/synthesis/{_candidate_slug(signal_id, signal.get('title', ''))}.md",
        "title": signal.get("title", ""),
        "status": status,
        "score": _synthesis_candidate_score(
            status, curation, related_papers, related_sources
        ),
        "curation_score": int(curation.get("score") or 0),
        "related_paper_count": len(related_papers),
        "related_source_count": len(related_sources),
        "related_papers": _synthesis_candidate_paper_rows(related_papers),
        "sources": _synthesis_candidate_source_rows(related_sources),
        "recommended_next_action": followup.get("title", ""),
    }


def _synthesis_candidate_score(
    status: str,
    curation: dict[str, Any],
    related_papers: list[dict[str, Any]],
    related_sources: list[dict[str, Any]],
) -> int:
    score = int(curation.get("score") or 0)
    score += 10 if status == "compute_scale_blocked" else 0
    score += min(len(related_papers), 5) * 5
    score += min(len(related_sources), 3) * 2
    return score


def _synthesis_candidate_paper_rows(
    related_papers: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    paper_rows = sorted(
        related_papers,
        key=lambda item: (
            -float(item["edge"].get("weight") or 0),
            item["node"].get("title", ""),
        ),
    )[:8]
    return [
        {
            "id": item["node"]["id"],
            "title": item["node"].get("title", ""),
            "weight": item["edge"].get("weight"),
            "shared_terms": item["edge"].get("shared_terms", []),
        }
        for item in paper_rows
    ]


def _synthesis_candidate_source_rows(
    related_sources: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    source_rows = sorted(
        related_sources, key=lambda item: item["node"].get("title", "")
    )[:5]
    return [
        {
            "id": item["node"]["id"],
            "title": item["node"].get("title", ""),
            "url": item["node"].get("url", ""),
        }
        for item in source_rows
    ]


def _synthesis_candidates(
    nodes: list[dict[str, Any]], edges: list[dict[str, Any]], *, limit: int = 25
) -> list[dict[str, Any]]:
    node_by_id, related = _synthesis_related_material(nodes, edges)
    candidates: list[dict[str, Any]] = []
    for signal_id, items in related.items():
        signal = node_by_id.get(signal_id)
        if signal is None:
            continue
        candidate = _synthesis_candidate_from_related(signal_id, signal, items)
        if candidate is not None:
            candidates.append(candidate)
    candidates.sort(
        key=lambda item: (-int(item["score"]), item["title"], item["signal_id"])
    )
    return candidates[:limit]


def _negative_result_candidates(
    nodes: list[dict[str, Any]], *, limit: int = 25
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for node in nodes:
        if node.get("kind") != "signal":
            continue
        status = _text(node.get("status"))
        if status not in {
            "compute_scale_blocked",
            "complete_no_paper",
            "failed",
            "needs_attention",
        }:
            continue
        curation_obj = node.get("curation")
        curation = curation_obj if isinstance(curation_obj, dict) else {}
        followup_obj = node.get("followup")
        followup = followup_obj if isinstance(followup_obj, dict) else {}
        candidates.append(
            {
                "signal_id": node["id"],
                "packet_path": f"candidates/negative/{_candidate_slug(node['id'], node.get('title', ''))}.md",
                "title": node.get("title", ""),
                "status": status,
                "score": int(curation.get("score") or 0),
                "hypothesis_status": node.get("hypothesis_status", ""),
                "evidence_strength": node.get("evidence_strength", ""),
                "claim_scope": node.get("claim_scope", ""),
                "scale_limits": node.get("scale_limits", ""),
                "recommended_next_action": followup.get("title", ""),
            }
        )
    candidates.sort(
        key=lambda item: (-int(item["score"]), item["title"], item["signal_id"])
    )
    return candidates[:limit]


def _summary(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    components: list[dict[str, Any]],
) -> dict[str, Any]:
    node_counts = Counter(node.get("kind", "unknown") for node in nodes)
    edge_counts = Counter(edge.get("kind", "unknown") for edge in edges)
    status_counts = Counter(
        str(node.get("status") or "") for node in nodes if node.get("kind") == "signal"
    )
    return {
        "paper_count": node_counts.get("paper", 0),
        "signal_count": node_counts.get("signal", 0),
        "source_count": node_counts.get("source", 0),
        "edge_count": len(edges),
        "similar_topic_edges": edge_counts.get("similar_topic", 0),
        "node_counts": dict(sorted(node_counts.items())),
        "edge_counts": dict(sorted(edge_counts.items())),
        "signal_status_counts": {
            k: status_counts[k] for k in sorted(status_counts) if k
        },
        "connected_component_count": len(components),
        "largest_components": components[:10],
        "synthesis_candidates": _synthesis_candidates(nodes, edges),
        "negative_result_candidates": _negative_result_candidates(nodes),
    }


def build_graph(
    *,
    corpus_repo: Path,
    promising_repo: Path,
    min_shared_terms: int = 2,
    max_similar_per_node: int = 12,
) -> dict[str, Any]:
    paper_nodes = load_paper_nodes(corpus_repo)
    signal_nodes = load_signal_nodes(promising_repo)
    source_nodes, source_edges = _source_edges_and_nodes(signal_nodes)
    base_nodes = paper_nodes + signal_nodes + source_nodes
    edges = _dedupe_edges(
        [
            *source_edges,
            *_same_project_edges(base_nodes),
            *_similar_topic_edges(
                base_nodes,
                min_shared_terms=min_shared_terms,
                max_similar_per_node=max_similar_per_node,
            ),
        ]
    )
    components = _connected_components(base_nodes, edges)
    graph = {
        "schema_version": GRAPH_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "inputs": {
            "corpus_repo": _safe_text(str(corpus_repo)),
            "promising_repo": _safe_text(str(promising_repo)),
            "min_shared_terms": min_shared_terms,
            "max_similar_per_node": max_similar_per_node,
        },
        "summary": _summary(base_nodes, edges, components),
        "nodes": sorted(
            base_nodes, key=lambda node: (node.get("kind", ""), node.get("id", ""))
        ),
        "edges": edges,
        "components": components,
    }
    return _safe_json(graph)


def _markdown_header_lines(graph: dict[str, Any]) -> list[str]:
    return [
        "# Enoch Paper Material Graph",
        "",
        f"Generated: `{graph.get('generated_at')}`",
        "",
        "Runtime context: see [current-runtime-snapshot.md](../current-runtime-snapshot.md) for live topology referenced by candidate material.",
        "",
        "## Summary",
        "",
    ]


def _markdown_summary_lines(summary: dict[str, Any]) -> list[str]:
    return [
        f"- Papers: {summary.get('paper_count', 0)}",
        f"- Signals: {summary.get('signal_count', 0)}",
        f"- Sources: {summary.get('source_count', 0)}",
        f"- Edges: {summary.get('edge_count', 0)}",
        f"- Similar-topic edges: {summary.get('similar_topic_edges', 0)}",
        f"- Connected components: {summary.get('connected_component_count', 0)}",
        "",
        "## Signal statuses",
        "",
    ]


def _markdown_signal_status_lines(summary: dict[str, Any]) -> list[str]:
    return [
        f"- `{status}`: {count}"
        for status, count in (summary.get("signal_status_counts") or {}).items()
    ]


def _markdown_synthesis_candidate_lines(candidate: dict[str, Any]) -> list[str]:
    lines = [
        f"### {candidate.get('title')} — score {candidate.get('score')} (`{candidate.get('status')}`)",
        f"- Signal: `{candidate.get('signal_id')}`",
    ]
    if candidate.get("packet_path"):
        lines.append(
            f"- Packet: [{candidate.get('packet_path')}]({candidate.get('packet_path')})"
        )
    lines.append(f"- Related papers: {candidate.get('related_paper_count', 0)}")
    if candidate.get("recommended_next_action"):
        lines.append(f"- Next action: {candidate.get('recommended_next_action')}")
    for paper in candidate.get("related_papers") or []:
        terms = ", ".join(paper.get("shared_terms") or [])
        lines.append(f"  - {paper.get('title')} — shared: {terms}")
    lines.append("")
    return lines


def _markdown_negative_candidate_lines(candidate: dict[str, Any]) -> list[str]:
    lines = [
        f"### {candidate.get('title')} — score {candidate.get('score')} (`{candidate.get('status')}`)",
        f"- Signal: `{candidate.get('signal_id')}`",
    ]
    if candidate.get("packet_path"):
        lines.append(
            f"- Packet: [{candidate.get('packet_path')}]({candidate.get('packet_path')})"
        )
    for key, label in (
        ("scale_limits", "Scale limits"),
        ("claim_scope", "Claim scope"),
        ("recommended_next_action", "Next action"),
    ):
        if candidate.get(key):
            lines.append(f"- {label}: {candidate.get(key)}")
    lines.append("")
    return lines


def _markdown_component_lines(component: dict[str, Any]) -> list[str]:
    lines = [
        f"### {component.get('id')} — {component.get('size')} nodes {component.get('kind_counts')}"
    ]
    lines.extend(f"- {title}" for title in component.get("sample_titles") or [])
    lines.append("")
    return lines


def _markdown_how_to_use_lines() -> list[str]:
    return [
        "## How to use this",
        "",
        "Use high-signal mixed components as paper-material candidates: a good component links prior public papers, useful/scale-blocked signals, source lineage, and repeated methods. The next layer should score these components for synthesis and queue bounded follow-up experiments that can turn weak individual runs into stronger paper-positive material.",
        "",
        "For live operations, timer checks, and artifact locations, see [Paper Material Graph Operations](operations.md).",
        "",
    ]


def _markdown(graph: dict[str, Any]) -> str:
    summary = graph.get("summary") or {}
    lines = _markdown_header_lines(graph)
    lines.extend(_markdown_summary_lines(summary))
    lines.extend(_markdown_signal_status_lines(summary))
    lines.extend(["", "## Top synthesis candidates", ""])
    for candidate in summary.get("synthesis_candidates") or []:
        lines.extend(_markdown_synthesis_candidate_lines(candidate))
    lines.extend(["", "## Negative / blocked result candidates", ""])
    for candidate in summary.get("negative_result_candidates") or []:
        lines.extend(_markdown_negative_candidate_lines(candidate))
    lines.extend(["", "## Largest components", ""])
    for component in summary.get("largest_components") or []:
        lines.extend(_markdown_component_lines(component))
    lines.extend([""])
    lines.extend(_markdown_how_to_use_lines())
    return "\n".join(lines)


def _log_summary(graph: dict[str, Any]) -> dict[str, Any]:
    summary = graph["summary"]
    return {
        "ok": True,
        "paper_count": summary.get("paper_count", 0),
        "signal_count": summary.get("signal_count", 0),
        "source_count": summary.get("source_count", 0),
        "edge_count": summary.get("edge_count", 0),
        "similar_topic_edges": summary.get("similar_topic_edges", 0),
        "connected_component_count": summary.get("connected_component_count", 0),
        "signal_status_counts": summary.get("signal_status_counts", {}),
        "synthesis_candidate_count": len(summary.get("synthesis_candidates") or []),
        "negative_result_candidate_count": len(
            summary.get("negative_result_candidates") or []
        ),
        "top_synthesis_titles": [
            candidate.get("title", "")
            for candidate in (summary.get("synthesis_candidates") or [])[:5]
        ],
        "top_negative_titles": [
            candidate.get("title", "")
            for candidate in (summary.get("negative_result_candidates") or [])[:5]
        ],
    }


def _candidate_packet_header_lines(
    candidate: dict[str, Any], *, kind: str, graph: dict[str, Any]
) -> list[str]:
    return [
        f"# {candidate.get('title') or 'Untitled candidate'}",
        "",
        f"Generated from graph: `{graph.get('generated_at')}`",
        "Runtime context: see [current-runtime-snapshot.md](../../current-runtime-snapshot.md) for live topology referenced by this packet.",
        f"Candidate kind: `{kind}`",
        f"Signal: `{candidate.get('signal_id')}`",
        f"Status: `{candidate.get('status')}`",
        f"Score: `{candidate.get('score', 0)}`",
        "",
        "## Operator next action",
        "",
        candidate.get("recommended_next_action") or "No explicit next action recorded.",
        "",
    ]


def _candidate_packet_scope_lines(candidate: dict[str, Any]) -> list[str]:
    if not (candidate.get("claim_scope") or candidate.get("scale_limits")):
        return []
    lines = ["## Scope and limits", ""]
    for key, label in (
        ("claim_scope", "Claim scope"),
        ("scale_limits", "Scale limits"),
        ("hypothesis_status", "Hypothesis status"),
        ("evidence_strength", "Evidence strength"),
    ):
        if candidate.get(key):
            value = (
                f"`{candidate.get(key)}`"
                if key in {"hypothesis_status", "evidence_strength"}
                else candidate.get(key)
            )
            lines.append(f"- {label}: {value}")
    lines.append("")
    return lines


def _candidate_packet_related_paper_lines(candidate: dict[str, Any]) -> list[str]:
    related_papers = candidate.get("related_papers") or []
    if not related_papers:
        return []
    lines = ["## Related paper material", ""]
    for paper in related_papers:
        terms = ", ".join(paper.get("shared_terms") or [])
        lines.append(
            f"- **{paper.get('title')}** (`{paper.get('id')}`) — shared terms: {terms or 'n/a'}"
        )
    lines.append("")
    return lines


def _candidate_packet_source_lines(candidate: dict[str, Any]) -> list[str]:
    sources = candidate.get("sources") or []
    if not sources:
        return []
    lines = ["## Source lineage", ""]
    for source in sources:
        url = source.get("url") or ""
        suffix = f" — {url}" if url else ""
        lines.append(f"- {source.get('title')} (`{source.get('id')}`){suffix}")
    lines.append("")
    return lines


def _candidate_packet_dashboard_lines() -> list[str]:
    return [
        "## Dashboard context",
        "",
        "This packet is generated from the paper-material graph and is safe to inspect while the queue is running. It is an operator packet, not a dispatch command.",
        "",
    ]


def _candidate_packet_markdown(
    candidate: dict[str, Any], *, kind: str, graph: dict[str, Any]
) -> str:
    lines = _candidate_packet_header_lines(candidate, kind=kind, graph=graph)
    lines.extend(_candidate_packet_scope_lines(candidate))
    lines.extend(_candidate_packet_related_paper_lines(candidate))
    lines.extend(_candidate_packet_source_lines(candidate))
    lines.extend(_candidate_packet_dashboard_lines())
    return "\n".join(str(line) for line in lines)


def write_candidate_packets(graph: dict[str, Any], packet_dir: Path) -> list[Path]:
    _reject_existing_symlink_components(packet_dir)
    packet_dir.mkdir(parents=True, exist_ok=True)
    for stale in packet_dir.glob("**/*.md"):
        stale.unlink()
    written: list[Path] = []
    summary = graph.get("summary") or {}
    for kind, key in (
        ("synthesis", "synthesis_candidates"),
        ("negative", "negative_result_candidates"),
    ):
        kind_dir = packet_dir / kind
        _reject_existing_symlink_components(kind_dir)
        kind_dir.mkdir(parents=True, exist_ok=True)
        for candidate in summary.get(key) or []:
            if not isinstance(candidate, dict):
                continue
            rel_path = _text(candidate.get("packet_path"))
            filename = (
                Path(rel_path).name
                if rel_path
                else f"{_candidate_slug(candidate.get('signal_id'), candidate.get('title'))}.md"
            )
            output = kind_dir / filename
            _reject_existing_symlink_components(output)
            output.write_text(
                _candidate_packet_markdown(candidate, kind=kind, graph=graph),
                encoding="utf-8",
            )
            written.append(output)
    return written


def write_outputs(
    graph: dict[str, Any],
    *,
    json_output: Path,
    markdown_output: Path | None = None,
    candidate_packet_dir: Path | None = None,
) -> None:
    _reject_existing_symlink_components(json_output.parent)
    json_output.parent.mkdir(parents=True, exist_ok=True)
    _reject_existing_symlink_components(json_output)
    json_output.write_text(
        json.dumps(graph, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    if markdown_output is not None:
        _reject_existing_symlink_components(markdown_output.parent)
        markdown_output.parent.mkdir(parents=True, exist_ok=True)
        _reject_existing_symlink_components(markdown_output)
        markdown_output.write_text(_markdown(graph), encoding="utf-8")
    if candidate_packet_dir is not None:
        write_candidate_packets(graph, candidate_packet_dir)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus-repo", required=True, type=Path)
    parser.add_argument("--promising-repo", required=True, type=Path)
    parser.add_argument("--json-output", required=True, type=Path)
    parser.add_argument("--markdown-output", type=Path)
    parser.add_argument("--candidate-packet-dir", type=Path)
    parser.add_argument("--min-shared-terms", type=int, default=2)
    parser.add_argument("--max-similar-per-node", type=int, default=12)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    graph = build_graph(
        corpus_repo=args.corpus_repo,
        promising_repo=args.promising_repo,
        min_shared_terms=args.min_shared_terms,
        max_similar_per_node=args.max_similar_per_node,
    )
    write_outputs(
        graph,
        json_output=args.json_output,
        markdown_output=args.markdown_output,
        candidate_packet_dir=args.candidate_packet_dir,
    )
    print(json.dumps(_log_summary(graph), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
