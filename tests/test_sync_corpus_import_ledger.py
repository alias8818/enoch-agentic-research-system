import json
from pathlib import Path

from scripts.sync_corpus_import_ledger import load_public_records, render_supabase_cli_sql, source_fingerprint


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
