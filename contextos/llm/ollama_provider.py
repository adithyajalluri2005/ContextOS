"""Models through Ollama's HTTP API: a local Ollama, or Ollama's cloud service.

Local (default): no key, requests go to http://localhost:11434 (or OLLAMA_HOST).
Cloud: set OLLAMA_API_KEY. Requests then go to https://ollama.com (unless OLLAMA_HOST
says otherwise) with the key as a Bearer token. The key is read only from the
environment, never stored, and never shown in messages.

Uses only the standard library.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

from contextos.llm.base import JSONSchema, Provider, ProviderError

HOST_ENV = "OLLAMA_HOST"
KEY_ENV = "OLLAMA_API_KEY"
DEFAULT_HOST = "http://localhost:11434"
CLOUD_HOST = "https://ollama.com"
DEFAULT_MODEL = "llama3.1"
# Default when the cloud service is used; local models like llama3.1 are not offered there.
DEFAULT_CLOUD_MODEL = "gpt-oss:120b"
LOCAL_NAMES = ("localhost", "127.0.0.1", "[::1]")
CONTEXT_TOKENS = 16_384
TIMEOUT_SECONDS = 600  # local models can be slow on long text

UrlOpen = Callable[..., Any]


def normalize_host(raw: str | None, default: str = DEFAULT_HOST) -> str:
    """Accept the forms OLLAMA_HOST takes, e.g. "0.0.0.0:11434", "localhost", "http://box:11434/".

    Plain http addresses without a port get Ollama's port 11434; https addresses keep
    the standard port, as the cloud service uses it.
    """
    host = (raw or "").strip() or default
    if "://" not in host:
        host = "http://" + host
    scheme, rest = host.split("://", 1)
    rest = rest.rstrip("/")
    # 0.0.0.0 means "listen everywhere" for the server; a client must use a real address.
    if rest == "0.0.0.0" or rest.startswith("0.0.0.0:"):
        rest = "localhost" + rest[len("0.0.0.0"):]
    if scheme == "http" and ":" not in rest.split("/", 1)[0]:
        rest = rest + ":11434"
    return f"{scheme}://{rest}"


class OllamaProvider(Provider):
    name = "ollama"
    # Leave room for the prompt text and the answer inside CONTEXT_TOKENS (about 4 characters a token).
    max_input_chars = 32_000

    def __init__(
        self,
        model: str | None = None,
        *,
        host: str | None = None,
        api_key: str | None = None,
        urlopen: UrlOpen | None = None,
    ) -> None:
        key = (api_key if api_key is not None else os.environ.get(KEY_ENV, "")).strip()
        self._api_key = key or None
        default_host = CLOUD_HOST if self._api_key else DEFAULT_HOST
        self.host = normalize_host(host if host is not None else os.environ.get(HOST_ENV), default_host)
        self.model = model or (DEFAULT_CLOUD_MODEL if self.cloud else DEFAULT_MODEL)
        if self._api_key and self.host.startswith("http://") and not _is_local(self.host):
            raise ProviderError(
                f"Not sending {KEY_ENV} over plain http to {self.host}. Use an https address in {HOST_ENV}."
            )
        self._urlopen = urlopen or urllib.request.urlopen

    @property
    def cloud(self) -> bool:
        """True when requests go to Ollama's cloud service."""
        return self.host == CLOUD_HOST

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
            headers=self._headers(),
            method="POST",
        )
        try:
            with self._urlopen(request, timeout=TIMEOUT_SECONDS) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = _error_detail(exc)
            if exc.code in (401, 403) and self._api_key:
                raise ProviderError(f"Ollama rejected the API key ({exc.code}). Check {KEY_ENV}.") from exc
            if exc.code in (401, 403):
                raise ProviderError(f"Ollama at {self.host} needs an API key. Set {KEY_ENV}.") from exc
            if exc.code == 404 and self.cloud:
                raise ProviderError(
                    f"Ollama's cloud service does not offer the model '{self.model}'. "
                    "Pick one from https://ollama.com/search?c=cloud and set CONTEXTOS_MODEL."
                ) from exc
            if exc.code == 404:
                raise ProviderError(
                    f"Ollama does not have the model '{self.model}'. Run: ollama pull {self.model}"
                ) from exc
            raise ProviderError(f"Ollama returned an error ({exc.code}): {detail}") from exc
        except urllib.error.URLError as exc:
            if self.cloud:
                raise ProviderError(
                    f"Could not reach Ollama's cloud service at {self.host}. Check your internet connection. ({exc.reason})"
                ) from exc
            raise ProviderError(f"Could not reach Ollama at {self.host}. Is it running? ({exc.reason})") from exc
        except (TimeoutError, json.JSONDecodeError) as exc:
            raise ProviderError(f"Ollama request failed: {exc}") from exc

        if data.get("done_reason") == "length":
            raise ProviderError("The model's answer was cut off because it was too long.")
        text = (data.get("message") or {}).get("content") or ""
        if not text.strip():
            raise ProviderError("Ollama returned an empty answer.")
        return text


    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    def __repr__(self) -> str:  # never show the key
        return f"OllamaProvider(model={self.model!r}, host={self.host!r}, key={'set' if self._api_key else 'none'})"


def _is_local(host: str) -> bool:
    name = host.split("://", 1)[1].split("/", 1)[0]
    name = name.rsplit(":", 1)[0] if not name.endswith("]") else name
    return name in LOCAL_NAMES


def _error_detail(exc: urllib.error.HTTPError) -> str:
    try:
        return json.loads(exc.read().decode("utf-8")).get("error") or exc.reason
    except Exception:  # the body is only used for the message
        return str(exc.reason)
