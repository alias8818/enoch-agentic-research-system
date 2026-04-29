from __future__ import annotations

import os
from typing import Callable

from fastapi import APIRouter, Header, HTTPException, Query

from ..config import GateConfig
from .logic import (
    draft_candidate_payload,
    eligible_paper_draft_candidates,
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

RequireBearer = Callable[[str | None], None]


def _mode_from_env(default: EnochCoreMode = "shadow") -> EnochCoreMode:
    value = os.environ.get("ENOCH_CORE_MODE", default).strip().lower()
    if value in {"off", "shadow", "compare", "enforce"}:
        return value  # type: ignore[return-value]
    return default


def create_enoch_core_router(config: GateConfig, require_bearer: RequireBearer) -> APIRouter:
    router = APIRouter(prefix="/enoch-core", tags=["enoch-core"])
    db_path = config.expanded_state_dir / "enoch_core.sqlite3"
    store = EnochCoreStore(db_path)

    def authorize(authorization: str | None) -> None:
        require_bearer(authorization)

    def current_mode(override: EnochCoreMode | None = None) -> EnochCoreMode:
        return override or _mode_from_env()

    def latest_snapshot_or_empty() -> dict:
        return store.rebuild_queue_projection()

    @router.get("/health", response_model=HealthResponse)
    def health(authorization: str | None = Header(default=None)) -> HealthResponse:
        authorize(authorization)
        return HealthResponse(mode=current_mode(), db_path=str(db_path))

    @router.post("/snapshots/n8n-queue", response_model=SnapshotIngestResponse)
    def ingest_n8n_queue_snapshot(
        payload: QueueSnapshotRequest,
        authorization: str | None = Header(default=None),
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

    @router.get("/projections/queue", response_model=QueueProjection)
    def get_queue_projection(
        authorization: str | None = Header(default=None),
        mode: EnochCoreMode | None = Query(default=None),
    ) -> QueueProjection:
        authorize(authorization)
        snapshot = latest_snapshot_or_empty()
        projection = queue_projection(snapshot)
        return QueueProjection(mode=current_mode(mode), **projection)

    @router.get("/candidates/paper-draft", response_model=CandidateResponse)
    def paper_draft_candidate(
        authorization: str | None = Header(default=None),
        mode: EnochCoreMode | None = Query(default=None),
    ) -> CandidateResponse:
        authorize(authorization)
        effective_mode = current_mode(mode)
        snapshot = latest_snapshot_or_empty()
        candidates = eligible_paper_draft_candidates(
            list(snapshot.get("queue_rows") or []),
            list(snapshot.get("paper_rows") or []),
        )
        active_count = len(queue_projection(snapshot)["active_rows"])
        if not candidates:
            return CandidateResponse(
                mode=effective_mode,
                action="noop",
                reason="No eligible finalize_positive project without an existing paper draft remains.",
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

    @router.get("/candidates/paper-polish", response_model=CandidateResponse)
    def paper_polish_candidate(
        authorization: str | None = Header(default=None),
        mode: EnochCoreMode | None = Query(default=None),
    ) -> CandidateResponse:
        authorize(authorization)
        effective_mode = current_mode(mode)
        snapshot = latest_snapshot_or_empty()
        candidates = eligible_paper_polish_candidates(list(snapshot.get("paper_rows") or []))
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
