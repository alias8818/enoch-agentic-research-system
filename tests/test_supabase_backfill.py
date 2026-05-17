from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.backfill_control_plane_to_supabase import json_text, stable_hash, valid_hash, import_sqlite_to_postgres


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
