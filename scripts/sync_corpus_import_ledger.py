#!/usr/bin/env python3
"""Sync Supabase corpus_imports from the public corpus index.

This is the deterministic bridge between public release evidence and the
operator dashboard. It matches public corpus rows to live paper rows by the
same source-record fingerprint used by the public corpus index. By default the
transaction rolls back; pass --apply to persist ledger rows.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_CORPUS_REPO = "enoch-ai-research-corpus"
DEFAULT_HF_DATASET_URL = "https://huggingface.co/datasets/aliasocracy/enoch-ai-research-corpus"


@dataclass(frozen=True)
class PublicCorpusRecord:
    source_record_fingerprint: str
    artifact_slug: str
    public_artifact_id: str
    public_manifest_path: str


@dataclass(frozen=True)
class MatchedCorpusRecord:
    paper_id: str
    source_record_fingerprint: str
    artifact_slug: str
    public_artifact_id: str
    public_manifest_path: str


def source_fingerprint(paper_id: str) -> str:
    return hashlib.sha256(paper_id.encode("utf-8")).hexdigest()[:16]


def _text(value: Any) -> str:
    return str(value or "").strip()


def load_public_records(corpus: Path) -> list[PublicCorpusRecord]:
    index_path = corpus / "papers" / "index.json"
    payload = json.loads(index_path.read_text(encoding="utf-8"))
    records: list[PublicCorpusRecord] = []
    seen: set[str] = set()
    for row in payload.get("papers") or []:
        fp = _text(row.get("source_record_fingerprint"))
        if not fp or fp in seen:
            continue
        slug = _text(row.get("slug"))
        manifest = _text(row.get("manifest_path")) or (f"papers/{slug}/paper_manifest.json" if slug else "")
        records.append(
            PublicCorpusRecord(
                source_record_fingerprint=fp,
                artifact_slug=slug,
                public_artifact_id=_text(row.get("public_id")),
                public_manifest_path=manifest,
            )
        )
        seen.add(fp)
    return records


def _connect(database_url: str) -> Any:
    import psycopg
    from psycopg.rows import dict_row

    return psycopg.connect(database_url, row_factory=dict_row)


def match_public_records_to_live_papers(paper_ids: list[str], records: list[PublicCorpusRecord]) -> list[MatchedCorpusRecord]:
    records_by_fingerprint = {record.source_record_fingerprint: record for record in records}
    matched: list[MatchedCorpusRecord] = []
    seen: set[str] = set()
    for paper_id in paper_ids:
        fingerprint = source_fingerprint(paper_id)
        record = records_by_fingerprint.get(fingerprint)
        if not record or paper_id in seen:
            continue
        matched.append(
            MatchedCorpusRecord(
                paper_id=paper_id,
                source_record_fingerprint=record.source_record_fingerprint,
                artifact_slug=record.artifact_slug,
                public_artifact_id=record.public_artifact_id,
                public_manifest_path=record.public_manifest_path,
            )
        )
        seen.add(paper_id)
    return matched


def sync_records(
    *,
    database_url: str,
    records: list[PublicCorpusRecord],
    corpus_repo: str = DEFAULT_CORPUS_REPO,
    hf_dataset_url: str = DEFAULT_HF_DATASET_URL,
    apply: bool = False,
) -> dict[str, Any]:
    if not records:
        raise ValueError("no public corpus records with source_record_fingerprint found")
    with _connect(database_url) as conn:
        try:
            with conn.cursor() as cur:
                cur.execute("set search_path to enoch, public")
                cur.execute("select paper_id from enoch.papers")
                live_paper_ids = [str(row["paper_id"] or "") for row in cur.fetchall()]
                matched_records = match_public_records_to_live_papers(live_paper_ids, records)
                cur.execute(
                    """
                    create temp table tmp_public_index(
                      paper_id text,
                      source_record_fingerprint text,
                      artifact_slug text,
                      public_artifact_id text,
                      public_manifest_path text
                    ) on commit drop
                    """
                )
                cur.executemany(
                    """
                    insert into tmp_public_index(
                      paper_id, source_record_fingerprint, artifact_slug, public_artifact_id, public_manifest_path
                    ) values (%s, %s, %s, %s, %s)
                    """,
                    [
                        (
                            record.paper_id,
                            record.source_record_fingerprint,
                            record.artifact_slug,
                            record.public_artifact_id,
                            record.public_manifest_path,
                        )
                        for record in matched_records
                    ],
                )
                cur.execute(
                    """
                    with matched as (
                      select
                        p.paper_id,
                        %s::text as corpus_repo,
                        pi.artifact_slug,
                        ''::text as commit_sha,
                        pi.public_manifest_path as manifest_path,
                        ''::text as manifest_hash,
                        pi.source_record_fingerprint,
                        pi.public_artifact_id,
                        'papers/index.json'::text as public_index_path,
                        true as hf_dataset_synced,
                        %s::text as hf_dataset_url
                      from enoch.papers p
                      join tmp_public_index pi
                        on pi.paper_id = p.paper_id
                    )
                    insert into enoch.corpus_imports(
                      paper_id, corpus_repo, artifact_slug, commit_sha, manifest_path, manifest_hash,
                      source_record_fingerprint, public_artifact_id, public_index_path, hf_dataset_synced,
                      hf_dataset_url, imported_at
                    )
                    select
                      paper_id, corpus_repo, artifact_slug, commit_sha, manifest_path, manifest_hash,
                      source_record_fingerprint, public_artifact_id, public_index_path, hf_dataset_synced,
                      hf_dataset_url, now()
                    from matched
                    on conflict (paper_id, corpus_repo) do update set
                      artifact_slug = excluded.artifact_slug,
                      commit_sha = excluded.commit_sha,
                      manifest_path = excluded.manifest_path,
                      manifest_hash = excluded.manifest_hash,
                      source_record_fingerprint = excluded.source_record_fingerprint,
                      public_artifact_id = excluded.public_artifact_id,
                      public_index_path = excluded.public_index_path,
                      hf_dataset_synced = excluded.hf_dataset_synced,
                      hf_dataset_url = excluded.hf_dataset_url
                    """,
                    (corpus_repo, hf_dataset_url),
                )
                changed = cur.rowcount
                cur.execute(
                    """
                    select
                      %s::integer as public_index_rows,
                      (select count(*) from tmp_public_index) as matched_public_index_rows,
                      (
                        select count(*)
                        from enoch.papers p
                        join tmp_public_index pi
                          on pi.paper_id = p.paper_id
                      ) as matched_live_papers,
                      (select count(*) from enoch.corpus_imports) as corpus_imports_total,
                      odc.publication_ready,
                      odc.publication_ready_total,
                      odc.corpus_imported,
                      odc.hf_dataset_synced
                    from enoch.operator_dashboard_counts odc
                    """,
                    (len(records),),
                )
                summary = dict(cur.fetchone() or {})
                summary["changed_rows"] = int(changed or 0)
                summary["mode"] = "apply" if apply else "dry-run"
            if apply:
                conn.commit()
                summary["committed"] = True
            else:
                conn.rollback()
                summary["committed"] = False
            return summary
        except Exception:
            conn.rollback()
            raise


def sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def render_supabase_cli_sql(
    records: list[PublicCorpusRecord],
    *,
    corpus_repo: str = DEFAULT_CORPUS_REPO,
    hf_dataset_url: str = DEFAULT_HF_DATASET_URL,
) -> str:
    """Render the same sync as SQL for `supabase db query --linked -f`."""

    if not records:
        raise ValueError("no public corpus records with source_record_fingerprint found")
    values = ",\n    ".join(
        "("
        + ",".join(
            sql_literal(value)
            for value in (
                record.source_record_fingerprint,
                record.artifact_slug,
                record.public_artifact_id,
                record.public_manifest_path,
            )
        )
        + ")"
        for record in records
    )
    return f"""set search_path to enoch, public;
