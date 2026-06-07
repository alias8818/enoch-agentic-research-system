from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build_paper_material_graph.py"
spec = importlib.util.spec_from_file_location("build_paper_material_graph", SCRIPT)
assert spec and spec.loader
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


def _write_corpus_paper(root: Path, slug: str, title: str, body: str) -> None:
    paper_dir = root / "papers" / slug
    paper_dir.mkdir(parents=True)
    (paper_dir / "paper.md").write_text(f"# {title}\n\n{body}\n", encoding="utf-8")
    (paper_dir / "paper_manifest.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-06-01T00:00:00+00:00",
                "paper_id": f"{slug}:run:arxiv_draft",
                "writer_provider": {"provider": "synthetic.new", "model": "hf:test"},
            }
        ),
        encoding="utf-8",
    )


def _write_promising_signal(
    root: Path,
    *,
    project_id: str,
    title: str,
    status: str = "useful_signal",
    source_url: str = "https://arxiv.org/abs/2605.06546",
) -> None:
    data = root / "data"
    data.mkdir(parents=True, exist_ok=True)
    record = {
        "schema_version": "enoch_promising_signal_v1",
        "project_id": project_id,
        "run_id": f"{project_id}-20260601T000000+0000",
        "title": title,
        "status": status,
        "hypothesis_status": "mixed",
        "evidence_strength": "moderate",
        "claim_scope": "Bounded speculative decoding evidence.",
        "scale_limits": "Tiny local test only.",
        "useful_signal_summary": "Speculative decoding signal worth combining with related papers.",
        "sources": [
            {
                "source_id": "arxiv:2605.06546",
                "url": source_url,
                "title": "Suffix speculative decoding reference",
            }
        ],
        "followup": {"recommended": True, "title": "Run shared follow-up"},
        "evidence": {
            "artifact_paths": ["run_notes.md", ".enoch/project_decision.json"]
        },
        "curation": {"bucket": "followup_recommended", "score": 83, "reasons": []},
        "updated_at": "2026-06-01T00:00:00Z",
    }
    with (data / "signals.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")


def test_build_graph_connects_papers_signals_sources_and_similar_topics(
    tmp_path: Path,
) -> None:
    corpus = tmp_path / "corpus"
    promising = tmp_path / "promising"
    _write_corpus_paper(
        corpus,
        "suffix-speculative-decoding-paper",
        "Suffix Speculative Decoding for Agentic Workloads",
        "We evaluate speculative decoding and verifier acceptance on agent traces.",
    )
    _write_promising_signal(
        promising,
        project_id="token-suffix-speculative-drafting",
        title="Token suffix speculative drafting without KV cache reuse",
        status="compute_scale_blocked",
    )

    graph = builder.build_graph(corpus_repo=corpus, promising_repo=promising)

    node_ids = {node["id"] for node in graph["nodes"]}
    assert "paper:suffix-speculative-decoding-paper" in node_ids
    assert "signal:token-suffix-speculative-drafting" in node_ids
    assert "source:https://arxiv.org/abs/2605.06546" in node_ids

    edges = {(edge["source"], edge["target"], edge["kind"]) for edge in graph["edges"]}
    assert (
        "signal:token-suffix-speculative-drafting",
        "source:https://arxiv.org/abs/2605.06546",
        "cites_source",
    ) in edges
    assert any(edge[2] == "similar_topic" for edge in edges)

    summary = graph["summary"]
    assert summary["node_counts"]["paper"] == 1
    assert summary["node_counts"]["signal"] == 1
    assert summary["signal_status_counts"]["compute_scale_blocked"] == 1
    assert summary["paper_count"] == 1
    assert summary["signal_count"] == 1
    assert summary["similar_topic_edges"] >= 1
    largest = summary["largest_components"]
    assert largest[0]["size"] == 3
    assert "members" not in largest[0]
    assert largest[0]["sample_member_ids"]
    candidates = summary["synthesis_candidates"]
    assert candidates[0]["signal_id"] == "signal:token-suffix-speculative-drafting"
    assert candidates[0]["related_paper_count"] == 1
    assert "Suffix Speculative Decoding" in candidates[0]["related_papers"][0]["title"]


