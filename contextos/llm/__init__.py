"""AI model providers behind one interface.

Choose one with the CONTEXTOS_PROVIDER environment variable, and optionally a
model with CONTEXTOS_MODEL. API keys are read only from environment variables
(ANTHROPIC_API_KEY, OPENAI_API_KEY); ContextOS never stores them.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping

from contextos.llm.base import JSONSchema, Provider, ProviderError
from contextos.llm.fake import FakeProvider

PROVIDER_ENV = "CONTEXTOS_PROVIDER"
MODEL_ENV = "CONTEXTOS_MODEL"


def _anthropic(model: str | None) -> Provider:
    from contextos.llm.anthropic_provider import AnthropicProvider

    return AnthropicProvider(model)


def _openai(model: str | None) -> Provider:
    from contextos.llm.openai_provider import OpenAIProvider

    return OpenAIProvider(model)


def _ollama(model: str | None) -> Provider:
    from contextos.llm.ollama_provider import OllamaProvider

    return OllamaProvider(model)


def _fake(model: str | None) -> Provider:
    return FakeProvider(model=model)


PROVIDERS: dict[str, Callable[[str | None], Provider]] = {
    "anthropic": _anthropic,
    "openai": _openai,
    "ollama": _ollama,
    "fake": _fake,
}


def get_provider(name: str | None = None, *, model: str | None = None, env: Mapping[str, str] | None = None) -> Provider:
    """Build the provider named by `name`, or by CONTEXTOS_PROVIDER if `name` is None."""
    env = os.environ if env is None else env
    choices = ", ".join(PROVIDERS)
    raw = name if name is not None else env.get(PROVIDER_ENV, "")
    key = raw.strip().lower()
    if not key:
        raise ProviderError(f"No AI provider chosen. Set {PROVIDER_ENV} to one of: {choices}.")
    if key not in PROVIDERS:
        raise ProviderError(f"Unknown AI provider '{raw.strip()}'. Choose one of: {choices}.")
    chosen_model = model if model is not None else (env.get(MODEL_ENV, "").strip() or None)
    return PROVIDERS[key](chosen_model)


__all__ = [
    "MODEL_ENV",
    "PROVIDERS",
    "PROVIDER_ENV",
    "FakeProvider",
    "JSONSchema",
    "Provider",
    "ProviderError",
    "get_provider",
]