create temp table tmp_public_index(
  source_record_fingerprint text,
  artifact_slug text,
  public_artifact_id text,
  public_manifest_path text
) on commit drop;
-- SQL output mode requires pgcrypto access because it cannot prefetch live paper IDs in Python.
insert into tmp_public_index(source_record_fingerprint, artifact_slug, public_artifact_id, public_manifest_path)
values
    {values};
with matched as (
  select
    p.paper_id,
    {sql_literal(corpus_repo)}::text as corpus_repo,
    pi.artifact_slug,
    ''::text as commit_sha,
    pi.public_manifest_path as manifest_path,
    ''::text as manifest_hash,
    pi.source_record_fingerprint,
    pi.public_artifact_id,
    'papers/index.json'::text as public_index_path,
    true as hf_dataset_synced,
    {sql_literal(hf_dataset_url)}::text as hf_dataset_url
  from enoch.papers p
  join tmp_public_index pi
    on pi.source_record_fingerprint = left(encode(extensions.digest(p.paper_id, 'sha256'), 'hex'), 16)
)
insert into enoch.corpus_imports(
  paper_id, corpus_repo, artifact_slug, commit_sha, manifest_path, manifest_hash,
  source_record_fingerprint, public_artifact_id, public_index_path, hf_dataset_synced,
  hf_dataset_url, imported_at
)
select
  paper_id, corpus_repo, artifact_slug, commit_sha, manifest_path, manifest_hash,
  source_record_fingerprint, public_artifact_id, public_index_path, hf_dataset_synced,
  hf_dataset_url, now()
