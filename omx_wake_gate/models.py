from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field

from .config import GateThresholdProfile


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SourceEvent(str, Enum):
    SESSION_START = "session-start"
    SESSION_IDLE = "session-idle"
    SESSION_STOP = "session-stop"
    SESSION_END = "session-end"
    ASK_USER_QUESTION = "ask-user-question"


class GateState(str, Enum):
    RUNNING = "running"
    PENDING_IDLE_GATE = "pending_idle_gate"
    WAITING_FOR_PROCESS_EXIT = "waiting_for_process_exit"
    WAITING_FOR_QUIET_WINDOW = "waiting_for_quiet_window"
    QUESTION_PENDING = "question_pending"
    WAKE_READY = "wake_ready"
    FINISHED_PENDING_GATE = "finished_pending_gate"
    FINISHED_READY = "finished_ready"
    CANCELLED = "cancelled"
    ERROR = "error"


class OmxEvent(BaseModel):
    event: SourceEvent
    run_id: str
    session_id: str
    project_id: str | None = None
    project_name: str | None = None
    question: str | None = None
    root_pid: int | None = None
    process_group_id: int | None = None
    timestamp: str = Field(default_factory=utc_now)
    tmux_session: str | None = None
    message: str | None = None


class ProcessSnapshot(BaseModel):
    tracked: bool = False
    root_pid: int | None = None
    process_alive: bool = False
    descendants_alive: bool = False
    gpu_processes_alive: bool = False
    project_cwd_processes_alive: bool = False


class ProcessInfo(BaseModel):
    pid: int
    ppid: int | None = None
    pgid: int | None = None
    elapsed_sec: int | None = None
    create_time: float | None = None
    cmdline: str = ""


class TelemetrySample(BaseModel):
    timestamp: str = Field(default_factory=utc_now)
    cpu_pct: float = 0.0
    gpu_pct: float = 0.0
    # Dedicated framebuffer memory on dGPU systems. On DGX Spark/UMA
    # systems this is a compatibility alias for UMA pressure because
    # nvidia-smi/NVML memory usage is not supported for iGPU platforms.
    vram_used_mib: int = 0
    gpu_compute_pids: list[int] = Field(default_factory=list)
    memory_source: str = "unknown"
    memory_total_mib: int = 0
    memory_available_mib: int = 0
    swap_free_mib: int = 0
    uma_allocatable_mib: int = 0
    uma_pressure_mib: int = 0


class RunRecord(BaseModel):
    run_id: str
    session_id: str
    project_id: str | None = None
    project_name: str | None = None
    project_dir: str | None = None
    workload_class: str | None = None
    workload_profile: GateThresholdProfile | None = None
    gate_state: GateState = GateState.RUNNING
    root_pid: int | None = None
    process_group_id: int | None = None
    baseline_vram_mib: int | None = None
    idle_seen_at: str | None = None
    last_event: SourceEvent | None = None
    last_event_at: str | None = None
    last_idempotency_key: str | None = None
    quiet_samples: list[TelemetrySample] = Field(default_factory=list)
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)


class GateCallback(BaseModel):
    event_type: Literal[
        "session_started",
        "question_pending",
        "wake_ready",
        "session_finished_ready",
        "gate_timeout",
        "gate_error",
    ]
    run_id: str
    session_id: str
    project_id: str | None = None
    project_name: str | None = None
    source_event: str
    gate_state: str
    seen_at: str = Field(default_factory=utc_now)
    idle_seen_at: str | None = None
    delivered_at: str = Field(default_factory=utc_now)
    process_tracking: ProcessSnapshot
    telemetry: dict
    reason: str
    idempotency_key: str


class DispatchRequest(BaseModel):
    run_id: str
    project_id: str | None = None
    project_dir: str
    prompt_file: str
    mode: Literal["exec", "resume"] = "exec"
    session_id: str | None = None
    last: bool = False
    model: str | None = None
    reasoning_effort: Literal["low", "medium", "high", "xhigh"] = "medium"
    sandbox: str = "danger-full-access"
    log_dir: str | None = None


class PrepareProjectRequest(BaseModel):
    run_id: str
    project_id: str
    project_name: str | None = None
    notion_page_url: str | None = None
    project_dir: str
    prompt_file: str
    prompt_text: str
    resume_prompt_file: str | None = None
    resume_prompt_text: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    overwrite: bool = True


class PaperArtifactFile(BaseModel):
    path: str
    content: str


class PaperArtifactRequest(BaseModel):
    run_id: str
    paper_id: str
    files: list[PaperArtifactFile]
    overwrite: bool = False


class PaperArtifactReadRequest(BaseModel):
    paths: list[str]
    max_bytes_per_file: int = 500_000


class SessionHistoryEntry(BaseModel):
    session_id: str
    started_at: str | None = None
    ended_at: str | None = None
    cwd: str | None = None
    pid: int | None = None


class ProjectDecision(BaseModel):
    project_decision: Literal[
        "continue",
        "finalize_negative",
        "finalize_positive",
        "branch_new_project",
        "blocked",
        "needs_review",
    ]
    hypothesis_status: Literal["supported", "unsupported", "mixed", "inconclusive"] = "inconclusive"
    confidence: Literal["low", "medium", "high"] = "medium"
    evidence_strength: Literal["weak", "moderate", "strong"] = "moderate"
    novelty_progress: bool = False
    results_changed: bool = False
    recommended_next_action: str = ""
    stop_reason: str = ""
    branch_project_name: str | None = None
    branch_reason: str | None = None
    decision_source: str = ""
    source_path: str | None = None
    updated_at: str = Field(default_factory=utc_now)


class ProjectStatusResponse(BaseModel):
    project_id: str
    project_dir: str
    available: bool = True
    run_id: str | None = None
    session_id: str | None = None
    project_name: str | None = None
    gate_state: str | None = None
    current_activity: str | None = None
    run_notes_tail: list[str] = Field(default_factory=list)
    recent_files: list[str] = Field(default_factory=list)
    result_files: list[str] = Field(default_factory=list)
    active_processes: list[ProcessInfo] = Field(default_factory=list)
    latest_session: SessionHistoryEntry | None = None
    project_decision: ProjectDecision | None = None
    decision_error: str | None = None
    updated_at: str = Field(default_factory=utc_now)
