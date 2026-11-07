"""Shared steps used by both the command-line tool and the MCP server.

Keeping them here means both front ends build packs the same way, with the same
secret hiding.
"""

from __future__ import annotations

from collections import Counter

from contextos.llm import Provider
from contextos.pack import ContextPack
from contextos.pack.builder import Progress, build_pack
from contextos.redact import ordered, redact_model
from contextos.store import Conversation


def make_pack(
    conv: Conversation,
    provider: Provider,
    *,
    include_transcript: bool = False,
    redact: bool = True,
    progress: Progress | None = None,
) -> ContextPack:
    """Build a pack for `conv`.

    With `redact` (the default) the chat is cleaned before the model sees it, the
    finished pack is checked again, and only the counts are recorded in `redacted`.
    Raises ProviderError or PackBuildError when the pack cannot be built.
    """
    hidden: Counter[str] = Counter()
    if redact:
        conv = redact_model(conv, hidden)
    pack = build_pack(conv, provider, include_transcript=include_transcript, progress=progress)
    if redact:
        pack = redact_model(pack, hidden).model_copy(update={"redacted": ordered(hidden)})
    return pack


__all__ = ["make_pack"]
