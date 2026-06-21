#!/usr/bin/env python3
"""Reconcile finalized publication drafts and the public corpus.

This is the guardrail for corpus-import status claims. By default it checks
only finalized `publication_draft` rows, which is the public corpus import
lane. Historical draft-review rows and future paper-writing candidates are
separate diagnostics, not part of the corpus-import backlog.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any
from enoch_control_plane.url_safety import urlopen_validated

DEFAULT_PAPER_STATUS = "publication_draft"


def source_fingerprint(paper_id: str) -> str:
    return hashlib.sha256(paper_id.encode("utf-8")).hexdigest()[:16]


def request_json(base_url: str, token: str, path: str) -> dict[str, Any]:
    req = urllib.request.Request(
        base_url.rstrip("/") + path, headers={"Authorization": f"Bearer {token}"}
    )
    with urlopen_validated(
        req,
        timeout=120,
        field_name="scripts/reconcile_paper_ledgers.py url",
        allow_private=True,
    ) as resp:
        return json.loads(resp.read())


def iter_review_rows(
    base_url: str, token: str, *, review_status: str, paper_status: str, page_size: int
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    page = 1
    while True:
        query = urllib.parse.urlencode(
            {
                "page": page,
                "page_size": page_size,
                "review_status": review_status,
                "paper_status": paper_status,
                "include_rank_reasons": "false",
            }
        )
        payload = request_json(
            base_url, token, f"/control/api/publication-automation?{query}"
        )
        page_rows = list(payload.get("rows") or [])
        rows.extend(page_rows)
        page_meta = payload.get("page") or {}
        total = int(page_meta.get("total") or len(rows))
        if len(rows) >= total or not page_rows:
            return rows
        page += 1


def load_public_index(corpus: Path) -> dict[str, Any]:
    index_path = corpus / "papers" / "index.json"
    payload = json.loads(index_path.read_text(encoding="utf-8"))
    papers = list(payload.get("papers") or [])
    by_fp = {
        str(row.get("source_record_fingerprint") or ""): row
        for row in papers
        if row.get("source_record_fingerprint")
    }
    return {
        "path": str(index_path),
        "count": int(payload.get("count") or len(papers)),
        "papers": papers,
        "by_fingerprint": by_fp,
    }


def compact_row(row: dict[str, Any]) -> dict[str, str]:
    return {
        "paper_id": str(row.get("paper_id") or ""),
        "project_id": str(row.get("project_id") or ""),
        "project_name": str(row.get("project_name") or ""),
        "run_id": str(row.get("run_id") or ""),
        "paper_status": str(row.get("paper_status") or ""),
        "review_status": str(row.get("review_status") or ""),
    }


def classify_finalized_rows(
    finalized_rows: list[dict[str, Any]], public: dict[str, Any]
) -> dict[str, list[dict[str, Any]]]:
    public_by_fp: dict[str, Any] = public["by_fingerprint"]
    exact_existing: list[dict[str, Any]] = []
    importable: list[dict[str, Any]] = []
    for row in finalized_rows:
        paper_id = str(row.get("paper_id") or "")
        fp = source_fingerprint(paper_id)
        if fp in public_by_fp:
            exact_existing.append(row)
        else:
            importable.append(row)
    return {
        "exact_existing": exact_existing,
        "importable": importable,
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare live Enoch paper ledgers with the public corpus index."
    )
    parser.add_argument(
        "--control-url",
        default=os.environ.get("ENOCH_CONTROL_URL", "http://127.0.0.1:8787"),
    )
    parser.add_argument("--token", default=os.environ.get("ENOCH_CONTROL_TOKEN", ""))
    parser.add_argument(
        "--corpus", type=Path, default=Path("../enoch-ai-research-corpus")
    )
    parser.add_argument("--page-size", type=int, default=200)
    parser.add_argument(
        "--paper-status",
        default=DEFAULT_PAPER_STATUS,
        help="Paper status to reconcile; defaults to publication_draft, the corpus import lane. Use '' only for legacy audit diagnostics.",
    )
    parser.add_argument(
        "--include-draft-candidate",
        action="store_true",
        help="Also fetch /control/state and report next_candidate as a separate paper-writing diagnostic.",
    )
    parser.add_argument(
        "--require-synced",
        action="store_true",
        help="Exit nonzero if unpublished finalized corpus-lane papers remain.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show exact-fingerprint diagnostics in human output.",
    )
    parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON only."
    )
    return parser


def fetch_reconciliation_inputs(
    args: argparse.Namespace,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    overview = request_json(
        args.control_url,
        args.token,
        "/control/api/v1/overview?active_limit=5&event_limit=5",
    )
    state = (
        request_json(args.control_url, args.token, "/control/state")
        if args.include_draft_candidate
        else {}
    )
    finalized_rows = iter_review_rows(
        args.control_url,
        args.token,
        review_status="finalized",
        paper_status=args.paper_status,
        page_size=args.page_size,
    )
    public = load_public_index(args.corpus)
    return overview, finalized_rows, public, state


def build_reconciliation_report(
    *,
    args: argparse.Namespace,
    overview: dict[str, Any],
    finalized_rows: list[dict[str, Any]],
    public: dict[str, Any],
    state: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    paper_status_filter = args.paper_status
    finalized_by_fp = {
        source_fingerprint(str(row.get("paper_id") or "")): row
        for row in finalized_rows
        if row.get("paper_id")
    }
    public_by_fp: dict[str, Any] = public["by_fingerprint"]
    missing_exact_fingerprint = [
        row for fp, row in finalized_by_fp.items() if fp not in public_by_fp
    ]
    classified = classify_finalized_rows(finalized_rows, public)
    importable = classified["importable"]
    public_without_live_finalized = [
        row for fp, row in public_by_fp.items() if fp not in finalized_by_fp
    ]
    next_candidate = (
        state.get("next_candidate") if args.include_draft_candidate else None
    )
    report = {
        "ok": not importable,
        "control_url": args.control_url,
        "paper_status_filter": paper_status_filter,
        "live_counts": overview.get("counts"),
        "operator_counts": overview.get("operator_counts"),
        "paper_counts": overview.get("paper_counts"),
        "next_draft_candidate": next_candidate,
        "live_finalized_count": len(finalized_rows),
        "public_corpus_count": public["count"],
        "exact_existing_finalized_count": len(classified["exact_existing"]),
        "missing_exact_fingerprint_count": len(missing_exact_fingerprint),
        "importable_finalized_count": len(importable),
        "unpublished_finalized_count": len(importable),
        "public_without_live_finalized_count": len(public_without_live_finalized),
        "importable_finalized_sample": [compact_row(row) for row in importable[:20]],
        "unpublished_finalized_sample": [compact_row(row) for row in importable[:20]],
        "public_without_live_finalized_sample": public_without_live_finalized[:20],
        "corpus_index": public["path"],
    }
    return report, importable


def print_draft_candidate_diagnostic(
    *, include_draft_candidate: bool, next_candidate: Any
) -> None:
    if not include_draft_candidate:
        return
    if next_candidate:
        print(
            "  next live draft candidate: " + json.dumps(next_candidate, sort_keys=True)
        )
        return
    print("  next live draft candidate: none")


def print_importable_sample(importable: list[dict[str, Any]]) -> None:
    if not importable:
        return
    print("  importable finalized sample:")
    for row in importable[:20]:
        item = compact_row(row)
        print(
            f"    - {item['project_name']} | {item['project_id']} | {item['paper_status']} / {item['review_status']}"
        )


def print_human_report(
    report: dict[str, Any],
    *,
    args: argparse.Namespace,
    importable: list[dict[str, Any]],
) -> None:
    paper_status_filter = report["paper_status_filter"]
    print("Paper ledger reconciliation")
    print(f"  paper status filter: {paper_status_filter or 'all'}")
    print(f"  finalized rows in corpus lane: {report['live_finalized_count']}")
    print(f"  public corpus rows: {report['public_corpus_count']}")
    print(
        f"  already represented by source fingerprint: {report['exact_existing_finalized_count']}"
    )
    print(f"  importable finalized rows: {report['importable_finalized_count']}")
    if args.verbose:
        print(
            f"  finalized rows missing exact fingerprint: {report['missing_exact_fingerprint_count']}"
        )
        print(
            f"  public rows outside this live finalized filter: {report['public_without_live_finalized_count']}"
        )
    print_draft_candidate_diagnostic(
        include_draft_candidate=args.include_draft_candidate,
        next_candidate=report["next_draft_candidate"],
    )
    print_importable_sample(importable)


def emit_reconciliation_report(
    report: dict[str, Any],
    *,
    args: argparse.Namespace,
    importable: list[dict[str, Any]],
) -> None:
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
        return
    print_human_report(report, args=args, importable=importable)


def main() -> int:
    args = build_arg_parser().parse_args()

    if not args.token:
        print("Set --token or ENOCH_CONTROL_TOKEN", file=sys.stderr)
        return 2

    overview, finalized_rows, public, state = fetch_reconciliation_inputs(args)
    report, importable = build_reconciliation_report(
        args=args,
        overview=overview,
        finalized_rows=finalized_rows,
        public=public,
        state=state,
    )
    emit_reconciliation_report(report, args=args, importable=importable)

    if args.require_synced and importable:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
