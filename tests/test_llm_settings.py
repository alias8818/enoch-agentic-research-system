from __future__ import annotations

import json
import tempfile
import urllib.error
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from enoch_control_plane.config import GateConfig
from enoch_control_plane.control_plane import read_models
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


def test_llm_model_health_summarizes_structured_output_capability_evidence() -> None:
    model_id = "minimax/minimax-m3"
    settings = default_llm_settings()
    openrouter = next(
        provider
        for provider in settings.providers
        if provider.provider_id == "openrouter"
    )
    openrouter.enabled = True
    settings.models.append(
        LLMModelSettings(
            model_id=model_id,
            provider_id="openrouter",
            label="MiniMax M3",
            enabled=True,
        )
    )
    research_generation = next(
        workflow
        for workflow in settings.workflows
        if workflow.workflow_id == "research_generation"
    )
    research_generation.provider_ids = ["openrouter"]
    research_generation.model_pool = [model_id]
    research_generation.default_model = model_id

    class FakeStore:
        def event_page(self, **_kwargs: object):
            return (
                [
                    {
                        "event_id": 3,
                        "payload": {
                            "provider_id": "openrouter",
                            "model_id": model_id,
                            "ok": True,
                            "status_code": 200,
                            "source": "format_probe",
                            "prompt_contract": "candidate_json",
                            "structured_output_mode": "json_schema",
                            "response_format_type": "json_schema",
                            "checked_at": "2026-06-10T23:01:00Z",
                            "finish_reason": "stop",
                            "visible_chars": 100,
                            "valid_json": True,
                            "schema_ok": True,
                            "malformed_kind": "",
                        },
                    },
                    {
                        "event_id": 2,
                        "payload": {
                            "provider_id": "openrouter",
                            "model_id": model_id,
                            "ok": False,
                            "status_code": 400,
                            "source": "format_probe",
                            "prompt_contract": "candidate_json",
                            "structured_output_mode": "json_object",
                            "response_format_type": "json_object",
                            "checked_at": "2026-06-10T23:00:00Z",
                            "failure_kind": "unsupported_response_format",
                            "error": "provider does not support response_format json_object",
                        },
                    },
                    {
                        "event_id": 1,
                        "payload": {
                            "provider_id": "openrouter",
                            "model_id": model_id,
                            "ok": True,
                            "status_code": 200,
                            "source": "format_probe",
                            "prompt_contract": "candidate_json",
                            "structured_output_mode": "prompt_only",
                            "response_format_type": "prompt_only",
                            "checked_at": "2026-06-10T22:59:00Z",
                            "finish_reason": "stop",
                            "visible_chars": 64,
                            "valid_json": True,
                            "schema_ok": False,
                            "malformed_kind": "legacy_candidate_array_shape",
                            "recoverable_json_shape": True,
                        },
                    },
                ],
                None,
                False,
            )

    summary = read_models.llm_model_health_summary(FakeStore(), settings)

    capability = summary["structured_output_capabilities"][f"openrouter:{model_id}"][
        "candidate_json"
    ]
    assert capability["schema_contract_name"] == "candidate_json/v1"
    assert capability["recommended_response_format_type"] == "json_schema"
    assert capability["modes"]["json_schema"]["status"] == "supported"
    assert capability["modes"]["json_schema"]["schema_ok_rate"] == 1
    assert capability["modes"]["json_object"]["status"] == "unsupported"
    assert capability["modes"]["json_object"]["unsupported_mode_errors"] == 1

    workflow = summary["workflow_recommendations"][0]
    assert workflow["workflow_id"] == "research_generation"
    assert workflow["status"] == "healthy"
    assert workflow["route_policy"]["mode"] == "observe_only"
    assert workflow["route_policy"]["production_route_mutation"] is False
    assert workflow["route_policy"]["recommended_response_format_type"] == "json_schema"
    assert workflow["models"][0]["recommendation"] == "usable"
    assert (
        workflow["models"][0]["contract_results"][0]["response_format_type"]
        == "json_schema"
    )


