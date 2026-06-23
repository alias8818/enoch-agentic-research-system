from __future__ import annotations

import os
from typing import Annotated, Callable, cast

from fastapi import APIRouter, Header, HTTPException, Query

from ..config import GateConfig
from ..control_plane.supabase_store import resolve_supabase_database_url
from .logic import (
    draft_candidate_payload,
    eligible_projected_paper_draft_candidates,
    eligible_paper_polish_candidates,
    polish_candidate_payload,
    queue_projection,
)
from .models import (
    CandidateResponse,
    EnochCoreMode,
    HealthResponse,
    QueueProjection,
    QueueSnapshotRequest,
    SnapshotIngestResponse,
)
from .store import EnochCoreStore, IdempotencyConflict
from .supabase_store import SupabaseEnochCoreStore

RequireBearer = Callable[[str | None], None]
_VALID_ENOCH_CORE_MODES: frozenset[str] = frozenset(
    {"off", "shadow", "compare", "enforce"}
)

_HTTP_409_IDEMPOTENCY_CONFLICT: dict[int, dict[str, str]] = {
    409: {"description": "Idempotency key reused with a different payload"},
}


def _mode_from_env(default: EnochCoreMode = "shadow") -> EnochCoreMode:
    value = os.environ.get("ENOCH_CORE_MODE", default).strip().lower()
    if value in _VALID_ENOCH_CORE_MODES:
        return cast(EnochCoreMode, value)
    return default


def _mode_from_override(override: EnochCoreMode | str | None) -> EnochCoreMode | None:
    if override is None:
        return None
    value = str(override).strip().lower()
    if value not in _VALID_ENOCH_CORE_MODES:
        raise HTTPException(status_code=400, detail=f"invalid enoch core mode: {value}")
    return cast(EnochCoreMode, value)


def create_enoch_core_router(
    config: GateConfig, require_bearer: RequireBearer
) -> APIRouter:
    router = APIRouter(prefix="/enoch-core", tags=["enoch-core"])
    local_db_path = config.expanded_state_dir / "enoch_core.sqlite3"
    backend = config.enoch_core_store_backend
    if backend == "control_plane":
        backend = (
            "supabase" if config.control_plane_store_backend == "supabase" else "sqlite"
        )
    if backend == "supabase":
        store = SupabaseEnochCoreStore(
            resolve_supabase_database_url(config.supabase_database_url)
        )
        store_path = "supabase"
    else:
        store = EnochCoreStore(local_db_path)
        store_path = str(local_db_path)

    def authorize(authorization: str | None) -> None:
        require_bearer(authorization)

    def current_mode(override: EnochCoreMode | str | None = None) -> EnochCoreMode:
        return _mode_from_override(override) or _mode_from_env()

    def latest_snapshot_or_empty() -> dict:
        return store.rebuild_queue_projection()

    @router.get("/health")
    def health(
        authorization: Annotated[str | None, Header()] = None,
    ) -> HealthResponse:
        authorize(authorization)
        return HealthResponse(
            mode=current_mode(), db_path=store_path, store_backend=backend
        )

    @router.post(
        "/snapshots/n8n-queue",
        responses=_HTTP_409_IDEMPOTENCY_CONFLICT,
    )
    def ingest_n8n_queue_snapshot(
        payload: QueueSnapshotRequest,
        authorization: Annotated[str | None, Header()] = None,
    ) -> SnapshotIngestResponse:
        authorize(authorization)
        mode = current_mode(payload.mode)
        normalized = payload.model_dump(mode="json")
        normalized["mode"] = mode
        try:
            event, snapshot_id = store.save_queue_snapshot(normalized)
        except IdempotencyConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return SnapshotIngestResponse(
            mode=mode,
            inserted=event.inserted,
            event_id=event.event_id,
            snapshot_id=snapshot_id,
            queue_rows=len(payload.queue_rows),
            paper_rows=len(payload.paper_rows),
            would_apply=False,
        )

    @router.get("/projections/queue")
    def get_queue_projection(
        authorization: Annotated[str | None, Header()] = None,
        mode: Annotated[EnochCoreMode | None, Query()] = None,
    ) -> QueueProjection:
        authorize(authorization)
        snapshot = latest_snapshot_or_empty()
        projection = queue_projection(snapshot)
        return QueueProjection(mode=current_mode(mode), **projection)

    @router.get("/candidates/paper-draft")
    def paper_draft_candidate(
        authorization: Annotated[str | None, Header()] = None,
        mode: Annotated[EnochCoreMode | None, Query()] = None,
    ) -> CandidateResponse:
        authorize(authorization)
        effective_mode = current_mode(mode)
        snapshot = latest_snapshot_or_empty()
        candidates = eligible_projected_paper_draft_candidates(
            list(snapshot.get("queue_rows") or []),
            list(snapshot.get("paper_rows") or []),
        )
        active_count = len(queue_projection(snapshot)["active_rows"])
        if not candidates:
            return CandidateResponse(
                mode=effective_mode,
                action="noop",
                reason="No eligible completed paper-draft candidate without an existing paper draft remains.",
                candidate=None,
                candidate_count=0,
                active_count=active_count,
                would_apply=False,
                snapshot_captured_at=snapshot.get("captured_at"),
            )
        return CandidateResponse(
            mode=effective_mode,
            action="draft",
            reason="Candidate proposal only; n8n remains the side-effect executor.",
            candidate=draft_candidate_payload(candidates[0]),
            candidate_count=len(candidates),
            active_count=active_count,
            would_apply=False,
            snapshot_captured_at=snapshot.get("captured_at"),
        )

    @router.get("/candidates/paper-polish")
    def paper_polish_candidate(
        authorization: Annotated[str | None, Header()] = None,
        mode: Annotated[EnochCoreMode | None, Query()] = None,
    ) -> CandidateResponse:
        authorize(authorization)
        effective_mode = current_mode(mode)
        snapshot = latest_snapshot_or_empty()
        candidates = eligible_paper_polish_candidates(
            list(snapshot.get("paper_rows") or [])
        )
        active_count = len(queue_projection(snapshot)["active_rows"])
        if not candidates:
            return CandidateResponse(
                mode=effective_mode,
                action="noop",
                reason="No eligible draft_review paper without publication_v1 remains.",
                candidate=None,
                candidate_count=0,
                active_count=active_count,
                would_apply=False,
                snapshot_captured_at=snapshot.get("captured_at"),
            )
        return CandidateResponse(
            mode=effective_mode,
            action="polish",
            reason="Candidate proposal only; n8n remains the side-effect executor.",
            candidate=polish_candidate_payload(candidates[0]),
            candidate_count=len(candidates),
            active_count=active_count,
            would_apply=False,
            snapshot_captured_at=snapshot.get("captured_at"),
        )

    return router
