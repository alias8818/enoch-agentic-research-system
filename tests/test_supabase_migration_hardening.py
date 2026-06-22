from __future__ import annotations

import re
from pathlib import Path


MIGRATIONS = Path("supabase/migrations")


def _migration(name: str) -> str:
    return (MIGRATIONS / name).read_text(encoding="utf-8")


def _function_definitions(sql: str) -> list[str]:
    pattern = re.compile(
        r"create\s+or\s+replace\s+function\s+.*?\$\$\s*;",
        re.IGNORECASE | re.DOTALL,
    )
    return pattern.findall(sql)


def test_trigger_functions_pin_search_path() -> None:
    offenders: list[str] = []
    for migration in MIGRATIONS.glob("*.sql"):
        for definition in _function_definitions(migration.read_text(encoding="utf-8")):
            if "set search_path" not in definition.lower():
                first_line = definition.strip().splitlines()[0]
                offenders.append(f"{migration.name}: {first_line}")

    assert offenders == []


def test_duplicate_state_contract_migration_is_transactional_and_parseable() -> None:
    sql = _migration("20260506183300_enforce_remaining_state_contract_surfaces.sql")

    assert re.search(r"^begin;", sql, flags=re.IGNORECASE | re.MULTILINE)
    assert re.search(r"^commit;", sql, flags=re.IGNORECASE | re.MULTILINE)
    assert ";;" not in sql


def test_publication_status_constraint_drop_targets_column_not_substring() -> None:
    sql = _migration("20260506103218_enoch_publication_status_parity.sql").lower()

    assert "pg_get_constraintdef" not in sql
    assert "a.attname = 'automation_status'" in sql
    assert "a.attnum = any(c.conkey)" in sql


def test_research_source_kind_rewrites_are_single_atomic_alter_statements() -> None:
    for name in [
        "20260519122000_research_lineage_followup_parent_source.sql",
        "20260520003500_research_synthesis_source_kind.sql",
    ]:
        sql = " ".join(_migration(name).lower().split())
        assert (
            "alter table enoch.research_sources "
            "drop constraint if exists research_sources_source_kind_check, "
            "add constraint research_sources_source_kind_check"
        ) in sql


def test_latest_research_source_kind_constraint_preserves_prior_values() -> None:
    initial = _migration("20260509140339_enoch_research_facility_ledgers.sql")
    followup = _migration("20260519122000_research_lineage_followup_parent_source.sql")
    latest = _migration("20260520003500_research_synthesis_source_kind.sql")

    def values(sql: str) -> set[str]:
        match = re.search(
            r"research_sources_source_kind_check.*?source_kind\s+in\s*\((.*?)\)\s*\)",
            sql,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if match is None:
            match = re.search(
                r"source_kind\s+text\s+not\s+null\s+check\s*\(source_kind\s+in\s*\((.*?)\)\)",
                sql,
                flags=re.IGNORECASE | re.DOTALL,
            )
        assert match is not None
        return set(re.findall(r"'([^']+)'", match.group(1)))

    assert values(initial) <= values(latest)
    assert values(followup) <= values(latest)
    assert "research_synthesis" in values(latest)


def test_corpus_import_fingerprint_migration_uses_bounded_backfill_and_concurrent_indexes() -> (
    None
):
    sql = _migration("20260506215306_enoch_corpus_import_ledger_publish_counts.sql")
    normalized = " ".join(sql.lower().split())

    assert "set local statement_timeout = '60s'" in normalized
    assert "set local lock_timeout = '5s'" in normalized
    assert "limit 1000" in normalized
    assert "get diagnostics rows_updated = row_count" in normalized
    assert "raise exception" in normalized
    assert "paper_id ||" in normalized
    assert "|| corpus_repo" in normalized
    assert "digest(paper_id, 'sha256')" not in normalized
    assert (
        "create unique index concurrently if not exists "
        "idx_corpus_imports_source_fingerprint"
    ) in normalized
    assert (
        "create index concurrently if not exists idx_corpus_imports_hf_dataset_synced"
    ) in normalized


def test_followup_branching_migration_uses_safe_locks_and_concurrent_index() -> None:
    sql = _migration("20260507222145_enoch_followup_branching.sql")
    normalized = " ".join(sql.lower().split())

    assert "set local statement_timeout = '60s'" in normalized
    assert "set local lock_timeout = '5s'" in normalized
    assert "add column if not exists followup_type text default ''" in normalized
    assert "followup_type text not null default" not in normalized
    assert "add constraint project_decisions_followup_type_check" in normalized
    assert "not valid" in normalized
    assert "validate constraint project_decisions_followup_type_check" in normalized
    assert (
        "commit; set statement_timeout = '60s'; set lock_timeout = '5s'; "
        "create index concurrently if not exists idx_project_decisions_followup"
    ) in normalized
