"""Local models through Ollama's HTTP API. Uses only the standard library."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

from contextos.llm.base import JSONSchema, Provider, ProviderError

HOST_ENV = "OLLAMA_HOST"
DEFAULT_HOST = "http://localhost:11434"
DEFAULT_MODEL = "llama3.1"
CONTEXT_TOKENS = 16_384
TIMEOUT_SECONDS = 600  # local models can be slow on long text

UrlOpen = Callable[..., Any]


def normalize_host(raw: str | None) -> str:
    """Accept the forms OLLAMA_HOST takes, e.g. "0.0.0.0:11434", "localhost", "http://box:11434/"."""
    host = (raw or "").strip() or DEFAULT_HOST
    if "://" not in host:
        host = "http://" + host
    scheme, rest = host.split("://", 1)
    rest = rest.rstrip("/")
    # 0.0.0.0 means "listen everywhere" for the server; a client must use a real address.
    if rest == "0.0.0.0" or rest.startswith("0.0.0.0:"):
        rest = "localhost" + rest[len("0.0.0.0"):]
    if ":" not in rest.split("/", 1)[0]:
        rest = rest + ":11434"
    return f"{scheme}://{rest}"


class OllamaProvider(Provider):
    name = "ollama"
    # Leave room for the prompt text and the answer inside CONTEXT_TOKENS (about 4 characters a token).
    max_input_chars = 32_000

    def __init__(self, model: str | None = None, *, host: str | None = None, urlopen: UrlOpen | None = None) -> None:
        self.model = model or DEFAULT_MODEL
        self.host = normalize_host(host if host is not None else os.environ.get(HOST_ENV))
        self._urlopen = urlopen or urllib.request.urlopen

    def _body(self, system: str, prompt: str, schema: JSONSchema | None) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.model,
            "stream": False,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "options": {"num_ctx": CONTEXT_TOKENS, "temperature": 0},
        }
        if schema is not None:
            body["format"] = schema
        return body

    def complete(self, system: str, prompt: str, *, schema: JSONSchema | None = None) -> str:
        url = f"{self.host}/api/chat"
        request = urllib.request.Request(
            url,
            data=json.dumps(self._body(system, prompt, schema)).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with self._urlopen(request, timeout=TIMEOUT_SECONDS) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = _error_detail(exc)
            if exc.code == 404:
                raise ProviderError(
                    f"Ollama does not have the model '{self.model}'. Run: ollama pull {self.model}"
                ) from exc
            raise ProviderError(f"Ollama returned an error ({exc.code}): {detail}") from exc
        except urllib.error.URLError as exc:
            raise ProviderError(f"Could not reach Ollama at {self.host}. Is it running? ({exc.reason})") from exc
        except (TimeoutError, json.JSONDecodeError) as exc:
            raise ProviderError(f"Ollama request failed: {exc}") from exc

        if data.get("done_reason") == "length":
            raise ProviderError("The model's answer was cut off because it was too long.")
        text = (data.get("message") or {}).get("content") or ""
        if not text.strip():
            raise ProviderError("Ollama returned an empty answer.")
        return text


def _error_detail(exc: urllib.error.HTTPError) -> str:
    try:
        return json.loads(exc.read().decode("utf-8")).get("error") or exc.reason
    except Exception:  # the body is only used for the message
        return str(exc.reason)
