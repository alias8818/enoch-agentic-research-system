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


def test_private_artifact_paths_are_redacted() -> None:
    signal = exporter.signal_from_row(
        _row(
            artifact_root="/home/jeremy/projects/private/signal",
            artifact_paths=["/opt/enoch-control-plane/projects/private/.enoch/project_decision.json"],
        )
    )

    serialized = json.dumps(signal, sort_keys=True)
    assert "/home/jeremy" not in serialized
    assert "/opt/enoch-control-plane" not in serialized
    assert "<local-path>" in serialized
    assert exporter.validate_signal(signal) == []


def test_public_markdown_sanitizes_publication_ready_phrase() -> None:
    signal = exporter.signal_from_row(_row(stop_reason="This is no-paper evidence rather than a publication-ready positive result."))

    markdown = exporter._markdown(signal)

    assert "publication-ready" not in markdown
    assert "paper-positive" in markdown



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
    manifest = json.loads((tmp_path / "data" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema_version"] == "enoch_promising_signal_manifest_v1"
    assert manifest["record_count"] == 2
    assert manifest["status_counts"] == {"promising_if_scaled": 1, "useful_signal": 1}
    assert manifest["project_ids"] == ["a-signal", "b-signal"]


def test_write_export_deduplicates_latest_row_and_removes_stale_files(tmp_path) -> None:
    stale = tmp_path / "signals" / "stale-signal.md"
    stale.parent.mkdir(parents=True)
    stale.write_text("stale", encoding="utf-8")

    result = exporter.write_export(
        [
            _row(project_id="dupe-signal", run_id="old-run", updated_at="2026-05-14T00:00:00Z", useful_signal_summary="old"),
            _row(project_id="dupe-signal", run_id="new-run", updated_at="2026-05-15T00:00:00Z", useful_signal_summary="new"),
        ],
        tmp_path,
    )

    records = [json.loads(line) for line in (tmp_path / "data" / "signals.jsonl").read_text(encoding="utf-8").splitlines()]
    assert result["count"] == 1
    assert records[0]["run_id"] == "new-run"
    assert records[0]["useful_signal_summary"] == "new"
    assert not stale.exists()
    assert not (tmp_path / "signals" / "dupe-signal-old-run.md").exists()


def test_validate_export_manifest_catches_count_and_status_drift(tmp_path) -> None:
    exporter.write_export([_row(project_id="signal-a"), _row(project_id="signal-b", compute_scale_blocked=True)], tmp_path)
    manifest_path = tmp_path / "data" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["record_count"] = 99
    manifest["status_counts"]["compute_scale_blocked"] = 0
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    issues = exporter.validate_export_repo(tmp_path)

    assert "manifest.record_count:99 != 2" in issues
    assert "manifest.status_counts.compute_scale_blocked:0 != 1" in issues


def test_validate_repo_against_rows_catches_control_plane_selection_drift(tmp_path) -> None:
    rows = [
        _row(project_id="clean-signal"),
        _row(project_id="missing-source", source_ids=[], source_urls=[], source_titles=[]),
    ]
    exporter.write_export(exporter.clean_export_rows(rows), tmp_path)
    manifest_path = tmp_path / "data" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["selection_summary"]["missing_required_evidence_or_fields"] = 0
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    issues = exporter.validate_repo_against_rows(rows, tmp_path)

    assert "selection_summary.missing_required_evidence_or_fields:0 != 1" in issues


def test_audit_backfill_report_classifies_exportable_and_missing_fields() -> None:
    rows = [
        _row(project_id="clean-signal"),
        _row(project_id="missing-summary", useful_signal_summary=""),
        _row(project_id="missing-source", source_ids=[], source_urls=[], source_titles=[]),
    ]

    report = exporter.audit_backfill(rows)

    assert report["summary"] == {
        "total_candidate_rows": 3,
        "export_cleanly_now": 1,
        "missing_required_evidence_or_fields": 2,
        "excluded_paper_or_corpus": 0,
        "hard_negative_or_stale": 0,
    }
    assert [row["project_id"] for row in report["buckets"]["export_cleanly_now"]] == ["clean-signal"]
    missing = {row["project_id"]: row for row in report["buckets"]["missing_required_evidence_or_fields"]}
    assert "useful_signal_summary:required" in missing["missing-summary"]["issues"]
    assert "sources:required" in missing["missing-source"]["issues"]


def test_clean_rows_from_audit_can_be_exported_without_invalid_historical_rows(tmp_path) -> None:
    rows = [
        _row(project_id="clean-signal"),
        _row(project_id="missing-source", source_ids=[], source_urls=[], source_titles=[]),
        _row(project_id="hard-negative", research_outcome="negative"),
    ]

    result = exporter.write_export(exporter.clean_export_rows(rows), tmp_path)

    records = [json.loads(line) for line in (tmp_path / "data" / "signals.jsonl").read_text(encoding="utf-8").splitlines()]
    manifest = json.loads((tmp_path / "data" / "manifest.json").read_text(encoding="utf-8"))
    assert result["count"] == 1
    assert [record["project_id"] for record in records] == ["clean-signal"]
    assert manifest["selection_summary"]["export_cleanly_now"] == 1
    assert manifest["selection_summary"]["missing_required_evidence_or_fields"] == 1
    assert manifest["selection_summary"]["hard_negative_or_stale"] == 1


def test_audit_backfill_report_classifies_paper_corpus_and_stale_rows() -> None:
    rows = [
        _row(project_id="paper-row", write_needed=True),
        _row(project_id="corpus-row", paper_id="paper-1", corpus_imported_at="2026-05-19T00:00:00Z"),
        _row(project_id="hard-negative", research_outcome="negative"),
        _row(project_id="stale", research_outcome=""),
    ]

    report = exporter.audit_backfill(rows)

    assert report["summary"] == {
        "total_candidate_rows": 4,
        "export_cleanly_now": 0,
        "missing_required_evidence_or_fields": 0,
        "excluded_paper_or_corpus": 2,
        "hard_negative_or_stale": 2,
    }
    paper = {row["project_id"]: row for row in report["buckets"]["excluded_paper_or_corpus"]}
    assert "paper_or_corpus_row" in paper["paper-row"]["issues"]
    assert "paper_or_corpus_row" in paper["corpus-row"]["issues"]
    stale = {row["project_id"]: row for row in report["buckets"]["hard_negative_or_stale"]}
    assert "research_outcome:not_export_status" in stale["hard-negative"]["issues"]
    assert "research_outcome:not_export_status" in stale["stale"]["issues"]


def test_audit_backfill_markdown_includes_backfill_plan() -> None:
    report = exporter.audit_backfill([_row(project_id="clean-signal")])

    markdown = exporter.audit_backfill_markdown(report)

    assert "# Promising signals backfill audit" in markdown
    assert "| Export cleanly now | 1 |" in markdown
    assert "## Backfill plan" in markdown
    assert "clean-signal" in markdown



def test_cli_writes_audit_json_and_markdown(tmp_path) -> None:
    input_json = tmp_path / "rows.json"
    input_json.write_text(json.dumps([_row(project_id="clean-signal")]), encoding="utf-8")
    output_repo = tmp_path / "unused-output-repo"
    audit_json = tmp_path / "audit" / "report.json"
    audit_md = tmp_path / "audit" / "report.md"

    rc = exporter.main([
        "--output-repo",
        str(output_repo),
        "--input-json",
        str(input_json),
        "--audit-report",
        str(audit_json),
        "--audit-markdown",
        str(audit_md),
    ])

    assert rc == 0
    report = json.loads(audit_json.read_text(encoding="utf-8"))
    assert report["summary"]["export_cleanly_now"] == 1
    assert not (output_repo / "data" / "signals.jsonl").exists()
    assert "# Promising signals backfill audit" in audit_md.read_text(encoding="utf-8")


def test_cli_clean_only_exports_valid_subset(tmp_path) -> None:
    input_json = tmp_path / "rows.json"
    input_json.write_text(
        json.dumps([
            _row(project_id="clean-signal"),
            _row(project_id="missing-source", source_ids=[], source_urls=[], source_titles=[]),
        ]),
        encoding="utf-8",
    )
    output_repo = tmp_path / "promising"

    rc = exporter.main([
        "--output-repo",
        str(output_repo),
        "--input-json",
        str(input_json),
        "--clean-only",
    ])

    assert rc == 0
    records = [json.loads(line) for line in (output_repo / "data" / "signals.jsonl").read_text(encoding="utf-8").splitlines()]
    manifest = json.loads((output_repo / "data" / "manifest.json").read_text(encoding="utf-8"))
    assert [record["project_id"] for record in records] == ["clean-signal"]
    assert manifest["selection_summary"]["missing_required_evidence_or_fields"] == 1