def test_llm_settings_reject_unknown_workflow_model() -> None:
    settings = default_llm_settings().model_dump(mode="json")
    settings["workflows"][0]["model_pool"].append("missing-model")

    with pytest.raises(ValueError, match="unknown models"):
        LLMSettings.model_validate(settings)


def test_llm_settings_rejects_untrusted_provider_base_url() -> None:
    settings = default_llm_settings().model_dump(mode="json")
    settings["providers"][0]["base_url"] = "https://attacker.example/openai/v1"

    with pytest.raises(ValueError, match="trusted LLM provider"):
        LLMSettings.model_validate(settings)


def test_llm_settings_rejects_cross_provider_api_key_env() -> None:
    settings = default_llm_settings().model_dump(mode="json")
    openrouter = next(
        provider
        for provider in settings["providers"]
        if provider["provider_id"] == "openrouter"
    )
    openrouter["api_key_env"] = "SYNTHETIC_API_KEY"

    with pytest.raises(ValueError, match="api_key_env for openrouter"):
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


def test_llm_settings_update_event_error_is_generic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingEventStore:
        def append_event(self, **_kwargs: object) -> int:
            raise RuntimeError("stack trace details must stay server-side")

    with tempfile.TemporaryDirectory() as tmp:
        config = _config(tmp)
        client = _client(config, monkeypatch, FailingEventStore())
        settings = default_llm_settings(config)

        response = client.post(
            "/control/api/settings/llm",
            headers={"Authorization": f"Bearer {TOKEN}"},
            json={"requested_by": "test", "settings": settings.model_dump(mode="json")},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["event_error"] == "settings update event could not be recorded"
        assert "RuntimeError" not in response.text
        assert "stack trace details" not in response.text


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
            json={
                "provider_id": "openrouter",
                "model_id": "moonshotai/kimi-k2.6",
                "source": "autopilot",
            },
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
            json={
                "provider_id": "openrouter",
                "model_id": "moonshotai/kimi-k2.6",
                "source": "autopilot",
            },
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
        assert payload["source"] == "autopilot"
        assert "or-secret-value" not in str(payload)


def test_llm_settings_format_probe_http_error_preserves_contract_and_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeResponse:
        status = 400

        def read(self, *_args: object) -> bytes:
            return b'{"error":"unsupported response_format json_object"}'

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
                model_id="minimax/minimax-m3",
                provider_id="openrouter",
                label="MiniMax M3",
                enabled=True,
            )
        )
        write_llm_settings(config, settings, updated_by="test")
        write_llm_provider_secrets(
            config, {"openrouter": "or-secret-value"}, settings=settings
        )

        def fake_urlopen(req, timeout: int):  # noqa: ANN001 - urllib test double
            raise urllib.error.HTTPError(
                req.full_url,
                400,
                "Bad Request",
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
            json={
                "provider_id": "openrouter",
                "model_id": "minimax/minimax-m3",
                "prompt_contract": "candidate_json",
                "structured_output_mode": "json_object",
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is False
        assert body["prompt_contract"] == "candidate_json"
        assert body["structured_output_mode"] == "json_object"
        assert body["response_format_type"] == "json_object"
        assert store.events
        payload = store.events[0]["payload"]
        assert payload["prompt_contract"] == "candidate_json"
        assert payload["structured_output_mode"] == "json_object"
        assert payload["response_format_type"] == "json_object"
        assert payload["failure_kind"] == "unsupported_response_format"


def test_llm_settings_model_test_records_visible_output_health(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self, *_args: object) -> bytes:
            return (
                b'{"choices":[{"message":{"content":""},"finish_reason":"length"}],'
                b'"usage":{"prompt_tokens":5,"completion_tokens":12,'
                b'"completion_tokens_details":{"reasoning_tokens":12}}}'
            )

    class FakeStore:
        def __init__(self) -> None:
            self.events: list[dict[str, object]] = []

        def append_event(self, **kwargs: object) -> int:
            self.events.append(
                {
                    "event_id": len(self.events) + 1,
                    "created_at": "2026-06-02T10:00:00Z",
                    **kwargs,
                }
            )
            return len(self.events)

        def event_page(self, **_kwargs: object):
            return self.events, None, False

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
                model_id="owl/strict-json",
                provider_id="openrouter",
                label="Owl Strict JSON",
                enabled=True,
                weight=90,
            )
        )
        write_llm_settings(config, settings, updated_by="test")
        write_llm_provider_secrets(
            config, {"openrouter": "or-secret-value"}, settings=settings
        )

        monkeypatch.setattr(
            "enoch_control_plane.control_plane.router.urllib.request.urlopen",
            lambda _req, timeout: FakeResponse(),
        )

        response = client.post(
            "/control/api/settings/llm/test",
            headers={"Authorization": f"Bearer {TOKEN}"},
            json={
                "provider_id": "openrouter",
                "model_id": "owl/strict-json",
                "source": "manual",
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        assert body["visible_chars"] == 0
        assert body["finish_reason"] == "length"
        assert body["reasoning_tokens"] == 12
        assert store.events
        payload = store.events[0]["payload"]
        assert payload["visible_chars"] == 0
        assert payload["finish_reason"] == "length"
        assert payload["input_tokens"] == 5
        assert payload["output_tokens"] == 12
        assert payload["reasoning_tokens"] == 12
        health = client.get(
            "/control/api/v1/observability/llm-models",
            headers={"Authorization": f"Bearer {TOKEN}"},
        )
        assert health.status_code == 200
        rows = {row["model_id"]: row for row in health.json()["models"]}
        owl = rows["owl/strict-json"]
        assert owl["endpoint_health"] == "healthy"
        assert owl["visible_output_health"] == "empty"
        assert owl["reasoning_budget_health"] == "length_limited"
        assert health.json()["structurally_unhealthy_count"] == 1


def test_llm_settings_format_probe_records_schema_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self, *_args: object) -> bytes:
            return (
                b'{"choices":[{"message":{"content":"{\\"ok\\":true,'
                b'\\"items\\":[1,2]}"},"finish_reason":"stop"}]}'
            )

    class FakeStore:
        def __init__(self) -> None:
            self.events: list[dict[str, object]] = []

        def append_event(self, **kwargs: object) -> int:
            self.events.append(kwargs)
            return len(self.events)

        def event_page(self, **_kwargs: object):
            return self.events, None, False

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
                model_id="owl/strict-json",
                provider_id="openrouter",
                label="Owl Strict JSON",
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
            json={
                "provider_id": "openrouter",
                "model_id": "owl/strict-json",
                "prompt_contract": "strict_json",
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        assert body["prompt_contract"] == "strict_json"
        assert body["valid_json"] is True
        assert body["schema_ok"] is True
        assert body["malformed_kind"] == ""
        assert '"max_tokens": 128' in str(seen["body"])
        assert "Return only this compact JSON object" in str(seen["body"])
        payload = store.events[0]["payload"]
        assert payload["source"] == "format_probe"
        assert payload["prompt_contract"] == "strict_json"
        assert payload["max_tokens"] == 128
        assert payload["valid_json"] is True
        assert payload["schema_ok"] is True
        assert payload["malformed_kind"] == ""


def test_llm_settings_candidate_json_probe_prompt_matches_schema_shape() -> None:
    from enoch_control_plane.control_plane.router import (
        _llm_format_probe_prompt,
        _llm_probe_json_schema,
    )

    prompt = _llm_format_probe_prompt("candidate_json")
    schema = _llm_probe_json_schema("candidate_json")

    assert schema["type"] == "object"
    assert schema["required"] == ["candidates"]
    assert "compact JSON object" in prompt
    assert '"candidates"' in prompt
    assert "compact JSON array" not in prompt


def test_llm_settings_candidate_json_probe_array_shape_is_recoverable_mismatch() -> (
    None
):
    from enoch_control_plane.control_plane.router import _evaluate_llm_format_probe

    result = _evaluate_llm_format_probe(
        "candidate_json",
        visible_text='[{"title":"Probe","rationale":"Legacy array shape"}]',
        finish_reason="stop",
    )

    assert result["valid_json"] is True
    assert result["schema_ok"] is False
    assert result["malformed_kind"] == "legacy_candidate_array_shape"
    assert result["recoverable_json_shape"] is True


def test_llm_settings_candidate_json_probe_uses_structured_output_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self, *_args: object) -> bytes:
            return (
                b'{"choices":[{"message":{"content":'
                b'"{\\"candidates\\":[{\\"title\\":\\"Probe\\",'
                b'\\"rationale\\":\\"Enough budget\\"}]}"},'
                b'"finish_reason":"stop"}]}'
            )

    class FakeStore:
        def __init__(self) -> None:
            self.events: list[dict[str, object]] = []

        def append_event(self, **kwargs: object) -> int:
            self.events.append(kwargs)
            return len(self.events)

        def event_page(self, **_kwargs: object):
            return self.events, None, False

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
                model_id="owl/candidate-json",
                provider_id="openrouter",
                label="Owl Candidate JSON",
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
            json={
                "provider_id": "openrouter",
                "model_id": "owl/candidate-json",
                "prompt_contract": "candidate_json",
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        assert body["prompt_contract"] == "candidate_json"
        assert body["max_tokens"] == 1024
        assert body["valid_json"] is True
        assert body["schema_ok"] is True
        assert body["malformed_kind"] == ""
        assert '"max_tokens": 1024' in str(seen["body"])
        request_payload = json.loads(str(seen["body"]))
        prompt = request_payload["messages"][0]["content"]
        assert "compact JSON object" in prompt
        assert '"candidates"' in prompt
        payload = store.events[0]["payload"]
        assert payload["source"] == "format_probe"
        assert payload["prompt_contract"] == "candidate_json"
        assert payload["max_tokens"] == 1024
        assert payload["valid_json"] is True
        assert payload["schema_ok"] is True
        assert payload["malformed_kind"] == ""


def test_llm_settings_candidate_json_probe_rejects_extra_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self, *_args: object) -> bytes:
            return (
                b'{"choices":[{"message":{"content":"{\\"candidates\\":'
                b'[{\\"title\\":\\"One\\",\\"rationale\\":\\"A\\"},'
                b'{\\"title\\":\\"Two\\",\\"rationale\\":\\"B\\"}]}"},'
                b'"finish_reason":"stop"}]}'
            )

    with tempfile.TemporaryDirectory() as tmp:
        config = _config(tmp)
        client = _client(config, monkeypatch=monkeypatch)
        settings = default_llm_settings(config)
        openrouter = next(
            provider
            for provider in settings.providers
            if provider.provider_id == "openrouter"
        )
        openrouter.enabled = True
        settings.models.append(
            LLMModelSettings(
                model_id="owl/candidate-json",
                provider_id="openrouter",
                label="Owl Candidate JSON",
                enabled=True,
                weight=90,
            )
        )
        write_llm_settings(config, settings, updated_by="test")
        write_llm_provider_secrets(
            config, {"openrouter": "or-secret-value"}, settings=settings
        )
        monkeypatch.setattr(
            "enoch_control_plane.control_plane.router.urllib.request.urlopen",
            lambda _req, timeout: FakeResponse(),
        )

        response = client.post(
            "/control/api/settings/llm/test",
            headers={"Authorization": f"Bearer {TOKEN}"},
            json={
                "provider_id": "openrouter",
                "model_id": "owl/candidate-json",
                "prompt_contract": "candidate_json",
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["valid_json"] is True
        assert body["candidate_count"] == 2
        assert body["schema_ok"] is False
        assert body["malformed_kind"] == "schema_mismatch"


def test_llm_settings_openrouter_candidate_json_object_probe_records_structured_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self, *_args: object) -> bytes:
            return (
                b'{"choices":[{"message":{"content":"{\\"candidates\\":'
                b'[{\\"title\\":\\"Probe\\",\\"rationale\\":\\"JSON object mode\\"}]}"},'
                b'"finish_reason":"stop"}]}'
            )

    class FakeStore:
        def __init__(self) -> None:
            self.events: list[dict[str, object]] = []

        def append_event(self, **kwargs: object) -> int:
            self.events.append(kwargs)
            return len(self.events)

        def event_page(self, **_kwargs: object):
            return self.events, None, False

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
                model_id="deepseek/deepseek-v4-pro",
                provider_id="openrouter",
                label="DeepSeek V4 Pro",
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
            json={
                "provider_id": "openrouter",
                "model_id": "deepseek/deepseek-v4-pro",
                "source": "manual",
                "prompt_contract": "candidate_json",
                "structured_output_mode": "json_object",
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        assert body["structured_output_mode"] == "json_object"
        assert body["response_format_type"] == "json_object"
        assert body["valid_json"] is True
        assert body["schema_ok"] is True
        assert body["candidate_count"] == 1
        assert body["candidate_title_complete"] is True
        assert body["candidate_rationale_complete"] is True

        request_payload = json.loads(str(seen["body"]))
        assert request_payload["response_format"] == {"type": "json_object"}

        event_payload = store.events[0]["payload"]
        assert event_payload["structured_output_mode"] == "json_object"
        assert event_payload["response_format_type"] == "json_object"
        assert event_payload["candidate_count"] == 1
        assert event_payload["candidate_title_complete"] is True
        assert event_payload["candidate_rationale_complete"] is True


def test_llm_settings_openrouter_candidate_schema_probe_records_structured_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self, *_args: object) -> bytes:
            return (
                b'{"choices":[{"message":{"content":"{\\"candidates\\":'
                b'[{\\"title\\":\\"Probe\\",\\"rationale\\":\\"Schema\\"}]}"},'
                b'"finish_reason":"stop"}]}'
            )

    class FakeStore:
        def __init__(self) -> None:
            self.events: list[dict[str, object]] = []

        def append_event(self, **kwargs: object) -> int:
            self.events.append(kwargs)
            return len(self.events)

        def event_page(self, **_kwargs: object):
            return self.events, None, False

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
                model_id="deepseek/deepseek-v4-pro",
                provider_id="openrouter",
                label="DeepSeek V4 Pro",
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
            json={
                "provider_id": "openrouter",
                "model_id": "deepseek/deepseek-v4-pro",
                "source": "manual",
                "prompt_contract": "candidate_json",
                "structured_output_mode": "json_schema",
                "reasoning_effort": "low",
                "reasoning_exclude": True,
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        assert body["prompt_contract"] == "candidate_json"
        assert body["max_tokens"] == 1024
        assert body["valid_json"] is True
        assert body["schema_ok"] is True
        assert body["structured_output_mode"] == "json_schema"
        assert body["response_format_type"] == "json_schema"
        assert body["reasoning_effort"] == "low"
        assert body["reasoning_excluded"] is True

        request_payload = json.loads(str(seen["body"]))
        assert request_payload["response_format"]["type"] == "json_schema"
        schema = request_payload["response_format"]["json_schema"]
        assert schema["name"] == "enoch_candidate_probe"
        assert schema["strict"] is True
        assert schema["schema"]["required"] == ["candidates"]
        assert request_payload["reasoning"] == {"effort": "low", "exclude": True}

        event_payload = store.events[0]["payload"]
        assert event_payload["source"] == "format_probe"
        assert event_payload["structured_output_mode"] == "json_schema"
        assert event_payload["response_format_type"] == "json_schema"
        assert event_payload["reasoning_effort"] == "low"
        assert event_payload["reasoning_excluded"] is True


def test_llm_settings_format_probe_records_malformed_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self, *_args: object) -> bytes:
            return (
                b'{"choices":[{"message":{"content":"not json"},'
                b'"finish_reason":"stop"}]}'
            )

    class FakeStore:
        def __init__(self) -> None:
            self.events: list[dict[str, object]] = []

        def append_event(self, **kwargs: object) -> int:
            self.events.append(
                {
                    "event_id": len(self.events) + 1,
                    "created_at": "2026-06-02T10:00:00Z",
                    **kwargs,
                }
            )
            return len(self.events)

        def event_page(self, **_kwargs: object):
            return self.events, None, False

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
                model_id="owl/strict-json",
                provider_id="openrouter",
                label="Owl Strict JSON",
                enabled=True,
                weight=90,
            )
        )
        write_llm_settings(config, settings, updated_by="test")
        write_llm_provider_secrets(
            config, {"openrouter": "or-secret-value"}, settings=settings
        )
        monkeypatch.setattr(
            "enoch_control_plane.control_plane.router.urllib.request.urlopen",
            lambda _req, timeout: FakeResponse(),
        )

        response = client.post(
            "/control/api/settings/llm/test",
            headers={"Authorization": f"Bearer {TOKEN}"},
            json={
                "provider_id": "openrouter",
                "model_id": "owl/strict-json",
                "prompt_contract": "strict_json",
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        assert body["valid_json"] is False
        assert body["schema_ok"] is False
        assert body["malformed_kind"] == "invalid_json"
        health = client.get(
            "/control/api/v1/observability/llm-models",
            headers={"Authorization": f"Bearer {TOKEN}"},
        )
        rows = {row["model_id"]: row for row in health.json()["models"]}
        assert rows["owl/strict-json"]["endpoint_health"] == "healthy"
        assert rows["owl/strict-json"]["format_health"] == "degraded"
        assert rows["owl/strict-json"]["latest_malformed_kind"] == "invalid_json"


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


def test_llm_model_health_summary_distinguishes_endpoint_and_format_health() -> None:
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
            model_id="hf:empty",
            provider_id="synthetic",
            label="Empty Output",
            enabled=True,
        ),
        LLMModelSettings(
            model_id="hf:bad-json",
            provider_id="synthetic",
            label="Bad JSON",
            enabled=True,
        ),
        LLMModelSettings(
            model_id="hf:ok",
            provider_id="synthetic",
            label="OK",
            enabled=True,
        ),
    ]

    class FakeStore:
        def event_page(self, **_kwargs):
            return (
                [
                    {
                        "event_id": 4,
                        "created_at": "2026-06-02T10:02:00Z",
                        "payload": {
                            "provider_id": "synthetic",
                            "model_id": "hf:ok",
                            "ok": True,
                            "status_code": 200,
                            "latency_ms": 65,
                            "checked_at": "2026-06-02T10:02:00Z",
                            "source": "format_probe",
                            "prompt_contract": "strict_json",
                            "valid_json": True,
                            "schema_ok": True,
                            "finish_reason": "stop",
                            "visible_chars": 42,
                        },
                    },
                    {
                        "event_id": 3,
                        "created_at": "2026-06-02T10:01:00Z",
                        "payload": {
                            "provider_id": "synthetic",
                            "model_id": "hf:bad-json",
                            "ok": True,
                            "status_code": 200,
                            "latency_ms": 70,
                            "checked_at": "2026-06-02T10:01:00Z",
                            "source": "format_probe",
                            "prompt_contract": "strict_json",
                            "valid_json": False,
                            "schema_ok": False,
                            "malformed_kind": "invalid_json",
                            "visible_chars": 12,
                            "response_preview_redacted": "{not json",
                        },
                    },
                    {
                        "event_id": 2,
                        "created_at": "2026-06-02T10:00:00Z",
                        "payload": {
                            "provider_id": "synthetic",
                            "model_id": "hf:empty",
                            "ok": True,
                            "status_code": 200,
                            "latency_ms": 80,
                            "checked_at": "2026-06-02T10:00:00Z",
                            "finish_reason": "length",
                            "visible_chars": 0,
                            "reasoning_tokens": 12,
                        },
                    },
                ],
                None,
                False,
            )

    summary = llm_model_health_summary(FakeStore(), settings)

    rows = {row["model_id"]: row for row in summary["models"]}
    assert summary["ok"] is False
    assert summary["unhealthy_count"] == 0
    assert summary["structurally_unhealthy_count"] == 2
    assert rows["hf:empty"]["endpoint_health"] == "healthy"
    assert rows["hf:empty"]["visible_output_health"] == "empty"
    assert rows["hf:empty"]["reasoning_budget_health"] == "length_limited"
    assert "increase output budget" in rows["hf:empty"]["operator_action"]
    assert rows["hf:bad-json"]["endpoint_health"] == "healthy"
    assert rows["hf:bad-json"]["format_health"] == "degraded"
    assert rows["hf:bad-json"]["format_success_rate"] == 0.0
    assert rows["hf:bad-json"]["latest_preview"] == "{not json"
    assert rows["hf:ok"]["format_health"] == "healthy"
    assert rows["hf:ok"]["workflow_health"] == "unmeasured"


