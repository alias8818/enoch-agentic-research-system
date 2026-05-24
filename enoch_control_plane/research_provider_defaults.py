"""Shared defaults for Enoch Research Facility provider integrations."""

from __future__ import annotations

DEFAULT_RESEARCH_PROVIDER_BASE_URL = "https://synthetic.int.exe.xyz"
DEFAULT_RESEARCH_PROVIDER_MODEL = "hf:zai-org/GLM-5.1"
DEFAULT_RESEARCH_PROVIDER_MODEL_ROTATION = (
    "hf:zai-org/GLM-5.1",
    "hf:moonshotai/Kimi-K2.6",
)
DEFAULT_ALLOWED_RESEARCH_MODELS = (
    "hf:moonshotai/Kimi-K2.6",
    "hf:zai-org/GLM-5.1",
)


def default_research_provider_openai_base_url(
    base_url: str = DEFAULT_RESEARCH_PROVIDER_BASE_URL,
) -> str:
    """Return the default OpenAI-compatible URL for a research provider base."""

    return f"{base_url.rstrip('/')}/openai/v1"
