from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "export_promising_signals.py"
spec = importlib.util.spec_from_file_location("export_promising_signals", SCRIPT)
assert spec and spec.loader
exporter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(exporter)


def _row(**overrides):
    row = {
        "project_id": "token-superposition-example",
        "run_id": "token-superposition-example-20260514T000000+0000",
        "project_name": "Token Superposition Example",
        "decision_summary": "finalize_negative (project decision is not positive)",
        "research_outcome": "useful_signal",
        "hypothesis_status": "mixed",
        "evidence_strength": "moderate",
        "claim_scope": "Bounded local/toy evidence only.",
        "scale_limits": "No full-scale model training was performed.",
        "useful_signal_summary": "Synthetic proxy showed a mechanism worth preserving.",
        "stop_reason": "No-paper closure because validation was not publication-grade.",
        "recommended_next_action": "Run a bounded direct follow-up.",
        "followup_recommended": True,
        "followup_type": "deepen",
        "followup_title": "Direct follow-up",
        "followup_hypothesis": "The mechanism transfers to a direct small model test.",
        "followup_required_evidence": ["direct model metrics"],
        "followup_success_threshold": "beats baseline by 10%",
        "followup_stop_condition": "stop if no baseline lift",
        "followup_depth": 1,
        "source_ids": ["arxiv:2605.06546"],
        "source_urls": ["https://arxiv.org/abs/2605.06546"],
        "source_titles": ["Efficient Pre-Training with Token Superposition"],
        "artifact_root": "/var/lib/enoch-control-plane/projects/token-superposition-example",
        "artifact_paths": ["run_notes.md", ".enoch/project_decision.json"],
        "has_live_paper_row": False,
        "write_needed": False,
        "bounded_paper_ready": False,
        "compute_scale_blocked": False,
        "updated_at": "2026-05-14T00:00:00Z",
    }
    row.update(overrides)
    return row


def test_exports_useful_signal_with_required_disclaimer_and_schema() -> None:
    signal = exporter.signal_from_row(_row())

    assert signal["status"] == "useful_signal"
    assert signal["do_not_overclaim"]["not_a_paper"] is True
    assert signal["do_not_overclaim"]["not_publication_validated"] is True
    assert "not validated papers" in signal["do_not_overclaim"]["disclaimer"]
    assert signal["sources"][0]["url"] == "https://arxiv.org/abs/2605.06546"
    assert exporter.validate_signal(signal) == []


def test_promising_if_scaled_and_compute_scale_blocked_statuses_are_deterministic() -> None:
    promising = exporter.signal_from_row(_row(research_outcome="promising_if_scaled"))
    blocked = exporter.signal_from_row(_row(research_outcome="promising_if_scaled", compute_scale_blocked=True))

    assert promising["status"] == "promising_if_scaled"
    assert blocked["status"] == "compute_scale_blocked"


def test_excludes_paper_positive_and_hard_negative_rows() -> None:
    rows = [
        _row(project_id="paper-positive", research_outcome="paper_positive", write_needed=True),
        _row(project_id="hard-negative", research_outcome="", hypothesis_status="unsupported"),
        _row(project_id="useful", research_outcome="useful_signal"),
    ]

    exported = exporter.export_signals(rows)

    assert [row["project_id"] for row in exported] == ["useful"]


def test_missing_required_fields_fail_closed() -> None:
    signal = exporter.signal_from_row(_row(useful_signal_summary=""))

    issues = exporter.validate_signal(signal)

    assert "useful_signal_summary:required" in issues



def test_source_records_keep_url_title_alignment() -> None:
    signal = exporter.signal_from_row(
        _row(
            source_records=[
                {
                    "source_id": "url-f3263e492b186b46f502db17",
                    "url": "https://arxiv.org/abs/2605.06546",
                    "title": "Token Superposition for Long-Context Anchor Compression",
                },
                {
                    "source_id": "arxiv:2605.06546",
                    "url": "https://arxiv.org/abs/2605.06546",
                    "title": "Efficient Pre-Training with Token Superposition",
                },
            ]
        )
    )

    by_id = {source["source_id"]: source for source in signal["sources"]}

    assert by_id["url-f3263e492b186b46f502db17"]["url"] == "https://arxiv.org/abs/2605.06546"
    assert by_id["url-f3263e492b186b46f502db17"]["title"] == "Token Superposition for Long-Context Anchor Compression"


def test_writes_deterministic_jsonl_markdown_and_index(tmp_path) -> None:
    rows = [
        _row(project_id="b-signal", project_name="B Signal"),
        _row(project_id="a-signal", project_name="A Signal", research_outcome="promising_if_scaled"),
    ]

    result = exporter.write_export(rows, tmp_path)

    assert result["count"] == 2
    jsonl = (tmp_path / "data" / "signals.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["project_id"] for line in jsonl] == ["a-signal", "b-signal"]
    assert (tmp_path / "signals" / "a-signal.md").exists()
    assert (tmp_path / "signals" / "b-signal.md").exists()
    assert "A Signal" in (tmp_path / "signals" / "index.md").read_text(encoding="utf-8")
    assert (tmp_path / "schemas" / "promising-signal.schema.json").exists()
