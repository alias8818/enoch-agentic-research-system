from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from scripts import research_provider_generate


def _provider_payload() -> dict:
    return {
        "id": "cmpl-provider-test",
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "candidates": [
                                {
                                    "title": "Ternary Residual Memory Probe",
                                    "generation_mode": "home_hardware_accessibility",
                                    "category": "quantization",
                                    "priority": "High",
                                    "hypothesis": "A tiny residual side channel can recover useful behavior from ternary weights below an int4 memory budget.",
                                    "mechanism": "Estimate critical activation directions and store sparse residuals only for those directions.",
                                    "description": "Provider-generated local compression candidate.",
                                    "implementation": "Quantize a small model, train residuals on calibration prompts, and compare against RTN ternary and int4.",
                                    "baseline_to_beat": "RTN ternary, 2-bit GPTQ, and int4 GPTQ at comparable memory.",
                                    "success_threshold": "Perplexity is at least 20% better than ternary while effective bits stay below 2.25.",
                                    "kill_condition": "Stop if residuals approach int4 size or gains vanish on held-out prompts.",
                                    "accessibility_delta": "If successful, useful local models fit in less VRAM.",
                                    "expected_artifacts": [
                                        "run_notes.md",
                                        "metrics.json",
                                        "failure_cases.json",
                                        ".enoch/project_decision.json",
                                    ],
                                    "required_evidence": [
                                        "baseline comparison",
                                        "metrics table",
                                        "failure cases",
                                        "decision artifact",
                                    ],
                                    "likely_failure_modes": [
                                        "residuals too large",
                                        "calibration overfit",
                                        "int4 remains better",
                                    ],
                                    "estimated_runtime_class": "medium",
                                    "expected_token_budget": "medium",
                                    "machine_target": "gb10",
                                    "model": "gpt-5.5",
                                    "sandbox": "danger-full-access",
                                    "novelty_score": 8,
                                    "feasibility_score": 6,
                                    "accessibility_score": 8,
                                    "falsifiability_score": 8,
                                    "novelty_comparison": "Unlike generic int4 quantization, this tests residual allocation below 2.25 effective bits.",
                                    "risk_notes": "Synthetic proposal; hardware and calibration details may dominate.",
                                }
                            ]
                        }
                    )
                }
            }
        ],
    }


def test_provider_response_becomes_research_candidate_with_source_record() -> None:
    candidates = research_provider_generate.candidates_from_provider_response(
        _provider_payload(),
        provider="synthetic.new",
        provider_model="hf:zai-org/GLM-5.1",
        topic="quantization",
        temperature=0.8,
        seed="seed-1",
        default_machine="gb10",
        default_model="gpt-5.5",
        default_sandbox="danger-full-access",
    )

    assert len(candidates) == 1
    row = candidates[0]
    assert row["provider"] == "synthetic.new"
    assert row["provider_model"] == "hf:zai-org/GLM-5.1"
    assert row["prompt_version"] == "research_provider_generate_v2"
    assert row["source_records"][0]["source_kind"] == "internal_generated"
    assert row["source_ids"]
    assert row["source_urls"][0].startswith("enoch://research-facility/provider/")
    assert row["raw_candidate_json"]["provider_response_id"] == "cmpl-provider-test"
    assert row["machine_target"] == "gb10"


def test_provider_response_enforces_requested_default_machine_target() -> None:
    payload = _provider_payload()
    candidate = json.loads(payload["choices"][0]["message"]["content"])["candidates"][0]
    candidate["machine_target"] = "research-facility-node"
    payload["choices"][0]["message"]["content"] = json.dumps(
        {"candidates": [candidate]}
    )

    candidates = research_provider_generate.candidates_from_provider_response(
        payload,
        provider="synthetic.new",
        provider_model="hf:zai-org/GLM-5.1",
        topic="Lane feed pressure: generate bounded work for machine_target=cpu-proxmox-1",
        temperature=0.8,
        seed="seed-override-machine",
        default_machine="cpu-proxmox-1",
        default_model="gpt-5.5",
        default_sandbox="danger-full-access",
    )

    assert candidates[0]["machine_target"] == "cpu-proxmox-1"
    assert (
        candidates[0]["raw_candidate_json"]["provider_candidate"]["machine_target"]
        == "research-facility-node"
    )


