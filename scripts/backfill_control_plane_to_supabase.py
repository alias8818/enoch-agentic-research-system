#!/usr/bin/env python3
"""Backfill the SQLite Enoch control-plane DB into the private Supabase schema.

Safety defaults:
- dry-run unless --apply is passed;
- rollback on dry-run after computing target counts;
- --reset-target is allowed only with --apply;
- no database URL is printed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from enoch_control_plane.enoch_core.logic import paper_draft_decision_gate

HASH_RE = re.compile(r"^[a-f0-9]{64}$")
DOMAIN_TABLES = (
    "operator_observations",
    "control_events",
    "corpus_imports",
    "publication_automation_items",
    "papers",
    "project_decisions",
    "runs",
    "queue_items",
    "projects",
)

POSTGRES_TABLE_COLUMNS = {
    "control_events": {
        "idempotency_key",
        "event_type",
        "entity_type",
        "entity_id",
        "payload_hash",
    },
    "papers": {"paper_id", "project_id", "run_id", "paper_type"},
    "publication_automation_items": {"paper_id"},
    "runs": {"run_id", "project_id"},
}

SQLITE_TABLE_ORDER_COLUMNS = {
    "projects": {"project_id"},
    "queue_items": {"project_id"},
    "runs": {"run_id"},
    "papers": {"paper_id"},
    "paper_review_items": {"paper_id"},
    "events": {"event_id"},
    "dashboard_observations": {"observation_id"},
    "control_flags": set(),
}


def sqlite_identifier(value: str, *, allowed: set[str], kind: str) -> str:
    if value not in allowed:
        raise ValueError(f"unsupported sqlite {kind}: {value}")
    return f'"{value}"'


def postgres_identifier(value: str, *, allowed: set[str], kind: str) -> str:
    if value not in allowed:
        raise ValueError(f"unsupported postgres {kind}: {value}")
    return value


def json_text(value: Any, default: Any) -> str:
    if value in (None, ""):
        return json.dumps(default, sort_keys=True, separators=(",", ":"))
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            parsed = default
        return json.dumps(parsed, sort_keys=True, separators=(",", ":"))
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def stable_hash(value: Any) -> str:
    text = value if isinstance(value, str) else json_text(value, {})
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def valid_hash(value: Any, payload: Any) -> str:
    text = "" if value is None else str(value)
    return text if HASH_RE.fullmatch(text) else stable_hash(payload)


def rows(conn: sqlite3.Connection, table: str, *, order_by: str = "") -> list[dict[str, Any]]:
    quoted_table = sqlite_identifier(table, allowed=set(SQLITE_TABLE_ORDER_COLUMNS), kind="table")
    if order_by:
        quoted_order_by = sqlite_identifier(order_by, allowed=SQLITE_TABLE_ORDER_COLUMNS[table], kind="order_by")
        suffix = f" order by {quoted_order_by}"
    else:
        suffix = ""
    try:
        return [dict(row) for row in conn.execute(f"select * from {quoted_table}{suffix}").fetchall()]
    except sqlite3.OperationalError:
        return []


def table_counts_sqlite(conn: sqlite3.Connection) -> dict[str, int]:
    tables = ("projects", "queue_items", "runs", "papers", "paper_review_items", "events", "dashboard_observations")
    counts: dict[str, int] = {}
    for table in tables:
        try:
            quoted_table = sqlite_identifier(table, allowed=set(SQLITE_TABLE_ORDER_COLUMNS), kind="table")
            counts[table] = int(conn.execute(f"select count(*) from {quoted_table}").fetchone()[0])
        except sqlite3.OperationalError:
            counts[table] = 0
    return counts


def execute_many(cur: Any, sql: str, params: Iterable[Sequence[Any]]) -> int:
    count = 0
    for item in params:
        cur.execute(sql, tuple(item))
        count += 1
    return count


def reject_target_identity_conflicts(
    cur: Any,
    *,
    table: str,
    key_columns: Sequence[str],
    identity_columns: Sequence[str],
    source_rows: Iterable[dict[str, Any]],
) -> None:
    """Fail closed when target upserts would rewrite immutable identity fields."""

    allowed_columns = POSTGRES_TABLE_COLUMNS.get(table)
    if allowed_columns is None:
        raise ValueError(f"unsupported postgres table: {table}")
    table_sql = postgres_identifier(table, allowed=set(POSTGRES_TABLE_COLUMNS), kind="table")
    key_sql = [
        postgres_identifier(column, allowed=allowed_columns, kind="column")
        for column in key_columns
    ]
    identity_sql = [
        postgres_identifier(column, allowed=allowed_columns, kind="column")
        for column in identity_columns
    ]
    select_columns = ", ".join(identity_sql)
    where_clause = " and ".join(f"{column} = %s" for column in key_sql)
    sql = f"select {select_columns} from {table_sql} where {where_clause}"
    for row in source_rows:
        key_values = tuple(row.get(column) for column in key_columns)
        if any(value in (None, "") for value in key_values):
            continue
        existing = cur.execute(sql, key_values).fetchone()
        if not existing:
            continue
        for column in identity_columns:
            if existing.get(column) != row.get(column):
                key_text = ", ".join(f"{name}={value!r}" for name, value in zip(key_columns, key_values, strict=True))
                raise ValueError(
                    f"conflicting target {table} identity for {key_text}: "
                    f"{column} target={existing.get(column)!r} source={row.get(column)!r}"
                )


def decision_file_candidates(project: dict[str, Any], project_roots: Sequence[Path]) -> list[Path]:
    candidates: list[Path] = []
    project_dir = str(project.get("project_dir") or "").strip()
    project_id = str(project.get("project_id") or "").strip()
    names = [value for value in (project_dir, project_id) if value]
    for name in names:
        path = Path(name).expanduser()
        if path.is_absolute():
            candidates.append(path)
    for root in project_roots:
        expanded = root.expanduser()
        for name in names:
            if name:
                candidates.append(expanded / name)
    seen: set[str] = set()
    result: list[Path] = []
    for candidate in candidates:
        key = str(candidate)
        if key not in seen:
            seen.add(key)
            result.append(candidate)
    return result


def decision_gate_state(gate: dict[str, Any]) -> str:
    if gate.get("eligible") is True:
        return "positive"
    reason = str(gate.get("reason") or "").lower()
    decision = str(gate.get("decision") or "").lower()
    if "missing" in reason:
        return "missing"
    if "could not" in reason or "malformed" in reason:
        return "malformed"
    if any(token in decision or token in reason for token in ("needs_review", "inconclusive", "caveat", "conditional")):
        return "unknown"
    if any(token in decision or token in reason for token in ("negative", "reject", "not positive", "nonpositive", "non_positive")):
        return "negative"
    return "unknown"


def load_project_decisions(projects: list[dict[str, Any]], queue_by_project: dict[str, dict[str, Any]], project_roots: Sequence[Path]) -> list[dict[str, Any]]:
    decisions: list[dict[str, Any]] = []
    if not project_roots:
        return decisions
    for project in projects:
        project_id = str(project.get("project_id") or "")
        if not project_id:
            continue
        queue_row = queue_by_project.get(project_id, {})
        for root in decision_file_candidates(project, project_roots):
            gate = paper_draft_decision_gate(root)
            if gate.get("values") or gate.get("reason") != "missing project decision artifact":
                payload = {"gate": gate, "project_root": str(root)}
                decisions.append({
                    "project_id": project_id,
                    "run_id": str(queue_row.get("current_run_id") or "") or None,
                    "decision_gate_state": decision_gate_state(gate),
                    "decision_summary": str(gate.get("decision") or gate.get("reason") or ""),
                    "artifact_path": str(root / ".enoch" / "project_decision.json") if (root / ".enoch" / "project_decision.json").exists() else (str(root / ".omx" / "project_decision.json") if (root / ".omx" / "project_decision.json").exists() else str(root / "project_decision.json")),
                    "payload_json": json_text(payload, {}),
                    "payload_hash": stable_hash(payload),
                    "decided_at": project.get("updated_at") or queue_row.get("updated_at"),
                })
                break
    return decisions


def import_sqlite_to_postgres(
    *,
    sqlite_path: Path,
    database_url: str,
    apply: bool,
    reset_target: bool,
    observation_limit: int,
    project_roots: Sequence[Path] = (),
) -> dict[str, Any]:
    if reset_target and not apply:
        raise ValueError("--reset-target requires --apply so dry-run cannot erase then roll back misleadingly")

    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:  # pragma: no cover - dependency declared in pyproject.
        raise RuntimeError("psycopg is required; run via uv or install project dependencies") from exc

    sqlite_path = sqlite_path.expanduser().resolve()
    if not sqlite_path.exists():
        raise FileNotFoundError(sqlite_path)

    sqlite_conn = sqlite3.connect(sqlite_path)
    sqlite_conn.row_factory = sqlite3.Row
    try:
        source_counts = table_counts_sqlite(sqlite_conn)
        project_rows = rows(sqlite_conn, "projects", order_by="project_id")
        queue_rows = rows(sqlite_conn, "queue_items", order_by="project_id")
        run_rows = rows(sqlite_conn, "runs", order_by="run_id")
        paper_rows = rows(sqlite_conn, "papers", order_by="paper_id")
        review_rows = rows(sqlite_conn, "paper_review_items", order_by="paper_id")
        event_rows = rows(sqlite_conn, "events", order_by="event_id")
        if observation_limit < 0:
            observation_rows = rows(sqlite_conn, "dashboard_observations", order_by="observation_id")
        elif observation_limit == 0:
            observation_rows = []
        else:
            observation_rows = [
                dict(row)
                for row in sqlite_conn.execute(
                    "select * from dashboard_observations order by observation_id desc limit ?",
                    (observation_limit,),
                ).fetchall()
            ]
        flags = rows(sqlite_conn, "control_flags")
    finally:
        sqlite_conn.close()

    run_ids = {str(row.get("run_id") or "") for row in run_rows if row.get("run_id")}
    queue_by_project = {str(row.get("project_id") or ""): row for row in queue_rows}
    decision_rows = load_project_decisions(project_rows, queue_by_project, project_roots)
    run_identity_rows = [
        {"run_id": row.get("run_id"), "project_id": row.get("project_id")}
        for row in run_rows
    ]
    paper_identity_rows = [
        {
            "paper_id": row.get("paper_id"),
            "project_id": row.get("project_id"),
            "run_id": row.get("run_id") if row.get("run_id") in run_ids else None,
            "paper_type": row.get("paper_type") or "arxiv_draft",
        }
        for row in paper_rows
    ]
    event_identity_rows = [
        {
            "idempotency_key": row.get("idempotency_key") or f"sqlite-event:{row.get('event_id')}",
            "event_type": row.get("event_type") or "unknown",
            "entity_type": row.get("entity_type") or "unknown",
            "entity_id": row.get("entity_id") or "",
            "payload_hash": valid_hash(row.get("payload_hash"), row.get("payload_json") or "{}"),
        }
        for row in event_rows
    ]

    imported: dict[str, int] = {
        "projects": 0,
        "queue_items": 0,
        "runs": 0,
        "papers": 0,
        "publication_automation_items": 0,
        "project_decisions": 0,
        "control_events": 0,
        "operator_observations": 0,
    }

    with psycopg.connect(database_url, row_factory=dict_row) as pg_conn:
        with pg_conn.cursor() as cur:
            cur.execute("set search_path to enoch, public")
            if reset_target:
                cur.execute("truncate table " + ", ".join(f"enoch.{table}" for table in DOMAIN_TABLES) + " restart identity cascade")
                cur.execute("delete from enoch.control_flags where singleton = true")

            reject_target_identity_conflicts(
                cur,
                table="runs",
                key_columns=("run_id",),
                identity_columns=("project_id",),
                source_rows=run_identity_rows,
            )
            reject_target_identity_conflicts(
                cur,
                table="papers",
                key_columns=("paper_id",),
                identity_columns=("project_id", "run_id", "paper_type"),
                source_rows=paper_identity_rows,
            )
            reject_target_identity_conflicts(
                cur,
                table="control_events",
                key_columns=("idempotency_key",),
                identity_columns=("event_type", "entity_type", "entity_id", "payload_hash"),
                source_rows=event_identity_rows,
            )

            if flags:
                flag = flags[0]
                cur.execute(
                    """
                    insert into control_flags(singleton, queue_paused, maintenance_mode, pause_reason, paused_at, paused_by, updated_at)
                    values (true, %s, %s, %s, %s, %s, %s)
                    on conflict (singleton) do update set
                      queue_paused = excluded.queue_paused,
                      maintenance_mode = excluded.maintenance_mode,
                      pause_reason = excluded.pause_reason,
                      paused_at = excluded.paused_at,
                      paused_by = excluded.paused_by,
                      updated_at = excluded.updated_at
                    where excluded.updated_at >= control_flags.updated_at
                    """,
                    (
                        bool(flag.get("queue_paused")),
                        bool(flag.get("maintenance_mode")),
                        str(flag.get("pause_reason") or ""),
                        flag.get("paused_at"),
                        str(flag.get("paused_by") or ""),
                        flag.get("updated_at"),
                    ),
                )

            imported["projects"] = execute_many(
                cur,
                """
                insert into projects(project_id, project_name, project_dir, notion_page_url, notion_page_id,
                  origin_idea_status, created_at, updated_at)
                values (%s,%s,%s,%s,%s,%s,%s,%s)
                on conflict (project_id) do update set
                  project_name=excluded.project_name,
                  project_dir=excluded.project_dir,
                  notion_page_url=excluded.notion_page_url,
                  notion_page_id=excluded.notion_page_id,
                  origin_idea_status=excluded.origin_idea_status,
                  created_at=excluded.created_at,
                  updated_at=excluded.updated_at
                where excluded.updated_at >= projects.updated_at
                """,
                (
                    (
                        row.get("project_id"),
                        row.get("project_name") or row.get("project_id"),
                        row.get("project_dir") or "",
                        row.get("notion_page_url") or "",
                        row.get("notion_page_id") or "",
                        row.get("origin_idea_status") or "unknown",
                        row.get("created_at"),
                        row.get("updated_at"),
                    )
                    for row in project_rows
                ),
            )

            imported["queue_items"] = execute_many(
                cur,
                """
                insert into queue_items(project_id, status, selection_rank, dispatch_priority, auto_continue,
                  continue_count, max_continues, retry_count, max_retries, current_run_id, current_session_id,
                  last_run_state, last_event_type, next_action_hint, manual_review_required, blocked_reason,
                  last_error, last_result_summary, machine_target, model, sandbox, last_dispatch_at,
                  last_callback_at, stale_after, updated_at)
                values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                on conflict (project_id) do update set
                  status=excluded.status, selection_rank=excluded.selection_rank,
                  dispatch_priority=excluded.dispatch_priority, auto_continue=excluded.auto_continue,
                  continue_count=excluded.continue_count, max_continues=excluded.max_continues,
                  retry_count=excluded.retry_count, max_retries=excluded.max_retries,
                  current_run_id=excluded.current_run_id, current_session_id=excluded.current_session_id,
                  last_run_state=excluded.last_run_state, last_event_type=excluded.last_event_type,
                  next_action_hint=excluded.next_action_hint, manual_review_required=excluded.manual_review_required,
                  blocked_reason=excluded.blocked_reason, last_error=excluded.last_error,
                  last_result_summary=excluded.last_result_summary, machine_target=excluded.machine_target,
                  model=excluded.model, sandbox=excluded.sandbox, last_dispatch_at=excluded.last_dispatch_at,
                  last_callback_at=excluded.last_callback_at, stale_after=excluded.stale_after,
                  updated_at=excluded.updated_at
                where excluded.updated_at >= queue_items.updated_at
                """,
                (
                    (
                        row.get("project_id"), row.get("status") or "unknown", int(row.get("selection_rank") or 0),
                        int(row.get("dispatch_priority") or 0), bool(row.get("auto_continue")), int(row.get("continue_count") or 0),
                        int(row.get("max_continues") or 0), int(row.get("retry_count") or 0), int(row.get("max_retries") or 0),
                        row.get("current_run_id") or "", row.get("current_session_id") or "", row.get("last_run_state") or "",
                        row.get("last_event_type") or "", row.get("next_action_hint") or "", bool(row.get("manual_review_required")),
                        row.get("blocked_reason") or "", row.get("last_error") or "", row.get("last_result_summary") or "",
                        row.get("machine_target") or "", row.get("model") or "", row.get("sandbox") or "",
                        row.get("last_dispatch_at"), row.get("last_callback_at"), row.get("stale_after"), row.get("updated_at"),
                    )
                    for row in queue_rows
                ),
            )

            imported["runs"] = execute_many(
                cur,
                """
                insert into runs(run_id, project_id, session_id, state, dispatch_mode, started_at, ended_at,
                  last_callback_at, gate_state, current_activity, idempotency_key, updated_at)
                values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                on conflict (run_id) do update set
                  project_id=excluded.project_id, session_id=excluded.session_id, state=excluded.state,
                  dispatch_mode=excluded.dispatch_mode, started_at=excluded.started_at, ended_at=excluded.ended_at,
                  last_callback_at=excluded.last_callback_at, gate_state=excluded.gate_state,
                  current_activity=excluded.current_activity, idempotency_key=excluded.idempotency_key,
                  updated_at=excluded.updated_at
                where excluded.updated_at >= runs.updated_at
                """,
                (
                    (
                        row.get("run_id"), row.get("project_id"), row.get("session_id") or "", row.get("state") or "unknown",
                        row.get("dispatch_mode") or "", row.get("started_at"), row.get("ended_at"), row.get("last_callback_at"),
                        row.get("gate_state") or "", row.get("current_activity") or "",
                        row.get("idempotency_key") or f"sqlite-run:{row.get('run_id')}", row.get("updated_at"),
                    )
                    for row in run_rows
                ),
            )

            imported["papers"] = execute_many(
                cur,
                """
                insert into papers(paper_id, project_id, run_id, paper_type, paper_status,
                  draft_markdown_path, draft_latex_path, evidence_bundle_path, claim_ledger_path,
                  manifest_path, artifact_root, artifact_payload_hash, generated_at, updated_at)
                values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                on conflict (paper_id) do update set
                  project_id=excluded.project_id, run_id=excluded.run_id, paper_type=excluded.paper_type,
                  paper_status=excluded.paper_status, draft_markdown_path=excluded.draft_markdown_path,
                  draft_latex_path=excluded.draft_latex_path, evidence_bundle_path=excluded.evidence_bundle_path,
                  claim_ledger_path=excluded.claim_ledger_path, manifest_path=excluded.manifest_path,
                  artifact_root=excluded.artifact_root, artifact_payload_hash=excluded.artifact_payload_hash,
                  generated_at=excluded.generated_at, updated_at=excluded.updated_at
                where excluded.updated_at >= papers.updated_at
                """,
                (
                    (
                        row.get("paper_id"), row.get("project_id"), row.get("run_id") if row.get("run_id") in run_ids else None,
                        row.get("paper_type") or "arxiv_draft", row.get("paper_status") or "unknown",
                        row.get("draft_markdown_path") or "", row.get("draft_latex_path") or "",
                        row.get("evidence_bundle_path") or "", row.get("claim_ledger_path") or "",
                        row.get("manifest_path") or "", row.get("artifact_root") or "", row.get("artifact_payload_hash") or "",
                        row.get("generated_at"), row.get("updated_at"),
                    )
                    for row in paper_rows
                ),
            )

            imported["project_decisions"] = execute_many(
                cur,
                """
                insert into project_decisions(project_id, run_id, decision_type, decision_gate_state,
                  decision_summary, artifact_path, payload_json, payload_hash, decided_at)
                values (%s,%s,'project_outcome',%s,%s,%s,%s::jsonb,%s,%s)
                on conflict (project_id, run_id, decision_type) do update set
                  decision_gate_state=excluded.decision_gate_state,
                  decision_summary=excluded.decision_summary,
                  artifact_path=excluded.artifact_path,
                  payload_json=excluded.payload_json,
                  payload_hash=excluded.payload_hash,
                  decided_at=excluded.decided_at
                where excluded.decided_at >= project_decisions.decided_at
                """,
                (
                    (
                        row["project_id"], row["run_id"] if row["run_id"] in run_ids else None,
                        row["decision_gate_state"], row["decision_summary"], row["artifact_path"],
                        row["payload_json"], row["payload_hash"], row["decided_at"],
                    )
                    for row in decision_rows
                ),
            )

            imported["publication_automation_items"] = execute_many(
                cur,
                """
                insert into publication_automation_items(paper_id, automation_status, automation_actor, blocker,
                  claimed_at, checklist_json, rank_score, rank_reasons_json, missing_signals_json,
                  rank_tiebreaker, source_audit_path, finalization_package_path, finalized_at,
                  decision_summary, created_at, updated_at)
                values (%s,%s,%s,%s,%s,%s::jsonb,%s,%s::jsonb,%s::jsonb,%s,%s,%s,%s,%s,%s,%s)
                on conflict (paper_id) do update set
                  automation_status=excluded.automation_status, automation_actor=excluded.automation_actor,
                  blocker=excluded.blocker, claimed_at=excluded.claimed_at, checklist_json=excluded.checklist_json,
                  rank_score=excluded.rank_score, rank_reasons_json=excluded.rank_reasons_json,
                  missing_signals_json=excluded.missing_signals_json, rank_tiebreaker=excluded.rank_tiebreaker,
                  source_audit_path=excluded.source_audit_path, finalization_package_path=excluded.finalization_package_path,
                  finalized_at=excluded.finalized_at, decision_summary=excluded.decision_summary,
                  created_at=excluded.created_at, updated_at=excluded.updated_at
                where excluded.updated_at >= publication_automation_items.updated_at
                """,
                (
                    (
                        row.get("paper_id"), row.get("review_status") or "unreviewed", row.get("reviewer") or "",
                        row.get("blocker") or "", row.get("claimed_at") or None, json_text(row.get("checklist_json"), {}),
                        int(row.get("rank_score") or 0), json_text(row.get("rank_reasons_json"), []),
                        json_text(row.get("missing_signals_json"), []), row.get("rank_tiebreaker") or "",
                        row.get("source_audit_path") or "", row.get("finalization_package_path") or "",
                        row.get("finalized_at") or None, row.get("decision_summary") or "",
                        row.get("created_at"), row.get("updated_at"),
                    )
                    for row in review_rows
                ),
            )

            imported["control_events"] = execute_many(
                cur,
                """
                insert into control_events(idempotency_key, event_type, entity_type, entity_id, payload_json, payload_hash, created_at)
                values (%s,%s,%s,%s,%s::jsonb,%s,%s)
                on conflict (idempotency_key) do update set
                  event_type=excluded.event_type, entity_type=excluded.entity_type, entity_id=excluded.entity_id,
                  payload_json=excluded.payload_json, payload_hash=excluded.payload_hash, created_at=excluded.created_at
                """,
                (
                    (
                        row.get("idempotency_key") or f"sqlite-event:{row.get('event_id')}", row.get("event_type") or "unknown",
                        row.get("entity_type") or "unknown", row.get("entity_id") or "",
                        json_text(row.get("payload_json"), {}), valid_hash(row.get("payload_hash"), row.get("payload_json") or "{}"),
                        row.get("created_at"),
                    )
                    for row in event_rows
                ),
            )

            imported["operator_observations"] = execute_many(
                cur,
                """
                insert into operator_observations(source, scope, observed_at, ttl_seconds, status, payload_json, payload_hash, created_at)
                values (%s,%s,%s,%s,%s,%s::jsonb,%s,%s)
                """,
                (
                    (
                        row.get("source") or "unknown", row.get("scope") or "", row.get("observed_at"),
                        int(row.get("ttl_seconds") or 0), row.get("status") or "unknown",
                        json_text(row.get("payload_json"), {}), valid_hash(row.get("payload_hash"), row.get("payload_json") or "{}"),
                        row.get("created_at"),
                    )
                    for row in observation_rows
                ),
            )

            target_counts = {
                row["table_name"]: int(row["row_count"])
                for row in cur.execute(
                    """
                    select 'projects' as table_name, count(*) as row_count from projects
                    union all select 'queue_items', count(*) from queue_items
                    union all select 'runs', count(*) from runs
                    union all select 'papers', count(*) from papers
                    union all select 'project_decisions', count(*) from project_decisions
                    union all select 'publication_automation_items', count(*) from publication_automation_items
                    union all select 'control_events', count(*) from control_events
                    union all select 'operator_observations', count(*) from operator_observations
                    """
                ).fetchall()
            }
            dashboard_counts = cur.execute("select * from operator_dashboard_counts").fetchone()
            result = {
                "ok": True,
                "mode": "apply" if apply else "dry-run",
                "sqlite_path": str(sqlite_path),
                "source_counts": source_counts,
                "import_attempted": imported,
                "target_counts_in_transaction": target_counts,
                "operator_dashboard_counts": dict(dashboard_counts or {}),
                "observation_limit": observation_limit,
            }
            if apply:
                pg_conn.commit()
                result["committed"] = True
            else:
                pg_conn.rollback()
                result["committed"] = False
            return result


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sqlite", required=True, type=Path, help="Path to control_plane.sqlite3 source DB")
    parser.add_argument("--database-url", default=os.environ.get("ENOCH_SUPABASE_DATABASE_URL", ""), help="Postgres/Supabase database URL; defaults to ENOCH_SUPABASE_DATABASE_URL")
    parser.add_argument("--apply", action="store_true", help="Commit the backfill transaction. Default is dry-run rollback.")
    parser.add_argument("--reset-target", action="store_true", help="Truncate target domain tables before import. Requires --apply.")
    parser.add_argument("--observation-limit", type=int, default=5000, help="Latest observations to import; 0 skips, -1 imports all. Default: 5000")
    parser.add_argument("--project-root", action="append", type=Path, default=[], help="Base directory used to resolve project_dir/project_id decision artifacts; may be repeated")
    parser.add_argument("--output", type=Path, help="Optional JSON report path")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if not args.database_url.strip():
        print("error: --database-url or ENOCH_SUPABASE_DATABASE_URL is required", file=sys.stderr)
        return 2
    result = import_sqlite_to_postgres(
        sqlite_path=args.sqlite,
        database_url=args.database_url,
        apply=args.apply,
        reset_target=args.reset_target,
        observation_limit=args.observation_limit,
        project_roots=args.project_root,
    )
    text = json.dumps(result, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
