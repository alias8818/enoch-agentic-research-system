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
DEFAULT_HF_DATASET_URL = (
    "https://huggingface.co/datasets/aliasocracy/enoch-ai-research-corpus"
)


@dataclass(frozen=True)
class PublicCorpusRecord:
    source_record_fingerprint: str
    artifact_slug: str
    public_artifact_id: str
    public_manifest_path: str
    title: str


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
        manifest = _text(row.get("manifest_path")) or (
            f"papers/{slug}/paper_manifest.json" if slug else ""
        )
        records.append(
            PublicCorpusRecord(
                source_record_fingerprint=fp,
                artifact_slug=slug,
                public_artifact_id=_text(row.get("public_id")),
                public_manifest_path=manifest,
                title=_text(row.get("title")) or slug,
            )
        )
        seen.add(fp)
    return records


def _connect(database_url: str) -> Any:
    import psycopg
    from psycopg.rows import dict_row

    return psycopg.connect(database_url, row_factory=dict_row)


def match_public_records_to_live_papers(
    paper_ids: list[str], records: list[PublicCorpusRecord]
) -> list[MatchedCorpusRecord]:
    records_by_fingerprint = {
        record.source_record_fingerprint: record for record in records
    }
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
    prune_stale: bool = False,
) -> dict[str, Any]:
    if not records:
        raise ValueError(
            "no public corpus records with source_record_fingerprint found"
        )
    with _connect(database_url) as conn:
        try:
            with conn.cursor() as cur:
                cur.execute("set search_path to enoch, public")
                cur.execute(
                    """
                    create temp table tmp_public_index(
                      source_record_fingerprint text,
                      artifact_slug text,
                      public_artifact_id text,
                      public_manifest_path text,
                      title text
                    ) on commit drop
                    """
                )
                cur.executemany(
                    """
                    insert into tmp_public_index(
                      source_record_fingerprint, artifact_slug, public_artifact_id, public_manifest_path, title
                    ) values (%s, %s, %s, %s, %s)
                    """,
                    [
                        (
                            record.source_record_fingerprint,
                            record.artifact_slug,
                            record.public_artifact_id,
                            record.public_manifest_path,
                            record.title,
                        )
                        for record in records
                    ],
                )
                cur.execute(
                    """
                    create temp table tmp_live_paper_fingerprints(
                      paper_id text,
                      project_id text,
                      source_record_fingerprint text
                    ) on commit drop
                    """
                )
                cur.execute("select paper_id, project_id from enoch.papers")
                live_papers = [
                    (
                        _text(row.get("paper_id")),
                        _text(row.get("project_id")),
                        source_fingerprint(_text(row.get("paper_id"))),
                    )
                    for row in cur.fetchall()
                    if _text(row.get("paper_id"))
                ]
                if live_papers:
                    cur.executemany(
                        """
                        insert into tmp_live_paper_fingerprints(paper_id, project_id, source_record_fingerprint)
                        values (%s, %s, %s)
                        """,
                        live_papers,
                    )
                cur.execute(
                    """
                    create temp table tmp_resolved_public_index as
                    select
                      coalesce(p.paper_id, 'public-corpus:' || pi.source_record_fingerprint || ':' || pi.artifact_slug) as paper_id,
                      coalesce(p.project_id, 'public-corpus:' || pi.source_record_fingerprint) as project_id,
                      pi.source_record_fingerprint,
                      pi.artifact_slug,
                      pi.public_artifact_id,
                      pi.public_manifest_path,
                      pi.title
                    from tmp_public_index pi
                    left join tmp_live_paper_fingerprints p
                      on pi.source_record_fingerprint = p.source_record_fingerprint
                    """
                )
                cur.execute(
                    """
                    create temp table tmp_conflicting_public_projects as
                    select p.project_id
                    from enoch.projects p
                    join tmp_resolved_public_index r on r.project_id = p.project_id
                    where r.project_id like 'public-corpus:%'
                      and (
                        coalesce(p.project_name, '') <> coalesce(nullif(r.title, ''), r.artifact_slug)
                        or coalesce(p.project_dir, '') <> r.artifact_slug
                        or coalesce(p.origin_idea_status, '') <> 'validated'
                      )
                    """
                )
                cur.execute(
                    "select count(*) as count from tmp_conflicting_public_projects"
                )
                project_conflicts = int((cur.fetchone() or {}).get("count") or 0)
                if project_conflicts:
                    raise RuntimeError(
                        f"conflicting public-corpus project identity rows: {project_conflicts}"
                    )
                cur.execute(
                    """
                    create temp table tmp_conflicting_public_papers as
                    select p.paper_id
                    from enoch.papers p
                    join tmp_resolved_public_index r on r.paper_id = p.paper_id
                    where r.paper_id like 'public-corpus:%'
                      and (
                        coalesce(p.project_id, '') <> r.project_id
                        or coalesce(p.paper_type, '') <> 'arxiv_draft'
                        or coalesce(p.paper_status, '') <> 'publication_draft'
                        or coalesce(p.draft_markdown_path, '') <> 'papers/' || r.artifact_slug || '/paper.md'
                        or coalesce(p.draft_latex_path, '') <> 'papers/' || r.artifact_slug || '/paper.tex'
                        or coalesce(p.evidence_bundle_path, '') <> 'papers/' || r.artifact_slug || '/evidence_bundle.json'
                        or coalesce(p.claim_ledger_path, '') <> 'papers/' || r.artifact_slug || '/claim_ledger.json'
                        or coalesce(p.manifest_path, '') <> r.public_manifest_path
                        or coalesce(p.artifact_root, '') <> 'papers/' || r.artifact_slug
                      )
                    """
                )
                cur.execute(
                    "select count(*) as count from tmp_conflicting_public_papers"
                )
                paper_conflicts = int((cur.fetchone() or {}).get("count") or 0)
                if paper_conflicts:
                    raise RuntimeError(
                        f"conflicting public-corpus paper identity rows: {paper_conflicts}"
                    )
                cur.execute(
                    """
                    insert into enoch.projects(project_id, project_name, project_dir, origin_idea_status)
                    select project_id, coalesce(nullif(title, ''), artifact_slug), artifact_slug, 'validated'
                    from tmp_resolved_public_index r
                    where not exists (select 1 from enoch.projects p where p.project_id = r.project_id)
                    on conflict (project_id) do nothing
                    """
                )
                cur.execute(
                    """
                    insert into enoch.papers(
                      paper_id, project_id, run_id, paper_type, paper_status,
                      draft_markdown_path, draft_latex_path, evidence_bundle_path, claim_ledger_path,
                      manifest_path, artifact_root, artifact_payload_hash
                    )
                    select
                      paper_id, project_id, null, 'arxiv_draft', 'publication_draft',
                      'papers/' || artifact_slug || '/paper.md',
                      'papers/' || artifact_slug || '/paper.tex',
                      'papers/' || artifact_slug || '/evidence_bundle.json',
                      'papers/' || artifact_slug || '/claim_ledger.json',
                      public_manifest_path,
                      'papers/' || artifact_slug,
                      ''
                    from tmp_resolved_public_index r
                    where not exists (select 1 from enoch.papers p where p.paper_id = r.paper_id)
                    on conflict (paper_id) do nothing
                    """
                )
                cur.execute(
                    """
                    with matched as (
                      select
                        pi.paper_id,
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
                      from tmp_resolved_public_index pi
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
                      commit_sha = coalesce(nullif(excluded.commit_sha, ''), enoch.corpus_imports.commit_sha),
                      manifest_path = excluded.manifest_path,
                      manifest_hash = coalesce(nullif(excluded.manifest_hash, ''), enoch.corpus_imports.manifest_hash),
                      source_record_fingerprint = excluded.source_record_fingerprint,
                      public_artifact_id = excluded.public_artifact_id,
                      public_index_path = excluded.public_index_path,
                      hf_dataset_synced = excluded.hf_dataset_synced,
                      hf_dataset_url = excluded.hf_dataset_url
                    """,
                    (corpus_repo, hf_dataset_url),
                )
                changed = cur.rowcount
                pruned_rows = 0
                if prune_stale:
                    cur.execute(
                        """
                        create temp table tmp_stale_imports as
                        select ci.paper_id
                        from enoch.corpus_imports ci
                        where ci.corpus_repo = %s
                          and not exists (
                            select 1
                            from tmp_resolved_public_index pi
                            where pi.source_record_fingerprint = ci.source_record_fingerprint
                          )
                        """,
                        (corpus_repo,),
                    )
                    cur.execute(
                        """
                        delete from enoch.corpus_imports ci
                        using tmp_stale_imports stale
                        where ci.corpus_repo = %s
                          and ci.paper_id = stale.paper_id
                        """,
                        (corpus_repo,),
                    )
                    pruned_rows = int(cur.rowcount or 0)

                cur.execute(
                    """
                    select
                      %s::integer as public_index_rows,
                      (select count(*) from tmp_public_index) as matched_public_index_rows,
                      (
                        select count(*)
                        from enoch.papers p
                        join tmp_resolved_public_index pi
                          on pi.paper_id = p.paper_id
                      ) as matched_live_papers,
                      (
                        select count(*)
                        from enoch.corpus_imports ci
                        where ci.corpus_repo = %s
                      ) as corpus_imports_total,
                      odc.publication_ready,
                      odc.publication_ready_total,
                      odc.corpus_imported,
                      odc.hf_dataset_synced,
                      (
                        select count(*)
                        from enoch.corpus_imports ci
                        where ci.corpus_repo = %s
                          and not exists (
                            select 1
                            from tmp_resolved_public_index pi
                            where pi.source_record_fingerprint = ci.source_record_fingerprint
                          )
                      ) as stale_corpus_imports,
                      (
                        select count(*)
                        from tmp_resolved_public_index pi
                        where not exists (
                            select 1
                            from enoch.corpus_imports ci
                            where ci.corpus_repo = %s
                              and ci.source_record_fingerprint = pi.source_record_fingerprint
                        )
                      ) as missing_public_records
                    from enoch.operator_dashboard_counts odc
                    """,
                    (len(records), corpus_repo, corpus_repo, corpus_repo),
                )
                summary = dict(cur.fetchone() or {})
                summary["changed_rows"] = int(changed or 0)
                summary["pruned_rows"] = pruned_rows
                summary["prune_stale"] = bool(prune_stale)
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
    prune_stale: bool = False,
    rollback: bool = False,
) -> str:
    """Render the same sync as SQL for `supabase db query --linked -f`."""

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
                record.public_manifest_path,
                record.title,
            )
        )
        + ")"
        for record in records
    )
    stale_delete_sql = (
        f"""
create temp table tmp_stale_imports as
select ci.paper_id
from enoch.corpus_imports ci
where ci.corpus_repo = {sql_literal(corpus_repo)}
  and not exists (
    select 1
    from tmp_resolved_public_index pi
    where pi.source_record_fingerprint = ci.source_record_fingerprint
  );
with pruned as (
  delete from enoch.corpus_imports ci
  using tmp_stale_imports stale
  where ci.corpus_repo = {sql_literal(corpus_repo)}
    and ci.paper_id = stale.paper_id
  returning 1
)
insert into tmp_pruned_rows(pruned_rows)
select count(*) from pruned;
"""
        if prune_stale
        else """
create temp table tmp_stale_imports(paper_id text) on commit drop;
insert into tmp_pruned_rows(pruned_rows) values (0);
"""
    )
    transaction_prefix = "begin;\n" if rollback else ""
    transaction_suffix = "\nrollback;\n" if rollback else ""
    return f"""{transaction_prefix}set search_path to enoch, public;
create temp table tmp_public_index(
  source_record_fingerprint text,
  artifact_slug text,
  public_artifact_id text,
  public_manifest_path text,
  title text
) on commit drop;
create temp table tmp_pruned_rows(pruned_rows integer not null) on commit drop;
-- SQL output mode requires pgcrypto access because it cannot prefetch live paper IDs in Python.
insert into tmp_public_index(source_record_fingerprint, artifact_slug, public_artifact_id, public_manifest_path, title)
values
    {values};
create temp table tmp_resolved_public_index as
select
  coalesce(p.paper_id, 'public-corpus:' || pi.source_record_fingerprint || ':' || pi.artifact_slug) as paper_id,
  coalesce(p.project_id, 'public-corpus:' || pi.source_record_fingerprint) as project_id,
  pi.source_record_fingerprint,
  pi.artifact_slug,
  pi.public_artifact_id,
  pi.public_manifest_path,
  pi.title
from tmp_public_index pi
left join enoch.papers p
  on pi.source_record_fingerprint = left(encode(extensions.digest(p.paper_id, 'sha256'), 'hex'), 16);
create temp table tmp_conflicting_public_projects as
select p.project_id
from enoch.projects p
join tmp_resolved_public_index r on r.project_id = p.project_id
where r.project_id like 'public-corpus:%'
  and (
    coalesce(p.project_name, '') <> coalesce(nullif(r.title, ''), r.artifact_slug)
    or coalesce(p.project_dir, '') <> r.artifact_slug
    or coalesce(p.origin_idea_status, '') <> 'validated'
  );
create temp table tmp_conflicting_public_papers as
select p.paper_id
from enoch.papers p
join tmp_resolved_public_index r on r.paper_id = p.paper_id
where r.paper_id like 'public-corpus:%'
  and (
    coalesce(p.project_id, '') <> r.project_id
    or coalesce(p.paper_type, '') <> 'arxiv_draft'
    or coalesce(p.paper_status, '') <> 'publication_draft'
    or coalesce(p.draft_markdown_path, '') <> 'papers/' || r.artifact_slug || '/paper.md'
    or coalesce(p.draft_latex_path, '') <> 'papers/' || r.artifact_slug || '/paper.tex'
    or coalesce(p.evidence_bundle_path, '') <> 'papers/' || r.artifact_slug || '/evidence_bundle.json'
    or coalesce(p.claim_ledger_path, '') <> 'papers/' || r.artifact_slug || '/claim_ledger.json'
    or coalesce(p.manifest_path, '') <> r.public_manifest_path
    or coalesce(p.artifact_root, '') <> 'papers/' || r.artifact_slug
  );
do $$
begin
  if exists (select 1 from tmp_conflicting_public_projects) then
    raise exception 'conflicting public-corpus project identity';
  end if;
  if exists (select 1 from tmp_conflicting_public_papers) then
    raise exception 'conflicting public-corpus paper identity';
  end if;
end $$;
insert into enoch.projects(project_id, project_name, project_dir, origin_idea_status)
select project_id, coalesce(nullif(title, ''), artifact_slug), artifact_slug, 'validated'
from tmp_resolved_public_index r
where not exists (select 1 from enoch.projects p where p.project_id = r.project_id)
on conflict (project_id) do nothing;
insert into enoch.papers(
  paper_id, project_id, run_id, paper_type, paper_status,
  draft_markdown_path, draft_latex_path, evidence_bundle_path, claim_ledger_path,
  manifest_path, artifact_root, artifact_payload_hash
)
select
  paper_id, project_id, null, 'arxiv_draft', 'publication_draft',
  'papers/' || artifact_slug || '/paper.md',
  'papers/' || artifact_slug || '/paper.tex',
  'papers/' || artifact_slug || '/evidence_bundle.json',
  'papers/' || artifact_slug || '/claim_ledger.json',
  public_manifest_path,
  'papers/' || artifact_slug,
  ''
from tmp_resolved_public_index r
where not exists (select 1 from enoch.papers p where p.paper_id = r.paper_id)
on conflict (paper_id) do nothing;
with matched as (
  select
    pi.paper_id,
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
  from tmp_resolved_public_index pi
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
  commit_sha = coalesce(nullif(excluded.commit_sha, ''), enoch.corpus_imports.commit_sha),
  manifest_path = excluded.manifest_path,
  manifest_hash = coalesce(nullif(excluded.manifest_hash, ''), enoch.corpus_imports.manifest_hash),
  source_record_fingerprint = excluded.source_record_fingerprint,
  public_artifact_id = excluded.public_artifact_id,
  public_index_path = excluded.public_index_path,
  hf_dataset_synced = excluded.hf_dataset_synced,
  hf_dataset_url = excluded.hf_dataset_url;

{stale_delete_sql}
select
  (select count(*) from tmp_public_index) as public_index_rows,
  (
    select count(*)
    from enoch.papers p
    join tmp_resolved_public_index pi
      on pi.paper_id = p.paper_id
  ) as matched_live_papers,
  (
    select count(*)
    from enoch.corpus_imports ci
    where ci.corpus_repo = {sql_literal(corpus_repo)}
  ) as corpus_imports_total,
  (select coalesce(sum(pruned_rows), 0) from tmp_pruned_rows) as pruned_rows,
  {str(prune_stale).lower()}::boolean as prune_stale,
  (
    select count(*)
    from enoch.corpus_imports ci
    where ci.corpus_repo = {sql_literal(corpus_repo)}
      and not exists (
        select 1
        from tmp_resolved_public_index pi
        where pi.source_record_fingerprint = ci.source_record_fingerprint
      )
  ) as stale_corpus_imports,
  (
    select count(*)
    from tmp_resolved_public_index pi
    where not exists (
        select 1
        from enoch.corpus_imports ci
        where ci.corpus_repo = {sql_literal(corpus_repo)}
          and ci.source_record_fingerprint = pi.source_record_fingerprint
    )
  ) as missing_public_records,
  odc.publication_ready,
  odc.publication_ready_total,
  odc.corpus_imported,
  odc.hf_dataset_synced
from enoch.operator_dashboard_counts odc;
{transaction_suffix}"""


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--corpus", type=Path, default=Path("../enoch-ai-research-corpus")
    )
    parser.add_argument(
        "--database-url", default=os.environ.get("ENOCH_SUPABASE_DATABASE_URL", "")
    )
    parser.add_argument("--corpus-repo", default=DEFAULT_CORPUS_REPO)
    parser.add_argument("--hf-dataset-url", default=DEFAULT_HF_DATASET_URL)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="commit the ledger sync; default is rollback/dry-run",
    )
    parser.add_argument(
        "--prune-stale",
        action="store_true",
        help="delete corpus_imports rows for this corpus repo that are absent from the public corpus index",
    )
    parser.add_argument(
        "--sql-rollback",
        action="store_true",
        help="when rendering SQL, wrap it in a transaction that rolls back for linked dry-runs",
    )
    parser.add_argument(
        "--sql-output",
        type=Path,
        help="write SQL for `supabase db query --linked -f` instead of connecting directly",
    )
    parser.add_argument("--output", type=Path, help="optional JSON report path")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    records = load_public_records(args.corpus)
    if args.sql_output:
        args.sql_output.write_text(
            render_supabase_cli_sql(
                records,
                corpus_repo=args.corpus_repo,
                hf_dataset_url=args.hf_dataset_url,
                prune_stale=bool(args.prune_stale),
                rollback=bool(args.sql_rollback),
            ),
            encoding="utf-8",
        )
        print(
            json.dumps(
                {
                    "ok": True,
                    "public_records": len(records),
                    "sql_output": str(args.sql_output),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    if not args.database_url.strip():
        print(
            "error: --database-url or ENOCH_SUPABASE_DATABASE_URL is required unless --sql-output is used",
            file=sys.stderr,
        )
        return 2
    report = sync_records(
        database_url=args.database_url,
        records=records,
        corpus_repo=args.corpus_repo,
        hf_dataset_url=args.hf_dataset_url,
        apply=bool(args.apply),
        prune_stale=bool(args.prune_stale),
    )
    report = {"ok": True, "public_records": len(records), **report}
    text = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