def test_provider_response_with_zero_usable_candidates_fails_closed() -> None:
    payload = {
        "id": "cmpl-empty",
        "choices": [{"message": {"content": json.dumps({"candidates": []})}}],
    }

    try:
        research_provider_generate.candidates_from_provider_response(
            payload,
            provider="synthetic.new",
            provider_model="hf:moonshotai/Kimi-K2.6",
            topic="quantization",
            temperature=0.3,
            seed="seed-empty",
            default_machine="gb10",
            default_model="gpt-5.5",
            default_sandbox="danger-full-access",
        )
    except ValueError as exc:
        assert "0 usable candidates" in str(exc)
    else:  # pragma: no cover - explicit failure branch for assertion clarity
        raise AssertionError("expected zero-candidate provider response to fail closed")


def test_provider_generate_calls_openai_compatible_endpoint_without_local_auth_when_empty_key() -> (
    None
):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(_provider_payload()).encode("utf-8")

    with patch(
        "scripts.research_provider_generate.urllib.request.urlopen",
        return_value=FakeResponse(),
    ) as urlopen:
        result = research_provider_generate.generate_provider_candidates(
            base_url="https://synthetic.int.exe.xyz/openai/v1",
            model="hf:zai-org/GLM-5.1",
            api_key="",
            max_candidates=1,
            topic="quantization",
            temperature=0.7,
            seed="seed-2",
        )

    assert result["ok"] is True
    assert result["candidate_count"] == 1
    request = urlopen.call_args.args[0]
    assert request.full_url.endswith("/chat/completions")
    assert "Authorization" not in request.headers
    payload = json.loads(request.data.decode("utf-8"))
    assert payload["model"] == "hf:zai-org/GLM-5.1"
    assert payload["temperature"] == 0.7
    assert payload["max_tokens"] == research_provider_generate.DEFAULT_MAX_TOKENS
    assert payload["response_format"] == {"type": "json_object"}
    prompt = payload["messages"][1]["content"]
    assert "Never return an empty candidates array" in prompt
    assert "GPT-2-small-class model architecture tests" in prompt
    assert "Tier 2 medium confirmation" in prompt
    assert "Pure simulations" in prompt


def test_provider_generate_can_request_strict_json_schema_response_format() -> None:
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(_provider_payload()).encode("utf-8")

    with patch(
        "scripts.research_provider_generate.urllib.request.urlopen",
        return_value=FakeResponse(),
    ) as urlopen:
        result = research_provider_generate.generate_provider_candidates(
            base_url="https://openrouter.ai/api/v1",
            model="deepseek/deepseek-v4-pro",
            api_key="or-secret",
            max_candidates=1,
            topic="quantization",
            temperature=0.7,
            seed="seed-json-schema",
            response_format_type="json_schema",
            reasoning_effort="low",
            reasoning_exclude=True,
        )

    assert result["ok"] is True
    request = urlopen.call_args.args[0]
    payload = json.loads(request.data.decode("utf-8"))
    assert payload["response_format"]["type"] == "json_schema"
    schema = payload["response_format"]["json_schema"]
    assert schema["name"] == "enoch_research_candidates"
    assert schema["strict"] is True
    assert schema["schema"]["required"] == ["candidates"]
    assert schema["schema"]["properties"]["candidates"]["maxItems"] == 1
    assert (
        schema["schema"]["properties"]["candidates"]["items"]["additionalProperties"]
        is False
    )
    assert payload["reasoning"] == {"effort": "low", "exclude": True}


def test_provider_generate_omits_authorization_for_proxy_default_even_with_key() -> (
    None
):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(_provider_payload()).encode("utf-8")

    with patch(
        "scripts.research_provider_generate.urllib.request.urlopen",
        return_value=FakeResponse(),
    ) as urlopen:
        research_provider_generate.generate_provider_candidates(
            base_url="https://synthetic.int.exe.xyz/openai/v1",
            model="hf:zai-org/GLM-5.1",
            api_key="secret-should-not-send",
            max_candidates=1,
            topic="quantization",
            temperature=0.7,
            seed="seed-proxy-no-auth",
        )

    request = urlopen.call_args.args[0]
    assert "Authorization" not in request.headers


def test_provider_generate_omits_authorization_for_proxy_trailing_dot_host() -> None:
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(_provider_payload()).encode("utf-8")

    with patch(
        "scripts.research_provider_generate.urllib.request.urlopen",
        return_value=FakeResponse(),
    ) as urlopen:
        research_provider_generate.generate_provider_candidates(
            base_url="https://synthetic.int.exe.xyz./openai/v1",
            model="hf:zai-org/GLM-5.1",
            api_key="secret-should-not-send",
            max_candidates=1,
            topic="quantization",
            temperature=0.7,
            seed="seed-proxy-no-auth-dot",
        )

    request = urlopen.call_args.args[0]
    assert "Authorization" not in request.headers


