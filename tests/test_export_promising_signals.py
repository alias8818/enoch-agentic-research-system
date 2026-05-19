from __future__ import annotations

import importlib.util
import json
import sys
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


def test_rank_signal_is_deterministic_explainable_and_bucketed() -> None:
    top = exporter.signal_from_row(
        _row(
            project_id="top-signal",
            evidence_strength="strong",
            hypothesis_status="supported",
            followup_recommended=True,
            followup_required_evidence=["direct metric", "ablation", "seed sweep"],
            artifact_paths=["run_notes.md", ".enoch/project_decision.json", ".enoch/metrics.json"],
        )
    )

    first = exporter.rank_signal(top)
    second = exporter.rank_signal(dict(reversed(list(top.items()))))

    assert first == second
    assert first["bucket"] == "top_external_researcher_candidates"
    assert first["score"] == 100
    assert first["score_breakdown"]["evidence_strength"] == 35
    assert first["score_breakdown"]["hypothesis_status"] == 30
    assert first["score_breakdown"]["source_lineage"] == 12
    assert first["score_breakdown"]["followup"] == 15
    assert first["score_breakdown"]["bounded_evidence"] == 18
    assert first["reasons"] == [
        "strong evidence_strength",
        "supported hypothesis_status",
        "source lineage present",
        "external source URL present",
        "bounded follow-up is specified",
        "local evidence artifact paths are present",
        "metrics artifact is present",
        "project decision artifact is present",
    ]