def test_llm_model_health_summary_recommends_workflow_pool_tuning() -> None:
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
            model_id="hf:empty",
            provider_id="synthetic",
            label="Empty Output",
            enabled=True,
        ),
        LLMModelSettings(
            model_id="hf:bad-json",
            provider_id="synthetic",
            label="Bad JSON",
            enabled=True,
        ),
        LLMModelSettings(
            model_id="hf:ok",
            provider_id="synthetic",
            label="OK",
            enabled=True,
        ),
    ]
    generation = next(
        workflow
        for workflow in settings.workflows
        if workflow.workflow_id == "research_generation"
    )
    generation.model_pool = ["hf:empty", "hf:bad-json", "hf:ok"]
    generation.default_model = "hf:empty"

    class FakeStore:
        def event_page(self, **_kwargs):
            return (
                [
                    {
                        "event_id": 3,
                        "created_at": "2026-06-02T10:02:00Z",
                        "payload": {
                            "provider_id": "synthetic",
                            "model_id": "hf:ok",
                            "ok": True,
                            "checked_at": "2026-06-02T10:02:00Z",
                            "source": "format_probe",
                            "prompt_contract": "candidate_json",
                            "valid_json": True,
                            "schema_ok": True,
                            "finish_reason": "stop",
                            "visible_chars": 120,
                        },
                    },
                    {
                        "event_id": 2,
                        "created_at": "2026-06-02T10:01:00Z",
                        "payload": {
                            "provider_id": "synthetic",
                            "model_id": "hf:bad-json",
                            "ok": True,
                            "checked_at": "2026-06-02T10:01:00Z",
                            "source": "format_probe",
                            "prompt_contract": "candidate_json",
                            "valid_json": False,
                            "schema_ok": False,
                            "malformed_kind": "invalid_json",
                            "finish_reason": "stop",
                            "visible_chars": 80,
                        },
                    },
                    {
                        "event_id": 1,
                        "created_at": "2026-06-02T10:00:00Z",
                        "payload": {
                            "provider_id": "synthetic",
                            "model_id": "hf:empty",
                            "ok": True,
                            "checked_at": "2026-06-02T10:00:00Z",
                            "source": "format_probe",
                            "prompt_contract": "candidate_json",
                            "valid_json": False,
                            "schema_ok": False,
                            "malformed_kind": "empty_visible_output",
                            "finish_reason": "length",
                            "visible_chars": 0,
                        },
                    },
                ],
                None,
                False,
            )

    summary = llm_model_health_summary(FakeStore(), settings)

    generation_rec = next(
        item
        for item in summary["workflow_recommendations"]
        if item["workflow_id"] == "research_generation"
    )
    by_model = {item["model_id"]: item for item in generation_rec["models"]}
    assert generation_rec["required_contracts"] == ["candidate_json"]
    assert generation_rec["status"] == "needs_attention"
    assert generation_rec["recommended_model_pool"] == ["hf:ok"]
    assert generation_rec["recommended_default_model"] == "hf:ok"
    assert by_model["hf:empty"]["recommendation"] == "increase_max_tokens_or_remove"
    assert by_model["hf:bad-json"]["recommendation"] == "remove_for_contract"
    assert by_model["hf:ok"]["recommendation"] == "usable"
    assert "increase max_tokens" in by_model["hf:empty"]["operator_action"]
    assert "structurally unreliable" in by_model["hf:bad-json"]["operator_action"]


