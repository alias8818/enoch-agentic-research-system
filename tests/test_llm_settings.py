from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from enoch_control_plane.config import GateConfig
from enoch_control_plane.control_plane.router import (
    _resolve_research_cycle_params,
    _resolve_research_provider_model,
    create_control_plane_router,
)
from enoch_control_plane.llm_settings import (
    LLMModelSettings,
    LLMSettings,
    default_llm_settings,
    read_llm_settings,
    write_llm_settings,
)


TOKEN = "test-token"


def _config(tmp: str) -> GateConfig:
    root = Path(tmp) / "projects"
    root.mkdir(parents=True, exist_ok=True)
    return GateConfig(
        state_dir=str(Path(tmp) / "state"),
        project_root=str(root),
        dispatch_script_path=str(Path(tmp) / "dispatch.sh"),
        control_api_bearer_token=TOKEN,
        completion_callback_url="http://example.invalid/callback",
        completion_callback_token="unused",
    )


def _client(config: GateConfig) -> TestClient:
    app = FastAPI()
    app.include_router(create_control_plane_router(config, lambda token: None))
    return TestClient(app)


def test_default_llm_settings_include_provider_and_workflow_pools() -> None:
    settings = default_llm_settings()

    assert {provider.provider_id for provider in settings.providers} >= {
        "synthetic",
        "openrouter",
        "openai",
        "anthropic",
    }
    workflows = {workflow.workflow_id: workflow for workflow in settings.workflows}
    assert workflows["research_generation"].model_pool
    assert workflows["paper_writing"].model_pool
    assert workflows["research_review"].model_pool


def test_llm_settings_reject_unknown_workflow_model() -> None:
    settings = default_llm_settings().model_dump(mode="json")
    settings["workflows"][0]["model_pool"].append("missing-model")

    with pytest.raises(ValueError, match="unknown models"):
        LLMSettings.model_validate(settings)


def test_llm_settings_api_does_not_expose_secret_values(monkeypatch: pytest.MonkeyPatch) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        monkeypatch.setenv("SYNTHETIC_API_KEY", "secret-value-that-must-not-return")
        client = _client(_config(tmp))

        response = client.get(
            "/control/api/settings/llm",
            headers={"Authorization": f"Bearer {TOKEN}"},
        )

        assert response.status_code == 200
        body = response.json()
        providers = body["settings"]["providers"]
        synthetic = next(
            provider for provider in providers if provider["provider_id"] == "synthetic"
        )
        assert synthetic["api_key_configured"] is True
        assert "secret-value-that-must-not-return" not in response.text


def test_llm_settings_api_persists_valid_updates() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        config = _config(tmp)
        client = _client(config)
        settings = default_llm_settings(config)
        openrouter = next(
            provider for provider in settings.providers if provider.provider_id == "openrouter"
        )
        openrouter.enabled = True
        settings.models.append(
            LLMModelSettings(
                model_id="openrouter/auto",
                provider_id="openrouter",
                label="OpenRouter Auto",
                enabled=True,
                weight=1,
            )
        )
        research = next(
            workflow
            for workflow in settings.workflows
            if workflow.workflow_id == "research_generation"
        )
        research.provider_ids = ["openrouter"]
        research.model_pool = ["openrouter/auto"]
        research.default_model = "openrouter/auto"

        response = client.post(
            "/control/api/settings/llm",
            headers={"Authorization": f"Bearer {TOKEN}"},
            json={"requested_by": "test", "settings": settings.model_dump(mode="json")},
        )

        assert response.status_code == 200
        assert response.json()["settings"]["workflows"][0]["default_model"] == "openrouter/auto"
        persisted = read_llm_settings(config)
        assert persisted.workflows[0].default_model == "openrouter/auto"


def test_research_provider_selection_uses_persisted_settings() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        config = _config(tmp)
        settings = default_llm_settings(config)
        openrouter = next(
            provider for provider in settings.providers if provider.provider_id == "openrouter"
        )
        openrouter.enabled = True
        settings.models.append(
            LLMModelSettings(
                model_id="openrouter/auto",
                provider_id="openrouter",
                label="OpenRouter Auto",
                enabled=True,
                weight=1,
            )
        )
        workflow = next(
            item for item in settings.workflows if item.workflow_id == "research_generation"
        )
        workflow.provider_ids = ["openrouter"]
        workflow.model_pool = ["openrouter/auto"]
        workflow.default_model = "openrouter/auto"
        write_llm_settings(config, settings, updated_by="test")
        create_control_plane_router(config, lambda token: None)

        model, allowed_models = _resolve_research_provider_model({})
        params = _resolve_research_cycle_params({})

        assert model == "openrouter/auto"
        assert allowed_models == ["openrouter/auto"]
        assert params.provider_openai_base_url == "https://openrouter.ai/api/v1"
