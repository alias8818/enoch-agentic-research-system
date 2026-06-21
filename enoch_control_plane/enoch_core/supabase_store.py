from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from typing import Any

from ..models import utc_now
from ._canonical import canonical_json as _canonical_json
from .store import AppendResult, IdempotencyConflict

ConnectionFactory = Callable[[], Any]


class SupabaseEnochCoreStore:
    """Postgres/Supabase implementation of the Enoch core shadow store.

    The public `/enoch-core/*` API remains proposal-only; this store only moves
    its shadow snapshots/events off local SQLite and into the private `enoch`
    Supabase schema so there is not a second local runtime database after the
    Supabase cutover.
    """

    def __init__(
        self, database_url: str, *, connect: ConnectionFactory | None = None
    ) -> None:
        self.database_url = database_url.strip()
        if not self.database_url:
            raise ValueError(
                "supabase_database_url is required for the Supabase Enoch core store"
            )
        self._connect_factory = connect or self._psycopg_connect
        self._external_connect_factory = connect is not None

    def _psycopg_connect(self) -> Any:
        try:
            import psycopg
            from psycopg.rows import dict_row
        except (
            ImportError
        ) as exc:  # pragma: no cover - dependency is declared in pyproject.
            raise RuntimeError(
                "psycopg is required for the Supabase Enoch core store"
            ) from exc
        return psycopg.connect(self.database_url, row_factory=dict_row)

    @contextmanager
    def _connect(self) -> Iterator[Any]:
        if self._external_connect_factory:
            conn = self._connect_factory()
            try:
                with conn:
                    with conn.cursor() as cur:
                        cur.execute("set search_path to enoch, public")
                    yield conn
            finally:
                close = getattr(conn, "close", None)
                if callable(close):
                    close()
            return

        conn = self._connect_factory()
        try:
            with conn.cursor() as cur:
                cur.execute("set statement_timeout to '45s'")
                cur.execute("set idle_in_transaction_session_timeout to '30s'")
                cur.execute("set search_path to enoch, public")
            yield conn
            conn.commit()
        except Exception:
            rollback = getattr(conn, "rollback", None)
            if callable(rollback):
                rollback()
            raise
        finally:
            close = getattr(conn, "close", None)
            if callable(close):
                close()

    @staticmethod
    def canonical_json(payload: Any) -> str:
        return _canonical_json(payload)

    @classmethod
    def payload_hash(cls, payload: Any) -> str:
        return hashlib.sha256(cls.canonical_json(payload).encode("utf-8")).hexdigest()

    @staticmethod
    def _json_payload(value: Any) -> Any:
        if value is None:
            return {}
        if isinstance(value, str):
            return json.loads(value or "{}")
        return value

    def _query(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, tuple(params))
                rows = cur.fetchall()
        return [dict(row) for row in rows]

    def append_event(
        self,
        *,
        idempotency_key: str,
        event_type: str,
        source: str,
        payload: dict[str, Any],
    ) -> AppendResult:
        payload_json = self.canonical_json(payload)
        payload_hash = self.payload_hash(payload)
        with self._connect() as conn:
            with conn.cursor() as cur:
                existing = cur.execute(
                    "select id, event_type, source, payload_hash from core_events where idempotency_key = %s",
                    (idempotency_key,),
                ).fetchone()
                if existing is not None:
                    if (
                        existing["event_type"] != event_type
                        or existing["source"] != source
                        or existing["payload_hash"] != payload_hash
                    ):
                        raise IdempotencyConflict(
                            f"idempotency key {idempotency_key!r} was reused with different event identity"
                        )
                    return AppendResult(event_id=int(existing["id"]), inserted=False)
                row = cur.execute(
                    """
                    insert into core_events(idempotency_key, event_type, source, payload_json, payload_hash, created_at)
                    values (%s, %s, %s, %s::jsonb, %s, %s)
                    returning id
                    """,
                    (
                        idempotency_key,
                        event_type,
                        source,
                        payload_json,
                        payload_hash,
                        utc_now(),
                    ),
                ).fetchone()
                return AppendResult(event_id=int(row["id"]), inserted=True)

    def save_queue_snapshot(self, payload: dict[str, Any]) -> tuple[AppendResult, int]:
        key = str(payload["idempotency_key"])
        event = self.append_event(
            idempotency_key=key,
            event_type="n8n.queue_snapshot",
            source=str(payload.get("source") or "n8n"),
            payload=payload,
        )
        payload_json = self.canonical_json(payload)
        with self._connect() as conn:
            with conn.cursor() as cur:
                row = cur.execute(
                    """
                    insert into core_snapshots(idempotency_key, snapshot_type, event_id, source, payload_json, created_at)
                    values (%s, %s, %s, %s, %s::jsonb, %s)
                    on conflict (idempotency_key) do update
                    set idempotency_key = excluded.idempotency_key
                    returning id
                    """,
                    (
                        key,
                        "n8n_queue",
                        event.event_id,
                        str(payload.get("source") or "n8n"),
                        payload_json,
                        utc_now(),
                    ),
                ).fetchone()
                return event, int(row["id"])

    def latest_snapshot(
        self, snapshot_type: str = "n8n_queue"
    ) -> dict[str, Any] | None:
        rows = self._query(
            """
            select payload_json from core_snapshots
            where snapshot_type = %s
            order by id desc
            limit 1
            """,
            (snapshot_type,),
        )
        if not rows:
            return None
        return self._json_payload(rows[0]["payload_json"])

    def all_snapshots(self, snapshot_type: str = "n8n_queue") -> list[dict[str, Any]]:
        rows = self._query(
            "select payload_json from core_snapshots where snapshot_type = %s order by id asc",
            (snapshot_type,),
        )
        return [self._json_payload(row["payload_json"]) for row in rows]

    def _live_queue_rows(self) -> list[dict[str, Any]]:
        return self._query(
            """
            select
              q.*,
              p.project_name,
              p.project_dir,
              p.notion_page_url,
              p.notion_page_id,
              p.origin_idea_status,
              coalesce(d.decision_gate_state, '') as decision_gate_state,
              coalesce(d.decision_summary, '') as decision_summary,
              coalesce(d.payload_json #>> '{project_decision,project_decision}', d.payload_json->>'project_decision', '') as project_decision,
              coalesce(d.payload_json #>> '{project_decision,research_outcome}', d.payload_json->>'research_outcome', '') as research_outcome,
              coalesce(d.payload_json #>> '{project_decision,hypothesis_status}', d.payload_json->>'hypothesis_status', '') as hypothesis_status,
              coalesce(d.payload_json #>> '{project_decision,evidence_strength}', d.payload_json->>'evidence_strength', '') as evidence_strength,
              coalesce(d.payload_json #>> '{project_decision,claim_scope}', d.payload_json->>'claim_scope', '') as claim_scope,
              coalesce(d.payload_json #>> '{project_decision,scale_limits}', d.payload_json->>'scale_limits', '') as scale_limits,
              coalesce(d.payload_json #>> '{project_decision,useful_signal_summary}', d.payload_json->>'useful_signal_summary', '') as useful_signal_summary,
              lower(coalesce(d.payload_json #>> '{project_decision,bounded_paper_ready}', d.payload_json->>'bounded_paper_ready', 'false')) in ('true', '1', 'yes') as bounded_paper_ready,
              lower(coalesce(d.payload_json #>> '{project_decision,compute_scale_blocked}', d.payload_json->>'compute_scale_blocked', 'false')) in ('true', '1', 'yes') as compute_scale_blocked,
              coalesce(d.payload_json #>> '{project_decision,recommended_next_action}', d.payload_json->>'recommended_next_action', '') as recommended_next_action,
              coalesce(d.payload_json #>> '{project_decision,stop_reason}', d.payload_json->>'stop_reason', '') as stop_reason,
              coalesce(d.followup_recommended, false) as followup_recommended,
              coalesce(d.followup_type, '') as followup_type,
              coalesce(d.followup_title, '') as followup_title,
              coalesce(d.followup_hypothesis, '') as followup_hypothesis,
              coalesce(d.followup_required_evidence, '[]'::jsonb) as followup_required_evidence,
              coalesce(d.followup_success_threshold, '') as followup_success_threshold,
              coalesce(d.followup_stop_condition, '') as followup_stop_condition,
              coalesce(d.followup_depth, 0) as followup_depth
            from queue_items q
            join projects p using(project_id)
            left join lateral (
              select d.*
              from project_decisions d
              where d.project_id = q.project_id
                and (d.run_id = nullif(q.current_run_id, '') or d.run_id is null)
              order by
                case when d.run_id = nullif(q.current_run_id, '') then 0 else 1 end,
                d.decided_at desc nulls last,
                d.decision_id desc nulls last
              limit 1
            ) d on true
            order by q.dispatch_priority asc, q.updated_at desc
            """
        )

    def _live_paper_rows(self) -> list[dict[str, Any]]:
        return self._query(
            """
            select
              pa.*,
              p.project_name,
              p.project_dir,
              p.notion_page_url,
              p.notion_page_id,
              rv.automation_status as review_status,
              rv.finalization_package_path,
              rv.finalized_at,
              ci.corpus_import_id,
              ci.artifact_slug,
              ci.commit_sha as corpus_commit_sha,
              ci.manifest_path as corpus_manifest_path,
              ci.manifest_hash as corpus_manifest_hash,
              ci.source_record_fingerprint,
              ci.hf_dataset_synced,
              ci.imported_at as corpus_imported_at,
              (ci.paper_id is not null) as corpus_imported
            from papers pa
            left join projects p using(project_id)
            left join publication_automation_items rv using(paper_id)
            left join corpus_imports ci using(paper_id)
            order by pa.updated_at desc
            """
        )

    def _live_queue_projection(self) -> dict[str, Any]:
        return {
            "source": "control_plane_db",
            "queue_rows": self._live_queue_rows(),
            "paper_rows": self._live_paper_rows(),
            "captured_at": utc_now(),
        }

    def rebuild_queue_projection(self) -> dict[str, Any]:
        try:
            return self._live_queue_projection()
        except Exception:
            pass
        return self.latest_snapshot("n8n_queue") or {
            "source": "none",
            "queue_rows": [],
            "paper_rows": [],
            "captured_at": None,
        }
