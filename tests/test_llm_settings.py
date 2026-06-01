from __future__ import annotations

import tempfile
import urllib.error
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from enoch_control_plane.config import GateConfig
from enoch_control_plane.control_plane.router import (
    _provider_api_key_for_base_url,
    _resolve_research_cycle_params,
    _resolve_research_provider_model,
    create_control_plane_router,
)
from enoch_control_plane.llm_settings import (
    LLMModelSettings,
    LLMSettings,
    default_llm_settings,
    llm_provider_api_key,
    llm_provider_secret_path,
    read_llm_settings,
    settings_response,
    write_llm_provider_secrets,
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


def _client(
    config: GateConfig,
    monkeypatch: pytest.MonkeyPatch | None = None,
    store=None,
) -> TestClient:
    app = FastAPI()
    if monkeypatch is not None and store is not None:
        monkeypatch.setattr(
            "enoch_control_plane.control_plane.router._control_plane_store_for_config",
            lambda _config: store,
        )
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


def test_llm_settings_api_does_not_expose_secret_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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


def test_llm_settings_api_persists_one_time_provider_secret() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        config = _config(tmp)
        client = _client(config)
        settings = default_llm_settings(config)
        openrouter = next(
            provider
            for provider in settings.providers
            if provider.provider_id == "openrouter"
        )
        openrouter.enabled = True

        response = client.post(
            "/control/api/settings/llm",
            headers={"Authorization": f"Bearer {TOKEN}"},
            json={
                "requested_by": "test",
                "settings": settings.model_dump(mode="json"),
                "provider_secrets": {"openrouter": "or-secret-value"},
            },
        )

        assert response.status_code == 200
        assert "or-secret-value" not in response.text
        providers = response.json()["settings"]["providers"]
        openrouter_response = next(
            provider
            for provider in providers
            if provider["provider_id"] == "openrouter"
        )
        assert openrouter_response["api_key_configured"] is True
        secret_path = llm_provider_secret_path(config, "openrouter")
        assert secret_path.read_text(encoding="utf-8") == "or-secret-value\n"
        assert secret_path.stat().st_mode & 0o777 == 0o600
        assert llm_provider_api_key(config, openrouter) == "or-secret-value"


def test_llm_settings_api_recovers_secret_pasted_into_env_field() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        config = _config(tmp)
        client = _client(config)
        settings = default_llm_settings(config).model_dump(mode="json")
        openrouter = next(
            provider
            for provider in settings["providers"]
            if provider["provider_id"] == "openrouter"
        )
        openrouter["enabled"] = True
        openrouter["api_key_env"] = "sk-or-operator-pasted-key"
        openrouter["api_key_configured"] = False

        response = client.post(
            "/control/api/settings/llm",
            headers={"Authorization": f"Bearer {TOKEN}"},
            json={"requested_by": "test", "settings": settings},
        )

        assert response.status_code == 200
        persisted = read_llm_settings(config)
        openrouter_saved = next(
            provider
            for provider in persisted.providers
            if provider.provider_id == "openrouter"
        )
        assert openrouter_saved.api_key_env == ""
        assert (
            llm_provider_secret_path(config, "openrouter").read_text(encoding="utf-8")
            == "sk-or-operator-pasted-key\n"
        )
        assert "sk-or-operator-pasted-key" not in response.text


def test_llm_settings_secret_status_uses_secret_file_when_env_missing() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        config = _config(tmp)
        settings = default_llm_settings(config)
        synthetic = next(
            provider
            for provider in settings.providers
            if provider.provider_id == "synthetic"
        )
        write_llm_provider_secrets(
            config, {"synthetic": "synthetic-secret"}, settings=settings
        )

        payload = settings_response(settings, config)

        provider = next(
            item for item in payload["providers"] if item["provider_id"] == "synthetic"
        )
        assert provider["api_key_configured"] is True
        assert "synthetic-secret" not in str(payload)


def test_research_provider_api_key_resolves_dashboard_secret_file() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        config = _config(tmp)
        settings = default_llm_settings(config)
        openrouter = next(
            provider
            for provider in settings.providers
            if provider.provider_id == "openrouter"
        )
        openrouter.enabled = True
        write_llm_settings(config, settings, updated_by="test")
        write_llm_provider_secrets(
            config, {"openrouter": "or-secret-value"}, settings=settings
        )
        create_control_plane_router(config, lambda token: None)

        assert (
            _provider_api_key_for_base_url("https://openrouter.ai/api/v1")
            == "or-secret-value"
        )


def test_llm_settings_api_persists_valid_updates() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        config = _config(tmp)
        client = _client(config)
        settings = default_llm_settings(config)
        openrouter = next(
            provider
            for provider in settings.providers
            if provider.provider_id == "openrouter"
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
        assert (
            response.json()["settings"]["workflows"][0]["default_model"]
            == "openrouter/auto"
        )
        persisted = read_llm_settings(config)
        assert persisted.workflows[0].default_model == "openrouter/auto"


def test_llm_settings_model_test_calls_exact_openai_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self, *_args: object) -> bytes:
            return b'{"choices":[{"message":{"content":"ok"}}]}'

    with tempfile.TemporaryDirectory() as tmp:
        config = _config(tmp)
        client = _client(config)
        settings = default_llm_settings(config)
        openrouter = next(
            provider
            for provider in settings.providers
            if provider.provider_id == "openrouter"
        )
        openrouter.enabled = True
        settings.models.append(
            LLMModelSettings(
                model_id="moonshotai/kimi-k2.6",
                provider_id="openrouter",
                label="Kimi K2.6",
                enabled=True,
                weight=90,
            )
        )
        write_llm_settings(config, settings, updated_by="test")
        write_llm_provider_secrets(
            config, {"openrouter": "or-secret-value"}, settings=settings
        )
        seen: dict[str, object] = {}

        def fake_urlopen(req, timeout: int):  # noqa: ANN001 - urllib test double
            seen["url"] = req.full_url
            seen["headers"] = dict(req.header_items())
            seen["body"] = req.data.decode("utf-8")
            seen["timeout"] = timeout
            return FakeResponse()

        monkeypatch.setattr(
            "enoch_control_plane.control_plane.router.urllib.request.urlopen",
            fake_urlopen,
        )

        response = client.post(
            "/control/api/settings/llm/test",
            headers={"Authorization": f"Bearer {TOKEN}"},
            json={"provider_id": "openrouter", "model_id": "moonshotai/kimi-k2.6"},
        )

        assert response.status_code == 200
        assert response.json()["ok"] is True
        assert seen["url"] == "https://openrouter.ai/api/v1/chat/completions"
        assert seen["timeout"] == 20
        assert "Bearer or-secret-value" in str(seen["headers"])
        assert '"model": "moonshotai/kimi-k2.6"' in str(seen["body"])


def test_llm_settings_model_test_records_scrubbed_health_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeResponse:
        status = 429

        def __enter__(self):
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self, *_args: object) -> bytes:
            return b'{"error":"rate limited for key or-secret-value"}'

        def close(self) -> None:
            return None

    class FakeStore:
        def __init__(self) -> None:
            self.events: list[dict[str, object]] = []

        def append_event(self, **kwargs: object) -> int:
            self.events.append(kwargs)
            return len(self.events)

    with tempfile.TemporaryDirectory() as tmp:
        config = _config(tmp)
        store = FakeStore()
        client = _client(config, monkeypatch=monkeypatch, store=store)
        settings = default_llm_settings(config)
        openrouter = next(
            provider
            for provider in settings.providers
            if provider.provider_id == "openrouter"
        )
        openrouter.enabled = True
        settings.models.append(
            LLMModelSettings(
                model_id="moonshotai/kimi-k2.6",
                provider_id="openrouter",
                label="Kimi K2.6",
                enabled=True,
                weight=90,
            )
        )
        write_llm_settings(config, settings, updated_by="test")
        write_llm_provider_secrets(
            config, {"openrouter": "or-secret-value"}, settings=settings
        )

        def fake_urlopen(req, timeout: int):  # noqa: ANN001 - urllib test double
            raise urllib.error.HTTPError(
                req.full_url,
                429,
                "Too Many Requests",
                hdrs=None,
                fp=FakeResponse(),
            )

        monkeypatch.setattr(
            "enoch_control_plane.control_plane.router.urllib.request.urlopen",
            fake_urlopen,
        )

        response = client.post(
            "/control/api/settings/llm/test",
            headers={"Authorization": f"Bearer {TOKEN}"},
            json={"provider_id": "openrouter", "model_id": "moonshotai/kimi-k2.6"},
        )

        assert response.status_code == 200
        assert response.json()["ok"] is False
        assert "or-secret-value" not in response.text
        assert store.events
        event = store.events[0]
        assert event["event_type"] == "settings.llm.model_test"
        assert event["entity_type"] == "llm_model"
        assert event["entity_id"] == "openrouter:moonshotai/kimi-k2.6"
        payload = event["payload"]
        assert payload["provider_id"] == "openrouter"
        assert payload["model_id"] == "moonshotai/kimi-k2.6"
        assert payload["status_code"] == 429
        assert payload["failure_kind"] == "rate_limited"
        assert "or-secret-value" not in str(payload)


