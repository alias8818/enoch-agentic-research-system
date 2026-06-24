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


def test_research_lineage_source_constraint_rewrites_use_versioned_names() -> None:
    guarded_constraints = {
        "research_sources_source_kind_check",
        "research_lineage_relation_type_check",
    }
    offenders: list[str] = []

    for migration in MIGRATIONS.glob("*.sql"):
        sql = migration.read_text(encoding="utf-8")
        dropped = set(
            re.findall(
                r"drop\s+constraint\s+if\s+exists\s+([a-zA-Z_][a-zA-Z0-9_]*)",
                sql,
                flags=re.IGNORECASE,
            )
        )
        added = set(
            re.findall(
                r"add\s+constraint\s+([a-zA-Z_][a-zA-Z0-9_]*)",
                sql,
                flags=re.IGNORECASE,
            )
        )
        for constraint in sorted((dropped & added) & guarded_constraints):
            offenders.append(f"{migration.name}: {constraint}")

    assert offenders == []


def test_research_lineage_source_constraint_widening_validates_existing_rows() -> None:
    for name in [
        "20260519122000_research_lineage_followup_parent_source.sql",
        "20260519190000_research_synthesis_lineage.sql",
        "20260520003500_research_synthesis_source_kind.sql",
    ]:
        sql = " ".join(_migration(name).lower().split())
        assert "if exists ( select 1 from enoch.research_" in sql
        assert "raise exception" in sql


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


def test_research_lineage_identity_is_unique_before_conflict_inserts() -> None:
    initial = " ".join(
        _migration("20260509140339_enoch_research_facility_ledgers.sql").lower().split()
    )
    hardening = " ".join(
        _migration("20260520004500_research_lineage_idempotency.sql").lower().split()
    )

    unique_index = (
        "create unique index concurrently if not exists "
        "idx_research_lineage_identity_unique on "
        "enoch.research_lineage(source_type, source_id, target_type, target_id, relation_type)"
    )
    assert unique_index in initial
    assert unique_index in hardening
    assert (
        "partition by source_type, source_id, target_type, target_id, relation_type"
        in hardening
    )


def test_native_idea_event_backfill_uses_unique_conflict_guard() -> None:
    sql = " ".join(_migration("20260506122514_enoch_native_ideas.sql").lower().split())

    assert "idx_idea_events_native_migration_once" in sql
    assert (
        "insert into enoch.idea_events(idea_id, event_type, actor, payload_json)" in sql
    )
    assert "on conflict do nothing" in sql


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


def test_migrations_do_not_create_blanket_service_role_all_policies() -> None:
    offenders: list[str] = []
    for migration in MIGRATIONS.glob("*.sql"):
        normalized = " ".join(migration.read_text(encoding="utf-8").lower().split())
        if "create policy service_role_all" in normalized:
            offenders.append(migration.name)
        if "using (true) with check (true)" in normalized:
            offenders.append(f"{migration.name}: using true")

    assert offenders == []


def test_service_role_all_cleanup_migration_drops_existing_blanket_policies() -> None:
    sql = _migration("20260624044500_drop_service_role_all_policies.sql")
    normalized = " ".join(sql.lower().split())

    assert "begin;" in normalized
    assert normalized.endswith("commit;")
    assert "from pg_tables" in normalized
    assert "where schemaname = 'enoch'" in normalized
    assert "drop policy if exists service_role_all on enoch.%i" in normalized
    assert "create policy service_role_all" not in normalized


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


def test_dashboard_read_model_indexes_build_concurrently_outside_transaction() -> None:
    sql = _migration("20260506232438_enoch_dashboard_read_model_indexes.sql")
    normalized = " ".join(sql.lower().split())

    assert "begin;" not in normalized
    assert "set statement_timeout = '30min'" in normalized
    assert "set lock_timeout = '30s'" in normalized
    assert normalized.count("create index concurrently if not exists") == 7
    assert "create index if not exists" not in normalized


def test_research_facility_indexes_build_concurrently_after_schema_transaction() -> (
    None
):
    sql = _migration("20260509140339_enoch_research_facility_ledgers.sql")
    normalized = " ".join(sql.lower().split())

    assert "set local statement_timeout = '5min'" in normalized
    assert "set local lock_timeout = '30s'" in normalized
    assert (
        "commit; set statement_timeout = '30min'; set lock_timeout = '30s'"
        in normalized
    )
    assert normalized.count("create index concurrently if not exists") == 6
    assert normalized.count("create unique index concurrently if not exists") == 3
    assert "create index if not exists idx_research" not in normalized
    assert "create unique index if not exists idx_research" not in normalized


def test_research_janitor_status_constraint_migration_is_transactional() -> None:
    sql = _migration("20260515001000_research_candidate_janitor_statuses.sql")
    normalized = " ".join(sql.lower().split())

    assert normalized.startswith("begin; set local statement_timeout = '5min'")
    assert "set local lock_timeout = '30s'" in normalized
    assert normalized.endswith("commit;")


def test_native_ideas_indexes_are_concurrent_and_backfill_is_separate() -> None:
    sql = _migration("20260506122514_enoch_native_ideas.sql")
    normalized = " ".join(sql.lower().split())

    assert "set local statement_timeout = '5min'" in normalized
    assert "set local lock_timeout = '30s'" in normalized
    assert (
        "commit; set statement_timeout = '30min'; set lock_timeout = '30s'"
        in normalized
    )
    assert normalized.count("create index concurrently if not exists idx_idea") == 3
    assert "create index if not exists idx_idea" not in normalized
    assert (
        "reset statement_timeout; begin; set local statement_timeout = '5min'; "
        "set local lock_timeout = '30s'; -- backfill native ideas"
    ) in normalized
    assert "on conflict (idea_id) do update set" not in normalized
    assert (
        "from latest_rows lr where lr.idea_id <> '' on conflict (idea_id) do nothing"
        in normalized
    )
