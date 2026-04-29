from __future__ import annotations

from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field, model_validator


class WorkloadClass(str, Enum):
    INFERENCE_EVAL = "inference_eval"
    TRAINING = "training"
    CONTROL_PLANE = "control_plane"
    AGENT_HARNESS = "agent_harness"


class GateThresholdProfile(BaseModel):
    idle_sustain_sec: int = Field(ge=30)
    cpu_idle_threshold_pct: float = Field(ge=0.0, le=100.0)
    gpu_idle_avg_threshold_pct: float = Field(ge=0.0, le=100.0)
    gpu_idle_peak_threshold_pct: float = Field(ge=0.0, le=100.0)
    vram_delta_threshold_mib: int = Field(ge=0)


class GateConfig(BaseModel):
    listen_host: str = "0.0.0.0"
    listen_port: int = 8787
    state_dir: str = "~/.local/state/omx-wake-gate"
    project_root: str = "~/enoch/projects"
    dispatch_script_path: str = "~/enoch/bin/enoch_omx_dispatch.sh"
    dispatch_timeout_sec: int = Field(default=30, ge=5)
    omx_inbound_bearer_token: str
    sample_interval_sec: int = Field(default=5, ge=1)
    default_workload_class: WorkloadClass = WorkloadClass.INFERENCE_EVAL
    idle_sustain_sec: int = Field(default=180, ge=30)
    cpu_idle_threshold_pct: float = Field(default=35.0, ge=0.0, le=100.0)
    gpu_idle_avg_threshold_pct: float = Field(default=10.0, ge=0.0, le=100.0)
    gpu_idle_peak_threshold_pct: float = Field(default=20.0, ge=0.0, le=100.0)
    vram_delta_threshold_mib: int = Field(default=1024, ge=0)
    workload_profiles: dict[str, GateThresholdProfile] = Field(default_factory=dict)
    max_wait_after_idle_sec: int = Field(default=43200, ge=60)
    stale_project_process_reaper_enabled: bool = True
    stale_project_process_grace_sec: int = Field(default=900, ge=0)
    stale_project_process_term_grace_sec: float = Field(default=5.0, ge=0.0, le=30.0)
    stale_project_process_command_markers: list[str] = Field(
        default_factory=lambda: [
            "timeout ",
            "llama-cli",
            "llama-server",
            "vllm",
            "sglang",
        ]
    )
    completion_callback_url: str = ""
    completion_callback_token: str = ""
    completion_callback_timeout_sec: int = Field(default=120, ge=5)
    # Deprecated compatibility aliases for early private prototypes. Prefer
    # completion_callback_* in public configs.
    n8n_callback_url: str = ""
    n8n_bearer_token: str = ""
    n8n_callback_timeout_sec: int = Field(default=120, ge=5)
    log_events: bool = True
    live_dispatch_enabled: bool = False
    worker_wake_gate_url: str = "http://worker.example:8787"
    worker_wake_gate_bearer_token: str = ""
    pushover_alerts_enabled: bool = False
    pushover_app_token: str = ""
    pushover_user_key: str = ""
    pushover_api_url: str = "https://api.pushover.net/1/messages.json"
    queue_alert_cooldown_sec: int = Field(default=1800, ge=60)
    queue_alert_hang_after_sec: int = Field(default=3600, ge=300)
    paper_writer_provider: str = "deterministic"
    paper_writer_base_url: str = "https://api.synthetic.new/openai/v1"
    paper_writer_model: str = "hf:zai-org/GLM-5.1"
    paper_writer_api_key: str = ""
    paper_writer_timeout_sec: int = Field(default=180, ge=10)
    paper_writer_temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    paper_writer_max_tokens: int = Field(default=12000, ge=512)
    paper_writer_fallback_enabled: bool = True
    paper_evidence_sync_enabled: bool = False
    paper_evidence_sync_ssh_host: str = "worker-user@worker.example"
    paper_evidence_sync_remote_root: str = "~/enoch/projects"
    paper_evidence_sync_timeout_sec: int = Field(default=90, ge=5)


    @model_validator(mode="after")
    def _normalize_callback_config(self) -> "GateConfig":
        if not self.completion_callback_url and self.n8n_callback_url:
            self.completion_callback_url = self.n8n_callback_url
        if not self.completion_callback_token and self.n8n_bearer_token:
            self.completion_callback_token = self.n8n_bearer_token
        if self.completion_callback_timeout_sec == 120 and self.n8n_callback_timeout_sec != 120:
            self.completion_callback_timeout_sec = self.n8n_callback_timeout_sec
        if not self.completion_callback_url:
            raise ValueError("completion_callback_url is required")
        if not self.completion_callback_token:
            raise ValueError("completion_callback_token is required")
        return self

    @property
    def expanded_state_dir(self) -> Path:
        return Path(self.state_dir).expanduser()

    @property
    def expanded_project_root(self) -> Path:
        return Path(self.project_root).expanduser()

    def _legacy_training_profile(self) -> GateThresholdProfile:
        return GateThresholdProfile(
            idle_sustain_sec=self.idle_sustain_sec,
            cpu_idle_threshold_pct=self.cpu_idle_threshold_pct,
            gpu_idle_avg_threshold_pct=self.gpu_idle_avg_threshold_pct,
            gpu_idle_peak_threshold_pct=self.gpu_idle_peak_threshold_pct,
            vram_delta_threshold_mib=self.vram_delta_threshold_mib,
        )

    def workload_profile_map(self) -> dict[str, GateThresholdProfile]:
        training = self._legacy_training_profile()
        inference_eval = GateThresholdProfile(
            idle_sustain_sec=max(300, self.idle_sustain_sec),
            cpu_idle_threshold_pct=min(20.0, self.cpu_idle_threshold_pct),
            gpu_idle_avg_threshold_pct=self.gpu_idle_avg_threshold_pct,
            gpu_idle_peak_threshold_pct=self.gpu_idle_peak_threshold_pct,
            vram_delta_threshold_mib=self.vram_delta_threshold_mib,
        )
        profiles = {
            WorkloadClass.INFERENCE_EVAL.value: inference_eval,
            WorkloadClass.TRAINING.value: training,
            WorkloadClass.CONTROL_PLANE.value: inference_eval.model_copy(deep=True),
            WorkloadClass.AGENT_HARNESS.value: inference_eval.model_copy(deep=True),
        }
        valid_names = {item.value for item in WorkloadClass}
        for name, profile in self.workload_profiles.items():
            if name not in valid_names:
                raise ValueError(
                    f"unsupported workload_class profile '{name}'; expected one of: "
                    f"{', '.join(sorted(valid_names))}"
                )
            profiles[name] = profile.model_copy(deep=True)
        return profiles

    def normalize_workload_class(self, raw: str | None) -> str:
        candidate = (raw or "").strip().lower().replace("-", "_")
        if not candidate:
            return self.default_workload_class.value
        valid_names = {item.value for item in WorkloadClass}
        if candidate not in valid_names:
            raise ValueError(
                f"unsupported workload_class '{raw}'; expected one of: "
                f"{', '.join(sorted(valid_names))}"
            )
        return candidate

    def resolve_workload_profile(
        self,
        raw: str | None,
    ) -> tuple[str, GateThresholdProfile]:
        workload_class = self.normalize_workload_class(raw)
        return workload_class, self.workload_profile_map()[workload_class]