def test_llm_model_health_summary_marks_recent_failures_and_stale_models() -> None:
    from enoch_control_plane.control_plane.read_models import llm_model_health_summary

    settings = default_llm_settings()
    synthetic = next(
        provider
        for provider in settings.providers
        if provider.provider_id == "synthetic"
    )
    synthetic.enabled = True
    settings.models = [
        LLMModelSettings(
            model_id="hf:healthy",
            provider_id="synthetic",
            label="Healthy",
            enabled=True,
        ),
        LLMModelSettings(
            model_id="hf:gone",
            provider_id="synthetic",
            label="Gone",
            enabled=True,
        ),
        LLMModelSettings(
            model_id="hf:stale",
            provider_id="synthetic",
            label="Stale",
            enabled=True,
        ),
    ]

    class FakeStore:
        def event_page(self, **_kwargs):
            return (
                [
                    {
                        "event_id": 3,
                        "created_at": "2026-06-01T19:00:00Z",
                        "payload": {
                            "provider_id": "synthetic",
                            "model_id": "hf:gone",
                            "ok": False,
                            "status_code": 404,
                            "failure_kind": "model_not_found",
                            "latency_ms": 120,
                            "checked_at": "2026-06-01T19:00:00Z",
                        },
                    },
                    {
                        "event_id": 2,
                        "created_at": "2026-06-01T18:59:00Z",
                        "payload": {
                            "provider_id": "synthetic",
                            "model_id": "hf:healthy",
                            "ok": True,
                            "status_code": 200,
                            "latency_ms": 80,
                            "checked_at": "2026-06-01T18:59:00Z",
                        },
                    },
                ],
                None,
                False,
            )

    summary = llm_model_health_summary(FakeStore(), settings)

    rows = {row["model_id"]: row for row in summary["models"]}
    assert summary["unhealthy_count"] == 2
    assert rows["hf:healthy"]["status"] == "healthy"
    assert rows["hf:healthy"]["success_rate"] == 1.0
    assert rows["hf:gone"]["status"] == "unhealthy"
    assert rows["hf:gone"]["latest_failure_kind"] == "model_not_found"
    assert rows["hf:stale"]["status"] == "stale"
    assert rows["hf:stale"]["latest"] is None


def test_research_provider_selection_uses_persisted_settings() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        config = _config(tmp)
        settings = default_llm_settings(config)
        openrouter = next(
            provider
            for provider in settings.providers
            if provider.provider_id == "openrouter"
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
            item
            for item in settings.workflows
            if item.workflow_id == "research_generation"
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
