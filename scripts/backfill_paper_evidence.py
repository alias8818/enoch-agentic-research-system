#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Literal

from fastapi import HTTPException

from enoch_control_plane.config import GateConfig
from enoch_control_plane.control_plane.models import PaperRecord, PaperStatus, utc_now
from enoch_control_plane.control_plane.paper_writer import (
    backfill_paper_evidence_artifacts,
)
from enoch_control_plane.control_plane.router import (
    _local_artifact_root,
    _local_paper_evidence_present,
    _sync_remote_project_evidence,
)
from enoch_control_plane.control_plane.store import ControlPlaneStore
from enoch_control_plane.control_plane.supabase_store import (
    SupabaseControlPlaneStore,
    SupabaseReadOnlyControlPlaneStore,
    resolve_supabase_database_url,
)

ProcessStatus = Literal["updated", "skipped", "failed"]


def load_config(path: Path) -> GateConfig:
    return GateConfig.model_validate(
        json.loads(path.expanduser().read_text(encoding="utf-8"))
    )


def make_store(config: GateConfig) -> Any:
    if config.control_plane_store_backend == "supabase_readonly":
        return SupabaseReadOnlyControlPlaneStore(
            resolve_supabase_database_url(config.supabase_database_url)
        )
    if config.control_plane_store_backend == "supabase":
        return SupabaseControlPlaneStore(
            resolve_supabase_database_url(config.supabase_database_url)
        )
    return ControlPlaneStore(config.expanded_state_dir / "control_plane.sqlite3")


def paper_record_from_row(row: dict[str, Any]) -> PaperRecord:
    return PaperRecord(
        paper_id=str(row.get("paper_id") or ""),
        project_id=str(row.get("project_id") or ""),
        run_id=str(row.get("run_id") or ""),
        paper_type=str(row.get("paper_type") or "arxiv_draft"),
        paper_status=PaperStatus(
            str(row.get("paper_status") or PaperStatus.PUBLICATION_DRAFT.value)
        ),
        draft_markdown_path=str(row.get("draft_markdown_path") or ""),
        draft_latex_path=str(row.get("draft_latex_path") or ""),
        evidence_bundle_path=str(row.get("evidence_bundle_path") or ""),
        claim_ledger_path=str(row.get("claim_ledger_path") or ""),
        manifest_path=str(row.get("manifest_path") or ""),
        generated_at=str(row.get("generated_at") or utc_now()),
        updated_at=utc_now(),
    )


