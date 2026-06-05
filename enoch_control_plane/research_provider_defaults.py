"""Shared defaults for Enoch Research Facility provider integrations."""

from __future__ import annotations

DEFAULT_RESEARCH_PROVIDER_BASE_URL = "https://synthetic.int.exe.xyz"
GLM_51_MODEL = "hf:zai-org/GLM-5.1"
DEFAULT_RESEARCH_PROVIDER_MODEL = GLM_51_MODEL
DEFAULT_RESEARCH_PROVIDER_MODEL_ROTATION = (
    GLM_51_MODEL,
)
DEFAULT_ALLOWED_RESEARCH_MODELS = (
    GLM_51_MODEL,
)


def default_research_provider_openai_base_url(
    base_url: str = DEFAULT_RESEARCH_PROVIDER_BASE_URL,
) -> str:
    """Return the default OpenAI-compatible URL for a research provider base."""

    return f"{base_url.rstrip('/')}/openai/v1"