def test_provider_generate_keeps_authorization_for_non_proxy_provider() -> None:
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(_provider_payload()).encode("utf-8")

    with patch(
        "scripts.research_provider_generate.urllib.request.urlopen",
        return_value=FakeResponse(),
    ) as urlopen:
        research_provider_generate.generate_provider_candidates(
            base_url="https://api.synthetic.new/openai/v1",
            model="hf:zai-org/GLM-5.1",
            api_key="secret-expected-to-send",
            max_candidates=1,
            topic="quantization",
            temperature=0.7,
            seed="seed-direct-auth",
        )

    request = urlopen.call_args.args[0]
    assert request.headers["Authorization"] == "Bearer secret-expected-to-send"


def test_provider_generate_rejects_authenticated_untrusted_provider_url(
    monkeypatch,
) -> None:
    def fake_urlopen(*_args, **_kwargs):
        raise AssertionError("urlopen should not run for untrusted authenticated URL")

    monkeypatch.setattr(
        research_provider_generate.urllib.request, "urlopen", fake_urlopen
    )

    with pytest.raises(ValueError, match="trusted LLM provider"):
        research_provider_generate.generate_provider_candidates(
            base_url="https://attacker.example/openai/v1",
            model="hf:zai-org/GLM-5.1",
            api_key="secret-should-not-send",
            max_candidates=1,
            topic="quantization",
            temperature=0.7,
            seed="seed-authenticated-untrusted",
        )


def test_provider_generate_retries_provider_call_error_before_succeeding(
    monkeypatch,
) -> None:
    calls = {"count": 0}

    def fake_call(**kwargs):  # noqa: ANN003 - mirrors provider call kwargs
        calls["count"] += 1
        if calls["count"] == 1:
            raise TimeoutError("temporary provider timeout")
        return _provider_payload()

    monkeypatch.setattr(
        research_provider_generate, "call_openai_compatible_chat", fake_call
    )

    result = research_provider_generate.generate_provider_candidates(
        base_url="https://synthetic.int.exe.xyz/openai/v1",
        model="hf:zai-org/GLM-5.1",
        api_key="",
        max_candidates=1,
        topic="quantization",
        temperature=0.7,
        seed="seed-call-retry",
        attempts=2,
    )

    assert result["candidate_count"] == 1
    assert result["attempts_used"] == 2


def test_provider_generate_retries_malformed_json_before_succeeding() -> None:
    class FakeResponse:
        calls = 0

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            FakeResponse.calls += 1
            if FakeResponse.calls == 1:
                payload = {
                    "id": "cmpl-bad",
                    "choices": [
                        {"message": {"content": '{"candidates":[{"title":"broken"'}}
                    ],
                }
            else:
                payload = _provider_payload()
            return json.dumps(payload).encode("utf-8")

    with patch(
        "scripts.research_provider_generate.urllib.request.urlopen",
        return_value=FakeResponse(),
    ):
        result = research_provider_generate.generate_provider_candidates(
            base_url="https://synthetic.int.exe.xyz/openai/v1",
            model="hf:moonshotai/Kimi-K2.6",
            api_key="",
            max_candidates=1,
            topic="quantization",
            temperature=0.3,
            seed="seed-retry",
            attempts=2,
        )

    assert result["candidate_count"] == 1
    assert result["attempts_requested"] == 2
    assert result["attempts_used"] == 2


def test_provider_generate_retries_null_choice_diagnostics_before_succeeding() -> None:
    class FakeResponse:
        calls = 0

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            FakeResponse.calls += 1
            if FakeResponse.calls == 1:
                payload = {"id": "cmpl-null-choice", "choices": [None]}
            else:
                payload = _provider_payload()
            return json.dumps(payload).encode("utf-8")

    with patch(
        "scripts.research_provider_generate.urllib.request.urlopen",
        return_value=FakeResponse(),
    ):
        result = research_provider_generate.generate_provider_candidates(
            base_url="https://synthetic.int.exe.xyz/openai/v1",
            model="hf:moonshotai/Kimi-K2.6",
            api_key="",
            max_candidates=1,
            topic="quantization",
            temperature=0.3,
            seed="seed-null-choice-retry",
            attempts=2,
        )

    assert result["candidate_count"] == 1
    assert result["attempts_used"] == 2


