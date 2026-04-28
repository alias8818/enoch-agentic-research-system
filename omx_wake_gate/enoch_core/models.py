from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from ..models import utc_now

EnochCoreMode = Literal["off", "shadow", "compare", "enforce"]


class QueueSnapshotRequest(BaseModel):
    """Snapshot of n8n queue and paper ledger rows for shadow projection.

    The idempotency key is required so n8n can safely retry snapshot posts.
    Same key + same payload is accepted idempotently; same key + different
    payload is rejected by the store.
    """

    idempotency_key: str = Field(min_length=1)
    source: str = "n8n"
    mode: EnochCoreMode = "shadow"
    queue_rows: list[dict[str, Any]] = Field(default_factory=list)
    paper_rows: list[dict[str, Any]] = Field(default_factory=list)
    captured_at: str = Field(default_factory=utc_now)


class SnapshotIngestResponse(BaseModel):
    ok: bool = True
    mode: EnochCoreMode
    inserted: bool
    event_id: int
    snapshot_id: int
    queue_rows: int
    paper_rows: int
    would_apply: bool = False
    message: str = "snapshot recorded locally only; no external side effects performed"


class QueueProjection(BaseModel):
    ok: bool = True
    mode: EnochCoreMode = "shadow"
    projection_version: str = "enoch-core.queue.v1"
    source: str = ""
    captured_at: str | None = None
    total_queue_rows: int = 0
    total_paper_rows: int = 0
    status_counts: dict[str, int] = Field(default_factory=dict)
    run_state_counts: dict[str, int] = Field(default_factory=dict)
    active_rows: list[dict[str, Any]] = Field(default_factory=list)
    draft_candidate_count: int = 0
    polish_candidate_count: int = 0
    warnings: list[str] = Field(default_factory=list)


class CandidateResponse(BaseModel):
    ok: bool = True
    mode: EnochCoreMode = "shadow"
    action: Literal["draft", "polish", "noop"]
    reason: str
    candidate: dict[str, Any] | None = None
    candidate_count: int = 0
    active_count: int = 0
    would_apply: bool = False
    snapshot_captured_at: str | None = None
    projection_version: str = "enoch-core.candidate.v1"


class HealthResponse(BaseModel):
    ok: bool = True
    service: str = "enoch_core"
    mode: EnochCoreMode = "shadow"
    db_path: str
    timestamp: str = Field(default_factory=utc_now)
