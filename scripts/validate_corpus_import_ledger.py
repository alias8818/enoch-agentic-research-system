#!/usr/bin/env python3
"""Validate Supabase corpus_imports against the public corpus index.

This is the read-only counterpart to sync_corpus_import_ledger.py. It makes the
public corpus index the source of truth and fails if the live Supabase import
ledger has stale rows, missing public rows, or dashboard imported counts that no
longer match the public index.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

try:
    from sync_corpus_import_ledger import (
        DEFAULT_CORPUS_REPO,
        load_public_records,
        sql_literal,
    )
except (
    ModuleNotFoundError
):  # pragma: no cover - import path used by pytest/package context
    from scripts.sync_corpus_import_ledger import (
        DEFAULT_CORPUS_REPO,
        load_public_records,
        sql_literal,
    )


def render_validation_sql(
    *, corpus: Path, corpus_repo: str = DEFAULT_CORPUS_REPO
) -> str:
    records = load_public_records(corpus)
    if not records:
        raise ValueError(
            "no public corpus records with source_record_fingerprint found"
        )
    values = ",\n    ".join(
        "("
        + ",".join(
            sql_literal(value)
            for value in (
                record.source_record_fingerprint,
                record.artifact_slug,
                record.public_artifact_id,
            )
        )
        + ")"
        for record in records
    )
    return f"""set search_path to enoch, public;
create temp table tmp_public_index(
  source_record_fingerprint text,
  artifact_slug text,
  public_artifact_id text
) on commit drop;
insert into tmp_public_index(source_record_fingerprint, artifact_slug, public_artifact_id)
values
    {values};
select
  (select count(*) from tmp_public_index) as public_index_rows,
  (
    select count(*)
    from enoch.corpus_imports ci
    where ci.corpus_repo = {sql_literal(corpus_repo)}
  ) as corpus_imports_total,
  odc.corpus_imported as dashboard_corpus_imported,
  (
    select count(*)
    from enoch.corpus_imports ci
    where ci.corpus_repo = {sql_literal(corpus_repo)}
      and not exists (
        select 1
        from tmp_public_index pi
        where pi.source_record_fingerprint = ci.source_record_fingerprint
      )
  ) as stale_corpus_imports,
  (
    select count(*)
    from tmp_public_index pi
    where not exists (
      select 1
      from enoch.corpus_imports ci
      where ci.corpus_repo = {sql_literal(corpus_repo)}
        and ci.source_record_fingerprint = pi.source_record_fingerprint
    )
  ) as missing_public_records,
  odc.publication_ready,
  odc.publication_ready_total
from enoch.operator_dashboard_counts odc;
"""


def _run_supabase_query(sql_path: Path, *, linked: bool, db_url: str) -> dict[str, Any]:
    cmd = ["supabase", "db", "query", "-f", str(sql_path), "-o", "json"]
    if linked:
        cmd.insert(3, "--linked")
    elif db_url.strip():
        cmd[3:3] = ["--db-url", db_url]
    else:
        raise ValueError("use --linked or --db-url/ENOCH_SUPABASE_DATABASE_URL")
    result = subprocess.run(
        cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False
    )
    if result.returncode != 0:
        raise SystemExit(
            result.stdout.strip()
            or f"supabase query failed with exit code {result.returncode}"
        )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        start = result.stdout.find("{")
        end = result.stdout.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(result.stdout[start : end + 1])
            except json.JSONDecodeError:
                pass
        raise SystemExit(
            f"failed to parse supabase JSON output: {exc}\n{result.stdout}"
        ) from exc


def _is_postgres_url(db_url: str) -> bool:
    scheme = urlsplit(db_url.strip()).scheme.lower()
    return scheme in {"postgres", "postgresql"}


def _run_postgres_query(sql: str, *, db_url: str) -> dict[str, Any]:
    try:
        import psycopg
    except ModuleNotFoundError as exc:  # pragma: no cover - dependency guard
        raise SystemExit(
            "psycopg is required for direct Postgres ledger validation; "
            "run via `uv run` or install psycopg[binary]"
        ) from exc

    metrics: dict[str, Any] | None = None
    with psycopg.connect(db_url, connect_timeout=10) as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql)
            while True:
                if cursor.description:
                    row = cursor.fetchone()
                    if row is not None:
                        columns = [column.name for column in cursor.description]
                        metrics = dict(zip(columns, row, strict=True))
                if not cursor.nextset():
                    break
    if metrics is None:
        raise SystemExit("ledger validation query returned no rows")
    return {"rows": [metrics]}


def _run_validation_query(
    sql: str, sql_path: Path, *, linked: bool, db_url: str
) -> dict[str, Any]:
    if not linked and _is_postgres_url(db_url):
        return _run_postgres_query(sql, db_url=db_url)
    return _run_supabase_query(sql_path, linked=linked, db_url=db_url)


def validate_metrics(row: dict[str, Any]) -> list[str]:
    public_rows = int(row.get("public_index_rows") or 0)
    imports_total = int(row.get("corpus_imports_total") or 0)
    dashboard_imported = int(row.get("dashboard_corpus_imported") or 0)
    stale = int(row.get("stale_corpus_imports") or 0)
    missing = int(row.get("missing_public_records") or 0)
    failures: list[str] = []
    if imports_total != public_rows:
        failures.append(
            f"corpus_imports_total {imports_total} != public_index_rows {public_rows}"
        )
    if dashboard_imported != public_rows:
        failures.append(
            f"dashboard_corpus_imported {dashboard_imported} != public_index_rows {public_rows}"
        )
    if stale != 0:
        failures.append(f"stale_corpus_imports {stale} != 0")
    if missing != 0:
        failures.append(f"missing_public_records {missing} != 0")
    return failures


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--corpus", type=Path, default=Path("../enoch-ai-research-corpus")
    )
    parser.add_argument("--corpus-repo", default=DEFAULT_CORPUS_REPO)
    parser.add_argument(
        "--linked",
        action="store_true",
        help="Run validation against the linked Supabase project",
    )
    parser.add_argument(
        "--db-url", default=os.environ.get("ENOCH_SUPABASE_DATABASE_URL", "")
    )
    parser.add_argument(
        "--sql-output", type=Path, help="Write validation SQL instead of running it"
    )
    parser.add_argument(
        "--report-json", type=Path, help="Write validation metrics JSON"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    sql = render_validation_sql(corpus=args.corpus, corpus_repo=args.corpus_repo)
    if args.sql_output:
        args.sql_output.write_text(sql, encoding="utf-8")
        print(
            json.dumps(
                {"ok": True, "sql_output": str(args.sql_output)},
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    with tempfile.TemporaryDirectory(prefix="enoch-ledger-validate-") as tmp:
        sql_path = Path(tmp) / "validate-corpus-import-ledger.sql"
        sql_path.write_text(sql, encoding="utf-8")
        payload = _run_validation_query(
            sql,
            sql_path,
            linked=bool(args.linked),
            db_url=str(args.db_url or ""),
        )
    rows = payload.get("rows") or []
    if not rows:
        raise SystemExit("ledger validation query returned no rows")
    metrics = dict(rows[0])
    failures = validate_metrics(metrics)
    report = {"ok": not failures, "metrics": metrics, "failures": failures}
    if args.report_json:
        args.report_json.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    print(json.dumps(report, indent=2, sort_keys=True))
    if failures:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
