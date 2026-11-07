"""The one interface every AI provider implements."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

JSONSchema = dict[str, Any]


class ProviderError(RuntimeError):
    """A provider could not be set up or could not give an answer.

    The message is written for the person running ContextOS: it says what went
    wrong and, where possible, what to do about it.
    """


class Provider(ABC):
    """Sends one prompt to a model and returns its text answer."""

    #: Short name used in CONTEXTOS_PROVIDER, e.g. "anthropic".
    name: str
    #: Model the provider sends requests to.
    model: str
    #: How much text (in characters) one request may carry. The pack builder
    #: splits longer chats into pieces of about this size.
    max_input_chars: int

    @abstractmethod
    def complete(self, system: str, prompt: str, *, schema: JSONSchema | None = None) -> str:
        """Return the model's answer to `prompt`.

        `schema` is a JSON Schema the answer must follow. Providers that can
        enforce a schema pass it on; the caller still checks the answer.
        """

    def __repr__(self) -> str:
        return f"{type(self).__name__}(model={self.model!r})"
