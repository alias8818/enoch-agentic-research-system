#!/usr/bin/env python3
"""One-shot live state sanity report for Enoch operators and agents.

The doctor intentionally checks boundaries rather than raw totals alone:
operator dashboard lanes, positive-only paper-writing eligibility, state-contract
compatibility, normalization drift, and optional public-corpus reconciliation.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from enoch_control_plane.control_plane.state_contract import (
    OperatorLane,
    STATE_REDUCTION_PLAN,
)  # noqa: E402
from scripts.normalize_state_surfaces import normalize  # noqa: E402
from scripts.reconcile_paper_ledgers import (  # noqa: E402
    classify_finalized_rows,
    iter_review_rows,
    load_public_index,
)
from scripts.validate_state_contract import validate  # noqa: E402

AGGREGATE_OPERATOR_COUNT_KEYS = {"needs_attention", "total_operator_items"}
REQUIRED_PAPER_PIPELINE_KEYS = {
    "write_needed",
    "raw_completed_no_paper_candidates",
    "not_writable_by_decision_gate",
    "finalize_needed",
    "publish_ready",
}
REQUIRED_INVESTIGATION_PIPELINE_KEYS = {
    "followup_needed",
    "max_followup_depth",
}
HARD_DRIFT_DISPOSITIONS = {"alias", "migrate_after_freeze"}
WARNING_DRIFT_DISPOSITIONS = {"legacy_internal"}
ACTIVE_QUEUE_STATUSES = (
    "dispatching",
    "running",
    "awaiting_wake",
    "wake_received",
    "reconciling",
)
ATTENTION_QUEUE_STATUSES = ("blocked", "needs_review", "dispatch_error")


def _legacy_runtime_context(database_url: str) -> dict[str, Any]:
    """Classify legacy/internal residue by runtime attachment.

    The state-reduction plan deliberately allows a small set of imported
    historical values (for example `runs.state=unknown` and blank
    `runs.gate_state`). This context check makes that warning deterministic:
    historical residue is tolerable, but the same residue attached to an active
    worker lane is runtime drift and should fail the doctor.
    """

    import psycopg

    active_statuses = ", ".join(f"'{status}'" for status in ACTIVE_QUEUE_STATUSES)
    attention_statuses = ", ".join(f"'{status}'" for status in ATTENTION_QUEUE_STATUSES)
    queries = {
        "ideas.idea_status.unknown": f"""
            select count(*) total,
                   count(*) filter (where q.project_id is not null) with_queue,
                   count(*) filter (where q.status in ({active_statuses})) active_queue,
                   count(*) filter (where q.status in ({attention_statuses})) attention_queue,
                   min(i.updated_at)::text oldest_updated_at,
                   max(i.updated_at)::text newest_updated_at
            from ideas i
            left join queue_items q on q.project_id = i.idea_id
            where coalesce(i.idea_status, '') = 'unknown'
        """,
        "projects.origin_idea_status.unknown": f"""
            select count(*) total,
                   count(*) filter (where q.project_id is not null) with_queue,
                   count(*) filter (where q.status in ({active_statuses})) active_queue,
                   count(*) filter (where q.status in ({attention_statuses})) attention_queue,
                   count(*) filter (where exists (select 1 from papers p where p.project_id = pr.project_id)) with_paper,
                   min(pr.updated_at)::text oldest_updated_at,
                   max(pr.updated_at)::text newest_updated_at
            from projects pr
            left join queue_items q on q.project_id = pr.project_id
            where coalesce(pr.origin_idea_status, '') = 'unknown'
        """,
        "runs.state.unknown": f"""
            select count(*) total,
                   count(*) filter (where q.current_run_id = r.run_id) current_queue_run,
                   count(*) filter (where q.current_run_id = r.run_id and q.status in ({active_statuses})) active_queue,
                   count(*) filter (where q.current_run_id = r.run_id and q.status in ({attention_statuses})) attention_queue,
                   count(*) filter (where exists (select 1 from papers p where p.run_id = r.run_id)) with_paper,
                   min(r.updated_at)::text oldest_updated_at,
                   max(r.updated_at)::text newest_updated_at
            from runs r
            left join queue_items q on q.project_id = r.project_id
            where coalesce(r.state, '') = 'unknown'
        """,
        "runs.gate_state.blank": f"""
            select count(*) total,
                   count(*) filter (where q.current_run_id = r.run_id) current_queue_run,
                   count(*) filter (where q.current_run_id = r.run_id and q.status in ({active_statuses})) active_queue,
                   count(*) filter (where q.current_run_id = r.run_id and q.status in ({attention_statuses})) attention_queue,
                   count(*) filter (where exists (select 1 from papers p where p.run_id = r.run_id)) with_paper,
                   min(r.updated_at)::text oldest_updated_at,
                   max(r.updated_at)::text newest_updated_at
            from runs r
            left join queue_items q on q.project_id = r.project_id
            where coalesce(r.gate_state, '') = ''
        """,
        "queue_items.last_run_state.blank": f"""
            select count(*) total,
                   count(*) filter (where q.status = 'queued' and coalesce(q.current_run_id, '') = '') queued_without_run,
                   count(*) filter (where q.status in ({active_statuses})) active_queue,
                   count(*) filter (where q.status in ({attention_statuses})) attention_queue,
                   min(q.updated_at)::text oldest_updated_at,
                   max(q.updated_at)::text newest_updated_at
            from queue_items q
            where coalesce(q.last_run_state, '') = ''
        """,
    }
    surfaces: dict[str, Any] = {}
    active_drift: list[dict[str, Any]] = []
    with psycopg.connect(database_url) as conn:
        with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
            cur.execute("set search_path to enoch, public")
            for surface, sql in queries.items():
                cur.execute(sql)
                row = dict(cur.fetchone() or {})
                row = {
                    key: (
                        int(value)
                        if key.endswith(("total", "queue", "run", "paper"))
                        else value
                    )
                    for key, value in row.items()
                }
                row["classification"] = (
                    "active_runtime_drift"
                    if int(row.get("active_queue") or 0)
                    else "historical_or_attention_residue"
                )
                surfaces[surface] = row
                if row["classification"] == "active_runtime_drift":
                    active_drift.append(
                        {
                            "surface": surface,
                            "active_queue": int(row.get("active_queue") or 0),
                            "total": int(row.get("total") or 0),
                        }
                    )
    return {"checked": True, "surfaces": surfaces, "active_runtime_drift": active_drift}


def _json_request(
    base_url: str, token: str, path: str, *, timeout: int = 60
) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    req = urllib.request.Request(base_url.rstrip("/") + path, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - operator-provided control URL
        return json.loads(resp.read())


def _load_token(*, token: str = "", token_file: str = "") -> str:
    if token:
        return token.strip()
    if token_file:
        return Path(token_file).read_text(encoding="utf-8").strip()
    return (
        os.environ.get("ENOCH_CONTROL_TOKEN")
        or os.environ.get("ENOCH_CONTROL_PLANE_TOKEN")
        or ""
    )


def _exception_text(exc: BaseException) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        return f"HTTP {exc.code}: {exc.reason}"
    if isinstance(exc, urllib.error.URLError):
        return f"URL error: {exc.reason}"
    return f"{exc.__class__.__name__}: {exc}"


def _live_reduction_drift(live_distincts: dict[str, Any]) -> dict[str, Any]:
    hard: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    by_surface: dict[str, list[dict[str, Any]]] = {}
    for surface, rows in sorted(live_distincts.items()):
        plan = STATE_REDUCTION_PLAN.get(surface, {})
        for value, count in rows:
            decision = plan.get(str(value), {})
            disposition = str(decision.get("disposition") or "")
            if (
                not count
                or disposition
                not in HARD_DRIFT_DISPOSITIONS | WARNING_DRIFT_DISPOSITIONS
            ):
                continue
            item = {
                "surface": surface,
                "value": str(value),
                "rows": int(count),
                "disposition": disposition,
                "replacement": str(decision.get("replacement") or ""),
                "operator_lane": str(decision.get("operator_lane") or ""),
                "reason": str(decision.get("reason") or ""),
            }
            by_surface.setdefault(surface, []).append(item)
            if disposition in HARD_DRIFT_DISPOSITIONS:
                hard.append(item)
            else:
                warnings.append(item)
    return {"hard_rows": hard, "warning_rows": warnings, "by_surface": by_surface}


def _dashboard_audit(overview: dict[str, Any]) -> dict[str, Any]:
    operator_counts = dict(overview.get("operator_counts") or {})
    detail_counts = dict(overview.get("operator_detail_counts") or {})
    allowed_operator_count_keys = {
        lane.value for lane in OperatorLane
    } | AGGREGATE_OPERATOR_COUNT_KEYS
    raw_detail_keys = sorted(set(operator_counts) - allowed_operator_count_keys)
    pipeline = dict(overview.get("paper_pipeline") or {})
    missing_pipeline_keys = sorted(REQUIRED_PAPER_PIPELINE_KEYS - set(pipeline))
    investigation_pipeline = dict(overview.get("investigation_pipeline") or {})
    missing_investigation_keys = sorted(
        REQUIRED_INVESTIGATION_PIPELINE_KEYS - set(investigation_pipeline)
    )
    write_needed = int(pipeline.get("write_needed") or 0)
    raw_candidates = int(pipeline.get("raw_completed_no_paper_candidates") or 0)
    gate_rejected = int(pipeline.get("not_writable_by_decision_gate") or 0)
    pipeline_inconsistent = (
        raw_candidates < write_needed or raw_candidates - write_needed != gate_rejected
    )
    return {
        "ok": not raw_detail_keys
        and not missing_pipeline_keys
        and not missing_investigation_keys
        and not pipeline_inconsistent,
        "operator_count_keys": sorted(operator_counts),
        "raw_detail_keys_in_operator_counts": raw_detail_keys,
        "operator_detail_count_keys": sorted(detail_counts),
        "paper_pipeline": {
            key: pipeline.get(key) for key in sorted(REQUIRED_PAPER_PIPELINE_KEYS)
        },
        "paper_pipeline_definitions": pipeline.get("definitions") or {},
        "missing_paper_pipeline_keys": missing_pipeline_keys,
        "paper_pipeline_inconsistent": pipeline_inconsistent,
        "investigation_pipeline": {
            key: investigation_pipeline.get(key)
            for key in sorted(REQUIRED_INVESTIGATION_PIPELINE_KEYS)
        },
        "investigation_pipeline_definitions": investigation_pipeline.get("definitions")
        or {},
        "missing_investigation_pipeline_keys": missing_investigation_keys,
        "paper_counts": overview.get("paper_counts") or {},
        "counts": overview.get("counts") or {},
    }


def _control_audit(*, control_url: str, token: str) -> dict[str, Any]:
    result: dict[str, Any] = {
        "control_url": control_url,
        "overview_ok": False,
        "health_ok": False,
    }
    try:
        overview = _json_request(
            control_url, token, "/control/api/v1/overview?active_limit=5&event_limit=5"
        )
        result["overview_ok"] = bool(overview.get("ok", True))
        result["overview"] = _dashboard_audit(overview)
    except Exception as exc:  # noqa: BLE001 - report any live smoke failure
        result["overview_error"] = _exception_text(exc)
    try:
        health = _json_request(
            control_url, token, "/control/api/v1/observability/health"
        )
        result["health_ok"] = bool(health.get("ok", True))
        result["health"] = {
            "route_observability_enabled": health.get("route_observability_enabled"),
            "latest_observation_at": health.get("latest_observation_at"),
        }
    except Exception as exc:  # noqa: BLE001
        result["health_error"] = _exception_text(exc)
    return result


def _corpus_audit(
    *, control_url: str, token: str, corpus: Path, page_size: int
) -> dict[str, Any]:
    result: dict[str, Any] = {"corpus": str(corpus), "checked": False}
    try:
        finalized_rows = iter_review_rows(
            control_url,
            token,
            review_status="finalized",
            paper_status="publication_draft",
            page_size=page_size,
        )
        public = load_public_index(corpus)
        classified = classify_finalized_rows(finalized_rows, public)
        result.update(
            {
                "checked": True,
                "live_finalized_publication_draft_count": len(finalized_rows),
                "public_corpus_count": public["count"],
                "exact_existing_finalized_count": len(classified["exact_existing"]),
                "importable_finalized_count": len(classified["importable"]),
                "importable_finalized_sample": [
                    {
                        "paper_id": str(row.get("paper_id") or ""),
                        "project_id": str(row.get("project_id") or ""),
                        "project_name": str(row.get("project_name") or ""),
                    }
                    for row in classified["importable"][:10]
                ],
            }
        )
    except Exception as exc:  # noqa: BLE001
        result["error"] = _exception_text(exc)
    return result


def evaluate_report(
    report: dict[str, Any], *, require_corpus_synced: bool = False
) -> dict[str, list[str]]:
    failures: list[str] = []
    warnings: list[str] = []

    state_contract = report.get("state_contract") or {}
    if not state_contract.get("ok"):
        failures.extend(
            f"state contract: {item}"
            for item in state_contract.get("failures") or ["failed"]
        )

    normalization = report.get("normalization") or {}
    if normalization.get("checked") and int(normalization.get("total_rows") or 0) != 0:
        failures.append(
            f"normalization dry-run would update {normalization.get('total_rows')} row(s)"
        )
    elif not normalization.get("checked"):
        warnings.append(
            "normalization dry-run skipped because no database URL was supplied"
        )

    legacy_context = report.get("legacy_runtime_context") or {}
    legacy_surfaces = legacy_context.get("surfaces") or {}

    drift = report.get("live_reduction_drift") or {}
    for row in drift.get("hard_rows") or []:
        failures.append(
            "live reduction drift: {surface}.{value} has {rows} row(s) with disposition {disposition}".format(
                **row
            )
        )
    for row in drift.get("warning_rows") or []:
        surface = str(row.get("surface") or "")
        value = str(row.get("value") or "")
        context_key = f"{surface}.{value if value else 'blank'}"
        context = legacy_surfaces.get(context_key) or {}
        if context.get(
            "classification"
        ) == "historical_or_attention_residue" and not int(
            context.get("active_queue") or 0
        ):
            continue
        warnings.append(
            "legacy internal rows remain: {surface}.{value} has {rows} row(s)".format(
                **row
            )
        )

    for row in legacy_context.get("active_runtime_drift") or []:
        failures.append(
            "legacy/internal state attached to active runtime lane: {surface} has {active_queue} active row(s) out of {total}".format(
                **row
            )
        )

    control = report.get("control_plane") or {}
    if control.get("checked"):
        if not control.get("overview_ok"):
            failures.append(
                f"control overview unavailable: {control.get('overview_error', 'not ok')}"
            )
        overview = control.get("overview") or {}
        for key in overview.get("raw_detail_keys_in_operator_counts") or []:
            failures.append(f"raw/detail stage leaked into operator_counts: {key}")
        if overview.get("missing_paper_pipeline_keys"):
            failures.append(
                f"paper_pipeline missing keys: {overview['missing_paper_pipeline_keys']}"
            )
        if overview.get("missing_investigation_pipeline_keys"):
            failures.append(
                f"investigation_pipeline missing keys: {overview['missing_investigation_pipeline_keys']}"
            )
        if overview.get("paper_pipeline_inconsistent"):
            failures.append(
                "paper_pipeline counts are inconsistent: raw candidates must equal write_needed + gate rejected"
            )
        if not control.get("health_ok"):
            warnings.append(
                f"control health smoke unavailable: {control.get('health_error', 'not ok')}"
            )
    else:
        warnings.append(
            "control-plane smoke skipped because no token/control URL was supplied"
        )

    corpus = report.get("corpus_reconciliation") or {}
    if corpus.get("checked"):
        importable = int(corpus.get("importable_finalized_count") or 0)
        if require_corpus_synced and importable:
            failures.append(
                f"corpus reconciliation has {importable} finalized publication draft(s) not in the public corpus"
            )
        elif importable:
            warnings.append(
                f"corpus reconciliation has {importable} finalized publication draft(s) not in the public corpus"
            )
    elif corpus:
        warnings.append(
            f"corpus reconciliation skipped or failed: {corpus.get('error', 'not checked')}"
        )

    return {"failures": failures, "warnings": warnings}


def run_doctor(
    *,
    database_url: str = "",
    control_url: str = "",
    token: str = "",
    corpus: Path | None = None,
    page_size: int = 200,
    require_corpus_synced: bool = False,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "source": "scripts/state_doctor.py",
        "state_contract": {},
        "normalization": {"checked": False},
        "live_reduction_drift": {"hard_rows": [], "warning_rows": [], "by_surface": {}},
        "legacy_runtime_context": {
            "checked": False,
            "surfaces": {},
            "active_runtime_drift": [],
        },
        "control_plane": {"checked": False},
    }

    state_contract = validate(database_url=database_url) if database_url else validate()
    report["state_contract"] = {
        "ok": state_contract.get("ok"),
        "failures": state_contract.get("failures") or [],
        "live_distincts": state_contract.get("live_distincts") or {},
    }
    if database_url:
        normalization = normalize(database_url, apply=False)
        report["normalization"] = {"checked": True, **normalization}
        report["live_reduction_drift"] = _live_reduction_drift(
            state_contract.get("live_distincts") or {}
        )
        report["legacy_runtime_context"] = _legacy_runtime_context(database_url)

    if control_url and token:
        report["control_plane"] = {
            "checked": True,
            **_control_audit(control_url=control_url, token=token),
        }

    if corpus is not None:
        report["corpus_reconciliation"] = {"corpus": str(corpus), "checked": False}
        if token and control_url and corpus.exists():
            report["corpus_reconciliation"] = _corpus_audit(
                control_url=control_url,
                token=token,
                corpus=corpus,
                page_size=page_size,
            )
        elif not corpus.exists():
            report["corpus_reconciliation"]["error"] = "corpus path does not exist"
        else:
            report["corpus_reconciliation"]["error"] = "missing token or control URL"

    evaluation = evaluate_report(report, require_corpus_synced=require_corpus_synced)
    report["failures"] = evaluation["failures"]
    report["warnings"] = evaluation["warnings"]
    report["ok"] = not report["failures"]
    return report


def _print_human(report: dict[str, Any]) -> None:
    print("Enoch state doctor")
    print(f"  overall: {'OK' if report.get('ok') else 'FAIL'}")
    print(
        f"  state contract: {'OK' if (report.get('state_contract') or {}).get('ok') else 'FAIL'}"
    )
    normalization = report.get("normalization") or {}
    if normalization.get("checked"):
        print(f"  normalization dry-run rows: {normalization.get('total_rows')}")
    control = report.get("control_plane") or {}
    if control.get("checked"):
        overview = control.get("overview") or {}
        pipeline = overview.get("paper_pipeline") or {}
        print(f"  control overview: {'OK' if control.get('overview_ok') else 'FAIL'}")
        print(
            "  paper pipeline: write_needed={write_needed} raw_completed_no_paper_candidates={raw_completed_no_paper_candidates} "
            "not_writable_by_decision_gate={not_writable_by_decision_gate} finalize_needed={finalize_needed} publish_ready={publish_ready}".format(
                **{key: pipeline.get(key, "?") for key in REQUIRED_PAPER_PIPELINE_KEYS}
            )
        )
        investigation = overview.get("investigation_pipeline") or {}
        print(
            "  investigation pipeline: followup_needed={followup_needed} max_followup_depth={max_followup_depth}".format(
                **{
                    key: investigation.get(key, "?")
                    for key in REQUIRED_INVESTIGATION_PIPELINE_KEYS
                }
            )
        )
        print(
            f"  operator_count keys: {', '.join(overview.get('operator_count_keys') or [])}"
        )
    legacy_context = report.get("legacy_runtime_context") or {}
    if legacy_context.get("checked"):
        active = legacy_context.get("active_runtime_drift") or []
        print(
            f"  legacy runtime context: {'OK' if not active else 'FAIL'} ({len(active)} active drift surface(s))"
        )
        for surface, row in sorted((legacy_context.get("surfaces") or {}).items()):
            print(
                "    {surface}: total={total} active_queue={active_queue} attention_queue={attention_queue} classification={classification}".format(
                    surface=surface,
                    total=row.get("total", 0),
                    active_queue=row.get("active_queue", 0),
                    attention_queue=row.get("attention_queue", 0),
                    classification=row.get("classification", "unknown"),
                )
            )
    corpus = report.get("corpus_reconciliation") or {}
    if corpus:
        if corpus.get("checked"):
            print(
                "  corpus reconciliation: finalized_publication_drafts={live_finalized_publication_draft_count} "
                "public_corpus={public_corpus_count} importable={importable_finalized_count}".format(
                    **corpus
                )
            )
        else:
            print(
                f"  corpus reconciliation: skipped ({corpus.get('error', 'not checked')})"
            )
    for item in report.get("failures") or []:
        print(f"  FAIL {item}")
    for item in report.get("warnings") or []:
        print(f"  WARN {item}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the Enoch state doctor before answering operator state/count questions."
    )
    parser.add_argument(
        "--database-url",
        default=os.environ.get("ENOCH_SUPABASE_DATABASE_URL", ""),
        help="Optional live Supabase/Postgres URL. Omitted from output.",
    )
    parser.add_argument(
        "--control-url",
        default=os.environ.get("ENOCH_CONTROL_URL")
        or os.environ.get("ENOCH_CONTROL_PLANE_URL")
        or "http://127.0.0.1:8787",
    )
    parser.add_argument(
        "--token",
        default="",
        help="Control-plane bearer token. Prefer --token-file/env; value is never printed.",
    )
    parser.add_argument(
        "--token-file",
        default="",
        help="File containing the control-plane bearer token.",
    )
    parser.add_argument(
        "--corpus",
        type=Path,
        default=None,
        help="Optional public corpus checkout for publication/corpus reconciliation.",
    )
    parser.add_argument("--page-size", type=int, default=200)
    parser.add_argument(
        "--warn-only-corpus",
        action="store_true",
        help="Downgrade corpus/public count drift to a warning. Default fails when --corpus is checked and importable finalized drafts remain.",
    )
    parser.add_argument(
        "--json", action="store_true", help="Emit the full JSON report."
    )
    parser.add_argument(
        "--output", type=Path, default=None, help="Optional JSON report path."
    )
    args = parser.parse_args()

    token = _load_token(token=args.token, token_file=args.token_file)
    report = run_doctor(
        database_url=args.database_url,
        control_url=args.control_url,
        token=token,
        corpus=args.corpus,
        page_size=args.page_size,
        require_corpus_synced=bool(args.corpus and not args.warn_only_corpus),
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        _print_human(report)
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
