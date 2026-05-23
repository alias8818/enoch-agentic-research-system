from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _latest_paper_eligibility_migration() -> Path:
    migrations = sorted((ROOT / "supabase" / "migrations").glob("*.sql"))
    matches = [
        path
        for path in migrations
        if "create or replace view enoch.paper_eligibility"
        in path.read_text(encoding="utf-8").lower()
    ]
    assert matches, "no paper_eligibility view migration found"
    return matches[-1]


def test_latest_paper_eligibility_prefers_current_run_decision() -> None:
    sql = _latest_paper_eligibility_migration().read_text(encoding="utf-8").lower()

    assert "select distinct on (q.project_id)" in sql
    assert "d.run_id = nullif(q.current_run_id, '')" in sql
    assert "case when d.run_id = nullif(q.current_run_id, '') then 0 else 1 end" in sql
    assert (
        "order by q.project_id, case when d.run_id = nullif(q.current_run_id, '') then 0 else 1 end,"
        in " ".join(sql.split())
    )


def test_latest_paper_eligibility_suppresses_papers_by_project_run_identity_only() -> (
    None
):
    sql = " ".join(
        _latest_paper_eligibility_migration()
        .read_text(encoding="utf-8")
        .lower()
        .split()
    )

    assert "has_project_paper_row" not in sql
    assert "as has_run_paper_row" in sql
    assert "paper.project_id = q.project_id and paper.run_id = q.current_run_id" in sql
    assert "not cb.has_run_paper_row" in sql
    assert "e.has_run_paper_row as has_live_paper_row" in sql
