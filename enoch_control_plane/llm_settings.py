from __future__ import annotations

import json
import os
import re
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any, Literal, Mapping

from pydantic import BaseModel, Field, model_validator

from .config import GateConfig
from .models import utc_now
from .research_provider_defaults import (
    DEFAULT_ALLOWED_RESEARCH_MODELS,
    DEFAULT_RESEARCH_PROVIDER_MODEL,
    default_research_provider_openai_base_url,
)
from .url_safety import validate_http_url


SETTINGS_SCHEMA_VERSION = 1
LLM_SETTINGS_FILENAME = "llm-provider-settings.json"
LLM_PROVIDER_SECRET_DIRNAME = "llm-provider-secrets"

ProviderApiFormat = Literal["openai_compatible", "anthropic_messages"]
WorkflowId = Literal[
    "research_generation",
    "paper_writing",
    "research_review",
    "general_agent",
]

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_.:-]{0,79}$")
_ENV_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,127}$")


def _normalize_id(value: str, *, field_name: str) -> str:
    normalized = str(value or "").strip().lower()
    if not _ID_RE.fullmatch(normalized):
        raise ValueError(
            f"{field_name} must start with a lowercase letter or digit and contain only "
            "lowercase letters, digits, underscore, dash, dot, or colon"
        )
    return normalized


def _normalize_secret_env(value: str) -> str:
    normalized = str(value or "").strip()
    if normalized and not _ENV_RE.fullmatch(normalized):
        raise ValueError("api_key_env must be an uppercase environment variable name")
    return normalized


def _bounded_text(value: str, *, limit: int = 240) -> str:
    return str(value or "").strip()[:limit]


class LLMProviderSettings(BaseModel):
    provider_id: str
    label: str
    api_format: ProviderApiFormat = "openai_compatible"
    base_url: str
    api_key_env: str = ""
    enabled: bool = True
    notes: str = ""

    @model_validator(mode="after")
    def _validate_provider(self) -> "LLMProviderSettings":
        self.provider_id = _normalize_id(self.provider_id, field_name="provider_id")
        self.label = _bounded_text(self.label or self.provider_id, limit=80)
        self.base_url = validate_http_url(
            self.base_url, field_name="provider base_url"
        ).rstrip("/")
        self.api_key_env = _normalize_secret_env(self.api_key_env)
        self.notes = _bounded_text(self.notes)
        return self


class LLMModelSettings(BaseModel):
    model_id: str
    provider_id: str
    label: str = ""
    enabled: bool = True
    weight: int = Field(default=1, ge=0, le=100)
    notes: str = ""

    @model_validator(mode="after")
    def _validate_model(self) -> "LLMModelSettings":
        model_id = str(self.model_id or "").strip()
        if not model_id or any(ord(ch) < 32 or ord(ch) == 127 for ch in model_id):
            raise ValueError(
                "model_id must be non-empty and must not contain control characters"
            )
        if len(model_id) > 180:
            raise ValueError("model_id must be 180 characters or fewer")
        self.model_id = model_id
        self.provider_id = _normalize_id(self.provider_id, field_name="provider_id")
        self.label = _bounded_text(self.label or model_id, limit=100)
        self.notes = _bounded_text(self.notes)
        return self


class LLMWorkflowSettings(BaseModel):
    workflow_id: WorkflowId
    label: str
    provider_ids: list[str] = Field(default_factory=list)
    model_pool: list[str] = Field(default_factory=list)
    default_model: str = ""
    enabled: bool = True
    temperature: float = Field(default=0.6, ge=0.0, le=2.0)
    max_tokens: int = Field(default=8000, ge=512, le=200000)
    notes: str = ""

    @model_validator(mode="after")
    def _validate_workflow(self) -> "LLMWorkflowSettings":
        self.label = _bounded_text(self.label or self.workflow_id, limit=100)
        self.provider_ids = [
            _normalize_id(item, field_name="provider_id")
            for item in self.provider_ids
            if str(item or "").strip()
        ]
        self.model_pool = [
            str(item or "").strip()
            for item in self.model_pool
            if str(item or "").strip()
        ]
        self.default_model = str(self.default_model or "").strip()
        self.notes = _bounded_text(self.notes)
        return self


