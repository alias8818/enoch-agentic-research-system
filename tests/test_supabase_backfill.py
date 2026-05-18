from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from scripts import backfill_control_plane_to_supabase
from scripts.backfill_control_plane_to_supabase import (
    import_sqlite_to_postgres,
    json_text,
    reject_target_identity_conflicts,
    stable_hash,
    valid_hash,
)


def test_json_text_normalizes_invalid_or_empty_payloads() -> None:
    assert json_text("", {}) == "{}"
    assert json_text("not json", []) == "[]"
    assert json_text({"b": 2, "a": 1}, {}) == '{"a":1,"b":2}'


def test_valid_hash_preserves_valid_sha256_and_replaces_invalid() -> None:
    valid = "a" * 64
    assert valid_hash(valid, "{}") == valid
    replacement = valid_hash("not-a-hash", json.dumps({"ok": True}))
    assert replacement == stable_hash(json.dumps({"ok": True}))
    assert len(replacement) == 64


def test_reset_target_requires_apply(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="--reset-target requires --apply"):
        import_sqlite_to_postgres(
            sqlite_path=tmp_path / "missing.sqlite3",
            database_url="postgresql://example.invalid/postgres",
            apply=False,
            reset_target=True,
            observation_limit=0,
        )


def test_backfill_rows_rejects_unallowlisted_table_name(tmp_path: Path) -> None:
    import sqlite3
    from scripts.backfill_control_plane_to_supabase import rows

    db = tmp_path / "state.sqlite3"
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("create table projects(project_id text)")
        with pytest.raises(ValueError, match="unsupported sqlite table"):
            rows(conn, "projects; drop table projects")


def test_backfill_rows_rejects_unallowlisted_order_by(tmp_path: Path) -> None:
    import sqlite3
    from scripts.backfill_control_plane_to_supabase import rows

    db = tmp_path / "state.sqlite3"
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("create table projects(project_id text)")
        with pytest.raises(ValueError, match="unsupported sqlite order_by"):
            rows(conn, "projects", order_by="project_id desc; drop table projects")


class _FakeCursor:
    def __init__(self, existing: dict[str, object] | None) -> None:
        self.existing = existing
        self.queries: list[tuple[str, tuple[object, ...]]] = []

    def execute(self, sql: str, params: tuple[object, ...]) -> "_FakeCursor":
        self.queries.append((sql, params))
        return self

    def fetchone(self) -> dict[str, object] | None:
        return self.existing


def test_backfill_target_identity_guard_rejects_existing_paper_drift() -> None:
    cur = _FakeCursor({"project_id": "project-a", "run_id": "run-a", "paper_type": "arxiv_draft"})

    with pytest.raises(ValueError, match="conflicting target papers identity"):
        reject_target_identity_conflicts(
            cur,
            table="papers",
            key_columns=("paper_id",),
            identity_columns=("project_id", "run_id", "paper_type"),
            source_rows=[
                {
                    "paper_id": "paper-1",
                    "project_id": "project-a",
                    "run_id": "run-b",
                    "paper_type": "arxiv_draft",
                }
            ],
        )


def test_backfill_target_identity_guard_allows_same_existing_identity() -> None:
    cur = _FakeCursor({"project_id": "project-a"})

    reject_target_identity_conflicts(
        cur,
        table="runs",
        key_columns=("run_id",),
        identity_columns=("project_id",),
        source_rows=[{"run_id": "run-a", "project_id": "project-a"}],
    )

    assert cur.queries
    assert "from runs" in cur.queries[0][0]
    assert cur.queries[0][1] == ("run-a",)


def test_backfill_conflict_updates_are_timestamp_guarded() -> None:
    source = inspect.getsource(backfill_control_plane_to_supabase.import_sqlite_to_postgres)

    for nullable_guard in (
        "control_flags.updated_at is null or excluded.updated_at >= control_flags.updated_at",
        "projects.updated_at is null or excluded.updated_at >= projects.updated_at",
        "queue_items.updated_at is null or excluded.updated_at >= queue_items.updated_at",
        "runs.updated_at is null or excluded.updated_at >= runs.updated_at",
        "papers.updated_at is null or excluded.updated_at >= papers.updated_at",
        "publication_automation_items.updated_at is null or excluded.updated_at >= publication_automation_items.updated_at",
    ):
        assert nullable_guard in source


def test_backfill_project_decision_conflict_update_is_decided_at_guarded() -> None:
    source = inspect.getsource(backfill_control_plane_to_supabase.import_sqlite_to_postgres)

    assert "where project_decisions.decided_at is null or excluded.decided_at >= project_decisions.decided_at" in source