def test_provider_generate_failure_contains_bounded_attempt_diagnostics() -> None:
    class FakeResponse:
        calls = 0

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            FakeResponse.calls += 1
            content = "not-json " + ("x" * 900)
            payload = {
                "id": f"cmpl-bad-{FakeResponse.calls}",
                "choices": [{"message": {"content": content}}],
            }
            return json.dumps(payload).encode("utf-8")

    with patch(
        "scripts.research_provider_generate.urllib.request.urlopen",
        return_value=FakeResponse(),
    ):
        with pytest.raises(
            research_provider_generate.ProviderCandidateGenerationError
        ) as exc_info:
            research_provider_generate.generate_provider_candidates(
                base_url="https://synthetic.int.exe.xyz/openai/v1",
                model="hf:moonshotai/Kimi-K2.6",
                api_key="",
                max_candidates=1,
                topic="quantization",
                temperature=0.3,
                seed="seed-bad",
                attempts=2,
            )

    attempts = exc_info.value.attempts
    assert len(attempts) == 2
    assert attempts[0]["attempt"] == 1
    assert attempts[0]["provider_response_id"] == "cmpl-bad-1"
    assert attempts[0]["content_length"] == 909
    assert len(attempts[0]["content_preview"]) == 600
    assert attempts[0]["content_truncated"] is True
    assert len(attempts[0]["content_sha256"]) == 64
    assert attempts[0]["error_type"] == "JSONDecodeError"
    assert "not-json" in attempts[0]["content_preview"]


def test_generation_prompt_includes_research_quality_policy() -> None:
    prompt = research_provider_generate.build_generation_prompt(
        max_candidates=1,
        topic="quantization",
        model="hf:zai-org/GLM-5.1",
        temperature=0.6,
        seed="seed-policy",
    )

    assert "Additional Research Quality policy" in prompt
    assert "Public-benefit research objective" in prompt
    assert "produce something useful for someone else in the world" in prompt
    assert "Negative results are useful when they save others time" in prompt
    assert "Do not treat proxy-only" in prompt
    assert "supported but still finalize_negative" in prompt
    assert "Include memory-architecture candidates in the regular idea mix" in prompt
    assert "semantic compression" in prompt
    assert "no-memory, full-transcript search, or flat vector retrieval" in prompt
    assert "Do not propose another automatic follow-up at max depth" in prompt
    assert "generation does not queue work until promotion policy allows it" in prompt


def test_generation_prompt_uses_requested_machine_target_contract() -> None:
    prompt = research_provider_generate.build_generation_prompt(
        max_candidates=1,
        topic="CPU-bound agent replay",
        model="hf:zai-org/GLM-5.1",
        temperature=0.6,
        seed="seed-cpu",
        default_machine="cpu-proxmox-1",
        default_model="gpt-5.5-mini",
        default_sandbox="workspace-write",
    )

    assert 'machine_target="cpu-proxmox-1"' in prompt
    assert 'model="gpt-5.5-mini"' in prompt
    assert 'sandbox="workspace-write"' in prompt
    assert 'machine_target="gb10"' not in prompt


def test_provider_generate_rejects_non_http_base_url_before_urlopen(
    monkeypatch,
) -> None:
    def fake_urlopen(*_args, **_kwargs):
        raise AssertionError("urlopen should not run for unsafe provider URL")

    monkeypatch.setattr(
        research_provider_generate.urllib.request, "urlopen", fake_urlopen
    )
    try:
        research_provider_generate.generate_provider_candidates(
            base_url="file:///etc/passwd",
            model="hf:zai-org/GLM-5.1",
            api_key="",
            max_candidates=1,
            topic="quantization",
            temperature=0.7,
            seed="seed",
        )
    except ValueError as exc:
        assert "provider base_url must use http or https" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected unsafe provider URL rejection")


def test_provider_generate_caps_excess_provider_candidates(monkeypatch) -> None:
    payload = _provider_payload()
    first = payload["choices"][0]["message"]["content"]
    data = json.loads(first)
    second = dict(data["candidates"][0])
    second["title"] = "Second Overrun Candidate"
    data["candidates"].append(second)
    payload["choices"][0]["message"]["content"] = json.dumps(data)

    monkeypatch.setattr(
        research_provider_generate,
        "call_openai_compatible_chat",
        lambda **_kwargs: payload,
    )

    result = research_provider_generate.generate_provider_candidates(
        base_url="https://synthetic.int.exe.xyz/openai/v1",
        model="hf:zai-org/GLM-5.1",
        api_key="",
        max_candidates=1,
        topic="quantization",
        temperature=0.7,
        seed="seed-cap",
    )

    assert result["candidate_count"] == 1
    assert len(result["candidates"]) == 1
    assert result["candidates"][0]["title"] == data["candidates"][0]["title"]