def artifact_root_for_row(config: GateConfig, row: dict[str, Any]) -> Path:
    project_id = str(row.get("project_id") or "").strip()
    project_dir = str(row.get("project_dir") or "").strip()
    return _local_artifact_root(
        config, project_id=project_id, project_dir_text=project_dir
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill evidence_bundle.json and claim_ledger.json for existing Enoch papers."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(
            os.environ.get("ENOCH_CONFIG")
            or os.environ.get("ENOCH_CONTROL_PLANE_CONFIG")
            or "config.example.json"
        ),
    )
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--paper-id", action="append", default=[])
    parser.add_argument(
        "--published-only",
        action="store_true",
        help="Only process papers already represented by a corpus_imports row.",
    )
    parser.add_argument(
        "--sync",
        action="store_true",
        help="Run worker/SSH evidence sync before regenerating evidence artifacts.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Rewrite existing evidence_bundle/claim_ledger/manifest files.",
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def _default_evidence_sync() -> dict[str, Any]:
    return {"enabled": False, "synced": False, "reason": "not_requested"}


def _source_project_dir_for_sync(config: GateConfig, row: dict[str, Any]) -> str:
    source_project_dir = str(row.get("project_dir") or "")
    resolved_root = str(config.expanded_project_root.resolve())
    if source_project_dir.startswith("/") and not source_project_dir.startswith(
        resolved_root
    ):
        return source_project_dir
    return ""


def _maybe_sync_evidence(
    config: GateConfig,
    args: argparse.Namespace,
    row: dict[str, Any],
    *,
    project_id: str,
    artifact_root: Path,
) -> dict[str, Any]:
    if not args.sync:
        return _default_evidence_sync()
    return _sync_remote_project_evidence(
        config,
        project_id=project_id,
        artifact_root=artifact_root,
        source_project_dir=_source_project_dir_for_sync(config, row),
        source_run_id=str(row.get("run_id") or ""),
    )


def _build_candidate(
    row: dict[str, Any],
    *,
    project_id: str,
    artifact_root: Path,
    record: PaperRecord,
    evidence_sync: dict[str, Any],
) -> dict[str, Any]:
    return {
        "project_id": project_id,
        "project_name": str(row.get("project_name") or project_id),
        "project_dir": str(artifact_root),
        "run_id": record.run_id,
        "current_run_id": record.run_id,
        "source_project_dir": str(row.get("project_dir") or ""),
        "evidence_sync": evidence_sync,
    }


def _failure_result(
    paper_id: str,
    project_id: str,
    artifact_root: Path,
    error: str,
) -> dict[str, Any]:
    return {
        "paper_id": paper_id,
        "project_id": project_id,
        "updated": False,
        "artifact_root": str(artifact_root),
        "error": error,
    }


def _process_paper_row(
    config: GateConfig,
    args: argparse.Namespace,
    row: dict[str, Any],
) -> tuple[ProcessStatus, dict[str, Any]]:
    paper_id = str(row.get("paper_id") or "")
    project_id = str(row.get("project_id") or "")
    artifact_root = artifact_root_for_row(config, row)
    try:
        artifact_root.mkdir(parents=True, exist_ok=True)
        evidence_sync = _maybe_sync_evidence(
            config, args, row, project_id=project_id, artifact_root=artifact_root
        )
        local_evidence = _local_paper_evidence_present(artifact_root)
        record = paper_record_from_row(row)
        candidate = _build_candidate(
            row,
            project_id=project_id,
            artifact_root=artifact_root,
            record=record,
            evidence_sync=evidence_sync,
        )
        if args.dry_run:
            return "skipped", {
                "paper_id": paper_id,
                "project_id": project_id,
                "dry_run": True,
                "artifact_root": str(artifact_root),
                "local_evidence_present": local_evidence,
                "evidence_sync": evidence_sync,
            }
        meta = backfill_paper_evidence_artifacts(
            config, candidate, record, force=args.force
        )
        return "updated", {
            "paper_id": paper_id,
            "project_id": project_id,
            "updated": True,
            "artifact_root": str(artifact_root),
            "meta": meta,
            "evidence_sync": evidence_sync,
        }
    except HTTPException as exc:
        return "failed", _failure_result(
            paper_id, project_id, artifact_root, str(exc.detail)
        )
    except Exception as exc:
        return "failed", _failure_result(
            paper_id,
            project_id,
            artifact_root,
            f"{type(exc).__name__}: {exc}",
        )


def _should_process_row(
    row: dict[str, Any],
    *,
    wanted: set[str],
    published_only: bool,
) -> bool:
    paper_id = str(row.get("paper_id") or "")
    if wanted and paper_id not in wanted:
        return False
    if published_only and not row.get("corpus_imported"):
        return False
    return True


def _record_status_count(status: ProcessStatus, counts: dict[str, int]) -> None:
    if status == "updated":
        counts["updated"] += 1
    elif status == "skipped":
        counts["skipped"] += 1
    else:
        counts["failed"] += 1


def _run_backfill_rows(
    config: GateConfig,
    args: argparse.Namespace,
    rows: list[dict[str, Any]],
) -> tuple[dict[str, int], list[dict[str, Any]]]:
    wanted = {str(item) for item in args.paper_id}
    counts = {"processed": 0, "updated": 0, "skipped": 0, "failed": 0}
    out_rows: list[dict[str, Any]] = []

    for row in rows:
        if not _should_process_row(
            row, wanted=wanted, published_only=args.published_only
        ):
            continue
        if args.limit and counts["processed"] >= args.limit:
            break
        counts["processed"] += 1
        status, result = _process_paper_row(config, args, row)
        out_rows.append(result)
        _record_status_count(status, counts)

    return counts, out_rows


def main() -> int:
    args = _parse_args()
    config = load_config(args.config)
    store = make_store(config)
    counts, out_rows = _run_backfill_rows(config, args, store.paper_rows())
    print(
        json.dumps(
            {**counts, "rows": out_rows[:200]},
            indent=2,
            sort_keys=True,
            default=str,
        )
    )
    return 1 if counts["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
