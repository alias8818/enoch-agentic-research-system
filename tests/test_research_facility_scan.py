from __future__ import annotations

import json
from pathlib import Path

from scripts import research_facility, research_facility_scan


def test_research_facility_scan_turns_source_json_into_candidate_batch(
    tmp_path: Path,
) -> None:
    source = tmp_path / "sources.json"
    output = tmp_path / "batch.json"
    source.write_text(
        json.dumps(
            [
                {
                    "source_kind": "arxiv",
                    "title": "Efficient KV Cache Compression for Local Inference",
                    "url": "https://arxiv.org/abs/2402.02750",
                    "summary": "A method for efficient KV cache quantization and attention memory reduction.",
                }
            ]
        ),
        encoding="utf-8",
    )

    assert (
        research_facility_scan.main(
            ["--source-json", str(source), "--output", str(output)]
        )
        == 0
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["source_count"] == 1
    assert payload["candidate_count"] == 1
    candidate = payload["candidates"][0]
    assert candidate["source_records"][0]["source_kind"] == "arxiv"
    assert candidate["source_urls"] == ["https://arxiv.org/abs/2402.02750"]
    assert candidate["category"] == "kv-compression"
    assert candidate["baseline_to_beat"]
    assert candidate["kill_condition"]

    plan = research_facility.plan_candidates(
        [candidate],
        research_facility.argparse.Namespace(
            default_machine="gb10",
            default_model="gpt-5.5",
            default_sandbox="danger-full-access",
            admit_threshold=72.0,
            review_threshold=58.0,
        ),
    )[0]
    assert plan.admission_decision in {"admitted", "needs_review", "rejected"}
    assert "fresh_grounded requires" not in plan.admission_reason


def test_research_facility_scan_parses_arxiv_atom_without_network(
    monkeypatch, tmp_path: Path
) -> None:
    atom = """<?xml version='1.0' encoding='UTF-8'?>
    <feed xmlns='http://www.w3.org/2005/Atom'>
      <entry>
        <id>https://arxiv.org/abs/2605.00001</id>
        <updated>2026-05-09T00:00:00Z</updated>
        <published>2026-05-09T00:00:00Z</published>
        <title>Speculative Decoding with Cache Aware Drafting</title>
        <summary>We study speculative decoding and cache-aware inference for efficient local serving.</summary>
        <author><name>Example Author</name></author>
      </entry>
    </feed>"""
    monkeypatch.setattr(
        research_facility_scan, "fetch_text", lambda url, timeout=20: atom
    )

    records = research_facility_scan.scan_arxiv(
        "all:speculative decoding", max_results=1, timeout=1
    )

    assert len(records) == 1
    assert records[0].source_kind == "arxiv"
    assert records[0].external_id == "2605.00001"
    assert "Speculative Decoding" in records[0].title
    candidate = research_facility_scan.candidate_from_source(
        records[0],
        default_machine="worker",
        default_model="model",
        default_sandbox="sandbox",
    )
    assert candidate["category"] == "spec-decoding"
    assert candidate["source_ids"] == [records[0].source_id]


def test_research_facility_scan_records_fetch_errors_without_losing_batch(
    monkeypatch, tmp_path: Path
) -> None:
    output = tmp_path / "batch.json"
    monkeypatch.setattr(
        research_facility_scan,
        "fetch_text",
        lambda url, timeout=20: (_ for _ in ()).throw(RuntimeError("rate limited")),
    )

    assert (
        research_facility_scan.main(
            ["--arxiv-query", "all:test", "--output", str(output)]
        )
        == 0
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["ok"] is False
    assert payload["source_count"] == 0
    assert payload["candidate_count"] == 0
    assert payload["errors"][0]["source"] == "arxiv:all:test"
    assert "rate limited" in payload["errors"][0]["error"]
