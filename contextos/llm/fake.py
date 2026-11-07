"""A provider that never calls a real AI service. Used by tests and demos."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from contextos.llm.base import JSONSchema, Provider, ProviderError

Answer = str | dict
Responder = Callable[[str, str], Answer]


@dataclass(frozen=True)
class FakeCall:
    system: str
    prompt: str
    schema: JSONSchema | None


def default_answer(system: str, prompt: str) -> dict:
    """A small, valid pack draft that depends only on the prompt, so output is repeatable."""
    return {
        "title": "Conversation summary",
        "summary": f"Summary made by the fake provider from {len(prompt)} characters of input.",
        "decisions": [],
        "open_questions": [],
        "next_steps": [],
        "key_facts": [],
        "code_snippets": [],
        "file_refs": [],
    }


class FakeProvider(Provider):
    """Returns prepared answers and records every call.

    `responses` can be:
    - None: every call gets `default_answer`.
    - a list of answers (text or dict), used one per call in order.
    - a function (system, prompt) -> answer.
    """

    name = "fake"

    def __init__(
        self,
        responses: Iterable[Answer] | Responder | None = None,
        *,
        model: str | None = None,
        max_input_chars: int = 400_000,
    ) -> None:
        self.model = model or "fake"
        self.max_input_chars = max_input_chars
        self.calls: list[FakeCall] = []
        if responses is None:
            self._responder: Responder = default_answer
        elif callable(responses):
            self._responder = responses
        else:
            queue = list(responses)

            def next_answer(system: str, prompt: str) -> Answer:
                if not queue:
                    raise ProviderError(f"FakeProvider ran out of answers after {len(self.calls)} call(s).")
                return queue.pop(0)

            self._responder = next_answer

    def complete(self, system: str, prompt: str, *, schema: JSONSchema | None = None) -> str:
        self.calls.append(FakeCall(system, prompt, schema))
        answer = self._responder(system, prompt)
        return answer if isinstance(answer, str) else json.dumps(answer, ensure_ascii=False)
