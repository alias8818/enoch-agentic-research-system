import json
from pathlib import Path

from scripts.sync_corpus_import_ledger import (
    load_public_records,
    match_public_records_to_live_papers,
    render_supabase_cli_sql,
    source_fingerprint,
)
from scripts.validate_corpus_import_ledger import render_validation_sql, validate_metrics


def test_source_fingerprint_matches_public_corpus_contract() -> None:
    assert source_fingerprint("paper-1") == "dbb6181095c94272"


def test_load_public_records_dedupes_fingerprints_and_derives_manifest(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    (corpus / "papers").mkdir(parents=True)
    (corpus / "papers" / "index.json").write_text(
        json.dumps(
            {
                "papers": [
                    {"source_record_fingerprint": "fp1", "slug": "paper-one", "public_id": "enoch-paper-0001"},
                    {"source_record_fingerprint": "fp1", "slug": "duplicate"},
                    {"source_record_fingerprint": "", "slug": "missing-fp"},
                ]
            }
        ),
        encoding="utf-8",
    )

    records = load_public_records(corpus)

    assert len(records) == 1
    assert records[0].source_record_fingerprint == "fp1"
    assert records[0].artifact_slug == "paper-one"
    assert records[0].public_artifact_id == "enoch-paper-0001"
    assert records[0].public_manifest_path == "papers/paper-one/paper_manifest.json"


def test_render_supabase_cli_sql_escapes_values(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    (corpus / "papers").mkdir(parents=True)
    (corpus / "papers" / "index.json").write_text(
        json.dumps({"papers": [{"source_record_fingerprint": "fp1", "slug": "paper's-one", "public_id": "id"}]}),
        encoding="utf-8",
    )
    records = load_public_records(corpus)

    sql = render_supabase_cli_sql(records)

    assert "paper''s-one" in sql
    assert "on conflict (paper_id, corpus_repo) do update" in sql
    assert "operator_dashboard_counts" in sql


def test_render_supabase_cli_sql_scopes_import_totals_to_corpus_repo(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    (corpus / "papers").mkdir(parents=True)
    (corpus / "papers" / "index.json").write_text(
        json.dumps({"papers": [{"source_record_fingerprint": "fp1", "slug": "paper-one", "public_id": "id"}]}),
        encoding="utf-8",
    )
    records = load_public_records(corpus)

    sql = render_supabase_cli_sql(records, corpus_repo="custom-corpus")

    assert "where ci.corpus_repo = 'custom-corpus'" in sql
    assert "as corpus_imports_total" in sql
    total_expr = sql.split("as corpus_imports_total", 1)[0].rsplit("(", 1)[-1]
    assert "where ci.corpus_repo = 'custom-corpus'" in total_expr


def test_render_supabase_cli_sql_can_prune_stale_rows_and_roll_back(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    (corpus / "papers").mkdir(parents=True)
    (corpus / "papers" / "index.json").write_text(
        json.dumps({"papers": [{"source_record_fingerprint": "fp1", "slug": "paper-one", "public_id": "id"}]}),
        encoding="utf-8",
    )
    records = load_public_records(corpus)

    sql = render_supabase_cli_sql(records, prune_stale=True, rollback=True)

    assert sql.startswith("begin;\n")
    assert "delete from enoch.corpus_imports ci" in sql
    assert "not exists (" in sql
    assert "tmp_pruned_rows" in sql
    assert "stale_corpus_imports" in sql
    assert "missing_public_records" in sql
    assert sql.rstrip().endswith("rollback;")


def test_match_public_records_to_live_papers_uses_python_fingerprint() -> None:
    paper_id = "paper-1"
    records = [
        type("Record", (), {
            "source_record_fingerprint": source_fingerprint(paper_id),
            "artifact_slug": "paper-one",
            "public_artifact_id": "enoch-paper-0001",
            "public_manifest_path": "papers/paper-one/paper_manifest.json",
        })(),
        type("Record", (), {
            "source_record_fingerprint": "no-match",
            "artifact_slug": "other",
            "public_artifact_id": "enoch-paper-0002",
            "public_manifest_path": "papers/other/paper_manifest.json",
        })(),
    ]

    matched = match_public_records_to_live_papers([paper_id, "unpublished"], records)

    assert len(matched) == 1
    assert matched[0].paper_id == paper_id
    assert matched[0].artifact_slug == "paper-one"


def test_validate_corpus_import_ledger_sql_checks_stale_and_missing(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    (corpus / "papers").mkdir(parents=True)
    (corpus / "papers" / "index.json").write_text(
        json.dumps({"papers": [{"source_record_fingerprint": "fp1", "slug": "paper-one", "public_id": "id"}]}),
        encoding="utf-8",
    )

    sql = render_validation_sql(corpus=corpus)

    assert "stale_corpus_imports" in sql
    assert "missing_public_records" in sql
    assert "dashboard_corpus_imported" in sql
    assert "corpus_imports_total" in sql


def test_validate_corpus_import_ledger_metrics_fail_on_drift() -> None:
    failures = validate_metrics(
        {
            "public_index_rows": 376,
            "corpus_imports_total": 493,
            "dashboard_corpus_imported": 493,
            "stale_corpus_imports": 117,
            "missing_public_records": 1,
        }
    )

    assert "corpus_imports_total 493 != public_index_rows 376" in failures
    assert "dashboard_corpus_imported 493 != public_index_rows 376" in failures
    assert "stale_corpus_imports 117 != 0" in failures
    assert "missing_public_records 1 != 0" in failures
