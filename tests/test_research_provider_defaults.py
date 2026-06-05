"""Guards for centralized Research Facility provider defaults."""

from __future__ import annotations

from pathlib import Path

from enoch_control_plane.research_provider_defaults import (
    DEFAULT_ALLOWED_RESEARCH_MODELS,
    DEFAULT_RESEARCH_PROVIDER_BASE_URL,
    DEFAULT_RESEARCH_PROVIDER_MODEL,
    DEFAULT_RESEARCH_PROVIDER_MODEL_ROTATION,
    default_research_provider_openai_base_url,
)


RUNTIME_DEFAULT_FILES = [
    Path("enoch_control_plane/control_plane/router.py"),
    Path("deploy/enoch_research_autopilot.py"),
    Path("scripts/research_provider_generate.py"),
    Path("scripts/research_facility_llm_review.py"),
]

CENTRALIZED_DEFAULT_LITERALS = [
    "https://synthetic.int.exe.xyz",
    "https://synthetic.int.exe.xyz/openai/v1",
    "hf:zai-org/GLM-5.1",
]


def test_research_provider_defaults_are_centralized() -> None:
    assert DEFAULT_RESEARCH_PROVIDER_BASE_URL == "https://synthetic.int.exe.xyz"
    assert default_research_provider_openai_base_url() == (
        "https://synthetic.int.exe.xyz/openai/v1"
    )
    assert DEFAULT_RESEARCH_PROVIDER_MODEL == "hf:zai-org/GLM-5.1"
    assert DEFAULT_RESEARCH_PROVIDER_MODEL_ROTATION == ("hf:zai-org/GLM-5.1",)
    assert DEFAULT_ALLOWED_RESEARCH_MODELS == ("hf:zai-org/GLM-5.1",)


def test_research_provider_defaults_exclude_kimi_for_structured_output() -> None:
    forbidden = "moonshotai/kimi"

    assert all(
        forbidden not in model.lower()
        for model in DEFAULT_RESEARCH_PROVIDER_MODEL_ROTATION
    )
    assert all(
        forbidden not in model.lower() for model in DEFAULT_ALLOWED_RESEARCH_MODELS
    )


def test_runtime_files_do_not_duplicate_provider_default_literals() -> None:
    offenders: list[str] = []
    for path in RUNTIME_DEFAULT_FILES:
        text = path.read_text(encoding="utf-8")
        for literal in CENTRALIZED_DEFAULT_LITERALS:
            if literal in text:
                offenders.append(f"{path}:{literal}")

    assert offenders == []
