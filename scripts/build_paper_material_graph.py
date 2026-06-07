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
)
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
    "using",
    "used",
    "with",
    "without",
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
    return text


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _first_markdown_heading(path: Path) -> str:
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("# "):
                return line[2:].strip()
    except OSError:
        return ""
    return ""


def _markdown_excerpt(path: Path, max_chars: int = 900) -> str:
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
    paper_md = paper_dir / "paper.md"
    if not paper_md.exists():
        return None
    manifest = _read_json(paper_dir / "paper_manifest.json")
    title = (
        _first_markdown_heading(paper_md) or paper_dir.name.replace("-", " ").title()
    )
    excerpt = _markdown_excerpt(paper_md)
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
    if not data_path.exists():
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
    claim_scope = _safe_text(record.get("claim_scope"))
    useful_summary = _safe_text(record.get("useful_signal_summary"))
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
        "scale_limits": _safe_text(record.get("scale_limits")),
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


def _similar_topic_edges(
    nodes: list[dict[str, Any]], *, min_shared_terms: int, max_similar_per_node: int
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    comparable = [node for node in nodes if node.get("kind") in {"paper", "signal"}]
    for index, left in enumerate(comparable):
        left_terms = set(left.get("terms") or [])
        if not left_terms:
            continue
        for right in comparable[index + 1 :]:
            right_terms = set(right.get("terms") or [])
            shared = sorted(left_terms & right_terms)
            if len(shared) < min_shared_terms:
                continue
            # Prefer cross-outcome paper/signal edges, but keep strong same-kind clusters too.
            if (
                left.get("kind") == right.get("kind")
                and len(shared) < min_shared_terms + 1
            ):
                continue
            weight = round(len(shared) / max(len(left_terms | right_terms), 1), 4)
            candidates.append(
                _edge(
                    left["id"],
                    right["id"],
                    "similar_topic",
                    weight=weight,
                    shared_terms=shared[:12],
                    shared_term_count=len(shared),
                )
            )
    candidates.sort(
        key=lambda edge: (
            -float(edge.get("weight") or 0),
            -int(edge.get("shared_term_count") or 0),
            edge["source"],
            edge["target"],
        )
    )
    if max_similar_per_node <= 0:
        return candidates
    degree: Counter[str] = Counter()
    kept: list[dict[str, Any]] = []
    for edge in candidates:
        if (
            degree[edge["source"]] >= max_similar_per_node
            or degree[edge["target"]] >= max_similar_per_node
        ):
            continue
        kept.append(edge)
        degree[edge["source"]] += 1
        degree[edge["target"]] += 1
    return kept


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


def _connected_components(
    nodes: list[dict[str, Any]], edges: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    adjacency: dict[str, set[str]] = {node["id"]: set() for node in nodes}
    for edge in edges:
        adjacency.setdefault(edge["source"], set()).add(edge["target"])
        adjacency.setdefault(edge["target"], set()).add(edge["source"])
    seen: set[str] = set()
    components: list[dict[str, Any]] = []
    node_by_id = {node["id"]: node for node in nodes}
    for node_id in sorted(adjacency):
        if node_id in seen:
            continue
        stack = [node_id]
        members: list[str] = []
        seen.add(node_id)
        while stack:
            current = stack.pop()
            members.append(current)
            for neighbor in sorted(adjacency.get(current, set())):
                if neighbor not in seen:
                    seen.add(neighbor)
                    stack.append(neighbor)
        kind_counts = Counter(
            node_by_id.get(member, {}).get("kind", "unknown") for member in members
        )
        if len(members) > 1:
            components.append(
                {
                    "id": f"component:{len(components) + 1}",
                    "size": len(members),
                    "kind_counts": dict(sorted(kind_counts.items())),
                    "sample_member_ids": sorted(members)[:25],
                    "sample_titles": [
                        node_by_id[member].get("title", member)
                        for member in sorted(members)
                        if member in node_by_id
                        and node_by_id[member].get("kind") != "source"
                    ][:8],
                }
            )
    components.sort(key=lambda item: (-item["size"], item["id"]))
    return components


def _synthesis_candidates(
    nodes: list[dict[str, Any]], edges: list[dict[str, Any]], *, limit: int = 25
) -> list[dict[str, Any]]:
    node_by_id = {node["id"]: node for node in nodes}
    related: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for edge in edges:
        if edge.get("kind") not in {"similar_topic", "cites_source"}:
            continue
        for source_id, target_id in (
            (edge["source"], edge["target"]),
            (edge["target"], edge["source"]),
        ):
            source = node_by_id.get(source_id)
            target = node_by_id.get(target_id)
            if not source or not target or source.get("kind") != "signal":
                continue
            related[source_id].append({"edge": edge, "node": target})
    candidates: list[dict[str, Any]] = []
    for signal_id, items in related.items():
        signal = node_by_id.get(signal_id)
        if signal is None:
            continue
        related_papers = [item for item in items if item["node"].get("kind") == "paper"]
        related_sources = [
            item for item in items if item["node"].get("kind") == "source"
        ]
        if not related_papers:
            continue
        status = _text(signal.get("status"))
        curation = (
            signal.get("curation") if isinstance(signal.get("curation"), dict) else {}
        )
        score = int(curation.get("score") or 0)
        score += 10 if status == "compute_scale_blocked" else 0
        score += min(len(related_papers), 5) * 5
        score += min(len(related_sources), 3) * 2
        paper_rows = sorted(
            related_papers,
            key=lambda item: (
                -float(item["edge"].get("weight") or 0),
                item["node"].get("title", ""),
            ),
        )[:8]
        source_rows = sorted(
            related_sources,
            key=lambda item: item["node"].get("title", ""),
        )[:5]
        followup = (
            signal.get("followup") if isinstance(signal.get("followup"), dict) else {}
        )
        candidates.append(
            {
                "signal_id": signal_id,
                "title": signal.get("title", ""),
                "status": status,
                "score": score,
                "curation_score": int(curation.get("score") or 0),
                "related_paper_count": len(related_papers),
                "related_source_count": len(related_sources),
                "related_papers": [
                    {
                        "id": item["node"]["id"],
                        "title": item["node"].get("title", ""),
                        "weight": item["edge"].get("weight"),
                        "shared_terms": item["edge"].get("shared_terms", []),
                    }
                    for item in paper_rows
                ],
                "sources": [
                    {
                        "id": item["node"]["id"],
                        "title": item["node"].get("title", ""),
                        "url": item["node"].get("url", ""),
                    }
                    for item in source_rows
                ],
                "recommended_next_action": followup.get("title", ""),
            }
        )
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


def _markdown(graph: dict[str, Any]) -> str:
    summary = graph.get("summary") or {}
    lines = [
        "# Enoch Paper Material Graph",
        "",
        f"Generated: `{graph.get('generated_at')}`",
        "",
        "## Summary",
        "",
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
    for status, count in (summary.get("signal_status_counts") or {}).items():
        lines.append(f"- `{status}`: {count}")
    lines.extend(["", "## Top synthesis candidates", ""])
    for candidate in summary.get("synthesis_candidates") or []:
        lines.append(
            f"### {candidate.get('title')} — score {candidate.get('score')} "
            f"(`{candidate.get('status')}`)"
        )
        lines.append(f"- Signal: `{candidate.get('signal_id')}`")
        lines.append(f"- Related papers: {candidate.get('related_paper_count', 0)}")
        if candidate.get("recommended_next_action"):
            lines.append(f"- Next action: {candidate.get('recommended_next_action')}")
        for paper in candidate.get("related_papers") or []:
            terms = ", ".join(paper.get("shared_terms") or [])
            lines.append(f"  - {paper.get('title')} — shared: {terms}")
        lines.append("")
    lines.extend(["", "## Negative / blocked result candidates", ""])
    for candidate in summary.get("negative_result_candidates") or []:
        lines.append(
            f"### {candidate.get('title')} — score {candidate.get('score')} "
            f"(`{candidate.get('status')}`)"
        )
        lines.append(f"- Signal: `{candidate.get('signal_id')}`")
        if candidate.get("scale_limits"):
            lines.append(f"- Scale limits: {candidate.get('scale_limits')}")
        if candidate.get("claim_scope"):
            lines.append(f"- Claim scope: {candidate.get('claim_scope')}")
        if candidate.get("recommended_next_action"):
            lines.append(f"- Next action: {candidate.get('recommended_next_action')}")
        lines.append("")
    lines.extend(["", "## Largest components", ""])
    for component in summary.get("largest_components") or []:
        lines.append(
            f"### {component.get('id')} — {component.get('size')} nodes "
            f"{component.get('kind_counts')}"
        )
        for title in component.get("sample_titles") or []:
            lines.append(f"- {title}")
        lines.append("")
    lines.extend(
        [
            "## How to use this",
            "",
            "Use high-signal mixed components as paper-material candidates: a good component links prior public papers, useful/scale-blocked signals, source lineage, and repeated methods. The next layer should score these components for synthesis and queue bounded follow-up experiments that can turn weak individual runs into stronger paper-positive material.",
            "",
        ]
    )
    return "\n".join(lines)


def write_outputs(
    graph: dict[str, Any], *, json_output: Path, markdown_output: Path | None = None
) -> None:
    json_output.parent.mkdir(parents=True, exist_ok=True)
    json_output.write_text(
        json.dumps(graph, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    if markdown_output is not None:
        markdown_output.parent.mkdir(parents=True, exist_ok=True)
        markdown_output.write_text(_markdown(graph), encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus-repo", required=True, type=Path)
    parser.add_argument("--promising-repo", required=True, type=Path)
    parser.add_argument("--json-output", required=True, type=Path)
    parser.add_argument("--markdown-output", type=Path)
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
        graph, json_output=args.json_output, markdown_output=args.markdown_output
    )
    print(json.dumps({"ok": True, **graph["summary"]}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
