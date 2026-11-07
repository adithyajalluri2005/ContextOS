"""OpenAI models through the official `openai` package (install: contextos[openai])."""

from __future__ import annotations

import os
from typing import Any

from contextos.llm.base import JSONSchema, Provider, ProviderError

KEY_ENV = "OPENAI_API_KEY"
DEFAULT_MODEL = "gpt-5"
MAX_OUTPUT_TOKENS = 16_000


def _api_errors() -> tuple[type[BaseException], ...]:
    try:
        import openai
    except ImportError:
        return ()
    return (openai.OpenAIError,)


class OpenAIProvider(Provider):
    name = "openai"
    max_input_chars = 200_000  # about 50k tokens

    def __init__(self, model: str | None = None, *, client: Any = None) -> None:
        self.model = model or DEFAULT_MODEL
        if client is None:
            client = self._make_client()
        self._client = client

    @staticmethod
    def _make_client() -> Any:
        key = os.environ.get(KEY_ENV, "").strip()
        if not key:
            raise ProviderError(f"{KEY_ENV} is not set. Set it in your environment to use the OpenAI provider.")
        try:
            import openai
        except ImportError as exc:
            raise ProviderError(
                "The OpenAI provider needs the 'openai' package. Install it with: pip install \"contextos[openai]\""
            ) from exc
        return openai.OpenAI(api_key=key)

    def _request(self, system: str, prompt: str, schema: JSONSchema | None) -> dict[str, Any]:
        request: dict[str, Any] = {
            "model": self.model,
            "max_completion_tokens": MAX_OUTPUT_TOKENS,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        }
        if schema is not None:
            request["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "context_pack_draft", "schema": schema, "strict": True},
            }
        return request

    def complete(self, system: str, prompt: str, *, schema: JSONSchema | None = None) -> str:
        try:
            response = self._client.chat.completions.create(**self._request(system, prompt, schema))
        except _api_errors() as exc:
            raise ProviderError(f"OpenAI request failed: {exc}") from exc

        if not response.choices:
            raise ProviderError("OpenAI returned no answer.")
        choice = response.choices[0]
        if getattr(choice.message, "refusal", None):
            raise ProviderError(f"The model declined to summarize this conversation: {choice.message.refusal}")
        if choice.finish_reason == "length":
            raise ProviderError("The model's answer was cut off because it was too long.")
        text = choice.message.content or ""
        if not text.strip():
            raise ProviderError("OpenAI returned an empty answer.")
        return text
