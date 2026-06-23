from __future__ import annotations

import re
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field, ValidationInfo, field_validator, model_validator

from enoch_control_plane.url_safety import secure_default_service_url, validate_http_url


_SSH_TARGET_RE = re.compile(
    r"^(?:[A-Za-z0-9_][A-Za-z0-9_.-]*@)?[A-Za-z0-9][A-Za-z0-9_.-]*$"
)


def _validate_config_http_url(
    value: str, *, field_name: str, allow_private: bool = True
) -> str:
    return validate_http_url(value, field_name=field_name, allow_private=allow_private)


class WorkloadClass(str, Enum):
    UNKNOWN = "unknown"
    CPU_ONLY = "cpu_only"
    GPU_REQUIRED = "gpu_required"
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


class WorkerTargetConfig(BaseModel):
    wake_gate_url: str
    bearer_token: str = ""
    role: str = ""
    min_memory_available_mib: int | None = Field(default=None, ge=0)

    @field_validator("wake_gate_url")
    @classmethod
    def _validate_wake_gate_url(cls, value: str) -> str:
        return _validate_config_http_url(
            value, field_name="worker target wake_gate_url"
        )


class GateConfig(BaseModel):
    listen_host: str = "0.0.0.0"
    listen_port: int = 8787
    state_dir: str = "~/.local/state/enoch-worker-gate"
    project_root: str = "~/enoch/projects"
    dispatch_script_path: str = "~/enoch/bin/enoch_codex_dispatch.sh"
    dispatch_timeout_sec: int = Field(default=30, ge=5)
    control_api_bearer_token: str = ""
    # Deprecated compatibility alias. Prefer control_api_bearer_token in new configs.
    omx_inbound_bearer_token: str = ""
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
    completion_callback_hmac_secret: str = ""
    completion_callback_timeout_sec: int = Field(default=120, ge=5)
    # Deprecated compatibility aliases for early private prototypes. Prefer
    # completion_callback_* in public configs.
    n8n_callback_url: str = ""
    n8n_bearer_token: str = ""
    n8n_callback_timeout_sec: int = Field(default=120, ge=5)
    log_events: bool = True
    live_dispatch_enabled: bool = False
    worker_wake_gate_url: str = secure_default_service_url("worker.example", 8787)
    worker_wake_gate_bearer_token: str = ""
    worker_targets: dict[str, WorkerTargetConfig] = Field(default_factory=dict)
    workload_machine_targets: dict[str, str] = Field(default_factory=dict)
    pushover_alerts_enabled: bool = False
    pushover_app_token: str = ""
    pushover_user_key: str = ""
    pushover_api_url: str = "https://api.pushover.net/1/messages.json"
    hermes_alert_webhook_enabled: bool = False
    hermes_alert_webhook_url: str = ""
    hermes_alert_webhook_secret: str = ""
    hermes_alert_webhook_timeout_sec: int = Field(default=8, ge=1, le=30)
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
    route_observability_enabled: bool = False
    route_observability_log_path: str = ""
    route_observability_slow_ms: int = Field(default=1000, ge=0)
    route_observability_memory_warn_rss_mib: int = Field(default=0, ge=0)
    operational_trace_enabled: bool = False
    operational_trace_log_path: str = ""
    operational_trace_max_payload_bytes: int = Field(default=16_384, ge=1024)
    control_plane_store_backend: str = "sqlite"
    enoch_core_store_backend: str = "control_plane"
    supabase_database_url: str = ""
    legacy_notion_api_enabled: bool = False

    @field_validator("paper_evidence_sync_ssh_host")
    @classmethod
    def _validate_paper_evidence_sync_ssh_host(cls, value: str) -> str:
        if not _SSH_TARGET_RE.fullmatch(value):
            raise ValueError(
                "paper_evidence_sync_ssh_host must be a safe ssh target "
                "like user@host or host"
            )
        return value

    @field_validator(
        "completion_callback_url",
        "n8n_callback_url",
        "worker_wake_gate_url",
        "pushover_api_url",
        "hermes_alert_webhook_url",
        "paper_writer_base_url",
    )
    @classmethod
    def _validate_outbound_http_url(cls, value: str, info: ValidationInfo) -> str:
        if not value:
            return value
        return _validate_config_http_url(value, field_name=str(info.field_name))

    @field_validator("paper_writer_base_url")
    @classmethod
    def _validate_external_provider_url(cls, value: str) -> str:
        if not value:
            return value
        return _validate_config_http_url(
            value, field_name="paper_writer_base_url", allow_private=False
        )

    @model_validator(mode="after")
    def _normalize_callback_config(self) -> "GateConfig":
        if not self.completion_callback_url and self.n8n_callback_url:
            self.completion_callback_url = self.n8n_callback_url
        if not self.completion_callback_token and self.n8n_bearer_token:
            self.completion_callback_token = self.n8n_bearer_token
        if (
            self.completion_callback_timeout_sec == 120
            and self.n8n_callback_timeout_sec != 120
        ):
            self.completion_callback_timeout_sec = self.n8n_callback_timeout_sec
        if not self.control_api_bearer_token and self.omx_inbound_bearer_token:
            self.control_api_bearer_token = self.omx_inbound_bearer_token
        if not self.omx_inbound_bearer_token and self.control_api_bearer_token:
            self.omx_inbound_bearer_token = self.control_api_bearer_token
        if self.control_plane_store_backend not in {
            "sqlite",
            "supabase_readonly",
            "supabase",
        }:
            raise ValueError(
                "control_plane_store_backend must be sqlite, supabase_readonly, or supabase"
            )
        if self.enoch_core_store_backend not in {"control_plane", "sqlite", "supabase"}:
            raise ValueError(
                "enoch_core_store_backend must be control_plane, sqlite, or supabase"
            )
        if not self.completion_callback_url:
            raise ValueError("completion_callback_url is required")
        if not self.completion_callback_token:
            raise ValueError("completion_callback_token is required")
        if not self.control_api_bearer_token:
            raise ValueError("control_api_bearer_token is required")
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
            WorkloadClass.UNKNOWN.value: inference_eval.model_copy(deep=True),
            WorkloadClass.CPU_ONLY.value: inference_eval.model_copy(deep=True),
            WorkloadClass.GPU_REQUIRED.value: training.model_copy(deep=True),
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

    def resolved_worker_target(self, machine_target: str | None) -> WorkerTargetConfig:
        target = (machine_target or "").strip()
        if target and target in self.worker_targets:
            raw_worker = self.worker_targets[target]
            worker = (
                raw_worker
                if isinstance(raw_worker, WorkerTargetConfig)
                else WorkerTargetConfig.model_validate(raw_worker)
            )
            return WorkerTargetConfig(
                wake_gate_url=worker.wake_gate_url,
                bearer_token=worker.bearer_token or self.worker_wake_gate_bearer_token,
                role=worker.role,
                min_memory_available_mib=worker.min_memory_available_mib,
            )
        return WorkerTargetConfig(
            wake_gate_url=self.worker_wake_gate_url,
            bearer_token=self.worker_wake_gate_bearer_token,
            role="default",
        )

    def workload_class_for_machine_target(
        self, machine_target: str | None, raw: str | None = None
    ) -> str:
        if (raw or "").strip():
            return self.normalize_workload_class(raw)
        target = (machine_target or "").strip()
        for (
            mapped_workload_class,
            mapped_target,
        ) in self.workload_machine_targets.items():
            if str(mapped_target).strip() == target:
                return self.normalize_workload_class(str(mapped_workload_class))
        return self.default_workload_class.value