class LLMSettings(BaseModel):
    schema_version: int = SETTINGS_SCHEMA_VERSION
    providers: list[LLMProviderSettings]
    models: list[LLMModelSettings]
    workflows: list[LLMWorkflowSettings]
    updated_at: str = ""
    updated_by: str = ""

    @model_validator(mode="after")
    def _validate_settings(self) -> "LLMSettings":
        if self.schema_version != SETTINGS_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported llm settings schema_version: {self.schema_version}"
            )
        provider_ids = [provider.provider_id for provider in self.providers]
        if len(provider_ids) != len(set(provider_ids)):
            raise ValueError("provider_id values must be unique")
        provider_id_set = set(provider_ids)

        model_ids = [model.model_id for model in self.models]
        if len(model_ids) != len(set(model_ids)):
            raise ValueError("model_id values must be unique")
        model_id_set = set(model_ids)
        for model in self.models:
            if model.provider_id not in provider_id_set:
                raise ValueError(
                    f"model {model.model_id!r} references unknown provider {model.provider_id!r}"
                )

        workflow_ids = [workflow.workflow_id for workflow in self.workflows]
        if len(workflow_ids) != len(set(workflow_ids)):
            raise ValueError("workflow_id values must be unique")
        for workflow in self.workflows:
            unknown_providers = sorted(set(workflow.provider_ids) - provider_id_set)
            if unknown_providers:
                raise ValueError(
                    f"workflow {workflow.workflow_id!r} references unknown providers: "
                    f"{', '.join(unknown_providers)}"
                )
            unknown_models = sorted(set(workflow.model_pool) - model_id_set)
            if unknown_models:
                raise ValueError(
                    f"workflow {workflow.workflow_id!r} references unknown models: "
                    f"{', '.join(unknown_models)}"
                )
            if (
                workflow.default_model
                and workflow.default_model not in workflow.model_pool
            ):
                raise ValueError(
                    f"workflow {workflow.workflow_id!r} default_model must be in model_pool"
                )
            if workflow.enabled and not workflow.model_pool:
                raise ValueError(
                    f"workflow {workflow.workflow_id!r} requires a model_pool"
                )
        self.updated_at = _bounded_text(self.updated_at)
        self.updated_by = _bounded_text(self.updated_by, limit=120)
        return self


def llm_settings_path(config: GateConfig) -> Path:
    configured = os.environ.get("ENOCH_LLM_SETTINGS_PATH", "").strip()
    if configured:
        return Path(configured).expanduser()
    return config.expanded_state_dir / LLM_SETTINGS_FILENAME


def _secret_file_name(provider_id: str) -> str:
    normalized = _normalize_id(provider_id, field_name="provider_id")
    return re.sub(r"[^a-z0-9_.-]", "_", normalized)


def llm_provider_secret_path(config: GateConfig, provider_id: str) -> Path:
    configured = os.environ.get("ENOCH_LLM_PROVIDER_SECRETS_DIR", "").strip()
    base_dir = (
        Path(configured).expanduser()
        if configured
        else (config.expanded_state_dir / LLM_PROVIDER_SECRET_DIRNAME)
    )
    return base_dir / f"{_secret_file_name(provider_id)}.token"


