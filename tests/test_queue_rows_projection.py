from __future__ import annotations

import inspect
import tempfile
from pathlib import Path

from enoch_control_plane.control_plane.store import ControlPlaneStore
from enoch_control_plane.control_plane.supabase_store import SupabaseControlPlaneStore


def test_sqlite_queue_rows_uses_one_ranked_paper_projection() -> None:
    source = inspect.getsource(ControlPlaneStore.queue_rows)

    assert "WITH scoped_papers AS" in source
    assert "ROW_NUMBER() OVER" in source
    assert "LEFT JOIN scoped_papers" in source
    assert "(SELECT pa." not in source
    assert "FROM papers pa LEFT JOIN" not in source


def test_supabase_queue_rows_uses_lateral_related_projection() -> None:
    query = SupabaseControlPlaneStore(
        "postgresql://example.invalid/postgres", connect=lambda: None
    )._queue_rows_query("order by q.updated_at desc")  # noqa: SLF001 - query-shape regression

    assert "left join lateral" in query.lower()
    assert "paq.paper_id as related_paper_id" in query
    assert "select pa.paper_id" not in query.lower()
    assert "select rv.automation_status" not in query.lower()
    assert "select ci.corpus_import_id" not in query.lower()
    assert "from corpus_imports ci" in query.lower()
    assert "limit 1" in query.lower()
    assert "from project_decisions d" in query


def test_sqlite_queue_rows_preserves_related_paper_projection_semantics() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        store = ControlPlaneStore(Path(tmp) / "control.sqlite3")
        with store._connect() as conn:  # noqa: SLF001 - projection regression fixture
            conn.execute(
                """
                insert into projects(project_id, project_name, project_dir, notion_page_url, notion_page_id, origin_idea_status, created_at, updated_at)
                values ('project-1', 'Project One', '/tmp/project-1', '', '', 'exploring', '2026-06-22T00:00:00Z', '2026-06-22T00:00:00Z')
                """
            )
            conn.execute(
                """
                insert into queue_items(project_id, status, selection_rank, dispatch_priority, auto_continue, continue_count, max_continues, retry_count, max_retries, current_run_id, current_session_id, last_run_state, last_event_type, next_action_hint, manual_review_required, blocked_reason, last_error, last_result_summary, machine_target, model, sandbox, updated_at)
                values ('project-1', 'running', 1, 1, 0, 0, 0, 0, 0, 'run-current', '', '', '', '', 0, '', '', '', '', '', '', '2026-06-22T00:00:00Z')
                """
            )
            conn.execute(
                """
                insert into papers(paper_id, project_id, run_id, paper_type, paper_status, draft_markdown_path, draft_latex_path, evidence_bundle_path, claim_ledger_path, manifest_path, generated_at, updated_at)
                values ('paper-stale', 'project-1', 'run-stale', 'arxiv_draft', 'stale', 'stale.md', '', 'stale-evidence.json', 'stale-claims.json', 'stale-manifest.json', '2026-06-22T00:00:00Z', '2026-06-22T00:10:00Z')
                """
            )
            conn.execute(
                """
                insert into papers(paper_id, project_id, run_id, paper_type, paper_status, draft_markdown_path, draft_latex_path, evidence_bundle_path, claim_ledger_path, manifest_path, generated_at, updated_at)
                values ('paper-current', 'project-1', 'run-current', 'arxiv_draft', 'publication_draft', 'draft.md', '', 'evidence.json', 'claims.json', 'manifest.json', '2026-06-22T00:00:00Z', '2026-06-22T00:01:00Z')
                """
            )
            conn.execute(
                """
                insert into paper_review_items(paper_id, review_status, reviewer, blocker, checklist_json, rank_score, rank_reasons_json, missing_signals_json, rank_tiebreaker, source_audit_path, finalization_package_path, finalized_at, decision_summary, created_at, updated_at)
                values ('paper-current', 'approved_for_finalization', '', '', '{}', 10, '[]', '[]', '', '', 'package/final.json', '', '', '2026-06-22T00:00:00Z', '2026-06-22T00:00:00Z')
                """
            )
            conn.execute(
                """
                insert into corpus_imports(paper_id, corpus_repo, artifact_slug, source_record_fingerprint, imported_at, created_at)
                values ('paper-current', 'repo', 'artifact-current', 'fingerprint-current', '2026-06-22T00:00:00Z', '2026-06-22T00:00:00Z')
                """
            )
            conn.execute(
                """
                insert into corpus_imports(paper_id, corpus_repo, artifact_slug, source_record_fingerprint, imported_at, created_at)
                values ('paper-current', 'other-repo', 'artifact-newer', 'fingerprint-newer', '2026-06-22T00:05:00Z', '2026-06-22T00:05:00Z')
                """
            )

        rows = store.queue_rows()

        assert len(rows) == 1
        row = rows[0]
        assert row["related_paper_id"] == "paper-current"
        assert row["related_paper_status"] == "publication_draft"
        assert row["related_review_status"] == "approved_for_finalization"
        assert row["related_finalization_package_path"] == "package/final.json"
        assert row["related_artifact_slug"] == "artifact-newer"
        assert row["related_source_record_fingerprint"] == "fingerprint-newer"
        assert row["related_corpus_imported"] == 1
