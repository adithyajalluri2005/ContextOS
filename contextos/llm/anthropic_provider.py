"""Claude models through the official `anthropic` package (install: contextos[anthropic])."""

from __future__ import annotations

import os
from typing import Any

from contextos.llm.base import JSONSchema, Provider, ProviderError

KEY_ENV = "ANTHROPIC_API_KEY"
DEFAULT_MODEL = "claude-opus-5-5"
MAX_OUTPUT_TOKENS = 16_000
EFFORT = "medium"

# Models that accept the server-side fallback: if a safety check declines the
# request, the API answers it with a fallback model inside the same call.
FALLBACK_BETA = "server-side-fallback-2026-07-01"
FALLBACK_MODELS = frozenset({"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"})

# Models that accept the `effort` setting. Others use their own default.
EFFORT_MODELS = FALLBACK_MODELS | {
    "claude-fable-5", "claude-sonnet-5", "claude-haiku-5-5",
    "claude-opus-4-8", "claude-opus-4-7", "claude-opus-4-6", "claude-sonnet-4-6",
}


def _api_errors() -> tuple[type[BaseException], ...]:
    try:
        import anthropic
    except ImportError:
        return ()
    return (anthropic.APIError,)


class AnthropicProvider(Provider):
    name = "anthropic"
    max_input_chars = 400_000  # about 100k tokens; well inside the context window

    def __init__(self, model: str | None = None, *, client: Any = None) -> None:
        self.model = model or DEFAULT_MODEL
        if client is None:
            client = self._make_client()
        self._client = client

    @staticmethod
    def _make_client() -> Any:
        key = os.environ.get(KEY_ENV, "").strip()
        if not key:
            raise ProviderError(f"{KEY_ENV} is not set. Set it in your environment to use the Anthropic provider.")
        try:
            import anthropic
        except ImportError as exc:
            raise ProviderError(
                "The Anthropic provider needs the 'anthropic' package. "
                "Install it with: pip install \"contextos[anthropic]\""
            ) from exc
        return anthropic.Anthropic(api_key=key)

    def _request(self, system: str, prompt: str, schema: JSONSchema | None) -> dict[str, Any]:
        output_config: dict[str, Any] = {}
        if self.model in EFFORT_MODELS:
            output_config["effort"] = EFFORT
        if schema is not None:
            output_config["format"] = {"type": "json_schema", "schema": schema}
        request: dict[str, Any] = {
            "model": self.model,
            "max_tokens": MAX_OUTPUT_TOKENS,
            "system": system,
            "messages": [{"role": "user", "content": prompt}],
        }
        if output_config:
            request["output_config"] = output_config
        if self.model in FALLBACK_MODELS:
            request["betas"] = [FALLBACK_BETA]
            request["fallbacks"] = "default"
        return request

    def complete(self, system: str, prompt: str, *, schema: JSONSchema | None = None) -> str:
        try:
            response = self._client.beta.messages.create(**self._request(system, prompt, schema))
        except _api_errors() as exc:
            raise ProviderError(f"Anthropic request failed: {exc}") from exc

        if response.stop_reason == "refusal":
            raise ProviderError("Claude declined to summarize this conversation (safety check).")
        if response.stop_reason == "max_tokens":
            raise ProviderError("Claude's answer was cut off because it was too long.")
        text = "".join(block.text for block in response.content if block.type == "text")
        if not text.strip():
            raise ProviderError("Claude returned an empty answer.")
        return text