def test_llm_model_health_summary_surfaces_recoverable_candidate_json_shape() -> None:
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
            model_id="hf:legacy-array",
            provider_id="synthetic",
            label="Legacy Array",
            enabled=True,
        )
    ]
    generation = next(
        workflow
        for workflow in settings.workflows
        if workflow.workflow_id == "research_generation"
    )
    generation.model_pool = ["hf:legacy-array"]
    generation.default_model = "hf:legacy-array"

    class FakeStore:
        def event_page(self, **_kwargs):
            return (
                [
                    {
                        "event_id": 1,
                        "created_at": "2026-06-10T02:00:00Z",
                        "payload": {
                            "provider_id": "synthetic",
                            "model_id": "hf:legacy-array",
                            "ok": True,
                            "checked_at": "2026-06-10T02:00:00Z",
                            "source": "format_probe",
                            "prompt_contract": "candidate_json",
                            "valid_json": True,
                            "schema_ok": False,
                            "malformed_kind": "legacy_candidate_array_shape",
                            "recoverable_json_shape": True,
                            "finish_reason": "stop",
                            "visible_chars": 80,
                        },
                    }
                ],
                None,
                False,
            )

    summary = llm_model_health_summary(FakeStore(), settings)

    row = summary["models"][0]
    assert row["endpoint_health"] == "healthy"
    assert row["format_health"] == "recoverable_mismatch"
    assert row["recoverable_json_shape_count"] == 1
    assert row["latest_recoverable_json_shape"] is True
    assert "prompt/schema parser recovery" in row["operator_action"]
    assert summary["structurally_unhealthy_count"] == 1
    generation_rec = next(
        item
        for item in summary["workflow_recommendations"]
        if item["workflow_id"] == "research_generation"
    )
    model_rec = generation_rec["models"][0]
    assert model_rec["recommendation"] == "repair_recoverable_shape"
    assert model_rec["recoverable_shape_failures"] == ["candidate_json"]
    assert model_rec["contract_results"][0]["recoverable_json_shape"] is True


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
        overridden = _resolve_research_cycle_params(
            {
                "provider_openai_base_url": "https://attacker.example/openai/v1",
                "provider_base_url": "https://attacker.example",
            }
        )

        assert model == "openrouter/auto"
        assert allowed_models == ["openrouter/auto"]
        assert params.provider_openai_base_url == "https://openrouter.ai/api/v1"
        assert params.provider_base_url == "https://openrouter.ai/api/v1"
        assert overridden.provider_openai_base_url == "https://openrouter.ai/api/v1"
        assert overridden.provider_base_url == "https://openrouter.ai/api/v1"
