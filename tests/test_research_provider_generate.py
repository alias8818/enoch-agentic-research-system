from __future__ import annotations

import json
from unittest.mock import patch

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
                                    "expected_artifacts": ["run_notes.md", "metrics.json", "failure_cases.json", ".enoch/project_decision.json"],
                                    "required_evidence": ["baseline comparison", "metrics table", "failure cases", "decision artifact"],
                                    "likely_failure_modes": ["residuals too large", "calibration overfit", "int4 remains better"],
                                    "estimated_runtime_class": "medium",
                                    "expected_token_budget": "medium",
                                    "machine_target": "192.168.1.77",
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
        prompt="prompt",
        topic="quantization",
        temperature=0.8,
        seed="seed-1",
        default_machine="192.168.1.77",
        default_model="gpt-5.5",
        default_sandbox="danger-full-access",
    )

    assert len(candidates) == 1
    row = candidates[0]
    assert row["provider"] == "synthetic.new"
    assert row["provider_model"] == "hf:zai-org/GLM-5.1"
    assert row["prompt_version"] == "research_provider_generate_v1"
    assert row["source_records"][0]["source_kind"] == "internal_generated"
    assert row["source_ids"]
    assert row["source_urls"][0].startswith("enoch://research-facility/provider/")
    assert row["raw_candidate_json"]["provider_response_id"] == "cmpl-provider-test"


def test_provider_generate_calls_openai_compatible_endpoint_without_local_auth_when_empty_key() -> None:
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(_provider_payload()).encode("utf-8")

    with patch("scripts.research_provider_generate.urllib.request.urlopen", return_value=FakeResponse()) as urlopen:
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