def default_llm_settings(config: GateConfig | None = None) -> LLMSettings:
    synthetic_base = default_research_provider_openai_base_url()
    paper_model = (
        str(getattr(config, "paper_writer_model", "") or "").strip()
        or DEFAULT_RESEARCH_PROVIDER_MODEL
    )
    model_ids = list(dict.fromkeys([*DEFAULT_ALLOWED_RESEARCH_MODELS, paper_model]))
    return LLMSettings(
        providers=[
            LLMProviderSettings(
                provider_id="synthetic",
                label="Synthetic",
                api_format="openai_compatible",
                base_url=synthetic_base,
                api_key_env="SYNTHETIC_API_KEY",
                enabled=True,
            ),
            LLMProviderSettings(
                provider_id="openrouter",
                label="OpenRouter",
                api_format="openai_compatible",
                base_url="https://openrouter.ai/api/v1",
                api_key_env="OPENROUTER_API_KEY",
                enabled=False,
            ),
            LLMProviderSettings(
                provider_id="openai",
                label="OpenAI",
                api_format="openai_compatible",
                base_url="https://api.openai.com/v1",
                api_key_env="OPENAI_API_KEY",
                enabled=False,
            ),
            LLMProviderSettings(
                provider_id="anthropic",
                label="Anthropic",
                api_format="anthropic_messages",
                base_url="https://api.anthropic.com/v1",
                api_key_env="ANTHROPIC_API_KEY",
                enabled=False,
            ),
        ],
        models=[
            LLMModelSettings(
                model_id=model_id,
                provider_id="synthetic",
                label=model_id.split("/")[-1] if "/" in model_id else model_id,
                enabled=True,
            )
            for model_id in model_ids
        ],
        workflows=[
            LLMWorkflowSettings(
                workflow_id="research_generation",
                label="Research agents",
                provider_ids=["synthetic"],
                model_pool=list(DEFAULT_ALLOWED_RESEARCH_MODELS),
                default_model=DEFAULT_RESEARCH_PROVIDER_MODEL,
                temperature=0.6,
                max_tokens=8000,
            ),
            LLMWorkflowSettings(
                workflow_id="paper_writing",
                label="Paper writing agents",
                provider_ids=["synthetic"],
                model_pool=[paper_model],
                default_model=paper_model,
                temperature=float(
                    getattr(config, "paper_writer_temperature", 0.2) or 0.2
                ),
                max_tokens=int(
                    getattr(config, "paper_writer_max_tokens", 12000) or 12000
                ),
            ),
            LLMWorkflowSettings(
                workflow_id="research_review",
                label="Research review agents",
                provider_ids=["synthetic"],
                model_pool=list(DEFAULT_ALLOWED_RESEARCH_MODELS),
                default_model=DEFAULT_RESEARCH_PROVIDER_MODEL,
                temperature=0.2,
                max_tokens=8000,
            ),
            LLMWorkflowSettings(
                workflow_id="general_agent",
                label="General LLM workflows",
                provider_ids=["synthetic"],
                model_pool=[DEFAULT_RESEARCH_PROVIDER_MODEL],
                default_model=DEFAULT_RESEARCH_PROVIDER_MODEL,
                temperature=0.3,
                max_tokens=8000,
            ),
        ],
        updated_at="",
        updated_by="defaults",
    )


def read_llm_settings(config: GateConfig) -> LLMSettings:
    path = llm_settings_path(config)
    if not path.exists():
        return default_llm_settings(config)
    payload = json.loads(path.read_text(encoding="utf-8"))
    return LLMSettings.model_validate(payload)


def write_llm_settings(
    config: GateConfig, settings: LLMSettings | dict[str, Any], *, updated_by: str
) -> LLMSettings:
    validated = (
        LLMSettings.model_validate(settings.model_dump(mode="json"))
        if isinstance(settings, LLMSettings)
        else LLMSettings.model_validate(settings)
    )
    validated.updated_at = utc_now()
    validated.updated_by = _bounded_text(updated_by or "operator", limit=120)
    path = llm_settings_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        validated.model_dump(mode="json"), indent=2, sort_keys=True
    ).encode("utf-8")
    tmp: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("wb", dir=path.parent, delete=False) as handle:
            handle.write(payload)
            tmp = Path(handle.name)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    finally:
        if tmp is not None:
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError:
                pass
    return validated


def _read_secret_file(path: Path) -> str:
    try:
        if path.is_symlink():
            return ""
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def llm_provider_api_key(config: GateConfig, provider: LLMProviderSettings) -> str:
    env_name = str(provider.api_key_env or "")
    if env_name:
        env_value = os.environ.get(env_name, "").strip()
        if env_value:
            return env_value
    return _read_secret_file(llm_provider_secret_path(config, provider.provider_id))


def write_llm_provider_secrets(
    config: GateConfig,
    secrets: Mapping[str, Any],
    *,
    settings: LLMSettings,
) -> list[str]:
    provider_ids = {provider.provider_id for provider in settings.providers}
    written: list[str] = []
    for raw_provider_id, raw_value in secrets.items():
        provider_id = _normalize_id(
            str(raw_provider_id or ""), field_name="provider_id"
        )
        if provider_id not in provider_ids:
            raise ValueError(
                f"provider secret references unknown provider: {provider_id}"
            )
        secret = str(raw_value or "")
        if not secret.strip():
            continue
        path = llm_provider_secret_path(config, provider_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.parent.is_symlink():
            raise ValueError("LLM provider secret directory must not be a symlink")
        tmp: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", dir=path.parent, delete=False
            ) as handle:
                handle.write(secret.strip())
                handle.write("\n")
                tmp = Path(handle.name)
            os.chmod(tmp, 0o600)
            os.replace(tmp, path)
            os.chmod(path, 0o600)
        finally:
            if tmp is not None:
                try:
                    if tmp.exists():
                        tmp.unlink()
                except OSError:
                    pass
        written.append(provider_id)
    return written