def test_rank_signal_bucket_priority_is_deterministic() -> None:
    rows = [
        _row(project_id="compute", compute_scale_blocked=True, evidence_strength="strong", hypothesis_status="supported"),
        _row(project_id="followup", evidence_strength="moderate", hypothesis_status="mixed", followup_recommended=True),
        _row(project_id="weak", evidence_strength="moderate", hypothesis_status="mixed", followup_recommended=False),
        _row(project_id="stale", evidence_strength="moderate", hypothesis_status="unsupported", followup_recommended=True),
    ]
    buckets = {
        row["project_id"]: exporter.rank_signal(exporter.signal_from_row(row))["bucket"]
        for row in rows
    }

    assert buckets == {
        "compute": "compute_scale_blocked",
        "followup": "followup_recommended",
        "weak": "weak_local_only_preserved",
        "stale": "likely_stale_low_value_archive",
    }


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
    assert (tmp_path / "signals" / "ranked-index.md").exists()
    assert (tmp_path / "signals" / "buckets" / "followup-recommended.md").exists()
    ranking = json.loads((tmp_path / "data" / "ranking.json").read_text(encoding="utf-8"))
    assert ranking["schema_version"] == "enoch_promising_signal_ranking_v1"
    assert ranking["bucket_counts"] == {"followup_recommended": 2}
    assert [item["project_id"] for item in ranking["items"]] == ["a-signal", "b-signal"]
    assert (tmp_path / "schemas" / "promising-signal.schema.json").exists()
    manifest = json.loads((tmp_path / "data" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema_version"] == "enoch_promising_signal_manifest_v1"
    assert manifest["record_count"] == 2
    assert manifest["status_counts"] == {"promising_if_scaled": 1, "useful_signal": 1}
    assert manifest["project_ids"] == ["a-signal", "b-signal"]
    assert manifest["ranking_summary"] == {"followup_recommended": 2}


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


def test_validate_export_repo_catches_ranking_drift(tmp_path) -> None:
    exporter.write_export([_row(project_id="signal-a"), _row(project_id="signal-b", compute_scale_blocked=True)], tmp_path)
    ranking_path = tmp_path / "data" / "ranking.json"
    ranking = json.loads(ranking_path.read_text(encoding="utf-8"))
    ranking["items"][0]["score"] = 1
    ranking_path.write_text(json.dumps(ranking), encoding="utf-8")

    issues = exporter.validate_export_repo(tmp_path)

    assert "ranking.items:drift" in issues


def test_validate_repo_against_rows_catches_control_plane_selection_drift(tmp_path) -> None:
    rows = [
        _row(project_id="clean-signal"),
        _row(project_id="missing-source", source_ids=[], source_urls=[], source_titles=[]),
    ]
    exporter.write_export(exporter.clean_export_rows(rows), tmp_path)
    manifest_path = tmp_path / "data" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["selection_summary"]["backfilled_exportable"] = 0
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    issues = exporter.validate_repo_against_rows(rows, tmp_path)

    assert "selection_summary.backfilled_exportable:0 != 1" in issues


def test_new_missing_source_lineage_is_blocked_after_cutoff() -> None:
    rows = [
        _row(
            project_id="new-unsourced",
            source_ids=[],
            source_urls=[],
            source_titles=[],
            updated_at="2026-05-20T00:00:00Z",
        ),
        _row(
            project_id="legacy-unsourced",
            source_ids=[],
            source_urls=[],
            source_titles=[],
            updated_at="2026-05-18T00:00:00Z",
        ),
    ]

    report = exporter.validate_source_backfill_policy(rows, created_after="2026-05-19T17:51:00Z")

    assert report["ok"] is False
    assert report["summary"] == {
        "legacy_backfilled_source_ok": 1,
        "new_missing_source_lineage_blocked": 1,
    }
    assert report["problems"][0]["project_id"] == "new-unsourced"


def test_export_postgres_query_traverses_idea_and_candidate_lineage(monkeypatch) -> None:
    executed: list[tuple[str, list[object]]] = []

    class Cursor:
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def execute(self, sql, params=()):  # noqa: ANN001 - lightweight DB fake
            executed.append((str(sql), list(params)))
        def fetchall(self): return []

    class Conn:
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def cursor(self): return Cursor()

    class FakePsycopg:
        def connect(self, *_args, **_kwargs): return Conn()

    monkeypatch.setenv("ENOCH_SUPABASE_DATABASE_URL", "postgres://example")
    monkeypatch.setitem(sys.modules, "psycopg", FakePsycopg())
    monkeypatch.setitem(sys.modules, "psycopg.rows", type("Rows", (), {"dict_row": object()})())

    exporter._fetch_postgres_rows([], "")

    sql = " ".join(executed[0][0].lower().split())
    assert "left join enoch.research_lineage idea_source_rl" in sql
    assert "idea_source_rl.target_type='idea'" in sql
    assert "left join enoch.research_lineage queued_rl" in sql
    assert "queued_rl.relation_type='queued_as'" in sql
    assert "left join enoch.research_lineage admitted_rl" in sql
    assert "admitted_rl.relation_type='admitted_as'" in sql
    assert "left join enoch.research_lineage candidate_source_rl" in sql
    assert "candidate_source_rl.relation_type='generated_from'" in sql


def test_audit_backfill_report_classifies_exportable_and_missing_fields() -> None:
    rows = [
        _row(project_id="clean-signal"),
        _row(project_id="missing-summary", useful_signal_summary=""),
        _row(project_id="missing-source", source_ids=[], source_urls=[], source_titles=[]),
    ]

    report = exporter.audit_backfill(rows)

    assert report["summary"] == {
        "total_candidate_rows": 3,
        "export_cleanly_now": 2,
        "backfilled_exportable": 1,
        "missing_required_evidence_or_fields": 1,
        "excluded_paper_or_corpus": 0,
        "hard_negative_or_stale": 0,
    }
    assert [row["project_id"] for row in report["buckets"]["export_cleanly_now"]] == ["clean-signal", "missing-source"]
    missing = {row["project_id"]: row for row in report["buckets"]["missing_required_evidence_or_fields"]}
    assert "useful_signal_summary:required" in missing["missing-summary"]["issues"]
    repaired = {row["project_id"]: row for row in report["buckets"]["export_cleanly_now"]}
    assert repaired["missing-source"]["backfill"]["actions"] == ["source_records:queue_project_metadata"]
    assert repaired["missing-source"]["backfill"]["classification"] == ["missing_research_source_lineage"]


def test_source_backfill_uses_internal_project_source_without_overclaiming() -> None:
    row = _row(
        project_id="missing-source",
        project_name="Missing Source Project",
        source_ids=[],
        source_urls=[],
        source_titles=[],
        source_records=[],
    )

    signal = exporter.signal_from_row(row)
    assert "sources:required" in exporter.validate_signal(signal)

    backfilled = exporter.backfill_promising_signal_row(row)
    repaired_signal = exporter.signal_from_row(backfilled)

    assert exporter.validate_signal(repaired_signal) == []
    assert repaired_signal["sources"] == [
        {
            "source_id": "internal_generated:missing-source",
            "url": "",
            "title": "Internal Enoch project: Missing Source Project",
        }
    ]
    assert backfilled["_promising_signal_backfill"]["classification"] == ["missing_research_source_lineage"]
    assert backfilled["_promising_signal_backfill"]["actions"] == ["source_records:queue_project_metadata"]


def test_unrecoverable_missing_source_stays_parked_with_machine_reason() -> None:
    row = _row(
        project_id="",
        project_name="",
        title="",
        source_ids=[],
        source_urls=[],
        source_titles=[],
        source_records=[],
    )

    report = exporter.audit_backfill([row])

    assert report["summary"]["missing_required_evidence_or_fields"] == 1
    parked = report["buckets"]["missing_required_evidence_or_fields"][0]
    assert "unrecoverable_project_identity" in parked["backfill"]["classification"]
    assert parked["backfill"]["actions"] == []


def test_audit_classifies_stale_duplicate_superseded_before_missing_fields() -> None:
    rows = [
        _row(project_id="dupe-signal", run_id="old", updated_at="2026-05-14T00:00:00Z", source_ids=[], source_urls=[], source_titles=[]),
        _row(project_id="dupe-signal", run_id="new", updated_at="2026-05-15T00:00:00Z"),
    ]

    report = exporter.audit_backfill(rows)

    assert report["summary"]["export_cleanly_now"] == 1
    assert report["summary"]["hard_negative_or_stale"] == 1
    stale = report["buckets"]["hard_negative_or_stale"][0]
    assert stale["run_id"] == "old"
    assert "stale_duplicate_superseded" in stale["backfill"]["classification"]


def test_backfill_report_redacts_private_paths() -> None:
    report = exporter.audit_backfill([
        _row(
            project_id="missing-source",
            source_ids=[],
            source_urls=[],
            source_titles=[],
            artifact_root="/home/jeremy/private/project",
            artifact_paths=["/var/lib/enoch-control-plane/projects/x/.enoch/project_decision.json"],
        )
    ])

    serialized = json.dumps(report, sort_keys=True)

    assert "/home/jeremy" not in serialized
    assert "/var/lib/enoch-control-plane" not in serialized


def test_clean_rows_from_audit_can_be_exported_without_invalid_historical_rows(tmp_path) -> None:
    rows = [
        _row(project_id="clean-signal"),
        _row(project_id="missing-source", source_ids=[], source_urls=[], source_titles=[]),
        _row(project_id="hard-negative", research_outcome="negative"),
    ]

    result = exporter.write_export(exporter.clean_export_rows(rows), tmp_path)

    records = [json.loads(line) for line in (tmp_path / "data" / "signals.jsonl").read_text(encoding="utf-8").splitlines()]
    manifest = json.loads((tmp_path / "data" / "manifest.json").read_text(encoding="utf-8"))
    assert result["count"] == 2
    assert [record["project_id"] for record in records] == ["clean-signal", "missing-source"]
    assert manifest["selection_summary"]["export_cleanly_now"] == 2
    assert manifest["selection_summary"]["backfilled_exportable"] == 1
    assert manifest["selection_summary"]["missing_required_evidence_or_fields"] == 0
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
        "backfilled_exportable": 0,
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
    assert [record["project_id"] for record in records] == ["clean-signal", "missing-source"]
    assert manifest["selection_summary"]["backfilled_exportable"] == 1
    assert manifest["selection_summary"]["missing_required_evidence_or_fields"] == 0