from matched
on conflict (paper_id, corpus_repo) do update set
  artifact_slug = excluded.artifact_slug,
  commit_sha = excluded.commit_sha,
  manifest_path = excluded.manifest_path,
  manifest_hash = excluded.manifest_hash,
  source_record_fingerprint = excluded.source_record_fingerprint,
  public_artifact_id = excluded.public_artifact_id,
  public_index_path = excluded.public_index_path,
  hf_dataset_synced = excluded.hf_dataset_synced,
  hf_dataset_url = excluded.hf_dataset_url;

select
  (select count(*) from tmp_public_index) as public_index_rows,
  (
    select count(*)
    from enoch.papers p
    join tmp_public_index pi
      on pi.source_record_fingerprint = left(encode(extensions.digest(p.paper_id, 'sha256'), 'hex'), 16)
  ) as matched_live_papers,
  (select count(*) from enoch.corpus_imports) as corpus_imports_total,
  odc.publication_ready,
  odc.publication_ready_total,
  odc.corpus_imported,
  odc.hf_dataset_synced
from enoch.operator_dashboard_counts odc;
"""


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=Path("../enoch-ai-research-corpus"))
    parser.add_argument("--database-url", default=os.environ.get("ENOCH_SUPABASE_DATABASE_URL", ""))
    parser.add_argument("--corpus-repo", default=DEFAULT_CORPUS_REPO)
    parser.add_argument("--hf-dataset-url", default=DEFAULT_HF_DATASET_URL)
    parser.add_argument("--apply", action="store_true", help="commit the ledger sync; default is rollback/dry-run")
    parser.add_argument("--sql-output", type=Path, help="write SQL for `supabase db query --linked -f` instead of connecting directly")
    parser.add_argument("--output", type=Path, help="optional JSON report path")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    records = load_public_records(args.corpus)
    if args.sql_output:
        args.sql_output.write_text(
            render_supabase_cli_sql(records, corpus_repo=args.corpus_repo, hf_dataset_url=args.hf_dataset_url),
            encoding="utf-8",
        )
        print(json.dumps({"ok": True, "public_records": len(records), "sql_output": str(args.sql_output)}, indent=2, sort_keys=True))
        return 0
    if not args.database_url.strip():
        print("error: --database-url or ENOCH_SUPABASE_DATABASE_URL is required unless --sql-output is used", file=sys.stderr)
        return 2
    report = sync_records(
        database_url=args.database_url,
        records=records,
        corpus_repo=args.corpus_repo,
        hf_dataset_url=args.hf_dataset_url,
        apply=bool(args.apply),
    )
    report = {"ok": True, "public_records": len(records), **report}
    text = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