def test_similarity_edges_are_bounded_to_strongest_local_neighborhood(
    tmp_path: Path,
) -> None:
    corpus = tmp_path / "corpus"
    promising = tmp_path / "promising"
    _write_corpus_paper(
        corpus,
        "speculative-decoding-one",
        "Speculative Decoding Acceptance Router",
        "Speculative decoding acceptance router latency verifier.",
    )
    _write_corpus_paper(
        corpus,
        "speculative-decoding-two",
        "Speculative Decoding KV Cache Router",
        "Speculative decoding KV cache router throughput.",
    )
    _write_corpus_paper(
        corpus,
        "memory-ledger",
        "Trace Memory Evidence Ledger",
        "Trace memory evidence ledger for agent replay.",
    )
    _write_promising_signal(
        promising,
        project_id="speculative-signal",
        title="Speculative decoding acceptance verifier",
    )

    graph = builder.build_graph(
        corpus_repo=corpus,
        promising_repo=promising,
        min_shared_terms=2,
        max_similar_per_node=1,
    )

    similar_edges = [edge for edge in graph["edges"] if edge["kind"] == "similar_topic"]
    degree: dict[str, int] = {}
    for edge in similar_edges:
        degree[edge["source"]] = degree.get(edge["source"], 0) + 1
        degree[edge["target"]] = degree.get(edge["target"], 0) + 1
    assert similar_edges
    assert max(degree.values()) <= 1
    assert len(similar_edges) < 4


def test_synthesis_candidates_include_scale_blocked_material(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    promising = tmp_path / "promising"
    _write_corpus_paper(
        corpus,
        "gb10-dense-router-audit",
        "GB10 Dense Router Audit Bundle",
        "Dense router audit harness for GB10 environment and routing evidence.",
    )
    for index in range(4):
        _write_promising_signal(
            promising,
            project_id=f"useful-signal-{index}",
            title=f"Useful dense router audit harness signal {index}",
            status="useful_signal",
        )
    _write_promising_signal(
        promising,
        project_id="scale-blocked-dense-router",
        title="Scale blocked dense router audit harness",
        status="compute_scale_blocked",
    )

    graph = builder.build_graph(corpus_repo=corpus, promising_repo=promising)

    candidates = graph["summary"]["synthesis_candidates"]
    assert any(
        candidate["status"] == "compute_scale_blocked" for candidate in candidates
    )
    negative = graph["summary"]["negative_result_candidates"]
    assert negative[0]["status"] == "compute_scale_blocked"
    assert negative[0]["title"] == "Scale blocked dense router audit harness"


def test_graph_output_redacts_private_paths_and_writes_json_and_markdown(
    tmp_path: Path,
) -> None:
    corpus = tmp_path / "corpus"
    promising = tmp_path / "promising"
    out_json = tmp_path / "graph" / "paper-material-graph.json"
    out_md = tmp_path / "graph" / "paper-material-graph.md"
    packet_dir = tmp_path / "graph" / "candidates"
    _write_corpus_paper(
        corpus,
        "memory-paper",
        "Trace Derived Memory for Paper Material",
        "Local path /home/jeremy/secret should not leak into public graph summaries.",
    )
    _write_promising_signal(
        promising,
        project_id="trace-memory-signal",
        title="Trace derived memory for long running agents",
        source_url="enoch://research-facility/provider/test",
    )

    graph = builder.build_graph(corpus_repo=corpus, promising_repo=promising)
    builder.write_outputs(
        graph,
        json_output=out_json,
        markdown_output=out_md,
        candidate_packet_dir=packet_dir,
    )

    serialized = out_json.read_text(encoding="utf-8")
    assert "/home/jeremy" not in serialized
    assert "<local-path>" in serialized
    markdown = out_md.read_text(encoding="utf-8")
    assert "# Enoch Paper Material Graph" in markdown
    assert "Trace Derived Memory" in markdown
    assert "candidates/synthesis/trace-memory-signal.md" in markdown
    assert "operations.md" in markdown
    packets = sorted(packet_dir.glob("**/*.md"))
    assert [packet.relative_to(packet_dir).as_posix() for packet in packets] == [
        "synthesis/trace-memory-signal.md"
    ]
    packet = packets[0].read_text(encoding="utf-8")
    assert "# Trace derived memory for long running agents" in packet
    assert "Operator next action" in packet


def test_log_summary_is_compact_and_operator_focused(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    promising = tmp_path / "promising"
    _write_corpus_paper(
        corpus,
        "memory-paper",
        "Trace Derived Memory for Paper Material",
        "Trace memory evidence ledger for agent replay.",
    )
    _write_promising_signal(
        promising,
        project_id="trace-memory-signal",
        title="Trace derived memory for long running agents",
    )

    graph = builder.build_graph(corpus_repo=corpus, promising_repo=promising)
    summary = builder._log_summary(graph)

    assert summary["ok"] is True
    assert summary["paper_count"] == 1
    assert summary["synthesis_candidate_count"] == 1
    assert "largest_components" not in summary
    assert "synthesis_candidates" not in summary
    assert summary["top_synthesis_titles"] == [
        "Trace derived memory for long running agents"
    ]