def settings_update_payload(
    settings_payload: Mapping[str, Any],
    provider_secrets: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    """Return a schema payload plus provider secrets recovered from operator input.

    The dashboard response includes derived fields such as api_key_configured.
    Operators also routinely paste provider keys into the env-name field.  The
    persisted schema should never keep either value, but the save path should
    salvage the secret instead of forcing another key-entry round trip.
    """

    payload = deepcopy(dict(settings_payload))
    secrets = dict(provider_secrets)
    recovered: list[str] = []
    providers = payload.get("providers") or []
    if not isinstance(providers, list):
        return payload, secrets, recovered
    for provider in providers:
        if not isinstance(provider, dict):
            continue
        provider.pop("api_key_configured", None)
        provider_id_raw = str(provider.get("provider_id") or "").strip()
        env_value = str(provider.get("api_key_env") or "").strip()
        if not env_value:
            continue
        try:
            _normalize_secret_env(env_value)
        except ValueError:
            provider_id = _normalize_id(provider_id_raw, field_name="provider_id")
            if not str(secrets.get(provider_id) or "").strip():
                secrets[provider_id] = env_value
                recovered.append(provider_id)
            provider["api_key_env"] = ""
    return payload, secrets, recovered


def settings_response(
    settings: LLMSettings, config: GateConfig | None = None
) -> dict[str, Any]:
    payload = settings.model_dump(mode="json")
    providers_by_id = {
        provider.provider_id: provider for provider in settings.providers
    }
    for provider in payload.get("providers", []):
        provider_id = str(provider.get("provider_id") or "")
        env_name = str(provider.get("api_key_env") or "")
        configured = bool(env_name and os.environ.get(env_name))
        if not configured and config is not None and provider_id in providers_by_id:
            configured = bool(
                llm_provider_api_key(config, providers_by_id[provider_id])
            )
        provider["api_key_configured"] = configured
    return payload


def workflow_settings(settings: LLMSettings, workflow_id: str) -> LLMWorkflowSettings:
    for workflow in settings.workflows:
        if workflow.workflow_id == workflow_id:
            return workflow
    raise ValueError(f"unknown LLM workflow: {workflow_id}")


def model_settings(settings: LLMSettings, model_id: str) -> LLMModelSettings:
    for model in settings.models:
        if model.model_id == model_id:
            return model
    raise ValueError(f"unknown LLM model: {model_id}")


def provider_settings(settings: LLMSettings, provider_id: str) -> LLMProviderSettings:
    for provider in settings.providers:
        if provider.provider_id == provider_id:
            return provider
    raise ValueError(f"unknown LLM provider: {provider_id}")


def resolve_workflow_model(
    settings: LLMSettings,
    workflow_id: WorkflowId,
    *,
    requested_model: str = "",
    require_openai_compatible: bool = False,
) -> tuple[LLMWorkflowSettings, LLMModelSettings, LLMProviderSettings]:
    workflow = workflow_settings(settings, workflow_id)
    candidate_model = str(requested_model or "").strip() or workflow.default_model
    if not candidate_model:
        enabled_pool = [
            model_id
            for model_id in workflow.model_pool
            if model_settings(settings, model_id).enabled
        ]
        candidate_model = enabled_pool[0] if enabled_pool else ""
    if candidate_model not in workflow.model_pool:
        raise ValueError(
            f"model {candidate_model!r} is not in workflow {workflow.workflow_id!r} model_pool"
        )
    model = model_settings(settings, candidate_model)
    provider = provider_settings(settings, model.provider_id)
    if not model.enabled:
        raise ValueError(f"model {model.model_id!r} is disabled")
    if not provider.enabled:
        raise ValueError(f"provider {provider.provider_id!r} is disabled")
    if require_openai_compatible and provider.api_format != "openai_compatible":
        raise ValueError(
            f"provider {provider.provider_id!r} is not OpenAI-compatible for workflow {workflow.workflow_id!r}"
        )
    return workflow, model, provider
