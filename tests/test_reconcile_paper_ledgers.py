from scripts.reconcile_paper_ledgers import (
    DEFAULT_PAPER_STATUS,
    classify_finalized_rows,
    source_fingerprint,
)


def test_classify_finalized_rows_matches_default_import_behavior() -> None:
    exact_paper_id = "project-a:run-a:arxiv_draft"
    importable_paper_id = "project-c:run-c:arxiv_draft"
    public = {
        "by_fingerprint": {
            source_fingerprint(exact_paper_id): {"slug": "already-imported"},
        },
    }
    rows = [
        {
            "paper_id": exact_paper_id,
            "project_name": "Already Imported",
            "paper_status": "publication_draft",
            "review_status": "finalized",
        },
        {
            "paper_id": importable_paper_id,
            "project_name": "Brand New",
            "paper_status": "publication_draft",
            "review_status": "finalized",
        },
    ]

    classified = classify_finalized_rows(rows, public)

    assert [row["paper_id"] for row in classified["exact_existing"]] == [exact_paper_id]
    assert [row["paper_id"] for row in classified["importable"]] == [
        importable_paper_id
    ]


def test_default_reconciliation_scope_is_publication_draft_lane() -> None:
    assert DEFAULT_PAPER_STATUS == "publication_draft"
